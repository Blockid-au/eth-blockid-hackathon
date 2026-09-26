import { useI18n } from "../i18n";
import type { DictKey } from "../dict";

export const GATES = [3, 6];

/** 8-step stepper from the prototype. `reach` = highest step the user may open; `onPick` makes steps clickable. */
export function Stepper({ cur, done, reach, onPick }: { cur: number; done: number; reach?: number; onPick?: (i: number) => void }) {
  const { t } = useI18n();
  return (
    <nav className="stepnav" aria-label={t("walk.eyebrow")}>
      {Array.from({ length: 8 }, (_, k) => k + 1).map((i) => {
        const cls = [i <= done && i !== cur ? "done" : "", GATES.includes(i) ? "gate" : ""].filter(Boolean).join(" ");
        const can = !!onPick && i <= (reach ?? done) && i !== cur;
        return (
          <button key={i} type="button" className={cls} aria-current={i === cur ? "step" : undefined} disabled={!can && i !== cur} onClick={() => can && onPick?.(i)}
            title={GATES.includes(i) ? t("gate.admin") : undefined}>
            <b>{String(i).padStart(2, "0")}</b>
            <span>{t(("step." + i) as DictKey)}</span>
          </button>
        );
      })}
    </nav>
  );
}
