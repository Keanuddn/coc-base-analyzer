import Foundation

/// Eine Karte: ein Befund, nicht zwölf Erkenntnisse auf einmal.
///
/// Der Text entsteht aus **festen Bausteinen**. Ein Sprachmodell ist optional
/// und darf nur formulieren -- es rechnet nichts und sieht keine Rohdaten.
public struct InsightCard: Equatable, Sendable, Identifiable {
    public let id: String
    public let finding: Finding
    public let headline: String
    public let body: String
    public let evidenceLines: [String]
    public let nextStep: String?
    /// Übungen, auf deren Chart die Karte führt -- alles muss nachprüfbar sein.
    public let chartExerciseIDs: [String]

    public init(
        finding: Finding,
        headline: String,
        body: String,
        evidenceLines: [String],
        nextStep: String?,
        chartExerciseIDs: [String]
    ) {
        self.id = finding.id
        self.finding = finding
        self.headline = headline
        self.body = body
        self.evidenceLines = evidenceLines
        self.nextStep = nextStep
        self.chartExerciseIDs = chartExerciseIDs
    }
}

/// Deine Rückmeldung zu einer Karte.
public enum CardFeedback: String, Equatable, Sendable, Codable {
    case correct
    case wrong
    case willTry

    public var displayName: String {
        switch self {
        case .correct: return "stimmt"
        case .wrong: return "stimmt nicht"
        case .willTry: return "probiere ich"
        }
    }
}

/// Rangfolge und Ursachenwahl: mehrere Detektoren können gleichzeitig feuern.
///
/// Diese Schicht entscheidet, welcher Befund der wichtigste ist, und
/// unterdrückt Dubletten -- „Pause zu kurz“ und „Drop-off“ sind meist eine
/// Geschichte, nicht zwei.
public struct InsightRanker {
    /// Detektoren, deren Befund einen anderen erklärt und ihn damit verdrängt.
    private static let explains: [String: Set<String>] = [
        "pause-too-short": ["drop-off"],
        "pre-fatigue": ["stagnation"],
        "session-density": ["drop-off"]
    ]

    /// Wie stark ein Befund gewichtet wird. Gedämpfte Detektoren (Rückmeldung
    /// „stimmt nicht“) rutschen nach unten.
    public var dampenedDetectorIDs: Set<String>

    public init(dampenedDetectorIDs: Set<String> = []) {
        self.dampenedDetectorIDs = dampenedDetectorIDs
    }

    public func rank(_ findings: [Finding]) -> [Finding] {
        let present = Set(findings.map(\.detectorID))

        // Dubletten entfernen: wenn ein erklärender Befund vorliegt, fällt der
        // erklärte weg.
        let suppressed = present.reduce(into: Set<String>()) { result, detectorID in
            if let explained = Self.explains[detectorID] {
                result.formUnion(explained)
            }
        }

        return findings
            .filter { !suppressed.contains($0.detectorID) }
            .filter { !$0.restsOnlyOnDisturbedEvidence }
            .sorted { lhs, rhs in
                let lhsScore = score(lhs)
                let rhsScore = score(rhs)
                if lhsScore != rhsScore { return lhsScore > rhsScore }
                return lhs.id < rhs.id
            }
    }

    private func score(_ finding: Finding) -> Int {
        var value: Int
        switch finding.severity {
        case .issue: value = 100
        case .positive: value = 50
        case .observation: value = 30
        }
        // Mehr Belege heißt belastbarer.
        value += finding.evidence.map(\.sampleSize).reduce(0, +)
        if dampenedDetectorIDs.contains(finding.detectorID) {
            value -= 200
        }
        return value
    }
}

/// Baut Karten aus Befunden -- ohne Sprachmodell, nachvollziehbar und offline.
public struct CardComposer {
    public let planVersion: PlanVersion

    public init(planVersion: PlanVersion) {
        self.planVersion = planVersion
    }

