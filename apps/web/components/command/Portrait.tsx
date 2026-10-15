import type { AgentLook } from "@aiciv/world-engine";

/** A flat, front-on chibi portrait (head and shoulders) drawn from the same look as the 3D character. */
export function Portrait({ look, size = 40, fallback, name }: { look?: AgentLook; size?: number; fallback?: string; name: string }) {
  if (!look) {
    return (
      <span className="grid shrink-0 place-items-center rounded-lg text-sm font-semibold text-ground" style={{ width: size, height: size, background: fallback }}>
        {name[0]}
      </span>
    );
  }
  const hair = look.hair.color;
  const ink = "#1A1424";
  const hat = look.hatColor ?? "#32D8FF";
  const brow = look.hair.style === "bald" ? ink : darken(hair, 0.35);
  return (
    <svg width={size} height={size} viewBox="0 0 100 100" role="img" aria-label={`${name}'s portrait`} className="shrink-0 rounded-lg" style={{ background: "#141B33" }}>
      {/* back hair */}
      {look.hair.style === "long" ? <rect x="16" y="22" width="68" height="66" rx="14" fill={hair} /> : null}
      {look.hair.style === "bob" ? <rect x="17" y="20" width="66" height="50" rx="16" fill={hair} /> : null}
      {look.hair.style === "afro" ? <ellipse cx="50" cy="32" rx="40" ry="30" fill={hair} /> : null}
      {look.hair.style === "ponytail" ? <ellipse cx="78" cy="30" rx="9" ry="14" fill={hair} /> : null}
      {look.hair.style === "buns" ? <><circle cx="24" cy="18" r="10" fill={hair} /><circle cx="76" cy="18" r="10" fill={hair} /></> : null}
      {/* shoulders */}
      <rect x="24" y="80" width="52" height="24" rx="10" fill={look.top.color} />
      {["vest", "sweatervest", "blazer", "cardigan"].includes(look.top.style) ? <path d="M43 80 L50 94 L57 80 Z" fill={look.top.style.includes("vest") ? look.top.accent : "#F4F6FA"} /> : null}
      {look.top.style === "blazer" && look.accessory !== "bowtie" ? <rect x="48" y="82" width="4" height="14" fill={look.top.accent} /> : null}
      {/* head */}
      <rect x="20" y="22" width="60" height="58" rx="18" fill={look.skin} />
      {/* front hair */}
      {hairFront(look.hair.style, hair)}
      {/* face */}
      {[-1, 1].map((s) => eye(50 + s * 13, 52, look, s))}
      {[-1, 1].map((s) => <rect key={s} x={50 + s * 13 - 5} y={look.eyes === "anime" ? 39 : 42} width="10" height="2.4" rx="1" fill={brow} transform={look.mouth === "flat" ? `rotate(${s * 10} ${50 + s * 13} 43)` : undefined} />)}
      {look.blush ? [-1, 1].map((s) => <ellipse key={s} cx={50 + s * 21} cy="61" rx="5" ry="2.6" fill="#FF8FA3" opacity="0.75" />) : null}
      {mouth(look.mouth)}
      {look.mustache ? <path d="M40 64 Q45 59 50 63 Q55 59 60 64 Q55 66 50 64.5 Q45 66 40 64 Z" fill="#2A1A12" /> : null}
      {/* accessories */}
      {look.accessory === "glasses" ? <g fill="none" stroke="#20202A" strokeWidth="2"><circle cx="37" cy="52" r="7" /><circle cx="63" cy="52" r="7" /><path d="M44 52 H56" /></g> : null}
      {look.accessory === "headphones" || look.accessory === "headset" ? (
        <g><path d="M18 50 Q18 14 50 14 Q82 14 82 50" fill="none" stroke="#2A2A36" strokeWidth="4" />
          {look.accessory === "headphones" ? <rect x="12" y="44" width="10" height="16" rx="4" fill={look.top.accent} /> : null}
          <rect x="78" y="44" width="10" height="16" rx="4" fill={look.top.accent} />
          {look.accessory === "headset" ? <path d="M82 58 Q74 70 60 68" fill="none" stroke="#2A2A36" strokeWidth="2.5" /> : null}</g>
      ) : null}
      {look.accessory === "cap" ? <g fill={hat}><path d="M20 30 Q20 10 50 10 Q80 10 80 30 Z" /><rect x="40" y="26" width="34" height="6" rx="3" /></g> : null}
      {look.accessory === "visor" ? <g fill={hat}><rect x="20" y="24" width="60" height="6" rx="3" /><rect x="38" y="26" width="36" height="5" rx="2.5" /></g> : null}
      {look.accessory === "beret" ? <ellipse cx="45" cy="20" rx="34" ry="10" fill={hat} transform="rotate(-10 45 20)" /> : null}
      {look.accessory === "beanie" ? <g><path d="M19 32 Q19 6 50 6 Q81 6 81 32 Z" fill={hat} /><rect x="18" y="26" width="64" height="8" rx="3" fill={darken(hat, 0.2)} /></g> : null}
      {look.accessory === "bowtie" ? <path d="M42 84 L50 88 L58 84 L58 92 L50 88 L42 92 Z" fill={look.top.accent} /> : null}
      {look.accessory === "scarf" ? <rect x="30" y="78" width="40" height="8" rx="4" fill={hat} /> : null}
    </svg>
  );
}

