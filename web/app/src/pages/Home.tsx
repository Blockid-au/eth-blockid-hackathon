import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useI18n } from "../i18n";
import { api } from "../api";
import { useAsync, useReducedMotion, useTitle } from "../lib/hooks";
import { Ring, Spark } from "../components/charts";
import { GATES } from "../components/Stepper";
import { GRADE_C } from "../lib/math";
import { arrow } from "../i18n";
import type { DictKey } from "../dict";

const HERO_PARTS = [
  { name: "Maya Chen", v: 42, c: "--c1" }, { name: "Tom Nguyen", v: 25, c: "--c2" }, { name: "Seed Fund I", v: 15, c: "--c3" },
  { name: "ESOP pool", v: 10, c: "--c4" }, { name: "Angels", v: 8, c: "--c5" },
];

const Check = () => <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true"><path d="M3 8.5l3 3 7-7" /></svg>;

function HeroDevice() {
  const { t } = useI18n();
  const reduce = useReducedMotion();
  const [stage, setStage] = useState(3);
  useEffect(() => {
    if (reduce) { setStage(3); return; }
    setStage(0);
    let s = 0, hold = 0;
    const id = setInterval(() => {
      if (hold > 0) { hold--; if (hold === 0) { s = 0; setStage(0); } return; }
      s = Math.min(s + 1, 3);
      setStage(s);
      if (s === 3) hold = 2;
    }, 1500);
    return () => clearInterval(id);
  }, [reduce]);
  const dim = (i: number) => "tile" + (i > stage ? " dim" : "");
  return (
    <div className="device" aria-label="Product preview" role="img">
      <div className="bar"><i /><i /><i /><span>eth.blockid.au</span></div>
      <div className="inner">
        <div className="urlrow"><span className="muted">https://</span><span>harbourline.com.au</span><span className="caret" aria-hidden="true" /></div>
        <div className="stages">
          {(["hs.1", "hs.2", "hs.3", "hs.4"] as DictKey[]).map((k, i) => <span key={k} className={i <= stage ? "on" : ""}>{t(k)}</span>)}
        </div>
        <div className="heroviz">
          <div className={dim(0)}>
            <small>{t("ht.sources")}</small>
            <div className="bigno">23</div>
            <div className="srcs"><b>asic.gov.au</b><b>ibisworld.com</b><b>crunchbase</b><b>afr.com</b><b>+19</b></div>
          </div>
          <div className={dim(1)}>
            <small>{t("ht.svi")}</small>
            <div className="gradeline"><span className="gradebadge">B</span><span className="bigno">A$3.36M</span></div>
            <span className="muted" style={{ fontSize: ".78rem" }}>{t("ht.range")}</span>
          </div>
          <div className={dim(2)}>
            <small>{t("ht.token")}</small>
            <span className="tick">HBL</span>
            <span className="muted" style={{ fontSize: ".78rem" }}>{t("ht.holders")}</span>
          </div>
          <div className={dim(3)}>
            <div style={{ width: 96 }}><Ring parts={HERO_PARTS} r={44} sw={18} size={120} label="Ownership ring" /></div>
            <span className="anchorline">{t("ht.anchored")}</span>
          </div>
        </div>
      </div>
    </div>
  );
}

