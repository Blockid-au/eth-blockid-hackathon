/* /method — how the scores work (same rules as the method box on every report). */
import { Link } from "react-router-dom";
import { useI18n } from "../../i18n";
import type { DictKey } from "../../dict";
import { FIT_KEYS, SUBSCORE_KEYS, TEAM_COMPONENTS } from "../../api";
import { BAND_EDGES, EvLabel, type Ev } from "./evidence";
import { useHrTitle } from "./common";

const PW: Record<string, number> = { domain_fit: 25, track_record: 25, leadership: 15, functional_depth: 15, verifiability: 10, commitment: 10 };

export function HrMethod() {
  const { t } = useI18n();
  useHrTitle(t("hr.nav.how"));
  const EVS: [Ev, DictKey][] = [["verified", "hr.ev.verified.d"], ["self", "hr.ev.self.d"], ["unconfirmed", "hr.ev.unconfirmed.d"], ["none", "hr.ev.none.d"], ["conflict", "hr.ev.conflict.d"]];
  return (
    <div className="wrap hp-page">
      <header className="shead"><div><span className="eyebrow">{t("hr.brand")}</span><h1>{t("hr.nav.how")}</h1><p>{t("hr.m.p")}</p></div></header>
      <div className="hp-duo">
        <section className="hp-card">
          <h2>{t("hr.pr.quality.h")} <span className="count">{t("hr.pr.parts.n", { n: 6 })}</span></h2>
          <table className="hp-comp"><tbody>
            {SUBSCORE_KEYS.map((k) => <tr key={k}><td className="lbl"><b>{t(("hr.sub." + k) as DictKey)}</b><span className="why">{t(("hr.sub." + k + ".d") as DictKey)}</span></td><td className="r mono">{PW[k]}%</td></tr>)}
          </tbody></table>
          <p className="hp-capnote"><i />{t("hr.pr.capnote", { c: 50 })}</p>
        </section>
        <section className="hp-card">
          <h2>{t("hr.m.fit")}</h2>
          <p className="hp-lead">{t("hr.m.fit.p")}</p>
          <ul className="hp-list">{FIT_KEYS.map((k) => <li key={k}>{t(("hr.fit." + k) as DictKey)}</li>)}</ul>
          <h2 style={{ marginTop: 8 }}>{t("hr.m.team")}</h2>
          <p className="hp-lead">{t("hr.pr.m.team")}</p>
          <ul className="hp-list">{TEAM_COMPONENTS.map((k) => <li key={k}>{t(("hr.comp." + k) as DictKey)}</li>)}</ul>
        </section>
      </div>
      <div className="hp-duo">
        <section className="hp-card">
          <h2>{t("hr.m.bands")}</h2>
          <table className="hp-comp"><tbody>
            {[...BAND_EDGES].reverse().map(([b, lo, hi]) => <tr key={b}><td className="lbl"><b>{t(("hr.band.fit." + b) as DictKey)}</b></td><td className="r mono">{lo}–{b === "strong" ? 100 : hi - 1}</td></tr>)}
          </tbody></table>
          <p className="hp-lead">{t("hr.m.conf")}</p>
        </section>
        <section className="hp-card">
          <h2>{t("hr.m.ev")}</h2>
          <ul className="hp-facts">{EVS.map(([e, d]) => <li key={e}><span><EvLabel ev={e} /></span><small className="muted-sm">{t(d)}</small></li>)}</ul>
        </section>
      </div>
      <section className="hp-consent">
        <h2>{t("hr.pr.cf.h")}</h2>
        <div><p>{t("hr.priv.1")}</p><p style={{ marginTop: 8 }}>{t("hr.priv.4")}</p></div>
        <div><p><b>{t("hr.pr.cf.never")}</b></p><ul><li>{t("hr.pr.cf.n1")}</li><li>{t("hr.pr.cf.n2")}</li><li>{t("hr.pr.cf.n3")}</li><li>{t("hr.pr.cf.n4")}</li></ul></div>
        <p className="legal">{t("hr.r.advisory")}</p>
      </section>
      <div className="row"><Link className="btn" to="/new/person">{t("hr.nav.person")}</Link><Link className="btn ghost" to="/new">{t("hr.nav.new")}</Link></div>
    </div>
  );
}
