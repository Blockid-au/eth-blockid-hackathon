import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  api, type CoDividend, type DividendLedger, type DividendPolicy, type DividendPolicyView, type PolicyFrequency, type PolicyIn, type PolicyKind, type UpcomingDividend,
} from "../api";
import { errText } from "../auth";
import { useI18n } from "../i18n";
import type { DictKey } from "../dict";
import { ErrorBox } from "../components/Layout";
import { useAsync } from "../lib/hooks";
import { shortAddr } from "../lib/addr";

/**
 * Automatic dividends (agents/src/blockid_agents/studio/dividend_policy.py).
 *   CompanyDividends   company workspace /c/:tk/dividends: the rule (set, send for approval, pause / resume),
 *                      next expected payment, and every dividend of the company with "Cancel payment" in the window
 *   PolicySummary      one-sentence rule, also used by the admin queue "Dividend rules"
 *   UpcomingDividends  investor position view: announced, not paid yet
 *   DividendLedgerCard investor portfolio: every dividend paid, with a link to the payment and a CSV download
 */
const SCAN_TX = "https://scan.blockid.au/tx/";

/* ---------- the rule in one sentence ---------- */
export function PolicySummary({ p }: { p: Pick<DividendPolicy, "kind" | "ratio_pct" | "fixed_maud" | "max_maud_per_round" | "frequency" | "veto_hours"> }) {
  const { t, fmt } = useI18n();
  const f = t(("dvp.sum.f." + p.frequency) as DictKey);
  const max = fmt(Number(p.max_maud_per_round), 2);
  return (
    <div className="stack" style={{ gap: 4 }}>
      <b>{p.kind === "payout_ratio" ? t("dvp.sum.payout_ratio", { r: fmt(Number(p.ratio_pct ?? 0), Number(p.ratio_pct ?? 0) % 1 ? 1 : 0), f, max }) : t("dvp.sum.fixed", { a: fmt(Number(p.fixed_maud ?? 0), 2), f, max })}</b>
      <span className="muted-sm">{t("dvp.sum.only", { c: t(("upd.cad." + p.frequency) as DictKey).toLowerCase() })} {t("dvp.sum.wait", { h: p.veto_hours })}</span>
    </div>
  );
}

export function PolicyPill({ s }: { s: DividendPolicy["status"] }) {
  const { t } = useI18n();
  const cls = s === "active" ? " ok" : s === "rejected" ? " bad" : s === "pending_approval" ? " gold" : "";
  return <span className={"pill" + cls}>{t(("dvp.st." + s) as DictKey)}</span>;
}

function DivPill({ s }: { s: string }) {
  const { t } = useI18n();
  const cls = s === "paid" ? " ok" : s === "rejected" || s === "failed" ? " bad" : s === "scheduled" || s === "pending" || s === "approved" || s === "paying" ? " gold" : "";
  const k = ("dvs.st." + s) as DictKey;
  return <span className={"pill" + cls}>{t(k) === k ? s : t(k)}</span>;
}

