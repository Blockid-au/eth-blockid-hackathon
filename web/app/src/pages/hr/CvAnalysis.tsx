/* CV analysis: the report tab (card.cv_review) and the live panel that fills in part by part while the run goes
   (partial.people[].cv). Everything here comes from the person's own CV (self-reported); a claim turns
   "confirmed" only when a verified public fact names the same organisation. */
import type { ReactNode } from "react";
import { useI18n } from "../../i18n";
import type { DictKey } from "../../dict";
import { Icon, SrcChips, type SrcIndex } from "./evidence";
import { monthOf, type CvClaimR, type CvLive, type CvReview, type CvRoleR, type CvSkillR, type CvTimeline } from "./cvTypes";

const LEVELS: CvSkillR["level"][] = ["expert", "strong", "working"];
const LV_N: Record<CvSkillR["level"], number> = { expert: 3, strong: 2, working: 1 };

function useDur() {
  const { t, fmt } = useI18n();
  return (m: number | null | undefined) => {
    if (m == null) return "–";
    const y = Math.floor(m / 12), r = m % 12;
    return y && r ? t("hr3.dur.ym", { y: fmt(y), m: fmt(r) }) : y ? t("hr3.dur.y", { y: fmt(y) }) : t("hr3.dur.m", { m: fmt(Math.max(1, r)) });
  };
}

function Stat({ v, l, tone }: { v: ReactNode; l: string; tone?: "warn" | "ok" }) {
  return <div className={"hx-cvstat" + (tone ? " " + tone : "")}><b className="num">{v}</b><small>{l}</small></div>;
}

/** Main roles overlapping another by more than 3 months, counting only roles whose dates carry a month
    (a year-only end like "2013" reads as December and would flag normal job changes). */
function preciseOverlaps(roles: CvRoleR[]): number {
  const precise = (x: string) => /present|current|nay|hiện/i.test(x) || /\b(19|20)\d\d[-/.]\d{1,2}\b|\b\d{1,2}[-/.](19|20)\d\d\b|[a-z]{3,}\.? ?(19|20)\d\d/i.test(x);
  const main = roles.filter((r) => ["employee", "founder", "freelance"].includes(r.kind) && precise(r.start) && precise(r.end))
    .map((r) => [monthOf(r.start)!, monthOf(r.end, true)!] as const).filter(([a, z]) => a != null && z != null).sort((x, y) => x[0] - y[0]);
  let n = 0;
  for (let k = 1; k < main.length; k++) if (main.slice(0, k).some(([, z]) => main[k][0] < z - 2)) n++;
  return n;
}

/** Horizontal career chart: one bar per role on a shared year axis; breaks of 6+ months shaded. */
function Gantt({ tl }: { tl: CvTimeline }) {
  const { t, fmt } = useI18n();
  const dur = useDur();
  const rows = tl.roles.map((r) => ({ r, a: monthOf(r.start), z: monthOf(r.end, true) ?? monthOf(r.start, true) })).filter((x): x is { r: CvRoleR; a: number; z: number } => x.a != null && x.z != null);
  if (!rows.length) return null;
  const lo = Math.min(...rows.map((x) => x.a)), hi = Math.max(...rows.map((x) => x.z)) + 1;
  const y0 = Math.floor(lo / 12), y1 = Math.ceil(hi / 12);
  const span = Math.max(12, y1 * 12 - y0 * 12);
  const pos = (m: number) => ((m - y0 * 12) / span) * 100;
  const step = span / 12 > 16 ? 4 : span / 12 > 8 ? 2 : 1;
  const ticks = Array.from({ length: Math.floor((y1 - y0) / step) + 1 }, (_, i) => y0 + i * step);
  const gaps = tl.stats.gaps.map((g) => ({ g, a: monthOf(g.from)!, z: monthOf(g.to, true)! + 1 })).filter((x) => x.a != null && x.z != null);
  return (
    <div className="hx-gantt" role="img" aria-label={t("hr3.tl.aria", { n: fmt(rows.length), y: fmt(tl.stats.years) })}>
      <div className="axis" aria-hidden="true"><span className="lbl" />
        <span className="track">{ticks.map((y) => <i key={y} style={{ left: pos(y * 12) + "%" }}>{y}</i>)}</span>
      </div>
      {rows.map(({ r, a, z }, i) => (
        <div className="row" key={i}>
          <span className="lbl"><b>{r.title || "–"}</b><small>{r.org}</small></span>
          <span className="track">
            {gaps.map(({ a: ga, z: gz }, j) => <em key={j} className="gap" style={{ left: pos(ga) + "%", width: pos(gz) - pos(ga) + "%" }} />)}
            <i className={"bar k-" + r.kind + (/present|current|nay|hiện/i.test(r.end) ? " now" : "")} style={{ left: pos(a) + "%", width: Math.max(1.2, pos(z + 1) - pos(a)) + "%" }} title={`${r.start || "?"} – ${r.end || "?"} · ${dur(r.months)}`} />
          </span>
        </div>
      ))}
      <div className="legend"><span><i className="bar" />{t("hr3.tl.role")}</span><span><i className="bar k-advisor" />{t("hr3.tl.side")}</span>{gaps.length > 0 && <span><em className="gap" />{t("hr3.tl.gap")}</span>}</div>
    </div>
  );
}

