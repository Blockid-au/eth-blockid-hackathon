/* "Founding team" card on the eth.blockid.au valuation report (docs/PLAN-HR-V2.md §3). The full report lives on
 * hr.blockid.au. States: none (assess CTA + people found on the website) · draft · queued/running (live progress,
 * refreshed every 5 s) · done (team score, each founder's fit to THIS business) · failed (reason + retry). */
import { useEffect, useRef, useState } from "react";
import { useI18n } from "../i18n";
import type { DictKey } from "../dict";
import { api, ApiError, type HrPhase, type HrSuggestedPerson, type TeamSummary } from "../api";
import { useAsync } from "../lib/hooks";
import { hrAssessUrl, hrLink, hrPersonUrl, hrTeamUrl, hrUrl } from "../lib/hrhost";
import "./teamlink.css";

/** Fields the valuation / summary may carry beyond the typed Summary (studio/hr.py; older APIs omit them). */
export type TeamSum = TeamSummary & {
  applied?: boolean; reason?: string | null; applied_at?: string | null;
  confidence?: "high" | "medium" | "low" | null; error?: string | null;
};

const initials = (n: string) => { const w = n.trim().split(/\s+/); return ((w[0]?.[0] ?? "") + (w.length > 1 ? w[w.length - 1][0] : "")).toUpperCase() || "?"; };
export const band = (x: number) => (x >= 85 ? "strong" : x >= 70 ? "good" : x >= 55 ? "partial" : x >= 40 ? "weak" : "poor");
const ACTIVE = new Set(["queued", "running"]);
const LEADS = new Set(["founder", "cofounder"]);

/** Plain-words ETA. */
export function useEta() {
  const { t, fmt } = useI18n();
  return (s: number | null | undefined) => {
    if (s == null || !Number.isFinite(s)) return null;
    if (s <= 15) return t("hl.eta.soon");
    return t("hl.eta", { t: s < 90 ? t("hl.sec", { n: fmt(Math.round(s / 5) * 5) }) : t("hl.min", { n: fmt(Math.ceil(s / 60)) }) });
  };
}

/** A thin progress bar with a % label (indeterminate when pct is unknown). */
export function ProgressBar({ pct, label }: { pct: number | null | undefined; label: string }) {
  const { fmt } = useI18n();
  const known = pct != null && Number.isFinite(pct);
  const p = known ? Math.max(0, Math.min(100, pct!)) : 0;
  return (
    <div className="tl-prog">
      <div className={"tl-bar" + (known ? "" : " ind")} role="progressbar" aria-label={label} aria-valuemin={0} aria-valuemax={100} aria-valuenow={known ? Math.round(p) : undefined}>
        <i style={known ? { width: `${Math.max(p, 3)}%` } : undefined} />
      </div>
      {known && <b className="num">{fmt(p, 0)}%</b>}
    </div>
  );
}

function Suggestions({ valuationId, people }: { valuationId: string; people: HrSuggestedPerson[] }) {
  const { t } = useI18n();
  if (!people.length) return null;
  const shown = people.slice(0, 8);
  return (
    <div className="tl-found">
      <span className="muted-sm">{t("hl.found")}</span>
      <ul className="tl-chips">
        {shown.map((p, i) => (
          <li key={p.full_name + i}>
            <a className="tl-chip" href={hrAssessUrl({ valuationId, people: [p] })} aria-label={t("hl.found.addp", { n: p.full_name })}>
              <span><b>{p.full_name}</b>{p.role ? " · " + p.role : ""}</span><em>+ {t("hl.found.add")}</em>
            </a>
          </li>
        ))}
      </ul>
      {shown.length > 1 && <a className="tl-link" href={hrAssessUrl({ valuationId, people: shown })}>{t("hl.found.all", { n: shown.length })} →</a>}
    </div>
  );
}