/* ---------- company: set the rule ---------- */
function PolicyForm({ ticker, cur, onSaved, onCancel }: { ticker: string; cur: DividendPolicy | null; onSaved: (v: DividendPolicyView, msg: string) => void; onCancel?: () => void }) {
  const { t } = useI18n();
  const [kind, setKind] = useState<PolicyKind>(cur?.kind ?? "payout_ratio");
  const [ratio, setRatio] = useState(cur?.ratio_pct != null ? String(cur.ratio_pct) : "30");
  const [fixed, setFixed] = useState(cur?.fixed_maud != null ? String(cur.fixed_maud) : "10000");
  const [max, setMax] = useState(cur ? String(cur.max_maud_per_round) : "50000");
  const [freq, setFreq] = useState<PolicyFrequency>(cur?.frequency ?? "quarterly");
  const [veto, setVeto] = useState(String(cur?.veto_hours ?? 24));
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const num = (v: string) => Number(v.trim().replace(/,/g, ""));
  const body: PolicyIn = { kind, ratio_pct: kind === "payout_ratio" ? num(ratio) : null, fixed_maud: kind === "fixed" ? num(fixed) : null, max_maud_per_round: num(max), frequency: freq, veto_hours: Math.round(num(veto)) };
  const ok = body.max_maud_per_round > 0 && body.veto_hours >= 1 && (kind === "payout_ratio" ? (body.ratio_pct ?? 0) > 0 : (body.fixed_maud ?? 0) > 0);
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!ok) { setErr(t("dvp.need")); return; }
    setBusy(true); setErr("");
    try { onSaved(await api.saveDividendPolicy(ticker, body), t("dvp.saved")); } catch (x) { setErr(errText(x, t)); } finally { setBusy(false); }
  };
  return (
    <form className="stack" onSubmit={submit} noValidate>
      {cur && (cur.status === "active" || cur.status === "paused") && <p className="banner warn" role="note">{t("dvp.editwarn")}</p>}
      <div className="segs" role="tablist" aria-label={t("dvp.kind")}>
        {(["payout_ratio", "fixed"] as PolicyKind[]).map((k) => <button key={k} type="button" role="tab" aria-selected={kind === k} onClick={() => setKind(k)}>{t(("dvp.kind." + k) as DictKey)}</button>)}
      </div>
      <div className="fgrid">
        {kind === "payout_ratio" ? (
          <label className="lf"><span>{t("dvp.ratio")}</span><input type="number" inputMode="decimal" min={0.1} max={100} step="any" value={ratio} onChange={(e) => setRatio(e.target.value)} /></label>
        ) : (
          <label className="lf"><span>{t("dvp.fixed")}</span><input type="number" inputMode="decimal" min={1} step="any" value={fixed} onChange={(e) => setFixed(e.target.value)} /></label>
        )}
        <label className="lf"><span>{t("dvp.max")}</span><input type="number" inputMode="decimal" min={1} step="any" value={max} onChange={(e) => setMax(e.target.value)} /></label>
        <label className="lf"><span>{t("dvp.freq")}</span>
          <select value={freq} onChange={(e) => setFreq(e.target.value as PolicyFrequency)}>
            {(["quarterly", "monthly"] as PolicyFrequency[]).map((x) => <option key={x} value={x}>{t(("dvp.freq." + x) as DictKey)}</option>)}
          </select>
        </label>
        <label className="lf"><span>{t("dvp.veto")}</span><input type="number" inputMode="numeric" min={1} max={168} step={1} value={veto} onChange={(e) => setVeto(e.target.value)} /></label>
      </div>
      {ok && <div className="pane"><PolicySummary p={{ ...body, max_maud_per_round: body.max_maud_per_round }} /></div>}
      <div className="row" style={{ gap: 8, flexWrap: "wrap" }}>
        <button className="btn" type="submit" disabled={busy}>{t("dvp.save")}</button>
        {onCancel && <button className="btn ghost" type="button" onClick={onCancel}>{t("dvp.keep")}</button>}
      </div>
      {err && <p className="err" role="alert">{err}</p>}
    </form>
  );
}

function PolicyCard({ v, onChanged }: { v: DividendPolicyView; onChanged: (v: DividendPolicyView) => void }) {
  const { t, fmt, date } = useI18n();
  const p = v.policy;
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; s: string } | null>(null);
  const act = async (a: "submit" | "pause" | "resume", okMsg: DictKey) => {
    setBusy(true); setMsg(null);
    try { onChanged(await api.policyAction(v.ticker, a)); setMsg({ ok: true, s: t(okMsg) }); } catch (x) { setMsg({ ok: false, s: errText(x, t) }); } finally { setBusy(false); }
  };
  const showForm = v.live && (!p || editing || p.status === "draft");
  return (
    <section className="card solid">
      <div className="between">
        <h4 style={{ margin: 0 }}>{t("dvp.h")}</h4>
        {p && <PolicyPill s={p.status} />}
      </div>
      <p className="sub">{t("dvp.p")}</p>
      {!v.live && <p className="banner gold">{t("dvp.onlylive")}</p>}
      {!p && v.live && <span className="muted-sm">{t("dvp.none")}</span>}
      {p && !showForm && <div className="pane"><PolicySummary p={p} /></div>}
      {p?.status === "rejected" && <p className="banner bad" role="note">{t("dvp.rejected", { r: p.reason || "–" })}</p>}
      {p?.approved_at && (p.status === "active" || p.status === "paused") && <span className="muted-sm">{t("dvp.approved", { d: date(p.approved_at) })}</span>}
      {p?.status === "active" && v.next && (
        <div className="nextact">
          <div><span className="eyebrow">{t("dvp.next")}</span><p>{t("dvp.next.p", { p: v.next.period_label, h: v.next.veto_hours, max: fmt(v.next.max_maud, 2) })}</p></div>
        </div>
      )}
      {showForm && <PolicyForm ticker={v.ticker} cur={p} onSaved={(nv, s) => { onChanged(nv); setEditing(false); setMsg({ ok: true, s }); }} onCancel={editing ? () => setEditing(false) : undefined} />}
      <div className="row" style={{ gap: 8, flexWrap: "wrap" }}>
        {p && (p.status === "draft" || p.status === "rejected") && <button className="btn gold" type="button" disabled={busy} onClick={() => act("submit", "dvp.submitted")}>{t("dvp.submit")}</button>}
        {p?.status === "active" && <button className="btn ghost sm" type="button" disabled={busy} onClick={() => act("pause", "dvp.paused")}>{t("dvp.pause")}</button>}
        {p?.status === "paused" && <button className="btn sm" type="button" disabled={busy} onClick={() => act("resume", "dvp.resumed")}>{t("dvp.resume")}</button>}
        {p && v.live && !editing && p.status !== "draft" && p.status !== "pending_approval" && <button className="btn ghost sm" type="button" onClick={() => setEditing(true)}>{t("dvp.edit")}</button>}
      </div>
      {msg && <p className={msg.ok ? "toast" : "err"} role={msg.ok ? "status" : "alert"}>{msg.s}</p>}
    </section>
  );
}

