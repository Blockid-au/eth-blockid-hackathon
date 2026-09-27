/* Business updates (studio/updates.py): founder form + drafts, update cards, full view, "Check this update".
 * Investor-facing copy stays plain: "recorded on blockchain", "fingerprint", "approved by a person". */
import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { sha256, toBytes } from "viem";
import { api, isMock, METRICS, type BizUpdate, type Cadence, type CompanyDetail, type Metric, type UpdateBody, type UpdateKpi } from "../api";
import { errText } from "../auth";
import { arrow, useI18n } from "../i18n";
import type { DictKey } from "../dict";
import { ErrorBox, Loading } from "../components/Layout";
import { useAsync, useTitle } from "../lib/hooks";
import { canonicalJson, parseLossless, plain } from "../lib/canonical";
import { CHAINS } from "../wallet";
import { shortAddr } from "../lib/addr";

const CADENCES: Cadence[] = ["monthly", "quarterly", "weekly", "annual"];

/* ---------- small pieces ---------- */
function useKpiFmt() {
  const { fmt, money } = useI18n();
  return (k: Pick<UpdateKpi, "unit">, v: number | null | undefined) => (v == null ? "–" : k.unit === "AUD" ? money(v) : fmt(v));
}

export function StatusPill({ s }: { s: BizUpdate["status"] }) {
  const { t } = useI18n();
  const cls = s === "published" ? " ok" : s === "rejected" || s === "failed" ? " bad" : s === "pending_approval" || s === "publishing" ? " gold" : "";
  return <span className={"pill" + cls}>{t(("upd.st." + s) as DictKey)}</span>;
}

function Chg({ p }: { p: number | null }) {
  const { t, chg } = useI18n();
  if (p == null) return <span className="chg flat">{t("upd.kpi.new")}</span>;
  return <span className={"chg " + arrow(p)}>{chg(p)}</span>;
}

