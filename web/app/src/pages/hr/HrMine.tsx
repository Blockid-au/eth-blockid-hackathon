import { Link } from "react-router-dom";
import { useI18n } from "../../i18n";
import type { DictKey } from "../../dict";
import { errText, useAuth } from "../../auth";
import { api } from "../../api";
import { ErrorBox, Loading } from "../../components/Layout";
import { useAsync } from "../../lib/hooks";
import { ACTIVE_HR, statusPill, useHrTitle } from "./common";
import { bandOf } from "./evidence";
import { useState } from "react";

/** /me — the reports this account asked for. */
export function HrMine() {
  const { t, fmt, date } = useI18n();
  const { me, loading, tryDemo, connect, busy } = useAuth();
  const [err, setErr] = useState("");
  const q = useAsync(() => (me ? api.hrMyTeams() : Promise.resolve({ teams: [] })), [me?.address, me?.username], 5000);
  useHrTitle(t("hr.me.h1"));
  const list = q.data?.teams ?? [];
  const anyActive = list.some((x) => ACTIVE_HR.includes(x.status));
  return (
    <div className="wrap page">
      <div className="shead" style={{ marginBottom: 18 }}>
        <div><span className="eyebrow">{t("hr.brand")}</span><h1>{t("hr.me.h1")}</h1><p>{t("hr.me.p")}</p></div>
        <div className="row"><Link className="btn" to="/new/person">{t("hr.nav.person")}</Link><Link className="btn ghost" to="/new">{t("hr.nav.new")}</Link></div>
      </div>
      {loading ? <Loading /> : !me ? (
        <div className="pane stateCard soft">
          <h2>{t("hr.me.signin")}</h2>
          <div className="row">
            <button className="btn" type="button" disabled={busy} onClick={async () => { setErr(""); try { await tryDemo(); } catch (e) { setErr(errText(e, t)); } }}>{t("hr.me.demo")}</button>
            <button className="btn ghost" type="button" disabled={busy} onClick={async () => { setErr(""); try { await connect(); } catch (e) { setErr(errText(e, t)); } }}>{t("hr.me.mm")}</button>
          </div>
          {err && <p className="err" role="alert">{err}</p>}
        </div>
      ) : q.error && !q.data ? <ErrorBox error={q.error} retry={q.reload} /> : q.loading && !q.data ? <Loading /> : list.length === 0 ? (
        <p className="empty">{t("hr.me.empty")} <Link to="/new/person">{t("hr.nav.person")} →</Link></p>
      ) : (
        <div className="pane">
          <div className="tbl"><table>
            <thead><tr><th>{t("hr.me.col.team")}</th><th>{t("hr.me.col.kind")}</th><th>{t("hr.me.col.status")}</th><th className="r">{t("hr.me.col.score")}</th><th className="r">{t("hr.me.col.people")}</th><th className="r">{t("hr.me.col.updated")}</th></tr></thead>
            <tbody>
              {list.map((x) => {
                const to = (x.mode === "person" ? "/p/" : "/r/") + encodeURIComponent(x.id);
                return (
                  <tr key={x.id}>
                    <td><Link to={to} style={{ fontWeight: 600 }}>{x.name}</Link>{x.valuation_id && <span className="muted-sm"> · {t("hr.me.linked")}</span>}</td>
                    <td>{t(x.mode === "person" ? "hr.me.kind.person" : "hr.me.kind.team")}{x.target_type ? <span className="muted-sm"> · {t(x.target_type === "role" ? "hr.pr.fit.role" : "hr.pr.fit.business")}</span> : null}</td>
                    <td><span className={"pill" + statusPill(x.status)}>{t(("hr.r.st." + x.status) as DictKey)}</span></td>
                    <td className="r">{x.score != null ? <><b className="num">{fmt(x.score, 0)}</b> <span className="muted-sm">{t(("hr.bandshort." + bandOf(x.score)) as DictKey)}</span></> : "–"}</td>
                    <td className="r num">{fmt(x.people_count)}</td>
                    <td className="r muted">{x.updated_at ? date(x.updated_at) : ""}</td>
                  </tr>
                );
              })}
            </tbody>
          </table></div>
          {anyActive && <p className="note">{t("v.poll")}</p>}
        </div>
      )}
    </div>
  );
}
