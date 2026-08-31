import Foundation

/// Schaffe ich morgens mehr als abends?
///
/// Wird nur beantwortet, wenn die Trainingszeit überhaupt variiert. Wer immer um
/// 18 Uhr trainiert, kann diese Frage nie beantworten -- dann sagt die App das
/// offen und schlägt eine Variation vor, statt eine Scheinantwort zu bauen.
public struct TimeOfDayDetector: Detector {
    public let id = "time-of-day"
    public let question = "Hängt meine Leistung an der Trainingszeit?"
    public let minimumSampleSize: Int
    public let repThreshold: Double

    public init(minimumSampleSize: Int = 4, repThreshold: Double = 1.0) {
        self.minimumSampleSize = minimumSampleSize
        self.repThreshold = repThreshold
    }

    public func run(_ input: AnalysisInput) -> DetectorResult {
        let sessions = input.sessions(planVersionID: input.planVersion.id)
        let buckets = Dictionary(grouping: sessions) {
            TimeOfDayBucket(date: $0.startedAt, calendar: input.calendar)
        }

        let populated = buckets.filter { $0.value.count >= minimumSampleSize }
        guard populated.count >= 2 else {
            return .silent(.notAnsweredWithoutVariation(dimension: .timeOfDay))
        }

        // Gleiche Übung, gleicher Satzindex, gleiche Last -- gepaart vergleichen.
        var bestFinding: Finding?
        var bestEffect = 0.0

        let exerciseIDs = Set(sessions.flatMap(\.workSets).map(\.exerciseID))
        for exerciseID in exerciseIDs {
            var repsByBucket: [TimeOfDayBucket: [Double]] = [:]
            for (bucket, bucketSessions) in populated {
                for session in bucketSessions {
                    guard let summary = Metrics.summarize(exerciseID: exerciseID, in: session),
                          let meanReps = Metrics.mean(summary.workSets.map { Double($0.reps) })
                    else { continue }
                    repsByBucket[bucket, default: []].append(meanReps)
                }
            }

            let usable = repsByBucket.filter { $0.value.count >= minimumSampleSize }
            guard usable.count >= 2 else { continue }

            let averages = usable.compactMapValues(Metrics.mean)
            guard let best = averages.max(by: { $0.value < $1.value }),
                  let worst = averages.min(by: { $0.value < $1.value }) else { continue }

            let effect = best.value - worst.value
            guard effect > bestEffect,
                  EffectGate.passes(
                      effect: effect,
                      minimum: repThreshold,
                      groupA: usable[best.key] ?? [],
                      groupB: usable[worst.key] ?? []
                  ) else { continue }

            let name = input.planVersion.exercise(id: exerciseID)?.name ?? exerciseID
            bestEffect = effect
            bestFinding = Finding(
                id: "\(id)-\(exerciseID)",
                detectorID: id,
                severity: .observation,
                observation: "Bei \(name) schaffst du \(best.key.displayName) im Schnitt \(String(format: "%.1f", effect)) Wiederholungen mehr als \(worst.key.displayName).",
                likelyCause: "Die Trainingszeit beeinflusst deine Leistung bei dieser Übung.",
                evidence: [
                    Evidence(
                        label: "Wiederholungen \(best.key.displayName)",
                        value: String(format: "%.1f", best.value),
                        sampleSize: usable[best.key]?.count ?? 0
                    ),
                    Evidence(
                        label: "Wiederholungen \(worst.key.displayName)",
                        value: String(format: "%.1f", worst.value),
                        sampleSize: usable[worst.key]?.count ?? 0
                    )
                ],
                exerciseIDs: [exerciseID],
                limitations: ["Tageszeit hängt oft mit Schlaf und Essen zusammen -- beides ist hier nicht getrennt."]
            )
        }

        guard let bestFinding else {
            return .silent(.effectTooSmall(observed: bestEffect, threshold: repThreshold))
        }
        return .finding(bestFinding)
    }
}

/// Leidet die Leistung, wenn die Session lang und zäh wird?
public struct SessionDensityDetector: Detector {
    public let id = "session-density"
    public let question = "Kosten lange Sessions mit viel Totzeit die späten Übungen?"
    public let minimumSampleSize: Int
    public let repThreshold: Double

    public init(minimumSampleSize: Int = 4, repThreshold: Double = 1.0) {
        self.minimumSampleSize = minimumSampleSize
        self.repThreshold = repThreshold
    }

