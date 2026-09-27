import { useEffect, useState } from "react";
import { Link, Navigate, useNavigate, useParams } from "react-router-dom";
import { api, type Holdings, type Position } from "../api";
import { errText, useAuth } from "../auth";
import { arrow, useI18n } from "../i18n";
import { Spark } from "../components/charts";
import { ErrorBox, Loading } from "../components/Layout";
import { GoogleButton } from "../components/GoogleButton";
import { SignInCard } from "../components/SignIn";
import { useAsync, useTitle } from "../lib/hooks";
import { GRADE_C } from "../lib/math";
import { shortAddr } from "../lib/addr";
import { CompanyUpdateList, UpdateFeed, UpdatePage } from "./Updates";
import { DividendLedgerCard, UpcomingDividends } from "./Dividends";
import { StatusBar } from "../components/StatusBar";

/**
 * Investor portal: what you own, what it is worth at the latest approved price, and the dividends you received.
 *   /i            your holdings (or the sample portfolio + sign-in when signed out)
 *   /i/demo       sample portfolio (a real holder on the testnet), no sign-in needed
 *   /i/h/:tk      one of your holdings;  /i/demo/:tk  one holding of the sample portfolio
 *   /i/u/:id      one published business update (with "Check this update")
 *   /i/account    how you signed in, your wallet, key backup / restore
 */
export default function InvestorPage() {
  const { view, tk } = useParams();
  if (view === "account") return <Account />;
  if (view === "u" && tk) return <UpdatePage id={tk} />;
  if (view === "demo") return <Portfolio demo tk={tk} />;
  if (view === "h" && tk) return <Portfolio tk={tk} />;
  if (!view || view === "holdings") return <Portfolio />;
  return <Navigate to="/i" replace />;
}

function Portfolio({ demo = false, tk }: { demo?: boolean; tk?: string }) {
  const { t } = useI18n();
  const { me, loading } = useAuth();
  const mine = !demo && !!me;
  const data = useAsync<Holdings>(() => (mine ? api.holdings() : api.demoHoldings()), [mine, me?.address], 60000);
  useTitle(t("in.title"));
  if (loading || (data.loading && !data.data)) return <Loading />;
  if (data.error) return <div className="wrap page"><ErrorBox error={data.error} retry={data.reload} /></div>;
  const h = data.data!;
  const base = mine ? "/i/h/" : "/i/demo/";
  if (tk) {
    const p = h.positions.find((x) => x.ticker.toUpperCase() === tk.toUpperCase());
    if (!p) return <Navigate to={mine ? "/i" : "/i/demo"} replace />;
    return <PositionView p={p} demo={!mine} back={mine ? "/i" : "/i/demo"} />;
  }
  const empty = mine && h.positions.length === 0;
  return (
    <div className="wrap page inv">
      <div className="head">
        <span className="eyebrow">{t("in.eyebrow")}</span>
        <h2>{mine ? t("in.h.mine") : t("in.h.demo")}</h2>
        <p>{mine ? t("in.p.mine") : t("in.p.demo")}</p>
      </div>
      <PortfolioStatus h={h} mine={mine} />
      {!me && <SignInCard />}
      {empty ? <Empty /> : <Summary h={h} base={base} />}
      {!empty && h.positions.length > 0 && <DividendLedgerCard demo={!mine} />}
      {!empty && h.positions.length > 0 && <UpdateFeed demo={!mine} />}
      {empty && <SampleBelow />}
      <p className="muted-sm">{t("in.legal")}</p>
    </div>
  );
}

