/* Fit tab (was "Requirements"; docs/PLAN-HR-V3.md §2, §3): one report can hold several lenses — the business, a JD
   and the role the person holds now. Per lens: verdict, Claimed vs Verified fit, relevant years, knockouts, the
   requirement matrix with its evidence level, the alternative-role hint, risks and interview questions.
   hr-1 reports have only `card.fit`; that shows as one lens without the hr-2 parts. */
import { useEffect, useState, type ReactNode } from "react";
import { useSearchParams } from "react-router-dom";
import { useI18n } from "../../i18n";
import type { DictKey } from "../../dict";
import type { FitLens, FitRequirement, HrFlagged, PersonCard, PersonFit, Team } from "../../api";
import { Icon, SrcChips, type SrcIndex } from "./evidence";
import { claimGap, fitsOf, fitVerdict, primaryLens, reqEvidence, yearsGauge } from "./v3";
import { useTx, VerdictBadge } from "./verify";
import "./v3.css";

const EVC: Record<ReturnType<typeof reqEvidence>, [string, ReactNode]> = {
  verified: ["v", Icon.ok], cv_only: ["s", Icon.self], contradicted: ["c", Icon.conf], none: ["n", Icon.none],
};
/** Evidence level of a requirement: verified · CV only · conflict · none. */
export function ReqEvidence({ r }: { r: FitRequirement }) {
  const { t } = useI18n();
  const e = reqEvidence(r);
  return <span className={"hp-ev " + EVC[e][0]} title={t(("hv.ev." + e + ".d") as DictKey)}>{EVC[e][1]}{t(("hv.ev." + e) as DictKey)}</span>;
}

/** Requirement matrix of one fit lens (the v2 table with the hr-2 evidence level). */
export function ReqMatrix({ fit, ix, hasTarget }: { fit: PersonFit | null | undefined; ix: SrcIndex; hasTarget: boolean }) {
  const { t } = useI18n();
  const reqs = fit?.requirements ?? [];
  if (!reqs.length) return <div className="hp-card"><p className="hp-lead">{t(hasTarget ? "hr.pr.req.none" : "hr.pr.req.notarget")}</p></div>;
  const RES: Record<string, [string, ReactNode, DictKey]> = {
    matched: ["met", Icon.met, "hr.pr.res.met"], partial: ["part", Icon.part, "hr.pr.res.part"], missing: ["miss", Icon.x, "hr.pr.res.nf"], unverified: ["unv", Icon.unc, "hr.pr.res.unv"],
  };
  const hasPrio = reqs.some((r) => r.must_have === false) && reqs.some((r) => r.must_have);
  const groups: [DictKey, typeof reqs][] = hasPrio ? [["hr.pr.req.must", reqs.filter((r) => r.must_have)], ["hr.pr.req.nice", reqs.filter((r) => !r.must_have)]] : [["hr.pr.reqs", reqs]];
  const count = (list: typeof reqs) => (["matched", "partial", "missing", "unverified"] as const).map((s) => [s, list.filter((r) => r.status === s).length] as const).filter(([, n]) => n > 0);
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
        <table className="hp-req hv-req">
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
                    <td><ReqEvidence r={r} /></td>
                    <td className="srccell"><SrcChips ix={ix} factIds={r.fact_ids} /></td>
                  </tr>
                );
              }),
            ])}
          </tbody>
        </table>
      </div>
      <p className="hp-foot">{t("hv.ev.legend")}</p>
    </div>
  );
}

function ScoreBars({ fit }: { fit: PersonFit }) {
  const { t, fmt } = useI18n();
  if (fit.claimed_score == null) return null;
  const ver = fit.verified_score ?? fit.score;
  const gap = claimGap(fit);
  const rows: [DictKey, number, string][] = [["hv.fit.claimed", fit.claimed_score, "cl"], ["hv.fit.verified", ver, "vf"]];
  return (
    <div className="hv-twobars">
      {rows.map(([k, v, c]) => (
        <div key={k} className={"hv-2b " + c}>
          <span className="l">{t(k)}</span>
          <span className="t" role="img" aria-label={`${t(k)} ${fmt(Math.round(v))}/100`}><i style={{ width: Math.max(0, Math.min(100, v)) + "%" }} />{fit.cap != null && <em style={{ left: fit.cap + "%" }} title={t("hv.fit.cap.tip", { c: fit.cap })} />}</span>
          <b className="num">{fmt(Math.round(v))}</b>
        </div>
      ))}
      {gap > 0 && <p className="hv-gap">{Icon.conf}<span>{t("hv.fit.gap", { n: fmt(gap) })}</span></p>}
    </div>
  );
}

