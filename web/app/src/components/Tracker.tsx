import { useState } from "react";
import { useI18n } from "../i18n";
import { errText, useAuth } from "../auth";
import { api, type CoEvent, type CompanyDetail, type SyncInfo, type SyncState } from "../api";
import { useNow } from "../lib/hooks";
import { CHAINS, chainOf, shortAddr, type ChainInfo } from "../wallet";
import type { DictKey } from "../dict";
import { EventList } from "../pages/Company";
import { DemoApproveGuide } from "./DemoGuide";
import { LowBalanceInline } from "./LowBalance";

type St = SyncState | "rejected";
interface Sub { label: string; done: boolean; tx?: string | null; chain?: ChainInfo }
interface Stage { key: string; title: string; state: St; note?: string; subs?: Sub[]; error?: string | null; action?: "approve" | "retry-issue" | "resync" }

const CHAIN_KEY: Record<string, ChainInfo> = { blockid: CHAINS.local, hoodi: CHAINS.hoodi, hsk: CHAINS.hsk };

export function defaultSync(c: CompanyDetail): SyncInfo {
  return c.sync ?? { blockid: c.local?.token ? "done" : "pending", hoodi: c.hoodi?.anchor_tx ? "done" : "pending", hsk: c.hsk?.anchor_tx ? "done" : "pending" };
}

function ev(events: CoEvent[], kind: string, chain?: string, pred?: (e: CoEvent) => boolean) {
  return events.filter((e) => e.kind === kind && (chain == null || chainOf(e.chain).key === CHAIN_KEY[chain].key) && (!pred || pred(e)));
}
const last = (xs: CoEvent[]) => (xs.length ? xs[0] : undefined); // events are newest first

function elapsed(ms: number) {
  const s = Math.max(0, Math.round(ms / 1000));
  const m = Math.floor(s / 60);
  return m ? `${m}m ${String(s % 60).padStart(2, "0")}s` : `${s}s`;
}

