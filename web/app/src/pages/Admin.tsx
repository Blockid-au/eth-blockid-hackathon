import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { safeNext } from "../components/DemoGuide";
import { useI18n } from "../i18n";
import { errText, useAuth } from "../auth";
import {
  api, ApiError, type AdminCompany, type ApprovalCompany, type Approvals, type AdminWallets, type AuditRow, type BizUpdate, type Offering, type CompanySummary, type DividendPolicy, type DividendReq, type IssuerWallet, type MintReq, type Stats, type Valuation,
} from "../api";
import { GradeChart, KTile, Ranges, StepArea } from "../components/charts";
import { MarkPanel } from "../components/MarkPanel";
import { CompanyTable } from "./Companies";
import { EventList } from "./Company";
import { ErrorBox } from "../components/Layout";
import { useAsync, useNow, usePageVisible, useTitle, type Async } from "../lib/hooks";
import { bandGrade } from "../lib/svi";
import { CHAINS, addrError, chainOf, isAddressValid, shortAddr } from "../wallet";
import type { DictKey } from "../dict";
import { SyncChips } from "../components/Tracker";
import { LowBalanceBanner } from "../components/LowBalance";
import { isSyncFailure, resolvedFailures } from "../lib/events";
import { AdminTransfersTab, tapi } from "./Transfers";
import { Crumbs, RailGroup, RailItem, SideLayout, StepHead } from "../components/Shell";
import { QUEUES, queueCounts, queueItems, type QueueKey } from "../lib/flow";
import { CompanyAdminsPanel } from "../components/CompanyAdmins";
import { ErrorFix } from "../components/ErrorFix";
import { StatusPill, UpdateView } from "./Updates";
import { PolicyPill, PolicySummary } from "./Dividends";
import { OfferingQueueItem } from "./Offerings";
import { AiHealthTab } from "./AiHealth";
import { OpsTab } from "./Ops";

const POLL = 12000;
const pwRequired = (e: unknown) => e instanceof ApiError && e.status === 403 && /password change/i.test(e.message);

/* ================= login ================= */
function LoginCard({ next }: { next: string | null }) {
  const { t } = useI18n();
  const { me, connect, login } = useAuth();
  const [mode, setMode] = useState<"w" | "p">(next ? "p" : "w");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const [u, setU] = useState("");
  const [p, setP] = useState("");
  const siwe = async () => {
    setErr(""); setBusy(true);
    try {
      const m = await connect();
      if (m?.role !== "admin") setErr(t("ad.bad.wallet"));
    } catch (e) { setErr(errText(e, t)); } finally { setBusy(false); }
  };
  const pass = async (e: React.FormEvent) => {
    e.preventDefault(); setErr(""); setBusy(true);
    try { await login(u.trim(), p); setP(""); }
    catch (x) { setErr(x instanceof ApiError && x.status === 429 ? t("ad.bad.rate") : x instanceof ApiError && (x.status === 401 || x.status === 403) ? t("ad.bad.pass") : errText(x, t)); }
    finally { setBusy(false); }
  };
  return (
    <div className="login">
      <h3>{t("ad.signin")}</h3>
      {me && me.role !== "admin" && <p className="banner warn">{t("ad.notadmin")}</p>}
      {next && <p className="note" role="status">{t("demo.return", { p: next })}</p>}
      <div className="segs" role="tablist" aria-label={t("ad.signin")}>
        <button type="button" role="tab" aria-selected={mode === "w"} onClick={() => { setMode("w"); setErr(""); }}>{t("ad.m.wallet")}</button>
        <button type="button" role="tab" aria-selected={mode === "p"} onClick={() => { setMode("p"); setErr(""); }}>{t("ad.m.pass")}</button>
      </div>
      {mode === "w" ? (
        <div style={{ display: "grid", gap: 12 }} role="tabpanel">
          <p className="sub muted">{t("ad.walletp")}</p>
          <button className="btn" type="button" onClick={siwe} disabled={busy}>{busy ? <span className="spinner" aria-hidden="true" /> : null}{t("ad.siwe")}</button>
        </div>
      ) : (
        <form style={{ display: "grid", gap: 12 }} onSubmit={pass} role="tabpanel">
          <p className="banner gold" style={{ margin: 0 }}><span><b>{t("demo.creds")}</b> · {t("demo.tag")}</span></p>
          <label className="lf"><span>{t("ad.user")}</span><input type="text" autoComplete="username" value={u} onChange={(e) => setU(e.target.value)} required /></label>
          <label className="lf"><span>{t("ad.pass")}</span><input type="password" autoComplete="current-password" value={p} onChange={(e) => setP(e.target.value)} required /></label>
          <button className="btn" type="submit" disabled={busy}>{t("ad.enter")}</button>
        </form>
      )}
      <p className="err" role="alert">{err}</p>
    </div>
  );
}

function ChangePassword({ onDone }: { onDone: () => void }) {
  const { t } = useI18n();
  const { logout } = useAuth();
  const [cur, setCur] = useState("");
  const [n1, setN1] = useState("");
  const [n2, setN2] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  // same rules as the server (studio/auth.py password_problem), shown under the field as it is typed
  const bytes = new TextEncoder().encode(n1).length;
  const n1Err = !n1 ? "" : !n1.trim() ? t("fx.pw.spaces") : n1.length < 10 ? t("ad.cp.short") : bytes > 72 ? t("fx.pw.long", { n: bytes }) : cur && n1 === cur ? t("fx.pw.same") : "";
  const n2Err = n2 && n1 !== n2 ? t("ad.cp.mismatch") : "";
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!cur) { setErr(t("fx.pw.cur")); return; }
    if (!n1 || n1Err) { setErr(n1Err || t("ad.cp.short")); return; }
    if (n1 !== n2) { setErr(t("ad.cp.mismatch")); return; }
    setBusy(true); setErr("");
    try { await api.changePassword(cur, n1); onDone(); }
    catch (x) { setErr(errText(x, t)); }
    finally { setBusy(false); }
  };
  return (
    <form className="login" onSubmit={submit} noValidate>
      <h3>{t("ad.cp.h")}</h3>
      <p className="sub muted">{t("ad.cp.p")}</p>
      <label className="lf"><span>{t("ad.cp.cur")}</span><input type="password" autoComplete="current-password" value={cur} onChange={(e) => setCur(e.target.value)} required /></label>
      <label className="lf"><span>{t("ad.cp.new")}</span><input type="password" autoComplete="new-password" minLength={10} className={n1Err ? "bad" : undefined} aria-invalid={!!n1Err} value={n1} onChange={(e) => setN1(e.target.value)} required />{n1Err && <span className="hint bad">{n1Err}</span>}</label>
      <label className="lf"><span>{t("ad.cp.rep")}</span><input type="password" autoComplete="new-password" minLength={10} className={n2Err ? "bad" : undefined} aria-invalid={!!n2Err} value={n2} onChange={(e) => setN2(e.target.value)} required />{n2Err && <span className="hint bad">{n2Err}</span>}</label>
      <div className="row">
        <button className="btn" type="submit" disabled={busy || !cur || !n1 || !!n1Err || n1 !== n2}>{t("ad.cp.go")}</button>
        <button className="btn ghost" type="button" onClick={() => void logout()}>{t("ad.logout")}</button>
      </div>
      <p className="err" role="alert">{err}</p>
    </form>
  );
}

