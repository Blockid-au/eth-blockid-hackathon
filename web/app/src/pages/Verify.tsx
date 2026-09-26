import { useEffect, useMemo, useState, type ReactNode } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useI18n } from "../i18n";
import type { DictKey } from "../dict";
import { API_BASE, api, type CompanySummary } from "../api";
import { useAsync, useTitle } from "../lib/hooks";
import { dimKey } from "../lib/svi";
import { CHAINS } from "../wallet";
import "./verify.css";
import { JNum, canonicalJson, canonicalReport, parseLossless, plain, pretty, reportHash, type JVal } from "../lib/canonical";

type ChainKey = "blockid" | "hoodi" | "hsk";
interface OnchainRow { chain: ChainKey; token: string; valuationReportHash: string | null; match: boolean; explorer_url: string; error?: string | null }
interface Formula {
  weights: Record<string, number>;
  grade_bands: { grade: string; min: number; label: string }[];
  stage_pre_revenue_range_aud: Record<string, [number, number, number]>;
  valuation_method: string;
  hash: string;
}
interface VerifyResp { ticker: string; name: string; report_hash: string; formula: Formula; onchain: OnchainRow[] }

const CHAIN_INFO = { blockid: CHAINS.local, hoodi: CHAINS.hoodi, hsk: CHAINS.hsk } as const;
const CHAIN_ORDER: ChainKey[] = ["blockid", "hoodi", "hsk"];
const TAMPER_DIM = "founder_quality";

/** GET the verify payload as raw text: the report's number lexemes must survive (see lib/canonical). */
async function loadVerify(tk: string): Promise<{ meta: VerifyResp; report: JVal }> {
  const res = await fetch(`${API_BASE}/v1/verify/${encodeURIComponent(tk)}`, { headers: { Accept: "application/json" }, credentials: "same-origin" });
  const text = await res.text();
  if (!res.ok) {
    let msg = "HTTP " + res.status;
    try { msg = String(JSON.parse(text).detail ?? msg); } catch { /* not JSON */ }
    throw new Error(msg);
  }
  const tree = parseLossless(text) as { [k: string]: JVal };
  return { meta: plain(tree) as VerifyResp, report: tree.report };
}

async function serverHash(reportText: string, signal: AbortSignal): Promise<string> {
  const res = await fetch(`${API_BASE}/v1/verify/hash`, {
    method: "POST", signal, credentials: "same-origin",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: `{"report":${reportText}}`, // raw text, so floats like 300000.0 reach Python unchanged
  });
  const j = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(String(j?.detail ?? "HTTP " + res.status));
  return String(j.report_hash);
}

/** Python round(x, nd) (half-to-even), good enough for the displayed recompute. */
function pyRound(x: number, nd: number): number {
  const f = Math.pow(10, nd);
  const y = x * f;
  const r = Math.round(y);
  const half = Math.abs(y % 1) === 0.5;
  return (half && r % 2 !== 0 ? r - 1 : r) / f;
}

interface Recomputed {
  rows: { key: string; score: number; weight: number; contribution: number; basis?: string }[];
  index: number; band: string; factor: number; low: number; mid: number; high: number; method: string;
}

