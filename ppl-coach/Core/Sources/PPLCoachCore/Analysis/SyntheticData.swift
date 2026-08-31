import Foundation

/// Reproduzierbarer Zufall. Ohne festen Seed wären Tests launisch.
public struct SeededRandom: RandomNumberGenerator {
    private var state: UInt64

    public init(seed: UInt64 = 42) {
        self.state = seed == 0 ? 0x4d595df4d0f33173 : seed
    }

    public mutating func next() -> UInt64 {
        state ^= state << 13
        state ^= state >> 7
        state ^= state << 17
        return state
    }

    /// Normalverteiltes Rauschen über Box-Muller.
    public mutating func gaussian(mean: Double = 0, standardDeviation: Double = 1) -> Double {
        let u1 = Double.random(in: 0.0001...0.9999, using: &self)
        let u2 = Double.random(in: 0.0001...0.9999, using: &self)
        let z = (-2 * Foundation.log(u1)).squareRoot() * Foundation.cos(2 * Double.pi * u2)
        return mean + z * standardDeviation
    }
}

/// Wahrheiten, die in die erzeugten Daten eingebaut werden.
///
/// Der zugehörige Detektor **muss** genau das finden. Umgekehrt darf bei
/// abgeschalteten Effekten (oder bei vertauschten Pausen) **kein** Detektor
/// anspringen -- das ist der Null-Test.
public struct SyntheticTruth: Sendable {
    /// Wiederholungsverlust im Folgesatz, wenn die Pause deutlich zu kurz war.
    public var repLossFromShortPause: Double
    /// Anteil der Sätze, in denen die Pause absichtlich zu kurz ausfällt.
    public var shortPauseProbability: Double
    /// Zusätzliche Sekunden pro Wiederholung pro Woche bei gleicher Last.
    public var tempoDriftPerWeek: Double
    /// Wiederholungsverlust je Satzindex innerhalb einer Übung.
    public var repLossPerSetIndex: Double
    /// Steigert sich die Last über die Wochen?
    public var progressesLoad: Bool
    /// Rauschen der Wiederholungen.
    public var repNoise: Double

    public init(
        repLossFromShortPause: Double = 0,
        shortPauseProbability: Double = 0,
        tempoDriftPerWeek: Double = 0,
        repLossPerSetIndex: Double = 0,
        progressesLoad: Bool = true,
        repNoise: Double = 0.4
    ) {
        self.repLossFromShortPause = repLossFromShortPause
        self.shortPauseProbability = shortPauseProbability
        self.tempoDriftPerWeek = tempoDriftPerWeek
        self.repLossPerSetIndex = repLossPerSetIndex
        self.progressesLoad = progressesLoad
        self.repNoise = repNoise
    }

    /// Keine eingebauten Effekte -- Grundlage der Null-Tests.
    public static let none = SyntheticTruth()
}

/// Erzeugt Trainingshistorien mit bekannten Eigenschaften.
///
/// Damit lässt sich die Analyse entwickeln und prüfen, bevor eine einzige echte
/// Session existiert -- und vor allem prüfen, dass sie auf Rauschen **schweigt**.
public struct SyntheticHistoryGenerator {
    public let planVersion: PlanVersion
    public var truth: SyntheticTruth
    private var random: SeededRandom

    public init(
        planVersion: PlanVersion = DefaultPlan.version(),
        truth: SyntheticTruth = .none,
        seed: UInt64 = 42
    ) {
        self.planVersion = planVersion
        self.truth = truth
        self.random = SeededRandom(seed: seed)
    }

    /// Startlast pro Übung, damit die Zahlen plausibel aussehen.
    private func baseWeight(for exercise: Exercise) -> Double {
        switch exercise.loadKind {
        case .bodyweight: return 0
        case .dumbbell: return 14
        case .cable: return 25
        case .machine: return 60
        case .barbell: return 70
        }
    }

