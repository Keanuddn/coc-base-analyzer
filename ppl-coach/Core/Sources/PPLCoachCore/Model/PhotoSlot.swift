import Foundation

/// Fester Aufnahme-Slot für Verlaufsfotos.
///
/// Ohne benannten Slot und ohne konstante Pose sind Fotos ein Album, kein
/// Verlauf. Die Pose gibt die App vor, damit zwei Bilder überhaupt vergleichbar
/// sind.
public enum PhotoSlot: String, Equatable, Sendable, Codable, CaseIterable {
    case chestFront
    case chestSide
    case tricepsFlexed
    case back
    case bicepsSide
    case legsFront
    case shouldersSide

    public var displayName: String {
        switch self {
        case .chestFront: return "Brust frontal"
        case .chestSide: return "Brust seitlich"
        case .tricepsFlexed: return "Arme (Trizeps) gebeugt"
        case .back: return "Rücken"
        case .bicepsSide: return "Arme (Bizeps) seitlich"
        case .legsFront: return "Beine frontal"
        case .shouldersSide: return "Schultern seitlich"
        }
    }

    /// Anleitung, die vor dem Auslösen angezeigt wird. Gleiche Pose ist die
    /// Voraussetzung für jeden Vergleich.
    public var poseInstruction: String {
        switch self {
        case .chestFront:
            return "Frontal zur Kamera, Arme locker seitlich, Schultern unten, nicht anspannen bis zum Auslösen."
        case .chestSide:
            return "90 Grad zur Seite gedreht, Arm der Kameraseite locker hängen lassen, Blick nach vorn."
        case .tricepsFlexed:
            return "Halb zur Seite gedreht, Arm nach oben gestreckt und hinter dem Kopf gebeugt, Trizeps zur Kamera."
        case .back:
            return "Rücken zur Kamera, Arme locker seitlich, Schulterblätter neutral, nicht spreizen."
        case .bicepsSide:
            return "Halb zur Seite gedreht, Ellbogen 90 Grad, Schulter unten, erst beim Auslöser anspannen."
        case .legsFront:
            return "Frontal, Füße hüftbreit, Gewicht gleichmäßig, Knie gestreckt aber nicht durchgedrückt."
        case .shouldersSide:
            return "Halb zur Seite gedreht, Arme locker hängen, Schultern bewusst tief lassen."
        }
    }

    /// Muskelgruppen, die dieser Slot zeigt. Wird gebraucht, um ein Foto-Urteil
    /// mit den passenden Übungen zu verknüpfen -- nicht mit der ganzen Woche.
    public var muscleGroups: [MuscleGroup] {
        switch self {
        case .chestFront, .chestSide: return [.chest]
        case .tricepsFlexed: return [.triceps]
        case .back: return [.back]
        case .bicepsSide: return [.biceps, .forearms]
        case .legsFront: return [.quads, .hamstrings, .calves]
        case .shouldersSide: return [.shoulders, .traps]
        }
    }
}

/// Hinweise, die immer gleich vor dem Auslösen stehen. Konstanz ist das, was
/// Fotos überhaupt vergleichbar macht.
public enum PhotoProtocolHint {
    public static let all = [
        "Gleicher Ort und gleiches Licht wie beim letzten Mal.",
        "Gleicher Abstand -- richte dich an der Schablone des Vorgängerfotos aus.",
        "Selbstauslöser nutzen, nicht mit ausgestrecktem Arm posieren."
    ]
}
