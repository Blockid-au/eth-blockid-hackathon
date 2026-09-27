/**
 * Admin queue: share-price requests beyond ±20 % of the stage recommendation (docs/VALUATION-V5-API.md §3,
 * DECISIONS-V5 #5). Same shape as the other admin queues: one item per screen (/admin/pricing/<id>), j / k to move,
 * approve / reject with a note, then back to the founder step when opened from a gate link (?return=).
 * A different platform admin than the requester must decide (four-eyes; the server enforces it).
 */
import { useEffect, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { errText, useAuth } from "../../auth";
import { useAsync } from "../../lib/hooks";
import { api5 } from "../../components/v5/api5";
import { useFmt5 } from "../../components/v5/ui";
import type { PriceRequest } from "../../components/v5/types";
import "../../components/v5/v5.css";

const safe = (s: string | null) => (s && s.startsWith("/") && !s.startsWith("//") ? s : null);

/** Pending price requests; resolves to [] when v5 is off (404). */
export function usePricingQueue(poll: number | null) {
  return useAsync<PriceRequest[]>(() => api5.priceRequests().catch(() => []), [], poll);
}

function PriceTrackMini({ r }: { r: PriceRequest }) {
  const { aud, pct, t } = useFmt5();
  const lo = Math.min(r.recommended_price_aud * 0.4, r.requested_price_aud * 0.9), hi = Math.max(r.recommended_price_aud * 2, r.requested_price_aud * 1.1);
  const X = (p: number) => Math.max(0, Math.min(100, ((p - lo) / (hi - lo)) * 100));
  const rec = r.recommended_price_aud;
  return (
    <div className="v5" role="img" aria-label={t("v5.ad.track", { r: aud(rec, 4), p: aud(r.requested_price_aud, 4), d: pct(r.deviation_pct, 1) })}>
      <div className="ptrack">
        <span className="z adm" style={{ left: 0, width: "100%" }} />
        <span className="z free" style={{ left: X(rec * 0.8) + "%", width: X(rec * 1.2) - X(rec * 0.8) + "%" }} />
        <span className="rec" style={{ left: X(rec) + "%" }} />
        <span className="cur adm" style={{ left: X(r.requested_price_aud) + "%" }} />
      </div>
      <div className="plbls"><span style={{ left: X(rec) + "%", fontWeight: 700 }}>{aud(rec, 4)}</span><span style={{ left: X(r.requested_price_aud) + "%", top: 0 }}>{aud(r.requested_price_aud, 4)}</span></div>
    </div>
  );
}

export function PricingQueue({ q, onChanged }: { q: ReturnType<typeof usePricingQueue>; onChanged: () => void }) {
  const { t, aud, pct, date } = useFmt5();
  const { me } = useAuth();
  const { item } = useParams();
  const [params] = useSearchParams();
  const back = safe(params.get("return"));
  const nav = useNavigate();
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState("");
  const [msg, setMsg] = useState<{ ok: boolean; s: string } | null>(null);
  const items = q.data ?? [];
  const found = item ? items.findIndex((x) => String(x.id) === item) : 0;
  const idx = found < 0 ? 0 : found;
  const cur = items[idx];
  const go = (i: number) => { const x = items[i]; if (x) nav(`/admin/pricing/${x.id}${back ? "?return=" + encodeURIComponent(back) : ""}`); };
  useEffect(() => {
    const on = (e: KeyboardEvent) => {
      const el = document.activeElement as HTMLElement | null;
      if (e.altKey || e.ctrlKey || e.metaKey || (el && /^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName))) return;
      if (e.key === "j" && idx < items.length - 1) go(idx + 1);
      if (e.key === "k" && idx > 0) go(idx - 1);
    };
    window.addEventListener("keydown", on);
    return () => window.removeEventListener("keydown", on);
  }); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { setNote(""); }, [cur?.id]);

  const act = async (approve: boolean) => {
    if (!cur) return;
    if (!approve && note.trim().length < 5) { setMsg({ ok: false, s: t("v5.ad.reason5") }); return; }
    setBusy(true); setMsg(null);
    const after = items[idx + 1] ?? items[idx - 1];
    try {
      if (approve) await api5.approvePrice(cur.id, note.trim()); else await api5.rejectPrice(cur.id, note.trim());
      await q.reload(); onChanged();
      const okMsg = t(approve ? "v5.ad.approved" : "v5.ad.rejected");
      if (back) { nav(back, { state: { flash: okMsg } }); return; }
      setMsg({ ok: true, s: okMsg });
      nav(after ? `/admin/pricing/${after.id}` : "/admin/pricing", { replace: true });
    } catch (e) { setMsg({ ok: false, s: errText(e, t) }); } finally { setBusy(false); }
  };

  if (!q.data) return <p className="note">{t("common.loading")}</p>;
  const mine = !!cur && !!cur.requested_by && [me?.address, me?.username].filter(Boolean).some((w) => String(w).toLowerCase() === String(cur.requested_by).toLowerCase());
  return (
    <div className="stack adm5" aria-busy={busy}>
      {back && <p className="banner gold"><span>{t("v5.ad.return")}</span><Link to={back}>{t("ad.ret.go")} →</Link></p>}
      {msg && <p className={"banner " + (msg.ok ? "ok" : "bad")} role={msg.ok ? "status" : "alert"}>{msg.s}</p>}
      {!cur ? (
        <div className="pane">
          <p style={{ margin: 0 }}>{t("v5.ad.empty")}</p>
          <div className="row">
            {back && <Link className="btn sm" to={back}>{t("ad.ret.go")} →</Link>}
            <Link className="btn ghost sm" to="/admin">{t("ad.nav.inbox")}</Link>
          </div>
        </div>
      ) : (
        <>
          <div className="qhead">
            <span>{t("ad.q.pos", { i: idx + 1, n: items.length })}</span>
            <span className="row" style={{ gap: 6 }}>
              <span className="hint">{t("ad.q.keys")}</span>
              <button className="btn ghost sm" type="button" disabled={idx === 0} onClick={() => go(idx - 1)}>↑ {t("ad.q.prev")}</button>
              <button className="btn ghost sm" type="button" disabled={idx >= items.length - 1} onClick={() => go(idx + 1)}>{t("ad.q.next")} ↓</button>
            </span>
          </div>
          <div className="pane">
            <div className="between">
              <span><b>{cur.company_name || (cur.url ?? "").replace(/^https?:\/\//, "")}</b> <span className="muted-sm">#{cur.id}{cur.created_at ? " · " + date(cur.created_at, true) : ""}</span></span>
              <Link className="btn ghost sm" to={`/v/${encodeURIComponent(cur.valuation_id)}/report#finalise`}>{t("v5.ad.open")}</Link>
            </div>
            <p className="note">{t("v5.ad.p")}</p>
            <div className="v5 ktiles">
              <div className="kt"><small>{t("v5.fn.recprice.s")}</small><b>{aud(cur.recommended_price_aud, 4)}</b></div>
              <div className="kt"><small>{t("v5.ad.req")}</small><b>{aud(cur.requested_price_aud, 4)}</b><em>{(cur.deviation_pct > 0 ? "+" : "") + pct(cur.deviation_pct, 1)}</em></div>
            </div>
            <PriceTrackMini r={cur} />
            <dl className="kv">
              <dt>{t("v5.fn.reason")}</dt><dd style={{ fontFamily: "var(--body)", fontSize: ".86rem" }}>{cur.reason}</dd>
              {cur.note && <><dt>{t("v5.fn.note")}</dt><dd style={{ fontFamily: "var(--body)", fontSize: ".86rem" }}>{cur.note}</dd></>}
              {cur.requested_by && <><dt>{t("v5.ad.by")}</dt><dd>{cur.requested_by}</dd></>}
            </dl>
            {mine && <p className="banner warn">{t("v5.ad.mine")}</p>}
            <label className="lf"><span>{t("v5.ad.note")}</span><input value={note} maxLength={1000} onChange={(e) => setNote(e.target.value)} /></label>
            <div className="row">
              <span className="grow" />
              <button className="btn danger sm" type="button" disabled={busy} onClick={() => void act(false)}>{t("v5.ad.reject")}</button>
              <button className="btn gold" type="button" disabled={busy || mine} onClick={() => void act(true)}>{t("v5.ad.approve")}</button>
            </div>
          </div>
          {items.length > 1 && (
            <div className="pane">
              <h4>{t("v5.ad.h")} · {items.length}</h4>
              <ol className="qlist">
                {items.map((x, i) => (
                  <li key={x.id}><Link to={`/admin/pricing/${x.id}`} aria-current={i === idx ? "true" : undefined}><span className="mono">{String(i + 1).padStart(2, "0")}</span>{x.company_name || x.url} · {aud(x.requested_price_aud, 4)}</Link></li>
                ))}
              </ol>
            </div>
          )}
        </>
      )}
    </div>
  );
}
