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
        let rawPlans = loaded.planVersions
        let migratedPlans = (rawPlans.isEmpty
            ? [DefaultPlan.version(createdAt: Date())]
            : rawPlans).map { $0.fillingMissingWarmupLoadFractions() }
        self.planVersions = migratedPlans
        self.sessions = loaded.sessions
        self.dailyContexts = loaded.dailyContexts
        self.bodyweight = loaded.bodyweight
        self.photos = loaded.photos
        self.trials = loaded.trials
        self.openSnapshot = loaded.openSnapshot
        self.dampenedDetectorIDs = loaded.dampenedDetectorIDs
        if !rawPlans.isEmpty, migratedPlans != rawPlans {
            persist()
        }
    }

    // MARK: - Ablageorte

    /// Ablage möglichst in iCloud, sonst lokal.
    ///
    /// Ein verlorenes iPhone darf nicht die ganze Historie samt Fotos kosten.
    /// Steht iCloud nicht bereit, arbeitet die App lokal weiter -- die
    /// Sicherung ist wichtig, aber sie darf das Training nicht blockieren.
    static func defaultDirectory() -> URL {
        let manager = FileManager.default

        if let container = manager.url(forUbiquityContainerIdentifier: nil) {
            let directory = container
                .appendingPathComponent("Documents", isDirectory: true)
                .appendingPathComponent("PPLCoach", isDirectory: true)
            do {
                try manager.createDirectory(at: directory, withIntermediateDirectories: true)
                return directory
            } catch {
                // Fällt auf den lokalen Ordner zurück.
            }
        }

        let base = manager.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
        let directory = base.appendingPathComponent("PPLCoach", isDirectory: true)
        try? manager.createDirectory(at: directory, withIntermediateDirectories: true)
        return directory
    }

    /// Liegt die Ablage in iCloud? Wird in den Einstellungen angezeigt, damit
    /// nicht stillschweigend ungesichert gearbeitet wird.
    var isBackedUpToICloud: Bool {
        directory.path.contains("Mobile Documents")
            || directory.path.contains("CloudDocs")
    }

    /// Schiebt neu geschriebene Dateien aktiv in die Cloud, statt auf einen
    /// günstigen Moment zu warten.
    private func requestUpload(of url: URL) {
        guard isBackedUpToICloud else { return }
        try? fileManager.startDownloadingUbiquitousItem(at: url)
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

    /// Trägt eine Störung nachträglich an einem beliebigen Satz nach -- auch
    /// Tage später im Verlauf, nicht nur während der Session.
    func markSet(sessionID: UUID, setID: UUID, marker: DisturbanceMarker) {
        guard let sessionIndex = sessions.firstIndex(where: { $0.id == sessionID }),
              let setIndex = sessions[sessionIndex].sets.firstIndex(where: { $0.id == setID })
        else { return }
        sessions[sessionIndex].sets[setIndex].disturbances.append(marker)
        persist()
    }

    /// Wertet alle laufenden Proben aus, deren Sessions vollständig sind.
    func evaluateRunningTrials() -> [TrialResult] {
        let planner = TrialPlanner()
        var results: [TrialResult] = []

        for trial in runningTrials {
            var updated = trial
            // Sessions, die während der Probe gelaufen sind, nachtragen.
            updated.sessionIDs = sessions
                .filter { $0.trialID == trial.id && $0.status == .completed }
                .map(\.id)

            guard let result = planner.evaluate(
                trial: updated,
                history: sessions,
                planVersion: currentPlan
            ) else {
                save(updated)
                continue
            }

            updated.status = .evaluated
            save(updated)
            results.append(result)
        }

        return results
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

    // MARK: - Simulator

    /// Füllt den Speicher mit synthetischen Wochen, damit Verlauf und
    /// Erkenntnisse im Simulator etwas zu zeigen haben. Echte Sessions bleiben
    /// unangetastet, bis du das bewusst auslöst.
    func loadSimulatorSample(weeks: Int = 8) {
        var generator = SyntheticHistoryGenerator(
            planVersion: currentPlan,
            truth: SyntheticTruth(
                repLossFromShortPause: 1.6,
                shortPauseProbability: 0.22,
                tempoDriftPerWeek: 0.05,
                repLossPerSetIndex: 0.35,
                progressesLoad: true
            ),
            seed: 7
        )
        let start = Date().addingTimeInterval(-Double(weeks) * 7 * 86_400)
        sessions = generator.generate(weeks: weeks, startingAt: start)
        dailyContexts = generator.dailyContexts(for: sessions)
        persist()
    }

    /// Leert Sessions, Kontext, Fotos und Proben -- Planfassungen bleiben.
    func resetLoggedData() {
        sessions = []
        dailyContexts = []
        bodyweight = []
        photos = []
        trials = []
        openSnapshot = nil
        persist()
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
            requestUpload(of: stateURL)
        } catch {
            assertionFailure("Speichern fehlgeschlagen: \(error)")
        }
    }
}
