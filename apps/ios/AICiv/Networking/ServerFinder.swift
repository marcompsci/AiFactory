import Foundation
import Network
import Observation

/// Finds AI Civilization servers on your Wi-Fi or hotspot with Bonjour (`_aiciv._tcp`, announced by
/// scripts/run-local.sh), so the phone connects without typing an address.
@MainActor
@Observable
final class ServerFinder {
    struct Found: Identifiable, Hashable {
        let name: String
        let host: String
        let apiPort: Int
        let webPort: Int
        var id: String { "\(host):\(apiPort)" }
        var apiURL: String { "http://\(host):\(apiPort)" }
        var webURL: String { "http://\(host):\(webPort)" }
    }

    static let serviceType = "_aiciv._tcp"
    private(set) var found: [Found] = []
    private(set) var searching = false
    private var browser: NWBrowser?

    func start() {
        guard browser == nil else { return }
        let params = NWParameters()
        params.includePeerToPeer = true
        let b = NWBrowser(for: .bonjourWithTXTRecord(type: Self.serviceType, domain: nil), using: params)
        b.browseResultsChangedHandler = { [weak self] results, _ in
            let list = results.compactMap(Self.parse)
            Task { @MainActor in self?.found = list.sorted { $0.name < $1.name } }
        }
        b.stateUpdateHandler = { [weak self] state in
            Task { @MainActor in
                switch state {
                case .ready: self?.searching = true
                case .failed, .cancelled: self?.searching = false; self?.browser = nil
                default: break
                }
            }
        }
        browser = b
        b.start(queue: .main)
    }

    func stop() {
        browser?.cancel()
        browser = nil
        searching = false
    }

    nonisolated static func parse(_ r: NWBrowser.Result) -> Found? {
        guard case let .service(name, _, _, _) = r.endpoint else { return nil }
        var txt: [String: String] = [:]
        if case let .bonjour(record) = r.metadata {
            for (k, v) in record.dictionary { txt[k] = v }
        }
        return found(name: name, txt: txt)
    }

    /// The announcement carries the Mac's .local name and ports: host=Omaris-MacBook-Pro.local api=8000 web=3000.
    nonisolated static func found(name: String, txt: [String: String]) -> Found? {
        guard let host = txt["host"]?.trimmingCharacters(in: .whitespaces), !host.isEmpty,
              host.range(of: #"^[A-Za-z0-9.-]+$"#, options: .regularExpression) != nil else { return nil }
        return Found(name: name, host: host, apiPort: Int(txt["api"] ?? "") ?? 8000, webPort: Int(txt["web"] ?? "") ?? 3000)
    }
}