export function KpiTable({ kpis }: { kpis: UpdateKpi[] }) {
  const { t } = useI18n();
  const f = useKpiFmt();
  if (!kpis.length) return null;
  return (
    <div className="tbl">
      <table>
        <thead><tr><th>{t("upd.kpi.metric")}</th><th className="r">{t("upd.kpi.now")}</th><th className="r">{t("upd.kpi.prev")}</th><th className="r">{t("upd.kpi.chg")}</th></tr></thead>
        <tbody>
          {kpis.map((k) => (
            <tr key={k.metric}>
              <td>{t(("upd.m." + k.metric) as DictKey)}</td>
              <td className="r num">{f(k, k.value)}</td>
              <td className="r num muted">{f(k, k.prev)}</td>
              <td className="r"><Chg p={k.change_pct} /></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function KpiChips({ kpis, n = 3 }: { kpis: UpdateKpi[]; n?: number }) {
  const { t } = useI18n();
  const f = useKpiFmt();
  return (
    <div className="upd-chips">
      {kpis.slice(0, n).map((k) => (
        <span key={k.metric} className="upd-chip"><small>{t(("upd.m." + k.metric) as DictKey)}</small> <b className="num">{f(k, k.value)}</b> <Chg p={k.change_pct} /></span>
      ))}
    </div>
  );
}

/** One line per update: title, period, summary, first numbers. */
export function UpdateCard({ u, to, showCo = false }: { u: BizUpdate; to?: string; showCo?: boolean }) {
  const { t, date } = useI18n();
  const inner = (
    <>
      <div className="between">
        <span>{showCo && <><b className="mono">{u.ticker}</b> · </>}<b>{u.title}</b></span>
        {u.status === "published" ? <span className="muted-sm">{u.published_at ? t("upd.published", { d: date(u.published_at) }) : ""}</span> : <StatusPill s={u.status} />}
      </div>
      <span className="muted-sm">{t("upd.period", { c: t(("upd.cad." + u.cadence) as DictKey), p: u.period_label })}</span>
      <p className="upd-sum">{u.body.summary}</p>
      <KpiChips kpis={u.body.kpis} />
    </>
  );
  return to ? <Link className="card solid upd-card" to={to}>{inner}</Link> : <div className="card solid upd-card">{inner}</div>;
}

/** The full update body (what investors read and what was approved). */
export function UpdateView({ u }: { u: BizUpdate }) {
  const { t } = useI18n();
  const b = u.body;
  return (
    <div className="stack">
      <p className="upd-lead">{b.summary}</p>
      <div className="cols">
        <section className="card solid">
          <h4>{t("upd.highlights")}</h4>
          {b.highlights.length ? <ul className="upd-ul">{b.highlights.map((h, i) => <li key={i}>{h}</li>)}</ul> : <span className="muted">–</span>}
        </section>
        <section className="card solid">
          <h4>{t("upd.risks")}</h4>
          {b.risks.length ? <ul className="upd-ul warn">{b.risks.map((h, i) => <li key={i}>{h}</li>)}</ul> : <span className="muted">{t("upd.norisks")}</span>}
        </section>
      </div>
      {b.kpis.length > 0 && (
        <section className="card solid">
          <h4>{t("upd.kpi.h")}</h4>
          <KpiTable kpis={b.kpis} />
          <span className="muted-sm">{t("upd.selfrep")}</span>
        </section>
      )}
      {b.note && (
        <section className="card solid">
          <h4>{t("upd.note")}</h4>
          <p style={{ margin: 0, whiteSpace: "pre-wrap" }}>{b.note}</p>
        </section>
      )}
    </div>
  );
}

/* ---------- proof: recorded on blockchain + check in the browser ---------- */
function stable(v: unknown): string {
  if (Array.isArray(v)) return "[" + v.map(stable).join(",") + "]";
  if (v && typeof v === "object") return "{" + Object.keys(v).sort().map((k) => JSON.stringify(k) + ":" + stable((v as Record<string, unknown>)[k])).join(",") + "}";
  return JSON.stringify(v ?? null);
}
function bodyOf(b: UpdateBody) {
  return { summary: b.summary, highlights: b.highlights, risks: b.risks, note: b.note,
    kpis: b.kpis.map((k) => ({ metric: k.metric, value: k.value, prev: k.prev, change_pct: k.change_pct, unit: k.unit })) };
}
type Check = { text: boolean; fp: boolean; chain: boolean | null };

async function runCheck(u: BizUpdate): Promise<Check> {
  const full = u.canonical ? u : await api.update(u.id);
  const canon = full.canonical ?? "";
  const parsed = parseLossless(canon);
  const again = canonicalJson(parsed);
  const fp = again === canon && !!full.content_hash && sha256(toBytes(again)) === full.content_hash.toLowerCase();
  const p = plain(parsed) as { title?: string; ticker?: string; body?: UpdateBody; period_end?: string };
  const text = p.title === u.title && p.ticker === u.ticker && p.period_end === u.period_end && !!p.body && stable(bodyOf(p.body)) === stable(bodyOf(u.body));
  let chain: boolean | null = null;
  const tx = full.anchor?.tx_hash;
  const want = full.content_hash ? ("0x424944550000" + full.content_hash.slice(2)).toLowerCase() : "";
  if (tx && !isMock) {
    try {
      const r = await fetch("/api/v1/rpc", { method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ jsonrpc: "2.0", id: 1, method: "eth_getTransactionByHash", params: [tx] }) });
      const j = (await r.json()) as { result?: { input?: string } | null };
      if (j.result?.input) chain = j.result.input.toLowerCase() === want;
    } catch { chain = null; }
  }
  return { text, fp, chain };
}

export function RecordBox({ u }: { u: BizUpdate }) {
  const { t, fmt } = useI18n();
  const [res, setRes] = useState<Check | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const tx = u.anchor?.tx_hash;
  const ok = res && res.text && res.fp && res.chain !== false;
  return (
    <section className="card upd-rec">
      <h4>{t("upd.rec.h")}</h4>
      {!tx ? <p className="muted" style={{ margin: 0 }}>{t("upd.rec.none")}</p> : (
        <>
          <p className="sub" style={{ margin: 0 }}>{t("upd.rec.p")}</p>
          <p style={{ margin: 0 }}>
            <a href={CHAINS.local.txUrl(tx)} target="_blank" rel="noopener noreferrer">{t("upd.rec.tx")} ↗</a>
            <span className="muted-sm"> · BlockID Chain{u.anchor?.block ? " · " + t("upd.rec.block", { b: fmt(u.anchor.block) }) : ""}</span>
          </p>
          {u.content_hash && <p className="muted-sm mono" style={{ margin: 0, overflowWrap: "anywhere" }}>{t("upd.rec.fp")}: {u.content_hash}</p>}
          <div className="row">
            <button className="btn sm" type="button" disabled={busy} onClick={async () => {
              setBusy(true); setErr(""); setRes(null);
              try { setRes(await runCheck(u)); } catch (e) { setErr(errText(e, t)); } finally { setBusy(false); }
            }}>{busy ? t("upd.chk.busy") : t("upd.chk.btn")}</button>
          </div>
          {res && (
            <ul className="upd-check" aria-live="polite">
              <li className={res.text ? "ok" : "bad"}>{res.text ? "✓" : "✗"} {t("upd.chk.text")}</li>
              <li className={res.fp ? "ok" : "bad"}>{res.fp ? "✓" : "✗"} {t("upd.chk.fp")}</li>
              <li className={res.chain === null ? "" : res.chain ? "ok" : "bad"}>{res.chain === null ? "–" : res.chain ? "✓" : "✗"} {res.chain === null ? t("upd.chk.chainSkip") : t("upd.chk.chain")}</li>
            </ul>
          )}
          {res && <p className={"banner " + (ok ? "ok" : "bad")} role="status">{ok ? t("upd.chk.ok") : t("upd.chk.bad")}</p>}
          {err && <p className="err" role="alert">{err}</p>}
        </>
      )}
    </section>
  );
}

/* ---------- investor: one update page (/i/u/:id), feeds ---------- */
export function UpdatePage({ id }: { id: string }) {
  const { t, date } = useI18n();
  const nav = useNavigate();
  const q = useAsync(() => api.update(id), [id]);
  const u = q.data;
  useTitle(u ? u.title : t("upd.list.h"));
  if (q.loading && !u) return <Loading />;
  if (!u) {
    return (
      <div className="wrap page inv">
        <p className="banner warn" role="status">{t("upd.page.missing")}</p>
        <Link className="btn ghost sm" to="/i" style={{ justifySelf: "start" }}>{t("upd.page.back")}</Link>
      </div>
    );
  }
  return (
    <div className="wrap page inv">
      <nav className="crumbs" aria-label={t("in.crumbs")}>
        <a href="/i" onClick={(e) => { e.preventDefault(); if (window.history.length > 1) nav(-1); else nav("/i"); }}>{t("upd.page.back")}</a> / <Link to={`/c/${u.ticker}/updates`}>{u.ticker}</Link> / <span>{u.period_label}</span>
      </nav>
      <div className="head">
        <span className="eyebrow">{u.ticker} · {u.company} · {t(("upd.cad." + u.cadence) as DictKey)}</span>
        <h2>{u.title}</h2>
        <p className="row" style={{ gap: 8 }}>{u.status !== "published" && <StatusPill s={u.status} />}{u.published_at ? t("upd.published", { d: date(u.published_at) }) : ""}</p>
      </div>
      <UpdateView u={u} />
      <RecordBox u={u} />
      <p className="muted-sm">{t("upd.legal")}</p>
    </div>
  );
}

/** "Latest updates" on the portfolio: updates of the businesses the viewer holds. */
export function UpdateFeed({ demo }: { demo: boolean }) {
  const { t } = useI18n();
  const q = useAsync(() => (demo ? api.demoUpdates() : api.myUpdates()), [demo], 120000);
  const list = q.data?.updates ?? [];
  return (
    <section className="stack">
      <div className="head" style={{ marginTop: 8 }}>
        <h3>{t("upd.feed.h")}</h3>
        <p>{t("upd.feed.p")}</p>
      </div>
      {q.error ? <ErrorBox error={q.error} retry={q.reload} /> : q.loading && !q.data ? <p className="note">{t("common.loading")}</p> :
        list.length === 0 ? <p className="note">{t("upd.feed.empty")}</p> : (
          <div className="upd-list">{list.slice(0, 6).map((u) => <UpdateCard key={u.id} u={u} to={`/i/u/${u.id}`} showCo />)}</div>
        )}
    </section>
  );
}

/** Published updates of one business (investor position view). */
export function CompanyUpdateList({ ticker }: { ticker: string }) {
  const { t } = useI18n();
  const q = useAsync(() => api.companyUpdates(ticker), [ticker]);
  const list = (q.data?.updates ?? []).filter((u) => u.status === "published");
  return (
    <section className="card">
      <h4>{t("upd.pos.h")}</h4>
      {q.error ? <ErrorBox error={q.error} retry={q.reload} /> : q.loading && !q.data ? <span className="muted">{t("common.loading")}</span> :
        list.length === 0 ? <span className="muted">{t("upd.pos.empty")}</span> : (
          <div className="upd-list">{list.map((u) => <UpdateCard key={u.id} u={u} to={`/i/u/${u.id}`} />)}</div>
        )}
    </section>
  );
}

/* ---------- founder / company workspace: /c/:tk/updates ---------- */
function lastMonthEnd(): string {
  const d = new Date();
  const e = new Date(d.getFullYear(), d.getMonth(), 0);
  return `${e.getFullYear()}-${String(e.getMonth() + 1).padStart(2, "0")}-${String(e.getDate()).padStart(2, "0")}`;
}

function PrepareForm({ c, onDone }: { c: CompanyDetail; onDone: (u: BizUpdate) => void }) {
  const { t } = useI18n();
  const [cadence, setCadence] = useState<Cadence>("monthly");
  const [end, setEnd] = useState(lastMonthEnd());
  const [vals, setVals] = useState<Record<Metric, string>>(() => Object.fromEntries(METRICS.map((m) => [m, ""])) as Record<Metric, string>);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; s: string } | null>(null);
  const kp = useAsync(() => api.kpis(c.ticker), [c.ticker]);
  const existing = useMemo(() => kp.data?.periods.find((p) => p.period_end === end)?.values, [kp.data, end]);
  useEffect(() => {
    setVals(Object.fromEntries(METRICS.map((m) => [m, existing?.[m] != null ? String(existing[m]) : ""])) as Record<Metric, string>);
  }, [existing]);
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    const kpis: Partial<Record<Metric, number | null>> = {};
    for (const m of METRICS) {
      const v = vals[m].trim().replace(/,/g, "");
      if (v !== "" && Number.isFinite(Number(v))) kpis[m] = Number(v);
      else if (existing?.[m] != null) kpis[m] = null; // cleared -> remove the stored value
    }
    if (!Object.values(kpis).some((v) => v != null)) { setMsg({ ok: false, s: t("upd.f.need") }); return; }
    setBusy(true); setMsg(null);
    try {
      const u = await api.prepareUpdate(c.ticker, { cadence, period_end: end, kpis, note: note.trim() });
      setMsg({ ok: true, s: t("upd.f.prepared") });
      void kp.reload();
      onDone(u);
    } catch (x) { setMsg({ ok: false, s: errText(x, t) }); } finally { setBusy(false); }
  };
  return (
    <form className="card solid" onSubmit={submit} noValidate>
      <h4>{t("upd.f.h")}</h4>
      <p className="sub">{t("upd.f.p")}</p>
      <div className="fgrid">
        <label className="lf"><span>{t("upd.f.cadence")}</span>
          <select value={cadence} onChange={(e) => setCadence(e.target.value as Cadence)}>
            {CADENCES.map((x) => <option key={x} value={x}>{t(("upd.cad." + x) as DictKey)}</option>)}
          </select>
        </label>
        <label className="lf"><span>{t("upd.f.end")}</span><input type="date" value={end} onChange={(e) => setEnd(e.target.value)} /></label>
        {METRICS.map((m) => (
          <label key={m} className="lf"><span>{t(("upd.m." + m) as DictKey)} <span className="muted-sm">({t(m === "customers" || m === "headcount" ? "upd.unit.count" : "upd.unit.aud")})</span></span>
            <input type="number" inputMode="decimal" step="any" min={m === "net_profit" || m === "gross_profit" ? undefined : 0} value={vals[m]} onChange={(e) => setVals((v) => ({ ...v, [m]: e.target.value }))} />
          </label>
        ))}
      </div>
      {existing && <span className="hint">{t("upd.f.loaded")}</span>}
      <label className="lf"><span>{t("upd.f.note")}</span><textarea value={note} maxLength={2000} placeholder={t("upd.f.notePh")} onChange={(e) => setNote(e.target.value)} /></label>
      <button className="btn" type="submit" disabled={busy} style={{ justifySelf: "start" }}>{t("upd.f.prepare")}</button>
      {msg && <p className={msg.ok ? "toast" : "err"} role={msg.ok ? "status" : "alert"}>{msg.s}</p>}
    </form>
  );
}

function DraftEditor({ u, onChanged }: { u: BizUpdate; onChanged: () => void }) {
  const { t } = useI18n();
  const [title, setTitle] = useState(u.title);
  const [summary, setSummary] = useState(u.body.summary);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; s: string } | null>(null);
  const dirty = title !== u.title || summary !== u.body.summary;
  const run = async (fn: () => Promise<unknown>, ok: string) => {
    setBusy(true); setMsg(null);
    try { await fn(); setMsg({ ok: true, s: ok }); onChanged(); } catch (x) { setMsg({ ok: false, s: errText(x, t) }); } finally { setBusy(false); }
  };
  return (
    <div className="stack">
      {u.status === "rejected" && u.reason && <p className="banner warn" role="status">{t("upd.rejected", { r: u.reason })}</p>}
      <label className="lf"><span>{t("upd.edit.title")}</span><input value={title} maxLength={200} onChange={(e) => setTitle(e.target.value)} /></label>
      <label className="lf"><span>{t("upd.edit.summary")}</span><textarea value={summary} maxLength={2000} rows={3} onChange={(e) => setSummary(e.target.value)} /></label>
      <div className="row">
        <button className="btn ghost sm" type="button" disabled={busy || !dirty || !title.trim()} onClick={() => run(() => api.editUpdate(u.id, { title, summary }), t("upd.edit.saved"))}>{t("upd.edit.save")}</button>
        <span className="grow" />
        <button className="btn gold sm" type="button" disabled={busy || !title.trim()} onClick={() => run(async () => { if (dirty) await api.editUpdate(u.id, { title, summary }); await api.submitUpdate(u.id); }, t("upd.sent"))}>{t("upd.send")} ◆</button>
      </div>
      {msg && <p className={msg.ok ? "toast" : "err"} role={msg.ok ? "status" : "alert"}>{msg.s}</p>}
    </div>
  );
}

