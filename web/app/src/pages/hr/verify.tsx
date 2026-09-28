/* hr-2 person report parts (docs/PLAN-HR-V3.md §3): the Decision card on the overview and the Verification tab
   (claim ledger: what the CV says next to what public sources say). "Not found" is never "false"; a conflict is
   always "needs human review" and shows both sides. */
import { useState } from "react";
import { Link } from "react-router-dom";
import { useI18n } from "../../i18n";
import type { DictKey } from "../../dict";
import type { FitLens, PersonCard, PersonFact, PersonTrust } from "../../api";
import { Icon, SrcChips, type SrcIndex } from "./evidence";
import { hostOf } from "./common";
import { CLAIM_STATUSES, monthOf, type ClaimDim, type ClaimStatus, type CvReview, type CvRoleR, type LedgerClaim } from "./cvTypes";
import { asBand, CLAIM_FILTERS, filterClaims, filterCount, fitsOf, fitVerdict, ledgerCounts, matchRoleClaim, QUADRANTS, quadrantCell, timelineTone, type ClaimFilter, type Quadrant } from "./v3";
import "./v3.css";

/** Translation with a fallback for server values that have no dictionary entry (new kinds, lookups…). */
export function useTx() {
  const { t } = useI18n();
  return (k: string, fb: string) => { const s = t(k as DictKey); return s === k ? fb : s; };
}
const withLens = (href: string, l: string) => { const q = new URLSearchParams(location.search); q.set("lens", l); return `${href}?${q}`; };

/* ---------- small shared chips ---------- */
export function StatusPill({ status }: { status: string }) {
  const { t } = useI18n();
  const s = (CLAIM_STATUSES as string[]).includes(status) ? status : "not_found";
  return <span className={"hv-st s-" + s}>{t(("hv.st." + s) as DictKey)}</span>;
}

/** Trust band chip: High · Medium · Low / needs review. */
export function TrustChip({ band, score }: { band: string | null | undefined; score?: number | null }) {
  const { t, fmt } = useI18n();
  const b = asBand(band);
  if (!b) return null;
  return <span className={"hv-trust b-" + b} title={t("hv.trust.tip")}>{Icon.shield}<span>{t("hv.trust.short")}: {t(("hv.tb." + b) as DictKey)}</span>{score != null && <b className="num">{fmt(Math.round(score))}</b>}</span>;
}

/** Fit verdict badge: Strong fit / Fit with conditions / Weak fit / Not suitable (+ score). */
export function VerdictBadge({ verdict, score, lens }: { verdict: string; score?: number | null; lens?: FitLens | string | null }) {
  const { t, fmt } = useI18n();
  const v = ["strong", "conditional", "weak", "not_suitable"].includes(verdict) ? verdict : "weak";
  return (
    <span className={"hv-verdict v-" + v}>
      {lens && <small>{t(("hv.lens." + lens) as DictKey)}</small>}
      <span>{t(("hv.v." + v) as DictKey)}</span>
      {score != null && <b className="num">{fmt(Math.round(score))}</b>}
    </span>
  );
}

const TIERS = [1, 2, 3, 4] as const;
function TierBadge({ tier }: { tier: number | null | undefined }) {
  const { t } = useI18n();
  if (tier == null || !(TIERS as readonly number[]).includes(tier)) return <span className="hv-tier none" title={t("hv.tier.none")}>–</span>;
  return <span className={"hv-tier t" + tier} title={t(("hv.tier." + tier) as DictKey)}>T{tier}<span className="sr-only"> · {t(("hv.tier." + tier) as DictKey)}</span></span>;
}

