import Foundation

/// Warum ein Messwert nicht typisch ist.
///
/// Der Wert selbst wird **nie** überschrieben oder gelöscht -- 240 Sekunden
/// Pause bleiben 240 Sekunden. Nur die Interpretation ändert sich.
public enum DisturbanceCategory: String, Equatable, Sendable, Codable {
    /// Von außen verursacht: Gespräch, Gerät belegt, Anruf, Toilette.
    /// Diese Punkte sind die am wenigsten verfälschten Pausendaten überhaupt,
    /// weil die Länge nichts mit der Tagesform zu tun hat.
    case external
    /// Selbst verursacht: brauchte länger, war noch nicht bereit.
    /// Nicht als saubere Dosis nutzbar, aber als Ermüdungssignal.
    case ownChoice
    /// Der Satz selbst ist ungültig: abgebrochen, verrutscht, Technik zerfallen.
    case botchedSet

    public var displayName: String {
        switch self {
        case .external: return "von außen"
        case .ownChoice: return "von mir"
        case .botchedSet: return "Satz vermasselt"
        }
    }
}

public enum DisturbanceReason: String, Equatable, Sendable, Codable, CaseIterable {
    case conversation
    case equipmentBusy
    case phoneCall
    case bathroomOrDrink
    case gymCrowded
    case neededLonger
    case notReadyYet
    case setAborted
    case slipped
    case wrongWeightSetting
    case formBreakdown
    case inAHurry

    public var category: DisturbanceCategory {
        switch self {
        case .conversation, .equipmentBusy, .phoneCall, .bathroomOrDrink, .gymCrowded, .inAHurry:
            return .external
        case .neededLonger, .notReadyYet:
            return .ownChoice
        case .setAborted, .slipped, .wrongWeightSetting, .formBreakdown:
            return .botchedSet
        }
    }

    public var displayName: String {
        switch self {
        case .conversation: return "Gespräch"
        case .equipmentBusy: return "Gerät belegt"
        case .phoneCall: return "Anruf"
        case .bathroomOrDrink: return "Toilette / Trinken"
        case .gymCrowded: return "Gym-Andrang"
        case .neededLonger: return "brauchte länger"
        case .notReadyYet: return "war noch nicht bereit"
        case .setAborted: return "Satz abgebrochen"
        case .slipped: return "verrutscht"
        case .wrongWeightSetting: return "falsches Gewicht eingestellt"
        case .formBreakdown: return "Technik zerfallen"
        case .inAHurry: return "in Eile"
        }
    }
}

public struct DisturbanceMarker: Equatable, Sendable, Codable {
    public enum Scope: String, Equatable, Sendable, Codable {
        case pause
        case set
    }

    public let scope: Scope
    public let reason: DisturbanceReason
    public var category: DisturbanceCategory { reason.category }

    public init(scope: Scope, reason: DisturbanceReason) {
        self.scope = scope
        self.reason = reason
    }
}

/// Ein tatsächlich ausgeführter Satz.
public struct SetRecord: Equatable, Sendable, Codable, Identifiable {
    public let id: UUID
    public let sessionID: UUID
    public let blockID: String
    public let exerciseID: String
    /// Laufender Index innerhalb der Übung, beginnend bei 1 (Warm-ups separat).
    public let setIndex: Int
    public let kind: SetKind
    /// Runde im Superset, sonst nil.
    public let supersetRound: Int?
    /// Rolle im Superset: 0 = erste Übung, 1 = zweite. Sonst nil.
    public let supersetMember: Int?

    // Soll
    public let targetReps: RepTarget
    public let targetPause: PauseTarget

    // Ist
    public let reps: Int
    public let weight: Double
    /// Dauer des Satzes in Sekunden. **nil bedeutet fehlend, nicht 0** --
    /// ein vergessener Timer darf nicht als superschneller Satz gelesen werden.
    public let duration: TimeInterval?
    public let startedAt: Date?
    public let stoppedAt: Date
    /// Tatsächliche Pause **nach** diesem Satz: von "Satz gestoppt" bis zum
    /// Start des nächsten Satzes. Beim letzten Satz der Session nil.
    public var actualPause: TimeInterval?

    public var disturbances: [DisturbanceMarker]

