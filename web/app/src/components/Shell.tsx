import { useEffect, type ReactNode } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useI18n } from "../i18n";
import type { DictKey } from "../dict";
import { GATE_AFTER, PHASES, type GateState } from "../lib/flow";

/* ================= layout: side rail + main column ================= */
export function SideLayout({ rail, label, children }: { rail: ReactNode; label: string; children: ReactNode }) {
  return (
    <section className="shellpage">
      <div className="wrap wide shell">
        <aside className="rail" aria-label={label}>{rail}</aside>
        <div className="shellmain">{children}</div>
      </div>
    </section>
  );
}

export function RailGroup({ title, aside, children }: { title?: ReactNode; aside?: ReactNode; children: ReactNode }) {
  return (
    <div className="rgroup">
      {title != null && <div className="rh"><span>{title}</span>{aside != null && <span>{aside}</span>}</div>}
      <ul>{children}</ul>
    </div>
  );
}

interface RailItemProps {
  to?: string | null;
  current?: boolean;
  done?: boolean;
  mark?: ReactNode;
  count?: number | null;
  gate?: boolean;
  hint?: string;
  external?: boolean;
  children: ReactNode;
}
/** One rail entry: a link, or a disabled row when `to` is missing. */
export function RailItem({ to, current, done, mark, count, gate, hint, children }: RailItemProps) {
  const cls = "ri" + (done ? " done" : "") + (current ? " cur" : "");
  const inner = (
    <>
      {mark != null && <span className="rdot" aria-hidden="true">{done && !current ? "✓" : mark}</span>}
      <span className="rlabel">{children}</span>
      {gate && <span className="rgm" aria-hidden="true">◆</span>}
      {count != null && <span className={"rcnt" + (count > 0 ? " hot" : "")}>{count}</span>}
    </>
  );
  return (
    <li>
      {to ? (
        <Link className={cls} to={to} aria-current={current ? "page" : undefined} title={hint}>{inner}</Link>
      ) : (
        <span className={cls + " off"} aria-disabled="true" title={hint}>{inner}</span>
      )}
    </li>
  );
}

export function GateRow({ n, state }: { n: 1 | 2; state: GateState }) {
  const { t } = useI18n();
  const k = (`flow.g${n}` + (state === "ok" ? ".ok" : state === "bad" ? ".bad" : state === "wait" ? ".wait" : "")) as DictKey;
  return <li className={"gaterow " + state}><span>{t(k)}</span></li>;
}

/** The 8-step founder flow rail. `href(n)` returns a link for reachable steps, null otherwise. */
export function FlowRail({ cur, reach, href, gates, after }: { cur: number; reach: number; href: (n: number) => string | null; gates: [GateState, GateState]; after?: ReactNode }) {
  const { t } = useI18n();
  return (
    <>
      {PHASES.map((p) => (
        <RailGroup key={p.key} title={t(("flow.ph." + p.key) as DictKey)}>
          {p.steps.map((n) => {
            const to = n <= reach ? href(n) : null;
            const g = GATE_AFTER[n];
            return (
              <FlowStepItem key={n} n={n} cur={cur} reach={reach} to={to} gate={g ? gates[g - 1] : undefined} />
            );
          })}
        </RailGroup>
      ))}
      {after}
    </>
  );
}
function FlowStepItem({ n, cur, reach, to, gate }: { n: number; cur: number; reach: number; to: string | null; gate?: GateState }) {
  const { t } = useI18n();
  return (
    <>
      <RailItem to={to} current={n === cur} done={n < reach || (n === reach && n !== cur && n === 8)} mark={String(n).padStart(2, "0")} hint={to ? undefined : t("flow.locked")}>
        {t(("step." + n) as DictKey)}
      </RailItem>
      {gate && <GateRow n={GATE_AFTER[n]} state={gate} />}
    </>
  );
}

/* ================= page header inside the main column ================= */
export function Crumbs({ items }: { items: { to?: string; label: ReactNode }[] }) {
  const { t } = useI18n();
  return (
    <nav className="crumbs" aria-label={t("crumb.label")}>
      {items.map((x, i) => (
        <span key={i}>{i > 0 && <span aria-hidden="true" className="sep">›</span>}{x.to && i < items.length - 1 ? <Link to={x.to}>{x.label}</Link> : <b>{x.label}</b>}</span>
      ))}
    </nav>
  );
}

export function StepHead({ eyebrow, title, desc, right }: { eyebrow?: ReactNode; title: ReactNode; desc?: ReactNode; right?: ReactNode }) {
  return (
    <header className="shead">
      <div>
        {eyebrow && <span className="eyebrow">{eyebrow}</span>}
        <h1>{title}</h1>
        {desc && <p>{desc}</p>}
      </div>
      {right && <div className="sright">{right}</div>}
    </header>
  );
}

/* ================= pager: previous / next with the reason when blocked ================= */
export interface PagerLink { to?: string; label: ReactNode; onClick?: () => void; disabled?: boolean; primary?: boolean; busy?: boolean }
export function Pager({ prev, next, reason, keys = true }: { prev?: PagerLink | null; next?: PagerLink | null; reason?: string | null; keys?: boolean }) {
  const nav = useNavigate();
  useEffect(() => {
    if (!keys) return;
    const on = (e: KeyboardEvent) => {
      if (e.altKey || e.ctrlKey || e.metaKey || e.shiftKey) return;
      const el = document.activeElement as HTMLElement | null;
      if (el && (/^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName) || el.isContentEditable)) return;
      const go = (l?: PagerLink | null) => { if (!l || l.disabled) return; if (l.onClick) l.onClick(); else if (l.to) nav(l.to); };
      if (e.key === "ArrowLeft") go(prev);
      if (e.key === "ArrowRight") go(next);
    };
    window.addEventListener("keydown", on);
    return () => window.removeEventListener("keydown", on);
  }, [prev, next, keys, nav]);
  const btn = (l: PagerLink, side: "prev" | "next") => {
    const cls = "btn" + (side === "prev" || l.primary === false ? " ghost" : "");
    const body = <>{side === "prev" && <span aria-hidden="true">←</span>}{l.busy ? <span className="spinner" aria-hidden="true" /> : null}{l.label}{side === "next" && <span aria-hidden="true">→</span>}</>;
    if (l.to && !l.disabled && !l.onClick) return <Link className={cls} to={l.to}>{body}</Link>;
    return <button className={cls} type="button" disabled={l.disabled} onClick={l.onClick ?? (() => l.to && nav(l.to))}>{body}</button>;
  };
  return (
    <div className="pager">
      <span className="pl">{prev ? btn(prev, "prev") : null}</span>
      <span className="pr">{reason && <span className="why" role="status">{reason}</span>}{next ? btn(next, "next") : null}</span>
    </div>
  );
}

/* ================= gate card: waiting for a person, with a deep link to the exact admin item ================= */
export function GateCard({ title, body, children }: { title: ReactNode; body?: ReactNode; children?: ReactNode }) {
  return (
    <div className="gatecard" role="status">
      <h3>{title}</h3>
      {body && <p>{body}</p>}
      {children}
    </div>
  );
}