/** Slim status line for the portfolio: whose holdings these are, how many, what they are worth. */
function PortfolioStatus({ h, mine }: { h: Holdings; mine: boolean }) {
  const { t, money } = useI18n();
  const { me } = useAuth();
  const demoAcct = mine && me?.auth_method === "demo";
  return (
    <StatusBar status={t(!mine ? "sb.st.sample" : demoAcct ? "sb.st.demo" : "sb.st.mine")} tone={mine && !demoAcct ? "ok" : "idle"}
      meta={t("sb.pf.meta", { n: h.positions.length, v: money(h.total_value_aud) }) + (demoAcct ? " · " + t("in.chip.demo") : !mine ? " · " + t("in.chip.sample") : "")}
      next={demoAcct || !me ? { label: t("sb.pf.signin"), to: "/i/account" } : null} />
  );
}

function Summary({ h, base }: { h: Holdings; base: string }) {
  const { t, fmt, money } = useI18n();
  return (
    <>
      <div className="kpis">
        <div className="kpi"><small>{t("in.k.value")}</small><b>{money(h.total_value_aud)}</b><span>{t("in.k.valueSub")}</span></div>
        <div className="kpi"><small>{t("in.k.cos")}</small><b>{fmt(h.positions.length)}</b><span>{t("in.k.cosSub")}</span></div>
        <div className="kpi"><small>{t("in.k.div")}</small><b>{fmt(h.dividends_total_maud, 2)}</b><span>{t("in.k.divSub")}</span></div>
        <div className="kpi"><small>{t("in.k.wallet")}</small><b className="mono" style={{ fontSize: "1.05rem" }}>{h.wallets[0] ? shortAddr(h.wallets[0]) : "–"}</b><span>{t("in.k.walletSub")}</span></div>
      </div>
      <div className="inv-list">
        {h.positions.map((p) => <PositionCard key={p.ticker} p={p} to={base + p.ticker} />)}
      </div>
    </>
  );
}

function PositionCard({ p, to }: { p: Position; to: string }) {
  const { t, fmt, money, pct, chg } = useI18n();
  const since = p.issue_price_aud ? ((p.mark_aud - p.issue_price_aud) / p.issue_price_aud) * 100 : 0;
  return (
    <Link className="card solid inv-card" to={to}>
      <div className="between">
        <span><b className="mono">{p.ticker}</b> · {p.name}</span>
        {p.grade && <span className="gchip" style={{ background: `var(${GRADE_C[p.grade] ?? "--c6"})` }}>{p.grade}</span>}
      </div>
      <div className="inv-val">{money(p.value_aud)}</div>
      <div className="inv-meta">
        <span>{t("in.c.shares", { n: fmt(p.shares), p: pct(p.pct, p.pct < 1 ? 3 : 2) })}</span>
        <span className={"chg " + arrow(since)}>{chg(since)} {t("in.c.since")}</span>
      </div>
      <Spark vals={p.spark_30d.length ? p.spark_30d : [p.mark_aud, p.mark_aud]} cls={arrow(p.change_30d ?? 0)} w={260} h={36} />
      <span className="muted-sm">{p.dividends_maud > 0 ? t("in.c.div", { n: fmt(p.dividends_maud, 2) }) : t("in.c.nodiv")}</span>
    </Link>
  );
}

