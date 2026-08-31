import Foundation

/// Wird dieselbe Last über die Wochen langsamer bewegt?
///
/// Die Killer-Metrik des Satz-Timers und der Ersatz für Whoops fehlende Angabe
/// zur Nähe am Muskelversagen: 80 kg × 8 in 22 s ist etwas anderes als 80 kg × 8
/// in 35 s. Die Last kann noch stimmen, während die Qualität kippt.
public struct TempoDriftDetector: Detector {
    public let id = "tempo-drift"
    public let question = "Bewege ich dieselbe Last langsamer als früher?"
    public let minimumSampleSize: Int
    /// Mindestanstieg der Sekunden pro Wiederholung.
    public let secondsPerRepThreshold: Double

    public init(minimumSampleSize: Int = 6, secondsPerRepThreshold: Double = 0.5) {
        self.minimumSampleSize = minimumSampleSize
        self.secondsPerRepThreshold = secondsPerRepThreshold
    }

    public func run(_ input: AnalysisInput) -> DetectorResult {
        let sessions = input.sessions(planVersionID: input.planVersion.id)
        // Nur Sätze mit vorhandener Dauer -- fehlende Dauer ist fehlend, nicht 0.
        let sets = sessions.flatMap(\.sets).filter {
            $0.countsForPerformance && $0.duration != nil
        }

        // Geschichtet nach Übung, Satzindex und Last: gleiches gegen Gleiches.
        let strata = Dictionary(grouping: sets) {
            Stratum(exerciseID: $0.exerciseID, setIndex: $0.setIndex, weight: $0.weight)
        }

        var best: (finding: Finding, effect: Double)?

        for (stratum, group) in strata {
            guard group.count >= minimumSampleSize else { continue }
            let sorted = group.sorted { $0.stoppedAt < $1.stoppedAt }
            let half = sorted.count / 2
            let early = sorted.prefix(half).compactMap(\.secondsPerRep)
            let late = sorted.suffix(sorted.count - half).compactMap(\.secondsPerRep)

            guard let earlyMean = Metrics.mean(early), let lateMean = Metrics.mean(late) else {
                continue
            }
            let effect = lateMean - earlyMean
            guard effect >= secondsPerRepThreshold else { continue }

            let name = input.planVersion.exercise(id: stratum.exerciseID)?.name ?? stratum.exerciseID
            let finding = Finding(
                id: "\(id)-\(stratum.exerciseID)-\(stratum.setIndex)",
                detectorID: id,
                severity: .issue,
                observation: "Bei \(name) brauchst du für dieselbe Last (\(LoadRecommendation.format(stratum.weight)) kg, Satz \(stratum.setIndex)) inzwischen länger pro Wiederholung.",
                likelyCause: "Die Qualität sinkt, bevor die Last kippt -- entweder Vorermüdung oder du kämpfst am Limit.",
                ruledOut: [
                    "Andere Last -- verglichen wurde nur dasselbe Gewicht",
                    "Anderer Satzindex -- verglichen wurde nur derselbe Satz"
                ],
                evidence: [
                    Evidence(
                        label: "Sekunden pro Wdh. früher",
                        value: String(format: "%.1f s", earlyMean),
                        sampleSize: early.count
                    ),
                    Evidence(
                        label: "Sekunden pro Wdh. jetzt",
                        value: String(format: "%.1f s", lateMean),
                        sampleSize: late.count
                    )
                ],
                exerciseIDs: [stratum.exerciseID],
                muscleGroups: input.planVersion.exercise(id: stratum.exerciseID)?.muscleGroups ?? [],
                limitations: [
                    "Langsamer kann auch bewusst kontrollierter heißen -- prüfe es gegen die Wiederholungen."
                ]
            )

            if best == nil || effect > best!.effect {
                best = (finding, effect)
            }
        }

        guard let best else {
            return .silent(.notEnoughData(have: sets.count, need: minimumSampleSize))
        }
        return .finding(best.finding)
    }

    struct Stratum: Hashable {
        let exerciseID: String
        let setIndex: Int
        let weight: Double
    }
}

/// Bricht die Leistung innerhalb einer Übung stark ein?
public struct DropOffDetector: Detector {
    public let id = "drop-off"
    public let question = "Fällt die Leistung vom ersten zum letzten Satz stark ab?"
    public let minimumSampleSize: Int
    /// Mittlerer Wiederholungsverlust, ab dem berichtet wird.
    public let repDropThreshold: Double

    public init(minimumSampleSize: Int = 4, repDropThreshold: Double = 2.5) {
        self.minimumSampleSize = minimumSampleSize
        self.repDropThreshold = repDropThreshold
    }

