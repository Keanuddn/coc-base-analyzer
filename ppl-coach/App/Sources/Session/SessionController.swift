import Foundation
import Combine
import PPLCoachCore

#if canImport(UIKit)
import UIKit
#endif

/// Bindet die Zustandsmaschine aus dem `Core`-Package an die Oberfläche.
///
/// Die Uhr in der Anzeige ist **nur Anzeige**. Pause und Satzdauer werden
/// jederzeit aus Zeitstempeln neu berechnet, damit sie Sperre, Anruf und
/// Absturz überleben.
@MainActor
final class SessionController: ObservableObject {
    @Published private(set) var phase: SessionPhase = .awaitingReadiness
    @Published private(set) var recommendation: LoadRecommendation?
    @Published private(set) var lastSets: [SetRecord] = []
    /// Läuft nur, solange etwas anzuzeigen ist -- treibt keine Logik.
    @Published private(set) var now: Date = Date()

    private var runtime: SessionRuntime?
    private let store: Store
    private let recommender = LoadRecommender()
    private var ticker: AnyCancellable?
    private var restEndNotified = false

    init(store: Store) {
        self.store = store
    }

    var session: SessionRecord? { runtime?.session }
    var plannedSetCount: Int { runtime?.plannedSets.count ?? 0 }
    var completedSetCount: Int { runtime?.session.sets.count ?? 0 }

    var isRunning: Bool {
        switch phase {
        case .finished, .aborted: return false
        default: return runtime != nil
        }
    }

    // MARK: - Start und Fortsetzen

    func start(day: TrainingDay) {
        let trial = store.activeTrial(for: day)
        let runtime = SessionRuntime(
            day: day,
            planVersion: store.currentPlan,
            startedAt: Date(),
            trialID: trial?.id
        )
        adopt(runtime)
        keepScreenAwake(true)
    }

    /// Setzt eine offene Session fort. Die Restpause ergibt sich aus den
    /// Zeitstempeln -- eine Pause, die währenddessen ablief, ist abgelaufen.
    func resumeIfPossible() {
        guard let snapshot = store.openSnapshot else { return }
        // Die Session behält die Planfassung, mit der sie gestartet ist.
        let plan = store.plan(id: snapshot.session.planVersionID) ?? store.currentPlan
        adopt(SessionRuntime(restoring: snapshot, planVersion: plan))
        keepScreenAwake(true)
    }

    private func adopt(_ runtime: SessionRuntime) {
        self.runtime = runtime
        syncFromRuntime()
        startTicker()
    }

    // MARK: - Aktionen

    func setReadiness(_ readiness: Readiness) {
        runtime?.setReadiness(readiness)
        syncFromRuntime()
    }

    func startSet() {
        try? runtime?.startSet(at: Date())
        Haptics.tap()
        syncFromRuntime()
    }

    func stopSet() {
        try? runtime?.stopSet(at: Date())
        restEndNotified = false
        Haptics.tap()
        syncFromRuntime()
    }

    func submit(reps: Int, weight: Double, disturbances: [DisturbanceMarker]) {
        try? runtime?.submit(
            SetEntry(reps: reps, weight: weight, disturbances: disturbances),
            at: Date()
        )
        Haptics.success()
        syncFromRuntime()
    }

    func finishRest() {
        try? runtime?.finishRest()
        syncFromRuntime()
    }

    func skipSet() {
        try? runtime?.skipCurrentSet()
        syncFromRuntime()
    }

    func skipExercise(reason: SkipReason) {
        try? runtime?.skipCurrentExercise(reason: reason)
        syncFromRuntime()
    }

    func replaceExercise(with exerciseID: String, reason: SkipReason) {
        try? runtime?.replaceCurrentExercise(with: exerciseID, reason: reason)
        syncFromRuntime()
    }

    func markLastSet(_ marker: DisturbanceMarker) {
        runtime?.markLastSet(marker)
        syncFromRuntime()
    }

