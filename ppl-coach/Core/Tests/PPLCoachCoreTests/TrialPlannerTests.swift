import XCTest
@testable import PPLCoachCore

final class TrialPlannerTests: XCTestCase {
    private let plan = DefaultPlan.version()
    private let planner = TrialPlanner()

    private func history(weeks: Int = 8, repNoise: Double = 0.4) -> [SessionRecord] {
        var generator = SyntheticHistoryGenerator(
            truth: SyntheticTruth(progressesLoad: false, repNoise: repNoise),
            seed: 101
        )
        return generator.generate(weeks: weeks)
    }

    // MARK: - Schwelle aus der eigenen Streuung

    func testThresholdComesFromOwnScatterNotFromAGutFeeling() throws {
        let sessions = history(repNoise: 1.2)
        let result = planner.plan(
            origin: .detector,
            question: "Bremst die Position im Split die Extensions?",
            intervention: .enforcePause(exerciseIDs: [DefaultPlan.ID.overheadExtension]),
            measuring: DefaultPlan.ID.overheadExtension,
            metric: .reps,
            history: sessions,
            planVersion: plan,
            runningTrials: []
        )
        let trial = try result.get()

        // Bei ±1 Wdh. Streuung muss das Kriterium klar darüber liegen.
        XCTAssertGreaterThan(trial.successThreshold, trial.baselineScatter)
        XCTAssertGreaterThanOrEqual(trial.successThreshold, 1.0)
    }

    func testQuietExerciseGetsTheMinimumThreshold() throws {
        let sessions = history(repNoise: 0.05)
        let trial = try planner.plan(
            origin: .detector,
            question: "Frage",
            intervention: .holdLoad(exerciseIDs: [DefaultPlan.ID.latPulldown]),
            measuring: DefaultPlan.ID.latPulldown,
            metric: .reps,
            history: sessions,
            planVersion: plan,
            runningTrials: []
        ).get()

        XCTAssertEqual(trial.successThreshold, 1.0, accuracy: 0.001)
    }

    func testNoisyDataNeedsMoreSessions() {
        let quiet = planner.sessionCount(forScatter: 0.05, baseline: 10)
        let noisy = planner.sessionCount(forScatter: 2.0, baseline: 10)
        XCTAssertEqual(quiet, 3, "bei ruhigen Werten reichen drei Sessions")
        XCTAssertGreaterThan(noisy, quiet)
        XCTAssertLessThanOrEqual(noisy, 8)
    }

    func testProposalTextSaysWhatHowLongAndWhatCounts() throws {
        let sessions = history()
        let trial = try planner.plan(
            origin: .detector,
            question: "Frage",
            intervention: .swapOrder(
                firstExerciseID: DefaultPlan.ID.cableFly,
                secondExerciseID: DefaultPlan.ID.overheadExtension,
                day: .push
            ),
            measuring: DefaultPlan.ID.overheadExtension,
            metric: .reps,
            history: sessions,
            planVersion: plan,
            runningTrials: []
        ).get()

        let text = trial.proposalText(planVersion: plan)
        XCTAssertTrue(text.contains("tauschen"), "was geändert wird")
        XCTAssertTrue(text.contains("Sessions"), "wie lange")
        XCTAssertTrue(text.contains("Ursache"), "was als Antwort gilt")
    }

    // MARK: - Keine überlappenden Proben

    func testParallelTrialOnTheSameDayIsRejected() throws {
        let sessions = history()
        let running = try planner.plan(
            origin: .detector,
            question: "Erste Frage",
            intervention: .swapOrder(
                firstExerciseID: DefaultPlan.ID.cableFly,
                secondExerciseID: DefaultPlan.ID.overheadExtension,
                day: .push
            ),
            measuring: DefaultPlan.ID.overheadExtension,
            metric: .reps,
            history: sessions,
            planVersion: plan,
            runningTrials: []
        ).get()

        var started = running
        started.status = .running

        let second = planner.plan(
            origin: .detector,
            question: "Zweite Frage am selben Tag",
            intervention: .enforcePause(exerciseIDs: [DefaultPlan.ID.pushdown]),
            measuring: DefaultPlan.ID.pushdown,
            metric: .reps,
            history: sessions,
            planVersion: plan,
            runningTrials: [started]
        )

        guard case let .failure(error) = second else {
            return XCTFail("zwei Variationen am selben Tag machen beide Fragen unbeantwortbar")
        }
        XCTAssertEqual(error, .conflictingTrialRunning(day: .push))
    }

