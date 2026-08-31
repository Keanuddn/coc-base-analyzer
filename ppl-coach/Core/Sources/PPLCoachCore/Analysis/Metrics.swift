import Foundation

/// Reine Rechnung ohne Urteil. Die Detektoren bauen ausschließlich hierauf auf,
/// damit sie billig, testbar und ohne Statistik im Kopf lesbar sind.
public enum Metrics {
    // MARK: - Streuung und Lage

    public static func mean(_ values: [Double]) -> Double? {
        guard !values.isEmpty else { return nil }
        return values.reduce(0, +) / Double(values.count)
    }

    /// Standardabweichung der Stichprobe (n-1). Grundlage für die Schwelle
    /// einer Probe: das Kriterium muss über der eigenen Streuung liegen.
    public static func standardDeviation(_ values: [Double]) -> Double? {
        guard values.count > 1, let average = mean(values) else { return nil }
        let sumOfSquares = values.reduce(0) { $0 + ($1 - average) * ($1 - average) }
        return (sumOfSquares / Double(values.count - 1)).squareRoot()
    }

    public static func median(_ values: [Double]) -> Double? {
        guard !values.isEmpty else { return nil }
        let sorted = values.sorted()
        let middle = sorted.count / 2
        if sorted.count.isMultiple(of: 2) {
            return (sorted[middle - 1] + sorted[middle]) / 2
        }
        return sorted[middle]
    }

    // MARK: - Satz

    public static func volume(_ set: SetRecord) -> Double {
        set.volume
    }

    /// Sekunden pro Wiederholung. Der Ermüdungs-Proxy, der Whoops fehlende
    /// Angabe zur Nähe am Muskelversagen ersetzt: bei gleicher Last werden die
    /// letzten Wiederholungen langsamer.
    public static func secondsPerRep(_ set: SetRecord) -> Double? {
        set.secondsPerRep
    }

    public static func pauseDeviation(_ set: SetRecord) -> TimeInterval? {
        set.pauseDeviation
    }

    // MARK: - Übung innerhalb einer Session

    public struct ExerciseSummary: Equatable, Sendable {
        public let exerciseID: String
        public let positionInSession: Int
        public let workSets: [SetRecord]
        public let volume: Double
        public let averageSecondsPerRep: Double?
        public let averagePauseDeviation: TimeInterval?
        /// Abfall vom ersten zum letzten Arbeitssatz in Wiederholungen.
        /// Positiv heißt: der letzte Satz war schwächer.
        public let repDropOff: Int?
        /// Anstieg der Zeit pro Wiederholung vom ersten zum letzten Satz.
        public let tempoDropOff: Double?

        public var reachedAllUpperBounds: Bool {
            !workSets.isEmpty && workSets.allSatisfy(\.reachedUpperBound)
        }
    }

    public static func summarize(
        exerciseID: String,
        in session: SessionRecord
    ) -> ExerciseSummary? {
        let sets = session.sets.filter {
            $0.exerciseID == exerciseID && $0.countsForPerformance
        }
        guard !sets.isEmpty else { return nil }

        let position = session.exercises
            .first { $0.effectiveExerciseID == exerciseID }?
            .positionInSession ?? 0

        let tempos = sets.compactMap(\.secondsPerRep)
        let deviations = sets.compactMap(\.pauseDeviation)

        var repDrop: Int?
        if let first = sets.first, let last = sets.last, sets.count > 1 {
            repDrop = first.reps - last.reps
        }

        var tempoDrop: Double?
        if let firstTempo = sets.first?.secondsPerRep,
           let lastTempo = sets.last?.secondsPerRep,
           sets.count > 1 {
            tempoDrop = lastTempo - firstTempo
        }

        return ExerciseSummary(
            exerciseID: exerciseID,
            positionInSession: position,
            workSets: sets,
            volume: sets.reduce(0) { $0 + $1.volume },
            averageSecondsPerRep: mean(tempos),
            averagePauseDeviation: mean(deviations),
            repDropOff: repDrop,
            tempoDropOff: tempoDrop
        )
    }

    // MARK: - Session

