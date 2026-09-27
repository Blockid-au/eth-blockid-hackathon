import { useEffect, useState } from "react";
import { encodeFunctionData, getAddress } from "viem";
import { useI18n } from "../i18n";
import { errText, useAuth } from "../auth";
import { ApiError, request, type CompanyDetail } from "../api";
import { useAsync } from "../lib/hooks";
import { CHAINS, addrError, isAddressValid, shortAddr, signInWithEthereum, switchOrAddChain } from "../wallet";

/* Secondary share transfers (backend: agents/src/blockid_agents/studio/transfers.py).
   free     = holder signs BlockIDShareToken.transfer in MetaMask; the API verifies the receipt.
   approval = token paused; holder files a request -> admin approves -> issuer forcedTransfer. */

type Mode = "free" | "approval";
interface Info { ticker: string; mode: Mode; paused: boolean | null; token: string; registry: string; chain_id: number }
interface Check { ok: boolean; reason: string | null; mode: Mode; from_verified: boolean; to_verified: boolean; balance: number; via?: "wallet" | "request"; pending?: number }
export interface TransferRow {
  id: number; company_id?: number; ticker?: string; company_name?: string; from_wallet: string; to_wallet: string; to_name: string;
  shares: number; mode: Mode; status: string; tx_hash?: string | null; note?: string | null; created_at?: string; requested_by?: string | null;
  /** admin queue: why the request would be refused right now (reason code), null when it may go */
  blocker?: string | null;
}
export interface KycRow { id: number; ticker?: string; company_name?: string; wallet: string; name: string; status: string; note?: string | null; requested_by?: string | null; created_at?: string }

const enc = encodeURIComponent;
export const tapi = {
  info: (tk: string) => request<Info>("GET", `/v1/companies/${enc(tk)}/transfer-info`),
  check: (tk: string, from_wallet: string, to_wallet: string, shares: number) =>
    request<Check>("POST", `/v1/companies/${enc(tk)}/transfers/check`, { from_wallet, to_wallet, shares }),
  history: (tk: string) => request<TransferRow[]>("GET", `/v1/companies/${enc(tk)}/transfers`),
  create: (tk: string, body: { to_wallet: string; to_name: string; shares: number; tx_hash?: string; note?: string }) =>
    request<TransferRow>("POST", `/v1/companies/${enc(tk)}/transfers`, body),
  kyc: (tk: string, name: string, wallet?: string) => request<KycRow | { status: string }>("POST", `/v1/companies/${enc(tk)}/kyc`, { name, wallet }),
  adminTransfers: () => request<TransferRow[]>("GET", "/v1/admin/transfers"),
  adminKyc: () => request<KycRow[]>("GET", "/v1/admin/kyc"),
  approveTransfer: (id: number) => request<unknown>("POST", `/v1/admin/transfers/${id}/approve`),
  rejectTransfer: (id: number, reason: string) => request<unknown>("POST", `/v1/admin/transfers/${id}/reject`, { reason }),
  approveKyc: (id: number) => request<unknown>("POST", `/v1/admin/kyc/${id}/approve`),
  rejectKyc: (id: number, reason: string) => request<unknown>("POST", `/v1/admin/kyc/${id}/reject`, { reason }),
  setMode: (cid: number, mode: Mode) => request<unknown>("POST", `/v1/admin/companies/${cid}/transfer-mode`, { mode }),
};

