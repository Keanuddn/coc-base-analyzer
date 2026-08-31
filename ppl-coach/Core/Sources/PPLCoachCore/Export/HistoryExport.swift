import Foundation

/// Vollständiger Export der Historie.
///
/// Das ist dein Trainingsgedächtnis und muss unabhängig von der App lesbar
/// bleiben -- deshalb ein offenes, selbsterklärendes Format mit Datumsangaben
/// nach ISO 8601 und Zahlen ohne Sonderformatierung.
public struct HistoryExport: Equatable, Sendable, Codable {
    public struct Meta: Equatable, Sendable, Codable {
        public let exportedAt: Date
        public let formatVersion: Int
        public let sessionCount: Int
        public let photoCount: Int

        public init(exportedAt: Date, formatVersion: Int, sessionCount: Int, photoCount: Int) {
            self.exportedAt = exportedAt
            self.formatVersion = formatVersion
            self.sessionCount = sessionCount
            self.photoCount = photoCount
        }
    }

    public let meta: Meta
    /// Alle Planversionen, damit alte Sessions interpretierbar bleiben.
    public let planVersions: [PlanVersion]
    public let sessions: [SessionRecord]
    public let dailyContexts: [DailyContext]
    public let bodyweight: [BodyweightRecord]
    public let photos: [PhotoRecord]
    public let trials: [Trial]

    public init(
        meta: Meta,
        planVersions: [PlanVersion],
        sessions: [SessionRecord],
        dailyContexts: [DailyContext],
        bodyweight: [BodyweightRecord],
        photos: [PhotoRecord],
        trials: [Trial]
    ) {
        self.meta = meta
        self.planVersions = planVersions
        self.sessions = sessions
        self.dailyContexts = dailyContexts
        self.bodyweight = bodyweight
        self.photos = photos
        self.trials = trials
    }
}

public enum HistoryExporter {
    public static let formatVersion = 1

    public static func makeExport(
        planVersions: [PlanVersion],
        sessions: [SessionRecord],
        dailyContexts: [DailyContext] = [],
        bodyweight: [BodyweightRecord] = [],
        photos: [PhotoRecord] = [],
        trials: [Trial] = [],
        exportedAt: Date = Date()
    ) -> HistoryExport {
        HistoryExport(
            meta: .init(
                exportedAt: exportedAt,
                formatVersion: formatVersion,
                sessionCount: sessions.count,
                photoCount: photos.count
            ),
            planVersions: planVersions,
            sessions: sessions.sorted { $0.startedAt < $1.startedAt },
            dailyContexts: dailyContexts.sorted { $0.cycleStart < $1.cycleStart },
            bodyweight: bodyweight.sorted { $0.date < $1.date },
            photos: photos.sorted { $0.takenAt < $1.takenAt },
            trials: trials
        )
    }

    public static func encoder() -> JSONEncoder {
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
        encoder.dateEncodingStrategy = .iso8601
        return encoder
    }

    public static func decoder() -> JSONDecoder {
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
        return decoder
    }

    public static func encode(_ export: HistoryExport) throws -> Data {
        try encoder().encode(export)
    }

    public static func decode(_ data: Data) throws -> HistoryExport {
        try decoder().decode(HistoryExport.self, from: data)
    }

    /// Kompakte Satztabelle als CSV -- für einen Blick in Numbers oder Excel,
    /// ohne die App zu brauchen.
    public static func setsCSV(sessions: [SessionRecord]) -> String {
        var lines = [
            [
                "session_id", "datum", "trainingstag", "uebung", "art", "satz",
                "gewicht_kg", "wiederholungen", "satzdauer_s", "pause_ist_s",
                "pause_soll_s", "stoerung", "superset_runde"
            ].joined(separator: ";")
        ]

        let formatter = ISO8601DateFormatter()
        for session in sessions.sorted(by: { $0.startedAt < $1.startedAt }) {
            for set in session.sets {
                let disturbance = set.disturbances
                    .map { "\($0.scope.rawValue):\($0.reason.rawValue)" }
                    .joined(separator: "|")
                lines.append(
                    [
                        session.id.uuidString,
                        formatter.string(from: set.stoppedAt),
                        session.day.rawValue,
                        set.exerciseID,
                        set.kind.rawValue,
                        String(set.setIndex),
                        numberText(set.weight),
                        String(set.reps),
                        set.duration.map { numberText($0) } ?? "",
                        set.actualPause.map { numberText($0) } ?? "",
                        set.targetPause.timerTarget.map { numberText($0) } ?? "",
                        disturbance,
                        set.supersetRound.map(String.init) ?? ""
                    ].joined(separator: ";")
                )
            }
        }

        return lines.joined(separator: "\n")
    }

    /// Fehlende Werte bleiben leer statt 0 -- eine fehlende Satzdauer darf
    /// nirgends als superschneller Satz erscheinen.
    private static func numberText(_ value: Double) -> String {
        value == value.rounded()
            ? String(Int(value))
            : String(format: "%.2f", value)
    }
}
