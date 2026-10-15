"use client";

import { RoundedBox } from "@react-three/drei";
import { useFrame } from "@react-three/fiber";
import type { AgentLook } from "@aiciv/world-engine";
import { useMemo, useRef, type MutableRefObject } from "react";
import * as THREE from "three";

/**
 * An agent as a chunky chibi character: an oversized rounded head with a simple, readable face, a stubby body,
 * mitten hands and big shoes, plus hair, outfit, accessory and a prop that say what the agent does.
 * Everything is built from a few primitives so 20 of them stay cheap to draw.
 */

export const DEFAULT_LOOK: AgentLook = {
  skin: "#F1C27D", hair: { style: "swoop", color: "#3B2416" }, eyes: "dot", eyeColor: "#1E1E1E", mouth: "smile",
  top: { style: "tee", color: "#32D8FF", accent: "#FFFFFF" }, bottom: { style: "pants", color: "#2D3346" }, shoes: "#1E1E26",
  accessory: "none",
};

const INK = "#1A1424";
const HEAD_Y = 1.6;      // head centre
const HW = 0.5, HH = 0.46, HD = 0.43; // head half-sizes

function Mat({ color, rough = 0.85 }: { color: string; rough?: number }) {
  return <meshStandardMaterial color={color} roughness={rough} metalness={0} />;
}

export function ChibiFigure({ look = DEFAULT_LOOK, motion }: { look?: AgentLook; motion?: MutableRefObject<{ walking: boolean }> }) {
  const armL = useRef<THREE.Group>(null);
  const armR = useRef<THREE.Group>(null);
  const legL = useRef<THREE.Group>(null);
  const legR = useRef<THREE.Group>(null);
  const head = useRef<THREE.Group>(null);
  const phase = useMemo(() => Math.random() * 10, []);

  useFrame(({ clock }) => {
    const t = clock.elapsedTime + phase;
    const walking = motion?.current.walking ?? false;
    const swing = walking ? Math.sin(t * 10) * 0.7 : Math.sin(t * 1.6) * 0.05;
    if (armL.current) armL.current.rotation.x = swing;
    if (armR.current) armR.current.rotation.x = -swing * (look.prop ? 0.4 : 1) - (look.prop ? 0.5 : 0);
    if (legL.current) legL.current.rotation.x = walking ? -swing * 0.8 : 0;
    if (legR.current) legR.current.rotation.x = walking ? swing * 0.8 : 0;
    if (head.current) head.current.rotation.z = walking ? Math.sin(t * 10) * 0.04 : Math.sin(t * 0.9) * 0.05;
  });

  const top = look.top;
  const sleeve = ["vest", "sweatervest", "overalls"].includes(top.style) ? top.accent : top.color;
  const shorts = look.bottom.style === "shorts";
  const skirt = look.bottom.style === "skirt";

  return (
    <group>
      {/* legs + shoes */}
      {[[-0.17, legL], [0.17, legR]].map(([x, ref]) => (
        <group key={x as number} ref={ref as MutableRefObject<THREE.Group>} position={[x as number, 0.55, 0]}>
          <mesh position={[0, -0.18, 0]}>
            <boxGeometry args={[0.2, 0.36, 0.22]} />
            <Mat color={shorts || skirt ? look.skin : look.bottom.color} />
          </mesh>
          {shorts ? (
            <mesh position={[0, -0.06, 0]}>
              <boxGeometry args={[0.24, 0.16, 0.25]} />
              <Mat color={look.bottom.color} />
            </mesh>
          ) : null}
          <RoundedBox args={[0.27, 0.18, 0.4]} radius={0.07} smoothness={2} position={[0, -0.43, 0.05]}>
            <Mat color={look.shoes} rough={0.6} />
          </RoundedBox>
        </group>
      ))}
      {skirt ? (
        <mesh position={[0, 0.55, 0]}>
          <cylinderGeometry args={[0.32, 0.44, 0.26, 10]} />
          <Mat color={look.bottom.color} />
        </mesh>
      ) : (
        <mesh position={[0, 0.58, 0]}>
          <boxGeometry args={[0.56, 0.16, 0.38]} />
          <Mat color={look.bottom.color} />
        </mesh>
      )}

      {/* torso */}
      <RoundedBox args={[0.62, 0.52, 0.42]} radius={0.1} smoothness={2} position={[0, 0.88, 0]}>
        <Mat color={top.color} />
      </RoundedBox>
      <TopDetails look={look} />

      {/* arms (pivot at the shoulder) with mitten hands */}
      {[[-1, armL], [1, armR]].map(([side, ref]) => (
        <group key={side as number} ref={ref as MutableRefObject<THREE.Group>} position={[(side as number) * 0.4, 1.08, 0]}>
          <RoundedBox args={[0.17, 0.4, 0.19]} radius={0.06} smoothness={2} position={[(side as number) * 0.03, -0.18, 0]} rotation={[0, 0, (side as number) * 0.15]}>
            <Mat color={sleeve} />
          </RoundedBox>
          <mesh position={[(side as number) * 0.07, -0.42, 0]}>
            <sphereGeometry args={[0.11, 12, 10]} />
            <Mat color={look.skin} />
          </mesh>
          {side === 1 && look.prop ? <Prop kind={look.prop} accent={top.accent} /> : null}
        </group>
      ))}

      {/* neck + head */}
      <mesh position={[0, 1.16, 0]}>
        <cylinderGeometry args={[0.12, 0.13, 0.12, 10]} />
        <Mat color={look.skin} />
      </mesh>
      <group ref={head} position={[0, HEAD_Y, 0]}>
        <RoundedBox args={[HW * 2, HH * 2, HD * 2]} radius={0.3} smoothness={4}>
          <Mat color={look.skin} rough={0.7} />
        </RoundedBox>
        {/* ears */}
        {[-1, 1].map((s) => (
          <mesh key={s} position={[s * (HW + 0.02), -0.02, 0]} scale={[0.5, 1, 0.8]}>
            <sphereGeometry args={[0.1, 10, 8]} />
            <Mat color={look.skin} />
          </mesh>
        ))}
        <Face look={look} />
        <Hair look={look} />
        <Accessory look={look} />
      </group>
    </group>
  );
}

