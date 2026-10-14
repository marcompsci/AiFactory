"use client";

import { useQuery } from "@tanstack/react-query";
import { useEffect } from "react";
import { api } from "@/lib/api";
import { human } from "@/lib/format";
import { Button, ErrorNote, Skeleton } from "./ui";

function DiffLine({ line }: { line: string }) {
  const cls = line.startsWith("+") && !line.startsWith("+++") ? "diff-add" : line.startsWith("-") && !line.startsWith("---") ? "diff-del" : line.startsWith("@@") ? "diff-hunk" : "";
  return <div className={`px-2 ${cls}`}>{line || " "}</div>;
}

export function ArtifactViewer({ id, onClose }: { id: string; onClose: () => void }) {
  const q = useQuery({ queryKey: ["artifact", id], queryFn: () => api.artifact(id) });
  useEffect(() => {
    const esc = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", esc);
    return () => window.removeEventListener("keydown", esc);
  }, [onClose]);
  const a = q.data;
  const isDiff = a && (a.kind === "diff" || a.kind === "patch");
  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-ground/70 p-0 sm:items-center sm:p-6" role="dialog" aria-modal="true" aria-label="Artifact" onClick={onClose}>
      <div className="glass flex max-h-[88dvh] w-full max-w-3xl flex-col rounded-t-2xl sm:rounded-2xl" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center gap-3 border-b border-line px-4 py-3">
          <div className="min-w-0">
            <div className="text-xs text-violet">{a ? human(a.kind) : "Artifact"}</div>
            <div className="truncate text-sm font-semibold">{a?.title ?? "Loading"}</div>
          </div>
          <Button className="ml-auto" onClick={() => a && navigator.clipboard?.writeText(a.content)} disabled={!a}>
            Copy
          </Button>
          <Button onClick={onClose} autoFocus>
            Close
          </Button>
        </div>
        <div className="scroll-thin overflow-auto p-2">
          {q.isLoading ? <Skeleton lines={8} /> : null}
          <ErrorNote error={q.error} />
          {a ? (
            <pre className="font-mono text-[12px] leading-relaxed text-ink-2">
              {isDiff ? String(a.content).split("\n").map((l, i) => <DiffLine key={i} line={l} />) : <div className="whitespace-pre-wrap px-2">{a.content}</div>}
            </pre>
          ) : null}
        </div>
      </div>
    </div>
  );
}
