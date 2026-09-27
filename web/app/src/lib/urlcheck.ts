/**
 * Client-side website link check (mirrors agents/.../studio/urlcheck.py `normalise`): runs before the server check
 * so obvious mistakes never leave the browser. Reason codes map to the `url.<reason>` dictionary keys.
 */
export type UrlReason = "empty" | "spaces" | "bad_url" | "no_tld" | "ip" | "not_public" | "lookalike" | "dns" | "unreachable" | "http_error";
export type UrlCheck = { ok: true; url: string } | { ok: false; reason: UrlReason; suggestion?: string };

const LABEL = /^(?!-)[a-z0-9-]{1,63}(?<!-)$/;
const TLD = /^(?:[a-z]{2,63}|xn--[a-z0-9-]{2,59})$/;
const LOCAL = [".local", ".internal", ".localhost", ".localdomain", ".lan", ".home.arpa", ".test", ".invalid", ".example"];
const CONFUSABLE: Record<string, string> = {
  "а": "a", "е": "e", "о": "o", "р": "p", "с": "c", "у": "y", "х": "x", "і": "i", "ј": "j", "ѕ": "s", "һ": "h", "ԁ": "d",
  "ԛ": "q", "ԝ": "w", "ɡ": "g", "ⅼ": "l", "ӏ": "l", "ı": "i", "α": "a", "ο": "o", "ν": "v", "ρ": "p", "τ": "t", "κ": "k", "ι": "i", "υ": "u",
};

/** RFC 3492 punycode decode of one label body (without the "xn--" prefix). */
export function punyDecode(input: string): string {
  const base = 36, tMin = 1, tMax = 26, skew = 38, damp = 700;
  const out: number[] = [];
  let n = 128, i = 0, bias = 72;
  const d = input.lastIndexOf("-");
  for (let j = 0; j < Math.max(0, d); j++) out.push(input.charCodeAt(j));
  const adapt = (delta: number, num: number, first: boolean) => {
    delta = first ? Math.floor(delta / damp) : delta >> 1;
    delta += Math.floor(delta / num);
    let k = 0;
    while (delta > ((base - tMin) * tMax) >> 1) { delta = Math.floor(delta / (base - tMin)); k += base; }
    return k + Math.floor(((base - tMin + 1) * delta) / (delta + skew));
  };
  for (let p = d > 0 ? d + 1 : 0; p < input.length;) {
    const oldi = i;
    for (let w = 1, k = base; ; k += base) {
      if (p >= input.length) throw new Error("bad punycode");
      const c = input.charCodeAt(p++);
      const digit = c - 48 < 10 ? c - 22 : c - 65 < 26 ? c - 65 : c - 97 < 26 ? c - 97 : base;
      if (digit >= base) throw new Error("bad punycode");
      i += digit * w;
      const t = k <= bias ? tMin : k >= bias + tMax ? tMax : k - bias;
      if (digit < t) break;
      w *= base - t;
    }
    bias = adapt(i - oldi, out.length + 1, oldi === 0);
    n += Math.floor(i / (out.length + 1));
    i %= out.length + 1;
    out.splice(i++, 0, n);
  }
  return String.fromCodePoint(...out);
}

export function unicodeHost(host: string): string {
  return host.split(".").map((l) => { if (!l.startsWith("xn--")) return l; try { return punyDecode(l.slice(4)); } catch { return l; } }).join(".");
}

/** Best ASCII reading of a Unicode host: look-alike letters and accents folded, anything else dropped. */
export function asciiGuess(host: string): string {
  const folded = [...host.toLowerCase()].map((c) => CONFUSABLE[c] ?? c).join("").normalize("NFKD");
  return folded.replace(/[^a-z0-9.-]/g, "");
}

export function checkUrlClient(raw: string): UrlCheck {
  const s = raw.trim();
  if (!s) return { ok: false, reason: "empty" };
  if (/\s/.test(s)) return { ok: false, reason: "spaces" };
  const withScheme = /^[a-z][a-z0-9+.-]*:\/\//i.test(s) ? s : "https://" + s;
  let u: URL;
  try { u = new URL(withScheme); } catch { return { ok: false, reason: "bad_url" }; }
  if (u.protocol !== "https:" && u.protocol !== "http:") return { ok: false, reason: "bad_url" };
  if (u.username || u.password) return { ok: false, reason: "bad_url" };
  const host = u.hostname.toLowerCase().replace(/\.$/, "");
  if (/^\[.*\]$/.test(host) || /^\d{1,3}(\.\d{1,3}){3}$/.test(host)) return { ok: false, reason: "ip" };
  if (host === "localhost" || LOCAL.some((x) => host.endsWith(x))) return { ok: false, reason: "not_public" };
  const labels = host.split(".");
  if (labels.some((l) => l.startsWith("xn--"))) {
    const g = asciiGuess(unicodeHost(host));
    const good = g && g !== host && g.includes(".") && g.split(".").every((l) => LABEL.test(l));
    return { ok: false, reason: "lookalike", suggestion: good ? g : undefined };
  }
  if (labels.length < 2) return { ok: false, reason: "no_tld" };
  if (!labels.every((l) => LABEL.test(l))) return { ok: false, reason: "bad_url" };
  if (!TLD.test(labels[labels.length - 1])) return { ok: false, reason: "no_tld" };
  u.hash = "";
  u.search = "";
  return { ok: true, url: u.toString().replace(/\/$/, "") };
}
