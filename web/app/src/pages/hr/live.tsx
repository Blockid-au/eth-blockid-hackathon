/* Live run screen (docs/PLAN-HR-V2.md §1–2): progress ring, ETA, current action, step timeline, live feed and
   person cards that fill in as partial results arrive. Works with the `progress` block of GET /v1/hr/teams/{id};
   older servers without it get a progress view derived from `steps`. */
import { useRef, useState } from "react";
import { Link } from "react-router-dom";
import { useI18n } from "../../i18n";
import type { DictKey } from "../../dict";
import { errText } from "../../auth";
import { api, ApiError, type HrFeedItem, type HrPartialPerson, type HrPhase, type HrProgress, type Team } from "../../api";
import { useNow } from "../../lib/hooks";
import { hostOf, initials } from "./common";
import { Icon } from "./evidence";
import { EthCtas } from "./ethCta";

const STEP_PHASE: Record<string, HrPhase> = {
  queued: "queued", start: "queued", fetch: "reading", read: "reading", search: "searching", extract: "extracting",
  score: "scoring", team: "scoring", done: "done", failed: "failed",
};
export const TIMELINE: HrPhase[] = ["reading", "searching", "extracting", "scoring", "done"];
const ORDER: HrPhase[] = ["queued", ...TIMELINE];
export const STALL_MS = 90_000;

/** The server's progress block, or one derived from the step log. */
export function progressOf(team: Team): HrProgress {
  if (team.progress) return team.progress;
  const steps = team.steps ?? [];
  const n = team.people.length || 1;
  const total = 2 + 4 * n + (team.mode === "person" ? 0 : 1);
  const last = steps[steps.length - 1];
  const phase: HrPhase = team.status === "failed" ? "failed" : team.status === "done" ? "done" : (last && STEP_PHASE[last.step]) || "queued";
  const people: HrPartialPerson[] = team.people.map((p) => {
    const mine = steps.filter((s) => s.person === p.full_name);
    const done = mine.some((s) => s.step === "score");
    return { id: p.id, name: p.full_name, status: done ? "done" : mine.length ? "working" : "waiting", facts: [] };
  });
  return {
    phase,
    pct: team.status === "done" ? 100 : Math.min(99, Math.round((steps.length / total) * 100)),
    eta_s: null,
    started_at: steps[0]?.at ?? null,
    updated_at: team.updated_at ?? last?.at ?? null,
    current: { person: last?.person ?? null, step: last?.step ?? "queued", detail: last?.msg ?? "" },
    feed: steps.map((s) => ({ at: s.at, level: s.step === "failed" ? "warn" : s.step === "score" || s.step === "done" ? "found" : "info", msg: s.msg, person: s.person ?? null })),
    counters: { pages_read: 0, searches: steps.filter((s) => s.step === "search").length, facts_verified: 0, facts_unconfirmed: 0, people_done: people.filter((p) => p.status === "done").length, people_total: team.people.length },
    partial: { people },
  };
}

const ms = (s?: string | null) => (s ? +new Date(s) : NaN);

/** Seconds left: the server's estimate counted down since the last heartbeat, else a straight-line guess. */
function secondsLeft(p: HrProgress, now: number): number | null {
  const up = ms(p.updated_at);
  if (p.eta_s != null) return Math.max(0, p.eta_s - (Number.isFinite(up) ? Math.max(0, (now - up) / 1000) : 0));
  const st = ms(p.started_at);
  if (!Number.isFinite(st) || p.pct < 5) return null;
  const el = (now - st) / 1000;
  return Math.max(0, (el * (100 - p.pct)) / p.pct);
}

