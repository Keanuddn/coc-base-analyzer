import Foundation
import PPLCoachCore

#if canImport(AuthenticationServices)
import AuthenticationServices
#endif

/// Zugangsdaten aus der Build-Konfiguration.
///
/// Client-ID und Secret stehen in `Config/Secrets.xcconfig`, das per
/// `.gitignore` ausgeschlossen ist -- Whoops Nutzungsbedingungen untersagen
/// Zugangsdaten in offenen Projekten.
enum WhoopCredentials {
    static var clientID: String {
        Bundle.main.object(forInfoDictionaryKey: "WHOOP_CLIENT_ID") as? String ?? ""
    }

    static var clientSecret: String {
        Bundle.main.object(forInfoDictionaryKey: "WHOOP_CLIENT_SECRET") as? String ?? ""
    }

    static var redirectURI: String {
        Bundle.main.object(forInfoDictionaryKey: "WHOOP_REDIRECT_URI") as? String
            ?? "pplcoach://whoop/callback"
    }

    static var isConfigured: Bool {
        !clientID.isEmpty && !clientSecret.isEmpty
    }
}

struct WhoopTokens: Codable, Equatable {
    var accessToken: String
    var refreshToken: String?
    var expiresAt: Date

    var isExpired: Bool {
        // Kleiner Vorlauf, damit ein Aufruf nicht mitten im Ablauf scheitert.
        Date().addingTimeInterval(60) >= expiresAt
    }
}

/// Tokens gehören in den Keychain, nicht in die Zustandsdatei.
enum TokenStore {
    private static let service = "com.pplcoach.whoop"
    private static let account = "tokens"

    static func save(_ tokens: WhoopTokens) {
        #if canImport(Security)
        guard let data = try? JSONEncoder().encode(tokens) else { return }
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account
        ]
        SecItemDelete(query as CFDictionary)

        var attributes = query
        attributes[kSecValueData as String] = data
        attributes[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlock
        SecItemAdd(attributes as CFDictionary, nil)
        #endif
    }

    static func load() -> WhoopTokens? {
        #if canImport(Security)
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
            kSecReturnData as String: true,
            kSecMatchLimit as String: kSecMatchLimitOne
        ]
        var item: CFTypeRef?
        guard SecItemCopyMatching(query as CFDictionary, &item) == errSecSuccess,
              let data = item as? Data else { return nil }
        return try? JSONDecoder().decode(WhoopTokens.self, from: data)
        #else
        return nil
        #endif
    }

    static func clear() {
        #if canImport(Security)
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account
        ]
        SecItemDelete(query as CFDictionary)
        #endif
    }
}

#if canImport(Security)
import Security
#endif

enum WhoopError: LocalizedError {
    case notConfigured
    case authorizationFailed
    case noRefreshToken
    case httpError(Int)
    case decoding(String)

    var errorDescription: String? {
        switch self {
        case .notConfigured:
            return "Whoop-Zugangsdaten fehlen. Secrets.xcconfig aus der Vorlage anlegen."
        case .authorizationFailed:
            return "Die Anmeldung bei Whoop wurde abgebrochen oder abgelehnt."
        case .noRefreshToken:
            return "Kein Refresh-Token vorhanden. Bitte neu verbinden."
        case let .httpError(code):
            return "Whoop antwortete mit Status \(code)."
        case let .decoding(detail):
            return "Antwort von Whoop nicht lesbar: \(detail)"
        }
    }
}

/// OAuth 2.0 Authorization Code Flow.
@MainActor
final class WhoopAuth: NSObject {
    private var session: Any?

