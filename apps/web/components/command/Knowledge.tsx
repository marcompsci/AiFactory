"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { knowledge, type Json } from "@/lib/api";
import { ago } from "@/lib/format";
import { Button, Empty, ErrorNote, Pill, Section, Skeleton } from "./ui";

const COMPANY_COLOR: Record<string, string> = { phoronomics: "#9BE7FF", phoronomic_studios: "#C9A3FF", shared: "#F4D58D" };
const COMPANIES = [
  { id: "", label: "All" },
  { id: "phoronomics", label: "Phoronomics" },
  { id: "phoronomic_studios", label: "Phoronomic Studios" },
];

/** The company knowledge base floating over the city: docs and skills for Phoronomics and Phoronomic Studios. */
export function KnowledgePanel() {
  const qc = useQueryClient();
  const [company, setCompany] = useState("");
  const [kind, setKind] = useState("");
  const [q, setQ] = useState("");
  const [open, setOpen] = useState<string | null>(null);
  const [editing, setEditing] = useState<Json | null>(null);
  const [uploadTo, setUploadTo] = useState("shared");
  const [uploaded, setUploaded] = useState<string | null>(null);
  const files = useRef<HTMLInputElement>(null);
  const list = useQuery({ queryKey: ["knowledge", company, kind, q], queryFn: () => knowledge.list(q, company, kind) });
  const refresh = () => qc.invalidateQueries({ queryKey: ["knowledge"] });
  const upload = useMutation({
    mutationFn: async (fl: FileList) => {
      const md = Array.from(fl).filter((f) => /\.(md|markdown|txt)$/i.test(f.name));
      for (const f of md) await knowledge.upload(f, uploadTo);
      return md.length;
    },
    onSuccess: (n) => { setUploaded(`Added ${n} file${n === 1 ? "" : "s"}.`); refresh(); },
  });

  if (editing) return <Editor doc={editing} onDone={() => { setEditing(null); refresh(); }} />;
  if (open) return <Reader slug={open} onBack={() => setOpen(null)} onEdit={(d) => setEditing(d)} onRemoved={() => { setOpen(null); refresh(); }} />;

  const d = list.data;
  return (
    <div className="space-y-4" data-testid="knowledge-panel">
      <p className="text-xs text-ink-2">
        What every agent can pull from: company docs and skills for Phoronomics and Phoronomic Studios. Agents get the entries that fit
        their task with each step, and can search and read the rest. Nothing here can override their safety rules or your approvals.
      </p>
      <div className="flex flex-wrap gap-1.5">
        {COMPANIES.map((c) => (
          <button key={c.id} type="button" onClick={() => setCompany(c.id)} aria-pressed={company === c.id}
            className={`rounded-full px-2.5 py-1 text-xs ${company === c.id ? "bg-white/15 text-ink" : "bg-white/5 text-ink-2"}`}>{c.label}</button>
        ))}
        <span className="mx-1 w-px bg-line" />
        {[["", "Everything"], ["skill", `Skills${d ? ` ${d.counts.skill}` : ""}`], ["doc", `Docs${d ? ` ${d.counts.doc}` : ""}`]].map(([id, label]) => (
          <button key={id} type="button" onClick={() => setKind(id)} aria-pressed={kind === id}
            className={`rounded-full px-2.5 py-1 text-xs ${kind === id ? "bg-white/15 text-ink" : "bg-white/5 text-ink-2"}`}>{label}</button>
        ))}
      </div>
      <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search docs and skills" aria-label="Search the knowledge base"
        className="w-full rounded-lg border border-line bg-transparent px-3 py-2 text-sm" />
      {d?.can_edit ? (
        <div className="flex flex-wrap items-center gap-2">
          <Button variant="primary" onClick={() => setEditing({ company: company || "shared", kind: kind || "doc", title: "", body: "", description: "" })}>New doc</Button>
          <select value={uploadTo} onChange={(e) => setUploadTo(e.target.value)} aria-label="Upload to"
            className="rounded-lg border border-line bg-ground px-2 py-1.5 text-xs">
            <option value="shared">Both companies</option><option value="phoronomics">Phoronomics</option><option value="phoronomic_studios">Phoronomic Studios</option>
          </select>
          <Button onClick={() => files.current?.click()} disabled={upload.isPending}>{upload.isPending ? "Uploading…" : "Upload .md files"}</Button>
          <input ref={files} type="file" multiple accept=".md,.markdown,.txt,text/markdown,text/plain" className="hidden"
            onChange={(e) => e.target.files?.length && upload.mutate(e.target.files)} data-testid="knowledge-upload" />
          {uploaded ? <span className="text-xs text-ok">{uploaded}</span> : null}
        </div>
      ) : null}
      <ErrorNote error={list.error || upload.error} />
      {list.isLoading ? <Skeleton lines={5} /> : null}
      {d && !d.items.length ? <Empty>{q ? "Nothing matches." : "Empty. Add a doc or upload SKILL.md files."}</Empty> : null}
      <ul className="space-y-2">
        {(d?.items ?? []).map((it: Json) => (
          <li key={it.slug}>
            <button type="button" onClick={() => setOpen(it.slug)} className="w-full rounded-lg border border-line p-2 text-left hover:bg-white/5">
              <div className="flex items-center gap-2">
                <span className="text-[11px]" aria-hidden>{it.kind === "skill" ? "✦" : "▤"}</span>
                <span className="min-w-0 flex-1 truncate text-sm">{it.title}</span>
                <Pill color={COMPANY_COLOR[it.company]}>{it.company_name}</Pill>
              </div>
              {it.description ? <p className="mt-0.5 line-clamp-2 text-xs text-ink-3">{it.description}</p> : null}
              <p className="mt-0.5 text-[11px] text-ink-3">{it.kind === "skill" ? "Skill" : "Doc"} · {(it.size / 1024).toFixed(1)} KB · {it.source} · {ago(it.updated_at)}</p>
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

function Reader({ slug, onBack, onEdit, onRemoved }: { slug: string; onBack: () => void; onEdit: (d: Json) => void; onRemoved: () => void }) {
  const q = useQuery({ queryKey: ["knowledge-doc", slug], queryFn: () => knowledge.get(slug) });
  const can = useQuery({ queryKey: ["knowledge", "", "", ""], queryFn: () => knowledge.list() }).data?.can_edit;
  const [confirm, setConfirm] = useState(false);
  const del = useMutation({ mutationFn: () => knowledge.remove(slug), onSuccess: onRemoved });
  const d = q.data;
  return (
    <div className="space-y-3">
      <Button onClick={onBack}>← All entries</Button>
      <ErrorNote error={q.error || del.error} />
      {d ? (
        <>
          <div className="flex items-start gap-2">
            <h3 className="min-w-0 flex-1 text-base font-semibold">{d.title}</h3>
            <Pill color={COMPANY_COLOR[d.company]}>{d.company_name}</Pill>
          </div>
          {d.description ? <p className="text-xs text-ink-2">{d.description}</p> : null}
          <p className="text-[11px] text-ink-3">{d.kind === "skill" ? "Skill" : "Doc"} · {d.source} · updated {ago(d.updated_at)} · <span className="font-mono">{d.slug}</span></p>
          {can ? (
            <div className="flex gap-2">
              <Button onClick={() => onEdit(d)}>Edit</Button>
              {confirm ? (
                <>
                  <Button variant="danger" onClick={() => del.mutate()} disabled={del.isPending}>Delete for good</Button>
                  <Button onClick={() => setConfirm(false)}>Keep it</Button>
                </>
              ) : <Button onClick={() => setConfirm(true)}>Delete</Button>}
            </div>
          ) : null}
          <Section title="Contents">
            <pre className="scroll-thin max-h-[50dvh] overflow-auto whitespace-pre-wrap rounded border border-line p-2 font-mono text-[11px] leading-relaxed text-ink-2">{d.body}</pre>
          </Section>
        </>
      ) : <Skeleton lines={6} />}
    </div>
  );
}

function Editor({ doc, onDone }: { doc: Json; onDone: () => void }) {
  const [f, setF] = useState({ title: doc.title ?? "", company: doc.company ?? "shared", kind: doc.kind ?? "doc", description: doc.description ?? "", body: doc.body ?? "" });
  const save = useMutation({ mutationFn: () => (doc.slug ? knowledge.update(doc.slug, f) : knowledge.create(f)), onSuccess: onDone });
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value });
  return (
    <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); save.mutate(); }}>
      <Button onClick={onDone}>← Cancel</Button>
      <label className="block space-y-1 text-xs"><span className="text-ink-3">Title</span>
        <input required maxLength={160} value={f.title} onChange={set("title")} className="w-full rounded border border-line bg-transparent px-2 py-1.5 text-sm" /></label>
      <div className="grid grid-cols-2 gap-2 text-xs">
        <label className="space-y-1"><span className="text-ink-3">Company</span>
          <select value={f.company} onChange={set("company")} className="w-full rounded border border-line bg-ground px-2 py-1.5">
            <option value="phoronomics">Phoronomics</option><option value="phoronomic_studios">Phoronomic Studios</option><option value="shared">Both</option>
          </select></label>
        <label className="space-y-1"><span className="text-ink-3">Kind</span>
          <select value={f.kind} onChange={set("kind")} className="w-full rounded border border-line bg-ground px-2 py-1.5">
            <option value="doc">Doc</option><option value="skill">Skill</option>
          </select></label>
      </div>
      <label className="block space-y-1 text-xs"><span className="text-ink-3">One-line description (agents use it to decide when it applies)</span>
        <input maxLength={1000} value={f.description} onChange={set("description")} className="w-full rounded border border-line bg-transparent px-2 py-1.5 text-sm" /></label>
      <label className="block space-y-1 text-xs"><span className="text-ink-3">Contents (Markdown)</span>
        <textarea value={f.body} onChange={set("body")} rows={14} className="w-full rounded border border-line bg-transparent p-2 font-mono text-[12px]" /></label>
      <ErrorNote error={save.error} />
      <Button type="submit" variant="primary" className="w-full" disabled={save.isPending || !f.title.trim()}>{doc.slug ? "Save changes" : "Add to the knowledge base"}</Button>
    </form>
  );
}
