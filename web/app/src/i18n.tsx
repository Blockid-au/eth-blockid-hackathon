import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { en, vi, type DictKey } from "./dict";

export type Lang = "en" | "vi";
const STORE = "blockid-lang";

function initialLang(): Lang {
  try {
    return localStorage.getItem(STORE) === "vi" ? "vi" : "en";
  } catch {
    return "en";
  }
}

export interface I18n {
  lang: Lang;
  setLang: (l: Lang) => void;
  t: (k: DictKey, vars?: Record<string, string | number>) => string;
  locale: string;
  /** Plain number with fixed decimals. */
  fmt: (n: number, d?: number) => string;
  /** A$ with compact suffix (A$3.36M, A$250k). */
  money: (aud: number) => string;
  /** A$ with fixed decimals, no compaction. */
  aud: (n: number, d?: number) => string;
  pct: (p: number, d?: number) => string;
  /** ▲ +1.23% / ▼ −1.23% / — 0.00% as in the prototype. */
  chg: (p: number) => string;
  date: (d: string | number | Date, withTime?: boolean) => string;
  ago: (d: string | number | Date) => string;
}

const Ctx = createContext<I18n | null>(null);

export function arrow(p: number): "up" | "down" | "flat" {
  return p > 0.005 ? "up" : p < -0.005 ? "down" : "flat";
}

export function I18nProvider({ children }: { children: ReactNode }) {
  const [lang, setLangState] = useState<Lang>(initialLang);
  useEffect(() => {
    document.documentElement.lang = lang;
  }, [lang]);
  const setLang = useCallback((l: Lang) => {
    setLangState(l);
    try {
      localStorage.setItem(STORE, l);
    } catch {
      /* private mode */
    }
  }, []);

  const value = useMemo<I18n>(() => {
    const dict = lang === "vi" ? vi : en;
    const locale = lang === "vi" ? "vi-VN" : "en-AU";
    const nfCache = new Map<number, Intl.NumberFormat>();
    const fmt = (n: number, d = 0) => {
      let f = nfCache.get(d);
      if (!f) {
        f = new Intl.NumberFormat(locale, { minimumFractionDigits: d, maximumFractionDigits: d });
        nfCache.set(d, f);
      }
      return f.format(Number.isFinite(n) ? n : 0);
    };
    const t: I18n["t"] = (k, vars) => {
      let s: string = (dict as Record<string, string>)[k] ?? (en as Record<string, string>)[k] ?? k;
      if (vars) for (const [vk, vv] of Object.entries(vars)) s = s.split("{" + vk + "}").join(String(vv));
      return s;
    };
    const money = (v: number) => {
      const a = Math.abs(v);
      const sign = v < 0 ? "−" : "";
      if (a >= 1e9) return `${sign}A$${fmt(a / 1e9, 2)}B`;
      if (a >= 1e6) return `${sign}A$${fmt(a / 1e6, a >= 1e7 ? 1 : 2)}M`;
      if (a >= 1e4) return `${sign}A$${fmt(a / 1e3, 0)}k`;
      return `${sign}A$${fmt(a, a >= 100 ? 0 : 2)}`;
    };
    const aud = (n: number, d = 2) => "A$" + fmt(n, d);
    const pct = (p: number, d = 1) => fmt(p, d) + "%";
    const chg = (p: number) => {
      const k = arrow(p);
      return (k === "up" ? "▲ +" : k === "down" ? "▼ −" : "— ") + fmt(Math.abs(p), 2) + "%";
    };
    const dfDay = new Intl.DateTimeFormat(locale, { day: "numeric", month: "short", year: "numeric" });
    const dfTime = new Intl.DateTimeFormat(locale, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
    const date = (d: string | number | Date, withTime = false) => {
      const x = new Date(d);
      if (isNaN(+x)) return "–";
      return (withTime ? dfTime : dfDay).format(x);
    };
    const rtf = new Intl.RelativeTimeFormat(locale, { numeric: "auto" });
    const ago = (d: string | number | Date) => {
      const s = (Date.now() - +new Date(d)) / 1000;
      if (!Number.isFinite(s)) return "–";
      if (s < 60) return rtf.format(-Math.max(0, Math.round(s)), "second");
      if (s < 3600) return rtf.format(-Math.round(s / 60), "minute");
      if (s < 86400) return rtf.format(-Math.round(s / 3600), "hour");
      if (s < 86400 * 45) return rtf.format(-Math.round(s / 86400), "day");
      return dfDay.format(new Date(d));
    };
    return { lang, setLang, t, locale, fmt, money, aud, pct, chg, date, ago };
  }, [lang, setLang]);

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useI18n(): I18n {
  const v = useContext(Ctx);
  if (!v) throw new Error("I18nProvider missing");
  return v;
}

export type { DictKey };