function DividendRows({ v, onChanged }: { v: DividendPolicyView; onChanged: (v: DividendPolicyView) => void }) {
  const { t, fmt, date } = useI18n();
  const [busy, setBusy] = useState<number | null>(null);
  const [msg, setMsg] = useState<{ ok: boolean; s: string } | null>(null);
  const cancel = async (d: CoDividend) => {
    if (!window.confirm(t("dvl.confirm", { n: fmt(d.total_maud, 2) }))) return;
    setBusy(d.id); setMsg(null);
    try { onChanged(await api.vetoDividend(v.ticker, d.id)); setMsg({ ok: true, s: t("dvl.cancelled") }); } catch (x) { setMsg({ ok: false, s: errText(x, t) }); } finally { setBusy(null); }
  };
  return (
    <section className="pane">
      <h4>{t("dvl.h")}</h4>
      {v.dividends.length === 0 ? <span className="muted">{t("dvl.empty")}</span> : (
        <div className="tbl"><table>
          <thead><tr><th>{t("dvl.date")}</th><th>{t("dvl.period")}</th><th className="num">{t("dvl.amount")}</th><th>{t("dvl.how")}</th><th>{t("dvl.status")}</th><th>{t("dvl.pays")}</th><th /></tr></thead>
          <tbody>
            {v.dividends.map((d) => (
              <tr key={d.id}>
                <td>{date(d.created_at)}</td>
                <td>{d.period_label ?? "–"}</td>
                <td className="num mono">{d.status === "skipped" ? "–" : fmt(d.total_maud, 2)}</td>
                <td>{t(d.source === "policy" ? "dvl.src.policy" : "dvl.src.manual")}</td>
                <td><DivPill s={d.status} />{(d.status === "skipped" || d.status === "vetoed") && d.note ? <span className="muted-sm"> · {d.note}</span> : null}</td>
                <td>{d.status === "scheduled" && d.pay_after ? date(d.pay_after, true) : d.tx_hash ? <a href={SCAN_TX + d.tx_hash} target="_blank" rel="noopener noreferrer" className="mono">{shortAddr(d.tx_hash)}</a> : "–"}</td>
                <td>{d.status === "scheduled" && <button className="btn danger sm" type="button" disabled={busy != null} onClick={() => void cancel(d)}>{t("dvl.cancel")}</button>}</td>
              </tr>
            ))}
          </tbody>
        </table></div>
      )}
      {msg && <p className={msg.ok ? "toast" : "err"} role={msg.ok ? "status" : "alert"}>{msg.s}</p>}
    </section>
  );
}

export function CompanyDividends({ ticker }: { ticker: string }) {
  const { t } = useI18n();
  const q = useAsync(() => api.dividendPolicy(ticker), [ticker], 30000);
  const [v, setV] = useState<DividendPolicyView | null>(null);
  useEffect(() => { if (q.data) setV(q.data); }, [q.data]);
  if (q.error && !v) return <ErrorBox error={q.error} retry={q.reload} />;
  if (!v) return <p className="note">{t("common.loading")}</p>;
  return (
    <div className="stack">
      <PolicyCard v={v} onChanged={setV} />
      <DividendRows v={v} onChanged={setV} />
      <p className="muted-sm">{t("dvp.legal")}</p>
    </div>
  );
}

