/**
 * Finalise & pricing (before tokenisation) — docs/VALUATION-V5-API.md §3, docs/DECISIONS-V5.md #5 and #7.
 *   1 Review the value range + confidence
 *   2 Price per share: recommended by stage; the founder may adjust it (within ±20 % at once with a note; beyond →
 *     a written reason and a different platform admin approves); live preview of share count, founder / investor
 *     split and offer price range
 *   3 Confirm → frozen proposal with an expiry (90 days)
 */
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import type { Valuation as Val } from "../../api";
import { errText } from "../../auth";
import { Bars100, RangeChart } from "../../components/charts";
import { api5 } from "../../components/v5/api5";
import { ConfPill, SeeHow, StageBadge, useFmt5 } from "../../components/v5/ui";
import { readFinal, STAGE_PRICE, stageKey, type TokView, type V5, type ValuationFinal } from "../../components/v5/types";
import { demoApproveLink } from "../../components/DemoGuide";
import { valPath } from "../../lib/flow";

/** Share count for a chosen price, the server's way: the recommendation keeps its clean count; any other price
 *  divides the value by it (existing companies keep their fully diluted count and the implied value moves). */
export function sharesFor(tok: TokView, pre: number, price: number): number {
  const p = tok.proposal;
  if (p?.fd_shares_existing) return p.fd_shares_existing;
  if (p && Math.abs(price - p.recommended_price_aud) < 1e-9) return p.total_shares;
  return price > 0 ? Math.round(pre / price) : 0;
}

/* ---------------- frozen proposal ---------------- */
export function FrozenCard({ f, v, state, compact }: { f: ValuationFinal; v: Val; state: TokView["final_state"]; compact?: boolean }) {
  const { t, money, aud, fmt, date, pct } = useFmt5();
  const ok = state === "valid";
  return (
    <div className={"frozen" + (ok ? "" : " pend")} role="status">
      <div className="between">
        <b>{t(("v5.fz.st." + state) as "v5.fz.st.valid")}</b>
        {f.valid_until && <span className={"pill " + (ok ? "ok" : "bad")}>{t(ok ? "v5.fz.until" : "v5.fz.ended", { d: date(f.valid_until) })}</span>}
      </div>
      <div className="ktiles">
        <div className="kt"><small>{t("v5.fz.value")}</small><b>{money(f.pre_money_aud)}</b><em>{money(f.low_aud)} – {money(f.high_aud)}</em></div>
        <div className="kt"><small>{t("v5.fz.price")}</small><b>{aud(f.price_per_share_aud, 4)}</b><em>{t("v5.fz.rec", { p: aud(f.recommended_price_aud, 4), d: (f.deviation_pct > 0 ? "+" : "") + pct(f.deviation_pct, 1) })}</em></div>
        <div className="kt"><small>{t("v5.fz.shares")}</small><b>{fmt(f.total_shares)}</b></div>
        <div className="kt"><small>{t("v5.fz.offer")}</small><b>{aud(f.offer_price_low_aud, 4)} – {aud(f.offer_price_high_aud, 4)}</b></div>
      </div>
      {!compact && (
        <>
          {(f.planned_raise_aud ?? 0) > 0 && <p className="sub">{t("v5.fz.raise", { r: money(f.planned_raise_aud ?? 0), n: fmt(f.new_shares ?? 0), d: pct(f.dilution_pct ?? 0, 1), v: money(f.post_money_aud ?? 0) })}</p>}
          {f.note && <p className="sub">{t("v5.fz.note")}: {f.note}</p>}
          {f.reason && <p className="sub">{t("v5.fz.reason")}: {f.reason}{f.approved_by ? " · " + t("v5.fz.approvedby", { a: f.approved_by }) : ""}</p>}
          {f.low_confidence_override && <p className="sub">{t("v5.fz.override", { a: f.low_confidence_override.by, r: f.low_confidence_override.reason })}</p>}
          {f.based_on_projections && <p className="lbl-proj">{t("v5.proj.label")}</p>}
          <p className="hint">{f.finalised_at ? t("v5.fz.at", { d: date(f.finalised_at, true) }) : ""}{f.report_hash ? " · " + t("v5.fz.hash", { h: f.report_hash.slice(0, 12) + "…" }) : ""}</p>
          {ok && <Link className="btn sm" style={{ justifySelf: "start" }} to={valPath(v.id, 4)}>{t("v5.fz.next")} →</Link>}
        </>
      )}
    </div>
  );
}

