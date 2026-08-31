import XCTest
@testable import PPLCoachCore

/// Zwei Sorten Tests pro Detektor:
///
/// 1. **Wahrheit finden:** in synthetischen Daten steckt ein bekannter Effekt --
///    der Detektor muss ihn melden.
/// 2. **Null-Test:** dieselben Daten ohne Effekt oder mit vertauschten Pausen --
///    der Detektor muss **schweigen**. Ein Detektor, der auf Rauschen
///    anspringt, ist kaputt.
final class DetectorTests: XCTestCase {
    private let plan = DefaultPlan.version()

    private func input(_ sessions: [SessionRecord], contexts: [DailyContext] = []) -> AnalysisInput {
        var utc = Calendar(identifier: .gregorian)
        utc.timeZone = TimeZone(secondsFromGMT: 0)!
        return AnalysisInput(
            planVersion: plan,
            sessions: sessions,
            dailyContexts: contexts,
            calendar: utc
        )
    }

    // MARK: - Zu kurze Pause

    func testShortPauseDetectorFindsTheInjectedEffect() {
        var generator = SyntheticHistoryGenerator(
            truth: SyntheticTruth(
                repLossFromShortPause: 2.5,
                shortPauseProbability: 0.45,
                progressesLoad: false,
                repNoise: 0.2
            ),
            seed: 7
        )
        let sessions = generator.generate(weeks: 10)
        let result = ShortPauseDetector().run(input(sessions))

        guard let finding = result.finding else {
            return XCTFail("erwartet einen Befund, war: \(String(describing: result.silenceReason))")
        }
        XCTAssertEqual(finding.detectorID, "pause-too-short")
        XCTAssertTrue(finding.likelyCause.contains("zu kurz"))
        XCTAssertFalse(finding.evidence.isEmpty)
        XCTAssertTrue(
            finding.ruledOut.contains { $0.contains("Satzindex") },
            "die Schichtung nach Satzindex muss als geprüft ausgewiesen sein"
        )
    }

    func testShortPauseDetectorStaysSilentWithoutEffect() {
        var generator = SyntheticHistoryGenerator(
            truth: SyntheticTruth(
                repLossFromShortPause: 0,
                shortPauseProbability: 0.45,
                progressesLoad: false,
                repNoise: 0.3
            ),
            seed: 11
        )
        let sessions = generator.generate(weeks: 10)
        let result = ShortPauseDetector().run(input(sessions))
        XCTAssertNil(result.finding, "ohne eingebauten Effekt darf nichts gemeldet werden")
    }

    /// Der harte Null-Test: Pausen zufällig vertauscht, jeder echte
    /// Zusammenhang zerstört.
    func testShortPauseDetectorStaysSilentOnShuffledPauses() {
        var generator = SyntheticHistoryGenerator(
            truth: SyntheticTruth(
                repLossFromShortPause: 2.5,
                shortPauseProbability: 0.45,
                progressesLoad: false,
                repNoise: 0.2
            ),
            seed: 7
        )
        let sessions = generator.generate(weeks: 10)
        let shuffled = generator.shufflingPauses(in: sessions)
        let result = ShortPauseDetector().run(input(shuffled))
        XCTAssertNil(result.finding, "auf Rauschen muss der Detektor schweigen")
    }

    func testShortPauseDetectorStaysSilentWithTooFewSessions() {
        var generator = SyntheticHistoryGenerator(
            truth: SyntheticTruth(repLossFromShortPause: 3, shortPauseProbability: 0.5),
            seed: 3
        )
        let sessions = generator.generate(weeks: 1)
        let result = ShortPauseDetector().run(input(sessions))
        XCTAssertNil(result.finding)
        if case let .notEnoughData(_, need) = result.silenceReason {
            XCTAssertEqual(need, 8)
        } else {
            XCTFail("erwartet notEnoughData, war: \(String(describing: result.silenceReason))")
        }
    }

    // MARK: - Tempo

    func testTempoDriftDetectorFindsSlowingDownAtSameLoad() {
        var generator = SyntheticHistoryGenerator(
            truth: SyntheticTruth(
                tempoDriftPerWeek: 0.35,
                progressesLoad: false,
                repNoise: 0.2
            ),
            seed: 21
        )
        let sessions = generator.generate(weeks: 10)
        let result = TempoDriftDetector().run(input(sessions))

        guard let finding = result.finding else {
            return XCTFail("erwartet einen Befund, war: \(String(describing: result.silenceReason))")
        }
        XCTAssertTrue(finding.observation.contains("länger pro Wiederholung"))
    }

    func testTempoDriftDetectorStaysSilentWithoutDrift() {
        var generator = SyntheticHistoryGenerator(
            truth: SyntheticTruth(tempoDriftPerWeek: 0, progressesLoad: false, repNoise: 0.2),
            seed: 22
        )
        let sessions = generator.generate(weeks: 10)
        XCTAssertNil(TempoDriftDetector().run(input(sessions)).finding)
    }

