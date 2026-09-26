/* Canonical report JSON, byte-identical to Python agents/src/blockid_agents/studio/report_hash.py:
 *   json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
 * JSON.parse would lose the int/float distinction (Python prints 300000.0, JS prints 300000), so this uses a
 * lossless parser that keeps number lexemes and re-prints them the way Python's repr(float) / str(int) does. */
import { keccak256, toBytes } from "viem";

export class JNum {
  constructor(public raw: string) {}
}
export type JVal = null | boolean | string | JNum | JVal[] | { [k: string]: JVal };

export const REPORT_KEYS = ["url", "profile", "competitors", "market", "svi", "self_reported"] as const;

export function parseLossless(text: string): JVal {
  let i = 0;
  const n = text.length;
  const ws = () => { while (i < n && " \t\n\r".includes(text[i])) i++; };
  const fail = (m: string): never => { throw new SyntaxError(`${m} at position ${i}`); };
  const value = (depth: number): JVal => {
    if (depth > 200) fail("nested too deeply");
    ws();
    const c = text[i];
    if (c === "{") {
      i++;
      const o: { [k: string]: JVal } = Object.create(null);
      ws();
      if (text[i] === "}") { i++; return o; }
      for (;;) {
        ws();
        if (text[i] !== '"') fail("expected string key");
        const k = str();
        ws();
        if (text[i] !== ":") fail("expected ':'");
        i++;
        o[k] = value(depth + 1);
        ws();
        if (text[i] === ",") { i++; continue; }
        if (text[i] === "}") { i++; return o; }
        fail("expected ',' or '}'");
      }
    }
    if (c === "[") {
      i++;
      const a: JVal[] = [];
      ws();
      if (text[i] === "]") { i++; return a; }
      for (;;) {
        a.push(value(depth + 1));
        ws();
        if (text[i] === ",") { i++; continue; }
        if (text[i] === "]") { i++; return a; }
        fail("expected ',' or ']'");
      }
    }
    if (c === '"') return str();
    if (text.startsWith("true", i)) { i += 4; return true; }
    if (text.startsWith("false", i)) { i += 5; return false; }
    if (text.startsWith("null", i)) { i += 4; return null; }
    const m = /^-?(0|[1-9]\d*)(\.\d+)?([eE][+-]?\d+)?/.exec(text.slice(i, i + 400));
    if (!m) fail("unexpected token");
    i += m![0].length;
    return new JNum(m![0]);
  };
  const str = (): string => {
    const s = i;
    i++;
    while (i < n && text[i] !== '"') i += text[i] === "\\" ? 2 : 1;
    if (i >= n) fail("unterminated string");
    i++;
    return JSON.parse(text.slice(s, i)) as string;
  };
  const v = value(0);
  ws();
  if (i !== n) fail("trailing data");
  return v;
}

/** Python repr(float(lexeme)) / str(int(lexeme)). */
export function pyNumber(raw: string): string {
  if (!/[.eE]/.test(raw)) return BigInt(raw).toString();
  const x = Number(raw);
  if (!Number.isFinite(x)) throw new RangeError("non-finite number " + raw);
  if (x === 0) return Object.is(x, -0) ? "-0.0" : "0.0";
  const neg = x < 0;
  const [mant, e] = Math.abs(x).toExponential().split("e");
  const digits = mant.replace(".", "");
  const exp = Number(e);
  let out: string;
  if (exp < -4 || exp >= 16) {
    out = digits[0] + (digits.length > 1 ? "." + digits.slice(1) : "") + "e" + (exp < 0 ? "-" : "+") + String(Math.abs(exp)).padStart(2, "0");
  } else if (exp >= 0) {
    const int = digits.slice(0, exp + 1).padEnd(exp + 1, "0");
    out = int + "." + (digits.slice(exp + 1) || "0");
  } else {
    out = "0." + "0".repeat(-exp - 1) + digits;
  }
  return (neg ? "-" : "") + out;
}

/** Python sorts str keys by code point (JS default sort is by UTF-16 unit). */
function cmpCodePoints(a: string, b: string): number {
  const A = Array.from(a), B = Array.from(b);
  for (let k = 0; k < Math.min(A.length, B.length); k++) {
    const d = A[k].codePointAt(0)! - B[k].codePointAt(0)!;
    if (d) return d;
  }
  return A.length - B.length;
}

export function canonicalJson(v: JVal): string {
  if (v === null) return "null";
  if (v === true) return "true";
  if (v === false) return "false";
  if (typeof v === "string") return JSON.stringify(v);
  if (v instanceof JNum) return pyNumber(v.raw);
  if (Array.isArray(v)) return "[" + v.map(canonicalJson).join(",") + "]";
  const keys = Object.keys(v).sort(cmpCodePoints);
  return "{" + keys.map((k) => JSON.stringify(k) + ":" + canonicalJson(v[k])).join(",") + "}";
}

export function canonicalReport(v: JVal): JVal {
  if (!v || typeof v !== "object" || Array.isArray(v) || v instanceof JNum) throw new TypeError("report must be a JSON object");
  const o: { [k: string]: JVal } = Object.create(null);
  for (const k of REPORT_KEYS) o[k] = k in v ? v[k] : null;
  return o;
}

export function reportHash(v: JVal): `0x${string}` {
  return keccak256(toBytes(canonicalJson(canonicalReport(v))));
}

/** Pretty printer that keeps number lexemes (for the editor). */
export function pretty(v: JVal, ind = ""): string {
  if (v instanceof JNum) return v.raw;
  if (v === null || typeof v !== "object") return JSON.stringify(v);
  const nx = ind + "  ";
  if (Array.isArray(v)) return v.length ? "[\n" + v.map((x) => nx + pretty(x, nx)).join(",\n") + "\n" + ind + "]" : "[]";
  const ks = Object.keys(v);
  return ks.length ? "{\n" + ks.map((k) => nx + JSON.stringify(k) + ": " + pretty(v[k], nx)).join(",\n") + "\n" + ind + "}" : "{}";
}

/** Plain JS value (numbers as Number) for display / arithmetic. */
export function plain(v: JVal): unknown {
  if (v instanceof JNum) return Number(v.raw);
  if (v === null || typeof v !== "object") return v;
  if (Array.isArray(v)) return v.map(plain);
  const o: Record<string, unknown> = {};
  for (const k of Object.keys(v)) o[k] = plain(v[k]);
  return o;
}
