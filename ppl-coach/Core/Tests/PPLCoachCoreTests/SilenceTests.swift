import XCTest
@testable import PPLCoachCore

/// Der wichtigste Test der ganzen Analyse: **schweigt sie auf Rauschen?**
///
/// Einzelne Detektoren einzeln zu prüfen reicht nicht. Die Engine führt 16
/// Detektoren über 19 Übungen aus -- wenn irgendwo ein Zufallsfund durchkommt,
/// erzählt die App eine Geschichte, die es nicht gibt. Diese Tests laufen über
/// mehrere Seeds, damit ein glücklicher Zufall nicht als Erfolg zählt.
final class SilenceTests: XCTestCase {
    private let plan = DefaultPlan.version()

    private func input(_ sessions: [SessionRecord]) -> AnalysisInput {
        var utc = Calendar(identifier: .gregorian)
        utc.timeZone = TimeZone(secondsFromGMT: 0)!
        return AnalysisInput(planVersion: plan, sessions: sessions, calendar: utc)
    }

    /// Saubere Progression, kein eingebauter Effekt: die Engine darf nichts
    /// behaupten, das eine Ursache benennt.
    func testEngineMakesNoCausalClaimOnCleanProgressingData() {
        for seed in [1, 2, 3, 5, 8] as [UInt64] {
            var generator = SyntheticHistoryGenerator(
                truth: SyntheticTruth(progressesLoad: true, repNoise: 0.35),
                seed: seed
            )
            let sessions = generator.generate(weeks: 12)
            let output = AnalysisEngine().run(input(sessions))

            let claims = output.cards.filter { $0.finding.severity == .issue }
            XCTAssertTrue(
                claims.isEmpty,
                "Seed \(seed): keine Ursache behaupten, wenn alles normal läuft. "
                    + "Gemeldet: \(claims.map(\.finding.detectorID))"
            )
        }
    }

    /// Pausen zufällig vertauscht -- jeder Zusammenhang zwischen Pause und
    /// Folgesatz ist zerstört. Kein pausenbezogener Detektor darf feuern.
    func testNoPauseDetectorFiresOnShuffledPauses() {
        for seed in [4, 7, 13, 21, 34] as [UInt64] {
            var generator = SyntheticHistoryGenerator(
                truth: SyntheticTruth(
                    repLossFromShortPause: 2.5,
                    shortPauseProbability: 0.45,
                    progressesLoad: false,
                    repNoise: 0.3
                ),
                seed: seed
            )
            let sessions = generator.generate(weeks: 12)
            let shuffled = generator.shufflingPauses(in: sessions)
            let output = AnalysisEngine().run(input(shuffled))

            let pauseDetectors: Set<String> = ["pause-too-short", "pause-too-long"]
            let fired = output.cards
                .map(\.finding.detectorID)
                .filter { pauseDetectors.contains($0) }
            XCTAssertTrue(
                fired.isEmpty,
                "Seed \(seed): auf vertauschten Pausen muss geschwiegen werden. Gefeuert: \(fired)"
            )
        }
    }

    /// Zu wenige Sessions: gar keine Karte, egal wie deutlich das Muster wäre.
    func testEngineIsSilentWithVeryFewSessions() {
        var generator = SyntheticHistoryGenerator(
            truth: SyntheticTruth(
                repLossFromShortPause: 4,
                shortPauseProbability: 0.6,
                repLossPerSetIndex: 3,
                progressesLoad: false
            ),
            seed: 99
        )
        let sessions = generator.generate(weeks: 1)
        let output = AnalysisEngine().run(input(sessions))
        XCTAssertTrue(
            output.cards.isEmpty,
            "Aus drei Sessions wird keine Geschichte gebaut. Gemeldet: \(output.cards.map(\.finding.detectorID))"
        )
    }

