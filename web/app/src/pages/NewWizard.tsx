import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { useI18n } from "../i18n";
import { errText, useAuth } from "../auth";
import { api, ApiError, type HrSuggestedPerson, type HrSuggestions, type SelfReported } from "../api";
import { Crumbs, FlowRail, Pager, SideLayout, StepHead } from "../components/Shell";
import { useAsync, useTitle } from "../lib/hooks";
import { en, type DictKey } from "../dict";
import { cleanInput, parseSelfReported, SR_FIELDS, type SrField } from "../lib/selfReported";
import { checkUrlClient } from "../lib/urlcheck";
import { ConsentBox, PeopleEditor } from "../components/PeopleEditor";
import "../components/teamlink.css";
import { emptyRow, MAX_PEOPLE, rowUsed, toPersonIn, validateRows, type PersonRow } from "../lib/people";
import { ContinueCard, watchJob } from "../components/ActiveJobs";
import { StartInputs, useStartV5 } from "./valuation5/Inputs";
import { api5 } from "../components/v5/api5";

/** Unfinished /start form, kept in this browser (website, founder figures, team rows; never the consent tick). */
const START_DRAFT = "blockid-start-draft-v1";
interface StartDraft { url: string; raw: Partial<Record<keyof SelfReported, string>>; team: PersonRow[] }
function loadStartDraft(): StartDraft | null {
  try {
    const d = JSON.parse(localStorage.getItem(START_DRAFT) || "null") as Partial<StartDraft> | null;
    if (!d || typeof d !== "object") return null;
    const out: StartDraft = { url: typeof d.url === "string" ? d.url.slice(0, 2048) : "", raw: d.raw && typeof d.raw === "object" ? d.raw : {},
      team: Array.isArray(d.team) ? d.team.slice(0, MAX_PEOPLE).map((r) => ({ ...emptyRow(r?.kind ?? "founder"), ...r })) : [] };
    return startDraftUsed(out) ? out : null;
  } catch { return null; }
}
const startDraftUsed = (d: StartDraft) => !!d.url.trim() || Object.values(d.raw).some((v) => !!v) || d.team.some(rowUsed);
function saveStartDraft(d: StartDraft | null) {
  try { if (d && startDraftUsed(d)) localStorage.setItem(START_DRAFT, JSON.stringify(d)); else localStorage.removeItem(START_DRAFT); } catch { /* private mode */ }
}

/** Optional founding team (hr.blockid.au review): sent with the valuation as `team`. After the website is checked,
 * people named on it are offered as one-click chips (GET /v1/hr/suggest-people?website=). */