    func testMissingSetDurationIsNotReadAsFastSet() {
        var generator = SyntheticHistoryGenerator(
            truth: SyntheticTruth(progressesLoad: false),
            seed: 5
        )
        var sessions = generator.generate(weeks: 8)
        // Alle Dauern entfernen -- fehlend ist fehlend, nicht 0.
        sessions = sessions.map { session in
            var copy = session
            copy.sets = copy.sets.map { set in
                SetRecord(
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
                    duration: nil,
                    startedAt: set.startedAt,
                    stoppedAt: set.stoppedAt,
                    actualPause: set.actualPause
                )
            }
            return copy
        }
        let result = TempoDriftDetector().run(input(sessions))
        XCTAssertNil(result.finding, "ohne Dauern darf kein Tempo-Befund entstehen")
    }

    // MARK: - Drop-off

    func testDropOffDetectorFindsInjectedDecline() {
        var generator = SyntheticHistoryGenerator(
            truth: SyntheticTruth(repLossPerSetIndex: 1.6, progressesLoad: false, repNoise: 0.2),
            seed: 31
        )
        let sessions = generator.generate(weeks: 6)
        guard let finding = DropOffDetector().run(input(sessions)).finding else {
            return XCTFail("erwartet einen Befund")
        }
        XCTAssertTrue(finding.observation.contains("verlierst"))
    }

    func testDropOffDetectorStaysSilentWhenSetsAreStable() {
        var generator = SyntheticHistoryGenerator(
            truth: SyntheticTruth(repLossPerSetIndex: 0, progressesLoad: false, repNoise: 0.2),
            seed: 32
        )
        let sessions = generator.generate(weeks: 6)
        XCTAssertNil(DropOffDetector().run(input(sessions)).finding)
    }

    // MARK: - Stagnation

    func testStagnationDetectorFindsFlatProgress() {
        var generator = SyntheticHistoryGenerator(
            truth: SyntheticTruth(progressesLoad: false, repNoise: 0.1),
            seed: 41
        )
        let sessions = generator.generate(weeks: 8)
        guard let finding = StagnationDetector().run(input(sessions)).finding else {
            return XCTFail("erwartet einen Befund")
        }
        XCTAssertTrue(finding.observation.contains("still"))
        XCTAssertTrue(
            finding.limitations.contains { $0.contains("Ernährung") },
            "die Grenze der Aussage muss benannt sein"
        )
    }

    func testStagnationDetectorStaysSilentWhenLoadIncreases() {
        var generator = SyntheticHistoryGenerator(
            truth: SyntheticTruth(progressesLoad: true, repNoise: 0.1),
            seed: 42
        )
        let sessions = generator.generate(weeks: 8)
        XCTAssertNil(StagnationDetector().run(input(sessions)).finding)
    }

    func testStagnationIgnoresBadDaysAndTrials() {
        var generator = SyntheticHistoryGenerator(
            truth: SyntheticTruth(progressesLoad: false, repNoise: 0.1),
            seed: 43
        )
        var sessions = generator.generate(weeks: 8)
        // Alles als schlechter Tag markieren -- damit bleibt nichts vergleichbar.
        sessions = sessions.map { session in
            var copy = session
            copy.tag = .badDay
            return copy
        }
        let result = StagnationDetector().run(input(sessions))
        XCTAssertNil(result.finding)
    }

    func testTrialSessionsAreExcludedFromComparableSessions() {
        var generator = SyntheticHistoryGenerator(seed: 44)
        var sessions = generator.generate(weeks: 4)
        let trialID = UUID()
        sessions[0].trialID = trialID

        let analysisInput = input(sessions)
        XCTAssertEqual(analysisInput.sessions.count, 12)
        XCTAssertEqual(analysisInput.comparableSessions.count, 11)
    }

    // MARK: - Uhrzeit

    func testTimeOfDayStaysSilentWhenTrainingTimeNeverVaries() {
        var generator = SyntheticHistoryGenerator(
            truth: SyntheticTruth(progressesLoad: false),
            seed: 51
        )
        let sessions = generator.generate(weeks: 10, hour: 18)
        let result = TimeOfDayDetector().run(input(sessions))
        XCTAssertNil(result.finding)
        XCTAssertEqual(
            result.silenceReason,
            .notAnsweredWithoutVariation(dimension: .timeOfDay),
            "ohne Variation muss die App das offen sagen statt zu raten"
        )
    }