function Skills({ skills }: { skills: CvSkillR[] }) {
  const { t, fmt } = useI18n();
  return (
    <div className="hx-cvskills">
      {LEVELS.map((lv) => {
        const xs = skills.filter((s) => s.level === lv);
        if (!xs.length) return null;
        return (
          <div key={lv}>
            <h3>{t(("hr3.lv." + lv) as DictKey)} <span className="count">{fmt(xs.length)}</span></h3>
            <ul>
              {xs.map((s) => (
                <li key={s.name} title={s.evidence || undefined}>
                  <span className="nm">{s.name}</span>
                  {s.years ? <span className="yr">{t("hr3.yrs", { n: fmt(s.years) })}</span> : null}
                  <span className="lv" aria-label={t(("hr3.lv." + lv) as DictKey)}>{[1, 2, 3].map((k) => <i key={k} className={k <= LV_N[lv] ? "on" : ""} />)}</span>
                </li>
              ))}
            </ul>
          </div>
        );
      })}
    </div>
  );
}

function Claims({ claims, ix }: { claims: CvClaimR[]; ix: SrcIndex }) {
  const { t, fmt } = useI18n();
  const n = claims.filter((c) => c.status === "confirmed").length;
  return (
    <>
      <div className="hx-claimbar" aria-hidden="true"><i style={{ width: (claims.length ? (n / claims.length) * 100 : 0) + "%" }} /></div>
      <p className="hp-lead">{t("hr3.claims.sum", { n: fmt(n), m: fmt(claims.length) })}</p>
      <ul className="hx-claims">
        {claims.map((c, i) => (
          <li key={i} className={c.status === "confirmed" ? "ok" : "no"}>
            <span className="st">{c.status === "confirmed" ? Icon.met : Icon.unc}</span>
            <span className="tx">{c.text}{c.org ? <small> · {c.org}</small> : null}</span>
            <span className="rs">{c.status === "confirmed" ? <>{t("hr3.claims.ok")} <SrcChips ix={ix} factIds={c.fact_ids} /></> : t("hr3.claims.no")}</span>
          </li>
        ))}
      </ul>
    </>
  );
}

