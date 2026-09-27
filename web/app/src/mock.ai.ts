/* Mock of the admin "AI health" API (studio/ai_admin.py) for ?mock=1: GET /v1/admin/ai/health + pause / resume.
   In-memory; minute windows move a little on every refresh so the 15 s auto-refresh is visible. */
import type { AiHealth, AiModel, AiStatus, AiWindow } from "./pages/AiHealth";

const MIN = 6e4, HOUR = 36e5, DAY = 864e5;
const iso = (t: number) => new Date(t).toISOString();
const nextMinute = () => iso(Math.ceil(Date.now() / MIN) * MIN);
const nextDay = () => { const d = new Date(); d.setUTCHours(24, 0, 0, 0); return d.toISOString(); };
const nextMonth = () => { const d = new Date(); d.setUTCMonth(d.getUTCMonth() + 1, 1); d.setUTCHours(0, 0, 0, 0); return d.toISOString(); };

interface Seed { id: string; provider: string; model: string; label: string; kind: "llm" | "search"; minute?: [number, number]; day?: [number, number]; month?: [number, number]; budget?: [number, number]; calls: number; errors: number; p50: number | null; p90: number | null; spend: number; open?: boolean; lastErr?: string; valid?: number | null }
const SEEDS: Seed[] = [
  { id: "claude-bridge", provider: "claude_bridge", model: "claude", label: "Claude (host bridge)", kind: "llm", day: [251, 300], calls: 251, errors: 4, p50: 38.2, p90: 96.5, spend: 0, valid: 0.99, lastErr: "timeout after 120 s" },
  { id: "sambanova:DeepSeek-V3.1", provider: "sambanova", model: "DeepSeek-V3.1", label: "SambaNova DeepSeek-V3.1", kind: "llm", minute: [14, 60], day: [3480, 12000], calls: 3480, errors: 21, p50: 6.1, p90: 14.2, spend: 0, valid: 0.97 },
  { id: "sambanova:DeepSeek-V3.2", provider: "sambanova", model: "DeepSeek-V3.2", label: "SambaNova DeepSeek-V3.2", kind: "llm", minute: [9, 60], day: [11620, 12000], calls: 11620, errors: 55, p50: 7.4, p90: 18.9, spend: 0, valid: 0.96 },
  { id: "deepinfra:deepseek-ai/DeepSeek-V4-Flash", provider: "deepinfra", model: "deepseek-ai/DeepSeek-V4-Flash", label: "DeepInfra DeepSeek-V4-Flash", kind: "llm", budget: [1.62, 3], calls: 812, errors: 9, p50: 9.8, p90: 27.3, spend: 1.62, valid: 0.98 },
  { id: "deepinfra:Qwen/Qwen3-235B-A22B", provider: "deepinfra", model: "Qwen/Qwen3-235B-A22B", label: "DeepInfra Qwen3-235B", kind: "llm", budget: [0.64, 3], calls: 96, errors: 31, p50: 22.4, p90: 71.0, spend: 0.64, open: true, valid: 0.88, lastErr: "HTTP 503: model overloaded" },
  { id: "search:brave", provider: "brave", model: "brave", label: "Brave Search", kind: "search", minute: [3, 20], month: [1712, 2000], calls: 402, errors: 2, p50: 0.9, p90: 2.1, spend: 0, valid: null },
  { id: "search:claude", provider: "claude_search", model: "claude", label: "Claude web search", kind: "search", day: [37, 150], calls: 37, errors: 0, p50: 19.5, p90: 41.0, spend: 0, valid: null },
];
const LABEL: Record<string, string> = { claude_bridge: "Claude bridge", sambanova: "SambaNova", deepinfra: "DeepInfra", brave: "Brave", claude_search: "Claude search" };
const CONC: Record<string, number> = { claude_bridge: 2, sambanova: 6, deepinfra: 8, brave: 4, claude_search: 2 };
const paused = new Map<string, { by: string; until: string | null; reason: string }>();

