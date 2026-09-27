import { useState } from "react";
import { useI18n } from "../i18n";
import type { DictKey } from "../dict";
import { PERSON_KINDS } from "../api";
import { emptyRow, equityTotal, MAX_PEOPLE, THIS_YEAR, type Errs, type FieldErr, type PersonRow } from "../lib/people";
import "./hr.css";

export const ROLE_SUGGESTIONS = ["CEO", "CTO", "COO", "CFO", "CPO", "CMO", "Head of Sales", "Head of Engineering", "Head of Product", "Chair", "Board member", "Advisor"];

/** Show a field error: always for a typed bad value; for a missing required value only after blur or a submit attempt. */
export function useTouched() {
  const [touched, setTouched] = useState<Set<string>>(new Set());
  const touch = (k: string) => setTouched((s) => (s.has(k) ? s : new Set(s).add(k)));
  return { touched, touch };
}

export function FieldError({ id, err }: { id: string; err?: FieldErr | null }) {
  const { t } = useI18n();
  return <span id={id} className="hr-ferr" role={err ? "alert" : undefined}>{err ? t(err.k, err.v) : ""}</span>;
}

/**
 * Editable list of people (name, role, type, full-time, start year, equity, links, bio).
 * `errs` comes from validateRows; `showAll` reveals required-field errors after a submit attempt.
 */
