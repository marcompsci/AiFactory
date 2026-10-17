import SpriteKit
import SwiftUI

/// The City tab: the pixel-art town as a native SpriteKit game, with native controls on top.
/// It always shows: with the bundled cast before you connect, and your live team once you're signed in.
struct CityGameView: View {
    @Environment(AppState.self) private var app
    @State private var game = GameModel()
    @State private var showSignIn = false
    @State private var showNearby = false
    @Environment(\.accessibilityVoiceOverEnabled) private var voiceOver

    var body: some View {
        ZStack {
            SpriteView(scene: game.scene, options: [.ignoresSiblingOrder], debugOptions: [])
                .ignoresSafeArea()
                .accessibilityLabel("City map")
                .accessibilityHint("Use the Nearby panel to walk, talk to agents and go into buildings")
            VStack(spacing: 8) {
                GameTopBar(game: game, signIn: { showSignIn = true })
                HStack(alignment: .top) {
                    ConnectBanner(game: game, signIn: { showSignIn = true })
                    Spacer()
                    if game.showMap { Minimap(game: game) }
                }
                .padding(.horizontal, 12)
                if let t = game.toast, Date().timeIntervalSince(t.at) < 4 {
                    Text(t.text).font(Pixel.mono(13)).foregroundStyle(GameStyle.cream).multilineTextAlignment(.center)
                        .padding(.horizontal, 14).padding(.vertical, 8).gamePanel().padding(.horizontal, 24)
                        .transition(.opacity)
                        .task(id: t.at) { try? await Task.sleep(nanoseconds: 4_100_000_000); if game.toast?.at == t.at { game.toast = nil } }
                }
                if let id = game.packageId, let pk = game.packages.first(where: { $0.id == id }) { PackageCard(pkg: pk) { game.packageId = nil } }
                Spacer()
                if game.talkingTo == nil && (voiceOver || showNearby) {
                    NearbyPanel(game: game) { showNearby = false }
                }
                if game.talkingTo == nil {
                    HStack {
                        Spacer()
                        Button { showNearby.toggle() } label: { Image(systemName: "person.2.fill").padding(10) }
                            .foregroundStyle(GameStyle.cream).gamePanel()
                            .accessibilityLabel(showNearby ? "Hide the Nearby panel" : "Show who and what is nearby")
                            .opacity(voiceOver ? 0 : 1)
                    }
                    .padding(.horizontal, 12)
                }
                if game.talkingTo == nil { GameControls(game: game) }
            }
            if let id = game.talkingTo, let a = game.agent(id) {
                VStack { Spacer(); DialogueView(game: game, agent: a) }
            }
        }
        .background(Color(hex: 0x120E1C))
        .sheet(item: $game.panel) { panel in
            switch panel {
            case .approvals: OwnerTowerView()
            case .journal, .findings: JournalView(startOnFindings: panel == .findings)
            case .avatar: AvatarEditor(game: game)
            }
        }
        .sheet(isPresented: $showSignIn) {
            VStack(spacing: 16) {
                Text("Sign in to play with your team").font(Pixel.title(16)).foregroundStyle(GameStyle.cream)
                SignInCard()
                Text("Until then the town shows your agents as they were set up, not their live work.").font(.caption).foregroundStyle(.secondary)
            }
            .padding(24)
            .presentationDetents([.medium])
        }
        .onAppear {
            game.sync(from: app)
            // CI screenshots: -townStart <map> opens the town at a building's door or inside it
            if let spot = UserDefaults.standard.string(forKey: "townStart") {
                let spots: [String: (String, Double, Double)] = [
                    "town": ("town", 24.5, 20.5), "nexus-spire": ("nexus-spire", 11, 9.2),
                    "data-observatory": ("data-observatory", 4.5, 6.9), "code-forge": ("code-forge", 8.5, 8.5),
                    "plaza": ("town", 24.5, 13.5), "sentinel-citadel": ("sentinel-citadel", 8.5, 9.5),
                    "central-bank": ("central-bank", 9.5, 9.5), "owners-tower": ("owners-tower", 8.5, 8.5),
                ]
                let at = spots[spot]
                if let at { game.scene.restore(map: at.0, x: at.1, y: at.2, facing: .up) }
            }
        }
        .onChange(of: app.agents) { game.sync(from: app) }
        .onChange(of: app.packages) { game.sync(from: app) }
        .onChange(of: app.connection) { game.sync(from: app) }
        .onChange(of: app.connection) { _, c in if c == .live { showSignIn = false } }
        .task(id: app.connection == .live) { await restoreAndSave() }
    }

