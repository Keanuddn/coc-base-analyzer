import Foundation

/// Sinken Wiederholungen oder Tempo im Folgesatz, wenn die Pause deutlich unter
/// Soll lag?
///
/// Vergleichsdesign: nur **dieselbe Übung, derselbe Satzindex, dieselbe Last**.
/// Der Satzindex wird geschichtet, weil späte Sätze ohnehin schwächer sind --
/// ohne die Schichtung findet man Ermüdung und nennt sie Pause.
public struct ShortPauseDetector: Detector {
    public let id = "pause-too-short"
    public let question = "Kosten zu kurze Pausen Leistung im nächsten Satz?"
    public let minimumSampleSize: Int
    /// Ab welcher Unterschreitung eine Pause als kurz gilt.
    public let shortfallThreshold: TimeInterval
    /// Mindestunterschied in Wiederholungen, damit es berichtet wird.
    public let repThreshold: Double
    /// Zusätzlich muss der Effekt die eigene Streuung deutlich übersteigen.
    ///
    /// Ohne diese Bedingung meldet der Detektor bei stark schwankenden
    /// Wiederholungen Zufallsfunde -- der Null-Test mit vertauschten Pausen hat
    /// genau das gezeigt. Eine höhere absolute Schwelle wäre der falsche Weg,
    /// weil sie echte Effekte bei ruhigen Übungen verschluckt.
    public let noiseMultiple: Double

    public init(
        minimumSampleSize: Int = 8,
        shortfallThreshold: TimeInterval = 20,
        repThreshold: Double = 1.0,
        noiseMultiple: Double = 1.5
    ) {
        self.minimumSampleSize = minimumSampleSize
        self.shortfallThreshold = shortfallThreshold
        self.repThreshold = repThreshold
        self.noiseMultiple = noiseMultiple
    }

    public func run(_ input: AnalysisInput) -> DetectorResult {
        let sessions = input.sessions(planVersionID: input.planVersion.id)
        let allPairs = PauseEffectExtractor.pairs(in: sessions)
        let sessionStart = Dictionary(
            sessions.map { ($0.id, $0.startedAt) },
            uniquingKeysWith: { first, _ in first }
        )

        // Verhaltensaussagen dürfen markierte Pausen nicht nutzen; von außen
        // verursachte Pausen sind für die Dosis-Wirkung dagegen besonders
        // wertvoll, weil ihre Länge nichts mit der Tagesform zu tun hat.
        let usable = allPairs.filter { $0.reflectsOwnBehaviour || $0.isExogenous }
        guard !usable.isEmpty else {
            return .silent(.notEnoughData(have: 0, need: minimumSampleSize))
        }

        var best: (finding: Finding, effect: Double)?
        var sawUnconfirmed = false

        let grouped = Dictionary(grouping: usable) { $0.exerciseID }
        for (exerciseID, pairs) in grouped {
            let comparison = compare(pairs)
            guard comparison.comparedPairs >= minimumSampleSize else { continue }
            guard let shortMean = comparison.shortMean,
                  let targetMean = comparison.onTargetMean else { continue }

            let effect = targetMean - shortMean
            let requiredEffect = max(repThreshold, noiseMultiple * comparison.scatter)
            guard effect >= requiredEffect else { continue }

            // Bestätigung im zweiten Zeitfenster -- sonst ist es bei ~19
            // parallel geprüften Übungen mit hoher Wahrscheinlichkeit Zufall.
            let outcome = ConfirmationGate.evaluate(
                items: pairs,
                sortKey: { sessionStart[$0.sessionID] ?? .distantPast },
                threshold: requiredEffect,
                effect: { subset in
                    let result = compare(subset)
                    guard result.comparedPairs >= minimumSampleSize / 2,
                          let short = result.shortMean,
                          let target = result.onTargetMean else { return nil }
                    return target - short
                }
            )
            guard let outcome, outcome.confirmed else {
                sawUnconfirmed = true
                continue
            }

            let shortReps = comparison.shortReps
            let onTargetReps = comparison.onTargetReps
            let comparedPairs = comparison.comparedPairs
            let disturbed = comparison.disturbedCount
            let name = input.planVersion.exercise(id: exerciseID)?.name ?? exerciseID
            let finding = Finding(
                id: "\(id)-\(exerciseID)",
                detectorID: id,
                severity: .issue,
                observation: "Bei \(name) fallen die Wiederholungen, wenn die Pause davor deutlich unter der Vorgabe lag.",
                likelyCause: "Die Pause vor dem Satz war zu kurz.",
                ruledOut: [
                    "Ermüdung im Verlauf der Übung -- verglichen wurden nur Sätze mit demselben Satzindex",
                    "Unterschiedliche Last -- verglichen wurden nur Sätze mit demselben Gewicht"
                ],
                evidence: [
                    Evidence(
                        label: "Wiederholungen nach kurzer Pause",
                        value: String(format: "%.1f", shortMean),
                        sampleSize: shortReps.count,
                        disturbedCount: disturbed
                    ),
                    Evidence(
                        label: "Wiederholungen nach Pause im Soll",
                        value: String(format: "%.1f", targetMean),
                        sampleSize: onTargetReps.count
                    ),
                    Evidence(
                        label: "Unterschied",
                        value: String(format: "%.1f Wdh.", effect),
                        sampleSize: comparedPairs
                    )
                ],
                exerciseIDs: [exerciseID],
                muscleGroups: input.planVersion.exercise(id: exerciseID)?.muscleGroups ?? [],
                limitations: ["Sagt nichts über Technik, Ernährung oder Schlaf."]
            )

            if best == nil || effect > best!.effect {
                best = (finding, effect)
            }
        }

        guard let best else {
            if sawUnconfirmed {
                return .silent(.awaitingConfirmationInSecondWindow)
            }
            return .silent(.notEnoughData(have: usable.count, need: minimumSampleSize))
        }
        if best.finding.restsOnlyOnDisturbedEvidence {
            return .silent(.onlyDisturbedEvidence)
        }
        return .finding(best.finding)
    }

