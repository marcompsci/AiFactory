"use client";

import type { ButtonHTMLAttributes, ReactNode } from "react";

type Variant = "primary" | "quiet" | "danger" | "approve";

const VARIANTS: Record<Variant, string> = {
  primary: "bg-cyan text-ground font-semibold hover:brightness-110",
  quiet: "bg-white/5 text-ink hover:bg-white/10 border border-line",
  danger: "bg-bad/15 text-bad border border-bad/40 hover:bg-bad/25",
  approve: "bg-ok text-ground font-semibold hover:brightness-110",
};

export function Button({ variant = "quiet", className = "", ...rest }: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant }) {
  return (
    <button
      type="button"
      {...rest}
      className={`inline-flex min-h-9 items-center justify-center gap-1.5 rounded-lg px-3 text-sm transition disabled:cursor-not-allowed disabled:opacity-40 ${VARIANTS[variant]} ${className}`}
    />
  );
}

export function Dot({ color, pulse = false }: { color: string; pulse?: boolean }) {
  return (
    <span className="relative inline-flex size-2 shrink-0">
      {pulse ? <span className="absolute inset-0 animate-ping rounded-full opacity-60 motion-reduce:hidden" style={{ background: color }} /> : null}
      <span className="relative inline-flex size-2 rounded-full" style={{ background: color }} />
    </span>
  );
}

export function Section({ title, aside, children }: { title: string; aside?: ReactNode; children: ReactNode }) {
  return (
    <section className="space-y-2">
      <div className="flex items-baseline justify-between gap-2">
        <h3 className="text-sm font-semibold text-ink">{title}</h3>
        {aside ? <div className="text-xs text-ink-3">{aside}</div> : null}
      </div>
      {children}
    </section>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="rounded-lg border border-dashed border-line px-3 py-4 text-sm text-ink-2">{children}</p>;
}

export function ErrorNote({ error }: { error: unknown }) {
  if (!error) return null;
  return <p className="rounded-lg border border-bad/40 bg-bad/10 px-3 py-2 text-sm text-bad">{String((error as Error).message ?? error)}</p>;
}

export function Skeleton({ lines = 3 }: { lines?: number }) {
  return (
    <div className="space-y-2" aria-busy="true" aria-label="Loading">
      {Array.from({ length: lines }, (_, i) => (
        <div key={i} className="h-4 animate-pulse rounded bg-white/5 motion-reduce:animate-none" style={{ width: `${90 - i * 15}%` }} />
      ))}
    </div>
  );
}

export function Pill({ color, children }: { color: string; children: ReactNode }) {
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs" style={{ color, background: `${color}1a` }}>
      <Dot color={color} />
      {children}
    </span>
  );
}