/** Report tab. */
export function CvAnalysis({ rv, ix }: { rv: CvReview | null | undefined; ix: SrcIndex }) {
  const { t, fmt } = useI18n();
  const dur = useDur();
  if (!rv) return <div className="hp-card"><h2>{t("hr3.tab")}</h2><p className="hp-lead">{t("hr3.none")}</p></div>;
  const tl = rv.timeline, ins = rv.insights, st = tl?.stats ? { ...tl.stats, overlaps: preciseOverlaps(tl.roles) } : undefined;
  const claims = rv.claims?.length ? rv.claims : ins?.claims ?? [];
  return (
    <>
      <div className="hp-card hx-cvhead">
        <div className="top">
          <div>
            <span className="eyebrow">{t("hr3.eyebrow")}</span>
            <h2>{tl?.headline || t("hr3.tab")}{ins && <span className={"hx-sen s-" + ins.seniority}>{t(("hr3.sen." + ins.seniority) as DictKey)}</span>}</h2>
            {ins?.summary && <p className="sum">{ins.summary}</p>}
          </div>
        </div>
        <div className="hx-cvstats">
          {st && <Stat v={fmt(st.years)} l={t("hr3.st.years")} />}
          {st && <Stat v={fmt(st.roles)} l={t("hr3.st.roles")} />}
          {st && <Stat v={dur(st.avg_tenure_months)} l={t("hr3.st.tenure")} />}
          {st && <Stat v={fmt(st.gaps.length)} l={t("hr3.st.gaps")} tone={st.gaps.length ? "warn" : undefined} />}
          {ins && <Stat v={fmt(ins.achievements.length)} l={t("hr3.st.results")} tone={ins.achievements.length ? "ok" : undefined} />}
          {claims.length > 0 && <Stat v={`${fmt(claims.filter((c) => c.status === "confirmed").length)}/${fmt(claims.length)}`} l={t("hr3.st.claims")} />}
        </div>
        <p className="hp-foot">{t("hr3.self", { w: fmt(rv.read.words) })}{rv.read.years ? " · " + t("hr3.covers", { a: rv.read.years[0], b: rv.read.years[1] }) : ""}</p>
      </div>

      {tl && tl.roles.length > 0 && (
        <div className="hp-card">
          <h2>{t("hr3.tl.h")} <span className="count">{t("hr3.tl.n", { n: fmt(tl.roles.length), y: fmt(tl.stats.years) })}</span></h2>
          <Gantt tl={tl} />
          {st && (st.gaps.length > 0 || st.short_stints > 0 || st.overlaps > 0) && (
            <ul className="hx-flags">
              {st.gaps.map((g, i) => <li key={i}>{Icon.conf}<span>{t("hr3.gap", { a: g.from, b: g.to, d: dur(g.months) })}</span></li>)}
              {st.short_stints > 0 && <li>{Icon.conf}<span>{t("hr3.short", { n: fmt(st.short_stints) })}</span></li>}
              {st.overlaps > 0 && <li>{Icon.conf}<span>{t("hr3.overlap", { n: fmt(st.overlaps) })}</span></li>}
            </ul>
          )}
          <ol className="hx-roles">
            {tl.roles.map((r, i) => (
              <li key={i}>
                <div className="h"><b>{r.title || "–"}</b><span className="org">{r.org}</span><span className="d">{r.start || "?"} – {r.end || "?"} · {dur(r.months)}</span></div>
                {(r.team_size || r.location) && <div className="m">{r.team_size ? t("hr3.team", { n: fmt(r.team_size) }) : null}{r.team_size && r.location ? " · " : ""}{r.location}</div>}
                {r.highlights.length > 0 && <ul>{r.highlights.map((h, j) => <li key={j}>{h}</li>)}</ul>}
              </li>
            ))}
          </ol>
        </div>
      )}

      {ins && ins.achievements.length > 0 && (
        <div className="hp-card">
          <h2>{t("hr3.ach.h")} <span className="count">{fmt(ins.achievements.length)}</span></h2>
          <div className="hx-achs">{ins.achievements.map((a, i) => <div key={i} className="hx-ach"><b>{a.metric || "✓"}</b><p>{a.text}</p>{a.org && <small>{a.org}</small>}</div>)}</div>
        </div>
      )}

      {ins && ins.skills.length > 0 && <div className="hp-card"><h2>{t("hr3.sk.h")} <span className="count">{fmt(ins.skills.length)}</span></h2><Skills skills={ins.skills} /></div>}

      {ins && (ins.strengths.length > 0 || ins.leadership.length > 0 || ins.concerns.length > 0) && (
        <div className="hp-duo">
          <div className="hp-card hx-cvlist ok">
            <h2>{t("hr3.str.h")}</h2>
            <ul>{[...ins.strengths, ...ins.leadership].map((x, i) => <li key={i}>{x}</li>)}</ul>
          </div>
          <div className="hp-card hx-cvlist warn">
            <h2>{t("hr3.con.h")}</h2>
            {ins.concerns.length ? <ul>{ins.concerns.map((x, i) => <li key={i}>{x}</li>)}</ul> : <p className="hp-lead">{t("hr3.con.none")}</p>}
          </div>
        </div>
      )}

      {claims.length > 0 && <div className="hp-card"><h2>{t("hr3.claims.h")}</h2><Claims claims={claims} ix={ix} /></div>}

      {((tl?.education.length ?? 0) > 0 || (tl?.certifications.length ?? 0) > 0 || (tl?.languages.length ?? 0) > 0 || (ins?.questions.length ?? 0) > 0) && (
        <div className="hp-duo">
          {tl && (tl.education.length > 0 || tl.certifications.length > 0 || tl.languages.length > 0) && (
            <div className="hp-card">
              <h2>{t("hr3.edu.h")}</h2>
              <ul className="hp-edu">{tl.education.map((e, i) => <li key={i}><b>{[e.degree, e.field].filter(Boolean).join(", ") || e.institution}</b><span className="muted-sm">{e.institution}{e.start || e.end ? ` · ${e.start || "?"} – ${e.end || "?"}` : ""}</span></li>)}</ul>
              {tl.certifications.length > 0 && <><h3 className="hx-sub">{t("hr3.cert")}</h3><div className="hp-chips">{tl.certifications.map((c) => <span key={c} className="hp-sk s">{c}</span>)}</div></>}
              {tl.languages.length > 0 && <><h3 className="hx-sub">{t("hr3.lang")}</h3><div className="hp-chips">{tl.languages.map((c) => <span key={c} className="hp-sk s">{c}</span>)}</div></>}
            </div>
          )}
          {ins && ins.questions.length > 0 && (
            <div className="hp-card">
              <h2>{t("hr3.q.h")}</h2>
              <ol className="hx-qs">{ins.questions.map((q, i) => <li key={i}>{q}</li>)}</ol>
            </div>
          )}
        </div>
      )}
    </>
  );
}

