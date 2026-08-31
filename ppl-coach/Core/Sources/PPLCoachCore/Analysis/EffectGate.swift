import Foundation

/// Gemeinsame Hürde für alle Detektoren, die Gruppenmittel vergleichen.
///
/// Eine feste absolute Schwelle allein reicht nicht: bei stark schwankenden
/// Wiederholungen entstehen Zufallsfunde, bei ruhigen Übungen verschluckt eine
/// hohe Schwelle echte Effekte. Deshalb muss ein Effekt **beides** erfüllen --
/// die verständliche Mindestgröße und ein Vielfaches der eigenen Streuung.
public enum EffectGate {
    public static let defaultNoiseMultiple = 1.5

    /// Verlangte Effektgröße für zwei Vergleichsgruppen.
    public static func required(
        minimum: Double,
        groupA: [Double],
        groupB: [Double],
        noiseMultiple: Double = defaultNoiseMultiple
    ) -> Double {
        let scatterA = Metrics.standardDeviation(groupA) ?? 0
        let scatterB = Metrics.standardDeviation(groupB) ?? 0
        return max(minimum, noiseMultiple * max(scatterA, scatterB))
    }

    /// Reicht der beobachtete Effekt?
    public static func passes(
        effect: Double,
        minimum: Double,
        groupA: [Double],
        groupB: [Double],
        noiseMultiple: Double = defaultNoiseMultiple
    ) -> Bool {
        effect >= required(
            minimum: minimum,
            groupA: groupA,
            groupB: groupB,
            noiseMultiple: noiseMultiple
        )
    }
}