/* ================= overview ================= */
function Overview({ stats, cos, onPick, wallets }: { stats: Async<Stats>; cos: Async<CompanySummary[]>; onPick: (tk: string) => void; wallets?: AdminWallets | null }) {
  const { t, fmt, money, chg, date, ago, locale } = useI18n();
  const [rangeSel, setRange] = useState<number | null>(null); // null = adaptive default
  const s = stats.data;
  if (!s) return stats.error ? <ErrorBox error={stats.error} retry={stats.reload} /> : <p className="note">{t("common.loading")}</p>;
  const k = s.kpis;
  const days = s.series.days, V = s.series.value_aud, C = s.series.companies;
  const n = days.length;
  // "Since launch": from the day before the first issuance, so a young platform is not a flat line with one jump
  const first = V.findIndex((x) => x > 0);
  const since = first < 0 ? 30 : Math.max(2, n - first);
  const range = rangeSel ?? (since <= 30 ? -1 : since <= 90 ? 90 : 365);
  const s90 = (arr: number[]) => Array.from({ length: 19 }, (_, i) => arr[Math.max(0, n - 1 - (90 - i * 5))] ?? 0);
  const pc = (arr: number[]) => { const a = arr[n - 31], b = arr[n - 1]; return a ? (b / a - 1) * 100 : null; };
  const avgSer = V.map((x, i) => (C[i] ? x / C[i] : 0));
  const span = range === -1 ? since : range;
  const lo = Math.max(0, n - 1 - span);
  const vals = V.slice(lo), labels = days.slice(lo), cnt = C.slice(lo);
  const dfmt = new Intl.DateTimeFormat(locale, { day: "numeric", month: "short" });
  // one pin per day the marked value changed (issuance or approved revaluation)
  const pins = vals.map((x, i) => ({ i, x })).filter(({ i, x }) => i > 0 && x !== vals[i - 1])
    .map(({ i, x }) => ({ i, label: t("ad.pin", { d: date(labels[i]), v: money(x), n: fmt(cnt[i]) }) }));
  const compact = (x: number) => (x >= 1e6 ? fmt(x / 1e6, 1) + "M" : fmt(x));
  const movers = s.movers.slice(0, 5);
  const syncOf = new Map((cos.data ?? []).map((c) => [c.ticker, c.sync]));
  const resolvedAct = resolvedFailures(s.activity, (e, ch) => syncOf.get(e.ticker ?? "")?.[ch as "blockid" | "hoodi" | "hsk"] === "done");
  return (
    <div style={{ display: "grid", gap: 16 }}>
      <LowBalanceBanner wallets={wallets} />
      <div className="kgrid">
        <KTile label={t("ad.k.co")} value={fmt(k.companies)} p={pc(C)} series={s90(C)} />
        <KTile label={t("ad.k.tok")} value={fmt(k.tokens)} p={null} series={s90(C).map((x) => x * 2)} sub={t("ad.k.toksub")} />
        <KTile label={t("ad.k.sh")} value={compact(k.shares)} p={null} series={s90(C)} sub={t("ad.k.issued1")} />
        <KTile label={t("ad.k.tx")} value={money(k.tx_value_aud)} p={null} series={s90(V)} sub={t("ad.issue1")} />
        <KTile label={t("ad.k.val")} value={money(k.total_valuation_aud)} p={pc(V)} series={s90(V)} />
        <KTile label={t("ad.k.avg")} value={money(k.avg_valuation_aud)} p={null} series={s90(avgSer)} sub={t("ad.k.median") + " " + money(k.median_valuation_aud)} />
        <KTile label={t("ad.k.mult")} value={fmt(k.avg_mark, 2) + "×"} p={k.avg_mark ? (k.avg_mark - 1) * 100 : null} series={s90(avgSer)} />
        <KTile label={t("ad.k.anch")} value={t("ad.k.anchval", { a: fmt(k.anchored), b: fmt(k.anchored_total) })} p={null} series={s90(C)} sub={k.anchored === k.anchored_total ? t("ad.k.anchsub") : ""} />
      </div>
      <div className="split">
        <div className="pane">
          <div className="phead"><h4>{t("ad.pv")}</h4><Ranges label={t("ad.range")} opts={[[t("ad.r.since"), -1], ["1M", 30], ["3M", 90], ["6M", 180], ["1Y", 365]]} value={range} onChange={setRange} /></div>
          <div className="chartscroll"><StepArea labels={labels} vals={vals} pins={pins} fmtV={money} fmtX={(i) => (labels[i] ? dfmt.format(new Date(labels[i])) : "")} ariaLabel={`${t("ad.pv")}: ${labels.length ? dfmt.format(new Date(labels[0])) : ""} ${money(vals[0] ?? 0)} → ${money(vals[vals.length - 1] ?? 0)}`} showPinValues={pins.length <= 4} /></div>
          <p className="note">{t("ad.pvnote")}</p>
        </div>
        <div className="pane">
          <h4>{t("ad.grades")}</h4>
          <GradeChart grades={s.grades} extra={(g) => money((cos.data ?? []).filter((c) => c.grade === g).reduce((a, c) => a + c.valuation_aud, 0))} />
          <h4>{t("ad.movers")}</h4>
          <div className="movers">
            {movers.map((m) => (
              <div key={m.ticker}><b className="mono">{m.ticker}</b><span>{m.name}</span><span className={"chg " + (m.change_30d > 0.005 ? "up" : m.change_30d < -0.005 ? "down" : "flat")}>{chg(m.change_30d)}</span></div>
            ))}
            {!movers.length && <p className="note">{t("common.none")}</p>}
          </div>
        </div>
      </div>
      <div className="split">
        <div className="pane">
          <div className="phead"><h4>{t("ad.co")}</h4><span className="note">{t("ad.clickrow")}</span></div>
          {cos.data ? <CompanyTable rows={cos.data} onPick={(c) => onPick(c.ticker)} /> : <p className="note">{t("common.loading")}</p>}
        </div>
        <div className="pane">
          <h4>{t("ad.feed")}</h4>
          <div className="feed">
            {s.activity.slice(0, 12).map((a, i) => {
              const done = resolvedAct.has(a);
              const col = a.kind === "issued" || a.kind === "anchored" ? "--gold-mark" : a.kind === "revalued" ? "--c3" : a.kind.startsWith("dividend") ? "--c5" : a.kind === "rejected" || isSyncFailure(a.kind) ? "--down" : "--up";
              const lbl = t(("ev." + a.kind) as DictKey);
              const known = !lbl.startsWith("ev.");
              // the server text is English; keep it only where it carries numbers or an error
              const keepText = !known || ["issued", "minted", "revalued", "dividend_created", "sync_failed", "sync_skipped"].includes(a.kind);
              const extra = keepText && a.text && a.text.toLowerCase() !== lbl.toLowerCase() && a.text.toLowerCase() !== a.kind.replace(/_/g, " ") ? a.text : (!a.tx_hash && a.chain ? chainOf(a.chain).name : null);
              return (
                <div key={i} className={done ? "resolved" : undefined}>
                  <i style={{ background: `var(${col})` }} />
                  <span>{a.ticker ? <b className="mono">{a.ticker}</b> : null} · {known ? lbl : a.kind.replace(/_/g, " ")}{done ? <span className="resolvedtag">✓ {t("ev.resolved")}</span> : null}{extra ? <span className="muted" title={extra}> · {extra.length > 90 ? extra.slice(0, 90) + "…" : extra}</span> : null}
                    {a.tx_hash ? <> · <a className="mono" style={{ fontSize: ".74rem" }} href={chainOf(a.chain).txUrl(a.tx_hash)} target="_blank" rel="noopener noreferrer">{shortAddr(a.tx_hash)}</a></> : null}</span>
                  <em>{ago(a.at)}</em>
                </div>
              );
            })}
            {!s.activity.length && <p className="note">{t("c.ev.empty")}</p>}
          </div>
        </div>
      </div>
    </div>
  );
}

/* ================= approvals ================= */
type HolderLike = { name: string; wallet: string; pct?: number; shares?: number };
function holdersOf(c: ApprovalCompany): HolderLike[] { return Array.isArray(c.holders) ? c.holders : []; }