    /// Restores your character and position once connected, then saves them while you play.
    private func restoreAndSave() async {
        guard app.connection == .live, let api = app.api else { return }
        if !game.restored, let st = try? await api.playState() {
            game.restored = true
            if let p = st.get("player") {
                if let look = p.get("look") {
                    game.look = PlayerLook(skin: look.s("skin").isEmpty ? game.look.skin : look.s("skin"), hairStyle: look.s("hair_style").isEmpty ? "spiky" : look.s("hair_style"),
                                           hair: look.s("hair").isEmpty ? game.look.hair : look.s("hair"), shirt: look.s("shirt").isEmpty ? game.look.shirt : look.s("shirt"),
                                           pants: look.s("pants").isEmpty ? game.look.pants : look.s("pants"), shoes: look.s("shoes").isEmpty ? game.look.shoes : look.s("shoes"),
                                           glasses: look.get("glasses")?.bool ?? true)
                }
                if !p.s("name").isEmpty { game.name = p.s("name") }
                let map = p.s("map")
                if let x = p.get("x")?.double, let y = p.get("y")?.double, !map.isEmpty {
                    game.scene.restore(map: map, x: x, y: y, facing: Dir(rawValue: p.s("facing")) ?? .down)
                }
            }
        }
        var lastMap = game.player.map
        while !Task.isCancelled {
            try? await Task.sleep(nanoseconds: 1_000_000_000)
            let changedRoom = game.player.map != lastMap
            if game.moved && (changedRoom || Int(Date().timeIntervalSince1970) % 8 == 0) {
                game.moved = false
                lastMap = game.player.map
                let p = game.player
                try? await api.savePlay(name: game.name, look: game.look, map: p.map, x: p.x, y: p.y, facing: p.facing)
            }
        }
    }
}

enum GameStyle {
    static let cream = Color(hex: 0xF3E9D2)
    static let panel = Color(hex: 0x191430)
    static let ink = Color(hex: 0x1D1626)
    static let button = Color(hex: 0x2A2246)
    static let go = Color(hex: 0x5BF2A5)
}

extension View {
    /// RPG panel: dark plum with a chunky cream frame.
    func gamePanel() -> some View {
        background(GameStyle.panel, in: RoundedRectangle(cornerRadius: 10))
            .overlay(RoundedRectangle(cornerRadius: 10).strokeBorder(GameStyle.cream, lineWidth: 3))
            .overlay(RoundedRectangle(cornerRadius: 12).strokeBorder(GameStyle.ink, lineWidth: 3).padding(-3))
            .shadow(color: .black.opacity(0.45), radius: 10, y: 6)
    }
}

struct GameTopBar: View {
    @Environment(AppState.self) private var app
    let game: GameModel
    let signIn: () -> Void

    var body: some View {
        let waiting = app.approvals.count + app.ownerWaiting
        HStack(spacing: 8) {
            HStack(spacing: 6) {
                Text("AI CIV").font(Pixel.title(13)).foregroundStyle(GameStyle.cream)
                Text(game.mode).font(Pixel.title(10)).padding(.horizontal, 7).padding(.vertical, 3)
                    .background(badgeColor, in: Capsule()).foregroundStyle(GameStyle.ink)
            }
            .padding(.horizontal, 10).padding(.vertical, 7)
            .background(GameStyle.panel.opacity(0.88), in: Capsule())
            Spacer()
            HStack(spacing: 2) {
                Button { game.panel = .approvals } label: {
                    Image(systemName: "bell.fill").overlay(alignment: .topTrailing) {
                        if waiting > 0 {
                            Text("\(waiting)").font(.system(size: 10, weight: .bold)).padding(3).background(Theme.warn, in: Circle()).foregroundStyle(GameStyle.ink).offset(x: 9, y: -9)
                        }
                    }
                }.accessibilityLabel("Approvals, \(waiting) waiting")
                Button { game.showMap.toggle() } label: { Image(systemName: "map.fill") }.accessibilityLabel("Minimap")
                Button { game.panel = .avatar } label: { Image(systemName: "person.fill") }.accessibilityLabel("Your character")
                Button { game.panel = .journal } label: { Image(systemName: "book.fill") }.accessibilityLabel("Mission journal")
            }
            .buttonStyle(GameIconButton())
            .padding(4)
            .background(GameStyle.panel.opacity(0.88), in: Capsule())
        }
        .padding(.horizontal, 12)
        .padding(.top, 4)
    }

