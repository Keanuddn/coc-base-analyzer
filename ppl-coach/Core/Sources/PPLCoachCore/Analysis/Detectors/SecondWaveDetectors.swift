import Foundation

/// Führt ein zu knappes oder zu langes Warm-up zu einem zähen ersten
/// Arbeitssatz?
///
/// Die drei gestaffelten Incline-Warm-ups sind genau dafür gemacht --
/// Abweichungen davon sind sichtbar.
public struct WarmupQualityDetector: Detector {
    public let id = "warmup-quality"
    public let question = "Wirkt sich das Warm-up auf den ersten Arbeitssatz aus?"
    public let minimumSampleSize: Int
    public let repThreshold: Double

    public init(minimumSampleSize: Int = 6, repThreshold: Double = 1.0) {
        self.minimumSampleSize = minimumSampleSize
        self.repThreshold = repThreshold
    }

    public func run(_ input: AnalysisInput) -> DetectorResult {
        let sessions = input.sessions(planVersionID: input.planVersion.id)
        // Paare: Warm-up-Umfang einer Übung gegen den ersten Arbeitssatz.
        var points: [(exerciseID: String, warmupSets: Int, firstWorkReps: Double, date: Date)] = []

        for session in sessions {
            let byExercise = Dictionary(grouping: session.sets) { $0.exerciseID }
            for (exerciseID, sets) in byExercise {
                let warmups = sets.filter { $0.kind == .warmup }
                guard !warmups.isEmpty else { continue }
                guard let firstWork = sets
                    .filter({ $0.countsForPerformance })
                    .min(by: { $0.setIndex < $1.setIndex }) else { continue }
                points.append(
                    (exerciseID, warmups.count, Double(firstWork.reps), session.startedAt)
                )
            }
        }

        let grouped = Dictionary(grouping: points) { $0.exerciseID }
        var best: (finding: Finding, effect: Double)?

        for (exerciseID, entries) in grouped {
            guard entries.count >= minimumSampleSize else { continue }
            let counts = Set(entries.map(\.warmupSets))
            // Ohne Variation im Warm-up-Umfang ist die Frage nicht beantwortbar.
            guard counts.count >= 2 else { continue }

            let full = entries.filter { $0.warmupSets == counts.max() }.map(\.firstWorkReps)
            let short = entries.filter { $0.warmupSets == counts.min() }.map(\.firstWorkReps)
            guard full.count >= 2, short.count >= 2 else { continue }
            guard let fullMean = Metrics.mean(full), let shortMean = Metrics.mean(short) else {
                continue
            }

            let effect = fullMean - shortMean
            guard EffectGate.passes(
                effect: effect,
                minimum: repThreshold,
                groupA: full,
                groupB: short
            ) else { continue }

            let name = input.planVersion.exercise(id: exerciseID)?.name ?? exerciseID
            let finding = Finding(
                id: "\(id)-\(exerciseID)",
                detectorID: id,
                severity: .issue,
                observation: "Bei \(name) startet der erste Arbeitssatz schwächer, wenn das Warm-up kürzer war.",
                likelyCause: "Zu knappes Warm-up vor dieser Übung.",
                ruledOut: ["Andere Übungen -- betrachtet wurde nur diese"],
                evidence: [
                    Evidence(
                        label: "Erster Satz nach vollem Warm-up",
                        value: String(format: "%.1f Wdh.", fullMean),
                        sampleSize: full.count
                    ),
                    Evidence(
                        label: "Erster Satz nach kurzem Warm-up",
                        value: String(format: "%.1f Wdh.", shortMean),
                        sampleSize: short.count
                    )
                ],
                exerciseIDs: [exerciseID],
                limitations: ["Warm-up-Umfang hängt oft mit Zeitdruck zusammen -- das ist hier nicht getrennt."]
            )
            if best == nil || effect > best!.effect { best = (finding, effect) }
        }

        guard let best else {
            return .silent(.notEnoughData(have: points.count, need: minimumSampleSize))
        }
        return .finding(best.finding)
    }
}

/// Was kostet der Superset-Partner?
///
/// Wrist Curls und Shrugs kommen immer direkt nach ihrer Partnerübung. Ob das
/// zu teuer ist, lässt sich beobachten -- sicher belegen aber nur mit einer
/// Probe, die den Superset auflöst.
public struct SupersetPriceDetector: Detector {
    public let id = "superset-price"
    public let question = "Kostet der Superset-Partner messbar Leistung?"
    public let minimumSampleSize: Int
    public let repThreshold: Double

    public init(minimumSampleSize: Int = 6, repThreshold: Double = 1.0) {
        self.minimumSampleSize = minimumSampleSize
        self.repThreshold = repThreshold
    }

