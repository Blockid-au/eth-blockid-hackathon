import { useEffect, useRef, useState } from "react";
import { Link, useLocation, useNavigate, useParams } from "react-router-dom";
import { useI18n } from "../i18n";
import { errText, useAuth } from "../auth";
import { api, ApiError, type CapRow, type CoEvent, type CoStatus, type CompanyDetail, type SyncInfo } from "../api";
import { isSyncFailure, resolvedFailures } from "../lib/events";
import { Bars100, Donut, HBars, Legend } from "../components/charts";
import { MarkPanel } from "../components/MarkPanel";
import { AddrCard, ManualSteps, NetworkDetails } from "../components/AddrCard";
import { ErrorBox, Loading } from "../components/Layout";
import { useAsync, useTitle } from "../lib/hooks";
import { colorAt, foldParts, GRADE_C } from "../lib/math";
import { readNumber } from "../lib/typed";
import { CHAINS, chainOf, isAddressValid, shortAddr } from "../wallet";
import type { DictKey } from "../dict";
import { Tracker } from "../components/Tracker";
import { TransferPanel } from "./Transfers";
import { DemoApproveGuide, demoApproveLink } from "../components/DemoGuide";
import { StatusBar, type StatusNext, type Tone } from "../components/StatusBar";
import { CompanyAdminsPanel, CompanyApprovals } from "../components/CompanyAdmins";
import { useMyCompanies } from "../lib/companyAdmins";
import { Crumbs, FlowRail, Pager, RailGroup, RailItem, SideLayout, StepHead } from "../components/Shell";
import { CO_SEG, CO_STEP, coGate, coReach, coStep, LIVE, valPath, WS, type WsSection } from "../lib/flow";
import { ErrorFix } from "../components/ErrorFix";
import { CompanyUpdates } from "./Updates";
import { CompanyDividends } from "./Dividends";
import { CompanyOffering } from "./Offerings";
import { OfferingBadge } from "../components/OfferingBadge";
import { TeamTile } from "../components/TeamCard";

const TRANSIENT: CoStatus[] = ["pending_issue", "issuing", "issued", "pending_anchor", "anchoring", "partially_anchored"];
const RUNNING: CoStatus[] = ["issuing", "anchoring"];

/* ---------- status timeline ---------- */
function Timeline({ status }: { status: CoStatus }) {
  const { t } = useI18n();
  const nodes: { k: string; label: DictKey; gate?: boolean }[] = [
    { k: "draft", label: "c.tl.draft" },
    { k: "pending_issue", label: "c.tl.pending_issue" },
    { k: "issuing", label: "c.tl.issuing", gate: true },
    { k: "issued", label: "c.tl.issued" },
    { k: "anchoring", label: "c.tl.anchoring" },
    { k: "anchored", label: "c.tl.anchored" },
  ];
  const pos: Record<string, number> = { draft: 0, pending_issue: 1, issuing: 2, issued: 3, pending_anchor: 3, anchoring: 4, anchored: 5 };
  const bad = status === "failed" || status === "rejected";
  const at = pos[status] ?? 0;
  return (
    <ol className="timeline" style={{ listStyle: "none", margin: 0, padding: 0 }} aria-label={t("trk.h")}>
      {nodes.map((n, i) => {
        const cls = i < at || (i === at && status === "anchored") ? "done" : i === at ? (bad ? "fail" : "cur") : "";
        return (
          <li key={n.k} className={"tl " + cls} aria-current={i === at ? "step" : undefined}>
            {n.gate && <span className="gm" title={t("gate.admin")} aria-hidden="true" />}
            <span className="nd" aria-hidden="true" />
            <span>{t(n.label)}</span>
            {n.gate && <span className="gl">◆ {t("c.gate")}</span>}
          </li>
        );
      })}
    </ol>
  );
}