    public func run(_ input: AnalysisInput) -> DetectorResult {
        let sessions = input.sessions(planVersionID: input.planVersion.id)
            .filter { $0.duration != nil }

        guard sessions.count >= minimumSampleSize * 2 else {
            return .silent(.notEnoughData(have: sessions.count, need: minimumSampleSize * 2))
        }

        // Letzte Übung jeder Session gegen die Sessiondauer.
        var points: [(duration: TimeInterval, reps: Double, exerciseID: String)] = []
        for session in sessions {
            guard let last = session.exercises
                .filter({ $0.effectiveExerciseID != nil })
                .max(by: { $0.positionInSession < $1.positionInSession }),
                let exerciseID = last.effectiveExerciseID,
                let summary = Metrics.summarize(exerciseID: exerciseID, in: session),
                let meanReps = Metrics.mean(summary.workSets.map { Double($0.reps) }),
                let duration = session.duration
            else { continue }
            points.append((duration, meanReps, exerciseID))
        }

        guard points.count >= minimumSampleSize * 2 else {
            return .silent(.notEnoughData(have: points.count, need: minimumSampleSize * 2))
        }

        let sorted = points.sorted { $0.duration < $1.duration }
        let half = sorted.count / 2
        let shortSessions = sorted.prefix(half).map(\.reps)
        let longSessions = sorted.suffix(sorted.count - half).map(\.reps)

        guard let shortMean = Metrics.mean(shortSessions),
              let longMean = Metrics.mean(longSessions) else {
            return .silent(.notEnoughData(have: points.count, need: minimumSampleSize * 2))
        }

        let effect = shortMean - longMean
        let required = EffectGate.required(
            minimum: repThreshold,
            groupA: shortSessions,
            groupB: longSessions
        )
        guard effect >= required else {
            return .silent(.effectTooSmall(observed: effect, threshold: required))
        }

        let affected = Array(Set(sorted.map(\.exerciseID))).sorted()
        let shortAverage = Metrics.mean(sorted.prefix(half).map(\.duration)) ?? 0
        let longAverage = Metrics.mean(sorted.suffix(sorted.count - half).map(\.duration)) ?? 0

        return .finding(
            Finding(
                id: id,
                detectorID: id,
                severity: .issue,
                observation: "In langen Sessions läuft die letzte Übung schlechter als in kurzen.",
                likelyCause: "Der Tank ist am Ende leer -- nicht die letzte Übung stagniert, die Session ist zu lang.",
                evidence: [
                    Evidence(
                        label: "Kurze Sessions (Ø \(Int(shortAverage / 60)) min)",
                        value: String(format: "%.1f Wdh.", shortMean),
                        sampleSize: shortSessions.count
                    ),
                    Evidence(
                        label: "Lange Sessions (Ø \(Int(longAverage / 60)) min)",
                        value: String(format: "%.1f Wdh.", longMean),
                        sampleSize: longSessions.count
                    )
                ],
                exerciseIDs: affected,
                limitations: ["Lange Sessions können auch aus Störungen entstehen, nicht aus Trödeln."]
            )
        )
    }
}

/// Hängt die Leistung am Whoop-Recovery des Tages?
///
/// Rechnet ausschließlich mit vollständigem Tageskontext: Recovery entsteht erst
/// nach dem Aufwachen, der Tages-Strain erst nach Tagesende.
public struct RecoveryPerformanceDetector: Detector {
    public let id = "recovery-performance"
    public let question = "Hängt meine Leistung am Recovery-Score des Tages?"
    public let minimumSampleSize: Int
    public let repThreshold: Double

    public init(minimumSampleSize: Int = 6, repThreshold: Double = 1.0) {
        self.minimumSampleSize = minimumSampleSize
        self.repThreshold = repThreshold
    }