    public func run(_ input: AnalysisInput) -> DetectorResult {
        let sessions = input.sessions(planVersionID: input.planVersion.id)

        // Zweite Übung jedes Supersets: Runde 1 gegen die späteren Runden.
        var byExercise: [String: (early: [Double], late: [Double])] = [:]

        for session in sessions {
            let secondMembers = session.sets.filter {
                $0.supersetMember == 1 && $0.countsForPerformance
            }
            for set in secondMembers {
                guard let round = set.supersetRound else { continue }
                var entry = byExercise[set.exerciseID] ?? (early: [], late: [])
                if round == 1 {
                    entry.early.append(Double(set.reps))
                } else {
                    entry.late.append(Double(set.reps))
                }
                byExercise[set.exerciseID] = entry
            }
        }

        var best: (finding: Finding, effect: Double)?

        for (exerciseID, entry) in byExercise {
            let total = entry.early.count + entry.late.count
            guard total >= minimumSampleSize, entry.early.count >= 2, entry.late.count >= 2 else {
                continue
            }
            guard let earlyMean = Metrics.mean(entry.early),
                  let lateMean = Metrics.mean(entry.late) else { continue }

            let effect = earlyMean - lateMean
            guard EffectGate.passes(
                effect: effect,
                minimum: repThreshold,
                groupA: entry.early,
                groupB: entry.late
            ) else { continue }

            let name = input.planVersion.exercise(id: exerciseID)?.name ?? exerciseID
            let finding = Finding(
                id: "\(id)-\(exerciseID)",
                detectorID: id,
                severity: .issue,
                observation: "\(name) verliert über die Superset-Runden deutlich an Wiederholungen.",
                likelyCause: "Der Superset-Partner davor kostet Leistung -- die zweite Übung zahlt den Preis.",
                evidence: [
                    Evidence(
                        label: "Erste Runde",
                        value: String(format: "%.1f Wdh.", earlyMean),
                        sampleSize: entry.early.count
                    ),
                    Evidence(
                        label: "Spätere Runden",
                        value: String(format: "%.1f Wdh.", lateMean),
                        sampleSize: entry.late.count
                    )
                ],
                exerciseIDs: [exerciseID],
                limitations: [
                    "Ein Abfall über Runden ist normal -- ob der Superset selbst zu teuer ist, zeigt erst eine Probe ohne ihn."
                ],
                suggestedVariation: .supersetPairing
            )
            if best == nil || effect > best!.effect { best = (finding, effect) }
        }

        guard let best else {
            return .silent(.notAnsweredWithoutVariation(dimension: .supersetPairing))
        }
        return .finding(best.finding)
    }
}

/// Waren die Lastsprünge zu groß?
///
/// Nach einem großen Sprung landen die Wiederholungen am unteren Rand oder
/// darunter. Kleine Sprünge halten die Progression stabil.
public struct LoadJumpDetector: Detector {
    public let id = "load-jump"
    public let question = "Sind meine Gewichtssprünge zu groß?"
    public let minimumSampleSize: Int

    public init(minimumSampleSize: Int = 3) {
        self.minimumSampleSize = minimumSampleSize
    }

    public func run(_ input: AnalysisInput) -> DetectorResult {
        let sessions = input.sessions(planVersionID: input.planVersion.id)
        var offenders: [(exerciseID: String, jump: Double, reps: Double, count: Int)] = []

        let exerciseIDs = Set(sessions.flatMap(\.workSets).map(\.exerciseID))
        for exerciseID in exerciseIDs {
            guard let exercise = input.planVersion.exercise(id: exerciseID),
                  !exercise.progressesByRepsOnly else { continue }

            let series = sessions.compactMap { session -> (Double, [SetRecord])? in
                let sets = session.sets.filter {
                    $0.exerciseID == exerciseID && $0.countsForPerformance
                }
                guard let first = sets.first else { return nil }
                return (first.weight, sets)
            }
            guard series.count >= 2 else { continue }

            var bigJumps: [(jump: Double, reps: Double)] = []
            for index in 1..<series.count {
                let jump = series[index].0 - series[index - 1].0
                // „Groß“ heißt: mehr als eine Stufe auf einmal.
                guard jump > exercise.weightStep.kilograms else { continue }
                let sets = series[index].1
                guard let meanReps = Metrics.mean(sets.map { Double($0.reps) }) else { continue }
                let missed = sets.contains(where: \.belowLowerBound)
                if missed {
                    bigJumps.append((jump, meanReps))
                }
            }

            guard bigJumps.count >= minimumSampleSize else { continue }
            guard let meanJump = Metrics.mean(bigJumps.map(\.jump)),
                  let meanReps = Metrics.mean(bigJumps.map(\.reps)) else { continue }
            offenders.append((exerciseID, meanJump, meanReps, bigJumps.count))
        }

        guard let worst = offenders.max(by: { $0.count < $1.count }) else {
            return .silent(.notEnoughData(have: offenders.count, need: minimumSampleSize))
        }

        let name = input.planVersion.exercise(id: worst.exerciseID)?.name ?? worst.exerciseID
        return .finding(
            Finding(
                id: "\(id)-\(worst.exerciseID)",
                detectorID: id,
                severity: .issue,
                observation: "Nach größeren Gewichtssprüngen bei \(name) fallen Sätze unter die untere Wiederholungsgrenze.",
                likelyCause: "Die Sprünge sind zu groß -- kleinere Stufen halten die Progression stabil.",
                evidence: [
                    Evidence(
                        label: "Mittlerer Sprung",
                        value: "\(LoadRecommendation.format(worst.jump)) kg",
                        sampleSize: worst.count
                    ),
                    Evidence(
                        label: "Wiederholungen danach",
                        value: String(format: "%.1f", worst.reps),
                        sampleSize: worst.count
                    )
                ],
                exerciseIDs: [worst.exerciseID],
                limitations: ["Ein einzelner Fehlversuch ist normal -- gemeldet wird erst ein Muster."]
            )
        )
    }
}

