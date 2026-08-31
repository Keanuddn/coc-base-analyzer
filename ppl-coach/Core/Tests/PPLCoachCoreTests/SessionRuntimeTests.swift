import XCTest
@testable import PPLCoachCore

/// Prüft den Rhythmus, der die ganze App trägt:
/// Satz starten → stoppen → Pause läuft → Eingabe (Timer ausgeblendet) →
/// Pause mit Restzeit wieder da → nächster Satz.
final class SessionRuntimeTests: XCTestCase {
    private let plan = DefaultPlan.version()
    private let start = Date(timeIntervalSince1970: 1_000_000)

    private func makeRuntime(day: TrainingDay = .push) -> SessionRuntime {
        let runtime = SessionRuntime(day: day, planVersion: plan, startedAt: start)
        runtime.setReadiness(.good)
        return runtime
    }

    // MARK: - Reihenfolge des Plans

    func testPushDayStartsWithInclineWarmup() {
        let runtime = makeRuntime()
        guard case let .preview(set) = runtime.phase else {
            return XCTFail("erwartet preview")
        }
        XCTAssertEqual(set.exerciseID, DefaultPlan.ID.inclinePress)
        XCTAssertEqual(set.kind, .warmup)
        XCTAssertEqual(set.setIndex, 1)
    }

    func testCableFliesSitBetweenTheTwoTricepsIsolationExercises() {
        let sets = SessionPlanFlattener.flatten(day: DefaultPlan.pushDay)
        let order = sets.map(\.exerciseID).reduce(into: [String]()) { result, id in
            if result.last != id { result.append(id) }
        }
        let overhead = order.firstIndex(of: DefaultPlan.ID.overheadExtension)
        let flies = order.firstIndex(of: DefaultPlan.ID.cableFly)
        let pushdown = order.firstIndex(of: DefaultPlan.ID.pushdown)
        XCTAssertNotNil(overhead)
        XCTAssertNotNil(flies)
        XCTAssertNotNil(pushdown)
        XCTAssertLessThan(overhead!, flies!)
        XCTAssertLessThan(flies!, pushdown!)
    }

    func testRdlWarmupSitsDirectlyBeforeTheRdlWorkSets() {
        let sets = SessionPlanFlattener.flatten(day: DefaultPlan.legsDay)
        guard let warmupIndex = sets.firstIndex(where: {
            $0.exerciseID == DefaultPlan.ID.romanianDeadlift && $0.kind == .warmup
        }) else {
            return XCTFail("RDL-Warm-up fehlt")
        }
        let next = sets[warmupIndex + 1]
        XCTAssertEqual(next.exerciseID, DefaultPlan.ID.romanianDeadlift)
        XCTAssertEqual(next.kind, .work)
        // Das Warm-up darf nicht am Tagesanfang stehen.
        XCTAssertGreaterThan(warmupIndex, 0)
        XCTAssertEqual(sets[0].exerciseID, DefaultPlan.ID.legPress)
    }

    // MARK: - Timer-Rhythmus

    func testSetTimerNeverStartsOnItsOwn() throws {
        let runtime = makeRuntime()
        // Ohne startSet bleibt es bei preview -- der Weg zur Maschine zählt nicht.
        guard case .preview = runtime.phase else { return XCTFail("erwartet preview") }
        try runtime.startSet(at: start)
        guard case .setRunning = runtime.phase else { return XCTFail("erwartet setRunning") }
    }

    func testSetDurationIsStopMinusStart() throws {
        let runtime = makeRuntime()
        try runtime.startSet(at: start)
        try runtime.stopSet(at: start.addingTimeInterval(22))
        guard case let .logging(context) = runtime.phase else {
            return XCTFail("erwartet logging")
        }
        XCTAssertEqual(context.duration, 22)
    }