    func testTrialsOnDifferentDaysAreAllowed() throws {
        let sessions = history()
        var running = try planner.plan(
            origin: .detector,
            question: "Push-Frage",
            intervention: .swapOrder(
                firstExerciseID: DefaultPlan.ID.cableFly,
                secondExerciseID: DefaultPlan.ID.overheadExtension,
                day: .push
            ),
            measuring: DefaultPlan.ID.overheadExtension,
            metric: .reps,
            history: sessions,
            planVersion: plan,
            runningTrials: []
        ).get()
        running.status = .running

        let second = planner.plan(
            origin: .detector,
            question: "Legs-Frage",
            intervention: .holdLoad(exerciseIDs: [DefaultPlan.ID.calfRaise]),
            measuring: DefaultPlan.ID.calfRaise,
            metric: .reps,
            history: sessions,
            planVersion: plan,
            runningTrials: [running]
        )
        XCTAssertNoThrow(try second.get())
    }

    func testTwoTrialsOnTheSameExerciseAreRejected() throws {
        let sessions = history()
        var running = try planner.plan(
            origin: .detector,
            question: "Frage",
            intervention: .holdLoad(exerciseIDs: [DefaultPlan.ID.calfRaise]),
            measuring: DefaultPlan.ID.calfRaise,
            metric: .reps,
            history: sessions,
            planVersion: plan,
            runningTrials: []
        ).get()
        running.status = .running

        let second = planner.plan(
            origin: .user,
            question: "Andere Frage, gleiche Übung",
            intervention: .custom(
                description: "Engerer Stand",
                exerciseIDs: [DefaultPlan.ID.calfRaise]
            ),
            measuring: DefaultPlan.ID.calfRaise,
            metric: .secondsPerRep,
            history: sessions,
            planVersion: plan,
            runningTrials: [running]
        )
        guard case .failure = second else {
            return XCTFail("dieselbe Übung darf nicht doppelt unter Probe stehen")
        }
    }

    // MARK: - Freie Probe

    func testUserIdeaIsTreatedWithTheSameRigour() throws {
        let sessions = history()
        let trial = try planner.plan(
            origin: .user,
            question: "Bringt mehr Volumen für die Arme etwas?",
            intervention: .custom(
                description: "Zwei Sätze Hammercurls mehr",
                exerciseIDs: [DefaultPlan.ID.hammerCurl]
            ),
            measuring: DefaultPlan.ID.hammerCurl,
            metric: .reps,
            history: sessions,
            planVersion: plan,
            runningTrials: []
        ).get()

        XCTAssertEqual(trial.origin, .user)
        // Schwelle und Laufzeit kommen trotzdem von der App.
        XCTAssertGreaterThanOrEqual(trial.successThreshold, 1.0)
        XCTAssertGreaterThanOrEqual(trial.sessionCount, 3)
    }

    // MARK: - Ableitung aus einem Befund

    func testProposalIsDerivedFromAFindingThatNeedsVariation() throws {
        // Ein Befund, der ohne Variation offen bleibt: Cable Flies stehen im
        // Plan direkt hinter den Overhead Extensions.
        let finding = Finding(
            id: "pre-fatigue-cable-fly",
            detectorID: "pre-fatigue",
            severity: .issue,
            observation: "Cable Flies laufen schlechter, wenn vorher mehr Volumen lag.",
            likelyCause: "Vorermüdung durch die Position im Tag.",
            evidence: [Evidence(label: "Beleg", value: "1,4 Wdh.", sampleSize: 6)],
            exerciseIDs: [DefaultPlan.ID.cableFly],
            suggestedVariation: .exerciseOrder
        )

        let sessions = history(weeks: 10)
        let proposal = planner.proposal(
            for: finding,
            planVersion: plan,
            history: sessions,
            runningTrials: []
        )
        let trial = try XCTUnwrap(proposal).get()

        XCTAssertEqual(trial.origin, .detector)
        guard case let .swapOrder(first, second, day) = trial.intervention else {
            return XCTFail("erwartet einen Reihenfolge-Tausch, war: \(trial.intervention)")
        }
        XCTAssertEqual(first, DefaultPlan.ID.cableFly)
        XCTAssertEqual(
            second,
            DefaultPlan.ID.overheadExtension,
            "Tauschpartner ist die Übung, die im Plan direkt davor steht"
        )
        XCTAssertEqual(day, .push)
    }

