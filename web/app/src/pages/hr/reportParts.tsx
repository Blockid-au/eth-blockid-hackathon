/* Building blocks shared by the person report (/p/:id) and the team report (/r/:id). */
import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { useI18n } from "../../i18n";
import type { DictKey } from "../../dict";
import { api, type PersonSubScore, type Team, type TeamReport } from "../../api";
import { errText } from "../../auth";
import { EvLabel, evOfPart, Icon, SrcChips, bandOf, bandWord, fmtDate, type Conf, type SrcIndex } from "./evidence";
import { partLabel } from "./common";

/** Bold segmented tab bar, sticky under the top nav. Each tab is a URL (links keep ?share=); arrow keys move between tabs. */
export function TabNav({ base, tabs, cur, label }: { base: string; tabs: [string, DictKey, number?][]; cur: string; label: string; className?: string }) {
  const { t, fmt } = useI18n();
  const { search } = useLocation();
  const nav = useNavigate();
  const box = useRef<HTMLDivElement>(null);
  const bar = useRef<HTMLDivElement>(null);
  const focusNext = useRef(false);
  const [fade, setFade] = useState("");
  const upd = useCallback(() => {
    const el = box.current;
    if (!el) return;
    const l = el.scrollLeft > 4, r = el.scrollLeft + el.clientWidth < el.scrollWidth - 4;
    setFade((l ? " fl" : "") + (r ? " fr" : ""));
  }, []);
  // keep the active tab in view and focused after keyboard moves
  useEffect(() => {
    const el = box.current;
    const a = el?.querySelector<HTMLElement>('[aria-selected="true"]');
    if (el && a) {
      const left = a.offsetLeft - (el.clientWidth - a.offsetWidth) / 2;
      el.scrollTo({ left: Math.max(0, left), behavior: "smooth" });
      if (focusNext.current) { a.focus({ preventScroll: true }); focusNext.current = false; }
    }
    upd();
  }, [cur, upd]);
  // publish the bar height so sticky side cards sit under it
  useEffect(() => {
    const el = bar.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(() => { document.documentElement.style.setProperty("--hr-tabs-h", el.offsetHeight + "px"); upd(); });
    ro.observe(el);
    return () => ro.disconnect();
  }, [upd]);
  const go = (k: string) => nav(`${base}/${k}${search}`, { replace: true });
  const onKey = (e: React.KeyboardEvent) => {
    const i = tabs.findIndex(([k]) => k === cur);
    let j = -1;
    if (e.key === "ArrowRight" || e.key === "ArrowDown") j = (i + 1) % tabs.length;
    else if (e.key === "ArrowLeft" || e.key === "ArrowUp") j = (i - 1 + tabs.length) % tabs.length;
    else if (e.key === "Home") j = 0;
    else if (e.key === "End") j = tabs.length - 1;
    if (j < 0) return;
    e.preventDefault();
    focusNext.current = true;
    go(tabs[j][0]);
  };
  return (
    <>
    <div className="hx-tabanchor" aria-hidden="true" />
    <div className="hx-tabbar" ref={bar}>
      <div className={"hx-tabs" + fade} role="tablist" aria-label={label} ref={box} onScroll={upd} onKeyDown={onKey}>
        {tabs.map(([k, lk, n]) => (
          <Link key={k} id={"tabbtn-" + k} role="tab" aria-selected={k === cur} aria-controls={"tab-" + k} tabIndex={k === cur ? 0 : -1}
            to={`${base}/${k}${search}`} replace>
            <span>{t(lk)}</span>{n != null && n > 0 ? <span className="n">{fmt(n)}</span> : null}
          </Link>
        ))}
      </div>
    </div>
    </>
  );
}

/** One tab panel. Every panel is rendered; inactive ones are hidden on screen and printed in order. */
export function Panel({ id, cur, title, children, className = "" }: { id: string; cur: string; title: string; children: ReactNode; className?: string }) {
  return (
    <section className={"hp-panel " + id + (id === cur ? "" : " hp-off") + (className ? " " + className : "")} role="tabpanel" aria-labelledby={"tabbtn-" + id} id={"tab-" + id}>
      <h2 className="hp-ptitle">{title}</h2>
      {children}
    </section>
  );
}

