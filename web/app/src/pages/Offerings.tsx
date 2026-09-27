import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  api, ApiError, type CompanyOfferingView, type Offering, type OfferingPack, type OfferingProgress, type OfferingStatus, type OfferingTerms, type Reservation,
} from "../api";
import { errText, useAuth } from "../auth";
import { useI18n } from "../i18n";
import type { DictKey } from "../dict";
import { ErrorBox, Loading } from "../components/Layout";
import { SignInCard } from "../components/SignIn";
import { StatusBar, type StatusNext, type Tone } from "../components/StatusBar";
import { useAsync, useTitle } from "../lib/hooks";
import { GRADE_C } from "../lib/math";
import { shortAddr } from "../lib/addr";
import { demoApproveLink } from "../components/DemoGuide";
import { readNumber, readWhole } from "../lib/typed";
import { OfferFinalNote } from "./valuation5/Finalise";
export { OfferingBadge } from "../components/OfferingBadge";

/**
 * Simulated share offering (agents/src/blockid_agents/studio/offerings.py). No money moves on testnet.
 *   CompanyOffering      company workspace /c/:tk/offering: terms, information pack preview, send for approval, close
 *   OfferingsList        /i/offerings: open and finished offerings
 *   OfferingDetail       /i/offerings/:id: information pack, "I have read the risks", reserve / withdraw
 *   MyReservations       portfolio card: my reservations with their status
 *   OfferingQueueItem    admin queue "Offerings" (open / settle)
 *   OfferingBadge        "Offering open" chip for business cards and the company page
 */

const TONE: Record<OfferingStatus, Tone> = {
  draft: "idle", pending_approval: "wait", rejected: "bad", cancelled: "idle", open: "ok", awaiting_settlement: "wait",
  settling: "run", settled: "ok", released: "idle", failed: "bad",
};

export function OfferingPill({ s }: { s: OfferingStatus }) {
  const { t } = useI18n();
  const cls = s === "open" || s === "settled" ? " ok" : s === "rejected" || s === "failed" ? " bad" : s === "pending_approval" || s === "awaiting_settlement" || s === "settling" ? " gold" : "";
  return <span className={"pill" + cls}>{t(("of.st." + s) as DictKey)}</span>;
}

function ResPill({ s }: { s: Reservation["status"] }) {
  const { t } = useI18n();
  const cls = s === "allocated" ? " ok" : s === "reserved" ? " gold" : "";
  return <span className={"pill" + cls}>{t(("of.rs." + s) as DictKey)}</span>;
}

function SimChip() {
  const { t } = useI18n();
  return <p className="chipline"><span className="infochip"><i aria-hidden="true" />{t("of.sim")}</span></p>;
}

/* ---------- progress ---------- */
function ProgressView({ o, p }: { o: Pick<Offering, "shares_offered" | "min_raise_aud" | "price_aud" | "closes_at" | "status" | "closed_at">; p: OfferingProgress }) {
  const { t, fmt, aud, date } = useI18n();
  const minShares = Number(o.price_aud) > 0 ? Number(o.min_raise_aud) / Number(o.price_aud) : 0;
  const minAt = o.shares_offered ? Math.min(100, (minShares / o.shares_offered) * 100) : 0;
  const closed = o.status !== "open";
  return (
    <div className="stack" style={{ gap: 8 }}>
      <div className="between"><b>{t("of.pr.reserved", { n: fmt(p.reserved_shares), N: fmt(o.shares_offered) })}</b><span className="muted-sm">{aud(p.reserved_aud, 2)}</span></div>
      <div className="of-bar" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(p.pct_of_offer)} aria-label={t("of.pr.reserved", { n: fmt(p.reserved_shares), N: fmt(o.shares_offered) })}>
        <i style={{ width: `${Math.min(100, p.pct_of_offer)}%` }} />
        {minAt > 0 && minAt < 100 && <b style={{ left: `${minAt}%` }} aria-hidden="true" />}
      </div>
      <div className="of-meta">
        <span>{p.min_reached ? t("of.pr.minok") : t("of.pr.min", { m: aud(Number(o.min_raise_aud), 2), p: fmt(Math.min(p.pct_of_min, 100), 0) + "%" })}</span>
        <span>{t("of.pr.investors", { n: fmt(p.investors) })}</span>
        {!closed && <span>{t("of.pr.left", { n: fmt(p.remaining_shares) })}</span>}
        <span>{closed && o.closed_at ? t("of.pr.closed", { d: date(o.closed_at) }) : t("of.pr.closes", { d: date(o.closes_at, true) })}</span>
      </div>
    </div>
  );
}

