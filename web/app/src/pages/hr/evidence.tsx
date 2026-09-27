/* Evidence labels, bands, confidence and the band track for BlockID HR reports (design spec §2.2–2.3). */
import type { ReactNode } from "react";
import { useI18n } from "../../i18n";
import type { DictKey } from "../../dict";
import type { HrSource, PersonCard, PersonSubScore, TeamReport } from "../../api";
import "./person.css";

/* ---------- icons (shape + word, never colour only) ---------- */
const P = { fill: "none", stroke: "currentColor", strokeWidth: 1.6, strokeLinecap: "round" as const, strokeLinejoin: "round" as const };
export const Icon = {
  ok: <svg viewBox="0 0 16 16" aria-hidden="true"><circle cx="8" cy="8" r="7" fill="currentColor" /><path d="M4.8 8.2l2.1 2.1 4.3-4.5" fill="none" stroke="var(--surface)" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" /></svg>,
  self: <svg viewBox="0 0 16 16" aria-hidden="true"><circle cx="8" cy="8" r="6.8" {...P} strokeWidth={1.5} /><circle cx="8" cy="6.4" r="2.1" fill="currentColor" /><path d="M4.4 12.2c.8-1.7 2.1-2.5 3.6-2.5s2.8.8 3.6 2.5" fill="currentColor" /></svg>,
  unc: <svg viewBox="0 0 16 16" aria-hidden="true"><circle cx="8" cy="8" r="6.6" {...P} strokeDasharray="2.6 2" /><path d="M6.3 6.2a1.8 1.8 0 113 1.4c-.7.4-1.1.8-1.1 1.6" {...P} strokeWidth={1.5} /><circle cx="8.2" cy="11.4" r=".9" fill="currentColor" /></svg>,
  none: <svg viewBox="0 0 16 16" aria-hidden="true"><circle cx="8" cy="8" r="6.8" {...P} strokeWidth={1.5} /><path d="M5 8h6" {...P} strokeWidth={1.8} /></svg>,
  conf: <svg viewBox="0 0 16 16" aria-hidden="true"><path d="M8 1.6l6.8 12.2H1.2z" {...P} strokeWidth={1.5} /><path d="M8 6v3.6" {...P} /><circle cx="8" cy="11.6" r=".9" fill="currentColor" /></svg>,
  met: <svg viewBox="0 0 16 16" aria-hidden="true"><path d="M3 8.4l3.1 3.1L13 4.6" {...P} strokeWidth={2.2} /></svg>,
  part: <svg viewBox="0 0 16 16" aria-hidden="true"><circle cx="8" cy="8" r="6" {...P} strokeWidth={2} /><path d="M8 2a6 6 0 010 12z" fill="currentColor" /></svg>,
  x: <svg viewBox="0 0 16 16" aria-hidden="true"><path d="M4 4l8 8M12 4l-8 8" {...P} strokeWidth={2.2} /></svg>,
  up: <svg viewBox="0 0 16 16" aria-hidden="true"><path d="M8 13V3M3.5 7.5L8 3l4.5 4.5" {...P} strokeWidth={2} /></svg>,
  down: <svg viewBox="0 0 16 16" aria-hidden="true"><path d="M8 3v10M3.5 8.5L8 13l4.5-4.5" {...P} strokeWidth={2} /></svg>,
  pin: <svg viewBox="0 0 16 16" aria-hidden="true"><path d="M8 14.5s5-4.6 5-8.3A5 5 0 003 6.2c0 3.7 5 8.3 5 8.3z" {...P} strokeWidth={1.5} /><circle cx="8" cy="6.3" r="1.8" fill="currentColor" /></svg>,
  team: <svg viewBox="0 0 16 16" aria-hidden="true"><circle cx="5.5" cy="5.5" r="2.3" fill="currentColor" /><circle cx="11" cy="6.2" r="1.9" fill="currentColor" opacity=".7" /><path d="M1.2 13.5c.6-2.4 2.3-3.6 4.3-3.6s3.7 1.2 4.3 3.6zM9.6 13.5c.3-1.5 1-2.6 2-3 1.7-.2 2.9.9 3.2 3z" fill="currentColor" /></svg>,
  shield: <svg viewBox="0 0 16 16" aria-hidden="true"><path d="M8 1.5l5.5 2v4.2c0 3.3-2.3 5.8-5.5 6.8-3.2-1-5.5-3.5-5.5-6.8V3.5z" {...P} strokeWidth={1.5} /><path d="M5.6 8l1.7 1.7 3.2-3.3" {...P} strokeWidth={1.5} /></svg>,
  print: <svg viewBox="0 0 16 16" aria-hidden="true"><path d="M4 6V1.8h8V6M4 12H2.4A.9.9 0 011.5 11V6.9c0-.5.4-.9.9-.9h11.2c.5 0 .9.4.9.9V11c0 .5-.4 1-.9 1H12" {...P} strokeWidth={1.4} /><rect x="4" y="9.5" width="8" height="5" {...P} strokeWidth={1.4} /></svg>,
  link: <svg viewBox="0 0 16 16" aria-hidden="true"><path d="M6.6 9.4a3 3 0 004.3 0l2.2-2.2a3 3 0 00-4.3-4.3l-.9.9M9.4 6.6a3 3 0 00-4.3 0L2.9 8.8a3 3 0 004.3 4.3l.9-.9" {...P} strokeWidth={1.5} /></svg>,
  lock: <svg viewBox="0 0 16 16" aria-hidden="true"><rect x="3" y="7" width="10" height="7.5" rx="1.6" {...P} strokeWidth={1.5} /><path d="M5.3 7V5a2.7 2.7 0 015.4 0v2" {...P} strokeWidth={1.5} /></svg>,
};

