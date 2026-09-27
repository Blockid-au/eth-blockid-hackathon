/**
 * v5 uploads. The browser reads every file (pdf.js / CSV) and sends text + the SHA-256 of the original bytes
 * (docs/EVALUATION-V5-API.md §3 documents); forecasts (docs/VALUATION-V5-API.md §2) are checked inline, then attested
 * and confirmed. Two modes: `vid` set → upload now (report page); no `vid` → kept in the /start draft and uploaded
 * right after the valuation is created (`flushUploads`).
 */
import { useRef, useState, type ReactNode } from "react";
import { errText } from "../../auth";
import { isMock } from "../../api";
import { api5, sha256Hex, type DocIn, type DocKind, type DocOut, type ProjectionIn, type ProjectionView } from "../../components/v5/api5";
import { downloadText, metricsTemplate, parseMetricsCsv, parseProjectionCsv, projectionTemplate, type LocalCheck, type MetricsParsed } from "../../components/v5/csv";
import { Checks, LevelBadge, useFmt5 } from "../../components/v5/ui";
import type { Check } from "../../components/v5/types";

const MAX_DECK = 20 * 1024 * 1024, MAX_CSV = 2 * 1024 * 1024, MAX_PROJ = 512 * 1024, MAX_CHARS = 60_000;

async function readPdfText(buf: ArrayBuffer): Promise<{ text: string; pages: number }> {
  const pdfjs = await import("pdfjs-dist/legacy/build/pdf.mjs");
  if (!pdfjs.GlobalWorkerOptions.workerPort) pdfjs.GlobalWorkerOptions.workerPort = new Worker(new URL("pdfjs-dist/legacy/build/pdf.worker.min.mjs", import.meta.url), { type: "module" });
  const doc = await pdfjs.getDocument({ data: new Uint8Array(buf), isEvalSupported: false }).promise;
  const parts: string[] = [];
  for (let i = 1; i <= Math.min(doc.numPages, 60); i++) {
    const page = await doc.getPage(i);
    const tc = await page.getTextContent();
    parts.push(`[slide ${i}] ` + (tc.items as { str?: string }[]).map((it) => it.str ?? "").join(" ").replace(/\s+/g, " ").trim());
    page.cleanup();
  }
  const pages = doc.numPages;
  await doc.destroy();
  return { text: parts.join("\n"), pages };
}

/** Server-side parse results (errors / consistency flags) as checks. */
function serverChecks(o: DocOut | undefined): Check[] {
  const p = o?.parsed;
  if (!p) return [];
  return [
    ...(p.errors ?? []).map((m) => ({ code: "server", severity: "error" as const, message: m })),
    ...(p.flags ?? []).map((f) => ({ code: f.code, severity: (f.severity === "high" ? "error" : f.severity === "info" ? "info" : "warning") as Check["severity"], message: f.message })),
  ];
}

export interface PendingDoc { doc: DocIn; checks: LocalCheck[]; metrics?: MetricsParsed; pages?: number }
export interface PendingProj { data: ProjectionIn | null; checks: LocalCheck[]; file: File | null; sha256: string; filename: string; attested: boolean }

/* ---------------- drop zone ---------------- */
function Drop({ accept, onFile, children, label }: { accept: string; onFile: (f: File) => void; children: ReactNode; label: string }) {
  const [over, setOver] = useState(false);
  const ref = useRef<HTMLInputElement>(null);
  return (
    <div className={"drop" + (over ? " over" : "")} onDragOver={(e) => { e.preventDefault(); setOver(true); }} onDragLeave={() => setOver(false)}
      onDrop={(e) => { e.preventDefault(); setOver(false); const f = e.dataTransfer.files?.[0]; if (f) onFile(f); }}>
      {children}
      <input ref={ref} type="file" accept={accept} hidden onChange={(e) => { const f = e.target.files?.[0]; if (f) onFile(f); e.target.value = ""; }} />
      <button type="button" className="btn ghost sm" onClick={() => ref.current?.click()}>{label}</button>
    </div>
  );
}