/// Wird bei hohen Wiederholungen die Bewegungsstrecke verkürzt?
///
/// Beim Wadenheben ist volle Range of Motion ausdrücklich gewollt. Eine kurze
/// Satzdauer bei 12--15 Wiederholungen ist der Verdacht auf Teilwiederholungen.
public struct RangeOfMotionDetector: Detector {
    public let id = "range-of-motion"
    public let question = "Verkürze ich bei hohen Wiederholungen die Bewegung?"
    public let minimumSampleSize: Int
    /// Unter diesem Wert pro Wiederholung wird es verdächtig kurz.
    public let secondsPerRepFloor: Double

    public init(minimumSampleSize: Int = 6, secondsPerRepFloor: Double = 1.4) {
        self.minimumSampleSize = minimumSampleSize
        self.secondsPerRepFloor = secondsPerRepFloor
    }

    public func run(_ input: AnalysisInput) -> DetectorResult {
        let sessions = input.sessions(planVersionID: input.planVersion.id)

        // Nur Übungen mit hoher Wiederholungsvorgabe und vorhandener Dauer.
        let candidates = sessions.flatMap(\.sets).filter { set in
            guard set.countsForPerformance, set.duration != nil else { return false }
            guard let lower = set.targetReps.lowerBound else { return false }
            return lower >= 12
        }

        let grouped = Dictionary(grouping: candidates) { $0.exerciseID }
        var worst: (exerciseID: String, tempo: Double, count: Int)?

        for (exerciseID, sets) in grouped {
            guard sets.count >= minimumSampleSize else { continue }
            let tempos = sets.compactMap(\.secondsPerRep)
            guard let mean = Metrics.mean(tempos), mean < secondsPerRepFloor else { continue }
            if worst == nil || mean < worst!.tempo {
                worst = (exerciseID, mean, tempos.count)
            }
        }

        guard let worst else {
            return .silent(.notEnoughData(have: candidates.count, need: minimumSampleSize))
        }

        let name = input.planVersion.exercise(id: worst.exerciseID)?.name ?? worst.exerciseID
        return .finding(
            Finding(
                id: "\(id)-\(worst.exerciseID)",
                detectorID: id,
                severity: .issue,
                observation: "Bei \(name) brauchst du nur \(String(format: "%.1f", worst.tempo)) s pro Wiederholung.",
                likelyCause: "Verdacht auf Teilwiederholungen -- bei hoher Wiederholungszahl gehört die volle Bewegungsstrecke dazu.",
                evidence: [
                    Evidence(
                        label: "Sekunden pro Wiederholung",
                        value: String(format: "%.1f s", worst.tempo),
                        sampleSize: worst.count
                    ),
                    Evidence(
                        label: "Schwelle",
                        value: String(format: "%.1f s", secondsPerRepFloor),
                        sampleSize: worst.count
                    )
                ],
                exerciseIDs: [worst.exerciseID],
                limitations: ["Ein schnelles Tempo kann auch Absicht sein -- die App kann die Bewegung nicht sehen."]
            )
        )
    }
}

/// Pull-ups als Frische-Barometer.
///
/// Erste schwere Übung am Pull-Tag mit maximalen Wiederholungen. Ein Einbruch
/// hier bei sonst normalem Volumen deutet auf Tagesform, nicht auf einen
/// Planfehler. Stabile Pull-ups bei schwachen Isolationsübungen danach deuten
/// umgekehrt auf Vorermüdung hinten im Tag.
public struct FreshnessBarometerDetector: Detector {
    public let id = "freshness-barometer"
    public let question = "Sagen die Pull-ups etwas über die Tagesform?"
    public let minimumSampleSize: Int
    public let repThreshold: Double