/* ---------------- price track: free band, admin zone, recommended mark, chosen price ---------------- */
function PriceTrack({ rec, price, lo, hi, band }: { rec: number; price: number; lo: number; hi: number; band: number }) {
  const { aud } = useFmt5();
  const X = (p: number) => Math.max(0, Math.min(100, ((p - lo) / (hi - lo)) * 100));
  const adm = Math.abs(price / rec - 1) > band + 1e-9;
  return (
    <div aria-hidden="true">
      <div className="ptrack">
        <span className="z adm" style={{ left: 0, width: "100%" }} />
        <span className="z free" style={{ left: X(rec * (1 - band)) + "%", width: X(rec * (1 + band)) - X(rec * (1 - band)) + "%" }} />
        <span className="rec" style={{ left: X(rec) + "%" }} />
        <span className={"cur" + (adm ? " adm" : "")} style={{ left: X(price) + "%" }} />
      </div>
      <div className="plbls">
        <span style={{ left: X(rec * (1 - band)) + "%" }}>{aud(rec * (1 - band), 3)}</span>
        <span style={{ left: X(rec) + "%", fontWeight: 700 }}>{aud(rec, 3)}</span>
        <span style={{ left: X(rec * (1 + band)) + "%" }}>{aud(rec * (1 + band), 3)}</span>
      </div>
    </div>
  );
}

function Pending({ tok, v, isAdmin, onChanged }: { tok: TokView; v: Val; isAdmin: boolean; onChanged: (x: TokView | null) => void }) {
  const { t, aud, pct, date } = useFmt5();
  const r = tok.pending!;
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const cancel = async () => { setBusy(true); setErr(""); try { onChanged(await api5.cancelPriceRequest(v.id, r.id)); } catch (e) { setErr(errText(e, t)); } finally { setBusy(false); } };
  return (
    <div className="frozen pend" role="status">
      <div className="between"><b>{t("v5.pr.h")}</b><span className="gatepill">◆ {t("gate.admin")}</span></div>
      <div className="ktiles">
        <div className="kt"><small>{t("v5.fn.recprice.s")}</small><b>{aud(r.recommended_price_aud, 4)}</b></div>
        <div className="kt"><small>{t("v5.fn.yourprice")}</small><b>{aud(r.requested_price_aud, 4)}</b><em>{(r.deviation_pct > 0 ? "+" : "") + pct(r.deviation_pct, 1)}</em></div>
      </div>
      <p className="sub">{t("v5.fn.reason")}: {r.reason}</p>
      {r.created_at && <p className="hint">{t("v5.pr.at", { d: date(r.created_at, true) })}</p>}
      <p className="sub">{t("v5.pr.p")}</p>
      <div className="row">
        {!isAdmin && <Link className="btn ghost sm" to={demoApproveLink(`/admin/pricing/${r.id}`, valPath(v.id, 3) + "#finalise")}>{t("v5.fz.gate")} →</Link>}
        <button type="button" className="btn ghost sm" disabled={busy} onClick={() => void cancel()}>{t("v5.pr.cancel")}</button>
      </div>
      {err && <p className="err" role="alert">{err}</p>}
    </div>
  );
}