function TeamPanel({ rows, setRows, consent, setConsent, tried, site }: { rows: PersonRow[]; setRows: (f: (r: PersonRow[]) => PersonRow[]) => void; consent: boolean; setConsent: (v: boolean) => void; tried: boolean; site: string | null }) {
  const { t } = useI18n();
  const used = rows.filter(rowUsed).length;
  const errs = used ? validateRows(rows, { requireOne: false }) : {};
  const box = useRef<HTMLDetailsElement>(null);
  useEffect(() => { if (tried && used && (Object.keys(errs).length || !consent) && box.current) box.current.open = true; }, [tried]); // eslint-disable-line react-hooks/exhaustive-deps
  const sug = useAsync<HrSuggestions | null>(() => (site ? api.hrSuggestPeople({ website: site }).catch(() => null) : Promise.resolve(null)), [site]);
  const host = site ? site.replace(/^https?:\/\/(www\.)?/, "").replace(/\/.*$/, "") : "";
  const found = site && sug.data?.website ? sug.data.people.slice(0, 8) : [];
  const has = (n: string) => rows.some((r) => r.full_name.trim().toLowerCase() === n.trim().toLowerCase());
  const add = (list: HrSuggestedPerson[]) => {
    setRows((rs) => {
      let out = [...rs];
      for (const p of list) {
        if (out.some((r) => r.full_name.trim().toLowerCase() === p.full_name.trim().toLowerCase())) continue;
        const kind = p.kind ?? (out.some(rowUsed) ? "cofounder" : "founder");
        const patch = { full_name: p.full_name, role: p.role.slice(0, 80), kind, links: p.source_url ?? "" };
        const i = out.findIndex((r) => !rowUsed(r));
        if (i >= 0) out[i] = { ...out[i], ...patch };
        else if (out.length < MAX_PEOPLE) out = [...out, { ...emptyRow(kind), ...patch }];
      }
      return out;
    });
    if (box.current) box.current.open = true;
  };
  const left = found.filter((p) => !has(p.full_name));
  return (
    <details className="tl-teambox" ref={box} open={used > 0 || undefined}>
      <summary>
        <h3>{t("hl.wz.h")} <span className="pill gold">{t("hl.wz.badge")}</span>{used > 0 && <span className="pill ok">{t("hl.wz.people", { n: used })}</span>}</h3>
        <p>{t("hl.wz.sub")}</p>
        <span className="tl-chev" aria-hidden="true">⌄</span>
      </summary>
      <div className="tl-teambody">
        <p className="note">{t("hl.wz.p")}</p>
        {site && (sug.loading || found.length > 0 || sug.data) && (
          <div className="tl-sugbox" aria-live="polite">
            {sug.loading && !sug.data ? (
              <span className="row muted-sm"><span className="spinner" aria-hidden="true" />{t("hl.wz.looking", { h: host })}</span>
            ) : found.length ? (
              <>
                <div className="between">
                  <span className="muted-sm">{t("hl.wz.found", { h: host })}</span>
                  {left.length > 1 && <button type="button" className="btn ghost sm" onClick={() => add(left)}>{t("hl.wz.addall")}</button>}
                </div>
                <ul className="tl-chips">
                  {found.map((p, i) => {
                    const done = has(p.full_name);
                    return (
                      <li key={p.full_name + i}>
                        <button type="button" className="tl-chip" disabled={done} onClick={() => add([p])} aria-label={t("hl.found.addp", { n: p.full_name })}>
                          <span><b>{p.full_name}</b>{p.role ? " · " + p.role : ""}</span><em>{done ? "✓ " + t("hl.wz.added") : "+ " + t("hl.wz.add")}</em>
                        </button>
                      </li>
                    );
                  })}
                </ul>
              </>
            ) : (
              <span className="muted-sm">{t("hl.wz.none", { h: host })}</span>
            )}
          </div>
        )}
        <PeopleEditor rows={rows} setRows={setRows} errs={errs} showAll={tried && used > 0} idPrefix="wz" />
        {used > 0 && <ConsentBox checked={consent} onChange={setConsent} showErr={tried} />}
      </div>
    </details>
  );
}