    public func run(_ input: AnalysisInput) -> DetectorResult {
        let sessions = input.sessions(planVersionID: input.planVersion.id)
        var dropsByExercise: [String: [Double]] = [:]

        for session in sessions {
            let exerciseIDs = Set(session.workSets.map(\.exerciseID))
            for exerciseID in exerciseIDs {
                guard let summary = Metrics.summarize(exerciseID: exerciseID, in: session),
                      let drop = summary.repDropOff,
                      summary.workSets.count >= 3 else { continue }
                dropsByExercise[exerciseID, default: []].append(Double(drop))
            }
        }

        var best: (finding: Finding, effect: Double)?

        for (exerciseID, drops) in dropsByExercise {
            guard drops.count >= minimumSampleSize else { continue }
            guard let average = Metrics.mean(drops), average >= repDropThreshold else { continue }

            let name = input.planVersion.exercise(id: exerciseID)?.name ?? exerciseID
            let finding = Finding(
                id: "\(id)-\(exerciseID)",
                detectorID: id,
                severity: .issue,
                observation: "Bei \(name) verlierst du im Schnitt \(String(format: "%.1f", average)) Wiederholungen vom ersten zum letzten Satz.",
                likelyCause: "Steiler Abfall innerhalb der Übung -- häufig zu kurze Pausen oder Vorermüdung aus der vorherigen Übung, nicht Stagnation der Übung selbst.",
                evidence: [
                    Evidence(
                        label: "Mittlerer Abfall",
                        value: String(format: "%.1f Wdh.", average),
                        sampleSize: drops.count
                    )
                ],
                exerciseIDs: [exerciseID],
                muscleGroups: input.planVersion.exercise(id: exerciseID)?.muscleGroups ?? [],
                limitations: ["Ein gewisser Abfall ist normal -- entscheidend ist die Veränderung über Wochen."]
            )

            if best == nil || average > best!.effect {
                best = (finding, average)
            }
        }

        guard let best else {
            return .silent(.notEnoughData(have: dropsByExercise.count, need: minimumSampleSize))
        }
        return .finding(best.finding)
    }
}

/// Steht eine Übung über Wochen still -- weder mehr Last in der Zielzone noch
/// mehr Wiederholungen bei gleicher Last?
public struct StagnationDetector: Detector {
    public let id = "stagnation"
    public let question = "Steht eine Übung über Wochen still?"
    public let minimumSampleSize: Int

    public init(minimumSampleSize: Int = 4) {
        self.minimumSampleSize = minimumSampleSize
    }

    public func run(_ input: AnalysisInput) -> DetectorResult {
        let sessions = input.sessions(planVersionID: input.planVersion.id)
        guard sessions.count >= minimumSampleSize else {
            return .silent(.notEnoughData(have: sessions.count, need: minimumSampleSize))
        }

        // Ein Planwechsel darf nicht als Stagnation gelesen werden.
        let versions = Set(input.sessions.map(\.planVersionID))
        if versions.count > 1, sessions.count < minimumSampleSize {
            return .silent(.planVersionChanged)
        }

        var stalled: [(exerciseID: String, weight: Double, reps: Double, count: Int)] = []

        let exerciseIDs = Set(sessions.flatMap(\.workSets).map(\.exerciseID))
        for exerciseID in exerciseIDs {
            let series = sessions.compactMap { session -> (Date, Double, Double)? in
                guard let summary = Metrics.summarize(exerciseID: exerciseID, in: session) else {
                    return nil
                }
                let weights = summary.workSets.map(\.weight)
                let reps = summary.workSets.map { Double($0.reps) }
                guard let topWeight = weights.max(), let meanReps = Metrics.mean(reps) else {
                    return nil
                }
                return (session.startedAt, topWeight, meanReps)
            }
            .sorted { $0.0 < $1.0 }

            guard series.count >= minimumSampleSize else { continue }

            let weights = series.map(\.1)
            let reps = series.map(\.2)
            let weightGain = (weights.last ?? 0) - (weights.first ?? 0)
            let repGain = (reps.last ?? 0) - (reps.first ?? 0)

            // Bodyweight-Übungen ohne Zusatzlast nur über Wiederholungen.
            let exercise = input.planVersion.exercise(id: exerciseID)
            if exercise?.progressesByRepsOnly == true, weights.allSatisfy({ $0 == 0 }) {
                if repGain <= 0 {
                    stalled.append((exerciseID, 0, reps.last ?? 0, series.count))
                }
                continue
            }

            if weightGain <= 0 && repGain <= 0 {
                stalled.append((exerciseID, weights.last ?? 0, reps.last ?? 0, series.count))
            }
        }

        guard let first = stalled.sorted(by: { $0.exerciseID < $1.exerciseID }).first else {
            return .silent(.effectTooSmall(observed: 0, threshold: 1))
        }

        let name = input.planVersion.exercise(id: first.exerciseID)?.name ?? first.exerciseID
        let weightText = first.weight > 0
            ? "\(LoadRecommendation.format(first.weight)) kg"
            : "Eigengewicht"

        return .finding(
            Finding(
                id: "\(id)-\(first.exerciseID)",
                detectorID: id,
                severity: .issue,
                observation: "\(name) steht seit \(first.count) Sessions still: weder mehr Last noch mehr Wiederholungen.",
                likelyCause: "Stagnation dieser Übung. Ursache muss in Pause, Position im Split oder Tagesform gesucht werden.",
                ruledOut: [
                    "Warm-ups -- die zählen nicht mit",
                    "Als schlechter Tag markierte Sessions und Proben -- die sind ausgeschlossen"
                ],
                evidence: [
                    Evidence(
                        label: "Aktuelle Arbeitslast",
                        value: weightText,
                        sampleSize: first.count
                    ),
                    Evidence(
                        label: "Mittlere Wiederholungen",
                        value: String(format: "%.1f", first.reps),
                        sampleSize: first.count
                    )
                ],
                exerciseIDs: [first.exerciseID],
                muscleGroups: input.planVersion.exercise(id: first.exerciseID)?.muscleGroups ?? [],
                limitations: [
                    "Sagt nicht, warum. Ernährung und Schlaf sind hier nicht enthalten."
                ]
            )
        )
    }
}