/** Live issuance tracker (/c/:ticker for companies not yet live on every chain). */
export function Tracker({ c, onChanged, only, feed = true }: { c: CompanyDetail; onChanged: () => void; only?: string[]; feed?: boolean }) {
  const { t, fmt } = useI18n();
  const { me } = useAuth();
  const now = useNow(1000);
  const [msg, setMsg] = useState<{ ok: boolean; s: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const admin = me?.role === "admin";
  const events = c.events ?? [];
  const sync = defaultSync(c);
  const N = c.cap_table?.length || (typeof c.holders === "number" ? c.holders : 0) || 0;
  const status = c.status;

  const deployed = (chain: string, contract: string) => last(ev(events, "deployed", chain, (e) => (e.data as { contract?: string } | null)?.contract === contract));
  const blockidSubs = (): Sub[] => {
    const L = CHAINS.local;
    const reg = deployed("blockid", "IdentityRegistry"), tok = deployed("blockid", "BlockIDShareToken"), dist = deployed("blockid", "DividendDistributor");
    const kyc = ev(events, "kyc", "blockid"), drip = ev(events, "drip", "blockid"), mint = ev(events, "issued", "blockid"), val = last(ev(events, "valuation_anchored", "blockid"));
    const bdone = sync.blockid === "done";
    return [
      { label: t("trk.sub.registry"), done: !!reg || !!c.local?.registry, tx: reg?.tx_hash, chain: L },
      { label: t("trk.sub.token"), done: !!tok || !!c.local?.token, tx: tok?.tx_hash, chain: L },
      { label: t("trk.sub.dist"), done: !!dist || !!c.local?.distributor, tx: dist?.tx_hash, chain: L },
      { label: t("trk.sub.kyc", { n: bdone ? N : Math.min(kyc.length, N), N }), done: bdone || (N > 0 && kyc.length >= N), tx: last(kyc)?.tx_hash, chain: L },
      { label: t("trk.sub.drip", { n: drip.length }), done: bdone || drip.length > 0, tx: last(drip)?.tx_hash, chain: L },
      { label: t("trk.sub.mint", { n: bdone ? N : Math.min(mint.length, N), N }), done: bdone || (N > 0 && mint.length >= N), tx: last(mint)?.tx_hash, chain: L },
      { label: t("trk.sub.val"), done: !!val || bdone, tx: val?.tx_hash, chain: L },
    ];
  };
  const extSubs = (key: "hoodi" | "hsk"): Sub[] => {
    const ch = CHAIN_KEY[key];
    const info = key === "hoodi" ? c.hoodi : c.hsk;
    const tok = deployed(key, "BlockIDShareToken");
    const mir = last(ev(events, key + "_mirrored", key));
    const anc = last(ev(events, "anchored", key));
    const done = sync[key] === "done";
    return [
      { label: t("trk.sub.mirror"), done: !!tok || !!info?.token, tx: tok?.tx_hash, chain: ch },
      { label: t("trk.sub.balances"), done: !!mir || done, tx: mir?.tx_hash, chain: ch },
      { label: t("trk.sub.paused"), done: !!mir || done, chain: ch },
      { label: t("trk.sub.root"), done: !!anc || !!info?.anchor_tx, tx: anc?.tx_hash ?? info?.anchor_tx, chain: ch },
    ];
  };

  const submitted = status !== "draft";
  const waiting = status === "pending_issue";
  const rejected = status === "rejected";
  const approved = submitted && !waiting && !rejected;
  const stages: Stage[] = [
    { key: "s1", title: t("trk.s1"), state: submitted ? "done" : "pending", note: t("trk.s1.p") },
    { key: "s2", title: rejected ? t("trk.s2.rej") : t("trk.s2"), state: rejected ? "rejected" : approved ? "done" : waiting ? "running" : "pending", note: t("trk.s2.p"), error: rejected ? c.error : null, action: waiting ? "approve" : undefined },
    { key: "s3", title: t("trk.s3"), state: approved ? sync.blockid : "pending", subs: approved ? blockidSubs() : undefined, error: sync.errors?.blockid ?? (status === "failed" ? c.error : null), action: sync.blockid === "failed" ? "retry-issue" : undefined },
    { key: "s4", title: t("trk.s4"), state: approved && sync.blockid === "done" ? sync.hoodi : "pending", subs: sync.blockid === "done" ? extSubs("hoodi") : undefined, error: sync.errors?.hoodi, action: sync.hoodi === "failed" || sync.hoodi === "skipped" ? "resync" : undefined },
    { key: "s5", title: t("trk.s5"), state: approved && sync.blockid === "done" ? sync.hsk : "pending", subs: sync.blockid === "done" ? extSubs("hsk") : undefined, error: sync.errors?.hsk, action: sync.hsk === "failed" || sync.hsk === "skipped" ? "resync" : undefined },
    { key: "s6", title: t("trk.s6"), state: status === "anchored" ? "done" : "pending", note: status === "anchored" ? t("trk.s6.p") : undefined },
  ];
  // a legacy "anchored" row that was never synced to HSK: offer the re-sync on stage 5
  if (status === "anchored" && sync.hsk !== "done") stages[4].action = "resync";

  const step = sync.step;
  const nowLine = step?.action
    ? t(("trk.act." + step.action) as DictKey, { c: (CHAIN_KEY[step.chain] ?? CHAINS.local).name, n: step.n ?? "", N: step.of ?? "" })
    : waiting ? t("trk.waiting") : status === "anchored" ? t("trk.done") : t(("c.st." + status) as DictKey);
  const start = sync.started_at ? Date.parse(sync.started_at) : NaN;
  const end = sync.finished_at ? Date.parse(sync.finished_at) : now;
  const showElapsed = Number.isFinite(start) && (status === "issuing" || status === "anchoring" || sync.finished_at);

  const act = async (kind: Stage["action"]) => {
    if (c.id == null || !kind) return;
    setBusy(true); setMsg(null);
    try {
      if (kind === "approve" || kind === "retry-issue") await api.approveIssue(c.id);
      else await api.approveAnchor(c.id);
      setMsg({ ok: true, s: t("trk.sent") });
      onChanged();
    } catch (e) {
      setMsg({ ok: false, s: errText(e, t) });
    } finally {
      setBusy(false);
    }
  };
  const actLabel = (a: Stage["action"]) => (a === "approve" ? t("trk.approve") : a === "resync" ? t("trk.resync") : t("trk.retry"));

  return (
    <div className="pane tracker">
      <div className="between">
        <div><h4 style={{ margin: 0 }}>{t("trk.h")}</h4><p className="note" style={{ margin: 0 }}>{t("trk.p")}</p></div>
        {showElapsed && <span className="muted-sm">{t("trk.elapsed")}: <b className="num">{elapsed(end - start)}</b></span>}
      </div>
      <p className="trk-now" aria-live="polite" aria-atomic="true" role="status">
        {(status === "issuing" || status === "anchoring") && <span className="spinner" aria-hidden="true" />}
        <b>{t("trk.now")}:</b> {nowLine}
      </p>
      <ol className="trk">
        {stages.map((s, i) => (only && !only.includes(s.key) ? null :
          <li key={s.key} className={"trk-st " + s.state} aria-current={s.state === "running" ? "step" : undefined}>
            <span className="trk-dot" aria-hidden="true">{s.state === "done" ? "✓" : s.state === "failed" || s.state === "rejected" ? "!" : s.state === "running" ? <span className="spinner" /> : i + 1}</span>
            <div className="trk-body">
              <div className="between">
                <b>{i + 1}. {s.title}</b>
                <span className={"pill" + (s.state === "done" ? " ok" : s.state === "failed" || s.state === "rejected" ? " bad" : s.state === "running" ? " gold" : "")}>{t(("trk.st." + (s.state === "rejected" ? "failed" : s.state)) as DictKey)}</span>
              </div>
              {s.note && (s.state === "running" || s.key === "s6" || s.key === "s1") && <p className="note">{s.note}</p>}
              {s.subs && s.state !== "pending" && (
                <ul className="trk-subs">
                  {s.subs.map((x, j) => (
                    <li key={j} className={x.done ? "done" : ""}>
                      <span aria-hidden="true">{x.done ? "✓" : "·"}</span> {x.label}
                      {x.tx && x.chain ? <> · <a className="tx" href={x.chain.txUrl(x.tx)} target="_blank" rel="noopener noreferrer">{shortAddr(x.tx)}</a></> : null}
                    </li>
                  ))}
                </ul>
              )}
              {s.error && (s.state === "failed" || s.state === "skipped" || s.state === "rejected") && <p className="banner bad" role="alert" style={{ margin: "6px 0 0" }}>{s.error}</p>}
              {!admin && s.action === "approve" && <DemoApproveGuide action={t("trk.approve")} tail="demo.tail.issue" admin={`/admin/issuance/${c.ticker}`} next={`/c/${c.ticker}/issue`} />}
              {admin && s.action && c.id != null && s.action !== "retry-issue" && <LowBalanceInline />}
              {admin && s.action && c.id != null && (
                <button className={"btn sm " + (s.action === "approve" ? "gold" : "ghost")} type="button" disabled={busy} onClick={() => act(s.action)} style={{ marginTop: 6 }}>{actLabel(s.action)}</button>
              )}
            </div>
          </li>
        ))}
      </ol>
      {msg && <p className={msg.ok ? "toast" : "err"} role={msg.ok ? "status" : "alert"}>{msg.s}</p>}
      {feed && events.length > 0 && (
        <details open={status !== "anchored"}>
          <summary className="muted-sm">{t("trk.feed")} · {fmt(Math.min(events.length, 8))}</summary>
          <EventList events={events.slice(0, 8)} sync={c.sync} />
        </details>
      )}
    </div>
  );
}

/** Compact per-chain chips (admin rows). */
export function SyncChips({ sync }: { sync?: SyncInfo | null }) {
  const { t } = useI18n();
  if (!sync) return null;
  const items: [string, SyncState][] = [["BlockID", sync.blockid], ["Hoodi", sync.hoodi], ["HSK", sync.hsk]];
  return (
    <span className="row" style={{ gap: 4, flexWrap: "wrap" }} aria-label={t("ad.sync")}>
      {items.map(([n, s]) => (
        <span key={n} aria-label={`${n}: ${t(("trk.st." + s) as DictKey)}`} className={"pill" + (s === "done" ? " ok" : s === "failed" || s === "skipped" ? " bad" : s === "running" ? " gold" : "")} title={(sync.errors as Record<string, string> | undefined)?.[n === "BlockID" ? "blockid" : n.toLowerCase()] ?? t(("trk.st." + s) as DictKey)}>
          {s === "running" ? "⟳ " : s === "done" ? "✓ " : s === "failed" || s === "skipped" ? "✗ " : "· "}{n}
        </span>
      ))}
    </span>
  );
}
