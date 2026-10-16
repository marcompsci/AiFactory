import SwiftUI

/// The home screen's look at the town: the same pixel art as the City tab, with each agent standing outside the
/// building the backend says they're in. Shows before you connect too (with the bundled cast).
struct TownPreview: View {
    @Environment(AppState.self) private var app
    private static let picture: CGImage? = {
        let town = Town.buildTown()
        let c = PixelArt.groundLayer(town)
        c.draw(PixelArt.beltLayer(town, frame: 0), at: 0, 0)
        let sprites = (PixelArt.propSprites(town) + town.buildings.map(PixelArt.building)).sorted { $0.baseY < $1.baseY }
        for s in sprites { c.draw(s.canvas, at: s.ox, s.oy) }
        return c.image()
    }()

    var body: some View {
        let agents = app.agents.isEmpty ? Roster.bundled : Array(app.agents.values)
        GeometryReader { g in
            let k = g.size.width / CGFloat(50 * Town.tile)
            ZStack(alignment: .topLeading) {
                if let img = Self.picture {
                    Image(decorative: img, scale: 1).interpolation(.none).resizable()
                        .frame(width: g.size.width, height: g.size.width * 38 / 50)
                }
                ForEach(Array(groups(agents).enumerated()), id: \.offset) { _, grp in
                    let dock = TownRules.dock(Town.shared, grp.district)
                    HStack(spacing: -4) {
                        ForEach(grp.agents.prefix(4)) { a in
                            if let img = PixelSprites.image(a.avatar.look.map(PixelSprites.outfit) ?? PixelSprites.outfit(PlayerLook()), .down,
                                                            app.agents.isEmpty ? .stand : (a.executionState == "EXECUTING" ? .work : .stand), 0) {
                                Image(decorative: img, scale: 1).interpolation(.none).resizable()
                                    .frame(width: 16 * k * 1.6, height: 24 * k * 1.6)
                            }
                        }
                    }
                    .position(x: (CGFloat(dock.x) - 1) * 16 * k, y: (CGFloat(dock.y) + 0.2) * 16 * k)
                }
            }
        }
        .aspectRatio(50 / 38, contentMode: .fit)
        .clipShape(RoundedRectangle(cornerRadius: 4))
        .overlay(alignment: .topLeading) { PixelHeader(text: "The city").padding(6) }
        .overlay(alignment: .bottomTrailing) {
            Button { app.openTab = "city" } label: {
                Label(app.agents.isEmpty ? "Explore the town" : "Play", systemImage: "gamecontroller.fill")
                    .font(Pixel.title(12)).padding(.horizontal, 12).padding(.vertical, 7)
                    .background(GameStyle.go, in: Capsule()).foregroundStyle(GameStyle.ink)
            }
            .padding(8)
        }
        .contentShape(Rectangle())
        .onTapGesture { app.openTab = "city" }
        .accessibilityLabel("The town. Opens the City tab.")
    }

    private struct DistrictGroup { let district: String; let agents: [Agent] }

    private func groups(_ agents: [Agent]) -> [DistrictGroup] {
        let live = !app.agents.isEmpty
        let by = Dictionary(grouping: agents) { live ? ($0.district ?? $0.homeDistrict) : $0.homeDistrict }
        return by.map { DistrictGroup(district: $0.key, agents: $0.value.sorted { $0.name < $1.name }) }.sorted { $0.district < $1.district }
    }
}

private extension Town {
    /// One shared copy for layout lookups in previews.
    static let shared: GameMap = Town.buildTown()
}