    /// Erzeugt `weeks` Wochen mit je drei Sessions (Push, Pull, Legs).
    ///
    /// - Parameters:
    ///   - startingAt: Zeitpunkt der ersten Session.
    ///   - hour: Trainingsbeginn. Konstant, damit die Uhrzeit-Frage bewusst
    ///     unbeantwortbar bleibt, solange keine Variation eingebaut wird.
    public mutating func generate(
        weeks: Int,
        startingAt: Date = Date(timeIntervalSince1970: 1_700_000_000),
        hour: Int = 18,
        calendar: Calendar = Calendar(identifier: .gregorian)
    ) -> [SessionRecord] {
        var sessions: [SessionRecord] = []
        var dayCursor = TrainingDay.push
        var utc = calendar
        utc.timeZone = TimeZone(secondsFromGMT: 0)!

        for week in 0..<weeks {
            for dayOffset in [0, 2, 4] {
                let base = startingAt.addingTimeInterval(Double(week * 7 + dayOffset) * 86_400)
                let start = setHour(hour, on: base, calendar: utc)
                sessions.append(
                    makeSession(day: dayCursor, week: week, startedAt: start)
                )
                dayCursor = dayCursor.next
            }
        }

        return sessions
    }

    /// Wie `generate`, variiert aber die Trainingszeit -- damit die
    /// Uhrzeit-Frage beantwortbar wird.
    public mutating func generateWithVaryingTime(
        weeks: Int,
        startingAt: Date = Date(timeIntervalSince1970: 1_700_000_000),
        morningHour: Int = 8,
        eveningHour: Int = 19,
        morningRepBonus: Double = 0,
        calendar: Calendar = Calendar(identifier: .gregorian)
    ) -> [SessionRecord] {
        var sessions: [SessionRecord] = []
        var dayCursor = TrainingDay.push
        var utc = calendar
        utc.timeZone = TimeZone(secondsFromGMT: 0)!

        for week in 0..<weeks {
            for dayOffset in [0, 2, 4] {
                let isMorning = week.isMultiple(of: 2)
                let base = startingAt.addingTimeInterval(Double(week * 7 + dayOffset) * 86_400)
                let start = setHour(isMorning ? morningHour : eveningHour, on: base, calendar: utc)
                sessions.append(
                    makeSession(
                        day: dayCursor,
                        week: week,
                        startedAt: start,
                        repBonus: isMorning ? morningRepBonus : 0
                    )
                )
                dayCursor = dayCursor.next
            }
        }

        return sessions
    }

    private func setHour(_ hour: Int, on date: Date, calendar: Calendar) -> Date {
        var components = calendar.dateComponents([.year, .month, .day], from: date)
        components.hour = hour
        components.minute = 0
        return calendar.date(from: components) ?? date
    }

    private mutating func makeSession(
        day: TrainingDay,
        week: Int,
        startedAt: Date,
        repBonus: Double = 0
    ) -> SessionRecord {
        guard let template = planVersion.template(for: day) else {
            return SessionRecord(
                day: day,
                planVersionID: planVersion.id,
                startedAt: startedAt,
                status: .completed
            )
        }

        let planned = SessionPlanFlattener.flatten(day: template)
        var session = SessionRecord(
            day: day,
            planVersionID: planVersion.id,
            startedAt: startedAt,
            status: .completed,
            readiness: .good,
            tag: .normal
        )

        var clock = startedAt
        var previousWasShortPause = false
        var records: [SetRecord] = []

        for set in planned {
            guard let exercise = planVersion.exercise(id: set.exerciseID) else { continue }

            let setStart = clock
            let targetReps = set.reps.upperBound ?? 8
            let lowerReps = set.reps.lowerBound ?? targetReps

            // Last: optional steigend über die Wochen.
            let progression = truth.progressesLoad ? Double(week) * exercise.weightStep.kilograms : 0
            let weight = set.kind == .warmup
                ? exercise.weightStep.snap(baseWeight(for: exercise) * 0.5)
                : exercise.weightStep.snap(baseWeight(for: exercise) + progression)

            // Wiederholungen: Ziel, minus Effekte, plus Rauschen.
            var reps = Double(targetReps)
            reps -= truth.repLossPerSetIndex * Double(max(0, set.setIndex - 1))
            if previousWasShortPause {
                reps -= truth.repLossFromShortPause
            }
            reps += repBonus
            reps += random.gaussian(standardDeviation: truth.repNoise)
            let finalReps = max(1, Int(reps.rounded()))

            // Satzdauer: Grundtempo plus optionaler Drift über die Wochen.
            let tempo = 2.4 + truth.tempoDriftPerWeek * Double(week)
                + random.gaussian(standardDeviation: 0.15)
            let duration = max(4, tempo * Double(finalReps))
            let stoppedAt = setStart.addingTimeInterval(duration)

            // Pause: Ziel, gelegentlich absichtlich zu kurz.
            let isShort = set.pause.enforcesRest
                && Double.random(in: 0...1, using: &random) < truth.shortPauseProbability
            let target = set.pause.timerTarget ?? 25
            let actualPause = isShort
                ? max(10, target - 35)
                : target + random.gaussian(standardDeviation: 6)

            records.append(
                SetRecord(
                    sessionID: session.id,
                    blockID: set.blockID,
                    exerciseID: set.exerciseID,
                    setIndex: set.setIndex,
                    kind: set.kind,
                    supersetRound: set.supersetRound,
                    supersetMember: set.supersetMember,
                    targetReps: set.reps,
                    targetPause: set.pause,
                    reps: max(1, min(finalReps, lowerReps + 12)),
                    weight: weight,
                    duration: duration,
                    startedAt: setStart,
                    stoppedAt: stoppedAt,
                    actualPause: actualPause
                )
            )

            previousWasShortPause = isShort
            clock = stoppedAt.addingTimeInterval(actualPause)
        }

        session.sets = records
        session.endedAt = clock
        session.exercises = buildExerciseRecords(planned: planned)
        return session
    }

