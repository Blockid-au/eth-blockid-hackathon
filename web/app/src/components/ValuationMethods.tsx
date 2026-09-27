import { useI18n } from "../i18n";
import { valEn, valVi, type ValKey } from "../dict.valuation";

/** Mirrors agents/src/blockid_agents/schemas.py (Triangulation, ValuationMethod, Anchor, CompMultiple). */
export interface ValuationMethodRow {
  method: "market_anchor" | "revenue_multiple" | "stage_scorecard";
  label: string;
  value_aud: number;
  low_aud: number;
  high_aud: number;
  weight: number;
  raw_weight?: number;
  inputs: Record<string, unknown>;
  sources: string[];
  notes: string[];
}
export interface Triangulation {
  version: string;
  value_aud: number;
  low_aud: number;
  high_aud: number;
  confidence: "high" | "medium" | "low";
  confidence_reasons: string[];
  methods: ValuationMethodRow[];
  listed?: boolean;
  listing?: string;
  as_of?: string;
  fx_as_of?: string;
}
export interface AnchorRow {
  kind: string; amount: number; currency: string; amount_aud: number; as_of: string; age_months: number | null;
  source_url: string; quote: string;
}
export interface CompRow { name: string; multiple: number; public: boolean; basis: string; source_url: string; quote: string }
export interface ValuationEvidence {
  anchors: AnchorRow[];
  comps: CompRow[];
  sector_multiples: { multiple: number; sector: string; source_url: string; quote: string }[];
  listing: { exchange: string; ticker: string; source_url: string; quote: string } | null;
}

type Vars = Record<string, string | number>;

function useVal() {
  const i = useI18n();
  const dict = i.lang === "vi" ? valVi : valEn;
  const tv = (k: ValKey, vars?: Vars) => {
    let s: string = dict[k] ?? valEn[k];
    if (vars) for (const [vk, vv] of Object.entries(vars)) s = s.split("{" + vk + "}").join(String(vv));
    return s;
  };
  return { ...i, tv };
}

function host(url: string): string {
  try { return new URL(url).hostname.replace(/^www\./, ""); } catch { return url; }
}

function num(x: unknown): number { const n = Number(x); return Number.isFinite(n) ? n : 0; }

const CONF_TONE: Record<Triangulation["confidence"], string> = { high: "ok", medium: "gold", low: "bad" };

/**
 * "How we reached this value": blended fair value + range, confidence with its reasons, and one row per method
 * (plain-language name, value, weight bar, what it is based on, sources). Props are the valuation result fields
 * `svi.triangulation` (or top-level `valuation_methods`) and, optionally, `valuation_evidence`.
 */