    func authorize() async throws -> WhoopTokens {
        guard WhoopCredentials.isConfigured else { throw WhoopError.notConfigured }

        #if canImport(AuthenticationServices)
        let state = UUID().uuidString
        var components = URLComponents(url: WhoopAPI.authorizationURL, resolvingAgainstBaseURL: false)
        components?.queryItems = [
            .init(name: "response_type", value: "code"),
            .init(name: "client_id", value: WhoopCredentials.clientID),
            .init(name: "redirect_uri", value: WhoopCredentials.redirectURI),
            .init(name: "scope", value: WhoopAPI.scopes.joined(separator: " ")),
            .init(name: "state", value: state)
        ]
        guard let url = components?.url,
              let scheme = URL(string: WhoopCredentials.redirectURI)?.scheme else {
            throw WhoopError.authorizationFailed
        }

        let callback: URL = try await withCheckedThrowingContinuation { continuation in
            let webSession = ASWebAuthenticationSession(
                url: url,
                callbackURLScheme: scheme
            ) { callbackURL, error in
                if let callbackURL {
                    continuation.resume(returning: callbackURL)
                } else {
                    continuation.resume(throwing: error ?? WhoopError.authorizationFailed)
                }
            }
            webSession.presentationContextProvider = self
            webSession.prefersEphemeralWebBrowserSession = false
            self.session = webSession
            webSession.start()
        }

        let items = URLComponents(url: callback, resolvingAgainstBaseURL: false)?.queryItems ?? []
        guard let code = items.first(where: { $0.name == "code" })?.value,
              items.first(where: { $0.name == "state" })?.value == state else {
            throw WhoopError.authorizationFailed
        }

        return try await exchange(code: code)
        #else
        throw WhoopError.notConfigured
        #endif
    }

    private func exchange(code: String) async throws -> WhoopTokens {
        try await requestToken(parameters: [
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": WhoopCredentials.redirectURI
        ])
    }

    func refresh(_ tokens: WhoopTokens) async throws -> WhoopTokens {
        guard let refreshToken = tokens.refreshToken else { throw WhoopError.noRefreshToken }
        return try await requestToken(parameters: [
            "grant_type": "refresh_token",
            "refresh_token": refreshToken,
            "scope": "offline"
        ])
    }

    private func requestToken(parameters: [String: String]) async throws -> WhoopTokens {
        var body = parameters
        body["client_id"] = WhoopCredentials.clientID
        body["client_secret"] = WhoopCredentials.clientSecret

        var request = URLRequest(url: WhoopAPI.tokenURL)
        request.httpMethod = "POST"
        request.setValue("application/x-www-form-urlencoded", forHTTPHeaderField: "Content-Type")
        request.setValue(WhoopAPI.userAgent, forHTTPHeaderField: "User-Agent")
        request.httpBody = body
            .map { "\($0.key)=\($0.value.addingPercentEncoding(withAllowedCharacters: .alphanumerics) ?? "")" }
            .joined(separator: "&")
            .data(using: .utf8)

        let (data, response) = try await URLSession.shared.data(for: request)
        if let http = response as? HTTPURLResponse, !(200..<300).contains(http.statusCode) {
            throw WhoopError.httpError(http.statusCode)
        }

        struct TokenResponse: Decodable {
            let access_token: String
            let refresh_token: String?
            let expires_in: Double?
        }

        do {
            let decoded = try JSONDecoder().decode(TokenResponse.self, from: data)
            return WhoopTokens(
                accessToken: decoded.access_token,
                refreshToken: decoded.refresh_token,
                expiresAt: Date().addingTimeInterval(decoded.expires_in ?? 3600)
            )
        } catch {
            throw WhoopError.decoding(String(describing: error))
        }
    }
}

#if canImport(AuthenticationServices) && canImport(UIKit)
import UIKit

extension WhoopAuth: ASWebAuthenticationPresentationContextProviding {
    func presentationAnchor(for session: ASWebAuthenticationSession) -> ASPresentationAnchor {
        // Das aktive Fenster der App, damit die Anmeldung darüber erscheint.
        let scene = UIApplication.shared.connectedScenes
            .compactMap { $0 as? UIWindowScene }
            .first { $0.activationState == .foregroundActive }
        return scene?.keyWindow ?? ASPresentationAnchor()
    }
}
#endif