    func testTimeOfDayFindsEffectWhenTrainingTimeVaries() {
        var generator = SyntheticHistoryGenerator(
            truth: SyntheticTruth(progressesLoad: false, repNoise: 0.2),
            seed: 52
        )
        let sessions = generator.generateWithVaryingTime(weeks: 16, morningRepBonus: 2.0)
        guard let finding = TimeOfDayDetector().run(input(sessions)).finding else {
            return XCTFail("erwartet einen Befund")
        }
        XCTAssertTrue(finding.observation.contains("morgens"))
    }

    // MARK: - Whoop

    func testRecoveryDetectorNeedsCompleteContext() {
        var generator = SyntheticHistoryGenerator(
            truth: SyntheticTruth(progressesLoad: false),
            seed: 61
        )
        let sessions = generator.generate(weeks: 8)
        let pending = generator.dailyContexts(
            for: sessions,
            lowRecoveryEveryOtherSession: true,
            status: .pending
        )
        let result = RecoveryPerformanceDetector().run(input(sessions, contexts: pending))
        XCTAssertNil(result.finding, "unvollständiger Tageskontext darf nicht gerechnet werden")
    }

    func testRecoveryDetectorUsesOnlyFirstSetsAsFreshnessSignal() {
        var generator = SyntheticHistoryGenerator(
            truth: SyntheticTruth(progressesLoad: false, repNoise: 0.2),
            seed: 62
        )
        var sessions = generator.generate(weeks: 10)
        let contexts = generator.dailyContexts(
            for: sessions,
            lowRecoveryEveryOtherSession: true,
            status: .complete
        )

        // Bei niedriger Recovery zwei Wiederholungen abziehen.
        for index in sessions.indices where index.isMultiple(of: 2) {
            sessions[index].sets = sessions[index].sets.map { set in
                SetRecord(
                    id: set.id,
                    sessionID: set.sessionID,
                    blockID: set.blockID,
                    exerciseID: set.exerciseID,
                    setIndex: set.setIndex,
                    kind: set.kind,
                    targetReps: set.targetReps,
                    targetPause: set.targetPause,
                    reps: max(1, set.reps - 2),
                    weight: set.weight,
                    duration: set.duration,
                    startedAt: set.startedAt,
                    stoppedAt: set.stoppedAt,
                    actualPause: set.actualPause
                )
            }
        }

        guard let finding = RecoveryPerformanceDetector()
            .run(input(sessions, contexts: contexts)).finding else {
            return XCTFail("erwartet einen Befund")
        }
        XCTAssertTrue(finding.likelyCause.contains("Tagesform"))
        XCTAssertTrue(finding.ruledOut.contains { $0.contains("erste Arbeitssatz") })
    }

    func testWhoopContextIsMatchedByCycleNotCalendarDay() {
        // Training um 00:30 gehört zum Zyklus, der am Vorabend begann.
        let trainingTime = Date(timeIntervalSince1970: 1_700_000_000)
        let session = SessionRecord(
            day: .push,
            planVersionID: plan.id,
            startedAt: trainingTime,
            status: .completed
        )
        let matching = DailyContext(
            cycleID: "richtig",
            cycleStart: trainingTime.addingTimeInterval(-6 * 3600),
            cycleEnd: trainingTime.addingTimeInterval(6 * 3600),
            status: .complete,
            recoveryScore: 70
        )
        let other = DailyContext(
            cycleID: "falsch",
            cycleStart: trainingTime.addingTimeInterval(6 * 3600),
            cycleEnd: trainingTime.addingTimeInterval(30 * 3600),
            status: .complete,
            recoveryScore: 30
        )

        let found = WhoopContextMapper.context(for: session, in: [other, matching])
        XCTAssertEqual(found?.cycleID, "richtig")
    }

    func testBaselineDeviationIsComputedFromHistory() {
        let start = Date(timeIntervalSince1970: 1_700_000_000)
        let contexts = (0..<10).map { index in
            DailyContext(
                cycleStart: start.addingTimeInterval(Double(index) * 86_400),
                status: .complete,
                recoveryScore: 70,
                hrvMilliseconds: index == 9 ? 40 : 60
            )
        }
        let withBaselines = WhoopContextMapper.withBaselines(contexts)
        // Der letzte Wert liegt 20 ms unter dem Mittel der vorherigen.
        XCTAssertEqual(withBaselines.last?.hrvDeviation ?? 0, -20, accuracy: 0.001)
        // Der erste Wert hat keine Vorgeschichte und damit keine Abweichung.
        XCTAssertNil(withBaselines.first?.hrvDeviation)
    }

    // MARK: - Ernährungs-Schweigeregel

