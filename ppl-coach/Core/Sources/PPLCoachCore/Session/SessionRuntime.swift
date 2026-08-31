import Foundation

/// Sichtbarer Zustand der geführten Session.
///
/// Der Rhythmus ist bewusst genau dieser:
///
/// `preview` → Satz starten → `setRunning` → Satz stoppen → `logging`
/// (Pausen-Timer läuft im Hintergrund weiter) → Eingabe bestätigen →
/// `resting` mit **Restzeit** → Pause vorbei → `preview` des nächsten Satzes.
///
/// Der Satz-Timer startet **nie** von allein: sonst würde der Weg zur Maschine
/// als Arbeitszeit gezählt und "80 kg × 8 in 22 s" wäre wertlos.
public enum SessionPhase: Equatable, Sendable {
    /// Ein Tap: Gut / Okay / Schlecht. Danach geht es in den ersten Satz.
    case awaitingReadiness
    /// Übung, Satz x von n, letzte Zahlen, Empfehlung. Großer Knopf "Satz starten".
    case preview(PlannedSet)
    case setRunning(PlannedSet, startedAt: Date)
    /// Eingabe von Wiederholungen und Gewicht. Die Pause läuft dabei weiter.
    case logging(LoggingContext)
    /// Pausen-Timer mit Restzeit, nach der Eingabe wieder sichtbar.
    case resting(RestingContext)
    /// Fotos in den Slots des Tages.
    case photos(day: TrainingDay, remaining: [PhotoSlot])
    case finished
    case aborted

    public struct LoggingContext: Equatable, Sendable {
        public let set: PlannedSet
        public let startedAt: Date?
        public let stoppedAt: Date
        /// Zeitpunkt, an dem die Zielpause abgelaufen wäre. nil bei Warm-ups
        /// und bei der ersten Übung eines Supersets.
        public let restTargetEnd: Date?

        public var duration: TimeInterval? {
            guard let startedAt else { return nil }
            return stoppedAt.timeIntervalSince(startedAt)
        }
    }

    public struct RestingContext: Equatable, Sendable {
        /// Der bereits geloggte Satz, nach dem pausiert wird.
        public let previousSet: PlannedSet
        public let nextSet: PlannedSet
        public let stoppedAt: Date
        public let restTargetEnd: Date

        /// Restzeit bis zum Ziel. Nach Ablauf negativ (Überziehung), nicht auf 0 geklemmt.
        public func remaining(at now: Date) -> TimeInterval {
            restTargetEnd.timeIntervalSince(now)
        }

        public func isOver(at now: Date) -> Bool {
            now >= restTargetEnd
        }
    }
}

/// Eingabe eines Satzes.
public struct SetEntry: Equatable, Sendable {
    public let reps: Int
    public let weight: Double
    public var disturbances: [DisturbanceMarker]

    public init(reps: Int, weight: Double, disturbances: [DisturbanceMarker] = []) {
        self.reps = reps
        self.weight = weight
        self.disturbances = disturbances
    }
}

public enum SessionRuntimeError: Error, Equatable {
    case wrongPhase(String)
    case noSuchExercise(String)
}

/// Führt die Session Satz für Satz und hält alle Ist-Werte.
///
/// Alle Zeiten kommen aus der **Wanduhr** (übergebene `Date`-Werte), nicht aus
/// einem laufenden Timer-Objekt. Dadurch überleben Pause und Satzdauer
/// Bildschirmsperre, Anruf und Absturz: der Rest wird jederzeit neu aus
/// Zeitstempeln berechnet.
public final class SessionRuntime {
    public private(set) var phase: SessionPhase
    public private(set) var session: SessionRecord
    public private(set) var plannedSets: [PlannedSet]

    private let planVersion: PlanVersion
    private var cursor: Int
    /// Übungen, die in dieser Session übersprungen oder ersetzt wurden.
    private var outcomes: [String: ExerciseOutcome] = [:]
    private var substitutions: [String: String] = [:]

    public init(
        day: TrainingDay,
        planVersion: PlanVersion,
        startedAt: Date,
        sessionID: UUID = UUID(),
        trialID: UUID? = nil
    ) {
        self.planVersion = planVersion
        let template = planVersion.template(for: day)
        self.plannedSets = template.map(SessionPlanFlattener.flatten) ?? []
        self.cursor = 0
        self.session = SessionRecord(
            id: sessionID,
            day: day,
            planVersionID: planVersion.id,
            startedAt: startedAt,
            trialID: trialID
        )
        self.phase = .awaitingReadiness
    }

    // MARK: - Ablauf

