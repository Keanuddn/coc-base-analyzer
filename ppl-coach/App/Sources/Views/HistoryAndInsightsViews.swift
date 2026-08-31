import SwiftUI
import Charts
import PPLCoachCore

/// Verlauf: eine Übung, eine Linie Last und eine Linie Wiederholungen.
/// Keine Dashboard-Wand.
struct HistoryView: View {
    @EnvironmentObject private var store: Store
    @State private var exerciseID: String = DefaultPlan.ID.inclinePress

    private var points: [ExercisePoint] {
        store.sessions
            .filter { $0.status == .completed }
            .sorted { $0.startedAt < $1.startedAt }
            .compactMap { session in
                guard let summary = Metrics.summarize(exerciseID: exerciseID, in: session)
                else { return nil }
                let reps = Metrics.mean(summary.workSets.map { Double($0.reps) }) ?? 0
                let weight = summary.workSets.map(\.weight).max() ?? 0
                let disturbed = summary.workSets.contains { !$0.disturbances.isEmpty }
                return ExercisePoint(
                    date: session.startedAt,
                    weight: weight,
                    reps: reps,
                    secondsPerRep: summary.averageSecondsPerRep,
                    disturbed: disturbed
                )
            }
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 22) {
                Picker("Übung", selection: $exerciseID) {
                    ForEach(store.currentPlan.exercises, id: \.id) { exercise in
                        Text(exercise.name).tag(exercise.id)
                    }
                }
                .pickerStyle(.menu)

                if points.isEmpty {
                    ContentUnavailableView(
                        "Noch keine Daten",
                        systemImage: "chart.line.uptrend.xyaxis",
                        description: Text("Nach den ersten Sessions erscheint hier der Verlauf.")
                    )
                } else {
                    chartSection(
                        title: "Arbeitslast",
                        unit: "Gewicht (kg)",
                        values: points.map { ($0.date, $0.weight, $0.disturbed) }
                    )
                    chartSection(
                        title: "Wiederholungen im Mittel",
                        unit: "Wiederholungen",
                        values: points.map { ($0.date, $0.reps, $0.disturbed) }
                    )
                    let tempoPoints = points.compactMap { point -> (Date, Double, Bool)? in
                        guard let value = point.secondsPerRep else { return nil }
                        return (point.date, value, point.disturbed)
                    }
                    if !tempoPoints.isEmpty {
                        chartSection(
                            title: "Zeit pro Wiederholung",
                            unit: "Sekunden pro Wiederholung",
                            values: tempoPoints
                        )
                    }
                }

                sessionList
            }
            .padding(16)
        }
        .navigationTitle("Verlauf")
    }

    /// Sessions zum Nachschauen -- und zum nachträglichen Markieren einer
    /// Störung, wenn dir Tage später einfällt, dass eine Pause untypisch war.
    private var sessionList: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("Sessions")
                .font(.system(size: 17, weight: .semibold))
                .foregroundStyle(GymTheme.primaryText)

            ForEach(
                store.sessions
                    .filter { $0.status == .completed }
                    .sorted { $0.startedAt > $1.startedAt }
                    .prefix(20)
            ) { session in
                NavigationLink {
                    SessionDetailView(session: session)
                } label: {
                    HStack {
                        VStack(alignment: .leading, spacing: 2) {
                            Text(session.day.displayName)
                                .font(.system(size: 15, weight: .medium))
                                .foregroundStyle(GymTheme.primaryText)
                            Text(session.startedAt.formatted(date: .abbreviated, time: .shortened))
                                .font(.system(size: 12))
                                .foregroundStyle(GymTheme.secondaryText)
                        }
                        Spacer()
                        Text("\(session.workSets.count) Sätze")
                            .font(.system(size: 13).monospacedDigit())
                            .foregroundStyle(GymTheme.secondaryText)
                        Image(systemName: "chevron.right")
                            .font(.system(size: 12))
                            .foregroundStyle(GymTheme.secondaryText)
                    }
                    .padding(12)
                    .background(GymTheme.surface, in: RoundedRectangle(cornerRadius: 12))
                }
                .buttonStyle(.plain)
            }
        }
    }

    private func chartSection(
        title: String,
        unit: String,
        values: [(Date, Double, Bool)]
    ) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(title)
                .font(.system(size: 17, weight: .semibold))
                .foregroundStyle(GymTheme.primaryText)

            Chart {
                ForEach(Array(values.enumerated()), id: \.offset) { _, entry in
                    LineMark(
                        x: .value("Datum", entry.0),
                        y: .value(unit, entry.1)
                    )
                    .foregroundStyle(GymTheme.Mode.work.accent)

                    // Markierte Punkte sind sichtbar, damit klar ist, was
                    // ausgeklammert wurde.
                    PointMark(
                        x: .value("Datum", entry.0),
                        y: .value(unit, entry.1)
                    )
                    .symbol(entry.2 ? .diamond : .circle)
                    .foregroundStyle(entry.2 ? GymTheme.secondaryText : GymTheme.Mode.work.accent)
                }
            }
            .chartXAxisLabel("Datum")
            .chartYAxisLabel(unit)
            .frame(height: 190)

            Text("Quelle: eigene Sessions · Raute = als Störung markiert")
                .font(.system(size: 11))
                .foregroundStyle(GymTheme.secondaryText)
        }
        .padding(14)
        .background(GymTheme.surface, in: RoundedRectangle(cornerRadius: 16))
    }

    private struct ExercisePoint {
        let date: Date
        let weight: Double
        let reps: Double
        let secondsPerRep: Double?
        let disturbed: Bool
    }
}

