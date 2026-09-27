/* "Running" tray: the signed-in user's background analyses (business valuations on eth, person / team reports on hr),
   shown as a pill in the top nav of both apps, a dropdown with progress + "Back to it", a one-time toast when a job
   finishes while the user is elsewhere, and the "Continue where you left off" card on the entry pages.
   Data: GET /v1/me/active-jobs (studio/active_jobs.py) — polled every 5 s while a job runs, 20 s otherwise, paused while
   the tab is hidden. The last list and the watched job ids live in localStorage so the tray shows up at once on load;
   the last visited page (tab / step) of each job lives in sessionStorage so "Back to it" returns to the exact screen. */
import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { createPortal } from "react-dom";
import { Link, useLocation } from "react-router-dom";
import { useI18n } from "../i18n";
import { useAuth } from "../auth";
import { ApiError, request } from "../api";
import { ethUrl, HR_HOST, hrUrl } from "../lib/hrhost";
import type { DictKey } from "../dict";
import "./activejobs.css";

export type JobKind = "valuation" | "hr_person" | "hr_team";
export type JobStatus = "queued" | "running" | "done" | "failed";
export interface ActiveJob {
  kind: JobKind; id: string; title: string; status: JobStatus; raw_status?: string; phase: string; pct: number;
  eta_s: number | null; url: string; started_at: string | null; updated_at: string | null; finished_at?: string | null;
  /** client only: added by watchJob() before the server lists it */
  local?: boolean;
}

const CACHE = "blockid-active-jobs-v1";    // {who, at, jobs}: last list, shown at once on load
const WATCH = "blockid-jobs-watched-v1";   // [{k, at}]: job keys this browser started or opened
const SEEN = "blockid-jobs-notified-v1";   // [key]: finished jobs already announced (toast) or looked at
const HIDDEN = "blockid-jobs-hidden-v1";   // [key]: finished jobs the user hid from the list
const LAST = "blockid-job-last:";          // sessionStorage, per job: last visited path (tab / step)
const CARD_HIDE = "blockid-jobs-card-hidden"; // sessionStorage: signature of what the continue card showed when hidden
export const HR_PERSON_DRAFT = "blockid-hr-person-draft-v2"; // kept by pages/hr/HrNewPerson.tsx (read only here)

const FAST = 5000, SLOW = 20000;
export const jobKey = (j: { kind: JobKind; id: string }) => `${j.kind}:${j.id}`;
export const isLive = (j: ActiveJob) => j.status === "queued" || j.status === "running";

/* ---------- storage helpers (every access may throw: private mode, blocked storage) ---------- */
function lsGet<T>(k: string, d: T): T { try { const s = localStorage.getItem(k); return s ? (JSON.parse(s) as T) : d; } catch { return d; } }
function lsSet(k: string, v: unknown) { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* ignore */ } }
function ssGet(k: string): string | null { try { return sessionStorage.getItem(k); } catch { return null; } }
function ssSet(k: string, v: string) { try { sessionStorage.setItem(k, v); } catch { /* ignore */ } }
const addTo = (k: string, key: string, max = 200) => { const a = lsGet<string[]>(k, []); if (!a.includes(key)) lsSet(k, [...a, key].slice(-max)); };

/* ---------- store (one poller for the pill, the dropdown and the continue card) ---------- */
interface Cache { who: string | null; at: number; jobs: ActiveJob[] }
interface State { jobs: ActiveJob[]; who: string | null; at: number; toasts: ActiveJob[]; hidden: string[] }
const cache0 = lsGet<Cache>(CACHE, { who: null, at: 0, jobs: [] });
let state: State = { jobs: Array.isArray(cache0.jobs) ? cache0.jobs : [], who: cache0.who ?? null, at: cache0.at || 0, toasts: [], hidden: lsGet<string[]>(HIDDEN, []) };
const subs = new Set<() => void>();
const put = (p: Partial<State>) => { state = { ...state, ...p }; subs.forEach((f) => f()); };
const subscribe = (f: () => void) => { subs.add(f); return () => { subs.delete(f); }; };
export function useActiveJobs(): State { return useSyncExternalStore(subscribe, () => state, () => state); }

