import Foundation

/// Warum ein Detektor schweigt. Ein Detektor liefert entweder einen Befund mit
/// Belegen oder **nichts** -- nie ein "vielleicht".
public enum SilenceReason: Equatable, Sendable {
    case notEnoughData(have: Int, need: Int)
    case effectTooSmall(observed: Double, threshold: Double)
    case planVersionChanged
    case missingPhotoSlot(PhotoSlot)
    case bodyweightFlatOrFalling
    case notAnsweredWithoutVariation(dimension: VariationDimension)
    case onlyDisturbedEvidence
    case awaitingConfirmationInSecondWindow

    public var displayText: String {
        switch self {
        case let .notEnoughData(have, need):
            return "Zu wenig Daten: \(have) von \(need) nötigen Belegen."
        case let .effectTooSmall(observed, threshold):
            let obs = String(format: "%.1f", observed)
            let thr = String(format: "%.1f", threshold)
            return "Unterschied zu klein (\(obs) gegenüber Schwelle \(thr))."
        case .planVersionChanged:
            return "Der Plan hat sich geändert -- über die Grenze hinweg wird nicht verglichen."
        case let .missingPhotoSlot(slot):
            return "Für „\(slot.displayName)“ fehlen vergleichbare Fotos."
        case .bodyweightFlatOrFalling:
            return "Körpergewicht unverändert oder fallend -- Aufbau ist dabei unwahrscheinlich, unabhängig vom Training."
        case let .notAnsweredWithoutVariation(dimension):
            return "Ohne Variation nicht beantwortbar: \(dimension.displayName)."
        case .onlyDisturbedEvidence:
            return "Alle Belege sind als Störung markiert."
        case .awaitingConfirmationInSecondWindow:
            return "Muster gesehen, wird erst nach Bestätigung in einem zweiten Zeitfenster gemeldet."
        }
    }
}

/// Dimension, die variiert werden muss, damit eine Frage beantwortbar wird.
public enum VariationDimension: String, Equatable, Sendable, Codable {
    case exerciseOrder
    case timeOfDay
    case supersetPairing
    case pauseAdherence
    case loadProgression

    public var displayName: String {
        switch self {
        case .exerciseOrder: return "Reihenfolge der Übungen"
        case .timeOfDay: return "Trainingszeit"
        case .supersetPairing: return "Superset ja oder nein"
        case .pauseAdherence: return "Einhaltung der Pausen"
        case .loadProgression: return "Steigerung der Last"
        }
    }
}

/// Ein einzelner Belegwert, der in der Karte auftaucht. Effekte werden immer in
/// verständlichen Einheiten angegeben -- nie als Korrelationskoeffizient.
public struct Evidence: Equatable, Sendable {
    public let label: String
    public let value: String
    /// Aus wie vielen Datenpunkten stammt der Wert?
    public let sampleSize: Int
    /// Wie viele davon waren als Störung markiert?
    public let disturbedCount: Int

    public init(label: String, value: String, sampleSize: Int, disturbedCount: Int = 0) {
        self.label = label
        self.value = value
        self.sampleSize = sampleSize
        self.disturbedCount = disturbedCount
    }
}

public enum FindingSeverity: String, Equatable, Sendable, Codable {
    /// Beobachtung ohne Handlungsbedarf.
    case observation
    /// Etwas bremst messbar.
    case issue
    /// Positive Entwicklung, die man halten sollte.
    case positive
}

/// Ein belastbarer Befund. Immer in der Form: Beobachtung, Ursache, Belege.
public struct Finding: Equatable, Sendable, Identifiable {
    public let id: String
    public let detectorID: String
    public let severity: FindingSeverity
    /// Was beobachtet wurde, in einem Satz.
    public let observation: String
    /// Die benannte wahrscheinlichste Ursache.
    public let likelyCause: String
    /// Ursachen, die geprüft und ausgeschlossen wurden.
    public let ruledOut: [String]
    public let evidence: [Evidence]
    /// Betroffene Übungen -- damit die Karte auf einen Chart führt.
    public let exerciseIDs: [String]
    public let muscleGroups: [MuscleGroup]
    /// Was diese Erklärung nicht abdeckt.
    public let limitations: [String]
    /// Vorschlag einer Variation, wenn die Frage ohne sie offen bleibt.
    public let suggestedVariation: VariationDimension?