    func testGrowthClaimIsBlockedWhenBodyweightIsFlat() {
        let start = Date(timeIntervalSince1970: 1_700_000_000)
        let records = (0..<8).map { index in
            BodyweightRecord(
                date: start.addingTimeInterval(Double(index) * 7 * 86_400),
                kilograms: 80,
                condition: "morgens"
            )
        }
        let guardRule = GrowthClaimGuard()
        let verdict = guardRule.evaluate(bodyweight: records)
        XCTAssertEqual(verdict, .blocked(.bodyweightFlatOrFalling))
        XCTAssertNotNil(guardRule.explanation(for: verdict))
    }

    func testGrowthClaimAllowedWhenBodyweightRises() {
        let start = Date(timeIntervalSince1970: 1_700_000_000)
        let records = (0..<6).map { index in
            BodyweightRecord(
                date: start.addingTimeInterval(Double(index) * 7 * 86_400),
                kilograms: 80 + Double(index) * 0.4
            )
        }
        let verdict = GrowthClaimGuard().evaluate(bodyweight: records)
        XCTAssertEqual(verdict, .growthPlausible)
    }

    func testGrowthClaimUnknownWithoutEnoughMeasurements() {
        let verdict = GrowthClaimGuard().evaluate(bodyweight: [])
        guard case .unknown = verdict else {
            return XCTFail("ohne Messungen kann nichts gesagt werden")
        }
    }

    // MARK: - Störungen in der Auswertung

    func testBehaviourClaimsIgnoreDisturbedPauses() {
        var generator = SyntheticHistoryGenerator(
            truth: SyntheticTruth(shortPauseProbability: 0.5, progressesLoad: false),
            seed: 71
        )
        var sessions = generator.generate(weeks: 8)
        // Alle Pausen als von außen gestört markieren.
        sessions = sessions.map { session in
            var copy = session
            copy.sets = copy.sets.map { set in
                var updated = set
                updated.disturbances = [
                    DisturbanceMarker(scope: .pause, reason: .conversation)
                ]
                return updated
            }
            return copy
        }

        let result = PauseConsistencyDetector().run(input(sessions))
        XCTAssertNil(
            result.finding,
            "eine Pause, die durch ein Gespräch lang wurde, ist nicht dein Verhalten"
        )
    }

    func testExternalDisturbancesAreMarkedAsExogenousDose() {
        var generator = SyntheticHistoryGenerator(
            truth: SyntheticTruth(shortPauseProbability: 0.5, progressesLoad: false),
            seed: 72
        )
        var sessions = generator.generate(weeks: 2)
        sessions[0].sets[3].disturbances = [
            DisturbanceMarker(scope: .pause, reason: .conversation)
        ]

        let pairs = PauseEffectExtractor.pairs(in: sessions)
        let exogenous = pairs.filter(\.isExogenous)
        XCTAssertFalse(exogenous.isEmpty)
        XCTAssertTrue(exogenous.allSatisfy { !$0.reflectsOwnBehaviour })
    }

    func testDisturbanceClusterIsItselfAFinding() {
        var generator = SyntheticHistoryGenerator(
            truth: SyntheticTruth(progressesLoad: false),
            seed: 73
        )
        var sessions = generator.generate(weeks: 8)
        // An der Kabelstation wird regelmäßig unterbrochen.
        sessions = sessions.map { session in
            var copy = session
            copy.sets = copy.sets.map { set in
                var updated = set
                if set.exerciseID == DefaultPlan.ID.cableFly {
                    updated.disturbances = [
                        DisturbanceMarker(scope: .pause, reason: .equipmentBusy)
                    ]
                }
                return updated
            }
            return copy
        }

        guard let finding = DisturbanceClusterDetector().run(input(sessions)).finding else {
            return XCTFail("erwartet einen Befund")
        }
        XCTAssertEqual(finding.exerciseIDs, [DefaultPlan.ID.cableFly])
        XCTAssertTrue(finding.likelyCause.contains("Gerät"))
    }

    // MARK: - Planwechsel

    func testSessionsOfOtherPlanVersionsAreNotCompared() {
        var generator = SyntheticHistoryGenerator(
            truth: SyntheticTruth(progressesLoad: false, repNoise: 0.1),
            seed: 81
        )
        var sessions = generator.generate(weeks: 8)
        // Die Hälfte gehört zu einer anderen Planversion.
        for index in sessions.indices where index < sessions.count / 2 {
            sessions[index] = SessionRecord(
                id: sessions[index].id,
                day: sessions[index].day,
                planVersionID: "andere-version",
                startedAt: sessions[index].startedAt,
                endedAt: sessions[index].endedAt,
                status: .completed,
                readiness: sessions[index].readiness,
                tag: sessions[index].tag,
                sets: sessions[index].sets,
                exercises: sessions[index].exercises
            )
        }

        let analysisInput = input(sessions)
        let currentVersion = analysisInput.sessions(planVersionID: plan.id)
        XCTAssertEqual(currentVersion.count, sessions.count - sessions.count / 2)
    }
}