function recompute(rep: Record<string, unknown>, f: Formula): Recomputed {
  const svi = (rep.svi ?? {}) as { dimensions?: Record<string, { score?: number; basis?: string }> };
  const dims = svi.dimensions ?? {};
  const num = (x: unknown) => (typeof x === "number" && Number.isFinite(x) ? x : 0);
  const rows = Object.entries(f.weights).map(([key, weight]) => {
    const score = num(dims[key]?.score);
    return { key, score, weight, contribution: weight * score, basis: dims[key]?.basis };
  });
  const index = pyRound(rows.reduce((s, r) => s + r.contribution, 0), 2);
  const band = (f.grade_bands.find((b) => index >= b.min) ?? f.grade_bands[f.grade_bands.length - 1]).label;
  const factor = 0.5 + index / 100;
  const profile = (rep.profile ?? {}) as { stage?: string; metrics?: { revenue_ttm_aud?: number } };
  const market = (rep.market ?? {}) as Record<string, number | null | undefined>;
  const rev = num(profile.metrics?.revenue_ttm_aud);
  const med = num(market.revenue_multiple_median);
  let low: number, mid: number, high: number, method: string;
  if (rev > 0 && med) {
    const lo = num(market.revenue_multiple_low) || med * 0.6;
    const hi = num(market.revenue_multiple_high) || med * 1.5;
    [low, mid, high] = [rev * lo * factor, rev * med * factor, rev * hi * factor];
    method = `revenue ${rev.toLocaleString("en-AU")} × multiple (${lo.toFixed(1)}x / ${med.toFixed(1)}x / ${hi.toFixed(1)}x) × factor ${factor.toFixed(2)}`;
  } else {
    const stage = profile.stage && f.stage_pre_revenue_range_aud[profile.stage] ? profile.stage : "seed";
    const [a, b, c] = f.stage_pre_revenue_range_aud[stage];
    [low, mid, high] = [a * factor, b * factor, c * factor];
    method = `stage benchmark (${stage}) × factor ${factor.toFixed(2)}`;
  }
  return { rows, index, band, factor, low: pyRound(low, -3), mid: pyRound(mid, -3), high: pyRound(high, -3), method };
}

function Short({ h }: { h?: string | null }) {
  if (!h) return <span className="hint">–</span>;
  return <span className="mono vf-hash" title={h}>{h.slice(0, 12)}…{h.slice(-8)}</span>;
}

function Mark({ ok }: { ok: boolean | null }) {
  if (ok === null) return <span className="pill">…</span>;
  return ok ? <span className="pill ok" aria-label="match">✓</span> : <span className="pill bad" aria-label="mismatch">✗</span>;
}

function Ext({ href, children }: { href: string; children: ReactNode }) {
  return <a href={href} target="_blank" rel="noopener noreferrer">{children}</a>;
}

