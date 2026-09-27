import { Link } from "react-router-dom";
import { useI18n } from "../i18n";
import { api } from "../api";
import { useAuth } from "../auth";
import { useAsync, useTitle } from "../lib/hooks";
import { Spark } from "../components/charts";
import { GRADE_C } from "../lib/math";
import { arrow } from "../i18n";
import type { DictKey } from "../dict";

const Check = () => <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true"><path d="M3 8.5l3 3 7-7" /></svg>;

/** Primary + secondary call to action, shared by the hero and the final band. The demo account opens by itself. */
function Ctas({ dark = false, chip = false }: { dark?: boolean; chip?: boolean }) {
  const { t } = useI18n();
  const { me } = useAuth();
  return (
    <div className="hv-ctas">
      <div className="ctas">
        <Link className="btn" to="/start">{t("cta.primary")}</Link>
        <Link className={"btn ghost" + (dark ? " hv-onDark" : "")} to="/start?goal=list">{t("cta.list")}</Link>
      </div>
      {chip && me?.auth_method === "demo" && (
        <span className="hv-chip" title={t("hv.demoChip.tip")}><i aria-hidden="true" />{t("hv.demoChip")} · <Link to="/i">{t("in.title")}</Link></span>
      )}
    </div>
  );
}

/** Two audiences, one simple visual each. */
function Paths() {
  const { t } = useI18n();
  const INV: DictKey[] = ["hv.pi.1", "hv.pi.2", "hv.pi.3", "hv.pi.4"];
  const BIZ: DictKey[] = ["hv.pb.1", "hv.pb.2", "hv.pb.3", "hv.pb.4"];
  return (
    <section className="block" id="how" aria-labelledby="paths-h">
      <div className="wrap">
        <div className="head">
          <span className="eyebrow">{t("hv.paths.eyebrow")}</span>
          <h2 id="paths-h">{t("hv.paths.h2")}</h2>
          <p>{t("hv.paths.p")}</p>
        </div>
        <div className="hv-paths">
          <div className="hv-path" aria-labelledby="pi-h">
            <h3 id="pi-h">{t("hv.pi.h")}</h3>
            <p>{t("hv.pi.p")}</p>
            <ol>{INV.map((k) => <li key={k}>{t(k)}</li>)}</ol>
            <Link className="btn" to="/start">{t("hv.pi.cta")} <span aria-hidden="true">→</span></Link>
          </div>
          <div className="hv-path biz" aria-labelledby="pb-h">
            <h3 id="pb-h">{t("hv.pb.h")}</h3>
            <p>{t("hv.pb.p")}</p>
            <ol>{BIZ.map((k) => <li key={k}>{t(k)}</li>)}</ol>
            <Link className="btn ghost" to="/start?goal=list">{t("hv.pb.cta")} <span aria-hidden="true">→</span></Link>
          </div>
        </div>
      </div>
    </section>
  );
}

/** Investor-oriented hero visual: an example holding card. Pure CSS/SVG. */
function HoldingCard() {
  const { t, fmt, aud } = useI18n();
  const bars = [38, 44, 41, 52, 58, 63];
  return (
    <div className="hv-card" role="img" aria-label={t("hv.card.aria")}>
      <div className="hv-card-top">
        <span className="eyebrow">{t("hv.card.label")}</span>
        <span className="hv-tag">{t("hv.card.example")}</span>
      </div>
      <div className="hv-co">
        <span className="hv-logo" aria-hidden="true">H</span>
        <div><b>Harbourline Logistics</b><span className="muted">HBL</span></div>
      </div>
      <div className="hv-grid">
        <div><small>{t("hv.card.shares")}</small><b className="num">{fmt(25000)}</b></div>
        <div><small>{t("hv.card.stake")}</small><b className="num">{fmt(0.74, 2)}%</b></div>
      </div>
      <div className="hv-value">
        <div>
          <small>{t("hv.card.value")}</small>
          <b className="num">{aud(25800, 0)}</b>
          <span className="hv-ok"><Check />{t("hv.card.checked")}</span>
        </div>
        <svg className="hv-bars" viewBox="0 0 96 64" aria-hidden="true">
          {bars.map((h, i) => <rect key={i} x={i * 16 + 2} y={64 - h} width="11" height={h} rx="2" />)}
        </svg>
      </div>
      <div className="hv-update">
        <small>{t("hv.card.update")}</small>
        <p>{t("hv.card.updateTxt")}</p>
      </div>
      <div className="hv-div">
        <span>{t("hv.card.div")}</span>
        <b className="num">+{aud(750, 0)}</b>
      </div>
      <span className="hv-proof">{t("hv.card.proof")}</span>
    </div>
  );
}

