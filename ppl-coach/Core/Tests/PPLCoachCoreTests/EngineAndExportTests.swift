import XCTest
@testable import PPLCoachCore

final class AnalysisEngineTests: XCTestCase {
    private let plan = DefaultPlan.version()

    private func input(
        _ sessions: [SessionRecord],
        bodyweight: [BodyweightRecord] = [],
        contexts: [DailyContext] = []
    ) -> AnalysisInput {
        var utc = Calendar(identifier: .gregorian)
        utc.timeZone = TimeZone(secondsFromGMT: 0)!
        return AnalysisInput(
            planVersion: plan,
            sessions: sessions,
            dailyContexts: contexts,
            bodyweight: bodyweight,
            calendar: utc
        )
    }

    func testDetectorCatalogIsFixedAndKnown() {
        let ids = AnalysisEngine.defaultDetectors.map(\.id)
        XCTAssertEqual(Set(ids).count, ids.count, "keine doppelten Detektoren")
        XCTAssertTrue(ids.contains("tempo-drift"))
        XCTAssertTrue(ids.contains("pause-too-short"))
        XCTAssertTrue(ids.contains("stagnation"))
    }

    func testEveryDetectorDeclaresItsQuestionAndSampleSize() {
        for detector in AnalysisEngine.defaultDetectors {
            XCTAssertFalse(detector.question.isEmpty, "\(detector.id) braucht eine Frage")
            XCTAssertGreaterThan(detector.minimumSampleSize, 0, "\(detector.id)")
        }
    }

    func testEngineStaysCompletelySilentOnAnEmptyHistory() {
        let output = AnalysisEngine().run(input([]))
        XCTAssertTrue(output.cards.isEmpty, "ohne Daten wird nichts behauptet")
        XCTAssertEqual(output.silences.count, AnalysisEngine.defaultDetectors.count)
    }

    func testEngineProducesCardsWithEvidenceOnRealPatterns() {
        var generator = SyntheticHistoryGenerator(
            truth: SyntheticTruth(
                repLossFromShortPause: 2.5,
                shortPauseProbability: 0.45,
                progressesLoad: false,
                repNoise: 0.2
            ),
            seed: 201
        )
        let sessions = generator.generate(weeks: 12)
        let output = AnalysisEngine().run(input(sessions))

        XCTAssertFalse(output.cards.isEmpty)
        for card in output.cards {
            XCTAssertFalse(card.headline.isEmpty)
            XCTAssertFalse(card.body.isEmpty)
            XCTAssertFalse(
                card.evidenceLines.isEmpty,
                "jede Behauptung braucht Belege: \(card.id)"
            )
        }
    }

    func testGrowthClaimGuardSuppressesStagnationWhenBodyweightIsFlat() {
        var generator = SyntheticHistoryGenerator(
            truth: SyntheticTruth(progressesLoad: false, repNoise: 0.1),
            seed: 202
        )
        let sessions = generator.generate(weeks: 10)

        let start = sessions[0].startedAt
        let flat = (0..<8).map { index in
            BodyweightRecord(
                date: start.addingTimeInterval(Double(index) * 7 * 86_400),
                kilograms: 80
            )
        }

        let withoutWeight = AnalysisEngine().run(input(sessions))
        let withFlatWeight = AnalysisEngine().run(input(sessions, bodyweight: flat))

        XCTAssertTrue(
            withoutWeight.cards.contains { $0.finding.detectorID == "stagnation" },
            "ohne Gewichtsdaten wird Stagnation gemeldet"
        )
        XCTAssertFalse(
            withFlatWeight.cards.contains { $0.finding.detectorID == "stagnation" },
            "bei flachem Gewicht darf keine Trainingsursache behauptet werden"
        )
        XCTAssertEqual(withFlatWeight.silences["stagnation"], .bodyweightFlatOrFalling)
        XCTAssertNotNil(withFlatWeight.growthNote)
    }

    func testRankerSuppressesDuplicateStories() {
        let pauseFinding = Finding(
            id: "pause",
            detectorID: "pause-too-short",
            severity: .issue,
            observation: "Pause zu kurz",
            likelyCause: "Ursache",
            evidence: [Evidence(label: "x", value: "1", sampleSize: 10)]
        )
        let dropFinding = Finding(
            id: "drop",
            detectorID: "drop-off",
            severity: .issue,
            observation: "Drop-off",
            likelyCause: "Ursache",
            evidence: [Evidence(label: "x", value: "1", sampleSize: 10)]
        )

        let ranked = InsightRanker().rank([dropFinding, pauseFinding])
        XCTAssertEqual(ranked.count, 1)
        XCTAssertEqual(
            ranked.first?.detectorID,
            "pause-too-short",
            "die erklärende Ursache verdrängt das erklärte Symptom"
        )
    }

