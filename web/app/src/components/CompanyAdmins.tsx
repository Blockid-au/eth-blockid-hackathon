/* Company admins panel + company-scoped approvals (Admin → Companies detail, and /c/:ticker). */
import { useState } from "react";
import { api, ApiError } from "../api";
import { errText } from "../auth";
import { useI18n } from "../i18n";
import { useAsync } from "../lib/hooks";
import { coAdminApi, type CoAdminRole, type CompanyAdmin } from "../lib/companyAdmins";
import { CHAINS, addrError, isAddressValid, shortAddr } from "../wallet";
import { useAuth } from "../auth";
import type { DictKey } from "../dict";

const POLL = 15000;
const forbidden = (e: unknown) => e instanceof ApiError && (e.status === 401 || e.status === 403 || e.status === 404);

function RevokeConfirm({ a, ticker, onDone, onCancel }: { a: CompanyAdmin; ticker: string; onDone: (msg: string, ok: boolean) => void; onCancel: () => void }) {
  const { t } = useI18n();
  const { me } = useAuth();
  const self = !!me?.address && me.address.toLowerCase() === a.address.toLowerCase();
  const [typed, setTyped] = useState("");
  const [busy, setBusy] = useState(false);
  const ok = typed.trim().toUpperCase() === ticker.toUpperCase();
  const go = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!ok) return;
    setBusy(true);
    try {
      const r = await coAdminApi.revoke(ticker, a.address);
      onDone(r.issuer && r.issuer !== "queued" ? `${t("ca.revoked")} · ${r.issuer}` : a.onchain ? t("ca.revoked.chain") : t("ca.revoked"), true);
    } catch (x) { onDone(errText(x, t), false); } finally { setBusy(false); }
  };
  return (
    <form className="banner bad" onSubmit={go} style={{ display: "grid", gap: 8 }}>
      <span>{t("ca.confirm.h", { a: a.label || shortAddr(a.address) })}{a.onchain ? " " + t("ca.confirm.chain") : ""}</span>
      {self && <b>{t("fx.ca.self")}</b>}
      <label className="lf"><span>{t("ca.confirm.p", { tk: ticker })}</span>
        <input value={typed} onChange={(e) => setTyped(e.target.value)} autoFocus spellCheck={false} aria-label={t("ca.confirm.p", { tk: ticker })} />
      </label>
      <span className="row">
        <button className="btn danger sm" type="submit" disabled={!ok || busy}>{t("ca.revoke")}</button>
        <button className="btn ghost sm" type="button" onClick={onCancel}>{t("common.cancel")}</button>
      </span>
    </form>
  );
}