    /// Ein Tap am Start. Danach direkt in die erste Übung.
    public func setReadiness(_ readiness: Readiness) {
        session.readiness = readiness
        if case .awaitingReadiness = phase {
            advanceToNextPreview()
        }
    }

    /// Satz-Timer starten. Nur von Hand -- niemals automatisch.
    public func startSet(at now: Date) throws {
        guard case let .preview(set) = phase else {
            throw SessionRuntimeError.wrongPhase("startSet erwartet preview")
        }
        phase = .setRunning(set, startedAt: now)
    }

    /// Satz-Timer stoppen. Ab hier läuft die Pause, und die Eingabe erscheint.
    public func stopSet(at now: Date) throws {
        switch phase {
        case let .setRunning(set, startedAt):
            phase = .logging(
                .init(
                    set: set,
                    startedAt: startedAt,
                    stoppedAt: now,
                    restTargetEnd: set.pause.timerTarget.map { now.addingTimeInterval($0) }
                )
            )
        case let .preview(set):
            // Satz-Timer vergessen: Dauer bleibt fehlend, nicht 0.
            phase = .logging(
                .init(
                    set: set,
                    startedAt: nil,
                    stoppedAt: now,
                    restTargetEnd: set.pause.timerTarget.map { now.addingTimeInterval($0) }
                )
            )
        default:
            throw SessionRuntimeError.wrongPhase("stopSet erwartet setRunning oder preview")
        }
    }

    /// Wiederholungen und Gewicht bestätigen.
    ///
    /// Danach erscheint der Pausen-Timer wieder -- mit der **Restzeit**, weil er
    /// während der Eingabe weitergelaufen ist. Ist die Pause schon vorbei
    /// (Eingabe dauerte länger), geht es direkt zum nächsten Satz.
    public func submit(_ entry: SetEntry, at now: Date) throws {
        guard case let .logging(context) = phase else {
            throw SessionRuntimeError.wrongPhase("submit erwartet logging")
        }

        let record = SetRecord(
            sessionID: session.id,
            blockID: context.set.blockID,
            exerciseID: effectiveExerciseID(for: context.set),
            setIndex: context.set.setIndex,
            kind: context.set.kind,
            supersetRound: context.set.supersetRound,
            supersetMember: context.set.supersetMember,
            targetReps: context.set.reps,
            targetPause: context.set.pause,
            reps: entry.reps,
            weight: entry.weight,
            duration: context.duration,
            startedAt: context.startedAt,
            stoppedAt: context.stoppedAt,
            disturbances: entry.disturbances
        )
        session.sets.append(record)
        recordOutcomeIfNeeded(for: context.set)

        cursor += 1

        guard let next = nextPlannedSet() else {
            finishToPhotos(at: now)
            return
        }

        if let restEnd = context.restTargetEnd, now < restEnd {
            phase = .resting(
                .init(
                    previousSet: context.set,
                    nextSet: next,
                    stoppedAt: context.stoppedAt,
                    restTargetEnd: restEnd
                )
            )
        } else {
            phase = .preview(next)
        }
    }

    /// "Bereit" während der Pause, oder Pausenende. Gibt den nächsten Satz frei.
    public func finishRest() throws {
        guard case let .resting(context) = phase else {
            throw SessionRuntimeError.wrongPhase("finishRest erwartet resting")
        }
        phase = .preview(context.nextSet)
    }

    /// Optionalen Satz überspringen (z. B. der vierte Satz Wadenheben).
    public func skipCurrentSet() throws {
        guard case .preview = phase else {
            throw SessionRuntimeError.wrongPhase("skipCurrentSet erwartet preview")
        }
        cursor += 1
        advanceToNextPreview()
    }

    /// Ganze Übung überspringen. Wird als übersprungen mit Grund gespeichert --
    /// nicht als "0 kg", damit die Analyse nicht auf falsche Ursachen kommt.
    public func skipCurrentExercise(reason: SkipReason) throws {
        guard case let .preview(set) = phase else {
            throw SessionRuntimeError.wrongPhase("skipCurrentExercise erwartet preview")
        }
        outcomes[set.blockID] = .skipped(reason: reason)
        skipRemainingSets(ofBlock: set.blockID)
        advanceToNextPreview()
    }

    /// Übung durch eine andere ersetzen. Der Ersatz bleibt als Ersatz erkennbar.
    public func replaceCurrentExercise(with exerciseID: String, reason: SkipReason) throws {
        guard case let .preview(set) = phase else {
            throw SessionRuntimeError.wrongPhase("replaceCurrentExercise erwartet preview")
        }
        guard planVersion.exercise(id: exerciseID) != nil else {
            throw SessionRuntimeError.noSuchExercise(exerciseID)
        }
        substitutions[set.blockID] = exerciseID
        outcomes[set.blockID] = .replaced(byExerciseID: exerciseID, reason: reason)
    }