/** Score parts: label + why · weight · bar (50 cap line) · score · points · evidence; total row. */
export function PartsTable({ parts, prefix, ix, cap = 50, kind, conf }: { parts: Record<string, PersonSubScore>; prefix: "hr.sub." | "hr.fit."; ix: SrcIndex; cap?: number; kind: "fit" | "q"; conf: Conf }) {
  const { t, fmt } = useI18n();
  const rows = Object.entries(parts ?? {});
  const w = (s: PersonSubScore) => (Number(s.weight) > 1 ? Number(s.weight) / 100 : Number(s.weight) || 0);
  const total = rows.reduce((a, [, s]) => a + (Number(s.score) || 0) * w(s), 0);
  return (
    <>
      <table className="hp-comp">
        <caption className="sr-only">{t("hr.pr.parts.cap")}</caption>
        <thead><tr><th scope="col">{t("hr.pr.col.part")}</th><th scope="col" className="wt">{t("hr.pr.col.weight")}</th><th scope="col">0 — 100</th><th scope="col" className="r">{t("hr.pr.col.score")}</th><th scope="col" className="r">{t("hr.pr.col.points")}</th><th scope="col">{t("hr.pr.col.evidence")}</th></tr></thead>
        <tbody>
          {rows.map(([k, s]) => {
            const v = Math.max(0, Math.min(100, Number(s.score) || 0));
            return (
              <tr key={k}>
                <td className="lbl"><b>{partLabel(t, prefix, k)}{s.capped && <span className="hp-capchip">{t("hr.pr.capped", { c: cap })}</span>}</b>{s.rationale && <span className="why">{s.rationale} <SrcChips ix={ix} factIds={s.fact_ids} /></span>}</td>
                <td className="wt mono muted">{fmt(w(s) * 100)}%</td>
                <td className="bc"><div className="hp-bar" role="img" aria-label={`${partLabel(t, prefix, k)} ${fmt(v)}/100`}><i className={v < 65 ? "mid" : ""} style={{ width: v + "%" }} /></div></td>
                <td className="r"><b>{fmt(v)}</b></td>
                <td className="r num">{fmt(v * w(s), 1)}</td>
                <td className="evc"><EvLabel ev={evOfPart(s)} /></td>
              </tr>
            );
          })}
        </tbody>
        <tfoot><tr><td>{t("hr.pr.total")}</td><td className="wt mono muted">100%</td><td className="bc" /><td className="r" /><td className="r num">{fmt(total, 1)} → {fmt(Math.round(total))}</td><td className="evc"><span className="muted" style={{ fontWeight: 500, fontSize: ".8rem" }}>{bandWord(t, total, conf, kind)} · {t(("hr.conf." + conf) as DictKey)}</span></td></tr></tfoot>
      </table>
      <p className="hp-capnote"><i />{t("hr.pr.capnote", { c: cap })}</p>
    </>
  );
}