/* ------------------------------------------------------------------ face */

function Face({ look }: { look: AgentLook }) {
  const z = HD + 0.005;
  return (
    <group position={[0, -0.02, z]}>
      {[-1, 1].map((s) => <Eye key={s} x={s * 0.2} kind={look.eyes} color={look.eyeColor} side={s} />)}
      {/* brows */}
      {[-1, 1].map((s) => (
        <mesh key={s} position={[s * 0.2, look.eyes === "anime" ? 0.21 : 0.17, 0.004]} rotation={[0, 0, look.mouth === "flat" ? s * 0.18 : -s * 0.08]}>
          <planeGeometry args={[0.15, 0.035]} />
          <meshBasicMaterial color={look.hair.style === "bald" ? INK : shade(look.hair.color, -0.35)} />
        </mesh>
      ))}
      {look.blush ? [-1, 1].map((s) => (
        <mesh key={s} position={[s * 0.32, -0.12, 0.002]} scale={[1.5, 1, 1]}>
          <circleGeometry args={[0.045, 16]} />
          <meshBasicMaterial color="#FF8FA3" transparent opacity={0.75} />
        </mesh>
      )) : null}
      <Mouth kind={look.mouth} />
      {look.mustache ? (
        <group position={[0, -0.16, 0.006]}>
          {[-1, 1].map((s) => (
            <mesh key={s} position={[s * 0.07, 0, 0]} rotation={[0, 0, s * 0.35]} scale={[1.6, 0.7, 1]}>
              <circleGeometry args={[0.05, 14]} />
              <meshBasicMaterial color="#2A1A12" />
            </mesh>
          ))}
        </group>
      ) : null}
    </group>
  );
}

