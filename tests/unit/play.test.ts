import { describe, expect, it } from "vitest";
import { animFor, beltRoute, dockFor, findPath, moveBody, packagePoint, placeAgents, statusLabel } from "../../apps/web/lib/play/engine";
import { buildInterior, buildTown, ENTERABLE, isSolid, TOWN_BUILDINGS } from "../../apps/web/lib/play/maps";
import { paintFrame, outfitFromPlayer, DEFAULT_PLAYER, SPRITE_W, SPRITE_H } from "../../apps/web/lib/play/sprites";

const town = buildTown();
const agent = (over: Record<string, unknown> = {}) => ({
  id: "a1", key: "developer", name: "Kade", role: "Developer", color: "#fff", shape: "s", height: 1, homeDistrict: "code-forge",
  district: "code-forge", waypoint: null, movement: "STATIONARY", execState: "IDLE", route: [], routeStartedAt: 0, position: [0, 0, 0],
  indicator: null, currentTask: null, carrying: null, ...over,
}) as never;

describe("town map", () => {
  it("is deterministic", () => {
    expect(buildTown().props.length).toBe(town.props.length);
  });

  it("can walk from the spawn to every building door", () => {
    for (const b of TOWN_BUILDINGS) {
      const path = findPath(town, { x: town.spawn.x + 0.5, y: town.spawn.y + 0.5 }, { x: b.door.x + 0.5, y: b.door.y + 0.5 });
      expect(path.length, b.id).toBeGreaterThan(0);
      expect(path.at(-1)).toEqual({ x: b.door.x + 0.5, y: b.door.y + 0.5 });
    }
  });

  it("connects every dock to every other dock by conveyor", () => {
    const ids = Object.keys(town.docks);
    for (const a of ids) for (const b of ids) if (a !== b) expect(beltRoute(town, town.docks[a], town.docks[b]).length, `${a}>${b}`).toBeGreaterThan(1);
  });

  it("has three enterable buildings, each with an interior you can leave", () => {
    expect(ENTERABLE).toEqual(["data-observatory", "nexus-spire", "code-forge"]);
    for (const id of ENTERABLE) {
      const m = buildInterior(id)!;
      expect(isSolid(m, m.spawn.x, m.spawn.y)).toBe(false);
      const exit = m.exits[0];
      expect(findPath(m, { x: m.spawn.x + 0.5, y: m.spawn.y + 0.5 }, { x: exit.x + 0.5, y: exit.y + 0.5 }).length).toBeGreaterThan(0);
      expect(isSolid(town, exit.at.x, exit.at.y)).toBe(false); // you come out in front of the door
      expect(m.workstations.length).toBeGreaterThanOrEqual(2);
    }
  });
});

describe("movement", () => {
  it("stops at walls and slides along them", () => {
    const m = buildInterior("code-forge")!;
    const p = moveBody(m, { x: 9.5, y: 2.5 }, 0, -2); // wall above
    expect(p.y).toBe(2.5);
    const q = moveBody(m, { x: 9.5, y: 9.5 }, 0.2, -0.2);
    expect(q.x).toBeCloseTo(9.7);
  });

  it("doesn't walk through an agent", () => {
    const m = buildInterior("code-forge")!;
    const p = moveBody(m, { x: 9.5, y: 9.5 }, 0.5, 0, [{ x: 10.2, y: 9.5 }]);
    expect(p.x).toBe(9.5);
  });

  it("taps on a wall walk to the nearest open tile", () => {
    const m = buildInterior("nexus-spire")!;
    const path = findPath(m, { x: 9.5, y: 9.5 }, { x: 9.5, y: 0.5 });
    expect(path.length).toBeGreaterThan(0);
    const end = path.at(-1)!;
    expect(isSolid(m, Math.floor(end.x), Math.floor(end.y))).toBe(false);
  });
});