export function ValuationMethods({ triangulation: tri, evidence }: { triangulation: Triangulation | null | undefined; evidence?: ValuationEvidence | null }) {
  const { tv, money, fmt, pct } = useVal();
  if (!tri) return null;
  const rows = [...tri.methods].sort((a, b) => b.weight - a.weight);

  const ageText = (a: number | null | undefined) =>
    a == null ? tv("val.age.unknown") : a < 1 ? tv("val.age.new") : tv("val.age", { n: Math.round(a) });

  const basedOn = (m: ValuationMethodRow): string[] => {
    const inp = m.inputs || {};
    if (m.method === "market_anchor") {
      const list = (inp.anchors as AnchorRow[] | undefined) || [];
      return list.map((a) => `${tv(("val.kind." + a.kind) as ValKey)} · ${money(a.amount_aud)} · ${ageText(a.age_months)}`);
    }
    if (m.method === "revenue_multiple") {
      const src = String(inp.revenue_source || "website");
      const ms = String(inp.multiple_source || "default");
      const out = [
        `${tv("val.rev", { v: money(num(inp.revenue_aud)) })} (${tv(("val.rev." + src) as ValKey)})`,
        `${tv("val.mult", { m: fmt(num(inp.median_multiple), 1) })} ${tv("val.mult.range", { lo: fmt(num(inp.low_multiple), 1), hi: fmt(num(inp.high_multiple), 1) })} — ${tv(("val.ms." + ms) as ValKey, { n: num(inp.n) })}`,
      ];
      if (num(inp.discount) > 0) out.push(tv("val.discount", { p: pct(num(inp.discount) * 100, 0) }));
      return out;
    }
    return [tv("val.stage", { stage: String(inp.stage || ""), f: fmt(num(inp.svi_factor), 2) })];
  };

  return (
    <section className="card solid" aria-labelledby="val-h">
      <div>
        <h4 id="val-h">{tv("val.h")}</h4>
        <p className="sub">{tv("val.sub")}</p>
      </div>

      <div className="row" style={{ display: "flex", flexWrap: "wrap", gap: 12, alignItems: "baseline" }}>
        <span className="muted-sm">{tv("val.value")}</span>
        <strong className="num" style={{ fontSize: "1.5rem" }}>{money(tri.value_aud)}</strong>
        <span className="muted-sm num">{tv("val.range", { lo: money(tri.low_aud), hi: money(tri.high_aud) })}</span>
        <span className={"pill " + CONF_TONE[tri.confidence]}>{tv("val.conf")}: {tv(("val.conf." + tri.confidence) as ValKey)}</span>
        {tri.listing ? <span className="chip">{tv("val.listed", { x: tri.listing })}</span> : null}
      </div>

      {tri.confidence_reasons.length > 0 && (
        <details>
          <summary className="muted-sm">{tv("val.conf.why")}</summary>
          <ul className="muted-sm">{tri.confidence_reasons.map((r, i) => <li key={i}>{r}</li>)}</ul>
        </details>
      )}

      {rows.length === 0 ? <p className="muted-sm">{tv("val.none")}</p> : (
        <div className="tbl">
          <table>
            <thead>
              <tr><th>{tv("val.col.method")}</th><th className="num">{tv("val.col.value")}</th><th>{tv("val.col.weight")}</th><th>{tv("val.col.based")}</th></tr>
            </thead>
            <tbody>
              {rows.map((m) => (
                <tr key={m.method} style={m.weight > 0 ? undefined : { opacity: 0.6 }}>
                  <td>
                    <strong>{tv(("val.m." + m.method) as ValKey)}</strong>
                    <div className="muted-sm">{tv(("val.m." + m.method + ".d") as ValKey)}</div>
                  </td>
                  <td className="num">{money(m.value_aud)}<div className="muted-sm">{money(m.low_aud)} – {money(m.high_aud)}</div></td>
                  <td style={{ minWidth: 110 }}>
                    {m.weight > 0 ? (
                      <>
                        <div aria-hidden="true" style={{ height: 6, borderRadius: 3, background: "var(--sunken)" }}>
                          <div style={{ width: `${Math.round(m.weight * 100)}%`, height: 6, borderRadius: 3, background: "var(--accent)" }} />
                        </div>
                        <span className="num muted-sm">{pct(m.weight * 100, 0)}</span>
                      </>
                    ) : <span className="muted-sm">{tv("val.notused")}</span>}
                  </td>
                  <td>
                    <ul className="muted-sm" style={{ margin: 0, paddingLeft: 16 }}>{basedOn(m).map((b, i) => <li key={i}>{b}</li>)}</ul>
                    {m.sources.length > 0 && (
                      <div className="muted-sm">{tv("val.sources")}: {m.sources.map((u, i) => (
                        <span key={u}>{i ? ", " : ""}<a href={u} target="_blank" rel="noopener noreferrer" title={tv("val.src.open")}>{host(u)}</a></span>
                      ))}</div>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {evidence && evidence.anchors.length > 0 && (
        <details>
          <summary className="muted-sm">{tv("val.anchors")} ({evidence.anchors.length})</summary>
          <ul className="muted-sm">
            {evidence.anchors.map((a, i) => (
              <li key={i}>
                {tv(("val.kind." + a.kind) as ValKey)} · {money(a.amount_aud)} ({a.currency} {fmt(a.amount, 0)}) · {ageText(a.age_months)} ·{" "}
                <a href={a.source_url} target="_blank" rel="noopener noreferrer">{host(a.source_url)}</a>
                <blockquote title={tv("val.quote")} style={{ margin: "4px 0 0 12px" }}>“{a.quote}”</blockquote>
              </li>
            ))}
          </ul>
        </details>
      )}

      {evidence && evidence.comps.length > 0 && (
        <details>
          <summary className="muted-sm">{tv("val.comps")} ({evidence.comps.length})</summary>
          <ul className="muted-sm">
            {evidence.comps.map((c) => (
              <li key={c.name}>{c.name} · {tv("val.mult", { m: fmt(c.multiple, 1) })} · <a href={c.source_url} target="_blank" rel="noopener noreferrer">{host(c.source_url)}</a></li>
            ))}
          </ul>
        </details>
      )}

      <p className="muted-sm">
        {tri.fx_as_of ? tv("val.fx", { d: tri.fx_as_of }) + " " : ""}
        {tri.as_of ? tv("val.asof", { d: tri.as_of }) + " " : ""}
        {tv("val.disclaimer")}
      </p>
    </section>
  );
}

export default ValuationMethods;