    func correctLastSet(reps: Int, weight: Double) {
        runtime?.correctLastSet(reps: reps, weight: weight)
        syncFromRuntime()
    }

    func finishEarly() {
        runtime?.finishEarly(at: Date())
        syncFromRuntime()
    }

    func completePhotos(tag: SessionTag) {
        runtime?.completePhotos(at: Date(), tag: tag)
        finishUp()
    }

    func abort() {
        runtime?.abort(at: Date())
        finishUp()
    }

    // MARK: - Anzeige

    /// Restzeit der Pause. Wird aus der Wanduhr berechnet, nicht heruntergezählt.
    func restRemaining() -> TimeInterval? {
        switch phase {
        case let .resting(context):
            return context.remaining(at: now)
        case let .logging(context):
            guard let end = context.restTargetEnd else { return nil }
            return max(0, end.timeIntervalSince(now))
        default:
            return nil
        }
    }

    /// Laufende Satzdauer, nur zur Anzeige.
    func elapsedSetDuration() -> TimeInterval? {
        guard case let .setRunning(_, startedAt) = phase else { return nil }
        return now.timeIntervalSince(startedAt)
    }

    func exercise(for set: PlannedSet) -> Exercise? {
        store.currentPlan.exercise(id: set.exerciseID)
    }

    /// Vorbelegung des Gewichtsfeldes: die aktuelle Empfehlung. Es gibt keinen
    /// Übernehmen-Knopf -- was du einträgst, ist die Entscheidung.
    var prefilledWeight: Double {
        recommendation?.weight ?? 0
    }

    var prefilledReps: Int {
        guard let set = currentPlannedSet() else { return 0 }
        if let goal = recommendation?.repsGoal { return goal }
        return set.reps.upperBound ?? 0
    }

    func currentPlannedSet() -> PlannedSet? {
        switch phase {
        case let .preview(set): return set
        case let .setRunning(set, _): return set
        case let .logging(context): return context.set
        case let .resting(context): return context.nextSet
        default: return nil
        }
    }

    // MARK: - Intern

    private func syncFromRuntime() {
        guard let runtime else { return }
        phase = runtime.phase
        updateRecommendation()
        store.saveOpen(runtime.snapshot())
    }

    private func updateRecommendation() {
        guard let runtime,
              let set = currentPlannedSet(),
              let exercise = store.currentPlan.exercise(id: set.exerciseID) else {
            recommendation = nil
            lastSets = []
            return
        }

        lastSets = store.lastSets(exerciseID: exercise.id)
        recommendation = recommender.recommend(
            exercise: exercise,
            target: set.reps,
            history: store.sessions,
            todaySets: runtime.setsSoFar(exerciseID: exercise.id),
            fallbackWeight: lastSets.first?.weight
        )
    }

    private func startTicker() {
        ticker = Timer.publish(every: 0.5, on: .main, in: .common)
            .autoconnect()
            .sink { [weak self] date in
                guard let self else { return }
                self.now = date
                self.notifyRestEndIfNeeded()
            }
    }

    /// Pausenende muss man **fühlen** -- das Handy liegt in der Pause nicht in
    /// der Hand.
    private func notifyRestEndIfNeeded() {
        guard case let .resting(context) = phase else { return }
        guard !restEndNotified, context.isOver(at: now) else { return }
        restEndNotified = true
        Haptics.restFinished()
    }

    private func finishUp() {
        if let session = runtime?.session {
            store.save(session)
        }
        store.clearOpenSession()
        phase = runtime?.phase ?? .finished
        ticker?.cancel()
        ticker = nil
        keepScreenAwake(false)
        runtime = nil
    }

    /// Während einer offenen Session bleibt der Bildschirm an.
    private func keepScreenAwake(_ enabled: Bool) {
        #if canImport(UIKit)
        UIApplication.shared.isIdleTimerDisabled = enabled
        #endif
    }
}