const PAINS = [1, 2, 3, 4] as const;
const PILLARS = [1, 2, 3, 4, 5] as const;
const PILLAR_ICONS = [
  <path key="1" d="M4 5h16v14H4zM8 9h8M8 13h5" />,
  <path key="2" d="M4 18l5-6 4 3 7-9M15 6h5v5" />,
  <path key="3" d="M12 3l8 4v5c0 4.5-3.4 8-8 9-4.6-1-8-4.5-8-9V7zM8.5 12l2.5 2.5 4.5-5" />,
  <path key="4" d="M3 7h18v12H3zM3 11h18M16 15h2" />,
  <path key="5" d="M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14zM16 16l5 5" />,
];

function LiveStats() {
  const { t, fmt, money, chg } = useI18n();
  const stats = useAsync(() => api.stats(), [], 30000);
  const cos = useAsync(() => api.companies(), [], 30000);
  const k = stats.data?.kpis;
  const recent = (cos.data ?? []).slice(0, 6);
  const allAnchored = !!k && k.anchored_total > 0 && k.anchored === k.anchored_total;
  const dash = stats.loading ? "…" : "–";
  return (
    <section className="block" id="live" aria-labelledby="live-h">
      <div className="wrap">
        <div className="head">
          <span className="eyebrow">{t("home.stats.eyebrow")}</span>
          <h2 id="live-h">{t("home.stats.h2")}</h2>
          <p>{t("home.stats.p")}</p>
        </div>
        {stats.error && !k ? <p className="banner warn" role="status"><span>{t("home.st.err")}</span><button className="btn ghost sm" type="button" onClick={() => void stats.reload()}>{t("common.retry")}</button></p> : null}
        <div className="statsstrip" aria-busy={stats.loading && !k} aria-live="polite">
          <div className="kpi"><small>{t("home.st.co")}</small><b className="num">{k ? fmt(k.companies) : dash}</b><span>{allAnchored ? t("home.st.cosub") : stats.data?.block ? t("home.st.asof", { b: fmt(stats.data.block) }) : " "}</span></div>
          <div className="kpi"><small>{t("home.st.tok")}</small><b className="num">{k ? fmt(k.tokens) : dash}</b><span>{t("home.st.tokSub")}</span></div>
          <div className="kpi"><small>{t("home.st.val")}</small><b className="num">{k ? money(k.total_valuation_aud) : dash}</b><span>{k ? `${t("ad.k.median")} ${money(k.median_valuation_aud)}` : " "}</span></div>
          <div className="kpi"><small>{t("home.st.ver")}</small><b className="num">{k ? `${fmt(k.anchored)} / ${fmt(k.anchored_total)}` : dash}</b><span><Link to="/verify">{t("home.st.verSub")} →</Link></span></div>
        </div>
        <div className="between" style={{ marginTop: 28 }}>
          <h3 style={{ fontSize: "1.15rem" }}>{t("home.recent")}</h3>
          <Link to="/companies">{t("home.recent.all")} →</Link>
        </div>
        {cos.error ? <p className="note" style={{ marginTop: 12 }}>{t("common.error")}</p> : !cos.loading && recent.length === 0 ? (
          <p className="empty" style={{ marginTop: 16 }}>{t("home.recent.empty")}</p>
        ) : (
          <div className="cogrid">
            {recent.map((c) => {
              const p = c.change_30d ?? 0;
              return (
                <Link key={c.ticker} className="cocard" to={`/c/${c.ticker}`}>
                  <div className="top">
                    <span className="tkr">{c.ticker}</span>
                    {c.grade && <span className="gchip" style={{ background: `var(${GRADE_C[c.grade] ?? "--c6"})` }} aria-label={`${t("ad.c.grade")} ${c.grade}`}>{c.grade}</span>}
                  </div>
                  <span style={{ fontWeight: 600 }}>{c.name}</span>
                  <div className="top">
                    <span className="num">{money(c.valuation_aud)}</span>
                    <span className={"chg " + arrow(p)}>{chg(p)}</span>
                  </div>
                  <Spark vals={c.spark_30d ?? [1, 1]} cls={arrow(p)} w={220} h={26} className="spark" />
                </Link>
              );
            })}
          </div>
        )}
        <div className="hv-check">
          <div>
            <h3>{t("hv.check.h")}</h3>
            <p className="muted">{t("hv.check.p")}</p>
          </div>
          <div className="row">
            <Link className="btn ghost" to="/verify">{t("hv.check.link")} →</Link>
            <Link className="hv-tech" to="/hsk">{t("hv.check.tech")}</Link>
          </div>
        </div>
      </div>
    </section>
  );
}