/* ---------- investor ---------- */
export function UpcomingDividends({ list }: { list: UpcomingDividend[] }) {
  const { t, fmt, date } = useI18n();
  if (!list.length) return null;
  return (
    <section className="card solid">
      <h4>{t("inv.up.h")}</h4>
      <ul className="inv-divs">
        {list.map((u) => (
          <li key={u.dividend_id}>
            <span>{u.ticker ? <b className="mono">{u.ticker} </b> : null}{u.period_label ? t("inv.up.row", { n: fmt(u.amount_maud, 2), p: u.period_label }) : t("inv.up.rowNoP", { n: fmt(u.amount_maud, 2) })}</span>
            <b>{t("inv.up.pays", { d: date(u.pay_after, true) })}</b>
          </li>
        ))}
      </ul>
      <span className="muted-sm">{t("inv.up.p")}</span>
    </section>
  );
}

const csvCell = (v: string | number) => {
  const s = String(v);
  return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
};

export function ledgerCsv(l: DividendLedger): string {
  const head = ["date", "ticker", "business", "amount_maud", "wallet", "transaction", "link"];
  const rows = l.paid.map((d) => [d.at, d.ticker, d.company, d.amount_maud.toFixed(6), d.wallet ?? "", d.tx_hash ?? "", d.tx_hash ? SCAN_TX + d.tx_hash : ""]);
  return [head, ...rows].map((r) => r.map(csvCell).join(",")).join("\r\n") + "\r\n";
}

function download(name: string, text: string) {
  const url = URL.createObjectURL(new Blob([text], { type: "text/csv;charset=utf-8" }));
  const a = document.createElement("a");
  a.href = url; a.download = name;
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function DividendLedgerCard({ demo }: { demo: boolean }) {
  const { t, fmt, date } = useI18n();
  const q = useAsync<DividendLedger>(() => (demo ? api.demoDividends() : api.myDividends()), [demo], 60000);
  if (q.error) return null;  // the portfolio above already shows dividends per business
  if (!q.data) return null;
  const l = q.data;
  return (
    <section className="card solid inv-ledger">
      <div className="between">
        <h4 style={{ margin: 0 }}>{t("inv.led.h")}</h4>
        {l.paid.length > 0 && <button className="btn ghost sm" type="button" onClick={() => download(`dividends-${new Date().toISOString().slice(0, 10)}.csv`, ledgerCsv(l))}>{t("inv.led.csv")}</button>}
      </div>
      <p className="muted-sm">{t("inv.led.p")}</p>
      {l.upcoming.length > 0 && (
        <div className="stack" style={{ gap: 6 }}>
          <span className="eyebrow">{t("inv.led.upcoming")}</span>
          <ul className="inv-divs">
            {l.upcoming.map((u) => (
              <li key={u.dividend_id}><span><b className="mono">{u.ticker}</b> · {u.company}{u.period_label ? ` · ${u.period_label}` : ""}</span><b>{fmt(u.amount_maud, 2)} mAUD · {t("inv.up.pays", { d: date(u.pay_after) })}</b></li>
            ))}
          </ul>
        </div>
      )}
      {l.paid.length === 0 ? <span className="muted">{t("inv.led.empty")}</span> : (
        <div className="tbl"><table>
          <thead><tr><th>{t("inv.led.date")}</th><th>{t("inv.led.co")}</th><th className="num">{t("inv.led.amt")}</th><th>{t("inv.led.tx")}</th></tr></thead>
          <tbody>
            {l.paid.slice(0, 100).map((d, i) => (
              <tr key={(d.tx_hash ?? "") + i}>
                <td>{date(d.at)}</td>
                <td><Link to={`/c/${d.ticker}/overview`}><b className="mono">{d.ticker}</b></Link> <span className="muted-sm">{d.company}</span></td>
                <td className="num mono">{fmt(d.amount_maud, 2)}</td>
                <td>{d.tx_hash ? <a href={SCAN_TX + d.tx_hash} target="_blank" rel="noopener noreferrer">{t("inv.led.view")} <span className="mono muted-sm">{shortAddr(d.tx_hash)}</span></a> : "–"}</td>
              </tr>
            ))}
          </tbody>
        </table></div>
      )}
      {l.paid.length > 0 && <b>{t("inv.led.total", { n: fmt(l.total_maud, 2) })}</b>}
      <span className="muted-sm">{t("inv.led.note")}</span>
    </section>
  );
}
