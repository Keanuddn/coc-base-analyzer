import Foundation

/// Feste Angaben der Whoop-API v2. Stand August 2026.
public enum WhoopAPI {
    public static let baseURL = URL(string: "https://api.prod.whoop.com/developer/v2")!
    public static let authorizationURL = URL(string: "https://api.prod.whoop.com/oauth/oauth2/auth")!
    public static let tokenURL = URL(string: "https://api.prod.whoop.com/oauth/oauth2/token")!

    /// Benötigte Berechtigungen. `read:body_measurement` ist optional.
    public static let scopes = [
        "read:recovery",
        "read:cycles",
        "read:sleep",
        "read:workout",
        "read:profile"
    ]

    /// Whoop blockt Anfragen ohne eigenen User-Agent.
    public static let userAgent = "PPLCoach/1.0 (iOS)"

    /// Globale Grenzen laut Dokumentation. Für einen Nutzer unkritisch, aber
    /// die App soll sie kennen statt sie zu erraten.
    public enum RateLimit {
        public static let perMinute = 100
        public static let perDay = 10_000
    }

    public enum Endpoint {
        case cycles(start: Date?, end: Date?, limit: Int, nextToken: String?)
        case recoveries(start: Date?, end: Date?, limit: Int, nextToken: String?)
        case sleeps(start: Date?, end: Date?, limit: Int, nextToken: String?)
        case workouts(start: Date?, end: Date?, limit: Int, nextToken: String?)
        case recoveryForCycle(cycleID: String)

        var path: String {
            switch self {
            case .cycles: return "/cycle"
            case .recoveries: return "/recovery"
            case .sleeps: return "/activity/sleep"
            case .workouts: return "/activity/workout"
            case let .recoveryForCycle(cycleID): return "/cycle/\(cycleID)/recovery"
            }
        }

        var queryItems: [URLQueryItem] {
            let formatter = ISO8601DateFormatter()
            func items(_ start: Date?, _ end: Date?, _ limit: Int, _ token: String?) -> [URLQueryItem] {
                var result: [URLQueryItem] = [
                    // Whoop erlaubt höchstens 25 pro Seite.
                    URLQueryItem(name: "limit", value: String(min(limit, 25)))
                ]
                if let start { result.append(.init(name: "start", value: formatter.string(from: start))) }
                if let end { result.append(.init(name: "end", value: formatter.string(from: end))) }
                if let token { result.append(.init(name: "nextToken", value: token)) }
                return result
            }

            switch self {
            case let .cycles(start, end, limit, token),
                 let .recoveries(start, end, limit, token),
                 let .sleeps(start, end, limit, token),
                 let .workouts(start, end, limit, token):
                return items(start, end, limit, token)
            case .recoveryForCycle:
                return []
            }
        }

        public func url(base: URL = WhoopAPI.baseURL) -> URL? {
            var components = URLComponents(
                url: base.appendingPathComponent(path),
                resolvingAgainstBaseURL: false
            )
            let items = queryItems
            components?.queryItems = items.isEmpty ? nil : items
            return components?.url
        }
    }
}

// MARK: - Antwortstrukturen

public struct WhoopCycle: Equatable, Sendable, Codable {
    public struct Score: Equatable, Sendable, Codable {
        public let strain: Double?
        public let averageHeartRate: Int?
        public let maxHeartRate: Int?

        enum CodingKeys: String, CodingKey {
            case strain
            case averageHeartRate = "average_heart_rate"
            case maxHeartRate = "max_heart_rate"
        }
    }

    public let id: String
    public let start: Date
    public let end: Date?
    public let timezoneOffset: String?
    public let scoreState: String?
    public let score: Score?

    enum CodingKeys: String, CodingKey {
        case id, start, end, score
        case timezoneOffset = "timezone_offset"
        case scoreState = "score_state"
    }

    /// Whoop liefert den Offset als "+02:00" oder "-0500".
    public var offsetSeconds: Int {
        WhoopOffsetParser.seconds(from: timezoneOffset) ?? 0
    }

    /// Nur ausgewertete Zyklen taugen für die Analyse.
    public var isScored: Bool {
        scoreState == "SCORED"
    }
}

public struct WhoopRecovery: Equatable, Sendable, Codable {
    public struct Score: Equatable, Sendable, Codable {
        public let recoveryScore: Double?
        public let restingHeartRate: Double?
        public let hrvRmssdMilli: Double?
        public let userCalibrating: Bool?

        enum CodingKeys: String, CodingKey {
            case recoveryScore = "recovery_score"
            case restingHeartRate = "resting_heart_rate"
            case hrvRmssdMilli = "hrv_rmssd_milli"
            case userCalibrating = "user_calibrating"
        }
    }

    public let cycleID: String?
    public let sleepID: String?
    public let scoreState: String?
    public let score: Score?

    enum CodingKeys: String, CodingKey {
        case cycleID = "cycle_id"
        case sleepID = "sleep_id"
        case scoreState = "score_state"
        case score
    }

    public var isScored: Bool { scoreState == "SCORED" }