function HowDiagram() {
  const { t } = useI18n();
  return (
    <figure>
      <div className="diagram">
        <svg viewBox="0 0 1000 330" role="img" aria-label="Flow: website to AI agents to SVI valuation, admin approval, then the issuer service issues on BlockID Chain, anchors on Hoodi and delivers tokens to wallets">
          <defs>
            <marker id="ar" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0 0L10 5L0 10z" fill="currentColor" /></marker>
            <marker id="arg" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0 0L10 5L0 10z" fill="var(--gold-mark)" /></marker>
          </defs>
          <text x="14" y="26" fontSize="11" fontWeight="600" letterSpacing="1.2" fill="var(--muted)">{t("d.lane1")}</text>
          <rect x="8" y="36" width="984" height="108" rx="14" fill="var(--sunken)" />
          <text x="14" y="190" fontSize="11" fontWeight="600" letterSpacing="1.2" fill="var(--gold)">{t("d.lane2")}</text>
          <rect x="8" y="200" width="984" height="108" rx="14" fill="none" stroke="var(--gold-mark)" strokeDasharray="6 5" strokeWidth="1.5" />
          <g fontSize="13" textAnchor="middle">
            <rect x="28" y="62" width="150" height="56" rx="10" fill="var(--surface)" stroke="var(--line)" /><text x="103" y="86" fontWeight="600" fill="currentColor">{t("d.n1")}</text><text x="103" y="104" fontSize="11" fill="var(--muted)">{t("d.n1s")}</text>
            <rect x="222" y="62" width="150" height="56" rx="10" fill="var(--surface)" stroke="var(--line)" /><text x="297" y="86" fontWeight="600" fill="currentColor">{t("d.n2")}</text><text x="297" y="104" fontSize="11" fill="var(--muted)">{t("d.n2s")}</text>
            <rect x="416" y="62" width="150" height="56" rx="10" fill="var(--surface)" stroke="var(--line)" /><text x="491" y="86" fontWeight="600" fill="currentColor">{t("d.n3")}</text><text x="491" y="104" fontSize="11" fill="var(--muted)">Brave Search</text>
            <rect x="610" y="62" width="150" height="56" rx="10" fill="var(--surface)" stroke="var(--line)" /><text x="685" y="86" fontWeight="600" fill="currentColor">{t("d.n4")}</text><text x="685" y="104" fontSize="11" fill="var(--muted)">{t("d.n4s")}</text>
            <rect x="804" y="62" width="168" height="56" rx="10" fill="var(--accent)" /><text x="888" y="86" fontWeight="700" fill="var(--accent-ink)">{t("d.n5")}</text><text x="888" y="104" fontSize="11" fill="var(--accent-ink)">{t("d.n5s")}</text>
          </g>
          <g stroke="currentColor" strokeWidth="1.5" fill="none">
            <line x1="178" y1="90" x2="218" y2="90" markerEnd="url(#ar)" /><line x1="372" y1="90" x2="412" y2="90" markerEnd="url(#ar)" />
            <line x1="566" y1="90" x2="606" y2="90" markerEnd="url(#ar)" /><line x1="760" y1="90" x2="800" y2="90" markerEnd="url(#ar)" />
          </g>
          <g fontSize="10.5" fill="var(--muted)" textAnchor="middle">
            <text x="198" y="80">{t("d.e1")}</text><text x="392" y="80">{t("d.e2")}</text><text x="586" y="80">{t("d.e3")}</text><text x="780" y="80">{t("d.e4")}</text>
          </g>
          <line x1="888" y1="118" x2="888" y2="222" stroke="var(--gold-mark)" strokeWidth="2" markerEnd="url(#arg)" />
          <rect x="802" y="150" width="172" height="26" rx="13" fill="var(--gold-soft)" stroke="var(--gold-mark)" />
          <text x="888" y="167" fontSize="11.5" fontWeight="700" textAnchor="middle" fill="var(--gold)">{t("d.gate")}</text>
          <g fontSize="13" textAnchor="middle">
            <rect x="804" y="226" width="168" height="56" rx="10" fill="var(--surface)" stroke="var(--line)" /><text x="888" y="250" fontWeight="600" fill="currentColor">{t("d.b1")}</text><text x="888" y="268" fontSize="11" fill="var(--muted)">{t("d.b1s")}</text>
            <rect x="560" y="226" width="168" height="56" rx="10" fill="var(--surface)" stroke="var(--gold-mark)" /><text x="644" y="250" fontWeight="600" fill="currentColor">{t("d.b2")}</text><text x="644" y="268" fontSize="11" fill="var(--muted)">{t("d.b2s")}</text>
            <rect x="316" y="226" width="168" height="56" rx="10" fill="var(--surface)" stroke="var(--line)" /><text x="400" y="250" fontWeight="600" fill="currentColor">{t("d.b3")}</text><text x="400" y="268" fontSize="11" fill="var(--muted)">MetaMask</text>
            <rect x="72" y="226" width="168" height="56" rx="10" fill="var(--surface)" stroke="var(--line)" /><text x="156" y="250" fontWeight="600" fill="currentColor">{t("d.b4")}</text><text x="156" y="268" fontSize="11" fill="var(--muted)">{t("d.b4s")}</text>
          </g>
          <g stroke="currentColor" strokeWidth="1.5" fill="none">
            <line x1="804" y1="254" x2="732" y2="254" markerEnd="url(#ar)" /><line x1="560" y1="254" x2="488" y2="254" markerEnd="url(#ar)" /><line x1="316" y1="254" x2="244" y2="254" markerEnd="url(#ar)" />
          </g>
          <g fontSize="10.5" fill="var(--muted)" textAnchor="middle">
            <text x="768" y="244">{t("d.f1")}</text><text x="524" y="244">{t("d.f2")}</text><text x="280" y="244">{t("d.f3")}</text>
          </g>
        </svg>
      </div>
      <figcaption>{t("how.cap")}</figcaption>
    </figure>
  );
}