function Eye({ x, kind, color, side }: { x: number; kind: string; color: string; side: number }) {
  if (kind === "happy" || kind === "sleepy") {
    // closed, curved eyes: ∩ for happy, a calm low arc for sleepy
    return (
      <mesh position={[x, kind === "happy" ? 0.03 : 0.0, 0.004]} rotation={[0, 0, kind === "happy" ? 0 : Math.PI]}>
        <torusGeometry args={[0.065, 0.017, 6, 16, Math.PI]} />
        <meshBasicMaterial color={INK} />
      </mesh>
    );
  }
  if (kind === "anime") {
    return (
      <group position={[x, 0.03, 0.002]}>
        <mesh scale={[1, 1.25, 1]}>
          <circleGeometry args={[0.085, 20]} />
          <meshBasicMaterial color="#FFFFFF" />
        </mesh>
        <mesh position={[0, -0.01, 0.002]} scale={[1, 1.3, 1]}>
          <circleGeometry args={[0.064, 20]} />
          <meshBasicMaterial color={color} />
        </mesh>
        <mesh position={[0, -0.01, 0.004]} scale={[1, 1.3, 1]}>
          <circleGeometry args={[0.034, 16]} />
          <meshBasicMaterial color={INK} />
        </mesh>
        <mesh position={[side * 0.022 + 0.01, 0.03, 0.006]}>
          <circleGeometry args={[0.022, 12]} />
          <meshBasicMaterial color="#FFFFFF" />
        </mesh>
        {/* upper lash line */}
        <mesh position={[0, 0.1, 0.003]}>
          <planeGeometry args={[0.19, 0.03]} />
          <meshBasicMaterial color={INK} />
        </mesh>
      </group>
    );
  }
  return (
    <group position={[x, 0.02, 0.002]}>
      <mesh scale={[0.75, 1.25, 1]}>
        <circleGeometry args={[0.06, 16]} />
        <meshBasicMaterial color={INK} />
      </mesh>
      <mesh position={[0.012, 0.025, 0.002]}>
        <circleGeometry args={[0.016, 10]} />
        <meshBasicMaterial color="#FFFFFF" />
      </mesh>
    </group>
  );
}

function Mouth({ kind }: { kind: string }) {
  const y = -0.17;
  if (kind === "grin") {
    return (
      <group position={[0, y + 0.02, 0.003]}>
        <mesh>
          <circleGeometry args={[0.08, 20, Math.PI, Math.PI]} />
          <meshBasicMaterial color="#7A1F35" />
        </mesh>
        <mesh position={[0, -0.005, 0.001]} scale={[1, 0.35, 1]}>
          <circleGeometry args={[0.07, 16, Math.PI, Math.PI]} />
          <meshBasicMaterial color="#FFFFFF" />
        </mesh>
      </group>
    );
  }
  if (kind === "o") {
    return (
      <mesh position={[0, y, 0.003]} scale={[0.85, 1, 1]}>
        <circleGeometry args={[0.04, 14]} />
        <meshBasicMaterial color="#7A1F35" />
      </mesh>
    );
  }
  if (kind === "flat") {
    return (
      <mesh position={[0, y, 0.003]}>
        <planeGeometry args={[0.1, 0.025]} />
        <meshBasicMaterial color={INK} />
      </mesh>
    );
  }
  return (
    <mesh position={[0, y + 0.03, 0.003]} rotation={[0, 0, Math.PI]}>
      <torusGeometry args={[0.06, 0.014, 6, 16, Math.PI]} />
      <meshBasicMaterial color={INK} />
    </mesh>
  );
}

/* ------------------------------------------------------------------ hair */

