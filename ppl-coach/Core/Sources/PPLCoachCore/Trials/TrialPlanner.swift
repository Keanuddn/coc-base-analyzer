import Foundation

/// Baut Proben und wertet sie aus.
///
/// Wichtig: **Laufzeit und Erfolgsschwelle rechnet immer die App**, egal ob die
/// Idee vom Detektor, vom Modell oder von dir kam. Das Modell darf den Eingriff
/// erfinden, nie die Bewertung.
public struct TrialPlanner {
    /// Wie viele Streuungen Unterschied als Antwort gelten.
    ///
    /// Schwanken die Wiederholungen ohnehin um ±1, muss das Kriterium darüber
    /// liegen -- daher „2 Wdh. mehr“ und keine Bauchzahl.
    public let scatterMultiple: Double
    /// Untergrenze der Schwelle, damit sie bei sehr ruhigen Übungen nicht
    /// unsinnig klein wird.
    public let minimumThreshold: Double
    /// Wie viele Sessions mindestens.
    public let minimumSessions: Int
    public let maximumSessions: Int

    public init(
        scatterMultiple: Double = 1.5,
        minimumThreshold: Double = 1.0,
        minimumSessions: Int = 3,
        maximumSessions: Int = 8
    ) {
        self.scatterMultiple = scatterMultiple
        self.minimumThreshold = minimumThreshold
        self.minimumSessions = minimumSessions
        self.maximumSessions = maximumSessions
    }

    public enum PlanningError: Error, Equatable {
        case notEnoughBaseline(have: Int, need: Int)
        case conflictingTrialRunning(day: TrainingDay)
        case exerciseAlreadyUnderTrial(exerciseID: String)
    }

    /// Erzeugt eine Probe. Schlägt fehl, wenn eine laufende Probe dieselbe
    /// Dimension messen würde -- zwei parallele Variationen am gleichen Tag
    /// machen beide Fragen unbeantwortbar.
    public func plan(
        origin: TrialOrigin,
        question: String,
        intervention: TrialIntervention,
        measuring exerciseID: String,
        metric: TrialMetric,
        history: [SessionRecord],
        planVersion: PlanVersion,
        runningTrials: [Trial]
    ) -> Result<Trial, PlanningError> {
        let affectedDays = intervention.affectedDays(in: planVersion)

        for running in runningTrials where running.status == .running {
            let runningDays = running.intervention.affectedDays(in: planVersion)
            if let overlap = runningDays.intersection(affectedDays).first {
                return .failure(.conflictingTrialRunning(day: overlap))
            }
            if running.measuredExerciseID == exerciseID {
                return .failure(.exerciseAlreadyUnderTrial(exerciseID: exerciseID))
            }
        }

        let values = baselineValues(exerciseID: exerciseID, metric: metric, sessions: history)
        guard values.count >= minimumSessions,
              let baseline = Metrics.mean(values) else {
            return .failure(.notEnoughBaseline(have: values.count, need: minimumSessions))
        }

        let scatter = Metrics.standardDeviation(values) ?? 0
        let threshold = max(minimumThreshold, scatterMultiple * scatter)
        let sessions = sessionCount(forScatter: scatter, baseline: baseline)

        return .success(
            Trial(
                origin: origin,
                question: question,
                intervention: intervention,
                measuredExerciseID: exerciseID,
                metric: metric,
                sessionCount: sessions,
                successThreshold: threshold,
                baselineValue: baseline,
                baselineScatter: scatter
            )
        )
    }

    /// Laufzeit aus der Streuung: unruhige Werte brauchen mehr Sessions, damit
    /// ein echter Effekt über dem Rauschen liegen kann.
    func sessionCount(forScatter scatter: Double, baseline: Double) -> Int {
        guard baseline > 0 else { return minimumSessions }
        let relative = scatter / baseline
        let extra = Int((relative * 20).rounded())
        return min(maximumSessions, max(minimumSessions, minimumSessions + extra))
    }

    /// Vergleichswerte aus der Zeit vor der Probe.
    func baselineValues(
        exerciseID: String,
        metric: TrialMetric,
        sessions: [SessionRecord]
    ) -> [Double] {
        sessions
            .filter { $0.status == .completed && $0.trialID == nil && $0.tag != .badDay }
            .sorted { $0.startedAt < $1.startedAt }
            .compactMap { value(exerciseID: exerciseID, metric: metric, in: $0) }
    }

    func value(exerciseID: String, metric: TrialMetric, in session: SessionRecord) -> Double? {
        let sets = session.sets.filter {
            $0.exerciseID == exerciseID && $0.countsForPerformance
        }
        guard !sets.isEmpty else { return nil }

        switch metric {
        case .reps:
            return Metrics.mean(sets.map { Double($0.reps) })
        case .secondsPerRep:
            return Metrics.mean(sets.compactMap(\.secondsPerRep))
        case .volume:
            return sets.reduce(0) { $0 + $1.volume }
        }
    }

