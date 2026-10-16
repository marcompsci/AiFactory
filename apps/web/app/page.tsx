"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import dynamic from "next/dynamic";
import { useEffect, useState } from "react";
import { ApprovalCall } from "@/components/command/Activity";
import { PackageCard } from "@/components/command/Company";
import { DistrictCard, Dock } from "@/components/command/Shell";
import { BottomPanels, CameraChips, SideNav, StatsBar } from "@/components/command/Frame";
import { useRealtime } from "@/hooks/useRealtime";
import { onSession } from "@/lib/auth";

// WebGL only runs in the browser.
const CityScene = dynamic(() => import("@/components/world/CityScene").then((m) => m.CityScene), {
  ssr: false,
  loading: () => <div className="fixed inset-0 grid place-items-center text-sm text-ink-3">Building the city…</div>,
});

function App() {
  const [reconnectKey, setReconnectKey] = useState(0);
  useRealtime(reconnectKey);
  useEffect(() => {
    // Sign-in (Google/GitHub via Supabase): reconnect whenever the session token changes, including right after the
    // OAuth redirect lands back here.
    let last: string | null = null;
    return onSession((s) => {
      const t = s?.access_token ?? null;
      if (t !== last) {
        last = t;
        setReconnectKey((k) => k + 1);
      }
    });
  }, []);
  useEffect(() => {
    if ("serviceWorker" in navigator && process.env.NODE_ENV === "production") navigator.serviceWorker.register("/sw.js").catch(() => {});
  }, []);
  return (
    <main>
      <CityScene />
      <StatsBar />
      <SideNav />
      <CameraChips />
      <BottomPanels />
      <ApprovalCall />
      <DistrictCard />
      <PackageCard />
      <Dock onReconnect={() => setReconnectKey((k) => k + 1)} />
      <a
        href="/play"
        className="fixed bottom-[calc(var(--sheet-peek)+16px)] right-3 z-30 rounded-full border-2 border-[#f3e9d2] bg-[#191430]/90 px-3 py-1.5 font-pixel text-sm text-[#f3e9d2] lg:bottom-6"
      >
        Play the town
      </a>
      <a
        href="/clinic"
        className="fixed bottom-[calc(var(--sheet-peek)+56px)] right-3 z-30 rounded-full border-2 border-[#f3e9d2] bg-[#191430]/90 px-3 py-1.5 font-pixel text-sm text-[#f3e9d2] lg:bottom-16"
      >
        Failure clinic
      </a>
    </main>
  );
}

export default function Page() {
  const [qc] = useState(() => new QueryClient({ defaultOptions: { queries: { retry: 1, staleTime: 5000 } } }));
  return (
    <QueryClientProvider client={qc}>
      <App />
    </QueryClientProvider>
  );
}