function Hair({ look }: { look: AgentLook }) {
  const c = look.hair.color;
  const style = look.hair.style;
  const hidden = look.accessory === "beanie" || look.accessory === "beret";
  const cap = (
    <RoundedBox args={[HW * 2 + 0.08, 0.42, HD * 2 + 0.08]} radius={0.18} smoothness={3} position={[0, HH - 0.1, -0.02]}>
      <Mat color={c} rough={0.6} />
    </RoundedBox>
  );
  const back = (h: number) => (
    <RoundedBox args={[HW * 2 + 0.06, h, 0.2]} radius={0.08} smoothness={2} position={[0, HH - h / 2 - 0.05, -HD - 0.04]}>
      <Mat color={c} rough={0.6} />
    </RoundedBox>
  );
  const sides = (h: number) => [-1, 1].map((s) => (
    <RoundedBox key={s} args={[0.14, h, HD * 2 - 0.1]} radius={0.06} smoothness={2} position={[s * (HW + 0.03), HH - h / 2 - 0.02, -0.06]}>
      <Mat color={c} rough={0.6} />
    </RoundedBox>
  ));
  const fringe = (tilt = 0.25) => (
    <RoundedBox args={[HW * 2 - 0.06, 0.18, 0.16]} radius={0.07} smoothness={2} position={[0.04, HH - 0.12, HD - 0.02]} rotation={[0.25, 0, tilt]}>
      <Mat color={c} rough={0.6} />
    </RoundedBox>
  );
  switch (style) {
    case "bald":
      return null;
    case "buzz":
      return (
        <RoundedBox args={[HW * 2 + 0.04, 0.3, HD * 2 + 0.04]} radius={0.14} smoothness={3} position={[0, HH - 0.08, -0.01]}>
          <Mat color={c} rough={0.9} />
        </RoundedBox>
      );
    case "spiky":
      return (
        <group>
          {cap}
          {back(0.5)}
          {[[-0.3, 0.2, 0.1, -0.5], [0, 0.32, 0.12, 0], [0.3, 0.2, 0.1, 0.5], [-0.18, 0.28, -0.25, -0.3], [0.18, 0.28, -0.25, 0.3], [0, 0.22, -0.4, 0]].map(([x, y, z, r], i) => (
            <mesh key={i} position={[x, HH + y - 0.05, z]} rotation={[-0.35 + (z < 0 ? -0.5 : 0.2), 0, r]}>
              <coneGeometry args={[0.14, 0.42, 5]} />
              <Mat color={c} rough={0.6} />
            </mesh>
          ))}
          {fringe(-0.15)}
        </group>
      );
    case "bob":
      return <group>{cap}{back(0.7)}{sides(0.72)}{fringe(0)}</group>;
    case "long":
      return <group>{cap}{back(1.25)}{sides(1.0)}{fringe(0.2)}</group>;
    case "ponytail":
      return (
        <group>
          {cap}
          {back(0.45)}
          {fringe(0.3)}
          <mesh position={[0, HH - 0.05, -HD - 0.22]} rotation={[0.9, 0, 0]}>
            <capsuleGeometry args={[0.13, 0.42, 6, 10]} />
            <Mat color={c} rough={0.6} />
          </mesh>
        </group>
      );
    case "buns":
      return (
        <group>
          {cap}
          {back(0.45)}
          {fringe(0)}
          {[-1, 1].map((s) => (
            <mesh key={s} position={[s * 0.36, HH + 0.12, -0.08]}>
              <sphereGeometry args={[0.2, 14, 12]} />
              <Mat color={c} rough={0.6} />
            </mesh>
          ))}
        </group>
      );
    case "curly":
      return (
        <group>
          {[...Array(13)].map((_, i) => {
            const a = (i / 13) * Math.PI * 2;
            return (
              <mesh key={i} position={[Math.cos(a) * 0.42, HH - 0.02 + (i % 3) * 0.05, Math.sin(a) * 0.36 - 0.04]}>
                <sphereGeometry args={[0.16, 10, 8]} />
                <Mat color={c} rough={0.7} />
              </mesh>
            );
          })}
          <mesh position={[0, HH + 0.04, -0.04]}>
            <sphereGeometry args={[0.36, 14, 10]} />
            <Mat color={c} rough={0.7} />
          </mesh>
          {back(0.55)}
        </group>
      );
    case "afro":
      return (
        <mesh position={[0, 0.26, -0.24]} scale={[1.08, 0.9, 0.82]}>
          <sphereGeometry args={[0.68, 18, 14]} />
          <Mat color={c} rough={0.95} />
        </mesh>
      );
    default: // swoop
      return (
        <group>
          {hidden ? null : cap}
          {back(0.55)}
          <RoundedBox args={[0.7, 0.2, 0.5]} radius={0.08} smoothness={2} position={[0.12, HH + 0.06, 0.12]} rotation={[0.2, 0, -0.25]}>
            <Mat color={c} rough={0.6} />
          </RoundedBox>
        </group>
      );
  }
}

/* ------------------------------------------------------------------ accessories and outfit details */