export function Finalise({ v, x, tok, isAdmin, onChanged }: { v: Val; x: V5; tok: TokView | null; isAdmin: boolean; onChanged: (t: TokView | null) => void }) {
  const { t, money, aud, fmt, pct, stage: sl } = useFmt5();
  const p = tok?.proposal ?? x.tri?.tokenisation ?? null;
  const stage = stageKey(p?.stage || x.eval?.stage.stage || x.tri?.stage_class?.stage || "seed");
  const pre = p?.pre_money_aud ?? x.tri?.value_aud ?? v.svi!.valuation_mid_aud;
  const low = p?.low_aud ?? x.tri?.low_aud ?? v.svi!.valuation_low_aud;
  const high = p?.high_aud ?? x.tri?.high_aud ?? v.svi!.valuation_high_aud;
  const rec = p?.recommended_price_aud ?? tok?.rules.default_price_by_stage[stage] ?? STAGE_PRICE[stage] ?? 1;
  const band = (tok?.rules.free_band_pct ?? 20) / 100;
  const days = tok?.rules.validity_days ?? 90;
  const hardLo = rec * (tok?.rules.hard_min_ratio ?? 0.2), hardHi = rec * (tok?.rules.hard_max_ratio ?? 5);
  const conf = tok?.confidence ?? x.tri?.confidence ?? "medium";
  const [step, setStep] = useState(1);
  const [priceS, setPriceS] = useState(() => String(rec));
  useEffect(() => { setPriceS(String(rec)); }, [rec]);
  const [raiseS, setRaiseS] = useState(() => (p?.raise_aud ? String(Math.round(p.raise_aud)) : ""));
  const [note, setNote] = useState("");
  const [reason, setReason] = useState("");
  const [override, setOverride] = useState("");
  const [ok, setOk] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [again, setAgain] = useState(false);

  if (!tok) return <div className="card"><h4>{t("v5.fn.h")}</h4><p className="sub">{t("common.loading")}</p></div>;
  if (tok.final && tok.final_state === "valid") return <FrozenCard f={tok.final} v={v} state="valid" />;
  if (tok.pending && tok.pending.status === "pending") return <Pending tok={tok} v={v} isAdmin={isAdmin} onChanged={onChanged} />;
  if (v.status !== "approved") {
    return (
      <div className="card" style={{ borderStyle: "dashed" }}>
        <h4>{t("v5.fn.h")}</h4>
        <p className="sub">{t("v5.fn.wait")}</p>
        <div className="ktiles"><div className="kt"><small>{t("v5.fn.recprice", { s: sl(stage) })}</small><b>{aud(rec, 4)}</b></div><div className="kt"><small>{t("v5.fn.value")}</small><b>{money(pre)}</b></div></div>
      </div>
    );
  }
  const old = tok.final && (tok.final_state === "expired" || tok.final_state === "stale") ? tok.final : null;
  if (old && !again) {
    return (
      <div className="stack">
        <FrozenCard f={old} v={v} state={tok.final_state} compact />
        <p className="banner warn">{t(tok.final_state === "stale" ? "v5.fn.stale" : "v5.fn.expired", { d: days })}</p>
        <button type="button" className="btn" style={{ justifySelf: "start" }} onClick={() => setAgain(true)}>{t("v5.fn.again")}</button>
      </div>
    );
  }

  const price = Number(priceS);
  const priceOk = Number.isFinite(price) && price > 0 && price >= hardLo - 1e-9 && price <= hardHi + 1e-9;
  const shares = priceOk ? sharesFor(tok, pre, price) : 0;
  const implied = shares * (priceOk ? price : 0);
  const dev = priceOk ? price / rec - 1 : 0;
  const changed = Math.abs(dev) > 1e-9;
  const outBand = Math.abs(dev) > band + 1e-9;
  const lowConf = conf === "low";
  const raise = Math.max(0, Number(raiseS.replace(/\D/g, "")) || 0);
  const newShares = priceOk && price > 0 ? Math.floor(raise / price) : 0;
  const founderPct = shares ? (shares / (shares + newShares)) * 100 : 100;
  const offLo = shares ? low / shares : 0, offHi = priceOk ? price : 0;
  const noteOk = outBand || !changed || note.trim().length >= 3;
  const reasonOk = !outBand || reason.trim().length >= 20;
  const overrideOk = !lowConf || (isAdmin && override.trim().length >= 10);
  const tooFew = priceOk && shares > 0 && shares < 10_000;
  const slLo = Math.max(hardLo, rec * 0.4), slHi = Math.min(hardHi, rec * 2);
  const blockers = tok.blockers.filter((b) => !(isAdmin && lowConf && /confidence/i.test(b)));
  const until = new Date(Date.now() + days * 864e5);

  const submit = async () => {
    setBusy(true); setErr("");
    try {
      const r = await api5.finalise(v.id, {
        ...(changed ? { price_per_share_aud: +price.toFixed(4) } : {}),
        ...(changed && !outBand ? { note: note.trim() } : note.trim() ? { note: note.trim() } : {}),
        ...(outBand ? { reason: reason.trim() } : {}),
        ...(lowConf && isAdmin ? { allow_low_confidence: true, override_reason: override.trim() } : {}),
        planned_raise_aud: raise,
      });
      setAgain(false);
      onChanged(r);
    } catch (e) { setErr(errText(e, t)); } finally { setBusy(false); }
  };

  const STEPS = [t("v5.fn.s1"), t("v5.fn.s2"), t("v5.fn.s3")];
  const canNext = step !== 2 || (priceOk && !tooFew && noteOk && reasonOk);
  return (
    <div className="card wz">
      <div className="between">
        <div><h4>{t("v5.fn.h")}</h4><p className="sub">{t("v5.fn.p")}</p></div>
        <StageBadge stage={stage} />
      </div>
      <ol className="wzsteps" style={{ ["--n" as string]: 3 }}>
        {STEPS.map((s, i) => (
          <li key={i} className={i + 1 === step ? "on" : i + 1 < step ? "done" : ""} aria-current={i + 1 === step ? "step" : undefined}>
            {i + 1 < step ? <button type="button" onClick={() => setStep(i + 1)}><b>{String(i + 1).padStart(2, "0")}</b><span>{s}</span></button> : <span><b>{String(i + 1).padStart(2, "0")}</b><span>{s}</span></span>}
          </li>
        ))}
      </ol>

      {step === 1 && (
        <div className="stack">
          <RangeChart low={low} mid={pre} high={high} />
          <div className="row" style={{ gap: 8 }}><ConfPill c={conf} />{x.tri?.uses_projections && <span className="lbl-proj">* {t("v5.proj.label")}</span>}</div>
          {x.tri && x.tri.confidence_reasons.length > 0 && (
            <SeeHow label={t("v5.ov.why.conf")}><ul className="checks">{x.tri.confidence_reasons.map((r, i) => <li key={i} className="info"><span className="ic" aria-hidden="true">i</span><span>{r}</span></li>)}</ul></SeeHow>
          )}
          {lowConf ? <p className="banner warn">{t(isAdmin ? "v5.fn.lowconf.adm" : "v5.fn.lowconf")}</p> : <p className="banner ok">{t("v5.fn.confok")}</p>}
          {blockers.length > 0 && <ul className="checks">{blockers.map((b, i) => <li key={i} className="warning"><span className="ic" aria-hidden="true">!</span><span>{b}</span></li>)}</ul>}
          <p className="sub">{t("v5.fn.s1.p", { d: days })}</p>
        </div>
      )}

      {step === 2 && (
        <div className="pricebox">
          <div className="between">
            <span>{t("v5.fn.recprice", { s: sl(stage) })} <b>{aud(rec, 4)}</b></span>
            {changed && <button type="button" className="btn ghost sm" onClick={() => setPriceS(String(rec))}>{t("v5.fn.reset")}</button>}
          </div>
          <div className="pr">
            <label className="lf" style={{ gap: 4 }}><span>{t("v5.fn.yourprice")}</span>
              <span className="srin" style={{ maxWidth: 200 }}><i aria-hidden="true">A$</i><input type="text" inputMode="decimal" className="inp" value={priceS} aria-invalid={!priceOk || tooFew} aria-describedby="fn-dev" onChange={(e) => setPriceS(e.target.value.replace(/[^\d.]/g, ""))} /></span>
            </label>
            <span id="fn-dev" className={"pill " + (outBand ? "gold" : "ok")} role="status">{priceOk ? (!changed ? t("v5.fn.dev0") : t("v5.fn.dev", { d: (dev > 0 ? "+" : "") + pct(dev * 100, 1) })) : "–"}</span>
          </div>
          <PriceTrack rec={rec} price={priceOk ? Math.min(Math.max(price, slLo), slHi) : rec} lo={slLo} hi={slHi} band={band} />
          <input type="range" min={slLo} max={slHi} step={rec / 100} value={priceOk ? Math.min(Math.max(price, slLo), slHi) : rec} aria-label={t("v5.fn.yourprice")} aria-valuetext={aud(priceOk ? price : 0, 4)}
            onChange={(e) => setPriceS(String(+Number(e.target.value).toFixed(4)))} />
          <div className="legend5"><span><i className="sw" style={{ background: "var(--accent-soft)", border: "1px solid var(--accent)" }} />{t("v5.fn.zone.free", { b: pct(band * 100, 0) })}</span><span><i className="sw" style={{ background: "var(--gold-soft)", border: "1px dashed var(--gold-mark)" }} />{t("v5.fn.zone.adm")}</span><span><i className="mk" />{t("v5.fn.zone.rec")}</span></div>
          {!priceOk && <p className="hint bad">{t("v5.fn.bad", { lo: aud(hardLo, 4), hi: aud(hardHi, 4) })}</p>}
          {tooFew && <p className="hint bad">{t("v5.fn.few", { n: fmt(10_000) })}</p>}

          <div className="ktiles">
            <div className="kt"><small>{t("v5.fn.shares")}</small><b>{fmt(shares)}</b><em>{p?.fd_shares_existing ? t("v5.fn.existing") : t("v5.fn.newco")}</em></div>
            <div className="kt"><small>{t("v5.fn.offer")}</small><b>{aud(offLo, 4)} – {aud(offHi, 4)}</b><em>{t("v5.fn.offer.p")}</em></div>
            <div className="kt"><small>{t("v5.fn.implied")}</small><b>{money(implied)}</b><em>{t("v5.fn.implied.p", { v: money(pre) })}</em></div>
          </div>
          <label className="lf"><span>{t("v5.fn.raise")}</span>
            <span className="srin" style={{ maxWidth: 260 }}><i aria-hidden="true">A$</i><input type="text" inputMode="numeric" value={raiseS ? fmt(Number(raiseS)) : ""} placeholder="0" onChange={(e) => setRaiseS(e.target.value.replace(/\D/g, ""))} /></span>
            <span className="hint">{t(p?.raise_aud ? "v5.fn.raise.pj" : "v5.fn.raise.p")}</span>
          </label>
          <Bars100 label={t("v5.fn.split")} parts={[{ name: t("v5.fn.founders"), v: shares, c: "--c1" }, { name: t("v5.fn.investors"), v: newShares, c: "--c3" }]} />
          <div className="legend5">
            <span><i className="sw" style={{ background: "var(--c1)" }} />{t("v5.fn.founders")} · {pct(founderPct, 1)} · {fmt(shares)}</span>
            <span><i className="sw" style={{ background: "var(--c3)" }} />{t("v5.fn.investors")} · {pct(100 - founderPct, 1)} · {fmt(newShares)}</span>
          </div>
          {raise > 0 && <p className="sub">{t("v5.fn.post", { v: money(implied + raise) })}</p>}

          {outBand ? (
            <div className="approve">
              <b>{t("v5.fn.needadmin")}</b>
              <p className="sub">{t("v5.fn.needadmin.p", { b: pct(band * 100, 0) })}</p>
              <label className="lf"><span>{t("v5.fn.reason")}</span><textarea value={reason} maxLength={1000} aria-invalid={!reasonOk} onChange={(e) => setReason(e.target.value)} placeholder={t("v5.fn.reason.ph")} /></label>
              <span className={"hint" + (reasonOk ? "" : " bad")}>{t("v5.fn.reason.min", { n: 20, c: reason.trim().length })}</span>
            </div>
          ) : (
            <label className="lf"><span>{t(changed ? "v5.fn.note.req" : "v5.fn.note")}</span><textarea value={note} maxLength={500} aria-invalid={!noteOk} onChange={(e) => setNote(e.target.value)} placeholder={t("v5.fn.note.ph")} /><span className={"hint" + (noteOk ? "" : " bad")}>{t(changed ? "v5.fn.note.min" : "v5.fn.note.p")}</span></label>
          )}
        </div>
      )}

      {step === 3 && (
        <div className="stack">
          <dl className="dl5">
            <dt>{t("v5.fn.value")}</dt><dd>{money(pre)} ({money(low)} – {money(high)})</dd>
            <dt>{t("v5.fn.recprice.s")}</dt><dd>{aud(rec, 4)}</dd>
            <dt>{t("v5.fn.yourprice")}</dt><dd><b>{aud(price, 4)}</b> {changed && <span className="muted-sm">({(dev > 0 ? "+" : "") + pct(dev * 100, 1)})</span>}</dd>
            <dt>{t("v5.fn.shares")}</dt><dd>{fmt(shares)}</dd>
            <dt>{t("v5.fn.offer")}</dt><dd>{aud(offLo, 4)} – {aud(offHi, 4)}</dd>
            <dt>{t("v5.fn.valid")}</dt><dd>{t("v5.fn.valid.v", { d: days, until: until.toLocaleDateString() })}</dd>
            {(note.trim() || reason.trim()) && <><dt>{outBand ? t("v5.fn.reason") : t("v5.fn.note")}</dt><dd>{outBand ? reason.trim() : note.trim()}</dd></>}
          </dl>
          {outBand && <p className="banner gold">{t("v5.fn.goesadmin")}</p>}
          {lowConf && isAdmin && (
            <div className="approve">
              <b>{t("v5.fn.lowconf.h")}</b>
              <label className="lf"><span>{t("v5.fn.override")}</span><textarea value={override} maxLength={1000} aria-invalid={!overrideOk} onChange={(e) => setOverride(e.target.value)} /></label>
              <span className={"hint" + (overrideOk ? "" : " bad")}>{t("v5.fn.reason.min", { n: 10, c: override.trim().length })}</span>
            </div>
          )}
          {lowConf && !isAdmin && <p className="banner warn">{t("v5.fn.lowconf")}</p>}
          <label className="row" style={{ alignItems: "flex-start", fontSize: ".86rem" }}>
            <input type="checkbox" checked={ok} onChange={(e) => setOk(e.target.checked)} style={{ marginTop: 4 }} />
            <span>{t("v5.fn.attest", { d: days })}</span>
          </label>
          {err && <p className="err" role="alert">{err}</p>}
        </div>
      )}

      <div className="wznav">
        {step > 1 ? <button type="button" className="btn ghost" onClick={() => setStep(step - 1)}>← {t("common.back")}</button> : <span />}
        {step < 3 ? (
          <button type="button" className="btn" disabled={!canNext} onClick={() => setStep(step + 1)}>{t("v5.fn.next")} →</button>
        ) : (
          <button type="button" className="btn gold" disabled={!ok || busy || !priceOk || !reasonOk || !noteOk || !overrideOk || (lowConf && !isAdmin)} onClick={() => void submit()}>{busy ? <span className="spinner" aria-hidden="true" /> : null}{outBand ? t("v5.fn.submitadm") : t("v5.fn.submit")}</button>
        )}
      </div>
    </div>
  );
}