/* ---------- cap table ---------- */
function CapTable({ rows, ticker, source, block }: { rows: CapRow[]; ticker: string; source?: string; block?: number | null }) {
  const { t, fmt } = useI18n();
  const fix = useLocation().hash === "#fix"; // arrived from an error's "Show the cap table" link
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => { if (fix) box.current?.scrollIntoView({ behavior: "smooth", block: "start" }); }, [fix]);
  const total = rows.reduce((a, r) => a + Number(r.shares), 0);
  const pct = (r: CapRow) => (r.pct != null ? Number(r.pct) : total ? (Number(r.shares) / total) * 100 : 0);
  if (!rows.length) return <p className="empty">{t("c.cap.empty")}</p>;
  return (
    <div className={"cols" + (fix ? " fix-flash" : "")} ref={box}>
      <div className="card solid">
        <h4>{t("c.cap")}</h4>
        <p className="sub">{source === "db" ? t("c.cap.db") : block ? t("c.cap.chain", { b: fmt(block) }) : t("c.cap.p")}</p>
        <div className="tbl">
          <table>
            <thead><tr><th>{t("t.holder")}</th><th>{t("t.wallet")}</th><th className="r">{t("t.shares")}</th><th className="r">%</th></tr></thead>
            <tbody>
              {rows.map((r, i) => (
                <tr key={r.wallet + i}>
                  <td><span className="sw" style={{ background: `var(${colorAt(i)})`, marginRight: 8 }} />{r.name}</td>
                  <td className="mono" style={{ fontSize: ".8rem" }}><a href={CHAINS.local.addrUrl(r.wallet)} target="_blank" rel="noopener noreferrer" title={r.wallet}>{shortAddr(r.wallet)}</a></td>
                  <td className="r">{fmt(Number(r.shares))}</td>
                  <td className="r">{fmt(pct(r), 2)}%</td>
                </tr>
              ))}
            </tbody>
            <tfoot><tr><th>{rows.length}</th><th /><th className="r">{fmt(total)}</th><th className="r">100%</th></tr></tfoot>
          </table>
        </div>
      </div>
      <div className="card solid">
        <h4>{t("s5.preview")}</h4>
        {(() => {
          const fp = foldParts(rows.map((r) => ({ name: r.name, v: Number(r.shares) })), t("c.other"));
          return (
            <>
              <Donut label={t("s5.preview")} center={total >= 1e6 ? fmt(total / 1e6, 1) + "M" : fmt(total)} sub={`${ticker} · ${t("t.shares").toLowerCase()}`}
                parts={fp.map((p) => ({ ...p, tip: `${p.name} · ${fmt(p.pct, 2)}% · ${fmt(p.v)}` }))} />
              <Legend parts={fp} />
            </>
          );
        })()}
      </div>
    </div>
  );
}