/* ---------- information pack ---------- */
export function PackView({ pack, hash, frozenAt }: { pack: OfferingPack; hash?: string | null; frozenAt?: string | null }) {
  const { t, fmt, aud, money, date, pct } = useI18n();
  const tm = pack.terms;
  const v = pack.valuation;
  const cap = pack.cap_table;
  const vs = tm.price_vs_mark_pct;
  return (
    <div className="stack">
      <p className="muted-sm">{hash ? t("of.pack.frozen", { d: frozenAt ? date(frozenAt) : "–", h: hash.slice(0, 12) + "…" }) : t("of.pack.preview")}</p>
      {pack.notices.length > 0 && (
        <div className="pane">
          <h4>{t("of.p.notices")}</h4>
          <ul className="of-risks">{pack.notices.map((n) => <li key={n}>{t(("of.n." + n) as DictKey)}</li>)}</ul>
        </div>
      )}
      <div className="cols">
        <section className="pane">
          <h4>{t("of.p.terms")}</h4>
          <dl className="of-dl">
            <dt>{t("of.p.price")}</dt><dd>{aud(tm.price_aud, tm.price_aud < 10 ? 4 : 2)}</dd>
            <dt>{t("of.p.offered")}</dt><dd>{fmt(tm.shares_offered)}</dd>
            <dt>{t("of.p.maxraise")}</dt><dd>{aud(tm.max_raise_aud, 2)}</dd>
            <dt>{t("of.p.min")}</dt><dd>{aud(tm.min_raise_aud, 2)}</dd>
            <dt>{t("of.p.per")}</dt><dd>{fmt(tm.max_per_investor_shares)}</dd>
            <dt>{t("of.p.closes")}</dt><dd>{date(tm.closes_at, true)}</dd>
            <dt>{t("of.p.cool")}</dt><dd>{t("of.p.coolV", { n: tm.cooling_off_days })}</dd>
          </dl>
          {vs != null && <span className="muted-sm">{t("of.p.vsmark", { p: (vs > 0 ? "+" : "") + pct(vs, 1) })}</span>}
        </section>
        <section className="pane">
          <h4>{t("of.p.val")}</h4>
          <p style={{ margin: 0 }}>{t("of.p.valP", { v: money(v.value_aud), p: aud(v.price_aud, 4) })}</p>
          {v.low_aud != null && v.high_aud != null && <span>{t("of.p.range", { lo: money(v.low_aud), hi: money(v.high_aud) })}</span>}
          {v.confidence && <span>{t("of.p.conf", { c: t(("of.p.conf." + v.confidence) as DictKey) })}</span>}
          <div className="row">
            {v.grade && <span className="gchip" style={{ background: `var(${GRADE_C[v.grade] ?? "--c6"})` }}>{v.grade}</span>}
            {v.valuation_id && <Link className="btn ghost sm" to={`/v/${encodeURIComponent(v.valuation_id)}/report`}>{t("of.p.report")}</Link>}
            <Link className="btn ghost sm" to={`/verify/${pack.company.ticker}`}>{t("of.p.check")}</Link>
          </div>
        </section>
      </div>
      <section className="pane">
        <h4>{t("of.p.upd")}</h4>
        {pack.updates.length === 0 ? <span className="muted">{t("of.p.noupd")}</span> : (
          <ul className="of-upd">
            {pack.updates.map((u) => (
              <li key={u.id}>
                <Link to={`/i/u/${encodeURIComponent(u.id)}`}><b>{u.title || u.period_label}</b></Link>
                <span className="muted-sm">{u.period_label}{u.published_at ? " · " + date(u.published_at) : ""}</span>
                {u.summary && <span className="muted">{u.summary}</span>}
              </li>
            ))}
          </ul>
        )}
      </section>
      <section className="pane">
        <h4>{t("of.p.cap")}</h4>
        <div className="cols">
          {([["of.p.before", cap.before], ["of.p.after", cap.after]] as const).map(([k, side]) => (
            <div key={k} className="stack" style={{ gap: 6 }}>
              <b>{t(k)}</b>
              <span className="muted-sm">{t("of.p.total", { n: fmt(side.total_shares) })}{"holders" in side ? " · " + t("of.p.holders", { n: fmt(side.holders) }) : ""}</span>
              <div className="tbl">
                <table>
                  <tbody>
                    {side.top.map((h, i) => <tr key={i}><td>{h.name || "–"}</td><td className="r">{fmt(h.shares)}</td><td className="r">{fmt(h.pct, 2)}%</td></tr>)}
                    {"new_shares" in side && <tr><td><b>{t("of.p.offered")}</b></td><td className="r"><b>{fmt(side.new_shares)}</b></td><td className="r"><b>{fmt(side.new_pct, 2)}%</b></td></tr>}
                  </tbody>
                </table>
              </div>
            </div>
          ))}
        </div>
        <span className="muted-sm">{t("of.p.newpct", { p: fmt(cap.after.new_pct, 2) + "%" })}</span>
      </section>
      <section className="pane">
        <h4>{t("of.p.use")}</h4>
        <p style={{ margin: 0, whiteSpace: "pre-wrap" }}>{tm.use_of_funds || t("of.p.nouse")}</p>
      </section>
      <section className="pane" id="risks">
        <h4>{t("of.p.risks")}</h4>
        <ul className="of-risks">{pack.risks.map((r) => <li key={r}>{t(("of.risk." + r) as DictKey)}</li>)}</ul>
      </section>
    </div>
  );
}