function IssueReview({ c, signer, onAct }: { c: ApprovalCompany; signer?: string | null; onAct: (fn: () => Promise<unknown>) => Promise<void> }) {
  const { t, fmt } = useI18n();
  const hs = holdersOf(c);
  const n = hs.length || (typeof c.holders === "number" ? c.holders : 0);
  const [reason, setReason] = useState("");
  const txs = [
    t("tx.reg"), t("tx.kycrole"), t("tx.tokN", { tk: c.ticker }), t("tx.div"),
    t("tx.kycN", { n }), t("tx.gasN", { n }), t("tx.mintN", { s: fmt(c.total_shares), tk: c.ticker, n }), t("tx.valN"),
  ];
  return (
    <div className="cols">
      <div className="approve">
        <dl className="kv">
          <dt>{t("s6.net")}</dt><dd>BlockID Chain · 262626</dd>
          <dt>{t("s6.token")}</dt><dd>{c.ticker} · decimals 0 · {fmt(c.total_shares)} × A${fmt(Number(c.share_price_aud ?? 1), 2)}</dd>
          <dt>{t("s6.txn")}</dt><dd>3 deploy · 1 role · {n} KYC · ≤{n} gas · {n} mint · 1 valuation</dd>
          <dt>{t("s6.signer")}</dt><dd>issuer-service {signer ? shortAddr(signer) : "0x2567…5ddf"}</dd>
        </dl>
        {hs.length > 0 && (
          <div className="tbl"><table>
            <thead><tr><th>{t("t.holder")}</th><th>{t("t.wallet")}</th><th className="r">%</th><th className="r">{t("t.shares")}</th></tr></thead>
            <tbody>{hs.map((h, i) => <tr key={i}><td>{h.name}</td><td className="mono" style={{ fontSize: ".78rem" }} title={h.wallet}>{shortAddr(h.wallet)}</td><td className="r">{h.pct != null ? fmt(Number(h.pct), 2) : "–"}</td><td className="r">{h.shares != null ? fmt(Number(h.shares)) : "–"}</td></tr>)}</tbody>
          </table></div>
        )}
        <div className="field">
          <button className="btn gold" type="button" onClick={() => onAct(() => api.approveIssue(c.id))}>{t("s6.sign")}</button>
        </div>
        <div className="field">
          <input className="inp" placeholder={t("ap.reason")} aria-label={t("ap.reason")} value={reason} onChange={(e) => setReason(e.target.value)} style={{ flex: 1 }} />
          <button className="btn danger sm" type="button" onClick={() => onAct(() => api.rejectCompany(c.id, reason || "rejected by admin"))}>{t("s6.reject")}</button>
        </div>
      </div>
      <div className="txs" aria-label={t("ap.txs")}>
        {txs.map((x, i) => <div key={i}><span className="dot wait" /><span>{x}</span><span className="h" /><span className="h">{i === 0 ? t("tx.wait") : ""}</span></div>)}
      </div>
    </div>
  );
}

/* ================= queues: one item at a time, in flow order ================= */
type Act = (fn: () => Promise<unknown>, okMsg?: string) => Promise<void>;

function ReturnBanner({ back }: { back: string }) {
  const { t } = useI18n();
  return (
    <div className="retbanner" role="note">
      <span><b>{t("ad.ret.h")}</b> · {t("ad.ret.p", { p: back })}</span>
      <Link className="btn ghost sm" to={back}>{t("ad.ret.back")}</Link>
    </div>
  );
}

