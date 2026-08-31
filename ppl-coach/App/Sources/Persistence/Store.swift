import Foundation
import PPLCoachCore

/// Alles, was die App dauerhaft behält.
///
/// Bewusst ein dateibasierter Speicher und kein SwiftData-Modell: die Typen im
/// `Core`-Package sind schon `Codable` und die einzige Quelle der Wahrheit.
/// Ein zweites Modell in der App wäre eine Fehlerquelle ohne Gegenwert, und der
/// Export nutzt exakt dieselbe Struktur.
@MainActor
final class Store: ObservableObject {
    @Published private(set) var planVersions: [PlanVersion]
    @Published private(set) var sessions: [SessionRecord]
    @Published private(set) var dailyContexts: [DailyContext]
    @Published private(set) var bodyweight: [BodyweightRecord]
    @Published private(set) var photos: [PhotoRecord]
    @Published private(set) var trials: [Trial]
    /// Offene Session, die nach Sperre oder Absturz fortgesetzt wird.
    @Published private(set) var openSnapshot: SessionRuntime.Snapshot?
    /// Detektoren, zu denen „stimmt nicht“ gesagt wurde.
    @Published private(set) var dampenedDetectorIDs: Set<String>

    private let fileManager = FileManager.default
    private let directory: URL

    init(directory: URL? = nil) {
        // Erst lokal auflösen: vor dem Ende der Initialisierung darf `self`
        // nicht gelesen werden.
        let resolved = directory ?? Store.defaultDirectory()
        self.directory = resolved
        let loaded = Store.load(from: resolved)
        self.planVersions = loaded.planVersions.isEmpty
            ? [DefaultPlan.version(createdAt: Date())]
            : loaded.planVersions
        self.sessions = loaded.sessions
        self.dailyContexts = loaded.dailyContexts
        self.bodyweight = loaded.bodyweight
        self.photos = loaded.photos
        self.trials = loaded.trials
        self.openSnapshot = loaded.openSnapshot
        self.dampenedDetectorIDs = loaded.dampenedDetectorIDs
    }

    // MARK: - Ablageorte

    static func defaultDirectory() -> URL {
        let base = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
        let directory = base.appendingPathComponent("PPLCoach", isDirectory: true)
        try? FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        return directory
    }

    /// Fotos liegen im App-Container, nicht in der Foto-Bibliothek.
    var photoDirectory: URL {
        let directory = self.directory.appendingPathComponent("Photos", isDirectory: true)
        try? fileManager.createDirectory(at: directory, withIntermediateDirectories: true)
        return directory
    }

    func photoURL(for photo: PhotoRecord) -> URL {
        photoDirectory.appendingPathComponent(photo.fileName)
    }

    private var stateURL: URL { directory.appendingPathComponent("state.json") }

    // MARK: - Plan

    var currentPlan: PlanVersion {
        planVersions.max { $0.createdAt < $1.createdAt } ?? DefaultPlan.version()
    }

    func plan(id: String) -> PlanVersion? {
        planVersions.first { $0.id == id }
    }

    /// Jede Änderung in „Mein Plan“ erzeugt eine neue Version. Alte Sessions
    /// bleiben damit gegen die damals gültige Vorgabe vergleichbar.
    func savePlan(_ updated: PlanVersion) {
        var version = updated
        if version.id == currentPlan.id {
            version = PlanVersion(
                id: "\(DefaultPlan.versionID)-\(Int(Date().timeIntervalSince1970))",
                createdAt: Date(),
                exercises: updated.exercises,
                days: updated.days
            )
        }
        planVersions.append(version)
        persist()
    }

    // MARK: - Trainingstag-Warteschlange

    /// Nächster Tag im Zyklus, nicht nach Wochentag. Ein verpasster Pull-Tag
    /// bleibt der nächste Tag, sonst kippt der Split still.
    var nextDayInQueue: TrainingDay {
        guard let last = sessions
            .filter({ $0.status == .completed })
            .max(by: { $0.startedAt < $1.startedAt }) else {
            return .push
        }
        return last.day.next
    }

    // MARK: - Sessions

    func save(_ session: SessionRecord) {
        if let index = sessions.firstIndex(where: { $0.id == session.id }) {
            sessions[index] = session
        } else {
            sessions.append(session)
        }
        persist()
    }

    /// Zustand nach jedem Tap sichern -- Sperre, Anruf und Absturz dürfen die
    /// Restpause und die offene Eingabe nicht löschen.
    func saveOpen(_ snapshot: SessionRuntime.Snapshot) {
        openSnapshot = snapshot
        if let index = sessions.firstIndex(where: { $0.id == snapshot.session.id }) {
            sessions[index] = snapshot.session
        } else {
            sessions.append(snapshot.session)
        }
        persist()
    }

    func clearOpenSession() {
        openSnapshot = nil
        persist()
    }