function ManagedUpdate({ u, open, onToggle, onChanged }: { u: BizUpdate; open: boolean; onToggle: () => void; onChanged: () => void }) {
  const { t } = useI18n();
  const editable = u.status === "draft" || u.status === "rejected";
  return (
    <div className="pane upd-item">
      <div className="between">
        <span><b>{u.title}</b> <span className="muted-sm">· {t("upd.period", { c: t(("upd.cad." + u.cadence) as DictKey), p: u.period_label })}</span></span>
        <span className="row" style={{ gap: 8 }}>
          <StatusPill s={u.status} />
          {u.status === "published" ? <Link className="btn ghost sm" to={`/i/u/${u.id}`}>{t("upd.open")}</Link>
            : <button className="btn ghost sm" type="button" aria-expanded={open} onClick={onToggle}>{open ? "▴" : "▾"} {t("upd.open")}</button>}
        </span>
      </div>
      {u.status === "failed" && u.error && <p className="banner warn">{t("upd.failed", { e: u.error })}</p>}
      {u.created_by && <span className="muted-sm">{t("upd.by", { w: shortAddr(u.created_by) || u.created_by })}</span>}
      {open && u.status !== "published" && (
        <>
          {editable && <DraftEditor key={u.updated_at} u={u} onChanged={onChanged} />}
          <UpdateView u={u} />
        </>
      )}
    </div>
  );
}

