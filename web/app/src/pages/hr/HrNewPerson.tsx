/* /new/person — "Analyse a person": 4 numbered sections + a sticky summary card (bottom bar on mobile).
   Maps to POST /v1/hr/people-reports {person: PersonIn, target, consent, run}. */
import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useI18n } from "../../i18n";
import type { DictKey } from "../../dict";
import { errText, useAuth } from "../../auth";
import { api, ApiError, PERSON_KINDS, type HrTarget, type PersonKind } from "../../api";
import { useAsync } from "../../lib/hooks";
import { checkName, normUrl, THIS_YEAR, type FieldErr } from "../../lib/people";
import { FieldError } from "../../components/PeopleEditor";
import { ROLE_SUGGESTIONS } from "../../components/PeopleEditor";
import { Icon } from "./evidence";
import { hostOf, useHrTitle } from "./common";

const MAX_MUST = 5, MAX_NICE = 4, MAX_LINKS = 6;
type Biz = { kind: "valuation" | "listed"; id: string; name: string; sub: string; ticker?: string };

function linkIcon(u: string): string {
  if (/linkedin\.com/i.test(u)) return "in";
  if (/github\.com|gitlab\.com/i.test(u)) return "GIT";
  if (/scholar\.google/i.test(u)) return "SCH";
  return "WEB";
}

