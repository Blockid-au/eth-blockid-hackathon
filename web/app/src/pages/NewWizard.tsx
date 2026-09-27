import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { useI18n } from "../i18n";
import { errText, useAuth } from "../auth";
import { api, ApiError, type SelfReported } from "../api";
import { Crumbs, FlowRail, Pager, SideLayout, StepHead } from "../components/Shell";
import { useAsync, useTitle } from "../lib/hooks";
import { en, type DictKey } from "../dict";
import { cleanInput, parseSelfReported, SR_FIELDS, type SrField } from "../lib/selfReported";
import { checkUrlClient } from "../lib/urlcheck";

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
  const [url, setUrl] = useState(() => (params.get("url") ?? "").slice(0, 2048));
  const [err, setErr] = useState("");
  const [bad, setBad0] = useState<UrlProblem | null>(null);
  const [busy, setBusy] = useState<"" | "check" | "start">("");
  const [raw, setRaw] = useState<SrRaw>({});
  const [badSr, setBad] = useState<Set<string>>(new Set());
  const input = useRef<HTMLInputElement>(null);
  useTitle(t(listing ? "new.eyebrow.list" : "new.eyebrow"));

  const fail = (p: UrlProblem) => { setBad0(p); input.current?.focus(); };
  const reasonText = (r: string | null | undefined) => (r && ("url." + r) in en ? t(("url." + r) as DictKey) : t("new.bad.url"));

  const start = async (e: React.FormEvent) => {
    e.preventDefault();
    setErr(""); setBad0(null);
    const c = checkUrlClient(url);
    if (!c.ok) { fail({ msg: reasonText(c.reason), suggestion: c.suggestion }); return; }
    const sr = parseSelfReported(raw);
    setBad(new Set(sr.bad.map((f) => f.key)));
    if (sr.bad.length) { setErr(t("sr.bad", { f: sr.bad.map((f) => t(f.label)).join(", ") })); return; }
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
      if (r.url) target = r.url.replace(/\/$/, "");
    } catch (x) {
      // 429: stop here; an older API without the check (404/405) or a network blip: let the valuation decide
      if (x instanceof ApiError && x.status === 429) { fail({ msg: t("url.rate") }); setBusy(""); return; }
    }
    setBusy("start");
    try {
      if (!me) await connect();
      const { id } = await api.createValuation(target, sr.metrics);
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
      <StepHead eyebrow={t("flow.stepof", { n: 1, p: t("flow.ph.a") })} title={t(listing ? "new.h2.list" : "new.h2")} desc={t(listing ? "new.p.list" : "new.p")} />
      <form className="panel" onSubmit={start} noValidate>
        <div className="ptitle"><div><h3>{t("s1.h")}</h3><p>{t("s1.p")}</p></div></div>
        <div className="field">
          <input ref={input} type="url" inputMode="url" autoComplete="url" spellCheck={false} placeholder="yourcompany.com.au" aria-label={t("c.website")} value={url}
            onChange={(e) => { setUrl(e.target.value); if (bad) setBad0(null); }} aria-invalid={!!bad} aria-describedby="url-err" autoFocus />
          <button className="btn" type="submit" disabled={!!busy} aria-busy={!!busy}>{busy ? <span className="spinner" aria-hidden="true" /> : null}{busy === "check" ? t("url.checking") : busy === "start" ? t("new.starting") : me ? t("s1.btn") : t("nav.connect") + " · " + t("s1.btn")}</button>
        </div>
        <div id="url-err" role="alert" className="urlhint">
          {bad && <span className="err" style={{ minHeight: 0 }}>{bad.msg}{bad.suggestion ? " " + t("url.didyou", { h: bad.suggestion }) : ""}</span>}
          {bad?.suggestion && <button type="button" className="btn ghost sm" onClick={() => applySuggestion(bad.suggestion!)}>{t("url.use", { h: bad.suggestion })}</button>}
        </div>
        {err && <p className="err" role="alert">{err}</p>}
        <SelfReportedFields raw={raw} setRaw={setRaw} bad={badSr} />
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