    /// Solange Whoop kalibriert, ist der Wert nicht belastbar.
    public var isCalibrating: Bool { score?.userCalibrating == true }
}

public struct WhoopSleep: Equatable, Sendable, Codable {
    public struct StageSummary: Equatable, Sendable, Codable {
        public let totalInBedTimeMilli: Double?

        enum CodingKeys: String, CodingKey {
            case totalInBedTimeMilli = "total_in_bed_time_milli"
        }
    }

    public struct Score: Equatable, Sendable, Codable {
        public let sleepPerformancePercentage: Double?
        public let stageSummary: StageSummary?

        enum CodingKeys: String, CodingKey {
            case sleepPerformancePercentage = "sleep_performance_percentage"
            case stageSummary = "stage_summary"
        }
    }

    public let id: String
    public let start: Date
    public let end: Date?
    public let score: Score?

    public var durationSeconds: TimeInterval? {
        guard let milli = score?.stageSummary?.totalInBedTimeMilli else { return nil }
        return milli / 1000
    }
}

public struct WhoopWorkout: Equatable, Sendable, Codable {
    public struct Score: Equatable, Sendable, Codable {
        public let strain: Double?
        public let averageHeartRate: Int?

        enum CodingKeys: String, CodingKey {
            case strain
            case averageHeartRate = "average_heart_rate"
        }
    }

    public let id: String
    public let start: Date
    public let end: Date?
    public let score: Score?
}

/// Paginierte Antwort. Whoop liefert maximal 25 Einträge pro Seite.
public struct WhoopPage<Element: Codable & Sendable>: Sendable, Codable {
    public let records: [Element]
    public let nextToken: String?

    enum CodingKeys: String, CodingKey {
        case records
        case nextToken = "next_token"
    }
}

enum WhoopOffsetParser {
    /// Wandelt "+02:00", "-0500" oder "Z" in Sekunden um.
    static func seconds(from text: String?) -> Int? {
        guard let text, !text.isEmpty else { return nil }
        if text == "Z" { return 0 }

        let sign: Int = text.hasPrefix("-") ? -1 : 1
        let digits = text.drop { $0 == "+" || $0 == "-" }
            .filter { $0.isNumber }
        guard digits.count >= 4 else { return nil }

        let hours = Int(digits.prefix(2)) ?? 0
        let minutes = Int(digits.dropFirst(2).prefix(2)) ?? 0
        return sign * (hours * 3600 + minutes * 60)
    }
}

/// Baut aus den Whoop-Antworten den Tageskontext der App.
public enum WhoopContextBuilder {
    /// Setzt Zyklen, Recovery, Schlaf und Workouts zu `DailyContext` zusammen.
    ///
    /// Ein Kontext gilt erst als `complete`, wenn Zyklus **und** Recovery
    /// ausgewertet sind und der Zyklus abgeschlossen ist -- der Tages-Strain
    /// ist vorher nicht endgültig.
    public static func build(
        cycles: [WhoopCycle],
        recoveries: [WhoopRecovery],
        sleeps: [WhoopSleep],
        workouts: [WhoopWorkout] = [],
        now: Date = Date()
    ) -> [DailyContext] {
        let recoveryByCycle = Dictionary(
            recoveries.compactMap { recovery -> (String, WhoopRecovery)? in
                guard let cycleID = recovery.cycleID else { return nil }
                return (cycleID, recovery)
            },
            uniquingKeysWith: { first, _ in first }
        )
        let sleepByID = Dictionary(
            sleeps.map { ($0.id, $0) },
            uniquingKeysWith: { first, _ in first }
        )

        return cycles.map { cycle in
            let recovery = recoveryByCycle[cycle.id]
            let sleep = recovery?.sleepID.flatMap { sleepByID[$0] }

            // Whoop-Workout, das in diesen Zyklus fällt.
            let workout = workouts.first { candidate in
                candidate.start >= cycle.start && (cycle.end.map { candidate.start < $0 } ?? true)
            }

            let cycleClosed = cycle.end.map { $0 <= now } ?? false
            let recoveryUsable = recovery?.isScored == true && recovery?.isCalibrating == false
            let status: ContextStatus =
                (cycleClosed && cycle.isScored && recoveryUsable) ? .complete : .pending

            return DailyContext(
                cycleID: cycle.id,
                sleepID: recovery?.sleepID,
                cycleStart: cycle.start,
                cycleEnd: cycle.end,
                timezoneOffsetSeconds: cycle.offsetSeconds,
                status: status,
                source: .whoop,
                recoveryScore: recovery?.score?.recoveryScore,
                hrvMilliseconds: recovery?.score?.hrvRmssdMilli,
                restingHeartRate: recovery?.score?.restingHeartRate,
                sleepPerformancePercentage: sleep?.score?.sleepPerformancePercentage,
                sleepDurationSeconds: sleep?.durationSeconds,
                dayStrain: cycle.score?.strain,
                workoutStrain: workout?.score?.strain,
                workoutAverageHeartRate: workout?.score?.averageHeartRate.map(Double.init)
            )
        }
    }
}
