import { Link } from "react-router-dom";
import { useI18n } from "../../i18n";
import type { DictKey } from "../../dict";
import { SUBSCORE_KEYS } from "../../api";
import { ethUrl } from "../../lib/hrhost";
import { Avatar, useHrTitle } from "./common";

const WEIGHTS: Record<(typeof SUBSCORE_KEYS)[number], number> = { domain_fit: 25, track_record: 25, leadership: 15, functional_depth: 15, verifiability: 10, commitment: 10 };

/** Illustration of a finished report (static example, clearly labelled). */
function ExampleCard() {
  const { t, fmt } = useI18n();
  const people: [string, string, number][] = [["Maya Chen", "CEO", 78], ["Tom Nguyen", "CTO", 74], ["Priya Shah", "Head of Sales", 66]];
  return (
    <div className="hr-demo" role="img" aria-label={t("hr.home.card.label")}>
      <div className="hr-demo-top">
        <span className="eyebrow">{t("hr.home.card.label")}</span>
        <span className="pill">{t("hr.home.card.example")}</span>
      </div>
      <div className="hr-demo-score">
        <span className="gradebadge">B</span>
        <div>
          <div className="hr-scorebig">{fmt(72.4, 1)}<small>{t("hr.r.of")}</small></div>
          <span className="muted-sm">{t("hr.r.score")} · Harbourline Logistics</span>
        </div>
      </div>
      <div className="hr-demo-people">
        {people.map(([n, r, s]) => (
          <div key={n}>
            <Avatar name={n} />
            <span><b style={{ fontSize: ".9rem" }}>{n}</b> <span className="muted-sm">· {r}</span></span>
            <span className="mono" style={{ fontWeight: 700 }}>{s}</span>
          </div>
        ))}
      </div>
      <div className="hr-bars">
        {(["complementarity", "key_roles", "concentration"] as const).map((k, i) => (
          <div className="hr-bar" key={k}><span>{t(("hr.comp." + k) as DictKey)}</span><span className="t"><i style={{ width: [82, 76, 58][i] + "%" }} /></span><span className="v">{[82, 76, 58][i]}</span></div>
        ))}
      </div>
    </div>
  );
}

export function HrHome() {
  const { t } = useI18n();
  useHrTitle("");
  return (
    <>
      <section className="hr-hero">
        <div className="wrap">
          <div>
            <span className="eyebrow">{t("hr.home.eyebrow")}</span>
            <h1>{t("hr.home.h1a")} <em>{t("hr.home.h1b")}</em></h1>
            <p className="pitch">{t("hr.home.pitch")}</p>
            <p className="pitch" style={{ fontSize: ".95rem" }}>{t("hr.home.ai")}</p>
            <div className="hr-starts">
              <Link className="hr-start primary" to="/new/person">
                <b>{t("hr.home.start.person")} <span aria-hidden="true">→</span></b>
                <small>{t("hr.home.start.person.p")}</small>
              </Link>
              <Link className="hr-start" to="/new">
                <b>{t("hr.home.cta")} <span aria-hidden="true">→</span></b>
                <small>{t("hr.home.start.team.p")}</small>
              </Link>
            </div>
            <p className="legal">{t("hr.home.legal")} <Link to="/me">{t("hr.home.mine")} →</Link></p>
          </div>
          <ExampleCard />
        </div>
      </section>

      <section className="block" id="how" aria-labelledby="hr-how-h">
        <div className="wrap">
          <div className="head">
            <span className="eyebrow">{t("hr.how.eyebrow")}</span>
            <h2 id="hr-how-h">{t("hr.how.h2")}</h2>
          </div>
          <ol className="hr-steps3">
            {[1, 2, 3].map((i) => (
              <li key={i}><h3>{t(`hr.how.${i}h` as DictKey)}</h3><p>{t(`hr.how.${i}p` as DictKey)}</p></li>
            ))}
          </ol>
        </div>
      </section>

      <section className="block" aria-labelledby="hr-what-h">
        <div className="wrap">
          <div className="head">
            <span className="eyebrow">{t("hr.what.eyebrow")}</span>
            <h2 id="hr-what-h">{t("hr.what.h2")}</h2>
            <p>{t("hr.what.p")}</p>
          </div>
          <ul className="hr-parts">
            {SUBSCORE_KEYS.map((k) => (
              <li key={k}><b>{t(("hr.sub." + k) as DictKey)} <i>{WEIGHTS[k]}%</i></b><p>{t(("hr.sub." + k + ".d") as DictKey)}</p></li>
            ))}
          </ul>
        </div>
      </section>

      <section className="block" aria-labelledby="hr-priv-h">
        <div className="wrap">
          <div className="head">
            <span className="eyebrow">{t("hr.priv.eyebrow")}</span>
            <h2 id="hr-priv-h">{t("hr.priv.h2")}</h2>
          </div>
          <ul className="hr-priv">
            {[1, 2, 3, 4].map((i) => <li key={i}>{t(`hr.priv.${i}` as DictKey)}</li>)}
          </ul>
        </div>
      </section>

      <section className="block" style={{ borderTop: 0, paddingTop: 0 }}>
        <div className="wrap">
          <div className="final">
            <h2>{t("hr.home.final.h")}</h2>
            <p>{t("hr.home.final.p")}</p>
            <div className="hv-ctas"><div className="ctas">
              <a className="btn" href={ethUrl("/start")}>{t("hr.home.final.btn")}</a>
              <Link className="btn ghost hv-onDark" to="/new">{t("hr.home.cta")}</Link>
            </div></div>
          </div>
        </div>
      </section>
    </>
  );
}