/** One step of the live panel (module level: a component defined inside the panel would remount on every
    once-a-second re-render of the run screen and restart its fade-in). */
function Step({ done, busy, label, sub, children }: { done: boolean; busy: boolean; label: string; sub?: string; children?: ReactNode }) {
  return (
    <li className={done ? "done" : busy ? "now" : "todo"}>
      <span className="dot" aria-hidden="true">{done ? Icon.met : busy ? <i /> : null}</span>
      <div><b>{label}</b>{sub && <small>{sub}</small>}{children}</div>
    </li>
  );
}

/** Live panel inside a person card on the run screen: four steps that tick off as each part lands. */
export function CvLivePanel({ cv, status }: { cv: CvLive | null | undefined; status: string }) {
  const { t, fmt } = useI18n();
  if (!cv?.read) return null;
  const r = cv.read, tl = cv.timeline, ins = cv.insights, cl = cv.claims;
  const busy = status === "working" || status === "waiting";
  return (
    <section className="hx-cvlive" aria-label={t("hr3.live.h")} aria-live="polite">
      <h3>{t("hr3.live.h")}</h3>
      <ol>
        <Step busy={busy} done label={t("hr3.live.read")} sub={t("hr3.live.read.s", { w: fmt(r.words), s: fmt(r.sections.length) }) + (r.years ? " · " + r.years[0] + "–" + r.years[1] : "")} />
        <Step busy={busy} done={!!tl} label={t("hr3.live.tl")} sub={tl ? t("hr3.live.tl.s", { n: fmt(tl.stats.roles), y: fmt(tl.stats.years), g: fmt(tl.stats.gaps.length) }) : t("hr3.live.wait")}>
          {tl && <ul className="mini">{tl.roles.slice(0, 3).map((x, i) => <li key={i}>{x.title || "–"} · <span>{x.org}</span></li>)}</ul>}
        </Step>
        <Step busy={busy} done={!!ins} label={t("hr3.live.ins")} sub={ins ? t("hr3.live.ins.s", { k: fmt(ins.skills.length), a: fmt(ins.achievements.length) }) : t("hr3.live.wait")}>
          {ins && ins.skills.length > 0 && <span className="chips">{ins.skills.slice(0, 6).map((s) => <i key={s.name} className={"l-" + s.level}>{s.name}</i>)}</span>}
        </Step>
        <Step busy={busy} done={!!cl} label={t("hr3.live.cl")} sub={cl ? t("hr3.claims.sum", { n: fmt(cl.filter((c) => c.status === "confirmed").length), m: fmt(cl.length) }) : t("hr3.live.cl.wait")} />
      </ol>
    </section>
  );
}