    private var badgeColor: Color {
        switch game.mode {
        case "LIVE": return GameStyle.go
        case "SIMULATION": return Color(hex: 0xC9A7FF)
        default: return Theme.warn
        }
    }
}

struct GameIconButton: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label.font(.system(size: 17)).foregroundStyle(GameStyle.cream)
            .frame(width: 40, height: 40).contentShape(Rectangle())
            .opacity(configuration.isPressed ? 0.6 : 1)
    }
}

/// Says plainly when the town isn't showing live work, with the one tap that fixes it.
struct ConnectBanner: View {
    @Environment(AppState.self) private var app
    let game: GameModel
    let signIn: () -> Void

    var body: some View {
        let state: (String, String?, (() -> Void)?)? = {
            if case .failed(let why) = app.connection, why.contains("Sign in") { return ("Your Mac is connected", "Sign in", signIn) }
            if case .failed(let why) = app.connection { return (why, "Try again", { app.connect() }) }
            if app.connection == .live { return nil }
            if AppState.isLocalhost(app.serverURL) {
                if let f = app.finder.found.first { return ("Found \(f.name)", "Connect", { app.use(f) }) }
                return ("Offline town: start AI Civ on your Mac", nil, nil)
            }
            if case .reconnecting(let n) = app.connection, n >= 2 { return ("Can't reach your Mac", "Retry", { app.connect() }) }
            return nil
        }()
        if let st = state {
            let (text, button, action) = st
            VStack(alignment: .leading, spacing: 6) {
                Text(text).font(Pixel.mono(12)).foregroundStyle(GameStyle.cream)
                if let button, let action {
                    Button(button, action: action).font(Pixel.title(12)).padding(.horizontal, 12).padding(.vertical, 6)
                        .background(GameStyle.go, in: RoundedRectangle(cornerRadius: 6)).foregroundStyle(GameStyle.ink)
                }
            }
            .padding(10)
            .gamePanel()
            .frame(maxWidth: 230, alignment: .leading)
        }
    }
}

/// The town from above: buildings, roads, packages and you.
struct Minimap: View {
    let game: GameModel
    private static let town = Town.buildTown()

    var body: some View {
        if game.mapId == "town" {
            TimelineView(.periodic(from: .now, by: 0.25)) { _ in
                Canvas { ctx, size in
                    let m = Self.town
                    let k = size.width / CGFloat(m.w)
                    for y in 0..<m.h {
                        for x in 0..<m.w {
                            let g = m.ground[m.idx(x, y)]
                            let c: Color = g == .path ? Color(hex: 0xD9B27A) : g == .plaza ? Color(hex: 0xB7BAC2) : g == .water ? Color(hex: 0x4AA3DC)
                                : m.solid[m.idx(x, y)] ? Color(hex: 0x3F8A40) : Color(hex: 0x5FAE4C)
                            ctx.fill(Path(CGRect(x: CGFloat(x) * k, y: CGFloat(y) * k, width: k + 0.5, height: k + 0.5)), with: .color(c))
                        }
                    }
                    for b in m.buildings {
                        ctx.fill(Path(CGRect(x: CGFloat(b.x) * k, y: CGFloat(b.y) * k, width: CGFloat(b.w) * k, height: CGFloat(b.h) * k)), with: .color(Color(hexString: b.roof)))
                    }
                    for p in game.packages where ["IN_TRANSIT", "ARRIVED", "QUEUED"].contains(p.status) {
                        let d = TownRules.dock(m, p.status == "ARRIVED" ? p.destination : p.origin)
                        ctx.fill(Path(CGRect(x: CGFloat(d.x) * k, y: CGFloat(d.y) * k, width: k * 1.5, height: k * 1.5)), with: .color(Theme.gold))
                    }
                    let me = CGRect(x: CGFloat(game.player.x) * k - 3, y: CGFloat(game.player.y) * k - 3, width: 6, height: 6)
                    ctx.fill(Path(me), with: .color(.white))
                    ctx.fill(Path(me.insetBy(dx: 1, dy: 1)), with: .color(Color(hex: 0xE2465E)))
                }
            }
            .frame(width: 120, height: 120 * 38 / 50)
            .clipShape(RoundedRectangle(cornerRadius: 6))
            .overlay(RoundedRectangle(cornerRadius: 6).strokeBorder(GameStyle.cream, lineWidth: 2))
            .accessibilityLabel("Town map")
        } else {
            Text(Town.name(of: game.mapId)).font(Pixel.title(11)).foregroundStyle(GameStyle.cream)
                .padding(.horizontal, 10).padding(.vertical, 6).gamePanel()
        }
    }
}