function Accessory({ look }: { look: AgentLook }) {
  const hat = look.hatColor ?? "#32D8FF";
  switch (look.accessory) {
    case "glasses":
      return (
        <group position={[0, 0.02, HD + 0.03]}>
          {[-1, 1].map((s) => (
            <mesh key={s} position={[s * 0.2, 0, 0]}>
              <torusGeometry args={[0.1, 0.018, 6, 20]} />
              <meshStandardMaterial color="#20202A" />
            </mesh>
          ))}
          <mesh>
            <boxGeometry args={[0.1, 0.022, 0.02]} />
            <meshStandardMaterial color="#20202A" />
          </mesh>
        </group>
      );
    case "headphones":
    case "headset":
      return (
        <group>
          <mesh position={[0, 0.06, -0.02]} rotation={[0, 0, 0]}>
            <torusGeometry args={[HW + 0.1, 0.04, 6, 24, Math.PI]} />
            <meshStandardMaterial color="#2A2A36" />
          </mesh>
          {[-1, 1].map((s) => (look.accessory === "headset" && s === -1 ? null : (
            <mesh key={s} position={[s * (HW + 0.08), -0.02, 0]} rotation={[0, 0, Math.PI / 2]}>
              <cylinderGeometry args={[0.15, 0.15, 0.1, 16]} />
              <meshStandardMaterial color={look.top.accent} />
            </mesh>
          )))}
          {look.accessory === "headset" ? (
            <mesh position={[HW - 0.05, -0.22, 0.25]} rotation={[0.9, 0, 0.6]}>
              <capsuleGeometry args={[0.02, 0.32, 4, 6]} />
              <meshStandardMaterial color="#2A2A36" />
            </mesh>
          ) : null}
        </group>
      );
    case "cap":
    case "visor":
      return (
        <group position={[0, HH + (look.hair.style === "afro" ? 0.12 : 0.03), 0]}>
          {look.accessory === "cap" ? (
            <mesh position={[0, 0.06, -0.02]} scale={[1, 0.62, 0.95]}>
              <sphereGeometry args={[HW + 0.06, 18, 10, 0, Math.PI * 2, 0, Math.PI / 2]} />
              <Mat color={hat} rough={0.6} />
            </mesh>
          ) : (
            <mesh position={[0, 0.0, -0.02]}>
              <cylinderGeometry args={[HW + 0.05, HW + 0.05, 0.1, 20, 1, true]} />
              <meshStandardMaterial color={hat} side={THREE.DoubleSide} />
            </mesh>
          )}
          <mesh position={[0, 0.0, HD + 0.12]} rotation={[0.12, 0, 0]}>
            <boxGeometry args={[0.7, 0.04, 0.32]} />
            <Mat color={hat} rough={0.6} />
          </mesh>
        </group>
      );
    case "beret":
      return (
        <mesh position={[-0.08, HH + 0.06, -0.02]} rotation={[0.1, 0, 0.25]} scale={[1, 0.32, 1]}>
          <sphereGeometry args={[HW + 0.1, 18, 12]} />
          <Mat color={hat} rough={0.8} />
        </mesh>
      );
    case "beanie":
      return (
        <group position={[0, HH - 0.08, -0.02]}>
          <mesh position={[0, 0.06, 0]} scale={[1, 0.85, 0.95]}>
            <sphereGeometry args={[HW + 0.06, 18, 10, 0, Math.PI * 2, 0, Math.PI / 2]} />
            <Mat color={hat} rough={0.95} />
          </mesh>
          <mesh position={[0, 0.04, 0]}>
            <cylinderGeometry args={[HW + 0.08, HW + 0.08, 0.14, 20]} />
            <Mat color={shade(hat, -0.2)} rough={0.95} />
          </mesh>
          <mesh position={[0, HW + 0.02, 0]}>
            <sphereGeometry args={[0.1, 10, 8]} />
            <Mat color={shade(hat, -0.2)} rough={0.95} />
          </mesh>
        </group>
      );
    case "scarf":
      return (
        <group position={[0, -HH - 0.08, 0]}>
          <mesh rotation={[Math.PI / 2, 0, 0]}>
            <torusGeometry args={[0.2, 0.08, 8, 16]} />
            <Mat color={hat} />
          </mesh>
          <mesh position={[0.12, -0.18, 0.2]} rotation={[0.2, 0, 0.1]}>
            <boxGeometry args={[0.13, 0.32, 0.06]} />
            <Mat color={hat} />
          </mesh>
        </group>
      );
    case "bowtie":
      return (
        <group position={[0, -HH - 0.1, 0.2]}>
          {[-1, 1].map((s) => (
            <mesh key={s} position={[s * 0.07, 0, 0]} rotation={[0, 0, s * Math.PI / 2]}>
              <coneGeometry args={[0.07, 0.13, 4]} />
              <meshStandardMaterial color={look.top.accent} />
            </mesh>
          ))}
        </group>
      );
    default:
      return null;
  }
}