export function PeopleEditor({ rows, setRows, errs, showAll, idPrefix = "pe" }: {
  rows: PersonRow[]; setRows: (f: (r: PersonRow[]) => PersonRow[]) => void; errs: Errs; showAll: boolean; idPrefix?: string;
}) {
  const { t, fmt } = useI18n();
  const { touched, touch } = useTouched();
  const set = (key: string, patch: Partial<PersonRow>) => setRows((rs) => rs.map((r) => (r.key === key ? { ...r, ...patch } : r)));
  const shown = (r: PersonRow, f: keyof PersonRow): FieldErr | null => {
    const e = errs[r.key + "." + f];
    if (!e) return null;
    const val = String(r[f] ?? "").trim();
    return val || showAll || touched.has(r.key + "." + f) ? e : null;
  };
  const eq = equityTotal(rows);
  const teamErr = errs["team.equity"] ?? errs["team.founder"] ?? (showAll ? errs["team.max"] : undefined);
  const listId = idPrefix + "-roles";

  const input = (r: PersonRow, f: keyof PersonRow, label: DictKey, extra: React.InputHTMLAttributes<HTMLInputElement> = {}) => {
    const e = shown(r, f);
    const id = `${idPrefix}-${r.key}-${f}`;
    return (
      <label className={"lf hr-f" + (e ? " bad" : "")}>
        <span>{t(label)}</span>
        <input className={"inp" + (e ? " bad" : "")} id={id} value={String(r[f] ?? "")} aria-invalid={!!e} aria-describedby={id + "-e"}
          onChange={(ev) => set(r.key, { [f]: ev.target.value } as Partial<PersonRow>)} onBlur={() => touch(r.key + "." + f)} {...extra} />
        <FieldError id={id + "-e"} err={e} />
      </label>
    );
  };

  return (
    <div className="hr-people">
      <datalist id={listId}>{ROLE_SUGGESTIONS.map((x) => <option key={x} value={x} />)}</datalist>
      {rows.map((r, i) => {
        const linksErr = shown(r, "links"), bioErr = shown(r, "bio");
        return (
          <fieldset key={r.key} className="hr-prow">
            <legend className="sr-only">{t("hr.p.person", { n: i + 1 })}</legend>
            <div className="hr-prow-head">
              <b>{t("hr.p.person", { n: i + 1 })}</b>
              <label className="hr-kind">
                <span className="sr-only">{t("hr.p.kind")}</span>
                <select className="inp" value={r.kind} aria-label={t("hr.p.kind")} onChange={(e) => set(r.key, { kind: e.target.value as PersonRow["kind"] })}>
                  {PERSON_KINDS.map((k) => <option key={k} value={k}>{t(("hr.kind." + k) as DictKey)}</option>)}
                </select>
              </label>
              {rows.length > 1 && <button type="button" className="btn ghost sm" onClick={() => setRows((rs) => rs.filter((x) => x.key !== r.key))}>{t("hr.p.remove")}</button>}
            </div>
            <div className="hr-pgrid">
              {input(r, "full_name", "hr.p.name", { autoComplete: "off", maxLength: 140, required: true })}
              {input(r, "role", "hr.p.role", { list: listId, placeholder: t("hr.p.role.ph"), maxLength: 100 })}
              <label className="lf hr-f">
                <span>{t("hr.p.ft")}</span>
                <select className="inp" value={r.full_time} onChange={(e) => set(r.key, { full_time: e.target.value as PersonRow["full_time"] })}>
                  <option value="">{t("hr.p.ft.unknown")}</option>
                  <option value="yes">{t("hr.p.ft.yes")}</option>
                  <option value="no">{t("hr.p.ft.no")}</option>
                </select>
                <span className="hr-ferr" />
              </label>
              {input(r, "start_year", "hr.p.year", { inputMode: "numeric", placeholder: String(THIS_YEAR - 3), maxLength: 4 })}
              {input(r, "equity_pct", "hr.p.equity", { inputMode: "decimal", placeholder: "0–100", maxLength: 6 })}
              {input(r, "linkedin", "hr.p.linkedin", { type: "url", inputMode: "url", placeholder: "linkedin.com/in/…", spellCheck: false })}
            </div>
            <label className={"lf hr-f" + (linksErr ? " bad" : "")}>
              <span>{t("hr.p.links")}</span>
              <textarea className={"inp" + (linksErr ? " bad" : "")} rows={2} value={r.links} placeholder={t("hr.p.links.ph")} spellCheck={false} aria-invalid={!!linksErr}
                aria-describedby={`${idPrefix}-${r.key}-links-e`} onChange={(e) => set(r.key, { links: e.target.value })} onBlur={() => touch(r.key + ".links")} />
              <FieldError id={`${idPrefix}-${r.key}-links-e`} err={linksErr} />
            </label>
            <label className={"lf hr-f" + (bioErr ? " bad" : "")}>
              <span>{t("hr.p.bio")} <span className="muted-sm">{fmt(r.bio.length)}/1,500</span></span>
              <textarea className={"inp" + (bioErr ? " bad" : "")} rows={2} value={r.bio} placeholder={t("hr.p.bio.ph")} aria-invalid={!!bioErr}
                aria-describedby={`${idPrefix}-${r.key}-bio-e`} onChange={(e) => set(r.key, { bio: e.target.value })} />
              <FieldError id={`${idPrefix}-${r.key}-bio-e`} err={bioErr} />
            </label>
          </fieldset>
        );
      })}
      <div className="between">
        <button type="button" className="btn ghost sm" disabled={rows.length >= MAX_PEOPLE} onClick={() => setRows((rs) => [...rs, emptyRow(rs.length === 0 ? "founder" : "cofounder")])}>+ {t("hr.p.add")}</button>
        {eq > 0 && <span className={"muted-sm" + (errs["team.equity"] ? " hr-bad" : "")}>{t("hr.p.equity.total", { p: fmt(eq, eq % 1 ? 1 : 0) })}</span>}
      </div>
      {teamErr && <p className="err" role="alert" style={{ margin: 0 }}>{t(teamErr.k, teamErr.v)}</p>}
    </div>
  );
}

/** The required consent checkbox. */
export function ConsentBox({ checked, onChange, showErr }: { checked: boolean; onChange: (v: boolean) => void; showErr: boolean }) {
  const { t } = useI18n();
  const bad = showErr && !checked;
  return (
    <div className={"hr-consent" + (bad ? " bad" : "")}>
      <label>
        <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} aria-invalid={bad} aria-describedby="hr-consent-sub" required />
        <span><b>{t("hr.p.consent")}</b><small id="hr-consent-sub">{t("hr.p.consent.sub")}</small></span>
      </label>
      {bad && <span className="hr-ferr" role="alert">{t("hr.e.consent")}</span>}
    </div>
  );
}

/** Count of the errors that block submit. */
export const errCount = (e: Errs) => Object.keys(e).length;