/// Joystick on the left; Journal and Talk / Use on the right.
struct GameControls: View {
    let game: GameModel
    @State private var knob = CGSize.zero
    private let radius: CGFloat = 46

    var body: some View {
        ZStack(alignment: .bottom) {
            HStack(alignment: .bottom) {
                joystick
                Spacer()
                HStack(alignment: .bottom, spacing: 14) {
                    Button { game.panel = .journal } label: {
                        Image(systemName: "backpack.fill").font(.system(size: 22)).foregroundStyle(GameStyle.cream)
                            .frame(width: 58, height: 58).background(Color(hex: 0x2A3A5E), in: Circle())
                            .overlay(Circle().strokeBorder(GameStyle.ink, lineWidth: 2))
                    }.accessibilityLabel("Mission journal")
                    Button { game.interact() } label: {
                        VStack(spacing: 2) {
                            Image(systemName: game.nearby?.kind == .object ? "hand.tap.fill" : "bubble.left.fill").font(.system(size: 24))
                            Text(game.nearby?.kind == .object ? "USE" : "TALK").font(Pixel.title(12))
                        }
                        .foregroundStyle(GameStyle.cream)
                        .frame(width: 84, height: 84).background(Color(hex: 0x5A5FBF), in: Circle())
                        .overlay(Circle().strokeBorder(GameStyle.ink, lineWidth: 2))
                        .opacity(game.nearby == nil ? 0.45 : 1)
                    }
                    .disabled(game.nearby == nil)
                    .accessibilityLabel(game.nearby?.label ?? "Nothing nearby")
                }
            }
            if let n = game.nearby {
                Text(n.label).font(Pixel.title(13)).foregroundStyle(GameStyle.cream)
                    .padding(.horizontal, 12).padding(.vertical, 7).background(GameStyle.panel.opacity(0.92), in: RoundedRectangle(cornerRadius: 8))
                    .frame(maxWidth: .infinity, alignment: .trailing)
                    .offset(y: -100)
            }
        }
        .padding(.horizontal, 18)
        .padding(.bottom, 14)
    }

    private var joystick: some View {
        ZStack {
            Circle().fill(GameStyle.panel.opacity(0.55)).overlay(Circle().strokeBorder(.white.opacity(0.25), lineWidth: 2))
            ForEach(0..<4) { i in
                Image(systemName: ["arrowtriangle.up.fill", "arrowtriangle.down.fill", "arrowtriangle.left.fill", "arrowtriangle.right.fill"][i])
                    .font(.system(size: 11)).foregroundStyle(.white.opacity(0.55))
                    .offset(x: CGFloat([0, 0, -50, 50][i]), y: CGFloat([-50, 50, 0, 0][i]))
            }
            Circle().fill(.white.opacity(0.28)).overlay(Circle().strokeBorder(.white.opacity(0.4), lineWidth: 2))
                .frame(width: 56, height: 56).offset(knob)
        }
        .frame(width: 128, height: 128)
        .contentShape(Circle())
        .gesture(DragGesture(minimumDistance: 0).onChanged { v in
            var x = v.location.x - 64, y = v.location.y - 64
            let d = hypot(x, y)
            if d > radius { x = x / d * radius; y = y / d * radius }
            knob = CGSize(width: x, height: y)
            game.stick = CGVector(dx: x / radius, dy: y / radius)
        }.onEnded { _ in
            knob = .zero
            game.stick = .zero
        })
        .accessibilityLabel("Movement joystick")
    }
}

struct PackageCard: View {
    let pkg: TownPackage
    let close: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack {
                Text(TownRules.packageLabel[pkg.type] ?? pkg.type.replacingOccurrences(of: "_", with: " ")).font(Pixel.title(14)).foregroundStyle(GameStyle.cream)
                Spacer()
                Button(action: close) { Image(systemName: "xmark").foregroundStyle(.secondary) }.accessibilityLabel("Close")
            }
            Text("\(Town.name(of: pkg.origin)) → \(Town.name(of: pkg.destination))").font(.caption).foregroundStyle(.secondary)
            HStack(spacing: 6) {
                Text(pkg.status.lowercased().replacingOccurrences(of: "_", with: " ")).font(.caption.bold()).foregroundStyle(Theme.cyan)
                if pkg.status == "IN_TRANSIT", let eta = pkg.eta { Text("arrives \(eta.formatted(date: .omitted, time: .shortened))").font(.caption).foregroundStyle(.secondary) }
            }
            Text("A package on the belt is a real handoff record. Moving or arriving isn't proof the work is done; the journal has the verified result.")
                .font(.caption2).foregroundStyle(.secondary)
        }
        .padding(12)
        .gamePanel()
        .padding(.horizontal, 24)
    }
}