export function TeamCard({ valuationId, teamId, summary, weight, sample = false, applied, onDone }: {
  valuationId: string; teamId?: string | null; summary?: TeamSum | null; weight?: number | null; sample?: boolean;
  /** the valuation's founder score came from this team report (svi basis "team_report") */
  applied?: boolean; onDone?: () => void;
}) {
  const { t, fmt, date } = useI18n();
  const eta = useEta();
  const [live, setLive] = useState(true);
  const q = useAsync<TeamSum | null>(
    () => (teamId && !sample ? api.hrTeamSummary(teamId) : Promise.resolve(summary ?? null)),
    [teamId, sample], teamId && !sample && live ? 5000 : null);
  const s: TeamSum | null = q.data ? { ...(summary ?? {}), ...q.data } as TeamSum : summary ?? null;
  const status = s?.status ?? (teamId ? "queued" : null);
  const running = !!status && ACTIVE.has(status);
  useEffect(() => { if (status) setLive(ACTIVE.has(status) || status === "draft"); }, [status]);
  // the team just finished: the valuation's score changes, so the page reloads it once
  const was = useRef(status);
  useEffect(() => { if (was.current && ACTIVE.has(was.current) && status === "done") onDone?.(); was.current = status; }, [status]); // eslint-disable-line react-hooks/exhaustive-deps
  const none = !teamId && !s;
  const sug = useAsync(() => (none && !sample ? api.hrSuggestPeople({ valuation_id: valuationId }) : Promise.resolve(null)), [none, sample, valuationId]);

  const w = weight != null ? (weight > 1 ? weight : weight * 100) : 30;
  const pctW = fmt(w, w % 1 ? 1 : 0);
  const id = s?.id ?? teamId ?? "";
  const denied = q.error instanceof ApiError && (q.error.status === 401 || q.error.status === 403);
  const phase: HrPhase | string = s?.progress?.phase ?? status ?? "queued";
  const pdone = s?.people.filter((p) => p.status === "done").length ?? 0;
  const ptotal = s?.people.length ?? 0;
  const isApplied = applied || s?.applied === true;
  const leads = (s?.people ?? []).map((p, i) => ({ p, i })).sort((a, b) => Number(LEADS.has(b.p.kind)) - Number(LEADS.has(a.p.kind)));

  const head = (
    <div className="tl-head">
      <div>
        <h4>{t("hl.h")}</h4>
        <span className="muted-sm">{t("hl.weight", { p: pctW })}</span>
      </div>
      {status === "done" && s?.score != null && (
        <div className="tl-score" aria-label={`${t("hl.score")} ${fmt(s.score, 0)}/100`}>
          <span className="gradebadge" aria-hidden="true">{s.grade ?? "–"}</span>
          <span>
            <b className="num">{fmt(s.score, 0)}</b><span className="muted-sm">/100</span>
            <small>{t(("hl.bt." + band(s.score)) as DictKey)}{s.confidence ? " · " + t("hl.conf", { c: t(("hl.conf." + s.confidence) as DictKey) }) : ""}</small>
          </span>
        </div>
      )}
    </div>
  );

  /* ---------- none: nobody assessed the founders yet ---------- */
  if (none || (denied && !s)) {
    const people = sug.data?.people ?? [];
    return (
      <section className="tl-card" aria-label={t("hl.h")}>
        {head}
        {denied ? <p className="note" style={{ margin: 0 }}>{t("hl.private")}</p> : <p className="sub" style={{ margin: 0 }}>{t("hl.none.p")}</p>}
        {!denied && <Suggestions valuationId={valuationId} people={people} />}
        <div className="tl-actions">
          {denied && id
            ? <a className="btn sm" href={hrTeamUrl(id)}>{t("hl.cta.open")} ↗</a>
            : <a className="btn sm" href={sample ? hrUrl("/new") : hrAssessUrl({ valuationId, people: people.slice(0, 8) })}>{t("hl.cta.assess")} →</a>}
        </div>
      </section>
    );
  }

  return (
    <section className="tl-card" aria-label={t("hl.h")} aria-busy={running}>
      {head}

      {status === "draft" && (
        <div className="tl-actions"><span className="muted-sm">{t("hl.st.draft")}</span><a className="btn sm" href={hrTeamUrl(id)}>{t("hl.cta.open")} ↗</a></div>
      )}

      {(running || phase === "stalled") && (
        <div className="tl-live" aria-live="polite">
          <div className="tl-liverow">
            <span className="tl-state">{phase !== "stalled" && <span className="spinner" aria-hidden="true" />}<b>{t(("hl.ph." + (["queued", "reading", "searching", "extracting", "scoring", "stalled"].includes(phase) ? phase : status === "queued" ? "queued" : "reading")) as DictKey)}</b></span>
            <span className="muted-sm">
              {[ptotal && pdone ? t("hl.pdone", { a: pdone, b: ptotal }) : null, eta(s?.progress?.eta_s)].filter(Boolean).join(" · ")}
            </span>
          </div>
          <ProgressBar pct={s?.progress?.pct ?? (status === "queued" ? 0 : null)} label={t("hl.st.running")} />
          <p className="muted-sm" style={{ margin: 0 }}>{t("hl.auto")} <a href={hrTeamUrl(id)}>{t("hl.runon")} ↗</a></p>
        </div>
      )}

      {status === "failed" && (
        <div className="tl-fail" role="alert">
          <b>{t("hl.failed")}</b>
          {(s?.error || s?.reason) && <span>{t("hl.failed.reason", { r: String(s?.error || s?.reason) })}</span>}
          <a href={hrTeamUrl(id)}>{t("hl.retry")} ↗</a>
        </div>
      )}

      {s && ptotal > 0 && s.people.some((p) => p.fit != null || p.score != null) && <p className="tl-legend">{t("hl.legend")}</p>}
      {s && ptotal > 0 && (
        <ul className="tl-people">
          {leads.map(({ p, i }) => {
            const href = p.url ? hrLink(p.url, "/r/" + encodeURIComponent(id)) : hrPersonUrl(id, p.id, i);
            const top = p.fit_matched?.[0], gap = p.fit_missing?.[0];
            return (
              <li key={i} className={p.status ? "st-" + p.status : undefined}>
                <span className="tl-av" aria-hidden="true">{initials(p.full_name)}</span>
                <div className="tl-who">
                  <a href={href} aria-label={t("hl.person.open", { n: p.full_name })}><b>{p.full_name}</b></a>
                  <small>{p.role || t(("hl.kind." + p.kind) as DictKey)}{running && p.status ? " · " + t(("hl.p." + p.status) as DictKey) : ""}</small>
                  {status === "done" && (top || gap) && (
                    <small className="tl-tg">{top && <span className="up">+ {top}</span>}{gap && <span className="dn">− {gap}</span>}</small>
                  )}
                </div>
                <div className="tl-nums">
                  {p.fit != null && <span title={t("hl.fit")}><b className="num">{fmt(p.fit, 0)}</b><small>{status === "done" ? t(("hl.bf." + band(p.fit)) as DictKey) : t("hl.fit.short")}</small></span>}
                  {p.score != null && <span className="q" title={t("hl.quality")}><b className="num">{fmt(p.score, 0)}</b><small>{t("hl.quality")}</small></span>}
                </div>
              </li>
            );
          })}
        </ul>
      )}

      {status === "done" && s && (s.strengths[0] || s.gaps[0]) && (
        <div className="tl-sg">
          {s.strengths[0] && <p><b>{t("hl.top")}:</b> {s.strengths[0]}</p>}
          {s.gaps[0] && <p><b>{t("hl.gap")}:</b> {s.gaps[0]}</p>}
        </div>
      )}

      {status === "done" && (
        <p className={"tl-applied" + (isApplied ? " ok" : "")}>
          {isApplied
            ? (s?.applied_at ? t("hl.applied.on", { d: date(s.applied_at, true) }) : t("hl.applied"))
            : s?.reason ? t("hl.notapplied", { r: s.reason }) : t("hl.notapplied.wait")}
        </p>
      )}
      {running && <p className="tl-applied">{t("hl.notapplied.wait")}</p>}

      {status !== "draft" && (
        <div className="tl-actions">
          <a className="btn sm" href={hrLink(s?.url, `/r/${encodeURIComponent(id)}`)}>{status === "done" ? t("hl.cta.full") : t("hl.cta.open")} ↗</a>
        </div>
      )}
    </section>
  );
}