function ProgressRing({ pct, label, size = 132 }: { pct: number; label: string; size?: number }) {
  const r = size / 2 - 9, C = 2 * Math.PI * r, v = Math.max(0, Math.min(100, pct));
  return (
    <div className="hx-ring" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(v)} aria-label={label} style={{ width: size, height: size }}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} aria-hidden="true">
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="var(--hx-ring-track)" strokeWidth={12} />
        <circle className="arc" cx={size / 2} cy={size / 2} r={r} fill="none" stroke="url(#hxRingGrad)" strokeWidth={12} strokeLinecap="round"
          strokeDasharray={`${(v / 100) * C} ${C}`} transform={`rotate(-90 ${size / 2} ${size / 2})`} />
        <defs><linearGradient id="hxRingGrad" x1="0" y1="0" x2="1" y2="1"><stop offset="0%" stopColor="var(--accent)" /><stop offset="100%" stopColor="var(--ok)" /></linearGradient></defs>
      </svg>
      <span className="v"><b className="num">{Math.round(v)}</b><small>%</small></span>
    </div>
  );
}

function FeedIcon({ level }: { level: HrFeedItem["level"] }) {
  if (level === "found") return <span className="fi found">{Icon.ok}</span>;
  if (level === "warn") return <span className="fi warn">{Icon.conf}</span>;
  return <span className="fi info" aria-hidden="true"><i /></span>;
}

function PersonLive({ p, role }: { p: HrPartialPerson; role?: string }) {
  const { t, fmt } = useI18n();
  const facts = p.facts ?? [];
  return (
    <article className={"hx-pl " + p.status} aria-label={p.name}>
      <header>
        <span className="hx-av" aria-hidden="true">{initials(p.name)}</span>
        <span className="nm"><b>{p.name}</b>{role && <small>{role}</small>}</span>
        <span className={"hx-st " + p.status}>{p.status === "working" && <i aria-hidden="true" />}{t(("hr2.run.ps." + p.status) as DictKey)}</span>
      </header>
      {(p.score != null || p.fit != null) && (
        <div className="hx-pl-sc">
          {p.fit != null && <span><small>{t("hr2.run.fit")}</small><b className="num">{fmt(Math.round(p.fit))}</b></span>}
          {p.score != null && <span><small>{t("hr2.run.quality")}</small><b className="num">{fmt(Math.round(p.score))}</b></span>}
        </div>
      )}
      {facts.length > 0 ? (
        <ul className="hx-pl-facts">
          {facts.slice(0, 3).map((f) => (
            <li key={f.id}><span className="ok">{Icon.ok}</span><span>{f.text}{f.url && <> · <a href={f.url} target="_blank" rel="noopener noreferrer nofollow">{hostOf(f.url)}</a></>}</span></li>
          ))}
          {facts.length > 3 && <li className="more">{t("hr2.run.more", { n: facts.length - 3 })}</li>}
        </ul>
      ) : (
        <p className="hx-pl-empty">{t(p.status === "waiting" ? "hr2.run.p.waiting" : p.status === "failed" ? "hr2.run.p.failed" : p.status === "done" ? "hr2.run.p.nofacts" : "hr2.run.p.working")}</p>
      )}
      {p.status === "working" && <div className="hx-shimmer" aria-hidden="true"><i /><i /></div>}
    </article>
  );
}

