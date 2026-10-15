import { describe, expect, it } from "vitest";
import { SEED } from "../../shared-types/src/index";
import { initialWorld, type AgentLook, type AgentSeed } from "./index";

const STYLES = {
  hair: ["swoop", "ponytail", "buzz", "spiky", "curly", "long", "buns", "afro", "bob", "bald"],
  eyes: ["dot", "anime", "happy", "sleepy"],
  mouth: ["smile", "grin", "flat", "o"],
  top: ["blazer", "jacket", "vest", "hoodie", "labcoat", "tee", "cardigan", "blouse", "sweatervest", "cape", "overalls"],
  bottom: ["pants", "shorts", "skirt"],
  accessory: ["none", "glasses", "headset", "headphones", "cap", "visor", "beret", "beanie", "scarf", "bowtie"],
};
const HEX = /^#[0-9A-Fa-f]{6}$/;

describe("agent looks", () => {
  const agents = SEED.agents as unknown as AgentSeed[];
  it("every agent has a complete chibi look the renderer understands", () => {
    for (const a of agents) {
      const l = a.avatar.look as AgentLook;
      expect(l, a.key).toBeTruthy();
      expect(STYLES.hair).toContain(l.hair.style);
      expect(STYLES.eyes).toContain(l.eyes);
      expect(STYLES.mouth).toContain(l.mouth);
      expect(STYLES.top).toContain(l.top.style);
      expect(STYLES.bottom).toContain(l.bottom.style);
      expect(STYLES.accessory).toContain(l.accessory);
      for (const c of [l.skin, l.hair.color, l.eyeColor, l.top.color, l.top.accent, l.bottom.color, l.shoes]) expect(c, a.key).toMatch(HEX);
    }
  });
  it("no two agents look alike, and the look reaches the world model", () => {
    const sigs = agents.map((a) => { const l = a.avatar.look!; return `${l.hair.style}${l.hair.color}${l.top.style}${l.top.color}`; });
    expect(new Set(sigs).size).toBe(agents.length);
    const w = initialWorld(agents);
    expect(Object.values(w.agents).every((x) => x.look?.hair.style)).toBe(true);
  });
});
