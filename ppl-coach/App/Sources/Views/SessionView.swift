import SwiftUI
import PPLCoachCore

/// Die Session übernimmt den ganzen Bildschirm -- keine Tab-Bar, kein
/// Navigations-Chrome. Man soll in zwei Sekunden sehen, ob man arbeitet,
/// pausiert oder eintragen soll.
struct SessionView: View {
    @EnvironmentObject private var store: Store
    @ObservedObject var controller: SessionController

    @State private var showExerciseOptions = false
    @State private var showAbortConfirm = false

    private var mode: GymTheme.Mode {
        switch controller.phase {
        case let .setRunning(set, _):
            return set.isWarmup ? .warmup : .work
        case .resting:
            return .rest
        case .logging:
            return .entry
        case let .preview(set):
            return set.isWarmup ? .warmup : .work
        default:
            return .entry
        }
    }

    var body: some View {
        ZStack {
            mode.background.ignoresSafeArea()

            switch controller.phase {
            case .awaitingReadiness:
                ReadinessView { controller.setReadiness($0) }

            case let .preview(set):
                previewScreen(set)

            case let .setRunning(set, _):
                setRunningScreen(set)

            case let .logging(context):
                LoggingScreen(controller: controller, context: context)

            case let .resting(context):
                restingScreen(context)

            case let .photos(day, slots):
                PhotoStepView(
                    day: day,
                    slots: slots,
                    onFinish: { tag in controller.completePhotos(tag: tag) }
                )

            case .finished, .aborted:
                SessionSummaryView(controller: controller)
            }
        }
        .preferredColorScheme(.dark)
        .animation(.easeInOut(duration: 0.2), value: mode.label)
    }

    // MARK: - Übung anzeigen, Satz starten

    private func previewScreen(_ set: PlannedSet) -> some View {
        VStack(spacing: 0) {
            header(set)

            Spacer()

            VStack(spacing: 22) {
                if set.isWarmup {
                    Text("WARM-UP")
                        .font(.system(size: 14, weight: .bold))
                        .tracking(2)
                        .foregroundStyle(GymTheme.Mode.warmup.accent)
                    if let note = set.intensityNote {
                        Text(note)
                            .font(.system(size: 20, weight: .medium))
                            .foregroundStyle(GymTheme.secondaryText)
                    }
                }

                // Immer eine Empfehlung -- nie ein leeres Feld.
                if let recommendation = controller.recommendation {
                    VStack(spacing: 6) {
                        Text(recommendation.displayText)
                            .font(GymTheme.numberFont(size: 46))
                            .foregroundStyle(GymTheme.primaryText)
                        Text(recommendation.reason)
                            .font(.system(size: 15))
                            .foregroundStyle(GymTheme.secondaryText)
                            .multilineTextAlignment(.center)
                    }
                }

                // Am oberen Rand stoppen, auch wenn mehr gehen.
                if let stopAt = controller.recommendation?.stopAtReps, !set.isWarmup {
                    Text("Bei \(stopAt) Wiederholungen stoppen")
                        .font(.system(size: 17, weight: .semibold))
                        .foregroundStyle(mode.accent)
                }

                lastNumbers
            }
            .padding(.horizontal, 24)

            Spacer()

            VStack(spacing: 12) {
                PrimaryButton(title: "Satz starten", mode: mode) {
                    controller.startSet()
                }
                HStack(spacing: 12) {
                    SecondaryButton(title: "Übung …") { showExerciseOptions = true }
                    if set.isOptional {
                        SecondaryButton(title: "Satz überspringen") { controller.skipSet() }
                    }
                }
            }
            .padding(.horizontal, 20)
            .padding(.bottom, 24)
        }
        .sheet(isPresented: $showExerciseOptions) {
            ExerciseOptionsSheet(controller: controller, set: set)
        }
    }

    /// Letzte Zahlen dieser Übung -- sonst tippt man im Gym aus dem Gedächtnis.
    private var lastNumbers: some View {
        Group {
            if controller.lastSets.isEmpty {
                Text("Noch keine Historie für diese Übung")
                    .font(.system(size: 14))
                    .foregroundStyle(GymTheme.secondaryText)
            } else {
                VStack(spacing: 8) {
                    Text("LETZTES MAL")
                        .font(.system(size: 12, weight: .semibold))
                        .tracking(1.4)
                        .foregroundStyle(GymTheme.secondaryText)
                    HStack(spacing: 14) {
                        ForEach(Array(controller.lastSets.enumerated()), id: \.offset) { _, set in
                            VStack(spacing: 2) {
                                Text("\(set.reps)×")
                                    .font(.system(size: 17, weight: .semibold).monospacedDigit())
                                    .foregroundStyle(GymTheme.primaryText)
                                Text("\(set.weight.kgText) kg")
                                    .font(.system(size: 13).monospacedDigit())
                                    .foregroundStyle(GymTheme.secondaryText)
                                if let duration = set.duration {
                                    Text("\(Int(duration)) s")
                                        .font(.system(size: 11).monospacedDigit())
                                        .foregroundStyle(GymTheme.secondaryText.opacity(0.7))
                                }
                            }
                        }
                    }
                }
                .padding(.top, 8)
            }
        }
    }

