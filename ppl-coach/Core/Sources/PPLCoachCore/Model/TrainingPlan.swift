import Foundation

/// Vorgabe für einen einzelnen Satz innerhalb eines Blocks.
public struct SetPrescription: Equatable, Sendable, Codable {
    public let kind: SetKind
    public let reps: RepTarget
    public let pause: PauseTarget
    /// Freitext für Intensitätsstaffeln im Warm-up, z. B. "~50 %" oder "leer".
    public let intensityNote: String?
    /// Letzter Satz einer Übung, der bewusst weggelassen werden darf
    /// (Wadenheben: 3--4 Sätze).
    public let isOptional: Bool
    /// Anteil der Arbeitslast für Warm-up-Sätze.
    ///
    /// `nil` fällt bei der Empfehlung auf 0,5. Explizites `0` heißt leer /
    /// ohne Last und bleibt von `nil` getrennt.
    public let loadFraction: Double?

    enum CodingKeys: String, CodingKey {
        case kind, reps, pause, intensityNote, isOptional, loadFraction
    }

    public init(
        kind: SetKind,
        reps: RepTarget,
        pause: PauseTarget,
        intensityNote: String? = nil,
        isOptional: Bool = false,
        loadFraction: Double? = nil
    ) {
        self.kind = kind
        self.reps = reps
        self.pause = pause
        self.intensityNote = intensityNote
        self.isOptional = isOptional
        self.loadFraction = loadFraction
    }

    public init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        kind = try container.decode(SetKind.self, forKey: .kind)
        reps = try container.decode(RepTarget.self, forKey: .reps)
        pause = try container.decode(PauseTarget.self, forKey: .pause)
        intensityNote = try container.decodeIfPresent(String.self, forKey: .intensityNote)
        isOptional = try container.decodeIfPresent(Bool.self, forKey: .isOptional) ?? false
        loadFraction = try container.decodeIfPresent(Double.self, forKey: .loadFraction)
    }

    public static func work(
        reps: RepTarget,
        pause: PauseTarget,
        isOptional: Bool = false
    ) -> SetPrescription {
        SetPrescription(kind: .work, reps: reps, pause: pause, isOptional: isOptional)
    }

    public static func warmup(
        reps: RepTarget,
        note: String? = nil,
        loadFraction: Double? = nil
    ) -> SetPrescription {
        // Warm-ups haben nie eine Pflichtpause.
        SetPrescription(
            kind: .warmup,
            reps: reps,
            pause: .none,
            intensityNote: note,
            loadFraction: loadFraction
        )
    }

    /// Schätzt den Lastanteil aus der Intensitätsnotiz, wenn im Plan kein
    /// `loadFraction` steht (ältere gespeicherte Fassungen).
    ///
    /// "leer" / "locker" → 0. "~75–80 %" → 0,75. Unbekannt bleibt `nil`.
    public static func inferredWarmupLoadFraction(from note: String?) -> Double? {
        guard let note, !note.isEmpty else { return nil }
        let folded = note.folding(
            options: [.diacriticInsensitive, .caseInsensitive],
            locale: Locale(identifier: "de_DE")
        )
        if folded.contains("leer") || folded.contains("locker") {
            return 0
        }
        if folded.contains("75") {
            return 0.75
        }
        if folded.contains("50-60") || folded.contains("50–60") {
            return 0.55
        }
        if folded.contains("50") {
            return 0.5
        }
        return nil
    }

    func withLoadFraction(_ fraction: Double?) -> SetPrescription {
        SetPrescription(
            kind: kind,
            reps: reps,
            pause: pause,
            intensityNote: intensityNote,
            isOptional: isOptional,
            loadFraction: fraction
        )
    }

    /// Übernimmt fehlende Warm-up-Anteile aus der kanonischen Vorgabe. Gesetzte
    /// Werte — auch explizites `0` — bleiben unverändert.
    static func mergingWarmupFractions(
        _ sets: [SetPrescription],
        canonical: [SetPrescription]
    ) -> [SetPrescription] {
        sets.enumerated().map { index, local in
            guard local.kind == .warmup, local.loadFraction == nil else {
                return local
            }
            let fromCanonical = index < canonical.count ? canonical[index].loadFraction : nil
            let fraction = fromCanonical
                ?? inferredWarmupLoadFraction(from: local.intensityNote)
                ?? 0.5
            return local.withLoadFraction(fraction)
        }
    }
}

/// Ein Abschnitt des Trainingstages: eine einzelne Übung oder ein Superset aus
/// zwei Übungen, bei dem die Pause erst nach der zweiten Übung läuft.
public enum Block: Equatable, Sendable, Codable, Identifiable {
    case single(id: String, exerciseID: String, sets: [SetPrescription])
    case superset(
        id: String,
        firstExerciseID: String,
        firstSets: [SetPrescription],
        secondExerciseID: String,
        secondSets: [SetPrescription]
    )

