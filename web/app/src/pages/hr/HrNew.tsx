import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { useI18n } from "../../i18n";
import { errText, useAuth } from "../../auth";
import { api, ApiError } from "../../api";
import { ConsentBox, FieldError, PeopleEditor } from "../../components/PeopleEditor";
import { emptyRow, normUrl, parseValuationRef, rowUsed, toPersonIn, validateRows, type Errs, type PersonRow } from "../../lib/people";
import { ethUrl } from "../../lib/hrhost";
import { useHrTitle } from "./common";
import { handedPeople } from "./parse";

/** /new — review a founding team (standalone or for a business valuation). */
export function HrNew() {
  const { t } = useI18n();
  const { me, tryDemo } = useAuth();
  const nav = useNavigate();
  const [params] = useSearchParams();
  const [name, setName] = useState("");
  const [website, setWebsite] = useState("");
  const [valRef, setValRef] = useState(() => (params.get("valuation") ?? "").slice(0, 200));
  const [rows, setRows] = useState<PersonRow[]>(() => {
    const handed = handedPeople(params);
    return handed.length ? handed.map((p) => ({ ...emptyRow(p.kind), full_name: p.full_name, role: p.role })) : [emptyRow("founder"), emptyRow("cofounder")];
  });
  const [consent, setConsent] = useState(false);
  const [tried, setTried] = useState(false);
  const [touched, setTouched] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const formRef = useRef<HTMLFormElement>(null);
  useHrTitle(t("hr.new.h1"));

  // prefill from the linked valuation (name + website)
  useEffect(() => {
    const id = parseValuationRef(params.get("valuation") ?? "");
    if (!id) return;
    api.valuation(id).then((v) => {
      const pn = typeof v.profile?.name === "string" ? v.profile.name : "";
      setName((n) => n || pn || new URL(v.url).hostname.replace(/^www\./, "").split(".")[0].replace(/^\w/, (c) => c.toUpperCase()));
      setWebsite((w) => w || v.url.replace(/^https?:\/\//, "").replace(/\/$/, ""));
    }).catch(() => undefined);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const errs: Errs = useMemo(() => {
    const e = validateRows(rows, { requireOne: true });
    if (!name.trim()) e["team.name"] = { k: "hr.e.teamname" };
    else if (name.trim().length > 120) e["team.name"] = { k: "hr.e.name.long" };
    if (website.trim() && !normUrl(website)) e["team.website"] = { k: "hr.e.website" };
    if (valRef.trim() && !parseValuationRef(valRef)) e["team.valuation"] = { k: "hr.e.val" };
    if (!consent) e["team.consent"] = { k: "hr.e.consent" };
    return e;
  }, [rows, name, website, valRef, consent]);
  const show = (k: string, val: string) => (errs[k] && (val.trim() || tried || touched.has(k)) ? errs[k] : null);
  const touch = (k: string) => setTouched((s) => new Set(s).add(k));

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
      const people = rows.filter(rowUsed).map(toPersonIn);
      let team = await api.hrCreateTeam({ name: name.trim(), website: website.trim() ? normUrl(website) : null, valuation_id: parseValuationRef(valRef), people, consent: true, run: true });
      if (team.status === "draft") team = await api.hrRun(team.id);
      nav(`/r/${encodeURIComponent(team.id)}`);
    } catch (x) {
      setErr(x instanceof ApiError && x.status === 429 ? t("hr.new.limit") : errText(x, t));
    } finally {
      setBusy(false);
    }
  };

  const nameErr = show("team.name", name), webErr = show("team.website", website), valErr = show("team.valuation", valRef);
  return (
    <div className="wrap page">
      <div className="shead" style={{ marginBottom: 18 }}>
        <div>
          <span className="eyebrow">{t("hr.new.eyebrow")}</span>
          <h1>{t("hr.new.h1")}</h1>
          <p>{t("hr.new.p")}</p>
        </div>
      </div>
      <form ref={formRef} className="panel hr-form" onSubmit={submit} noValidate>
        <section className="hr-sec" aria-labelledby="hr-sec-team">
          <h3 id="hr-sec-team">{t("hr.new.team")}</h3>
          <div className="hr-g3">
            <label className={"lf hr-f" + (nameErr ? " bad" : "")}>
              <span>{t("hr.new.name")}</span>
              <input className={"inp" + (nameErr ? " bad" : "")} value={name} maxLength={140} onChange={(e) => setName(e.target.value)} onBlur={() => touch("team.name")} aria-invalid={!!nameErr} aria-describedby="hr-name-e" required autoComplete="organization" />
              <FieldError id="hr-name-e" err={nameErr} />
            </label>
            <label className={"lf hr-f" + (webErr ? " bad" : "")}>
              <span>{t("hr.new.website")}</span>
              <input className={"inp mono" + (webErr ? " bad" : "")} value={website} inputMode="url" spellCheck={false} placeholder="company.com.au" onChange={(e) => setWebsite(e.target.value)} aria-invalid={!!webErr} aria-describedby="hr-web-e" />
              <FieldError id="hr-web-e" err={webErr} />
            </label>
            <label className={"lf hr-f" + (valErr ? " bad" : "")}>
              <span>{t("hr.new.val")}</span>
              <input className={"inp mono" + (valErr ? " bad" : "")} value={valRef} spellCheck={false} placeholder={t("hr.new.val.ph")} onChange={(e) => setValRef(e.target.value)} aria-invalid={!!valErr} aria-describedby="hr-val-e hr-val-h" />
              <FieldError id="hr-val-e" err={valErr} />
              {!valErr && <small id="hr-val-h" className="muted-sm">{t("hr.new.val.hint")}{parseValuationRef(valRef) ? <> · <a href={ethUrl(`/v/${encodeURIComponent(parseValuationRef(valRef)!)}/report`)}>{parseValuationRef(valRef)} ↗</a></> : null}</small>}
            </label>
          </div>
        </section>
        <section className="hr-sec" aria-labelledby="hr-sec-people">
          <h3 id="hr-sec-people">{t("hr.new.people")}</h3>
          <p>{t("hr.new.people.p")}</p>
          <PeopleEditor rows={rows} setRows={setRows} errs={errs} showAll={tried} idPrefix="hrn" />
        </section>
        <ConsentBox checked={consent} onChange={setConsent} showErr={tried} />
        <div className="hr-submit">
          <button className="btn" type="submit" disabled={busy} aria-busy={busy}>{busy ? <span className="spinner" aria-hidden="true" /> : null}{busy ? t("hr.new.starting") : t("hr.new.submit")}</button>
          <Link className="btn ghost" to="/new/person">{t("hr.nav.person")}</Link>
          {err && <span className="err" role="alert">{err}</span>}
        </div>
        {!me && <p className="quietline" style={{ margin: 0 }}>{t("hr.new.signin")}</p>}
      </form>
    </div>
  );
}