const EN = {
  h: "Transfer shares",
  p: "Secondary transfers between KYC-verified wallets on BlockID Chain. Hoodi and HashKey mirrors are re-anchored automatically.",
  free: "Free transfer", approval: "Admin approval required",
  freeP: "You sign the transfer yourself in MetaMask; it settles on-chain immediately.",
  apprP: "The share token is paused for direct transfers. Your request goes to an admin; the issuer executes it after approval.",
  signin: "Sign in with the wallet that holds the shares", to: "Receiver wallet", name: "Receiver name", n: "Shares", note: "Note (optional)",
  bal: "Your balance", check: "Check", send: "Sign transfer in MetaMask", req: "Submit for approval",
  kycH: "Receiver is not KYC-verified", kycP: "Ask the admin to verify this wallet in the company's identity registry.", kycBtn: "Request KYC",
  kycSent: "KYC request sent to the admin.", sent: "Transfer recorded on BlockID Chain. Mirrors are being re-anchored.", reqSent: "Request submitted. Waiting for admin approval.",
  waiting: "Waiting for the transaction…", hist: "Transfer history", none: "No transfers yet.", mismatch: "MetaMask account differs from the signed-in wallet",
  r_not_verified: "Receiver (or sender) is not KYC-verified", r_balance: "Not enough shares", r_paused: "Token paused: this company requires admin approval",
  r_frozen: "Wallet frozen by the transfer agent", r_lockup: "Lock-up period still active", r_cap: "Shareholder cap reached", r_self: "Sender and receiver are the same",
  r_reverted: "The transfer would revert", ok: "Checks passed", youAreNot: "You hold no shares of this company.",
  thTk: "Ticker", thCo: "Company", thFrom: "From", thTo: "To", thMode: "Mode", thStatus: "Status",
  st_pending: "Pending", st_approved: "Approved", st_rejected: "Rejected", st_failed: "Failed", st_done: "Done", st_confirmed: "Confirmed", st_executed: "Executed", st_verified: "Verified",
};
const VI: typeof EN = {
  h: "Chuyển nhượng cổ phần",
  p: "Chuyển nhượng thứ cấp giữa các ví đã KYC trên BlockID Chain. Bản mirror trên Hoodi và HashKey được neo lại tự động.",
  free: "Chuyển nhượng tự do", approval: "Cần admin phê duyệt",
  freeP: "Bạn tự ký lệnh chuyển trong MetaMask; giao dịch được ghi trên chuỗi ngay.",
  apprP: "Token đang tạm dừng chuyển trực tiếp. Yêu cầu của bạn được gửi tới admin; issuer thực hiện sau khi duyệt.",
  signin: "Đăng nhập bằng ví đang nắm cổ phần", to: "Ví người nhận", name: "Tên người nhận", n: "Số cổ phần", note: "Ghi chú (tuỳ chọn)",
  bal: "Số dư của bạn", check: "Kiểm tra", send: "Ký chuyển nhượng trong MetaMask", req: "Gửi yêu cầu duyệt",
  kycH: "Người nhận chưa KYC", kycP: "Đề nghị admin xác minh ví này trong sổ định danh của công ty.", kycBtn: "Yêu cầu KYC",
  kycSent: "Đã gửi yêu cầu KYC tới admin.", sent: "Đã ghi nhận chuyển nhượng trên BlockID Chain. Đang neo lại các bản mirror.", reqSent: "Đã gửi yêu cầu. Chờ admin phê duyệt.",
  waiting: "Đang chờ giao dịch…", hist: "Lịch sử chuyển nhượng", none: "Chưa có chuyển nhượng.", mismatch: "Tài khoản MetaMask khác ví đang đăng nhập",
  r_not_verified: "Người nhận (hoặc người gửi) chưa KYC", r_balance: "Không đủ cổ phần", r_paused: "Token tạm dừng: công ty này yêu cầu admin duyệt",
  r_frozen: "Ví bị đóng băng bởi transfer agent", r_lockup: "Đang trong thời gian khoá", r_cap: "Đã đạt số cổ đông tối đa", r_self: "Người gửi và người nhận trùng nhau",
  r_reverted: "Giao dịch sẽ bị revert", ok: "Đạt mọi điều kiện", youAreNot: "Bạn chưa nắm cổ phần của công ty này.",
  thTk: "Mã", thCo: "Doanh nghiệp", thFrom: "Từ", thTo: "Đến", thMode: "Chế độ", thStatus: "Trạng thái",
  st_pending: "Đang chờ", st_approved: "Đã duyệt", st_rejected: "Bị từ chối", st_failed: "Thất bại", st_done: "Hoàn tất", st_confirmed: "Đã xác nhận", st_executed: "Đã thực hiện", st_verified: "Đã xác minh",
};
export function useTx() {
  const { lang } = useI18n() as unknown as { lang: string };
  return lang === "vi" ? VI : EN;
}
const stText = (L: typeof EN, st: string) => (L as Record<string, string>)["st_" + st] ?? st;
const reasonText = (L: typeof EN, r: string | null) => (r ? (L as Record<string, string>)["r_" + r] ?? r : "");

const TRANSFER_ABI = [{ type: "function", name: "transfer", stateMutability: "nonpayable", inputs: [{ name: "to", type: "address" }, { name: "value", type: "uint256" }], outputs: [{ type: "bool" }] }] as const;