/* ---------- mint request with dilution preview ---------- */
function MintForm({ c, onSent }: { c: CompanyDetail; onSent: () => void }) {
  const { t, fmt, aud } = useI18n();
  const [wallet, setWallet] = useState("");
  const [name, setName] = useState("");
  const [shares, setShares] = useState("100000");
  const [reason, setReason] = useState("");
  const [msg, setMsg] = useState<{ ok: boolean; s: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const add = Math.max(0, Math.floor(Number(shares) || 0));
  const w = isAddressValid(wallet);
  const base = c.cap_table.reduce((a, r) => a + Number(r.shares), 0) || c.total_shares;
  const ex = w ? c.cap_table.findIndex((r) => r.wallet.toLowerCase() === w.toLowerCase()) : -1;
  const before = c.cap_table.map((r, i) => ({ name: r.name, v: Number(r.shares), c: colorAt(i) }));
  const after = before.map((p, i) => (i === ex ? { ...p, v: p.v + add } : p));
  if (ex < 0) after.push({ name: name || t("m.investor"), v: add, c: "--c6" });
  const aTot = base + add;
  const mark = c.mark_aud || 1;
  useEffect(() => { if (ex >= 0 && !name) setName(c.cap_table[ex].name); }, [ex]); // eslint-disable-line react-hooks/exhaustive-deps

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!w) { setMsg({ ok: false, s: t("v.sh.badaddr") }); return; }
    if (!name.trim()) { setMsg({ ok: false, s: t("v.sh.badname") }); return; }
    if (add < 1) { setMsg({ ok: false, s: t("m.new") + " ≥ 1" }); return; }
    setBusy(true); setMsg(null);
    try {
      await api.requestMint(c.ticker, { to_wallet: w, holder_name: name.trim(), shares: add, reason: reason.trim() });
      setMsg({ ok: true, s: t("c.mint.sent") });
      onSent();
    } catch (x) {
      setMsg({ ok: false, s: errText(x, t) });
    } finally {
      setBusy(false);
    }
  };
  return (
    <form className="card solid" onSubmit={submit} noValidate>
      <h4>{t("m.h")}</h4>
      <p className="sub">{t("m.p")}</p>
      <div className="fgrid">
        <label className="lf"><span>{t("c.mint.to")}</span><input className={"mono" + (wallet && !w ? " bad" : "")} value={wallet} placeholder="0x…" spellCheck={false} onChange={(e) => setWallet(e.target.value.trim())} onBlur={() => w && setWallet(w)} aria-invalid={!!wallet && !w} /></label>
        <label className="lf"><span>{t("c.mint.name")}</span><input value={name} onChange={(e) => setName(e.target.value)} /></label>
        <label className="lf"><span>{t("m.new")}</span><input type="number" min={1} step={1000} value={shares} onChange={(e) => setShares(e.target.value)} /></label>
        <label className="lf"><span>{t("c.mint.reason")}</span><input value={reason} onChange={(e) => setReason(e.target.value)} /></label>
      </div>
      {wallet && !w && <span className="hint bad">{t("v.sh.badaddr")}</span>}
      {ex >= 0 && <span className="hint">{t("c.mint.existing")}</span>}
      <p className="sub"><b className="num">{fmt(add)}</b> · {aud(add * mark, 0)} @ {aud(mark, 2)}</p>
      <div className="bars100">
        <Bars100 label={t("m.before")} parts={before} />
        <Bars100 label={t("m.after")} parts={after} />
      </div>
      <div className="tbl">
        <table>
          <thead><tr><th>{t("t.holder")}</th><th className="r">{t("m.before")}</th><th className="r">{t("m.after")}</th><th className="r">Δ</th></tr></thead>
          <tbody>
            {after.map((p, i) => {
              const b = i < before.length ? (before[i].v / (base || 1)) * 100 : 0;
              const a = (p.v / (aTot || 1)) * 100, d = a - b;
              return (
                <tr key={i}>
                  <td><span className="sw" style={{ background: `var(${p.c})`, marginRight: 8 }} />{p.name}</td>
                  <td className="r">{i < before.length ? fmt(b, 1) + "%" : "–"}</td>
                  <td className="r">{fmt(a, 1)}%</td>
                  <td className="r"><span className={"chg " + (d > 0.005 ? "up" : d < -0.005 ? "down" : "flat")}>{(d >= 0 ? "+" : "−") + fmt(Math.abs(d), 1)}</span></td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <button className="btn" type="submit" disabled={busy} style={{ justifySelf: "start" }}>{t("m.request")}</button>
      {msg && <p className={msg.ok ? "toast" : "err"} role={msg.ok ? "status" : "alert"}>{msg.s}</p>}
    </form>
  );
}

/* ---------- dividend plan ---------- */
function DividendForm({ c, onSent }: { c: CompanyDetail; onSent: () => void }) {
  const { t, fmt } = useI18n();
  const [amt, setAmt] = useState("50000");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; s: string } | null>(null);
  const [root, setRoot] = useState<string | null>(null);
  // cents allowed; the API refuses more than 6 decimals and tells what rounding leaves with the company
  const typed = readNumber(amt);
  const amtOk = typed.kind === "ok" && typed.n >= 0.01 && typed.dp <= 2 && typed.n <= 1e12;
  const total = amtOk && typed.kind === "ok" ? typed.n : 0;
  const m6 = (n: number) => fmt(n, Math.round(n * 1e6) % 10000 === 0 ? 2 : 6);
  const supply = c.cap_table.reduce((a, r) => a + Number(r.shares), 0) || 1;
  const rows = c.cap_table.map((r, i) => {
    const pay = Math.floor(((total * Number(r.shares)) / supply) * 100) / 100;
    return { name: r.name, value: pay, color: colorAt(i), label: fmt(pay, 2), tip: `${r.name} · ${fmt((Number(r.shares) / supply) * 100, 1)}% · ${fmt(pay, 2)} mAUD` };
  });
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!amtOk) return;
    setBusy(true); setMsg(null);
    try {
      const r = await api.requestDividend(c.ticker, total);
      setRoot(r?.merkle_root ?? null);
      const paid = r?.total_maud ?? total;
      const rest = (r?.remainder_units ?? 0) / 1e6;
      setMsg({ ok: true, s: t("c.div.sent") + " " + (rest > 0 ? t("fx2.div.paidRest", { x: m6(paid), y: m6(rest) }) : t("fx2.div.paid", { x: m6(paid) })) });
      onSent();
    } catch (x) {
      setMsg({ ok: false, s: errText(x, t) });
    } finally {
      setBusy(false);
    }
  };
  return (
    <form className="card solid" onSubmit={submit} noValidate>
      <h4>{t("dv.h")}</h4>
      <p className="sub">{t("dv.p")}</p>
      <div className="field" style={{ alignItems: "center" }}>
        <label htmlFor="div-amt" className="sub">{t("dv.amt")}</label>
        <input id="div-amt" type="text" inputMode="decimal" value={amt} aria-invalid={!amtOk || undefined} aria-describedby={!amtOk ? "div-amt-err" : undefined} onChange={(e) => setAmt(e.target.value)} style={{ maxWidth: 160 }} />
      </div>
      {!amtOk && <span id="div-amt-err" className="err">{t("fx2.div.amt")}</span>}
      <HBars rows={rows} x0={130} x1={380} rowH={36} ariaLabel={t("dv.h")} />
      <div className="merkle"><span>{t("dv.root")}</span> <span>{root ?? t("c.div.root")}</span> · <span>{t("dv.deadline")}</span></div>
      <button className="btn ghost" type="submit" disabled={busy || !amtOk} style={{ justifySelf: "start" }}>{t("dv.request")}</button>
      {msg && <p className={msg.ok ? "toast" : "err"} role={msg.ok ? "status" : "alert"}>{msg.s}</p>}
    </form>
  );
}

