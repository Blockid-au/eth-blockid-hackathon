import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import type { DictKey } from "../dict";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useI18n } from "../i18n";
import { errText, useAuth } from "../auth";
import { api, ApiError, type Evidence, type Svi, type TickerCandidate, type Valuation as Val } from "../api";
import { Crumbs, FlowRail, Pager, SideLayout, StepHead, type PagerLink } from "../components/Shell";
import { phaseOf, valAuto, valGate, valPath, valReach, VAL_STEP } from "../lib/flow";
import { demoApproveLink } from "../components/DemoGuide";
import { StatusBar, type StatusNext, type Tone } from "../components/StatusBar";
import { Contrib, Donut, HBars, Legend, Radar, RangeChart } from "../components/charts";
import { ValuationMethods, type Triangulation, type ValuationEvidence } from "../components/ValuationMethods";
import { ErrorBox, Loading } from "../components/Layout";
import { TeamCard } from "../components/TeamCard";
import { useAsync, useTitle } from "../lib/hooks";
import { bandGrade, dimRows, OVERRIDABLE, stepLabel } from "../lib/svi";
import { allocate, colorAt, foldParts } from "../lib/math";
import { SAMPLE, SAMPLE_EVIDENCE } from "../lib/sample";
import { SR_FIELDS, type SrField } from "../lib/selfReported";
import { addrError, isAddressValid } from "../wallet";

const ACTIVE = ["queued", "running", "waiting_approval"];

/* ================= founder-provided figures ================= */
function SelfReportedTable({ sr }: { sr: NonNullable<Val["self_reported"]> }) {
  const { t, fmt, aud, pct } = useI18n();
  const dec = (n: number) => (Number.isInteger(n) ? 0 : 1);
  const show = (f: SrField, n: number) => (f.kind === "aud" ? aud(n, 0) : f.kind === "pct" ? pct(n, dec(n)) : fmt(n, dec(n)));
  const rows = SR_FIELDS.filter((f) => typeof sr[f.key] === "number");
  if (!rows.length) return null;
  return (
    <div className="card">
      <div className="between"><h4>{t("sr.table")}</h4><span className="pill sr" title={t("sr.chip.tip")}>{t("sr.chip")}</span></div>
      <p className="sub">{t("sr.table.p")}</p>
      <div className="tbl"><table>
        <tbody>
          {rows.map((f) => <tr key={f.key}><td>{t(f.label)}</td><td className="r mono">{show(f, sr[f.key] as number)}</td></tr>)}
        </tbody>
      </table></div>
    </div>
  );
}

