import XCTest
@testable import PPLCoachCore

final class LoadRecommenderTests: XCTestCase {
    private let recommender = LoadRecommender()
    private let incline = DefaultPlan.exercises.first { $0.id == DefaultPlan.ID.inclinePress }!
    private let curls = DefaultPlan.exercises.first { $0.id == DefaultPlan.ID.bicepCurl }!
    private let pullUps = DefaultPlan.exercises.first { $0.id == DefaultPlan.ID.pullUp }!
    private let target = RepTarget.range(min: 6, max: 10)

    private func session(
        exerciseID: String,
        reps: [Int],
        weight: Double,
        at date: Date = Date(timeIntervalSince1970: 1_000_000),
        botchedIndices: Set<Int> = [],
        kind: SetKind = .work,
        target: RepTarget = .range(min: 6, max: 10)
    ) -> SessionRecord {
        var record = SessionRecord(
            day: .push,
            planVersionID: DefaultPlan.versionID,
            startedAt: date,
            status: .completed
        )
        for (index, value) in reps.enumerated() {
            record.sets.append(
                SetRecord(
                    sessionID: record.id,
                    blockID: "block",
                    exerciseID: exerciseID,
                    setIndex: index + 1,
                    kind: kind,
                    targetReps: target,
                    targetPause: .seconds(120),
                    reps: value,
                    weight: weight,
                    duration: 25,
                    startedAt: date,
                    stoppedAt: date.addingTimeInterval(25),
                    disturbances: botchedIndices.contains(index)
                        ? [DisturbanceMarker(scope: .set, reason: .slipped)]
                        : []
                )
            )
        }
        return record
    }

    // MARK: - Die Kernregel

    func testIncreaseOnlyWhenEverySetReachedUpperBound() {
        let history = [session(exerciseID: incline.id, reps: [10, 10, 10, 10], weight: 80)]
        let result = recommender.recommend(exercise: incline, target: target, history: history)
        XCTAssertEqual(result.direction, .increase)
        XCTAssertEqual(result.weight, 82.5)
        XCTAssertEqual(result.reason, "letztes Mal alle Sätze am oberen Rand")
    }

    /// Der Fall aus der Besprechung: 10 / 11 / 7 bei 6--10 heißt halten.
    func testTenElevenSevenMeansHoldNotIncrease() {
        let history = [session(exerciseID: incline.id, reps: [10, 11, 7], weight: 80)]
        let result = recommender.recommend(exercise: incline, target: target, history: history)
        XCTAssertEqual(result.direction, .hold)
        XCTAssertEqual(result.weight, 80, "kein Aufladen, solange ein Satz zurückbleibt")
        XCTAssertEqual(result.reason, "letztes Mal nicht alle Sätze am oberen Rand")
    }

    func testSetsAboveUpperBoundStillCountAsReached() {
        let history = [session(exerciseID: incline.id, reps: [11, 12, 10], weight: 80)]
        let result = recommender.recommend(exercise: incline, target: target, history: history)
        XCTAssertEqual(result.direction, .increase)
    }

    func testDecreaseOnlyWhenASetFallsBelowLowerBound() {
        let history = [session(exerciseID: incline.id, reps: [8, 7, 5], weight: 80)]
        let result = recommender.recommend(exercise: incline, target: target, history: history)
        XCTAssertEqual(result.direction, .decrease)
        XCTAssertEqual(result.weight, 77.5)
    }

    func testMixedSetsInsideRangeMeanHold() {
        let history = [session(exerciseID: incline.id, reps: [9, 8, 8], weight: 80)]
        let result = recommender.recommend(exercise: incline, target: target, history: history)
        XCTAssertEqual(result.direction, .hold)
        XCTAssertEqual(result.weight, 80)
    }

    func testRecommendationIsNeverEmpty() {
        let result = recommender.recommend(
            exercise: incline,
            target: target,
            history: [],
            fallbackWeight: 60
        )
        XCTAssertEqual(result.direction, .hold)
        XCTAssertEqual(result.weight, 60)
        XCTAssertFalse(result.displayText.isEmpty)
    }

    // MARK: - Am oberen Rand stoppen

    func testRecommendationTellsWhereToStop() {
        let result = recommender.recommend(exercise: incline, target: target, history: [])
        XCTAssertEqual(result.stopAtReps, 10)
    }

    func testMaxExercisesHaveNoStopHint() {
        let result = recommender.recommend(exercise: pullUps, target: .maximum, history: [])
        XCTAssertNil(result.stopAtReps)
    }

    // MARK: - Gewichtsschritte

    func testDumbbellStepIsRespected() {
        let history = [
            session(
                exerciseID: curls.id,
                reps: [12, 12, 12],
                weight: 16,
                target: .range(min: 8, max: 12)
            )
        ]
        let result = recommender.recommend(
            exercise: curls,
            target: .range(min: 8, max: 12),
            history: history
        )
        XCTAssertEqual(result.direction, .increase)
        XCTAssertEqual(result.weight, 18, "Kurzhanteln gehen in 2-kg-Schritten")
    }

