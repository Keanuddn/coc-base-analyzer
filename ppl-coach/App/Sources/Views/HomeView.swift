import SwiftUI
import PPLCoachCore

/// Ein großer Knopf, plus der nächste Tag in der Warteschlange. Alles andere
/// liegt im Menü daneben.
struct HomeView: View {
    @EnvironmentObject private var store: Store
    @ObservedObject var controller: SessionController

    @State private var selectedDay: TrainingDay?
    @State private var showDayPicker = false

    private var nextDay: TrainingDay {
        selectedDay ?? store.nextDayInQueue
    }

    var body: some View {
        NavigationStack {
            ZStack {
                GymTheme.Mode.entry.background.ignoresSafeArea()

                VStack(spacing: 0) {
                    if store.openSnapshot != nil {
                        resumeBanner
                    }

                    Spacer()

                    VStack(spacing: 10) {
                        Text("NÄCHSTES TRAINING")
                            .font(.system(size: 13, weight: .semibold))
                            .tracking(1.6)
                            .foregroundStyle(GymTheme.secondaryText)

                        Text(nextDay.displayName)
                            .font(.system(size: 44, weight: .bold, design: .rounded))
                            .foregroundStyle(GymTheme.primaryText)

                        Button("Anderer Tag") { showDayPicker = true }
                            .font(.system(size: 15))
                            .foregroundStyle(GymTheme.Mode.work.accent)
                    }

                    if let trial = store.activeTrial(for: nextDay) {
                        trialBanner(trial)
                    }

                    Spacer()

                    lastSessionSummary

                    Spacer()

                    PrimaryButton(title: "Training starten", mode: .work) {
                        controller.start(day: nextDay)
                    }
                    .padding(.horizontal, 20)
                    .padding(.bottom, 12)

                    menuRow
                        .padding(.bottom, 20)
                }
            }
            .navigationTitle("PPL Coach")
            .navigationBarTitleDisplayMode(.inline)
            .preferredColorScheme(.dark)
            .confirmationDialog("Trainingstag wählen", isPresented: $showDayPicker) {
                ForEach(TrainingDay.allCases, id: \.self) { day in
                    Button(day.displayName) { selectedDay = day }
                }
                Button("Abbrechen", role: .cancel) {}
            }
        }
    }

    private var resumeBanner: some View {
        Button {
            controller.resumeIfPossible()
        } label: {
            HStack(spacing: 10) {
                Image(systemName: "arrow.clockwise")
                VStack(alignment: .leading, spacing: 2) {
                    Text("Offene Session fortsetzen")
                        .font(.system(size: 16, weight: .semibold))
                    Text("Restpause und offene Eingabe sind erhalten")
                        .font(.system(size: 13))
                        .foregroundStyle(GymTheme.secondaryText)
                }
                Spacer()
            }
            .foregroundStyle(GymTheme.primaryText)
            .padding(16)
            .background(GymTheme.surface, in: RoundedRectangle(cornerRadius: 16))
            .padding(.horizontal, 20)
            .padding(.top, 12)
        }
        .buttonStyle(.plain)
    }

    private func trialBanner(_ trial: Trial) -> some View {
        VStack(spacing: 6) {
            Text("PROBE LÄUFT")
                .font(.system(size: 12, weight: .bold))
                .tracking(1.4)
                .foregroundStyle(GymTheme.Mode.rest.accent)
            Text(trial.intervention.displayText)
                .font(.system(size: 15, weight: .medium))
                .foregroundStyle(GymTheme.primaryText)
                .multilineTextAlignment(.center)
        }
        .padding(14)
        .frame(maxWidth: .infinity)
        .background(GymTheme.surface, in: RoundedRectangle(cornerRadius: 16))
        .padding(.horizontal, 20)
        .padding(.top, 20)
    }

    private var lastSessionSummary: some View {
        Group {
            if let last = store.sessions
                .filter({ $0.status == .completed })
                .max(by: { $0.startedAt < $1.startedAt }) {
                let summary = Metrics.summarize(session: last)
                HStack(spacing: 28) {
                    statistic("Letztes Mal", last.day.displayName)
                    statistic("Sätze", "\(summary.workSetCount)")
                    if let duration = summary.duration {
                        statistic("Dauer", "\(Int(duration / 60)) min")
                    }
                }
            } else {
                Text("Noch keine Session aufgezeichnet")
                    .font(.system(size: 14))
                    .foregroundStyle(GymTheme.secondaryText)
            }
        }
    }