    public struct SessionSummary: Equatable, Sendable {
        public let sessionID: UUID
        public let day: TrainingDay
        public let startedAt: Date
        public let duration: TimeInterval?
        public let workSetCount: Int
        public let totalVolume: Double
        public let averagePauseDeviation: TimeInterval?
        /// Streuung der tatsächlichen Pausen -- hohe Streuung heißt unruhiger
        /// Ablauf und damit unberechenbare Folgesätze.
        public let pauseSpread: Double?
        /// Volumen pro Minute. Lange Sessions mit viel Totzeit kosten oft die
        /// späten Übungen.
        public let density: Double?
        public let timeOfDay: TimeOfDayBucket

        public var isUsableForTrends: Bool {
            workSetCount > 0
        }
    }

    public static func summarize(
        session: SessionRecord,
        calendar: Calendar = .current
    ) -> SessionSummary {
        let workSets = session.workSets
        let deviations = workSets.compactMap(\.pauseDeviation)
        let pauses = workSets.compactMap(\.actualPause)

        var density: Double?
        if let duration = session.duration, duration > 0 {
            density = session.totalVolume / (duration / 60)
        }

        return SessionSummary(
            sessionID: session.id,
            day: session.day,
            startedAt: session.startedAt,
            duration: session.duration,
            workSetCount: workSets.count,
            totalVolume: session.totalVolume,
            averagePauseDeviation: mean(deviations),
            pauseSpread: standardDeviation(pauses),
            density: density,
            timeOfDay: TimeOfDayBucket(date: session.startedAt, calendar: calendar)
        )
    }
}

/// Grobe Tageszeit. Feiner aufzulösen wäre bei einer Session pro Tag sinnlos.
public enum TimeOfDayBucket: String, Equatable, Sendable, Codable, CaseIterable {
    case morning
    case afternoon
    case evening

    public init(date: Date, calendar: Calendar = .current) {
        let hour = calendar.component(.hour, from: date)
        switch hour {
        case ..<12: self = .morning
        case 12..<17: self = .afternoon
        default: self = .evening
        }
    }

    public var displayName: String {
        switch self {
        case .morning: return "morgens"
        case .afternoon: return "nachmittags"
        case .evening: return "abends"
        }
    }
}

/// Ein Paar aus Pause und dem darauf folgenden Satz derselben Übung.
///
/// Gepaart und geschichtet statt roh korreliert: verglichen werden nur Sätze
/// **derselben Übung, desselben Satzindex und derselben Last**. Ohne die
/// Schichtung nach Satzindex findet man Ermüdung und nennt sie Pause.
public struct PauseEffectPair: Equatable, Sendable {
    public let exerciseID: String
    public let setIndex: Int
    public let weight: Double
    public let pause: TimeInterval
    public let pauseTarget: TimeInterval
    public let nextReps: Int
    public let nextSecondsPerRep: Double?
    public let pauseDisturbance: DisturbanceCategory?
    public let sessionID: UUID

    public var pauseDeviation: TimeInterval { pause - pauseTarget }

    /// Nur von außen verursachte Störungen taugen als saubere Dosis: eine
    /// selbst gewählte lange Pause kann Folge von Erschöpfung sein, was die
    /// Wirkungsrichtung umdreht.
    public var isExogenous: Bool {
        pauseDisturbance == .external
    }

    /// Aussagen über das eigene Verhalten dürfen markierte Pausen nicht nutzen.
    public var reflectsOwnBehaviour: Bool {
        pauseDisturbance == nil
    }
}

public enum PauseEffectExtractor {
    /// Bildet alle Paare "Pause → nächster Satz" innerhalb derselben Übung.
    public static func pairs(in sessions: [SessionRecord]) -> [PauseEffectPair] {
        var result: [PauseEffectPair] = []

        for session in sessions {
            let sets = session.sets
            for index in sets.indices.dropLast() {
                let current = sets[index]
                let next = sets[index + 1]

                guard current.countsForPerformance, next.countsForPerformance else { continue }
                guard current.exerciseID == next.exerciseID else { continue }
                guard let pause = current.actualPause else { continue }
                guard let target = current.targetPause.timerTarget else { continue }
                guard current.weight == next.weight else { continue }

                result.append(
                    PauseEffectPair(
                        exerciseID: current.exerciseID,
                        setIndex: next.setIndex,
                        weight: next.weight,
                        pause: pause,
                        pauseTarget: target,
                        nextReps: next.reps,
                        nextSecondsPerRep: next.secondsPerRep,
                        pauseDisturbance: current.pauseDisturbance?.category,
                        sessionID: session.id
                    )
                )
            }
        }

        return result
    }
}
