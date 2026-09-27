/* Admin "AI health" screen — /admin/ai (docs/PLAN-AI-GATEWAY.md §3). Data: GET /v1/admin/ai/health (shape in
   agents/src/blockid_agents/studio/ai_admin.py), pause / resume per model (platform admins). Auto-refresh 15 s. */
import { useEffect, useState } from "react";
import { request } from "../api";
import { useAuth, errText } from "../auth";
import { useI18n } from "../i18n";
import { useAsync, useNow } from "../lib/hooks";
import { ErrorBox } from "../components/Layout";
import { StatusBar, type Tone } from "../components/StatusBar";
import type { DictKey } from "../dict";
import "./aihealth.css";

export type AiStatus = "healthy" | "demoted" | "skipped" | "open" | "paused";
export interface AiWindow { window: "minute" | "day" | "month" | "budget_day" | string; used: number; limit: number | null; pct: number | null; resets_at: string | null; source?: "ledger" | "headers" | string }
export interface AiModel {
  id: string; provider: string; model: string; label: string; kind: "llm" | "search" | string;
  status: AiStatus; status_reason: string | null; paused: boolean; paused_by: string | null; paused_until: string | null;
  circuit: { state: "closed" | "open" | "half_open" | string; open_until: string | null; consecutive_failures: number } | null;
  windows: AiWindow[]; usage_pct: number | null; calls_24h: number; errors_24h: number; error_rate: number | null;
  schema_valid_rate: number | null; latency_p50_s: number | null; latency_p90_s: number | null;
  tokens_in_today?: number | null; tokens_out_today?: number | null; spend_today_usd: number | null;
  next_reset: string | null; context_tokens?: number | null; profiles?: string[]; last_error: { at: string; error: string } | null;
}
export interface AiProvider { id: string; label: string; concurrency: number | null; spend_today_usd: number | null; budget_today_usd: number | null; models: string[] }
export interface AiFallback { at: string; profile?: string | null; agent?: string | null; failed: string; next: string | null; outcome?: string | null; error?: string | null }
export interface AiHealth {
  generated_at: string; routing?: "dynamic" | "static" | string; thresholds?: { demote_pct: number; skip_pct: number };
  providers: AiProvider[]; models: AiModel[]; profiles?: Record<string, string[]>; recent_fallbacks: AiFallback[];
}

const enc = encodeURIComponent;
export const aiApi = {
  health: () => request<AiHealth>("GET", "/v1/admin/ai/health"),
  pause: (id: string, minutes: number | null, reason = "") => request<{ ok: boolean; model: AiModel }>("POST", `/v1/admin/ai/models/${enc(id)}/pause`, { reason, minutes }),
  resume: (id: string) => request<{ ok: boolean; model: AiModel }>("POST", `/v1/admin/ai/models/${enc(id)}/resume`),
};

const REFRESH = 15000;
const STATUS_TONE: Record<string, string> = { healthy: "ok", demoted: "warn", skipped: "bad", open: "bad", paused: "idle" };
const STATUS_ICON: Record<string, string> = { healthy: "●", demoted: "▲", skipped: "■", open: "✕", paused: "❚❚" };
const usd = (x: number | null | undefined, fmt: (n: number, d?: number) => string) => (x == null ? "–" : "US$" + fmt(x, x < 10 ? 2 : 0));
const secs = (x: number | null | undefined, fmt: (n: number, d?: number) => string) => (x == null ? "–" : fmt(x, x < 10 ? 1 : 0) + " s");

function StatusChip({ s }: { s: AiStatus | string }) {
  const { t } = useI18n();
  const key = ("ai.st." + s) as DictKey;
  const lbl = t(key);
  return <span className={"aipill " + (STATUS_TONE[s] ?? "idle")}><i aria-hidden="true">{STATUS_ICON[s] ?? "●"}</i>{lbl.startsWith("ai.st.") ? s : lbl}</span>;
}