export function Home() {
  const { t } = useI18n();
  useTitle("");
  return (
    <>
      <section className="hero">
        <div className="wrap">
          <div>
            <span className="eyebrow">{t("hero.eyebrow")}</span>
            <h1 style={{ marginTop: 16 }}>{t("hero.h1a")} <em>{t("hero.h1b")}</em></h1>
            <p className="pitch hv-pitch">{t("hero.pitch")}</p>
            <Ctas chip />
            <p className="legal">{t("hero.legal")}</p>
          </div>
          <HoldingCard />
        </div>
      </section>

      <Paths />

      <section className="block" id="problem" aria-labelledby="prob-h">
        <div className="wrap">
          <div className="head">
            <span className="eyebrow">{t("hv.prob.eyebrow")}</span>
            <h2 id="prob-h">{t("hv.prob.h2")}</h2>
            <p>{t("hv.prob.p")}</p>
          </div>
          <ol className="hv-pains">
            {PAINS.map((i) => (
              <li key={i}>
                <span className="hv-num" aria-hidden="true">{i}</span>
                <h3>{t(`hv.prob.${i}h` as DictKey)}</h3>
                <p>{t(`hv.prob.${i}p` as DictKey)}</p>
              </li>
            ))}
          </ol>
        </div>
      </section>

      <section className="block" id="get" aria-labelledby="get-h">
        <div className="wrap">
          <div className="head">
            <span className="eyebrow">{t("hv.get.eyebrow")}</span>
            <h2 id="get-h">{t("hv.get.h2")}</h2>
            <p>{t("hv.get.p")}</p>
          </div>
          <ul className="hv-pillars">
            {PILLARS.map((i) => (
              <li key={i}>
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{PILLAR_ICONS[i - 1]}</svg>
                <h3>{t(`hv.get.${i}h` as DictKey)}</h3>
                <p>{t(`hv.get.${i}p` as DictKey)}</p>
              </li>
            ))}
          </ul>
        </div>
      </section>

      <LiveStats />

      <section className="block" style={{ borderTop: 0, paddingTop: 0 }}>
        <div className="wrap">
          <div className="final">
            <h2>{t("fin.h")}</h2>
            <p>{t("fin.p")}</p>
            <Ctas dark />
            <p className="hv-finlegal">{t("hero.legal")}</p>
          </div>
        </div>
      </section>
    </>
  );
}
