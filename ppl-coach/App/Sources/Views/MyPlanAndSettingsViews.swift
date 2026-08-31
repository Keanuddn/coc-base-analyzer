import SwiftUI
import PPLCoachCore

/// „Mein Plan“: die einzige Stelle, an der sich der Plan ändert -- und nur,
/// weil du speicherst. Jedes Speichern erzeugt eine neue Version, damit alte
/// Sessions gegen die damals gültige Vorgabe vergleichbar bleiben.
struct MyPlanView: View {
    @EnvironmentObject private var store: Store
    @State private var draft: PlanVersion?
    @State private var showSavedHint = false

    private var plan: PlanVersion {
        draft ?? store.currentPlan
    }

    var body: some View {
        List {
            Section {
                Text("Änderungen gelten ab der nächsten Session. Alte Sessions bleiben gegen die bisherige Fassung vergleichbar.")
                    .font(.system(size: 13))
                    .foregroundStyle(GymTheme.secondaryText)
            }

            ForEach(TrainingDay.allCases, id: \.self) { day in
                if let template = plan.template(for: day) {
                    Section(day.displayName) {
                        ForEach(template.blocks, id: \.id) { block in
                            blockRows(block)
                        }
                    }
                }
            }

            Section("Gewichtsschritte") {
                Text("Standard sind 2,5 kg. Pro Übung anpassbar -- an einer Maschine mit 5-kg-Raster ist eine Empfehlung von 82,5 kg nicht einstellbar.")
                    .font(.system(size: 13))
                    .foregroundStyle(GymTheme.secondaryText)

                ForEach(plan.exercises, id: \.id) { exercise in
                    HStack {
                        Text(exercise.name)
                            .font(.system(size: 15))
                        Spacer()
                        Menu("\(exercise.weightStep.kilograms.kgText) kg") {
                            ForEach([1.0, 2.0, 2.5, 5.0], id: \.self) { value in
                                Button("\(value.kgText) kg") {
                                    updateStep(exerciseID: exercise.id, kilograms: value)
                                }
                            }
                        }
                        .font(.system(size: 15, weight: .medium))
                    }
                }
            }
        }
        .navigationTitle("Mein Plan")
        .toolbar {
            ToolbarItem(placement: .confirmationAction) {
                Button("Speichern") {
                    if let draft {
                        store.savePlan(draft)
                        self.draft = nil
                        showSavedHint = true
                    }
                }
                .disabled(draft == nil)
            }
        }
        .alert("Neue Planfassung gespeichert", isPresented: $showSavedHint) {
            Button("Ok", role: .cancel) {}
        } message: {
            Text("Ab hier wird gegen die neue Vorgabe verglichen. Die Analyse kennzeichnet den Bruch.")
        }
    }

    @ViewBuilder
    private func blockRows(_ block: Block) -> some View {
        switch block {
        case let .single(_, exerciseID, sets):
            exerciseRow(exerciseID: exerciseID, sets: sets, isSuperset: false)
        case let .superset(_, firstID, firstSets, secondID, secondSets):
            exerciseRow(exerciseID: firstID, sets: firstSets, isSuperset: true)
            exerciseRow(exerciseID: secondID, sets: secondSets, isSuperset: true)
        }
    }

    private func exerciseRow(
        exerciseID: String,
        sets: [SetPrescription],
        isSuperset: Bool
    ) -> some View {
        let work = sets.filter { $0.kind == .work }
        let warmups = sets.filter { $0.kind == .warmup }

        return VStack(alignment: .leading, spacing: 4) {
            HStack(spacing: 6) {
                Text(plan.exercise(id: exerciseID)?.name ?? exerciseID)
                    .font(.system(size: 16, weight: .semibold))
                if isSuperset {
                    Text("Superset")
                        .font(.system(size: 11, weight: .bold))
                        .padding(.horizontal, 6)
                        .padding(.vertical, 2)
                        .background(GymTheme.stroke, in: Capsule())
                }
            }

            HStack(spacing: 10) {
                Text("\(work.count) Arbeitssätze")
                if let first = work.first {
                    Text("·")
                    Text(first.reps.displayText)
                    if first.pause.enforcesRest {
                        Text("·")
                        Text(first.pause.displayText)
                    }
                }
            }
            .font(.system(size: 13))
            .foregroundStyle(GymTheme.secondaryText)

            if !warmups.isEmpty {
                Text("\(warmups.count) Warm-up-Sätze, keine Pflichtpause")
                    .font(.system(size: 12))
                    .foregroundStyle(GymTheme.secondaryText.opacity(0.8))
            }
        }
        .padding(.vertical, 2)
    }

    /// Ändert die kleinste Gewichtsstufe einer Übung.
    private func updateStep(exerciseID: String, kilograms: Double) {
        var exercises = plan.exercises
        guard let index = exercises.firstIndex(where: { $0.id == exerciseID }) else { return }
        exercises[index].weightStep = WeightStep(kilograms: kilograms)
        draft = PlanVersion(
            id: plan.id,
            createdAt: plan.createdAt,
            exercises: exercises,
            days: plan.days
        )
    }
}

/// Einstellungen, Whoop, Körpergewicht, Export.
struct SettingsView: View {
    @EnvironmentObject private var store: Store
    @EnvironmentObject private var whoop: WhoopSync

    @State private var soundEnabled = Haptics.soundEnabled
    @State private var hapticsEnabled = Haptics.hapticsEnabled
    @State private var newWeight: Double = 80
    @State private var exportURL: URL?
    @State private var showShare = false