function model(s: Seed): AiModel {
  const jitter = (x: number) => Math.max(0, Math.round(x + (Math.random() - 0.5) * 6));
  const windows: AiWindow[] = [];
  const add = (window: string, v: [number, number] | undefined, resets: string, j = false) => {
    if (!v) return;
    const used = j ? jitter(v[0]) : v[0];
    windows.push({ window, used, limit: v[1], pct: Math.round((used / v[1]) * 1000) / 10, resets_at: resets, source: s.id === "sambanova:DeepSeek-V3.2" && window === "day" ? "headers" : "ledger" });
  };
  add("minute", s.minute, nextMinute(), true);
  add("day", s.day, nextDay());
  add("month", s.month, nextMonth());
  add("budget_day", s.budget, nextDay());
  const usage = windows.reduce((a, w) => Math.max(a, w.pct ?? 0), 0);
  const p = paused.get(s.id);
  if (p && p.until && Date.parse(p.until) < Date.now()) paused.delete(s.id);
  const pz = paused.get(s.id);
  const hot = windows.filter((w) => (w.pct ?? 0) >= 80).sort((a, b) => (b.pct ?? 0) - (a.pct ?? 0))[0];
  const status: AiStatus = pz ? "paused" : s.open ? "open" : usage >= 95 ? "skipped" : usage >= 80 ? "demoted" : "healthy";
  const reason = pz ? (pz.reason || null) : s.open ? "5 failures in a row — skipped for a few minutes, then one test call"
    : hot ? `near its ${hot.window === "budget_day" ? "daily budget" : hot.window + " limit"} (${Math.round(hot.pct ?? 0)} %)` : null;
  return {
    id: s.id, provider: s.provider, model: s.model, label: s.label, kind: s.kind, status, status_reason: reason,
    paused: !!pz, paused_by: pz?.by ?? null, paused_until: pz?.until ?? null,
    circuit: s.open ? { state: "open", open_until: iso(Date.now() + 4 * MIN), consecutive_failures: 5 } : { state: "closed", open_until: null, consecutive_failures: 0 },
    windows, usage_pct: usage, calls_24h: s.calls, errors_24h: s.errors, error_rate: s.calls ? s.errors / s.calls : null,
    schema_valid_rate: s.valid ?? null, latency_p50_s: s.p50, latency_p90_s: s.p90,
    tokens_in_today: s.kind === "llm" ? s.calls * 5200 : null, tokens_out_today: s.kind === "llm" ? s.calls * 900 : null,
    spend_today_usd: s.spend, next_reset: hot?.resets_at ?? nextDay(), context_tokens: s.kind === "llm" ? (s.provider === "sambanova" ? 32768 : 131072) : null,
    profiles: s.kind === "llm" ? ["extract_json", "reason_score", "long_context"] : ["search"],
    last_error: s.lastErr ? { at: iso(Date.now() - 7 * MIN), error: s.lastErr } : s.errors ? { at: iso(Date.now() - 3 * HOUR), error: "HTTP 429: rate limit" } : null,
  };
}

export function aiHealth(): AiHealth {
  const models = SEEDS.map(model);
  const by = (p: string) => models.filter((m) => m.provider === p);
  const providers = [...new Set(SEEDS.map((s) => s.provider))].map((id) => ({
    id, label: LABEL[id] ?? id, concurrency: CONC[id] ?? null,
    spend_today_usd: Math.round(by(id).reduce((a, m) => a + (m.spend_today_usd ?? 0), 0) * 100) / 100,
    budget_today_usd: id === "deepinfra" ? 3 : null, models: by(id).map((m) => m.id),
  }));
  const ok = (ids: string[]) => ids.filter((id) => { const m = models.find((x) => x.id === id); return m && m.status !== "skipped" && m.status !== "open" && m.status !== "paused"; });
  const t0 = Date.now();
  return {
    generated_at: iso(t0), routing: "dynamic", thresholds: { demote_pct: 80, skip_pct: 95 }, providers, models,
    profiles: {
      extract_json: ok(["sambanova:DeepSeek-V3.1", "deepinfra:deepseek-ai/DeepSeek-V4-Flash", "claude-bridge", "sambanova:DeepSeek-V3.2"]),
      reason_score: ok(["claude-bridge", "sambanova:DeepSeek-V3.1", "deepinfra:deepseek-ai/DeepSeek-V4-Flash"]),
      long_context: ok(["claude-bridge", "deepinfra:deepseek-ai/DeepSeek-V4-Flash"]),
      search: ok(["search:brave", "search:claude"]),
    },
    recent_fallbacks: [
      { at: iso(t0 - 2 * MIN), profile: "reason_score", agent: "people_analyst", failed: "claude-bridge", next: "sambanova:DeepSeek-V3.1", outcome: "timeout", error: "timeout after 120 s" },
      { at: iso(t0 - 9 * MIN), profile: "extract_json", agent: "market_evidence", failed: "deepinfra:Qwen/Qwen3-235B-A22B", next: "sambanova:DeepSeek-V3.1", outcome: "error", error: "HTTP 503: model overloaded" },
      { at: iso(t0 - 26 * MIN), profile: "extract_json", agent: "site_intake", failed: "sambanova:DeepSeek-V3.2", next: "deepinfra:deepseek-ai/DeepSeek-V4-Flash", outcome: "skipped", error: "95 % of the daily limit used" },
      { at: iso(t0 - 41 * MIN), profile: "reason_score", agent: "valuation", failed: "sambanova:DeepSeek-V3.1", next: "claude-bridge", outcome: "cancelled", error: null },
      { at: iso(t0 - 2 * HOUR), profile: "search", agent: "people_analyst", failed: "search:claude", next: "search:brave", outcome: "rate_limited", error: "HTTP 429" },
      { at: iso(t0 - 5 * HOUR), profile: "extract_json", agent: "competitors", failed: "sambanova:DeepSeek-V3.1", next: "deepinfra:deepseek-ai/DeepSeek-V4-Flash", outcome: "schema_invalid", error: "output did not match CompetitorList" },
    ].filter((f) => Date.parse(f.at) > t0 - DAY),
  };
}

export function aiPause(id: string, by: string, body: { minutes?: number | null; reason?: string } | null): AiModel | null {
  const s = SEEDS.find((x) => x.id === id);
  if (!s) return null;
  paused.set(id, { by, until: body?.minutes ? iso(Date.now() + body.minutes * MIN) : null, reason: body?.reason ?? "" });
  return model(s);
}

export function aiResume(id: string): AiModel | null {
  const s = SEEDS.find((x) => x.id === id);
  if (!s) return null;
  paused.delete(id);
  return model(s);
}
