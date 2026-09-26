export const shortAddr = (a?: string | null) => (a ? a.slice(0, 6) + "…" + a.slice(-4) : "");