    /// Vergleicht kurze gegen soll-konforme Pausen, geschichtet nach Satzindex
    /// und Last. Ohne diese Schichtung findet man Ermüdung und nennt sie Pause.
    private func compare(_ pairs: [PauseEffectPair]) -> Comparison {
        let strata = Dictionary(grouping: pairs) {
            StratumKey(setIndex: $0.setIndex, weight: $0.weight)
        }

        var shortReps: [Double] = []
        var onTargetReps: [Double] = []
        var comparedPairs = 0
        var disturbed = 0

        for (_, stratum) in strata {
            let short = stratum.filter { $0.pauseDeviation <= -shortfallThreshold }
            let onTarget = stratum.filter { $0.pauseDeviation > -shortfallThreshold }
            guard !short.isEmpty, !onTarget.isEmpty else { continue }

            shortReps.append(contentsOf: short.map { Double($0.nextReps) })
            onTargetReps.append(contentsOf: onTarget.map { Double($0.nextReps) })
            comparedPairs += short.count + onTarget.count
            disturbed += stratum.filter { $0.pauseDisturbance != nil }.count
        }

        return Comparison(
            shortReps: shortReps,
            onTargetReps: onTargetReps,
            comparedPairs: comparedPairs,
            disturbedCount: disturbed
        )
    }

    struct Comparison {
        let shortReps: [Double]
        let onTargetReps: [Double]
        let comparedPairs: Int
        let disturbedCount: Int

        var shortMean: Double? { Metrics.mean(shortReps) }
        var onTargetMean: Double? { Metrics.mean(onTargetReps) }

        /// Streuung innerhalb der Vergleichsgruppen. Ein Effekt muss klar
        /// darüber liegen, sonst ist er nicht von Rauschen zu unterscheiden.
        var scatter: Double {
            let shortScatter = Metrics.standardDeviation(shortReps) ?? 0
            let targetScatter = Metrics.standardDeviation(onTargetReps) ?? 0
            return max(shortScatter, targetScatter)
        }
    }

    struct StratumKey: Hashable {
        let setIndex: Int
        let weight: Double
    }
}