export default function VerifyPage() {
  const { t, fmt, money } = useI18n();
  const { ticker } = useParams();
  const nav = useNavigate();
  useTitle(t("vf.title"));

  const cos = useAsync<CompanySummary[]>(() => api.companies(), []);
  const [data, setData] = useState<{ meta: VerifyResp; report: JVal } | null>(null);
  const [loadErr, setLoadErr] = useState("");
  const [loading, setLoading] = useState(false);
  const [text, setText] = useState("");
  const [original, setOriginal] = useState("");
  const [srv, setSrv] = useState<{ hash: string | null; err: string; busy: boolean }>({ hash: null, err: "", busy: false });

  useEffect(() => {
    if (!ticker) { setData(null); return; }
    let alive = true;
    setLoading(true); setLoadErr("");
    loadVerify(ticker).then((d) => {
      if (!alive) return;
      setData(d);
      const p = pretty(d.report);
      setText(p); setOriginal(p);
    }).catch((e) => { if (alive) { setData(null); setLoadErr(e instanceof Error ? e.message : String(e)); } })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [ticker]);

  // browser-side hash of whatever is in the editor
  const local = useMemo(() => {
    if (!text.trim()) return { hash: null as string | null, err: "", tree: null as JVal | null, canonical: "" };
    try {
      const tree = parseLossless(text);
      return { hash: reportHash(tree), err: "", tree, canonical: canonicalJson(canonicalReport(tree)) };
    } catch (e) {
      return { hash: null, err: e instanceof Error ? e.message : String(e), tree: null, canonical: "" };
    }
  }, [text]);

  // server-side hash of the same text (debounced)
  useEffect(() => {
    if (!local.tree) { setSrv({ hash: null, err: "", busy: false }); return; }
    const ac = new AbortController();
    setSrv((s) => ({ ...s, busy: true }));
    const id = window.setTimeout(() => {
      serverHash(text.trim(), ac.signal)
        .then((h) => setSrv({ hash: h, err: "", busy: false }))
        .catch((e) => { if (!ac.signal.aborted) setSrv({ hash: null, err: e instanceof Error ? e.message : String(e), busy: false }); });
    }, 350);
    return () => { ac.abort(); window.clearTimeout(id); };
  }, [text, local.tree]);

  const formula = data?.meta.formula;
  const rep = local.tree ? (plain(local.tree) as Record<string, unknown>) : null;
  const rc = rep && formula ? recompute(rep, formula) : null;
  const svi = (rep?.svi ?? null) as null | { index?: number; band?: string; valuation_low_aud?: number; valuation_mid_aud?: number; valuation_high_aud?: number };

  const onchain = (data?.meta.onchain ?? []).slice().sort((a, b) => CHAIN_ORDER.indexOf(a.chain) - CHAIN_ORDER.indexOf(b.chain));
  const withHash = onchain.filter((c) => c.valuationReportHash);
  const eq = (a?: string | null, b?: string | null) => !!a && !!b && a.toLowerCase() === b.toLowerCase();
  const browserVsServer = local.hash && srv.hash ? eq(local.hash, srv.hash) : null;
  const verdict: "ok" | "bad" | "wait" | "none" | "info" =
    !local.hash ? "none"
      : !onchain.length ? "info"
      : srv.busy || (!srv.hash && !srv.err) ? "wait"
        : withHash.length > 0 && browserVsServer === true && withHash.every((c) => eq(c.valuationReportHash, local.hash)) ? "ok"
          : "bad";
  const edited = !!original && text !== original;

  const tamper = () => {
    if (!local.tree || typeof local.tree !== "object" || Array.isArray(local.tree) || local.tree instanceof JNum) return;
    const tree = local.tree as { [k: string]: JVal };
    const s = tree.svi as { [k: string]: JVal } | null;
    const d = (s?.dimensions as { [k: string]: JVal } | undefined)?.[TAMPER_DIM] as { [k: string]: JVal } | undefined;
    if (!d) return;
    const cur = d.score instanceof JNum ? Number(d.score.raw) : 0;
    const next = cur >= 99 ? cur - 1 : cur + 1;
    d.score = new JNum(d.score instanceof JNum && /[.eE]/.test(d.score.raw) ? next.toFixed(1) : String(next));
    setText(pretty(tree));
  };

  const dimLabel = (k: string) => { const dk = dimKey(k); return dk ? t(dk) : k.replace(/_/g, " "); };
  const cmp = (a: number | undefined, b: number) => a !== undefined && a !== null && Math.abs(Number(a) - b) < 0.5;

  return (
    <div className="wrap page stack">
      <div className="head">
        <span className="eyebrow">{t("vf.eyebrow")}</span>
        <h2>{t("vf.title")}</h2>
        <p>{t("vf.lead")}</p>
      </div>

      <ol className="vf-steps">
        {(["vf.s1", "vf.s2", "vf.s3", "vf.s4"] as DictKey[]).map((k, i) => <li key={k}><b>{i + 1}</b><span>{t(k)}</span></li>)}
      </ol>

      <div className="card solid">
        <div className="vf-pick">
          <label className="lf">
            <span>{t("vf.pick")}</span>
            <select value={ticker ?? ""} onChange={(e) => nav(e.target.value ? `/verify/${e.target.value}` : "/verify")}>
              <option value="">{t("vf.pick.none")}</option>
              {(cos.data ?? []).map((c) => <option key={c.ticker} value={c.ticker}>{c.ticker} · {c.name}</option>)}
            </select>
          </label>
          {ticker && <Link className="btn ghost sm" to={`/c/${ticker}`}>{t("vf.opencompany")} →</Link>}
        </div>
        {loading && <p className="muted row"><span className="spinner" aria-hidden="true" />{t("common.loading")}</p>}
        {loadErr && <div className="banner bad" role="alert">{loadErr}</div>}
        {!ticker && <p className="note">{t("vf.paste.hint")}</p>}
      </div>

      {local.hash && (
        <div className={"vf-verdict " + verdict} role="status" aria-live="polite">
          <span className="vf-icon" aria-hidden="true">{verdict === "ok" ? "✓" : verdict === "bad" ? "✗" : verdict === "info" ? "i" : "…"}</span>
          <div>
            <b>{verdict === "ok" ? t("vf.ok") : verdict === "bad" ? t("vf.bad") : verdict === "info" ? t("vf.info") : t("vf.wait")}</b>
            <p>
              {verdict === "ok" ? t("vf.ok.p", { n: withHash.length })
                : verdict === "bad" ? (edited ? t("vf.bad.edited") : t("vf.bad.p"))
                  : verdict === "info" ? t("vf.bad.nochain") : t("vf.wait.p")}
            </p>
          </div>
        </div>
      )}

      <section className="stack" aria-labelledby="vf-h">
        <h3 id="vf-h">{t("vf.hashes")}</h3>
        <div className="vf-cols">
          <div className="card">
            <div className="between"><h4>{t("vf.browser")}</h4>{local.hash && <Mark ok={true} />}</div>
            <p className="note">{t("vf.browser.p")}</p>
            {local.err ? <span className="pill bad">{local.err}</span> : <code className="vf-full">{local.hash ?? "–"}</code>}
          </div>
          <div className="card">
            <div className="between"><h4>{t("vf.server")}</h4><Mark ok={srv.busy ? null : browserVsServer} /></div>
            <p className="note">{t("vf.server.p")}</p>
            {srv.err ? <span className="pill bad">{srv.err}</span> : <code className="vf-full">{srv.busy ? "…" : srv.hash ?? "–"}</code>}
          </div>
          <div className="card">
            <div className="between"><h4>{t("vf.onchain")}</h4></div>
            <p className="note">{t("vf.onchain.p")}</p>
            {!onchain.length ? <p className="hint">{ticker ? t("vf.onchain.none") : t("vf.onchain.pick")}</p> : (
              <ul className="vf-chains">
                {onchain.map((c) => (
                  <li key={c.chain}>
                    <div className="between">
                      <b>{CHAIN_INFO[c.chain]?.name ?? c.chain}</b>
                      {c.valuationReportHash ? <Mark ok={eq(c.valuationReportHash, local.hash)} /> : <span className="pill">{c.error ?? "–"}</span>}
                    </div>
                    <Short h={c.valuationReportHash} />
                    <Ext href={c.explorer_url}>{t("vf.explorer")} →</Ext>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      </section>

      <section className="stack" aria-labelledby="vf-r">
        <div className="between">
          <h3 id="vf-r">{t("vf.report")}</h3>
          <div className="row">
            <button className="btn gold sm" type="button" onClick={tamper} disabled={!local.tree}>{t("vf.tamper")}</button>
            <button className="btn ghost sm" type="button" onClick={() => setText(original)} disabled={!edited}>{t("vf.reset")}</button>
          </div>
        </div>
        <p className="note">{t("vf.report.p")}</p>
        <label className="lf">
          <span className="sr-only">{t("vf.report")}</span>
          <textarea className="vf-editor mono" spellCheck={false} value={text} onChange={(e) => setText(e.target.value)} placeholder={t("vf.paste.ph")} rows={16} />
        </label>
        {local.canonical && (
          <details className="card">
            <summary>{t("vf.canonical")} · {fmt(new TextEncoder().encode(local.canonical).length)} bytes</summary>
            <code className="vf-full vf-canon">{local.canonical}</code>
          </details>
        )}
      </section>

      {formula && rc && (
        <section className="stack" aria-labelledby="vf-f">
          <h3 id="vf-f">{t("vf.formula")}</h3>
          <p className="note">{t("vf.formula.p")}</p>
          <div className="cols">
            <div className="card">
              <h4>{t("vf.svi")}</h4>
              <div className="tbl">
                <table>
                  <thead><tr><th>{t("vf.dim")}</th><th>{t("vf.basis")}</th><th className="r">{t("vf.score")}</th><th className="r">{t("vf.weight")}</th><th className="r">{t("vf.contrib")}</th></tr></thead>
                  <tbody>
                    {rc.rows.map((r) => (
                      <tr key={r.key}>
                        <td>{dimLabel(r.key)}</td>
                        <td><span className="pill">{r.basis ?? "–"}</span></td>
                        <td className="r num">{fmt(r.score, 1)}</td>
                        <td className="r num">× {fmt(r.weight, 2)}</td>
                        <td className="r num">= {fmt(r.contribution, 2)}</td>
                      </tr>
                    ))}
                    <tr className="vf-total">
                      <td colSpan={3}>{t("vf.sum")}</td>
                      <td className="r num">{fmt(rc.rows.reduce((s, r) => s + r.weight, 0), 2)}</td>
                      <td className="r num"><b>{fmt(rc.index, 2)}</b></td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </div>
            <div className="card">
              <h4>{t("vf.recomputed")}</h4>
              <div className="tbl">
                <table>
                  <thead><tr><th /><th className="r">{t("vf.inreport")}</th><th className="r">{t("vf.recalc")}</th><th className="r" /></tr></thead>
                  <tbody>
                    <tr><td>{t("vf.index")}</td><td className="r num">{svi?.index != null ? fmt(Number(svi.index), 2) : "–"}</td><td className="r num">{fmt(rc.index, 2)}</td><td className="r"><Mark ok={svi?.index != null && Math.abs(Number(svi.index) - rc.index) < 0.005} /></td></tr>
                    <tr><td>{t("vf.band")}</td><td className="r">{svi?.band ?? "–"}</td><td className="r">{rc.band}</td><td className="r"><Mark ok={svi?.band === rc.band} /></td></tr>
                    <tr><td>{t("vf.low")}</td><td className="r num">{svi?.valuation_low_aud != null ? money(svi.valuation_low_aud) : "–"}</td><td className="r num">{money(rc.low)}</td><td className="r"><Mark ok={cmp(svi?.valuation_low_aud, rc.low)} /></td></tr>
                    <tr><td>{t("vf.mid")}</td><td className="r num">{svi?.valuation_mid_aud != null ? money(svi.valuation_mid_aud) : "–"}</td><td className="r num">{money(rc.mid)}</td><td className="r"><Mark ok={cmp(svi?.valuation_mid_aud, rc.mid)} /></td></tr>
                    <tr><td>{t("vf.high")}</td><td className="r num">{svi?.valuation_high_aud != null ? money(svi.valuation_high_aud) : "–"}</td><td className="r num">{money(rc.high)}</td><td className="r"><Mark ok={cmp(svi?.valuation_high_aud, rc.high)} /></td></tr>
                  </tbody>
                </table>
              </div>
              <p className="note mono">{rc.method}</p>
            </div>
          </div>
          <div className="cols">
            <div className="card">
              <h4>{t("vf.bands")}</h4>
              <div className="vf-bands">
                {formula.grade_bands.map((b) => (
                  <span key={b.grade} className={"vf-band" + (rc.band === b.label ? " on" : "")}><b>{b.grade}</b> ≥ {b.min}<small>{b.label.replace(/^[A-E] - /, "")}</small></span>
                ))}
              </div>
            </div>
            <div className="card">
              <h4>{t("vf.method")}</h4>
              <p className="note">{formula.valuation_method}</p>
              <p className="note mono">{formula.hash}</p>
            </div>
          </div>
        </section>
      )}
      <p><Link to="/companies">← {t("common.back")}</Link></p>
    </div>
  );
}
