import Foundation
import PPLCoachCore

/// Holt Zyklen, Recovery, Schlaf und Workouts von Whoop.
///
/// **Polling statt Webhooks:** Whoop-Webhooks brauchen eine öffentlich
/// erreichbare Adresse, und die App ist bewusst serverlos. Bei 100 Anfragen pro
/// Minute Limit ist Polling für einen Nutzer völlig unproblematisch.
actor WhoopClient {
    private let auth: WhoopAuth
    private var tokens: WhoopTokens?

    init(auth: WhoopAuth) {
        self.auth = auth
        self.tokens = TokenStore.load()
    }

    var isConnected: Bool {
        tokens != nil
    }

    func connect() async throws {
        let fresh = try await auth.authorize()
        tokens = fresh
        TokenStore.save(fresh)
    }

    func disconnect() {
        tokens = nil
        TokenStore.clear()
    }

    private func validToken() async throws -> String {
        guard let current = tokens else { throw WhoopError.noRefreshToken }
        if current.isExpired {
            let refreshed = try await auth.refresh(current)
            tokens = refreshed
            TokenStore.save(refreshed)
            return refreshed.accessToken
        }
        return current.accessToken
    }

    /// Lädt eine paginierte Liste vollständig. Whoop liefert höchstens 25
    /// Einträge pro Seite und einen `nextToken`.
    private func fetchAll<Element: Codable & Sendable>(
        _ makeEndpoint: (String?) -> WhoopAPI.Endpoint,
        as type: Element.Type,
        pageLimit: Int = 40
    ) async throws -> [Element] {
        var result: [Element] = []
        var token: String?
        var pages = 0

        repeat {
            guard let url = makeEndpoint(token).url() else { break }
            let page: WhoopPage<Element> = try await get(url)
            result.append(contentsOf: page.records)
            token = page.nextToken
            pages += 1
        } while token != nil && pages < pageLimit

        return result
    }

    private func get<T: Decodable>(_ url: URL) async throws -> T {
        let token = try await validToken()
        var request = URLRequest(url: url)
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        // Ohne eigenen User-Agent blockt Whoop die Anfrage.
        request.setValue(WhoopAPI.userAgent, forHTTPHeaderField: "User-Agent")

        let (data, response) = try await URLSession.shared.data(for: request)
        if let http = response as? HTTPURLResponse, !(200..<300).contains(http.statusCode) {
            throw WhoopError.httpError(http.statusCode)
        }

        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
        do {
            return try decoder.decode(T.self, from: data)
        } catch {
            throw WhoopError.decoding(String(describing: error))
        }
    }

    /// Holt den Tageskontext für einen Zeitraum.
    func fetchContexts(from start: Date, to end: Date = Date()) async throws -> [DailyContext] {
        let cycles = try await fetchAll(
            { token in .cycles(start: start, end: end, limit: 25, nextToken: token) },
            as: WhoopCycle.self
        )
        let recoveries = try await fetchAll(
            { token in .recoveries(start: start, end: end, limit: 25, nextToken: token) },
            as: WhoopRecovery.self
        )
        let sleeps = try await fetchAll(
            { token in .sleeps(start: start, end: end, limit: 25, nextToken: token) },
            as: WhoopSleep.self
        )
        let workouts = try await fetchAll(
            { token in .workouts(start: start, end: end, limit: 25, nextToken: token) },
            as: WhoopWorkout.self
        )

        return WhoopContextBuilder.build(
            cycles: cycles,
            recoveries: recoveries,
            sleeps: sleeps,
            workouts: workouts
        )
    }
}

/// Steuert, wann synchronisiert wird, und schreibt in den Store.
@MainActor
final class WhoopSync: ObservableObject {
    @Published private(set) var isConnected = false
    @Published private(set) var lastSync: Date?
    @Published private(set) var lastError: String?
    @Published private(set) var isSyncing = false

    private let auth = WhoopAuth()
    private let client: WhoopClient

    init() {
        self.client = WhoopClient(auth: auth)
        self.isConnected = TokenStore.load() != nil
    }

    var lastSyncText: String {
        guard let lastSync else { return "noch nicht synchronisiert" }
        return lastSync.formatted(date: .abbreviated, time: .shortened)
    }

    func connect(into store: Store) async {
        do {
            try await client.connect()
            isConnected = true
            lastError = nil
            // Beim ersten Verbinden Historie nachladen, damit die Baselines für
            // HRV und Recovery sofort stehen. Ein HRV-Tageswert allein sagt
            // kaum etwas -- erst der Abstand zum eigenen Mittel über Wochen.
            await sync(into: store, backfillDays: 180)
        } catch {
            lastError = (error as? LocalizedError)?.errorDescription
                ?? error.localizedDescription
        }
    }

    func disconnect() {
        Task { await client.disconnect() }
        isConnected = false
        lastSync = nil
    }

    /// Wird beim App-Start, vor dem Session-Start und einmal morgens gerufen.
    func sync(into store: Store, backfillDays: Int = 21) async {
        guard isConnected, !isSyncing else { return }
        isSyncing = true
        defer { isSyncing = false }

        let start = Calendar.current.date(
            byAdding: .day,
            value: -backfillDays,
            to: Date()
        ) ?? Date().addingTimeInterval(-Double(backfillDays) * 86_400)

        do {
            let contexts = try await client.fetchContexts(from: start)
            store.merge(contexts: contexts)
            lastSync = Date()
            lastError = nil
        } catch {
            // Die App muss ohne Whoop vollständig benutzbar bleiben: ein
            // Fehler hier hält niemanden vom Training ab.
            lastError = (error as? LocalizedError)?.errorDescription
                ?? error.localizedDescription
        }
    }
}