function PositionView({ p, demo, back }: { p: Position; demo: boolean; back: string }) {
  const { t, fmt, money, aud, pct, chg, date } = useI18n();
  useTitle(`${p.ticker} · ${t("in.title")}`);
  const since = p.issue_price_aud ? ((p.mark_aud - p.issue_price_aud) / p.issue_price_aud) * 100 : 0;
  return (
    <div className="wrap page inv">
      <nav className="crumbs" aria-label={t("in.crumbs")}><Link to={back}>{demo ? t("in.h.demo") : t("in.h.mine")}</Link> / <span>{p.ticker}</span></nav>
      <div className="head">
        <span className="eyebrow">{p.ticker}</span>
        <h2>{p.name}</h2>
        <p>{t("in.pos.sentence", { n: fmt(p.shares), s: fmt(p.supply), p: pct(p.pct, p.pct < 1 ? 3 : 2), price: aud(p.mark_aud, 3), v: money(p.value_aud) })}</p>
      </div>
      {demo && <p className="chipline"><span className="infochip"><i aria-hidden="true" />{t("in.chip.sample")}</span></p>}
      <div className="kpis">
        <div className="kpi"><small>{t("in.k.value")}</small><b>{money(p.value_aud)}</b><span>{t("in.pos.price", { p: aud(p.mark_aud, 3) })}</span></div>
        <div className="kpi"><small>{t("in.pos.own")}</small><b>{pct(p.pct, p.pct < 1 ? 3 : 2)}</b><span>{t("in.pos.ownSub", { n: fmt(p.shares) })}</span></div>
        <div className="kpi"><small>{t("in.pos.since")}</small><b className={"chg " + arrow(since)} style={{ fontSize: "1.55rem" }}>{chg(since)}</b><span>{t("in.pos.sinceSub", { p: aud(p.issue_price_aud, 2) })}</span></div>
        <div className="kpi"><small>{t("in.k.div")}</small><b>{fmt(p.dividends_maud, 2)}</b><span>{t("in.k.divSub")}</span></div>
      </div>
      <UpcomingDividends list={p.upcoming ?? []} />
      <div className="cols">
        <section className="card solid">
          <h4>{t("in.pos.trend")}</h4>
          <Spark vals={p.spark_30d.length ? p.spark_30d : [p.mark_aud, p.mark_aud]} cls={arrow(p.change_30d ?? 0)} w={480} h={90} />
          <span className="muted-sm">{t("in.pos.trendSub")}</span>
        </section>
        <section className="card solid">
          <h4>{t("in.pos.divs")}</h4>
          {p.dividends.length === 0 ? <span className="muted">{t("in.c.nodiv")}</span> : (
            <ul className="inv-divs">
              {p.dividends.map((d, i) => <li key={i}><span>{date(d.at)}</span><b>{d.tx_hash ? <a href={`https://scan.blockid.au/tx/${d.tx_hash}`} target="_blank" rel="noopener noreferrer">{fmt(d.amount_maud, 2)} mAUD</a> : `${fmt(d.amount_maud, 2)} mAUD`}</b></li>)}
            </ul>
          )}
          <span className="muted-sm">{t("in.pos.divSub")}</span>
        </section>
      </div>
      <CompanyUpdateList ticker={p.ticker} />
      <section className="card">
        <h4>{t("in.pos.next")}</h4>
        <div className="row" style={{ flexWrap: "wrap", gap: 10 }}>
          <Link className="btn ghost sm" to={`/c/${p.ticker}/overview`}>{t("in.pos.profile")}</Link>
          <Link className="btn ghost sm" to={`/c/${p.ticker}/activity`}>{t("in.pos.updates")}</Link>
          <Link className="btn ghost sm" to={`/verify/${p.ticker}`}>{t("in.pos.check")}</Link>
        </div>
        <span className="muted-sm">{t("in.pos.nextSub")}</span>
      </section>
      <p className="muted-sm">{t("in.legal")}</p>
    </div>
  );
}

function Empty() {
  const { t } = useI18n();
  return (
    <section className="card solid">
      <h4>{t("in.empty.h")}</h4>
      <p className="muted">{t("in.empty.p")}</p>
      <div className="row" style={{ flexWrap: "wrap", gap: 10 }}>
        <Link className="btn sm" to="/companies">{t("in.empty.browse")}</Link>
        <Link className="btn ghost sm" to="/start">{t("in.empty.list")}</Link>
      </div>
    </section>
  );
}

function SampleBelow() {
  const { t } = useI18n();
  const data = useAsync(() => api.demoHoldings(), []);
  if (!data.data || data.data.positions.length === 0) return null;
  return (
    <>
      <div className="head" style={{ marginTop: 12 }}>
        <span className="eyebrow">{t("in.sample.eyebrow")}</span>
        <h3>{t("in.h.demo")}</h3>
        <p>{t("in.p.demo")}</p>
      </div>
      <Summary h={data.data} base="/i/demo/" />
    </>
  );
}

