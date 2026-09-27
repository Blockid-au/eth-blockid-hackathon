/* Team report /r/:id/:tab? — tabs: Overview · People · Gaps & risks · Sources. A person-mode report redirects to /p/:id. */
import { useMemo } from "react";
import { Link, Navigate, useParams } from "react-router-dom";
import { useI18n } from "../../i18n";
import type { DictKey } from "../../dict";
import { TEAM_COMPONENTS, type PersonCard, type Team, type TeamFunction } from "../../api";
import { StatusBar } from "../../components/StatusBar";
import { EthCtas } from "./ethCta";
import { initials, partLabel, useHrTitle } from "./common";
import { BandTrack, bandOf, bandWord, confidenceOf, ConfPill, EvLabel, fmtDate, halfWidth, Icon, srcIndex, type Conf } from "./evidence";
import { ConsentFooter, MethodBox, Panel, ReportActions, ScoreInline, SourcesTable, TabNav } from "./reportParts";
import { ReportState, useHrReport } from "./HrPerson";

const TEAM_TABS = ["overview", "people", "gaps", "sources"] as const;
type TTab = (typeof TEAM_TABS)[number];
const FUNCS: TeamFunction[] = ["tech", "commercial", "domain", "finance"];

function personConf(c: PersonCard): Conf { return confidenceOf(c.fit?.components ?? c.subscores).conf; }
function teamConf(people: PersonCard[]): Conf {
  const all = Object.assign({}, ...people.map((c, i) => Object.fromEntries(Object.entries(c.fit?.components ?? c.subscores).map(([k, s]) => [i + k, s]))));
  return confidenceOf(all).conf;
}