    func testMachineRasterNeverProducesUnreachableWeight() {
        var machine = incline
        machine.weightStep = WeightStep(kilograms: 5)
        let history = [session(exerciseID: machine.id, reps: [10, 10, 10], weight: 80)]
        let result = recommender.recommend(exercise: machine, target: target, history: history)
        XCTAssertEqual(result.weight, 85, "kein 82,5 kg an einem 5-kg-Raster")
    }

    // MARK: - Eigengewicht

    func testBodyweightMaxExerciseRecommendsRepsNotKilograms() {
        let history = [
            session(exerciseID: pullUps.id, reps: [9, 8, 7, 7], weight: 0, target: .maximum)
        ]
        let result = recommender.recommend(
            exercise: pullUps,
            target: .maximum,
            history: history
        )
        XCTAssertEqual(result.repsGoal, 8, "eine mehr als der schwächste Satz")
        XCTAssertEqual(result.weight, 0)
        XCTAssertTrue(result.displayText.contains("Wdh."))
    }

    func testBodyweightRangeExerciseSuggestsAddedLoadOnlyAtUpperBound() {
        let dips = DefaultPlan.exercises.first { $0.id == DefaultPlan.ID.dips }!
        let history = [
            session(
                exerciseID: dips.id,
                reps: [12, 12, 12],
                weight: 0,
                target: .range(min: 8, max: 12)
            )
        ]
        let result = recommender.recommend(
            exercise: dips,
            target: .range(min: 8, max: 12),
            history: history
        )
        XCTAssertEqual(result.direction, .increase)
        XCTAssertEqual(result.weight, 2.5, "erst jetzt Zusatzlast")
        XCTAssertEqual(result.reason, "obere Grenze erreicht -- Zusatzlast versuchen")
    }

    // MARK: - Was nicht mitzählt

    func testWarmupSetsDoNotDriveTheRecommendation() {
        let history = [
            session(exerciseID: incline.id, reps: [12, 12], weight: 20, kind: .warmup)
        ]
        let result = recommender.recommend(
            exercise: incline,
            target: target,
            history: history,
            fallbackWeight: 75
        )
        XCTAssertEqual(result.reason, "erste Session mit dieser Übung")
        XCTAssertEqual(result.weight, 75)
    }

    func testBotchedSetsAreIgnored() {
        // Der dritte Satz war vermasselt -- die übrigen erreichten das Ziel.
        let history = [
            session(
                exerciseID: incline.id,
                reps: [10, 10, 3],
                weight: 80,
                botchedIndices: [2]
            )
        ]
        let result = recommender.recommend(exercise: incline, target: target, history: history)
        XCTAssertEqual(result.direction, .increase)
    }

    func testWeightChangeMidExerciseDoesNotDistortTheDecision() {
        var record = session(exerciseID: incline.id, reps: [10, 10], weight: 80)
        // Dritter Satz mit anderer Last -- fließt nicht in die Entscheidung ein.
        record.sets.append(
            SetRecord(
                sessionID: record.id,
                blockID: "block",
                exerciseID: incline.id,
                setIndex: 3,
                kind: .work,
                targetReps: target,
                targetPause: .seconds(120),
                reps: 4,
                weight: 90,
                duration: 20,
                startedAt: record.startedAt,
                stoppedAt: record.startedAt.addingTimeInterval(20)
            )
        )
        let result = recommender.recommend(exercise: incline, target: target, history: [record])
        XCTAssertEqual(result.direction, .increase)
        XCTAssertEqual(result.weight, 82.5)
    }

    func testMostRecentSessionWins() {
        let older = session(
            exerciseID: incline.id,
            reps: [10, 10, 10],
            weight: 80,
            at: Date(timeIntervalSince1970: 1_000_000)
        )
        let newer = session(
            exerciseID: incline.id,
            reps: [7, 7, 7],
            weight: 82.5,
            at: Date(timeIntervalSince1970: 1_600_000)
        )
        let result = recommender.recommend(
            exercise: incline,
            target: target,
            history: [older, newer]
        )
        XCTAssertEqual(result.direction, .hold)
        XCTAssertEqual(result.weight, 82.5)
    }

    // MARK: - Zweiter Satz am selben Tag

    func testSecondSetTodayUsesTodaysWeightNotLastWeeksIncrease() {
        let history = [session(exerciseID: incline.id, reps: [10, 10, 10], weight: 80)]
        let todaySets = [
            SetRecord(
                sessionID: UUID(),
                blockID: "block",
                exerciseID: incline.id,
                setIndex: 1,
                kind: .work,
                targetReps: target,
                targetPause: .seconds(120),
                reps: 9,
                weight: 82.5,
                duration: 26,
                startedAt: Date(),
                stoppedAt: Date()
            )
        ]
        let result = recommender.recommend(
            exercise: incline,
            target: target,
            history: history,
            todaySets: todaySets
        )
        XCTAssertEqual(result.direction, .hold)
        XCTAssertEqual(result.weight, 82.5)
        XCTAssertEqual(result.reason, "heutige Arbeitslast")
    }