    public init(
        id: UUID = UUID(),
        sessionID: UUID,
        blockID: String,
        exerciseID: String,
        setIndex: Int,
        kind: SetKind,
        supersetRound: Int? = nil,
        supersetMember: Int? = nil,
        targetReps: RepTarget,
        targetPause: PauseTarget,
        reps: Int,
        weight: Double,
        duration: TimeInterval?,
        startedAt: Date?,
        stoppedAt: Date,
        actualPause: TimeInterval? = nil,
        disturbances: [DisturbanceMarker] = []
    ) {
        self.id = id
        self.sessionID = sessionID
        self.blockID = blockID
        self.exerciseID = exerciseID
        self.setIndex = setIndex
        self.kind = kind
        self.supersetRound = supersetRound
        self.supersetMember = supersetMember
        self.targetReps = targetReps
        self.targetPause = targetPause
        self.reps = reps
        self.weight = weight
        self.duration = duration
        self.startedAt = startedAt
        self.stoppedAt = stoppedAt
        self.actualPause = actualPause
        self.disturbances = disturbances
    }

    public var isWork: Bool { kind == .work }

    /// Satz ist als vermasselt markiert und fällt damit aus Leistungstrends.
    public var isBotched: Bool {
        disturbances.contains { $0.category == .botchedSet }
    }

    /// Die Pause nach diesem Satz ist als Störung markiert.
    public var pauseDisturbance: DisturbanceMarker? {
        disturbances.first { $0.scope == .pause }
    }

    /// Zählt der Satz für Leistungs- und Stagnationsauswertungen?
    public var countsForPerformance: Bool {
        isWork && !isBotched
    }

    public var volume: Double {
        Double(reps) * weight
    }

    /// Sekunden pro Wiederholung -- Ermüdungs-Proxy. Nur wenn die Dauer da ist.
    public var secondsPerRep: Double? {
        guard let duration, reps > 0 else { return nil }
        return duration / Double(reps)
    }

    /// Abweichung der tatsächlichen Pause von der Zielpause.
    /// Positiv heißt länger als vorgegeben.
    public var pauseDeviation: TimeInterval? {
        guard let actualPause, let target = targetPause.timerTarget else { return nil }
        return actualPause - target
    }

    public var reachedUpperBound: Bool {
        guard let upper = targetReps.upperBound else { return false }
        return reps >= upper
    }

    public var belowLowerBound: Bool {
        guard let lower = targetReps.lowerBound else { return false }
        return reps < lower
    }
}

/// Wie eine geplante Übung in dieser Session behandelt wurde.
public enum ExerciseOutcome: Equatable, Sendable, Codable {
    case performed
    case skipped(reason: SkipReason)
    /// Ersetzt durch eine andere Übung. Zeigt auf die tatsächlich gemachte.
    case replaced(byExerciseID: String, reason: SkipReason)
}

public enum SkipReason: String, Equatable, Sendable, Codable, CaseIterable {
    case equipmentBusy
    case pain
    case time
    case other

    public var displayName: String {
        switch self {
        case .equipmentBusy: return "Gerät belegt"
        case .pain: return "Schmerz"
        case .time: return "Zeit"
        case .other: return "anderer Grund"
        }
    }
}

public struct ExerciseRecord: Equatable, Sendable, Codable {
    public let blockID: String
    public let plannedExerciseID: String
    public var outcome: ExerciseOutcome
    /// Position der Übung in der Session, beginnend bei 1. Wird für die
    /// Vorermüdungs-Analyse gebraucht.
    public let positionInSession: Int

    public init(
        blockID: String,
        plannedExerciseID: String,
        outcome: ExerciseOutcome,
        positionInSession: Int
    ) {
        self.blockID = blockID
        self.plannedExerciseID = plannedExerciseID
        self.outcome = outcome
        self.positionInSession = positionInSession
    }

    /// Tatsächlich ausgeführte Übung -- bei Ersatz die Ersatzübung.
    public var effectiveExerciseID: String? {
        switch outcome {
        case .performed: return plannedExerciseID
        case .skipped: return nil
        case let .replaced(byExerciseID, _): return byExerciseID
        }
    }
}

/// Ein Tap zu Beginn der Session. Bleibt trotz Whoop, weil sich subjektives
/// Gefühl und Recovery-Score häufig widersprechen -- und dieser Widerspruch
/// selbst ein Signal ist.
public enum Readiness: String, Equatable, Sendable, Codable, CaseIterable {
    case good
    case okay
    case bad

    public var displayName: String {
        switch self {
        case .good: return "Gut"
        case .okay: return "Okay"
        case .bad: return "Schlecht"
        }
    }
}

