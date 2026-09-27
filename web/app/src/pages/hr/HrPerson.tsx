/* Person report: /p/:id/:tab? (person-mode report) and /r/:id/p/:key/:tab? (one person inside a team report).
   Layout and wording follow the approved prototype (hr-design/prototype.html): answer first, then evidence, then CV. */
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { Link, Navigate, useParams, useSearchParams } from "react-router-dom";
import { useI18n } from "../../i18n";
import type { DictKey } from "../../dict";
import { errText, useAuth } from "../../auth";
import { api, ApiError, type CvProfile, type PersonCard, type PersonSubScore, type Team, type TeamReport } from "../../api";
import { StatusBar } from "../../components/StatusBar";
import { ErrorBox, Loading } from "../../components/Layout";
import { useAsync } from "../../lib/hooks";
import { ACTIVE_HR, hostOf, initials, partLabel, Ring, STATUS_TONE, useHrTitle } from "./common";
import { LiveRun } from "./live";
import { EthCtas } from "./ethCta";
import { BandTrack, bandOf, bandWord, confidenceOf, ConfPill, cleanWhy, EvLabel, evOfSource, fmtDate, halfWidth, Icon, SrcChips, srcIndex, type Conf, type SrcIndex } from "./evidence";
import { CvAnalysis } from "./CvAnalysis";
import type { CvReview } from "./cvTypes";
import { ConsentFooter, MethodBox, Panel, PartsTable, ReportActions, ScoreInline, SourcesTable, TabNav } from "./reportParts";

export const PERSON_TABS = ["overview", "score", "requirements", "cv", "cvreview", "assessment", "sources"] as const;
type PTab = (typeof PERSON_TABS)[number];

/** Load a report (person or team) with polling while it runs; shared by the person and team pages. */
export function useHrReport(id: string) {
  const [params] = useSearchParams();
  const share = params.get("share");
  const { me } = useAuth();
  const q = useAsync<Team>(() => api.hrTeam(id, share), [id, share, me?.address, me?.username]);
  const active = !!q.data && ACTIVE_HR.includes(q.data.status);
  const { reload } = q;
  // poll every 2 s while it runs, every 5 s while the tab is hidden; refresh at once when the tab comes back
  useEffect(() => {
    if (!active) return;
    let dead = false;
    let timer = 0;
    const loop = () => { timer = window.setTimeout(async () => { if (dead) return; await reload(); if (!dead) loop(); }, document.hidden ? 5000 : 2000); };
    const onVis = () => { if (!document.hidden && !dead) { clearTimeout(timer); void reload().then(() => { if (!dead) { clearTimeout(timer); loop(); } }); } };
    loop();
    document.addEventListener("visibilitychange", onVis);
    return () => { dead = true; clearTimeout(timer); document.removeEventListener("visibilitychange", onVis); };
  }, [active, reload]);
  return q;
}

/** Error / progress states shared by both report pages. Returns null when the report is ready to show. */
export function ReportState({ q, id }: { q: ReturnType<typeof useHrReport>; id: string }) {
  const { t } = useI18n();
  const { me, tryDemo, busy } = useAuth();
  const [runErr, setRunErr] = useState("");
  const [running, setRunning] = useState(false);
  const team = q.data;
  if (q.loading && !team) return <Loading />;
  if (q.error && !team) {
    const e = q.error;
    const priv = e instanceof ApiError && (e.status === 401 || e.status === 403);
    return (
      <div className="wrap page stack">
        {priv ? (
          <div className="pane stateCard soft">
            <h2>{t("hr.r.private.h")}</h2>
            <p>{t("hr.r.private.p")}</p>
            <div className="row">
              {!me && <button className="btn" type="button" disabled={busy} onClick={() => void tryDemo().catch(() => undefined)}>{t("hr.me.demo")}</button>}
              <Link className="btn ghost" to="/new/person">{t("hr.nav.person")}</Link>
            </div>
          </div>
        ) : e instanceof ApiError && e.status === 404 ? <p className="quietline bad">{t("hr.r.notfound")}</p> : <ErrorBox error={e} retry={q.reload} />}
      </div>
    );
  }
  if (!team) return <Loading />;
  if (team.status === "done" && team.result) return null;
  if (team.status !== "draft") return <LiveRun team={team} onUpdate={q.setData} />;
  const run = async () => {
    setRunErr(""); setRunning(true);
    try { q.setData(await api.hrRun(team.id)); } catch (x) { setRunErr(x instanceof ApiError && x.status === 429 ? t("hr.new.limit") : errText(x, t)); } finally { setRunning(false); }
  };
  const tone = STATUS_TONE[team.status];
  return (
    <div className="wrap hp-page">
      <nav className="crumbs" aria-label={t("crumb.label")}><Link to="/me">{t("hr.nav.me")}</Link><span aria-hidden="true" className="sep">›</span><b>{team.name}</b></nav>
      <StatusBar status={t(("hr.r.st." + team.status) as DictKey)} tone={tone} since={ACTIVE_HR.includes(team.status) ? team.steps[0]?.at ?? team.created_at : null} meta={<span className="mono">{id}</span>} />
      <header className="shead"><div><span className="eyebrow">{t(team.mode === "person" ? "hr.pr.eyebrow" : "hr.r.eyebrow")}</span><h1>{team.name}</h1></div></header>
      <p className="quietline">{t("hr.r.draft.p")}</p>
      {team.can_edit && (
        <div className="row"><button className="btn" type="button" disabled={running} onClick={run}>{running ? <span className="spinner" aria-hidden="true" /> : null}{t("hr.r.run")}</button>{runErr && <span className="err" role="alert">{runErr}</span>}</div>
      )}
    </div>
  );
}