    // MARK: - Anzeige

    func testDisplayTextFormatsGermanDecimalComma() {
        let history = [session(exerciseID: incline.id, reps: [10, 10, 10], weight: 80)]
        let result = recommender.recommend(exercise: incline, target: target, history: history)
        XCTAssertEqual(result.displayText, "Empfehlung 82,5 kg")
    }

    // MARK: - Warm-up als Anteil der Arbeitslast

    func testWarmupFiftyPercentOfHeldWorkingWeight() {
        let history = [session(exerciseID: incline.id, reps: [9, 8, 8], weight: 80)]
        let result = recommender.recommend(
            exercise: incline,
            target: target,
            history: history,
            warmupLoadFraction: 0.5
        )
        XCTAssertEqual(result.direction, .hold)
        XCTAssertEqual(result.weight, 40)
        XCTAssertEqual(result.reason, "50 % der Arbeitslast (80 kg)")
        XCTAssertEqual(result.displayText, "Empfehlung 40 kg")
    }

    func testWarmupZeroFractionMeansEmptyBar() {
        let history = [session(exerciseID: incline.id, reps: [9, 8, 8], weight: 80)]
        let result = recommender.recommend(
            exercise: incline,
            target: target,
            history: history,
            warmupLoadFraction: 0
        )
        XCTAssertEqual(result.direction, .hold)
        XCTAssertEqual(result.weight, 0)
        XCTAssertEqual(result.reason, "Warm-up ohne Last")
    }

    func testWarmupSeventyFivePercentOfEightyIsSixty() {
        let history = [session(exerciseID: incline.id, reps: [9, 8, 8], weight: 80)]
        let result = recommender.recommend(
            exercise: incline,
            target: target,
            history: history,
            warmupLoadFraction: 0.75
        )
        XCTAssertEqual(result.direction, .hold)
        XCTAssertEqual(result.weight, 60)
        XCTAssertEqual(result.reason, "75 % der Arbeitslast (80 kg)")
    }

    /// 8 / 8 / 8 liegt in 6--10, wäre aber unter 10--12. Die Warm-up-Spanne
    /// darf die Arbeits-Empfehlung nicht nach unten ziehen.
    func testWarmupFractionUsesWorkTargetNotWarmupRepRange() {
        let history = [session(exerciseID: incline.id, reps: [8, 8, 8], weight: 80)]
        let result = recommender.recommend(
            exercise: incline,
            target: target,
            history: history,
            warmupLoadFraction: 0.5
        )
        XCTAssertEqual(result.weight, 40, "halten bei 80, nicht reduzieren wegen Warm-up 10–12")
        XCTAssertEqual(result.direction, .hold)
    }

    func testBodyweightWarmupWithZeroWorkWeightStaysZero() {
        let history = [
            session(exerciseID: pullUps.id, reps: [9, 8, 7, 7], weight: 0, target: .maximum)
        ]
        let result = recommender.recommend(
            exercise: pullUps,
            target: .maximum,
            history: history,
            warmupLoadFraction: 0
        )
        XCTAssertEqual(result.weight, 0)
        XCTAssertNil(result.repsGoal, "keine Kilogramm-Empfehlung aus 0 kg erfinden")
        XCTAssertEqual(result.reason, "Warm-up ohne Last")
    }

    /// 10/8/9/9 bei 77,5 kg: halten. Warm-up 1 (leer) muss 0 kg sein, nicht 77,5.
    func testEmptyWarmupOfHeldSeventySevenFiveIsZero() {
        let history = [session(exerciseID: incline.id, reps: [10, 8, 9, 9], weight: 77.5)]
        let empty = recommender.recommend(
            exercise: incline,
            target: target,
            history: history,
            warmupLoadFraction: 0
        )
        XCTAssertEqual(empty.weight, 0)
        XCTAssertEqual(empty.displayText, "Empfehlung 0 kg")
        XCTAssertEqual(empty.direction, .hold)

        let half = recommender.recommend(
            exercise: incline,
            target: target,
            history: history,
            warmupLoadFraction: 0.5
        )
        XCTAssertEqual(half.weight, 37.5)

        let threeQuarter = recommender.recommend(
            exercise: incline,
            target: target,
            history: history,
            warmupLoadFraction: 0.75
        )
        XCTAssertEqual(threeQuarter.weight, 57.5)

        let work = recommender.recommend(
            exercise: incline,
            target: target,
            history: history
        )
        XCTAssertEqual(work.weight, 77.5)
        XCTAssertEqual(work.reason, "letztes Mal nicht alle Sätze am oberen Rand")
    }
}