    public func compose(_ finding: Finding, trial: Trial? = nil) -> InsightCard {
        var lines = finding.evidence.map { evidence -> String in
            var line = "\(evidence.label): \(evidence.value) (\(evidence.sampleSize) Belege"
            if evidence.disturbedCount > 0 {
                line += ", \(evidence.disturbedCount) davon markiert"
            }
            line += ")"
            return line
        }

        if !finding.ruledOut.isEmpty {
            lines.append("Geprüft und ausgeschlossen: " + finding.ruledOut.joined(separator: "; "))
        }
        if !finding.limitations.isEmpty {
            lines.append("Nicht abgedeckt: " + finding.limitations.joined(separator: "; "))
        }

        let nextStep: String?
        if let trial {
            nextStep = trial.proposalText(planVersion: planVersion)
        } else if let dimension = finding.suggestedVariation {
            nextStep = "Ohne Variation nicht sicher zu beantworten: \(dimension.displayName)."
        } else {
            nextStep = nil
        }

        return InsightCard(
            finding: finding,
            headline: finding.observation,
            body: finding.likelyCause,
            evidenceLines: lines,
            nextStep: nextStep,
            chartExerciseIDs: finding.exerciseIDs
        )
    }
}

/// Führt alle Detektoren aus und liefert Karten plus die Gründe fürs Schweigen.
public struct AnalysisEngine {
    public let detectors: [any Detector]
    public var ranker: InsightRanker
    public let growthGuard: GrowthClaimGuard

    public init(
        detectors: [any Detector]? = nil,
        ranker: InsightRanker = InsightRanker(),
        growthGuard: GrowthClaimGuard = GrowthClaimGuard()
    ) {
        self.detectors = detectors ?? AnalysisEngine.defaultDetectors
        self.ranker = ranker
        self.growthGuard = growthGuard
    }

    /// Feste Reihenfolge -- der Katalog steht vorher fest. Es wird **nicht**
    /// frei nach Auffälligkeiten gesucht, sonst ist bei 19 Übungen ein
    /// Zufallsfund garantiert.
    public static var defaultDetectors: [any Detector] {
        [
            TempoDriftDetector(),
            ShortPauseDetector(),
            LongPauseDetector(),
            DropOffDetector(),
            StagnationDetector(),
            PreFatigueDetector(),
            PauseConsistencyDetector(),
            TimeOfDayDetector(),
            SessionDensityDetector(),
            RecoveryPerformanceDetector(),
            DisturbanceClusterDetector()
        ]
    }

    public struct Output: Sendable {
        public let cards: [InsightCard]
        /// Warum die übrigen Detektoren geschwiegen haben -- sichtbar, damit
        /// klar ist, was noch fehlt.
        public let silences: [String: SilenceReason]
        /// Hinweis statt Trainingsursache, wenn das Körpergewicht flach ist.
        public let growthNote: String?
    }

    public func run(_ input: AnalysisInput) -> Output {
        var findings: [Finding] = []
        var silences: [String: SilenceReason] = [:]

        for detector in detectors {
            switch detector.run(input) {
            case let .finding(finding):
                findings.append(finding)
            case let .silent(reason):
                silences[detector.id] = reason
            }
        }

        let verdict = growthGuard.evaluate(bodyweight: input.bodyweight)
        let note = growthGuard.explanation(for: verdict)

        // Schweigeregel: keine Trainingsursache für fehlenden Aufbau
        // behaupten, solange das Körpergewicht flach oder fallend ist.
        if case .blocked = verdict {
            findings = findings.filter { $0.detectorID != "stagnation" }
            silences["stagnation"] = .bodyweightFlatOrFalling
        }

        let composer = CardComposer(planVersion: input.planVersion)
        let cards = ranker.rank(findings).map { composer.compose($0) }

        return Output(cards: cards, silences: silences, growthNote: note)
    }
}