/** Identity · Org · Title · Dates · Metric / Degree: ✓ matched, ✗ differs, – not applicable. */
function DimChips({ c }: { c: LedgerClaim }) {
  const { t } = useI18n();
  const d = c.dims ?? {};
  const last: ClaimDim = d.metric != null ? "metric" : d.degree != null ? "degree" : c.kind === "education" ? "degree" : "metric";
  const dims: ClaimDim[] = ["identity", "org", "title", "dates", last];
  return (
    <span className="hv-dims">
      {dims.map((k) => {
        const v = d[k];
        const cls = v === true ? "y" : v === false ? "n" : "na";
        const mark = v === true ? "✓" : v === false ? "✗" : "–";
        const state = t(v === true ? "hv.dim.y" : v === false ? "hv.dim.n" : "hv.dim.na");
        return <span key={k} className={"hv-dim " + cls} title={`${t(("hv.dim." + k) as DictKey)}: ${state}`}><i aria-hidden="true">{mark}</i>{t(("hv.dim." + k) as DictKey)}<span className="sr-only">: {state}</span></span>;
      })}
    </span>
  );
}

/* ---------- Decision card (overview) ---------- */
export function DecisionCard({ card, fitHref, verifyHref }: { card: PersonCard; fitHref: string; verifyHref?: string | null }) {
  const { t, fmt } = useI18n();
  const d = card.decision;
  if (!d) return null;
  const q: Quadrant = (QUADRANTS as readonly string[]).includes(d.quadrant) ? (d.quadrant as Quadrant) : "verify_first";
  const [row, col] = quadrantCell(q);
  const lenses = fitsOf(card);
  const tr = card.trust;
  const band = asBand(tr?.band ?? d.trust_band);
  const reasons = (d.reasons ?? []).slice(0, 3), verify = (d.verify ?? []).slice(0, 3);
  const cells: Quadrant[][] = [["other_role", "proceed"], ["stop", "verify_first"]];
  return (
    <section className={"hp-card hv-decision q-" + q} aria-labelledby="hv-dec-h">
      <div className="hv-dtop">
        <div className="hv-dtxt">
          <span className="eyebrow">{t("hv.dec.eyebrow")}</span>
          <h2 id="hv-dec-h" className="hv-qword">{t(("hv.q." + q) as DictKey)}</h2>
          <p className="hp-lead">{t(("hv.q." + q + ".p") as DictKey)}</p>
          <div className="hv-dfacts">
            <div>
              <h3>{t("hv.dec.fit")}</h3>
              <div className="hv-chips">
                {lenses.length ? lenses.map(([l, f]) => <Link key={l} to={withLens(fitHref, l)} className="hv-chiplink"><VerdictBadge lens={l} verdict={fitVerdict(f)} score={f.score} /></Link>) : <span className="muted-sm">{t("hv.dec.nofit")}</span>}
              </div>
            </div>
            <div>
              <h3>{t("hv.dec.trust")}</h3>
              <div className="hv-chips">
                {band ? <TrustChip band={band} score={tr?.score} /> : <span className="muted-sm">{t("hv.dec.notrust")}</span>}
                {tr?.coverage_pct != null && <span className="muted-sm">{t("hv.trust.cov", { p: fmt(Math.round(tr.coverage_pct)) })}</span>}
              </div>
            </div>
          </div>
        </div>
        <div className="hv-matrix" role="img" aria-label={t("hv.dec.aria", { q: t(("hv.q." + q) as DictKey) })}>
          <span className="ya" aria-hidden="true">{t("hv.dec.ax.trust")} ↑</span>
          <div className="cells" aria-hidden="true">
            {cells.map((r, ri) => r.map((c, ci) => <span key={c} className={"cell c-" + c + (ri === row && ci === col ? " on" : "")}>{t(("hv.q." + c) as DictKey)}</span>))}
          </div>
          <span className="xa" aria-hidden="true">{t("hv.dec.ax.fit")} →</span>
        </div>
      </div>
      {(reasons.length > 0 || verify.length > 0) && (
        <div className="hv-dlists">
          {reasons.length > 0 && <div className="why"><h3>{Icon.up}{t("hv.dec.why")}</h3><ul>{reasons.map((x, i) => <li key={i}>{x}</li>)}</ul></div>}
          {verify.length > 0 && <div className="chk"><h3>{Icon.conf}{t("hv.dec.verify")}</h3><ol>{verify.map((x, i) => <li key={i}>{x}</li>)}</ol></div>}
        </div>
      )}
      {verifyHref && <p className="hv-dfoot hr-noprint"><Link to={verifyHref}>{t("hv.dec.openver")} →</Link></p>}
    </section>
  );
}

