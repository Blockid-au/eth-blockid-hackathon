/**
 * /start — stage-aware founder inputs v2 (docs/PLAN-EVALUATION-V5.md §3.1 / §5.1, docs/EVALUATION-V5-API.md §3).
 * A short step-by-step flow: 1 stage ("Looks like: Seed — change") · 2 revenue & customers · 3 retention & efficiency ·
 * 4 market, moat & last round · 5 documents (deck / metrics CSV, forecast). Only the fields that matter at the chosen
 * stage are shown; each says why it matters and how it is checked (L1 typed → L2 with a document).
 * Shown only when GET /v1/studio/evaluation/config says v5 is enabled; otherwise /start is unchanged.
 */
import { useEffect, useMemo, useState } from "react";
import type { DictKey } from "../../dict";
import { api5, evalConfig, type EvalConfig } from "../../components/v5/api5";
import { LevelBadge, StageBadge, useFmt5 } from "../../components/v5/ui";
import { STAGES } from "../../components/v5/types";
import { DocUploads, flushUploads, ProjectionsCard, type PendingDoc, type PendingProj } from "./Uploads";

type Kind = "aud" | "pct" | "int" | "months" | "text" | "url" | "list" | "month" | "select" | "note";
type Group = "revenue" | "customers" | "retention" | "efficiency" | "market" | "moat" | "round";
interface F { key: string; group: Group; kind: Kind; min: number; max?: number; lo?: number; minStage: (typeof STAGES)[number]; only?: (typeof STAGES)[number][]; opts?: string[]; ex?: string; marketplace?: boolean }