/* ---------- company workspace ---------- */
const toLocalInput = (iso: string) => {
  const d = new Date(iso);
  if (!Number.isFinite(d.getTime())) return "";
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`;
};

function TermsForm({ v, onSaved, onCancel }: { v: CompanyOfferingView; onSaved: (x: CompanyOfferingView) => void; onCancel?: () => void }) {
  const { t, fmt, aud, date } = useI18n();
  const o = v.offering;
  const [price, setPrice] = useState(String(o?.price_aud ?? v.defaults.price_aud));
  const [shares, setShares] = useState(String(o?.shares_offered ?? Math.max(1, Math.round(v.defaults.total_shares * 0.1))));
  const [min, setMin] = useState(String(o?.min_raise_aud ?? ""));
  const [per, setPer] = useState(String(o?.max_per_investor_shares ?? ""));
  const [closes, setCloses] = useState(o ? toLocalInput(o.closes_at) : toLocalInput(new Date(Date.now() + 14 * 864e5).toISOString()));
  const [holders, setHolders] = useState(o?.max_holders != null ? String(o.max_holders) : "");
  const [use, setUse] = useState(o?.use_of_funds ?? "");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  // the API's checks, repeated where each value is typed (studio/offerings.py check_terms)
  const cap = v.defaults.max_holders;             // the share token's own cap on BlockID Chain (null = no limit)
  const maxDays = v.defaults.max_days_open ?? 180;
  const pr = readNumber(price);
  const priceN = pr.kind === "ok" ? pr.n : NaN;
  const priceErr: DictKey | null = pr.kind !== "ok" || pr.n <= 0 || pr.n > 1_000_000 ? "fx2.of.price" : null;
  const sharesN = readWhole(shares);
  const sharesErr: DictKey | null = sharesN == null || sharesN < 1 || sharesN > 1e12 ? "fx2.of.whole" : null;
  const worth = !priceErr && !sharesErr ? Math.round(priceN * (sharesN as number) * 100) / 100 : NaN;
  const mr = readNumber(min);
  const minN = mr.kind === "empty" ? 0 : mr.kind === "ok" ? mr.n : NaN;
  const minErr: DictKey | null = !Number.isFinite(minN) || minN < 0 ? "fx2.of.amount" : Number.isFinite(worth) && minN > worth ? "fx2.of.minOver" : null;
  const perN = per.trim() ? readWhole(per) : sharesN;
  const perErr: DictKey | null = perN == null || perN < 1 ? "fx2.of.whole" : sharesN != null && perN > sharesN ? "fx2.of.perOver" : null;
  const closeAt = new Date(closes);
  const closeMs = closeAt.getTime();
  const closeErr: DictKey | null = !Number.isFinite(closeMs) ? "fx2.of.closeBad" : closeMs <= Date.now() + 5 * 60e3 ? "fx2.of.closeSoon"
    : closeMs > Date.now() + maxDays * 864e5 ? "fx2.of.closeFar" : null;
  const holdersN = holders.trim() ? readWhole(holders) : null;
  const holdersErr: DictKey | null = !holders.trim() ? null : holdersN == null || holdersN < 1 ? "fx2.of.whole"
    : holdersN < v.defaults.holders ? "fx2.of.holdersLow" : cap != null && holdersN > cap ? "fx2.of.holdersHigh" : null;
  const ok = !priceErr && !sharesErr && !minErr && !perErr && !closeErr && !holdersErr;
  const body: OfferingTerms = {
    price_aud: priceN, shares_offered: sharesN ?? 0, min_raise_aud: Number.isFinite(minN) ? minN : 0,
    max_per_investor_shares: perN ?? 0, closes_at: Number.isFinite(closeMs) ? closeAt.toISOString() : "",
    use_of_funds: use.trim(), max_holders: holdersN,
  };
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!ok) { setErr(t("fx2.fix")); return; }
    setBusy(true); setErr("");
    try { onSaved(await api.saveOffering(v.ticker, body)); } catch (x) { setErr(errText(x, t)); } finally { setBusy(false); }
  };
  const fe = (k: DictKey | null, vars?: Record<string, string | number>) => (k ? <span className="err">{t(k, vars)}</span> : null);
  const vars = { a: Number.isFinite(worth) ? aud(worth, 2) : "–", n: fmt(sharesN ?? 0), d: maxDays, h: fmt(v.defaults.holders), c: cap != null ? fmt(cap) : "–" };
  return (
    <form className="stack" onSubmit={submit} noValidate>
      <div className="fgrid">
        <label className="lf"><span>{t("of.f.price")}</span><input type="text" inputMode="decimal" value={price} aria-invalid={!!priceErr || undefined} onChange={(e) => setPrice(e.target.value)} />{fe(priceErr) ?? <span className="muted-sm">{t("of.f.priceHint", { p: aud(v.defaults.price_aud, 4) })}</span>}<OfferFinalNote final={(v.defaults as { final?: unknown }).final} /></label>
        <label className="lf"><span>{t("of.f.shares")}</span><input type="text" inputMode="numeric" value={shares} aria-invalid={!!sharesErr || undefined} onChange={(e) => setShares(e.target.value)} />{fe(sharesErr) ?? <span className="muted-sm">{t("of.f.sharesHint", { n: fmt(v.defaults.total_shares) })}</span>}</label>
        <label className="lf"><span>{t("of.f.min")}</span><input type="text" inputMode="decimal" value={min} placeholder="0" aria-invalid={!!minErr || undefined} onChange={(e) => setMin(e.target.value)} />{fe(minErr, vars) ?? <span className="muted-sm">{t("of.f.minHint")}</span>}</label>
        <label className="lf"><span>{t("of.f.max")}</span><input type="text" inputMode="numeric" value={per} placeholder={shares} aria-invalid={!!perErr || undefined} onChange={(e) => setPer(e.target.value)} />{fe(perErr, vars)}</label>
        <label className="lf"><span>{t("of.f.close")}</span><input type="datetime-local" value={closes} aria-invalid={!!closeErr || undefined} onChange={(e) => setCloses(e.target.value)} />{fe(closeErr, vars)}</label>
        <label className="lf"><span>{t("of.f.holders")}</span><input type="text" inputMode="numeric" value={holders} placeholder={cap != null ? String(cap) : ""} aria-invalid={!!holdersErr || undefined} onChange={(e) => setHolders(e.target.value)} />{fe(holdersErr, vars) ?? <span className="muted-sm">{cap != null ? t("of.f.holdersHint", { n: fmt(cap), h: fmt(v.defaults.holders) }) : t("fx2.of.holdersNoCap", { h: fmt(v.defaults.holders) })}</span>}</label>
      </div>
      <label className="lf"><span>{t("of.f.use")}</span><textarea value={use} maxLength={2000} placeholder={t("of.f.usePh")} onChange={(e) => setUse(e.target.value)} /></label>
      {ok && <div className="pane"><b>{t("of.sum", { n: fmt(body.shares_offered), p: aud(body.price_aud, body.price_aud < 10 ? 4 : 2), max: aud(body.shares_offered * body.price_aud, 2), min: aud(body.min_raise_aud, 2), per: fmt(body.max_per_investor_shares), d: date(body.closes_at, true) })}</b></div>}
      <div className="row" style={{ gap: 8 }}>
        <button className="btn" type="submit" disabled={busy || !ok}>{t("of.save")}</button>
        {onCancel && <button className="btn ghost" type="button" onClick={onCancel}>{t("of.keep")}</button>}
      </div>
      {err && <p className="err" role="alert">{err}</p>}
    </form>
  );
}

function ReservationTable({ rows }: { rows: Reservation[] }) {
  const { t, fmt, aud, date } = useI18n();
  if (!rows.length) return <span className="muted">{t("of.res.empty")}</span>;
  return (
    <div className="tbl">
      <table>
        <thead><tr><th>{t("of.res.who")}</th><th className="r">{t("of.res.shares")}</th><th className="r">{t("of.res.amount")}</th><th>{t("of.res.status")}</th><th>{t("of.res.date")}</th></tr></thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.id}>
              <td>{r.name} <span className="mono muted-sm" title={r.wallet}>{shortAddr(r.wallet)}</span></td>
              <td className="r">{fmt(r.shares)}</td><td className="r">{aud(r.amount_aud, 2)}</td>
              <td><ResPill s={r.status} /></td><td>{date(r.created_at, true)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function CompanyOffering({ ticker }: { ticker: string }) {
  const { t, fmt, date } = useI18n();
  const { me } = useAuth();
  const [poll, setPoll] = useState<number>(20000);
  const q = useAsync<CompanyOfferingView>(() => api.companyOffering(ticker), [ticker], poll);
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; s: string } | null>(null);
  const [local, setLocal] = useState<CompanyOfferingView | null>(null);
  useEffect(() => { setLocal(null); }, [q.data]);  // a fresh server view replaces the one an action returned
  const v = local ?? q.data;
  useEffect(() => { setPoll(v?.offering?.status === "settling" ? 4000 : 20000); }, [v?.offering?.status]);
  if (q.loading && !v) return <Loading />;
  if (!v) return <ErrorBox error={q.error} retry={q.reload} />;
  const o = v.offering;
  const set = (x: CompanyOfferingView, s: DictKey) => { setLocal(x); setEditing(false); setMsg({ ok: true, s: t(s) }); };
  const act = async (a: "submit" | "cancel" | "close", okMsg: DictKey) => {
    if (a === "close" && !window.confirm(t("of.closeConfirm"))) return;
    setBusy(true); setMsg(null);
    try { set(await api.offeringAction(ticker, a), okMsg); } catch (x) { setMsg({ ok: false, s: errText(x, t) }); } finally { setBusy(false); }
  };
  const showForm = v.live && (!o || editing || o.status === "draft");
  const tone: Tone = o ? TONE[o.status] : "idle";
  let next: StatusNext | null = null;
  if (o?.status === "pending_approval" && me?.role !== "admin") next = { label: t("of.approveLink"), to: demoApproveLink(`/admin/offerings/${o.id}`, `/c/${ticker}/offering`) };
  else if (o?.status === "pending_approval" || o?.status === "awaiting_settlement" || o?.status === "failed") next = { label: t("of.approveLink"), to: `/admin/offerings/${o.id}?return=${encodeURIComponent(`/c/${ticker}/offering`)}` };
  else if (o?.status === "open") next = { label: t("of.i.see"), to: `/i/offerings/${o.id}` };
  const note = !o ? null : o.status === "open" ? t("of.openNote", { d: date(o.closes_at, true) }) : o.status === "pending_approval" ? t("of.wait")
    : o.status === "awaiting_settlement" ? t("of.awaitNote") : o.status === "settling" ? t("of.settlingNote") : o.status === "failed" ? t("of.failedNote") : null;
  return (
    <div className="stack">
      <StatusBar status={o ? t(("of.st." + o.status) as DictKey) : t("of.st.none")} tone={tone} since={o?.status === "settling" ? o.settle_approved_at ?? null : null}
        meta={o && v.progress && o.status !== "draft" && o.status !== "rejected" && o.status !== "pending_approval" ? t("of.sb.meta", { n: fmt(v.progress.reserved_shares), N: fmt(o.shares_offered), d: date(o.closes_at) }) : t("of.sim")}
        next={next} />
      {msg && <p className={msg.ok ? "toast" : "err"} role={msg.ok ? "status" : "alert"}>{msg.s}</p>}
      {!v.live && <p className="quietline">{t("of.onlylive")}</p>}
      {o?.status === "rejected" && <p className="quietline bad" role="note">{t("of.rejected", { r: o.reason || "–" })}</p>}
      {note && <p className="quietline">{note}</p>}

      {v.live && (
        <section className="card solid">
          <div className="between"><h4 style={{ margin: 0 }}>{t("of.c.h")}</h4>{o && <OfferingPill s={o.status} />}</div>
          <p className="sub">{t("of.c.p")}</p>
          {!o && <span className="muted-sm">{t("of.none")}</span>}
          {showForm ? <TermsForm key={o?.id ?? "new"} v={v} onSaved={(x) => set(x, "of.saved")} onCancel={editing ? () => setEditing(false) : undefined} /> : null}
          <div className="row" style={{ gap: 8 }}>
            {o && (o.status === "draft" || o.status === "rejected") && !editing && <button className="btn gold" type="button" disabled={busy} onClick={() => act("submit", "of.submitted")}>{t("of.submit")}</button>}
            {o?.status === "rejected" && !editing && <button className="btn ghost" type="button" onClick={() => setEditing(true)}>{t("of.edit")}</button>}
            {o && (o.status === "draft" || o.status === "rejected" || o.status === "pending_approval") && <button className="btn ghost sm" type="button" disabled={busy} onClick={() => act("cancel", "of.cancelled")}>{t("of.cancel")}</button>}
            {o?.status === "open" && <button className="btn ghost" type="button" disabled={busy} onClick={() => act("close", "of.closedMsg")}>{t("of.close")}</button>}
          </div>
        </section>
      )}

      {o && v.progress && o.status !== "draft" && o.status !== "rejected" && o.status !== "pending_approval" && (
        <section className="card solid"><ProgressView o={o} p={v.progress} /></section>
      )}
      {o && v.pack && (
        <section className="card solid">
          <h4>{t("of.pack.h")}</h4>
          <p className="sub">{t("of.pack.p")}</p>
          <PackView pack={v.pack} hash={o.status === "draft" || o.status === "rejected" ? null : o.pack_hash} frozenAt={o.submitted_at} />
        </section>
      )}
      {o && o.status !== "draft" && o.status !== "rejected" && o.status !== "pending_approval" && (
        <section className="card solid"><h4>{t("of.res.h")}</h4><ReservationTable rows={v.reservations} /></section>
      )}
      {v.history.length > 0 && (
        <section className="card">
          <h4>{t("of.hist.h")}</h4>
          <ul className="of-upd">
            {v.history.map((h) => (
              <li key={h.id}>
                <span className="row"><OfferingPill s={h.status} /><b>{t("of.pr.reserved", { n: fmt(h.progress.reserved_shares), N: fmt(h.shares_offered) })}</b></span>
                <span className="muted-sm">{h.closed_at ? t("of.pr.closed", { d: date(h.closed_at) }) : date(h.created_at ?? h.closes_at)}</span>
              </li>
            ))}
          </ul>
        </section>
      )}
      <p className="muted-sm">{t("of.legal")}</p>
    </div>
  );
}

/* ---------- investor: list ---------- */
function OfferingCard({ o }: { o: Offering }) {
  const { t, aud } = useI18n();
  return (
    <Link className="card solid inv-card" to={`/i/offerings/${o.id}`}>
      <div className="between">
        <span><b className="mono">{o.ticker}</b> · {o.company_name}</span>
        {o.grade && <span className="gchip" style={{ background: `var(${GRADE_C[o.grade] ?? "--c6"})` }}>{o.grade}</span>}
      </div>
      <div className="row"><OfferingPill s={o.status} /><span className="muted-sm">{aud(Number(o.price_aud), Number(o.price_aud) < 10 ? 4 : 2)} / {t("t.shares").toLowerCase()}</span></div>
      {o.progress && <ProgressView o={o} p={o.progress} />}
      <span className="muted-sm">{t("of.i.see")} →</span>
    </Link>
  );
}

export function OfferingsList() {
  const { t } = useI18n();
  useTitle(t("of.i.h"));
  const q = useAsync(() => api.offerings(), [], 30000);
  if (q.loading && !q.data) return <Loading />;
  if (!q.data) return <div className="wrap page"><ErrorBox error={q.error} retry={q.reload} /></div>;
  const open = q.data.offerings.filter((o) => o.status === "open");
  const past = q.data.offerings.filter((o) => o.status !== "open");
  return (
    <div className="wrap page inv">
      <div className="head">
        <span className="eyebrow">{t("in.eyebrow")}</span>
        <h2>{t("of.i.h")}</h2>
        <p>{t("of.i.p")}</p>
      </div>
      <StatusBar status={t("of.i.open")} tone={open.length ? "ok" : "idle"} meta={`${open.length} · ${t("of.sim")}`} next={{ label: t("in.title"), to: "/i" }} />
      {open.length === 0 ? <p className="empty">{t("of.i.empty")}</p> : <div className="inv-list">{open.map((o) => <OfferingCard key={o.id} o={o} />)}</div>}
      {past.length > 0 && (
        <>
          <h3 style={{ fontSize: "1.1rem", marginTop: 12 }}>{t("of.i.past")}</h3>
          <div className="inv-list">{past.map((o) => <OfferingCard key={o.id} o={o} />)}</div>
        </>
      )}
      <p className="muted-sm">{t("of.legal")}</p>
    </div>
  );
}

/* ---------- investor: one offering ---------- */
function ReserveForm({ o, onDone }: { o: Offering; onDone: (msg: string) => void }) {
  const { t, fmt, aud, date } = useI18n();
  const [mode, setMode] = useState<"shares" | "aud">("shares");
  const [val, setVal] = useState("");
  const [ack, setAck] = useState(false);
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const price = Number(o.price_aud);
  const room = Math.max(0, Math.min(o.max_per_investor_shares - (o.mine_reserved_shares ?? 0), o.progress?.remaining_shares ?? o.shares_offered));
  // whole shares only, at most what is left for this investor, worth at least A$0.01 (the API checks the same)
  const typed = readNumber(val);
  const n = typed.kind === "ok" ? typed.n : NaN;
  const shares = mode === "shares" ? (typed.kind === "ok" && typed.dp === 0 ? n : NaN) : Math.floor(n / price);
  const minShares = price > 0 ? Math.max(1, Math.ceil(0.005 / price - 1e-9)) : 1;
  const fieldErr: string | null = typed.kind === "empty" ? null
    : typed.kind === "bad" || n <= 0 ? t("of.d.need")
    : mode === "shares" && typed.dp > 0 ? t("fx2.of.wholeShares")
    : !(shares >= 1) ? t("of.d.need")
    : shares > room ? t("fx2.of.overRoom", { n: fmt(room) })
    : Math.round(shares * price * 100) / 100 < 0.01 ? t("fx2.of.minCent", { n: fmt(minShares) }) : null;
  const valid = typed.kind === "ok" && !fieldErr;
  if (room <= 0) return <p className="quietline">{(o.progress?.remaining_shares ?? 1) <= 0 ? t("of.d.soldout") : t("of.d.full")}</p>;
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!valid) { setErr(fieldErr ?? t("of.d.need")); return; }
    setBusy(true); setErr("");
    try {
      const r = await api.reserve(o.id, { ...(mode === "shares" ? { shares } : { amount_aud: n }), risk_ack: ack, ...(name.trim() ? { name: name.trim() } : {}) });
      setVal("");
      onDone(t("of.d.done", { d: date(r.reservation.cooling_off_until, true) }));
    } catch (x) { setErr(errText(x, t)); } finally { setBusy(false); }
  };
  return (
    <form className="stack" onSubmit={submit} noValidate>
      <div className="segs" role="tablist" aria-label={t("of.d.by")}>
        {(["shares", "aud"] as const).map((m) => <button key={m} type="button" role="tab" aria-selected={mode === m} onClick={() => { setMode(m); setVal(""); }}>{t(m === "shares" ? "of.d.byShares" : "of.d.byAud")}</button>)}
      </div>
      <div className="fgrid">
        <label className="lf"><span>{t(mode === "shares" ? "of.d.byShares" : "of.d.byAud")}</span>
          <input type="text" inputMode={mode === "shares" ? "numeric" : "decimal"} value={val} aria-invalid={!!fieldErr || undefined} onChange={(e) => { setVal(e.target.value); setErr(""); }} />
          {fieldErr ? <span className="err">{fieldErr}</span>
            : <span className="muted-sm">{valid ? t("of.d.eq", { n: fmt(shares), a: aud(shares * price, 2) }) + " · " + t("fx2.of.canAdd", { n: fmt(room - shares) }) : t("of.d.room", { n: fmt(room) })}</span>}
        </label>
        <label className="lf"><span>{t("of.d.name")}</span><input value={name} maxLength={120} onChange={(e) => setName(e.target.value)} /></label>
      </div>
      <label className="of-ack"><input type="checkbox" checked={ack} onChange={(e) => setAck(e.target.checked)} /><span>{t("of.d.ack")} (<a href="#risks">{t("of.p.risks").toLowerCase()}</a>)</span></label>
      <div className="row"><button className="btn" type="submit" disabled={busy || !ack || !valid}>{t("of.d.btn")}</button><span className="muted-sm">{t("of.sim")}</span></div>
      {err && <p className="err" role="alert">{err}</p>}
    </form>
  );
}

function MineList({ o, rows, onChanged }: { o: Offering; rows: Reservation[]; onChanged: (msg: string) => void }) {
  const { t, fmt, aud, date } = useI18n();
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  if (!rows.length) return null;
  return (
    <section className="card solid">
      <h4>{t("of.d.mine")}</h4>
      <ul className="of-upd">
        {rows.map((r) => (
          <li key={r.id} className="between">
            <span className="row"><ResPill s={r.status} /><b>{fmt(r.shares)}</b> · {aud(r.amount_aud, 2)} <span className="muted-sm">{date(r.created_at, true)}</span></span>
            {r.status === "reserved" && (r.can_withdraw ? (
              <span className="row"><span className="muted-sm">{t("of.d.until", { d: date(r.cooling_off_until, true) })}</span>
                <button className="btn ghost sm" type="button" disabled={busy} onClick={async () => { setBusy(true); setErr(""); try { await api.withdrawReservation(o.id, r.id); onChanged(t("of.d.withdrawn")); } catch (x) { setErr(errText(x, t)); } finally { setBusy(false); } }}>{t("of.d.withdraw")}</button></span>
            ) : <span className="muted-sm">{t("of.d.firm")}</span>)}
          </li>
        ))}
      </ul>
      {err && <p className="err" role="alert">{err}</p>}
    </section>
  );
}

export function OfferingDetail({ id }: { id: string }) {
  const { t, fmt, date } = useI18n();
  const { me } = useAuth();
  const q = useAsync<Offering>(() => api.offering(id), [id, me?.address], 20000);
  const [msg, setMsg] = useState("");
  useTitle(q.data ? `${q.data.ticker} · ${t("of.i.h")}` : t("of.i.h"));
  if (q.loading && !q.data) return <Loading />;
  if (!q.data) {
    const missing = q.error instanceof ApiError && (q.error.status === 404 || q.error.status === 422);
    return (
      <div className="wrap page inv">
        {missing ? (
          <div className="stack">
            <p className="empty">{t("fx2.of.missing")}</p>
            <Link className="btn" to="/i/offerings" style={{ justifySelf: "start" }}>{t("fx2.of.seeAll")}</Link>
          </div>
        ) : <><ErrorBox error={q.error} retry={q.reload} /><Link className="btn ghost" to="/i/offerings">{t("of.i.back")}</Link></>}
      </div>
    );
  }
  const o = q.data;
  const p = o.progress;
  const open = o.status === "open" && Date.parse(o.closes_at) > Date.now();
  const changed = (m: string) => { setMsg(m); void q.reload(); };
  return (
    <div className="wrap page inv">
      <nav className="crumbs" aria-label={t("in.crumbs")}><Link to="/i/offerings">{t("of.i.back")}</Link> / <span>{o.ticker}</span></nav>
      <div className="head">
        <span className="eyebrow">{t("of.i.h")}</span>
        <h2>{o.company_name}</h2>
        <p>{t("of.sum", { n: fmt(o.shares_offered), p: "A$" + fmt(Number(o.price_aud), Number(o.price_aud) < 10 ? 4 : 2), max: "A$" + fmt(o.max_raise_aud, 2), min: "A$" + fmt(Number(o.min_raise_aud), 2), per: fmt(o.max_per_investor_shares), d: date(o.closes_at, true) })}</p>
      </div>
      <StatusBar status={t(("of.st." + o.status) as DictKey)} tone={TONE[o.status]}
        meta={p ? t("of.sb.meta", { n: fmt(p.reserved_shares), N: fmt(o.shares_offered), d: date(o.closes_at) }) : null}
        next={open && me?.address ? { label: t("of.d.reserve"), onClick: () => document.getElementById("reserve")?.scrollIntoView({ behavior: "smooth" }) } : { label: t("in.pos.profile"), to: `/c/${o.ticker}/overview` }} />
      <SimChip />
      {!["open", "awaiting_settlement", "settling", "settled", "released", "failed"].includes(o.status) && <p className="quietline">{t("of.d.private")}</p>}
      {msg && <p className="toast" role="status">{msg}</p>}
      {p && <section className="card solid"><ProgressView o={o} p={p} /><span className="muted-sm">{t("of.d.how")}</span></section>}
      <MineList o={o} rows={o.mine ?? []} onChanged={changed} />
      {o.pack && <section className="card"><h4>{t("of.pack.h")}</h4><PackView pack={o.pack} hash={o.pack_hash} frozenAt={o.submitted_at} /></section>}
      <section className="card solid" id="reserve">
        <h4>{t("of.d.reserve")}</h4>
        <p className="sub">{t("of.d.p")} {t("of.d.cool", { n: o.cooling_off_days })}</p>
        {!open ? <p className="quietline">{t("of.d.closed")}</p> : !me?.address ? (
          <><p className="quietline">{t("of.d.signin")}</p><SignInCard /></>
        ) : <ReserveForm o={o} onDone={changed} />}
      </section>
      <p className="muted-sm">{t("of.legal")}</p>
    </div>
  );
}

/* ---------- portfolio card ---------- */
export function MyReservations() {
  const { t, fmt, aud, date } = useI18n();
  const q = useAsync(() => api.myReservations(), [], 60000);
  const rows = q.data?.reservations ?? [];
  return (
    <section className="card solid">
      <div className="between"><h4 style={{ margin: 0 }}>{t("of.pf.h")}</h4><Link className="btn ghost sm" to="/i/offerings">{t("of.pf.all")}</Link></div>
      <p className="sub">{t("of.pf.p")}</p>
      {rows.length === 0 ? <span className="muted">{q.loading ? t("common.loading") : t("of.pf.none")}</span> : (
        <ul className="of-upd">
          {rows.map((r) => (
            <li key={r.id} className="between">
              <span className="row"><ResPill s={r.status} /><Link to={`/i/offerings/${r.offering_id}`}><b className="mono">{r.ticker}</b> · {r.company_name}</Link></span>
              <span className="row muted-sm"><b>{fmt(r.shares)}</b> · {aud(r.amount_aud, 2)} · {r.offering_status ? t(("of.st." + r.offering_status) as DictKey) : ""}{r.status === "reserved" && r.can_withdraw ? " · " + t("of.d.until", { d: date(r.cooling_off_until) }) : ""}</span>
            </li>
          ))}
        </ul>
      )}
      <span className="muted-sm">{t("of.sim")}</span>
    </section>
  );
}

/* ---------- admin queue ---------- */
type Act = (fn: () => Promise<unknown>, okMsg?: string) => Promise<void>;
export function OfferingQueueItem({ o, busy, act }: { o: Offering; busy: boolean; act: Act }) {
  const { t, fmt, date } = useI18n();
  const [reason, setReason] = useState("");
  const toOpen = o.status === "pending_approval";
  const reg = o.register;
  return (
    <div className="pane">
      <div className="between">
        <span><b className="mono">{o.ticker}</b> · {o.company_name} <span className="muted-sm">{o.created_by ? "· " + t("ap.req", { w: shortAddr(o.created_by) || o.created_by }) : ""}{o.updated_at ? " · " + date(o.updated_at, true) : ""}</span></span>
        <span className="row" style={{ gap: 8 }}><OfferingPill s={o.status} />{o.ticker && <Link className="btn ghost sm" to={`/c/${o.ticker}/offering`}>{t("ad.co.open")}</Link>}</span>
      </div>
      {o.status === "failed" && o.error && <p className="quietline bad">{t("of.ad.failed", { e: o.error })}</p>}
      <p className="note">{t(toOpen ? "of.ad.open.p" : "of.ad.settle.p")}</p>
      {o.progress && !toOpen && <><ProgressView o={o} p={o.progress} /><b>{t("of.ad.alloc", { n: fmt(o.progress.reserved_shares), k: fmt(o.progress.investors) })}</b></>}
      {o.pack && toOpen && <PackView pack={o.pack} hash={o.pack_hash} frozenAt={o.submitted_at} />}
      {toOpen && <label className="lf"><span>{t("of.ad.reason")}</span><input value={reason} maxLength={1000} onChange={(e) => setReason(e.target.value)} /></label>}
      <div className="row">
        <span className="grow" />
        {toOpen ? (
          <>
            <button className="btn danger sm" type="button" disabled={busy} onClick={() => act(() => api.rejectOffering(o.id, reason.trim() || "sent back by admin"), t("of.ad.rejected"))}>{t("of.ad.reject")}</button>
            <button className="btn gold" type="button" disabled={busy} onClick={() => act(() => api.approveOffering(o.id), t("of.ad.opened"))}>{t("of.ad.approve")}</button>
          </>
        ) : (
          <>
            {reg ? <span className={"muted-sm" + (reg.fits ? "" : " err")} role={reg.fits ? undefined : "alert"}>
              {reg.cap != null ? t("fx2.of.reg", { n: fmt(reg.count), c: fmt(reg.cap), a: fmt(reg.after) }) : t("fx2.of.regNoCap", { n: fmt(reg.count), a: fmt(reg.after) })}
              {!reg.fits && " " + t("fx2.of.regOver")}</span>
              : o.register === null ? <span className="muted-sm">{t("fx2.of.regUnknown")}</span> : null}
            <button className="btn danger sm" type="button" disabled={busy} onClick={() => act(() => api.releaseOffering(o.id, "released by admin"), t("of.ad.released"))}>{t(o.status === "failed" ? "fx2.of.releaseRest" : "of.ad.release")}</button>
            <button className="btn gold" type="button" disabled={busy || (reg ? !reg.fits : false)} onClick={() => act(() => api.settleOffering(o.id), t("of.ad.settling"))}>{t("of.ad.settle")}</button>
          </>
        )}
      </div>
    </div>
  );
}
