/* "Founding team" card on the eth.blockid.au valuation report. The full report lives on hr.blockid.au. */
import { useEffect, useState } from "react";
import { useI18n } from "../i18n";
import type { DictKey } from "../dict";
import { api, ApiError, type TeamSummary } from "../api";
import { useAsync } from "../lib/hooks";
import { hrUrl } from "../lib/hrhost";
import "./hr.css";

const initials = (n: string) => { const w = n.trim().split(/\s+/); return ((w[0]?.[0] ?? "") + (w.length > 1 ? w[w.length - 1][0] : "")).toUpperCase() || "?"; };
const band = (x: number) => (x >= 85 ? "strong" : x >= 70 ? "good" : x >= 55 ? "partial" : x >= 40 ? "weak" : "poor");

export function TeamCard({ valuationId, teamId, summary, weight, sample = false }: { valuationId: string; teamId?: string | null; summary?: TeamSummary | null; weight?: number | null; sample?: boolean }) {
  const { t, fmt } = useI18n();
  const running = (s?: TeamSummary | null) => !!s && (s.status === "queued" || s.status === "running");
  const [live, setLive] = useState(true);
  const q = useAsync<TeamSummary | null>(() => (teamId && !sample ? api.hrTeamSummary(teamId) : Promise.resolve(summary ?? null)), [teamId, sample], teamId && live ? 5000 : null);
  useEffect(() => { const st = q.data?.status; if (st) setLive(st === "queued" || st === "running" || st === "draft"); }, [q.data?.status]);
  const s = q.data ?? summary ?? null;
  const w = weight != null ? (weight > 1 ? weight : weight * 100) : 30;
  const pct = fmt(w, w % 1 ? 1 : 0);
  const head = (
    <div className="hr-card-head">
      <div>
        <h4>{t("hr.card.h")}</h4>
        <span className="muted-sm">{t("hr.card.weight", { p: pct })}</span>
      </div>
      {s?.score != null && (
        <div className="row" style={{ gap: 10 }}>
          <span className="gradebadge" style={{ width: 36, height: 36, fontSize: "1.15rem" }} aria-label={`${t("ad.c.grade")} ${s.grade ?? ""}`}>{s.grade ?? "–"}</span>
          <span><b className="num" style={{ font: "800 1.5rem/1 var(--display)" }}>{fmt(s.score, 0)}</b><span className="muted-sm"> /100 · {t(("hr.band.team." + band(s.score)) as DictKey)}</span></span>
        </div>
      )}
    </div>
  );
  if (!teamId && !s) {
    return (
      <div className="hr-card">
        {head}
        <p className="sub" style={{ margin: 0 }}>{t("hr.card.add.p")}</p>
        <div className="row"><a className="btn sm" href={hrUrl(sample ? "/new" : `/new?valuation=${encodeURIComponent(valuationId)}`)}>{t("hr.card.add")} →</a></div>
      </div>
    );
  }
  const id = s?.id ?? teamId!;
  const denied = q.error instanceof ApiError && (q.error.status === 401 || q.error.status === 403);
  return (
    <div className="hr-card">
      {head}
      {denied && !s && <p className="note" style={{ margin: 0 }}>{t("hr.card.noaccess")}</p>}
      {running(s) && <p className="row muted-sm" style={{ margin: 0 }}><span className="spinner" aria-hidden="true" />{t("hr.card.running")}</p>}
      {s?.status === "failed" && <p className="note" style={{ margin: 0, color: "var(--bad)" }}>{t("hr.card.failed")}</p>}
      {s && s.people.length > 0 && (
        <ul className="hr-card-people">
          {s.people.map((p, i) => (
            <li key={i}>
              <span className="hr-avatar" aria-hidden="true">{initials(p.full_name)}</span>
              <a href={hrUrl(`/r/${encodeURIComponent(id)}/p/n${i + 1}`)}><b>{p.full_name}</b><small>{p.role || t(("hr.kind." + p.kind) as DictKey)}</small></a>
              <span className="num">{p.fit != null ? fmt(p.fit, 0) : p.score != null ? fmt(p.score, 0) : "–"}<small className="muted" style={{ display: "block" }}>{p.fit != null ? t("hr.card.fit") : p.score != null ? t("hr.card.quality") : ""}</small></span>
            </li>
          ))}
        </ul>
      )}
      {s && (s.strengths[0] || s.gaps[0]) && (
        <div className="cols" style={{ gap: 12 }}>
          {s.strengths[0] && <p style={{ margin: 0, fontSize: ".86rem" }}><b>{t("hr.card.top")}:</b> {s.strengths[0]}</p>}
          {s.gaps[0] && <p style={{ margin: 0, fontSize: ".86rem" }}><b>{t("hr.card.gap")}:</b> {s.gaps[0]}</p>}
        </div>
      )}
      <div className="row">
        <a className="btn sm" href={hrUrl(`/r/${encodeURIComponent(id)}`)}>{running(s) ? t("hr.card.watch") : t("hr.card.open")} ↗</a>
      </div>
    </div>
  );
}