/** Mirrors schemas.SelfReportedMetricsV2 (keys + bounds). `minStage` follows the plan's §3.1 table. */
export const FIELDS: F[] = [
  { key: "revenue_ttm_aud", group: "revenue", kind: "aud", min: 0, max: 1e12, minStage: "idea", ex: "450000" },
  { key: "revenue_model", group: "revenue", kind: "select", min: 0, minStage: "idea", opts: ["subscription", "transactional", "marketplace", "services", "hardware", "other"] },
  { key: "mrr_aud", group: "revenue", kind: "aud", min: 0, max: 1e11, minStage: "pre-seed", ex: "38000" },
  { key: "revenue_prev_ttm_aud", group: "revenue", kind: "aud", min: 0, max: 1e12, minStage: "seed", ex: "210000" },
  { key: "arr_aud", group: "revenue", kind: "aud", min: 0, max: 1e12, minStage: "seed", ex: "456000" },
  { key: "mrr_6m_ago_aud", group: "revenue", kind: "aud", min: 0, max: 1e11, minStage: "seed" },
  { key: "mrr_12m_ago_aud", group: "revenue", kind: "aud", min: 0, max: 1e11, minStage: "seed" },
  { key: "gmv_ttm_aud", group: "revenue", kind: "aud", min: 0, max: 1e13, minStage: "seed", marketplace: true },
  { key: "take_rate_pct", group: "revenue", kind: "pct", min: 0, max: 100, minStage: "seed", marketplace: true },
  { key: "gross_margin_pct", group: "revenue", kind: "pct", min: -100, max: 100, minStage: "seed", ex: "72" },
  { key: "waitlist", group: "customers", kind: "int", min: 0, max: 1e9, minStage: "idea", only: ["idea", "pre-seed"], ex: "800" },
  { key: "pilots_paid", group: "customers", kind: "int", min: 0, max: 1e5, minStage: "idea", only: ["idea", "pre-seed"], ex: "2" },
  { key: "lois", group: "customers", kind: "int", min: 0, max: 1e5, minStage: "idea", only: ["idea", "pre-seed"], ex: "4" },
  { key: "paying_customers", group: "customers", kind: "int", min: 0, max: 1e9, minStage: "idea", ex: "120" },
  { key: "active_users_monthly", group: "customers", kind: "int", min: 0, max: 1e10, minStage: "idea" },
  { key: "paying_customers_12m_ago", group: "customers", kind: "int", min: 0, max: 1e9, minStage: "seed" },
  { key: "active_users_daily", group: "customers", kind: "int", min: 0, max: 1e10, minStage: "seed" },
  { key: "contracted_backlog_aud", group: "customers", kind: "aud", min: 0, max: 1e12, minStage: "seed" },
  { key: "qualified_pipeline_aud", group: "customers", kind: "aud", min: 0, max: 1e12, minStage: "seed" },
  { key: "top_customer_share_pct", group: "customers", kind: "pct", min: 0, max: 100, minStage: "seed", ex: "18" },
  { key: "public_logos", group: "customers", kind: "list", min: 0, max: 30, minStage: "idea", ex: "Linfox, Toll" },
  { key: "logo_churn_monthly_pct", group: "retention", kind: "pct", min: 0, max: 100, minStage: "seed", ex: "2.5" },
  { key: "grr_pct", group: "retention", kind: "pct", min: 0, max: 100, minStage: "seed", ex: "90" },
  { key: "nrr_pct", group: "retention", kind: "pct", min: 0, max: 500, minStage: "seed", ex: "108" },
  { key: "m3_retention_pct", group: "retention", kind: "pct", min: 0, max: 100, minStage: "seed" },
  { key: "m12_retention_pct", group: "retention", kind: "pct", min: 0, max: 100, minStage: "seed" },
  { key: "nps", group: "retention", kind: "int", min: -100, max: 100, lo: -100, minStage: "pre-seed" },
  { key: "raised_to_date_aud", group: "efficiency", kind: "aud", min: 0, max: 1e12, minStage: "idea" },
  { key: "cash_aud", group: "efficiency", kind: "aud", min: 0, max: 1e12, minStage: "pre-seed" },
  { key: "burn_monthly_aud", group: "efficiency", kind: "aud", min: 0, max: 1e11, minStage: "pre-seed" },
  { key: "net_new_arr_12m_aud", group: "efficiency", kind: "aud", min: -1e12, max: 1e12, minStage: "seed" },
  { key: "cac_aud", group: "efficiency", kind: "aud", min: 0, max: 1e9, minStage: "seed" },
  { key: "arpa_monthly_aud", group: "efficiency", kind: "aud", min: 0, max: 1e9, minStage: "seed" },
  { key: "employees", group: "efficiency", kind: "int", min: 0, max: 1e7, minStage: "idea" },
  { key: "target_customer", group: "market", kind: "text", min: 0, max: 120, minStage: "idea", ex: "Australian freight carriers with 5–200 trucks" },
  { key: "target_customer_count", group: "market", kind: "int", min: 0, max: 1e10, minStage: "idea", ex: "38000" },
  { key: "target_count_source_url", group: "market", kind: "url", min: 0, max: 500, minStage: "idea", ex: "https://www.abs.gov.au/…" },
  { key: "annual_price_aud", group: "market", kind: "aud", min: 0, max: 1e9, minStage: "idea", ex: "4800" },
  { key: "geographies", group: "market", kind: "list", min: 0, max: 20, minStage: "idea", ex: "AU, NZ" },
  { key: "patents", group: "moat", kind: "list", min: 0, max: 20, minStage: "idea", ex: "AU2024123456" },
  { key: "trademarks", group: "moat", kind: "list", min: 0, max: 20, minStage: "idea" },
  { key: "licences", group: "moat", kind: "list", min: 0, max: 20, minStage: "idea", ex: "AFSL 123456" },
  { key: "integrations_count", group: "moat", kind: "int", min: 0, max: 1e5, minStage: "idea", ex: "14" },
  { key: "exclusive_contracts", group: "moat", kind: "int", min: 0, max: 1e4, minStage: "idea" },
  { key: "moat_note", group: "moat", kind: "note", min: 0, max: 500, minStage: "idea" },
  { key: "last_round_type", group: "round", kind: "select", min: 0, minStage: "idea", opts: ["pre-seed", "angel", "seed", "series-a", "series-b", "series-c", "grant", "safe", "other"] },
  { key: "last_round_date", group: "round", kind: "month", min: 0, minStage: "idea" },
  { key: "last_round_post_money_aud", group: "round", kind: "aud", min: 0, max: 1e13, minStage: "idea" },
  { key: "lead_investor", group: "round", kind: "text", min: 0, max: 120, minStage: "idea" },
];
const STEP_GROUPS: Group[][] = [[], ["revenue", "customers"], ["retention", "efficiency"], ["market", "moat", "round"], []];
const si = (s: string) => Math.max(0, (STAGES as readonly string[]).indexOf(s));