    public init(
        id: String,
        detectorID: String,
        severity: FindingSeverity,
        observation: String,
        likelyCause: String,
        ruledOut: [String] = [],
        evidence: [Evidence],
        exerciseIDs: [String] = [],
        muscleGroups: [MuscleGroup] = [],
        limitations: [String] = [],
        suggestedVariation: VariationDimension? = nil
    ) {
        self.id = id
        self.detectorID = detectorID
        self.severity = severity
        self.observation = observation
        self.likelyCause = likelyCause
        self.ruledOut = ruledOut
        self.evidence = evidence
        self.exerciseIDs = exerciseIDs
        self.muscleGroups = muscleGroups
        self.limitations = limitations
        self.suggestedVariation = suggestedVariation
    }

    /// Anteil markierter Belege. Ein Befund darf nicht ausschließlich auf
    /// markierten Sätzen beruhen.
    public var restsOnlyOnDisturbedEvidence: Bool {
        guard !evidence.isEmpty else { return false }
        return evidence.allSatisfy { $0.sampleSize > 0 && $0.disturbedCount == $0.sampleSize }
    }
}

/// Ergebnis eines Detektorlaufs.
public enum DetectorResult: Equatable, Sendable {
    case finding(Finding)
    case silent(SilenceReason)

    public var finding: Finding? {
        if case let .finding(value) = self { return value }
        return nil
    }

    public var silenceReason: SilenceReason? {
        if case let .silent(value) = self { return value }
        return nil
    }
}

/// Alles, was ein Detektor sehen darf.
public struct AnalysisInput: Sendable {
    public let planVersion: PlanVersion
    /// Nur abgeschlossene Sessions, aufsteigend nach Startzeit.
    public let sessions: [SessionRecord]
    public let dailyContexts: [DailyContext]
    public let bodyweight: [BodyweightRecord]
    public let photos: [PhotoRecord]
    public let calendar: Calendar

    public init(
        planVersion: PlanVersion,
        sessions: [SessionRecord],
        dailyContexts: [DailyContext] = [],
        bodyweight: [BodyweightRecord] = [],
        photos: [PhotoRecord] = [],
        calendar: Calendar = .current
    ) {
        self.planVersion = planVersion
        self.sessions = sessions
            .filter { $0.status == .completed }
            .sorted { $0.startedAt < $1.startedAt }
        self.dailyContexts = dailyContexts
        self.bodyweight = bodyweight.sorted { $0.date < $1.date }
        self.photos = photos.sorted { $0.takenAt < $1.takenAt }
        self.calendar = calendar
    }

    /// Sessions, die als normale Wochen gelesen werden dürfen.
    ///
    /// Ausgeschlossen: Proben (absichtliche Variation), als schlechter Tag
    /// markierte und abgebrochene Sessions sowie Readiness „schlecht“. Sonst
    /// würde ein bewusst veränderter oder ein mieser Tag als Stagnation zählen.
    public var comparableSessions: [SessionRecord] {
        sessions.filter {
            $0.trialID == nil && $0.tag != .badDay && $0.tag != .aborted && $0.readiness != .bad
        }
    }

    public func sessions(day: TrainingDay) -> [SessionRecord] {
        comparableSessions.filter { $0.day == day }
    }

    /// Sessions einer Planversion -- über Versionsgrenzen wird nicht verglichen.
    public func sessions(planVersionID: String) -> [SessionRecord] {
        comparableSessions.filter { $0.planVersionID == planVersionID }
    }

    public func context(for session: SessionRecord) -> DailyContext? {
        dailyContexts.first { $0.covers(session.startedAt) }
    }
}

/// Gemeinsame Schnittstelle aller Detektoren.
///
/// Jeder Detektor beantwortet **genau eine** Frage, hat eine Mindeststichprobe,
/// eine Effektschwelle in verständlichen Einheiten und klare Schweigeregeln.
public protocol Detector: Sendable {
    var id: String { get }
    /// Die Frage in einem Satz.
    var question: String { get }
    /// Wie viele Belege es mindestens braucht.
    var minimumSampleSize: Int { get }
    func run(_ input: AnalysisInput) -> DetectorResult
}