    func testPauseAdherenceFindingBecomesAPauseTrial() throws {
        let finding = Finding(
            id: "pause-too-short-pushdown",
            detectorID: "pause-too-short",
            severity: .issue,
            observation: "Bei Pushdowns fallen die Wiederholungen nach kurzen Pausen.",
            likelyCause: "Die Pause war zu kurz.",
            evidence: [Evidence(label: "Beleg", value: "1,6 Wdh.", sampleSize: 12)],
            exerciseIDs: [DefaultPlan.ID.pushdown],
            suggestedVariation: .pauseAdherence
        )

        let trial = try XCTUnwrap(
            planner.proposal(
                for: finding,
                planVersion: plan,
                history: history(weeks: 10),
                runningTrials: []
            )
        ).get()

        guard case let .enforcePause(ids) = trial.intervention else {
            return XCTFail("erwartet eine Pausen-Probe")
        }
        XCTAssertEqual(ids, [DefaultPlan.ID.pushdown])
        XCTAssertEqual(trial.metric, .reps)
    }

    func testSupersetFindingDissolvesTheRightBlock() throws {
        let finding = Finding(
            id: "superset-price",
            detectorID: "superset-price",
            severity: .issue,
            observation: "Wrist Curls leiden unter dem Superset.",
            likelyCause: "Der Partner kostet Leistung.",
            evidence: [Evidence(label: "Beleg", value: "2 Wdh.", sampleSize: 8)],
            exerciseIDs: [DefaultPlan.ID.wristCurl],
            suggestedVariation: .supersetPairing
        )

        let trial = try XCTUnwrap(
            planner.proposal(
                for: finding,
                planVersion: plan,
                history: history(weeks: 10),
                runningTrials: []
            )
        ).get()

        guard case let .dissolveSuperset(blockID) = trial.intervention else {
            return XCTFail("erwartet das Auflösen eines Supersets")
        }
        XCTAssertEqual(blockID, "pull-5-curls-superset")
    }

    func testFindingWithoutOpenQuestionYieldsNoProposal() {
        let finding = Finding(
            id: "x",
            detectorID: "x",
            severity: .observation,
            observation: "Beobachtung",
            likelyCause: "Ursache",
            evidence: [],
            exerciseIDs: [DefaultPlan.ID.latPulldown]
        )
        XCTAssertNil(
            planner.proposal(
                for: finding,
                planVersion: plan,
                history: history(),
                runningTrials: []
            )
        )
    }

    // MARK: - Auswertung

    func testTrialSucceedsWhenImprovementExceedsThreshold() throws {
        let baseline = history(weeks: 6, repNoise: 0.2)
        var trial = try planner.plan(
            origin: .detector,
            question: "Frage",
            intervention: .enforcePause(exerciseIDs: [DefaultPlan.ID.pushdown]),
            measuring: DefaultPlan.ID.pushdown,
            metric: .reps,
            history: baseline,
            planVersion: plan,
            runningTrials: []
        ).get()
        trial.status = .running

        // Probe-Sessions mit klar mehr Wiederholungen.
        var generator = SyntheticHistoryGenerator(
            truth: SyntheticTruth(progressesLoad: false, repNoise: 0.2),
            seed: 121
        )
        var trialSessions = generator.generate(weeks: 4)
        trialSessions = trialSessions.map { session in
            var copy = session
            copy.trialID = trial.id
            copy.sets = copy.sets.map { set in
                guard set.exerciseID == DefaultPlan.ID.pushdown else { return set }
                return SetRecord(
                    id: set.id,
                    sessionID: set.sessionID,
                    blockID: set.blockID,
                    exerciseID: set.exerciseID,
                    setIndex: set.setIndex,
                    kind: set.kind,
                    targetReps: set.targetReps,
                    targetPause: set.targetPause,
                    reps: set.reps + 3,
                    weight: set.weight,
                    duration: set.duration,
                    startedAt: set.startedAt,
                    stoppedAt: set.stoppedAt,
                    actualPause: set.actualPause
                )
            }
            return copy
        }
        trial.sessionIDs = trialSessions.map(\.id)

        let result = try XCTUnwrap(
            planner.evaluate(trial: trial, history: trialSessions, planVersion: plan)
        )
        XCTAssertTrue(result.succeeded)
        XCTAssertTrue(result.verdict.contains("Hat geholfen"))
        XCTAssertGreaterThan(result.difference, result.threshold)
    }