let who: string | null = null;
let timer: number | undefined;
let inflight = false;

/** Path of the job page the browser is on (this host only), as a job key. */
export function jobKeyOfPath(pathname: string): string | null {
  if (HR_HOST) {
    const r = /^\/r\/([^/]+)/.exec(pathname);
    if (r) return `hr_team:${decodeURIComponent(r[1])}`;
    const p = /^\/p\/([^/]+)/.exec(pathname);
    return p ? `hr_person:${decodeURIComponent(p[1])}` : null;
  }
  const v = /^\/v\/([^/]+)/.exec(pathname);
  return v && v[1] !== "sample" ? `valuation:${decodeURIComponent(v[1])}` : null;
}

function merge(server: ActiveJob[]): ActiveJob[] {
  // keep a job watchJob() added a moment ago until the server lists it (queue insert / replica lag)
  const keys = new Set(server.map(jobKey));
  const watched = lsGet<{ k: string; at: number }[]>(WATCH, []);
  const fresh = new Set(watched.filter((w) => Date.now() - w.at < 60000).map((w) => w.k));
  const keep = state.jobs.filter((j) => j.local && !keys.has(jobKey(j)) && fresh.has(jobKey(j)));
  lsSet(WATCH, watched.filter((w) => keys.has(w.k) || Date.now() - w.at < 864e5).slice(-100));
  return [...keep, ...server];
}

function announce(prev: ActiveJob[], next: ActiveJob[]) {
  const before = new Map(prev.map((j) => [jobKey(j), j]));
  const seen = lsGet<string[]>(SEEN, []);
  const here = typeof location !== "undefined" ? jobKeyOfPath(location.pathname) : null;
  const out: ActiveJob[] = [];
  for (const j of next) {
    const k = jobKey(j), b = before.get(k);
    if (isLive(j) || !b || !isLive(b) || seen.includes(k)) continue;
    addTo(SEEN, k);
    if (k !== here) out.push(j); // finished while the user was elsewhere in the app
  }
  if (out.length) put({ toasts: [...state.toasts.filter((t) => !out.some((o) => jobKey(o) === jobKey(t))), ...out].slice(-3) });
}

export async function refreshJobs(): Promise<void> {
  if (!who || inflight) return;
  inflight = true;
  const asked = who;
  try {
    const r = await request<{ jobs: ActiveJob[] }>("GET", "/v1/me/active-jobs");
    if (asked !== who) return;
    const jobs = merge(Array.isArray(r?.jobs) ? r.jobs : []);
    const prev = state.who === who ? state.jobs : [];
    announce(prev, jobs);
    put({ jobs, who, at: Date.now() });
    lsSet(CACHE, { who, at: Date.now(), jobs: jobs.filter((j) => !j.local) } satisfies Cache);
  } catch (e) {
    if (e instanceof ApiError && (e.status === 401 || e.status === 403)) put({ jobs: [], at: Date.now() });
    // 404 (an older API) or a network blip: keep what we have
  } finally {
    inflight = false;
    schedule();
  }
}

function schedule() {
  clearTimeout(timer);
  if (!who) return;
  const ms = state.jobs.some(isLive) ? FAST : SLOW;
  timer = window.setTimeout(() => { if (typeof document !== "undefined" && document.hidden) schedule(); else void refreshJobs(); }, ms);
}

function setWho(w: string | null) {
  if (w === who && (w || !state.who)) return;
  who = w;
  clearTimeout(timer);
  if (!w) { put({ jobs: [], who: null, toasts: [] }); lsSet(CACHE, { who: null, at: Date.now(), jobs: [] }); return; } // signed out: forget the list
  if (state.who !== w) put({ jobs: [], who: w, toasts: [] });
  void refreshJobs();
}