    // MARK: - Auswertung

    /// Wertet eine gelaufene Probe aus.
    ///
    /// Abgebrochene Proben werden nicht als Ergebnis gelesen -- sie sind eine
    /// unbeantwortete Frage, kein Nein.
    public func evaluate(
        trial: Trial,
        history: [SessionRecord],
        planVersion: PlanVersion
    ) -> TrialResult? {
        guard trial.status == .running || trial.status == .evaluated else { return nil }

        let trialSessions = history.filter { trial.sessionIDs.contains($0.id) }
        let values = trialSessions
            .sorted { $0.startedAt < $1.startedAt }
            .compactMap { value(exerciseID: trial.measuredExerciseID, metric: trial.metric, in: $0) }

        guard values.count >= trial.sessionCount, let trialValue = Metrics.mean(values) else {
            return nil
        }

        let rawDifference = trialValue - trial.baselineValue
        // Bei Zeit pro Wiederholung ist eine Verringerung die Verbesserung.
        let improvement = trial.metric.lowerIsBetter ? -rawDifference : rawDifference
        let succeeded = improvement >= trial.successThreshold

        let name = planVersion.exercise(id: trial.measuredExerciseID)?.name
            ?? trial.measuredExerciseID
        let verdict: String
        if succeeded {
            verdict = "Hat geholfen: \(name) zeigt \(String(format: "%.1f", improvement)) "
                + "\(trial.metric.displayName) Verbesserung, die Schwelle lag bei "
                + "\(String(format: "%.1f", trial.successThreshold))."
        } else {
            verdict = "Hat nicht geholfen: die Veränderung bei \(name) blieb unter der "
                + "Schwelle von \(String(format: "%.1f", trial.successThreshold)) "
                + "\(trial.metric.displayName). Die Ursache liegt woanders."
        }

        return TrialResult(
            trialID: trial.id,
            baselineValue: trial.baselineValue,
            trialValue: trialValue,
            difference: improvement,
            threshold: trial.successThreshold,
            sessionsObserved: values.count,
            succeeded: succeeded,
            verdict: verdict
        )
    }

    // MARK: - Vorschlag aus einem Befund

    /// Leitet aus einem Befund, der ohne Variation offen bleibt, eine Probe ab.
    ///
    /// Das ist der deterministische Grundfall: der Detektor weiß, welche
    /// Dimension seiner Frage nicht variiert, und hat dafür eine feste Vorlage.
    public func proposal(
        for finding: Finding,
        planVersion: PlanVersion,
        history: [SessionRecord],
        runningTrials: [Trial]
    ) -> Result<Trial, PlanningError>? {
        guard let dimension = finding.suggestedVariation,
              let exerciseID = finding.exerciseIDs.first else { return nil }

        let intervention: TrialIntervention
        let metric: TrialMetric

        switch dimension {
        case .exerciseOrder:
            guard let partner = precedingExercise(of: exerciseID, in: planVersion) else {
                return nil
            }
            guard let day = planVersion.days.first(where: { template in
                template.blocks.contains { $0.exerciseIDs.contains(exerciseID) }
            })?.day else { return nil }
            intervention = .swapOrder(
                firstExerciseID: exerciseID,
                secondExerciseID: partner,
                day: day
            )
            metric = .reps

        case .timeOfDay:
            intervention = .shiftTrainingTime(to: .morning)
            metric = .reps

        case .supersetPairing:
            guard let blockID = supersetBlockID(containing: exerciseID, in: planVersion) else {
                return nil
            }
            intervention = .dissolveSuperset(blockID: blockID)
            metric = .reps

        case .pauseAdherence:
            intervention = .enforcePause(exerciseIDs: finding.exerciseIDs)
            metric = .reps

        case .loadProgression:
            intervention = .holdLoad(exerciseIDs: finding.exerciseIDs)
            metric = .secondsPerRep
        }

        return plan(
            origin: .detector,
            question: finding.observation,
            intervention: intervention,
            measuring: exerciseID,
            metric: metric,
            history: history,
            planVersion: planVersion,
            runningTrials: runningTrials
        )
    }

    /// Übung, die im Plan direkt vor der gegebenen steht -- der natürliche
    /// Tauschpartner für eine Reihenfolge-Probe.
    func precedingExercise(of exerciseID: String, in planVersion: PlanVersion) -> String? {
        for template in planVersion.days {
            let order = template.blocks.flatMap(\.exerciseIDs)
            guard let index = order.firstIndex(of: exerciseID), index > 0 else { continue }
            return order[index - 1]
        }
        return nil
    }

    func supersetBlockID(containing exerciseID: String, in planVersion: PlanVersion) -> String? {
        for template in planVersion.days {
            for block in template.blocks where block.isSuperset {
                if block.exerciseIDs.contains(exerciseID) { return block.id }
            }
        }
        return nil
    }
}
