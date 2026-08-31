import Foundation

/// Kleinste Gewichtsstufe, in der eine Übung überhaupt verstellbar ist.
///
/// Standard sind 2,5 kg. Pro Übung frei änderbar, weil Kurzhanteln oft in
/// 1- oder 2-kg-Schritten vorliegen und Maschinen einem 5-kg-Raster folgen.
/// Eine Empfehlung von 82,5 kg ist an einem 5-kg-Raster nicht einstellbar --
/// deshalb wird jede Empfehlung auf eine erreichbare Stufe gerundet.
public struct WeightStep: Equatable, Sendable {
    public static let standard = WeightStep(kilograms: 2.5)

    public let kilograms: Double

    public init(kilograms: Double) {
        precondition(kilograms > 0, "Gewichtsstufe muss größer als 0 sein")
        self.kilograms = kilograms
    }

    /// Rundet auf die nächste erreichbare Stufe. Bei genau mittigem Abstand
    /// wird abgerundet, damit keine Last vorgeschlagen wird, die über dem
    /// liegt, was die Regel hergibt.
    public func snap(_ weight: Double) -> Double {
        guard weight > 0 else { return 0 }
        let steps = (weight / kilograms).rounded(.toNearestOrAwayFromZero)
        let candidate = steps * kilograms
        if abs(candidate - weight) == kilograms / 2 {
            return (steps - 1) * kilograms
        }
        return candidate
    }

    /// Nächste Stufe nach oben, ausgehend von einer erreichbaren Last.
    public func increment(from weight: Double) -> Double {
        snap(weight) + kilograms
    }

    /// Nächste Stufe nach unten, nie unter 0.
    public func decrement(from weight: Double) -> Double {
        max(0, snap(weight) - kilograms)
    }
}
