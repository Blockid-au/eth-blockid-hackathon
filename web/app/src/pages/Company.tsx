import { useEffect, useState } from "react";
import { Link, useLocation, useParams } from "react-router-dom";
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
import { CHAINS, chainOf, isAddressValid, shortAddr } from "../wallet";
import type { DictKey } from "../dict";
import { Tracker } from "../components/Tracker";
import { TransferPanel } from "./Transfers";
import { DemoApproveGuide } from "../components/DemoGuide";
import { CompanyAdminsPanel, CompanyApprovals } from "../components/CompanyAdmins";
import { useMyCompanies } from "../lib/companyAdmins";

const TRANSIENT: CoStatus[] = ["pending_issue", "issuing", "issued", "pending_anchor", "anchoring", "partially_anchored"];
const RUNNING: CoStatus[] = ["issuing", "anchoring"];
const LIVE: CoStatus[] = ["issued", "pending_anchor", "anchoring", "anchored", "partially_anchored"];

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
  const total = rows.reduce((a, r) => a + Number(r.shares), 0);
  const pct = (r: CapRow) => (r.pct != null ? Number(r.pct) : total ? (Number(r.shares) / total) * 100 : 0);
  if (!rows.length) return <p className="empty">{t("c.cap.empty")}</p>;
  return (
    <div className="cols">
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
  const total = Math.max(0, Math.floor(Number(amt) || 0));
  const supply = c.cap_table.reduce((a, r) => a + Number(r.shares), 0) || 1;
  const rows = c.cap_table.map((r, i) => {
    const pay = Math.floor(((total * Number(r.shares)) / supply) * 100) / 100;
    return { name: r.name, value: pay, color: colorAt(i), label: fmt(pay, 2), tip: `${r.name} · ${fmt((Number(r.shares) / supply) * 100, 1)}% · ${fmt(pay, 2)} mAUD` };
  });
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (total < 1) return;
    setBusy(true); setMsg(null);
    try {
      const r = await api.requestDividend(c.ticker, total);
      setRoot(r?.merkle_root ?? null);
      setMsg({ ok: true, s: t("c.div.sent") });
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
        <input id="div-amt" type="number" min={0} step={1000} value={amt} onChange={(e) => setAmt(e.target.value)} style={{ maxWidth: 160 }} />
      </div>
      <HBars rows={rows} x0={130} x1={380} rowH={36} ariaLabel={t("dv.h")} />
      <div className="merkle"><span>{t("dv.root")}</span> <span>{root ?? t("c.div.root")}</span> · <span>{t("dv.deadline")}</span></div>
      <button className="btn ghost" type="submit" disabled={busy || total < 1} style={{ justifySelf: "start" }}>{t("dv.request")}</button>
      {msg && <p className={msg.ok ? "toast" : "err"} role={msg.ok ? "status" : "alert"}>{msg.s}</p>}
    </form>
  );
}

/* ---------- events ---------- */
/** Localised one-line detail for an event, built from its data (the server's `text` is English-only). */
function useEventDetail() {
  const { t, fmt, aud } = useI18n();
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
      case "dividend_created":
        return d.total_units != null ? `${fmt(Number(d.total_units) / 1e6, 2)} mAUD` : null;
      case "sync_failed": case "sync_skipped":
        return [ch, d.error ? String(d.error) : ""].filter(Boolean).join(": ") || null;
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
        <div className="row"><Link className="btn" to="/companies">{t("nav.companies")}</Link><Link className="btn ghost" to="/new">{t("cta.primary")}</Link></div>
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
      <DemoApproveGuide action={t("trk.approve")} tail="demo.tail.issue" next={`/c/${ticker}`} />
    </div>
  );
}