    private func statistic(_ label: String, _ value: String) -> some View {
        VStack(spacing: 4) {
            Text(value)
                .font(.system(size: 20, weight: .semibold).monospacedDigit())
                .foregroundStyle(GymTheme.primaryText)
            Text(label)
                .font(.system(size: 12))
                .foregroundStyle(GymTheme.secondaryText)
        }
    }

    private var menuRow: some View {
        HStack(spacing: 10) {
            menuLink("Verlauf", "chart.line.uptrend.xyaxis") { HistoryView() }
            menuLink("Erkenntnisse", "lightbulb") { InsightsView() }
            menuLink("Fotos", "camera") { PhotoTimelineView() }
            menuLink("Mein Plan", "slider.horizontal.3") { MyPlanView() }
            menuLink("Mehr", "gearshape") { SettingsView() }
        }
        .padding(.horizontal, 20)
    }

    private func menuLink<Destination: View>(
        _ title: String,
        _ icon: String,
        @ViewBuilder destination: @escaping () -> Destination
    ) -> some View {
        NavigationLink {
            destination()
        } label: {
            VStack(spacing: 6) {
                Image(systemName: icon)
                    .font(.system(size: 18, weight: .medium))
                Text(title)
                    .font(.system(size: 11))
            }
            .foregroundStyle(GymTheme.secondaryText)
            .frame(maxWidth: .infinity)
            .frame(height: 62)
            .background(GymTheme.surface, in: RoundedRectangle(cornerRadius: 14))
        }
        .buttonStyle(.plain)
    }
}

/// Ein Tap direkt nach „Training starten“: Gut / Okay / Schlecht.
///
/// Bleibt trotz Whoop, weil sich subjektives Gefühl und Recovery-Score häufig
/// widersprechen -- und genau dieser Widerspruch ein eigenes Signal ist.
struct ReadinessView: View {
    let onSelect: (Readiness) -> Void

    var body: some View {
        VStack(spacing: 40) {
            Spacer()

            VStack(spacing: 10) {
                Text("Wie fühlst du dich jetzt?")
                    .font(.system(size: 28, weight: .bold))
                    .foregroundStyle(GymTheme.primaryText)
                Text("Ein Tap, dann geht es los.")
                    .font(.system(size: 15))
                    .foregroundStyle(GymTheme.secondaryText)
            }

            VStack(spacing: 14) {
                ForEach(Readiness.allCases, id: \.self) { readiness in
                    Button {
                        Haptics.tap()
                        onSelect(readiness)
                    } label: {
                        Text(readiness.displayName)
                            .font(.system(size: 24, weight: .bold, design: .rounded))
                            .foregroundStyle(GymTheme.primaryText)
                            .frame(maxWidth: .infinity)
                            .frame(height: 84)
                            .background(GymTheme.surface, in: RoundedRectangle(cornerRadius: 18))
                    }
                    .buttonStyle(.plain)
                }
            }
            .padding(.horizontal, 24)

            Spacer()
        }
    }
}

/// Kurzer Abschluss mit den Zahlen der Session.
struct SessionSummaryView: View {
    @EnvironmentObject private var store: Store
    @ObservedObject var controller: SessionController

    var body: some View {
        VStack(spacing: 26) {
            Spacer()
            Image(systemName: "checkmark.circle")
                .font(.system(size: 56, weight: .light))
                .foregroundStyle(GymTheme.Mode.work.accent)

            Text("Session gespeichert")
                .font(.system(size: 26, weight: .bold))
                .foregroundStyle(GymTheme.primaryText)

            if let session = store.sessions.max(by: { $0.startedAt < $1.startedAt }) {
                let summary = Metrics.summarize(session: session)
                VStack(spacing: 10) {
                    row("Arbeitssätze", "\(summary.workSetCount)")
                    row("Volumen", "\(Int(summary.totalVolume)) kg")
                    if let duration = summary.duration {
                        row("Dauer", "\(Int(duration / 60)) min")
                    }
                    if let deviation = summary.averagePauseDeviation {
                        row(
                            "Pausenabweichung",
                            "\(deviation > 0 ? "+" : "")\(Int(deviation)) s"
                        )
                    }
                }
                .padding(20)
                .background(GymTheme.surface, in: RoundedRectangle(cornerRadius: 18))
                .padding(.horizontal, 24)
            }

            Spacer()
        }
    }

    private func row(_ label: String, _ value: String) -> some View {
        HStack {
            Text(label)
                .foregroundStyle(GymTheme.secondaryText)
            Spacer()
            Text(value)
                .font(.system(size: 17, weight: .semibold).monospacedDigit())
                .foregroundStyle(GymTheme.primaryText)
        }
        .font(.system(size: 15))
    }
}
