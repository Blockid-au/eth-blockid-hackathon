import { useEffect, useRef, useState } from "react";
import type { DictKey } from "../dict";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useI18n } from "../i18n";
import { errText, useAuth } from "../auth";
import { api, ApiError, type Evidence, type Svi, type TickerCandidate, type Valuation as Val } from "../api";
import { Stepper } from "../components/Stepper";
import { DemoApproveGuide } from "../components/DemoGuide";
import { Contrib, Donut, HBars, Legend, Radar, RangeChart } from "../components/charts";
import { ErrorBox, Loading } from "../components/Layout";
import { useAsync, useTitle } from "../lib/hooks";
import { bandGrade, dimRows, OVERRIDABLE, stepLabel } from "../lib/svi";
import { allocate, colorAt, foldParts } from "../lib/math";
import { SAMPLE, SAMPLE_EVIDENCE } from "../lib/sample";
import { SR_FIELDS, type SrField } from "../lib/selfReported";
import { isAddressValid } from "../wallet";

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
    <div className="panel" role="region" aria-labelledby="s2h">
      <div className="ptitle"><div><h3 id="s2h">{t("s2.h")}</h3><p>{t("s2.p")}</p></div><span className="live" aria-live="polite">{ACTIVE.includes(v.status) && v.status !== "waiting_approval" ? <i /> : null}{t(("v.st." + v.status) as "v.st.queued")}</span></div>
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