/** Show a job in the tray right away (e.g. just after it was started); the next poll replaces it with server data. */
export function watchJob(j: { kind: JobKind; id: string; title: string; url?: string }) {
  const k = jobKey(j);
  const w = lsGet<{ k: string; at: number }[]>(WATCH, []).filter((x) => x.k !== k);
  lsSet(WATCH, [...w, { k, at: Date.now() }].slice(-100));
  if (!state.jobs.some((x) => jobKey(x) === k)) {
    const path = j.url ?? (j.kind === "valuation" ? `/v/${encodeURIComponent(j.id)}/research` : `/${j.kind === "hr_person" ? "p" : "r"}/${encodeURIComponent(j.id)}`);
    const now = new Date().toISOString();
    put({ jobs: [{ kind: j.kind, id: j.id, title: j.title, status: "queued", phase: "queued", pct: 0, eta_s: null, url: path, started_at: now, updated_at: now, local: true }, ...state.jobs] });
  }
  setTimeout(() => void refreshJobs(), 1200);
}

function hideJob(j: ActiveJob) {
  addTo(HIDDEN, jobKey(j));
  addTo(SEEN, jobKey(j));
  put({ hidden: lsGet<string[]>(HIDDEN, []), toasts: state.toasts.filter((t) => jobKey(t) !== jobKey(j)) });
}
const dropToast = (j: ActiveJob) => put({ toasts: state.toasts.filter((t) => jobKey(t) !== jobKey(j)) });