    func testRestKeepsRunningDuringInputAndReappearsWithRemainingTime() throws {
        let runtime = makeRuntime(day: .push)
        // Zu den Arbeitssätzen der Incline vorspulen (3 Warm-ups).
        try performSets(runtime, count: 3, from: start)

        guard case let .preview(workSet) = runtime.phase else {
            return XCTFail("erwartet preview des Arbeitssatzes")
        }
        XCTAssertEqual(workSet.kind, .work)
        XCTAssertEqual(workSet.pause.timerTarget, 120)

        var now = start.addingTimeInterval(300)
        try runtime.startSet(at: now)
        now = now.addingTimeInterval(25)
        try runtime.stopSet(at: now)

        // Eingabe dauert 15 Sekunden -- die Pause läuft dabei weiter.
        now = now.addingTimeInterval(15)
        try runtime.submit(SetEntry(reps: 8, weight: 80), at: now)

        guard case let .resting(context) = runtime.phase else {
            return XCTFail("erwartet resting mit Restzeit")
        }
        XCTAssertEqual(context.remaining(at: now), 105, accuracy: 0.001)
        XCTAssertFalse(context.isOver(at: now))
    }

    func testNoSecondRestScreenWhenInputTookLongerThanTheRest() throws {
        let runtime = makeRuntime(day: .push)
        try performSets(runtime, count: 3, from: start)

        var now = start.addingTimeInterval(300)
        try runtime.startSet(at: now)
        now = now.addingTimeInterval(25)
        try runtime.stopSet(at: now)

        // Eingabe dauert länger als die Zielpause von 120 s.
        now = now.addingTimeInterval(150)
        try runtime.submit(SetEntry(reps: 8, weight: 80), at: now)

        guard case .preview = runtime.phase else {
            return XCTFail("erwartet direkt den nächsten Satz")
        }
    }

    func testRestRemainingGoesNegativeAfterTheTarget() throws {
        let runtime = makeRuntime(day: .push)
        try performSets(runtime, count: 3, from: start)

        var now = start.addingTimeInterval(300)
        try runtime.startSet(at: now)
        now = now.addingTimeInterval(25)
        try runtime.stopSet(at: now)
        try runtime.submit(SetEntry(reps: 8, weight: 80), at: now.addingTimeInterval(10))

        guard case let .resting(context) = runtime.phase else {
            return XCTFail("erwartet resting")
        }

        let eightSecondsOver = context.restTargetEnd.addingTimeInterval(8)
        XCTAssertEqual(context.remaining(at: eightSecondsOver), -8, accuracy: 0.001)
        XCTAssertTrue(context.isOver(at: eightSecondsOver))
        guard case .resting = runtime.phase else {
            return XCTFail("Überziehung darf nicht automatisch zum nächsten Satz springen")
        }
    }

    func testRestFinishesIntoPreviewOfNextSet() throws {
        let runtime = makeRuntime(day: .push)
        try performSets(runtime, count: 3, from: start)

        var now = start.addingTimeInterval(300)
        try runtime.startSet(at: now)
        now = now.addingTimeInterval(25)
        try runtime.stopSet(at: now)
        try runtime.submit(SetEntry(reps: 8, weight: 80), at: now.addingTimeInterval(10))

        guard case let .resting(context) = runtime.phase else {
            return XCTFail("erwartet resting")
        }
        let expectedNext = context.nextSet
        try runtime.finishRest()

        guard case let .preview(next) = runtime.phase else {
            return XCTFail("erwartet preview")
        }
        XCTAssertEqual(next.id, expectedNext.id)
    }

    // MARK: - Warm-up

    func testInclineWarmupFractionsFollowTheRamp() {
        let sets = SessionPlanFlattener.flatten(day: DefaultPlan.pushDay)
        let warmups = sets.filter {
            $0.exerciseID == DefaultPlan.ID.inclinePress && $0.isWarmup
        }
        XCTAssertEqual(warmups.map(\.loadFraction), [0, 0.5, 0.75])
    }

    func testLegPressAndRdlWarmupFractions() {
        let sets = SessionPlanFlattener.flatten(day: DefaultPlan.legsDay)
        let press = sets.filter {
            $0.exerciseID == DefaultPlan.ID.legPress && $0.isWarmup
        }
        let rdl = sets.filter {
            $0.exerciseID == DefaultPlan.ID.romanianDeadlift && $0.isWarmup
        }
        XCTAssertEqual(press.map(\.loadFraction), [0.4, 0.55])
        XCTAssertEqual(rdl.map(\.loadFraction), [0.5])
    }