    func testDampenedDetectorSinksToTheBottom() {
        let a = Finding(
            id: "a",
            detectorID: "tempo-drift",
            severity: .issue,
            observation: "A",
            likelyCause: "A",
            evidence: [Evidence(label: "x", value: "1", sampleSize: 5)]
        )
        let b = Finding(
            id: "b",
            detectorID: "pause-consistency",
            severity: .observation,
            observation: "B",
            likelyCause: "B",
            evidence: [Evidence(label: "x", value: "1", sampleSize: 5)]
        )

        let ranked = InsightRanker(dampenedDetectorIDs: ["tempo-drift"]).rank([a, b])
        XCTAssertEqual(ranked.first?.detectorID, "pause-consistency")
    }

    func testFindingsBasedOnlyOnDisturbedEvidenceAreDropped() {
        let finding = Finding(
            id: "x",
            detectorID: "pause-too-short",
            severity: .issue,
            observation: "Beobachtung",
            likelyCause: "Ursache",
            evidence: [Evidence(label: "x", value: "1", sampleSize: 6, disturbedCount: 6)]
        )
        XCTAssertTrue(InsightRanker().rank([finding]).isEmpty)
    }

    func testCardShowsHowManyEvidenceItemsWereMarked() {
        let finding = Finding(
            id: "x",
            detectorID: "pause-too-short",
            severity: .issue,
            observation: "Beobachtung",
            likelyCause: "Ursache",
            ruledOut: ["Ermüdung"],
            evidence: [Evidence(label: "Belege", value: "1,6 Wdh.", sampleSize: 9, disturbedCount: 2)],
            limitations: ["Ernährung nicht enthalten"]
        )
        let card = CardComposer(planVersion: plan).compose(finding)

        XCTAssertTrue(card.evidenceLines.contains { $0.contains("9 Belege") })
        XCTAssertTrue(card.evidenceLines.contains { $0.contains("2 davon markiert") })
        XCTAssertTrue(card.evidenceLines.contains { $0.contains("ausgeschlossen") })
        XCTAssertTrue(card.evidenceLines.contains { $0.contains("Nicht abgedeckt") })
    }

    func testCardWithOpenQuestionNamesTheMissingVariation() {
        let finding = Finding(
            id: "x",
            detectorID: "pre-fatigue",
            severity: .issue,
            observation: "Beobachtung",
            likelyCause: "Ursache",
            evidence: [Evidence(label: "x", value: "1", sampleSize: 6)],
            suggestedVariation: .exerciseOrder
        )
        let card = CardComposer(planVersion: plan).compose(finding)
        XCTAssertTrue(card.nextStep?.contains("Reihenfolge") == true)
    }

    func testCardWithTrialShowsWhatHowLongAndWhatCounts() throws {
        let sessions = SyntheticHistoryGenerator(
            truth: SyntheticTruth(progressesLoad: false),
            seed: 203
        ).generateCopy(weeks: 8)

        let trial = try TrialPlanner().plan(
            origin: .detector,
            question: "Frage",
            intervention: .enforcePause(exerciseIDs: [DefaultPlan.ID.pushdown]),
            measuring: DefaultPlan.ID.pushdown,
            metric: .reps,
            history: sessions,
            planVersion: plan,
            runningTrials: []
        ).get()

        let finding = Finding(
            id: "x",
            detectorID: "pause-too-short",
            severity: .issue,
            observation: "Beobachtung",
            likelyCause: "Ursache",
            evidence: [Evidence(label: "x", value: "1", sampleSize: 9)],
            exerciseIDs: [DefaultPlan.ID.pushdown]
        )
        let card = CardComposer(planVersion: plan).compose(finding, trial: trial)
        XCTAssertTrue(card.nextStep?.contains("Sessions") == true)
        XCTAssertEqual(card.chartExerciseIDs, [DefaultPlan.ID.pushdown])
    }
}

final class WhoopParsingTests: XCTestCase {
    func testTimezoneOffsetParsing() {
        XCTAssertEqual(WhoopOffsetParser.seconds(from: "+02:00"), 7200)
        XCTAssertEqual(WhoopOffsetParser.seconds(from: "-0500"), -18000)
        XCTAssertEqual(WhoopOffsetParser.seconds(from: "Z"), 0)
        XCTAssertNil(WhoopOffsetParser.seconds(from: nil))
        XCTAssertNil(WhoopOffsetParser.seconds(from: ""))
    }