/* ---------- helpers ---------- */
function yearOf(s?: string | number | null): number | null {
  if (s == null) return null;
  const m = /(\d{4})/.exec(String(s));
  return m ? +m[1] : null;
}
function drivers(parts: Record<string, PersonSubScore>) {
  const rows = Object.entries(parts ?? {}).map(([k, s]) => ({ k, s, imp: ((Number(s.score) || 0) - 60) * (Number(s.weight) > 1 ? Number(s.weight) / 100 : Number(s.weight) || 0) }));
  const up = rows.filter((r) => r.imp > 0).sort((a, b) => b.imp - a.imp).slice(0, 2);
  const dn = rows.filter((r) => r.imp < 0).sort((a, b) => a.imp - b.imp).slice(0, 2);
  if (!dn.length) dn.push(...rows.sort((a, b) => a.imp - b.imp).slice(0, 1).filter((r) => !up.includes(r)));
  return { up, dn };
}

function ProfileCard({ card, team, ix }: { card: PersonCard; team: Team; ix: SrcIndex }) {
  const { t, fmt } = useI18n();
  const p: CvProfile = card.profile ?? {};
  const inp = team.people.find((x) => x.id === card.person_id);
  const sr = card.self_reported ?? {};
  const links = p.links?.length ? p.links : (inp?.urls ?? []).map((u) => ({ url: u, label: null }));
  const srcUrls = new Set([...ix.byId.values()].map((x) => x.s.url));
  const linkEv = (u: string) => (/linkedin\.com/i.test(u) ? "self" : srcUrls.has(u) || [...srcUrls].some((s) => hostOf(s) === hostOf(u)) ? "verified" : "unconfirmed") as "self" | "verified" | "unconfirmed";
  const years = (p.experience ?? []).map((e) => yearOf(e.start)).filter((y): y is number => y != null);
  const yrs = years.length ? new Date().getFullYear() - Math.min(...years) : null;
  const pct = p.completeness_pct;
  return (
    <section className="hp-card hp-profile" aria-label={t("hr.pr.profile")}>
      <div className="hp-ptop">
        <div className="hp-avatar" aria-hidden="true">{initials(card.full_name)}</div>
        <div><h1 className="hp-pname">{card.full_name}</h1>{card.role && <span className="muted-sm">{card.role}</span>}</div>
      </div>
      {(p.headline?.text || sr.headline) && <p className="hp-headline">{p.headline?.text || sr.headline} {p.headline?.source && <EvLabel ev={evOfSource(p.headline.source)} iconOnly />}</p>}
      <div className="hp-rel">
        <span className="hp-tag">{t(("hr.kind." + card.kind) as DictKey)}</span>
        {sr.full_time != null && <span className="hp-tag">{t(sr.full_time ? "hr.r.ft" : "hr.r.pt")}</span>}
        {sr.start_year && <span className="hp-tag">{t("hr.r.since", { y: sr.start_year })}</span>}
        {sr.equity_pct != null && <span className="hp-tag">{t("hr.r.equity", { p: fmt(sr.equity_pct, sr.equity_pct % 1 ? 1 : 0) })}</span>}
      </div>
      {(p.location?.text || yrs) && (
        <div className="hp-meta">
          {p.location?.text && <span>{Icon.pin}{p.location.text}</span>}
          {yrs != null && yrs > 0 && <span>{Icon.team}{t("hr.pr.yrs", { n: yrs })}</span>}
        </div>
      )}
      {links.length > 0 && (
        <ul className="hp-plinks" aria-label={t("hr.pr.links")}>
          {links.map((l) => <li key={l.url}><a href={l.url} target="_blank" rel="noopener noreferrer nofollow">{l.label || l.url.replace(/^https?:\/\/(www\.)?/, "")}</a><EvLabel ev={linkEv(l.url)} /></li>)}
        </ul>
      )}
      {pct != null && (
        <div className="hp-complete">
          <Ring value={pct} size={56} label={t("hr.pr.complete", { p: fmt(pct) })} />
          <div><b>{t("hr.pr.complete", { p: fmt(pct) })}</b><p>{t("hr.pr.complete.p")}</p></div>
        </div>
      )}
    </section>
  );
}