function ValuationItem({ v, busy, act }: { v: Valuation; busy: boolean; act: Act }) {
  const { t, fmt, money, date } = useI18n();
  return (
    <div className="pane">
      <div className="between">
        <span><b style={{ overflowWrap: "anywhere" }}>{v.url.replace(/^https?:\/\//, "")}</b> <span className="muted-sm">{v.requested_by ? t("ap.req", { w: shortAddr(v.requested_by) || v.requested_by }) : ""} · {v.created_at ? date(v.created_at, true) : ""}</span></span>
        {v.svi && <span className="row"><span className="gchip" style={{ background: "var(--c3)" }}>{bandGrade(v.svi)}</span><span className="num">SVI {fmt(v.svi.index, 1)}</span></span>}
      </div>
      {v.svi && (
        <div className="kpis">
          <div className="kpi"><small>{t("ad.qv.mid")}</small><b>{money(v.svi.valuation_mid_aud)}</b><span>{money(v.svi.valuation_low_aud)} – {money(v.svi.valuation_high_aud)}</span></div>
          <div className="kpi"><small>{t("s2.src")}</small><b>{fmt(v.counters?.sources ?? 0)}</b><span>{t("s2.comp")}: {fmt(v.counters?.competitors ?? v.competitors?.length ?? 0)}</span></div>
          <div className="kpi"><small>{t("v.warn")}</small><b>{fmt((v.warnings ?? []).length)}</b><span>{(v.warnings ?? [])[0] ?? " "}</span></div>
        </div>
      )}
      {(v.warnings ?? []).length > 0 && <div className="banner warn">{(v.warnings ?? []).map((w, i) => <span key={i}>· {w}</span>)}</div>}
      <p className="note">{t("ad.qv.note")}</p>
      <div className="row">
        <Link className="btn ghost sm" to={`/v/${encodeURIComponent(v.id)}/report`}>{t("ap.open")}</Link>
        <span className="grow" />
        <button className="btn danger sm" type="button" disabled={busy} onClick={() => act(() => api.decide(v.id, false), t("ap.rejected"))}>{t("ap.reject")}</button>
        <button className="btn gold" type="button" disabled={busy} onClick={() => act(() => api.decide(v.id, true), t("v.adm.done"))}>{t("s3.approve")}</button>
      </div>
    </div>
  );
}

function IssuanceItem({ c, signer, wallets, act }: { c: ApprovalCompany; signer?: string | null; wallets?: AdminWallets | null; act: Act }) {
  const { t, fmt, money } = useI18n();
  return (
    <div className="pane">
      <div className="between">
        <span><b className="mono">{c.ticker}</b> · {c.name} <span className="muted-sm">· {money(Number(c.valuation_aud))} · {fmt(Number(c.total_shares))} {t("t.shares").toLowerCase()} · {t("ap.holders", { n: holdersOf(c).length || Number(c.holders) || 0 })}{c.created_by ? " · " + t("ap.req", { w: shortAddr(c.created_by) || c.created_by }) : ""}</span></span>
        <Link className="btn ghost sm" to={`/c/${c.ticker}/issue`}>{t("ad.co.open")}</Link>
      </div>
      <p className="note">{t("trk.approve")}: BlockID Chain → Ethereum Hoodi → HashKey Chain testnet</p>
      <LowBalanceBanner wallets={wallets} compact />
      {c.error && <ErrorFix error={c.error} info={c.error_info} ticker={c.ticker} companyId={c.local_token ? c.id : null} />}
      <IssueReview c={c} signer={signer} onAct={(fn) => act(fn)} />
    </div>
  );
}

function SyncItem({ c, busy, act }: { c: ApprovalCompany; busy: boolean; act: Act }) {
  const { t } = useI18n();
  return (
    <div className="pane">
      <div className="between">
        <span><b className="mono">{c.ticker}</b> · {c.name} <span className="muted-sm">· {c.local_token ? shortAddr(c.local_token) : ""}</span></span>
        <Link className="btn ghost sm" to={`/c/${c.ticker}/sync`}>{t("ad.co.open")}</Link>
      </div>
      <SyncChips sync={c.sync} />
      {c.error ? (
        <ErrorFix error={c.error} info={c.error_info} ticker={c.ticker} companyId={c.id} onDone={() => void act(async () => undefined)} />
      ) : (
        <div className="row"><span className="grow" /><button className="btn gold" type="button" disabled={busy} onClick={() => act(() => api.approveAnchor(c.id))}>{t("trk.resync")}</button></div>
      )}
    </div>
  );
}

function MintItem({ m, busy, act }: { m: MintReq; busy: boolean; act: Act }) {
  const { t, fmt } = useI18n();
  return (
    <div className="pane">
      <div className="between">
        <span><b className="mono">{m.ticker}</b> · {t("ap.mintrow", { n: fmt(Number(m.shares)), tk: m.ticker ?? "", name: m.holder_name })} <span className="muted-sm mono" title={m.to_wallet}>{shortAddr(m.to_wallet)}</span></span>
        {m.ticker && <Link className="btn ghost sm" to={`/c/${m.ticker}/cap-table`}>{t("ad.co.open")}</Link>}
      </div>
      <p className="note">{m.reason || "–"}{m.requested_by ? " · " + t("ap.req", { w: shortAddr(m.requested_by) || m.requested_by }) : ""}</p>
      <div className="row">
        <span className="grow" />
        <button className="btn danger sm" type="button" disabled={busy} onClick={() => act(() => api.rejectMint(m.id, "rejected by admin"), t("ap.rejected"))}>{t("ap.reject")}</button>
        <button className="btn gold" type="button" disabled={busy} onClick={() => act(() => api.approveMint(m.id))}>{t("ap.approve")}</button>
      </div>
    </div>
  );
}

function DividendItem({ d, busy, act }: { d: DividendReq; busy: boolean; act: Act }) {
  const { t, fmt } = useI18n();
  return (
    <div className="pane">
      <div className="between">
        <span><b className="mono">{d.ticker}</b> · {t("ap.divrow", { n: fmt(d.total_maud ?? d.total_units / 1e6, 2), tk: d.ticker ?? "" })}{d.holders ? " · " + t("ap.holders", { n: d.holders }) : ""}</span>
        <span className="merkle">{d.merkle_root ? shortAddr(d.merkle_root) : ""}</span>
      </div>
      <div className="row">
        <span className="grow" />
        <button className="btn danger sm" type="button" disabled={busy} onClick={() => act(() => api.rejectDividend(d.id, "rejected by admin"), t("ap.rejected"))}>{t("ap.reject")}</button>
        <button className="btn gold" type="button" disabled={busy} onClick={() => act(() => api.approveDividend(d.id))}>{t("ap.approve")}</button>
      </div>
    </div>
  );
}

function UpdateItem({ u, busy, act }: { u: BizUpdate; busy: boolean; act: Act }) {
  const { t, date } = useI18n();
  const [reason, setReason] = useState("");
  return (
    <div className="pane">
      <div className="between">
        <span><b className="mono">{u.ticker}</b> · {u.company} · <b>{u.title}</b> <span className="muted-sm">· {t("upd.period", { c: t(("upd.cad." + u.cadence) as DictKey), p: u.period_label })}{u.created_by ? " · " + t("ap.req", { w: shortAddr(u.created_by) || u.created_by }) : ""}{u.updated_at ? " · " + date(u.updated_at, true) : ""}</span></span>
        <span className="row" style={{ gap: 8 }}><StatusPill s={u.status} /><Link className="btn ghost sm" to={`/c/${u.ticker}/updates`}>{t("ad.co.open")}</Link></span>
      </div>
      {u.status === "failed" && u.error && <p className="banner warn">{t("upd.failed", { e: u.error })}</p>}
      <p className="note">{t("upd.ad.p")}</p>
      <UpdateView u={u} />
      <label className="lf"><span>{t("upd.ad.reason")}</span><input value={reason} maxLength={1000} onChange={(e) => setReason(e.target.value)} /></label>
      <div className="row">
        <span className="grow" />
        <button className="btn danger sm" type="button" disabled={busy} onClick={() => act(() => api.rejectUpdate(u.id, reason.trim() || "rejected by admin"), t("upd.ad.rejected"))}>{t("upd.ad.reject")}</button>
        <button className="btn gold" type="button" disabled={busy} onClick={() => act(() => api.approveUpdate(u.id), t("upd.ad.published"))}>{t("upd.ad.approve")}</button>
      </div>
    </div>
  );
}

function PolicyItem({ p, busy, act }: { p: DividendPolicy; busy: boolean; act: Act }) {
  const { t, date } = useI18n();
  const [reason, setReason] = useState("");
  return (
    <div className="pane">
      <div className="between">
        <span><b className="mono">{p.ticker}</b> · {p.company_name} <span className="muted-sm">{p.created_by ? "· " + t("pol.ad.by", { w: shortAddr(p.created_by) || p.created_by }) : ""}{p.updated_at ? " · " + date(p.updated_at, true) : ""}</span></span>
        <span className="row" style={{ gap: 8 }}><PolicyPill s={p.status} />{p.ticker && <Link className="btn ghost sm" to={`/c/${p.ticker}/dividends`}>{t("ad.co.open")}</Link>}</span>
      </div>
      <p className="note">{t("pol.ad.p")}</p>
      <div className="pane"><PolicySummary p={p} /></div>
      <label className="lf"><span>{t("pol.ad.reason")}</span><input value={reason} maxLength={1000} onChange={(e) => setReason(e.target.value)} /></label>
      <div className="row">
        <span className="grow" />
        <button className="btn danger sm" type="button" disabled={busy} onClick={() => act(() => api.rejectPolicy(p.id, reason.trim() || "rejected by admin"), t("pol.ad.rejected"))}>{t("pol.ad.reject")}</button>
        <button className="btn gold" type="button" disabled={busy} onClick={() => act(() => api.approvePolicy(p.id), t("pol.ad.approved"))}>{t("pol.ad.approve")}</button>
      </div>
    </div>
  );
}

type AnyItem = Valuation | ApprovalCompany | MintReq | DividendReq | BizUpdate | DividendPolicy | Offering;
const keyOf = (q: QueueKey, x: AnyItem): string =>
  q === "valuations" || q === "updates" ? (x as Valuation | BizUpdate).id : q === "issuance" || q === "sync" ? (x as ApprovalCompany).ticker : String((x as MintReq).id);
function itemLabel(q: QueueKey, x: AnyItem): string {
  if (q === "valuations") return (x as Valuation).url.replace(/^https?:\/\//, "");
  if (q === "updates") return `${(x as BizUpdate).ticker} · ${(x as BizUpdate).title}`;
  if (q === "policies") return `${(x as DividendPolicy).ticker ?? ""} · ${(x as DividendPolicy).company_name ?? ""}`;
  if (q === "offerings") return `${(x as Offering).ticker ?? ""} · ${(x as Offering).company_name ?? ""} · #${(x as Offering).id}`;
  if (q === "issuance" || q === "sync") return `${(x as ApprovalCompany).ticker} · ${(x as ApprovalCompany).name}`;
  return `${(x as MintReq).ticker ?? ""} #${(x as MintReq).id}`;
}

function QueueView({ q, ap, wallets, onChanged }: { q: QueueKey; ap: Async<Approvals>; wallets?: AdminWallets | null; onChanged: () => void }) {
  const { t } = useI18n();
  const { item } = useParams();
  const [params] = useSearchParams();
  const back = safeNext(params.get("return"));
  const nav = useNavigate();
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; s: string } | null>(null);
  const items = queueItems(ap.data)[q] as AnyItem[];
  const found = item ? items.findIndex((x) => keyOf(q, x) === item) : 0;
  const idx = found < 0 ? 0 : found;
  const cur = items[idx];
  const base = `/admin/${q}`;
  const go = (i: number) => { const x = items[i]; if (x) nav(`${base}/${encodeURIComponent(keyOf(q, x))}${back ? "?return=" + encodeURIComponent(back) : ""}`); };
  useEffect(() => {
    const on = (e: KeyboardEvent) => {
      const el = document.activeElement as HTMLElement | null;
      if (e.altKey || e.ctrlKey || e.metaKey || (el && /^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName))) return;
      if (e.key === "j" && idx < items.length - 1) go(idx + 1);
      if (e.key === "k" && idx > 0) go(idx - 1);
    };
    window.addEventListener("keydown", on);
    return () => window.removeEventListener("keydown", on);
  }); // eslint-disable-line react-hooks/exhaustive-deps

  const act: Act = async (fn, okMsg = t("ap.sent")) => {
    setBusy(true); setMsg(null);
    const after = items[idx + 1] ?? items[idx - 1];
    try {
      await fn();
      await ap.reload(); onChanged();
      if (back) { nav(back, { state: { flash: okMsg } }); return; }
      setMsg({ ok: true, s: okMsg });
      nav(after ? `${base}/${encodeURIComponent(keyOf(q, after))}` : base, { replace: true });
    } catch (e) { setMsg({ ok: false, s: errText(e, t) }); }
    finally { setBusy(false); }
  };

  if (!ap.data) return ap.error ? <ErrorBox error={ap.error} retry={ap.reload} /> : <p className="note">{t("common.loading")}</p>;
  const qi = QUEUES.findIndex((x) => x.key === q);
  const counts = queueCounts(ap.data);
  const nextQ = QUEUES.slice(qi + 1).find((x) => counts[x.key] > 0) ?? QUEUES.slice(0, qi).find((x) => counts[x.key] > 0);
  return (
    <div className="stack" aria-busy={busy}>
      {back && <ReturnBanner back={back} />}
      {msg && <p className={"banner " + (msg.ok ? "ok" : "bad")} role={msg.ok ? "status" : "alert"}>{msg.s}</p>}
      {item && found < 0 && items.length > 0 && <p className="banner warn" role="status">{t("ad.q.gone")}</p>}
      {!cur ? (
        <div className="pane">
          <p style={{ margin: 0 }}>{item && back ? t("ad.q.done") : t("ad.q.empty")}</p>
          <div className="row">
            {back && <Link className="btn sm" to={back}>{t("ad.ret.go")} →</Link>}
            <Link className="btn ghost sm" to="/admin">{t("ad.nav.inbox")}</Link>
            {nextQ && <Link className={"btn sm" + (back ? " ghost" : "")} to={`/admin/${nextQ.key}`}>{t("ad.q.nextq", { q: t(("ad.q." + nextQ.key) as DictKey) })} →</Link>}
          </div>
        </div>
      ) : (
        <>
          <div className="qhead">
            <span>{t("ad.q.pos", { i: idx + 1, n: items.length })}</span>
            <span className="row" style={{ gap: 6 }}>
              <span className="hint">{t("ad.q.keys")}</span>
              <button className="btn ghost sm" type="button" disabled={idx === 0} onClick={() => go(idx - 1)}>↑ {t("ad.q.prev")}</button>
              <button className="btn ghost sm" type="button" disabled={idx >= items.length - 1} onClick={() => go(idx + 1)}>{t("ad.q.next")} ↓</button>
            </span>
          </div>
          {q === "valuations" && <ValuationItem key={keyOf(q, cur)} v={cur as Valuation} busy={busy} act={act} />}
          {q === "issuance" && <IssuanceItem key={keyOf(q, cur)} c={cur as ApprovalCompany} signer={wallets?.issuer?.address} wallets={wallets} act={act} />}
          {q === "sync" && <SyncItem key={keyOf(q, cur)} c={cur as ApprovalCompany} busy={busy} act={act} />}
          {q === "mints" && <MintItem key={keyOf(q, cur)} m={cur as MintReq} busy={busy} act={act} />}
          {q === "dividends" && <DividendItem key={keyOf(q, cur)} d={cur as DividendReq} busy={busy} act={act} />}
          {q === "updates" && <UpdateItem key={keyOf(q, cur)} u={cur as BizUpdate} busy={busy} act={act} />}
          {q === "policies" && <PolicyItem key={keyOf(q, cur)} p={cur as DividendPolicy} busy={busy} act={act} />}
          {q === "offerings" && <OfferingQueueItem key={keyOf(q, cur)} o={cur as Offering} busy={busy} act={act} />}
          {items.length > 1 && (
            <div className="pane">
              <h4>{t(("ad.q." + q) as DictKey)} · {items.length}</h4>
              <ol className="qlist">
                {items.map((x, i) => (
                  <li key={keyOf(q, x)}><Link to={`${base}/${encodeURIComponent(keyOf(q, x))}${back ? "?return=" + encodeURIComponent(back) : ""}`} aria-current={i === idx ? "true" : undefined}><span className="mono">{String(i + 1).padStart(2, "0")}</span>{itemLabel(q, x)}</Link></li>
                ))}
              </ol>
            </div>
          )}
        </>
      )}
    </div>
  );
}

function Inbox({ ap, nTr }: { ap: Async<Approvals>; nTr: number | null }) {
  const { t } = useI18n();
  if (!ap.data) return ap.error ? <ErrorBox error={ap.error} retry={ap.reload} /> : <p className="note">{t("common.loading")}</p>;
  const items = queueItems(ap.data);
  const counts = queueCounts(ap.data);
  const total = counts.total + (nTr ?? 0);
  const first = QUEUES.find((x) => counts[x.key] > 0);
  return (
    <div className="stack">
      {first ? (
        <div className="nextact">
          <div><span className="eyebrow">{t("ws.next")}</span><p>{t("ad.inbox.first", { q: t(("ad.q." + first.key) as DictKey), n: counts[first.key] })}</p></div>
          <Link className="btn gold" to={`/admin/${first.key}`}>{t("ad.review")} <span aria-hidden="true">→</span></Link>
        </div>
      ) : <p className="empty">{total ? t("ad.inbox.onlytr") : t("ap.empty")}</p>}
      <div className="pane">
        <div className="tbl"><table>
          <thead><tr><th>{t("ad.inbox.q")}</th><th className="r">{t("ad.inbox.n")}</th><th>{t("ad.inbox.oldest")}</th><th /></tr></thead>
          <tbody>
            {QUEUES.map((x, i) => {
              const list = items[x.key] as AnyItem[];
              return (
                <tr key={x.key}>
                  <td><span className="mono muted">{i + 1}</span> {x.gate && <span className="gdiamond" aria-hidden="true">◆</span>} <Link to={`/admin/${x.key}`}>{t(("ad.q." + x.key) as DictKey)}</Link></td>
                  <td className="r"><b>{list.length}</b></td>
                  <td className="muted-sm">{list[0] ? itemLabel(x.key, list[0]) : "–"}</td>
                  <td className="r">{list.length ? <Link className="btn ghost sm" to={`/admin/${x.key}`}>{t("ad.review")}</Link> : <span className="pill ok">✓</span>}</td>
                </tr>
              );
            })}
            <tr>
              <td><span className="mono muted">{QUEUES.length + 1}</span> <Link to="/admin/transfers">{t("ad.q.transfers")}</Link></td>
              <td className="r"><b>{nTr ?? "–"}</b></td><td className="muted-sm">–</td>
              <td className="r">{nTr ? <Link className="btn ghost sm" to="/admin/transfers">{t("ad.review")}</Link> : <span className="pill ok">✓</span>}</td>
            </tr>
          </tbody>
        </table></div>
        <p className="note">{t("ad.inbox.p")}</p>
      </div>
    </div>
  );
}

/* ================= companies ================= */
function Revalue({ c, cur, onDone }: { c: { id: number; ticker: string; total_shares: number; valuation_aud: number }; cur: number; onDone: () => void }) {
  const { t, fmt, aud, chg } = useI18n();
  const [val, setVal] = useState(String(Math.round(c.valuation_aud)));
  const [note, setNote] = useState("");
  const [msg, setMsg] = useState<{ ok: boolean; s: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const v = Number(val) || 0;
  const mark = v / (c.total_shares || 1);
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!(v > 0)) return;
    setBusy(true); setMsg(null);
    try {
      const r = await api.revalue(c.id, v, note.trim());
      setMsg({ ok: true, s: `${t("rv.ok")} ${aud(Number(r?.mark_aud ?? mark), 4)}${r?.issuer ? " · issuer: " + r.issuer : ""}` });
      onDone();
    } catch (x) { setMsg({ ok: false, s: errText(x, t) }); }
    finally { setBusy(false); }
  };
  return (
    <form className="pane" onSubmit={submit}>
      <h4>{t("rv.h")} · {c.ticker}</h4>
      <p className="note">{t("rv.p")}</p>
      <div className="fgrid">
        <label className="lf"><span>{t("rv.val")}</span><input type="number" min={1} step={1000} value={val} onChange={(e) => setVal(e.target.value)} /></label>
        <label className="lf"><span>{t("rv.note")}</span><input value={note} onChange={(e) => setNote(e.target.value)} maxLength={200} /></label>
      </div>
      <p className="sub">{t("rv.newmark", { m: aud(mark, 4), p: chg(cur ? (mark / cur - 1) * 100 : 0) })} · {fmt(c.total_shares)} {t("t.shares").toLowerCase()}</p>
      <button className="btn gold" type="submit" disabled={busy || !(v > 0)} style={{ justifySelf: "start" }}>{t("rv.go")}</button>
      {msg && <p className={msg.ok ? "toast" : "err"} role={msg.ok ? "status" : "alert"}>{msg.s}</p>}
    </form>
  );
}