async function waitReceipt(hash: string, tries = 40): Promise<{ status: string } | null> {
  for (let i = 0; i < tries; i++) {
    const r = await fetch(CHAINS.local.rpc, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ jsonrpc: "2.0", id: 1, method: "eth_getTransactionReceipt", params: [hash] }) });
    const j = (await r.json()) as { result?: { status: string } | null };
    if (j.result) return j.result;
    await new Promise((res) => setTimeout(res, 1500));
  }
  return null;
}

export function ModeBadge({ mode }: { mode: Mode }) {
  const L = useTx();
  return <span className={"pill"} style={{ background: mode === "approval" ? "var(--gold-soft)" : "var(--accent-soft)", color: mode === "approval" ? "var(--gold)" : "var(--accent-deep)" }}>{mode === "approval" ? "◆ " + L.approval : "⇄ " + L.free}</span>;
}

/* A sent-but-not-yet-recorded transaction survives reloads (per company + wallet), so it is recorded, never sent twice. */
interface PendingTx { hash: string; to: string; name: string; shares: number; note: string }
const pendKey = (tk: string, w: string) => `bid.tx.pending.${tk.toUpperCase()}.${w.toLowerCase()}`;
function readPending(tk: string, w: string | null): PendingTx | null {
  if (!w) return null;
  try { const x = JSON.parse(localStorage.getItem(pendKey(tk, w)) || "null"); return x && /^0x[0-9a-f]{64}$/i.test(x.hash) ? x : null; } catch { return null; }
}
function writePending(tk: string, w: string, p: PendingTx | null) {
  try { if (p) localStorage.setItem(pendKey(tk, w), JSON.stringify(p)); else localStorage.removeItem(pendKey(tk, w)); } catch { /* private mode */ }
}
/** "<code>: words" from the API (studio/transfers.py reason_detail) -> the translated reason, else the text as is. */
function apiReason(L: typeof EN, msg: string): string {
  const m = /^(\w+):/.exec(msg);
  return m && (L as Record<string, string>)["r_" + m[1]] ? reasonText(L, m[1]) : msg;
}