/* ---------- Verification tab ---------- */
function TrustCard({ trust }: { trust: PersonTrust }) {
  const { t, fmt } = useI18n();
  const b = asBand(trust.band);
  const cons = trust.consistency;
  return (
    <div className={"hp-card hv-trustcard b-" + (b ?? "none")}>
      <h2>{t("hv.trust.h")}</h2>
      <div className="hv-trustline">
        <span className="band">{b ? t(("hv.tb." + b) as DictKey) : "–"}</span>
        {trust.score != null ? <span className="sc num">{fmt(Math.round(trust.score))}<small>/100</small></span> : <span className="muted-sm">{t("hv.trust.hidden")}</span>}
      </div>
      <ul className="hv-trustfacts">
        {trust.coverage_pct != null && <li>{t("hv.trust.cov.l", { p: fmt(Math.round(trust.coverage_pct)) })}</li>}
        {(trust.contradicted_key ?? 0) > 0 && <li className="bad">{Icon.conf}{t("hv.trust.ckey", { n: fmt(trust.contradicted_key ?? 0) })}</li>}
        {cons && <li>{(cons.overlaps ?? 0) + (cons.date_issues ?? 0) > 0 ? t("hv.trust.cons", { o: fmt(cons.overlaps ?? 0), d: fmt(cons.date_issues ?? 0) }) : t("hv.trust.cons.ok")}</li>}
      </ul>
      <p className="hp-foot">{t("hv.trust.p")}</p>
    </div>
  );
}

function SourceSays({ c, facts, ix }: { c: LedgerClaim; facts: Map<string, PersonFact>; ix: SrcIndex }) {
  const { t } = useI18n();
  const fs = (c.fact_ids ?? []).map((id) => facts.get(id)).filter((f): f is PersonFact => !!f);
  if (c.conflict) {
    const k = c.conflict;
    return (
      <div className="hv-src conflict">
        <q>{k.quote}</q>
        {(k.field || k.source_value) && <small>{k.field ? t("hv.conf.field", { f: k.field, v: k.source_value ?? "–" }) : k.source_value}</small>}
        <a href={k.url} target="_blank" rel="noopener noreferrer nofollow">{hostOf(k.url)} ↗</a>
      </div>
    );
  }
  if (fs.length) {
    return (
      <ul className="hv-src facts">
        {fs.slice(0, 3).map((f) => <li key={f.id}>{f.text} <SrcChips ix={ix} factIds={[f.id]} />{f.quote && <q>{f.quote}</q>}</li>)}
      </ul>
    );
  }
  if (c.sources?.length) {
    return <ul className="hv-src links">{c.sources.slice(0, 3).map((s) => <li key={s.url}><a href={s.url} target="_blank" rel="noopener noreferrer nofollow">{hostOf(s.url)} ↗</a></li>)}</ul>;
  }
  const empty: DictKey = c.status === "unverifiable" ? "hv.src.unverifiable" : c.status === "not_found" ? "hv.src.notfound" : "hv.src.none";
  return <p className="hv-src none">{t(empty)}</p>;
}