function CompanyDetailPane({ tk, row, onChanged }: { tk: string; row?: AdminCompany; onChanged: () => void }) {
  const { t } = useI18n();
  const d = useAsync(() => api.company(tk), [tk], POLL);
  const [msg, setMsg] = useState<{ ok: boolean; s: string } | null>(null);
  const c = d.data;
  const id = c?.id ?? row?.id;
  const status = c?.status ?? row?.status;
  const act = async (fn: () => Promise<unknown>) => {
    setMsg(null);
    try { await fn(); setMsg({ ok: true, s: t("ap.sent") }); await d.reload(); onChanged(); }
    catch (e) { setMsg({ ok: false, s: errText(e, t) }); }
  };
  const onchain = status === "issued" || status === "pending_anchor" || status === "anchoring" || status === "anchored" || status === "partially_anchored";
  const localToken = c?.local?.token ?? c?.local_token ?? row?.local_token;
  return (
    <div style={{ display: "grid", gap: 16 }}>
      <div className="between">
        <span className="row"><b className="mono" style={{ fontSize: "1.1rem" }}>{tk}</b><span>{c?.name ?? row?.name}</span>{status && <span className="pill">{t(("c.st." + status) as DictKey)}</span>}</span>
        <span className="row">
          {id != null && status === "pending_issue" && <button className="btn gold sm" type="button" onClick={() => act(() => api.approveIssue(id))}>{t("s6.sign")}</button>}
          {id != null && (status === "issued" || status === "pending_anchor" || status === "partially_anchored" || (status === "anchored" && c?.sync && (c.sync.hoodi !== "done" || c.sync.hsk !== "done"))) && <button className="btn gold sm" type="button" onClick={() => act(() => api.approveAnchor(id))}>{t("trk.resync")}</button>}
          {id != null && status === "failed" && <button className="btn gold sm" type="button" onClick={() => act(() => (c?.local?.block ? api.approveAnchor(id) : api.approveIssue(id)))}>{t("common.retry")}</button>}
          {id != null && status && ["draft", "pending_issue", "issued", "pending_anchor", "failed"].includes(status) && <button className="btn danger sm" type="button" onClick={() => act(() => api.rejectCompany(id, "rejected by admin"))}>{t("ap.reject")}</button>}
          {id != null && localToken && status !== "issuing" && <button className="btn ghost sm" type="button" onClick={() => act(() => api.refreshCompany(id))}>{t("fix.refresh")}</button>}
          <Link className="btn ghost sm" to={`/c/${tk}`}>{t("ad.co.open")}</Link>
        </span>
      </div>
      {msg && <p className={"banner " + (msg.ok ? "ok" : "bad")} role={msg.ok ? "status" : "alert"}>{msg.s}</p>}
      {(c?.error || row?.error) && (
        <ErrorFix error={c?.error || row?.error} info={c?.error_info ?? row?.error_info ?? null} ticker={tk}
          companyId={localToken ? id : null} onDone={() => { void d.reload(); onChanged(); }} />
      )}
      {d.error && !c ? <ErrorBox error={d.error} retry={d.reload} /> : null}
      {c && c.marks?.length ? (
        <MarkPanel kpis ticker={c.ticker} name={c.name} grade={c.grade ?? "C"} svi={c.svi} marks={c.marks} events={c.events} valuation={c.valuation_aud} totalShares={c.total_shares} holders={c.cap_table?.length ?? c.holders ?? 0} />
      ) : null}
      {c && id != null && onchain && localToken && <Revalue c={{ id, ticker: c.ticker, total_shares: c.total_shares, valuation_aud: c.valuation_aud }} cur={c.mark_aud} onDone={() => { void d.reload(); onChanged(); }} />}
      <CompanyAdminsPanel ticker={tk} onChanged={() => void d.reload()} />
      {c && <div className="pane"><h4>{t("c.ev")}</h4><EventList events={c.events ?? []} sync={c.sync} /></div>}
    </div>
  );
}