    func testEndpointBuildsUrlWithPaginationLimit() throws {
        let url = try XCTUnwrap(
            WhoopAPI.Endpoint
                .recoveries(start: nil, end: nil, limit: 100, nextToken: "abc")
                .url()
        )
        let components = try XCTUnwrap(URLComponents(url: url, resolvingAgainstBaseURL: false))
        let items = try XCTUnwrap(components.queryItems)

        XCTAssertTrue(url.path.hasSuffix("/recovery"))
        XCTAssertEqual(
            items.first { $0.name == "limit" }?.value,
            "25",
            "Whoop erlaubt höchstens 25 pro Seite"
        )
        XCTAssertEqual(items.first { $0.name == "nextToken" }?.value, "abc")
    }

    func testScopesCoverEverythingTheAnalysisNeeds() {
        XCTAssertTrue(WhoopAPI.scopes.contains("read:recovery"))
        XCTAssertTrue(WhoopAPI.scopes.contains("read:cycles"))
        XCTAssertTrue(WhoopAPI.scopes.contains("read:sleep"))
        XCTAssertTrue(WhoopAPI.scopes.contains("read:workout"))
    }

    func testContextIsPendingUntilCycleClosedAndRecoveryScored() {
        let now = Date(timeIntervalSince1970: 1_700_100_000)
        let openCycle = WhoopCycle(
            id: "open",
            start: now.addingTimeInterval(-3600),
            end: nil,
            timezoneOffset: "+02:00",
            scoreState: "SCORED",
            score: .init(strain: 12, averageHeartRate: 120, maxHeartRate: 160)
        )
        let recovery = WhoopRecovery(
            cycleID: "open",
            sleepID: "sleep-1",
            scoreState: "SCORED",
            score: .init(
                recoveryScore: 70,
                restingHeartRate: 50,
                hrvRmssdMilli: 65,
                userCalibrating: false
            )
        )

        let contexts = WhoopContextBuilder.build(
            cycles: [openCycle],
            recoveries: [recovery],
            sleeps: [],
            now: now
        )
        XCTAssertEqual(contexts.first?.status, .pending, "offener Zyklus ist noch nicht endgültig")
        XCTAssertFalse(contexts.first?.isUsableForAnalysis ?? true)
    }

    func testContextBecomesCompleteWhenEverythingIsScored() {
        let now = Date(timeIntervalSince1970: 1_700_100_000)
        let closed = WhoopCycle(
            id: "closed",
            start: now.addingTimeInterval(-86_400),
            end: now.addingTimeInterval(-3600),
            timezoneOffset: "+02:00",
            scoreState: "SCORED",
            score: .init(strain: 14, averageHeartRate: 118, maxHeartRate: 158)
        )
        let recovery = WhoopRecovery(
            cycleID: "closed",
            sleepID: "sleep-2",
            scoreState: "SCORED",
            score: .init(
                recoveryScore: 64,
                restingHeartRate: 51,
                hrvRmssdMilli: 58,
                userCalibrating: false
            )
        )
        let sleep = WhoopSleep(
            id: "sleep-2",
            start: now.addingTimeInterval(-90_000),
            end: now.addingTimeInterval(-60_000),
            score: .init(
                sleepPerformancePercentage: 88,
                stageSummary: .init(totalInBedTimeMilli: 27_000_000)
            )
        )

        let context = WhoopContextBuilder.build(
            cycles: [closed],
            recoveries: [recovery],
            sleeps: [sleep],
            now: now
        ).first

        XCTAssertEqual(context?.status, .complete)
        XCTAssertEqual(context?.recoveryScore, 64)
        XCTAssertEqual(context?.sleepPerformancePercentage, 88)
        XCTAssertEqual(context?.sleepDurationSeconds, 27_000)
        XCTAssertEqual(context?.timezoneOffsetSeconds, 7200)
        XCTAssertEqual(context?.recoveryZone, .yellow)
    }

    func testCalibratingRecoveryIsNotTreatedAsUsable() {
        let now = Date(timeIntervalSince1970: 1_700_100_000)
        let closed = WhoopCycle(
            id: "c",
            start: now.addingTimeInterval(-86_400),
            end: now.addingTimeInterval(-3600),
            timezoneOffset: "Z",
            scoreState: "SCORED",
            score: .init(strain: 10, averageHeartRate: 100, maxHeartRate: 140)
        )
        let calibrating = WhoopRecovery(
            cycleID: "c",
            sleepID: nil,
            scoreState: "SCORED",
            score: .init(
                recoveryScore: 50,
                restingHeartRate: 55,
                hrvRmssdMilli: 40,
                userCalibrating: true
            )
        )

        let context = WhoopContextBuilder.build(
            cycles: [closed],
            recoveries: [calibrating],
            sleeps: [],
            now: now
        ).first
        XCTAssertEqual(context?.status, .pending)
    }

