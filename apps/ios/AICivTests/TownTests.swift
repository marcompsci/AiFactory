import XCTest
@testable import AICiv

/// The native town keeps the same rules as the web version (tests/unit/play.test.ts).
final class TownTests: XCTestCase {
    let town = Town.buildTown()

    private func agent(_ key: String = "developer", state: String = "IDLE", district: String = "code-forge", moving: Bool = false, carrying: String? = nil, id: String = "a1") -> TownAgent {
        TownAgent(id: id, key: key, name: "Kade", role: "Developer", homeDistrict: "code-forge", district: district, execState: state,
                  moving: moving, carrying: carrying, look: nil, color: "#ffffff")
    }

    func testTownIsDeterministic() {
        XCTAssertEqual(Town.buildTown().props.count, town.props.count)
        XCTAssertEqual(town.w, 50)
        XCTAssertEqual(town.h, 38)
    }

    func testEveryDoorIsReachableFromTheSpawn() {
        for b in Town.buildings {
            let p = TownRules.path(town, from: Vec(x: Double(town.spawn.x) + 0.5, y: Double(town.spawn.y) + 0.5),
                                   to: Vec(x: Double(b.door.x) + 0.5, y: Double(b.door.y) + 0.5))
            XCTAssertFalse(p.isEmpty, b.id)
            XCTAssertEqual(p.last, Vec(x: Double(b.door.x) + 0.5, y: Double(b.door.y) + 0.5), b.id)
        }
    }

    func testEveryDockConnectsByConveyor() {
        let ids = Array(town.docks.keys)
        for a in ids { for b in ids where a != b { XCTAssertGreaterThan(TownRules.beltRoute(town, town.docks[a]!, town.docks[b]!).count, 1, "\(a)>\(b)") } }
    }

    func testThreeInteriorsYouCanLeave() {
        XCTAssertEqual(Town.enterable, ["data-observatory", "nexus-spire", "code-forge"])
        for id in Town.enterable {
            let m = Town.buildInterior(id)!
            XCTAssertFalse(m.isSolid(m.spawn.x, m.spawn.y))
            let exit = m.exits[0]
            XCTAssertFalse(TownRules.path(m, from: Vec(x: Double(m.spawn.x) + 0.5, y: Double(m.spawn.y) + 0.5), to: Vec(x: Double(exit.x) + 0.5, y: Double(exit.y) + 0.5)).isEmpty)
            XCTAssertFalse(town.isSolid(exit.at.x, exit.at.y))
            XCTAssertGreaterThanOrEqual(m.workstations.count, 2)
        }
    }

    func testWallsStopYouAndAgentsBlockYou() {
        let m = Town.buildInterior("code-forge")!
        XCTAssertEqual(TownRules.move(m, Vec(x: 9.5, y: 2.5), dx: 0, dy: -2).y, 2.5)
        XCTAssertEqual(TownRules.move(m, Vec(x: 9.5, y: 9.5), dx: 0.2, dy: -0.2).x, 9.7, accuracy: 1e-9)
        XCTAssertEqual(TownRules.move(m, Vec(x: 9.5, y: 9.5), dx: 0.5, dy: 0, blockers: [Vec(x: 10.2, y: 9.5)]).x, 9.5)
        let tapWall = TownRules.path(Town.buildInterior("nexus-spire")!, from: Vec(x: 9.5, y: 9.5), to: Vec(x: 9.5, y: 0.5))
        XCTAssertFalse(tapWall.isEmpty)
    }

    func testAnimationsFollowBackendState() {
        XCTAssertEqual(TownRules.anim(agent(state: "EXECUTING")), .coding)
        XCTAssertEqual(TownRules.anim(agent("researcher", state: "EXECUTING")), .researching)
        XCTAssertEqual(TownRules.anim(agent("qa", state: "REVIEWING")), .testing)
        XCTAssertEqual(TownRules.anim(agent(state: "WAITING_FOR_APPROVAL")), .waiting)
        XCTAssertEqual(TownRules.anim(agent(state: "COMPLETED")), .celebrating)
        XCTAssertEqual(TownRules.anim(agent(moving: true, carrying: "brief")), .delivering)
        XCTAssertEqual(TownRules.anim(agent(state: "EXECUTING"), talking: true), .talking)
        XCTAssertEqual(TownRules.anim(agent()), .idle)
        XCTAssertEqual(TownRules.statusLabel(agent(state: "WAITING_FOR_APPROVAL")), "Needs your approval")
    }