/** One limit window: a meter with the 80 % / 95 % marks (demote / skip thresholds). */
function UsageBar({ w, demote, skip }: { w: AiWindow; demote: number; skip: number }) {
  const { t, fmt, date } = useI18n();
  const pct = w.pct == null ? null : Math.max(0, Math.min(100, w.pct));
  const tone = pct == null ? "idle" : pct >= skip ? "bad" : pct >= demote ? "warn" : "ok";
  const name = t(("ai.w." + w.window) as DictKey);
  const label = name.startsWith("ai.w.") ? w.window : name;
  const money = w.window === "budget_day";
  const used = money ? usd(w.used, fmt) : fmt(w.used);
  const lim = w.limit == null ? "–" : money ? usd(w.limit, fmt) : fmt(w.limit);
  const tip = `${label}: ${t("ai.w.used", { u: used, l: lim })}${pct != null ? ` (${fmt(pct, 0)} %)` : ""}${w.resets_at ? " · " + t("ai.w.resets", { t: date(w.resets_at, true) }) : ""}`;
  return (
    <div className="aiw" title={tip}>
      <div className="aiw-top">
        <span>{label}{w.source === "headers" ? <span className="muted"> · {t("ai.w.headers")}</span> : null}</span>
        <span className="num">{w.limit == null ? t("ai.w.none") : <>{t("ai.w.used", { u: used, l: lim })} <b className={"aiw-pct " + tone}>{pct == null ? "" : fmt(pct, 0) + " %"}</b></>}</span>
      </div>
      <div className="aiw-bar" role="meter" aria-label={tip} aria-valuemin={0} aria-valuemax={100} aria-valuenow={pct ?? 0}>
        <span className={"aiw-fill " + tone} style={{ width: `${pct ?? 0}%` }} />
        <i className="aiw-mark" style={{ left: `${demote}%` }} aria-hidden="true" />
        <i className="aiw-mark hard" style={{ left: `${skip}%` }} aria-hidden="true" />
      </div>
    </div>
  );
}

function PauseControls({ m, can, onDone }: { m: AiModel; can: boolean; onDone: (msg: string) => void }) {
  const { t } = useI18n();
  const [mins, setMins] = useState<number>(60);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  if (!can) return null;
  const go = async (fn: () => Promise<unknown>, msg: string) => {
    setBusy(true); setErr("");
    try { await fn(); onDone(msg); } catch (e) { setErr(errText(e, t)); } finally { setBusy(false); }
  };
  return (
    <div className="aictl">
      {m.paused ? (
        <button type="button" className="btn sm" disabled={busy} onClick={() => go(() => aiApi.resume(m.id), t("ai.resume.done", { m: m.label }))}>{t("ai.resume")}</button>
      ) : (
        <>
          <label className="sr-only" htmlFor={"aip-" + m.id}>{t("ai.pause.for")}</label>
          <select id={"aip-" + m.id} value={mins} onChange={(e) => setMins(Number(e.target.value))} disabled={busy}>
            {[30, 60, 1440, 0].map((x) => <option key={x} value={x}>{t(("ai.pause." + x) as DictKey)}</option>)}
          </select>
          <button type="button" className="btn ghost sm" disabled={busy} onClick={() => go(() => aiApi.pause(m.id, mins || null), t("ai.pause.done", { m: m.label }))}>{t("ai.pause")}</button>
        </>
      )}
      {err && <span className="err" role="alert">{err}</span>}
    </div>
  );
}

function ModelCard({ m, demote, skip, can, onDone }: { m: AiModel; demote: number; skip: number; can: boolean; onDone: (msg: string) => void }) {
  const { t, fmt, date, ago } = useI18n();
  const er = m.error_rate == null ? null : m.error_rate * 100;
  return (
    <article className={"aicard t-" + (STATUS_TONE[m.status] ?? "idle")} aria-label={m.label}>
      <header>
        <div>
          <h5>{m.label}</h5>
          <span className="muted aisub">{t(("ai.kind." + (m.kind === "search" ? "search" : "llm")) as DictKey)} · <span className="mono">{m.id}</span></span>
        </div>
        <StatusChip s={m.status} />
      </header>
      {m.status_reason && <p className="aireason">{m.status_reason}</p>}
      {m.paused && <p className="aireason">{t("ai.m.pausedby", { w: m.paused_by ?? "admin" })} · {m.paused_until ? t("ai.m.until", { t: date(m.paused_until, true) }) : t("ai.m.untilres")}</p>}
      {m.circuit?.state === "open" && m.circuit.open_until && <p className="aireason bad">{t("ai.m.circuit", { t: date(m.circuit.open_until, true), n: m.circuit.consecutive_failures })}</p>}
      <div className="aiws">
        {m.windows.length ? m.windows.map((w) => <UsageBar key={w.window} w={w} demote={demote} skip={skip} />) : <p className="note">{t("ai.w.none")}</p>}
      </div>
      <dl className="aistats">
        <div><dt>{t("ai.m.err")}</dt><dd className={"num" + (er != null && er >= 10 ? " bad" : er != null && er >= 3 ? " warn" : "")}>{er == null ? "–" : fmt(er, er < 10 ? 1 : 0) + " %"} <small className="muted">{fmt(m.errors_24h)}/{fmt(m.calls_24h)}</small></dd></div>
        <div><dt>{t("ai.m.lat")}</dt><dd className="num">{secs(m.latency_p50_s, fmt)} / {secs(m.latency_p90_s, fmt)}</dd></div>
        <div><dt>{t("ai.m.spend")}</dt><dd className="num">{usd(m.spend_today_usd, fmt)}</dd></div>
        <div><dt>{t("ai.m.reset")}</dt><dd className="num">{m.next_reset ? date(m.next_reset, true) : "–"}</dd></div>
        {m.schema_valid_rate != null && <div><dt>{t("ai.m.valid")}</dt><dd className="num">{fmt(m.schema_valid_rate * 100, 0)} %</dd></div>}
      </dl>
      {m.last_error && <p className="ailast"><span className="muted">{t("ai.m.lasterr", { t: ago(m.last_error.at) })}</span> <span title={m.last_error.error}>{m.last_error.error.length > 140 ? m.last_error.error.slice(0, 140) + "…" : m.last_error.error}</span></p>}
      <PauseControls m={m} can={can} onDone={onDone} />
    </article>
  );
}