function AddAdmin({ ticker, issued, admins, onDone }: { ticker: string; issued: boolean; admins: CompanyAdmin[]; onDone: (msg: string, ok: boolean) => void }) {
  const { t } = useI18n();
  const [addr, setAddr] = useState("");
  const [label, setLabel] = useState("");
  const [role, setRole] = useState<CoAdminRole>("manager");
  const [onchain, setOnchain] = useState(false);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const a = isAddressValid(addr);  // EIP-55: a wrong mixed-case checksum is rejected, the zero address too
  const addrErr = addrError(t, addr);
  // an address already listed (and not revoked) is an update: show what it is now, so a role is not changed by accident
  const listed = a ? admins.find((x) => x.status !== "revoked" && x.address.toLowerCase() === a.toLowerCase()) : undefined;
  const onAddr = (v: string) => {
    setAddr(v); setErr("");
    const hit = isAddressValid(v) ? admins.find((x) => x.status !== "revoked" && x.address.toLowerCase() === v.toLowerCase()) : undefined;
    if (hit) { setRole(hit.role); setLabel(hit.label || ""); setOnchain(hit.onchain); }
  };
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!a) { setErr(addrErr || t("ca.bad.addr")); return; }
    setErr(""); setBusy(true);
    try {
      const r = await coAdminApi.add(ticker, { address: a, label: label.trim(), role, onchain: onchain && issued });
      setAddr(""); setLabel(""); setOnchain(false); setRole("manager");
      const who = r.label || shortAddr(r.address);
      const text = r.updated
        ? (r.previous_role && r.previous_role !== r.role
          ? t("fx.ca.roleChanged", { a: who, from: t(("ca.role." + r.previous_role) as DictKey), to: t(("ca.role." + r.role) as DictKey) })
          : t("fx.ca.updated", { a: who }))
        : onchain && issued ? t("ca.added.chain") : t("ca.added");
      onDone(text, true);
    } catch (x) { setErr(errText(x, t)); } finally { setBusy(false); }
  };
  return (
    <form onSubmit={submit} noValidate style={{ display: "grid", gap: 8 }}>
      <div className="coadm-add">
        <input className={"mono" + (addrErr ? " bad" : "")} placeholder={t("ca.addr.ph")} aria-label={t("t.wallet")} aria-invalid={!!addrErr} value={addr} onChange={(e) => onAddr(e.target.value.trim())} spellCheck={false} />
        <input placeholder={t("ca.label")} aria-label={t("ca.label")} value={label} maxLength={120} onChange={(e) => setLabel(e.target.value)} />
        <select value={role} onChange={(e) => setRole(e.target.value as CoAdminRole)} aria-label={t("ca.role")}>
          <option value="manager">{t("ca.role.manager")}</option>
          <option value="owner">{t("ca.role.owner")}</option>
        </select>
        <button className="btn sm" type="submit" disabled={busy || !!addrErr}>{busy ? <span className="spinner" aria-hidden="true" /> : null}{listed ? t("fx.ca.update") : t("ca.add")}</button>
      </div>
      {addrErr && <p className="err" style={{ margin: 0 }}>{addrErr}</p>}
      {listed && <p className="note" style={{ margin: 0 }}>{t("fx.ca.listed", { r: t(("ca.role." + listed.role) as DictKey) })}{listed.role !== role ? " " + t("fx.ca.willChange", { from: t(("ca.role." + listed.role) as DictKey), to: t(("ca.role." + role) as DictKey) }) : ""}</p>}
      <label className="row" style={{ gap: 8, fontSize: ".86rem" }}>
        <input type="checkbox" checked={onchain && issued} disabled={!issued} onChange={(e) => setOnchain(e.target.checked)} />
        <span>{t("ca.onchain.cb")}{!issued ? <span className="muted"> · {t("ca.onchain.notyet")}</span> : null}</span>
      </label>
      {onchain && issued && <p className="note" style={{ margin: 0 }}>{t("ca.onchain.note")}</p>}
      <p className="err" role="alert" style={{ margin: 0 }}>{err}</p>
    </form>
  );
}