    public func run(_ input: AnalysisInput) -> DetectorResult {
        let sessions = input.sessions(planVersionID: input.planVersion.id)

        // Nur der erste Arbeitssatz jeder Hauptübung: filtert die Ermüdung
        // innerhalb der Session heraus und ist damit der sauberste Frische-Wert.
        var points: [(recovery: Double, firstSetReps: Double)] = []

        for session in sessions {
            guard let context = WhoopContextMapper.context(for: session, in: input.dailyContexts),
                  context.isUsableForAnalysis,
                  let recovery = context.recoveryScore else { continue }

            let firstSets = Dictionary(grouping: session.workSets) { $0.exerciseID }
                .compactMap { $0.value.min(by: { $0.setIndex < $1.setIndex }) }
            guard let meanReps = Metrics.mean(firstSets.map { Double($0.reps) }) else { continue }
            points.append((recovery, meanReps))
        }

        guard points.count >= minimumSampleSize else {
            return .silent(.notEnoughData(have: points.count, need: minimumSampleSize))
        }

        let low = points.filter { $0.recovery < 50 }.map(\.firstSetReps)
        let high = points.filter { $0.recovery >= 50 }.map(\.firstSetReps)
        guard !low.isEmpty, !high.isEmpty else {
            return .silent(.notAnsweredWithoutVariation(dimension: .timeOfDay))
        }
        guard let lowMean = Metrics.mean(low), let highMean = Metrics.mean(high) else {
            return .silent(.notEnoughData(have: points.count, need: minimumSampleSize))
        }

        let effect = highMean - lowMean
        let required = EffectGate.required(minimum: repThreshold, groupA: low, groupB: high)
        guard effect >= required else {
            return .silent(.effectTooSmall(observed: effect, threshold: required))
        }

        return .finding(
            Finding(
                id: id,
                detectorID: id,
                severity: .observation,
                observation: "An Tagen mit niedrigem Recovery starten deine Hauptübungen schwächer.",
                likelyCause: "Tagesform, nicht Planfehler. Schwache Tage sind erklärbar und kein Grund, den Plan zu ändern.",
                ruledOut: ["Ermüdung im Verlauf der Session -- gewertet wurde nur der erste Arbeitssatz"],
                evidence: [
                    Evidence(
                        label: "Erster Satz bei Recovery unter 50",
                        value: String(format: "%.1f Wdh.", lowMean),
                        sampleSize: low.count
                    ),
                    Evidence(
                        label: "Erster Satz bei Recovery ab 50",
                        value: String(format: "%.1f Wdh.", highMean),
                        sampleSize: high.count
                    )
                ],
                limitations: ["Recovery hängt selbst an Schlaf und Belastung -- die Kette ist länger als dieser Befund."]
            )
        )
    }
}

/// Schweigeregel für Aufbau-Aussagen.
///
/// Wenn die Arme nicht wachsen, weil zu wenig gegessen wird, kann der
/// Detektor-Katalog das nicht sehen -- er würde die beste *verfügbare*
/// Trainingsursache nennen und selbstsicher daneben liegen. Deshalb wird bei
/// flachem oder fallendem Körpergewicht kein Trainingsfehler behauptet.
public struct GrowthClaimGuard {
    public let minimumSampleSize: Int
    /// Ab welcher Zunahme in Kilogramm Aufbau plausibel ist.
    public let gainThreshold: Double

    public init(minimumSampleSize: Int = 4, gainThreshold: Double = 0.5) {
        self.minimumSampleSize = minimumSampleSize
        self.gainThreshold = gainThreshold
    }

    public enum Verdict: Equatable, Sendable {
        /// Aufbau ist unter diesen Bedingungen plausibel.
        case growthPlausible
        /// Körpergewicht flach oder fallend -- keine Trainingsursache behaupten.
        case blocked(SilenceReason)
        /// Zu wenig Gewichtsdaten, um überhaupt etwas zu sagen.
        case unknown(SilenceReason)
    }

    public func evaluate(bodyweight: [BodyweightRecord], over days: Int = 42) -> Verdict {
        let sorted = bodyweight.sorted { $0.date < $1.date }
        guard sorted.count >= minimumSampleSize, let last = sorted.last else {
            return .unknown(.notEnoughData(have: sorted.count, need: minimumSampleSize))
        }

        let cutoff = last.date.addingTimeInterval(-Double(days) * 86_400)
        let window = sorted.filter { $0.date >= cutoff }
        guard let first = window.first, window.count >= 2 else {
            return .unknown(.notEnoughData(have: window.count, need: 2))
        }

        let change = last.kilograms - first.kilograms
        if change < gainThreshold {
            return .blocked(.bodyweightFlatOrFalling)
        }
        return .growthPlausible
    }

    /// Text, der statt einer Trainingsursache erscheint.
    public func explanation(for verdict: Verdict) -> String? {
        switch verdict {
        case .growthPlausible:
            return nil
        case .blocked:
            return "Dein Körpergewicht ist seit Wochen unverändert oder fällt. Aufbau ist unter diesen Bedingungen unwahrscheinlich -- unabhängig vom Training."
        case .unknown:
            return "Ohne regelmäßige Gewichtsmessung lässt sich nicht trennen, ob es am Training oder am Essen liegt."
        }
    }
}