function ModelTable({ models, can, onDone }: { models: AiModel[]; can: boolean; onDone: (msg: string) => void }) {
  const { t, fmt } = useI18n();
  return (
    <div className="tbl">
      <table className="aitable">
        <thead><tr><th>{t("ai.col.model")}</th><th>{t("ai.col.status")}</th><th className="r">{t("ai.col.usage")}</th><th className="r">{t("ai.m.err")}</th><th className="r">{t("ai.m.lat")}</th><th className="r">{t("ai.m.spend")}</th><th /></tr></thead>
        <tbody>
          {models.map((m) => (
            <tr key={m.id}>
              <td><b>{m.label}</b><br /><span className="mono muted aisub">{m.id}</span></td>
              <td><StatusChip s={m.status} /></td>
              <td className="r num">{m.usage_pct == null ? "–" : fmt(m.usage_pct, 0) + " %"}</td>
              <td className="r num">{m.error_rate == null ? "–" : fmt(m.error_rate * 100, 1) + " %"}</td>
              <td className="r num">{secs(m.latency_p50_s, fmt)} / {secs(m.latency_p90_s, fmt)}</td>
              <td className="r num">{usd(m.spend_today_usd, fmt)}</td>
              <td className="r"><PauseControls m={m} can={can} onDone={onDone} /></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function AiHealthTab() {
  const { t, fmt, date, ago } = useI18n();
  const { me } = useAuth();
  const can = me?.role === "admin" && !me?.must_change;
  const h = useAsync(() => aiApi.health(), [], REFRESH);
  const now = useNow(1000);
  const [got, setGot] = useState(Date.now());
  const [view, setView] = useState<"cards" | "table">("cards");
  const [toast, setToast] = useState("");
  useEffect(() => { if (h.data) setGot(Date.now()); }, [h.data]);
  useEffect(() => { if (!toast) return; const x = setTimeout(() => setToast(""), 4000); return () => clearTimeout(x); }, [toast]);
  const d = h.data;
  if (!d) return h.error ? <ErrorBox error={h.error} retry={h.reload} /> : <p className="note">{t("common.loading")}</p>;
  const demote = d.thresholds?.demote_pct ?? 80, skip = d.thresholds?.skip_pct ?? 95;
  const n = (s: AiStatus[]) => d.models.filter((m) => s.includes(m.status)).length;
  const healthy = n(["healthy"]), demoted = n(["demoted"]), down = n(["skipped", "open", "paused"]);
  const llm = d.models.filter((m) => m.kind !== "search");
  const noLlm = llm.length > 0 && llm.every((m) => m.status !== "healthy" && m.status !== "demoted");
  const tone: Tone = noLlm ? "bad" : demoted + down ? "wait" : "ok";
  const spend = d.providers.reduce((a, p) => a + (p.spend_today_usd ?? 0), 0);
  const budget = d.providers.reduce((a, p) => a + (p.budget_today_usd ?? 0), 0);
  const label = (id: string | null) => (id ? d.models.find((m) => m.id === id)?.label ?? id : t("ai.fb.none"));
  const onDone = (msg: string) => { setToast(msg); void h.reload(); };
  return (
    <div className="aihealth">
      <StatusBar tone={tone} status={noLlm ? t("ai.sb.bad") : demoted + down ? t("ai.sb.warn", { n: demoted + down }) : t("ai.sb.ok")}
        meta={<span className="sb-meta">{t("ai.sb.meta", { s: Math.max(0, Math.round((now - got) / 1000)) })} · {t(d.routing === "static" ? "ai.routing.static" : "ai.routing.dynamic")}</span>} />
      {h.error ? <p className="banner warn" role="alert">{t("ai.err.down")}</p> : null}
      {toast && <p className="banner ok" role="status">{toast}</p>}
      {!can && <p className="note">{t("ai.adminonly")}</p>}
      <div className="aikpis">
        <div className="aikpi"><small>{t("ai.k.healthy")}</small><b className="num">{fmt(healthy)}</b><span className="muted">{t("ai.k.of", { n: d.models.length })}</span></div>
        <div className="aikpi"><small>{t("ai.k.demoted")}</small><b className={"num" + (demoted ? " warn" : "")}>{fmt(demoted)}</b><span className="muted">≥ {demote} %</span></div>
        <div className="aikpi"><small>{t("ai.k.down")}</small><b className={"num" + (down ? " bad" : "")}>{fmt(down)}</b><span className="muted">≥ {skip} %</span></div>
        <div className="aikpi"><small>{t("ai.k.spend")}</small><b className="num">{usd(spend, fmt)}</b><span className="muted">{budget ? t("ai.k.budget", { b: usd(budget, fmt) }) : t("ai.k.nobudget")}</span></div>
      </div>

      <div className="pane">
        <h4>{t("ai.prov.h")}</h4>
        <div className="aiprov">
          {d.providers.map((p) => {
            const pct = p.budget_today_usd ? Math.min(100, ((p.spend_today_usd ?? 0) / p.budget_today_usd) * 100) : null;
            const worst = d.models.filter((m) => m.provider === p.id).map((m) => m.status);
            const st: AiStatus = worst.includes("open") ? "open" : worst.includes("skipped") ? "skipped" : worst.includes("demoted") ? "demoted" : worst.length && worst.every((x) => x === "paused") ? "paused" : "healthy";
            return (
              <div key={p.id} className="aiprovc">
                <div className="aiprov-top"><b>{p.label}</b><StatusChip s={st} /></div>
                <span className="muted aisub">{t("ai.prov.models", { n: p.models.length })}{p.concurrency ? " · " + t("ai.prov.conc", { n: p.concurrency }) : ""}</span>
                <span className="num">{t("ai.m.spend")}: {usd(p.spend_today_usd, fmt)}{p.budget_today_usd ? " / " + usd(p.budget_today_usd, fmt) : ""}</span>
                {pct != null && <UsageBar w={{ window: "budget_day", used: p.spend_today_usd ?? 0, limit: p.budget_today_usd, pct, resets_at: null }} demote={demote} skip={skip} />}
              </div>
            );
          })}
        </div>
      </div>

      <div className="pane">
        <div className="phead">
          <h4>{t("ai.models.h")}</h4>
          <button type="button" className="linkbtn" onClick={() => setView(view === "cards" ? "table" : "cards")}>{view === "cards" ? t("ai.table") : t("ai.cards")}</button>
        </div>
        <p className="note">{t("ai.w.marks")}</p>
        {!d.models.length ? <p className="note">{t("ai.models.empty")}</p> : view === "table" ? <ModelTable models={d.models} can={can} onDone={onDone} /> : (
          <div className="aigrid">{d.models.map((m) => <ModelCard key={m.id} m={m} demote={demote} skip={skip} can={can} onDone={onDone} />)}</div>
        )}
      </div>

      <div className="split">
        <div className="pane">
          <h4>{t("ai.fb.h")}</h4>
          {!d.recent_fallbacks.length ? <p className="note">{t("ai.fb.empty")}</p> : (
            <div className="feed">
              {d.recent_fallbacks.slice(0, 30).map((f, i) => {
                const out = f.outcome ? t(("ai.out." + f.outcome) as DictKey) : "";
                return (
                  <div key={i}>
                    <i style={{ background: `var(${f.outcome === "cancelled" ? "--c3" : f.next ? "--warn" : "--down"})` }} />
                    <span>{t("ai.fb.line", { f: label(f.failed), n: label(f.next) })}{out && !out.startsWith("ai.out.") ? <span className="muted"> · {out}</span> : null}
                      {f.profile ? <span className="muted"> · {t(("ai.prof." + f.profile) as DictKey).startsWith("ai.prof.") ? f.profile : t(("ai.prof." + f.profile) as DictKey)}</span> : null}
                      {f.agent ? <span className="muted mono"> · {f.agent}</span> : null}
                      {f.error ? <span className="muted" title={f.error}> · {f.error.length > 80 ? f.error.slice(0, 80) + "…" : f.error}</span> : null}</span>
                    <em title={date(f.at, true)}>{ago(f.at)}</em>
                  </div>
                );
              })}
            </div>
          )}
        </div>
        {d.profiles && (
          <div className="pane">
            <h4>{t("ai.prof.h")}</h4>
            <div className="aiprof">
              {Object.entries(d.profiles).map(([k, ids]) => {
                const nm = t(("ai.prof." + k) as DictKey);
                return (
                  <div key={k}>
                    <b>{nm.startsWith("ai.prof.") ? k : nm}</b>
                    <ol>{ids.map((id) => { const m = d.models.find((x) => x.id === id); return <li key={id}>{label(id)} {m && m.status !== "healthy" ? <StatusChip s={m.status} /> : null}</li>; })}</ol>
                  </div>
                );
              })}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