/// Leiden die Übungen am Ende des Tages unter dem, was vorher passiert ist?
///
/// Das ist der Mechanismus hinter „die Arme kommen nicht“: wenn Isolation immer
/// zuletzt steht und vorher viel Volumen liegt, ist die Ursache die Position,
/// nicht die Übung.
public struct PreFatigueDetector: Detector {
    public let id = "pre-fatigue"
    public let question = "Leiden die späten Übungen unter dem bisherigen Volumen?"
    public let minimumSampleSize: Int
    public let repThreshold: Double

    public init(minimumSampleSize: Int = 4, repThreshold: Double = 1.0) {
        self.minimumSampleSize = minimumSampleSize
        self.repThreshold = repThreshold
    }

    public func run(_ input: AnalysisInput) -> DetectorResult {
        let sessions = input.sessions(planVersionID: input.planVersion.id)

        // Isolationsübungen in der zweiten Hälfte des Tages.
        var byExercise: [String: [(volumeBefore: Double, reps: Double)]] = [:]

        for session in sessions {
            let positions = session.exercises
            guard let maxPosition = positions.map(\.positionInSession).max(), maxPosition > 2 else {
                continue
            }

            for record in positions {
                guard let exerciseID = record.effectiveExerciseID,
                      let exercise = input.planVersion.exercise(id: exerciseID),
                      exercise.role == .isolation,
                      Double(record.positionInSession) > Double(maxPosition) / 2,
                      let summary = Metrics.summarize(exerciseID: exerciseID, in: session),
                      let meanReps = Metrics.mean(summary.workSets.map { Double($0.reps) })
                else { continue }

                let volumeBefore = session.volumeBefore(position: record.positionInSession)
                byExercise[exerciseID, default: []].append((volumeBefore, meanReps))
            }
        }

        var best: (finding: Finding, effect: Double)?

        for (exerciseID, points) in byExercise {
            guard points.count >= minimumSampleSize else { continue }
            let sorted = points.sorted { $0.volumeBefore < $1.volumeBefore }
            let half = sorted.count / 2
            guard half > 0 else { continue }

            let lowVolume = sorted.prefix(half).map(\.reps)
            let highVolume = sorted.suffix(sorted.count - half).map(\.reps)
            guard let lowMean = Metrics.mean(lowVolume), let highMean = Metrics.mean(highVolume) else {
                continue
            }

            let effect = lowMean - highMean
            guard effect >= repThreshold else { continue }

            let name = input.planVersion.exercise(id: exerciseID)?.name ?? exerciseID
            let finding = Finding(
                id: "\(id)-\(exerciseID)",
                detectorID: id,
                severity: .issue,
                observation: "\(name) läuft schlechter, wenn vorher in der Session mehr Volumen lag.",
                likelyCause: "Vorermüdung durch die Position im Tag -- nicht die Übung selbst.",
                ruledOut: ["Andere Planversion -- verglichen wurde nur innerhalb derselben"],
                evidence: [
                    Evidence(
                        label: "Wiederholungen bei wenig Vorvolumen",
                        value: String(format: "%.1f", lowMean),
                        sampleSize: lowVolume.count
                    ),
                    Evidence(
                        label: "Wiederholungen bei viel Vorvolumen",
                        value: String(format: "%.1f", highMean),
                        sampleSize: highVolume.count
                    )
                ],
                exerciseIDs: [exerciseID],
                muscleGroups: input.planVersion.exercise(id: exerciseID)?.muscleGroups ?? [],
                limitations: [
                    "Die Reihenfolge selbst variiert nie -- sicher belegen lässt sich das nur mit einer Probe."
                ],
                suggestedVariation: .exerciseOrder
            )

            if best == nil || effect > best!.effect {
                best = (finding, effect)
            }
        }

        guard let best else {
            return .silent(.notAnsweredWithoutVariation(dimension: .exerciseOrder))
        }
        return .finding(best.finding)
    }
}