    func lastSets(exerciseID: String) -> [SetRecord] {
        sessions
            .filter { $0.status == .completed }
            .sorted { $0.startedAt > $1.startedAt }
            .first { session in
                session.sets.contains { $0.exerciseID == exerciseID && $0.countsForPerformance }
            }?
            .sets
            .filter { $0.exerciseID == exerciseID && $0.countsForPerformance } ?? []
    }

    // MARK: - Kontext, Fotos, Gewicht

    func merge(contexts: [DailyContext]) {
        for context in contexts {
            if let index = dailyContexts.firstIndex(where: { $0.cycleID == context.cycleID }) {
                dailyContexts[index] = context
            } else {
                dailyContexts.append(context)
            }
        }
        // Baselines neu rechnen -- Rohwerte allein sagen wenig.
        dailyContexts = WhoopContextMapper.withBaselines(dailyContexts)
        persist()
    }

    func add(_ photo: PhotoRecord) {
        photos.append(photo)
        persist()
    }

    /// Vorgängerfoto desselben Slots -- Schablone beim Auslösen und
    /// Vergleichspartner in der Timeline.
    func lastPhoto(slot: PhotoSlot) -> PhotoRecord? {
        photos.filter { $0.slot == slot }.max { $0.takenAt < $1.takenAt }
    }

    func add(_ record: BodyweightRecord) {
        bodyweight.append(record)
        persist()
    }

    var latestBodyweight: Double? {
        bodyweight.max { $0.date < $1.date }?.kilograms
    }

    // MARK: - Proben

    func save(_ trial: Trial) {
        if let index = trials.firstIndex(where: { $0.id == trial.id }) {
            trials[index] = trial
        } else {
            trials.append(trial)
        }
        persist()
    }

    var runningTrials: [Trial] {
        trials.filter { $0.status == .running }
    }

    /// Läuft für den kommenden Tag eine Probe? Dann werden die Sessions markiert.
    func activeTrial(for day: TrainingDay) -> Trial? {
        runningTrials.first { trial in
            trial.intervention.affectedDays(in: currentPlan).contains(day)
        }
    }

    // MARK: - Rückmeldung zu Karten

    func recordFeedback(_ feedback: CardFeedback, detectorID: String) {
        switch feedback {
        case .wrong:
            dampenedDetectorIDs.insert(detectorID)
        case .correct, .willTry:
            dampenedDetectorIDs.remove(detectorID)
        }
        persist()
    }

    // MARK: - Analyse

    func analysisInput() -> AnalysisInput {
        AnalysisInput(
            planVersion: currentPlan,
            sessions: sessions,
            dailyContexts: dailyContexts,
            bodyweight: bodyweight,
            photos: photos
        )
    }

    // MARK: - Export

    func makeExport() -> HistoryExport {
        HistoryExporter.makeExport(
            planVersions: planVersions,
            sessions: sessions,
            dailyContexts: dailyContexts,
            bodyweight: bodyweight,
            photos: photos,
            trials: trials
        )
    }

    func writeExport() throws -> URL {
        let data = try HistoryExporter.encode(makeExport())
        let url = fileManager.temporaryDirectory
            .appendingPathComponent("ppl-coach-export.json")
        try data.write(to: url, options: .atomic)
        return url
    }

    func writeCSV() throws -> URL {
        let csv = HistoryExporter.setsCSV(sessions: sessions)
        let url = fileManager.temporaryDirectory
            .appendingPathComponent("ppl-coach-saetze.csv")
        try Data(csv.utf8).write(to: url, options: .atomic)
        return url
    }

    // MARK: - Laden und Speichern

    private struct State: Codable {
        var planVersions: [PlanVersion] = []
        var sessions: [SessionRecord] = []
        var dailyContexts: [DailyContext] = []
        var bodyweight: [BodyweightRecord] = []
        var photos: [PhotoRecord] = []
        var trials: [Trial] = []
        var openSnapshot: SessionRuntime.Snapshot?
        var dampenedDetectorIDs: Set<String> = []
    }

    private static func load(from directory: URL) -> State {
        let url = directory.appendingPathComponent("state.json")
        guard let data = try? Data(contentsOf: url) else { return State() }
        do {
            return try HistoryExporter.decoder().decode(State.self, from: data)
        } catch {
            // Lieber leer starten als abstürzen; die Datei bleibt als Sicherung
            // liegen und kann später von Hand geprüft werden.
            let backup = directory.appendingPathComponent("state-unreadable.json")
            try? data.write(to: backup, options: .atomic)
            return State()
        }
    }

    private func persist() {
        let state = State(
            planVersions: planVersions,
            sessions: sessions,
            dailyContexts: dailyContexts,
            bodyweight: bodyweight,
            photos: photos,
            trials: trials,
            openSnapshot: openSnapshot,
            dampenedDetectorIDs: dampenedDetectorIDs
        )
        do {
            let data = try HistoryExporter.encoder().encode(state)
            // Atomar schreiben, damit ein Absturz mitten im Speichern die
            // Historie nicht zerstört.
            try data.write(to: stateURL, options: .atomic)
        } catch {
            assertionFailure("Speichern fehlgeschlagen: \(error)")
        }
    }
}