/// Wird die Leistung auch schlechter, wenn die Pause deutlich **über** dem Soll
/// liegt? Es gibt ein Fenster -- „länger = besser“ gilt nicht.
public struct LongPauseDetector: Detector {
    public let id = "pause-too-long"
    public let question = "Kostet Auskühlen bei zu langen Pausen Leistung?"
    public let minimumSampleSize: Int
    public let excessThreshold: TimeInterval
    public let repThreshold: Double

    public init(
        minimumSampleSize: Int = 8,
        excessThreshold: TimeInterval = 45,
        repThreshold: Double = 1.0
    ) {
        self.minimumSampleSize = minimumSampleSize
        self.excessThreshold = excessThreshold
        self.repThreshold = repThreshold
    }

    public func run(_ input: AnalysisInput) -> DetectorResult {
        let pairs = PauseEffectExtractor.pairs(in: input.sessions(planVersionID: input.planVersion.id))
            .filter { $0.reflectsOwnBehaviour || $0.isExogenous }

        // Sinnvoll vor allem bei Isolationsübungen mit kurzer Zielpause.
        let candidates = pairs.filter { pair in
            guard let exercise = input.planVersion.exercise(id: pair.exerciseID) else { return false }
            return exercise.role == .isolation
        }

        guard candidates.count >= minimumSampleSize else {
            return .silent(.notEnoughData(have: candidates.count, need: minimumSampleSize))
        }

        let long = candidates.filter { $0.pauseDeviation >= excessThreshold }
        let onTarget = candidates.filter { abs($0.pauseDeviation) < excessThreshold }

        guard !long.isEmpty, !onTarget.isEmpty else {
            return .silent(.notEnoughData(have: min(long.count, onTarget.count), need: 1))
        }
        guard let longMean = Metrics.mean(long.map { Double($0.nextReps) }),
              let targetMean = Metrics.mean(onTarget.map { Double($0.nextReps) }) else {
            return .silent(.notEnoughData(have: candidates.count, need: minimumSampleSize))
        }

        let longReps = long.map { Double($0.nextReps) }
        let targetReps = onTarget.map { Double($0.nextReps) }
        let effect = targetMean - longMean
        let required = EffectGate.required(
            minimum: repThreshold,
            groupA: longReps,
            groupB: targetReps
        )
        guard effect >= required else {
            return .silent(.effectTooSmall(observed: effect, threshold: required))
        }

        let affected = Array(Set(long.map(\.exerciseID))).sorted()
        return .finding(
            Finding(
                id: id,
                detectorID: id,
                severity: .issue,
                observation: "Bei den Isolationsübungen fallen die Wiederholungen auch dann, wenn die Pause deutlich länger war als vorgegeben.",
                likelyCause: "Zu lange Pausen bei kurzen Zielpausen -- der Muskel kühlt aus. Es gibt ein Fenster, nicht nur „länger ist besser“.",
                ruledOut: ["Zu kurze Pausen -- hier wurden ausdrücklich die überlangen betrachtet"],
                evidence: [
                    Evidence(
                        label: "Wiederholungen nach überlanger Pause",
                        value: String(format: "%.1f", longMean),
                        sampleSize: long.count
                    ),
                    Evidence(
                        label: "Wiederholungen bei Pause im Soll",
                        value: String(format: "%.1f", targetMean),
                        sampleSize: onTarget.count
                    )
                ],
                exerciseIDs: affected,
                limitations: ["Gilt nur für Isolationsübungen mit kurzer Zielpause."]
            )
        )
    }
}

/// Schwanken die tatsächlichen Pausen bei derselben Übung stark?
///
/// Nutzt ausschließlich **unmarkierte** Pausen: eine Pause, die durch ein
/// Gespräch lang wurde, ist nicht dein Verhalten.
public struct PauseConsistencyDetector: Detector {
    public let id = "pause-consistency"
    public let question = "Halte ich die Pausen überhaupt gleichmäßig ein?"
    public let minimumSampleSize: Int
    /// Ab welcher Standardabweichung es unruhig wird.
    public let spreadThreshold: Double

    public init(minimumSampleSize: Int = 10, spreadThreshold: Double = 30) {
        self.minimumSampleSize = minimumSampleSize
        self.spreadThreshold = spreadThreshold
    }