function TeamReportView({ team, tab }: { team: Team; tab: TTab }) {
  const { t, fmt, lang } = useI18n();
  const rep = team.result!;
  const tb = rep.team!;
  const ix = useMemo(() => srcIndex(rep, null), [rep]);
  const conf = teamConf(rep.people);
  const hw = halfWidth(conf);
  const lo = Math.max(0, tb.score - hw), hi = Math.min(100, tb.score + hw);
  const base = `/r/${encodeURIComponent(team.id)}`;
  const people = [...rep.people].sort((a, b) => (b.multiplier ?? 1) - (a.multiplier ?? 1));
  const pUrl = (c: PersonCard) => `${base}/p/${c.person_id}${location.search}`;
  const valId = team.valuation_id;
  const tabs: [TTab, DictKey, number?][] = [["overview", "hr.tab.overview"], ["people", "hr.tab.people", rep.people.length], ["gaps", "hr.tab.gaps"], ["sources", "hr.tab.sources", ix.byId.size]];
  const points = (tb.score * 0.3);
  return (
    <div className="wrap hp-page">
      <div className="hp-printhead">
        <span className="brand"><span className="brand-name">BlockID<span className="brand-tld"> HR</span></span></span>
        <span>{t("hr.r.eyebrow")} <b className="mono">{team.id}</b> · {fmtDate(new Date().toISOString(), lang)} · hr.blockid.au{base}</span>
      </div>
      <nav className="crumbs hr-noprint" aria-label={t("crumb.label")}><Link to="/me">{t("hr.nav.me")}</Link><span aria-hidden="true" className="sep">›</span><b>{team.name}</b></nav>
      <StatusBar status={t("hr.r.st.done")} tone="ok"
        meta={<span className="num">{t("hr.pr.sbmeta", { s: fmt(rep.counters?.searches ?? 0), p: fmt(rep.counters?.pages_fetched ?? rep.sources.length), f: fmt(rep.counters?.facts_verified ?? 0) })} · <span className="mono">{team.id}</span></span>}
        next={{ label: t("hr.pr.pdf"), onClick: () => window.print() }} />
      <header className="shead">
        <div>
          <span className="eyebrow">{t("hr.r.eyebrow")}{team.is_demo ? " · " + t("hr.r.demo") : ""}</span>
          <h1>{team.name}</h1>
          {team.website && <p><a href={team.website} target="_blank" rel="noopener noreferrer nofollow">{team.website.replace(/^https?:\/\//, "")}</a></p>}
        </div>
        <ReportActions team={team} path={base} />
      </header>
      <TabNav base={base} tabs={tabs} cur={tab} label={t("hr.pr.menu")} />

      <Panel id="overview" cur={tab} title={t("hr.tab.overview")}>
        <section className="hp-card hp-hero" aria-labelledby="team-h">
          <div className="hp-teamhero">
            <div style={{ display: "grid", gap: 14 }}>
              <p className="eyebrow" id="team-h" style={{ margin: 0 }}>{t("hr.r.score")}</p>
              <div className="hp-scoreline">
                <div><div className={"hp-band" + (conf === "low" ? " low" : "")}>{bandWord(t, tb.score, conf, "team")}</div><div className="hp-range">{t("hr.pr.range", { lo: fmt(lo), hi: fmt(hi) })} · {t("ad.c.grade")} {tb.grade}</div></div>
                <div className={"hp-bigno num" + (conf === "low" ? " low" : "")}>{fmt(Math.round(tb.score))}<small>/100</small></div>
              </div>
              <ConfPill conf={conf} />
              <BandTrack score={tb.score} lo={lo} hi={hi} label={t("hr.pr.track.aria", { s: fmt(tb.score), b: bandWord(t, tb.score, "high", "team"), lo: fmt(lo), hi: fmt(hi), c: t(("hr.conf." + conf) as DictKey) })} />
              <p className="hp-lead">{t("hr.tr.formula", { p: fmt(tb.people_component ?? 0, 1), f: fmt(tb.team_component ?? 0, 1), r: fmt(tb.red_flag_penalty ?? 0, 1) })}</p>
            </div>
            <div className="hp-contrib">
              <h3 className="eyebrow" style={{ margin: 0 }}>{t("hr.tr.contrib")}</h3>
              <div className="hp-stack" role="img" aria-label={t("hr.tr.contrib.aria", { s: fmt(points, 1) })}>
                <i style={{ width: points + "%", background: "var(--accent)" }} />
                <i style={{ width: 30 - points + "%", background: "var(--accent-soft)" }} />
                <i style={{ width: "70%", background: "var(--sunken)" }} />
              </div>
              <p className="hp-lead">{t("hr.tr.contrib.p", { s: fmt(tb.score, 0), x: fmt(points, 1) })}</p>
              {valId ? <p className="hp-lead"><b>{t("hr.r.valuation")}.</b> {t("hr.r.valuation.p")}</p> : <p className="hp-lead">{t("hr.tr.noval")}</p>}
            </div>
          </div>
        </section>
        <EthCtas website={team.website ?? (team.target?.type === "business" ? team.target.website : null)} valuationId={valId} name={team.name} />
        <div className="hp-card">
          <h2>{t("hr.tr.comp")} <span className="count">{t("hr.tr.comp.n", { n: rep.people.length })}</span></h2>
          <div className="hp-tbl">
            <table className="hp-comp hp-teamcomp">
              <thead><tr><th scope="col">{t("hr.np.sum.person")}</th><th scope="col">{t("hr.p.kind")}</th><th scope="col" className="r">{t("hr.tr.weight")}</th><th scope="col">{t("hr.me.col.score")}</th><th scope="col" /></tr></thead>
              <tbody>
                {people.map((c) => (
                  <tr key={c.person_id}>
                    <td className="lbl"><b>{c.full_name}</b><span className="why">{c.role}</span></td>
                    <td>{t(("hr.kind." + c.kind) as DictKey)}</td>
                    <td className="r mono">{fmt(c.multiplier ?? 1, 1)}×</td>
                    <td><ScoreInline score={c.fit?.score ?? c.score} conf={personConf(c)} kind={c.fit ? "fit" : "q"} /></td>
                    <td className="r"><Link to={pUrl(c)}>{t("hr.tr.open")} →</Link></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
        <div className="hp-panel">
          <div className="hp-card">
            <h2>{t("hr.r.map")}</h2>
            <p className="hp-lead">{t("hr.r.map.p")}</p>
            <div className="hp-tbl">
              <table className="hp-map">
                <thead><tr><th scope="col">{t("hr.np.sum.person")}</th>{FUNCS.map((f) => <th key={f} scope="col">{t(("hr.fn." + f) as DictKey)}</th>)}</tr></thead>
                <tbody>
                  {people.map((c) => <tr key={c.person_id}><td>{c.full_name}</td>{FUNCS.map((f) => <td key={f}>{c.functions.includes(f) ? <span className="on">{Icon.met}<span className="sr-only">{t("hr.r.map.covered")}</span></span> : <span className="muted" aria-label="–">·</span>}</td>)}</tr>)}
                </tbody>
                <tfoot><tr><td>{t("hr.tr.team")}</td>{FUNCS.map((f) => <td key={f}>{tb.coverage?.[f] ? <span className="on">{Icon.met}{t("hr.r.map.covered")}</span> : <span className="gap">{Icon.conf}{t("hr.r.map.gap")}</span>}</td>)}</tr></tfoot>
              </table>
            </div>
          </div>
          <div className="hp-card">
            <h2>{t("hr.r.radar")}</h2>
            <div className="hr-bars">
              {TEAM_COMPONENTS.filter((k) => tb.components?.[k] != null).map((k) => {
                const v = Math.max(0, Math.min(100, Number(tb.components[k]) || 0));
                const why = tb.component_detail?.[k]?.rationale;
                return (
                  <div className="hr-bar" key={k} title={why || undefined}>
                    <span>{partLabel(t, "hr.comp.", k)}{why && <small>{why}</small>}</span>
                    <span className="t"><i className={v < 50 ? "low" : ""} style={{ width: v + "%" }} /></span>
                    <span className="v">{fmt(v)}</span>
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      </Panel>

      <Panel id="people" cur={tab} title={t("hr.tab.people")}>
        <div className="hp-people">
          {people.map((c) => {
            const pc = personConf(c), sc = c.fit?.score ?? c.score;
            return (
              <article key={c.person_id} className="hp-pc">
                <div className="hp-pc-head">
                  <span className="hp-avatar" aria-hidden="true">{initials(c.full_name)}</span>
                  <span><b>{c.full_name}</b><small>{c.role} · {t(("hr.kind." + c.kind) as DictKey)} · {fmt(c.multiplier ?? 1, 1)}×</small></span>
                  <span className="num">{fmt(Math.round(sc))}<small>{bandWord(t, sc, pc, c.fit ? "fit" : "q")}</small></span>
                </div>
                <ConfPill conf={pc} />
                {c.strengths[0] && <p style={{ margin: 0, fontSize: ".88rem" }}><b>{t("hr.card.top")}:</b> {c.strengths[0]}</p>}
                {c.gaps[0] && <p style={{ margin: 0, fontSize: ".88rem" }}><b>{t("hr.card.gap")}:</b> {c.gaps[0]}</p>}
                <div className="row" style={{ justifyContent: "space-between" }}>
                  <span className="row" style={{ gap: 6 }}><EvLabel ev="verified" /> <span className="muted-sm">{fmt(c.facts.length)}</span>{c.unconfirmed.length > 0 && <><EvLabel ev="unconfirmed" /> <span className="muted-sm">{fmt(c.unconfirmed.length)}</span></>}</span>
                  <Link className="btn ghost sm" to={pUrl(c)}>{t("hr.tr.open")} →</Link>
                </div>
              </article>
            );
          })}
        </div>
      </Panel>

      <Panel id="gaps" cur={tab} title={t("hr.tab.gaps")}>
        <div className="hp-card">
          <h2>{t("hr.pr.sr")}</h2>
          <div className="hp-sr">
            <div className="st"><h3>{Icon.up}{t("hr.r.strengths")}</h3>{tb.strengths.length ? <ul>{tb.strengths.map((s, i) => <li key={i}>{s}</li>)}</ul> : <p className="muted-sm">{t("common.none")}</p>}</div>
            <div className="rk"><h3>{Icon.conf}{t("hr.r.gaps")}</h3>{tb.gaps.length ? <ul>{tb.gaps.map((s, i) => <li key={i}>{s}</li>)}</ul> : <p className="muted-sm">{t("common.none")}</p>}</div>
          </div>
        </div>
        {tb.risks.length > 0 && <div className="hp-card"><h2>{t("hr.r.risks")}</h2><ul className="hp-list">{tb.risks.map((s, i) => <li key={i}>{s}</li>)}</ul></div>}
        {(tb.red_flags?.length ?? 0) > 0 && <div className="hp-card"><h2>{t("hr.r.flags")}</h2><ul className="hp-list">{tb.red_flags!.map((f, i) => <li key={i}>{f.text}</li>)}</ul></div>}
        {tb.questions.length > 0 && (
          <div className="hp-card"><h2>{t("hr.r.questions")} <span className="count">{t("hr.tr.q.p")}</span></h2><ol className="hp-qs">{tb.questions.map((q, i) => <li key={i}><div>{q}</div></li>)}</ol></div>
        )}
      </Panel>

      <Panel id="sources" cur={tab} title={t("hr.tab.sources")}>
        <div className="hp-card"><h2>{t("hr.pr.sources")} <span className="count">{t("hr.pr.sources.count", { n: ix.byId.size })}</span></h2><SourcesTable ix={ix} /></div>
        <div className="hp-card"><h2>{t("hr.pr.method.title")}</h2><MethodBox rep={rep} team={team} /></div>
        <ConsentFooter team={team} names={rep.people.map((c) => c.full_name).join(", ")} />
      </Panel>
      <p className="muted-sm hr-noprint" style={{ margin: 0 }}>{t("hr.r.advisory")}</p>
    </div>
  );
}

export function HrReport() {
  const { id = "", tab: rawTab } = useParams();
  const { t } = useI18n();
  const q = useHrReport(id);
  const team = q.data;
  useHrTitle(team?.name ?? t("hr.r.eyebrow"));
  const tab = (TEAM_TABS as readonly string[]).includes(rawTab ?? "") ? (rawTab as TTab) : "overview";
  if (team?.mode === "person") return <Navigate to={`/p/${encodeURIComponent(id)}${location.search}`} replace />;
  if (!team || team.status !== "done" || !team.result) return <ReportState q={q} id={id} />;
  if (!team.result.team) return <Navigate to={`/p/${encodeURIComponent(id)}${location.search}`} replace />;
  return <TeamReportView team={team} tab={tab} />;
}

export { bandOf };