/** Company workspace overview: "Team" tile (team score + link to the hr report), or a small CTA when no team report
 * is linked to the company's valuation. Hidden when the viewer cannot read the valuation. */
export function TeamTile({ valuationId, canManage }: { valuationId: string; canManage: boolean }) {
  const { t, fmt } = useI18n();
  const eta = useEta();
  const [poll, setPoll] = useState(false);
  const v = useAsync(() => api.valuation(valuationId), [valuationId]);
  const teamId = v.data?.team_id ?? v.data?.team?.id ?? null;
  const q = useAsync<TeamSum | null>(() => (teamId ? api.hrTeamSummary(teamId) : Promise.resolve(null)), [teamId], teamId && poll ? 5000 : null);
  const s: TeamSum | null = (q.data ?? v.data?.team ?? null) as TeamSum | null;
  useEffect(() => { setPoll(!!s && ACTIVE.has(s.status)); }, [s?.status]); // eslint-disable-line react-hooks/exhaustive-deps
  if (!v.data && (v.loading || !v.error)) return null;
  if (!teamId && !s) {
    if (!canManage) return null;  // (an unreadable valuation also lands here: managers still get the CTA)
    return (
      <div className="tl-tile">
        <div><small>{t("hl.co.h")} · {t("hl.co.sub")}</small><span className="muted-sm">{t("hl.co.none")}</span></div>
        <a className="btn sm" href={hrAssessUrl({ valuationId })}>{t("hl.cta.assess")} →</a>
      </div>
    );
  }
  const id = s?.id ?? teamId!;
  const running = !!s && ACTIVE.has(s.status);
  return (
    <div className="tl-tile">
      <div>
        <small>{t("hl.co.h")} · {t("hl.co.sub")}</small>
        {s?.status === "done" && s.score != null ? (
          <span className="tl-tv">
            <span className="gradebadge" aria-hidden="true">{s.grade ?? "–"}</span>
            <b>{fmt(s.score, 0)}</b><span>/100 · {t(("hl.bt." + band(s.score)) as DictKey)}{s.people.length ? " · " + t("hl.wz.people", { n: s.people.length }) : ""}</span>
          </span>
        ) : running ? (
          <span className="tl-tv" style={{ minWidth: 200 }}>
            <span>{t("hl.co.running", { p: fmt(s?.progress?.pct ?? 0, 0) })}{eta(s?.progress?.eta_s) ? " · " + eta(s?.progress?.eta_s) : ""}</span>
          </span>
        ) : s?.status === "failed" ? (
          <span className="muted-sm" style={{ color: "var(--bad)" }}>{t("hl.failed")}</span>
        ) : (
          <span className="muted-sm">{t("hl.st.draft")}</span>
        )}
        {running && <ProgressBar pct={s?.progress?.pct} label={t("hl.st.running")} />}
      </div>
      <a className="btn ghost sm" href={hrLink(s?.url, `/r/${encodeURIComponent(id)}`)}>{t("hl.cta.open")} ↗</a>
    </div>
  );
}