/* ---------- events ---------- */
/** Localised one-line detail for an event, built from its data (the server's `text` is English-only). */
function useEventDetail() {
  const { t, fmt, aud, date } = useI18n();
  return (e: CoEvent): string | null => {
    const d = (e.data ?? {}) as Record<string, unknown>;
    const ch = e.chain != null ? chainOf(e.chain).name : "";
    switch (e.kind) {
      case "issued": case "minted": case "transferred":
        return d.shares != null ? t("evd.shares", { n: fmt(Number(d.shares)), name: String(d.name || d.to_name || shortAddr(String(d.wallet ?? d.to_wallet ?? ""))) }) : null;
      case "kyc":
        return d.name ? String(d.name) : d.wallet ? shortAddr(String(d.wallet)) : null;
      case "deployed":
        return d.contract ? String(d.contract) : null;
      case "revalued":
        return d.mark_aud != null ? t("evd.mark", { m: aud(Number(d.mark_aud), 4) }) : null;
      case "dividend_created": case "dividend_vetoed":
        return d.total_units != null ? `${fmt(Number(d.total_units) / 1e6, 2)} mAUD` : null;
      case "dividend_declared":
        return d.total_units != null ? t("evd.declared", { n: fmt(Number(d.total_units) / 1e6, 2), d: d.pay_after ? date(String(d.pay_after), true) : "–" }) + (d.period ? ` · ${String(d.period)}` : "") : null;
      case "offering_opened":
        return d.shares != null ? t("evd.of.opened", { n: fmt(Number(d.shares)), p: aud(Number(d.price_aud ?? 0), 4), d: d.closes_at ? date(String(d.closes_at)) : "–" }) : null;
      case "offering_closed":
        return t("evd.of.closed", { n: fmt(Number(d.shares ?? 0)), k: fmt(Number(d.investors ?? 0)) });
      case "offering_released":
        return d.released != null ? t("evd.of.released", { k: fmt(Number(d.released)) }) : null;
      case "offering_settled":
        return t("evd.of.settled", { n: fmt(Number(d.shares ?? 0)), k: fmt(Number(d.investors ?? 0)) });
      case "sync_failed": case "sync_skipped":
        return [ch, d.error ? String(d.error) : ""].filter(Boolean).join(": ") || null;
      case "refreshed":
        return d.holders != null ? t("evd.holders", { n: fmt(Number(d.holders)) }) : null;
      case "resync_requested":
        return Array.isArray(d.chains) ? d.chains.map((c) => chainOf(c).name).join(", ") : null;
      case "valuation_anchored": case "anchored": case "sync_started": case "hoodi_mirrored": case "hsk_mirrored":
        return e.tx_hash ? null : ch || null;
      default:
        return null;
    }
  };
}

export function EventList({ events, sync }: { events: CoEvent[]; sync?: SyncInfo | null }) {
  const { t, date } = useI18n();
  const detail = useEventDetail();
  if (!events.length) return <p className="note">{t("c.ev.empty")}</p>;
  const resolved = resolvedFailures(events, sync ? (_e, ch) => sync[ch as "blockid" | "hoodi" | "hsk"] === "done" : undefined);
  const color = (k: string) => (k === "issued" || k === "anchored" || k === "hoodi_mirrored" || k === "hsk_mirrored" ? "--gold-mark" : k === "revalued" ? "--c3" : k.startsWith("dividend") ? "--c5" : k === "rejected" || isSyncFailure(k) ? "--down" : k === "minted" ? "--up" : "--c6");
  return (
    <div className="evlist">
      {events.map((e, i) => {
        const ch = e.chain != null ? chainOf(e.chain) : null;
        const known = (("ev." + e.kind) as DictKey);
        const label = t(known) === known ? e.kind.replace(/_/g, " ") : t(known);
        const isKnown = t(known) !== known;
        const extra = isKnown ? detail(e) : e.text && e.text.toLowerCase() !== label.toLowerCase() ? e.text : null;
        const done = resolved.has(e);
        return (
          <div key={e.id ?? i} className={done ? "resolved" : undefined}>
            <i style={{ background: `var(${color(e.kind)})` }} />
            <span>
              {label}
              {done ? <span className="resolvedtag">✓ {t("ev.resolved")}</span> : null}
              {extra ? <span className="muted" title={done ? extra : undefined}> · {done && extra.length > 80 ? extra.slice(0, 80) + "…" : extra}</span> : null}
              {ch && e.tx_hash ? <> · <a className="tx" href={ch.txUrl(e.tx_hash)} target="_blank" rel="noopener noreferrer">{shortAddr(e.tx_hash)}</a> <span className="hint">{ch.name}{e.block ? ` #${e.block}` : ""}</span></> : null}
            </span>
            <em>{date(e.at, true)}</em>
          </div>
        );
      })}
    </div>
  );
}