    private func buildExerciseRecords(planned: [PlannedSet]) -> [ExerciseRecord] {
        var seen = Set<String>()
        var result: [ExerciseRecord] = []
        for set in planned where !seen.contains(set.blockID) {
            seen.insert(set.blockID)
            result.append(
                ExerciseRecord(
                    blockID: set.blockID,
                    plannedExerciseID: set.exerciseID,
                    outcome: .performed,
                    positionInSession: set.positionInSession
                )
            )
        }
        return result
    }

    /// Vertauscht die Pausen zufällig zwischen allen Sätzen und zerstört damit
    /// jeden echten Zusammenhang zwischen Pause und Folgesatz.
    ///
    /// Ein Detektor, der hier anspringt, ist kaputt -- dieselbe Logik wie die
    /// harten Negative im Base-Analyzer-Projekt.
    public mutating func shufflingPauses(in sessions: [SessionRecord]) -> [SessionRecord] {
        var allPauses = sessions.flatMap(\.sets).compactMap(\.actualPause)
        allPauses.shuffle(using: &random)

        var cursor = 0
        var result: [SessionRecord] = []
        for session in sessions {
            var copy = session
            for index in copy.sets.indices {
                guard copy.sets[index].actualPause != nil, cursor < allPauses.count else { continue }
                copy.sets[index].actualPause = allPauses[cursor]
                cursor += 1
            }
            result.append(copy)
        }
        return result
    }

    /// Erzeugt Whoop-Tageskontexte zu einer Historie.
    public mutating func dailyContexts(
        for sessions: [SessionRecord],
        lowRecoveryEveryOtherSession: Bool = false,
        status: ContextStatus = .complete
    ) -> [DailyContext] {
        sessions.enumerated().map { index, session in
            let isLow = lowRecoveryEveryOtherSession && index.isMultiple(of: 2)
            let recovery = isLow
                ? 30 + random.gaussian(standardDeviation: 5)
                : 75 + random.gaussian(standardDeviation: 5)
            let cycleStart = session.startedAt.addingTimeInterval(-8 * 3600)
            return DailyContext(
                cycleID: "cycle-\(index)",
                sleepID: "sleep-\(index)",
                cycleStart: cycleStart,
                cycleEnd: cycleStart.addingTimeInterval(24 * 3600),
                status: status,
                recoveryScore: recovery,
                hrvMilliseconds: 60 + random.gaussian(standardDeviation: 8),
                restingHeartRate: 52 + random.gaussian(standardDeviation: 2),
                sleepPerformancePercentage: 85 + random.gaussian(standardDeviation: 6),
                sleepDurationSeconds: 7.5 * 3600,
                dayStrain: 14 + random.gaussian(standardDeviation: 2)
            )
        }
    }
}