    public init(minimumSampleSize: Int = 5, repThreshold: Double = 1.5) {
        self.minimumSampleSize = minimumSampleSize
        self.repThreshold = repThreshold
    }

    public func run(_ input: AnalysisInput) -> DetectorResult {
        let pullSessions = input.sessions(day: .pull)
            .filter { $0.planVersionID == input.planVersion.id }

        var points: [(pullUpReps: Double, laterIsolationReps: Double)] = []

        for session in pullSessions {
            let pullUps = session.sets.filter {
                $0.exerciseID == DefaultPlan.ID.pullUp && $0.countsForPerformance
            }
            guard let pullMean = Metrics.mean(pullUps.map { Double($0.reps) }) else { continue }

            // Isolationsübungen in der zweiten Hälfte des Tages.
            let isolationIDs = session.exercises.compactMap { record -> String? in
                guard let id = record.effectiveExerciseID,
                      let exercise = input.planVersion.exercise(id: id),
                      exercise.role == .isolation else { return nil }
                return id
            }
            let isolationSets = session.sets.filter {
                isolationIDs.contains($0.exerciseID) && $0.countsForPerformance
            }
            guard let isolationMean = Metrics.mean(isolationSets.map { Double($0.reps) }) else {
                continue
            }
            points.append((pullMean, isolationMean))
        }

        guard points.count >= minimumSampleSize else {
            return .silent(.notEnoughData(have: points.count, need: minimumSampleSize))
        }

        let sorted = points.sorted { $0.pullUpReps < $1.pullUpReps }
        let half = sorted.count / 2
        guard half > 0 else {
            return .silent(.notEnoughData(have: points.count, need: minimumSampleSize))
        }

        let weakDays = sorted.prefix(half)
        let strongDays = sorted.suffix(sorted.count - half)
        guard let weakIsolation = Metrics.mean(weakDays.map(\.laterIsolationReps)),
              let strongIsolation = Metrics.mean(strongDays.map(\.laterIsolationReps)) else {
            return .silent(.notEnoughData(have: points.count, need: minimumSampleSize))
        }

        let together = strongIsolation - weakIsolation
        let required = EffectGate.required(
            minimum: repThreshold,
            groupA: weakDays.map(\.laterIsolationReps),
            groupB: strongDays.map(\.laterIsolationReps)
        )

        // Fall 1: Pull-ups und Isolation bewegen sich gemeinsam -- Tagesform.
        if together >= required {
            return .finding(
                Finding(
                    id: "\(id)-day-form",
                    detectorID: id,
                    severity: .observation,
                    observation: "An Tagen mit schwachen Pull-ups sind auch die späteren Armübungen schwächer.",
                    likelyCause: "Tagesform, kein Planfehler. Die ganze Session fällt zusammen ab.",
                    evidence: [
                        Evidence(
                            label: "Armübungen an starken Pull-up-Tagen",
                            value: String(format: "%.1f Wdh.", strongIsolation),
                            sampleSize: strongDays.count
                        ),
                        Evidence(
                            label: "Armübungen an schwachen Pull-up-Tagen",
                            value: String(format: "%.1f Wdh.", weakIsolation),
                            sampleSize: weakDays.count
                        )
                    ],
                    exerciseIDs: [DefaultPlan.ID.pullUp],
                    limitations: ["Sagt nicht, warum die Tagesform schwankt -- dafür ist der Whoop-Kontext da."]
                )
            )
        }

        // Fall 2: Pull-ups stabil, Isolation schwach -- Vorermüdung hinten.
        if abs(together) < repThreshold * 0.5 {
            return .finding(
                Finding(
                    id: "\(id)-late-fatigue",
                    detectorID: id,
                    severity: .observation,
                    observation: "Deine Pull-ups sind stabil, die späteren Armübungen aber unabhängig davon schwach.",
                    likelyCause: "Nicht die Tagesform, sondern die Position im Tag -- vorne bist du frisch, hinten nicht.",
                    evidence: [
                        Evidence(
                            label: "Unterschied der Armübungen",
                            value: String(format: "%.1f Wdh.", abs(together)),
                            sampleSize: points.count
                        )
                    ],
                    exerciseIDs: [DefaultPlan.ID.pullUp],
                    limitations: ["Sicher belegen lässt sich das nur mit einer Probe, die die Reihenfolge ändert."],
                    suggestedVariation: .exerciseOrder
                )
            )
        }

        return .silent(.effectTooSmall(observed: abs(together), threshold: repThreshold))
    }
}