/** 404 from /v1/companies/:tk: either unknown, or not public yet (drafts are visible to the owner and admins only). */
function PrivateCompany({ ticker, onSignedIn }: { ticker: string; onSignedIn: () => void }) {
  const { t } = useI18n();
  const { me, busy, connect } = useAuth();
  const [err, setErr] = useState("");
  useEffect(() => { if (me) onSignedIn(); }, [me?.address, me?.username]); // eslint-disable-line react-hooks/exhaustive-deps
  if (me) {
    return (
      <div className="pane stateCard">
        <h2>{t("c.private.h")}</h2>
        <p>{t("c.private.signed", { t: ticker })}</p>
        <div className="row"><Link className="btn" to="/companies">{t("nav.companies")}</Link><Link className="btn ghost" to="/start">{t("cta.primary")}</Link></div>
      </div>
    );
  }
  return (
    <div className="pane stateCard">
      <span className="eyebrow">{t("c.eyebrow")} · <span className="mono">{ticker}</span></span>
      <h2>{t("c.private.h")}</h2>
      <p>{t("c.private.p", { t: ticker })}</p>
      <div className="row">
        <button className="btn" type="button" disabled={busy} onClick={async () => { setErr(""); try { await connect(); } catch (e) { setErr(errText(e, t)); } }}>
          {busy ? <span className="spinner" aria-hidden="true" /> : null}{busy ? t("nav.connecting") : t("nav.connect")}
        </button>
        <Link className="btn ghost" to="/admin">{t("c.private.admin")}</Link>
        <Link className="btn ghost" to="/companies">{t("nav.companies")}</Link>
      </div>
      {err && <p className="err" role="alert">{err}</p>}
      <DemoApproveGuide action={t("trk.approve")} tail="demo.tail.issue" admin={`/admin/issuance/${ticker}`} next={`/c/${ticker}/issue`} />
    </div>
  );
}

type Sec = "issue" | "sync" | "wallet" | WsSection;
const ORDER: Sec[] = ["issue", "sync", "wallet", ...WS];