export default function CompanyPage() {
  const { ticker: raw = "" } = useParams();
  const ticker = raw.toUpperCase();
  const { t, fmt, money } = useI18n();
  const { me } = useAuth();
  const mine = useMyCompanies();
  const loc = useLocation();
  const flash = (loc.state as { flash?: string; companyId?: number } | null)?.flash;
  const companyId = (loc.state as { companyId?: number } | null)?.companyId;
  const [status, setStatus] = useState<CoStatus | "">("");
  const q = useAsync<CompanyDetail>(() => api.company(ticker), [ticker], status && RUNNING.includes(status) ? 3000 : status && (TRANSIENT.includes(status) || status === "draft") ? 15000 : 30000);
  const c = q.data;
  useEffect(() => { if (c) setStatus(c.status); }, [c?.status]); // eslint-disable-line react-hooks/exhaustive-deps
  const [toast, setToast] = useState("");
  const [submitMsg, setSubmitMsg] = useState("");
  useTitle(c ? `${c.ticker} · ${c.name}` : ticker);

  if (q.loading && !c) return <Loading />;
  if (!c) {
    return (
      <div className="wrap page stack">
        {flash && <p className="banner gold">{flash}</p>}
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

  return (
    <section className="block" style={{ borderTop: 0, paddingTop: 40 }}>
      <div className="wrap stack" style={{ gap: 20 }}>
        <div className="between">
          <div className="head" style={{ marginBottom: 0 }}>
            <span className="eyebrow">{t("c.eyebrow")} · {t(("c.st." + c.status) as DictKey)}</span>
            <h2 className="row" style={{ gap: 12 }}>
              <span className="mono" style={{ color: "var(--accent)", letterSpacing: ".1em" }}>{c.ticker}</span>
              <span>{c.name}</span>
              {c.grade && <span className="gchip lg" style={{ background: `var(${GRADE_C[c.grade] ?? "--c6"})` }} aria-label={`${t("ad.c.grade")} ${c.grade}`}>{c.grade}</span>}
            </h2>
            {c.website && <a href={c.website} target="_blank" rel="noopener noreferrer" className="muted-sm">{c.website.replace(/^https?:\/\//, "")}</a>}
          </div>
          {TRANSIENT.includes(c.status) && <span className="live"><i />{t(("c.st." + c.status) as DictKey)}</span>}
        </div>
        {flash && <p className="banner gold" role="status">{flash}</p>}
        {c.status === "draft" || c.status === "rejected" ? <div className="pane"><Timeline status={c.status} /></div> : null}
        {c.status !== "draft" && <Tracker c={c} onChanged={() => void q.reload()} />}
        {c.status === "rejected" && <p className="banner bad" role="alert">{t("c.st.rejected")}{c.error ? ": " + c.error : ""}</p>}
        {c.status === "draft" && (
          <div className="banner gold"><span>{t("c.draftnote")}</span>{(c.id ?? companyId) != null && me && <button className="btn gold sm" type="button" onClick={submit}>{t("c.submit")}</button>}{submitMsg && <span>{submitMsg}</span>}</div>
        )}

        <div className="kpis">
          <div className="kpi"><small>{t("c.k.val")}</small><b>{money(c.valuation_aud)}</b><span>{t("c.k.valsub", { s: c.svi != null ? fmt(Number(c.svi), 1) : "–", g })}</span></div>
          <div className="kpi"><small>{t("k.shares")}</small><b>{fmt(c.total_shares)}</b><span>{t("c.k.sharesub", { tk: c.ticker })}</span></div>
          <div className="kpi"><small>{t("k.holders")}</small><b>{fmt(holders.length || c.holders || 0)}</b><span>{live ? t("k.kyc") : " "}</span></div>
          <div className="kpi"><small>{t("k.anchor")}</small><b>{c.hoodi?.block ? "#" + fmt(c.hoodi.block) : t("c.k.noanchor")}</b><span>Ethereum Hoodi{c.hsk?.block ? ` · HashKey #${fmt(c.hsk.block)}` : ""}</span></div>
        </div>

        {live && c.marks?.length ? (
          <MarkPanel ticker={c.ticker} name={c.name} grade={g} svi={c.svi} marks={c.marks} events={c.events} valuation={c.valuation_aud} totalShares={c.total_shares} holders={holders.length} />
        ) : null}

        <CapTable rows={holders} ticker={c.ticker} source={c.cap_table_source} block={c.cap_table_block} />
        {live && localToken && <TransferPanel c={c} onDone={() => void q.reload()} />}

        <div className="panel">
          <div className="ptitle"><div><h3>{t("s8.h").replace("HBL", c.ticker)}</h3><p>{t("s8.p")}</p></div></div>
          <div className="cols">
            <AddrCard chain={CHAINS.local} address={localToken} ticker={c.ticker} onToast={setToast} />
            <AddrCard chain={CHAINS.hoodi} address={hoodiToken} ticker={c.ticker} onToast={setToast} />
            <AddrCard chain={CHAINS.hsk} address={hskToken} ticker={c.ticker} onToast={setToast} />
          </div>
          <p className="toast" role="status">{toast}</p>
          {c.hoodi?.merkle_root && (
            <p className="merkle">{t("c.anchor.root")} {c.hoodi.merkle_root}{c.hoodi.anchor_tx ? <> · <a href={CHAINS.hoodi.txUrl(c.hoodi.anchor_tx)} target="_blank" rel="noopener noreferrer">Hoodi {shortAddr(c.hoodi.anchor_tx)}</a></> : null}{c.hsk?.anchor_tx ? <> · <a href={CHAINS.hsk.txUrl(c.hsk.anchor_tx)} target="_blank" rel="noopener noreferrer">HSK {shortAddr(c.hsk.anchor_tx)}</a></> : null}</p>
          )}
          <div className="cols">
            <ManualSteps ticker={c.ticker} />
            <NetworkDetails />
          </div>
        </div>

        <div className="head" style={{ marginBottom: 0, marginTop: 12 }}>
          <span className="eyebrow">{t("dash.eyebrow")}</span>
          <h2>{t("dash.h2")}</h2>
          <p>{t("dash.p")}</p>
        </div>
        {!live ? <p className="empty">{t("c.onlyissued")}</p> : !canRequest ? <p className="banner gold">{t("c.needauth")}</p> : (
          <div className="cols">
            <MintForm c={c} onSent={() => void q.reload()} />
            <DividendForm c={c} onSent={() => void q.reload()} />
          </div>
        )}
        {live && canManage && c.id != null && <CompanyApprovals companyId={c.id} onChanged={() => void q.reload()} />}
        {canManage && <CompanyAdminsPanel ticker={c.ticker} onChanged={mine.reload} />}

        <div className="pane">
          <h4>{t("c.ev")}</h4>
          <EventList events={c.events ?? []} sync={c.sync} />
        </div>
      </div>
    </section>
  );
}