    // MARK: - Satz läuft

    private func setRunningScreen(_ set: PlannedSet) -> some View {
        VStack(spacing: 0) {
            header(set)
            Spacer()

            VStack(spacing: 10) {
                Text(mode.label.uppercased())
                    .font(.system(size: 14, weight: .bold))
                    .tracking(2)
                    .foregroundStyle(mode.accent)

                Text((controller.elapsedSetDuration() ?? 0).clockText)
                    .font(GymTheme.timerFont(size: 96))
                    .foregroundStyle(GymTheme.primaryText)

                Text(set.reps.displayText)
                    .font(.system(size: 19, weight: .medium))
                    .foregroundStyle(GymTheme.secondaryText)
            }

            Spacer()

            PrimaryButton(title: "Satz stoppen", mode: mode) {
                controller.stopSet()
            }
            .padding(.horizontal, 20)
            .padding(.bottom, 24)
        }
    }

    // MARK: - Pause mit Restzeit

    private func restingScreen(_ context: SessionPhase.RestingContext) -> some View {
        let remaining = controller.restRemaining() ?? 0
        // Nach dem Ziel weiterzählen (negativ). Nicht automatisch weitergehen.
        let isOver = remaining <= 0

        return VStack(spacing: 0) {
            header(context.nextSet)
            Spacer()

            VStack(spacing: 10) {
                Text("PAUSE")
                    .font(.system(size: 14, weight: .bold))
                    .tracking(2)
                    .foregroundStyle(GymTheme.Mode.rest.accent)

                Text(remaining.clockText)
                    .font(GymTheme.timerFont(size: 96))
                    .foregroundStyle(isOver ? GymTheme.Mode.rest.accent : GymTheme.primaryText)

                Text(isOver
                     ? "Pause vorbei"
                     : "Ziel \(context.previousSet.pause.displayText)")
                    .font(.system(size: 17, weight: .medium))
                    .foregroundStyle(GymTheme.secondaryText)

                Text("Nächster Satz: \(exerciseName(context.nextSet))")
                    .font(.system(size: 15))
                    .foregroundStyle(GymTheme.secondaryText)
                    .padding(.top, 6)
            }

            Spacer()

            VStack(spacing: 12) {
                PrimaryButton(
                    title: isOver ? "Weiter" : "Bereit",
                    mode: .rest
                ) {
                    controller.finishRest()
                }
                // Störung markieren: der Wert bleibt gespeichert, wird aber
                // nicht als eigenes Verhalten gelesen.
                DisturbanceButton { marker in
                    controller.markLastSet(marker)
                }
            }
            .padding(.horizontal, 20)
            .padding(.bottom, 24)
        }
    }

    // MARK: - Kopfzeile

    private func header(_ set: PlannedSet) -> some View {
        VStack(spacing: 6) {
            HStack {
                Text(exerciseName(set))
                    .font(.system(size: 24, weight: .bold))
                    .foregroundStyle(GymTheme.primaryText)
                Spacer()
                Button {
                    showAbortConfirm = true
                } label: {
                    Image(systemName: "xmark")
                        .font(.system(size: 16, weight: .semibold))
                        .foregroundStyle(GymTheme.secondaryText)
                        .frame(width: 40, height: 40)
                }
                .buttonStyle(.plain)
            }

            HStack(spacing: 14) {
                Text(set.isWarmup
                     ? "Warm-up \(set.setIndex) von \(set.totalSetsForExercise)"
                     : "Satz \(set.setIndex) von \(set.totalSetsForExercise)")
                Text("·")
                Text(set.reps.displayText)
                if set.enforcesRest {
                    Text("·")
                    Text(set.pause.displayText)
                }
                Spacer()
            }
            .font(.system(size: 14, weight: .medium))
            .foregroundStyle(GymTheme.secondaryText)

            ProgressView(
                value: Double(controller.completedSetCount),
                total: Double(max(1, controller.plannedSetCount))
            )
            .tint(mode.accent)
        }
        .padding(.horizontal, 20)
        .padding(.top, 12)
        .confirmationDialog(
            "Session beenden?",
            isPresented: $showAbortConfirm,
            titleVisibility: .visible
        ) {
            Button("Vorzeitig beenden und Fotos machen") { controller.finishEarly() }
            Button("Abbrechen und verwerfen", role: .destructive) { controller.abort() }
            Button("Weiter trainieren", role: .cancel) {}
        }
    }

    private func exerciseName(_ set: PlannedSet) -> String {
        controller.exercise(for: set)?.name ?? set.exerciseID
    }
}

// MARK: - Eintragen

/// Die Eingabe blendet den Timer aus -- aber die Pause läuft im Hintergrund
/// weiter und erscheint danach mit der Restzeit.
private struct LoggingScreen: View {
    @ObservedObject var controller: SessionController
    let context: SessionPhase.LoggingContext

    @State private var reps: Double = 0
    @State private var weight: Double = 0
    @State private var disturbances: [DisturbanceMarker] = []
    @State private var didPrefill = false