    public func run(_ input: AnalysisInput) -> DetectorResult {
        let sessions = input.sessions(planVersionID: input.planVersion.id)
        let sets = sessions.flatMap(\.sets).filter {
            $0.countsForPerformance && $0.pauseDisturbance == nil && $0.actualPause != nil
        }

        let grouped = Dictionary(grouping: sets) { $0.exerciseID }
        var worst: (exerciseID: String, spread: Double, count: Int)?

        for (exerciseID, exerciseSets) in grouped {
            let pauses = exerciseSets.compactMap(\.actualPause)
            guard pauses.count >= minimumSampleSize else { continue }
            guard let spread = Metrics.standardDeviation(pauses) else { continue }
            if worst == nil || spread > worst!.spread {
                worst = (exerciseID, spread, pauses.count)
            }
        }

        guard let worst else {
            return .silent(.notEnoughData(have: sets.count, need: minimumSampleSize))
        }
        guard worst.spread >= spreadThreshold else {
            return .silent(.effectTooSmall(observed: worst.spread, threshold: spreadThreshold))
        }

        let name = input.planVersion.exercise(id: worst.exerciseID)?.name ?? worst.exerciseID
        return .finding(
            Finding(
                id: "\(id)-\(worst.exerciseID)",
                detectorID: id,
                severity: .observation,
                observation: "Die Pausen bei \(name) schwanken stark.",
                likelyCause: "Unruhiger Ablauf an dieser Übung -- dadurch werden die Folgesätze unberechenbar.",
                evidence: [
                    Evidence(
                        label: "Streuung der Pausen",
                        value: String(format: "±%.0f s", worst.spread),
                        sampleSize: worst.count
                    )
                ],
                exerciseIDs: [worst.exerciseID],
                limitations: ["Markierte Störungen sind ausgeschlossen -- die Schwankung ist selbst gewählt."]
            )
        )
    }
}

/// Häufen sich Störungen bei einer bestimmten Übung? Das ist selbst ein Befund:
/// vielleicht ist das Zeitfenster oder das Gerät das Problem.
public struct DisturbanceClusterDetector: Detector {
    public let id = "disturbance-cluster"
    public let question = "Werde ich an einer bestimmten Übung regelmäßig unterbrochen?"
    public let minimumSampleSize: Int
    public let shareThreshold: Double

    public init(minimumSampleSize: Int = 8, shareThreshold: Double = 0.4) {
        self.minimumSampleSize = minimumSampleSize
        self.shareThreshold = shareThreshold
    }

    public func run(_ input: AnalysisInput) -> DetectorResult {
        let sets = input.sessions.flatMap(\.sets).filter(\.isWork)
        let grouped = Dictionary(grouping: sets) { $0.exerciseID }

        var worst: (exerciseID: String, share: Double, count: Int, disturbed: Int)?

        for (exerciseID, exerciseSets) in grouped {
            guard exerciseSets.count >= minimumSampleSize else { continue }
            let disturbed = exerciseSets.filter {
                $0.disturbances.contains { $0.category == .external }
            }.count
            let share = Double(disturbed) / Double(exerciseSets.count)
            if worst == nil || share > worst!.share {
                worst = (exerciseID, share, exerciseSets.count, disturbed)
            }
        }

        guard let worst else {
            return .silent(.notEnoughData(have: sets.count, need: minimumSampleSize))
        }
        guard worst.share >= shareThreshold else {
            return .silent(.effectTooSmall(observed: worst.share, threshold: shareThreshold))
        }

        let name = input.planVersion.exercise(id: worst.exerciseID)?.name ?? worst.exerciseID
        return .finding(
            Finding(
                id: "\(id)-\(worst.exerciseID)",
                detectorID: id,
                severity: .observation,
                observation: "An \(name) wirst du regelmäßig unterbrochen.",
                likelyCause: "Gerät oder Zeitfenster -- nicht dein Training.",
                evidence: [
                    Evidence(
                        label: "Anteil gestörter Sätze",
                        value: String(format: "%.0f %%", worst.share * 100),
                        sampleSize: worst.count,
                        disturbedCount: worst.disturbed
                    )
                ],
                exerciseIDs: [worst.exerciseID],
                limitations: ["Beeinflusst die Auswertung nur indirekt -- die Werte selbst bleiben gültig."]
            )
        )
    }
}