function CompaniesTab({ onChanged }: { onChanged: () => void }) {
  const { item } = useParams();
  const nav = useNavigate();
  const sel = item ? item.toUpperCase() : null;
  const setSel = (tk: string) => nav(`/admin/companies/${tk}`);
  const { t, fmt, money, date } = useI18n();
  const all = useAsync(() => api.adminCompanies(), [], POLL);
  const rows = all.data ?? [];
  const row = rows.find((r) => r.ticker === sel);
  return (
    <div style={{ display: "grid", gap: 16 }}>
      <div className="pane">
        <div className="phead"><h4>{t("ad.co")}</h4><span className="note">{t("ad.clickrow")}</span></div>
        {all.error ? <ErrorBox error={all.error} retry={all.reload} /> : (
          <div className="tbl">
            <table className="ctable">
              <thead><tr><th>{t("ad.c.tk")}</th><th>{t("ad.c.name")}</th><th>{t("ad.w.status")}</th><th className="r">{t("ad.c.val")}</th><th className="r">{t("k.shares")}</th><th className="r">{t("ad.c.hold")}</th><th>{t("ap.req", { w: "" }).trim()}</th><th>{t("ad.w.since")}</th></tr></thead>
              <tbody>
                {rows.map((c) => (
                  <tr key={c.id} tabIndex={0} aria-selected={c.ticker === sel} onClick={() => setSel(c.ticker)} onKeyDown={(e) => { if (e.key === "Enter") setSel(c.ticker); }}>
                    <td className="mono" style={{ fontWeight: 600 }}>{c.ticker}</td>
                    <td>{c.name}</td>
                    <td><span className={"pill" + (c.status === "anchored" ? " ok" : c.status === "failed" || c.status === "rejected" ? " bad" : c.status === "pending_issue" || c.status === "issued" || c.status === "pending_anchor" || c.status === "partially_anchored" ? " gold" : "")}>{t(("c.st." + c.status) as DictKey)}</span>{c.status !== "draft" && c.status !== "pending_issue" && c.status !== "rejected" ? <div style={{ marginTop: 4 }}><SyncChips sync={c.sync} /></div> : null}</td>
                    <td className="r">{money(Number(c.valuation_aud))}</td>
                    <td className="r">{fmt(Number(c.total_shares))}</td>
                    <td className="r">{Array.isArray(c.holders) ? c.holders.length : c.holders ?? "–"}</td>
                    <td className="mono muted-sm" title={c.created_by ?? ""}>{c.created_by?.startsWith("0x") ? shortAddr(c.created_by) : c.created_by}</td>
                    <td className="muted-sm">{c.created_at ? date(c.created_at) : ""}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
      {sel ? <CompanyDetailPane key={sel} tk={sel} row={row} onChanged={() => { void all.reload(); onChanged(); }} /> : <p className="empty">{t("ad.co.pick")}</p>}
    </div>
  );
}

function TransfersTab({ onChanged }: { onChanged: () => void }) {
  const all = useAsync(() => api.adminCompanies(), [], POLL);
  const rows = (all.data ?? []).map((c) => ({ id: c.id, ticker: c.ticker, name: c.name, local_token: c.local_token,
    transfer_mode: (c as { transfer_mode?: "free" | "approval" }).transfer_mode }));
  return <AdminTransfersTab companies={rows} onChanged={() => { void all.reload(); onChanged(); }} />;
}

/* ================= wallets ================= */
function WalletsTab() {
  const { t, date, fmt } = useI18n();
  const w = useAsync(() => api.adminWallets(), []);
  const iw = useAsync(() => api.issuerWallets(), []);
  const [addr, setAddr] = useState("");
  const [label, setLabel] = useState("");
  const [err, setErr] = useState("");
  const [confirm, setConfirm] = useState<string | null>(null);
  const [msg, setMsg] = useState("");
  const add = async (e: React.FormEvent) => {
    e.preventDefault();
    const a = isAddressValid(addr);
    if (!a) { setErr(addrError(t, addr) || t("ad.bad.addr")); return; }
    if (!label.trim()) { setErr(t("ad.bad.label")); return; }
    setErr("");
    try { await api.addIssuerWallet(a, label.trim()); setAddr(""); setLabel(""); await iw.reload(); }
    catch (x) { setErr(errText(x, t)); }
  };
  const revoke = async (x: IssuerWallet) => {
    if (confirm !== x.address) { setConfirm(x.address); return; }
    setConfirm(null);
    try { await api.revokeIssuerWallet(x.address); setMsg(""); await iw.reload(); }
    catch (e) { setMsg(errText(e, t)); }
  };
  // balances arrive as wei strings; show whole units (18 decimals)
  const bal = (v: unknown) => (v == null || v === "" ? "–" : fmt(Number(BigInt(String(v)) / 10n ** 12n) / 1e6, 4));
  const svc = [["ad.aw.issuer", w.data?.issuer], ["ad.aw.relayer", w.data?.relayer]] as const;
  return (
    <div style={{ display: "grid", gap: 16 }}>
      <LowBalanceBanner wallets={w.data} />
      <div className="adminwallet">
        <span className="eyebrow" style={{ color: "var(--gold)" }}>{t("ad.aw.list")}</span>
        {w.error ? <ErrorBox error={w.error} retry={w.reload} /> : !w.data ? <span className="note">{t("common.loading")}</span> : (
          <>
            {w.data.admins.map((a) => <span className="full" key={a}><a href={CHAINS.local.addrUrl(a)} target="_blank" rel="noopener noreferrer" style={{ color: "inherit" }}>{a}</a></span>)}
            <span className="eyebrow" style={{ color: "var(--gold)", marginTop: 6 }}>{t("ad.aw.svc")}</span>
            {svc.map(([k, x]) => (
              <span key={k} style={{ display: "grid", gap: 2 }}>
                <span className="muted-sm">{t(k)}</span>
                <span className="full">{x?.address ?? "–"}</span>
                {x?.address && <span className="note">{t("ad.aw.bal", { a: bal(x.local_balance), b: bal(x.hoodi_balance), c: bal((x as { hsk_balance?: unknown }).hsk_balance) })}</span>}
              </span>
            ))}
            <span className="note">{t("lb.gas")}</span>
            <span className="note">{t("ad.awnote")}</span>
          </>
        )}
      </div>
      <div className="pane">
        <div className="phead"><h4>{t("ad.iw")}</h4><span className="note mono">ISSUER_ROLE</span></div>
        <form className="addform" onSubmit={add} noValidate>
          <input className={"mono" + (addrError(t, addr) ? " bad" : "")} placeholder="0x… wallet address" aria-label={t("t.wallet")} aria-invalid={!!addrError(t, addr)} title={addrError(t, addr) || undefined} value={addr} onChange={(e) => { setAddr(e.target.value.trim()); setErr(addrError(t, e.target.value.trim())); }} spellCheck={false} />
          <input placeholder={t("ad.w.label")} aria-label={t("ad.w.label")} value={label} onChange={(e) => setLabel(e.target.value)} />
          <button className="btn sm" type="submit">{t("ad.grant")}</button>
        </form>
        <p className="err" role="alert">{err || msg}</p>
        {iw.error ? <ErrorBox error={iw.error} retry={iw.reload} /> : (iw.data ?? []).length === 0 ? <p className="note">{iw.loading ? t("common.loading") : t("ad.iw.empty")}</p> : (
          <div className="tbl"><table>
            <thead><tr><th>{t("ad.w.label")}</th><th>{t("t.wallet")}</th><th>{t("ad.w.status")}</th><th>{t("ad.w.since")}</th><th /></tr></thead>
            <tbody>
              {(iw.data ?? []).map((x) => (
                <tr key={x.address}>
                  <td>{x.label}</td>
                  <td className="mono" style={{ fontSize: ".8rem" }} title={x.address}>{shortAddr(x.address)}</td>
                  <td><span className={"status " + (x.status === "active" ? "active" : x.status === "revoked" ? "revoked" : "pending")}>{t(("ad.st." + (x.status === "active" || x.status === "revoked" ? x.status : "pending")) as DictKey)}</span></td>
                  <td className="muted">{x.status === "revoked" && x.revoked_at ? date(x.revoked_at) : x.granted_at ? date(x.granted_at) : "–"}</td>
                  <td className="r">
                    {x.status === "active" && (
                      <span className="row" style={{ justifyContent: "flex-end", gap: 8 }}>
                        <button type="button" className="linkbtn" onClick={() => revoke(x)}>{confirm === x.address ? t("ad.confirm") : t("ad.revoke")}</button>
                        {confirm === x.address && <button type="button" className="linkbtn" style={{ color: "var(--muted)" }} onClick={() => setConfirm(null)}>{t("common.cancel")}</button>}
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table></div>
        )}
      </div>
    </div>
  );
}

function AuditTab() {
  const { t, date } = useI18n();
  const a = useAsync(() => api.audit(), [], POLL);
  const col = (s: string) => (/revok|reject|fail|error/.test(s) ? "--c2" : /grant|approv|anchor|issue/.test(s) ? "--c1" : /request|submit|creat/.test(s) ? "--c4" : "--c3");
  const detail = (d: AuditRow["detail"]) => {
    if (!d || typeof d !== "object") return "";
    const e = Object.entries(d).filter(([, v]) => v != null && v !== "" && typeof v !== "object");
    return e.length ? " · " + e.map(([k, v]) => `${k}=${String(v)}`).join(", ") : "";
  };
  return (
    <div className="pane">
      <h4>{t("ad.audit")}</h4>
      {a.error ? <ErrorBox error={a.error} retry={a.reload} /> : (a.data ?? []).length === 0 ? <p className="note">{a.loading ? t("common.loading") : t("ad.audit.empty")}</p> : (
        <div className="feed">
          {(a.data ?? []).map((r) => (
            <div key={r.id}>
              <i style={{ background: `var(${col(r.action)})` }} />
              <span><span className="mono" title={r.actor}>{r.actor.startsWith("0x") ? shortAddr(r.actor) : r.actor}</span> · {r.action.replace(/_/g, " ")}{r.target ? <> · <b>{r.target.startsWith("0x") && r.target.length === 42 ? shortAddr(r.target) : r.target}</b></> : null}<span className="muted">{detail(r.detail)}</span></span>
              <em>{date(r.at, true)}</em>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/* ================= console ================= */
const SECTIONS = ["inbox", "dashboard", "valuations", "issuance", "sync", "mints", "dividends", "policies", "updates", "offerings", "transfers", "companies", "wallets", "audit", "ai", "ops"] as const;
type Section = (typeof SECTIONS)[number];

function Console({ onPwRequired }: { onPwRequired: () => void }) {
  const { t, fmt } = useI18n();
  const { me, logout } = useAuth();
  const { section: rawSec } = useParams();
  const section: Section = (SECTIONS as readonly string[]).includes(rawSec ?? "") ? (rawSec as Section) : "inbox";
  const visible = usePageVisible();
  const now = useNow(1000);
  const nav = useNavigate();
  const stats = useAsync(() => api.stats(), [], POLL);
  const cos = useAsync(() => api.companies(), [], POLL);
  const ap = useAsync(() => api.approvals(), [], POLL);
  const tr = useAsync(() => Promise.all([tapi.adminTransfers(), tapi.adminKyc()]), [], POLL);
  const wallets = useAsync(() => api.adminWallets(), [], 60000);
  const [updated, setUpdated] = useState(Date.now());
  useEffect(() => { if (stats.data) setUpdated(Date.now()); }, [stats.data]);
  useEffect(() => { if (pwRequired(ap.error) || pwRequired(wallets.error)) onPwRequired(); }, [ap.error, wallets.error, onPwRequired]);
  useEffect(() => { if (rawSec && rawSec !== section) nav("/admin", { replace: true }); }, [rawSec, section, nav]);
  const counts = useMemo(() => queueCounts(ap.data), [ap.data]);
  const nTr = tr.data ? [...tr.data[0], ...tr.data[1]].filter((x) => x.status === "pending" || x.status === "failed").length : null;
  const who = me?.address ? shortAddr(me.address) : me?.username ?? "admin";
  const refreshAll = () => { void stats.reload(); void cos.reload(); void ap.reload(); void tr.reload(); };
  const title: Record<Section, string> = {
    inbox: t("ad.nav.inbox"), dashboard: t("ad.t.ov"), valuations: t("ad.q.valuations"), issuance: t("ad.q.issuance"), sync: t("ad.q.sync"),
    mints: t("ad.q.mints"), dividends: t("ad.q.dividends"), policies: t("ad.q.policies"), updates: t("ad.q.updates"), offerings: t("ad.q.offerings"), transfers: t("ad.q.transfers"), companies: t("ad.t.cos"), wallets: t("ad.t.wa"), audit: t("ad.t.au"), ai: t("ad.t.ai"), ops: t("ad.t.ops"),
  };
  const isQueue = (QUEUES.map((x) => x.key) as string[]).includes(section);
  const rail = (
    <>
      <RailGroup>
        <RailItem to="/admin" current={section === "inbox"} count={counts.total + (nTr ?? 0)}>{t("ad.nav.inbox")}</RailItem>
        <RailItem to="/admin/dashboard" current={section === "dashboard"}>{t("ad.t.ov")}</RailItem>
      </RailGroup>
      <RailGroup title={t("ad.nav.queues")}>
        {QUEUES.map((x, i) => <RailItem key={x.key} to={`/admin/${x.key}`} current={section === x.key} mark={i + 1} gate={x.gate} count={counts[x.key]}>{t(("ad.q." + x.key) as DictKey)}</RailItem>)}
        <RailItem to="/admin/transfers" current={section === "transfers"} mark={QUEUES.length + 1} count={nTr}>{t("ad.q.transfers")}</RailItem>
      </RailGroup>
      <RailGroup title={t("ad.nav.registry")}>
        <RailItem to="/admin/companies" current={section === "companies"}>{t("ad.t.cos")}</RailItem>
        <RailItem to="/admin/wallets" current={section === "wallets"}>{t("ad.t.wa")}</RailItem>
      </RailGroup>
      <RailGroup title={t("ad.nav.trust")}>
        <RailItem to="/admin/audit" current={section === "audit"}>{t("ad.t.au")}</RailItem>
        <RailItem to="/admin/ai" current={section === "ai"}>{t("ad.t.ai")}</RailItem>
      </RailGroup>
      <RailGroup title={t("ad.nav.ops")}>
        <RailItem to="/admin/ops" current={section === "ops"}>{t("ad.t.ops")}</RailItem>
      </RailGroup>
    </>
  );
  const qi = QUEUES.findIndex((x) => x.key === section);
  return (
    <SideLayout rail={rail} label={t("ad.eyebrow")}>
      <Crumbs items={[{ to: "/admin", label: t("ad.eyebrow") }, { label: title[section] }]} />
      <div className="chead">
        <div className="whoami"><span>{t("ad.signedas")}</span><span className="addrpill" title={me?.address ?? undefined}>{who}</span><button className="btn ghost sm" type="button" onClick={() => void logout()}>{t("ad.logout")}</button></div>
        <span className="live" aria-live="off">
          {visible ? <i /> : <i style={{ background: "var(--faint)", animation: "none" }} />}
          <span>{visible ? t("ad.live", { s: Math.max(0, Math.round((now - updated) / 1000)) }) : t("ad.paused")}</span>
          {stats.data?.block ? <span className="mono muted">#{fmt(stats.data.block)}</span> : null}
        </span>
      </div>
      <StepHead eyebrow={isQueue ? t("ad.q.eyebrow", { i: qi + 1 }) + (QUEUES[qi]?.gate ? " · ◆ " + t("gate.admin") : "") : t("ad.eyebrow")}
        title={section === "inbox" ? t("ad.inbox.h", { n: counts.total + (nTr ?? 0) }) : title[section]}
        desc={t(("ad.d." + section) as DictKey)} />
      {section === "inbox" && <Inbox ap={ap} nTr={nTr} />}
      {section === "dashboard" && <Overview stats={stats} cos={cos} wallets={wallets.data} onPick={(tk) => nav(`/admin/companies/${tk}`)} />}
      {isQueue && <QueueView q={section as QueueKey} ap={ap} wallets={wallets.data} onChanged={refreshAll} />}
      {section === "transfers" && <TransfersTab onChanged={refreshAll} />}
      {section === "companies" && <CompaniesTab onChanged={refreshAll} />}
      {section === "wallets" && <WalletsTab />}
      {section === "audit" && <AuditTab />}
      {section === "ai" && <AiHealthTab />}
      {section === "ops" && <OpsTab />}
    </SideLayout>
  );
}

export default function AdminPage() {
  const { t } = useI18n();
  const { me, loading, refresh, setMe } = useAuth();
  const [needPw, setNeedPw] = useState(false);
  const [params] = useSearchParams();
  const nav = useNavigate();
  const next = safeNext(params.get("next"));
  const back = safeNext(params.get("return"));
  useTitle(t("ad.eyebrow"));
  const isAdmin = me?.role === "admin";
  const mustChange = isAdmin && (me?.must_change || needPw);
  // back to the page that sent the judge here (e.g. /c/DPT) once signed in as admin
  useEffect(() => { if (!loading && isAdmin && !mustChange && next) nav(next, { replace: true }); }, [loading, isAdmin, mustChange, next, nav]);
  if (!loading && isAdmin && !mustChange) return <Console onPwRequired={() => setNeedPw(true)} />;
  return (
    <section className="block admin-band" style={{ borderTop: 0, paddingTop: 40, minHeight: "70vh" }}>
      <div className="wrap">
        <div className="head">
          <span className="eyebrow">{t("ad.eyebrow")}</span>
          <h2>{t("ad.h2")}</h2>
          <p>{t("ad.p")}</p>
        </div>
        {loading ? <p className="note">{t("common.loading")}</p> : !isAdmin ? <LoginCard next={next ?? back} /> : (
          <ChangePassword onDone={async () => { setNeedPw(false); const m = await refresh(); if (m) setMe({ ...m, must_change: false }); }} />
        )}
      </div>
    </section>
  );
}
