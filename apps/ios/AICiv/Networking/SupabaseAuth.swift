import AuthenticationServices
import CryptoKit
import Foundation
import UIKit

/// Sign in with Google or GitHub through Supabase Auth, using the OAuth PKCE flow in a system browser sheet
/// (ASWebAuthenticationSession). The app never sees your Google or GitHub password. The session's access and refresh
/// tokens live in the Keychain on this device only; the access token is what the API checks.
/// Supabase must list `aiciv://auth-callback` under Authentication → URL Configuration → Redirect URLs.
@MainActor
final class SupabaseAuth: NSObject, ASWebAuthenticationPresentationContextProviding {
    static let callbackScheme = "aiciv"
    static let redirect = "aiciv://auth-callback"

    struct Session: Codable {
        let accessToken: String
        let refreshToken: String
        let expiresAt: Date
        let email: String?
        let provider: String?
    }

    enum AuthFailure: LocalizedError {
        case notConfigured, cancelled, badCallback(String), exchange(String)
        var errorDescription: String? {
            switch self {
            case .notConfigured: return "Sign-in isn't set up on this server yet (no Supabase address)."
            case .cancelled: return "Sign-in was cancelled."
            case .badCallback(let m): return "Sign-in didn't complete: \(m)"
            case .exchange(let m): return "Sign-in failed: \(m)"
            }
        }
    }

    let supabaseURL: URL
    let publishableKey: String
    private var webSession: ASWebAuthenticationSession?

    init(supabaseURL: URL, publishableKey: String) {
        self.supabaseURL = supabaseURL
        self.publishableKey = publishableKey
    }

    nonisolated func presentationAnchor(for session: ASWebAuthenticationSession) -> ASPresentationAnchor {
        MainActor.assumeIsolated {
            UIApplication.shared.connectedScenes.compactMap { ($0 as? UIWindowScene)?.keyWindow }.first ?? ASPresentationAnchor()
        }
    }

    // MARK: PKCE

    static func makeVerifier() -> String {
        var bytes = [UInt8](repeating: 0, count: 48)
        _ = SecRandomCopyBytes(kSecRandomDefault, bytes.count, &bytes)
        return base64url(Data(bytes))
    }

    static func challenge(for verifier: String) -> String {
        base64url(Data(SHA256.hash(data: Data(verifier.utf8))))
    }

    static func base64url(_ d: Data) -> String {
        d.base64EncodedString().replacingOccurrences(of: "+", with: "-").replacingOccurrences(of: "/", with: "_").replacingOccurrences(of: "=", with: "")
    }

    func authorizeURL(provider: String, challenge: String) -> URL {
        var c = URLComponents(url: supabaseURL.appendingPathComponent("auth/v1/authorize"), resolvingAgainstBaseURL: false)!
        c.queryItems = [
            URLQueryItem(name: "provider", value: provider),
            URLQueryItem(name: "redirect_to", value: Self.redirect),
            URLQueryItem(name: "code_challenge", value: challenge),
            URLQueryItem(name: "code_challenge_method", value: "s256"),
        ]
        return c.url!
    }

    /// Opens the provider's sign-in page and returns a Supabase session.
    func signIn(provider: String) async throws -> Session {
        let verifier = Self.makeVerifier()
        let url = authorizeURL(provider: provider, challenge: Self.challenge(for: verifier))
        let callback: URL = try await withCheckedThrowingContinuation { cont in
            let s = ASWebAuthenticationSession(url: url, callbackURLScheme: Self.callbackScheme) { url, error in
                if let url { cont.resume(returning: url) } else if let e = error as? ASWebAuthenticationSessionError, e.code == .canceledLogin {
                    cont.resume(throwing: AuthFailure.cancelled)
                } else {
                    cont.resume(throwing: AuthFailure.badCallback(error?.localizedDescription ?? "no callback"))
                }
            }
            s.presentationContextProvider = self
            s.prefersEphemeralWebBrowserSession = false
            self.webSession = s
            if !s.start() { cont.resume(throwing: AuthFailure.badCallback("could not open the sign-in page")) }
        }
        let items = URLComponents(url: callback, resolvingAgainstBaseURL: false)?.queryItems ?? []
        if let err = items.first(where: { $0.name == "error_description" })?.value { throw AuthFailure.badCallback(err) }
        guard let code = items.first(where: { $0.name == "code" })?.value else { throw AuthFailure.badCallback("no code returned") }
        return try await token(grant: "pkce", body: ["auth_code": code, "code_verifier": verifier])
    }

    func refresh(_ s: Session) async throws -> Session {
        try await token(grant: "refresh_token", body: ["refresh_token": s.refreshToken])
    }

    private func token(grant: String, body: [String: String]) async throws -> Session {
        var c = URLComponents(url: supabaseURL.appendingPathComponent("auth/v1/token"), resolvingAgainstBaseURL: false)!
        c.queryItems = [URLQueryItem(name: "grant_type", value: grant)]
        var r = URLRequest(url: c.url!)
        r.httpMethod = "POST"
        r.setValue("application/json", forHTTPHeaderField: "Content-Type")
        r.setValue(publishableKey, forHTTPHeaderField: "apikey")
        r.httpBody = try JSONEncoder().encode(body)
        let (data, resp) = try await URLSession.shared.data(for: r)
        guard (resp as? HTTPURLResponse)?.statusCode == 200 else {
            let msg = (try? JSONSerialization.jsonObject(with: data) as? [String: Any]).flatMap { ($0["error_description"] ?? $0["msg"] ?? $0["message"]) as? String }
            throw AuthFailure.exchange(msg ?? "status \((resp as? HTTPURLResponse)?.statusCode ?? 0)")
        }
        let j = try JSONSerialization.jsonObject(with: data) as? [String: Any] ?? [:]
        guard let access = j["access_token"] as? String, let refresh = j["refresh_token"] as? String else { throw AuthFailure.exchange("no tokens") }
        let expiresIn = (j["expires_in"] as? Double) ?? 3600
        let user = j["user"] as? [String: Any]
        let provider = (user?["app_metadata"] as? [String: Any])?["provider"] as? String
        return Session(accessToken: access, refreshToken: refresh, expiresAt: Date().addingTimeInterval(expiresIn),
                       email: user?["email"] as? String, provider: provider)
    }

    // MARK: Keychain storage

    static func save(_ s: Session?) {
        if let s, let data = try? JSONEncoder().encode(s) {
            Keychain.save(String(decoding: data, as: UTF8.self), account: "supabase-session")
            Keychain.save(s.accessToken)  // the API bearer token
        } else {
            Keychain.save("", account: "supabase-session")
            Keychain.save("")
        }
    }

    static func load() -> Session? {
        guard let raw = Keychain.load(account: "supabase-session"), let data = raw.data(using: .utf8) else { return nil }
        return try? JSONDecoder().decode(Session.self, from: data)
    }
}