/** List + (for platform admins and company owners) add / revoke. Renders nothing for viewers without rights. */
export function CompanyAdminsPanel({ ticker, onChanged }: { ticker: string; onChanged?: () => void }) {
  const { t, date } = useI18n();
  const q = useAsync(() => coAdminApi.list(ticker), [ticker], POLL);
  const [confirm, setConfirm] = useState<string | null>(null);
  const [msg, setMsg] = useState<{ ok: boolean; s: string } | null>(null);
  if (q.error && forbidden(q.error)) return null;
  const d = q.data;
  const canManage = d?.you === "platform_admin" || d?.you === "company_owner";
  const done = (s: string, ok: boolean) => { setMsg({ ok, s }); setConfirm(null); void q.reload(); onChanged?.(); };
  const active = (d?.admins ?? []).filter((a) => a.status !== "revoked");
  const revoked = (d?.admins ?? []).filter((a) => a.status === "revoked");
  const owners = active.filter((a) => a.role === "owner" && a.status === "active").length;
  return (
    <div className="pane" style={{ display: "grid", gap: 12 }}>
      <div className="phead">
        <h4>{t("ca.h")}</h4>
        {d && <span className="pill gold">{t(("ca.you." + d.you) as DictKey)}</span>}
      </div>
      <p className="note" style={{ margin: 0 }}>{t("ca.p")}</p>
      {msg && <p className={"banner " + (msg.ok ? "ok" : "bad")} role={msg.ok ? "status" : "alert"}>{msg.s}</p>}
      {q.error && !d ? <p className="err">{errText(q.error, t)}</p> : !d ? <p className="note">{t("common.loading")}</p> : (
        <div className="tbl"><table>
          <thead><tr><th>{t("ca.label")}</th><th>{t("t.wallet")}</th><th>{t("ca.role")}</th><th>{t("ad.w.status")}</th><th>{t("ca.chain")}</th><th>{t("ad.w.since")}</th><th /></tr></thead>
          <tbody>
            {[...active, ...revoked].map((a) => (
              <tr key={a.id} style={a.status === "revoked" ? { opacity: 0.6 } : undefined}>
                <td>{a.label || "–"}</td>
                <td className="mono" style={{ fontSize: ".8rem" }}><a href={CHAINS.local.addrUrl(a.address)} target="_blank" rel="noopener noreferrer" title={a.address}>{shortAddr(a.address)}</a></td>
                <td><span className={"pill" + (a.role === "owner" ? " gold" : "")}>{t(("ca.role." + a.role) as DictKey)}</span></td>
                <td><span className={"status " + (a.status === "active" ? "active" : a.status === "revoked" ? "revoked" : "pending")}>{t(("ca.st." + a.status) as DictKey)}</span>{a.error ? <div className="err" style={{ fontSize: ".74rem", margin: "4px 0 0" }} title={a.error}>{a.error.length > 80 ? a.error.slice(0, 80) + "…" : a.error}</div> : null}</td>
                <td>
                  {a.onchain ? <span className="pill ok" title={t("ca.chain.roles")}>{t("ca.chain.on")}</span> : <span className="pill">{t("ca.chain.off")}</span>}
                  {a.grant_tx ? <> <a className="mono" style={{ fontSize: ".72rem" }} href={CHAINS.local.txUrl(a.grant_tx)} target="_blank" rel="noopener noreferrer">{shortAddr(a.grant_tx)}</a></> : null}
                  {a.revoke_tx ? <> <a className="mono" style={{ fontSize: ".72rem", color: "var(--muted)" }} href={CHAINS.local.txUrl(a.revoke_tx)} target="_blank" rel="noopener noreferrer">✕ {shortAddr(a.revoke_tx)}</a></> : null}
                </td>
                <td className="muted-sm">{a.status === "revoked" && a.revoked_at ? date(a.revoked_at) : a.added_at ? date(a.added_at) : "–"}</td>
                <td className="r">
                  {canManage && (a.status !== "revoked" || a.onchain) && !(a.role === "owner" && a.status === "active" && owners <= 1) && (
                    <button type="button" className="linkbtn" onClick={() => setConfirm(confirm === a.address ? null : a.address)}>{a.status === "revoked" ? t("ca.retry") : t("ca.revoke")}</button>
                  )}
                </td>
              </tr>
            ))}
            {!d.admins.length && <tr><td colSpan={7} className="note">{t("ca.empty")}</td></tr>}
          </tbody>
        </table></div>
      )}
      {d && confirm && (() => { const a = d.admins.find((x) => x.address === confirm); return a ? <RevokeConfirm a={a} ticker={d.ticker} onDone={done} onCancel={() => setConfirm(null)} /> : null; })()}
      {d && canManage && <AddAdmin ticker={d.ticker} issued={d.issued} admins={d.admins} onDone={done} />}
      {d && !canManage && <p className="note" style={{ margin: 0 }}>{t("ca.readonly")}</p>}
      <p className="note" style={{ margin: 0 }}>{t("ca.mirrors")}</p>
    </div>
  );
}