export function CompanyUpdates({ c, canManage, live }: { c: CompanyDetail; canManage: boolean; live: boolean }) {
  const { t } = useI18n();
  const q = useAsync(() => api.companyUpdates(c.ticker), [c.ticker, canManage], 20000);
  const [openId, setOpenId] = useState<string | null>(null);
  const list = q.data?.updates ?? [];
  const manage = canManage && !!q.data?.can_manage;
  useEffect(() => { if (!openId && manage) { const d = list.find((u) => u.status === "draft" || u.status === "rejected"); if (d) setOpenId(d.id); } }, [q.data]); // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <div className="stack">
      {manage && live && <PrepareForm c={c} onDone={(u) => { setOpenId(u.id); void q.reload(); }} />}
      {manage && !live && <p className="quietline">{t("upd.f.onlylive")}</p>}
      {!manage && <p className="note">{t("upd.f.viewer")}</p>}
      <div className="pane">
        <h4>{t("upd.list.h")}</h4>
        {manage && <span className="muted-sm">{t("upd.list.mine")}</span>}
        {q.error ? <ErrorBox error={q.error} retry={q.reload} /> : q.loading && !q.data ? <span className="muted">{t("common.loading")}</span> :
          list.length === 0 ? <span className="muted">{t("upd.list.empty")}</span> : manage ? (
            <div className="stack">{list.map((u) => <ManagedUpdate key={u.id} u={u} open={openId === u.id} onToggle={() => setOpenId(openId === u.id ? null : u.id)} onChanged={() => void q.reload()} />)}</div>
          ) : (
            <div className="upd-list">{list.map((u) => <UpdateCard key={u.id} u={u} to={`/i/u/${u.id}`} />)}</div>
          )}
      </div>
      <p className="muted-sm">{t("upd.legal")}</p>
    </div>
  );
}