    func testTrialFailsWhenNothingChanges() throws {
        let baseline = history(weeks: 6, repNoise: 0.2)
        var trial = try planner.plan(
            origin: .detector,
            question: "Frage",
            intervention: .enforcePause(exerciseIDs: [DefaultPlan.ID.pushdown]),
            measuring: DefaultPlan.ID.pushdown,
            metric: .reps,
            history: baseline,
            planVersion: plan,
            runningTrials: []
        ).get()
        trial.status = .running

        var generator = SyntheticHistoryGenerator(
            truth: SyntheticTruth(progressesLoad: false, repNoise: 0.2),
            seed: 131
        )
        var trialSessions = generator.generate(weeks: 4)
        trialSessions = trialSessions.map { session in
            var copy = session
            copy.trialID = trial.id
            return copy
        }
        trial.sessionIDs = trialSessions.map(\.id)

        let result = try XCTUnwrap(
            planner.evaluate(trial: trial, history: trialSessions, planVersion: plan)
        )
        XCTAssertFalse(result.succeeded)
        XCTAssertTrue(result.verdict.contains("Ursache liegt woanders"))
    }

    func testLowerIsBetterForTempoMetric() throws {
        let baseline = history(weeks: 6, repNoise: 0.2)
        var trial = try planner.plan(
            origin: .detector,
            question: "Frage",
            intervention: .holdLoad(exerciseIDs: [DefaultPlan.ID.legPress]),
            measuring: DefaultPlan.ID.legPress,
            metric: .secondsPerRep,
            history: baseline,
            planVersion: plan,
            runningTrials: []
        ).get()
        trial.status = .running

        var generator = SyntheticHistoryGenerator(
            truth: SyntheticTruth(progressesLoad: false, repNoise: 0.2),
            seed: 141
        )
        var trialSessions = generator.generate(weeks: 4)
        trialSessions = trialSessions.map { session in
            var copy = session
            copy.trialID = trial.id
            copy.sets = copy.sets.map { set in
                guard set.exerciseID == DefaultPlan.ID.legPress, let duration = set.duration else {
                    return set
                }
                // Deutlich schneller pro Wiederholung.
                return SetRecord(
                    id: set.id,
                    sessionID: set.sessionID,
                    blockID: set.blockID,
                    exerciseID: set.exerciseID,
                    setIndex: set.setIndex,
                    kind: set.kind,
                    targetReps: set.targetReps,
                    targetPause: set.targetPause,
                    reps: set.reps,
                    weight: set.weight,
                    duration: duration * 0.4,
                    startedAt: set.startedAt,
                    stoppedAt: set.stoppedAt,
                    actualPause: set.actualPause
                )
            }
            return copy
        }
        trial.sessionIDs = trialSessions.map(\.id)

        let result = try XCTUnwrap(
            planner.evaluate(trial: trial, history: trialSessions, planVersion: plan)
        )
        XCTAssertTrue(result.succeeded, "weniger Sekunden pro Wdh. ist eine Verbesserung")
        XCTAssertGreaterThan(result.difference, 0)
    }

    func testCancelledTrialIsNotReadAsAResult() throws {
        let baseline = history(weeks: 6)
        var trial = try planner.plan(
            origin: .detector,
            question: "Frage",
            intervention: .enforcePause(exerciseIDs: [DefaultPlan.ID.pushdown]),
            measuring: DefaultPlan.ID.pushdown,
            metric: .reps,
            history: baseline,
            planVersion: plan,
            runningTrials: []
        ).get()
        trial.status = .cancelled

        XCTAssertNil(
            planner.evaluate(trial: trial, history: baseline, planVersion: plan),
            "eine abgebrochene Probe ist eine offene Frage, kein Nein"
        )
    }

    func testEvaluationNeedsTheFullPlannedNumberOfSessions() throws {
        let baseline = history(weeks: 6, repNoise: 1.5)
        var trial = try planner.plan(
            origin: .detector,
            question: "Frage",
            intervention: .enforcePause(exerciseIDs: [DefaultPlan.ID.pushdown]),
            measuring: DefaultPlan.ID.pushdown,
            metric: .reps,
            history: baseline,
            planVersion: plan,
            runningTrials: []
        ).get()
        trial.status = .running
        // Nur eine einzige Session -- zu wenig.
        let single = baseline.filter { $0.day == .push }.prefix(1).map { session -> SessionRecord in
            var copy = session
            copy.trialID = trial.id
            return copy
        }
        trial.sessionIDs = single.map(\.id)

        XCTAssertNil(planner.evaluate(trial: trial, history: Array(single), planVersion: plan))
    }

    func testBaselineExcludesBadDaysAndTrialSessions() {
        var sessions = history(weeks: 6)
        sessions[0].tag = .badDay
        sessions[1].trialID = UUID()

        let values = planner.baselineValues(
            exerciseID: DefaultPlan.ID.inclinePress,
            metric: .reps,
            sessions: sessions
        )
        let allPushSessions = sessions.filter { $0.day == .push }.count
        XCTAssertLessThan(values.count, allPushSessions + 1)
    }
}
