import Foundation

/// Vorgabe für die Wiederholungen eines Satzes.
///
/// `range` ist die Klammer der Doppelprogression: gesteigert wird erst, wenn
/// **jeder** Arbeitssatz die obere Grenze erreicht. Deshalb wird am oberen Rand
/// gestoppt, auch wenn mehr gehen -- zusätzliche Wiederholungen im ersten Satz
/// kosten den letzten Satz seine Qualität.
///
/// `maximum` gilt für Übungen wie Pull-ups, bei denen ausdrücklich so viele
/// Wiederholungen wie möglich gemacht werden. Dort gibt es keinen Stop.
public enum RepTarget: Equatable, Sendable, Codable {
    case range(min: Int, max: Int)
    case maximum

    public var lowerBound: Int? {
        switch self {
        case let .range(min, _): return min
        case .maximum: return nil
        }
    }

    public var upperBound: Int? {
        switch self {
        case let .range(_, max): return max
        case .maximum: return nil
        }
    }

    /// Soll die App vor dem Satz sagen "bei X stoppen"?
    public var stopAtUpperBound: Int? {
        upperBound
    }

    public func contains(_ reps: Int) -> Bool {
        switch self {
        case let .range(min, max): return reps >= min && reps <= max
        case .maximum: return reps > 0
        }
    }

    public var displayText: String {
        switch self {
        case let .range(min, max): return "\(min)–\(max) Wdh."
        case .maximum: return "max. Wdh."
        }
    }
}

/// Zielpause nach einem Satz.
///
/// Der Timer zielt immer auf die **untere** Grenze einer Spanne; länger bleiben
/// ist erlaubt und wird als tatsächliche Pause gespeichert. `none` steht für
/// Warm-up-Sätze (kein Pausenzwang) und für die erste Übung eines Supersets,
/// nach der ohne Pause weitergemacht wird.
public enum PauseTarget: Equatable, Sendable, Codable {
    case none
    case range(min: TimeInterval, max: TimeInterval)

    public static func seconds(_ value: TimeInterval) -> PauseTarget {
        .range(min: value, max: value)
    }

    /// Zeit, auf die der Pausen-Timer läuft.
    public var timerTarget: TimeInterval? {
        switch self {
        case .none: return nil
        case let .range(min, _): return min
        }
    }

    public var upperBound: TimeInterval? {
        switch self {
        case .none: return nil
        case let .range(_, max): return max
        }
    }

    public var enforcesRest: Bool {
        timerTarget != nil
    }

    public var displayText: String {
        switch self {
        case .none:
            return "keine Pflichtpause"
        case let .range(min, max):
            let lower = Int(min.rounded())
            let upper = Int(max.rounded())
            return lower == upper ? "\(lower)s Pause" : "\(lower)–\(upper)s Pause"
        }
    }
}

/// Warm-up oder Arbeitssatz. Warm-ups werden geführt und gespeichert, zählen
/// aber nicht in Stagnations- und Volumenkennzahlen der Arbeitsleistung.
public enum SetKind: String, Equatable, Sendable, Codable {
    case warmup
    case work
}
