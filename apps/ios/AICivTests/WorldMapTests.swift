import XCTest
@testable import AICiv

/// The iPhone city is built from the same seeded layout as the website's (District.tsx rng and towersFor), so the
/// buildings must come out identical. Expected values were produced by running the website's code on districts.json.
final class WorldMapTests: XCTestCase {
    func testRngMatchesTheWebsite() {
        var r = WorldMap.Rng("code-forge")
        XCTAssertEqual(r.next(), 0.7485360081773251, accuracy: 1e-12)
        XCTAssertEqual(r.next(), 0.5026478774379939, accuracy: 1e-12)
        XCTAssertEqual(r.next(), 0.9916641477029771, accuracy: 1e-12)
    }

    func testTowersMatchTheWebsite() {
        let expected: [String: Int] = ["nexus-spire": 2, "code-forge": 5, "sentinel-citadel": 5, "vision-quarter": 15, "data-observatory": 3,
                                       "memory-vault": 4, "owners-tower": 3, "central-bank": 3, "claude-code-factory": 8,
                                       "github-factory": 8, "codex-factory": 8]
        for d in Roster.districts { XCTAssertEqual(WorldMap.towers(d).count, expected[d.id], d.id) }
        let forge = try? XCTUnwrap(Roster.districts.first { $0.id == "code-forge" })
        guard let first = forge.map(WorldMap.towers)?.first else { return XCTFail("no forge") }
        XCTAssertEqual(first.pos.x, -8.4, accuracy: 1e-9)
        XCTAssertEqual(first.pos.y, 9.478642849472818, accuracy: 1e-9)
        XCTAssertEqual(first.pos.z, -5.0105915097519755, accuracy: 1e-9)
        XCTAssertEqual(first.size.x, 3.991664147702977, accuracy: 1e-9)
        let tower = Roster.districts.first { $0.id == "owners-tower" }.map(WorldMap.towers)?.first
        XCTAssertEqual(tower?.rot ?? 0, Double.pi / 4, accuracy: 1e-9)
    }

    func testRoutesWalkOverThePlazaRing() {
        guard let a = Roster.districts.first(where: { $0.id == "code-forge" }),
              let b = Roster.districts.first(where: { $0.id == "central-bank" }) else { return XCTFail("districts") }
        let start = WorldMap.home(a, slot: 0)
        let end = WorldMap.home(b, slot: 0)
        let route = WorldMap.route(from: start, fromDistrict: a, to: b, target: end)
        XCTAssertGreaterThan(route.count, 3)
        XCTAssertEqual(route.last?.x ?? 0, end.x, accuracy: 1e-9)
        // every point between the two gates stays on or outside the plaza
        for p in route { XCTAssertGreaterThanOrEqual(hypot(p.x, p.z), WorldMap.plazaRadius - 0.01) }
        let len = WorldMap.length(route)
        XCTAssertTrue(WorldMap.sample(route, len + 1).done)
        XCTAssertFalse(WorldMap.sample(route, len / 2).done)
    }

    func testFallbackBeltsReachEveryDistrict() {
        let (nodes, segments) = WorldMap.logistics(Roster.districts)
        XCTAssertFalse(segments.isEmpty)
        let ids = Set(nodes.map(\.id))
        for s in segments { XCTAssertTrue(ids.contains(s.from) && ids.contains(s.to), s.id) }
        for d in Roster.districts where d.id != "nexus-spire" {
            XCTAssertTrue(nodes.contains { $0.district == d.id }, d.id)
        }
    }
}