    func testPullUpLockerWarmupIsEmptyBar() {
        let sets = SessionPlanFlattener.flatten(day: DefaultPlan.pullDay)
        let warmup = sets.first {
            $0.exerciseID == DefaultPlan.ID.pullUp && $0.isWarmup
        }
        XCTAssertEqual(warmup?.loadFraction, 0)
    }

    func testSetPrescriptionDecodesWithoutLoadFraction() throws {
        let json = """
        {
          "kind": "warmup",
          "reps": { "range": { "min": 6, "max": 8 } },
          "pause": { "none": {} },
          "intensityNote": "~50 %"
        }
        """.data(using: .utf8)!
        let decoded = try JSONDecoder().decode(SetPrescription.self, from: json)
        XCTAssertNil(decoded.loadFraction, "altes Plan-JSON ohne Feld bleibt ladbar")
        XCTAssertEqual(decoded.kind, .warmup)
    }

    func testStalePlanWithoutLoadFractionFillsInclineRamp() {
        let stale = PlanVersion(
            id: "stale",
            createdAt: Date(timeIntervalSince1970: 0),
            exercises: DefaultPlan.exercises,
            days: [
                DayTemplate(day: .push, blocks: [
                    .single(id: "push-1-incline", exerciseID: DefaultPlan.ID.inclinePress, sets: [
                        .warmup(reps: .range(min: 10, max: 12), note: "leer / leicht"),
                        .warmup(reps: .range(min: 6, max: 8), note: "~50 %"),
                        .warmup(reps: .range(min: 3, max: 4), note: "~75–80 %"),
                        .work(reps: .range(min: 6, max: 10), pause: .range(min: 120, max: 150))
                    ])
                ])
            ]
        )
        XCTAssertEqual(
            SessionPlanFlattener.flatten(day: stale.days[0]).filter(\.isWarmup).map(\.loadFraction),
            [nil, nil, nil] as [Double?]
        )

        let filled = stale.fillingMissingWarmupLoadFractions()
        let sets = SessionPlanFlattener.flatten(day: filled.days[0])
        XCTAssertEqual(
            sets.filter(\.isWarmup).map(\.loadFraction),
            [0, 0.5, 0.75] as [Double?]
        )
        XCTAssertNil(sets.first { !$0.isWarmup }?.loadFraction)
    }

    func testResolvedFractionTreatsExplicitZeroAsEmptyBar() {
        let empty = SessionPlanFlattener.flatten(day: DefaultPlan.pushDay).first {
            $0.exerciseID == DefaultPlan.ID.inclinePress && $0.isWarmup
        }
        XCTAssertEqual(empty?.loadFraction, 0)
        XCTAssertEqual(empty?.resolvedWarmupLoadFraction, 0)

        let work = SessionPlanFlattener.flatten(day: DefaultPlan.pushDay).first {
            $0.exerciseID == DefaultPlan.ID.inclinePress && !$0.isWarmup
        }
        XCTAssertNil(work?.resolvedWarmupLoadFraction)
    }

    func testLeerNoteWithoutStoredFractionResolvesToZero() {
        let day = DayTemplate(day: .push, blocks: [
            .single(id: "custom", exerciseID: DefaultPlan.ID.inclinePress, sets: [
                .warmup(reps: .range(min: 10, max: 12), note: "leer / leicht"),
                .warmup(reps: .range(min: 6, max: 8), note: "~50 %"),
                .warmup(reps: .range(min: 3, max: 4), note: "~75–80 %"),
                .work(reps: .range(min: 6, max: 10), pause: .seconds(120))
            ])
        ])
        let sets = SessionPlanFlattener.flatten(day: day).filter(\.isWarmup)
        XCTAssertEqual(sets.map(\.loadFraction), [nil, nil, nil] as [Double?])
        XCTAssertEqual(sets.map(\.resolvedWarmupLoadFraction), [0, 0.5, 0.75] as [Double?])
    }