export type Raw5 = Record<string, string>;
const KEY = "blockid-start-v5";
function loadRaw(): { raw: Raw5; stage: string | null } {
  try { const d = JSON.parse(localStorage.getItem(KEY) || "null"); return { raw: d?.raw && typeof d.raw === "object" ? d.raw : {}, stage: typeof d?.stage === "string" ? d.stage : null }; } catch { return { raw: {}, stage: null }; }
}

/** Deterministic preview of tools/stage.py rules (round ≤ 30 months > revenue band > raised); the server preview wins. */
export function localStage(raw: Raw5): { stage: string; basis: string } {
  const n = (k: string) => { const x = Number(raw[k]); return raw[k] && Number.isFinite(x) ? x : null; };
  const r = raw.last_round_type;
  const recent = !raw.last_round_date || (Date.now() - +new Date(raw.last_round_date + "-01")) / (30.4 * 864e5) <= 30;
  const byRound = r && recent ? ({ "pre-seed": "pre-seed", angel: "pre-seed", safe: "pre-seed", seed: "seed", "series-a": "series-a", "series-b": "growth", "series-c": "growth" } as Record<string, string>)[r] : undefined;
  const rev = n("arr_aud") ?? n("revenue_ttm_aud") ?? (n("mrr_aud") != null ? n("mrr_aud")! * 12 : null);
  const byRev = rev == null ? null : rev <= 0 ? "idea" : rev < 150e3 ? "pre-seed" : rev < 1.5e6 ? "seed" : rev < 15e6 ? "series-a" : "growth";
  if (byRound && byRev && Math.abs(si(byRound) - si(byRev)) >= 2) return { stage: si(byRound) < si(byRev) ? byRound : byRev, basis: "conflict" };
  if (byRound) return { stage: byRound, basis: "round" };
  if (byRev) return { stage: byRev, basis: "revenue" };
  const raised = n("raised_to_date_aud");
  if (raised != null) return { stage: raised < 1e6 ? "pre-seed" : raised < 5e6 ? "seed" : raised < 30e6 ? "series-a" : "growth", basis: "raised" };
  return { stage: "pre-seed", basis: "default" };
}

function clean(kind: Kind, s: string): string {
  if (kind === "aud" || kind === "int") return (s.trim().startsWith("-") ? "-" : "") + s.replace(/\D/g, "").replace(/^0+(?=\d)/, "");
  if (kind === "pct" || kind === "months") { let x = s.replace(/,/g, ".").replace(/[^\d.-]/g, ""); x = (x.startsWith("-") ? "-" : "") + x.replace(/-/g, ""); const i = x.indexOf("."); return i < 0 ? x : x.slice(0, i + 1) + x.slice(i + 1).replace(/\./g, ""); }
  return s;
}