function Hero({ card, team, rep, ix, path }: { card: PersonCard; team: Team; rep: TeamReport; ix: SrcIndex; path: string }) {
  const { t, fmt } = useI18n();
  const fit = card.fit;
  const parts = fit?.components ?? card.subscores;
  const score = fit?.score ?? card.score;
  const kind = fit ? "fit" : "q";
  const { conf } = confidenceOf(parts);
  const hw = halfWidth(conf);
  const lo = Math.max(0, score - hw), hi = Math.min(100, score + hw);
  const bLo = bandOf(lo), bHi = bandOf(hi);
  const d = drivers(parts);
  const prefix = fit ? "hr.fit." : "hr.sub.";
  const tg = team.target;
  const tgName = tg?.type === "role" ? [tg.title, tg.company].filter(Boolean).join(" · ") : tg?.company || tg?.ticker || (tg?.website ? hostOf(tg.website) : team.mode === "team" ? team.name : "");
  const exp = card.profile?.experience ?? [];
  const years = exp.map((e) => yearOf(e.start)).filter((y): y is number => y != null);
  const ventures = card.profile?.ventures ?? [];
  const exits = ventures.filter((v) => /exit|acquired|ipo/i.test(String(v.outcome ?? ""))).length;
  const verified = card.facts.length;
  const selfParts = Object.values(parts).filter((s) => s.self_reported).length;
  const ann = t("hr.pr.track.aria", { s: fmt(score), b: bandWord(t, score, "high", kind), lo: fmt(lo), hi: fmt(hi), c: t(("hr.conf." + conf) as DictKey) });
  const teamCard = team.mode === "team" && rep.team;
  const eyebrow = fit ? t(fit.target_type === "role" ? "hr.pr.fit.role" : "hr.pr.fit.business") : t("hr.pr.quality.h");
  return (
    <section className="hp-card hp-hero" aria-labelledby="fit-h">
      <div className="hp-herohead">
        <div>
          <p className="eyebrow" id="fit-h" style={{ margin: 0 }}>{eyebrow}</p>
          {tgName && (
            <div className="hp-target">
              {tg?.type === "business" && tg.ticker && <span className="hp-tick">{tg.ticker}</span>}
              <b>{t("hr.pr.for", { n: tgName })}</b>
              {card.role && <span className="muted" style={{ fontSize: ".86rem" }}>· {t("hr.pr.asrole", { r: card.role })}</span>}
            </div>
          )}
        </div>
        <ReportActions team={team} path={path} />
      </div>
      <div className="hp-scoreline">
        <div>
          <div className={"hp-band" + (conf === "low" ? " low" : "")}>{bandWord(t, score, conf, kind)}</div>
          <div className="hp-range">{t("hr.pr.range", { lo: fmt(lo), hi: fmt(hi) })}{bLo !== bHi ? " · " + t("hr.pr.range.cross", { a: t(("hr.bandshort." + bandOf(score)) as DictKey), b: t(("hr.bandshort." + (bandOf(score) === bHi ? bLo : bHi)) as DictKey) }) : ""}</div>
        </div>
        <div className={"hp-bigno num" + (conf === "low" ? " low" : "")} aria-label={t("hr.pr.outof", { s: fmt(score) })}>{fmt(Math.round(score))}<small>/100</small></div>
        <div className="hp-conf">
          <ConfPill conf={conf} />
          <p>{t("hr.pr.conf.reason", { v: verified, u: card.unconfirmed.length, s: selfParts })} <b style={{ color: "var(--ink)" }}>{t("hr.pr.next")}</b> {t(("hr.next." + conf) as DictKey)}</p>
        </div>
      </div>
      <BandTrack score={score} lo={lo} hi={hi} label={ann} />
      {card.profile?.summary && <p className="hp-summary">{card.profile.summary}</p>}
      {(d.up.length > 0 || d.dn.length > 0) && (
        <div className="hp-drivers">
          <div className="up">
            <h3>{Icon.up}{t("hr.pr.up")}</h3>
            <ul>{d.up.length ? d.up.map(({ k, s }) => <li key={k}><b>{partLabel(t, prefix, k)} {fmt(s.score)}.</b> {cleanWhy(s.rationale)} <SrcChips ix={ix} factIds={s.fact_ids} /></li>) : <li className="muted">{t("hr.pr.up.none")}</li>}</ul>
          </div>
          <div className="dn">
            <h3>{Icon.down}{t("hr.pr.down")}</h3>
            <ul>{d.dn.length ? d.dn.map(({ k, s }) => <li key={k}><b>{partLabel(t, prefix, k)} {fmt(s.score)}.</b> {cleanWhy(s.rationale)} <SrcChips ix={ix} factIds={s.fact_ids} /></li>) : <li className="muted">{t("common.none")}</li>}</ul>
          </div>
        </div>
      )}
      <div className="hp-hl">
        {years.length > 0 && <div><b className="num">{fmt(new Date().getFullYear() - Math.min(...years))}</b><small>{t("hr.pr.hl.years")}</small></div>}
        <div><b className="num">{fmt(ventures.length)}</b><small>{t("hr.pr.hl.ventures")}</small></div>
        <div><b className="num">{fmt(exits)}</b><small>{t("hr.pr.hl.exits")}</small></div>
        <div><b className="num">{fmt(verified)}</b><small>{t("hr.pr.hl.facts")}</small></div>
      </div>
      {fit && <p className="hp-lead">{t("hr.pr.qualityline", { s: fmt(card.score, 0), b: t(("hr.bandshort." + bandOf(card.score)) as DictKey) })}</p>}
      {teamCard && (
        <div className="hp-teamline">
          {Icon.team}
          <span>{t("hr.pr.teamline", { m: fmt(card.multiplier ?? 1, 1), n: team.name, b: bandWord(t, rep.team!.score, "medium", "team"), s: fmt(rep.team!.score, 0) })}</span>
          <Link to={`/r/${encodeURIComponent(team.id)}${location.search}`}>{t("hr.pr.openteam")} →</Link>
        </div>
      )}
    </section>
  );
}