    func testFillingDoesNotOverwriteExplicitZero() {
        let stale = PlanVersion(
            id: "custom",
            createdAt: Date(timeIntervalSince1970: 0),
            exercises: DefaultPlan.exercises,
            days: [
                DayTemplate(day: .legs, blocks: [
                    .single(id: "unmatched", exerciseID: DefaultPlan.ID.legPress, sets: [
                        .warmup(reps: .range(min: 10, max: 12), note: "leicht", loadFraction: 0)
                    ])
                ])
            ]
        )
        let filled = stale.fillingMissingWarmupLoadFractions()
        let warmup = SessionPlanFlattener.flatten(day: filled.days[0]).first
        XCTAssertEqual(warmup?.loadFraction, 0)
    }

    func testInferredWarmupFractionsFromNotes() {
        XCTAssertEqual(SetPrescription.inferredWarmupLoadFraction(from: "leer / leicht"), 0)
        XCTAssertEqual(SetPrescription.inferredWarmupLoadFraction(from: "locker"), 0)
        XCTAssertEqual(SetPrescription.inferredWarmupLoadFraction(from: "~50 %"), 0.5)
        XCTAssertEqual(SetPrescription.inferredWarmupLoadFraction(from: "~75–80 %"), 0.75)
        XCTAssertEqual(SetPrescription.inferredWarmupLoadFraction(from: "~50–60 %"), 0.55)
        XCTAssertNil(SetPrescription.inferredWarmupLoadFraction(from: "leicht"))
        XCTAssertNil(SetPrescription.inferredWarmupLoadFraction(from: nil))
    }

    func testWarmupHasNoForcedRest() throws {
        let runtime = makeRuntime(day: .push)
        var now = start
        try runtime.startSet(at: now)
        now = now.addingTimeInterval(30)
        try runtime.stopSet(at: now)

        guard case let .logging(context) = runtime.phase else {
            return XCTFail("erwartet logging")
        }
        XCTAssertNil(context.restTargetEnd, "Warm-up darf keinen Pausenzwang haben")

        try runtime.submit(SetEntry(reps: 12, weight: 20), at: now.addingTimeInterval(5))
        guard case .preview = runtime.phase else {
            return XCTFail("nach dem Warm-up geht es direkt weiter")
        }
    }

    // MARK: - Superset

    func testSupersetAlternatesAndRestsOnlyAfterSecondExercise() {
        let sets = SessionPlanFlattener.flatten(day: DefaultPlan.pullDay)
        let superset = sets.filter { $0.blockID == "pull-5-curls-superset" }

        XCTAssertEqual(superset.count, 6, "3 Runden mit je zwei Übungen")
        XCTAssertEqual(superset[0].exerciseID, DefaultPlan.ID.bicepCurl)
        XCTAssertEqual(superset[1].exerciseID, DefaultPlan.ID.wristCurl)
        XCTAssertEqual(superset[2].exerciseID, DefaultPlan.ID.bicepCurl)

        // Nach den Curls keine Pause, nach den Wrist Curls schon.
        XCTAssertFalse(superset[0].enforcesRest)
        XCTAssertTrue(superset[1].enforcesRest)
        XCTAssertEqual(superset[1].pause.timerTarget, 60)

        // Beide Übungen teilen sich eine Position in der Session.
        XCTAssertEqual(superset[0].positionInSession, superset[1].positionInSession)
        XCTAssertEqual(superset[0].supersetRound, 1)
        XCTAssertEqual(superset[1].supersetRound, 1)
        XCTAssertEqual(superset[2].supersetRound, 2)
    }