/* ---------------- hand-off for company creation (step 5) ---------------- */
/** The valid final of a v5 valuation (null when the flag is off, no v5 data, or no valid final). */
export function useFinal(v: Val | null | undefined, enabled: boolean) {
  const [tok, setTok] = useState<TokView | null>(null);
  useEffect(() => {
    if (!v || !enabled) { setTok(null); return; }
    let live = true;
    api5.tokenisation(v.id).then((x) => { if (live) setTok(x); }).catch(() => { if (live) setTok(null); });
    return () => { live = false; };
  }, [v?.id, enabled]); // eslint-disable-line react-hooks/exhaustive-deps
  return tok;
}

export function FinalHint({ v, tok }: { v: Val; tok: TokView | null }) {
  const { t, aud, fmt, date } = useFmt5();
  if (!tok) return null;
  const f = tok.final;
  if (f && tok.final_state === "valid") return <p className="quietline"><span>✓ {t("v5.hint.final", { n: fmt(f.total_shares), p: aud(f.price_per_share_aud, 4), d: f.valid_until ? date(f.valid_until) : "–" })}</span></p>;
  return (
    <p className="quietline bad" role="status">
      <span>{t(tok.pending ? "v5.hint.pending" : f ? "v5.hint.expired" : "v5.hint.first")}</span>
      <Link to={valPath(v.id, 3) + "#finalise"}>{t("v5.fn.h")} →</Link>
    </p>
  );
}

/** Offering form: the finalised price the server now uses as the default (`defaults.final`, VALUATION_V5 only). */
export function OfferFinalNote({ final }: { final: unknown }) {
  const { t, aud, date } = useFmt5();
  const f = readFinal(final);
  if (!f) return null;
  const ok = !f.valid_until || +new Date(f.valid_until) > Date.now();
  return <span className={"muted-sm" + (ok ? "" : " bad")}>{ok ? t("v5.of.final", { p: aud(f.price_per_share_aud, 4), lo: aud(f.offer_price_low_aud, 4), hi: aud(f.offer_price_high_aud, 4), d: f.valid_until ? date(f.valid_until) : "–" }) : t("v5.of.expired")}</span>;
}
