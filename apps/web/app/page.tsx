"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import dynamic from "next/dynamic";
import { useEffect, useState } from "react";
import { ApprovalCall } from "@/components/command/Activity";
import { PackageCard } from "@/components/command/Company";
import { DistrictCard, Dock, TopBar } from "@/components/command/Shell";
import { useRealtime } from "@/hooks/useRealtime";

// WebGL only runs in the browser.
const CityScene = dynamic(() => import("@/components/world/CityScene").then((m) => m.CityScene), {
  ssr: false,
  loading: () => <div className="fixed inset-0 grid place-items-center text-sm text-ink-3">Building the city…</div>,
});

function App() {
  const [reconnectKey, setReconnectKey] = useState(0);
  useRealtime(reconnectKey);
  useEffect(() => {
    if ("serviceWorker" in navigator && process.env.NODE_ENV === "production") navigator.serviceWorker.register("/sw.js").catch(() => {});
  }, []);
  return (
    <main>
      <CityScene />
      <TopBar />
      <ApprovalCall />
      <DistrictCard />
      <PackageCard />
      <Dock onReconnect={() => setReconnectKey((k) => k + 1)} />
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