    func testSupersetFirstExerciseGoesStraightToSecondWithoutRest() throws {
        let runtime = makeRuntime(day: .pull)
        // Vor bis zum Superset: 1 Warm-up + 4 Pull-ups + 3 Rudern + 3 Pulldown + 3 Pec Deck.
        try performSets(runtime, count: 14, from: start)

        guard case let .preview(curlSet) = runtime.phase else {
            return XCTFail("erwartet preview")
        }
        XCTAssertEqual(curlSet.exerciseID, DefaultPlan.ID.bicepCurl)

        var now = start.addingTimeInterval(3000)
        try runtime.startSet(at: now)
        now = now.addingTimeInterval(30)
        try runtime.stopSet(at: now)
        try runtime.submit(SetEntry(reps: 10, weight: 16), at: now.addingTimeInterval(8))

        guard case let .preview(next) = runtime.phase else {
            return XCTFail("nach Übung A ohne Pause direkt zu B")
        }
        XCTAssertEqual(next.exerciseID, DefaultPlan.ID.wristCurl)
    }

    // MARK: - Fehlende Satzdauer

    func testForgottenSetTimerLeavesDurationMissingNotZero() throws {
        let runtime = makeRuntime()
        // stopSet direkt aus preview: Timer wurde nie gestartet.
        try runtime.stopSet(at: start.addingTimeInterval(40))
        guard case let .logging(context) = runtime.phase else {
            return XCTFail("erwartet logging")
        }
        XCTAssertNil(context.duration)

        try runtime.submit(SetEntry(reps: 12, weight: 20), at: start.addingTimeInterval(45))
        let record = runtime.session.sets[0]
        XCTAssertNil(record.duration, "fehlend darf nicht 0 werden")
        XCTAssertNil(record.secondsPerRep)
    }

    // MARK: - Tatsächliche Pause

    func testActualPauseIsMeasuredUntilTheNextSetStarts() throws {
        let runtime = makeRuntime(day: .push)
        var now = start

        // Warm-up 1
        try runtime.startSet(at: now)
        now = now.addingTimeInterval(30)
        try runtime.stopSet(at: now)
        try runtime.submit(SetEntry(reps: 12, weight: 20), at: now.addingTimeInterval(5))

        // 40 Sekunden später der nächste Satz.
        let nextStart = now.addingTimeInterval(40)
        try runtime.startSet(at: nextStart)
        now = nextStart.addingTimeInterval(25)
        try runtime.stopSet(at: now)
        try runtime.submit(SetEntry(reps: 8, weight: 40), at: now.addingTimeInterval(5))

        runtime.finishEarly(at: now.addingTimeInterval(10))
        let measuredPause = try XCTUnwrap(runtime.session.sets[0].actualPause)
        XCTAssertEqual(measuredPause, 40, accuracy: 0.001)
    }

    // MARK: - Skip und Ersatz

    func testSkippingAnExerciseIsRecordedWithReasonAndNotAsZeroWeight() throws {
        let runtime = makeRuntime(day: .push)
        try performSets(runtime, count: 3, from: start)
        try runtime.skipCurrentExercise(reason: .pain)

        guard case let .preview(next) = runtime.phase else {
            return XCTFail("erwartet nächste Übung")
        }
        XCTAssertEqual(next.exerciseID, DefaultPlan.ID.flatPress)

        runtime.finishEarly(at: start.addingTimeInterval(4000))
        let inclineRecord = runtime.session.exercises.first { $0.blockID == "push-1-incline" }
        XCTAssertEqual(inclineRecord?.outcome, .skipped(reason: .pain))
        // Keine Arbeitssätze mit 0 kg als Nebenwirkung.
        XCTAssertTrue(runtime.session.sets.allSatisfy { $0.weight > 0 || $0.kind == .warmup })
    }

    func testReplacedExerciseIsStoredAsTheExerciseActuallyPerformed() throws {
        let runtime = makeRuntime(day: .push)
        try performSets(runtime, count: 3, from: start)
        try runtime.replaceCurrentExercise(with: DefaultPlan.ID.flatPress, reason: .equipmentBusy)

        var now = start.addingTimeInterval(400)
        try runtime.startSet(at: now)
        now = now.addingTimeInterval(25)
        try runtime.stopSet(at: now)
        try runtime.submit(SetEntry(reps: 8, weight: 70), at: now.addingTimeInterval(5))

        let record = runtime.session.sets.last
        XCTAssertEqual(record?.exerciseID, DefaultPlan.ID.flatPress)

        runtime.finishEarly(at: now.addingTimeInterval(60))
        let outcome = runtime.session.exercises.first { $0.blockID == "push-1-incline" }?.outcome
        XCTAssertEqual(
            outcome,
            .replaced(byExerciseID: DefaultPlan.ID.flatPress, reason: .equipmentBusy)
        )
    }