/** Sources table (S1…Sn) with fetch date and hash. */
export function SourcesTable({ ix }: { ix: SrcIndex }) {
  const { t, lang } = useI18n();
  const rows = [...ix.byId.values()].sort((a, b) => a.n - b.n);
  if (!rows.length) return <p className="hp-lead">{t("hr.pr.nosources")}</p>;
  const kindWord = (k?: string) => { const key = ("hr.src." + (k || "page")) as DictKey; const s = t(key); return s === key ? k : s; };
  return (
    <div className="hp-tbl">
      <table className="hp-srct">
        <caption className="sr-only">{t("hr.pr.sources")}</caption>
        <thead><tr><th scope="col">ID</th><th scope="col">{t("hr.pr.col.page")}</th><th scope="col">{t("hr.pr.col.type")}</th><th scope="col">{t("hr.pr.col.fetched")}</th></tr></thead>
        <tbody>
          {rows.map(({ n, s }) => (
            <tr key={s.id} id={"src-" + s.id}>
              <td className="id">S{n}</td>
              <td><a href={s.url} target="_blank" rel="noopener noreferrer nofollow">{s.title || s.url}</a><span className="url">{s.url.replace(/^https?:\/\//, "")}</span></td>
              <td>{kindWord(s.kind)}</td>
              <td><span className="hash">{s.fetched_at ? fmtDate(s.fetched_at, lang) : "–"}{s.sha256 ? " · " + s.sha256.slice(0, 8) : ""}</span></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** Method box + "checked by a person" box. */
export function MethodBox({ rep, team }: { rep: TeamReport; team: Team }) {
  const { t, fmt } = useI18n();
  const m = rep.method ?? {};
  const pw = m.person_weights ?? {};
  const c = rep.counters ?? {};
  return (
    <div className="hp-method" id="method">
      <div>
        <h3>{t("hr.pr.method.h")}</h3>
        <ul>
          <li>{t("hr.pr.m.1", { s: fmt(c.searches ?? 0), b: fmt(c.search_budget ?? 12), p: fmt(c.pages_fetched ?? rep.sources.length) })}</li>
          <li>{t("hr.pr.m.2")}</li>
          <li>{t("hr.pr.m.3", { w: Object.values(pw).map((x) => fmt(x > 1 ? x : x * 100)).join(" / ") || "25 / 25 / 15 / 15 / 10 / 10", c: m.cap_without_evidence ?? 50 })}</li>
          <li>{t("hr.pr.m.4")}</li>
          <li>{t("hr.pr.m.5")}</li>
          {team.mode !== "person" && <li>{t("hr.pr.m.team")}</li>}
          {(m.notes ?? []).map((n, i) => <li key={i}>{n}</li>)}
        </ul>
      </div>
      <div>
        <h3>{t("hr.pr.person.h")}</h3>
        <ul>
          <li>{team.valuation_id ? t("hr.pr.p.val") : t("hr.pr.p.noval")}</li>
          <li>{t("hr.pr.p.2")}</li>
          <li>{t("hr.pr.p.3")}</li>
        </ul>
        <p style={{ marginTop: 10 }} className="hr-noprint"><a className="btn ghost sm" href={`mailto:info@blockid.au?subject=${encodeURIComponent("BlockID HR report " + team.id + " — mistake")}`}>{t("hr.pr.mistake")}</a></p>
      </div>
    </div>
  );
}

/** Consent and fairness footer. */
export function ConsentFooter({ team, names }: { team: Team; names: string }) {
  const { t, lang } = useI18n();
  return (
    <footer className="hp-consent" aria-labelledby="cf-h">
      <h2 id="cf-h">{Icon.shield}{t("hr.pr.cf.h")}</h2>
      <div>
        <p>{t("hr.pr.cf.agreed", { n: names, d: team.consented_at ? fmtDate(team.consented_at, lang) : "–" })}</p>
        <p style={{ marginTop: 8 }}>{t("hr.pr.cf.remove")} <a href="mailto:info@blockid.au">info@blockid.au</a>.</p>
      </div>
      <div>
        <p><b>{t("hr.pr.cf.never")}</b></p>
        <ul>
          <li>{t("hr.pr.cf.n1")}</li>
          <li>{t("hr.pr.cf.n2")}</li>
          <li>{t("hr.pr.cf.n3")}</li>
          <li>{t("hr.pr.cf.n4")}</li>
        </ul>
      </div>
      <p className="legal">{t("hr.pr.legal", { id: team.id, d: fmtDate(team.result?.created_at ?? team.updated_at, lang) })}</p>
    </footer>
  );
}

/** Copy link (creates a share token for the requester/admin) + Download PDF (print). */
export function ReportActions({ team, path }: { team: Team; path: string }) {
  const { t } = useI18n();
  const [msg, setMsg] = useState("");
  const copy = async () => {
    setMsg("");
    try {
      let token = team.share_token ?? new URLSearchParams(location.search).get("share");
      if (!token && team.can_edit) token = (await api.hrShare(team.id)).share_token;
      const url = `${location.origin}${path}${token ? `?share=${encodeURIComponent(token)}` : ""}`;
      await navigator.clipboard.writeText(url).catch(() => { throw new Error(url); });
      setMsg(t("hr.r.share.copied"));
    } catch (e) {
      setMsg(e instanceof Error && e.message.startsWith("http") ? e.message : errText(e, t));
    }
    setTimeout(() => setMsg(""), 5000);
  };
  return (
    <div className="hp-acts">
      <button className="btn ghost sm" type="button" onClick={() => window.print()}>{Icon.print}{t("hr.pr.pdf")}</button>
      <button className="btn ghost sm" type="button" onClick={copy}>{Icon.link}{t("hr.pr.copy")}</button>
      {msg && <span className="muted-sm" role="status" style={{ alignSelf: "center", overflowWrap: "anywhere" }}>{msg}</span>}
    </div>
  );
}

/** Label for a team/person score with confidence, e.g. "Good fit 78 · Medium". */
export function ScoreInline({ score, conf, kind }: { score: number | null | undefined; conf: Conf; kind: "fit" | "q" | "team" }) {
  const { t, fmt } = useI18n();
  if (score == null) return <span className="muted">–</span>;
  return <span>{bandWord(t, score, conf, kind)} <b className="num">{fmt(score, 0)}</b> · {t(("hr.conf." + conf) as DictKey)}</span>;
}

export { bandOf };