function MetricsPreview({ m }: { m: MetricsParsed }) {
  const { t, money, pct, fmt } = useFmt5();
  return (
    <div className="ktiles">
      <div className="kt"><small>{t("v5.up.months")}</small><b>{fmt(m.months)}</b></div>
      {m.last?.mrr != null && <div className="kt"><small>{t("v5.up.lastmrr", { m: m.last.month })}</small><b>{money(m.last.mrr)}</b></div>}
      {m.cmgr_pct != null && <div className="kt"><small>CMGR</small><b>{pct(m.cmgr_pct, 1)}</b></div>}
      {m.yoy_pct != null && <div className="kt"><small>{t("v5.up.yoy")}</small><b>{pct(m.yoy_pct, 0)}</b></div>}
      {m.nrr_pct != null && <div className="kt"><small>NRR</small><b>{pct(m.nrr_pct, 0)}</b></div>}
      {m.grr_pct != null && <div className="kt"><small>GRR</small><b>{pct(m.grr_pct, 0)}</b></div>}
    </div>
  );
}

type Item = PendingDoc & { state: "ready" | "sending" | "sent" | "error"; server?: Check[]; err?: string };

/* ---------------- pitch deck + metrics CSV ---------------- */
export function DocUploads({ vid, pending, setPending, onUploaded }: { vid?: string; pending?: PendingDoc[]; setPending?: (f: (p: PendingDoc[]) => PendingDoc[]) => void; onUploaded?: () => void }) {
  const { t } = useFmt5();
  const [items, setItems] = useState<Item[]>([]);
  const [msg, setMsg] = useState("");
  const list: Item[] = vid ? items : (pending ?? []).map((p) => ({ ...p, state: "ready" as const }));
  const hasErr = (p: PendingDoc) => p.checks.some((c) => c.severity === "error");

  const read = async (f: File) => {
    setMsg("");
    const isCsv = /\.csv$/i.test(f.name) || f.type === "text/csv";
    const kind: DocKind = isCsv ? "metrics_csv" : "deck";
    if (!/\.(pdf|csv|md|txt)$/i.test(f.name)) { setMsg(t("v5.up.type")); return; }
    if (f.size > (isCsv ? MAX_CSV : MAX_DECK)) { setMsg(t("v5.up.size", { m: isCsv ? "2 MB" : "20 MB" })); return; }
    let p: PendingDoc;
    try {
      const buf = await f.arrayBuffer();
      const sha256 = await sha256Hex(buf);
      if (isCsv) {
        const text = new TextDecoder().decode(buf);
        const m = parseMetricsCsv(text);
        p = { doc: { kind, filename: f.name, sha256, rows: text }, checks: m.checks, metrics: m };
      } else {
        const r = /\.pdf$/i.test(f.name) ? await readPdfText(buf) : { text: new TextDecoder().decode(buf), pages: undefined };
        const text = r.text.slice(0, MAX_CHARS);
        const checks: LocalCheck[] = [];
        if (text.replace(/\[slide \d+\]/g, "").trim().length < 200) checks.push({ code: "deck.scan", severity: "warning" });
        if (r.text.length > MAX_CHARS) checks.push({ code: "deck.cut", severity: "info", vars: { n: MAX_CHARS } });
        p = { doc: { kind, filename: f.name, sha256, text }, checks, pages: r.pages };
      }
    } catch { setMsg(t("v5.up.read")); return; }
    if (!vid) {
      setPending?.((xs) => [...xs.filter((x) => (kind === "metrics_csv" ? x.doc.kind !== "metrics_csv" : x.doc.sha256 !== p.doc.sha256)), p].slice(-5));
      return;
    }
    const idx = items.length;
    setItems((xs) => [...xs, { ...p, state: hasErr(p) ? "error" : "sending" }]);
    if (hasErr(p)) return;
    try {
      const out = await api5.addDocument(vid, p.doc);
      setItems((xs) => xs.map((x, i) => (i === idx ? { ...x, state: "sent", server: serverChecks(out) } : x)));
      onUploaded?.();
    } catch (e) {
      setItems((xs) => xs.map((x, i) => (i === idx ? { ...x, state: "error", err: errText(e, t) } : x)));
    }
  };

  return (
    <div className="stack" style={{ gap: 10 }}>
      <Drop accept=".pdf,.csv,.md,.txt,application/pdf,text/csv" onFile={(f) => void read(f)} label={t("v5.up.pick")}>
        <b>{t("v5.up.h")}</b>
        <span className="sub">{t("v5.up.p")}</span>
        <span className="row" style={{ gap: 6 }}><LevelBadge level={2} /><span className="hint">{t("v5.up.lvl")}</span></span>
        <button type="button" className="linkbtn" style={{ color: "var(--accent)", fontSize: ".82rem" }} onClick={() => downloadText("blockid-metrics-monthly.csv", metricsTemplate())}>↓ {t("v5.up.tpl")}</button>
      </Drop>
      {msg && <p className="hint bad" role="alert">{msg}</p>}
      {list.map((it, i) => {
        const st = hasErr(it) ? "error" : it.state;
        return (
          <div className="upl" key={it.doc.sha256 + i}>
            <div className="hd">
              <b>{it.doc.filename}</b>
              <span className="row" style={{ gap: 6 }}>
                <span className="pill">{t(it.doc.kind === "deck" ? "v5.up.deck" : "v5.up.csv")}{it.pages ? " · " + t("v5.up.pages", { n: it.pages }) : ""}</span>
                <span className={"pill " + (st === "sent" ? "ok" : st === "error" ? "bad" : "gold")}>{t(("v5.up.st." + (vid ? st : st === "error" ? "error" : "queued")) as "v5.up.st.ready")}</span>
                {!vid && <button type="button" className="xbtn" aria-label={t("v5.up.remove", { f: it.doc.filename })} onClick={() => setPending?.((xs) => xs.filter((x) => x.doc.sha256 !== it.doc.sha256))}>×</button>}
              </span>
            </div>
            {it.metrics && <MetricsPreview m={it.metrics} />}
            <Checks items={[...it.checks, ...(it.server ?? [])]} empty={t("v5.up.clean")} />
            {it.err && <p className="err">{it.err}</p>}
            <span className="hint mono">sha256 {it.doc.sha256.slice(0, 16)}…</span>
          </div>
        );
      })}
    </div>
  );
}