function TopDetails({ look }: { look: AgentLook }) {
  const { style, color, accent } = look.top;
  const front = 0.215;
  switch (style) {
    case "blazer":
    case "cardigan":
      return (
        <group position={[0, 0.88, front]}>
          <mesh position={[0, 0.08, 0]} rotation={[0, 0, Math.PI]}>
            <coneGeometry args={[0.13, 0.32, 3]} />
            <meshStandardMaterial color="#F4F6FA" />
          </mesh>
          {style === "blazer" && look.accessory !== "bowtie" ? (
            <mesh position={[0, 0.02, 0.012]}>
              <boxGeometry args={[0.06, 0.3, 0.02]} />
              <meshStandardMaterial color={accent} />
            </mesh>
          ) : null}
          {[0.05, -0.08].map((y) => (
            <mesh key={y} position={[0.11, y, 0.005]}>
              <circleGeometry args={[0.02, 8]} />
              <meshBasicMaterial color={style === "cardigan" ? accent : shade(color, -0.3)} />
            </mesh>
          ))}
        </group>
      );
    case "labcoat":
      return (
        <group>
          <RoundedBox args={[0.66, 0.36, 0.44]} radius={0.06} smoothness={2} position={[0, 0.55, 0]}>
            <Mat color={color} />
          </RoundedBox>
          <mesh position={[0, 0.85, front + 0.01]}>
            <boxGeometry args={[0.02, 0.6, 0.01]} />
            <meshBasicMaterial color="#C9D1DE" />
          </mesh>
          <mesh position={[-0.16, 0.95, front + 0.012]}>
            <boxGeometry args={[0.12, 0.1, 0.01]} />
            <meshBasicMaterial color={accent} />
          </mesh>
        </group>
      );
    case "hoodie":
      return (
        <group>
          <mesh position={[0, 1.1, -0.17]} scale={[1, 0.55, 0.7]}>
            <sphereGeometry args={[0.3, 14, 10]} />
            <Mat color={color} />
          </mesh>
          <mesh position={[0, 0.76, front + 0.005]}>
            <boxGeometry args={[0.34, 0.14, 0.02]} />
            <Mat color={shade(color, -0.12)} />
          </mesh>
          {[-1, 1].map((s) => (
            <mesh key={s} position={[s * 0.07, 0.98, front + 0.01]}>
              <boxGeometry args={[0.025, 0.16, 0.01]} />
              <meshBasicMaterial color={accent} />
            </mesh>
          ))}
        </group>
      );
    case "jacket":
      return (
        <group position={[0, 0.88, front + 0.006]}>
          <mesh>
            <boxGeometry args={[0.04, 0.5, 0.01]} />
            <meshBasicMaterial color={accent} />
          </mesh>
          <mesh position={[0, 0.25, -0.02]} rotation={[0.3, 0, 0]}>
            <boxGeometry args={[0.46, 0.08, 0.1]} />
            <Mat color={shade(color, -0.15)} />
          </mesh>
        </group>
      );
    case "vest":
    case "sweatervest":
      return (
        <group position={[0, 0.88, front + 0.004]}>
          <mesh position={[0, 0.12, 0]} rotation={[0, 0, Math.PI]}>
            <coneGeometry args={[0.12, 0.28, 3]} />
            <meshStandardMaterial color={accent} />
          </mesh>
          {style === "sweatervest" ? (
            <mesh position={[0, 0.02, 0.012]}>
              <boxGeometry args={[0.05, 0.24, 0.02]} />
              <meshStandardMaterial color="#C8322B" />
            </mesh>
          ) : null}
          {[-0.1, -0.18].map((y) => (
            <mesh key={y} position={[0, y, 0.004]}>
              <planeGeometry args={[0.6, 0.025]} />
              <meshBasicMaterial color={shade(color, 0.2)} />
            </mesh>
          ))}
        </group>
      );
    case "overalls":
      return (
        <group position={[0, 0.88, front + 0.004]}>
          <mesh position={[0, -0.06, 0]}>
            <boxGeometry args={[0.4, 0.34, 0.02]} />
            <Mat color={shade(color, -0.1)} />
          </mesh>
          {[-1, 1].map((s) => (
            <mesh key={s} position={[s * 0.15, 0.18, 0]}>
              <boxGeometry args={[0.06, 0.18, 0.02]} />
              <Mat color={shade(color, -0.1)} />
            </mesh>
          ))}
          <mesh position={[0, -0.02, 0.012]}>
            <boxGeometry args={[0.14, 0.1, 0.01]} />
            <meshBasicMaterial color={accent} />
          </mesh>
        </group>
      );
    case "cape":
      return (
        <group>
          <mesh position={[0, 0.72, -0.24]} rotation={[0.12, 0, 0]}>
            <boxGeometry args={[0.78, 0.82, 0.05]} />
            <Mat color={color} />
          </mesh>
          {[[-0.2, 0.9], [0.18, 0.62], [-0.05, 0.5], [0.25, 0.95]].map(([x, y], i) => (
            <mesh key={i} position={[x, y, -0.27]} rotation={[0, Math.PI, 0]}>
              <circleGeometry args={[0.035, 5]} />
              <meshBasicMaterial color={accent} />
            </mesh>
          ))}
          <mesh position={[0, 1.1, 0]} rotation={[Math.PI / 2, 0, 0]}>
            <torusGeometry args={[0.22, 0.05, 6, 16]} />
            <meshStandardMaterial color={accent} />
          </mesh>
        </group>
      );
    case "blouse":
      return (
        <group position={[0, 1.08, front - 0.02]}>
          {[-1, 1].map((s) => (
            <mesh key={s} position={[s * 0.08, 0, 0.02]} rotation={[0, 0, s * -0.6]}>
              <boxGeometry args={[0.14, 0.08, 0.02]} />
              <meshStandardMaterial color={accent} />
            </mesh>
          ))}
        </group>
      );
    default: // tee: a chest graphic in the accent colour
      return (
        <group position={[0, 0.9, front + 0.006]}>
          <mesh rotation={[0, 0, Math.PI / 4]}>
            <planeGeometry args={[0.14, 0.14]} />
            <meshBasicMaterial color={accent} />
          </mesh>
          <mesh position={[0, 0.2, -0.01]}>
            <planeGeometry args={[0.6, 0.05]} />
            <meshBasicMaterial color={shade(color, -0.15)} />
          </mesh>
        </group>
      );
  }
}