export function TransferPanel({ c, onDone }: { c: CompanyDetail; onDone: () => void }) {
  const { t, fmt } = useI18n();
  const L = useTx();
  const { me, refresh } = useAuth() as ReturnType<typeof useAuth> & { refresh?: () => Promise<void> };
  const info = useAsync(() => tapi.info(c.ticker), [c.ticker], 20000);
  const hist = useAsync(() => tapi.history(c.ticker), [c.ticker], 20000);
  const [to, setTo] = useState("");
  const [name, setName] = useState("");
  const [n, setN] = useState("100");
  const [note, setNote] = useState("");
  const [chk, setChk] = useState<Check | null>(null);
  const [msg, setMsg] = useState<{ ok: boolean; s: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [touched, setTouched] = useState(false);
  const mode: Mode = info.data?.mode ?? "free";
  const me_addr = me?.address ? getAddress(me.address) : null;
  const [pending, setPendingState] = useState<PendingTx | null>(() => readPending(c.ticker, me_addr));
  useEffect(() => { setPendingState(readPending(c.ticker, me_addr)); }, [c.ticker, me_addr]);
  const setPending = (p: PendingTx | null) => { if (me_addr) writePending(c.ticker, me_addr, p); setPendingState(p); };
  const w = isAddressValid(to);
  const mine = me_addr ? c.cap_table.find((r) => r.wallet.toLowerCase() === me_addr.toLowerCase()) : undefined;
  const held = Number(mine?.shares ?? 0);
  // inline checks, shown as soon as something is typed (all of them on submit)
  const nT = n.trim();
  const sharesErr = !nT ? t("fx.tr.sharesNeed") : !/^\d+$/.test(nT) ? t("fx.tr.whole") : Number(nT) < 1 ? t("fx.tr.sharesNeed") : Number(nT) > held ? t("fx.tr.max", { n: fmt(held) }) : "";
  const shares = sharesErr ? 0 : Number(nT);
  const toErr = to ? addrError(t, to) || (w && me_addr && w === me_addr ? t("fx.tr.self") : "") : touched ? t("fx.addr.need") : "";
  const nameErr = !name.trim() && (touched || name.length > 0) ? t("fx.tr.nameNeed") : "";
  const formOk = !!w && !toErr && !sharesErr && !!name.trim();

  const doCheck = async (): Promise<Check | null> => {
    if (!me_addr || !w || !shares) return null;
    try { const r = await tapi.check(c.ticker, me_addr, w, shares); setChk(r); return r; }
    catch (e) { setMsg({ ok: false, s: errText(e, t) }); return null; }
  };
  const kyc = async () => {
    if (!w) return;
    setBusy(true);
    try { await tapi.kyc(c.ticker, name.trim() || "Investor", w); setMsg({ ok: true, s: L.kycSent }); }
    catch (e) { setMsg({ ok: false, s: errText(e, t) }); }
    finally { setBusy(false); }
  };
  /** Record a sent transaction: wait for its receipt, then report it (the API refuses a hash twice). */
  const record = async (p: PendingTx) => {
    setBusy(true);
    setMsg({ ok: true, s: L.waiting + " " + shortAddr(p.hash) });
    try {
      const rc = await waitReceipt(p.hash);
      if (!rc) { setMsg({ ok: false, s: t("fx.tr.stillWaiting", { h: shortAddr(p.hash) }) }); return; }
      if (rc.status !== "0x1") { setPending(null); setMsg({ ok: false, s: t("fx.tr.reverted", { h: shortAddr(p.hash) }) }); return; }
      try {
        await tapi.create(c.ticker, { to_wallet: p.to, to_name: p.name, shares: p.shares, tx_hash: p.hash, note: p.note });
      } catch (e) {
        if (!(e instanceof ApiError && e.status === 409 && /already recorded/i.test(e.message))) throw e;
      }
      setPending(null);
      setMsg({ ok: true, s: L.sent });
      setChk(null); void hist.reload(); onDone();
    } catch (x) {
      setMsg({ ok: false, s: t("fx.tr.recordFail", { e: errText(x, t) }) });
    } finally {
      setBusy(false);
    }
  };
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setTouched(true);
    setMsg(null);
    if (pending) { void record(pending); return; }  // never a second send while one is not recorded
    if (!formOk || !w || !me_addr) return;
    const r = await doCheck();
    if (!r || !r.ok) { if (r && !r.ok) setMsg({ ok: false, s: reasonText(L, r.reason) }); return; }
    setBusy(true);
    try {
      // branch on the fresh check (the mode may have changed since the page polled it)
      if (r.via === "request" || r.mode === "approval") {
        await tapi.create(c.ticker, { to_wallet: w, to_name: name.trim(), shares, note: note.trim() });
        setMsg({ ok: true, s: L.reqSent });
        setChk(null); void hist.reload(); onDone();
      } else {
        await switchOrAddChain(CHAINS.local);
        const eth = window.ethereum!;
        const accts = (await eth.request({ method: "eth_requestAccounts" })) as string[];
        if (!accts?.length || getAddress(accts[0]) !== me_addr) { setMsg({ ok: false, s: L.mismatch }); return; }
        const data = encodeFunctionData({ abi: TRANSFER_ABI, functionName: "transfer", args: [w as `0x${string}`, BigInt(shares)] });
        const hash = (await eth.request({ method: "eth_sendTransaction", params: [{ from: me_addr, to: getAddress(c.local?.token ?? c.local_token ?? ""), data }] })) as string;
        const p = { hash, to: w, name: name.trim(), shares, note: note.trim() };
        setPending(p);  // from here on the form only records this transaction
        setBusy(false);
        await record(p);
        return;
      }
    } catch (x) {
      setMsg({ ok: false, s: x instanceof ApiError ? apiReason(L, x.message) : errText(x, t) });
    } finally {
      setBusy(false);
    }
  };
  const bad = (err: string) => (err ? " bad" : "");

  return (
    <div className="panel">
      <div className="ptitle between">
        <div><h3>{L.h}</h3><p>{L.p}</p></div>
        <ModeBadge mode={mode} />
      </div>
      <p className="sub">{mode === "approval" ? L.apprP : L.freeP}</p>
      <div className="cols">
        {!me_addr ? (
          <div className="card solid"><p>{L.signin}</p><button className="btn gold sm" type="button" onClick={async () => { try { await signInWithEthereum(); await refresh?.(); location.reload(); } catch (e) { setMsg({ ok: false, s: errText(e, t) }); } }}>MetaMask</button></div>
        ) : (
          <form className="card solid" onSubmit={submit} noValidate>
            <p className="sub">{L.bal}: <b className="num">{fmt(held)}</b> {c.ticker} · <span className="mono">{shortAddr(me_addr)}</span>{!mine && <> · {L.youAreNot}</>}</p>
            {pending ? (
              <div className="banner gold" role="status" style={{ display: "grid", gap: 6 }}>
                <span>{t("fx.tr.pending", { h: shortAddr(pending.hash), n: fmt(pending.shares), a: shortAddr(pending.to) })}</span>
                <a className="mono" href={CHAINS.local.txUrl(pending.hash)} target="_blank" rel="noopener noreferrer">{pending.hash}</a>
              </div>
            ) : (
              <div className="fgrid">
                <label className="lf"><span>{L.to}</span><input className={"mono" + bad(toErr)} value={to} placeholder="0x…" spellCheck={false} aria-invalid={!!toErr} onChange={(e) => { setTo(e.target.value.trim()); setChk(null); }} />{toErr && <span className="hint bad">{toErr}</span>}</label>
                <label className="lf"><span>{L.name}</span><input className={bad(nameErr)} value={name} maxLength={120} aria-invalid={!!nameErr} onChange={(e) => setName(e.target.value)} />{nameErr && <span className="hint bad">{nameErr}</span>}</label>
                <label className="lf"><span>{L.n}</span><input className={bad(n ? sharesErr : "")} inputMode="numeric" value={n} aria-invalid={!!sharesErr} onChange={(e) => { setN(e.target.value); setChk(null); }} />{(n || touched) && sharesErr && <span className="hint bad">{sharesErr}</span>}</label>
                <label className="lf"><span>{L.note}</span><input value={note} maxLength={500} onChange={(e) => setNote(e.target.value)} /></label>
              </div>
            )}
            {!pending && chk && (chk.ok ? <p className="banner ok">✓ {L.ok}</p> : <p className="banner warn">{reasonText(L, chk.reason)}</p>)}
            {!pending && chk && !chk.to_verified && (
              <div className="banner gold"><span><b>{L.kycH}</b> · {L.kycP}</span><button className="btn gold sm" type="button" disabled={busy} onClick={kyc}>{L.kycBtn}</button></div>
            )}
            <div className="row">
              {!pending && <button className="btn ghost sm" type="button" disabled={busy || !formOk} onClick={() => void doCheck()}>{L.check}</button>}
              <button className="btn gold sm" type="submit" disabled={busy || (!pending && !formOk)}>
                {busy ? <span className="spinner" aria-hidden="true" /> : null}
                {pending ? (busy ? t("fx.tr.waitingBtn") : t("fx.tr.recordBtn", { h: shortAddr(pending.hash) })) : mode === "approval" ? L.req : L.send}
              </button>
            </div>
            {msg && <p className={"banner " + (msg.ok ? "ok" : "bad")} role={msg.ok ? "status" : "alert"}>{msg.s}</p>}
          </form>
        )}
        <div className="card solid">
          <h4>{L.hist}</h4>
          <TransferList rows={hist.data ?? []} />
        </div>
      </div>
    </div>
  );
}