/** raw → SelfReportedMetricsV2 body + the keys that are out of bounds. Only fields shown at `stage` are sent. */
export function collect(raw: Raw5, stage: string): { metrics: Record<string, unknown>; bad: string[] } {
  const metrics: Record<string, unknown> = {};
  const bad: string[] = [];
  for (const f of FIELDS) {
    const s = (raw[f.key] ?? "").trim();
    if (!s || !visible(f, stage, raw)) continue;
    if (f.kind === "text" || f.kind === "note" || f.kind === "select") { if (s.length > (f.max ?? 120)) bad.push(f.key); else metrics[f.key] = s; continue; }
    if (f.kind === "url") { if (!/^https?:\/\/\S+\.\S+/.test(s) || s.length > 500) bad.push(f.key); else metrics[f.key] = s; continue; }
    if (f.kind === "month") { if (!/^\d{4}(-\d{2})?$/.test(s)) bad.push(f.key); else metrics[f.key] = s; continue; }
    if (f.kind === "list") { const xs = s.split(/[,;\n]/).map((x) => x.trim()).filter(Boolean); if (xs.length > (f.max ?? 20) || xs.some((x) => x.length > 120)) bad.push(f.key); else if (xs.length) metrics[f.key] = xs; continue; }
    const n = Number(s);
    if (!Number.isFinite(n) || n < (f.lo ?? f.min) || n > (f.max ?? 1e15) || (f.kind === "int" && !Number.isInteger(n))) bad.push(f.key);
    else metrics[f.key] = n;
  }
  return { metrics, bad };
}
function visible(f: F, stage: string, raw: Raw5): boolean {
  if (f.only && !f.only.includes(stage as (typeof STAGES)[number])) return false;
  if (f.marketplace && raw.revenue_model !== "marketplace") return false;
  return si(stage) >= si(f.minStage);
}

/* ---------------- state hook (owned by NewWizard) ---------------- */
export function useStartV5() {
  const [cfg, setCfg] = useState<EvalConfig | null>(null);
  useEffect(() => { let live = true; void evalConfig().then((c) => { if (live) setCfg(c); }); return () => { live = false; }; }, []);
  const [d0] = useState(loadRaw);
  const [raw, setRaw] = useState<Raw5>(d0.raw);
  const [declared, setDeclared] = useState<string | null>(d0.stage);
  const [docs, setDocs] = useState<PendingDoc[]>([]);
  const [proj, setProj] = useState<PendingProj | null>(null);
  const [bad, setBad] = useState<string[]>([]);
  const [server, setServer] = useState<{ stage: string; basis: string; reasons: string[] } | null>(null);
  const guess = useMemo(() => localStage(raw), [raw]);
  // server preview (tools/stage.py) when signed in; the local rules stand in otherwise
  useEffect(() => {
    if (!cfg?.enabled) return;
    const { metrics } = collect(raw, "growth");
    if (!Object.keys(metrics).length) { setServer(null); return; }
    const id = setTimeout(() => { api5.stagePreview(metrics).then(setServer).catch(() => setServer(null)); }, 600);
    return () => clearTimeout(id);
  }, [raw, cfg?.enabled]);
  const detected = server?.stage && si(server.stage) >= 0 ? server.stage : guess.stage;
  const stage = declared ?? detected;
  useEffect(() => { try { localStorage.setItem(KEY, JSON.stringify({ raw, stage: declared })); } catch { /* private mode */ } }, [raw, declared]);
  return {
    enabled: cfg?.enabled === true, cfg, raw, setRaw, stage, detected, declared, setDeclared, basis: server?.basis ?? guess.basis, reasons: server?.reasons ?? [],
    docs, setDocs, proj, setProj, bad, setBad,
    collect: () => { const c = collect(raw, stage); setBad(c.bad); return c; },
    flush: (vid: string) => flushUploads(vid, docs, proj),
    clear: () => { setRaw({}); setDeclared(null); setDocs([]); setProj(null); setBad([]); try { localStorage.removeItem(KEY); } catch { /* */ } },
    used: () => Object.values(raw).some(Boolean) || docs.length > 0 || !!proj,
  };
}
export type StartV5 = ReturnType<typeof useStartV5>;