export function HrNewPerson() {
  const { t, fmt } = useI18n();
  const { me, tryDemo } = useAuth();
  const nav = useNavigate();
  const [params] = useSearchParams();
  useHrTitle(t("hr.np.h1"));

  // 1 person
  const [name, setName] = useState(() => (params.get("name") ?? "").slice(0, 120));
  const [role, setRole] = useState("");
  const [kind, setKind] = useState<PersonKind>("founder");
  const [headline, setHeadline] = useState("");
  const [ft, setFt] = useState<"" | "yes" | "no">("");
  const [year, setYear] = useState("");
  const [equity, setEquity] = useState("");
  const [links, setLinks] = useState<string[]>([""]);
  const [bio, setBio] = useState("");
  const [cv, setCv] = useState("");
  // 2 target
  const [tt, setTt] = useState<"business" | "role">(() => (params.get("target") === "role" ? "role" : "business"));
  const [biz, setBiz] = useState<Biz | null>(null);
  const [bizQ, setBizQ] = useState("");
  const [bizWeb, setBizWeb] = useState("");
  const [company, setCompany] = useState("");
  const [title, setTitle] = useState("");
  const [desc, setDesc] = useState("");
  // 3 requirements
  const [must, setMust] = useState<string[]>([]);
  const [nice, setNice] = useState<string[]>([]);
  const [reqIn, setReqIn] = useState("");
  // 4 consent
  const [c1, setC1] = useState(false);
  const [c2, setC2] = useState(false);
  const [tried, setTried] = useState(false);
  const [touched, setTouched] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const formRef = useRef<HTMLFormElement>(null);
  const touch = (k: string) => setTouched((s) => new Set(s).add(k));

  // businesses to pick from: my valuations + listed businesses
  const vals = useAsync(() => (me ? api.myValuations() : Promise.resolve([])), [me?.address, me?.username]);
  const cos = useAsync(() => api.companies(), []);
  const options: Biz[] = useMemo(() => {
    const v = (vals.data ?? []).map((x) => ({ kind: "valuation" as const, id: x.id, name: (typeof x.profile?.name === "string" && x.profile.name) || hostOf(x.url), sub: hostOf(x.url) + " · " + t(("v.st." + x.status) as DictKey) }));
    const c = (cos.data ?? []).map((x) => ({ kind: "listed" as const, id: x.ticker, ticker: x.ticker, name: x.name, sub: (x.website ? hostOf(x.website) + " · " : "") + (x.grade ? t("ad.c.grade") + " " + x.grade : "") }));
    return [...v, ...c];
  }, [vals.data, cos.data, t]);
  useEffect(() => {
    const vid = params.get("valuation");
    if (!vid || biz) return;
    const o = options.find((x) => x.kind === "valuation" && x.id === vid);
    setBiz(o ?? { kind: "valuation", id: vid, name: vid, sub: "" });
  }, [options]); // eslint-disable-line react-hooks/exhaustive-deps
  const matches = bizQ.trim() ? options.filter((o) => (o.name + " " + o.sub + " " + (o.ticker ?? "")).toLowerCase().includes(bizQ.trim().toLowerCase())).slice(0, 8) : [];

  const target: HrTarget | null = tt === "business"
    ? biz ? (biz.kind === "valuation" ? { type: "business", valuation_id: biz.id } : { type: "business", ticker: biz.ticker }) : bizWeb.trim() && normUrl(bizWeb) ? { type: "business", website: normUrl(bizWeb) } : null
    : { type: "role", company: company.trim(), title: title.trim(), description: desc.trim(), requirements: [...must, ...nice.map((x) => "Nice to have: " + x)] };
  const targetName = tt === "business" ? biz?.name || (bizWeb.trim() ? hostOf(normUrl(bizWeb) ?? bizWeb) : "") : [title.trim(), company.trim()].filter(Boolean).join(" · ");

  const errs = useMemo(() => {
    const e: Record<string, FieldErr> = {};
    const n = checkName(name, true); if (n) e.name = n;
    if (role.trim().length > 80) e.role = { k: "hr.e.role" };
    if (headline.trim().length > 200) e.headline = { k: "hr.np.e.headline" };
    if (year.trim() && (!/^\d{4}$/.test(year.trim()) || +year < 1950 || +year > THIS_YEAR)) e.year = { k: "hr.e.year", v: { y: THIS_YEAR } };
    if (equity.trim()) { const p = Number(equity.replace(",", ".")); if (!Number.isFinite(p) || p < 0 || p > 100) e.equity = { k: "hr.e.equity" }; }
    links.forEach((l, i) => { if (l.trim() && !normUrl(l)) e["link" + i] = { k: "hr.e.url", v: { u: l.trim().slice(0, 48) } }; });
    if (bio.length > 1500) e.bio = { k: "hr.e.bio" };
    if (cv.length > 20000) e.cv = { k: "hr.np.e.cv" };
    if (tt === "business") {
      if (bizWeb.trim() && !normUrl(bizWeb)) e.bizWeb = { k: "hr.e.website" };
      else if (!biz && !bizWeb.trim()) e.biz = { k: "hr.np.e.biz" };
    } else {
      if (!company.trim()) e.company = { k: "hr.np.e.company" };
      if (!title.trim()) e.title = { k: "hr.np.e.title" };
      if (desc.length > 5000) e.desc = { k: "hr.np.e.desc" };
    }
    if (!c1) e.c1 = { k: "hr.e.consent" };
    if (!c2) e.c2 = { k: "hr.np.e.use" };
    return e;
  }, [name, role, headline, year, equity, links, bio, cv, tt, biz, bizWeb, company, title, desc, c1, c2]);
  const show = (k: string, val = "") => (errs[k] && (val.trim() || tried || touched.has(k)) ? errs[k] : null);

  const addReq = () => {
    const r = reqIn.trim().slice(0, 200);
    if (!r) return;
    if (must.length < MAX_MUST && !must.includes(r)) setMust((m) => [...m, r]);
    else if (nice.length < MAX_NICE && !nice.includes(r) && !must.includes(r)) setNice((m) => [...m, r]);
    else return;
    setReqIn("");
  };
  const full = must.length >= MAX_MUST && nice.length >= MAX_NICE;

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setTried(true); setErr("");
    const n = Object.keys(errs).length;
    if (n) {
      setErr(t("hr.e.fix", { n }));
      requestAnimationFrame(() => (formRef.current?.querySelector("[aria-invalid=true]") as HTMLElement | null)?.focus());
      return;
    }
    setBusy(true);
    try {
      if (!me) await tryDemo();
      const urls = [...new Set(links.map((l) => (l.trim() ? normUrl(l) : null)).filter((u): u is string => !!u))].slice(0, MAX_LINKS);
      const person = {
        full_name: name.trim(), role: role.trim(), kind, headline: headline.trim() || null, full_time: ft === "" ? null : ft === "yes",
        start_year: year.trim() ? +year : null, equity_pct: equity.trim() ? Number(equity.replace(",", ".")) : null, urls, bio: bio.trim() || null, cv: cv.trim() || null,
      };
      let r = await api.hrCreatePersonReport({ person, target, consent: true, run: true });
      if (r.status === "draft") r = await api.hrRun(r.id);
      nav(`/p/${encodeURIComponent(r.id)}`);
    } catch (x) {
      setErr(x instanceof ApiError && x.status === 429 ? t("hr.new.limit") : errText(x, t));
    } finally {
      setBusy(false);
    }
  };

  const fld = (k: string, label: DictKey, input: React.ReactNode, hint?: React.ReactNode, val = "") => {
    const e = show(k, val);
    return (
      <div className={"hp-fld" + (e ? " bad" : "")}>
        <label htmlFor={"np-" + k}>{t(label)}</label>
        {input}
        {e ? <FieldError id={"np-" + k + "-e"} err={e} /> : hint ? <span className="hint" id={"np-" + k + "-e"}>{hint}</span> : null}
      </div>
    );
  };
  const aria = (k: string, val = "") => ({ id: "np-" + k, "aria-invalid": !!show(k, val), "aria-describedby": "np-" + k + "-e", onBlur: () => touch(k) });
  const gate = !c1 || !c2 ? t("hr.np.gate") : Object.keys(errs).length ? t("hr.e.fix", { n: Object.keys(errs).length }) : "";
  const nLinks = links.filter((l) => l.trim()).length;

  return (
    <div className="wrap hp-page">
      <header className="shead">
        <div><span className="eyebrow">{t("hr.np.eyebrow")}</span><h1>{t("hr.np.h1")}</h1><p>{t("hr.np.p")}</p></div>
      </header>
      <form ref={formRef} className="hp-formgrid" onSubmit={submit} noValidate aria-label={t("hr.np.h1")}>
        <div className="hp-fpanel">
          {/* 1 */}
          <section className="hp-fsec" aria-labelledby="f1">
            <header><b>1</b><div><h2 id="f1">{t("hr.np.s1")}</h2><p>{t("hr.np.s1.p")}</p></div></header>
            <div className="hp-frow">
              {fld("name", "hr.p.name", <input type="text" autoComplete="off" maxLength={140} value={name} onChange={(e) => setName(e.target.value)} {...aria("name", name)} required />, undefined, name)}
              {fld("role", "hr.np.role", <input type="text" list="np-roles" maxLength={100} value={role} placeholder={t("hr.p.role.ph")} onChange={(e) => setRole(e.target.value)} {...aria("role", role)} />, undefined, role)}
            </div>
            <datalist id="np-roles">{ROLE_SUGGESTIONS.map((x) => <option key={x} value={x} />)}</datalist>
            <div className="hp-fld">
              <span className="lab" id="np-rel">{t("hr.np.rel")}</span>
              <div className="hp-seg" role="radiogroup" aria-labelledby="np-rel">
                {PERSON_KINDS.map((k) => <label key={k}><input type="radio" name="np-kind" checked={kind === k} onChange={() => setKind(k)} />{t(("hr.kind." + k) as DictKey)}</label>)}
              </div>
            </div>
            {fld("headline", "hr.np.headline", <input type="text" maxLength={220} value={headline} placeholder={t("hr.np.headline.ph")} onChange={(e) => setHeadline(e.target.value)} {...aria("headline", headline)} />, undefined, headline)}
            <div className="hp-frow three">
              <div className="hp-fld"><label htmlFor="np-ft">{t("hr.np.works")}</label><select id="np-ft" value={ft} onChange={(e) => setFt(e.target.value as "" | "yes" | "no")}><option value="">{t("hr.p.ft.unknown")}</option><option value="yes">{t("hr.r.ft")}</option><option value="no">{t("hr.r.pt")}</option></select></div>
              {fld("year", "hr.p.year", <input type="text" inputMode="numeric" maxLength={4} placeholder={String(THIS_YEAR - 3)} value={year} onChange={(e) => setYear(e.target.value)} {...aria("year", year)} />, undefined, year)}
              {fld("equity", "hr.np.equity", <input type="text" inputMode="decimal" maxLength={6} placeholder="0–100" value={equity} onChange={(e) => setEquity(e.target.value)} {...aria("equity", equity)} />, undefined, equity)}
            </div>
            <div className="hp-fld">
              <span className="lab">{t("hr.np.links")}</span>
              {links.map((l, i) => {
                const e = show("link" + i, l);
                return (
                  <div key={i} style={{ display: "grid", gap: 4 }}>
                    <div className="hp-linkrow">
                      <span className="ico" aria-hidden="true">{linkIcon(l)}</span>
                      <input className={"mono" + (e ? " bad" : "")} type="url" inputMode="url" spellCheck={false} placeholder="https://" value={l} aria-label={t("hr.np.link", { n: i + 1 })} aria-invalid={!!e} aria-describedby={"np-link" + i + "-e"}
                        onChange={(ev) => setLinks((ls) => ls.map((x, j) => (j === i ? ev.target.value : x)))} />
                      {links.length > 1 ? <button type="button" aria-label={t("hr.p.remove")} onClick={() => setLinks((ls) => ls.filter((_, j) => j !== i))}>✕</button> : <span />}
                    </div>
                    {e ? <FieldError id={"np-link" + i + "-e"} err={e} /> : /linkedin\.com/i.test(l) ? <span className="hint" id={"np-link" + i + "-e"}>{t("hr.np.linkedin")}</span> : null}
                  </div>
                );
              })}
              <button className="hp-addlink" type="button" disabled={links.length >= MAX_LINKS} onClick={() => setLinks((ls) => [...ls, ""])}>+ {t("hr.np.addlink")}</button>
            </div>
            {fld("bio", "hr.p.bio", <textarea rows={3} value={bio} placeholder={t("hr.p.bio.ph")} onChange={(e) => setBio(e.target.value)} {...aria("bio", bio)} />, t("hr.np.bio.hint", { n: fmt(bio.length) }), bio)}
            {fld("cv", "hr.np.cv", <textarea rows={4} value={cv} placeholder={t("hr.np.cv.ph")} onChange={(e) => setCv(e.target.value)} {...aria("cv", cv)} />, t("hr.np.cv.hint", { n: fmt(cv.length) }), cv)}
          </section>

          {/* 2 */}
          <section className="hp-fsec" aria-labelledby="f2">
            <header><b>2</b><div><h2 id="f2">{t("hr.np.s2")}</h2><p>{t("hr.np.s2.p")}</p></div></header>
            <div className="hp-targets" role="radiogroup" aria-labelledby="f2">
              <label className="hp-tcard"><input type="radio" name="np-tgt" checked={tt === "business"} onChange={() => setTt("business")} />
                <span className="tt"><span className="radio" />{t("hr.np.t.business")}</span><span className="kind">{t("hr.pr.fit.business")}</span><p>{t("hr.np.t.business.p")}</p></label>
              <label className="hp-tcard"><input type="radio" name="np-tgt" checked={tt === "role"} onChange={() => setTt("role")} />
                <span className="tt"><span className="radio" />{t("hr.np.t.role")}</span><span className="kind">{t("hr.pr.fit.role")}</span><p>{t("hr.np.t.role.p")}</p></label>
            </div>
            {tt === "business" ? (
              <div style={{ display: "grid", gap: 12 }}>
                <div className={"hp-fld" + (show("biz") ? " bad" : "")}>
                  <label htmlFor="np-bizq">{t("hr.np.biz")}</label>
                  {biz ? (
                    <div className="hp-combo">
                      {biz.ticker && <span className="hp-tick">{biz.ticker}</span>}
                      <span style={{ minWidth: 0 }}><span className="nm">{biz.name}</span>{biz.sub && <><br /><span className="sub">{biz.sub}</span></>}</span>
                      <button type="button" onClick={() => { setBiz(null); setBizQ(""); }}>{t("hr.np.change")}</button>
                    </div>
                  ) : (
                    <>
                      <input id="np-bizq" type="text" value={bizQ} placeholder={t("hr.np.biz.ph")} onChange={(e) => setBizQ(e.target.value)} autoComplete="off" aria-invalid={!!show("biz")} aria-describedby="np-biz-e" />
                      {matches.length > 0 && (
                        <ul className="hp-results" role="listbox" aria-label={t("hr.np.biz")}>
                          {matches.map((o) => (
                            <li key={o.kind + o.id}><button type="button" role="option" aria-selected={false} onClick={() => { setBiz(o); setBizQ(""); setBizWeb(""); }}>
                              {o.ticker ? <span className="hp-tick">{o.ticker}</span> : <span className="pill">{t("hr.np.biz.val")}</span>}<span><b>{o.name}</b> <span className="muted-sm">{o.sub}</span></span>
                            </button></li>
                          ))}
                        </ul>
                      )}
                      {bizQ.trim() && !matches.length && <span className="hint">{t("hr.np.biz.none")}</span>}
                      {show("biz") && <FieldError id="np-biz-e" err={show("biz")} />}
                    </>
                  )}
                </div>
                {!biz && fld("bizWeb", "hr.np.biz.web", <input className="mono" type="url" inputMode="url" spellCheck={false} placeholder="company.com.au" value={bizWeb} onChange={(e) => setBizWeb(e.target.value)} {...aria("bizWeb", bizWeb)} />, t("hr.np.biz.web.hint"), bizWeb)}
              </div>
            ) : (
              <div style={{ display: "grid", gap: 12 }}>
                <div className="hp-frow">
                  {fld("company", "hr.np.company", <input type="text" maxLength={160} value={company} placeholder={t("hr.np.company.ph")} onChange={(e) => setCompany(e.target.value)} {...aria("company", company)} />, undefined, company)}
                  {fld("title", "hr.np.title", <input type="text" maxLength={160} value={title} placeholder={t("hr.np.title.ph")} onChange={(e) => setTitle(e.target.value)} {...aria("title", title)} />, undefined, title)}
                </div>
                {fld("desc", "hr.np.desc", <textarea rows={4} value={desc} placeholder={t("hr.np.desc.ph")} onChange={(e) => setDesc(e.target.value)} {...aria("desc", desc)} />, t("hr.np.desc.hint", { n: fmt(desc.length) }), desc)}
              </div>
            )}
          </section>

          {/* 3 */}
          <section className="hp-fsec" aria-labelledby="f3">
            <header><b>3</b><div><h2 id="f3">{t("hr.np.s3")}</h2><p>{t(tt === "role" ? "hr.np.s3.p" : "hr.np.s3.biz")}</p></div></header>
            {tt === "role" && (
              <>
                {([["must", must, setMust, MAX_MUST, "hr.pr.req.must"], ["nice", nice, setNice, MAX_NICE, "hr.pr.req.nice"]] as const).map(([g, list, set, max, lk]) => (
                  <div className="hp-reqgroup" key={g}>
                    <div className="gh">{t(lk)} <span>{t("hr.np.req.count", { n: list.length, m: max })}</span></div>
                    <div className="hp-chips">
                      {list.length === 0 && <span className="muted-sm">{t("hr.np.req.empty")}</span>}
                      {list.map((r) => (
                        <span key={r} className={"hp-rchip" + (g === "must" ? " must" : "")}>
                          <span className="txt" title={r}>{r}</span>
                          {g === "must"
                            ? <button type="button" aria-label={t("hr.np.req.down")} disabled={nice.length >= MAX_NICE} onClick={() => { setMust((m) => m.filter((x) => x !== r)); setNice((n) => [...n, r]); }}>↓</button>
                            : <button type="button" aria-label={t("hr.np.req.up")} disabled={must.length >= MAX_MUST} onClick={() => { setNice((m) => m.filter((x) => x !== r)); setMust((n) => [...n, r]); }}>↑</button>}
                          <button type="button" aria-label={t("hr.p.remove")} onClick={() => set((m: string[]) => m.filter((x) => x !== r))}>✕</button>
                        </span>
                      ))}
                    </div>
                  </div>
                ))}
                <div className="hp-addreq">
                  <input type="text" maxLength={200} value={reqIn} placeholder={full ? t("hr.np.req.full") : t("hr.np.req.ph")} aria-label={t("hr.np.req.add")} disabled={full}
                    onChange={(e) => setReqIn(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); addReq(); } }} />
                  <button className="btn ghost sm" type="button" disabled={full || !reqIn.trim()} onClick={addReq}>{t("hr.np.req.add")}</button>
                </div>
              </>
            )}
          </section>

          {/* 4 */}
          <section className="hp-fsec" aria-labelledby="f4">
            <header><b>4</b><div><h2 id="f4">{t("hr.np.s4")}</h2><p>{t("hr.np.s4.p")}</p></div></header>
            <div style={{ display: "grid", gap: 10 }}>
              <label className={"hp-chk" + (show("c1") ? " bad" : "")}><input type="checkbox" checked={c1} onChange={(e) => setC1(e.target.checked)} aria-invalid={!!show("c1")} /><span>{t("hr.np.c1", { n: name.trim() || t("hr.np.theperson") })}<small>{t("hr.np.c1.sub")}</small></span></label>
              <label className={"hp-chk" + (show("c2") ? " bad" : "")}><input type="checkbox" checked={c2} onChange={(e) => setC2(e.target.checked)} aria-invalid={!!show("c2")} /><span>{t("hr.np.c2", { n: targetName || t("hr.np.thistarget") })}</span></label>
            </div>
            <p className="hp-never"><b>{t("hr.np.never.b")}</b> {t("hr.np.never")}</p>
          </section>
        </div>

        <aside className="hp-sumcard" aria-label={t("hr.np.sum")}>
          <h2>{t("hr.np.sum")}</h2>
          <p className="mini"><b>{name.trim() || "–"}</b>{targetName ? " · " + targetName : ""}{tt === "role" ? " · " + t("hr.np.req.n", { n: must.length + nice.length }) : ""}</p>
          <dl>
            <dt>{t("hr.np.sum.person")}</dt><dd>{name.trim() ? `${name.trim()} · ${t(("hr.kind." + kind) as DictKey)}` : "–"}</dd>
            <dt>{t("hr.np.s2")}</dt><dd>{targetName || "–"}</dd>
            {tt === "role" && <><dt>{t("hr.np.s3")}</dt><dd>{t("hr.np.sum.reqs", { m: must.length, n: nice.length })}</dd></>}
            <dt>{t("hr.np.links")}</dt><dd>{fmt(nLinks)}</dd>
            <dt>{t("hr.np.sum.search")}</dt><dd>{t("hr.np.sum.search.v")}</dd>
            <dt>{t("hr.np.sum.time")}</dt><dd>{t("hr.np.sum.time.v")}</dd>
          </dl>
          {gate && <p className="gate" id="np-gate" role={tried ? "alert" : undefined}>{Icon.lock}<span>{tried && err ? err : gate}</span></p>}
          {!gate && err && <p className="gate" role="alert">{Icon.conf}<span>{err}</span></p>}
          <button className="btn" type="submit" disabled={busy || !c1 || !c2} aria-busy={busy} aria-describedby="np-gate">{busy ? <span className="spinner" aria-hidden="true" /> : null}{busy ? t("hr.new.starting") : t("hr.new.submit")}</button>
          <p className="fine">{t("hr.np.fine")}{!me ? " " + t("hr.new.signin") : ""}</p>
        </aside>
      </form>
    </div>
  );
}