/* ---------- evidence labels ---------- */
export type Ev = "verified" | "self" | "unconfirmed" | "none" | "conflict" | "computed";
const EV: Record<Ev, [string, ReactNode, DictKey]> = {
  verified: ["v", Icon.ok, "hr.ev.verified"],
  self: ["s", Icon.self, "hr.ev.self"],
  unconfirmed: ["u", Icon.unc, "hr.ev.unconfirmed"],
  none: ["n", Icon.none, "hr.ev.none"],
  conflict: ["c", Icon.conf, "hr.ev.conflict"],
  computed: ["n", Icon.none, "hr.ev.computed"],
};
export function EvLabel({ ev, iconOnly = false }: { ev: Ev; iconOnly?: boolean }) {
  const { t } = useI18n();
  const [c, ic, k] = EV[ev];
  return <span className={"hp-ev " + c + (iconOnly ? " io" : "")} title={iconOnly ? t(k) : undefined}>{ic}{iconOnly ? <span className="sr-only">{t(k)}</span> : t(k)}</span>;
}
export function evOfSource(src?: { type?: string; fact_ids?: string[] } | null): Ev {
  if (!src) return "self";
  if (src.type === "verified") return src.fact_ids?.length === 0 ? "unconfirmed" : "verified";
  if (src.type === "self_reported") return "self";
  return "unconfirmed";
}
export function evOfPart(s: PersonSubScore): Ev {
  if (s.capped) return "none";
  if (s.self_reported) return "self";
  if (s.fact_ids?.length) return "verified";
  return "unconfirmed";
}

/* ---------- sources S1…Sn ---------- */
export interface SrcIndex { byId: Map<string, { n: number; s: HrSource }>; factSrc: Map<string, string> }
export function srcIndex(rep: TeamReport | null | undefined, person?: PersonCard | null): SrcIndex {
  const byId = new Map<string, { n: number; s: HrSource }>();
  const list = (rep?.sources ?? []).filter((s) => !person || s.person_id == null || s.person_id === person.person_id);
  list.forEach((s, i) => byId.set(s.id, { n: i + 1, s }));
  const factSrc = new Map<string, string>();
  for (const c of person ? [person] : rep?.people ?? []) for (const f of c.facts ?? []) if (f.source_id) factSrc.set(f.id, f.source_id);
  return { byId, factSrc };
}
/** Source chips "S3" for fact ids and/or source ids; links jump to the sources table. */
export function SrcChips({ ix, factIds, sourceIds, urls }: { ix: SrcIndex; factIds?: string[] | null; sourceIds?: string[] | null; urls?: string[] | null }) {
  const ids = new Set<string>();
  (factIds ?? []).forEach((f) => { const s = ix.factSrc.get(f); if (s) ids.add(s); });
  (sourceIds ?? []).forEach((s) => ids.add(s));
  (urls ?? []).forEach((u) => { for (const [id, x] of ix.byId) if (x.s.url === u) ids.add(id); });
  const nums = [...ids].map((id) => ix.byId.get(id)).filter((x): x is { n: number; s: HrSource } => !!x).sort((a, b) => a.n - b.n);
  if (!nums.length) return null;
  return <span className="hp-srcs">{nums.map((x) => <a key={x.s.id} className="hp-src" href={`#src-${x.s.id}`} title={x.s.title || x.s.url}>S{x.n}</a>)}</span>;
}