    var body: some View {
        List {
            Section("Whoop") {
                if whoop.isConnected {
                    HStack {
                        Text("Verbunden")
                        Spacer()
                        Text(whoop.lastSyncText)
                            .font(.system(size: 13))
                            .foregroundStyle(GymTheme.secondaryText)
                    }
                    Button("Jetzt synchronisieren") {
                        Task { await whoop.sync(into: store) }
                    }
                    Button("Verbindung trennen", role: .destructive) {
                        whoop.disconnect()
                    }
                } else if WhoopCredentials.isConfigured {
                    Button("Mit Whoop verbinden") {
                        Task { await whoop.connect(into: store) }
                    }
                    Text("Beim ersten Verbinden wird Historie nachgeladen, damit die Baselines für HRV und Recovery sofort stehen. Rohwerte allein sagen wenig.")
                        .font(.system(size: 13))
                        .foregroundStyle(GymTheme.secondaryText)
                } else {
                    Text("Whoop ist nicht konfiguriert. Auf dem Mac `App/Config/Secrets.example.xcconfig` nach `Secrets.xcconfig` kopieren und Client-ID/Secret eintragen.")
                        .font(.system(size: 13))
                        .foregroundStyle(GymTheme.secondaryText)
                }
                if let error = whoop.lastError {
                    Text(error)
                        .font(.system(size: 13))
                        .foregroundStyle(.red)
                }
            }

            Section("Körpergewicht") {
                Text("Selten, aber unter gleichen Bedingungen. Ohne den Verlauf sind Foto-Urteile über die Arme in einer Diät unbrauchbar.")
                    .font(.system(size: 13))
                    .foregroundStyle(GymTheme.secondaryText)
                HStack {
                    Text("\(newWeight.kgText) kg")
                        .font(.system(size: 17, weight: .semibold).monospacedDigit())
                    Spacer()
                    Stepper("", value: $newWeight, in: 40...200, step: 0.1)
                        .labelsHidden()
                }
                Button("Eintragen") {
                    store.add(
                        BodyweightRecord(
                            date: Date(),
                            kilograms: newWeight,
                            condition: "morgens"
                        )
                    )
                }
                if let latest = store.latestBodyweight {
                    Text("Letzter Wert: \(latest.kgText) kg")
                        .font(.system(size: 13))
                        .foregroundStyle(GymTheme.secondaryText)
                }
            }

            Section("Signale") {
                Toggle("Ton bei Pausenende", isOn: $soundEnabled)
                    .onChange(of: soundEnabled) { _, value in Haptics.soundEnabled = value }
                Toggle("Vibration", isOn: $hapticsEnabled)
                    .onChange(of: hapticsEnabled) { _, value in Haptics.hapticsEnabled = value }
                Text("Das Pausenende muss man fühlen -- in der Pause liegt das Handy nicht in der Hand.")
                    .font(.system(size: 13))
                    .foregroundStyle(GymTheme.secondaryText)
            }

            Section("Proben") {
                if store.runningTrials.isEmpty {
                    Text("Keine laufende Probe.")
                        .foregroundStyle(GymTheme.secondaryText)
                } else {
                    ForEach(store.runningTrials) { trial in
                        VStack(alignment: .leading, spacing: 4) {
                            Text(trial.intervention.displayText)
                                .font(.system(size: 15, weight: .medium))
                            Text(trial.proposalText(planVersion: store.currentPlan))
                                .font(.system(size: 13))
                                .foregroundStyle(GymTheme.secondaryText)
                            Button("Probe abbrechen") {
                                var cancelled = trial
                                cancelled.status = .cancelled
                                store.save(cancelled)
                            }
                            .font(.system(size: 13))
                        }
                    }
                }
            }

            Section("Export") {
                Text("Dein Trainingsgedächtnis, unabhängig von der App.")
                    .font(.system(size: 13))
                    .foregroundStyle(GymTheme.secondaryText)
                Button("Alles als JSON exportieren") {
                    exportURL = try? store.writeExport()
                    showShare = exportURL != nil
                }
                Button("Sätze als CSV exportieren") {
                    exportURL = try? store.writeCSV()
                    showShare = exportURL != nil
                }
            }

            Section("Daten") {
                LabeledContent("Sessions", value: "\(store.sessions.count)")
                LabeledContent("Fotos", value: "\(store.photos.count)")
                LabeledContent("Planfassungen", value: "\(store.planVersions.count)")
                LabeledContent(
                    "Sicherung",
                    value: store.isBackedUpToICloud ? "iCloud" : "nur auf diesem Gerät"
                )
                if !store.isBackedUpToICloud {
                    Text("iCloud ist nicht verfügbar. Ein verlorenes iPhone würde die ganze Historie samt Fotos kosten -- exportiere in der Zwischenzeit regelmäßig.")
                        .font(.system(size: 13))
                        .foregroundStyle(.orange)
                }
            }

            #if DEBUG
            Section("Simulator") {
                Text("Acht synthetische Wochen mit eingebautem Pausen-Effekt, damit Verlauf und Erkenntnisse etwas zeigen. Keine echten Trainingsdaten.")
                    .font(.system(size: 13))
                    .foregroundStyle(GymTheme.secondaryText)
                Button("Beispieldaten laden") {
                    store.loadSimulatorSample()
                }
                Button("Aufgezeichnete Daten leeren", role: .destructive) {
                    store.resetLoggedData()
                }
            }
            #endif
        }
        .navigationTitle("Einstellungen")
        .sheet(isPresented: $showShare) {
            if let exportURL {
                ShareLink(item: exportURL) {
                    Label("Teilen", systemImage: "square.and.arrow.up")
                }
                .padding()
            }
        }
    }
}
