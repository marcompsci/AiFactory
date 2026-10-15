"use client";

import dynamic from "next/dynamic";

const Cast = dynamic(() => import("@/components/world/Cast").then((m) => m.Cast), { ssr: false });

export default function CastPage() {
  return <Cast />;
}
