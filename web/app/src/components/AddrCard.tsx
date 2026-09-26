import { useMemo, useState } from "react";
import qrcode from "qrcode-generator";
import { useI18n } from "../i18n";
import { addTokenToWallet, CHAINS, type ChainInfo } from "../wallet";
import { errText } from "../auth";
import { getAddress } from "viem";

export function QR({ text, label }: { text: string; label: string }) {
  const { n, d } = useMemo(() => {
    const q = qrcode(0, "M");
    q.addData(text);
    q.make();
    const n = q.getModuleCount();
    let d = "";
    for (let r = 0; r < n; r++) for (let c = 0; c < n; c++) if (q.isDark(r, c)) d += `M${c} ${r}h1v1h-1z`;
    return { n, d };
  }, [text]);
  return (
    <div className="qr" role="img" aria-label={label} style={{ background: "#fff", color: "#0D1B1E" }}>
      <svg viewBox={`-1 -1 ${n + 2} ${n + 2}`} shapeRendering="crispEdges" aria-hidden="true"><path d={d} fill="currentColor" /></svg>
    </div>
  );
}

function checksum(a: string) {
  try { return getAddress(a); } catch { return a; }
}

export function AddrCard({ chain, address, ticker, onToast }: { chain: ChainInfo; address?: string | null; ticker: string; onToast: (s: string) => void }) {
  const { t } = useI18n();
  const [busy, setBusy] = useState(false);
  const hoodi = chain.key === "hoodi" || chain.key === "hsk";
  const lbl = chain.key === "hoodi" ? t("s8.hoodi") : chain.key === "hsk" ? t("s8.hsk") : t("s8.local");
  if (!address) {
    return (
      <div className={"addrcard" + (hoodi ? " hoodi" : "")} style={{ gridTemplateColumns: "1fr" }}>
        <div>
          <div className="lbl">{lbl}</div>
          <div className="full muted">{t("c.notyet")}</div>
          <p className="note">{hoodi ? t("c.addr.hoodiwait") : t("c.addr.localwait")}</p>
        </div>
      </div>
    );
  }
  const addr = checksum(address);
  const copy = async () => {
    try { await navigator.clipboard.writeText(addr); } catch { /* ignore: selection still possible */ }
    onToast(t("toast.copied"));
  };
  const add = async () => {
    setBusy(true);
    try {
      await addTokenToWallet(chain, addr, ticker);
      onToast(t("toast.added"));
    } catch (e) {
      onToast(errText(e, t));
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className={"addrcard" + (hoodi ? " hoodi" : "")}>
      <div><div className="lbl">{lbl}</div><div className="full">{addr}</div></div>
      <QR text={addr} label={t("c.qr", { a: addr })} />
      <div className="acts">
        <button className="btn ghost sm" type="button" onClick={copy}>{t("s8.copy")}</button>
        <a className="btn ghost sm" href={chain.tokenUrl(addr)} target="_blank" rel="noopener noreferrer">{chain.key === "hoodi" ? t("s8.ether") : chain.key === "hsk" ? t("s8.hskscan") : t("s8.scan")}</a>
        <button className={"btn sm" + (hoodi ? " gold" : "")} type="button" onClick={add} disabled={busy}>{t("s8.add")}</button>
      </div>
    </div>
  );
}

export function NetworkDetails() {
  const { t } = useI18n();
  const L = CHAINS.local, H = CHAINS.hoodi, K = CHAINS.hsk;
  return (
    <div className="card">
      <h4>{t("s8.net")}</h4>
      <dl className="kv">
        <dt>{t("s8.name")}</dt><dd>{L.name}</dd><dt>RPC</dt><dd>{L.rpc}</dd><dt>Chain ID</dt><dd>{L.id} ({L.hex})</dd><dt>{t("s8.sym")}</dt><dd>{L.currency} · {t("s8.dec18")}</dd><dt>Explorer</dt><dd><a href={L.explorer} target="_blank" rel="noopener noreferrer">{L.explorer}</a></dd>
      </dl>
      <dl className="kv" style={{ borderTop: "1px solid var(--line)", paddingTop: 10 }}>
        <dt>{t("s8.name")}</dt><dd>{H.name}</dd><dt>RPC</dt><dd>{H.rpc}</dd><dt>Chain ID</dt><dd>{H.id} ({H.hex})</dd><dt>{t("s8.sym")}</dt><dd>{H.currency} · {t("s8.dec18")}</dd><dt>Explorer</dt><dd><a href={H.explorer} target="_blank" rel="noopener noreferrer">{H.explorer}</a></dd>
      </dl>
      <dl className="kv" style={{ borderTop: "1px solid var(--line)", paddingTop: 10 }}>
        <dt>{t("s8.name")}</dt><dd>{K.name}</dd><dt>RPC</dt><dd>{K.rpc}</dd><dt>Chain ID</dt><dd>{K.id} ({K.hex})</dd><dt>{t("s8.sym")}</dt><dd>{K.currency} · {t("s8.dec18")}</dd><dt>Explorer</dt><dd><a href={K.explorer} target="_blank" rel="noopener noreferrer">{K.explorer}</a></dd>
      </dl>
    </div>
  );
}

export function ManualSteps({ ticker }: { ticker: string }) {
  const { t } = useI18n();
  return (
    <div className="card">
      <h4>{t("s8.manual")}</h4>
      <ol className="steps">
        <li>{t("s8.m1")}</li>
        <li>{t("s8.m2")}</li>
        <li>{t("s8.m3").replace("HBL", ticker)}</li>
        <li>{t("s8.m4")}</li>
        <li>{t("s8.m5")}</li>
      </ol>
    </div>
  );
}