/* ---------------- one field ---------------- */
function Field({ f, s }: { f: F; s: StartV5 }) {
  const { t, fmt } = useFmt5();
  const v = s.raw[f.key] ?? "";
  const isBad = s.bad.includes(f.key);
  const set = (x: string) => s.setRaw((r) => ({ ...r, [f.key]: x }));
  const lbl = t(("v5.f." + f.key) as DictKey);
  const why = t(("v5.f." + f.key + ".why") as DictKey);
  const shown = (f.kind === "aud" || f.kind === "int") && v && v !== "-" ? (v.startsWith("-") ? "-" : "") + fmt(Math.abs(Number(v))) : v;
  const id = "f5-" + f.key;
  const unit = f.kind === "aud" ? "A$" : f.kind === "pct" ? "%" : null;
  return (
    <div className={"sfield" + (isBad ? " bad" : "")}>
      <span><label htmlFor={id}>{lbl}</label><LevelBadge level={1} short /></span>
      {f.kind === "select" ? (
        <select id={id} className="inp" value={v} onChange={(e) => set(e.target.value)} aria-describedby={id + "-w"}>
          <option value="">–</option>
          {f.opts!.map((o) => <option key={o} value={o}>{t(("v5.opt." + o) as DictKey)}</option>)}
        </select>
      ) : f.kind === "note" ? (
        <textarea id={id} className="inp" value={v} maxLength={f.max} onChange={(e) => set(e.target.value)} aria-describedby={id + "-w"} rows={3} />
      ) : (
        <span className="srin">
          {unit === "A$" && <i aria-hidden="true">A$</i>}
          <input id={id} type={f.kind === "month" ? "month" : f.kind === "url" ? "url" : "text"} autoComplete="off" value={shown} placeholder={f.ex ? t("v5.eg", { x: f.kind === "aud" || f.kind === "int" ? fmt(Number(f.ex)) : f.ex }) : "–"}
            inputMode={f.kind === "aud" || f.kind === "int" ? "numeric" : f.kind === "pct" || f.kind === "months" ? "decimal" : undefined} aria-invalid={isBad} aria-describedby={id + "-w"}
            onChange={(e) => set(clean(f.kind, e.target.value))} />
          {unit === "%" && <i aria-hidden="true">%</i>}
        </span>
      )}
      <span className="why" id={id + "-w"}>{why}</span>
      {isBad && <span className="hint bad" role="alert">{t("v5.f.bad")}</span>}
    </div>
  );
}