function LiveStats() {
  const { t, fmt, money, chg } = useI18n();
  const stats = useAsync(() => api.stats(), [], 30000);
  const cos = useAsync(() => api.companies(), [], 30000);
  const k = stats.data?.kpis;
  const recent = (cos.data ?? []).slice(0, 6);
  return (
    <section className="block" id="live" aria-labelledby="live-h">
      <div className="wrap">
        <div className="head">
          <span className="eyebrow">{t("home.stats.eyebrow")}</span>
          <h2 id="live-h">{t("home.stats.h2")}</h2>
          <p>{t("home.stats.p")}</p>
        </div>
        <div className="statsstrip" aria-busy={stats.loading}>
          <div className="kpi"><small>{t("home.st.co")}</small><b>{k ? fmt(k.companies) : "–"}</b><span>{stats.data?.block ? t("home.st.asof", { b: fmt(stats.data.block) }) : " "}</span></div>
          <div className="kpi"><small>{t("home.st.val")}</small><b>{k ? money(k.total_valuation_aud) : "–"}</b><span>{k ? `${t("ad.k.avg")} ${money(k.avg_valuation_aud)}` : " "}</span></div>
          <div className="kpi"><small>{t("home.st.tok")}</small><b>{k ? fmt(k.tokens) : "–"}</b><span>{t("home.st.tokSub")}</span></div>
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
            <p className="pitch">{t("hero.pitch")}</p>
            <div className="ctas">
              <Link className="btn" to="/new">{t("cta.primary")}</Link>
              <Link className="btn ghost" to="/v/sample">{t("cta.secondary")}</Link>
            </div>
            <p className="legal">{t("hero.legal")}</p>
            <div className="chips">
              {(["chip.1", "chip.2", "chip.3", "chip.4"] as DictKey[]).map((k) => <span className="chip" key={k}><Check /><span>{t(k)}</span></span>)}
            </div>
          </div>
          <HeroDevice />
        </div>
      </section>

      <section className="block" id="how" aria-labelledby="how-h">
        <div className="wrap">
          <div className="head">
            <span className="eyebrow">{t("how.eyebrow")}</span>
            <h2 id="how-h">{t("how.h2")}</h2>
            <p>{t("how.p")}</p>
          </div>
          <HowDiagram />
        </div>
      </section>

      <section className="block" id="walk" aria-labelledby="walk-h">
        <div className="wrap">
          <div className="head">
            <span className="eyebrow">{t("walk.eyebrow")}</span>
            <h2 id="walk-h">{t("walk.h2")}</h2>
            <p>{t("new.p")}</p>
          </div>
          <ol className="teaser" style={{ listStyle: "none", padding: 0, margin: 0 }}>
            {Array.from({ length: 8 }, (_, i) => i + 1).map((i) => (
              <li key={i} style={{ display: "contents" }}>
                <div className={GATES.includes(i) ? "gate" : ""} title={GATES.includes(i) ? t("gate.admin") : undefined}>
                  <b>{String(i).padStart(2, "0")}</b><span>{t(("step." + i) as DictKey)}</span>
                </div>
              </li>
            ))}
          </ol>
          <div className="row" style={{ marginTop: 20 }}>
            <Link className="btn" to="/new">{t("home.walk.cta")}</Link>
            <Link className="btn ghost" to="/v/sample">{t("cta.secondary")}</Link>
          </div>
        </div>
      </section>

      <LiveStats />

      <section className="block" style={{ borderTop: 0, paddingTop: 0 }}>
        <div className="wrap">
          <div className="final">
            <h2>{t("fin.h")}</h2>
            <p>{t("fin.p")}</p>
            <Link className="btn" to="/new">{t("cta.primary")}</Link>
          </div>
        </div>
      </section>
    </>
  );
}
