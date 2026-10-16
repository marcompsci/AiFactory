"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import dynamic from "next/dynamic";
import { useEffect, useState } from "react";
import { useRealtime } from "@/hooks/useRealtime";
import { onSession } from "@/lib/auth";

const Game = dynamic(() => import("@/components/play/Game").then((m) => m.Game), {
  ssr: false,
  loading: () => <div className="fixed inset-0 grid place-items-center bg-[#120E1C] font-pixel text-[#f3e9d2]">Loading the town…</div>,
});

function Play() {
  const [reconnectKey, setReconnectKey] = useState(0);
  useRealtime(reconnectKey); // snapshot → live events → replay on reconnect, same as the 3D city
  useEffect(() => {
    let last: string | null = null;
    return onSession((s) => {
      const t = s?.access_token ?? null;
      if (t !== last) { last = t; setReconnectKey((k) => k + 1); }
    });
  }, []);
  return <Game />;
}

export default function PlayPage() {
  const [qc] = useState(() => new QueryClient({ defaultOptions: { queries: { retry: 1, staleTime: 5000 } } }));
  return (
    <QueryClientProvider client={qc}>
      <Play />
    </QueryClientProvider>
  );
}