/// Eine einzelne Session mit allen Sätzen.
///
/// Hier lässt sich eine Störung **nachträglich** markieren. Der Messwert bleibt
/// unverändert -- nur die Interpretation ändert sich.
struct SessionDetailView: View {
    @EnvironmentObject private var store: Store
    let session: SessionRecord

    var body: some View {
        List {
            Section {
                LabeledContent("Trainingstag", value: session.day.displayName)
                LabeledContent(
                    "Beginn",
                    value: session.startedAt.formatted(date: .abbreviated, time: .shortened)
                )
                if let duration = session.duration {
                    LabeledContent("Dauer", value: "\(Int(duration / 60)) min")
                }
                if let readiness = session.readiness {
                    LabeledContent("Bereitschaft", value: readiness.displayName)
                }
                if let tag = session.tag {
                    LabeledContent("Rückblick", value: tag.displayName)
                }
            }

            Section("Sätze") {
                ForEach(session.sets) { set in
                    setRow(set)
                }
            }

            let skipped = session.exercises.filter {
                if case .performed = $0.outcome { return false }
                return true
            }
            if !skipped.isEmpty {
                Section("Übersprungen oder ersetzt") {
                    ForEach(skipped, id: \.blockID) { record in
                        VStack(alignment: .leading, spacing: 2) {
                            Text(name(record.plannedExerciseID))
                                .font(.system(size: 15, weight: .medium))
                            Text(outcomeText(record.outcome))
                                .font(.system(size: 13))
                                .foregroundStyle(GymTheme.secondaryText)
                        }
                    }
                }
            }
        }
        .navigationTitle(session.startedAt.formatted(date: .abbreviated, time: .omitted))
    }

    private func setRow(_ set: SetRecord) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack {
                Text(name(set.exerciseID))
                    .font(.system(size: 15, weight: .medium))
                if set.kind == .warmup {
                    Text("Warm-up")
                        .font(.system(size: 11, weight: .bold))
                        .padding(.horizontal, 5)
                        .padding(.vertical, 1)
                        .background(GymTheme.stroke, in: Capsule())
                }
                Spacer()
                Text("\(set.reps)× \(set.weight.kgText) kg")
                    .font(.system(size: 15).monospacedDigit())
            }

            HStack(spacing: 10) {
                Text(set.duration.map { "\(Int($0)) s Satz" } ?? "Dauer fehlt")
                if let pause = set.actualPause {
                    Text("·")
                    Text("\(Int(pause)) s Pause")
                }
                if let deviation = set.pauseDeviation {
                    Text("·")
                    Text("\(deviation > 0 ? "+" : "")\(Int(deviation)) s")
                }
            }
            .font(.system(size: 12).monospacedDigit())
            .foregroundStyle(GymTheme.secondaryText)

            if set.disturbances.isEmpty {
                Menu("Nachträglich als nicht typisch markieren") {
                    ForEach(DisturbanceReason.allCases, id: \.self) { reason in
                        Button(reason.displayName) {
                            store.markSet(
                                sessionID: session.id,
                                setID: set.id,
                                marker: DisturbanceMarker(
                                    scope: reason.category == .botchedSet ? .set : .pause,
                                    reason: reason
                                )
                            )
                        }
                    }
                }
                .font(.system(size: 12))
            } else {
                Text("Markiert: \(set.disturbances.map(\.reason.displayName).joined(separator: ", "))")
                    .font(.system(size: 12))
                    .foregroundStyle(GymTheme.Mode.rest.accent)
            }
        }
        .padding(.vertical, 2)
    }

    private func name(_ exerciseID: String) -> String {
        store.currentPlan.exercise(id: exerciseID)?.name ?? exerciseID
    }

    private func outcomeText(_ outcome: ExerciseOutcome) -> String {
        switch outcome {
        case .performed:
            return "ausgeführt"
        case let .skipped(reason):
            return "übersprungen (\(reason.displayName))"
        case let .replaced(byExerciseID, reason):
            return "ersetzt durch \(name(byExerciseID)) (\(reason.displayName))"
        }
    }
}

/// Erkenntnisse: eine Karte, ein Befund. Nicht zwölf auf einmal.
struct InsightsView: View {
    @EnvironmentObject private var store: Store
    @State private var output: AnalysisEngine.Output?
    @State private var startedTrial: Trial?
    @State private var trialResults: [TrialResult] = []

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                if let note = output?.growthNote {
                    calloutBox(
                        title: "Vor jeder Aussage zum Muskelaufbau",
                        text: note
                    )
                }