    func testOptionalSetCanBeSkipped() throws {
        let runtime = makeRuntime(day: .legs)
        let sets = SessionPlanFlattener.flatten(day: DefaultPlan.legsDay)
        let calfSets = sets.filter { $0.exerciseID == DefaultPlan.ID.calfRaise }
        XCTAssertEqual(calfSets.count, 4)
        XCTAssertTrue(calfSets.last!.isOptional, "vierter Satz Wadenheben ist optional")
    }

    // MARK: - Störungsmarker

    func testDisturbanceMarkerKeepsTheMeasuredValue() throws {
        let runtime = makeRuntime()
        try runtime.startSet(at: start)
        try runtime.stopSet(at: start.addingTimeInterval(30))
        try runtime.submit(
            SetEntry(
                reps: 12,
                weight: 20,
                disturbances: [DisturbanceMarker(scope: .pause, reason: .conversation)]
            ),
            at: start.addingTimeInterval(35)
        )

        let record = runtime.session.sets[0]
        XCTAssertEqual(record.reps, 12, "der Messwert bleibt unverändert")
        XCTAssertEqual(record.pauseDisturbance?.category, .external)
        XCTAssertFalse(record.isBotched)
    }

    func testBotchedSetIsExcludedFromPerformance() throws {
        let runtime = makeRuntime(day: .push)
        try performSets(runtime, count: 3, from: start)

        var now = start.addingTimeInterval(300)
        try runtime.startSet(at: now)
        now = now.addingTimeInterval(25)
        try runtime.stopSet(at: now)
        try runtime.submit(
            SetEntry(
                reps: 4,
                weight: 80,
                disturbances: [DisturbanceMarker(scope: .set, reason: .slipped)]
            ),
            at: now.addingTimeInterval(5)
        )

        let record = runtime.session.sets.last!
        XCTAssertTrue(record.isBotched)
        XCTAssertFalse(record.countsForPerformance)
    }

    func testMarkingLastSetAfterwards() throws {
        let runtime = makeRuntime()
        try runtime.startSet(at: start)
        try runtime.stopSet(at: start.addingTimeInterval(30))
        try runtime.submit(SetEntry(reps: 12, weight: 20), at: start.addingTimeInterval(35))

        runtime.markLastSet(DisturbanceMarker(scope: .pause, reason: .equipmentBusy))
        XCTAssertEqual(runtime.session.sets[0].disturbances.count, 1)
    }

    // MARK: - Korrektur

    func testCorrectingLastSetKeepsTimingData() throws {
        let runtime = makeRuntime()
        try runtime.startSet(at: start)
        try runtime.stopSet(at: start.addingTimeInterval(30))
        try runtime.submit(SetEntry(reps: 12, weight: 20), at: start.addingTimeInterval(35))

        runtime.correctLastSet(reps: 10, weight: 22.5)
        let record = runtime.session.sets[0]
        XCTAssertEqual(record.reps, 10)
        XCTAssertEqual(record.weight, 22.5)
        XCTAssertEqual(record.duration, 30, "die gemessene Dauer bleibt erhalten")
    }

    // MARK: - Fortsetzen