function LedgerTimeline({ roles, claims }: { roles: CvRoleR[]; claims: LedgerClaim[] }) {
  const { t } = useI18n();
  const rows = roles.map((r) => ({ r, c: matchRoleClaim(r, claims), a: monthOf(r.start), z: monthOf(r.end, true) ?? monthOf(r.start, true) }))
    .filter((x): x is { r: CvRoleR; c: LedgerClaim | null; a: number; z: number } => x.a != null && x.z != null);
  if (!rows.length) return null;
  const lo = Math.min(...rows.map((x) => x.a)), hi = Math.max(...rows.map((x) => x.z)) + 1;
  const y0 = Math.floor(lo / 12), y1 = Math.ceil(hi / 12);
  const span = Math.max(12, y1 * 12 - y0 * 12);
  const pos = (m: number) => ((m - y0 * 12) / span) * 100;
  const step = span / 12 > 16 ? 4 : span / 12 > 8 ? 2 : 1;
  const ticks = Array.from({ length: Math.floor((y1 - y0) / step) + 1 }, (_, i) => y0 + i * step);
  return (
    <div className="hx-gantt hv-tl">
      <div className="axis" aria-hidden="true"><span className="lbl" /><span className="track">{ticks.map((y) => <i key={y} style={{ left: pos(y * 12) + "%" }}>{y}</i>)}</span></div>
      {rows.map(({ r, c, a, z }, i) => {
        const tone = timelineTone(c?.status);
        const st = t(c ? (("hv.st." + ((CLAIM_STATUSES as string[]).includes(c.status) ? c.status : "not_found")) as DictKey) : "hv.tl.noclaim");
        return (
          <div className="row" key={i}>
            <span className="lbl"><b>{r.title || "–"}</b><small>{r.org}</small></span>
            <span className="track">
              <i className={"bar tone-" + tone} style={{ left: pos(a) + "%", width: Math.max(1.2, pos(z + 1) - pos(a)) + "%" }} title={`${r.start || "?"} – ${r.end || "?"} · ${st}`}><span className="sr-only">{st}</span></i>
            </span>
          </div>
        );
      })}
      <div className="legend">
        <span><i className="bar tone-ok" />{t("hv.st.verified")}</span>
        <span><i className="bar tone-part" />{t("hv.st.partly_verified")}</span>
        <span><i className="bar tone-unv" />{t("hv.tl.unv")}</span>
        <span><i className="bar tone-bad" />{t("hv.tl.bad")}</span>
      </div>
    </div>
  );
}