    func testAgentsAppearWhereTheBackendSaysTheyAre() {
        let forge = Town.buildInterior("code-forge")!
        let here = TownRules.place(forge, [agent(), agent(district: "sentinel-citadel", id: "a2")], now: 0, talkingTo: nil, town: town)
        XCTAssertEqual(here.map(\.agent.id), ["a1"])
        XCTAssertTrue(TownRules.place(town, [agent()], now: 0, talkingTo: nil, town: town).isEmpty)
        XCTAssertEqual(TownRules.place(town, [agent(district: "nexus-spire", moving: true)], now: 1, talkingTo: nil, town: town).count, 1)
    }

    func testPackagesMoveByTheServerClock() {
        let t0 = Date(timeIntervalSince1970: 1_800_000_000)
        let pkg = TownPackage(id: "p1", type: "research_brief", status: "IN_TRANSIT", origin: "data-observatory", destination: "nexus-spire",
                              routeStartedAt: t0, eta: t0.addingTimeInterval(10))
        XCTAssertEqual(TownRules.packagePoint(town, pkg, serverNow: t0)!.progress, 0)
        XCTAssertEqual(TownRules.packagePoint(town, pkg, serverNow: t0.addingTimeInterval(5))!.progress, 0.5, accuracy: 1e-9)
        let end = TownRules.packagePoint(town, pkg, serverNow: t0.addingTimeInterval(30))!
        let dock = TownRules.dock(town, "nexus-spire")
        XCTAssertEqual(end.x, Double(dock.x) + 0.5)
        XCTAssertEqual(end.y, Double(dock.y) + 0.5)
        var received = pkg
        received.status = "RECEIVED"
        XCTAssertNil(TownRules.packagePoint(town, received, serverNow: t0))
        let outside = TownPackage(id: "p2", type: "code_artifact", status: "QUEUED", origin: "codex-factory", destination: "code-forge", routeStartedAt: nil, eta: nil)
        XCTAssertEqual(TownRules.packagePoint(town, outside, serverNow: t0)!.x, Double(town.docks[Town.depotId]!.x) + 0.5)
    }

    func testSpritesPaintEveryDirectionAndPose() {
        let o = PixelSprites.outfit(PlayerLook())
        for d in Dir.allCases {
            for p in Pose.allCases {
                let px = PixelSprites.paint(o, d, p, 1)
                XCTAssertEqual(px.count, PixelSprites.w * PixelSprites.h)
                XCTAssertGreaterThan(px.compactMap { $0 }.count, 100)
                XCTAssertTrue(px.contains(PixelSprites.ink))
                XCTAssertNotNil(PixelSprites.image(o, d, p, 1))
            }
        }
        let l = PixelSprites.paint(o, .left, .stand, 0), r = PixelSprites.paint(o, .right, .stand, 0)
        XCTAssertEqual(r[3], l[PixelSprites.w - 1 - 3])
    }

    func testArtPaintsTheWholeTown() {
        let ground = PixelArt.groundLayer(town)
        XCTAssertEqual(ground.width, 50 * 16)
        XCTAssertEqual(ground.pixel(5, 5)?.a, 255)
        XCTAssertNotNil(ground.image())
        for b in Town.buildings { XCTAssertNotNil(PixelArt.building(b).canvas.image(), b.id) }
        XCTAssertFalse(PixelArt.propSprites(town).isEmpty)
    }

    func testBundledCastShipsWithTheApp() {
        XCTAssertEqual(Roster.bundled.count, 19)
        XCTAssertTrue(Roster.bundled.contains { $0.name == "Lumen" && $0.avatar.look != nil })
    }

    func testBundledDistrictsBuildTheHomeCity() {
        XCTAssertEqual(Roster.districts.count, 11)
        XCTAssertTrue(Roster.districts.contains { $0.id == "nexus-spire" && $0.architecture == "spire" })
        let city = CityScene()
        city.sync(districts: Roster.districts, agents: Roster.bundled, live: false, packages: [], serverOffset: 0)
        for d in Roster.districts { XCTAssertNotNil(city.scene.rootNode.childNode(withName: "district:\(d.id)", recursively: false), d.id) }
        XCTAssertEqual(city.scene.rootNode.childNodes.filter { $0.name?.hasPrefix("agent:") == true }.count, Roster.bundled.count)
        XCTAssertEqual(city.scene.rootNode.childNodes.filter { $0.name == "belt" }.count, 10)
    }

    func testShadeMatchesTheWebFormula() {
        XCTAssertEqual(shade("#808080", -0.5), "#404040")
        XCTAssertEqual(shade("#000000", 0.5), "#808080")
    }
}