/** What the agent carries in its right hand: the tool of its trade. */
function Prop({ kind, accent }: { kind: string; accent: string }) {
  const at = [0.08, -0.5, 0.12] as const;
  const g = (children: React.ReactNode, rot: [number, number, number] = [0, 0, 0]) => (
    <group position={at} rotation={rot}>{children}</group>
  );
  switch (kind) {
    case "tablet":
      return g(<RoundedBox args={[0.32, 0.42, 0.04]} radius={0.02} smoothness={2}><meshStandardMaterial color="#20232E" emissive={accent} emissiveIntensity={0.35} /></RoundedBox>, [0.3, 0.3, 0]);
    case "clipboard":
      return g(<group><mesh><boxGeometry args={[0.3, 0.38, 0.03]} /><Mat color="#B07A44" /></mesh><mesh position={[0, -0.02, 0.02]}><planeGeometry args={[0.24, 0.28]} /><meshBasicMaterial color="#FFFFFF" /></mesh></group>, [0.3, 0.3, 0]);
    case "laptop":
      return g(<group><mesh><boxGeometry args={[0.42, 0.03, 0.3]} /><meshStandardMaterial color="#C9CED8" /></mesh><mesh position={[0, 0.14, -0.15]} rotation={[-0.3, 0, 0]}><boxGeometry args={[0.42, 0.28, 0.02]} /><meshStandardMaterial color="#2A2E3A" emissive={accent} emissiveIntensity={0.3} /></mesh></group>, [0, 0, 0]);
    case "magnifier":
      return g(<group><mesh position={[0, 0.18, 0]}><torusGeometry args={[0.12, 0.025, 6, 18]} /><meshStandardMaterial color="#3A3A46" /></mesh><mesh position={[0, 0.18, 0]}><circleGeometry args={[0.11, 16]} /><meshStandardMaterial color="#BDE7FF" transparent opacity={0.5} /></mesh><mesh position={[0, -0.02, 0]}><cylinderGeometry args={[0.025, 0.025, 0.2, 8]} /><Mat color="#6B4B2E" /></mesh></group>, [0, 0.4, 0]);
    case "book":
      return g(<group><mesh><boxGeometry args={[0.3, 0.38, 0.08]} /><Mat color={accent} /></mesh><mesh position={[0.15, 0, 0]}><boxGeometry args={[0.02, 0.36, 0.07]} /><meshBasicMaterial color="#FFFFFF" /></mesh></group>, [0.2, 0.4, 0]);
    case "brush":
      return g(<group><mesh rotation={[0, 0, 0.3]}><cylinderGeometry args={[0.025, 0.025, 0.42, 8]} /><Mat color="#B07A44" /></mesh><mesh position={[-0.06, 0.22, 0]}><sphereGeometry args={[0.05, 8, 6]} /><Mat color={accent} /></mesh></group>);
    case "phone":
      return g(<RoundedBox args={[0.14, 0.26, 0.03]} radius={0.02} smoothness={2}><meshStandardMaterial color="#20232E" emissive="#7FD3FF" emissiveIntensity={0.4} /></RoundedBox>, [0.2, 0.3, 0]);
    case "tote":
      return g(<group position={[0, -0.12, 0]}><mesh><boxGeometry args={[0.3, 0.3, 0.12]} /><Mat color="#E8DCC2" /></mesh><mesh position={[0, 0.18, 0]}><torusGeometry args={[0.08, 0.015, 6, 12, Math.PI]} /><Mat color="#7A4A2E" /></mesh></group>);
    case "coin":
      return g(<mesh rotation={[Math.PI / 2, 0, 0]}><cylinderGeometry args={[0.15, 0.15, 0.04, 20]} /><meshStandardMaterial color="#F4C542" metalness={0.6} roughness={0.3} /></mesh>, [0, 0.6, 0]);
    case "calculator":
      return g(<group><RoundedBox args={[0.24, 0.32, 0.05]} radius={0.02} smoothness={2}><Mat color="#3A3F4F" /></RoundedBox><mesh position={[0, 0.09, 0.03]}><planeGeometry args={[0.18, 0.07]} /><meshBasicMaterial color="#9BE8C6" /></mesh></group>, [0.3, 0.3, 0]);
    case "envelope":
      return g(<group><mesh><boxGeometry args={[0.34, 0.22, 0.02]} /><Mat color="#FFFFFF" /></mesh><mesh position={[0, 0.03, 0.012]} rotation={[0, 0, Math.PI]}><circleGeometry args={[0.17, 3]} /><meshBasicMaterial color="#E3E7EE" /></mesh></group>, [0.2, 0.3, 0]);
    case "jar":
      return g(<group><mesh><cylinderGeometry args={[0.13, 0.13, 0.26, 14]} /><meshStandardMaterial color="#D9F3FF" transparent opacity={0.6} /></mesh><mesh position={[0, -0.05, 0]}><cylinderGeometry args={[0.11, 0.11, 0.12, 12]} /><meshStandardMaterial color="#F4C542" metalness={0.5} /></mesh><mesh position={[0, 0.15, 0]}><cylinderGeometry args={[0.14, 0.14, 0.05, 14]} /><Mat color="#FF8FB8" /></mesh></group>);
    case "crystal":
      return g(<mesh position={[0, 0.08, 0]}><octahedronGeometry args={[0.15, 0]} /><meshStandardMaterial color="#C9B8FF" emissive="#A66BFF" emissiveIntensity={0.9} /></mesh>);
    case "wrench":
      return g(<group><mesh><boxGeometry args={[0.06, 0.4, 0.04]} /><meshStandardMaterial color="#A8B0BD" metalness={0.6} roughness={0.3} /></mesh><mesh position={[0, 0.22, 0]}><torusGeometry args={[0.07, 0.03, 6, 10, Math.PI * 1.5]} /><meshStandardMaterial color="#A8B0BD" metalness={0.6} roughness={0.3} /></mesh></group>, [0, 0, -0.3]);
    case "blueprint":
      return g(<mesh rotation={[0, 0, Math.PI / 2.4]}><cylinderGeometry args={[0.06, 0.06, 0.5, 10]} /><Mat color="#3F7BD8" /></mesh>);
    default:
      return null;
  }
}

/** Lighten (amt > 0) or darken (amt < 0) a hex colour. */
export function shade(hex: string, amt: number): string {
  const c = new THREE.Color(hex);
  const t = amt > 0 ? new THREE.Color("#FFFFFF") : new THREE.Color("#000000");
  return `#${c.lerp(t, Math.abs(amt)).getHexString()}`;
}