/* ---------- bands, confidence, range ---------- */
export type Band = "strong" | "good" | "partial" | "weak" | "poor";
export const bandOf = (x: number): Band => (x >= 85 ? "strong" : x >= 70 ? "good" : x >= 55 ? "partial" : x >= 40 ? "weak" : "poor");
export const BAND_EDGES: [Band, number, number][] = [["poor", 0, 40], ["weak", 40, 55], ["partial", 55, 70], ["good", 70, 85], ["strong", 85, 100]];
export type Conf = "high" | "medium" | "low";
/** Share of weighted points backed by verified evidence. */
export function confidenceOf(parts: Record<string, PersonSubScore> | null | undefined): { conf: Conf; share: number } {
  const rows = Object.values(parts ?? {});
  const tot = rows.reduce((a, s) => a + (Number(s.score) || 0) * (Number(s.weight) || 0), 0);
  const ver = rows.filter((s) => evOfPart(s) === "verified").reduce((a, s) => a + (Number(s.score) || 0) * (Number(s.weight) || 0), 0);
  const share = tot > 0 ? ver / tot : 0;
  return { conf: share >= 0.75 ? "high" : share >= 0.45 ? "medium" : "low", share };
}
export const halfWidth = (c: Conf) => (c === "high" ? 4 : c === "medium" ? 6 : 10);

export function ConfPill({ conf }: { conf: Conf }) {
  const { t } = useI18n();
  const on = conf === "high" ? 3 : conf === "medium" ? 2 : 1;
  return (
    <span className={"hp-confpill " + conf}>
      <span className="hp-confbars" aria-hidden="true">{[6, 9, 12].map((h, i) => <i key={i} className={i < on ? "" : "off"} style={{ height: h }} />)}</span>
      {t(("hr.conf." + conf) as DictKey)}
    </span>
  );
}

/** 0–100 band track with the marker and the likely range bracket. */
export function BandTrack({ score, lo, hi, label }: { score: number; lo: number; hi: number; label: string }) {
  const { t } = useI18n();
  const b = bandOf(score);
  const cl = (x: number) => Math.max(0, Math.min(100, x));
  return (
    <div className="hp-track" role="img" aria-label={label}>
      {BAND_EDGES.map(([k, a, z]) => (
        <div key={k} className={"seg" + (k === b ? " on" : "")} style={{ left: a + "%", width: z - a + "%" }}><span>{t(("hr.bandshort." + k) as DictKey)}</span></div>
      ))}
      <div className="rng" style={{ left: cl(lo) + "%", width: cl(hi) - cl(lo) + "%" }} />
      <div className="mk" style={{ left: cl(score) + "%" }}><b>{Math.round(score)}</b><i /></div>
    </div>
  );
}

/** "Good fit" / "Strong team" etc.; Low confidence reads "Not enough evidence". */
export function bandWord(t: (k: DictKey) => string, score: number, conf: Conf, kind: "fit" | "q" | "team"): string {
  if (conf === "low") return t("hr.band.low");
  return t(("hr.band." + kind + "." + bandOf(score)) as DictKey);
}

export function fmtDate(d: string | null | undefined, lang: string): string {
  if (!d) return "";
  const x = new Date(d);
  return isNaN(+x) ? d : x.toLocaleDateString(lang === "vi" ? "vi-VN" : "en-AU", { day: "numeric", month: "short", year: "numeric" });
}
