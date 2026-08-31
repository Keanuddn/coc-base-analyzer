import Foundation

public enum MuscleGroup: String, Equatable, Sendable, Codable, CaseIterable {
    case chest
    case triceps
    case back
    case biceps
    case forearms
    case shoulders
    case traps
    case quads
    case hamstrings
    case glutes
    case calves

    public var displayName: String {
        switch self {
        case .chest: return "Brust"
        case .triceps: return "Trizeps"
        case .back: return "Rücken"
        case .biceps: return "Bizeps"
        case .forearms: return "Unterarme"
        case .shoulders: return "Schultern"
        case .traps: return "Nacken"
        case .quads: return "Oberschenkel vorn"
        case .hamstrings: return "Oberschenkel hinten"
        case .glutes: return "Gesäß"
        case .calves: return "Waden"
        }
    }
}

/// Rolle der Übung im Tag. Wichtig für die Analyse: bei Isolationsübungen wird
/// Vorermüdung geprüft, bei Compounds eher Tagesform.
public enum ExerciseRole: String, Equatable, Sendable, Codable {
    case compound
    case isolation
}

/// Womit die Last verstellt wird -- bestimmt die kleinste sinnvolle Stufe und
/// ob Fortschritt überhaupt in Kilogramm gemessen werden kann.
public enum LoadKind: String, Equatable, Sendable, Codable {
    case barbell
    case dumbbell
    case machine
    case cable
    /// Eigengewicht, optional mit Zusatzlast (Dips, Pull-ups).
    case bodyweight

    public var defaultStep: WeightStep {
        // Standard sind laut Entscheidung überall 2,5 kg; abweichende Raster
        // werden pro Übung in "Mein Plan" gesetzt.
        WeightStep.standard
    }
}

public struct Exercise: Identifiable, Equatable, Sendable, Codable {
    public let id: String
    public let name: String
    public let muscleGroups: [MuscleGroup]
    public let role: ExerciseRole
    public let loadKind: LoadKind
    /// Kleinste einstellbare Stufe. Standard 2,5 kg, pro Übung änderbar.
    public var weightStep: WeightStep
    /// Bekannte Ersatzübungen. Ein Ersatz ist damit als Ersatz erkennbar und
    /// wird nicht als neue Übung oder als "0 kg" gelesen.
    public let knownAlternatives: [String]

    public init(
        id: String,
        name: String,
        muscleGroups: [MuscleGroup],
        role: ExerciseRole,
        loadKind: LoadKind,
        weightStep: WeightStep = .standard,
        knownAlternatives: [String] = []
    ) {
        self.id = id
        self.name = name
        self.muscleGroups = muscleGroups
        self.role = role
        self.loadKind = loadKind
        self.weightStep = weightStep
        self.knownAlternatives = knownAlternatives
    }

    /// Bei Eigengewichtsübungen ohne Zusatzlast ist Fortschritt nur über
    /// Wiederholungen messbar -- die Empfehlung darf dort keine Stangen-Kilos
    /// vorschlagen.
    public var progressesByRepsOnly: Bool {
        loadKind == .bodyweight
    }
}