    func testRecoveryZones() {
        func zone(_ score: Double) -> DailyContext.RecoveryZone? {
            DailyContext(cycleStart: Date(), recoveryScore: score).recoveryZone
        }
        XCTAssertEqual(zone(80), .green)
        XCTAssertEqual(zone(50), .yellow)
        XCTAssertEqual(zone(20), .red)
    }
}

final class HistoryExportTests: XCTestCase {
    func testRoundTripKeepsEverything() throws {
        var generator = SyntheticHistoryGenerator(seed: 301)
        let sessions = generator.generate(weeks: 3)
        let contexts = generator.dailyContexts(for: sessions)
        let bodyweight = [
            BodyweightRecord(date: sessions[0].startedAt, kilograms: 80.4, condition: "morgens")
        ]
        let photos = [
            PhotoRecord(
                sessionID: sessions[0].id,
                slot: .chestFront,
                takenAt: sessions[0].startedAt,
                fileName: "a.jpg",
                locationNote: "Schlafzimmer, Deckenlicht"
            )
        ]

        let export = HistoryExporter.makeExport(
            planVersions: [DefaultPlan.version()],
            sessions: sessions,
            dailyContexts: contexts,
            bodyweight: bodyweight,
            photos: photos
        )
        let data = try HistoryExporter.encode(export)
        let decoded = try HistoryExporter.decode(data)

        XCTAssertEqual(decoded.sessions.count, sessions.count)
        XCTAssertEqual(decoded.meta.formatVersion, HistoryExporter.formatVersion)
        XCTAssertEqual(decoded.photos.first?.locationNote, "Schlafzimmer, Deckenlicht")
        XCTAssertEqual(decoded.bodyweight.first?.kilograms, 80.4)
        XCTAssertEqual(decoded.dailyContexts.count, contexts.count)
    }

    func testMissingSetDurationStaysEmptyInCsvInsteadOfZero() {
        let now = Date(timeIntervalSince1970: 1_700_000_000)
        var session = SessionRecord(
            day: .push,
            planVersionID: DefaultPlan.versionID,
            startedAt: now,
            status: .completed
        )
        session.sets = [
            SetRecord(
                sessionID: session.id,
                blockID: "b",
                exerciseID: DefaultPlan.ID.inclinePress,
                setIndex: 1,
                kind: .work,
                targetReps: .range(min: 6, max: 10),
                targetPause: .seconds(120),
                reps: 8,
                weight: 80,
                duration: nil,
                startedAt: nil,
                stoppedAt: now,
                actualPause: nil
            )
        ]

        let csv = HistoryExporter.setsCSV(sessions: [session])
        let dataLine = csv.split(separator: "\n")[1]
        let columns = dataLine.split(separator: ";", omittingEmptySubsequences: false)

        // Spalte 9 ist die Satzdauer, Spalte 10 die tatsächliche Pause.
        XCTAssertEqual(columns[8], "", "fehlende Dauer darf nicht als 0 erscheinen")
        XCTAssertEqual(columns[9], "")
        XCTAssertEqual(columns[6], "80")
        XCTAssertEqual(columns[7], "8")
    }

    func testCsvIncludesDisturbanceMarkers() {
        let now = Date(timeIntervalSince1970: 1_700_000_000)
        var session = SessionRecord(
            day: .push,
            planVersionID: DefaultPlan.versionID,
            startedAt: now,
            status: .completed
        )
        session.sets = [
            SetRecord(
                sessionID: session.id,
                blockID: "b",
                exerciseID: DefaultPlan.ID.cableFly,
                setIndex: 1,
                kind: .work,
                targetReps: .range(min: 12, max: 15),
                targetPause: .seconds(60),
                reps: 13,
                weight: 25,
                duration: 30,
                startedAt: now,
                stoppedAt: now.addingTimeInterval(30),
                actualPause: 240,
                disturbances: [DisturbanceMarker(scope: .pause, reason: .conversation)]
            )
        ]

        let csv = HistoryExporter.setsCSV(sessions: [session])
        XCTAssertTrue(csv.contains("pause:conversation"))
        XCTAssertTrue(csv.contains("240"), "der Messwert bleibt erhalten")
    }
}

// MARK: - Testhilfe

extension SyntheticHistoryGenerator {
    /// Bequemer Zugriff für Tests, die den Generator nicht als `var` halten.
    func generateCopy(weeks: Int) -> [SessionRecord] {
        var copy = self
        return copy.generate(weeks: weeks)
    }
}
