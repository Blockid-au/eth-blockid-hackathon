/** Largest-remainder allocation of whole shares (same as the prototype). */
export function allocate(total: number, pcts: number[]): number[] {
  const raw = pcts.map((p) => (total * p) / 100);
  const base = raw.map(Math.floor);
  let left = total - base.reduce((a, b) => a + b, 0);
  raw
    .map((r, i) => [r - base[i], i] as const)
    .sort((a, b) => b[0] - a[0])
    .forEach(([, i]) => {
      if (left > 0) {
        base[i]++;
        left--;
      }
    });
  return base;
}

export function niceTicks(mn: number, mx: number, n = 4): number[] {
  const step = Math.pow(10, Math.floor(Math.log10((mx - mn) / n || 1)));
  const s = [1, 2, 2.5, 5, 10].map((m) => m * step).find((m) => (mx - mn) / m <= n) || step * 10;
  const out: number[] = [];
  for (let v = Math.floor(mn / s) * s; v <= mx + 1e-9; v += s) out.push(+v.toFixed(6));
  if (out.length < 2) out.push(+(out[0] + s).toFixed(6));
  return out;
}

export const median = (a: number[]) => {
  if (!a.length) return 0;
  const s = a.slice().sort((x, y) => x - y), m = s.length >> 1;
  return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
};

/** Grade → (mu, sigma) per year, as in the prototype. */
export const GBM: Record<string, [number, number]> = { A: [0.15, 0.25], B: [0.1, 0.35], C: [0.05, 0.5], D: [0, 0.65], E: [-0.05, 0.8] };
export const GRADE_C: Record<string, string> = { A: "--c1", B: "--c3", C: "--c4", D: "--c2", E: "--c6" };
export const SERIES = ["--c1", "--c2", "--c3", "--c4", "--c5", "--c6"];

export interface FanPoint { d: number; p10: number; p25: number; p50: number; p75: number; p90: number }

/** Seeded GBM fan, identical algorithm to the prototype admin detail (240 paths, 26 steps). */
export function fan(seedStr: string, grade: string, m0: number, horizonDays: number, steps = 26, paths = 240): FanPoint[] {
  let s = [...seedStr].reduce((a, ch) => a * 31 + ch.charCodeAt(0), 7) >>> 0;
  const rnd = () => (s = (Math.imul(s, 1664525) + 1013904223) >>> 0) / 4294967296;
  const gauss = () => {
    let u = 0, v = 0;
    while (!u) u = rnd();
    while (!v) v = rnd();
    return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v);
  };
  const [mu, sg] = GBM[grade] ?? GBM.C;
  const dt = horizonDays / 365 / steps, P: number[][] = [];
  for (let p = 0; p < paths; p++) {
    let x = m0;
    const row = [x];
    for (let k = 0; k < steps; k++) {
      x *= Math.exp((mu - (sg * sg) / 2) * dt + sg * Math.sqrt(dt) * gauss());
      row.push(x);
    }
    P.push(row);
  }
  const q = (arr: number[], f: number) => {
    const a = arr.slice().sort((x, y) => x - y);
    return a[Math.floor(f * (a.length - 1))];
  };
  return Array.from({ length: steps + 1 }, (_, k) => {
    const col = P.map((r) => r[k]);
    return { d: (k * horizonDays) / steps, p10: q(col, 0.1), p25: q(col, 0.25), p50: q(col, 0.5), p75: q(col, 0.75), p90: q(col, 0.9) };
  });
}

export const DAY = 864e5;

/** Categorical colour by rank: first 5 get c1..c5, everything after folds into grey c6 ("Other"). Never cycles. */
export const colorAt = (i: number) => (i < 5 ? SERIES[i] : "--c6");
export function foldParts<T extends { name: string; v: number }>(parts: T[], otherLabel: string): { name: string; v: number; c: string; pct: number }[] {
  const tot = parts.reduce((a, p) => a + Math.max(p.v, 0), 0) || 1;
  const out = parts.slice(0, parts.length > 6 ? 5 : 6).map((p, i) => ({ name: p.name, v: p.v, c: i < 5 ? SERIES[i] : "--c6", pct: (p.v / tot) * 100 }));
  if (parts.length > 6) {
    const v = parts.slice(5).reduce((a, p) => a + Math.max(p.v, 0), 0);
    out.push({ name: `${otherLabel} (${parts.length - 5})`, v, c: "--c6", pct: (v / tot) * 100 });
  }
  return out;
}