    /// Alles als schlechter Tag markiert: nichts ist vergleichbar, also nichts
    /// zu melden.
    func testEngineIsSilentWhenEverySessionIsTaggedBadDay() {
        var generator = SyntheticHistoryGenerator(
            truth: SyntheticTruth(progressesLoad: false, repNoise: 0.1),
            seed: 55
        )
        var sessions = generator.generate(weeks: 12)
        sessions = sessions.map { session in
            var copy = session
            copy.tag = .badDay
            return copy
        }
        let output = AnalysisEngine().run(input(sessions))
        XCTAssertTrue(output.cards.isEmpty)
    }

    /// Fehlende Satzdauern dürfen nirgends zu einem Tempo- oder
    /// Bewegungsbefund führen.
    func testNoTempoClaimsWithoutMeasuredDurations() {
        var generator = SyntheticHistoryGenerator(
            truth: SyntheticTruth(tempoDriftPerWeek: 0.5, progressesLoad: false),
            seed: 66
        )
        var sessions = generator.generate(weeks: 12)
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
                    supersetRound: set.supersetRound,
                    supersetMember: set.supersetMember,
                    targetReps: set.targetReps,
                    targetPause: set.targetPause,
                    reps: set.reps,
                    weight: set.weight,
                    duration: nil,
                    startedAt: nil,
                    stoppedAt: set.stoppedAt,
                    actualPause: set.actualPause,
                    disturbances: set.disturbances
                )
            }
            return copy
        }

        let output = AnalysisEngine().run(input(sessions))
        let tempoDetectors: Set<String> = ["tempo-drift", "range-of-motion"]
        let fired = output.cards.map(\.finding.detectorID).filter { tempoDetectors.contains($0) }
        XCTAssertTrue(fired.isEmpty, "Ohne gemessene Dauern kein Tempo-Befund. Gefeuert: \(fired)")
    }

    /// Jede Karte, die die Engine ausgibt, muss Belege mit Stichprobengröße
    /// haben -- sonst ist es eine Behauptung.
    func testEveryCardCarriesEvidenceWithSampleSize() {
        var generator = SyntheticHistoryGenerator(
            truth: SyntheticTruth(
                repLossFromShortPause: 2.5,
                shortPauseProbability: 0.45,
                repLossPerSetIndex: 1.2,
                progressesLoad: false,
                repNoise: 0.2
            ),
            seed: 77
        )
        let sessions = generator.generate(weeks: 14)
        let output = AnalysisEngine().run(input(sessions))

        XCTAssertFalse(output.cards.isEmpty, "hier soll durchaus etwas gefunden werden")
        for card in output.cards {
            XCTAssertFalse(card.evidenceLines.isEmpty, card.id)
            XCTAssertTrue(
                card.finding.evidence.allSatisfy { $0.sampleSize > 0 },
                "\(card.id): Belege ohne Stichprobengröße sind keine Belege"
            )
            // Mindestens eines von beidem: geprüfte Ausschlüsse oder benannte
            // Grenzen. Ein Befund ohne beides wäre eine nackte Behauptung.
            XCTAssertFalse(
                card.finding.limitations.isEmpty && card.finding.ruledOut.isEmpty,
                "\(card.id): weder Ausschlüsse noch Grenzen benannt"
            )
        }
    }

    /// Jeder Detektor im Katalog wird auch tatsächlich ausgeführt und liefert
    /// entweder einen Befund oder einen Schweigegrund -- nie nichts.
    func testEveryDetectorReportsEitherFindingOrReason() {
        var generator = SyntheticHistoryGenerator(seed: 88)
        let sessions = generator.generate(weeks: 8)
        let analysisInput = input(sessions)
        let output = AnalysisEngine().run(analysisInput)

        let accountedFor = Set(output.cards.map(\.finding.detectorID))
            .union(output.silences.keys)
        for detector in AnalysisEngine.defaultDetectors {
            XCTAssertTrue(
                accountedFor.contains(detector.id),
                "\(detector.id) hat weder Befund noch Schweigegrund geliefert"
            )
        }
    }
}