                // Ergebnisse abgelaufener Proben -- eine Probe ohne Auswertung
                // wäre nur ein guter Vorsatz.
                ForEach(trialResults, id: \.trialID) { result in
                    calloutBox(
                        title: result.succeeded ? "Probe hat geholfen" : "Probe hat nichts gebracht",
                        text: result.verdict
                    )
                }

                if let cards = output?.cards, !cards.isEmpty {
                    ForEach(cards) { card in
                        cardView(card)
                    }
                } else {
                    ContentUnavailableView(
                        "Noch keine belastbare Aussage",
                        systemImage: "lightbulb",
                        description: Text("Lieber nichts sagen als eine Geschichte aus zwei Sessions bauen.")
                    )
                }

                if let silences = output?.silences, !silences.isEmpty {
                    silenceSection(silences)
                }
            }
            .padding(16)
        }
        .navigationTitle("Erkenntnisse")
        .onAppear(perform: runAnalysis)
        .alert("Probe gestartet", isPresented: .constant(startedTrial != nil)) {
            Button("Ok") { startedTrial = nil }
        } message: {
            if let startedTrial {
                Text(startedTrial.proposalText(planVersion: store.currentPlan))
            }
        }
    }

    private func runAnalysis() {
        trialResults = store.evaluateRunningTrials()
        let engine = AnalysisEngine(
            ranker: InsightRanker(dampenedDetectorIDs: store.dampenedDetectorIDs)
        )
        output = engine.run(store.analysisInput())
    }

    private func cardView(_ card: InsightCard) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            Text(card.headline)
                .font(.system(size: 19, weight: .semibold))
                .foregroundStyle(GymTheme.primaryText)

            Text(card.body)
                .font(.system(size: 15))
                .foregroundStyle(GymTheme.primaryText.opacity(0.85))

            VStack(alignment: .leading, spacing: 6) {
                ForEach(card.evidenceLines, id: \.self) { line in
                    Text(line)
                        .font(.system(size: 13))
                        .foregroundStyle(GymTheme.secondaryText)
                }
            }

            if let nextStep = card.nextStep {
                Text(nextStep)
                    .font(.system(size: 14, weight: .medium))
                    .foregroundStyle(GymTheme.Mode.rest.accent)
            }

            // Rückmeldung: „stimmt nicht“ dämpft den Detektor,
            // „probiere ich“ startet eine Probe.
            HStack(spacing: 8) {
                ForEach(
                    [CardFeedback.correct, .wrong, .willTry],
                    id: \.self
                ) { feedback in
                    Button(feedback.displayName) {
                        handle(feedback, card: card)
                    }
                    .font(.system(size: 13, weight: .medium))
                    .buttonStyle(.bordered)
                }
            }
        }
        .padding(16)
        .background(GymTheme.surface, in: RoundedRectangle(cornerRadius: 16))
    }

    private func handle(_ feedback: CardFeedback, card: InsightCard) {
        store.recordFeedback(feedback, detectorID: card.finding.detectorID)

        // „Probiere ich“ startet die Probe -- Laufzeit und Erfolgsschwelle
        // rechnet die App, nicht das Modell und nicht der Detektor.
        if feedback == .willTry {
            let result = TrialPlanner().proposal(
                for: card.finding,
                planVersion: store.currentPlan,
                history: store.sessions,
                runningTrials: store.runningTrials
            )
            if case let .success(trial) = result {
                var started = trial
                started.status = .running
                started.startedAt = Date()
                store.save(started)
                startedTrial = started
            }
        }
        runAnalysis()
    }

    private func calloutBox(title: String, text: String) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(title)
                .font(.system(size: 13, weight: .bold))
                .tracking(0.8)
                .foregroundStyle(GymTheme.Mode.rest.accent)
            Text(text)
                .font(.system(size: 14))
                .foregroundStyle(GymTheme.primaryText)
        }
        .padding(14)
        .background(GymTheme.surface, in: RoundedRectangle(cornerRadius: 14))
    }

    /// Sichtbar machen, warum die übrigen Detektoren geschwiegen haben.
    private func silenceSection(_ silences: [String: SilenceReason]) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("Noch offen")
                .font(.system(size: 15, weight: .semibold))
                .foregroundStyle(GymTheme.primaryText)

            ForEach(silences.sorted(by: { $0.key < $1.key }), id: \.key) { entry in
                VStack(alignment: .leading, spacing: 2) {
                    Text(question(for: entry.key))
                        .font(.system(size: 13, weight: .medium))
                        .foregroundStyle(GymTheme.primaryText.opacity(0.8))
                    Text(entry.value.displayText)
                        .font(.system(size: 12))
                        .foregroundStyle(GymTheme.secondaryText)
                }
            }
        }
        .padding(14)
        .background(GymTheme.surface.opacity(0.6), in: RoundedRectangle(cornerRadius: 14))
    }

    private func question(for detectorID: String) -> String {
        AnalysisEngine.defaultDetectors.first { $0.id == detectorID }?.question ?? detectorID
    }
}
