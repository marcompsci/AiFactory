import SwiftUI
import WebKit

/// The 3D city is the web app (React Three Fiber) in a full-screen web view; everything else is native.
struct CityView: View {
    @Environment(AppState.self) private var app

    var body: some View {
        ZStack(alignment: .top) {
            if let url = URL(string: app.webURL) {
                CityWebView(url: url).ignoresSafeArea()
            }
            ConnectionBadge().padding(.top, 4)
        }
    }
}

struct CityWebView: UIViewRepresentable {
    let url: URL

    func makeUIView(context: Context) -> WKWebView {
        let view = WKWebView()
        view.isOpaque = false
        view.backgroundColor = UIColor(Theme.ground)
        view.scrollView.isScrollEnabled = false
        view.load(URLRequest(url: url))
        return view
    }

    func updateUIView(_ view: WKWebView, context: Context) {
        if view.url?.host != url.host || view.url?.port != url.port { view.load(URLRequest(url: url)) }
    }
}

struct ConnectionBadge: View {
    @Environment(AppState.self) private var app

    var body: some View {
        let (text, color): (String, Color) = {
            switch app.connection {
            case .live: return ("Live", Theme.ok)
            case .connecting, .idle: return ("Connecting", Theme.cyan)
            case .reconnecting(let n): return ("Reconnecting (\(n))", Theme.warn)
            case .failed(let why): return (why, Theme.bad)
            }
        }()
        StatusPill(text: text, color: color).background(.ultraThinMaterial, in: Capsule())
    }
}

struct CompanyView: View {
    @Environment(AppState.self) private var app
    @State private var source = "apple_charts"
    @State private var query = "productivity"
    @State private var sending = false
    @State private var message: String?

    var body: some View {
            List {
                Section("Send a researcher out") {
                    Picker("Source", selection: $source) {
                        Text("App Store charts").tag("apple_charts")
                        Text("Etsy").tag("etsy")
                        Text("Depop").tag("depop")
                        Text("Your App Store Connect").tag("app_store_connect")
                    }
                    TextField("What to research", text: $query).textInputAutocapitalization(.never)
                    Button(sending ? "Sending" : "Start research") { Task { await start() } }.disabled(sending || query.count < 2)
                    if let message { Text(message).font(.caption).foregroundStyle(.secondary) }
                }
                Section("Opportunities") {
                    if app.opportunities.isEmpty { Text("No packets yet.").foregroundStyle(.secondary) }
                    ForEach(app.opportunities) { o in
                        VStack(alignment: .leading, spacing: 4) {
                            HStack {
                                Text(o.title).lineLimit(1)
                                Spacer()
                                StatusPill(text: Format.human(o.status), color: Theme.status(o.status))
                            }
                            Text("score \(String(format: "%.2f", o.opportunityScore)), \(o.confidence) confidence" + (o.dataMode == "fixture" ? ", fixture data" : ""))
                                .font(.caption).foregroundStyle(.secondary)
                        }
                    }
                }
                Section("Chain of command") {
                    let all = Array(app.agents.values)
                    if let gm = all.first(where: { $0.tier == "general_manager" }) {
                        OrgRow(agent: gm, depth: 0, all: all)
                    }
                }
            }
            .navigationTitle("Company")
            .refreshable { await app.refresh() }
    }

    private func start() async {
        guard let api = app.api else { return }
        sending = true
        defer { sending = false }
        do {
            try await api.startResearch(source: source, query: query)
            message = "Researcher dispatched. Watch the city."
        } catch {
            message = error.localizedDescription
        }
    }
}

struct OrgRow: View {
    let agent: Agent
    let depth: Int
    let all: [Agent]

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack {
                Circle().fill(Color(hexString: agent.avatar.color)).frame(width: 8, height: 8)
                Text(agent.name)
                Text(agent.role).foregroundStyle(.secondary).lineLimit(1)
                Spacer()
                Text(agent.modelName.replacingOccurrences(of: "claude-", with: "")).font(.system(.caption2, design: .monospaced)).foregroundStyle(.secondary)
            }
            .padding(.leading, CGFloat(depth) * 14)
            ForEach(all.filter { $0.supervisorAgentId == agent.id }.sorted { $0.name < $1.name }) { child in
                OrgRow(agent: child, depth: depth + 1, all: all)
            }
        }
    }
}

struct ActivityView: View {
    @Environment(AppState.self) private var app

    var body: some View {
            List(app.ledger.feed) { e in
                let line = FeedText.line(e, agents: app.agents)
                VStack(alignment: .leading, spacing: 2) {
                    HStack {
                        Text(line.who).font(.caption.bold())
                        if e.isSimulation { Text("sim").font(.caption2).foregroundStyle(Theme.warn) }
                        Spacer()
                        Text("#\(e.sequence)").font(.system(.caption2, design: .monospaced)).foregroundStyle(.secondary)
                    }
                    Text(line.text).font(.subheadline)
                }
            }
            .overlay { if app.ledger.feed.isEmpty { ContentUnavailableView("Quiet for now", systemImage: "waveform") } }
            .navigationTitle("Activity")
    }
}

struct SettingsView: View {
    @Environment(AppState.self) private var app
    @State private var server = ""
    @State private var web = ""
    @State private var token = ""

    var body: some View {
            Form {
                AccountSection()
                Section {
                    TextField("API address", text: $server).keyboardType(.URL).textInputAutocapitalization(.never).autocorrectionDisabled()
                    TextField("City (web app) address", text: $web).keyboardType(.URL).textInputAutocapitalization(.never).autocorrectionDisabled()
                    SecureField(app.tokenSet ? "Access token (saved)" : "Access token", text: $token)
                    Button("Connect") { app.saveSettings(server: server, web: web, token: token.isEmpty ? nil : token) }
                } header: {
                    Text("Server")
                } footer: {
                    Text("Signing in above is easiest. Or paste the AICIV_API_TOKEN from your server; it is stored in the iOS Keychain on this device only.")
                }
                if let h = app.health {
                    Section("System") {
                        LabeledContent("Agents' brains", value: h.executionMode == "live" ? h.providers.joined(separator: ", ") : "Simulation (no model key)")
                        LabeledContent("Sign-in", value: h.authMode)
                        LabeledContent("Sandbox network", value: h.networkIsolation ? "Isolated" : "Not isolated")
                        LabeledContent("Emergency stop", value: h.emergencyStopped ? "On" : "Off")
                    }
                }
            }
            .navigationTitle("Settings")
            .onAppear { server = app.serverURL; web = app.webURL }
            .task { if app.auth == nil { await app.loadPublicConfig() } }
    }
}