/* ================= step 2: agents ================= */
function AgentLog({ v }: { v: Val }) {
  const { t, fmt, date } = useI18n();
  const t0 = v.created_at ? +new Date(v.created_at) : NaN;
  const when = (at?: string | null) => {
    if (!at) return "–";
    if (/^\d+:\d\d$/.test(at)) return at;
    const x = +new Date(at);
    if (!Number.isFinite(x)) return at;
    if (Number.isFinite(t0) && x >= t0) { const s = Math.round((x - t0) / 1000); return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`; }
    return date(x, true);
  };
  const c = v.counters ?? {};
  return (
    <div className="panel" role="region" aria-label={t("s2.h")}>
      <div className="cols">
        <div className="log" aria-live="polite">
          {v.steps.length === 0 && <div><span className="dot run" /><span>{t("v.queued")}</span><em>…</em></div>}
          {v.steps.map((s) => {
            const st = /done|ok|complete|success/i.test(s.status) ? "ok" : /run|active|progress/i.test(s.status) ? "run" : /fail|error/i.test(s.status) ? "fail" : "";
            return (
              <div key={s.key}>
                <span className={"dot " + st} aria-label={s.status} />
                <span>{stepLabel(s.key, t)}{s.detail ? <small>{s.detail}</small> : null}</span>
                <em>{st === "ok" || st === "fail" ? when(s.at) : st === "run" ? "…" : "–"}</em>
              </div>
            );
          })}
        </div>
        <div className="card">
          <h4>{t("s2.found")}</h4>
          <div className="counter">
            <div><b>{fmt(c.pages ?? 0)}</b><small>{t("s2.pages")}</small></div>
            <div><b>{fmt(c.competitors ?? v.competitors?.length ?? 0)}</b><small>{t("s2.comp")}</small></div>
            <div><b>{fmt(c.sources ?? 0)}</b><small>{t("s2.src")}</small></div>
          </div>
          <p className="note">{t("s2.note")}</p>
          {ACTIVE.includes(v.status) && v.status !== "waiting_approval" && <p className="note">{t("v.running.note")} · {t("v.poll")}</p>}
        </div>
      </div>
    </div>
  );
}

/* ================= step 3: report ================= */
function AdminReview({ v, svi, onDone }: { v: Val; svi: Svi; onDone: (x: Val) => void }) {
  const { t, fmt } = useI18n();
  const [scores, setScores] = useState<Record<string, number>>(() => Object.fromEntries(Object.entries(svi.dimensions).map(([k, d]) => [k, Number(d.score)])));
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  const rows = dimRows(svi, t, scores);
  const idx = rows.reduce((a, r) => a + r.score * r.weight, 0);
  const decide = async (approved: boolean) => {
    setBusy(true); setMsg("");
    try {
      const changed = Object.fromEntries(Object.entries(scores).filter(([k, s]) => OVERRIDABLE.has(k) && s !== Number(svi.dimensions[k]?.score)));
      const r = await api.decide(v.id, approved, approved && Object.keys(changed).length ? changed : undefined);
      setMsg(t("v.adm.done"));
      onDone(r && typeof r === "object" && "status" in r ? r : { ...v, status: approved ? "approved" : "rejected" });
    } catch (e) {
      setMsg(errText(e, t));
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="approve">
      <div className="between"><h4 style={{ margin: 0, font: "600 1rem/1.3 var(--display)" }}>{t("v.adm.h")}</h4><span className="gatepill">{t("gate.admin")}</span></div>
      <p className="sub muted">{t("v.adm.p")}</p>
      <div className="dimedit">
        {rows.map((r) => (
          <label key={r.key}>
            <span>{r.label} <span className="hint">×{fmt(r.weight, 2)}{r.basis && r.basis !== "self_reported" ? " · " + r.basis : ""}</span>{r.basis === "self_reported" && <> <span className="pill sr" title={t("sr.chip.tip")}>{t("sr.chip")}</span></>}</span>
            <input type="number" min={0} max={100} step={1} value={scores[r.key]} disabled={!OVERRIDABLE.has(r.key)} title={OVERRIDABLE.has(r.key) ? undefined : r.basis || "computed"} onChange={(e) => setScores((s) => ({ ...s, [r.key]: Math.max(0, Math.min(100, Number(e.target.value) || 0)) }))} aria-label={`${r.label} score`} />
          </label>
        ))}
      </div>
      <div className="totalrow ok"><span>{t("v.adm.preview")}</span><span>{fmt(idx, 1)} · {bandGrade({ band: "", index: idx })}</span></div>
      <div className="field">
        <button className="btn gold" type="button" disabled={busy} onClick={() => decide(true)}>{t("s3.approve")}</button>
        <button className="btn ghost" type="button" disabled={busy} onClick={() => decide(false)}>{t("v.adm.reject")}</button>
      </div>
      <p className="toast" role="status">{msg}</p>
    </div>
  );
}

function Report({ v, evidence, isAdmin, onDecided, onTeamDone }: { v: Val; evidence: Evidence[] | undefined; isAdmin: boolean; onDecided: (x: Val) => void; onTeamDone?: () => void }) {
  const { t, fmt, money, date } = useI18n();
  const svi = v.svi!;
  const rows = dimRows(svi, t);
  const g = bandGrade(svi);
  const comps = (v.competitors ?? []).slice(0, 8);
  const nSrc = (s: unknown) => (Array.isArray(s) ? s.length : typeof s === "number" ? s : 0);
  return (
    <div className="panel" role="region" aria-label={t("s3.h")}>
      {isAdmin && v.status === "waiting_approval" && <AdminReview v={v} svi={svi} onDone={onDecided} />}
      <div className="row" style={{ gap: 14 }}>
        <span className="gradebadge" aria-label={`${t("ad.c.grade")} ${g}`}>{g}</span>
        <span className="bigno">{money(svi.valuation_mid_aud)}</span>
        <span className="muted">{t("v.score", { s: fmt(svi.index, 1) })} · {money(svi.valuation_low_aud)} – {money(svi.valuation_high_aud)}</span>
      </div>
      <TeamCard valuationId={v.id} teamId={v.team_id} summary={v.team} weight={svi.weights?.founder_quality} sample={v.id === "sample"}
        applied={svi.dimensions?.founder_quality?.basis === "team_report"} onDone={onTeamDone} />
      <div className="cols">
        <div className="card"><h4>{t("s3.radar")}</h4><Radar dims={rows} /></div>
        <div className="card">
          <h4>{t("s3.build")}</h4>
          <p className="sub">{t("s3.buildp")}</p>
          <Contrib dims={rows} totalLabel={t("v.total", { g })} />
        </div>
      </div>
      {v.self_reported && <SelfReportedTable sr={v.self_reported} />}
      {(svi as { triangulation?: Triangulation | null }).triangulation && (
        <ValuationMethods triangulation={(svi as { triangulation?: Triangulation | null }).triangulation}
          evidence={(v as { valuation_evidence?: ValuationEvidence | null }).valuation_evidence} />
      )}
      <div className="cols">
        <div className="card">
          <h4>{t("s3.range")}</h4>
          <RangeChart low={svi.valuation_low_aud} mid={svi.valuation_mid_aud} high={svi.valuation_high_aud} />
          {svi.method && <p className="sub">{t("v.method", { m: svi.method })}</p>}
        </div>
        <div className="card">
          <h4>{t("s3.comp")}</h4>
          {comps.length ? (
            <HBars
              ariaLabel="Competitor funding bar chart"
              axis
              ndLabel={t("v.nd")}
              rows={comps.map((c) => ({
                name: c.name,
                value: c.raised_aud == null ? null : c.raised_aud / 1e6,
                color: "--c3",
                label: c.raised_aud == null ? "" : fmt(c.raised_aud / 1e6, 1),
                tip: `${c.name} · ${c.raised_aud == null ? t("v.nd") : money(c.raised_aud)}${nSrc(c.sources) ? " · " + t("v.sources", { n: nSrc(c.sources) }) : ""}${c.note ? " · " + c.note : ""}`,
              }))}
            />
          ) : <p className="note">{t("common.none")}</p>}
          {comps.length > 0 && (
            <ul className="complist">
              {comps.map((c) => (
                <li key={c.name}>
                  {c.url ? <a href={c.url} target="_blank" rel="noopener noreferrer nofollow">{c.name}</a> : <span>{c.name}</span>}
                  <span className="muted-sm">{c.raised_aud == null ? t("v.nd") : money(c.raised_aud)}{c.note ? " · " + c.note : ""}</span>
                  {c.basis === "model_suggested_verified" && <span className="pill ok" title={t("v.verified.tip")}>✓ {t("v.verified")}</span>}
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
      <div className="cols">
        {svi.narrative && <div className="card"><h4>{t("v.narr")}</h4><p className="narr">{svi.narrative}</p></div>}
        <div className="card">
          <h4>{t("v.evidence")}</h4>
          <p className="sub">{t("v.evidence.p")}</p>
          {!evidence ? <p className="note">{t("common.loading")}</p> : evidence.length === 0 ? <p className="note">{t("v.evidence.empty")}</p> : (
            <div className="evidence">
              {evidence.map((e, i) => {
                let dom = e.url;
                try { dom = new URL(e.url).hostname; } catch { /* keep */ }
                return (
                  <div key={i}>
                    <a href={e.url} target="_blank" rel="noopener noreferrer nofollow">{e.title || dom}</a>
                    <span className="dom">{e.kind ? <span className="pill" style={{ marginRight: 6 }}>{e.kind}</span> : null}{dom}{e.retrieved_at ? " · " + t("v.retrieved", { d: date(e.retrieved_at, true) }) : ""}</span>
                    {e.snippet && <p>{e.snippet}</p>}
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

/* ================= notes: research warnings, collapsed at the end ================= */
function Notes({ items }: { items: string[] }) {
  const { t } = useI18n();
  if (!items.length) return null;
  return (
    <details className="notes">
      <summary>{t("v.notes", { n: items.length })}</summary>
      <ul>{items.map((w, i) => <li key={i}>{w}</li>)}</ul>
      <p>{t("v.notes.p")}</p>
    </details>
  );
}

/** The job stopped while reading the website (bad link, site down or blocking us). */
export function siteReadFailed(v: Val): boolean {
  if (v.status !== "failed") return false;
  const step = v.steps.find((s) => s.key === "read_site");
  return (!!step && /fail|error/i.test(step.status)) || /SiteError|could not read|not a website url|does not resolve|not a public/i.test(v.error ?? "");
}

function SiteFailed({ v }: { v: Val }) {
  const { t } = useI18n();
  return (
    <div className="pane stateCard soft" role="alert">
      <h2>{t("v.site.h")}</h2>
      <p className="mono muted-sm" style={{ overflowWrap: "anywhere" }}>{v.url.replace(/^https?:\/\//, "")}</p>
      <p>{t("v.site.p")}</p>
      <div className="row"><Link className="btn" to={`/start?url=${encodeURIComponent(v.url.replace(/^https?:\/\//, "").replace(/\/$/, ""))}`}>{t("v.site.btn")}</Link></div>
    </div>
  );
}

/* ================= step 4: ticker ================= */
function TickerStep({ name, setName, ticker, setTicker }: { name: string; setName: (s: string) => void; ticker: string; setTicker: (s: string) => void }) {
  const { t } = useI18n();
  const [cands, setCands] = useState<TickerCandidate[] | null>(null);
  const [err, setErr] = useState("");
  const [custom, setCustom] = useState("");
  // result of the server check for the code being tried (a candidate, a typed code, or the saved draft)
  const [chk, setChk] = useState<{ tk: string; state: "checking" | "ok" | "bad"; reason?: string | null; alts?: string[] } | null>(null);
  const seq = useRef(0);

  /** Accept a code only after the server says it is valid, not reserved and not used by another company. */
  const tryCode = useCallback(async (tk: string) => {
    const my = ++seq.current;
    setChk({ tk, state: "checking" });
    try {
      const r = await api.checkTicker(tk, name.trim());
      if (my !== seq.current) return;
      setChk({ tk, state: r.ok ? "ok" : "bad", reason: r.reason, alts: r.suggestions });
      setTicker(r.ok ? tk : "");
    } catch (e) {
      if (my !== seq.current) return;
      setChk(null);
      setErr(errText(e, t));
    }
  }, [name, setTicker, t]);

  // a code saved in this browser earlier may have been taken since: check it again
  useEffect(() => { if (ticker && /^[A-Z]{3}$/.test(ticker)) void tryCode(ticker); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!name.trim()) return;
    let live = true;
    const id = setTimeout(async () => {
      try {
        const r = await api.suggestTickers(name.trim());
        if (!live) return;
        setCands(r.candidates);
        setErr("");
        if (!custom && (!ticker || !r.candidates.some((c) => c.ticker === ticker && c.available))) {
          const first = r.candidates.find((c) => c.available);
          if (first) void tryCode(first.ticker);
        }
      } catch (e) {
        if (live) setErr(errText(e, t));
      }
    }, 400);
    return () => { live = false; clearTimeout(id); };
  }, [name]); // eslint-disable-line react-hooks/exhaustive-deps

  const onCustom = (raw: string) => {
    const x = raw.toUpperCase().replace(/[^A-Z]/g, "").slice(0, 3);
    setCustom(x);
    if (x.length === 3) void tryCode(x);
    else {
      seq.current++;
      setChk(x ? { tk: x, state: "bad", reason: "format" } : null);
      if (x) setTicker("");
      else { const first = cands?.find((c) => c.available); if (first) void tryCode(first.ticker); }
    }
  };
  const bad = chk?.state === "bad";
  const msg = !chk ? "" : chk.state === "checking" ? t("tk.checking", { t: chk.tk }) : chk.state === "ok" ? t("tk.ok", { t: chk.tk })
    : chk.reason === "taken" ? t("tk.taken", { t: chk.tk }) : chk.reason === "reserved" ? t("tk.reserved", { t: chk.tk }) : t("tk.format");
  return (
    <div className="cols">
      <div className="card">
        <label className="lf"><span>{t("v.tk.cname")}</span><input value={name} onChange={(e) => setName(e.target.value)} maxLength={80} aria-invalid={!name.trim()} /></label>
        {!name.trim() && <span className="hint bad">{t("tk.name")}</span>}
        <div className="tickers" role="group" aria-label={t("s4.h")}>
          {cands?.map((c) => (
            <button key={c.ticker} type="button" className="tk" aria-pressed={c.ticker === ticker} disabled={!c.available} onClick={() => { setCustom(""); void tryCode(c.ticker); }} title={c.available ? c.rule : t("v.tk.taken")}>{c.ticker}</button>
          ))}
          {!cands && !err && <span className="note">{t("common.loading")}</span>}
        </div>
        <label className="lf"><span>{t("v.tk.custom")}</span>
          <input className={"tkinput" + (bad && custom ? " bad" : "")} value={custom} maxLength={3} aria-invalid={bad && !!custom} aria-describedby="tk-msg" onChange={(e) => onCustom(e.target.value)} />
        </label>
        {msg && (
          <p id="tk-msg" className={"hint" + (bad ? " bad" : chk?.state === "ok" ? " ok" : "")} role={bad ? "alert" : "status"}>
            {chk?.state === "ok" ? "✓ " : bad ? "✗ " : ""}{msg}
            {bad && (chk?.alts?.length ?? 0) > 0 && (
              <> {t("tk.try")}{" "}{chk!.alts!.map((a) => <button key={a} type="button" className="linkbtn mono" onClick={() => { setCustom(""); void tryCode(a); }}>{a}</button>).reduce<ReactNode[]>((acc, el, i) => (i ? [...acc, " · ", el] : [el]), [])}</>
            )}
          </p>
        )}
        {err && <p className="err" role="alert">{err}</p>}
        <p className="sub"><span>{t("s4.name")}</span>: <b>{name || "…"} ORD ({ticker || "???"})</b></p>
      </div>
      <div className="card">
        <h4>{t("s4.rules")}</h4>
        {cands && cands.length ? (
          <ul className="rules">
            {cands.map((c) => (
              <li key={c.ticker}>
                <span className={c.available ? "ok" : "no"}>{c.available ? "✓" : "✗"}</span>
                <span className={c.available ? "" : "no"}>{c.rule || (c.available ? "" : t("v.tk.taken"))}</span>
                <span className={"mono" + (c.available ? "" : " no")}>{c.ticker}</span>
              </li>
            ))}
          </ul>
        ) : <p className="note">{t("v.tk.none")}</p>}
      </div>
    </div>
  );
}

/* ================= step 5: shareholders ================= */
interface Row { id: number; name: string; wallet: string; pct: string }
let rowSeq = 1;

function HoldersStep({ v, name, ticker, defaultWallet }: { v: Val; name: string; ticker: string; defaultWallet?: string | null }) {
  const { t, fmt, money } = useI18n();
  const nav = useNavigate();
  const mid = Math.round(v.svi!.valuation_mid_aud);
  const [total, setTotal] = useState<string>(String(mid));
  const [rows, setRows] = useState<Row[]>(() => [{ id: rowSeq++, name: "", wallet: defaultWallet ?? "", pct: "100" }]);
  const [busy, setBusy] = useState(false);
  const [stage, setStage] = useState<"" | "creating" | "submitting" | "opening">("");
  const [err, setErr] = useState("");
  const [touched, setTouched] = useState(false);
  // re-check the share code: another company may have taken it since step 4
  const [tkBad, setTkBad] = useState<string | null>(null);
  useEffect(() => {
    if (!/^[A-Z]{3}$/.test(ticker)) { setTkBad(null); return; }
    let live = true;
    api.checkTicker(ticker, name).then((r) => { if (live) setTkBad(r.ok ? null : ticker); }).catch(() => { /* the server checks again on create */ });
    return () => { live = false; };
  }, [ticker, name]);

  const upd = (id: number, k: keyof Row, val: string) => setRows((rs) => rs.map((r) => (r.id === id ? { ...r, [k]: val } : r)));
  const pcts = rows.map((r) => Number(r.pct) || 0);
  const sumP = pcts.reduce((a, b) => a + b, 0);
  const ok = Math.abs(sumP - 100) < 1e-6;
  const T = Math.max(0, Math.floor(Number(total) || 0));
  // the same rules as the server (tools/captable.py + routes create_company), caught on the row that breaks them
  const totalErr = !/^\d+$/.test(total.trim()) || T < 1 ? t("fx.sh.supply") : T < rows.length ? t("fx.sh.few", { n: rows.length }) : "";
  const shares = ok ? allocate(T, pcts) : pcts.map((p) => Math.floor((T * p) / 100));
  const seen = new Map<string, number>();
  const pctErr = rows.map((r) => {
    const v = r.pct.trim();
    if (!v || !(Number(v) > 0)) return t("fx.sh.pctNeed");
    if (!/^\d+(\.\d{1,2})?$/.test(v)) return t("fx.sh.dec");
    if (Number(v) > 100) return t("fx.sh.pctMax");
    return "";
  });
  const rowErr = rows.map((r, i) => {
    const a = isAddressValid(r.wallet);
    if (!r.name.trim()) return t("v.sh.badname");
    if (!a) return r.wallet.trim() ? addrError(t, r.wallet) : t("v.sh.badaddr");
    const k = a.toLowerCase();
    if (seen.has(k)) return t("v.sh.dup");
    seen.set(k, 1);
    if (pctErr[i]) return "%";
    if (ok && !totalErr && shares[i] < 1) return t("fx.sh.zero", { n: fmt(T) });  // server: "would receive 0 shares"
    return "";
  });
  const tickerReady = /^[A-Z]{3}$/.test(ticker) && !tkBad && name.trim().length > 0;
  const valid = ok && T >= 1 && !totalErr && rowErr.every((e) => !e) && tickerReady;
  const folded = foldParts(rows.map((r, i) => ({ name: r.name || "—", v: Math.max(pcts[i], 0) })), t("c.other"));
  const parts = folded.map((p) => ({ ...p, tip: `${p.name} · ${fmt(p.v, 2)}%` }));

  const submit = async () => {
    setTouched(true);
    if (!valid) {
      setErr(t("v.sh.need"));
      // take the person to the first thing to fix: a bad row, else the % column of the last row
      const bad = rowErr.findIndex((e) => !!e);
      const i = bad >= 0 ? bad : rows.length - 1;
      const el = totalErr && bad < 0 ? document.querySelector<HTMLInputElement>("#supply")
        : document.querySelector<HTMLInputElement>(`[data-caprow="${i}"] ${bad >= 0 && rowErr[bad] !== "%" ? "input" : "input[type=number]"}`);
      el?.scrollIntoView({ behavior: "smooth", block: "center" });
      el?.focus({ preventScroll: true });
      return;
    }
    setBusy(true); setErr(""); setStage("creating");
    try {
      const holders = rows.map((r, i) => ({ name: r.name.trim(), wallet: isAddressValid(r.wallet)!, pct: Math.round(pcts[i] * 100) / 100 }));
      const c = await api.createCompany({ valuation_id: v.id, name: name.trim(), ticker, share_price_aud: 1, total_shares: T, holders });
      const tk = c.ticker ?? ticker;
      setStage("submitting");
      try {
        if (c.id != null) await api.submitCompany(c.id);
      } catch (e) {
        setStage("opening");
        nav(`/c/${tk}/issue`, { state: { flash: t("v.sh.draft", { e: errText(e, t) }), companyId: c.id } });
        return;
      }
      setStage("opening");
      nav(`/c/${tk}/issue`, { state: { flash: t("c.submitted") } });
    } catch (e) {
      setErr(errText(e, t));
    } finally {
      setBusy(false);
      setStage("");
    }
  };

  return (
    <>
      {!tickerReady && (
        <p className="quietline bad" role="alert">
          <span>{tkBad ? t("tk.stale", { t: tkBad }) : !name.trim() ? t("tk.name") : t("tk.first")}</span>
          <Link to={valPath(v.id, 4)}>{t("tk.back")} →</Link>
        </p>
      )}
      <div className="cols">
        <div className="card">
          <div className="field" style={{ alignItems: "center" }}>
            <label htmlFor="supply" className="sub">{t("s5.supply")}</label>
            <input id="supply" type="number" min={1} step={1000} value={total} className={totalErr ? "bad" : undefined} aria-invalid={!!totalErr} aria-describedby="supply-err" onChange={(e) => setTotal(e.target.value)} style={{ maxWidth: 180 }} />
            <button type="button" className="btn ghost sm" onClick={() => setTotal(String(mid))}>{money(mid)}</button>
          </div>
          <span className="hint">{t("v.sh.default", { n: fmt(mid) })}</span>
          {totalErr && <span id="supply-err" className="hint bad" role="alert">{totalErr}</span>}
          <div className="tbl captbl">
            <table>
              <thead><tr><th>{t("t.holder")}</th><th>{t("t.wallet")}</th><th className="r">%</th><th className="r">{t("t.shares")}</th><th><span className="sr-only">{t("v.sh.remove", { n: "" })}</span></th></tr></thead>
              <tbody>
                {rows.map((r, i) => {
                  const e0 = touched || r.wallet ? rowErr[i] : "";
                  const e = e0 === "%" ? "" : e0;  // percentage problems are shown under the % field
                  const pe = touched || r.pct.trim() !== "" ? pctErr[i] : "";
                  const addrBad = !!r.wallet && !isAddressValid(r.wallet);
                  return (
                    <tr key={r.id} data-caprow={i}>
                      <td><span className="sw" style={{ background: `var(${colorAt(i)})`, marginRight: 8 }} /><input className={"w-name" + (touched && !r.name.trim() ? " bad" : "")} value={r.name} placeholder={t("v.sh.name")} aria-label={`${t("t.holder")} ${i + 1}`} onChange={(x) => upd(r.id, "name", x.target.value)} /></td>
                      <td>
                        <input className={"w-addr" + (addrBad || (touched && e) ? " bad" : "")} value={r.wallet} placeholder="0x…" spellCheck={false} aria-label={`${t("t.wallet")} ${i + 1}`} aria-invalid={addrBad}
                          onChange={(x) => upd(r.id, "wallet", x.target.value.trim())}
                          onBlur={() => { const a = isAddressValid(r.wallet); if (a && a !== r.wallet) upd(r.id, "wallet", a); }} />
                        {e && <div className="hint bad">{e}</div>}
                      </td>
                      <td className="r"><input className={"w-pct" + (pe || ((touched || sumP > 100) && !ok) ? " bad" : "")} type="number" step="0.01" min={0} max={100} value={r.pct} aria-label={`${r.name || t("t.holder")} %`} aria-invalid={!ok || !!pctErr[i]} onChange={(x) => upd(r.id, "pct", x.target.value)} />{pe && <div className="hint bad">{pe}</div>}</td>
                      <td className="r">{fmt(shares[i] || 0)}</td>
                      <td>{rows.length > 1 && <button type="button" className="xbtn" aria-label={t("v.sh.remove", { n: r.name || String(i + 1) })} onClick={() => setRows((rs) => rs.filter((x) => x.id !== r.id))}>×</button>}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <button type="button" className="btn ghost sm" style={{ justifySelf: "start" }} onClick={() => setRows((rs) => [...rs, { id: rowSeq++, name: "", wallet: "", pct: String(Math.max(0, +(100 - sumP).toFixed(2))) }])}>+ {t("v.sh.add")}</button>
          <div className={"cap-total " + (ok ? "ok" : "bad")} role="status" aria-live="polite">
            <b>{t("cap.total", { p: fmt(sumP, 2) })}</b>
            <span className="bar" aria-hidden="true"><i style={{ width: `${Math.min(100, Math.max(0, sumP))}%` }} /></span>
            <span>{ok ? `${t("cap.ok")} · ${fmt(T)} ${t("t.shares").toLowerCase()}` : sumP < 100 ? t("cap.left", { p: fmt(100 - sumP, 2) }) : t("cap.over", { p: fmt(sumP - 100, 2) })}</span>
            {!ok && rows.length > 0 && (() => {
              const lastRow = rows[rows.length - 1];
              const rest = +(Number(lastRow.pct || 0) + 100 - sumP).toFixed(2);
              return rest > 0 ? <button type="button" className="btn ghost sm" onClick={() => upd(lastRow.id, "pct", String(rest))}>{t("cap.balance")}</button> : null;
            })()}
          </div>
        </div>
        <div className="card">
          <h4>{t("s5.preview")}</h4>
          <Donut parts={parts} center={T >= 1e6 ? fmt(T / 1e6, 1) + "M" : fmt(T)} sub={`${ticker || "???"} · ${t("t.shares").toLowerCase()}`} label={t("s5.preview")} />
          <Legend parts={folded.map((p) => ({ ...p, pct: p.v }))} />
          <p className="note">{t("s5.kyc")}</p>
        </div>
      </div>
      <p className="err" role="alert">{err}</p>
      <div className="pager">
        <span className="pl"><Link className="btn ghost" to={valPath(v.id, 4)}><span aria-hidden="true">←</span>{t("step.4")}</Link></span>
        <button className="btn gold" type="button" disabled={busy} onClick={submit}>{busy ? <span className="spinner" aria-hidden="true" /> : null}{busy ? t(stage ? (("sh.stage." + stage) as DictKey) : "v.sh.creating") : t("v.sh.submit")}</button>
      </div>
    </>
  );
}

/* ================= page ================= */
function useDraft(id: string) {
  const key = "bid.v." + id;
  const read = (): { name: string; ticker: string } => {
    try { const x = JSON.parse(sessionStorage.getItem(key) || "{}"); return { name: String(x.name ?? ""), ticker: String(x.ticker ?? "") }; } catch { return { name: "", ticker: "" }; }
  };
  const [d, setD] = useState(read);
  useEffect(() => { setD(read()); }, [id]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { try { sessionStorage.setItem(key, JSON.stringify(d)); } catch { /* private mode */ } }, [key, d]);
  return {
    name: d.name, ticker: d.ticker,
    setName: (name: string) => setD((x) => ({ ...x, name })),
    setTicker: (ticker: string) => setD((x) => ({ ...x, ticker })),
  };
}

export default function ValuationPage() {
  const { id = "", step: seg } = useParams();
  const { t } = useI18n();
  const nav = useNavigate();
  const { me, loading: authLoading, connect } = useAuth();
  const sample = id === "sample";
  const [status, setStatus] = useState<string>("");
  const poll = sample || !status || ACTIVE.includes(status) ? 3000 : null;
  const q = useAsync<Val>(() => (sample ? Promise.resolve(SAMPLE) : api.valuation(id)), [id, me?.address, me?.username], sample ? null : poll);
  const v = q.data;
  useEffect(() => { if (v) setStatus(v.status); }, [v?.status]); // eslint-disable-line react-hooks/exhaustive-deps
  const hasEvidence = !!v && ((v.counters?.sources ?? 0) > 0 || !!v.svi);
  const ev = useAsync<Evidence[] | undefined>(() => (sample ? Promise.resolve(SAMPLE_EVIDENCE) : hasEvidence ? api.evidence(id) : Promise.resolve(undefined)), [id, hasEvidence, v?.status, v?.counters?.sources]);
  const host = v ? v.url.replace(/^https?:\/\//, "") : "";
  useTitle(t("v.eyebrow") + (host ? " · " + host : ""));

  const reach = valReach(v, sample);
  const want = seg ? VAL_STEP[seg] : undefined;
  const cur = want ? Math.min(want, reach) : valAuto(v);
  const { name, ticker, setName, setTicker } = useDraft(id);
  const [toast, setToast] = useState("");
  // canonical URL: /v/:id/<step>; an unknown or not-yet-reachable step falls back to the furthest allowed one
  useEffect(() => {
    if (v && VAL_STEP[seg ?? ""] !== cur) nav(valPath(id, cur), { replace: true });
  }, [v != null, seg, cur, id]); // eslint-disable-line react-hooks/exhaustive-deps
  // research finished while watching step 2: move on to the report
  const hadSvi = useRef<boolean | null>(null);
  useEffect(() => {
    if (!v) return;
    if (hadSvi.current === false && v.svi && cur === 2) { nav(valPath(id, 3)); setToast(t("flow.auto.report")); }
    hadSvi.current = !!v.svi;
  }, [v?.svi]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (v?.status === "approved" && !name) {
      const pn = typeof v.profile?.name === "string" ? v.profile.name : "";
      let h = "";
      try { h = new URL(v.url).hostname.replace(/^www\./, "").split(".")[0]; } catch { /* */ }
      setName(pn || h.replace(/^\w/, (c) => c.toUpperCase()));
    }
  }, [v?.status]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (!toast) return; const x = setTimeout(() => setToast(""), 5000); return () => clearTimeout(x); }, [toast]);

  const rail = (
    <FlowRail cur={cur} reach={sample ? 3 : reach} gates={[valGate(v), "none"]}
      href={(n) => (n === 1 ? "/start" : n <= 5 ? valPath(id, n) : null)} />
  );

  if (q.loading && !v) return <SideLayout rail={rail} label={t("flow.nav")}><Loading /></SideLayout>;
  if (q.error && !v) {
    const e = q.error;
    return (
      <SideLayout rail={rail} label={t("flow.nav")}>
        <div className="stack">
          {e instanceof ApiError && (e.status === 401 || e.status === 403) ? (
            <>
              <StatusBar status={t("sb.st.private")} tone="idle" step={3} done={0} />
              <div className="pane stateCard soft">
                <h2>{t("v.private.h")}</h2>
                <p>{t("v.private.p")}</p>
                <div className="row">
                  <Link to="/start" className="btn">{t("v.private.btn")}</Link>
                  <Link to="/companies" className="btn ghost">{t("nav.companies")}</Link>
                  {!me && !authLoading && <button className="btn ghost" type="button" onClick={() => void connect().catch(() => undefined)}>{t("nav.connect")}</button>}
                </div>
              </div>
            </>
          ) : (
            <>
              {e instanceof ApiError && e.status === 404 ? <p className="quietline bad">{t("v.notfound")}</p> : <ErrorBox error={e} retry={q.reload} />}
              <Link to="/start" className="btn ghost" style={{ justifySelf: "start" }}>{t("v.newval")}</Link>
            </>
          )}
        </div>
      </SideLayout>
    );
  }
  if (!v) return <SideLayout rail={rail} label={t("flow.nav")}><Loading /></SideLayout>;

  const running = ACTIVE.includes(v.status) && v.status !== "waiting_approval";
  const HEAD: Record<number, [DictKey, DictKey]> = { 2: ["s2.h", "s2.p"], 3: ["s3.h", "s3.p"], 4: ["s4.h", "s4.p"], 5: ["s5.h", "s5.p"] };
  const statusPill = cur === 5 ? <span className="gatepill mono">{ticker}</span> : null;
  const isAdmin = me?.role === "admin" && !sample;
  const SB: Record<string, [DictKey, Tone]> = {
    queued: ["sb.st.queued", "run"], running: ["sb.st.researching", "run"], waiting_approval: ["sb.st.waiting", "wait"],
    approved: ["sb.st.approved", "ok"], rejected: ["sb.st.rejected", "bad"], failed: ["sb.st.failed", "bad"],
  };
  const [sbKey, sbTone] = sample ? (["sb.st.sample", "idle"] as [DictKey, Tone]) : SB[v.status] ?? (["sb.st.queued", "idle"] as [DictKey, Tone]);
  const retryTo = `/start?url=${encodeURIComponent(v.url.replace(/^https?:\/\//, "").replace(/\/$/, ""))}`;
  let sbNext: StatusNext | null = null;
  if (!sample && v.status === "waiting_approval" && !isAdmin) sbNext = { label: t("sb.next.approve"), to: demoApproveLink(`/admin/valuations/${encodeURIComponent(v.id)}`, valPath(v.id, 4)) };
  else if (!sample && (v.status === "failed" || v.status === "rejected")) sbNext = { label: t("sb.next.retry"), to: retryTo };
  else if (!sample && v.status === "approved" && cur < 4) sbNext = { label: t("step.4"), to: valPath(id, 4) };
  const sbDone = sample ? 3 : v.status === "approved" ? 3 : v.svi ? 2 : 1;
  const siteFail = siteReadFailed(v);

  // pager
  const prev = cur > 2 ? { to: valPath(id, cur - 1), label: t(("step." + (cur - 1)) as DictKey) } : { to: "/start", label: t("step.1") };
  let next: PagerLink | null = null;
  let reason: string | null = null;
  if (cur === 2) { next = { to: valPath(id, 3), label: t("step.3"), disabled: !v.svi }; if (!v.svi) reason = t("flow.why.research"); }
  if (cur === 3) {
    if (sample) next = { to: "/start", label: t("cta.primary") };
    else if (v.status === "approved") next = { to: valPath(id, 4), label: t("step.4") };
    else if (v.status === "rejected" || v.status === "failed") next = { to: "/start", label: t("v.newval") };
    else { next = { label: t("step.4"), disabled: true }; reason = t("flow.why.g1"); }
  }
  if (cur === 4) {
    const ok = /^[A-Z]{3}$/.test(ticker) && !!name.trim();
    next = { to: valPath(id, 5), label: t("step.5"), disabled: !ok };
    if (!ok) reason = t("flow.why.ticker");
  }

  return (
    <SideLayout rail={rail} label={t("flow.nav")}>
      <Crumbs items={[{ to: "/start", label: t("nav.studio") }, { label: host }, { label: `${String(cur).padStart(2, "0")} ${t(("step." + cur) as DictKey)}` }]} />
      <StatusBar status={t(sbKey)} tone={sbTone} step={cur} done={sbDone} since={running ? v.created_at : null} next={sbNext} />
      <StepHead eyebrow={t("flow.stepof", { n: cur, p: t(("flow.ph." + phaseOf(cur)) as DictKey) }) + (sample ? " · " + t("cta.secondary") : "")}
        title={t(HEAD[cur][0])} desc={t(HEAD[cur][1])} right={statusPill} />
      {toast && <p className="toast" role="status">{toast}</p>}
      {v.status === "failed" && !siteFail && (
        <p className="quietline bad" role="alert"><span>{t("v.stopped", { e: (v.error || "").slice(0, 160) })}</span><Link to={retryTo}>{t("sb.next.retry")} →</Link></p>
      )}
      {q.error ? <ErrorBox error={q.error} retry={q.reload} /> : null}

      {cur === 2 && siteFail && <SiteFailed v={v} />}
      {cur === 2 && <AgentLog v={v} />}
      {cur === 3 && v.svi && <Report v={v} evidence={ev.data} isAdmin={isAdmin} onDecided={(x) => q.setData(x)} onTeamDone={() => void q.reload()} />}
      {cur === 4 && !sample && (
        <div className="panel"><TickerStep name={name} setName={setName} ticker={ticker} setTicker={setTicker} /></div>
      )}
      {cur === 5 && !sample && (
        <div className="panel"><HoldersStep v={v} name={name} ticker={ticker} defaultWallet={me?.address} /></div>
      )}
      {(cur === 2 || cur === 3) && <Notes items={v.warnings ?? []} />}
      {cur !== 5 && <Pager prev={prev} next={next} reason={reason} />}
    </SideLayout>
  );
}
