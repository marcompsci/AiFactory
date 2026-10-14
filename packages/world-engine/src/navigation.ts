import { DISTRICT_BY_ID, gatePosition, type Vec3 } from "./districts";

/**
 * Deterministic navigation over a hub-and-spoke walkway graph:
 *   district gate ── walkway ── plaza ring ── walkway ── district gate
 * Same inputs always give the same route, so every client animates identically.
 */
export const PLAZA_RADIUS = 11;

function ringPoint(toward: Vec3): Vec3 {
  const len = Math.hypot(toward[0], toward[2]);
  if (len < 0.001) return [0, 0, PLAZA_RADIUS];
  return [(toward[0] / len) * PLAZA_RADIUS, 0, (toward[2] / len) * PLAZA_RADIUS];
}

function angle(p: Vec3): number {
  return Math.atan2(p[2], p[0]);
}

/** Walk the plaza ring the short way between two ring points, in fixed angular steps. */
function ringArc(a: Vec3, b: Vec3): Vec3[] {
  let a0 = angle(a);
  const a1 = angle(b);
  let delta = a1 - a0;
  while (delta > Math.PI) delta -= Math.PI * 2;
  while (delta < -Math.PI) delta += Math.PI * 2;
  const steps = Math.max(1, Math.ceil(Math.abs(delta) / (Math.PI / 8)));
  const pts: Vec3[] = [];
  for (let i = 1; i < steps; i++) {
    a0 += delta / steps;
    pts.push([Math.cos(a0) * PLAZA_RADIUS, 0, Math.sin(a0) * PLAZA_RADIUS]);
  }
  return pts;
}

export function route(from: Vec3, fromDistrict: string, toDistrict: string, target: Vec3): Vec3[] {
  if (fromDistrict === toDistrict || !DISTRICT_BY_ID[toDistrict]) return [from, target];
  const ga = gatePosition(fromDistrict);
  const gb = gatePosition(toDistrict);
  const ra = ringPoint(ga);
  const rb = ringPoint(gb);
  return dedupe([from, ga, ra, ...ringArc(ra, rb), rb, gb, target]);
}

function dedupe(points: Vec3[]): Vec3[] {
  const out: Vec3[] = [];
  for (const p of points) {
    const last = out[out.length - 1];
    if (!last || Math.hypot(p[0] - last[0], p[2] - last[2]) > 0.05) out.push(p);
  }
  return out;
}

export function routeLength(points: Vec3[]): number {
  let total = 0;
  for (let i = 1; i < points.length; i++) total += Math.hypot(points[i][0] - points[i - 1][0], points[i][2] - points[i - 1][2]);
  return total;
}

/** Position along a polyline at distance `d` (clamped). Also returns heading in radians. */
export function sampleRoute(points: Vec3[], d: number): { position: Vec3; heading: number; done: boolean } {
  if (points.length === 0) return { position: [0, 0, 0], heading: 0, done: true };
  let remaining = Math.max(0, d);
  for (let i = 1; i < points.length; i++) {
    const a = points[i - 1];
    const b = points[i];
    const seg = Math.hypot(b[0] - a[0], b[2] - a[2]);
    if (remaining <= seg) {
      const t = seg === 0 ? 1 : remaining / seg;
      return {
        position: [a[0] + (b[0] - a[0]) * t, 0, a[2] + (b[2] - a[2]) * t],
        heading: Math.atan2(b[0] - a[0], b[2] - a[2]),
        done: false,
      };
    }
    remaining -= seg;
  }
  const n = points.length;
  const last = points[n - 1];
  const prev = points[n - 2] ?? last;
  return { position: last, heading: Math.atan2(last[0] - prev[0], last[2] - prev[2]), done: true };
}