export default function CompanyPage() {
  const { ticker: raw = "", section } = useParams();
  const ticker = raw.toUpperCase();
  const { t, fmt, money, date } = useI18n();
  const { me } = useAuth();
  const mine = useMyCompanies();
  const loc = useLocation();
  const nav = useNavigate();
  const flash = (loc.state as { flash?: string; companyId?: number } | null)?.flash;
  const companyId = (loc.state as { companyId?: number } | null)?.companyId;
  const [status, setStatus] = useState<CoStatus | "">("");
  const q = useAsync<CompanyDetail>(() => api.company(ticker), [ticker], status && RUNNING.includes(status) ? 3000 : status && (TRANSIENT.includes(status) || status === "draft") ? 15000 : 30000);
  const c = q.data;
  useEffect(() => { if (c) setStatus(c.status); }, [c?.status]); // eslint-disable-line react-hooks/exhaustive-deps
  const [toast, setToast] = useState("");
  const [submitMsg, setSubmitMsg] = useState("");
  useTitle(c ? `${c.ticker} · ${c.name}` : ticker);

  // follow the issuer: 6 -> 7 -> 8 while the founder watches
  const lastStep = useRef<number | null>(null);
  const step = c ? coStep(c) : 6;
  useEffect(() => {
    if (!c) return;
    const prev = lastStep.current;
    lastStep.current = step;
    if (prev != null && step > prev && section === CO_SEG[prev]) nav(`/c/${c.ticker}/${CO_SEG[step]}`, { replace: true });
  }, [step]); // eslint-disable-line react-hooks/exhaustive-deps
  // /c/:tk without a section (or with an unknown one, e.g. /c/EBA/verify): the current flow step, or the workspace
  // once everything is live
  useEffect(() => {
    if (c && (!section || !(ORDER as string[]).includes(section))) nav(`/c/${c.ticker}/${c.status === "anchored" || step === 8 ? "overview" : CO_SEG[step]}`, { replace: true, state: loc.state });
  }, [c != null, section]); // eslint-disable-line react-hooks/exhaustive-deps

  if (q.loading && !c) return <Loading />;
  if (!c) {
    return (
      <div className="wrap page stack">
        {flash && <p className="toast" role="status">{flash}</p>}
        {q.error instanceof ApiError && q.error.status === 404 ? (
          <PrivateCompany ticker={ticker} onSignedIn={() => void q.reload()} />
        ) : (
          <>
            <ErrorBox error={q.error} retry={q.reload} />
            <Link className="btn ghost" to="/companies" style={{ justifySelf: "start" }}>{t("nav.companies")}</Link>
          </>
        )}
      </div>
    );
  }

  const live = LIVE.includes(c.status);
  const holders = c.cap_table?.length ? c.cap_table : [];
  const localToken = c.local?.token ?? c.local_token ?? null;
  const hoodiToken = c.hoodi?.token ?? c.hoodi_token ?? null;
  const hskToken = c.hsk?.token ?? c.hsk_token ?? null;
  const g = c.grade ?? "C";
  const isCoAdmin = mine.list.some((x) => x.ticker === c.ticker);  // active company admin (owner / manager)
  const canManage = !!me && (me.role === "admin" || isCoAdmin);
  const canRequest = !!me && (canManage || (!!me.address && !!c.created_by && me.address.toLowerCase() === c.created_by.toLowerCase()) || !c.created_by);
  const submit = async () => {
    const id = c.id ?? companyId;
    if (id == null) return;
    try { await api.submitCompany(id); setSubmitMsg(t("c.submitted")); void q.reload(); } catch (e) { setSubmitMsg(errText(e, t)); }
  };

  // which sections this viewer can open, and why not
  const reach = coReach(c);
  const why = (s: Sec): string | null => {
    if (s === "issue") return null;
    if (s === "sync" || s === "wallet") return CO_STEP[s] <= reach ? null : t("flow.locked");
    if (s === "overview" || s === "cap-table" || s === "activity" || s === "updates") return null;
    if (!live) return t("ws.needlive");
    if (s === "transfers") return localToken ? (me ? null : t("ws.needsign")) : t("ws.needlive");
    if (s === "mint" || s === "dividends") return canRequest ? null : t("ws.needauth");
    if (s === "team" || s === "offering") return canManage ? null : t("ws.needauth");
    return null;
  };
  const sec: Sec = (ORDER as string[]).includes(section ?? "") && !why(section as Sec) ? (section as Sec) : (section ? "overview" : CO_SEG[step] as Sec);
  const open = ORDER.filter((s) => !why(s));
  const at = open.indexOf(sec);
  const label = (s: Sec) => (CO_STEP[s] ? t(("step." + CO_STEP[s]) as DictKey) : t(("ws." + s) as DictKey));
  const prevS = at > 0 ? open[at - 1] : null;
  const nextS = at >= 0 && at < open.length - 1 ? open[at + 1] : null;
  const flowN = CO_STEP[sec];

  const rail = (
    <>
      <FlowRail cur={flowN ?? 0} reach={Math.max(reach, 6)} gates={["ok", coGate(c)]}
        href={(n) => (n <= 3 ? (c.valuation_id ? valPath(c.valuation_id, Math.max(2, n)) : null) : n <= 5 ? null : `/c/${c.ticker}/${CO_SEG[n]}`)} />
      <RailGroup title={t("flow.ph.d")} aside={<span className="mono">{c.ticker}</span>}>
        {WS.map((s) => <RailItem key={s} to={why(s) ? null : `/c/${c.ticker}/${s}`} current={sec === s} hint={why(s) ?? undefined} gate={s === "mint" || s === "dividends" || s === "offering"}>{t(("ws." + s) as DictKey)}</RailItem>)}
        <RailItem to={`/verify/${c.ticker}`}>{t("ws.verify")} <span aria-hidden="true">↗</span></RailItem>
      </RailGroup>
    </>
  );

  const nextAct = (() => {
    if (c.status === "draft") return { k: "ws.next.draft" as DictKey, to: "issue" };
    if (c.status === "pending_issue") return { k: "ws.next.wait" as DictKey, to: "issue" };
    if (c.status === "rejected" || c.status === "failed") return { k: "ws.next.fail" as DictKey, to: "issue" };
    if (step === 6) return { k: "ws.next.issuing" as DictKey, to: "issue" };
    if (step === 7) return { k: "ws.next.sync" as DictKey, to: "sync" };
    return { k: "ws.next.live" as DictKey, to: "wallet" };
  })();

  const SB: Record<string, [DictKey, Tone]> = {
    draft: ["sb.st.draft", "idle"], pending_issue: ["sb.st.waiting", "wait"], issuing: ["sb.st.creating", "run"],
    issued: ["sb.st.copying", "run"], pending_anchor: ["sb.st.copying", "run"], anchoring: ["sb.st.copying", "run"],
    partially_anchored: ["sb.st.copying", "run"], anchored: ["sb.st.live", "ok"], rejected: ["sb.st.rejected", "bad"], failed: ["sb.st.failed", "bad"],
  };
  const [sbKey, sbTone] = SB[c.status] ?? (["sb.st.draft", "idle"] as [DictKey, Tone]);
  const sbStep = c.status === "anchored" ? 8 : step;
  const sbDone = c.status === "anchored" ? 8 : c.status === "draft" || c.status === "pending_issue" || c.status === "rejected" ? 5 : step - 1;
  let sbNext: StatusNext | null = null;
  if (c.status === "pending_issue" && me?.role !== "admin") sbNext = { label: t("sb.next.approve"), to: demoApproveLink(`/admin/issuance/${c.ticker}`, `/c/${c.ticker}/issue`) };
  else if (sec !== nextAct.to) sbNext = { label: label(nextAct.to as Sec), to: `/c/${c.ticker}/${nextAct.to}` };

  return (
    <SideLayout rail={rail} label={t("flow.nav")}>
      <Crumbs items={[{ to: "/companies", label: t("nav.companies") }, { to: `/c/${c.ticker}/overview`, label: c.ticker }, { label: label(sec) }]} />
      <div className="cohead">
        <h1 className="row" style={{ gap: 12 }}>
          <span className="mono" style={{ color: "var(--accent)", letterSpacing: ".1em" }}>{c.ticker}</span>
          <span>{c.name}</span>
          {c.grade && <span className="gchip lg" style={{ background: `var(${GRADE_C[c.grade] ?? "--c6"})` }} aria-label={`${t("ad.c.grade")} ${c.grade}`}>{c.grade}</span>}
        </h1>
        <span className="row" style={{ gap: 8 }}>
          {c.offering?.status === "open" && <Link to={`/i/offerings/${c.offering.id}`} aria-label={t("of.badge.see")}><OfferingBadge /></Link>}
          {c.website && <a href={c.website} target="_blank" rel="noopener noreferrer" className="muted-sm">{c.website.replace(/^https?:\/\//, "")}</a>}
        </span>
      </div>
      {sec !== "offering" && (  /* the offering section shows its own status line */
        <StatusBar status={t(sbKey)} tone={sbTone} step={sbStep} done={sbDone} since={sbTone === "run" ? c.sync?.started_at ?? null : null}
          meta={sbTone === "run" || sec === "overview" ? t(nextAct.k, { tk: c.ticker }) : null} next={sbNext} />
      )}
      <StepHead eyebrow={flowN ? t("flow.stepof", { n: flowN, p: t("flow.ph.c") }) : t("ws.h")} title={flowN ? t(("step." + flowN) as DictKey) : t(("ws." + sec) as DictKey)} desc={t((flowN ? "flow.d" + flowN : "ws.d." + sec) as DictKey)} />
      {flash && <p className="toast" role="status">{flash}</p>}
      {c.error && c.status !== "rejected" && !(sec === "sync" && Object.keys(c.sync?.errors ?? {}).length) && !(sec === "issue" && c.status === "failed") && (
        <ErrorFix error={c.error} info={c.error_info} ticker={c.ticker} companyId={c.local?.token ? c.id : null}
          onDone={() => void q.reload()} hideLink={c.error_info?.target === sec} />
      )}

      {sec === "issue" && (
        <>
          {c.status === "draft" || c.status === "rejected" ? <div className="pane"><Timeline status={c.status} /></div> : null}
          {c.status !== "draft" && <Tracker c={c} onChanged={() => void q.reload()} only={["s1", "s2", "s3"]} feed={false} />}
          {c.status === "rejected" && <p className="quietline bad" role="alert">{t("c.st.rejected")}{c.error ? ": " + c.error : ""}</p>}
          {c.status === "draft" && (
            <p className="quietline"><span>{t("c.draftnote")}</span>{(c.id ?? companyId) != null && me && <button className="btn gold sm" type="button" onClick={submit}>{t("c.submit")}</button>}{submitMsg && <span role="status">{submitMsg}</span>}</p>
          )}
        </>
      )}
      {sec === "sync" && (
        <>
          <Tracker c={c} onChanged={() => void q.reload()} only={["s4", "s5", "s6"]} />
          {c.hoodi?.merkle_root && (
            <p className="merkle">{t("c.anchor.root")} {c.hoodi.merkle_root}{c.hoodi.anchor_tx ? <> · <a href={CHAINS.hoodi.txUrl(c.hoodi.anchor_tx)} target="_blank" rel="noopener noreferrer">Hoodi {shortAddr(c.hoodi.anchor_tx)}</a></> : null}{c.hsk?.anchor_tx ? <> · <a href={CHAINS.hsk.txUrl(c.hsk.anchor_tx)} target="_blank" rel="noopener noreferrer">HSK {shortAddr(c.hsk.anchor_tx)}</a></> : null}</p>
          )}
        </>
      )}
      {sec === "wallet" && (
        <div className="panel">
          <div className="cols3">
            <AddrCard chain={CHAINS.local} address={localToken} ticker={c.ticker} onToast={setToast} />
            <AddrCard chain={CHAINS.hoodi} address={hoodiToken} ticker={c.ticker} onToast={setToast} />
            <AddrCard chain={CHAINS.hsk} address={hskToken} ticker={c.ticker} onToast={setToast} />
          </div>
          <p className="toast" role="status">{toast}</p>
          <div className="cols">
            <ManualSteps ticker={c.ticker} />
            <NetworkDetails />
          </div>
        </div>
      )}

      {sec === "overview" && (
        <>
          {c.offering?.status === "open" && (
            <p className="quietline"><OfferingBadge /><span>{t("of.co.open", { d: date(c.offering.closes_at, true) })}</span><Link to={`/i/offerings/${c.offering.id}`}>{t("of.badge.see")} →</Link></p>
          )}
          <div className="kpis">
            <div className="kpi"><small>{t("c.k.val")}</small><b>{money(c.valuation_aud)}</b><span>{t("c.k.valsub", { s: c.svi != null ? fmt(Number(c.svi), 1) : "–", g })}</span></div>
            <div className="kpi"><small>{t("k.shares")}</small><b>{fmt(c.total_shares)}</b><span>{t("c.k.sharesub", { tk: c.ticker })}</span></div>
            <div className="kpi"><small>{t("k.holders")}</small><b>{fmt(holders.length || c.holders || 0)}</b><span>{live ? t("k.kyc") : " "}</span></div>
            <div className="kpi"><small>{t("k.anchor")}</small><b>{c.hoodi?.block ? "#" + fmt(c.hoodi.block) : t("c.k.noanchor")}</b><span>Ethereum Hoodi{c.hsk?.block ? ` · HashKey #${fmt(c.hsk.block)}` : ""}</span></div>
          </div>
          {c.valuation_id && <TeamTile valuationId={c.valuation_id} canManage={canManage || canRequest} />}
          {live && c.marks?.length ? (
            <MarkPanel ticker={c.ticker} name={c.name} grade={g} svi={c.svi} marks={c.marks} events={c.events} valuation={c.valuation_aud} totalShares={c.total_shares} holders={holders.length} />
          ) : null}
        </>
      )}
      {sec === "updates" && <CompanyUpdates c={c} canManage={canManage} live={live} />}
      {sec === "offering" && <CompanyOffering ticker={c.ticker} />}
      {sec === "cap-table" && <CapTable rows={holders} ticker={c.ticker} source={c.cap_table_source} block={c.cap_table_block} />}
      {sec === "transfers" && <TransferPanel c={c} onDone={() => void q.reload()} />}
      {sec === "mint" && <MintForm c={c} onSent={() => void q.reload()} />}
      {sec === "dividends" && (
        <>
          {canManage && <CompanyDividends ticker={c.ticker} />}
          <DividendForm c={c} onSent={() => void q.reload()} />
        </>
      )}
      {sec === "activity" && <div className="pane"><EventList events={c.events ?? []} sync={c.sync} /></div>}
      {sec === "team" && (
        <>
          {live && c.id != null && <CompanyApprovals companyId={c.id} onChanged={() => void q.reload()} />}
          <CompanyAdminsPanel ticker={c.ticker} onChanged={mine.reload} />
        </>
      )}

      <Pager prev={prevS ? { to: `/c/${c.ticker}/${prevS}`, label: label(prevS) } : null}
        next={nextS ? { to: `/c/${c.ticker}/${nextS}`, label: label(nextS), primary: !!CO_STEP[sec] } : null} />
    </SideLayout>
  );
}