export function TransferList({ rows, admin }: { rows: TransferRow[]; admin?: boolean }) {
  const { fmt } = useI18n();
  const L = useTx();
  if (!rows.length) return <p className="empty">{L.none}</p>;
  return (
    <div className="tbl">
      <table>
        <thead><tr>{admin && <th>{L.thTk}</th>}<th>{L.thFrom}</th><th>{L.thTo}</th><th className="r">{L.n}</th><th>{L.thMode}</th><th>{L.thStatus}</th><th>Tx</th></tr></thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.id}>
              {admin && <td className="mono">{r.ticker}</td>}
              <td className="mono" title={r.from_wallet}>{shortAddr(r.from_wallet)}</td>
              <td className="mono" title={r.to_wallet}>{r.to_name ? r.to_name + " · " : ""}{shortAddr(r.to_wallet)}</td>
              <td className="r">{fmt(Number(r.shares))}</td>
              <td title={r.mode === "approval" ? L.approval : L.free}><span aria-hidden="true">{r.mode === "approval" ? "◆" : "⇄"}</span><span className="sr-only">{r.mode === "approval" ? L.approval : L.free}</span></td>
              <td title={r.note ?? undefined}>{stText(L, r.status)}</td>
              <td className="mono">{r.tx_hash ? <a href={CHAINS.local.txUrl(r.tx_hash)} target="_blank" rel="noopener noreferrer">{shortAddr(r.tx_hash)}</a> : "–"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/* ---------- admin tab: transfer mode per company + approval queues ---------- */
export function AdminTransfersTab({ companies, onChanged }: { companies: { id: number; ticker: string; name: string; transfer_mode?: Mode; local_token?: string | null }[]; onChanged: () => void }) {
  const { t, fmt } = useI18n();
  const L = useTx();
  const tr = useAsync(() => tapi.adminTransfers(), [], 10000);
  const ky = useAsync(() => tapi.adminKyc(), [], 10000);
  const [msg, setMsg] = useState<{ ok: boolean; s: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const act = async (fn: () => Promise<unknown>) => {
    setBusy(true); setMsg(null);
    try { await fn(); setMsg({ ok: true, s: t("ap.sent") }); void tr.reload(); void ky.reload(); onChanged(); }
    catch (e) { setMsg({ ok: false, s: e instanceof ApiError ? apiReason(L, e.message) : errText(e, t) }); void tr.reload(); }
    finally { setBusy(false); }
  };
  const pendT = (tr.data ?? []).filter((x) => x.status === "pending" || x.status === "failed");
  const pendK = (ky.data ?? []).filter((x) => x.status === "pending" || x.status === "failed");
  return (
    <div style={{ display: "grid", gap: 16 }}>
      {msg && <p className={"banner " + (msg.ok ? "ok" : "bad")} role={msg.ok ? "status" : "alert"}>{msg.s}</p>}
      <section className="apsec">
        <h4 className="eyebrow">{L.approval}</h4>
        <div className="tbl">
          <table>
            <thead><tr><th>{L.thTk}</th><th>{L.thCo}</th><th>{L.approval}</th><th>{L.thMode}</th></tr></thead>
            <tbody>
              {companies.filter((c) => c.local_token).map((c) => (
                <tr key={c.id}>
                  <td className="mono">{c.ticker}</td>
                  <td>{c.name}</td>
                  <td><input type="checkbox" aria-label={`${c.ticker} ${L.approval}`} disabled={busy} checked={c.transfer_mode === "approval"}
                    onChange={(e) => act(() => tapi.setMode(c.id, e.target.checked ? "approval" : "free"))} /></td>
                  <td><ModeBadge mode={c.transfer_mode ?? "free"} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
      <section className="apsec">
        <h4 className="eyebrow">{L.h} · {pendT.length}</h4>
        {pendT.map((x) => (
          <div className="aprow" key={x.id}>
            <div className="between">
              <span><b className="mono">{x.ticker}</b> · {fmt(Number(x.shares))} · <span className="mono">{shortAddr(x.from_wallet)}</span> → {x.to_name ? x.to_name + " " : ""}<span className="mono">{shortAddr(x.to_wallet)}</span></span>
              <span className="muted-sm">{stText(L, x.status)}{x.note ? " · " + x.note : ""}</span>
            </div>
            {x.blocker && <p className="banner warn" role="status" style={{ margin: 0 }}>{t("fx.tr.blocked", { r: reasonText(L, x.blocker) })}</p>}
            <div className="row">
              <button className="btn gold sm" type="button" disabled={busy || !!x.blocker} onClick={() => act(() => tapi.approveTransfer(x.id))}>{t("ap.approve")}</button>
              {x.status === "pending" && <button className="btn danger sm" type="button" disabled={busy} onClick={() => act(() => tapi.rejectTransfer(x.id, "rejected by admin"))}>{t("ap.reject")}</button>}
            </div>
          </div>
        ))}
      </section>
      <section className="apsec">
        <h4 className="eyebrow">KYC · {pendK.length}</h4>
        {pendK.map((x) => (
          <div className="aprow" key={x.id}>
            <div className="between">
              <span><b className="mono">{x.ticker}</b> · {x.name} · <span className="mono" title={x.wallet}>{shortAddr(x.wallet)}</span></span>
              <span className="muted-sm">{stText(L, x.status)}{x.note ? " · " + x.note : ""}</span>
            </div>
            <div className="row">
              <button className="btn gold sm" type="button" disabled={busy} onClick={() => act(() => tapi.approveKyc(x.id))}>{t("ap.approve")}</button>
              {x.status === "pending" && <button className="btn danger sm" type="button" disabled={busy} onClick={() => act(() => tapi.rejectKyc(x.id, "rejected by admin"))}>{t("ap.reject")}</button>}
            </div>
          </div>
        ))}
      </section>
      <section className="apsec">
        <h4 className="eyebrow">{L.hist}</h4>
        <TransferList rows={tr.data ?? []} admin />
      </section>
    </div>
  );
}