function Requirements({ card, ix }: { card: PersonCard; ix: SrcIndex }) {
  const { t } = useI18n();
  const reqs = card.fit?.requirements ?? [];
  if (!reqs.length) return <div className="hp-card"><p className="hp-lead">{t(card.fit ? "hr.pr.req.none" : "hr.pr.req.notarget")}</p></div>;
  const RES: Record<string, [string, ReactNode, DictKey]> = {
    matched: ["met", Icon.met, "hr.pr.res.met"], partial: ["part", Icon.part, "hr.pr.res.part"], missing: ["miss", Icon.x, "hr.pr.res.nf"], unverified: ["unv", Icon.unc, "hr.pr.res.unv"],
  };
  const hasPrio = reqs.some((r) => r.must_have === false) && reqs.some((r) => r.must_have);
  const groups: [DictKey, typeof reqs][] = hasPrio ? [["hr.pr.req.must", reqs.filter((r) => r.must_have)], ["hr.pr.req.nice", reqs.filter((r) => !r.must_have)]] : [["hr.pr.reqs", reqs]];
  const count = (list: typeof reqs) => (["matched", "partial", "missing", "unverified"] as const).map((s) => [s, list.filter((r) => r.status === s).length] as const).filter(([, n]) => n > 0);
  const ev = (r: (typeof reqs)[number]) => (r.status === "missing" ? "none" : r.fact_ids?.length ? "verified" : r.self_reported ? "self" : "unconfirmed") as "none" | "verified" | "self" | "unconfirmed";
  return (
    <div className="hp-card">
      <h2>{t("hr.pr.reqs")} <span className="count">{t("hr.pr.req.count", { n: reqs.length })}</span></h2>
      <div className="hp-reqsum">
        {groups.map(([gk, list], gi) => (
          <span key={gk} style={{ display: "contents" }}>
            {gi > 0 && <span style={{ color: "var(--line)" }}>|</span>}
            <span><b>{t(gk)}:</b></span>
            {count(list).map(([s, n]) => <span key={s} className={"hp-res " + RES[s][0]}>{RES[s][1]}{n} {t(RES[s][2]).toLowerCase()}</span>)}
          </span>
        ))}
      </div>
      <div className="hp-tbl">
        <table className="hp-req">
          <caption className="sr-only">{t("hr.pr.reqs")}</caption>
          <thead><tr><th scope="col">{t("hr.pr.col.req")}</th><th scope="col">{t("hr.pr.col.result")}</th><th scope="col">{t("hr.pr.col.evidence")}</th><th scope="col">{t("hr.pr.col.sources")}</th></tr></thead>
          <tbody>
            {groups.map(([gk, list]) => [
              hasPrio ? <tr key={gk} className="grp"><td colSpan={4}>{t(gk)}</td></tr> : null,
              ...list.map((r, i) => {
                const res = RES[r.status] ?? RES.unverified;
                return (
                  <tr key={gk + i}>
                    <td className="rq">{r.requirement}{r.note && <span className="note">{r.note}</span>}</td>
                    <td><span className={"hp-res " + res[0]}>{res[1]}{t(res[2])}</span></td>
                    <td><EvLabel ev={ev(r)} /></td>
                    <td className="srccell"><SrcChips ix={ix} factIds={r.fact_ids} /></td>
                  </tr>
                );
              }),
            ])}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function Cv({ card, ix }: { card: PersonCard; ix: SrcIndex }) {
  const { t } = useI18n();
  const p = card.profile ?? {};
  const now = new Date().getFullYear();
  const exp = [...(p.experience ?? [])].sort((a, b) => (yearOf(b.end) ?? 9999) - (yearOf(a.end) ?? 9999) || (yearOf(b.start) ?? 0) - (yearOf(a.start) ?? 0));
  const dur = (s?: string | null, e?: string | null) => { const a = yearOf(s), z = e ? yearOf(e) : now; return a != null && z != null && z >= a ? t("hr.pr.dur", { n: Math.max(1, z - a) }) : ""; };
  const skClass = (src?: { type?: string }) => (src?.type === "verified" ? "v" : src?.type === "self_reported" ? "s" : "u");
  const OUT: Record<string, [string, DictKey]> = { active: ["op", "hr.pr.out.active"], exit: ["acq", "hr.pr.out.exit"], acquired: ["acq", "hr.pr.out.acquired"], ipo: ["acq", "hr.pr.out.ipo"], closed: ["cl", "hr.pr.out.closed"], unknown: ["cl", "hr.pr.out.unknown"] };
  const empty = !exp.length && !p.education?.length && !p.skills?.length && !p.ventures?.length;
  return (
    <>
      {p.summary && <div className="hp-card"><h2>{t("hr.pr.summary")}</h2><p style={{ margin: 0 }}>{p.summary}</p></div>}
      {empty && <div className="hp-card"><p className="hp-lead">{t("hr.pr.none")}</p></div>}
      {exp.length > 0 && (
        <div className="hp-card">
          <h2>{t("hr.pr.exp")} <span className="count">{t("hr.pr.exp.count", { n: exp.length })}</span></h2>
          <ol className="hp-tl">
            {exp.map((e, i) => (
              <li key={i} className={(!e.end ? "now" : "") + (e.source?.type === "self_reported" ? " self" : "")}>
                <div className="hp-tlh"><h3>{e.title || "–"} · <span className="org">{e.org}</span></h3><span className="hp-dates">{e.start || "?"} – {e.end || t("hr.pr.present")}{dur(e.start, e.end) ? " · " + dur(e.start, e.end) : ""}</span></div>
                {e.achievements && e.achievements.length > 0 && <ul>{e.achievements.map((a, j) => <li key={j}>{a}</li>)}</ul>}
                <div className="hp-tlev"><EvLabel ev={evOfSource(e.source)} /><SrcChips ix={ix} factIds={e.source?.fact_ids} urls={e.source?.urls} /></div>
              </li>
            ))}
          </ol>
        </div>
      )}
      {((p.education?.length ?? 0) > 0 || (p.skills?.length ?? 0) > 0) && (
        <div className="hp-duo">
          {(p.education?.length ?? 0) > 0 && (
            <div className="hp-card">
              <h2>{t("hr.pr.edu")}</h2>
              <ul className="hp-edu">
                {p.education!.map((e, i) => (
                  <li key={i}>
                    <div className="row"><b>{[e.degree, e.field].filter(Boolean).join(", ") || e.institution}</b><EvLabel ev={evOfSource(e.source)} /></div>
                    <span className="muted-sm">{e.institution}{e.start || e.end ? ` · ${e.start ?? "?"} – ${e.end ?? t("hr.pr.present")}` : ""} <SrcChips ix={ix} factIds={e.source?.fact_ids} urls={e.source?.urls} /></span>
                  </li>
                ))}
              </ul>
              <p className="hp-foot">{t("hr.pr.edu.note")}</p>
            </div>
          )}
          {(p.skills?.length ?? 0) > 0 && (
            <div className="hp-card">
              <h2>{t("hr.pr.skills")}</h2>
              <div className="hp-skills">
                {p.skills!.map((g, i) => (
                  <div key={i}><h3>{g.group}</h3><div className="hp-chips">{g.items.map((s) => <span key={s} className={"hp-sk " + skClass(g.source)}>{s}</span>)}</div></div>
                ))}
              </div>
              <div className="hp-legend"><span><span className="hp-sk v">{t("hr.ev.verified")}</span></span><span><span className="hp-sk s">{t("hr.ev.self")}</span></span><span><span className="hp-sk u">{t("hr.ev.unconfirmed")}</span></span></div>
            </div>
          )}
        </div>
      )}
      {(p.ventures?.length ?? 0) > 0 && (
        <div className="hp-card">
          <h2>{t("hr.pr.ventures")} <span className="count">{t("hr.pr.ventures.count", { n: p.ventures!.length, x: p.ventures!.filter((v) => /exit|acquired|ipo/i.test(String(v.outcome))).length })}</span></h2>
          <div className="hp-ventures">
            {p.ventures!.map((v, i) => {
              const o = OUT[String(v.outcome ?? "unknown")] ?? OUT.unknown;
              return (
                <article key={i} className="hp-vc">
                  <span className={"hp-outcome " + o[0]}>{t(o[1])}</span>
                  <h3>{v.name}</h3>
                  <p className="role">{[v.role, v.year].filter(Boolean).join(" · ")}</p>
                  <span><EvLabel ev={evOfSource(v.source)} /> <SrcChips ix={ix} factIds={v.source?.fact_ids} urls={v.source?.urls} /></span>
                </article>
              );
            })}
          </div>
        </div>
      )}
      {((p.publications?.length ?? 0) > 0 || (p.awards?.length ?? 0) > 0) && (
        <div className="hp-duo">
          {(p.publications?.length ?? 0) > 0 && <div className="hp-card"><h2>{t("hr.pr.pubs")}</h2><ul className="hp-list">{p.publications!.map((x, i) => <li key={i}>{x.title}{x.venue ? ` · ${x.venue}` : ""}{x.year ? ` · ${x.year}` : ""} <EvLabel ev={evOfSource(x.source)} iconOnly /></li>)}</ul></div>}
          {(p.awards?.length ?? 0) > 0 && <div className="hp-card"><h2>{t("hr.pr.awards")}</h2><ul className="hp-list">{p.awards!.map((x, i) => <li key={i}>{x.title}{x.year ? ` · ${x.year}` : ""} <EvLabel ev={evOfSource(x.source)} iconOnly /></li>)}</ul></div>}
        </div>
      )}
    </>
  );
}

function Assessment({ card }: { card: PersonCard }) {
  const { t } = useI18n();
  const check = [...card.gaps, ...(card.fit?.risks ?? [])];
  const qs = [...(card.fit?.interview_questions ?? []), ...card.questions];
  return (
    <>
      <div className="hp-card">
        <h2>{t("hr.pr.sr")}</h2>
        <div className="hp-sr">
          <div className="st"><h3>{Icon.up}{t("hr.r.strengths")}</h3>{card.strengths.length ? <ul>{card.strengths.map((s, i) => <li key={i}>{s}</li>)}</ul> : <p className="muted-sm">{t("common.none")}</p>}</div>
          <div className="rk"><h3>{Icon.conf}{t("hr.pr.check")}</h3>{check.length ? <ul>{check.map((s, i) => <li key={i}>{s}</li>)}</ul> : <p className="muted-sm">{t("common.none")}</p>}</div>
        </div>
      </div>
      {qs.length > 0 && (
        <div className="hp-card">
          <h2>{t("hr.pr.questions", { n: card.full_name.split(/\s+/)[0] })} <span className="count">{t("hr.pr.questions.p")}</span></h2>
          <ol className="hp-qs">{qs.map((q, i) => <li key={i}><div>{q}</div></li>)}</ol>
        </div>
      )}
      {card.unconfirmed.length > 0 && (
        <div className="hp-card">
          <h2>{t("hr.pr.unconf")} <span className="count">{card.unconfirmed.length}</span></h2>
          <p className="hp-lead">{t("hr.r.unconf.tip")}</p>
          <ul className="hp-facts">
            {card.unconfirmed.map((u, i) => (
              <li key={i} className="u"><span>{u.text} <EvLabel ev="unconfirmed" /></span>{u.reason && <small className="muted-sm">{u.reason}</small>}{u.url && <a href={u.url} target="_blank" rel="noopener noreferrer nofollow">{u.url.replace(/^https?:\/\//, "")}</a>}</li>
            ))}
          </ul>
        </div>
      )}
    </>
  );
}

function Facts({ card, ix }: { card: PersonCard; ix: SrcIndex }) {
  const { t } = useI18n();
  if (!card.facts.length) return null;
  return (
    <div className="hp-card">
      <h2>{t("hr.r.facts")} <span className="count">{card.facts.length}</span></h2>
      <ul className="hp-facts">
        {card.facts.map((f) => (
          <li key={f.id}><span>{f.text} <EvLabel ev="verified" iconOnly /> <SrcChips ix={ix} factIds={[f.id]} /></span>{f.quote && <q>{f.quote}</q>}</li>
        ))}
      </ul>
    </div>
  );
}

/** The full person report for one PersonCard. */
export function PersonReport({ team, card, base, tab }: { team: Team; card: PersonCard; base: string; tab: PTab }) {
  const { t, fmt, lang } = useI18n();
  const rep = team.result!;
  const ix = useMemo(() => srcIndex(rep, card), [rep, card]);
  const parts = card.fit?.components ?? card.subscores;
  const conf: Conf = confidenceOf(parts).conf;
  const c = rep.counters ?? {};
  const cvr = (card as PersonCard & { cv_review?: CvReview }).cv_review;
  const tabs: [PTab, DictKey, number?][] = [
    ["overview", "hr.tab.overview"], ["score", "hr.tab.score"], ["requirements", "hr.tab.requirements", card.fit?.requirements?.length],
    ["cv", "hr.tab.cv"], ...(cvr ? [["cvreview", "hr3.tab"] as [PTab, DictKey]] : []), ["assessment", "hr.tab.assessment"], ["sources", "hr.tab.sources", ix.byId.size],
  ];
  const path = base.replace(/\/$/, "");
  const tgv = team.target;
  const bizTarget = tgv?.type === "business" ? tgv : team.mode === "team" ? { type: "business" as const, website: team.website, valuation_id: team.valuation_id, company: team.name } : null;
  return (
    <div className="wrap hp-page">
      <div className="hp-printhead">
        <span className="brand"><span className="brand-name">BlockID<span className="brand-tld"> HR</span></span></span>
        <span>{t("hr.pr.eyebrow")} <b className="mono">{team.id}</b> · {fmtDate(new Date().toISOString(), lang)} · hr.blockid.au{path}</span>
      </div>
      <nav className="crumbs hr-noprint" aria-label={t("crumb.label")}>
        <Link to="/me">{t("hr.nav.me")}</Link><span aria-hidden="true" className="sep">›</span>
        {team.mode === "team" && <><Link to={`/r/${encodeURIComponent(team.id)}${location.search}`}>{team.name}</Link><span aria-hidden="true" className="sep">›</span></>}
        <b>{card.full_name}</b>
      </nav>
      <StatusBar status={t("hr.r.st.done")} tone="ok" meta={<span className="num">{t("hr.pr.sbmeta", { s: fmt(c.searches ?? 0), p: fmt(c.pages_fetched ?? rep.sources.length), f: fmt(card.facts.length) })} · <span className="mono">{team.id}</span></span>}
        next={{ label: t("hr.pr.pdf"), onClick: () => window.print() }} />
      {team.is_demo && <p className="quietline hr-noprint" style={{ margin: 0 }}>{t("hr.r.demo")}</p>}
      <TabNav base={path} tabs={tabs} cur={tab} label={t("hr.pr.menu")} />
      <div className="hp-report">
        <aside className="hp-side" aria-label={t("hr.pr.profile")}>
          <ProfileCard card={card} team={team} ix={ix} />
        </aside>
        <div className="hp-main">
          <Panel id="overview" cur={tab} title={t("hr.tab.overview")}>
            <Hero card={card} team={team} rep={rep} ix={ix} path={path} />
            {cvr?.timeline && (
              <Link className="hx-cvcallout hr-noprint" to={`${path}/cvreview${location.search}`}>
                <span className="ic" aria-hidden="true">CV</span>
                <span><b>{t("hr3.ov.h")}</b><small>{t("hr3.ov.p", { y: fmt(cvr.timeline.stats.years), r: fmt(cvr.timeline.stats.roles), g: fmt(cvr.timeline.stats.gaps.length), c: fmt(cvr.claims.filter((x) => x.status === "confirmed").length), m: fmt(cvr.claims.length) })}</small></span>
                <span className="go">{t("hr3.ov.open")} →</span>
              </Link>
            )}
            {bizTarget && <EthCtas website={bizTarget.website ?? team.website} valuationId={bizTarget.valuation_id ?? team.valuation_id} name={bizTarget.company ?? (team.mode === "team" ? team.name : null)} />}
          </Panel>
          <Panel id="score" cur={tab} title={t("hr.tab.score")}>
            {card.fit && (
              <div className="hp-card">
                <h2>{t(card.fit.target_type === "role" ? "hr.pr.fit.role" : "hr.pr.fit.business")} <span className="count">{t("hr.pr.parts.n", { n: Object.keys(card.fit.components).length })}</span></h2>
                <p className="hp-lead">{t("hr.pr.parts.lead", { c: rep.method?.cap_without_evidence ?? 50 })}</p>
                <PartsTable parts={card.fit.components} prefix="hr.fit." ix={ix} cap={rep.method?.cap_without_evidence ?? 50} kind="fit" conf={conf} />
              </div>
            )}
            <div className="hp-card">
              <h2>{t("hr.pr.quality.h")} <span className="count">{t("hr.pr.parts.n", { n: Object.keys(card.subscores).length })}</span></h2>
              <p className="hp-lead">{t("hr.pr.parts.lead", { c: rep.method?.cap_without_evidence ?? 50 })}</p>
              <PartsTable parts={card.subscores} prefix="hr.sub." ix={ix} cap={rep.method?.cap_without_evidence ?? 50} kind="q" conf={confidenceOf(card.subscores).conf} />
            </div>
            <div className="hp-card"><h2>{t("hr.pr.method.title")}</h2><MethodBox rep={rep} team={team} /></div>
          </Panel>
          <Panel id="requirements" cur={tab} title={t("hr.tab.requirements")}><Requirements card={card} ix={ix} /></Panel>
          <Panel id="cv" cur={tab} title={t("hr.tab.cv")}><Cv card={card} ix={ix} /></Panel>
          <Panel id="cvreview" cur={tab} title={t("hr3.tab")}><CvAnalysis rv={cvr} ix={ix} /></Panel>
          <Panel id="assessment" cur={tab} title={t("hr.tab.assessment")}><Assessment card={card} /></Panel>
          <Panel id="sources" cur={tab} title={t("hr.tab.sources")}>
            <div className="hp-card">
              <h2>{t("hr.pr.sources")} <span className="count">{t("hr.pr.sources.count", { n: ix.byId.size })}</span></h2>
              <SourcesTable ix={ix} />
            </div>
            <Facts card={card} ix={ix} />
            <ConsentFooter team={team} names={card.full_name} />
          </Panel>
          <p className="muted-sm hr-noprint" style={{ margin: 0 }}><ScoreInline score={card.fit?.score ?? card.score} conf={conf} kind={card.fit ? "fit" : "q"} /> · {t("hr.r.advisory")}</p>
        </div>
      </div>
    </div>
  );
}

/** Route element for /p/:id/:tab? and /r/:id/p/:key/:tab?. */
export function HrPersonPage() {
  const { id = "", key, tab: rawTab } = useParams();
  const { t } = useI18n();
  const q = useHrReport(id);
  const team = q.data;
  const tab = (PERSON_TABS as readonly string[]).includes(rawTab ?? "") ? (rawTab as PTab) : "overview";
  const rep = team?.status === "done" ? team.result : null;
  let card: PersonCard | undefined;
  if (rep && key) {
    const m = /^n(\d+)$/.exec(key);
    card = m ? rep.people[+m[1] - 1] : rep.people.find((c) => String(c.person_id) === key);
  } else if (rep) card = rep.people[0];
  useHrTitle(card?.full_name ?? team?.name ?? t("hr.pr.eyebrow"));
  if (!team || !rep) return <ReportState q={q} id={id} />;
  if (!key && team.mode === "team") return <Navigate to={`/r/${encodeURIComponent(id)}${location.search}`} replace />;
  if (!card) return <div className="wrap page"><p className="quietline bad">{t("hr.r.notfound")}</p><Link to={`/r/${encodeURIComponent(id)}`}>{t("hr.pr.openteam")} →</Link></div>;
  const base = key ? `/r/${encodeURIComponent(id)}/p/${encodeURIComponent(key)}` : `/p/${encodeURIComponent(id)}`;
  return <PersonReport team={team} card={card} base={base} tab={tab} />;
}