/* ---------------- the flow ---------------- */
export function StartInputs({ s, listing }: { s: StartV5; listing?: boolean }) {
  const { t, stage: sl } = useFmt5();
  const [step, setStep] = useState(0);
  const groupsAt = (i: number) => STEP_GROUPS[i].map((g) => ({ g, fs: FIELDS.filter((f) => f.group === g && visible(f, s.stage, s.raw)) })).filter((x) => x.fs.length);
  const steps = [0, 1, 2, 3, 4].filter((i) => i === 0 || i === 4 || groupsAt(i).length > 0);
  const k = Math.min(step, steps.length - 1);
  const cur = steps[k];
  const filled = (i: number) => STEP_GROUPS[i].reduce((a, g) => a + FIELDS.filter((f) => f.group === g && s.raw[f.key]).length, 0);
  const NAMES = [t("v5.in.s0"), t("v5.in.s1"), t("v5.in.s2"), t("v5.in.s3"), t("v5.in.s4")];
  const nFilled = FIELDS.filter((f) => s.raw[f.key] && visible(f, s.stage, s.raw)).length;
  useEffect(() => { if (s.bad.length) { const f = FIELDS.find((x) => x.key === s.bad[0]); const i = f ? STEP_GROUPS.findIndex((gs) => gs.includes(f.group)) : -1; const j = steps.indexOf(i); if (j >= 0) setStep(j); } }, [s.bad]); // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <details className="srbox v5" open={nFilled > 0 || s.docs.length > 0 || undefined}>
      <summary>{t(listing ? "v5.in.h.list" : "v5.in.h")}{nFilled > 0 && <span className="pill gold" style={{ marginLeft: 8 }}>{nFilled}</span>}{s.docs.length + (s.proj ? 1 : 0) > 0 && <span className="pill ok" style={{ marginLeft: 6 }}>{t("v5.in.files", { n: s.docs.length + (s.proj ? 1 : 0) })}</span>}</summary>
      <p className="note" style={{ margin: 0 }}>{t("v5.in.p")}</p>
      <ol className="wzsteps" style={{ ["--n" as string]: steps.length }}>
        {steps.map((i, j) => (
          <li key={i} className={j === k ? "on" : j < k ? "done" : ""} aria-current={j === k ? "step" : undefined}>
            <button type="button" onClick={() => setStep(j)}><b>{String(j + 1).padStart(2, "0")}</b><span>{NAMES[i]}{i > 0 && i < 4 && filled(i) > 0 ? ` · ${filled(i)}` : ""}</span></button>
          </li>
        ))}
      </ol>

      {cur === 0 && (
        <div className="stack" style={{ gap: 12 }}>
          <div className="row" style={{ gap: 10 }}>
            <span>{t("v5.in.looks")}</span><StageBadge stage={s.detected} />
            {s.declared && s.declared !== s.detected && <span className="pill gold">{t("v5.in.youchose", { s: sl(s.declared) })}</span>}
          </div>
          <p className="sub">{t(("v5.in.basis." + (s.basis in { round: 1, revenue: 1, raised: 1, conflict: 1, listing: 1, hint: 1 } ? s.basis : "default")) as DictKey)}</p>
          {s.reasons.length > 0 && <ul className="muted-sm">{s.reasons.slice(0, 3).map((r, i) => <li key={i}>{r}</li>)}</ul>}
          <div className="stagechips" role="group" aria-label={t("v5.in.change")}>
            {STAGES.map((x) => <button key={x} type="button" aria-pressed={s.stage === x} onClick={() => s.setDeclared(x === s.detected ? null : x)}>{sl(x)}</button>)}
          </div>
          <p className="hint">{t("v5.in.stagep")}</p>
          <div className="legend5"><span><LevelBadge level={1} />{t("v5.in.l1")}</span><span><LevelBadge level={2} />{t("v5.in.l2")}</span></div>
        </div>
      )}
      {cur > 0 && cur < 4 && (
        <div className="sgroups">
          {groupsAt(cur).map(({ g, fs }) => (
            <fieldset key={g} className="card" style={{ margin: 0 }}>
              <legend className="sr-only">{t(("v5.g." + g) as DictKey)}</legend>
              <div className="between"><h4>{t(("v5.g." + g) as DictKey)}</h4><span className="hint">{t(("v5.g." + g + ".p") as DictKey)}</span></div>
              <div className="sfields">{fs.map((f) => <Field key={f.key} f={f} s={s} />)}</div>
            </fieldset>
          ))}
        </div>
      )}
      {cur === 4 && (
        <div className="stack">
          <div className="card"><DocUploads pending={s.docs} setPending={s.setDocs} /></div>
          <ProjectionsCard stage={s.stage} pending={s.proj} setPending={s.setProj} />
        </div>
      )}
      <div className="wznav">
        {k > 0 ? <button type="button" className="btn ghost sm" onClick={() => setStep(k - 1)}>← {NAMES[steps[k - 1]]}</button> : <span />}
        {k < steps.length - 1 ? <button type="button" className="btn ghost sm" onClick={() => setStep(k + 1)}>{NAMES[steps[k + 1]]} →</button> : <span className="hint">{t("v5.in.done")}</span>}
      </div>
    </details>
  );
}