function Mine() {
  const { t, date, money } = useI18n();
  const { me } = useAuth();
  const vals = useAsync(() => api.myValuations(), [me?.address, me?.username]);
  const cos = useAsync(() => api.myCompanies(), [me?.address, me?.username]);
  const vs = (vals.data ?? []).slice(0, 8), cs = cos.data ?? [];
  if (!vs.length && !cs.length) return null;
  return (
    <div className="cols" style={{ marginTop: 20 }}>
      {vs.length > 0 && (
        <div className="pane">
          <h4>{t("v.mine")}</h4>
          <div className="tbl"><table>
            <tbody>
              {vs.map((v) => (
                <tr key={v.id}>
                  <td style={{ maxWidth: 220, overflow: "hidden", textOverflow: "ellipsis" }}><Link to={`/v/${encodeURIComponent(v.id)}`}>{v.url.replace(/^https?:\/\//, "")}</Link></td>
                  <td><span className={"pill" + (v.status === "approved" ? " ok" : v.status === "waiting_approval" ? " gold" : v.status === "failed" || v.status === "rejected" ? " bad" : "")}>{t(("v.st." + v.status) as DictKey)}</span></td>
                  <td className="r muted">{v.created_at ? date(v.created_at) : ""}</td>
                </tr>
              ))}
            </tbody>
          </table></div>
        </div>
      )}
      {cs.length > 0 && (
        <div className="pane">
          <h4>{t("v.mine.co")}</h4>
          <div className="tbl"><table>
            <tbody>
              {cs.map((c) => (
                <tr key={c.id}>
                  <td className="mono" style={{ fontWeight: 600 }}><Link to={`/c/${c.ticker}`}>{c.ticker}</Link></td>
                  <td>{c.name}</td>
                  <td className="r">{money(Number(c.valuation_aud))}</td>
                  <td><span className="pill">{t(("c.st." + c.status) as DictKey)}</span></td>
                </tr>
              ))}
            </tbody>
          </table></div>
        </div>
      )}
    </div>
  );
}

type SrRaw = Partial<Record<keyof SelfReported, string>>;

/** Optional founder-provided figures. AUD / integer inputs keep digits only and show grouped thousands. */
function SelfReportedFields({ raw, setRaw, bad }: { raw: SrRaw; setRaw: (f: (r: SrRaw) => SrRaw) => void; bad: Set<string> }) {
  const { t, fmt } = useI18n();
  const shown = (f: SrField) => {
    const s = raw[f.key] ?? "";
    return (f.kind === "aud" || f.kind === "int") && s ? fmt(Number(s)) : s;
  };
  const unit = (f: SrField) => (f.kind === "aud" ? "A$" : f.kind === "pct" ? "%" : null);
  const filled = SR_FIELDS.filter((f) => raw[f.key]).length;
  const box = useRef<HTMLDetailsElement>(null);
  useEffect(() => { if (bad.size && box.current) box.current.open = true; }, [bad]);
  return (
    <details className="srbox" ref={box}>
      <summary>{t("sr.toggle")}{filled > 0 && <span className="pill gold" style={{ marginLeft: 8 }}>{filled}</span>}</summary>
      <p className="note" style={{ margin: 0 }}>{t("sr.help")} {t("sr.why")}</p>
      <div className="srgrid">
        {SR_FIELDS.map((f) => (
          <label key={f.key} className={"srf" + (bad.has(f.key) ? " bad" : "")}>
            <span>{t(f.label)}</span>
            <span className="srin">
              {unit(f) === "A$" && <i aria-hidden="true">A$</i>}
              <input type="text" inputMode={f.kind === "pct" ? "text" : f.kind === "months" ? "decimal" : "numeric"} autoComplete="off" value={shown(f)} placeholder="–" aria-invalid={bad.has(f.key)}
                onChange={(e) => { const v = cleanInput(f.kind, e.target.value); setRaw((r) => ({ ...r, [f.key]: v })); }} />
              {unit(f) === "%" && <i aria-hidden="true">%</i>}
            </span>
          </label>
        ))}
      </div>
    </details>
  );
}

/** An inline link-check problem: the reason, plus a one-click fix when we can guess the intended address. */
interface UrlProblem { msg: string; suggestion?: string }

export default function NewWizard() {
  const { t } = useI18n();
  const { me, connect } = useAuth();
  const nav = useNavigate();
  const [params] = useSearchParams();
  const listing = params.get("goal") === "list";
  const [draft0] = useState(() => (params.get("url") ? null : loadStartDraft()));
  const [restored, setRestored] = useState(!!draft0);
  const [url, setUrl] = useState(() => (params.get("url") ?? draft0?.url ?? "").slice(0, 2048));
  const [err, setErr] = useState("");
  const [bad, setBad0] = useState<UrlProblem | null>(null);
  const [busy, setBusy] = useState<"" | "check" | "start">("");
  const [raw, setRaw] = useState<SrRaw>(() => draft0?.raw ?? {});
  const s5 = useStartV5();  // v5 founder inputs + uploads; only shown when /v1/studio/evaluation/config says enabled
  const [badSr, setBad] = useState<Set<string>>(new Set());
  const [team, setTeam] = useState<PersonRow[]>(() => (draft0?.team.length ? draft0.team : [emptyRow("founder")]));
  useEffect(() => { saveStartDraft({ url, raw, team }); }, [url, raw, team]);
  const discardDraft = () => { saveStartDraft(null); setUrl(""); setRaw({}); s5.clear(); setTeam([emptyRow("founder")]); setTeamOk(false); setSite(null); setBad0(null); setErr(""); setRestored(false); };
  const [teamOk, setTeamOk] = useState(false);
  const [teamTried, setTeamTried] = useState(false);
  const [site, setSite] = useState<string | null>(null);  // website checked (client rules) → people suggestions
  const checkSite = (v: string) => { const c = checkUrlClient(v); if (c.ok && c.url) setSite(c.url.replace(/\/$/, "")); };
  useEffect(() => { if (url) checkSite(url); }, []); // eslint-disable-line react-hooks/exhaustive-deps
  const input = useRef<HTMLInputElement>(null);
  useTitle(t(listing ? "new.eyebrow.list" : "new.eyebrow"));

  const fail = (p: UrlProblem) => { setBad0(p); input.current?.focus(); };
  const reasonText = (r: string | null | undefined) => (r && ("url." + r) in en ? t(("url." + r) as DictKey) : t("new.bad.url"));

  const start = async (e: React.FormEvent) => {
    e.preventDefault();
    setErr(""); setBad0(null);
    const c = checkUrlClient(url);
    if (!c.ok) { fail({ msg: reasonText(c.reason), suggestion: c.suggestion }); return; }
    const sr = parseSelfReported(s5.enabled ? {} : raw);
    setBad(new Set(sr.bad.map((f) => f.key)));
    if (sr.bad.length) { setErr(t("sr.bad", { f: sr.bad.map((f) => t(f.label)).join(", ") })); return; }
    const c5 = s5.enabled ? s5.collect() : null;
    if (c5?.bad.length) { setErr(t("sr.bad", { f: c5.bad.map((k) => t(("v5.f." + k) as DictKey)).join(", ") })); return; }
    const teamRows = team.filter(rowUsed);
    if (teamRows.length) {
      setTeamTried(true);
      const n = Object.keys(validateRows(team, { requireOne: false })).length + (teamOk ? 0 : 1);
      if (n) { setErr(t("hl.wz.bad", { n })); return; }
    }
    let target = c.url;
    setBusy("check");
    try {
      const r = await api.checkUrl(c.url);
      if (!r.ok) {
        let sug: string | undefined;
        try { sug = r.suggestion ? new URL(r.suggestion).hostname : undefined; } catch { /* ignore */ }
        fail({ msg: reasonText(r.reason), suggestion: sug });
        setBusy("");
        return;
      }
      if (r.url) { target = r.url.replace(/\/$/, ""); setSite(target); }
    } catch (x) {
      // 429: stop here; an older API without the check (404/405) or a network blip: let the valuation decide
      if (x instanceof ApiError && x.status === 429) { fail({ msg: t("url.rate") }); setBusy(""); return; }
    }
    setBusy("start");
    try {
      if (!me) await connect();
      const teamIn = teamRows.length ? { people: teamRows.map(toPersonIn), consent: true as const } : undefined;
      const { id, team_id } = c5 ? await api5.createValuation(target, c5.metrics, teamIn) : await api.createValuation(target, sr.metrics, teamIn);
      if (c5) { await s5.flush(id).catch(() => []); s5.clear(); }
      const hostName = target.replace(/^https?:\/\/(www\.)?/, "").replace(/\/.*$/, "");
      watchJob({ kind: "valuation", id, title: hostName });
      if (team_id) watchJob({ kind: "hr_team", id: team_id, title: hostName });
      saveStartDraft(null);
      nav(`/v/${encodeURIComponent(id)}`);
    } catch (x) {
      setErr(x instanceof ApiError && x.status === 429 ? t("new.limit") : errText(x, t));
    } finally {
      setBusy("");
    }
  };

  const applySuggestion = (h: string) => { setUrl(h); setBad0(null); input.current?.focus(); };

  return (
    <SideLayout label={t("flow.nav")} rail={<FlowRail cur={1} reach={1} gates={["none", "none"]} href={(n) => (n === 1 ? "/start" : null)} />}>
      <Crumbs items={[{ to: "/start", label: t("nav.studio") }, { label: "01 " + t("step.1") }]} />
      <ContinueCard draft={restored && startDraftUsed({ url, raw, team }) ? {
        label: url.trim() ? t("jobs.cont.draft.start", { w: url.trim().replace(/^https?:\/\/(www\.)?/, "").replace(/\/.*$/, "") }) : t("jobs.cont.draft.start.none"),
        sub: [team.filter(rowUsed).length ? t("jobs.cont.draft.people", { n: team.filter(rowUsed).length }) : "", t("jobs.cont.draft.restored")].filter(Boolean).join(" · "),
        onDiscard: discardDraft,
      } : null} />
      <StepHead eyebrow={t("flow.stepof", { n: 1, p: t("flow.ph.a") })} title={t(listing ? "new.h2.list" : "new.h2")} desc={t(listing ? "new.p.list" : "new.p")} />
      <form className="panel" onSubmit={start} noValidate>
        <div className="ptitle"><div><h3>{t("s1.h")}</h3><p>{t("s1.p")}</p></div></div>
        <div className="field">
          <input ref={input} type="url" inputMode="url" autoComplete="url" spellCheck={false} placeholder="yourcompany.com.au" aria-label={t("c.website")} value={url}
            onChange={(e) => { setUrl(e.target.value); if (bad) setBad0(null); }} onBlur={(e) => checkSite(e.target.value)} aria-invalid={!!bad} aria-describedby="url-err" autoFocus />
          <button className="btn" type="submit" disabled={!!busy} aria-busy={!!busy}>{busy ? <span className="spinner" aria-hidden="true" /> : null}{busy === "check" ? t("url.checking") : busy === "start" ? t("new.starting") : me ? t("s1.btn") : t("nav.connect") + " · " + t("s1.btn")}</button>
        </div>
        <div id="url-err" role="alert" className="urlhint">
          {bad && <span className="err" style={{ minHeight: 0 }}>{bad.msg}{bad.suggestion ? " " + t("url.didyou", { h: bad.suggestion }) : ""}</span>}
          {bad?.suggestion && <button type="button" className="btn ghost sm" onClick={() => applySuggestion(bad.suggestion!)}>{t("url.use", { h: bad.suggestion })}</button>}
        </div>
        {err && <p className="err" role="alert">{err}</p>}
        <TeamPanel rows={team} setRows={setTeam} consent={teamOk} setConsent={setTeamOk} tried={teamTried} site={site} />
        {s5.enabled ? <StartInputs s={s5} listing={listing} /> : <SelfReportedFields raw={raw} setRaw={setRaw} bad={badSr} />}
        {!me && <p className="quietline">{t("new.signin")}</p>}
        <div className="cols3">
          <div className="card"><h4>{t("s1.c1")}</h4><p className="sub">{t("s1.c1p")}</p></div>
          <div className="card"><h4>{t("s1.c2")}</h4><p className="sub">{t("s1.c2p")}</p></div>
          <div className="card"><h4>{t("s1.c3")}</h4><p className="sub">{t("s1.c3p")}</p></div>
        </div>
      </form>
      <Pager keys={false} prev={{ to: "/", label: t("flow.home") }} next={{ to: "/v/sample/report", label: t("cta.secondary"), primary: false }} />
      {me && <Mine />}
    </SideLayout>
  );
}
