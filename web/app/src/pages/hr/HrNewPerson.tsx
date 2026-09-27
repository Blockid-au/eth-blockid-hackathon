/* /new/person — "Analyse a person": a 3-step wizard (1 Who → 2 Compare with → 3 Consent & start) with a live preview
   card. The draft is kept in this browser. Maps to POST /v1/hr/people-reports {person: PersonIn, target, consent, run}. */
import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { useI18n } from "../../i18n";
import type { DictKey } from "../../dict";
import { errText, useAuth } from "../../auth";
import { api, ApiError, PERSON_KINDS, type HrTarget, type PersonKind } from "../../api";
import { useAsync } from "../../lib/hooks";
import { checkName, normUrl, THIS_YEAR, type FieldErr } from "../../lib/people";
import { FieldError, ROLE_SUGGESTIONS } from "../../components/PeopleEditor";
import { Icon } from "./evidence";
import { hostOf, initials, useHrTitle } from "./common";
import { bizInitials, handedPeople, hueOf, parsePaste, suggestRequirements, type PasteGuess } from "./parse";

const MAX_MUST = 5, MAX_NICE = 4, MAX_LINKS = 6;
const DRAFT_KEY = "blockid-hr-person-draft-v2";
type Step = 1 | 2 | 3;
type Biz = { kind: "valuation" | "listed"; id: string; name: string; sub: string; ticker?: string; website?: string | null };

interface Draft {
  step: Step; name: string; role: string; kind: PersonKind; headline: string; ft: "" | "yes" | "no"; year: string; equity: string;
  links: string[]; bio: string; cv: string; tt: "business" | "role"; biz: Biz | null; bizWeb: string; company: string; title: string; desc: string;
  must: string[]; nice: string[];
}
const EMPTY: Draft = {
  step: 1, name: "", role: "", kind: "founder", headline: "", ft: "", year: "", equity: "", links: [""], bio: "", cv: "",
  tt: "business", biz: null, bizWeb: "", company: "", title: "", desc: "", must: [], nice: [],
};
const STEP_KEYS: Record<Step, RegExp> = { 1: /^(name|role|headline|year|equity|link\d+|bio|cv)$/, 2: /^(biz|bizWeb|company|title|desc)$/, 3: /^(c1|c2)$/ };

function loadDraft(): Draft | null {
  try {
    const raw = localStorage.getItem(DRAFT_KEY);
    if (!raw) return null;
    const d = { ...EMPTY, ...(JSON.parse(raw) as Partial<Draft>) };
    if (!Array.isArray(d.links) || !d.links.length) d.links = [""];
    if (![1, 2, 3].includes(d.step)) d.step = 1;
    return d;
  } catch { return null; }
}
const isBlank = (d: Draft) => !d.name.trim() && !d.headline.trim() && !d.links.some((l) => l.trim()) && !d.bio.trim() && !d.cv.trim() && !d.biz && !d.bizWeb.trim() && !d.company.trim() && !d.title.trim() && !d.desc.trim();

function linkIcon(u: string): string {
  if (/linkedin\.com/i.test(u)) return "in";
  if (/github\.com|gitlab\.com/i.test(u)) return "GIT";
  if (/scholar\.google/i.test(u)) return "SCH";
  return "WEB";
}

function BizLogo({ b }: { b: { name: string; ticker?: string } }) {
  return <span className={"hx-logo" + (b.ticker ? " tick" : "")} style={{ ["--h" as string]: hueOf(b.ticker || b.name) }} aria-hidden="true">{b.ticker ? b.ticker.slice(0, 4) : bizInitials(b.name)}</span>;
}