    func testRestoringAnOpenSessionRecomputesRemainingRestFromTimestamps() throws {
        let runtime = makeRuntime(day: .push)
        try performSets(runtime, count: 3, from: start)

        var now = start.addingTimeInterval(300)
        try runtime.startSet(at: now)
        now = now.addingTimeInterval(25)
        try runtime.stopSet(at: now)
        try runtime.submit(SetEntry(reps: 8, weight: 80), at: now.addingTimeInterval(10))

        let snapshot = runtime.snapshot()
        let restored = SessionRuntime(restoring: snapshot, planVersion: plan)

        guard case let .resting(context) = restored.phase else {
            return XCTFail("die offene Pause muss erhalten bleiben")
        }
        // 60 Sekunden nach dem Satzstopp sind von 120 noch 60 übrig --
        // unabhängig davon, ob die App zwischenzeitlich gesperrt war.
        let sixtyAfterStop = now.addingTimeInterval(60)
        XCTAssertEqual(context.remaining(at: sixtyAfterStop), 60, accuracy: 0.001)
        XCTAssertEqual(restored.session.sets.count, 4)
    }

    func testRestoringAfterRestElapsedKeepsNegativeOvertime() throws {
        let runtime = makeRuntime(day: .push)
        try performSets(runtime, count: 3, from: start)

        var now = start.addingTimeInterval(300)
        try runtime.startSet(at: now)
        now = now.addingTimeInterval(25)
        try runtime.stopSet(at: now)
        try runtime.submit(SetEntry(reps: 8, weight: 80), at: now.addingTimeInterval(10))

        let restored = SessionRuntime(restoring: runtime.snapshot(), planVersion: plan)
        guard case let .resting(context) = restored.phase else {
            return XCTFail("erwartet resting")
        }
        // Zielpause 120 s ab Satzstopp; 600 s später sind 480 s Überziehung.
        XCTAssertEqual(context.remaining(at: now.addingTimeInterval(600)), -480, accuracy: 0.001)
        XCTAssertTrue(context.isOver(at: now.addingTimeInterval(600)))
    }

    // MARK: - Abschluss

    func testSessionEndsInPhotosThenFinished() throws {
        let runtime = makeRuntime(day: .push)
        let total = runtime.plannedSets.count
        try performSets(runtime, count: total, from: start)

        guard case let .photos(day, slots) = runtime.phase else {
            return XCTFail("nach dem letzten Satz kommen die Fotos")
        }
        XCTAssertEqual(day, .push)
        XCTAssertEqual(slots, [.chestFront, .chestSide, .tricepsFlexed])

        runtime.completePhotos(at: start.addingTimeInterval(5000), tag: .normal)
        guard case .finished = runtime.phase else { return XCTFail("erwartet finished") }
        XCTAssertEqual(runtime.session.status, .completed)
        XCTAssertEqual(runtime.session.tag, .normal)
        XCTAssertNotNil(runtime.session.duration)
    }

    func testAbortedSessionIsMarkedAndNotCompleted() {
        let runtime = makeRuntime()
        runtime.abort(at: start.addingTimeInterval(600))
        XCTAssertEqual(runtime.session.status, .aborted)
        XCTAssertEqual(runtime.session.tag, .aborted)
    }

    func testReadinessIsStoredAndAdvancesIntoFirstSet() {
        let runtime = SessionRuntime(day: .push, planVersion: plan, startedAt: start)
        guard case .awaitingReadiness = runtime.phase else {
            return XCTFail("Session beginnt mit dem Readiness-Tap")
        }
        runtime.setReadiness(.bad)
        XCTAssertEqual(runtime.session.readiness, .bad)
        guard case .preview = runtime.phase else { return XCTFail("erwartet preview") }
    }

    // MARK: - Hilfsfunktion

    /// Spielt `count` Sätze mit realistischen Zeiten durch.
    private func performSets(_ runtime: SessionRuntime, count: Int, from origin: Date) throws {
        var now = origin
        for _ in 0..<count {
            guard case let .preview(set) = runtime.phase else { return }
            try runtime.startSet(at: now)
            now = now.addingTimeInterval(30)
            try runtime.stopSet(at: now)
            now = now.addingTimeInterval(8)
            let reps = set.reps.upperBound ?? 8
            try runtime.submit(SetEntry(reps: reps, weight: 60), at: now)
            if case let .resting(context) = runtime.phase {
                now = context.restTargetEnd
                try runtime.finishRest()
            }
        }
    }
}