function Account() {
  const { t } = useI18n();
  const { me, loading, logout, refresh } = useAuth();
  const nav = useNavigate();
  const [key, setKey] = useState<string | null>(null);
  const [local, setLocal] = useState<boolean | null>(null);
  const [restore, setRestore] = useState("");
  const [msg, setMsg] = useState("");
  useTitle(t("in.acc.h"));
  useEffect(() => {
    if (!me?.address) return;
    import("../devicewallet").then((m) => m.hasDeviceKey(me.address!)).then(setLocal).catch(() => setLocal(false));
  }, [me?.address]);
  if (loading) return <Loading />;
  const method = me?.auth_method ?? "wallet";
  return (
    <div className="wrap page inv">
      <div className="head">
        <span className="eyebrow">{t("in.eyebrow")}</span>
        <h2>{t("in.acc.h")}</h2>
        <p>{t("in.acc.p")}</p>
      </div>
      {!me ? <SignInCard /> : (
        <>
          <section className="card solid">
            <h4>{t("in.acc.how")}</h4>
            <p>{t(("in.acc.m." + method) as "in.acc.m.guest")}{me.account?.email ? ` · ${me.account.email}` : ""}</p>
            {me.address && <p className="mono" style={{ overflowWrap: "anywhere" }}>{me.address}</p>}
            {method === "guest" && (
              <div style={{ display: "grid", gap: 8 }}>
                <span className="muted">{t("in.acc.keep")}</span>
                <GoogleButton onDone={() => void refresh()} />
              </div>
            )}
          </section>
          {method === "demo" && <SignInCard />}
          {local && (
            <section className="card solid">
              <h4>{t("in.acc.backup")}</h4>
              <p className="muted">{t("in.acc.backupP")}</p>
              {key ? (
                <>
                  <p className="mono inv-key">{key}</p>
                  <div className="row" style={{ gap: 10, flexWrap: "wrap" }}>
                    <button className="btn ghost sm" type="button" onClick={() => { navigator.clipboard?.writeText(key).then(() => setMsg(t("in.acc.copied")), () => setMsg("")); }}>{t("in.acc.copy")}</button>
                    <button className="btn ghost sm" type="button" onClick={() => setKey(null)}>{t("in.acc.hide")}</button>
                  </div>
                </>
              ) : (
                <button className="btn ghost sm" type="button" onClick={async () => { const m = await import("../devicewallet"); setKey(await m.exportKey(me.address!)); }}>{t("in.acc.show")}</button>
              )}
              {msg && <span className="muted-sm" role="status">{msg}</span>}
            </section>
          )}
          <div className="row" style={{ gap: 10, flexWrap: "wrap" }}>
            <Link className="btn sm" to="/i">{t("in.acc.toHold")}</Link>
            <button className="btn ghost sm" type="button" onClick={async () => { await logout(); nav("/"); }}>{t("nav.signout")}</button>
          </div>
        </>
      )}
      <section className="card">
        <h4>{t("in.acc.restore")}</h4>
        <p className="muted">{t("in.acc.restoreP")}</p>
        <form className="field" onSubmit={async (e) => {
          e.preventDefault();
          setMsg("");
          try { const m = await import("../devicewallet"); await m.importKey(restore); setRestore(""); await refresh(); nav("/i"); } catch (err) { setMsg(errText(err, t)); }
        }}>
          <input id="restore-key" type="password" autoComplete="off" spellCheck={false} placeholder="0x…" aria-label={t("in.acc.restore")} value={restore} onChange={(e) => setRestore(e.target.value)} />
          <button className="btn ghost sm" type="submit" disabled={!restore.trim()}>{t("in.acc.restoreBtn")}</button>
        </form>
        {msg && !key && <span role="alert" className="muted-sm">{msg}</span>}
      </section>
    </div>
  );
}