    public var id: String {
        switch self {
        case let .single(id, _, _): return id
        case let .superset(id, _, _, _, _): return id
        }
    }

    public var exerciseIDs: [String] {
        switch self {
        case let .single(_, exerciseID, _):
            return [exerciseID]
        case let .superset(_, first, _, second, _):
            return [first, second]
        }
    }

    public var isSuperset: Bool {
        if case .superset = self { return true }
        return false
    }

    fileprivate func fillingMissingWarmupLoadFractions(from canonical: Block?) -> Block {
        switch self {
        case let .single(id, exerciseID, sets):
            let canonicalSets: [SetPrescription]
            if case let .single(_, _, matched) = canonical {
                canonicalSets = matched
            } else {
                canonicalSets = []
            }
            return .single(
                id: id,
                exerciseID: exerciseID,
                sets: SetPrescription.mergingWarmupFractions(sets, canonical: canonicalSets)
            )
        case let .superset(id, firstID, firstSets, secondID, secondSets):
            var canonicalFirst: [SetPrescription] = []
            var canonicalSecond: [SetPrescription] = []
            if case let .superset(_, _, first, _, second) = canonical {
                canonicalFirst = first
                canonicalSecond = second
            }
            return .superset(
                id: id,
                firstExerciseID: firstID,
                firstSets: SetPrescription.mergingWarmupFractions(firstSets, canonical: canonicalFirst),
                secondExerciseID: secondID,
                secondSets: SetPrescription.mergingWarmupFractions(secondSets, canonical: canonicalSecond)
            )
        }
    }
}

/// Push, Pull oder Legs. Die Reihenfolge im Zyklus ist fest; welcher Tag als
/// nächstes ansteht, ergibt sich aus der Warteschlange, nicht aus dem Wochentag.
public enum TrainingDay: String, Equatable, Sendable, Codable, CaseIterable {
    case push
    case pull
    case legs

    public var displayName: String {
        switch self {
        case .push: return "Push"
        case .pull: return "Pull"
        case .legs: return "Legs/Schultern"
        }
    }

    /// Nächster Tag im Zyklus. Ein verpasster Pull-Tag bleibt der nächste Tag,
    /// damit der Split nicht still kippt.
    public var next: TrainingDay {
        switch self {
        case .push: return .pull
        case .pull: return .legs
        case .legs: return .push
        }
    }

    /// Muskelgruppen für die Foto-Slots des Tages.
    public var photoSlots: [PhotoSlot] {
        switch self {
        case .push: return [.chestFront, .chestSide, .tricepsFlexed]
        case .pull: return [.back, .bicepsSide]
        case .legs: return [.legsFront, .shouldersSide]
        }
    }
}

public struct DayTemplate: Equatable, Sendable, Codable {
    public let day: TrainingDay
    public let blocks: [Block]

    public init(day: TrainingDay, blocks: [Block]) {
        self.day = day
        self.blocks = blocks
    }
}

/// Eine Fassung des Plans. Jede Änderung in "Mein Plan" erzeugt eine neue
/// Version, damit alte Sessions gegen die damals gültige Vorgabe vergleichbar
/// bleiben und die Analyse einen Bruch erkennen kann.
public struct PlanVersion: Equatable, Sendable, Codable, Identifiable {
    public let id: String
    public let createdAt: Date
    public let exercises: [Exercise]
    public let days: [DayTemplate]

    public init(id: String, createdAt: Date, exercises: [Exercise], days: [DayTemplate]) {
        self.id = id
        self.createdAt = createdAt
        self.exercises = exercises
        self.days = days
    }

    public func exercise(id: String) -> Exercise? {
        exercises.first { $0.id == id }
    }

    public func template(for day: TrainingDay) -> DayTemplate? {
        days.first { $0.day == day }
    }

    /// Füllt fehlende Warm-up-`loadFraction`-Werte aus dem kanonischen Plan.
    ///
    /// Gespeicherte Fassungen von vor dem Feld bleiben damit nutzbar, ohne
    /// Gewichtsschritte oder Satzzahlen zu überschreiben. Explizites `0`
    /// (leere Stange) wird nicht zu `nil` und nicht zu 0,5.
    public func fillingMissingWarmupLoadFractions(
        from canonical: PlanVersion = DefaultPlan.version()
    ) -> PlanVersion {
        let canonicalByDay = Dictionary(uniqueKeysWithValues: canonical.days.map { ($0.day, $0) })
        let filledDays = days.map { day -> DayTemplate in
            let canonicalBlocks = Dictionary(
                uniqueKeysWithValues: (canonicalByDay[day.day]?.blocks ?? []).map { ($0.id, $0) }
            )
            let filledBlocks = day.blocks.map { block in
                block.fillingMissingWarmupLoadFractions(from: canonicalBlocks[block.id])
            }
            return DayTemplate(day: day.day, blocks: filledBlocks)
        }
        return PlanVersion(
            id: id,
            createdAt: createdAt,
            exercises: exercises,
            days: filledDays
        )
    }
}