    private var step: Double {
        controller.exercise(for: context.set)?.weightStep.kilograms ?? 2.5
    }

    var body: some View {
        VStack(spacing: 0) {
            VStack(spacing: 4) {
                Text(controller.exercise(for: context.set)?.name ?? context.set.exerciseID)
                    .font(.system(size: 22, weight: .bold))
                    .foregroundStyle(GymTheme.primaryText)
                HStack(spacing: 8) {
                    Text(context.set.isWarmup
                         ? "Warm-up \(context.set.setIndex)"
                         : "Satz \(context.set.setIndex)")
                    if let duration = context.duration {
                        Text("·")
                        Text("\(Int(duration)) s gebraucht")
                    } else {
                        Text("· Dauer nicht gemessen")
                    }
                }
                .font(.system(size: 14))
                .foregroundStyle(GymTheme.secondaryText)
            }
            .padding(.top, 24)

            Spacer()

            VStack(spacing: 34) {
                NumberStepper(
                    title: "Wiederholungen",
                    unit: context.set.reps.displayText,
                    value: $reps,
                    step: 1,
                    format: { String(Int($0)) }
                )
                NumberStepper(
                    title: "Gewicht",
                    unit: "kg",
                    value: $weight,
                    step: step,
                    format: { $0.kgText }
                )
            }

            Spacer()

            VStack(spacing: 12) {
                PrimaryButton(title: "Eintragen", mode: .entry) {
                    controller.submit(
                        reps: Int(reps),
                        weight: weight,
                        disturbances: disturbances
                    )
                }
                DisturbanceButton(selected: disturbances) { marker in
                    disturbances.append(marker)
                }
            }
            .padding(.horizontal, 20)
            .padding(.bottom, 24)
        }
        .onAppear {
            guard !didPrefill else { return }
            didPrefill = true
            reps = Double(controller.prefilledReps)
            weight = controller.prefilledWeight
        }
    }
}

// MARK: - Störung markieren

/// „Nicht typisch“ -- ein Tap, dann ein Grund. Nie Pflicht.
struct DisturbanceButton: View {
    var selected: [DisturbanceMarker] = []
    let onSelect: (DisturbanceMarker) -> Void

    @State private var showOptions = false

    var body: some View {
        Button {
            showOptions = true
        } label: {
            HStack(spacing: 8) {
                Image(systemName: selected.isEmpty ? "flag" : "flag.fill")
                Text(selected.isEmpty
                     ? "Nicht typisch"
                     : "Markiert: \(selected.map(\.reason.displayName).joined(separator: ", "))")
            }
            .font(.system(size: 15, weight: .medium))
            .foregroundStyle(GymTheme.secondaryText)
            .frame(maxWidth: .infinity)
            .frame(height: 48)
            .overlay(
                RoundedRectangle(cornerRadius: 14)
                    .stroke(GymTheme.stroke, lineWidth: 1)
            )
        }
        .buttonStyle(.plain)
        .confirmationDialog("Was war nicht typisch?", isPresented: $showOptions, titleVisibility: .visible) {
            ForEach(DisturbanceReason.allCases, id: \.self) { reason in
                Button(reason.displayName) {
                    onSelect(
                        DisturbanceMarker(
                            scope: reason.category == .botchedSet ? .set : .pause,
                            reason: reason
                        )
                    )
                }
            }
            Button("Abbrechen", role: .cancel) {}
        }
    }
}

// MARK: - Übung überspringen oder ersetzen

private struct ExerciseOptionsSheet: View {
    @EnvironmentObject private var store: Store
    @ObservedObject var controller: SessionController
    let set: PlannedSet
    @Environment(\.dismiss) private var dismiss

    @State private var reason: SkipReason = .equipmentBusy

    var body: some View {
        NavigationStack {
            List {
                Section("Grund") {
                    Picker("Grund", selection: $reason) {
                        ForEach(SkipReason.allCases, id: \.self) { value in
                            Text(value.displayName).tag(value)
                        }
                    }
                    .pickerStyle(.segmented)
                }

                Section {
                    Button("Übung überspringen") {
                        controller.skipExercise(reason: reason)
                        dismiss()
                    }
                } footer: {
                    Text("Wird als übersprungen mit Grund gespeichert -- nicht als Satz mit 0 kg. Sonst würde die Analyse auf falsche Ursachen kommen.")
                }

                Section("Durch andere Übung ersetzen") {
                    ForEach(alternatives, id: \.id) { exercise in
                        Button(exercise.name) {
                            controller.replaceExercise(with: exercise.id, reason: reason)
                            dismiss()
                        }
                    }
                }
            }
            .navigationTitle("Übung")
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Zurück") { dismiss() }
                }
            }
        }
    }

    /// Bekannte Ersatzübungen zuerst, danach alles andere.
    private var alternatives: [Exercise] {
        let plan = store.currentPlan
        guard let current = plan.exercise(id: set.exerciseID) else { return [] }
        let known = current.knownAlternatives.compactMap { plan.exercise(id: $0) }
        let rest = plan.exercises.filter {
            $0.id != current.id && !current.knownAlternatives.contains($0.id)
        }
        return known + rest
    }
}