/** Pending mints / dividends / transfers of ONE company, with approve / reject (platform admin or company admin). */
export function CompanyApprovals({ companyId, onChanged }: { companyId: number; onChanged?: () => void }) {
  const { t, fmt } = useI18n();
  const ap = useAsync(() => coAdminApi.approvals(), [], POLL);
  const tr = useAsync(() => coAdminApi.transfers().catch(() => []), [], POLL);
  const [msg, setMsg] = useState<{ ok: boolean; s: string } | null>(null);
  const [busy, setBusy] = useState(false);
  if (ap.error && forbidden(ap.error)) return null;
  if (!ap.data) return null;
  const mints = ap.data.mints.filter((m) => m.company_id === companyId);
  const divs = ap.data.dividends.filter((d) => d.company_id === companyId);
  const trs = (tr.data ?? []).filter((x) => x.company_id === companyId && x.status === "pending");
  const act = async (fn: () => Promise<unknown>, ok: string) => {
    setBusy(true); setMsg(null);
    try { await fn(); setMsg({ ok: true, s: ok }); await Promise.all([ap.reload(), tr.reload()]); onChanged?.(); }
    catch (e) {
      // "<reason code>: words" from a transfer that may not go (studio/transfers.py): the reason in the reader's language
      const code = e instanceof ApiError ? /^(self|balance|frozen|lockup|not_verified|cap):/.exec(e.message)?.[1] : undefined;
      setMsg({ ok: false, s: code ? t(`fx.r.${code}` as DictKey) : errText(e, t) });
      void tr.reload();
    } finally { setBusy(false); }
  };
  return (
    <div className="pane" style={{ display: "grid", gap: 10 }} aria-busy={busy}>
      <div className="phead"><h4>{t("ca.ap.h")}</h4><span className="gatepill">{t("gate.admin")}</span></div>
      <p className="note" style={{ margin: 0 }}>{t("ca.ap.p")}</p>
      {msg && <p className={"banner " + (msg.ok ? "ok" : "bad")} role={msg.ok ? "status" : "alert"}>{msg.s}</p>}
      {!mints.length && !divs.length && !trs.length && <p className="empty">{t("ca.ap.empty")}</p>}
      {mints.map((m) => (
        <div className="aprow" key={"m" + m.id}>
          <div className="between">
            <span>{t("ap.mintrow", { n: fmt(Number(m.shares)), tk: m.ticker ?? "", name: m.holder_name })} <span className="muted-sm mono" title={m.to_wallet}>{shortAddr(m.to_wallet)}</span></span>
            <span className="muted-sm">{m.reason}{m.requested_by ? " · " + t("ap.req", { w: shortAddr(m.requested_by) || m.requested_by }) : ""}</span>
          </div>
          <div className="row">
            <button className="btn gold sm" type="button" disabled={busy} onClick={() => act(() => api.approveMint(m.id), t("ap.sent"))}>{t("ap.approve")}</button>
            <button className="btn danger sm" type="button" disabled={busy} onClick={() => act(() => api.rejectMint(m.id, "rejected by company admin"), t("ap.rejected"))}>{t("ap.reject")}</button>
          </div>
        </div>
      ))}
      {divs.map((d) => (
        <div className="aprow" key={"d" + d.id}>
          <div className="between">
            <span>{t("ap.divrow", { n: fmt(d.total_maud ?? d.total_units / 1e6, 2), tk: d.ticker ?? "" })}{d.holders ? " · " + t("ap.holders", { n: d.holders }) : ""}</span>
            <span className="merkle">{d.merkle_root ? shortAddr(d.merkle_root) : ""}</span>
          </div>
          <div className="row">
            <button className="btn gold sm" type="button" disabled={busy} onClick={() => act(() => api.approveDividend(d.id), t("ap.sent"))}>{t("ap.approve")}</button>
            <button className="btn danger sm" type="button" disabled={busy} onClick={() => act(() => api.rejectDividend(d.id, "rejected by company admin"), t("ap.rejected"))}>{t("ap.reject")}</button>
          </div>
        </div>
      ))}
      {trs.map((x) => (
        <div className="aprow" key={"t" + x.id}>
          <div className="between">
            <span>{t("ca.ap.tr", { n: fmt(Number(x.shares)) })} <span className="muted-sm mono">{shortAddr(x.from_wallet)} → {shortAddr(x.to_wallet)}</span>{x.to_name ? <span className="muted-sm"> · {x.to_name}</span> : null}</span>
          </div>
          {x.blocker && <p className="banner warn" role="status" style={{ margin: 0 }}>{t("fx.tr.blocked", { r: t((`fx.r.${x.blocker}`) as DictKey) })}</p>}
          <div className="row">
            <button className="btn gold sm" type="button" disabled={busy || !!x.blocker} onClick={() => act(() => coAdminApi.approveTransfer(x.id), t("ap.sent"))}>{t("ap.approve")}</button>
            <button className="btn danger sm" type="button" disabled={busy} onClick={() => act(() => coAdminApi.rejectTransfer(x.id, "rejected by company admin"), t("ap.rejected"))}>{t("ap.reject")}</button>
          </div>
        </div>
      ))}
    </div>
  );
}