describe("agents follow backend state", () => {
  it("maps execution states to animations", () => {
    expect(animFor(agent({ execState: "EXECUTING" }))).toBe("CODING");
    expect(animFor(agent({ key: "researcher", execState: "EXECUTING" }))).toBe("RESEARCHING");
    expect(animFor(agent({ key: "qa", execState: "REVIEWING" }))).toBe("TESTING");
    expect(animFor(agent({ execState: "WAITING_FOR_APPROVAL" }))).toBe("WAITING");
    expect(animFor(agent({ execState: "COMPLETED" }))).toBe("CELEBRATING");
    expect(animFor(agent({ movement: "MOVING", carrying: "brief" }))).toBe("DELIVERING");
    expect(animFor(agent({ execState: "EXECUTING" }), true)).toBe("TALKING");
    expect(animFor(agent())).toBe("IDLE");
    expect(statusLabel(agent({ execState: "WAITING_FOR_APPROVAL" }))).toBe("Needs your approval");
  });

  it("puts agents in the building the backend says they're in", () => {
    const forge = buildInterior("code-forge")!;
    const here = placeAgents(forge, [agent(), agent({ id: "a2", district: "sentinel-citadel" })], 0, null, town);
    expect(here.map((p) => p.agent.id)).toEqual(["a1"]);
    expect(placeAgents(town, [agent()], 0, null, town)).toEqual([]); // standing still indoors: not on the road
    expect(placeAgents(town, [agent({ movement: "MOVING", district: "nexus-spire" })], 1000, null, town)).toHaveLength(1);
  });
});

describe("packages", () => {
  const pkg = (over: Record<string, unknown>) => ({
    id: "p1", type: "research_brief", status: "IN_TRANSIT", origin: "data-observatory", destination: "nexus-spire", route: [],
    routeStartedAt: "2026-01-01T00:00:00Z", eta: "2026-01-01T00:00:10Z", opportunityId: null, priority: 5, updatedAt: 0, ...over,
  }) as never;
  const t0 = Date.parse("2026-01-01T00:00:00Z");

  it("move along the belt by the server's route clock", () => {
    const start = packagePoint(town, pkg({}), t0)!;
    const mid = packagePoint(town, pkg({}), t0 + 5000)!;
    const end = packagePoint(town, pkg({}), t0 + 20000)!;
    expect(start.progress).toBe(0);
    expect(mid.progress).toBeCloseTo(0.5);
    expect(end.progress).toBe(1);
    const dock = dockFor(town, "nexus-spire");
    expect([end.x, end.y]).toEqual([dock.x + 0.5, dock.y + 0.5]);
  });

  it("wait at the destination once arrived and disappear once received", () => {
    expect(packagePoint(town, pkg({ status: "ARRIVED" }), t0)!.progress).toBe(1);
    expect(packagePoint(town, pkg({ status: "RECEIVED" }), t0)).toBeNull();
    expect(packagePoint(town, pkg({ status: "QUEUED" }), t0 + 99999)!.progress).toBe(0);
  });

  it("use the logistics depot for districts outside town", () => {
    const p = packagePoint(town, pkg({ origin: "codex-factory", status: "QUEUED" }), t0)!;
    expect([p.x, p.y]).toEqual([town.docks["logistics-depot"].x + 0.5, town.docks["logistics-depot"].y + 0.5]);
  });
});

describe("sprites", () => {
  it("paint every direction and pose inside the frame, outlined", () => {
    const o = outfitFromPlayer(DEFAULT_PLAYER);
    for (const d of ["down", "up", "left", "right"] as const) for (const pose of ["stand", "walk", "work", "talk", "celebrate", "carry", "read"] as const) {
      const px = paintFrame(o, d, pose, 1);
      expect(px).toHaveLength(SPRITE_W * SPRITE_H);
      expect(px.filter(Boolean).length).toBeGreaterThan(100);
      expect(px.includes("#1D1626")).toBe(true);
    }
  });

  it("mirror left into right", () => {
    const o = outfitFromPlayer(DEFAULT_PLAYER);
    const l = paintFrame(o, "left", "stand", 0), r = paintFrame(o, "right", "stand", 0);
    expect(r[3]).toBe(l[SPRITE_W - 1 - 3]);
  });
});