function Report({ v, evidence, isAdmin, onDecided }: { v: Val; evidence: Evidence[] | undefined; isAdmin: boolean; onDecided: (x: Val) => void }) {
  const { t, fmt, money, date } = useI18n();
  const svi = v.svi!;
  const rows = dimRows(svi, t);
  const g = bandGrade(svi);
  const comps = (v.competitors ?? []).slice(0, 8);
  const nSrc = (s: unknown) => (Array.isArray(s) ? s.length : typeof s === "number" ? s : 0);
  return (
    <div className="panel" role="region" aria-labelledby="s3h">
      <div className="ptitle">
        <div><h3 id="s3h">{t("s3.h")}</h3><p>{t("s3.p")}</p></div>
        <span className="gatepill">{v.status === "approved" ? "✓ " + t("v.st.approved") : t("gate.admin")}</span>
      </div>
      {v.status === "waiting_approval" && <p className="banner gold" role="status"><span className="spinner" aria-hidden="true" />{t("v.waiting")}</p>}
      {v.status === "rejected" && <p className="banner bad" role="status">{t("v.rejected")}</p>}
      {!isAdmin && v.status === "waiting_approval" && <DemoApproveGuide action={t("s3.approve")} tail="demo.tail.val" />}
      {isAdmin && v.status === "waiting_approval" && <AdminReview v={v} svi={svi} onDone={onDecided} />}
      <div className="row" style={{ gap: 14 }}>
        <span className="gradebadge" aria-label={`${t("ad.c.grade")} ${g}`}>{g}</span>
        <span className="bigno">{money(svi.valuation_mid_aud)}</span>
        <span className="muted">SVI {fmt(svi.index, 1)} · {money(svi.valuation_low_aud)} – {money(svi.valuation_high_aud)}</span>
      </div>
      <div className="cols">
        <div className="card"><h4>{t("s3.radar")}</h4><Radar dims={rows} /></div>
        <div className="card">
          <h4>{t("s3.build")}</h4>
          <p className="sub">{t("s3.buildp")}</p>
          <Contrib dims={rows} totalLabel={t("v.total", { g })} />
        </div>
      </div>
      {v.self_reported && <SelfReportedTable sr={v.self_reported} />}
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

/* ================= step 4: ticker ================= */
function TickerStep({ name, setName, ticker, setTicker }: { name: string; setName: (s: string) => void; ticker: string; setTicker: (s: string) => void }) {
  const { t } = useI18n();
  const [cands, setCands] = useState<TickerCandidate[] | null>(null);
  const [err, setErr] = useState("");
  const [custom, setCustom] = useState("");
  useEffect(() => {
    if (!name.trim()) return;
    let live = true;
    const id = setTimeout(async () => {
      try {
        const r = await api.suggestTickers(name.trim());
        if (!live) return;
        setCands(r.candidates);
        setErr("");
        if (!ticker || !r.candidates.some((c) => c.ticker === ticker)) {
          const first = r.candidates.find((c) => c.available);
          if (first && !custom) setTicker(first.ticker);
        }
      } catch (e) {
        if (live) setErr(errText(e, t));
      }
    }, 400);
    return () => { live = false; clearTimeout(id); };
  }, [name]); // eslint-disable-line react-hooks/exhaustive-deps
  const bad = custom !== "" && !/^[A-Z]{3}$/.test(custom);
  return (
    <div className="cols">
      <div className="card">
        <label className="lf"><span>{t("v.tk.cname")}</span><input value={name} onChange={(e) => setName(e.target.value)} maxLength={80} /></label>
        <div className="tickers" role="group" aria-label={t("s4.h")}>
          {cands?.map((c) => (
            <button key={c.ticker} type="button" className="tk" aria-pressed={c.ticker === ticker} disabled={!c.available} onClick={() => { setCustom(""); setTicker(c.ticker); }} title={c.available ? c.rule : t("v.tk.taken")}>{c.ticker}</button>
          ))}
          {!cands && !err && <span className="note">{t("common.loading")}</span>}
        </div>
        <label className="lf"><span>{t("v.tk.custom")}</span>
          <input className={"tkinput" + (bad ? " bad" : "")} value={custom} maxLength={3} aria-invalid={bad} onChange={(e) => { const x = e.target.value.toUpperCase().replace(/[^A-Z]/g, ""); setCustom(x); if (/^[A-Z]{3}$/.test(x)) setTicker(x); }} />
        </label>
        {bad && <span className="hint bad">{t("v.tk.bad")}</span>}
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

  const upd = (id: number, k: keyof Row, val: string) => setRows((rs) => rs.map((r) => (r.id === id ? { ...r, [k]: val } : r)));
  const pcts = rows.map((r) => Number(r.pct) || 0);
  const sumP = pcts.reduce((a, b) => a + b, 0);
  const ok = Math.abs(sumP - 100) < 1e-6;
  const T = Math.max(0, Math.floor(Number(total) || 0));
  const shares = ok ? allocate(T, pcts) : pcts.map((p) => Math.floor((T * p) / 100));
  const seen = new Map<string, number>();
  const rowErr = rows.map((r) => {
    const a = isAddressValid(r.wallet);
    if (!r.name.trim()) return t("v.sh.badname");
    if (!a) return t("v.sh.badaddr");
    const k = a.toLowerCase();
    if (seen.has(k)) return t("v.sh.dup");
    seen.set(k, 1);
    if (!(Number(r.pct) > 0)) return "%";
    return "";
  });
  const valid = ok && T >= 1 && rowErr.every((e) => !e) && /^[A-Z]{3}$/.test(ticker) && name.trim().length > 0;
  const folded = foldParts(rows.map((r, i) => ({ name: r.name || "—", v: Math.max(pcts[i], 0) })), t("c.other"));
  const parts = folded.map((p) => ({ ...p, tip: `${p.name} · ${fmt(p.v, 2)}%` }));

  const submit = async () => {
    setTouched(true);
    if (!valid) { setErr(t("v.sh.need")); return; }
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
        nav(`/c/${tk}`, { state: { flash: t("v.sh.draft", { e: errText(e, t) }), companyId: c.id } });
        return;
      }
      setStage("opening");
      nav(`/c/${tk}`, { state: { flash: t("c.submitted") } });
    } catch (e) {
      setErr(errText(e, t));
    } finally {
      setBusy(false);
      setStage("");
    }
  };

  return (
    <>
      <div className="cols">
        <div className="card">
          <div className="field" style={{ alignItems: "center" }}>
            <label htmlFor="supply" className="sub">{t("s5.supply")}</label>
            <input id="supply" type="number" min={1} step={1000} value={total} onChange={(e) => setTotal(e.target.value)} style={{ maxWidth: 180 }} />
            <button type="button" className="btn ghost sm" onClick={() => setTotal(String(mid))}>{money(mid)}</button>
          </div>
          <span className="hint">{t("v.sh.default", { n: fmt(mid) })}</span>
          <div className="tbl">
            <table>
              <thead><tr><th>{t("t.holder")}</th><th>{t("t.wallet")}</th><th className="r">%</th><th className="r">{t("t.shares")}</th><th><span className="sr-only">{t("v.sh.remove", { n: "" })}</span></th></tr></thead>
              <tbody>
                {rows.map((r, i) => {
                  const e = touched || r.wallet ? rowErr[i] : "";
                  const addrBad = !!r.wallet && !isAddressValid(r.wallet);
                  return (
                    <tr key={r.id}>
                      <td><span className="sw" style={{ background: `var(${colorAt(i)})`, marginRight: 8 }} /><input className={"w-name" + (touched && !r.name.trim() ? " bad" : "")} value={r.name} placeholder={t("v.sh.name")} aria-label={`${t("t.holder")} ${i + 1}`} onChange={(x) => upd(r.id, "name", x.target.value)} /></td>
                      <td>
                        <input className={"w-addr" + (addrBad || (touched && e) ? " bad" : "")} value={r.wallet} placeholder="0x…" spellCheck={false} aria-label={`${t("t.wallet")} ${i + 1}`} aria-invalid={addrBad}
                          onChange={(x) => upd(r.id, "wallet", x.target.value.trim())}
                          onBlur={() => { const a = isAddressValid(r.wallet); if (a && a !== r.wallet) upd(r.id, "wallet", a); }} />
                        {e && <div className="hint bad">{e}</div>}
                      </td>
                      <td className="r"><input type="number" step="0.01" min={0} max={100} value={r.pct} aria-label={`${r.name || t("t.holder")} %`} onChange={(x) => upd(r.id, "pct", x.target.value)} /></td>
                      <td className="r">{fmt(shares[i] || 0)}</td>
                      <td>{rows.length > 1 && <button type="button" className="xbtn" aria-label={t("v.sh.remove", { n: r.name || String(i + 1) })} onClick={() => setRows((rs) => rs.filter((x) => x.id !== r.id))}>×</button>}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <button type="button" className="btn ghost sm" style={{ justifySelf: "start" }} onClick={() => setRows((rs) => [...rs, { id: rowSeq++, name: "", wallet: "", pct: String(Math.max(0, +(100 - sumP).toFixed(2))) }])}>+ {t("v.sh.add")}</button>
          <div className={"totalrow " + (ok ? "ok" : "bad")} role="status">
            {ok ? `${t("s5.ok")} · ${fmt(T)} ${t("t.shares").toLowerCase()}` : t("s5.bad", { p: fmt(sumP, 2) })}
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
      <div className="pnav" style={{ borderTop: 0, paddingTop: 0 }}>
        <span />
        <button className="btn" type="button" disabled={busy} onClick={submit}>{busy ? <span className="spinner" aria-hidden="true" /> : null}{busy ? t(stage ? (("sh.stage." + stage) as DictKey) : "v.sh.creating") : t("v.sh.submit")}</button>
      </div>
    </>
  );
}

/* ================= page ================= */
export default function ValuationPage() {
  const { id = "" } = useParams();
  const { t } = useI18n();
  const { me, loading: authLoading, connect } = useAuth();
  const sample = id === "sample";
  const [status, setStatus] = useState<string>("");
  const poll = sample || !status || ACTIVE.includes(status) ? 3000 : null;
  const q = useAsync<Val>(() => (sample ? Promise.resolve(SAMPLE) : api.valuation(id)), [id, me?.address, me?.username], sample ? null : poll);
  const v = q.data;
  useEffect(() => { if (v) setStatus(v.status); }, [v?.status]); // eslint-disable-line react-hooks/exhaustive-deps
  const hasEvidence = !!v && ((v.counters?.sources ?? 0) > 0 || !!v.svi);
  const ev = useAsync<Evidence[] | undefined>(() => (sample ? Promise.resolve(SAMPLE_EVIDENCE) : hasEvidence ? api.evidence(id) : Promise.resolve(undefined)), [id, hasEvidence, v?.status, v?.counters?.sources]);
  useTitle(t("v.eyebrow") + (v ? " · " + v.url.replace(/^https?:\/\//, "") : ""));

  const auto = !v ? 2 : v.svi ? 3 : 2;
  const [view, setView] = useState<number | null>(null);
  const cur = view ?? auto;
  const reach = !v ? 2 : sample ? 3 : v.status === "approved" ? 5 : v.svi ? 3 : 2;
  const [name, setName] = useState("");
  const [ticker, setTicker] = useState("");
  const nameInit = useRef(false);
  useEffect(() => {
    if (!nameInit.current && v?.status === "approved") {
      nameInit.current = true;
      const pn = typeof v.profile?.name === "string" ? v.profile.name : "";
      let host = "";
      try { host = new URL(v.url).hostname.replace(/^www\./, "").split(".")[0]; } catch { /* */ }
      setName(pn || host.replace(/^\w/, (c) => c.toUpperCase()));
    }
  }, [v]);

  if (q.loading && !v) return <Loading />;
  if (q.error && !v) {
    const e = q.error;
    return (
      <div className="wrap page stack">
        {e instanceof ApiError && e.status === 404 ? <p className="banner warn">{t("v.notfound")}</p> :
          e instanceof ApiError && (e.status === 401 || e.status === 403) ? (
            <div className="banner gold"><span>{t("v.signin")}</span>{!me && !authLoading && <button className="btn sm" type="button" onClick={() => void connect().catch(() => undefined)}>{t("nav.connect")}</button>}</div>
          ) : <ErrorBox error={e} retry={q.reload} />}
        <Link to="/new" className="btn ghost" style={{ justifySelf: "start" }}>{t("v.newval")}</Link>
      </div>
    );
  }
  if (!v) return <Loading />;

  const done = v.status === "approved" ? Math.max(3, cur - 1) : v.svi ? 2 : 1;
  const host = v.url.replace(/^https?:\/\//, "");
  return (
    <section className="block" style={{ borderTop: 0, paddingTop: 40 }}>
      <div className="wrap stack">
        <div className="head" style={{ marginBottom: 12 }}>
          <span className="eyebrow">{t("v.eyebrow")}{sample ? " · " + t("cta.secondary") : ""}</span>
          <h2 style={{ overflowWrap: "anywhere" }}>{host}</h2>
        </div>
        <Stepper cur={cur} done={done} reach={reach} onPick={(i) => setView(i)} />
        {v.status === "failed" && <p className="banner bad" role="alert">{t("v.failed", { e: v.error || "" })}</p>}
        {(v.warnings ?? []).length > 0 && <div className="banner warn" role="status"><b>{t("v.warn")}</b>{(v.warnings ?? []).map((w, i) => <span key={i}>· {w}</span>)}</div>}
        {q.error ? <ErrorBox error={q.error} retry={q.reload} /> : null}

        {cur === 2 && <AgentLog v={v} />}
        {cur === 3 && v.svi && <Report v={v} evidence={ev.data} isAdmin={me?.role === "admin" && !sample} onDecided={(x) => q.setData(x)} />}
        {reach >= 4 && !sample && (
          <div className="panel" hidden={cur !== 4}>
            <div className="ptitle"><div><h3>{t("s4.h")}</h3><p>{t("s4.p")}</p></div></div>
            <TickerStep name={name} setName={setName} ticker={ticker} setTicker={setTicker} />
          </div>
        )}
        {reach >= 5 && !sample && (
          <div className="panel" hidden={cur !== 5}>
            <div className="ptitle"><div><h3>{t("s5.h")}</h3><p>{t("s5.p")}</p></div><span className="gatepill mono">{ticker}</span></div>
            <HoldersStep v={v} name={name} ticker={ticker} defaultWallet={me?.address} />
          </div>
        )}

        <div className="pnav">
          {cur > 2 ? <button className="btn ghost" type="button" onClick={() => setView(cur - 1)}>{t("nav.back")}</button> : <span />}
          {cur === 2 && v.svi && <button className="btn" type="button" onClick={() => setView(3)}>{t("nav.next")}</button>}
          {cur === 3 && sample && <Link className="btn" to="/new">{t("cta.primary")}</Link>}
          {cur === 3 && !sample && v.status === "approved" && <button className="btn" type="button" onClick={() => setView(4)}>{t("v.continue")}</button>}
          {cur === 3 && (v.status === "rejected" || v.status === "failed") && <Link className="btn" to="/new">{t("v.newval")}</Link>}
          {cur === 4 && <button className="btn" type="button" disabled={!/^[A-Z]{3}$/.test(ticker) || !name.trim()} onClick={() => setView(5)}>{t("nav.next")}</button>}
        </div>
      </div>
    </section>
  );
}