function RelevantYears({ fit }: { fit: PersonFit }) {
  const { t, fmt } = useI18n();
  const tx = useTx();
  const r = fit.relevant;
  if (!r) return null;
  const g = yearsGauge(r.years, r.min_years);
  const short = r.min_years != null && r.years < r.min_years;
  return (
    <div className="hp-card">
      <h2>{t("hv.yrs.h")}</h2>
      <div className={"hv-gauge" + (short ? " short" : "")} role="img" aria-label={r.min_years != null ? t("hv.yrs.vs", { y: fmt(r.years, 1), m: fmt(r.min_years) }) : t("hv.yrs.only", { y: fmt(r.years, 1) })}>
        <span className="t"><i style={{ width: g.you + "%" }} />{g.need != null && <em style={{ left: g.need + "%" }}><small>{t("hv.yrs.min", { m: fmt(r.min_years!) })}</small></em>}</span>
      </div>
      <p className="hp-lead"><b className="num">{fmt(r.years, 1)}</b> {r.min_years != null ? t("hv.yrs.vs.p", { m: fmt(r.min_years) }) : t("hv.yrs.only.p")}{short ? " · " + t("hv.yrs.short") : ""}</p>
      {(r.roles?.length ?? 0) > 0 && (
        <details className="hv-roles">
          <summary>{t("hv.yrs.roles", { n: fmt(r.roles!.length) })}</summary>
          <ul>
            {r.roles!.map((x, i) => (
              <li key={i}>
                <span className={"hv-rel r-" + x.relevance}>{tx("hv.rel." + x.relevance, x.relevance)}</span>
                <span><b>{x.title || "–"}</b> · {x.org}{x.months ? <small> · {t("hv.yrs.months", { n: fmt(x.months) })}</small> : null}{x.reason && <small className="d">{x.reason}</small>}</span>
              </li>
            ))}
          </ul>
        </details>
      )}
      <p className="hp-foot">{t("hv.yrs.foot")}</p>
    </div>
  );
}

function Knockouts({ fit }: { fit: PersonFit }) {
  const { t } = useI18n();
  const ks = fit.knockouts ?? [];
  if (!ks.length) return null;
  const byText = new Map((fit.requirements ?? []).map((r) => [r.requirement.trim().toLowerCase(), r] as const));
  return (
    <div className="hp-card hv-knock">
      <h2>{t("hv.ko.h")}</h2>
      <p className="hp-lead">{t("hv.ko.p")}</p>
      <ul>
        {ks.map((k, i) => {
          const r = byText.get(k.trim().toLowerCase());
          const st = r ? (r.status === "matched" ? "met" : r.status === "partial" ? "part" : "miss") : "unk";
          return <li key={i} className={st}><span className="ic" aria-hidden="true">{st === "met" ? Icon.met : st === "part" ? Icon.part : st === "miss" ? Icon.x : Icon.unc}</span><span>{k}</span>{r && <small>{t(st === "met" ? "hr.pr.res.met" : st === "part" ? "hr.pr.res.part" : "hr.pr.res.nf")}</small>}</li>;
        })}
      </ul>
    </div>
  );
}

export function FlaggedNote({ items }: { items: HrFlagged[] | null | undefined }) {
  const { t } = useI18n();
  if (!items?.length) return null;
  return (
    <div className="hv-flagged" role="note">
      {Icon.conf}
      <div>
        <b>{t("hv.flag.h")}</b>
        <ul>{items.map((f, i) => <li key={i}><q>{f.text}</q>{f.reason ? <small> — {f.reason}</small> : null}</li>)}</ul>
      </div>
    </div>
  );
}