/// Rückblick am Ende der Session.
public enum SessionTag: String, Equatable, Sendable, Codable, CaseIterable {
    case normal
    case badDay
    case aborted

    public var displayName: String {
        switch self {
        case .normal: return "normal"
        case .badDay: return "schlechter Tag"
        case .aborted: return "abgebrochen"
        }
    }
}

public enum SessionStatus: String, Equatable, Sendable, Codable {
    case open
    case completed
    case aborted
}

public struct SessionRecord: Equatable, Sendable, Codable, Identifiable {
    public let id: UUID
    public let day: TrainingDay
    public let planVersionID: String
    public let startedAt: Date
    public var endedAt: Date?
    public var status: SessionStatus
    public var readiness: Readiness?
    public var tag: SessionTag?
    public var sets: [SetRecord]
    public var exercises: [ExerciseRecord]
    public var photoIDs: [UUID]
    /// Läuft diese Session innerhalb einer Probe? Dann darf sie nicht als
    /// normale Woche gelesen werden.
    public var trialID: UUID?

    public init(
        id: UUID = UUID(),
        day: TrainingDay,
        planVersionID: String,
        startedAt: Date,
        endedAt: Date? = nil,
        status: SessionStatus = .open,
        readiness: Readiness? = nil,
        tag: SessionTag? = nil,
        sets: [SetRecord] = [],
        exercises: [ExerciseRecord] = [],
        photoIDs: [UUID] = [],
        trialID: UUID? = nil
    ) {
        self.id = id
        self.day = day
        self.planVersionID = planVersionID
        self.startedAt = startedAt
        self.endedAt = endedAt
        self.status = status
        self.readiness = readiness
        self.tag = tag
        self.sets = sets
        self.exercises = exercises
        self.photoIDs = photoIDs
        self.trialID = trialID
    }

    public var duration: TimeInterval? {
        guard let endedAt else { return nil }
        return endedAt.timeIntervalSince(startedAt)
    }

    public var workSets: [SetRecord] {
        sets.filter(\.countsForPerformance)
    }

    public var totalVolume: Double {
        workSets.reduce(0) { $0 + $1.volume }
    }

    public func sets(forExercise exerciseID: String) -> [SetRecord] {
        sets.filter { $0.exerciseID == exerciseID }
    }

    /// Kumuliertes Arbeitsvolumen bis zu einer Position -- Grundlage für
    /// "späte Übungen leiden unter der bisherigen Session".
    public func volumeBefore(position: Int) -> Double {
        let blockIDs = exercises.filter { $0.positionInSession < position }.map(\.blockID)
        return sets
            .filter { blockIDs.contains($0.blockID) && $0.countsForPerformance }
            .reduce(0) { $0 + $1.volume }
    }
}

public struct PhotoRecord: Equatable, Sendable, Codable, Identifiable {
    public let id: UUID
    public let sessionID: UUID?
    public let slot: PhotoSlot
    public let takenAt: Date
    /// Dateiname im App-Container.
    public let fileName: String
    /// Einmal festgelegte Beschreibung von Ort und Licht, danach jedes Mal
    /// angezeigt.
    public let locationNote: String?
    /// Vorgängerfoto desselben Slots -- dient als Schablone beim Auslösen und
    /// als Vergleichspartner in der Timeline.
    public let previousPhotoID: UUID?
    public let bodyweightAtTime: Double?

    public init(
        id: UUID = UUID(),
        sessionID: UUID?,
        slot: PhotoSlot,
        takenAt: Date,
        fileName: String,
        locationNote: String? = nil,
        previousPhotoID: UUID? = nil,
        bodyweightAtTime: Double? = nil
    ) {
        self.id = id
        self.sessionID = sessionID
        self.slot = slot
        self.takenAt = takenAt
        self.fileName = fileName
        self.locationNote = locationNote
        self.previousPhotoID = previousPhotoID
        self.bodyweightAtTime = bodyweightAtTime
    }
}

public struct BodyweightRecord: Equatable, Sendable, Codable, Identifiable {
    public let id: UUID
    public let date: Date
    public let kilograms: Double
    /// Bedingung, z. B. "morgens nüchtern". Ohne konstante Bedingung ist der
    /// Verlauf nicht lesbar.
    public let condition: String?

    public init(id: UUID = UUID(), date: Date, kilograms: Double, condition: String? = nil) {
        self.id = id
        self.date = date
        self.kilograms = kilograms
        self.condition = condition
    }
}
