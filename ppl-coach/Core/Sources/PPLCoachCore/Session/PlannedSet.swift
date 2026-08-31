import Foundation

/// Ein einzelner geführter Schritt des Tages, aus dem Plan flachgeklopft.
///
/// Die Reihenfolge dieser Liste **ist** der geführte Ablauf. Supersets stehen
/// darin abwechselnd (A, B, A, B, ...), damit die Führung Runde für Runde
/// funktioniert und die Pause nur an der zweiten Übung hängt.
public struct PlannedSet: Equatable, Sendable, Identifiable {
    public let id: String
    public let blockID: String
    public let exerciseID: String
    public let setIndex: Int
    public let kind: SetKind
    public let reps: RepTarget
    public let pause: PauseTarget
    public let intensityNote: String?
    public let isOptional: Bool
    /// Anteil der Arbeitslast; nur bei Warm-ups gesetzt. Siehe `SetPrescription`.
    public let loadFraction: Double?
    public let supersetRound: Int?
    public let supersetMember: Int?
    /// Position der Übung in der Session, beginnend bei 1.
    public let positionInSession: Int
    /// Wie viele Sätze diese Übung insgesamt vorsieht (für "Satz 2 von 4").
    public let totalSetsForExercise: Int

    public var isWarmup: Bool { kind == .warmup }
    public var isSupersetFirst: Bool { supersetMember == 0 }

    /// Läuft nach diesem Satz ein Pausen-Timer? Bei Warm-ups und bei der ersten
    /// Übung eines Supersets nicht.
    public var enforcesRest: Bool { pause.enforcesRest }
}

public enum SessionPlanFlattener {
    /// Baut die geführte Satzliste für einen Trainingstag.
    public static func flatten(day: DayTemplate) -> [PlannedSet] {
        var result: [PlannedSet] = []
        var position = 0

        for block in day.blocks {
            switch block {
            case let .single(blockID, exerciseID, sets):
                position += 1
                let workCount = sets.filter { $0.kind == .work }.count
                let warmupCount = sets.filter { $0.kind == .warmup }.count
                var workIndex = 0
                var warmupIndex = 0

                for prescription in sets {
                    let index: Int
                    let total: Int
                    if prescription.kind == .work {
                        workIndex += 1
                        index = workIndex
                        total = workCount
                    } else {
                        warmupIndex += 1
                        index = warmupIndex
                        total = warmupCount
                    }

                    result.append(
                        PlannedSet(
                            id: "\(blockID)-\(prescription.kind.rawValue)-\(index)",
                            blockID: blockID,
                            exerciseID: exerciseID,
                            setIndex: index,
                            kind: prescription.kind,
                            reps: prescription.reps,
                            pause: prescription.pause,
                            intensityNote: prescription.intensityNote,
                            isOptional: prescription.isOptional,
                            loadFraction: prescription.loadFraction,
                            supersetRound: nil,
                            supersetMember: nil,
                            positionInSession: position,
                            totalSetsForExercise: total
                        )
                    )
                }

            case let .superset(blockID, firstID, firstSets, secondID, secondSets):
                // Beide Übungen des Supersets teilen sich eine Position, weil
                // sie als eine Einheit trainiert werden.
                position += 1
                let rounds = max(firstSets.count, secondSets.count)

                for round in 0..<rounds {
                    if round < firstSets.count {
                        let prescription = firstSets[round]
                        result.append(
                            PlannedSet(
                                id: "\(blockID)-a-\(round + 1)",
                                blockID: blockID,
                                exerciseID: firstID,
                                setIndex: round + 1,
                                kind: prescription.kind,
                                reps: prescription.reps,
                                pause: prescription.pause,
                                intensityNote: prescription.intensityNote,
                                isOptional: prescription.isOptional,
                                loadFraction: prescription.loadFraction,
                                supersetRound: round + 1,
                                supersetMember: 0,
                                positionInSession: position,
                                totalSetsForExercise: firstSets.count
                            )
                        )
                    }
                    if round < secondSets.count {
                        let prescription = secondSets[round]
                        result.append(
                            PlannedSet(
                                id: "\(blockID)-b-\(round + 1)",
                                blockID: blockID,
                                exerciseID: secondID,
                                setIndex: round + 1,
                                kind: prescription.kind,
                                reps: prescription.reps,
                                pause: prescription.pause,
                                intensityNote: prescription.intensityNote,
                                isOptional: prescription.isOptional,
                                loadFraction: prescription.loadFraction,
                                supersetRound: round + 1,
                                supersetMember: 1,
                                positionInSession: position,
                                totalSetsForExercise: secondSets.count
                            )
                        )
                    }
                }
            }
        }

        return result
    }
}