    /// Störung nachträglich am letzten Satz markieren.
    public func markLastSet(_ marker: DisturbanceMarker) {
        guard !session.sets.isEmpty else { return }
        session.sets[session.sets.count - 1].disturbances.append(marker)
    }

    /// Letzten Satz korrigieren, solange die Session offen ist.
    public func correctLastSet(reps: Int, weight: Double) {
        guard let last = session.sets.indices.last else { return }
        let old = session.sets[last]
        session.sets[last] = SetRecord(
            id: old.id,
            sessionID: old.sessionID,
            blockID: old.blockID,
            exerciseID: old.exerciseID,
            setIndex: old.setIndex,
            kind: old.kind,
            supersetRound: old.supersetRound,
            supersetMember: old.supersetMember,
            targetReps: old.targetReps,
            targetPause: old.targetPause,
            reps: reps,
            weight: weight,
            duration: old.duration,
            startedAt: old.startedAt,
            stoppedAt: old.stoppedAt,
            actualPause: old.actualPause,
            disturbances: old.disturbances
        )
    }

    /// Fotos abschließen und Session beenden.
    public func completePhotos(at now: Date, tag: SessionTag = .normal) {
        session.status = .completed
        session.endedAt = now
        session.tag = tag
        finalizeExerciseRecords()
        phase = .finished
    }

    /// Session vorzeitig beenden -- geht direkt zu den Fotos.
    public func finishEarly(at now: Date) {
        finishToPhotos(at: now)
    }

    /// Abbrechen. Bleibt als abgebrochen markiert und wird nicht als Ergebnis
    /// gelesen.
    public func abort(at now: Date) {
        session.status = .aborted
        session.endedAt = now
        session.tag = .aborted
        finalizeExerciseRecords()
        phase = .aborted
    }

    // MARK: - Fortsetzen nach Sperre oder Absturz

    /// Zustand, der zum Fortsetzen gespeichert werden muss.
    public struct Snapshot: Equatable, Sendable, Codable {
        public let session: SessionRecord
        public let cursor: Int
        public let substitutions: [String: String]
        /// Zeitstempel des letzten Satz-Stopps, falls gerade pausiert wird.
        public let restStoppedAt: Date?
        public let restTargetEnd: Date?
        public let phaseKind: PhaseKind

        public enum PhaseKind: String, Equatable, Sendable, Codable {
            case awaitingReadiness
            case preview
            case setRunning
            case logging
            case resting
            case photos
            case finished
            case aborted
        }
    }

    public func snapshot() -> Snapshot {
        var stoppedAt: Date?
        var targetEnd: Date?
        let kind: Snapshot.PhaseKind

        switch phase {
        case .awaitingReadiness: kind = .awaitingReadiness
        case .preview: kind = .preview
        case let .setRunning(_, startedAt):
            kind = .setRunning
            stoppedAt = startedAt
        case let .logging(context):
            kind = .logging
            stoppedAt = context.stoppedAt
            targetEnd = context.restTargetEnd
        case let .resting(context):
            kind = .resting
            stoppedAt = context.stoppedAt
            targetEnd = context.restTargetEnd
        case .photos: kind = .photos
        case .finished: kind = .finished
        case .aborted: kind = .aborted
        }

        return Snapshot(
            session: session,
            cursor: cursor,
            substitutions: substitutions,
            restStoppedAt: stoppedAt,
            restTargetEnd: targetEnd,
            phaseKind: kind
        )
    }

