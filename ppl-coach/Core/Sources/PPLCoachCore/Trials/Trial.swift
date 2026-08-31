import Foundation

/// Was in einer Probe geändert wird.
///
/// Zwei Quellen, dieselbe Prüfung: der Detektor schlägt aus einem festen
/// Katalog vor, das Modell darf darüber hinausgehen, und du kannst jederzeit
/// selbst eine Variation anlegen. Der Unterschied ist nur, **wer die Idee
/// hatte** -- nicht, wie streng geprüft wird.
public enum TrialIntervention: Equatable, Sendable, Codable {
    /// Reihenfolge zweier Übungen desselben Tages tauschen.
    case swapOrder(firstExerciseID: String, secondExerciseID: String, day: TrainingDay)
    /// Superset auflösen, beide Übungen getrennt mit eigener Pause.
    case dissolveSuperset(blockID: String)
    /// Zielpause bei bestimmten Übungen strikt einhalten.
    case enforcePause(exerciseIDs: [String])
    /// Trainingszeit in ein anderes Tagesfenster legen.
    case shiftTrainingTime(to: TimeOfDayBucket)
    /// Gewicht bewusst halten, um Wiederholungen und Tempo isoliert zu prüfen.
    case holdLoad(exerciseIDs: [String])
    /// Eigene Idee -- beliebige Variation, in einem Satz beschrieben.
    case custom(description: String, exerciseIDs: [String])

    public var displayText: String {
        switch self {
        case let .swapOrder(first, second, day):
            return "Am \(day.displayName)-Tag \(first) und \(second) tauschen"
        case let .dissolveSuperset(blockID):
            return "Superset \(blockID) auflösen"
        case let .enforcePause(exerciseIDs):
            return "Zielpause strikt einhalten bei: \(exerciseIDs.joined(separator: ", "))"
        case let .shiftTrainingTime(bucket):
            return "Training \(bucket.displayName) legen"
        case let .holdLoad(exerciseIDs):
            return "Gewicht halten bei: \(exerciseIDs.joined(separator: ", "))"
        case let .custom(description, _):
            return description
        }
    }

    public var affectedExerciseIDs: [String] {
        switch self {
        case let .swapOrder(first, second, _): return [first, second]
        case .dissolveSuperset: return []
        case let .enforcePause(ids): return ids
        case .shiftTrainingTime: return []
        case let .holdLoad(ids): return ids
        case let .custom(_, ids): return ids
        }
    }

    /// Betroffene Trainingstage -- für die Regel „eine laufende Variation pro
    /// Trainingstag“.
    public func affectedDays(in planVersion: PlanVersion) -> Set<TrainingDay> {
        switch self {
        case let .swapOrder(_, _, day):
            return [day]
        case .shiftTrainingTime:
            return Set(TrainingDay.allCases)
        case let .dissolveSuperset(blockID):
            let days = planVersion.days.filter { template in
                template.blocks.contains { $0.id == blockID }
            }
            return Set(days.map(\.day))
        case let .enforcePause(ids), let .holdLoad(ids), let .custom(_, ids):
            let days = planVersion.days.filter { template in
                template.blocks.contains { block in
                    block.exerciseIDs.contains { ids.contains($0) }
                }
            }
            return Set(days.map(\.day))
        }
    }
}

/// Woran gemessen wird, ob die Probe geholfen hat.
public enum TrialMetric: String, Equatable, Sendable, Codable {
    case reps
    case secondsPerRep
    case volume

    public var displayName: String {
        switch self {
        case .reps: return "Wiederholungen"
        case .secondsPerRep: return "Sekunden pro Wiederholung"
        case .volume: return "Volumen"
        }
    }

    /// Bei Zeit pro Wiederholung ist weniger besser.
    public var lowerIsBetter: Bool {
        self == .secondsPerRep
    }
}

public enum TrialStatus: String, Equatable, Sendable, Codable {
    case proposed
    case running
    case evaluated
    case declined
    case cancelled
}

public enum TrialOrigin: String, Equatable, Sendable, Codable {
    /// Deterministisch aus einem Detektor.
    case detector
    /// Vorschlag des Modells über mehrere Befunde hinweg.
    case model
    /// Eigene Idee.
    case user
}

/// Eine Probe: was ändern, wie lange, was gilt als Antwort.
public struct Trial: Equatable, Sendable, Codable, Identifiable {
    public let id: UUID
    public let origin: TrialOrigin
    /// Die Frage, die ohne Variation nicht beantwortbar war.
    public let question: String
    public let intervention: TrialIntervention
    /// Übung, an der gemessen wird.
    public let measuredExerciseID: String
    public let metric: TrialMetric
    /// Wie viele Sessions die Probe läuft -- berechnet, nicht geraten.
    public let sessionCount: Int
    /// Ab welchem Unterschied es als Antwort gilt -- aus der eigenen Streuung.
    public let successThreshold: Double
    /// Vergleichswert aus der Zeit vor der Probe.
    public let baselineValue: Double
    /// Streuung vor der Probe, aus der die Schwelle abgeleitet wurde.
    public let baselineScatter: Double
    public var status: TrialStatus
    public var startedAt: Date?
    public var sessionIDs: [UUID]

    public init(
        id: UUID = UUID(),
        origin: TrialOrigin,
        question: String,
        intervention: TrialIntervention,
        measuredExerciseID: String,
        metric: TrialMetric,
        sessionCount: Int,
        successThreshold: Double,
        baselineValue: Double,
        baselineScatter: Double,
        status: TrialStatus = .proposed,
        startedAt: Date? = nil,
        sessionIDs: [UUID] = []
    ) {
        self.id = id
        self.origin = origin
        self.question = question
        self.intervention = intervention
        self.measuredExerciseID = measuredExerciseID
        self.metric = metric
        self.sessionCount = sessionCount
        self.successThreshold = successThreshold
        self.baselineValue = baselineValue
        self.baselineScatter = baselineScatter
        self.status = status
        self.startedAt = startedAt
        self.sessionIDs = sessionIDs
    }

    /// Der Satz, der dem Nutzer gezeigt wird: was ändern, wie lange, was gilt
    /// als Antwort.
    public func proposalText(planVersion: PlanVersion) -> String {
        let name = planVersion.exercise(id: measuredExerciseID)?.name ?? measuredExerciseID
        let threshold = String(format: "%.1f", successThreshold)
        let direction = metric.lowerIsBetter ? "weniger" : "mehr"
        return "\(intervention.displayText) für \(sessionCount) Sessions. "
            + "Wenn \(name) danach \(threshold) \(metric.displayName) \(direction) zeigt, "
            + "war es die Ursache."
    }
}

public struct TrialResult: Equatable, Sendable {
    public let trialID: UUID
    public let baselineValue: Double
    public let trialValue: Double
    public let difference: Double
    public let threshold: Double
    public let sessionsObserved: Int
    public let succeeded: Bool
    public let verdict: String
}