/// The City game without looking at the map: who's here, what you can use, and where you can go. Opens on its own
/// with VoiceOver, or from the people button. Every row walks you there (or talks / uses right away when close).
/// Four buttons that move you one tile and say what's ahead, plus "look around": the VoiceOver way to walk.
struct StepPad: View {
    let game: GameModel

    var body: some View {
        HStack(spacing: 8) {
            pad(.left, "arrow.left")
            VStack(spacing: 6) {
                pad(.up, "arrow.up")
                pad(.down, "arrow.down")
            }
            pad(.right, "arrow.right")
            Spacer()
            Button { game.ask(.look) } label: {
                Label("Look around", systemImage: "eye").font(.caption).padding(8)
            }
            .foregroundStyle(GameStyle.cream).gamePanel()
            .accessibilityHint("Says what's in each direction")
        }
    }

    private func pad(_ d: Dir, _ icon: String) -> some View {
        Button { game.ask(.step(d)) } label: { Image(systemName: icon).frame(width: 34, height: 28) }
            .foregroundStyle(GameStyle.cream).gamePanel()
            .accessibilityLabel("Step \(TownRules.dirName(d))")
    }
}

struct NearbyPanel: View {
    let game: GameModel
    var close: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Text(game.mapId == "town" ? "In town" : Town.name(of: game.mapId)).font(Pixel.title(14)).foregroundStyle(GameStyle.cream)
                    .accessibilityAddTraits(.isHeader)
                Spacer()
                Button("Close", action: close).font(.caption).foregroundStyle(GameStyle.cream)
            }
            ScrollView {
                VStack(alignment: .leading, spacing: 6) {
                    header("Move one step")
                    StepPad(game: game)
                    if !game.people.isEmpty { header("People") }
                    ForEach(game.people) { h in
                        Button { game.ask(.talk(h.id)) } label: { row("Talk to \(h.name)", h.detail, h.steps) }
                            .accessibilityLabel("Talk to \(h.name), \(h.detail), \(h.steps) steps away")
                    }
                    if !game.places.isEmpty { header("Things to use") }
                    ForEach(game.places) { h in
                        Button { game.ask(.use(h.id)) } label: { row(h.name, "", h.steps) }
                            .accessibilityLabel("\(h.name), \(h.steps) steps away")
                    }
                    if game.mapId == "town" {
                        header("Go to")
                        ForEach(Town.buildings.filter(\.enterable), id: \.id) { b in
                            Button { game.ask(.goToBuilding(b.id)) } label: { row(b.name, "walk to the door and go in", nil) }
                                .accessibilityLabel("Go to \(b.name)")
                        }
                    } else {
                        Button { game.ask(.leave) } label: { row("Leave", "back to town", nil) }
                            .accessibilityLabel("Leave \(Town.name(of: game.mapId)), back to town")
                    }
                }
            }
            .frame(maxHeight: 280)
        }
        .padding(12)
        .gamePanel()
        .padding(.horizontal, 12)
    }

    private func header(_ t: String) -> some View {
        Text(t.uppercased()).font(Pixel.mono(11)).foregroundStyle(GameStyle.cream.opacity(0.7)).padding(.top, 4).accessibilityAddTraits(.isHeader)
    }

    private func row(_ title: String, _ detail: String, _ steps: Int?) -> some View {
        HStack {
            VStack(alignment: .leading, spacing: 1) {
                Text(title).font(.subheadline.bold()).foregroundStyle(GameStyle.cream)
                if !detail.isEmpty { Text(detail).font(.caption).foregroundStyle(GameStyle.cream.opacity(0.75)).lineLimit(1) }
            }
            Spacer()
            if let steps { Text("\(steps) steps").font(Pixel.mono(11)).foregroundStyle(GameStyle.cream.opacity(0.7)) }
        }
        .padding(.vertical, 6).padding(.horizontal, 8)
        .background(Color.black.opacity(0.25), in: RoundedRectangle(cornerRadius: 6))
    }
}