    /// Stellt eine offene Session wieder her. Die Restpause wird aus den
    /// Zeitstempeln neu berechnet -- eine Pause, die währenddessen ablief, ist
    /// korrekt abgelaufen.
    public init(restoring snapshot: Snapshot, planVersion: PlanVersion) {
        self.planVersion = planVersion
        let template = planVersion.template(for: snapshot.session.day)
        self.plannedSets = template.map(SessionPlanFlattener.flatten) ?? []
        self.session = snapshot.session
        self.cursor = snapshot.cursor
        self.substitutions = snapshot.substitutions
        // Platzhalter, damit alle gespeicherten Eigenschaften gesetzt sind --
        // erst danach dürfen Methoden aufgerufen werden.
        self.phase = .awaitingReadiness
        for record in snapshot.session.exercises {
            self.outcomes[record.blockID] = record.outcome
        }

        switch snapshot.phaseKind {
        case .finished:
            self.phase = .finished
        case .aborted:
            self.phase = .aborted
        case .photos:
            self.phase = .photos(
                day: snapshot.session.day,
                remaining: snapshot.session.day.photoSlots
            )
        case .setRunning:
            if let set = plannedSetAtCursor(), let startedAt = snapshot.restStoppedAt {
                self.phase = .setRunning(set, startedAt: startedAt)
            } else {
                self.phase = plannedSetAtCursor().map(SessionPhase.preview) ?? .finished
            }
        case .logging:
            if let set = plannedSetAtCursor(), let stoppedAt = snapshot.restStoppedAt {
                self.phase = .logging(
                    .init(
                        set: set,
                        startedAt: nil,
                        stoppedAt: stoppedAt,
                        restTargetEnd: snapshot.restTargetEnd
                    )
                )
            } else {
                self.phase = plannedSetAtCursor().map(SessionPhase.preview) ?? .finished
            }
        case .resting:
            if let next = plannedSetAtCursor(),
               let stoppedAt = snapshot.restStoppedAt,
               let targetEnd = snapshot.restTargetEnd {
                let previous = cursor > 0 ? plannedSets[cursor - 1] : next
                self.phase = .resting(
                    .init(
                        previousSet: previous,
                        nextSet: next,
                        stoppedAt: stoppedAt,
                        restTargetEnd: targetEnd
                    )
                )
            } else {
                self.phase = plannedSetAtCursor().map(SessionPhase.preview) ?? .finished
            }
        case .awaitingReadiness:
            self.phase = .awaitingReadiness
        case .preview:
            self.phase = plannedSetAtCursor().map(SessionPhase.preview) ?? .finished
        }
    }

    // MARK: - Abfragen für die Oberfläche

    /// Nächster Satz, ohne den Zustand zu verändern.
    public func upcomingSet() -> PlannedSet? {
        plannedSetAtCursor()
    }

    /// Sätze dieser Session für eine Übung -- Grundlage für die Vorbelegung des
    /// Gewichts ab dem zweiten Satz.
    public func setsSoFar(exerciseID: String) -> [SetRecord] {
        session.sets.filter { $0.exerciseID == exerciseID }
    }

    // MARK: - Intern

    private func plannedSetAtCursor() -> PlannedSet? {
        guard cursor < plannedSets.count else { return nil }
        return plannedSets[cursor]
    }

    private func nextPlannedSet() -> PlannedSet? {
        while cursor < plannedSets.count {
            let candidate = plannedSets[cursor]
            if case .skipped = outcomes[candidate.blockID] {
                cursor += 1
                continue
            }
            return candidate
        }
        return nil
    }

    private func advanceToNextPreview() {
        if let next = nextPlannedSet() {
            phase = .preview(next)
        } else {
            phase = .photos(day: session.day, remaining: session.day.photoSlots)
        }
    }

    private func skipRemainingSets(ofBlock blockID: String) {
        while cursor < plannedSets.count, plannedSets[cursor].blockID == blockID {
            cursor += 1
        }
    }

    private func effectiveExerciseID(for set: PlannedSet) -> String {
        substitutions[set.blockID] ?? set.exerciseID
    }

    private func recordOutcomeIfNeeded(for set: PlannedSet) {
        if outcomes[set.blockID] == nil {
            outcomes[set.blockID] = .performed
        }
    }

    private func finishToPhotos(at now: Date) {
        session.endedAt = now
        finalizeExerciseRecords()
        phase = .photos(day: session.day, remaining: session.day.photoSlots)
    }

    /// Trägt die tatsächlichen Pausen nach und baut die Übungs-Ergebnisse.
    ///
    /// Die Pause nach einem Satz ist die Zeit bis zum Start des nächsten Satzes.
    /// Damit stimmt sie automatisch auch dann, wenn die Eingabe länger dauerte
    /// als die Zielpause.
    private func finalizeExerciseRecords() {
        for index in session.sets.indices.dropLast() {
            let current = session.sets[index]
            let next = session.sets[index + 1]
            let reference = next.startedAt ?? next.stoppedAt
            session.sets[index].actualPause = reference.timeIntervalSince(current.stoppedAt)
        }

        var records: [ExerciseRecord] = []
        var seen = Set<String>()
        for set in plannedSets {
            guard !seen.contains(set.blockID) else { continue }
            seen.insert(set.blockID)
            let outcome = outcomes[set.blockID] ?? .skipped(reason: .other)
            records.append(
                ExerciseRecord(
                    blockID: set.blockID,
                    plannedExerciseID: set.exerciseID,
                    outcome: outcome,
                    positionInSession: set.positionInSession
                )
            )
        }
        session.exercises = records
    }
}