const EMPTY: ProjectionIn = { currency: "AUD", fiscal_year_end: "06-30", audited: false, cash: 0, debt: 0, shares_fd: null, planned_raise: 0, years: [] };

/* ---------------- forecast (valuation) ---------------- */
export function ProjectionsCard({ vid, stage, pending, setPending, onConfirmed }: { vid?: string; stage: string; pending?: PendingProj | null; setPending?: (p: PendingProj | null) => void; onConfirmed?: () => void }) {
  const { t, money, fmt, pct, lang } = useFmt5();
  const [local, setLocal] = useState<PendingProj | null>(null);
  const [server, setServer] = useState<ProjectionView | null>(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; s: string } | null>(null);
  const cur = vid ? local : pending ?? null;
  const set = (p: PendingProj | null) => { setServer(null); setMsg(null); if (vid) setLocal(p); else setPending?.(p); };
  const labels = Object.fromEntries(["year", "actual", "revenue", "cogs", "opex", "ebitda", "d_and_a", "tax", "capex", "nwc", "headcount", "customers", "currency", "fiscal_year_end", "cash", "debt", "shares_fd", "planned_raise", "audited"].map((k) => [k, t(("v5.pj.r." + k) as "v5.pj.r.year")]));

  const read = async (f: File) => {
    setMsg(null);
    if (/\.(xlsm|xls)$/i.test(f.name)) { setMsg({ ok: false, s: t("v5.pj.macro") }); return; }
    if (!/\.(csv|xlsx)$/i.test(f.name)) { setMsg({ ok: false, s: t("v5.pj.type") }); return; }
    if (f.size > MAX_PROJ) { setMsg({ ok: false, s: t("v5.up.size", { m: "512 KB" }) }); return; }
    const buf = await f.arrayBuffer();
    const sha256 = await sha256Hex(buf);
    if (/\.xlsx$/i.test(f.name)) { set({ data: null, checks: [{ code: "pj.xlsx", severity: "info" }], file: f, sha256, filename: f.name, attested: false }); return; }
    const r = parseProjectionCsv(new TextDecoder().decode(buf), stage);
    set({ data: r.data, checks: r.checks, file: f, sha256, filename: f.name, attested: false });
  };
  const localErr = (cur?.checks ?? []).some((c) => c.severity === "error");
  const serverErr = (server?.checks ?? []).some((c) => c.severity === "error");
  const errors = localErr || serverErr;
  const years = server?.parsed?.years ?? cur?.data?.years ?? [];

  /* upload (draft) → server checks shown; then confirm with the attestation */
  const upload = async () => {
    if (!vid || !cur) return;
    setBusy(true); setMsg(null);
    try { setServer(await api5.uploadProjections(vid, cur.data, cur.file)); } catch (e) { setMsg({ ok: false, s: errText(e, t) }); } finally { setBusy(false); }
  };
  const confirm = async () => {
    if (!vid || !server) return;
    setBusy(true); setMsg(null);
    try {
      const r = await api5.confirmProjections(vid, server.id);
      setServer(r.projection);
      setMsg({ ok: true, s: r.value_before_aud != null && r.value_after_aud != null ? t("v5.pj.moved", { a: money(r.value_before_aud), b: money(r.value_after_aud), p: pct(r.moved_pct ?? 0, 1) }) + (r.back_to_review ? " " + t("v5.pj.back") : "") : t("v5.pj.done") });
      onConfirmed?.();
    } catch (e) { setMsg({ ok: false, s: errText(e, t) }); } finally { setBusy(false); }
  };
  const step = !cur ? 1 : !server && vid ? 2 : errors || !cur.attested ? 2 : 3;
  const tplCsv = () => downloadText("blockid-projections-v1.csv", projectionTemplate(labels));

  return (
    <div className="card">
      <div className="between"><h4>{t("v5.pj.h")}</h4><span className="pill">{t("v5.pj.opt")}</span></div>
      <p className="sub">{t("v5.pj.p")}</p>
      <ol className="wzsteps" style={{ ["--n" as string]: 3 }}>
        {[t("v5.pj.s1"), t("v5.pj.s2"), t("v5.pj.s3")].map((s, i) => <li key={i} className={i + 1 === step ? "on" : i + 1 < step ? "done" : ""}><span><b>{String(i + 1).padStart(2, "0")}</b><span>{s}</span></span></li>)}
      </ol>
      <div className="row">
        {isMock ? <button type="button" className="btn ghost sm" onClick={tplCsv}>↓ {t("v5.pj.tpl.csv")}</button>
          : <a className="btn ghost sm" href={api5.templateUrl("csv", lang)} download>↓ {t("v5.pj.tpl.csv")}</a>}
        {!isMock && <a className="btn ghost sm" href={api5.templateUrl("xlsx", lang)} download>↓ {t("v5.pj.tpl.xlsx")}</a>}
      </div>
      <Drop accept=".csv,.xlsx,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" onFile={(f) => void read(f)} label={t("v5.pj.pick")}>
        <span className="sub">{t("v5.pj.drop")}</span>
      </Drop>
      {cur && (
        <div className="upl">
          <div className="hd"><b>{cur.filename}</b><button type="button" className="xbtn" aria-label={t("v5.up.remove", { f: cur.filename })} onClick={() => set(null)}>×</button></div>
          {years.length > 0 && (
            <div className="pgrid tbl">
              <table>
                <caption className="sr-only">{t("v5.pj.h")}</caption>
                <thead><tr><th>{t("v5.col.year")}</th>{years.map((y) => <th key={y.year} className="r">{y.year} {y.actual ? "A" : "P"}</th>)}</tr></thead>
                <tbody>
                  <tr><td>{t("v5.pj.r.revenue")}</td>{years.map((y) => <td key={y.year} className="r">{money(y.revenue)}</td>)}</tr>
                  <tr><td>EBITDA</td>{years.map((y) => <td key={y.year} className="r">{money(y.ebitda ?? y.revenue - y.cogs - y.opex)}</td>)}</tr>
                  <tr><td>{t("v5.pj.gm")}</td>{years.map((y) => <td key={y.year} className="r">{y.revenue ? fmt(((y.revenue - y.cogs) / y.revenue) * 100) + "%" : "–"}</td>)}</tr>
                </tbody>
              </table>
            </div>
          )}
          <Checks items={server ? server.checks : cur.checks} empty={t("v5.pj.clean")} />
          {server && <p className="hint">{t("v5.pj.server", { e: server.errors ?? server.checks.filter((c) => c.severity === "error").length, w: server.warnings ?? server.checks.filter((c) => c.severity === "warning").length })}</p>}
          {!errors && (server || !vid) && (
            <label className="row" style={{ alignItems: "flex-start", fontSize: ".84rem" }}>
              <input type="checkbox" checked={cur.attested} onChange={(e) => (vid ? setLocal({ ...cur, attested: e.target.checked }) : setPending?.({ ...cur, attested: e.target.checked }))} style={{ marginTop: 4 }} />
              <span>{t("v5.pj.attest")}</span>
            </label>
          )}
          <p className="lbl-proj">{t("v5.proj.label")}</p>
          {vid ? (
            !server ? <button type="button" className="btn" style={{ justifySelf: "start" }} disabled={busy || localErr} onClick={() => void upload()}>{busy ? <span className="spinner" aria-hidden="true" /> : null}{t("v5.pj.check")}</button>
              : server.status === "confirmed" ? <span className="pill ok" style={{ justifySelf: "start" }}>✓ {t("v5.pj.confirmed")}</span>
                : <button type="button" className="btn gold" style={{ justifySelf: "start" }} disabled={busy || errors || !cur.attested || server.can_confirm === false} onClick={() => void confirm()}>{busy ? <span className="spinner" aria-hidden="true" /> : null}{t("v5.pj.confirm")}</button>
          ) : cur.attested && !errors ? <span className="pill ok" style={{ justifySelf: "start" }}>✓ {t("v5.pj.queued")}</span> : null}
        </div>
      )}
      {msg && <p className={msg.ok ? "banner ok" : "hint bad"} role={msg.ok ? "status" : "alert"}>{msg.s}</p>}
    </div>
  );
}

/** After POST /v1/studio/valuations: send what the founder added on /start. Failures are reported, never block. */
export async function flushUploads(vid: string, docs: PendingDoc[], proj: PendingProj | null): Promise<string[]> {
  const errs: string[] = [];
  for (const d of docs) {
    if (d.checks.some((c) => c.severity === "error")) continue;
    try { await api5.addDocument(vid, d.doc); } catch (e) { errs.push(d.doc.filename + ": " + (e instanceof Error ? e.message : String(e))); }
  }
  if (proj && proj.attested && !proj.checks.some((c) => c.severity === "error")) {
    try {
      const up = await api5.uploadProjections(vid, proj.data ?? EMPTY, proj.file);
      if (!up.checks.some((c) => c.severity === "error")) await api5.confirmProjections(vid, up.id);
      else errs.push(proj.filename + ": " + up.checks.filter((c) => c.severity === "error").map((c) => c.message).join("; "));
    } catch (e) { errs.push(proj.filename + ": " + (e instanceof Error ? e.message : String(e))); }
  }
  return errs;
}
