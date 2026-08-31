import Foundation

/// Vollständigkeit des Tageskontexts.
///
/// Recovery entsteht erst nach dem Aufwachen, der Tages-Strain erst nach
/// Tagesende. Der Kontext wird also nachträglich vollständig. **Detektoren
/// rechnen ausschließlich mit `complete`**, sonst entstehen Befunde auf halben
/// Daten.
public enum ContextStatus: String, Equatable, Sendable, Codable {
    case pending
    case complete
}

public enum ContextSource: String, Equatable, Sendable, Codable {
    case whoop
    case manual
}

/// Tageskontext neben dem Training. Ab v1 aus Whoop, plus der Readiness-Tap.
///
/// Der Schlüssel ist **nicht** das Kalenderdatum, sondern der physiologische
/// Zyklus von Whoop: er hat Start, Ende und Zeitzonen-Offset. Damit sind
/// Spätabend-Training und Reisen automatisch korrekt zugeordnet.
public struct DailyContext: Equatable, Sendable, Codable, Identifiable {
    public let id: UUID
    /// Whoop-Zyklus, in dessen Zeitraum die Session fällt.
    public let cycleID: String?
    public let sleepID: String?
    public let cycleStart: Date
    public let cycleEnd: Date?
    public let timezoneOffsetSeconds: Int

    public var status: ContextStatus
    public var source: ContextSource

    /// 0--100. Erst nach abgeschlossenem Schlaf verfügbar.
    public var recoveryScore: Double?
    public var hrvMilliseconds: Double?
    public var restingHeartRate: Double?
    public var sleepPerformancePercentage: Double?
    public var sleepDurationSeconds: TimeInterval?
    /// 0--21. Erst nach Tagesende endgültig.
    public var dayStrain: Double?
    /// Whoop-Workout der Session, nur als Kontext -- nie als Ersatz für die
    /// eigenen Satzdaten.
    public var workoutStrain: Double?
    public var workoutAverageHeartRate: Double?

    /// Abweichung vom eigenen Mittel über Wochen. Rohwerte sagen wenig; erst
    /// der Abstand zur Baseline ist interpretierbar.
    public var hrvDeviation: Double?
    public var recoveryDeviation: Double?

    public init(
        id: UUID = UUID(),
        cycleID: String? = nil,
        sleepID: String? = nil,
        cycleStart: Date,
        cycleEnd: Date? = nil,
        timezoneOffsetSeconds: Int = 0,
        status: ContextStatus = .pending,
        source: ContextSource = .whoop,
        recoveryScore: Double? = nil,
        hrvMilliseconds: Double? = nil,
        restingHeartRate: Double? = nil,
        sleepPerformancePercentage: Double? = nil,
        sleepDurationSeconds: TimeInterval? = nil,
        dayStrain: Double? = nil,
        workoutStrain: Double? = nil,
        workoutAverageHeartRate: Double? = nil,
        hrvDeviation: Double? = nil,
        recoveryDeviation: Double? = nil
    ) {
        self.id = id
        self.cycleID = cycleID
        self.sleepID = sleepID
        self.cycleStart = cycleStart
        self.cycleEnd = cycleEnd
        self.timezoneOffsetSeconds = timezoneOffsetSeconds
        self.status = status
        self.source = source
        self.recoveryScore = recoveryScore
        self.hrvMilliseconds = hrvMilliseconds
        self.restingHeartRate = restingHeartRate
        self.sleepPerformancePercentage = sleepPerformancePercentage
        self.sleepDurationSeconds = sleepDurationSeconds
        self.dayStrain = dayStrain
        self.workoutStrain = workoutStrain
        self.workoutAverageHeartRate = workoutAverageHeartRate
        self.hrvDeviation = hrvDeviation
        self.recoveryDeviation = recoveryDeviation
    }

    /// Fällt ein Zeitpunkt in diesen Zyklus? Ein offener Zyklus (ohne Ende)
    /// gilt bis jetzt.
    public func covers(_ date: Date) -> Bool {
        guard date >= cycleStart else { return false }
        guard let cycleEnd else { return true }
        return date < cycleEnd
    }

    public var isUsableForAnalysis: Bool {
        status == .complete
    }

    /// Whoops Farbzonen: grün ab 67, gelb ab 34, sonst rot.
    public enum RecoveryZone: String, Equatable, Sendable {
        case green, yellow, red

        public var displayName: String {
            switch self {
            case .green: return "grün"
            case .yellow: return "gelb"
            case .red: return "rot"
            }
        }
    }

    public var recoveryZone: RecoveryZone? {
        guard let recoveryScore else { return nil }
        switch recoveryScore {
        case 67...: return .green
        case 34..<67: return .yellow
        default: return .red
        }
    }
}

/// Ordnet Sessions den Whoop-Zyklen zu und rechnet Baselines.
public enum WhoopContextMapper {
    /// Findet den Zyklus, in dessen Zeitraum der Trainingsbeginn fällt.
    ///
    /// Bewusst über den Zyklus und nicht über das Kalenderdatum: Whoop rechnet
    /// physiologisch, wodurch ein Training um 00:30 zum vorherigen Zyklus
    /// gehört und Reisen ohne Sonderfall funktionieren.
    public static func context(
        for session: SessionRecord,
        in contexts: [DailyContext]
    ) -> DailyContext? {
        contexts
            .filter { $0.covers(session.startedAt) }
            .sorted { $0.cycleStart > $1.cycleStart }
            .first
    }

    /// Trägt die Abweichungen zur eigenen Baseline nach.
    ///
    /// - Parameter window: Anzahl vorhergehender Tage, aus denen die Baseline
    ///   gebildet wird. Deshalb wird beim ersten Verbinden Historie nachgeladen:
    ///   sonst gibt es wochenlang keine brauchbare Baseline.
    public static func withBaselines(
        _ contexts: [DailyContext],
        window: Int = 30
    ) -> [DailyContext] {
        let sorted = contexts.sorted { $0.cycleStart < $1.cycleStart }
        var result: [DailyContext] = []

        for (index, context) in sorted.enumerated() {
            var updated = context
            let start = max(0, index - window)
            let previous = sorted[start..<index]

            let hrvValues = previous.compactMap(\.hrvMilliseconds)
            if let baseline = Metrics.mean(hrvValues), let current = context.hrvMilliseconds {
                updated.hrvDeviation = current - baseline
            }

            let recoveryValues = previous.compactMap(\.recoveryScore)
            if let baseline = Metrics.mean(recoveryValues), let current = context.recoveryScore {
                updated.recoveryDeviation = current - baseline
            }

            result.append(updated)
        }

        return result
    }
}
