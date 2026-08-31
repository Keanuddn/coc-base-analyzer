import Foundation

public enum LoadDirection: String, Equatable, Sendable, Codable {
    case increase
    case hold
    case decrease

    public var displayName: String {
        switch self {
        case .increase: return "steigern"
        case .hold: return "halten"
        case .decrease: return "reduzieren"
        }
    }
}

/// Empfehlung für die Last einer Übung.
///
/// Es gibt **immer** eine Empfehlung, sobald eine Übung startet -- nie ein
/// leeres Feld. Ohne Historie ist es die Startlast, sonst steigern, halten oder
/// reduzieren. Einen "Übernehmen"-Knopf gibt es nicht: das nach dem Satz
/// eingetragene Gewicht ist die Entscheidung.
public struct LoadRecommendation: Equatable, Sendable {
    public let exerciseID: String
    public let direction: LoadDirection
    /// Vorgeschlagene Last, auf eine erreichbare Stufe gerundet.
    public let weight: Double
    /// Kurzer Grund, der auf dem Satz-Screen steht.
    public let reason: String
    /// Bei Übungen mit Ziel "max" wird in Wiederholungen gedacht, nicht in Kilo.
    public let repsGoal: Int?
    /// Vor dem Satz angezeigter Hinweis, bei welcher Wiederholung gestoppt wird.
    public let stopAtReps: Int?

    public var displayText: String {
        if let repsGoal {
            return "Empfehlung \(repsGoal) Wdh."
        }
        return "Empfehlung \(LoadRecommendation.format(weight)) kg"
    }

    static func format(_ value: Double) -> String {
        value == value.rounded()
            ? String(Int(value))
            : String(format: "%.1f", value).replacingOccurrences(of: ".", with: ",")
    }
}

/// Leitet die Last-Empfehlung aus der letzten ausgeführten Arbeits-Serie ab.
///
/// Die Regel ist bewusst streng, damit 10 / 11 / 7 nicht als Freifahrtschein
/// nach oben gelesen wird:
///
/// - **Steigern** nur wenn *jeder* Arbeitssatz die obere Wdh.-Grenze erreicht
/// - **Reduzieren** nur wenn *mindestens ein* Satz unter die untere Grenze fällt
/// - **Halten** in jedem anderen Fall, auch bei gemischten Sätzen
///
/// Der schwächste Arbeitssatz ist die Bremse, nicht der stärkste: bei Mittelwert
/// oder Mehrheit würden 10 und 11 für "hoch" stimmen, man lädt auf und der
/// dritte Satz bricht wieder ein.
public struct LoadRecommender {
    public init() {}

    /// - Parameters:
    ///   - exercise: Übung, für die empfohlen wird.
    ///   - target: Wiederholungsvorgabe der **Arbeitssätze** -- auch dann, wenn
    ///     die Anzeige gerade ein Warm-up ist. Die Warm-up-Spanne darf die
    ///     Steigerungsregel nicht verdrehen.
    ///   - history: Sessions, neueste zuerst oder beliebig -- wird sortiert.
    ///   - todaySets: Bereits in dieser Session geloggte Sätze dieser Übung.
    ///   - fallbackWeight: Startlast, wenn es noch keine Historie gibt.
    ///   - warmupLoadFraction: Wenn gesetzt, ist das Ergebnis die gerundete
    ///     Warm-up-Last als Anteil der Arbeits-Empfehlung. `0` heißt ohne Last.
    public func recommend(
        exercise: Exercise,
        target: RepTarget,
        history: [SessionRecord],
        todaySets: [SetRecord] = [],
        fallbackWeight: Double? = nil,
        warmupLoadFraction: Double? = nil
    ) -> LoadRecommendation {
        let work = workRecommendation(
            exercise: exercise,
            target: target,
            history: history,
            todaySets: todaySets,
            fallbackWeight: fallbackWeight
        )
        return applyWarmupFraction(work, fraction: warmupLoadFraction, step: exercise.weightStep)
    }

    private func applyWarmupFraction(
        _ work: LoadRecommendation,
        fraction: Double?,
        step: WeightStep
    ) -> LoadRecommendation {
        guard let fraction else { return work }

        if fraction == 0 || work.weight == 0 {
            return LoadRecommendation(
                exerciseID: work.exerciseID,
                direction: .hold,
                weight: 0,
                reason: "Warm-up ohne Last",
                repsGoal: nil,
                stopAtReps: work.stopAtReps
            )
        }

        let percent = Int((fraction * 100).rounded())
        let workKg = LoadRecommendation.format(work.weight)
        return LoadRecommendation(
            exerciseID: work.exerciseID,
            direction: .hold,
            weight: step.snap(work.weight * fraction),
            reason: "\(percent) % der Arbeitslast (\(workKg) kg)",
            repsGoal: nil,
            stopAtReps: work.stopAtReps
        )
    }