/* ---------- links ---------- */
const pathOf = (u: string) => { try { const x = new URL(u, "https://x.invalid"); return x.pathname + x.search + x.hash; } catch { return u; } };
const onThisHost = (k: JobKind) => (k === "valuation") !== HR_HOST;
/** Where "Back to it" goes: the exact tab / step last seen in this tab, else the job's own page. */
export function jobTarget(j: ActiveJob): { internal: boolean; to: string } {
  const base = pathOf(j.url);
  let last = onThisHost(j.kind) ? ssGet(LAST + jobKey(j)) : null;
  if (last && j.status === "done" && j.kind === "valuation" && /\/research(?:[?#]|$)/.test(last)) last = null; // research finished: open the report
  const to = last || base;
  if (onThisHost(j.kind)) return { internal: true, to };
  return { internal: false, to: j.kind === "valuation" ? ethUrl(to) : hrUrl(to) };
}

function JobLink({ j, className, children, onClick }: { j: ActiveJob; className?: string; children: React.ReactNode; onClick?: () => void }) {
  const tg = jobTarget(j);
  const click = () => { if (!isLive(j)) addTo(SEEN, jobKey(j)); onClick?.(); };
  return tg.internal ? <Link className={className} to={tg.to} onClick={click}>{children}</Link> : <a className={className} href={tg.to} onClick={click}>{children}</a>;
}

/* ---------- small parts ---------- */
function useTick(on: boolean, ms = 1000) {
  const [, set] = useState(0);
  useEffect(() => { if (!on) return; const id = setInterval(() => set((x) => x + 1), ms); return () => clearInterval(id); }, [on, ms]);
}

function Ring({ pct, live, size = 18 }: { pct: number; live: boolean; size?: number }) {
  const r = 7, c = 2 * Math.PI * r;
  return (
    <svg className={"aj-ring" + (live ? " live" : "")} width={size} height={size} viewBox="0 0 18 18" aria-hidden="true">
      <circle className="aj-ring-track" cx="9" cy="9" r={r} />
      <circle className="aj-ring-bar" cx="9" cy="9" r={r} strokeDasharray={c} strokeDashoffset={c * (1 - Math.max(0, Math.min(100, pct)) / 100)} />
      {!live && <path className="aj-ring-tick" d="M5.6 9.3l2.2 2.2 4.4-4.6" />}
    </svg>
  );
}

function useFmt() {
  const { t, ago } = useI18n();
  const phase = (j: ActiveJob) => { const k = ("jobs.ph." + (j.status === "queued" ? "queued" : j.phase)) as DictKey; const s = t(k); return s === k ? t(("jobs.st." + j.status) as DictKey) : s; };
  const eta = (j: ActiveJob, at: number) => {
    if (!isLive(j) || j.eta_s == null) return "";
    const left = Math.max(0, j.eta_s - (Date.now() - at) / 1000);
    if (left <= 5) return t("jobs.eta.soon");
    return t("jobs.eta", { t: left < 60 ? t("jobs.t.s", { n: Math.round(left) }) : t("jobs.t.min", { n: Math.ceil(left / 60) }) });
  };
  const finished = (j: ActiveJob) => (j.finished_at ? t("jobs.finished", { t: ago(j.finished_at) }) : "");
  return { t, phase, eta, finished };
}

function JobRow({ j, at, onGo, compact = false }: { j: ActiveJob; at: number; onGo?: () => void; compact?: boolean }) {
  const { t, phase, eta, finished } = useFmt();
  const live = isLive(j);
  const pct = j.status === "done" ? 100 : Math.max(0, Math.min(100, Math.round(j.pct || 0)));
  const tone = j.status === "done" ? "ok" : j.status === "failed" ? "bad" : "run";
  const meta = live ? [phase(j), eta(j, at)].filter(Boolean).join(" · ") : [j.status === "failed" ? phase(j) : "", finished(j)].filter(Boolean).join(" · ");
  return (
    <li className={"aj-job " + tone + (compact ? " compact" : "")}>
      <div className="aj-job-top">
        <span className="aj-kind">{t(("jobs.kind." + j.kind) as DictKey)}</span>
        <span className={"aj-st " + tone}>{t(("jobs.st." + j.status) as DictKey)}</span>
        {!live && <button type="button" className="aj-x" onClick={() => hideJob(j)} aria-label={t("jobs.dismiss")} title={t("jobs.dismiss")}>×</button>}
      </div>
      <b className="aj-title" title={j.title}>{j.title}</b>
      <div className="aj-bar" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={pct} aria-label={j.title}><i style={{ width: pct + "%" }} /></div>
      <div className="aj-job-bot">
        <span className="aj-meta">{live && <b className="mono">{pct}%</b>}{meta && <span>{meta}</span>}</span>
        <JobLink j={j} className={"btn sm" + (live ? " ghost" : "")} onClick={onGo}>{live ? t("jobs.back") : j.status === "failed" ? t("jobs.failed.view") : t("jobs.view")}{" →"}</JobLink>
      </div>
    </li>
  );
}

/* ---------- toasts ---------- */
function Toasts() {
  const { toasts } = useActiveJobs();
  const { t } = useI18n();
  const { pathname } = useLocation();
  useEffect(() => { // the user opened the finished job some other way: the toast is no longer news
    const k = jobKeyOfPath(pathname);
    if (k && state.toasts.some((x) => jobKey(x) === k)) put({ toasts: state.toasts.filter((x) => jobKey(x) !== k) });
  }, [pathname]);
  useEffect(() => {
    if (!toasts.length) return;
    const id = setTimeout(() => put({ toasts: state.toasts.slice(1) }), 12000);
    return () => clearTimeout(id);
  }, [toasts]);
  if (!toasts.length) return null;
  return createPortal(
    <div className="aj-toasts" role="status" aria-live="polite">
      {toasts.map((j) => (
        <div key={jobKey(j)} className={"aj-toast " + (j.status === "failed" ? "bad" : "ok")}>
          <Ring pct={100} live={false} size={22} />
          <div className="aj-toast-txt">
            <b>{t(j.status === "failed" ? "jobs.toast.failed" : "jobs.toast.done", { title: j.title })}</b>
            <span>{t(("jobs.kind." + j.kind) as DictKey)}</span>
          </div>
          <JobLink j={j} className="btn sm" onClick={() => dropToast(j)}>{j.status === "failed" ? t("jobs.failed.view") : t("jobs.toast.view")}</JobLink>
          <button type="button" className="aj-x" onClick={() => dropToast(j)} aria-label={t("jobs.toast.close")}>×</button>
        </div>
      ))}
    </div>,
    document.body,
  );
}

/* ---------- continue card ---------- */
export interface ContinueDraft { label: string; sub?: string; to?: string; action?: string; onDiscard?: () => void }

/** "Continue where you left off": running / recently finished jobs and an unfinished form. Hidden when empty. */
export function ContinueCard({ draft }: { draft?: ContinueDraft | null }) {
  const { t } = useI18n();
  const { jobs, at, hidden } = useActiveJobs();
  const list = jobs.filter((j) => isLive(j) || !hidden.includes(jobKey(j))).slice(0, 4);
  useTick(list.some(isLive), 5000);
  const sig = list.map(jobKey).join(",") + "|" + (draft?.label ?? "");
  const [closed, setClosed] = useState(() => ssGet(CARD_HIDE) === sig);
  useEffect(() => { setClosed(ssGet(CARD_HIDE) === sig); }, [sig]);
  if ((!list.length && !draft) || closed) return null;
  return (
    <section className="aj-card" aria-labelledby="aj-card-h">
      <div className="aj-card-head">
        <div>
          <h2 id="aj-card-h">{t("jobs.cont.h")}</h2>
          <p>{t("jobs.cont.p")}</p>
        </div>
        <button type="button" className="btn ghost sm" onClick={() => { ssSet(CARD_HIDE, sig); setClosed(true); }}>{t("jobs.cont.hide")}</button>
      </div>
      {draft && (
        <div className="aj-draft">
          <span className="aj-draft-ic" aria-hidden="true">✎</span>
          <span className="aj-draft-txt"><b>{draft.label}</b>{draft.sub && <span>{draft.sub}</span>}</span>
          {draft.to && <Link className="btn sm" to={draft.to}>{draft.action ?? t("jobs.cont.draft.open")} →</Link>}
          {draft.onDiscard && <button type="button" className="btn ghost sm" onClick={draft.onDiscard}>{t("jobs.cont.draft.discard")}</button>}
        </div>
      )}
      {list.length > 0 && <ul className="aj-list aj-card-list">{list.map((j) => <JobRow key={jobKey(j)} j={j} at={at} compact />)}</ul>}
    </section>
  );
}

/** hr entry pages (/, /new, /new/person): the card goes at the top of <main> without touching those pages. */
const HR_ENTRY = new Set(["/", "/new", "/new/person"]);
function personDraft(): ContinueDraft | null | "blank" {
  const d = lsGet<Record<string, unknown> | null>(HR_PERSON_DRAFT, null);
  if (!d || typeof d !== "object") return null;
  const s = (k: string) => (typeof d[k] === "string" ? (d[k] as string).trim() : "");
  const any = ["name", "headline", "bio", "cv", "bizWeb", "company", "title", "desc"].some((k) => s(k)) || (Array.isArray(d.links) && d.links.some((l) => typeof l === "string" && l.trim())) || !!d.biz;
  return any ? { label: s("name") ? "name:" + s("name") : "noname", to: "/new/person" } : "blank";
}
function HrContinueSlot() {
  const { t } = useI18n();
  const { pathname } = useLocation();
  const [host, setHost] = useState<HTMLElement | null>(null);
  const entry = HR_ENTRY.has(pathname.replace(/\/+$/, "") || "/");
  useEffect(() => {
    if (!entry) return;
    const main = document.getElementById("main");
    if (!main) return;
    const el = document.createElement("div");
    el.className = "aj-slot";
    main.insertBefore(el, main.firstChild);
    setHost(el);
    return () => { el.remove(); setHost(null); };
  }, [entry]);
  if (!host || !entry) return null;
  const pd = pathname.startsWith("/new/person") ? null : personDraft(); // on /new/person the form itself is the draft
  const draft: ContinueDraft | null = pd && pd !== "blank"
    ? { label: pd.label.startsWith("name:") ? t("jobs.cont.draft.person", { n: pd.label.slice(5) }) : t("jobs.cont.draft.person.none"), to: pd.to }
    : null;
  return createPortal(<div className="wrap aj-slot-in"><ContinueCard draft={draft} /></div>, host);
}

/* ---------- nav pill + dropdown ---------- */
export function ActiveJobs() {
  const { t } = useI18n();
  const { me, loading } = useAuth();
  const { jobs, at, hidden, who: cachedWho } = useActiveJobs();
  const { pathname, search } = useLocation();
  const [open, setOpen] = useState(false);
  const [pos, setPos] = useState<{ top: number; right: number } | null>(null);
  const box = useRef<HTMLSpanElement>(null);
  const btn = useRef<HTMLButtonElement>(null);
  const meId = me ? (me.address ?? me.username ?? "?").toLowerCase() : null;

  useEffect(() => { if (!loading) setWho(meId); }, [meId, loading]);
  useEffect(() => {
    const vis = () => { if (!document.hidden) void refreshJobs(); };
    document.addEventListener("visibilitychange", vis);
    return () => document.removeEventListener("visibilitychange", vis);
  }, []);
  // remember the exact screen (tab / step) of the job page being looked at; a finished job counts as seen
  useEffect(() => {
    setOpen(false);
    const k = jobKeyOfPath(pathname);
    if (!k) return;
    ssSet(LAST + k, pathname + search);
    const j = state.jobs.find((x) => jobKey(x) === k);
    if (j && !isLive(j)) addTo(SEEN, k);
    if (Date.now() - state.at > FAST) void refreshJobs();
  }, [pathname, search]);
  useEffect(() => {
    if (!open) return;
    const place = () => { // under the pill, clamped inside the viewport (16 px gutters; the menu is min(380px, 100vw - 32px) wide)
      const r = btn.current?.getBoundingClientRect();
      if (!r) return;
      const iw = window.innerWidth, mw = Math.min(380, iw - 32);
      setPos({ top: r.bottom + 8, right: Math.min(Math.max(16, iw - r.right), Math.max(16, iw - 16 - mw)) });
    };
    place();
    const close = (e: MouseEvent | KeyboardEvent) => {
      if (e instanceof KeyboardEvent ? e.key === "Escape" : !box.current?.contains(e.target as Node)) { setOpen(false); if (e instanceof KeyboardEvent) btn.current?.focus(); }
    };
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", close);
    window.addEventListener("resize", place);
    return () => { document.removeEventListener("mousedown", close); document.removeEventListener("keydown", close); window.removeEventListener("resize", place); };
  }, [open]);
  const shown = me || (loading && cachedWho) ? jobs.filter((j) => isLive(j) || !hidden.includes(jobKey(j))) : [];
  const live = shown.filter(isLive), ready = shown.filter((j) => !isLive(j));
  useTick(open && live.length > 0);
  const pct = live.length ? Math.round(live.reduce((a, j) => a + (j.pct || 0), 0) / live.length) : 100;
  const newReady = ready.filter((j) => !lsGet<string[]>(SEEN, []).includes(jobKey(j))).length;
  return (
    <>
      {HR_HOST && <HrContinueSlot />}
      <Toasts />
      {shown.length > 0 && (
        <span className="menuwrap aj" ref={box}>
          <button ref={btn} type="button" className={"aj-pill" + (live.length ? " live" : " ready") + (newReady ? " fresh" : "")} aria-haspopup="dialog" aria-expanded={open}
            aria-label={t("jobs.pill.aria", { n: live.length, r: ready.length })} onClick={() => setOpen((o) => !o)}>
            <Ring pct={pct} live={live.length > 0} />
            {live.length ? (
              <span className="aj-pill-txt"><span className="aj-lbl">{t("jobs.pill.running", { n: live.length })}</span><span className="aj-dot" aria-hidden="true"> · </span><b>{pct}%</b></span>
            ) : (
              <span className="aj-pill-txt"><span className="aj-lbl">{t("jobs.pill.ready", { n: ready.length })}</span><b className="aj-n">{ready.length}</b></span>
            )}
          </button>
          {open && (
            <div className="aj-menu" role="dialog" aria-label={t("jobs.menu.h")} style={pos ? { top: pos.top, right: pos.right } : undefined}>
              <div className="aj-menu-h"><b>{t("jobs.menu.h")}</b><span>{t("jobs.menu.sub")}</span></div>
              <ul className="aj-list">{shown.map((j) => <JobRow key={jobKey(j)} j={j} at={at} onGo={() => setOpen(false)} />)}</ul>
            </div>
          )}
        </span>
      )}
    </>
  );
}