export function Verification({ card, rv, ix }: { card: PersonCard; rv: CvReview; ix: SrcIndex }) {
  const { t, fmt } = useI18n();
  const tx = useTx();
  const [flt, setFlt] = useState<ClaimFilter>("all");
  const l = rv.ledger;
  if (!l) return null;
  const claims = l.claims ?? [];
  const counts = ledgerCounts(l);
  const total = claims.length || CLAIM_STATUSES.reduce((a, s) => a + counts[s], 0);
  const shown = filterClaims(claims, flt);
  const facts = new Map(card.facts.map((f) => [f.id, f] as const));
  const roles = rv.timeline?.roles ?? [];
  const order: ClaimStatus[] = ["verified", "partly_verified", "unverifiable", "not_found", "contradicted"];
  return (
    <>
      <div className="hp-card hv-vhead">
        <h2>{t("hv.ver.h")} <span className="count">{t("hv.ver.n", { n: fmt(total) })}</span></h2>
        <p className="hv-note">{Icon.shield}<span><b>{t("hv.ver.note.b")}</b> {t("hv.ver.note")}</span></p>
        {total > 0 && (
          <>
            <div className="hv-cbar" role="img" aria-label={order.map((s) => `${t(("hv.st." + s) as DictKey)} ${counts[s]}`).join(" · ")}>
              {order.map((s) => (counts[s] ? <i key={s} className={"s-" + s} style={{ width: (counts[s] / total) * 100 + "%" }} /> : null))}
            </div>
            <ul className="hv-clegend">
              {order.map((s) => <li key={s} className={"s-" + s}><i aria-hidden="true" /><b className="num">{fmt(counts[s])}</b> {t(("hv.st." + s) as DictKey)}</li>)}
            </ul>
          </>
        )}
      </div>

      {card.trust && <TrustCard trust={card.trust} />}

      <div className="hp-card">
        <h2>{t("hv.led.h")}</h2>
        <div className="hv-filters" role="group" aria-label={t("hv.flt.aria")}>
          {CLAIM_FILTERS.map((f) => {
            const n = filterCount(counts, total, f);
            return (
              <button key={f} type="button" className={"hv-flt f-" + f} aria-pressed={flt === f} onClick={() => setFlt(f)} disabled={f !== "all" && n === 0}>
                {t(("hv.flt." + f) as DictKey)} <span className="n num">{fmt(n)}</span>
              </button>
            );
          })}
        </div>
        {shown.length === 0 ? <p className="hp-lead">{t("hv.led.empty")}</p> : (
          <div className="hp-tbl">
            <table className="hv-ledger">
              <caption className="sr-only">{t("hv.led.h")}</caption>
              <thead><tr><th scope="col">{t("hv.col.cv")}</th><th scope="col">{t("hv.col.src")}</th><th scope="col">{t("hv.col.checks")}</th><th scope="col">{t("hv.col.status")}</th><th scope="col">{t("hv.col.tier")}</th></tr></thead>
              <tbody>
                {shown.map((c) => (
                  <tr key={c.id} className={"s-" + c.status}>
                    <td className="cv" data-l={t("hv.col.cv")}>
                      <span className="k">{tx("hv.kind." + c.kind, c.kind)}{(c.importance ?? 1) >= 3 ? " · " + t("hv.imp.key") : ""}</span>
                      <b>{c.text}</b>
                      {c.cv_quote && <q>{c.cv_quote}</q>}
                    </td>
                    <td className="src" data-l={t("hv.col.src")}><SourceSays c={c} facts={facts} ix={ix} />{c.note && <small className="note">{c.note}</small>}</td>
                    <td className="dims" data-l={t("hv.col.checks")}><DimChips c={c} /></td>
                    <td className="st" data-l={t("hv.col.status")}><StatusPill status={c.status} /></td>
                    <td className="tier" data-l={t("hv.col.tier")}><TierBadge tier={c.best_tier} /><SrcChips ix={ix} factIds={c.fact_ids} urls={c.sources?.map((s) => s.url)} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <p className="hp-foot">{t("hv.tier.legend")}</p>
      </div>

      {roles.length > 0 && claims.length > 0 && (
        <div className="hp-card">
          <h2>{t("hv.tl.h")}</h2>
          <p className="hp-lead">{t("hv.tl.p")}</p>
          <LedgerTimeline roles={roles} claims={claims} />
        </div>
      )}

      {((l.namesakes?.length ?? 0) > 0 || (l.lookups?.length ?? 0) > 0) && (
        <div className="hp-duo">
          {(l.namesakes?.length ?? 0) > 0 && (
            <div className="hp-card hv-namesakes">
              <h2>{t("hv.ns.h")} <span className="count">{fmt(l.namesakes!.length)}</span></h2>
              <p className="hp-lead">{t("hv.ns.p")}</p>
              <ul className="hp-list">{l.namesakes!.map((n, i) => <li key={i}><a href={n.url} target="_blank" rel="noopener noreferrer nofollow">{hostOf(n.url)} ↗</a>{n.reason ? <small> · {n.reason}</small> : null}</li>)}</ul>
            </div>
          )}
          {(l.lookups?.length ?? 0) > 0 && (
            <div className="hp-card">
              <h2>{t("hv.lk.h")}</h2>
              <ul className="hv-lookups">
                {l.lookups!.map((k, i) => (
                  <li key={i} className={k.found ? "ok" : "no"}>
                    <span className="ic" aria-hidden="true">{k.found ? Icon.met : Icon.none}</span>
                    <span>
                      <b>{tx("hv.lk." + k.kind, k.kind)}</b>{k.query ? <small> · {k.query}</small> : null}
                      <small className="d">{k.found ? t("hv.lk.found") : t("hv.lk.nf")}{k.detail ? " — " + k.detail : ""}</small>
                    </span>
                    {k.url && <a href={k.url} target="_blank" rel="noopener noreferrer nofollow">{hostOf(k.url)} ↗</a>}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </>
  );
}