    private func workRecommendation(
        exercise: Exercise,
        target: RepTarget,
        history: [SessionRecord],
        todaySets: [SetRecord],
        fallbackWeight: Double?
    ) -> LoadRecommendation {
        let stopAt = target.stopAtUpperBound

        // Ab dem zweiten Satz derselben Übung heute gilt die heutige
        // Arbeitslast, nicht nochmal die Steigerung von letzter Woche.
        if let todayReference = todaySets.first(where: { $0.countsForPerformance }) {
            return LoadRecommendation(
                exerciseID: exercise.id,
                direction: .hold,
                weight: todayReference.weight,
                reason: "heutige Arbeitslast",
                repsGoal: nil,
                stopAtReps: stopAt
            )
        }

        guard let series = lastWorkSeries(exerciseID: exercise.id, history: history) else {
            let start = fallbackWeight ?? 0
            return LoadRecommendation(
                exerciseID: exercise.id,
                direction: .hold,
                weight: exercise.weightStep.snap(start),
                reason: "erste Session mit dieser Übung",
                repsGoal: nil,
                stopAtReps: stopAt
            )
        }

        if exercise.progressesByRepsOnly {
            return bodyweightRecommendation(
                exercise: exercise,
                target: target,
                series: series,
                stopAt: stopAt
            )
        }

        let reference = series.referenceWeight
        let step = exercise.weightStep

        if series.allReachedUpperBound {
            return LoadRecommendation(
                exerciseID: exercise.id,
                direction: .increase,
                weight: step.increment(from: reference),
                reason: "letztes Mal alle Sätze am oberen Rand",
                repsGoal: nil,
                stopAtReps: stopAt
            )
        }

        if series.anyBelowLowerBound {
            return LoadRecommendation(
                exerciseID: exercise.id,
                direction: .decrease,
                weight: step.decrement(from: reference),
                reason: "letztes Mal ein Satz unter der unteren Grenze",
                repsGoal: nil,
                stopAtReps: stopAt
            )
        }

        return LoadRecommendation(
            exerciseID: exercise.id,
            direction: .hold,
            weight: step.snap(reference),
            reason: series.holdReason,
            repsGoal: nil,
            stopAtReps: stopAt
        )
    }

    // MARK: - Eigengewicht

    /// Bei Pull-ups und Dips ohne Zusatzlast ist Fortschritt nur über
    /// Wiederholungen messbar. Zusatzlast wird erst vorgeschlagen, wenn alle
    /// Sätze klar über einer Marke liegen -- nicht Kilo an der Stange.
    private func bodyweightRecommendation(
        exercise: Exercise,
        target: RepTarget,
        series: WorkSeries,
        stopAt: Int?
    ) -> LoadRecommendation {
        let hasAddedLoad = series.referenceWeight > 0

        if case .maximum = target {
            let minReps = series.sets.map(\.reps).min() ?? 0
            if hasAddedLoad {
                return LoadRecommendation(
                    exerciseID: exercise.id,
                    direction: .hold,
                    weight: exercise.weightStep.snap(series.referenceWeight),
                    reason: "max. Wdh., Zusatzlast halten",
                    repsGoal: nil,
                    stopAtReps: nil
                )
            }
            return LoadRecommendation(
                exerciseID: exercise.id,
                direction: minReps > 0 ? .increase : .hold,
                weight: 0,
                reason: "letztes Mal mindestens \(minReps) Wdh. pro Satz",
                repsGoal: max(minReps + 1, 1),
                stopAtReps: nil
            )
        }

        if series.allReachedUpperBound {
            if hasAddedLoad {
                return LoadRecommendation(
                    exerciseID: exercise.id,
                    direction: .increase,
                    weight: exercise.weightStep.increment(from: series.referenceWeight),
                    reason: "letztes Mal alle Sätze am oberen Rand",
                    repsGoal: nil,
                    stopAtReps: stopAt
                )
            }
            return LoadRecommendation(
                exerciseID: exercise.id,
                direction: .increase,
                weight: exercise.weightStep.kilograms,
                reason: "obere Grenze erreicht -- Zusatzlast versuchen",
                repsGoal: nil,
                stopAtReps: stopAt
            )
        }

        return LoadRecommendation(
            exerciseID: exercise.id,
            direction: series.anyBelowLowerBound ? .decrease : .hold,
            weight: series.anyBelowLowerBound
                ? exercise.weightStep.decrement(from: series.referenceWeight)
                : exercise.weightStep.snap(series.referenceWeight),
            reason: series.anyBelowLowerBound
                ? "letztes Mal ein Satz unter der unteren Grenze"
                : series.holdReason,
            repsGoal: nil,
            stopAtReps: stopAt
        )
    }

    // MARK: - Letzte Arbeits-Serie

    struct WorkSeries {
        let sets: [SetRecord]
        let referenceWeight: Double

        var allReachedUpperBound: Bool {
            !sets.isEmpty && sets.allSatisfy(\.reachedUpperBound)
        }

        var anyBelowLowerBound: Bool {
            sets.contains(where: \.belowLowerBound)
        }

        var holdReason: String {
            if sets.contains(where: { !$0.reachedUpperBound }) {
                return "letztes Mal nicht alle Sätze am oberen Rand"
            }
            return "letztes Mal gehalten"
        }
    }

    /// Letzte Session, in der diese Übung tatsächlich als Arbeitssatz gemacht
    /// wurde. Übersprungene und vermasselte Sätze zählen nicht, Warm-ups auch
    /// nicht. Verglichen werden nur Sätze mit dem Gewicht des **ersten**
    /// Arbeitssatzes, damit eine Gewichtsänderung mitten in der Übung die
    /// Entscheidung nicht verfälscht.
    func lastWorkSeries(exerciseID: String, history: [SessionRecord]) -> WorkSeries? {
        let sorted = history
            .filter { $0.status == .completed || $0.status == .open }
            .sorted { $0.startedAt > $1.startedAt }

        for session in sorted {
            let candidates = session.sets.filter {
                $0.exerciseID == exerciseID && $0.countsForPerformance
            }
            guard let first = candidates.first else { continue }
            let sameWeight = candidates.filter { $0.weight == first.weight }
            return WorkSeries(sets: sameWeight, referenceWeight: first.weight)
        }
        return nil
    }
}