export function FitTab({ card, team, ix }: { card: PersonCard; team: Team; ix: SrcIndex }) {
  const { t, fmt } = useI18n();
  const [params] = useSearchParams();
  const lenses = fitsOf(card);
  const want = params.get("lens") as FitLens | null;
  const pick = () => (want && lenses.some(([l]) => l === want) ? want : primaryLens(card));
  const [lens, setLens] = useState<FitLens | null>(pick);
  useEffect(() => { if (want && lenses.some(([l]) => l === want)) setLens(want); }, [want]);
  if (!lenses.length) return <ReqMatrix fit={null} ix={ix} hasTarget={false} />;
  const [cur, fit] = lenses.find(([l]) => l === lens) ?? lenses[0];
  const v = fitVerdict(fit);
  const tg = team.target;
  const flagged = cur === "jd" && tg?.type === "role" ? tg.flagged : null;
  const hr2 = fit.verdict != null || fit.claimed_score != null || fit.lens != null;
  const risks = fit.risks ?? [], qs = fit.interview_questions ?? [];
  return (
    <>
      {lenses.length > 1 && (
        <div className="hv-lenses" role="group" aria-label={t("hv.lens.aria")}>
          {lenses.map(([l, f]) => (
            <button key={l} type="button" aria-pressed={l === cur} onClick={() => setLens(l)}>
              <span>{t(("hv.lens." + l) as DictKey)}</span><b className="num">{fmt(Math.round(f.score))}</b>
            </button>
          ))}
        </div>
      )}
      <section className={"hp-card hv-fithead v-" + v} aria-labelledby="hv-fit-h">
        <div className="top">
          <div>
            <span className="eyebrow">{t(("hv.lens." + cur + ".long") as DictKey)}</span>
            <h2 id="hv-fit-h">{fit.title || fit.label || t(("hv.lens." + cur) as DictKey)}</h2>
            {fit.template && <p className="hp-lead">{fit.template.stage_band ? t("hv.tpl", { r: fit.template.label, s: fit.template.stage_band }) : t("hv.tpl.nostage", { r: fit.template.label })}</p>}
          </div>
          <VerdictBadge verdict={v} score={fit.score} />
        </div>
        {!hr2 && <p className="hp-lead">{t("hv.fit.v1")}</p>}
        <ScoreBars fit={fit} />
        {fit.cap != null && <p className="hv-cap">{Icon.conf}<span>{t("hv.fit.cap", { c: fmt(fit.cap) })}</span></p>}
        <p className="hp-foot">{t("hv.fit.scale")}</p>
      </section>
      <FlaggedNote items={flagged} />
      {fit.alt_role && (
        <div className="hv-alt">
          <span className="ic" aria-hidden="true">{Icon.up}</span>
          <div><b>{t("hv.alt.h", { r: fit.alt_role.role, s: fmt(Math.round(fit.alt_role.score)) })}</b>{fit.alt_role.reason && <p>{fit.alt_role.reason}</p>}</div>
        </div>
      )}
      {(fit.relevant || (fit.knockouts?.length ?? 0) > 0) && (
        <div className="hp-duo">
          <RelevantYears fit={fit} />
          <Knockouts fit={fit} />
        </div>
      )}
      <ReqMatrix fit={fit} ix={ix} hasTarget />
      {(risks.length > 0 || qs.length > 0) && (
        <div className="hp-card">
          <h2>{t("hv.rq.h")}</h2>
          <div className="hp-sr">
            <div className="rk"><h3>{Icon.conf}{t("hr.pr.check")}</h3>{risks.length ? <ul>{risks.map((s, i) => <li key={i}>{s}</li>)}</ul> : <p className="muted-sm">{t("common.none")}</p>}</div>
            <div className="st"><h3>{Icon.up}{t("hv.rq.q")}</h3>{qs.length ? <ol>{qs.map((s, i) => <li key={i}>{s}</li>)}</ol> : <p className="muted-sm">{t("common.none")}</p>}</div>
          </div>
        </div>
      )}
    </>
  );
}
