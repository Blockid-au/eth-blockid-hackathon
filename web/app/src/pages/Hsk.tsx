import { useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { useI18n } from "../i18n";
import type { DictKey } from "../dict";
import { useAsync, useTitle } from "../lib/hooks";
import { shortAddr } from "../lib/addr";
import { loadHskDemo, okAddr, okHash, type HskDemo, type HskProposal } from "../lib/hsk";
import { CHAINS, switchOrAddChain } from "../wallet";
import { errText } from "../auth";
import { Loading } from "../components/Layout";

const H = CHAINS.hsk;

function Ext({ href, children }: { href: string; children: ReactNode }) {
  return <a href={href} target="_blank" rel="noopener noreferrer">{children}</a>;
}

function TxLink({ h }: { h?: string }) {
  if (!okHash(h)) return <span className="hint">–</span>;
  return <a className="tx mono" href={H.txUrl(h)} target="_blank" rel="noopener noreferrer">{shortAddr(h)}</a>;
}

function AddBtn() {
  const { t } = useI18n();
  const [msg, setMsg] = useState("");
  return (
    <>
      <button className="btn ghost sm" type="button" onClick={async () => {
        setMsg("");
        try { await switchOrAddChain(H); setMsg(t("hsk.added")); } catch (e) { setMsg(errText(e, t)); }
      }}>{t("hsk.addnet")}</button>
      {msg && <span className="toast" role="status">{msg}</span>}
    </>
  );
}

/** AI proposes → human approves → issuer executes (static principle strip). */
export function HskFlow() {
  const { t } = useI18n();
  const steps: { k: DictKey; s: DictKey; gate?: boolean }[] = [
    { k: "hsk.f1", s: "hsk.f1s" },
    { k: "hsk.f2", s: "hsk.f2s", gate: true },
    { k: "hsk.f3", s: "hsk.f3s" },
  ];
  return (
    <ol className="timeline" style={{ listStyle: "none", margin: 0, padding: 0 }} aria-label={t("hsk.flow")}>
      {steps.map((n) => (
        <li key={n.k} className="tl done">
          {n.gate && <span className="gm" aria-hidden="true" />}
          <span className="nd" aria-hidden="true" />
          <span>{t(n.k)}</span>
          <span className="hint">{t(n.s)}</span>
        </li>
      ))}
    </ol>
  );
}

function Contracts({ d }: { d: HskDemo }) {
  const { t } = useI18n();
  const rows: [DictKey, string | undefined][] = [
    ["hsk.c.prov", d.agentProvenance], ["hsk.c.reg", d.identityRegistry], ["hsk.c.share", d.shareToken],
    ["hsk.c.div", d.dividendDistributor], ["hsk.c.pay", d.payToken], ["hsk.c.anchor", d.capTableAnchor],
  ];
  const roles: [DictKey, string | undefined][] = [["hsk.r.op", d.operator], ["hsk.r.relayer", d.relayer], ["hsk.r.approver", d.approver]];
  return (
    <>
      <div className="hskgrid">
        {rows.map(([k, a]) => (
          <div key={k} className="card">
            <div className="between"><h4>{t(k)}</h4>{okAddr(a) && <span className="pill ok">{t("hsk.deployed")}</span>}</div>
            {okAddr(a) ? (
              <>
                <span className="mono hskaddr">{a}</span>
                <Ext href={H.addrUrl(a)}>{t("hsk.explorer")} →</Ext>
              </>
            ) : <span className="muted">{t("c.notyet")}</span>}
          </div>
        ))}
      </div>
      {roles.some(([, a]) => okAddr(a)) && (
        <div className="card" style={{ marginTop: 16 }}>
          <h4>{t("hsk.roles")}</h4>
          <dl className="kv">
            {roles.filter(([, a]) => okAddr(a)).map(([k, a]) => (
              <span key={k} style={{ display: "contents" }}><dt>{t(k)}</dt><dd><Ext href={H.addrUrl(a!)}>{a}</Ext></dd></span>
            ))}
          </dl>
          <p className="note">{t("hsk.roles.p")}</p>
        </div>
      )}
    </>
  );
}

function Proposal({ p, contract }: { p: HskProposal; contract?: string }) {
  const { t } = useI18n();
  const [state, setState] = useState<"idle" | "busy" | "ok" | "no" | "err">("idle");
  const [err, setErr] = useState("");
  const id = typeof p.id === "number" ? p.id : Number(p.id);
  const canVerify = okAddr(contract) && okHash(p.contentHash) && Number.isFinite(id);
  const run = async () => {
    if (!canVerify) return;
    setState("busy"); setErr("");
    try { const { verifyProposal } = await import("../lib/hskVerify"); setState((await verifyProposal(contract!, id, p.contentHash as `0x${string}`)) ? "ok" : "no"); }
    catch (e) { setState("err"); setErr(e instanceof Error ? e.message.split("\n")[0] : String(e)); }
  };
  const executed = (p.status ?? "").toLowerCase() === "executed";
  const steps: [DictKey, string | undefined][] = [["hsk.f1", p.proposeTx], ["hsk.f2", p.approveTx], ["hsk.f3", p.executeTx]];
  return (
    <div className="card">
      <div className="between">
        <h4>#{Number.isFinite(id) ? id : "?"} · {p.agent ?? "agent"}{p.kind ? <span className="muted"> · {p.kind}</span> : null}</h4>
        {p.status && <span className={"pill " + (executed ? "ok" : "gold")}>{p.status}</span>}
      </div>
      <ol className="timeline" style={{ listStyle: "none", margin: 0, padding: 0 }} aria-label={t("hsk.flow")}>
        {steps.map(([k, tx], i) => (
          <li key={k} className={"tl " + (okHash(tx) ? "done" : "")}>
            {i === 1 && <span className="gm" aria-hidden="true" />}
            <span className="nd" aria-hidden="true" />
            <span>{t(k)}</span>
            <TxLink h={tx} />
          </li>
        ))}
      </ol>
      <dl className="kv">
        {p.contentHash && <><dt>{t("hsk.hash")}</dt><dd>{p.contentHash}</dd></>}
        {p.modelId && <><dt>{t("hsk.model")}</dt><dd>{p.modelId}</dd></>}
      </dl>
      <div className="row">
        <button className="btn sm" type="button" onClick={run} disabled={!canVerify || state === "busy"}>
          {state === "busy" ? <span className="spinner" aria-hidden="true" /> : null}{t("hsk.verify")}
        </button>
        <span role="status" aria-live="polite">
          {state === "ok" && <span className="pill ok">✓ {t("hsk.v.ok")}</span>}
          {state === "no" && <span className="pill bad">✗ {t("hsk.v.no")}</span>}
          {state === "err" && <span className="pill bad" title={err}>✗ {t("hsk.v.err")}</span>}
        </span>
      </div>
    </div>
  );
}

function Dividends({ d }: { d: HskDemo }) {
  const { t, date, locale } = useI18n();
  const holders = Array.isArray(d.holders) ? d.holders : [];
  // payout token is DemoAUD (mAUD, 6 decimals): show whole mAUD, keep the raw base units in the tooltip
  const maud = new Intl.NumberFormat(locale, { minimumFractionDigits: 2, maximumFractionDigits: 6 });
  const isNum = (v: unknown) => typeof v === "number" || (typeof v === "string" && v.trim() !== "" && !isNaN(Number(v)));
  const num = (v: unknown) => (isNum(v) ? <span title={String(v)}>{maud.format(Number(v) / 1e6)} mAUD</span> : "–");
  const hasMeta = d.roundId != null || d.claimDeadline != null || d.dividendTotal != null || d.merkleRoot;
  if (!hasMeta && !holders.length) return <p className="empty">{t("hsk.div.empty")}</p>;
  return (
    <div className="cols">
      <div className="card">
        <h4>{t("hsk.div.round")}</h4>
        <dl className="kv">
          {d.roundId != null && <><dt>{t("hsk.div.id")}</dt><dd>{d.roundId}</dd></>}
          {d.dividendTotal != null && <><dt>{t("hsk.div.total")}</dt><dd>{num(d.dividendTotal)}</dd></>}
          {typeof d.claimDeadline === "number" && <><dt>{t("hsk.div.deadline")}</dt><dd>{date(d.claimDeadline * 1000, true)}</dd></>}
          {d.merkleRoot && <><dt>{t("hsk.div.root")}</dt><dd>{d.merkleRoot}</dd></>}
        </dl>
        <p className="note">{t("hsk.div.units")}</p>
      </div>
      <div className="card">
        <h4>{t("hsk.div.claims")}</h4>
        {holders.length ? (
          <div className="tbl">
            <table>
              <thead><tr><th>{t("t.wallet")}</th><th className="r">{t("hsk.div.amt")}</th></tr></thead>
              <tbody>
                {holders.map((h, i) => (
                  <tr key={i}>
                    <td className="mono">{okAddr(h.account) ? <Ext href={H.addrUrl(h.account)}>{shortAddr(h.account)}</Ext> : "–"}</td>
                    <td className="r num">{num(h.amount)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : <p className="note">{t("hsk.div.empty")}</p>}
      </div>
    </div>
  );
}

function Txs({ txs }: { txs?: Record<string, string> }) {
  const list = txs && typeof txs === "object" ? Object.entries(txs).filter(([, h]) => okHash(h)) : [];
  if (!list.length) return null;
  return (
    <div className="evlist">
      {list.map(([k, h]) => (
        <div key={k}>
          <i style={{ background: "var(--gold-mark)" }} />
          <span>{k.replace(/[_-]+/g, " ")}</span>
          <em><TxLink h={h} /></em>
        </div>
      ))}
    </div>
  );
}

function Pending() {
  const { t } = useI18n();
  return (
    <div className="banner gold" role="status">
      <span className="dot wait" aria-hidden="true" />
      <span><b>{t("hsk.pending")}</b> {t("hsk.pending.p")}</span>
    </div>
  );
}

export default function HskPage() {
  const { t } = useI18n();
  useTitle(t("hsk.title"));
  const q = useAsync(() => loadHskDemo(), [], 60000);
  const d = q.data;
  if (q.loading && d === undefined) return <Loading />;
  const prov = Array.isArray(d?.provenance) ? d!.provenance! : [];
  return (
    <div className="wrap page stack">
      <div className="head">
        <span className="eyebrow">{t("hsk.eyebrow")}</span>
        <h2>{t("hsk.title")}</h2>
        <p>{t("hsk.msg")}</p>
      </div>
      <div className="row">
        <AddBtn />
        <Ext href={H.explorer}>{t("hsk.explorer")} →</Ext>
        <span className="hint">Chain ID {H.id} ({H.hex}) · RPC {H.rpc}</span>
      </div>

      <section className="stack" aria-labelledby="hsk-flow">
        <h3 id="hsk-flow">{t("hsk.flow")}</h3>
        <HskFlow />
      </section>

      {!d ? <Pending /> : (
        <>
          <section className="stack" aria-labelledby="hsk-c">
            <h3 id="hsk-c">{t("hsk.contracts")}</h3>
            <Contracts d={d} />
          </section>

          <section className="stack" aria-labelledby="hsk-p">
            <h3 id="hsk-p">{t("hsk.prov")}</h3>
            <p className="note">{t("hsk.prov.p")}</p>
            {prov.length ? <div className="cols">{prov.map((p, i) => <Proposal key={p.id ?? i} p={p} contract={d.agentProvenance} />)}</div>
              : <p className="empty">{t("hsk.prov.empty")}</p>}
          </section>

          <section className="stack" aria-labelledby="hsk-d">
            <h3 id="hsk-d">{t("hsk.div")}</h3>
            <Dividends d={d} />
          </section>

          {d.txs && Object.keys(d.txs).length > 0 && (
            <section className="stack" aria-labelledby="hsk-t">
              <h3 id="hsk-t">{t("hsk.txs")}</h3>
              <div className="card"><Txs txs={d.txs} /></div>
            </section>
          )}
        </>
      )}
      <p><Link to="/">← {t("common.back")}</Link></p>
    </div>
  );
}
