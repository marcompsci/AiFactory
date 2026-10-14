import { BELT_HEIGHT, DISTRICTS, gatePosition, type Vec3 } from "./districts";

/**
 * Client mirror of services/logistics/graph.py, used to draw belts before the snapshot arrives and in the
 * offline demo. The server's nodes and routes always win when present; a parity test keeps both in step.
 */
export const RING_RADIUS = 16;

export interface BeltNode {
  id: string;
  kind: "dispatch" | "receiving" | "junction";
  district: string | null;
  position: Vec3;
}

export interface BeltSegment {
  id: string;
  from_node: string;
  to_node: string;
  length: number;
  status: "UP" | "DOWN";
}

const round3 = (n: number) => Math.round(n * 1000) / 1000;

export function buildLogistics(): { nodes: BeltNode[]; routes: BeltSegment[] } {
  const nodes: BeltNode[] = [];
  const routes: BeltSegment[] = [];
  const junctions: [number, string][] = [];
  const dist = (a: Vec3, b: Vec3) => round3(Math.hypot(a[0] - b[0], a[2] - b[2]));
  for (const d of DISTRICTS) {
    const [gx, , gz] = gatePosition(d.id);
    const n = Math.hypot(gx, gz) || 1;
    const px = -gz / n;
    const pz = gx / n;
    const dispatch: BeltNode = { id: `${d.id}:dispatch`, kind: "dispatch", district: d.id, position: [gx + px * 3, BELT_HEIGHT, gz + pz * 3] };
    const receiving: BeltNode = { id: `${d.id}:receiving`, kind: "receiving", district: d.id, position: [gx - px * 3, BELT_HEIGHT, gz - pz * 3] };
    const junction: BeltNode = { id: `junction:${d.id}`, kind: "junction", district: d.id, position: [(gx / n) * RING_RADIUS, BELT_HEIGHT, (gz / n) * RING_RADIUS] };
    nodes.push(dispatch, receiving, junction);
    routes.push({ id: `${dispatch.id}->${junction.id}`, from_node: dispatch.id, to_node: junction.id, length: dist(dispatch.position, junction.position), status: "UP" });
    routes.push({ id: `${junction.id}->${receiving.id}`, from_node: junction.id, to_node: receiving.id, length: dist(junction.position, receiving.position), status: "UP" });
    junctions.push([Math.atan2(junction.position[2], junction.position[0]), junction.id]);
  }
  junctions.sort((a, b) => Math.round(a[0] * 1e6) - Math.round(b[0] * 1e6) || (a[1] < b[1] ? -1 : 1));
  const pos = Object.fromEntries(nodes.map((x) => [x.id, x.position]));
  junctions.forEach(([, a], i) => {
    const b = junctions[(i + 1) % junctions.length][1];
    const len = dist(pos[a], pos[b]);
    routes.push({ id: `${a}->${b}`, from_node: a, to_node: b, length: len, status: "UP" });
    routes.push({ id: `${b}->${a}`, from_node: b, to_node: a, length: len, status: "UP" });
  });
  return { nodes, routes };
}

/** Where a package is along its route at `elapsedSeconds`, given belt speed. Returns done=true at the end. */
export function packagePosition(
  route: string[],
  segments: Record<string, { from: Vec3; to: Vec3; length: number }>,
  elapsedSeconds: number,
  speed: number,
): { position: Vec3; done: boolean; segmentIndex: number } {
  let remaining = Math.max(0, elapsedSeconds) * speed;
  for (let i = 0; i < route.length; i++) {
    const s = segments[route[i]];
    if (!s) continue;
    if (remaining <= s.length) {
      const t = s.length ? remaining / s.length : 1;
      return { position: [s.from[0] + (s.to[0] - s.from[0]) * t, s.from[1], s.from[2] + (s.to[2] - s.from[2]) * t], done: false, segmentIndex: i };
    }
    remaining -= s.length;
  }
  const last = segments[route[route.length - 1]];
  return { position: last ? last.to : [0, BELT_HEIGHT, 0], done: true, segmentIndex: route.length - 1 };
}