function hairFront(style: string, c: string) {
  switch (style) {
    case "bald":
      return null;
    case "buzz":
      return <path d="M20 40 Q20 20 50 19 Q80 20 80 40 L80 34 Q74 26 50 26 Q26 26 20 34 Z" fill={c} />;
    case "spiky":
      return <path d="M18 42 L22 18 L30 26 L36 8 L44 22 L52 4 L58 20 L68 8 L70 24 L80 16 L82 42 Q70 30 50 32 Q30 30 18 42 Z" fill={c} />;
    case "curly":
      return <g fill={c}>{[22, 32, 42, 52, 62, 72, 80].map((x, i) => <circle key={x} cx={x} cy={i % 2 ? 22 : 26} r="9" />)}</g>;
    case "afro":
      return <path d="M20 40 Q22 22 50 22 Q78 22 80 40 L80 30 Q70 18 50 18 Q30 18 20 30 Z" fill={c} />;
    case "swoop":
      return <path d="M18 44 Q18 16 50 16 Q82 16 82 40 Q66 26 44 36 Q30 30 18 44 Z" fill={c} />;
    default: // bob, long, ponytail, buns: a full fringe
      return <path d="M17 46 Q17 16 50 16 Q83 16 83 46 L80 46 Q78 32 66 34 Q50 30 34 36 Q22 34 20 46 Z" fill={c} />;
  }
}

function eye(cx: number, cy: number, look: AgentLook, side: number) {
  const ink = "#1A1424";
  if (look.eyes === "happy") return <path key={side} d={`M${cx - 6} ${cy + 2} Q${cx} ${cy - 6} ${cx + 6} ${cy + 2}`} fill="none" stroke={ink} strokeWidth="2.6" strokeLinecap="round" />;
  if (look.eyes === "sleepy") return <path key={side} d={`M${cx - 6} ${cy - 1} Q${cx} ${cy + 5} ${cx + 6} ${cy - 1}`} fill="none" stroke={ink} strokeWidth="2.6" strokeLinecap="round" />;
  if (look.eyes === "anime") {
    return (
      <g key={side}>
        <ellipse cx={cx} cy={cy} rx="7" ry="8.5" fill="#FFFFFF" />
        <ellipse cx={cx} cy={cy + 1} rx="5.4" ry="7" fill={look.eyeColor} />
        <ellipse cx={cx} cy={cy + 1} rx="2.8" ry="3.6" fill={ink} />
        <circle cx={cx + 2} cy={cy - 2.5} r="1.8" fill="#FFFFFF" />
        <rect x={cx - 8} y={cy - 9.5} width="16" height="2.4" rx="1" fill={ink} />
      </g>
    );
  }
  return <g key={side}><ellipse cx={cx} cy={cy} rx="3.6" ry="5.5" fill={ink} /><circle cx={cx + 1} cy={cy - 2} r="1.3" fill="#FFFFFF" /></g>;
}

function mouth(kind: string) {
  const ink = "#1A1424";
  if (kind === "grin") return <g><path d="M42 64 Q50 74 58 64 Z" fill="#7A1F35" /><path d="M43 64.5 H57 Q55 67 50 67 Q45 67 43 64.5 Z" fill="#FFFFFF" /></g>;
  if (kind === "o") return <ellipse cx="50" cy="66" rx="3" ry="3.6" fill="#7A1F35" />;
  if (kind === "flat") return <rect x="45" y="65" width="10" height="2.4" rx="1" fill={ink} />;
  return <path d="M44 63 Q50 69 56 63" fill="none" stroke={ink} strokeWidth="2.4" strokeLinecap="round" />;
}

function darken(hex: string, amt: number): string {
  const n = parseInt(hex.replace("#", ""), 16);
  const ch = (v: number) => Math.round(v * (1 - amt)).toString(16).padStart(2, "0");
  return `#${ch((n >> 16) & 255)}${ch((n >> 8) & 255)}${ch(n & 255)}`;
}