/** Full-page live view of a running / stalled / failed report. */
export function LiveRun({ team, onUpdate }: { team: Team; onUpdate: (t: Team) => void }) {
  const { t, fmt } = useI18n();
  const now = useNow(1000);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const lastPhase = useRef<HrPhase>("queued");
  const p = progressOf(team);
  const failed = team.status === "failed" || p.phase === "failed";
  const up = ms(p.updated_at);
  const stalled = !failed && (p.phase === "stalled" || (team.status === "running" && Number.isFinite(up) && now - up > STALL_MS));
  const live = ORDER.includes(p.phase) && !failed;
  if (live) lastPhase.current = p.phase;
  const stepPhase = STEP_PHASE[p.current.step];
  const cur: HrPhase = live ? p.phase : lastPhase.current !== "queued" ? lastPhase.current : stepPhase && TIMELINE.includes(stepPhase) && stepPhase !== "done" ? stepPhase : "reading";
  const ci = ORDER.indexOf(cur);
  const left = secondsLeft(p, now);
  const eta = failed ? "" : stalled ? t("hr2.run.eta.stalled") : cur === "queued" ? t("hr2.run.eta.queued") : left == null ? t("hr2.run.eta.calc") : left < 45 ? t("hr2.run.eta.lt1") : t("hr2.run.eta.min", { n: Math.max(1, Math.round(left / 60)) });
  const t0 = ms(p.started_at ?? p.feed[0]?.at);
  const when = (at: string) => { const x = ms(at); if (!Number.isFinite(t0) || !Number.isFinite(x) || x < t0) return ""; const s = Math.round((x - t0) / 1000); return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`; };
  const feed = [...(p.feed ?? [])].reverse();
  const roles = new Map(team.people.map((x) => [x.id, x.role] as const));
  const partial = p.partial?.people?.length ? p.partial.people : team.people.map((x) => ({ id: x.id, name: x.full_name, status: "waiting" as const, facts: [] }));
  const c = p.counters ?? { pages_read: 0, searches: 0, facts_verified: 0, facts_unconfirmed: 0, people_done: 0, people_total: team.people.length };
  const stepWord = (k: string) => { const key = ("hr.r.step." + k) as DictKey; const s = t(key); return s === key ? k : s; };
  const stepTxt = stepWord(p.current.step);
  const detail = p.current.detail && p.current.detail !== stepTxt ? p.current.detail : "";
  const tg = team.target;
  const tgName = tg?.type === "role" ? [tg.title, tg.company].filter(Boolean).join(" · ") : tg?.company || tg?.ticker || (tg?.website ? hostOf(tg.website) : "");

  const retry = async () => {
    setErr(""); setBusy(true);
    try { onUpdate(await api.hrRun(team.id)); } catch (x) { setErr(x instanceof ApiError && x.status === 429 ? t("hr.new.limit") : errText(x, t)); } finally { setBusy(false); }
  };

  return (
    <div className="wrap hp-page hx-run">
      <nav className="crumbs" aria-label={t("crumb.label")}><Link to="/me">{t("hr.nav.me")}</Link><span aria-hidden="true" className="sep">›</span><b>{team.name}</b></nav>
      <section className={"hx-runhead" + (failed ? " failed" : stalled ? " stalled" : "")} aria-labelledby="run-h">
        <ProgressRing pct={p.pct} label={t("hr2.run.ring", { p: fmt(Math.round(p.pct)) })} />
        <div className="hx-runtxt">
          <span className="eyebrow">{t(team.mode === "person" ? "hr.pr.eyebrow" : "hr.r.eyebrow")}{tgName ? " · " + t("hr.pr.for", { n: tgName }) : ""}</span>
          <h1 id="run-h">{team.name}</h1>
          <p className="hx-now" aria-live="polite">
            {!failed && !stalled && <span className="pulse" aria-hidden="true" />}
            {failed ? t("hr2.run.cur.failed") : cur === "queued" ? t("hr2.run.cur.queued") : stalled ? t("hr2.run.cur.stalled") : (
              <>{p.current.person && <b>{p.current.person} · </b>}{stepTxt}{detail && <span className="dt"> — {detail}</span>}</>
            )}
          </p>
          {eta && <p className="hx-eta">{eta}</p>}
          <dl className="hx-counters">
            <div><dt>{t("hr2.run.c.people")}</dt><dd className="num">{fmt(c.people_done)}/{fmt(c.people_total || team.people.length)}</dd></div>
            <div><dt>{t("hr2.run.c.pages")}</dt><dd className="num">{fmt(c.pages_read)}</dd></div>
            <div><dt>{t("hr2.run.c.searches")}</dt><dd className="num">{fmt(c.searches)}</dd></div>
            <div><dt>{t("hr2.run.c.facts")}</dt><dd className="num ok">{fmt(c.facts_verified)}</dd></div>
            <div><dt>{t("hr2.run.c.unconf")}</dt><dd className="num warn">{fmt(c.facts_unconfirmed)}</dd></div>
          </dl>
        </div>
      </section>

      {stalled && (
        <div className="hx-alert warn" role="status">
          {Icon.conf}
          <div><b>{t("hr2.run.stalled.h")}</b><p>{t("hr2.run.stalled.p")}</p></div>
        </div>
      )}
      {failed && (
        <div className="hx-alert bad" role="alert">
          {Icon.conf}
          <div>
            <b>{t("hr2.run.failed.h")}</b>
            <p>{team.error ? t("hr2.run.failed.why", { e: team.error.slice(0, 240) }) : t("hr2.run.failed.p")}</p>
            <div className="row" style={{ marginTop: 10 }}>
              {team.can_edit ? (
                <button className="btn" type="button" disabled={busy} onClick={retry}>{busy ? <span className="spinner" aria-hidden="true" /> : null}{t("hr.r.retry")}</button>
              ) : <span className="muted-sm">{t("hr2.run.failed.owner")}</span>}
              <Link className="btn ghost" to="/new/person">{t("hr.nav.person")}</Link>
              {err && <span className="err" role="alert">{err}</span>}
            </div>
          </div>
        </div>
      )}

      <ol className="hx-timeline" aria-label={t("hr.r.steps")}>
        {TIMELINE.map((ph, i) => {
          const idx = ORDER.indexOf(ph);
          const st = idx < ci ? "done" : idx > ci ? "todo" : failed ? "fail" : ph === "done" ? "done" : "now";
          return (
            <li key={ph} className={st} aria-current={st === "now" ? "step" : undefined}>
              <span className="dot" aria-hidden="true">{st === "done" ? Icon.met : st === "fail" ? Icon.x : i + 1}</span>
              <span className="lb">{t(("hr2.run.t." + ph) as DictKey)}<small className="sr-only"> · {t(("hr2.run.s." + st) as DictKey)}</small></span>
            </li>
          );
        })}
      </ol>

      <div className="hx-rungrid">
        <section className="hx-feedcard" aria-labelledby="feed-h">
          <h2 id="feed-h">{t("hr2.run.feed")} <span className="count">{fmt(feed.length)}</span></h2>
          {feed.length === 0 ? <p className="hp-lead">{t("hr.r.waiting")}</p> : (
            <ol className="hx-feed" aria-live="polite" aria-relevant="additions">
              {feed.map((f, i) => (
                <li key={f.at + i + f.msg} className={f.level + (i === 0 && !failed ? " new" : "")}>
                  <FeedIcon level={f.level} />
                  <span className="msg">
                    {f.person && <b className="who">{f.person}</b>}
                    <span>{f.msg}</span>
                    {f.source && <a href={f.source} target="_blank" rel="noopener noreferrer nofollow" className="src">{hostOf(f.source)} ↗</a>}
                  </span>
                  <time dateTime={f.at}>{when(f.at)}</time>
                </li>
              ))}
            </ol>
          )}
        </section>
        <section className="hx-peoplecard" aria-labelledby="ppl-h">
          <h2 id="ppl-h">{t(team.mode === "person" ? "hr2.run.person" : "hr2.run.people")}</h2>
          <div className="hx-pls">{partial.map((x) => <PersonLive key={x.id} p={x} role={roles.get(x.id)} />)}</div>
          <div className="hx-leave">
            {Icon.shield}
            <p><b>{t("hr2.run.leave.h")}</b> {t("hr2.run.leave.p")} <Link to="/me">{t("hr.nav.me")} →</Link></p>
          </div>
        </section>
      </div>
      {tg?.type === "business" && <EthCtas website={tg.website ?? team.website} valuationId={tg.valuation_id ?? team.valuation_id} name={tg.company ?? team.name} />}
      {team.mode === "team" && !tg && <EthCtas website={team.website} valuationId={team.valuation_id} name={team.name} />}
    </div>
  );
}