export function HrNewPerson() {
  const { t, fmt } = useI18n();
  const { me, tryDemo } = useAuth();
  const nav = useNavigate();
  const [params] = useSearchParams();
  useHrTitle(t("hr.np.h1"));

  const hasParams = !!(params.get("name") || params.get("valuation") || params.get("target") || params.get("website") || params.get("person"));
  const handed = handedPeople(params)[0];
  const [boot] = useState(() => {
    if (!hasParams) {
      const saved = loadDraft();
      if (saved && !isBlank(saved)) return { d: saved, restored: true };
    }
    const d: Draft = {
      ...EMPTY, name: (params.get("name") ?? handed?.full_name ?? "").slice(0, 120), role: handed?.role ?? "", kind: handed?.kind ?? "founder",
      tt: params.get("target") === "role" ? "role" : "business",
      bizWeb: (params.get("website") ?? "").slice(0, 200),
    };
    return { d, restored: false };
  });
  const [restored, setRestored] = useState(boot.restored);
  const [d, setD] = useState<Draft>(boot.d);
  const set = (p: Partial<Draft>) => setD((x) => ({ ...x, ...p }));
  const step = d.step;
  useEffect(() => { try { localStorage.setItem(DRAFT_KEY, JSON.stringify(d)); } catch { /* private mode */ } }, [d]);

  const [c1, setC1] = useState(false);
  const [c2, setC2] = useState(false);
  const [tried, setTried] = useState<Set<Step>>(new Set());
  const [touched, setTouched] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [paste, setPaste] = useState("");
  const [more, setMore] = useState(() => !!(d.bio || d.cv || d.year || d.equity || d.ft));
  const panelRef = useRef<HTMLDivElement>(null);
  const touch = (k: string) => setTouched((s) => new Set(s).add(k));

  /* ---------- quick start: paste a LinkedIn / URL / CV ---------- */
  const guess: PasteGuess = useMemo(() => parsePaste(paste), [paste]);
  const newUrls = guess.urls.filter((u) => !d.links.includes(u));
  const canUse = { name: !!guess.name && guess.name !== d.name.trim(), headline: !!guess.headline && guess.headline !== d.headline.trim(), role: !!guess.role && guess.role !== d.role.trim(), cv: !!guess.cv && guess.cv !== d.cv, urls: newUrls.length > 0 };
  const anyGuess = Object.values(canUse).some(Boolean);
  const addUrls = (urls: string[], links = d.links) => [...links.filter((l) => l.trim()), ...urls].filter((u, i, a) => a.indexOf(u) === i).slice(0, MAX_LINKS);
  const useAll = () => {
    const p: Partial<Draft> = {};
    if (canUse.name) p.name = guess.name!.slice(0, 120);
    if (canUse.headline) p.headline = guess.headline!.slice(0, 200);
    if (canUse.role && !d.role.trim()) p.role = guess.role!;
    if (canUse.cv) { p.cv = guess.cv!; setMore(true); }
    if (canUse.urls) { const l = addUrls(newUrls); p.links = l.length ? l : [""]; }
    set(p);
    setPaste("");
  };

  /* ---------- businesses: my valuations + BlockID businesses ---------- */
  const vals = useAsync(() => (me ? api.myValuations() : Promise.resolve([])), [me?.address, me?.username]);
  const cos = useAsync(() => api.companies(), []);
  const options: Biz[] = useMemo(() => {
    const v = (vals.data ?? []).map((x) => ({ kind: "valuation" as const, id: x.id, name: (typeof x.profile?.name === "string" && x.profile.name) || hostOf(x.url), sub: hostOf(x.url) + " · " + t(("v.st." + x.status) as DictKey), website: x.url }));
    const c = (cos.data ?? []).map((x) => ({ kind: "listed" as const, id: x.ticker, ticker: x.ticker, name: x.name, sub: (x.website ? hostOf(x.website) : "") + (x.grade ? (x.website ? " · " : "") + t("ad.c.grade") + " " + x.grade : ""), website: x.website ?? null }));
    return [...v, ...c];
  }, [vals.data, cos.data, t]);
  useEffect(() => {
    const vid = params.get("valuation");
    if (!vid || d.biz) return;
    const o = options.find((x) => x.kind === "valuation" && x.id === vid);
    set({ biz: o ?? { kind: "valuation", id: vid, name: vid, sub: "" }, tt: "business" });
  }, [options]); // eslint-disable-line react-hooks/exhaustive-deps
  const [bizQ, setBizQ] = useState("");
  const [open, setOpen] = useState(false);
  const [act, setAct] = useState(0);
  const q = bizQ.trim().toLowerCase();
  const matches = useMemo(() => {
    const f = (o: Biz) => !q || (o.name + " " + o.sub + " " + (o.ticker ?? "")).toLowerCase().includes(q);
    return [...options.filter((o) => o.kind === "valuation" && f(o)).slice(0, 5), ...options.filter((o) => o.kind === "listed" && f(o)).slice(0, 8)];
  }, [options, q]);
  const pick = (o: Biz) => { set({ biz: o, bizWeb: "" }); setBizQ(""); setOpen(false); };
  const onComboKey = (e: React.KeyboardEvent) => {
    if (e.key === "ArrowDown") { e.preventDefault(); setOpen(true); setAct((a) => Math.min(matches.length - 1, a + 1)); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setAct((a) => Math.max(0, a - 1)); }
    else if (e.key === "Enter" && open && matches[act]) { e.preventDefault(); pick(matches[act]); }
    else if (e.key === "Escape") setOpen(false);
  };
  useEffect(() => setAct(0), [q]);

  /* ---------- requirements ---------- */
  const [reqIn, setReqIn] = useState("");
  const [editing, setEditing] = useState<{ g: "must" | "nice"; i: number; v: string } | null>(null);
  const suggestions = useMemo(() => suggestRequirements(d.desc + "\n" + d.title).filter((s) => !d.must.concat(d.nice).some((x) => x.toLowerCase() === s.toLowerCase())), [d.desc, d.title, d.must, d.nice]);
  const full = d.must.length >= MAX_MUST && d.nice.length >= MAX_NICE;
  const addReq = (raw: string) => {
    const r = raw.trim().slice(0, 200);
    if (!r || d.must.concat(d.nice).includes(r)) return false;
    if (d.must.length < MAX_MUST) set({ must: [...d.must, r] });
    else if (d.nice.length < MAX_NICE) set({ nice: [...d.nice, r] });
    else return false;
    return true;
  };
  const addAllSuggested = () => {
    const must = [...d.must], nice = [...d.nice];
    for (const s of suggestions) { if (must.length < MAX_MUST) must.push(s); else if (nice.length < MAX_NICE) nice.push(s); }
    set({ must, nice });
  };
  const saveEdit = () => {
    if (!editing) return;
    const v = editing.v.trim().slice(0, 200);
    const list = [...d[editing.g]];
    if (v) list[editing.i] = v; else list.splice(editing.i, 1);
    set({ [editing.g]: list } as Partial<Draft>);
    setEditing(null);
  };

  /* ---------- target + validation ---------- */
  const target: HrTarget | null = d.tt === "business"
    ? d.biz ? (d.biz.kind === "valuation" ? { type: "business", valuation_id: d.biz.id } : { type: "business", ticker: d.biz.ticker }) : d.bizWeb.trim() && normUrl(d.bizWeb) ? { type: "business", website: normUrl(d.bizWeb) } : null
    : { type: "role", company: d.company.trim(), title: d.title.trim(), description: d.desc.trim(), requirements: [...d.must, ...d.nice.map((x) => "Nice to have: " + x)] };
  const targetName = d.tt === "business" ? d.biz?.name || (d.bizWeb.trim() ? hostOf(normUrl(d.bizWeb) ?? d.bizWeb) : "") : [d.title.trim(), d.company.trim()].filter(Boolean).join(" · ");

  const errs = useMemo(() => {
    const e: Record<string, FieldErr> = {};
    const n = checkName(d.name, true); if (n) e.name = n;
    if (d.role.trim().length > 80) e.role = { k: "hr.e.role" };
    if (d.headline.trim().length > 200) e.headline = { k: "hr.np.e.headline" };
    if (d.year.trim() && (!/^\d{4}$/.test(d.year.trim()) || +d.year < 1950 || +d.year > THIS_YEAR)) e.year = { k: "hr.e.year", v: { y: THIS_YEAR } };
    if (d.equity.trim()) { const p = Number(d.equity.replace(",", ".")); if (!Number.isFinite(p) || p < 0 || p > 100) e.equity = { k: "hr.e.equity" }; }
    d.links.forEach((l, i) => { if (l.trim() && !normUrl(l)) e["link" + i] = { k: "hr.e.url", v: { u: l.trim().slice(0, 48) } }; });
    if (d.bio.length > 1500) e.bio = { k: "hr.e.bio" };
    if (d.cv.length > 20000) e.cv = { k: "hr.np.e.cv" };
    if (d.tt === "business") {
      if (d.bizWeb.trim() && !normUrl(d.bizWeb)) e.bizWeb = { k: "hr.e.website" };
      else if (!d.biz && !d.bizWeb.trim()) e.biz = { k: "hr.np.e.biz" };
    } else {
      if (!d.company.trim()) e.company = { k: "hr.np.e.company" };
      if (!d.title.trim()) e.title = { k: "hr.np.e.title" };
      if (d.desc.length > 5000) e.desc = { k: "hr.np.e.desc" };
    }
    if (!c1) e.c1 = { k: "hr.e.consent" };
    if (!c2) e.c2 = { k: "hr.np.e.use" };
    return e;
  }, [d, c1, c2]);
  const stepOf = (k: string): Step => (STEP_KEYS[1].test(k) ? 1 : STEP_KEYS[2].test(k) ? 2 : 3);
  const stepErrs = (s: Step) => Object.keys(errs).filter((k) => stepOf(k) === s);
  const show = (k: string, val = "") => (errs[k] && (val.trim() || tried.has(stepOf(k)) || touched.has(k)) ? errs[k] : null);
  const stepOk = (s: Step) => stepErrs(s).length === 0;
  const curOk = stepOk(step);
  useEffect(() => { if (curOk && step < 3) setErr(""); }, [curOk, step]);
  const focusFirstBad = () => requestAnimationFrame(() => (panelRef.current?.querySelector("[aria-invalid=true]") as HTMLElement | null)?.focus());
  const goto = (s: Step) => {
    setErr("");
    if (s > step) {
      for (let x = step; x < s; x = (x + 1) as Step) {
        if (!stepOk(x)) { setTried((tr) => new Set(tr).add(x)); set({ step: x }); setErr(t("hr.e.fix", { n: stepErrs(x).length })); focusFirstBad(); return; }
      }
    }
    set({ step: s });
    requestAnimationFrame(() => { panelRef.current?.scrollIntoView({ block: "start", behavior: "smooth" }); (panelRef.current?.querySelector("h2") as HTMLElement | null)?.focus({ preventScroll: true }); });
  };

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (step < 3) { goto((step + 1) as Step); return; }
    setTried(new Set([1, 2, 3])); setErr("");
    const bad = ([1, 2, 3] as Step[]).find((s) => !stepOk(s));
    if (bad) {
      if (bad !== 3) set({ step: bad });
      setErr(t("hr.e.fix", { n: Object.keys(errs).length }));
      focusFirstBad();
      return;
    }
    setBusy(true);
    try {
      if (!me) await tryDemo();
      const urls = [...new Set(d.links.map((l) => (l.trim() ? normUrl(l) : null)).filter((u): u is string => !!u))].slice(0, MAX_LINKS);
      const person = {
        full_name: d.name.trim(), role: d.role.trim(), kind: d.kind, headline: d.headline.trim() || null, full_time: d.ft === "" ? null : d.ft === "yes",
        start_year: d.year.trim() ? +d.year : null, equity_pct: d.equity.trim() ? Number(d.equity.replace(",", ".")) : null, urls, bio: d.bio.trim() || null, cv: d.cv.trim() || null,
      };
      let r = await api.hrCreatePersonReport({ person, target, consent: true, run: true });
      if (r.status === "draft") r = await api.hrRun(r.id);
      try { localStorage.removeItem(DRAFT_KEY); } catch { /* ignore */ }
      nav(`/p/${encodeURIComponent(r.id)}`);
    } catch (x) {
      setErr(x instanceof ApiError && x.status === 429 ? t("hr.new.limit") : errText(x, t));
    } finally {
      setBusy(false);
    }
  };
  const reset = () => { setD({ ...EMPTY }); setC1(false); setC2(false); setTried(new Set()); setTouched(new Set()); setRestored(false); setPaste(""); try { localStorage.removeItem(DRAFT_KEY); } catch { /* ignore */ } };

  const fld = (k: string, label: DictKey, input: React.ReactNode, hint?: React.ReactNode, val = "", req = false) => {
    const e = show(k, val);
    return (
      <div className={"hp-fld" + (e ? " bad" : "")}>
        <label htmlFor={"np-" + k}>{t(label)}{req && <span className="hx-req" aria-hidden="true"> *</span>}</label>
        {input}
        {e ? <FieldError id={"np-" + k + "-e"} err={e} /> : hint ? <span className="hint" id={"np-" + k + "-e"}>{hint}</span> : null}
      </div>
    );
  };
  const aria = (k: string, val = "") => ({ id: "np-" + k, "aria-invalid": !!show(k, val), "aria-describedby": "np-" + k + "-e", onBlur: () => touch(k) });
  const nLinks = d.links.filter((l) => l.trim()).length;
  const STEPS: [Step, DictKey, DictKey][] = [[1, "hr2.np.s1", "hr2.np.s1.p"], [2, "hr2.np.s2", "hr2.np.s2.p"], [3, "hr2.np.s3", "hr2.np.s3.p"]];
  const nextLabel = step === 1 ? t("hr2.np.next2") : step === 2 ? t("hr2.np.next3") : busy ? t("hr.new.starting") : t("hr2.np.start");

  /* ---------- step bodies ---------- */
  const s1 = (
    <>
      <div className="hx-quick">
        <label htmlFor="np-paste"><b>{t("hr2.np.quick")}</b><span>{t("hr2.np.quick.p")}</span></label>
        <textarea id="np-paste" rows={2} value={paste} placeholder={t("hr2.np.quick.ph")} onChange={(e) => setPaste(e.target.value)} spellCheck={false} />
        {paste.trim() && (
          <div className="hx-guess" role="status">
            {anyGuess ? (
              <>
                <span className="lb">{t(guess.from === "linkedin" ? "hr2.np.g.fromli" : guess.from === "url" ? "hr2.np.g.fromurl" : "hr2.np.g.fromtext")}</span>
                <div className="hx-gchips">
                  {canUse.name && <button type="button" onClick={() => set({ name: guess.name!.slice(0, 120) })}><small>{t("hr.p.name")}</small>{guess.name}</button>}
                  {canUse.headline && <button type="button" onClick={() => set({ headline: guess.headline!.slice(0, 200) })}><small>{t("hr.np.headline")}</small>{guess.headline}</button>}
                  {canUse.role && <button type="button" onClick={() => set({ role: guess.role! })}><small>{t("hr.np.role")}</small>{guess.role}</button>}
                  {newUrls.map((u) => <button key={u} type="button" onClick={() => { const l = addUrls([u]); set({ links: l.length ? l : [""] }); }}><small>{t("hr2.np.g.link")}</small>{u.replace(/^https?:\/\/(www\.)?/, "")}</button>)}
                  {canUse.cv && <button type="button" onClick={() => { set({ cv: guess.cv! }); setMore(true); }}><small>{t("hr.np.cv")}</small>{t("hr2.np.g.cv", { n: fmt(guess.cv!.length) })}</button>}
                </div>
                <div className="row"><button className="btn sm" type="button" onClick={useAll}>{t("hr2.np.g.all")}</button><button className="btn ghost sm" type="button" onClick={() => setPaste("")}>{t("hr2.np.g.clear")}</button></div>
                {guess.from === "linkedin" && <p className="hint">{t("hr2.np.g.linote")}</p>}
              </>
            ) : <span className="lb">{t("hr2.np.g.none")}</span>}
          </div>
        )}
      </div>
      <div className="hp-frow">
        {fld("name", "hr.p.name", <input type="text" autoComplete="off" maxLength={140} value={d.name} onChange={(e) => set({ name: e.target.value })} {...aria("name", d.name)} required />, undefined, d.name, true)}
        {fld("role", "hr.np.role", <input type="text" list="np-roles" maxLength={100} value={d.role} placeholder={t("hr.p.role.ph")} onChange={(e) => set({ role: e.target.value })} {...aria("role", d.role)} />, undefined, d.role)}
      </div>
      <datalist id="np-roles">{ROLE_SUGGESTIONS.map((x) => <option key={x} value={x} />)}</datalist>
      <div className="hp-fld">
        <span className="lab" id="np-rel">{t("hr.np.rel")}</span>
        <div className="hp-seg" role="radiogroup" aria-labelledby="np-rel">
          {PERSON_KINDS.map((k) => <label key={k}><input type="radio" name="np-kind" checked={d.kind === k} onChange={() => set({ kind: k })} />{t(("hr.kind." + k) as DictKey)}</label>)}
        </div>
      </div>
      {fld("headline", "hr.np.headline", <input type="text" maxLength={220} value={d.headline} placeholder={t("hr.np.headline.ph")} onChange={(e) => set({ headline: e.target.value })} {...aria("headline", d.headline)} />, undefined, d.headline)}
      <div className="hp-fld">
        <span className="lab">{t("hr.np.links")}</span>
        {d.links.map((l, i) => {
          const e = show("link" + i, l);
          return (
            <div key={i} style={{ display: "grid", gap: 4 }}>
              <div className="hp-linkrow">
                <span className={"ico" + (l.trim() && normUrl(l) ? " on" : "")} aria-hidden="true">{linkIcon(l)}</span>
                <input className={"mono" + (e ? " bad" : "")} type="url" inputMode="url" spellCheck={false} placeholder="https://linkedin.com/in/…" value={l} aria-label={t("hr.np.link", { n: i + 1 })} aria-invalid={!!e} aria-describedby={"np-link" + i + "-e"}
                  onBlur={() => touch("link" + i)} onChange={(ev) => set({ links: d.links.map((x, j) => (j === i ? ev.target.value : x)) })} />
                {d.links.length > 1 ? <button type="button" aria-label={t("hr.p.remove")} onClick={() => set({ links: d.links.filter((_, j) => j !== i) })}>✕</button> : <span />}
              </div>
              {e ? <FieldError id={"np-link" + i + "-e"} err={e} /> : /linkedin\.com/i.test(l) ? <span className="hint" id={"np-link" + i + "-e"}>{t("hr.np.linkedin")}</span> : null}
            </div>
          );
        })}
        <button className="hp-addlink" type="button" disabled={d.links.length >= MAX_LINKS} onClick={() => set({ links: [...d.links, ""] })}>+ {t("hr.np.addlink")}</button>
      </div>
      <details className="hx-more" open={more} onToggle={(e) => setMore((e.target as HTMLDetailsElement).open)}>
        <summary>{t("hr2.np.more")}<span className="muted-sm"> · {t("hr2.np.more.p")}</span></summary>
        <div className="hx-more-body">
          <div className="hp-frow three">
            <div className="hp-fld"><label htmlFor="np-ft">{t("hr.np.works")}</label><select id="np-ft" value={d.ft} onChange={(e) => set({ ft: e.target.value as Draft["ft"] })}><option value="">{t("hr.p.ft.unknown")}</option><option value="yes">{t("hr.r.ft")}</option><option value="no">{t("hr.r.pt")}</option></select></div>
            {fld("year", "hr.p.year", <input type="text" inputMode="numeric" maxLength={4} placeholder={String(THIS_YEAR - 3)} value={d.year} onChange={(e) => set({ year: e.target.value })} {...aria("year", d.year)} />, undefined, d.year)}
            {fld("equity", "hr.np.equity", <input type="text" inputMode="decimal" maxLength={6} placeholder="0–100" value={d.equity} onChange={(e) => set({ equity: e.target.value })} {...aria("equity", d.equity)} />, undefined, d.equity)}
          </div>
          {fld("bio", "hr.p.bio", <textarea rows={3} value={d.bio} placeholder={t("hr.p.bio.ph")} onChange={(e) => set({ bio: e.target.value })} {...aria("bio", d.bio)} />, t("hr.np.bio.hint", { n: fmt(d.bio.length) }), d.bio)}
          {fld("cv", "hr.np.cv", <textarea rows={4} value={d.cv} placeholder={t("hr.np.cv.ph")} onChange={(e) => set({ cv: e.target.value })} {...aria("cv", d.cv)} />, t("hr.np.cv.hint", { n: fmt(d.cv.length) }), d.cv)}
        </div>
      </details>
    </>
  );

  const bizErr = show("biz");
  const s2 = (
    <>
      <div className="hp-targets" role="radiogroup" aria-label={t("hr2.np.s2")}>
        <label className="hp-tcard"><input type="radio" name="np-tgt" checked={d.tt === "business"} onChange={() => set({ tt: "business" })} />
          <span className="tt"><span className="radio" />{t("hr.np.t.business")}</span><span className="kind">{t("hr.pr.fit.business")}</span><p>{t("hr.np.t.business.p")}</p></label>
        <label className="hp-tcard"><input type="radio" name="np-tgt" checked={d.tt === "role"} onChange={() => set({ tt: "role" })} />
          <span className="tt"><span className="radio" />{t("hr.np.t.role")}</span><span className="kind">{t("hr.pr.fit.role")}</span><p>{t("hr.np.t.role.p")}</p></label>
      </div>
      {d.tt === "business" ? (
        <div style={{ display: "grid", gap: 12 }}>
          <div className={"hp-fld" + (bizErr ? " bad" : "")}>
            <label htmlFor="np-bizq">{t("hr.np.biz")}<span className="hx-req" aria-hidden="true"> *</span></label>
            {d.biz ? (
              <div className="hp-combo">
                <BizLogo b={d.biz} />
                <span style={{ minWidth: 0 }}><span className="nm">{d.biz.name}</span>{d.biz.sub && <><br /><span className="sub">{d.biz.sub}</span></>}</span>
                <button type="button" onClick={() => { set({ biz: null }); setBizQ(""); requestAnimationFrame(() => document.getElementById("np-bizq")?.focus()); }}>{t("hr.np.change")}</button>
              </div>
            ) : (
              <div className="hx-combo">
                <input id="np-bizq" type="text" role="combobox" aria-autocomplete="list" aria-expanded={open && matches.length > 0} aria-controls="np-bizlist"
                  aria-activedescendant={open && matches[act] ? "np-opt-" + act : undefined} value={bizQ} placeholder={t("hr.np.biz.ph")} autoComplete="off"
                  aria-invalid={!!bizErr} aria-describedby="np-biz-e"
                  onChange={(e) => { setBizQ(e.target.value); setOpen(true); }} onFocus={() => setOpen(true)} onBlur={() => setTimeout(() => setOpen(false), 150)} onKeyDown={onComboKey} />
                {open && matches.length > 0 && (
                  <ul className="hx-options" id="np-bizlist" role="listbox" aria-label={t("hr.np.biz")}>
                    {matches.map((o, i) => (
                      <li key={o.kind + o.id} id={"np-opt-" + i} role="option" aria-selected={i === act} className={(i === act ? "act" : "") + (i === 0 || matches[i - 1].kind !== o.kind ? " first" : "")}
                        data-group={i === 0 || matches[i - 1].kind !== o.kind ? t(o.kind === "valuation" ? "hr2.np.biz.mine" : "hr2.np.biz.listed") : undefined}
                        onMouseDown={(e) => { e.preventDefault(); pick(o); }} onMouseEnter={() => setAct(i)}>
                        <BizLogo b={o} />
                        <span className="tx"><b>{o.name}</b><small>{o.sub}</small></span>
                        {o.kind === "valuation" && <span className="pill">{t("hr.np.biz.val")}</span>}
                      </li>
                    ))}
                  </ul>
                )}
                {bizQ.trim() && !matches.length && <span className="hint">{t("hr.np.biz.none")}</span>}
                {bizErr ? <FieldError id="np-biz-e" err={bizErr} /> : <span className="hint" id="np-biz-e">{t("hr2.np.biz.hint", { n: fmt(options.length) })}</span>}
              </div>
            )}
          </div>
          {!d.biz && fld("bizWeb", "hr.np.biz.web", <input className="mono" type="url" inputMode="url" spellCheck={false} placeholder="company.com.au" value={d.bizWeb} onChange={(e) => set({ bizWeb: e.target.value })} {...aria("bizWeb", d.bizWeb)} />, t("hr.np.biz.web.hint"), d.bizWeb)}
        </div>
      ) : (
        <div style={{ display: "grid", gap: 14 }}>
          <div className="hp-frow">
            {fld("company", "hr.np.company", <input type="text" maxLength={160} value={d.company} placeholder={t("hr.np.company.ph")} onChange={(e) => set({ company: e.target.value })} {...aria("company", d.company)} />, undefined, d.company, true)}
            {fld("title", "hr.np.title", <input type="text" maxLength={160} value={d.title} placeholder={t("hr.np.title.ph")} onChange={(e) => set({ title: e.target.value })} {...aria("title", d.title)} />, undefined, d.title, true)}
          </div>
          {fld("desc", "hr.np.desc", <textarea rows={5} value={d.desc} placeholder={t("hr.np.desc.ph")} onChange={(e) => set({ desc: e.target.value })} {...aria("desc", d.desc)} />, t("hr.np.desc.hint", { n: fmt(d.desc.length) }), d.desc)}
          {suggestions.length > 0 && !full && (
            <div className="hx-sugg" aria-live="polite">
              <div className="gh"><span>{Icon.up}{t("hr2.np.sugg")}</span><button type="button" className="linkbtn" onClick={addAllSuggested}>{t("hr2.np.sugg.all")}</button></div>
              <div className="hp-chips">{suggestions.map((s) => <button key={s} type="button" className="hx-schip" onClick={() => addReq(s)}><span aria-hidden="true">+</span> {s}</button>)}</div>
            </div>
          )}
          {([["must", d.must, MAX_MUST, "hr.pr.req.must"], ["nice", d.nice, MAX_NICE, "hr.pr.req.nice"]] as const).map(([g, list, max, lk]) => (
            <div className="hp-reqgroup" key={g}>
              <div className="gh">{t(lk)} <span>{t("hr.np.req.count", { n: list.length, m: max })}</span></div>
              <div className="hp-chips">
                {list.length === 0 && <span className="muted-sm">{t("hr.np.req.empty")}</span>}
                {list.map((r, i) => editing && editing.g === g && editing.i === i ? (
                  <input key={g + i} className="hx-chipedit" autoFocus value={editing.v} maxLength={200} aria-label={t("hr2.np.req.edit")}
                    onChange={(e) => setEditing({ ...editing, v: e.target.value })} onBlur={saveEdit}
                    onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); saveEdit(); } else if (e.key === "Escape") setEditing(null); }} />
                ) : (
                  <span key={g + r} className={"hp-rchip" + (g === "must" ? " must" : "")}>
                    <button type="button" className="txt" title={t("hr2.np.req.edit")} onClick={() => setEditing({ g, i, v: r })}>{r}</button>
                    {g === "must"
                      ? <button type="button" aria-label={t("hr.np.req.down")} disabled={d.nice.length >= MAX_NICE} onClick={() => set({ must: d.must.filter((x) => x !== r), nice: [...d.nice, r] })}>↓</button>
                      : <button type="button" aria-label={t("hr.np.req.up")} disabled={d.must.length >= MAX_MUST} onClick={() => set({ nice: d.nice.filter((x) => x !== r), must: [...d.must, r] })}>↑</button>}
                    <button type="button" aria-label={t("hr.p.remove")} onClick={() => set({ [g]: list.filter((x) => x !== r) } as Partial<Draft>)}>✕</button>
                  </span>
                ))}
              </div>
            </div>
          ))}
          <div className="hp-addreq">
            <input type="text" maxLength={200} value={reqIn} placeholder={full ? t("hr.np.req.full") : t("hr.np.req.ph")} aria-label={t("hr.np.req.add")} disabled={full}
              onChange={(e) => setReqIn(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); if (addReq(reqIn)) setReqIn(""); } }} />
            <button className="btn ghost sm" type="button" disabled={full || !reqIn.trim()} onClick={() => { if (addReq(reqIn)) setReqIn(""); }}>{t("hr.np.req.add")}</button>
          </div>
        </div>
      )}
    </>
  );

  const s3 = (
    <>
      <dl className="hx-review">
        <div><dt>{t("hr.np.sum.person")}</dt><dd>{d.name.trim() || "–"}{d.role.trim() ? " · " + d.role.trim() : ""} · {t(("hr.kind." + d.kind) as DictKey)}</dd><button type="button" className="linkbtn" onClick={() => goto(1)}>{t("hr2.np.edit")}</button></div>
        <div><dt>{t("hr.np.links")}</dt><dd>{nLinks ? d.links.filter((l) => l.trim()).map((l) => hostOf(normUrl(l) ?? l)).join(", ") : t("hr2.np.nolinks")}</dd><button type="button" className="linkbtn" onClick={() => goto(1)}>{t("hr2.np.edit")}</button></div>
        <div><dt>{t("hr2.np.s2")}</dt><dd>{targetName || "–"}{d.tt === "role" ? " · " + t("hr.np.sum.reqs", { m: d.must.length, n: d.nice.length }) : ""}</dd><button type="button" className="linkbtn" onClick={() => goto(2)}>{t("hr2.np.edit")}</button></div>
      </dl>
      {nLinks === 0 && !d.cv.trim() && <p className="hx-tip">{Icon.conf}<span>{t("hr2.np.tip.nolinks")}</span></p>}
      <div style={{ display: "grid", gap: 10 }}>
        <label className={"hp-chk" + (show("c1") ? " bad" : "")}><input type="checkbox" checked={c1} onChange={(e) => setC1(e.target.checked)} aria-invalid={!!show("c1")} /><span>{t("hr.np.c1", { n: d.name.trim() || t("hr.np.theperson") })}<small>{t("hr.np.c1.sub")}</small></span></label>
        <label className={"hp-chk" + (show("c2") ? " bad" : "")}><input type="checkbox" checked={c2} onChange={(e) => setC2(e.target.checked)} aria-invalid={!!show("c2")} /><span>{t("hr.np.c2", { n: targetName || t("hr.np.thistarget") })}</span></label>
      </div>
      <p className="hp-never"><b>{t("hr.np.never.b")}</b> {t("hr.np.never")}</p>
      <p className="hint" style={{ margin: 0 }}>{t("hr.np.fine")}{!me ? " " + t("hr.new.signin") : ""}</p>
    </>
  );

  return (
    <div className="wrap hp-page hx-wizpage">
      <header className="shead">
        <div><span className="eyebrow">{t("hr.np.eyebrow")}</span><h1>{t("hr.np.h1")}</h1><p>{t("hr2.np.lead")}</p></div>
      </header>
      {restored && (
        <p className="hx-restored" role="status">{t("hr2.np.restored")} <button type="button" className="linkbtn" onClick={reset}>{t("hr2.np.startover")}</button></p>
      )}
      <ol className="hx-steps" aria-label={t("hr2.np.progress")}>
        {STEPS.map(([s, lk]) => {
          const done = s < step && stepOk(s);
          return (
            <li key={s} className={(s === step ? "cur" : "") + (done ? " done" : "") + (tried.has(s) && !stepOk(s) && s !== step ? " bad" : "")}>
              <button type="button" onClick={() => goto(s)} aria-current={s === step ? "step" : undefined}>
                <span className="n" aria-hidden="true">{done ? Icon.met : s}</span>
                <span className="lb"><small>{t("hr2.np.stepn", { n: s })}</small>{t(lk)}</span>
              </button>
            </li>
          );
        })}
      </ol>
      <form className="hx-wiz" onSubmit={submit} noValidate aria-label={t("hr.np.h1")}>
        <div className="hx-wizpanel" ref={panelRef}>
          <header className="hx-stephead">
            <h2 tabIndex={-1}>{t(STEPS[step - 1][1])}</h2>
            <p>{t(STEPS[step - 1][2])}</p>
          </header>
          <div className="hx-stepbody">{step === 1 ? s1 : step === 2 ? s2 : s3}</div>
          <footer className="hx-stepfoot">
            {err && <p className="hx-err" role="alert">{Icon.conf}<span>{err}</span></p>}
            <div className="hx-stepbtns">
              {step > 1 ? <button className="btn ghost" type="button" onClick={() => goto((step - 1) as Step)}>← {t("hr2.np.back")}</button> : <Link className="btn ghost" to="/">{t("hr2.np.cancel")}</Link>}
              <button className="btn hx-next" type="submit" disabled={busy || (step === 3 && (!c1 || !c2))} aria-busy={busy}>
                {busy ? <span className="spinner" aria-hidden="true" /> : null}{nextLabel}{step < 3 && <span aria-hidden="true"> →</span>}
              </button>
            </div>
            {step === 3 && (!c1 || !c2) && <p className="hx-gate">{Icon.lock}<span>{t("hr.np.gate")}</span></p>}
          </footer>
        </div>

        <aside className="hx-preview" aria-label={t("hr2.np.preview")}>
          <div className="hx-pvcard">
            <div className="hx-pvtop">
              <span className="eyebrow">{t("hr2.np.preview")}</span>
              <span className="hx-pvav" aria-hidden="true">{d.name.trim() ? initials(d.name) : "?"}</span>
              <b className={"hx-pvname" + (d.name.trim() ? "" : " ph")}>{d.name.trim() || t("hr2.np.pv.name")}</b>
              <span className="hx-pvhl">{d.headline.trim() || (d.role.trim() ? d.role.trim() : t("hr2.np.pv.headline"))}</span>
              <span className="hx-pvtags"><span>{t(("hr.kind." + d.kind) as DictKey)}</span>{d.role.trim() && d.headline.trim() && <span>{d.role.trim()}</span>}</span>
            </div>
            <div className="hx-pvbody">
              <div className="hx-pvrow">
                <small>{t("hr.np.links")}</small>
                {nLinks ? <span className="hx-pvlinks">{d.links.filter((l) => l.trim()).map((l, i) => <span key={i} className={normUrl(l) ? "" : "bad"} title={l}>{linkIcon(l)}</span>)}</span> : <span className="muted-sm">{t("hr2.np.nolinks")}</span>}
              </div>
              <div className="hx-pvrow">
                <small>{t("hr2.np.s2")}</small>
                {targetName ? (
                  <span className="hx-pvtgt">{d.tt === "business" && <BizLogo b={d.biz ?? { name: targetName }} />}<b>{targetName}</b></span>
                ) : <span className="muted-sm">{t("hr2.np.pv.target")}</span>}
                {d.tt === "role" && (d.must.length + d.nice.length > 0) && <span className="muted-sm">{t("hr.np.sum.reqs", { m: d.must.length, n: d.nice.length })}</span>}
              </div>
              <ul className="hx-pvcheck">
                <li className={d.name.trim() && !errs.name ? "ok" : ""}>{d.name.trim() && !errs.name ? Icon.met : <i />}{t("hr2.np.chk.name")}</li>
                <li className={nLinks > 0 ? "ok" : ""}>{nLinks > 0 ? Icon.met : <i />}{t("hr2.np.chk.links")}</li>
                <li className={stepOk(2) ? "ok" : ""}>{stepOk(2) ? Icon.met : <i />}{t("hr2.np.chk.target")}</li>
                <li className={c1 && c2 ? "ok" : ""}>{c1 && c2 ? Icon.met : <i />}{t("hr2.np.chk.consent")}</li>
              </ul>
              <p className="hx-pvfoot">{t("hr2.np.pv.foot")}</p>
            </div>
          </div>
        </aside>
      </form>
    </div>
  );
}
