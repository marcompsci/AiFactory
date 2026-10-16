import SwiftUI
import WebKit

/// The 3D city is the web app (React Three Fiber) in a full-screen web view; everything else is native.
struct CityView: View {
    @Environment(AppState.self) private var app

    private var needsSignIn: Bool {
        if case .failed(let why) = app.connection { return why.contains("Sign in") }
        return false
    }

    private var unreachable: Bool {
        switch app.connection {
        case .reconnecting(let n): return n >= 3
        case .failed(let why): return !why.contains("Sign in")
        default: return false
        }
    }

    var body: some View {
        ZStack(alignment: .top) {
            if AppState.isLocalhost(app.webURL) {
                FindMacView()
            } else if needsSignIn {
                // the city page can't sign in by itself (Google blocks sign-in inside embedded browsers): sign in here first
                VStack(spacing: 14) {
                    Spacer()
                    Text("Connected to your Mac").font(.headline).foregroundStyle(Theme.ok)
                    SignInCard()
                    Text("After you sign in, the city opens here.").font(.caption).foregroundStyle(.secondary)
                    Spacer()
                }
                .padding(24)
                .frame(maxWidth: .infinity, maxHeight: .infinity)
                .background(Pixel.sky.ignoresSafeArea())
            } else if unreachable {
                VStack(spacing: 14) {
                    Spacer()
                    Image(systemName: "wifi.exclamationmark").font(.largeTitle).foregroundStyle(Theme.warn)
                    Text("Can't reach your Mac").font(.title3.bold())
                    Text("On the Mac, double-click start-for-iphone.command. Keep the Mac on the same Wi-Fi as this phone, or on this phone's hotspot.")
                        .font(.subheadline).foregroundStyle(.secondary).multilineTextAlignment(.center)
                    ForEach(app.finder.found) { f in
                        Button { app.use(f) } label: { Label("Connect to \(f.name)", systemImage: "desktopcomputer") }.buttonStyle(.borderedProminent)
                    }
                    Button("Try again") { app.connect() }.buttonStyle(.bordered)
                    Spacer()
                }
                .padding(24)
                .frame(maxWidth: .infinity, maxHeight: .infinity)
                .background(Pixel.sky.ignoresSafeArea())
                .onAppear { app.startFinding() }
            } else if let url = URL(string: app.webURL.trimmingCharacters(in: CharacterSet(charactersIn: "/")) + "/play") {
                // V6: the City tab is the playable pixel-art town (the 3D city is one tap away in its top bar)
                let token = Keychain.load() ?? ""
                CityWebView(url: url, apiURL: app.serverURL, token: token).ignoresSafeArea()
                    .id("\(app.serverURL)|\(app.webURL)|\(app.session?.accessToken.suffix(12) ?? "")")  // reload with a new session
            }
            ConnectionBadge().padding(.top, 4)
        }
    }
}

struct CityWebView: UIViewRepresentable {
    let url: URL
    var apiURL: String = ""
    var token: String = ""

    /// Hands the app's connection (API address and signed-in session) to the city page before it loads, so the city
    /// connects as you without a second sign-in inside the web view.
    static func connectionScript(apiURL: String, token: String) -> String {
        let payload = (try? JSONSerialization.data(withJSONObject: ["apiUrl": apiURL, "token": token, "native": true])) ?? Data()
        let json = String(decoding: payload, as: UTF8.self)
        let literal = (try? JSONSerialization.data(withJSONObject: [json], options: [.fragmentsAllowed])).map { String(decoding: $0, as: UTF8.self) } ?? "[\"{}\"]"
        return "try { localStorage.setItem('aiciv.connection', \(literal)[0]); } catch (e) {}"
    }

    func makeUIView(context: Context) -> WKWebView {
        let config = WKWebViewConfiguration()
        if !apiURL.isEmpty {
            config.userContentController.addUserScript(WKUserScript(source: Self.connectionScript(apiURL: apiURL, token: token),
                                                                    injectionTime: .atDocumentStart, forMainFrameOnly: true))
        }
        let view = WKWebView(frame: .zero, configuration: config)
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
                AgentPortrait(agent: agent, size: 28)
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
                FoundMacsSection()
                AccountSection()
                Section {
                    TextField("Your Mac's address, e.g. 192.168.1.20", text: $server).keyboardType(.URL).textInputAutocapitalization(.never).autocorrectionDisabled()
                    TextField("City address (fills in from the Mac's address)", text: $web).keyboardType(.URL).textInputAutocapitalization(.never).autocorrectionDisabled()
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


/// Shown until the app has found your Mac: it searches by itself; nothing to type.
struct FindMacView: View {
    @Environment(AppState.self) private var app
    var body: some View {
        VStack(spacing: 16) {
            ProgressView().controlSize(.large)
            Text("Looking for your Mac…").font(.title3.bold())
            Text("On your Mac, double-click start-for-iphone.command (in aifactory/scripts). Keep the phone and the Mac on the same Wi-Fi, or the Mac on this phone's hotspot. The city opens as soon as it's found.")
                .font(.subheadline).foregroundStyle(.secondary).multilineTextAlignment(.center)
            ForEach(app.finder.found) { f in
                Button { app.use(f) } label: { Label("Connect to \(f.name)", systemImage: "desktopcomputer") }
                    .buttonStyle(.borderedProminent)
            }
        }
        .padding(28)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(Pixel.sky.ignoresSafeArea())
        .onAppear { app.startFinding() }
    }
}

struct FoundMacsSection: View {
    @Environment(AppState.self) private var app
    var body: some View {
        Section {
            if app.finder.found.isEmpty {
                HStack { ProgressView(); Text("Looking for your Mac…").foregroundStyle(.secondary) }
            }
            ForEach(app.finder.found) { f in
                Button { app.use(f) } label: {
                    HStack {
                        Label(f.name, systemImage: "desktopcomputer")
                        Spacer()
                        if f.apiURL == app.serverURL { Image(systemName: "checkmark").foregroundStyle(Theme.ok) }
                    }
                }
            }
        } header: {
            Text("Your Mac")
        } footer: {
            Text("Found automatically on your Wi-Fi or hotspot when start-for-iphone.command is running. Tap to connect.")
        }
        .onAppear { app.startFinding() }
    }
}
