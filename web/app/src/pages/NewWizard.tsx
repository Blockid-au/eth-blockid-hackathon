import { useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useI18n } from "../i18n";
import { errText, useAuth } from "../auth";
import { api, ApiError, type SelfReported } from "../api";
import { Stepper } from "../components/Stepper";
import { useAsync, useTitle } from "../lib/hooks";
import type { DictKey } from "../dict";
import { cleanInput, parseSelfReported, SR_FIELDS, type SrField } from "../lib/selfReported";

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

function normUrl(s: string): string | null {
  let u = s.trim();
  if (!u) return null;
  if (!/^https?:\/\//i.test(u)) u = "https://" + u;
  try {
    const x = new URL(u);
    if (!x.hostname.includes(".") || x.hostname.length < 4) return null;
    return x.toString().replace(/\/$/, "");
  } catch {
    return null;
  }
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

export default function NewWizard() {
  const { t } = useI18n();
  const { me, connect } = useAuth();
  const nav = useNavigate();
  const [url, setUrl] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const [raw, setRaw] = useState<SrRaw>({});
  const [bad, setBad] = useState<Set<string>>(new Set());
  useTitle(t("new.eyebrow"));

  const start = async (e: React.FormEvent) => {
    e.preventDefault();
    setErr("");
    const u = normUrl(url);
    if (!u) { setErr(t("new.bad.url")); return; }
    const sr = parseSelfReported(raw);
    setBad(new Set(sr.bad.map((f) => f.key)));
    if (sr.bad.length) { setErr(t("sr.bad", { f: sr.bad.map((f) => t(f.label)).join(", ") })); return; }
    setBusy(true);
    try {
      if (!me) await connect();
      const { id } = await api.createValuation(u, sr.metrics);
      nav(`/v/${encodeURIComponent(id)}`);
    } catch (x) {
      setErr(x instanceof ApiError && x.status === 429 ? t("new.limit") : errText(x, t));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="block" style={{ borderTop: 0, paddingTop: 40 }}>
      <div className="wrap">
        <div className="head">
          <span className="eyebrow">{t("new.eyebrow")}</span>
          <h2>{t("new.h2")}</h2>
          <p>{t("new.p")}</p>
        </div>
        <Stepper cur={1} done={0} />
        <form className="panel" onSubmit={start} noValidate>
          <div className="ptitle"><div><h3>{t("s1.h")}</h3><p>{t("s1.p")}</p></div></div>
          <div className="field">
            <input type="url" inputMode="url" autoComplete="url" placeholder="https://yourcompany.com.au" aria-label="Company website" value={url} onChange={(e) => setUrl(e.target.value)} aria-invalid={!!err} aria-describedby="url-err" autoFocus />
            <button className="btn" type="submit" disabled={busy}>{busy ? <span className="spinner" aria-hidden="true" /> : null}{busy ? t("new.starting") : me ? t("s1.btn") : t("nav.connect") + " · " + t("s1.btn")}</button>
          </div>
          <p className="err" id="url-err" role="alert">{err}</p>
          <SelfReportedFields raw={raw} setRaw={setRaw} bad={bad} />
          {!me && <p className="banner gold">{t("new.signin")}</p>}
          <div className="cols3">
            <div className="card"><h4>{t("s1.c1")}</h4><p className="sub">{t("s1.c1p")}</p></div>
            <div className="card"><h4>{t("s1.c2")}</h4><p className="sub">{t("s1.c2p")}</p></div>
            <div className="card"><h4>{t("s1.c3")}</h4><p className="sub">{t("s1.c3p")}</p></div>
          </div>
        </form>
        {me && <Mine />}
      </div>
    </section>
  );
}
