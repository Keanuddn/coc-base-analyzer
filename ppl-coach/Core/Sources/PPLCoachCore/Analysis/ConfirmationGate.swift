import Foundation

/// „Zweimal, dann reden.“
///
/// Ein Detektor prüft dieselbe Frage über viele Übungen und nimmt den stärksten
/// Treffer. Bei ~19 Übungen ist ein Zufallsfund damit praktisch garantiert --
/// genau das hat der Null-Test mit vertauschten Pausen gezeigt.
///
/// Die Gegenmaßnahme ist keine höhere Schwelle (die würde echte Effekte
/// verschlucken), sondern **Bestätigung in einem zweiten Zeitfenster**: der
/// Effekt muss in der früheren *und* in der späteren Hälfte der Daten
/// vorhanden sein, mit gleichem Vorzeichen und jeweils über der Schwelle.
/// Ein Zufall überlebt das selten, ein echter Zusammenhang schon.
public enum ConfirmationGate {
    public struct Outcome: Equatable, Sendable {
        /// Effekt über alle Daten -- die Zahl, die in der Karte steht.
        public let overallEffect: Double
        public let earlyEffect: Double
        public let lateEffect: Double
        public let confirmed: Bool
    }

    /// Teilt eine zeitlich sortierbare Menge in zwei Fenster und prüft, ob der
    /// Effekt in beiden auftritt.
    ///
    /// - Parameters:
    ///   - items: Datenpunkte.
    ///   - sortKey: Zeitstempel je Datenpunkt.
    ///   - threshold: Mindesteffekt, in verständlichen Einheiten.
    ///   - effect: Berechnet den Effekt für eine Teilmenge, oder nil wenn zu
    ///     wenig Daten vorliegen.
    public static func evaluate<Item>(
        items: [Item],
        sortKey: (Item) -> Date,
        threshold: Double,
        effect: ([Item]) -> Double?
    ) -> Outcome? {
        guard let overall = effect(items), overall >= threshold else { return nil }

        let sorted = items.sorted { sortKey($0) < sortKey($1) }
        let split = sorted.count / 2
        guard split > 0, sorted.count - split > 0 else { return nil }

        let early = Array(sorted.prefix(split))
        let late = Array(sorted.suffix(sorted.count - split))

        guard let earlyEffect = effect(early), let lateEffect = effect(late) else {
            return Outcome(
                overallEffect: overall,
                earlyEffect: 0,
                lateEffect: 0,
                confirmed: false
            )
        }

        let confirmed = earlyEffect >= threshold && lateEffect >= threshold
        return Outcome(
            overallEffect: overall,
            earlyEffect: earlyEffect,
            lateEffect: lateEffect,
            confirmed: confirmed
        )
    }
}
