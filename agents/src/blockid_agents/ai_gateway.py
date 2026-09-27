"""AI gateway: resilient, quota-aware routing of every hosted LLM / search call (docs/PLAN-AI-GATEWAY.md §1).

Pieces (all process-local except the ledger, which is shared by the API and the worker through Postgres):

* **Usage ledger** (`Ledger`: `PgLedger` on studio.ai_usage / studio.ai_model_state / studio.ai_cache, `MemoryLedger`
  without a database): one row per attempt (model, profile, agent, user, outcome, latency, tokens, estimated cost,
  fallback target), the last provider rate-limit headers, admin pauses and circuit state per model.
* **Limits / quota windows** (`Gateway.windows`): SambaNova 60 rpm + 12,000 rpd per model, Claude bridge
  BRIDGE_COMPLETE_MAX_PER_DAY (/complete) and BRIDGE_MAX_PER_DAY (/search), Brave BRAVE_MONTHLY_QUOTA,
  DeepInfra DEEPINFRA_DAILY_BUDGET_USD (US$ estimated from tokens x config.MODEL_PRICES_USD_PER_MTOK), per-model
  overrides in AI_LIMITS. Usage = max(our ledger count, what x-ratelimit-* headers say). >= 80 % of any window:
  **demoted** (tried only after the healthy models); >= 95 %: **skipped** until the window resets.
* **Circuit breaker** per model: 3 consecutive failures, or >= 50 % errors over >= 6 calls in 5 min, or one
  429/402 -> open for 2, 4, 8, 10 min (exponential, capped); then half-open: one probe call decides.
* **Pacing**: a token bucket per rate-limited model (90 % of its rpm, bursts of rpm/6) spreads bursts from many users.
* **Concurrency**: SambaNova 6 per model, DeepInfra 8, Claude bridge 2 — with a fair per-user queue (`FairLimiter`:
  the user served least recently goes first), user id from `user_scope()` (set where jobs start).
* **Task profiles**: extract_json | reason_score | long_context (prompt > 30k tokens) | search. The candidates are the
  configured pool (env lists), filtered by AI_PROFILE_* and by context window (pre-check), ordered by
  quality x reliability / cost (benchmark priors in PRIORS, blended with the ledger's success rate, schema-valid rate
  and p90 latency, recomputed every AI_STATS_TTL_S = 1 h), or by env order with AI_ROUTING=static.
* **Per-call deadlines + hedging** (`Gateway.complete`): each backend call runs in a worker thread with a connect
  (10 s) and total deadline (Claude 120 s, SambaNova 60 s, DeepInfra 90 s); a hung call is cancelled (its connection
  closed) and the next model starts. Interactive routers also start the next healthy model once the primary has run
  past its p90 latency (8-45 s, 20 s without data): the first schema-valid answer wins, the other is cancelled.
* **Schema repair**: the adapters retry once on the same model with the validation error; then the next model.
* **Result cache**: identical (profile, schema, system, user) -> the stored answer for 24 h (AI_CACHE_TTL_HOURS).
* **Feed messages** (HR live progress, llm.emit): "Claude busy → using DeepSeek" (llm_fallback), and
  {"type": "llm_rerouted", "message": "SambaNova DeepSeek-V3.1 near its daily limit → using ..."} /
  {"type": "llm_hedged", "message": "... is slow → also asking ..."}.

Model ids: "sambanova:<model>", "deepinfra:<model>", "claude-bridge", "claude-cli", "search:brave", "search:claude".
"""
from __future__ import annotations

import concurrent.futures as cf
import contextlib
import contextvars
import hashlib
import itertools
import json
import logging
import math
import re
import threading
import time
from collections import deque
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from .config import (
    DEFAULT_CONTEXT_TOKENS,
    DEFAULT_PAID_PRICE_USD_PER_MTOK,
    MODEL_CONTEXT_TOKENS,
    MODEL_PRICES_USD_PER_MTOK,
    Settings,
    get_settings,
)

log = logging.getLogger(__name__)

PROFILES = ("extract_json", "reason_score", "long_context", "search")
LONG_CONTEXT_TOKENS = 30_000
OUTPUT_RESERVE_TOKENS = 4_000
CHARS_PER_TOKEN = 3.2  # conservative for mixed English / JSON / URLs

# Schema -> task profile. Anything unknown is extract_json; tier cloud_max is always reason_score; any prompt over
# LONG_CONTEXT_TOKENS is long_context.
SCHEMA_PROFILES: dict[str, str] = {
    "StartupProfile": "extract_json", "CompetitorList": "extract_json", "FundingClaims": "extract_json",
    "RelevanceVerdicts": "extract_json", "CompanyFinancials": "extract_json", "ValuationEvidence": "extract_json",
    "PersonAnalysis": "extract_json", "SuggestedPeople": "extract_json",
    "QualitativeScores": "reason_score", "Narrative": "reason_score", "MarketAnalysis": "reason_score",
    "TeamAnalysis": "reason_score", "ContractReview": "reason_score",
    # evaluation v5 analysts (docs/PLAN-EVALUATION-V5.md §2.2): cited claims only -> extract_json
    "TractionClaims": "extract_json", "MarketSizeClaims": "extract_json", "MoatClaims": "extract_json",
    "RetentionClaims": "extract_json", "DeckFacts": "extract_json",
    # valuation v5 agent (agents/valuation_agent.py, docs/PLAN-VALUATION-V5.md §5.3): picking one key from a fixed
    # list and copying deal quotes are extraction; rating 5 Berkus milestones and 12 risks from evidence is judgement
    "IndustryPick": "extract_json", "DealClaims": "extract_json", "StartupFactors": "reason_score",
}

# Benchmark priors per profile (docs/LLM-ROUTING.md "AI gateway benchmark"): quality 0..1 (agreement with the
# Claude reference / grounded answers), typical p90 latency in s. Keys: model id, or the model part after the
# provider (same weights on either provider unless listed). Refresh with scripts/ai-benchmark.py.
PRIORS: dict[str, dict[str, tuple[float, float]]] = {
    # (quality 0-1, p90 latency s) from scripts/ai-benchmark.py --run, 27 Sep 2026
    # (scripts/fixtures/ai-benchmark-results.json: schema-valid, grounded facts, fin extraction, score MAE vs Claude)
    "extract_json": {
        "claude-bridge": (0.95, 124), "claude-cli": (0.95, 124),
        "sambanova:DeepSeek-V3.2": (0.92, 18), "sambanova:DeepSeek-V3.1": (0.86, 25),
        "sambanova:gpt-oss-120b": (0.84, 9), "sambanova:Meta-Llama-3.3-70B-Instruct": (0.8, 11),
        "sambanova:gemma-4-31B-it": (0.78, 20),
        "deepinfra:deepseek-ai/DeepSeek-V4-Flash": (0.92, 28), "deepinfra:openai/gpt-oss-120b": (0.6, 62),
        "deepinfra:Qwen/Qwen3-235B-A22B-Instruct-2507": (0.84, 65),
    },
    "reason_score": {
        "claude-bridge": (0.97, 124), "claude-cli": (0.97, 124),
        "sambanova:DeepSeek-V3.2": (0.8, 18), "sambanova:DeepSeek-V3.1": (0.76, 25),
        "sambanova:gpt-oss-120b": (0.74, 9), "sambanova:Meta-Llama-3.3-70B-Instruct": (0.62, 11),
        "sambanova:gemma-4-31B-it": (0.55, 20),  # score MAE 23 vs Claude
        "deepinfra:deepseek-ai/DeepSeek-V4-Flash": (0.8, 28), "deepinfra:openai/gpt-oss-120b": (0.55, 62),
        "deepinfra:Qwen/Qwen3-235B-A22B-Instruct-2507": (0.78, 65),
    },
}
PRIORS["long_context"] = dict(PRIORS["extract_json"])
DEFAULT_PRIOR = (0.6, 30.0)
LATENCY_REF_S = 60.0  # latency term: reliability x 1 / (1 + p90 / LATENCY_REF_S)
COST_UNIT_USD = 0.002  # cost term: 1 + expected US$ per call / COST_UNIT_USD (+ scarcity)
SCARCITY = {"claude-bridge": 0.5, "claude-cli": 0.5}  # subscription capacity is small: use it where it matters
TYPICAL_OUTPUT_TOKENS = {"extract_json": 1500, "reason_score": 1500, "long_context": 2500}
SMOOTHING = 10.0  # Beta prior weight (calls) for success / schema-valid rates

PROVIDER_LABELS = {"sambanova": "SambaNova", "deepinfra": "DeepInfra", "claude_bridge": "Claude (bridge)",
                   "claude_cli": "Claude (CLI)", "brave": "Brave Search", "claude_search": "Claude web search"}
FAIL_OUTCOMES = ("error", "timeout", "schema_invalid", "rate_limited")

# ------------------------------------------------------------------ user context (fair queue)
_USER: contextvars.ContextVar[str] = contextvars.ContextVar("ai_user", default="")


def current_user() -> str:
    return _USER.get() or "system"


@contextlib.contextmanager
def user_scope(user: str | None) -> Iterator[None]:
    """Everything the job does inside this block is queued / accounted as `user` (the job runner sets it)."""
    tok = _USER.set((user or "").strip().lower()[:120])
    try:
        yield
    finally:
        _USER.reset(tok)


# ------------------------------------------------------------------ helpers
def utcnow_ts() -> float:
    return time.time()


def _iso(ts: float | None) -> str | None:
    return None if ts is None else datetime.fromtimestamp(ts, UTC).isoformat(timespec="seconds")


def day_start(ts: float) -> float:
    d = datetime.fromtimestamp(ts, UTC)
    return datetime(d.year, d.month, d.day, tzinfo=UTC).timestamp()


def month_start(ts: float) -> float:
    d = datetime.fromtimestamp(ts, UTC)
    return datetime(d.year, d.month, 1, tzinfo=UTC).timestamp()


def next_month(ts: float) -> float:
    d = datetime.fromtimestamp(ts, UTC)
    y, m = (d.year + 1, 1) if d.month == 12 else (d.year, d.month + 1)
    return datetime(y, m, 1, tzinfo=UTC).timestamp()


def estimate_tokens(*texts: str) -> int:
    return int(math.ceil(sum(len(t or "") for t in texts) / CHARS_PER_TOKEN))


def profile_for(schema_name: str, tier: str = "cloud", prompt_tokens: int = 0) -> str:
    if prompt_tokens > LONG_CONTEXT_TOKENS:
        return "long_context"
    if tier == "cloud_max":
        return "reason_score"
    return SCHEMA_PROFILES.get(schema_name, "extract_json")


def split_id(mid: str) -> tuple[str, str]:
    """model id -> (provider, model)."""
    if mid == "claude-bridge":
        return "claude_bridge", "sonnet"
    if mid == "claude-cli":
        return "claude_cli", "sonnet"
    if mid.startswith("search:"):
        name = mid.split(":", 1)[1]
        return ("brave" if name == "brave" else "claude_search"), name
    prov, _, model = mid.partition(":")
    return prov, model


def full_label(mid: str | None) -> str:
    """"sambanova:DeepSeek-V3.1" -> "SambaNova DeepSeek-V3.1", "claude-bridge" -> "Claude"."""
    if not mid:
        return "the model"
    if mid in ("claude-bridge", "claude-cli"):
        return "Claude"
    if mid == "search:brave":
        return "Brave Search"
    if mid == "search:claude":
        return "Claude web search"
    prov, model = split_id(mid)
    return f"{PROVIDER_LABELS.get(prov, prov)} {model.rsplit('/', 1)[-1]}".strip()


def context_tokens(mid: str) -> int | None:
    if mid.startswith("search:"):
        return None
    return MODEL_CONTEXT_TOKENS.get(mid, DEFAULT_CONTEXT_TOKENS)


def price(mid: str) -> tuple[float, float]:
    """US$ per 1M tokens (in, out); 0 for the free tier / subscription."""
    prov, _ = split_id(mid)
    if prov != "deepinfra":
        return (0.0, 0.0)
    return MODEL_PRICES_USD_PER_MTOK.get(mid, DEFAULT_PAID_PRICE_USD_PER_MTOK)


def estimate_cost(mid: str, tokens_in: int | None, tokens_out: int | None) -> float:
    pin, pout = price(mid)
    return ((tokens_in or 0) * pin + (tokens_out or 0) * pout) / 1e6


def prior(profile: str, mid: str) -> tuple[float, float]:
    table = PRIORS.get(profile, {})
    if mid in table:
        return table[mid]
    model = split_id(mid)[1]
    for k, v in table.items():  # same model on another provider
        if split_id(k)[1] == model:
            return v
    return DEFAULT_PRIOR


def classify(e: BaseException) -> str:
    from .llm import RateLimited, SchemaError

    if isinstance(e, SchemaError):
        return "schema_invalid"
    if isinstance(e, RateLimited):
        return "rate_limited"
    if isinstance(e, DeadlineExceeded):
        return "timeout"
    msg = str(e).lower()
    if "429" in msg or "402" in msg or "rate-limit" in msg or "rate limit" in msg or "cap reached" in msg:
        return "rate_limited"
    if "timeout" in msg or "timed out" in msg:
        return "timeout"
    return "error"


class DeadlineExceeded(RuntimeError):
    pass


# ------------------------------------------------------------------ rate-limit headers
_DUR = re.compile(r"(\d+(?:\.\d+)?)(ms|s|m|h|d)")


def _reset_seconds(v: str, now: float) -> float | None:
    """'30', '1.5s', '6m0s', '1h2m', epoch seconds / ms -> seconds from now."""
    v = (v or "").strip().lower()
    if not v:
        return None
    try:
        x = float(v)
    except ValueError:
        parts = _DUR.findall(v)
        if not parts:
            return None
        mult = {"ms": 0.001, "s": 1, "m": 60, "h": 3600, "d": 86400}
        return sum(float(n) * mult[u] for n, u in parts)
    if x > 1e12:  # epoch ms
        return max(0.0, x / 1000 - now)
    if x > 1e9:  # epoch s
        return max(0.0, x - now)
    return x


def parse_rate_headers(headers: dict | None, now: float) -> dict[str, dict]:
    """Provider rate-limit headers -> {window: {"limit", "remaining", "reset_at"}} for minute / day / month.

    OpenAI style (SambaNova, DeepInfra when sent): x-ratelimit-{limit,remaining,reset}-requests[-day|-minute];
    Brave: x-ratelimit-{limit,remaining,reset}: "<per second>, <per month>"."""
    out: dict[str, dict] = {}
    if not headers:
        return out
    h = {k.lower(): str(v) for k, v in headers.items()}
    brave = h.get("x-ratelimit-remaining", "")
    if "," in brave:
        rem = [x.strip() for x in brave.split(",")]
        lim = [x.strip() for x in h.get("x-ratelimit-limit", "").split(",")]
        rst = [x.strip() for x in h.get("x-ratelimit-reset", "").split(",")]
        if len(rem) > 1 and rem[1].isdigit():
            w = {"remaining": int(rem[1])}
            if len(lim) > 1 and lim[1].isdigit():
                w["limit"] = int(lim[1])
            if len(rst) > 1:
                s = _reset_seconds(rst[1], now)
                if s is not None:
                    w["reset_at"] = now + s
            out["month"] = w
        return out
    for suffix, window in (("-requests", "minute"), ("-requests-minute", "minute"), ("-requests-day", "day"),
                           ("-requests-month", "month")):
        rem = h.get(f"x-ratelimit-remaining{suffix}")
        if rem is None:
            continue
        try:
            w: dict[str, Any] = {"remaining": int(float(rem))}
        except ValueError:
            continue
        lim = h.get(f"x-ratelimit-limit{suffix}")
        if lim:
            with contextlib.suppress(ValueError):
                w["limit"] = int(float(lim))
        s = _reset_seconds(h.get(f"x-ratelimit-reset{suffix}", ""), now)
        if s is not None:
            w["reset_at"] = now + s
        out[window] = w
    return out


# ------------------------------------------------------------------ circuit breaker
class CircuitBreaker:
    """closed -> open (after `threshold` consecutive failures, an error rate >= `error_rate` over >= `min_calls` in
    `window_s`, or a hard failure such as a 429) for base_open_s x 2^(opens-1) capped at max_open_s -> half_open
    (one probe call allowed) -> closed on success / open again (longer) on failure."""

    def __init__(self, *, threshold: int = 3, window_s: float = 300, min_calls: int = 6, error_rate: float = 0.5,
                 base_open_s: float = 120, max_open_s: float = 600, clock: Callable[[], float] = time.time,
                 on_change: Callable[[CircuitBreaker], None] | None = None):
        self.threshold, self.window_s, self.min_calls, self.error_rate = threshold, window_s, min_calls, error_rate
        self.base_open_s, self.max_open_s, self.clock = base_open_s, max_open_s, clock
        self.on_change = on_change
        self.state = "closed"
        self.open_until: float | None = None
        self.opens = 0
        self.consecutive = 0
        self.probing = False
        self.events: deque[tuple[float, bool]] = deque(maxlen=200)
        self.lock = threading.Lock()

    def current(self) -> str:
        with self.lock:
            if self.state == "open" and self.open_until is not None and self.clock() >= self.open_until:
                return "half_open"
            return self.state

    def allow(self) -> bool:
        """May a call go out now? In half-open, only the first caller gets the probe."""
        with self.lock:
            if self.state == "open":
                if self.open_until is not None and self.clock() < self.open_until:
                    return False
                self.state, self.probing = "half_open", False
            if self.state == "half_open":
                if self.probing:
                    return False
                self.probing = True
            return True

    def release(self) -> None:
        """A probe that never produced a verdict (skipped / cancelled): let the next caller probe."""
        with self.lock:
            if self.state == "half_open":
                self.probing = False

    def success(self) -> None:
        changed = False
        with self.lock:
            self.events.append((self.clock(), True))
            self.consecutive = 0
            if self.state != "closed":
                self.state, self.open_until, self.opens, self.probing = "closed", None, 0, False
                changed = True
        if changed and self.on_change:
            self.on_change(self)

    def failure(self, hard: bool = False) -> None:
        with self.lock:
            now = self.clock()
            self.events.append((now, False))
            self.consecutive += 1
            recent = [ok for t, ok in self.events if t >= now - self.window_s]
            rate_bad = len(recent) >= self.min_calls and recent.count(False) / len(recent) >= self.error_rate
            trip = self.state == "half_open" or hard or self.consecutive >= self.threshold or rate_bad
            if trip:
                self.opens += 1
                self.state, self.probing = "open", False
                self.open_until = now + min(self.max_open_s, self.base_open_s * 2 ** (self.opens - 1))
        if trip and self.on_change:
            self.on_change(self)

    def restore(self, state: str, open_until: float | None, opens: int, consecutive: int) -> None:
        with self.lock:
            self.state = state if state in ("closed", "open") else "closed"
            self.open_until, self.opens, self.consecutive = open_until, int(opens or 0), int(consecutive or 0)

    def snapshot(self) -> dict:
        return {"state": self.current(), "open_until": _iso(self.open_until) if self.state == "open" else None,
                "consecutive_failures": self.consecutive}


# ------------------------------------------------------------------ pacing
class TokenBucket:
    """`rate` tokens per second, bursts up to `capacity`. acquire() reserves a token and sleeps until it is due;
    it refuses (False) when that would take longer than max_wait."""

    def __init__(self, rate: float, capacity: float, *, clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep):
        self.rate, self.capacity = rate, max(1.0, capacity)
        self.tokens = self.capacity
        self.clock, self.sleep = clock, sleep
        self.t = clock()
        self.lock = threading.Lock()

    def acquire(self, max_wait: float = 0.0) -> bool:
        with self.lock:
            now = self.clock()
            self.tokens = min(self.capacity, self.tokens + (now - self.t) * self.rate)
            self.t = now
            if self.tokens >= 1:
                self.tokens -= 1
                return True
            wait = (1 - self.tokens) / self.rate
            if wait > max_wait:
                return False
            self.tokens -= 1  # reserved: the next caller waits behind us
        self.sleep(wait)
        return True


# ------------------------------------------------------------------ fair per-user concurrency
class FairLimiter:
    """At most `capacity` calls at once. Waiting callers are served round-robin by user: the user whose last grant
    is the oldest (or who was never served) goes next, FIFO within a user — one heavy user cannot starve others."""

    def __init__(self, capacity: int):
        self.capacity = max(1, int(capacity))
        self.active = 0
        self.cond = threading.Condition()
        self.waiting: dict[str, deque[int]] = {}
        self.served: dict[str, int] = {}
        self._tickets = itertools.count()
        self._grants = itertools.count()

    def _next(self) -> tuple[str, int] | None:
        best = None
        for u, q in self.waiting.items():
            key = (self.served.get(u, -1), q[0])
            if best is None or key < best[0]:
                best = (key, u, q[0])
        return None if best is None else (best[1], best[2])

    def acquire(self, user: str, timeout: float) -> bool:
        with self.cond:
            t = next(self._tickets)
            self.waiting.setdefault(user, deque()).append(t)
            deadline = time.monotonic() + max(0.0, timeout)
            while True:
                if self.active < self.capacity and self._next() == (user, t):
                    self._drop(user, t)
                    self.active += 1
                    self.served[user] = next(self._grants)
                    self.cond.notify_all()
                    return True
                left = deadline - time.monotonic()
                if left <= 0:
                    self._drop(user, t)
                    self.cond.notify_all()
                    return False
                self.cond.wait(left)

    def _drop(self, user: str, t: int) -> None:
        q = self.waiting.get(user)
        if q is not None:
            with contextlib.suppress(ValueError):
                q.remove(t)
            if not q:
                del self.waiting[user]

    def release(self) -> None:
        with self.cond:
            self.active = max(0, self.active - 1)
            self.cond.notify_all()

    def snapshot(self) -> dict:
        with self.cond:
            return {"limit": self.capacity, "in_use": self.active,
                    "queued": sum(len(q) for q in self.waiting.values())}


# ------------------------------------------------------------------ ledger
@dataclass
class CallRecord:
    model_id: str
    outcome: str  # ok | error | timeout | schema_invalid | rate_limited | cancelled | skipped
    sent: bool = True  # a request reached the provider (counts toward rpm / rpd / month)
    schema_ok: bool | None = None
    latency_s: float | None = None
    tokens_in: int | None = None
    tokens_out: int | None = None
    cost_usd: float | None = None
    error: str | None = None
    profile: str | None = None
    agent: str | None = None
    user: str | None = None
    fallback_to: str | None = None
    hedged: bool = False
    at: float = 0.0

    @property
    def provider(self) -> str:
        return split_id(self.model_id)[0]


@dataclass
class Stats:
    n: int = 0
    ok: int = 0
    errors: int = 0
    schema_n: int = 0
    schema_ok: int = 0
    p50: float | None = None
    p90: float | None = None
    last_error: dict | None = None


def _pct(values: list[float], q: float) -> float | None:
    if not values:
        return None
    v = sorted(values)
    k = (len(v) - 1) * q
    lo, hi = int(math.floor(k)), int(math.ceil(k))
    return v[lo] + (v[hi] - v[lo]) * (k - lo)


class Ledger:
    """Interface. counts_all / stats_all return {model_id: ...}; times are epoch seconds (UTC)."""

    def record(self, rec: CallRecord) -> None: ...
    def counts_all(self, now: float) -> dict[str, dict]: ...
    def provider_spend_day(self, provider: str, now: float) -> float: ...
    def stats_all(self, since: float) -> dict[str, Stats]: ...
    def states_all(self) -> dict[str, dict]: ...
    def set_state(self, model_id: str, **fields) -> None: ...
    def recent_fallbacks(self, limit: int = 30) -> list[dict]: ...
    def cache_get(self, key: str, max_age_s: float, now: float) -> dict | None: ...
    def cache_put(self, key: str, profile: str, model_id: str, schema: str, value: Any, now: float) -> None: ...


def _counts(rows: list[CallRecord], now: float) -> dict:
    d0, m0 = day_start(now), month_start(now)
    sent = [r for r in rows if r.sent and r.at >= m0]
    today = [r for r in rows if r.at >= d0]
    return {"minute": sum(1 for r in sent if r.at > now - 60), "day": sum(1 for r in sent if r.at >= d0),
            "month": len(sent), "tokens_in_day": sum(r.tokens_in or 0 for r in today),
            "tokens_out_day": sum(r.tokens_out or 0 for r in today),
            "spend_day": sum(r.cost_usd or 0 for r in today)}


class MemoryLedger(Ledger):
    """In-process ledger (no database: tests, the CLI, local runs)."""

    def __init__(self):
        self.rows: list[CallRecord] = []
        self.state: dict[str, dict] = {}
        self.cache: dict[str, tuple[float, dict]] = {}
        self.lock = threading.Lock()

    def record(self, rec: CallRecord) -> None:
        with self.lock:
            self.rows.append(rec)
            if len(self.rows) > 50_000:
                del self.rows[:10_000]

    def counts_all(self, now: float) -> dict[str, dict]:
        with self.lock:
            by: dict[str, list[CallRecord]] = {}
            for r in self.rows:
                by.setdefault(r.model_id, []).append(r)
        return {m: _counts(rs, now) for m, rs in by.items()}

    def provider_spend_day(self, provider: str, now: float) -> float:
        d0 = day_start(now)
        with self.lock:
            return sum(r.cost_usd or 0 for r in self.rows if r.provider == provider and r.at >= d0)

    def stats_all(self, since: float) -> dict[str, Stats]:
        with self.lock:
            rows = [r for r in self.rows if r.at >= since]
        out: dict[str, Stats] = {}
        lat: dict[str, list[float]] = {}
        for r in rows:
            s = out.setdefault(r.model_id, Stats())
            if r.sent and r.outcome != "cancelled":
                s.n += 1
                s.ok += r.outcome == "ok"
                s.errors += r.outcome in FAIL_OUTCOMES
            if r.schema_ok is not None:
                s.schema_n += 1
                s.schema_ok += bool(r.schema_ok)
            if r.outcome == "ok" and r.latency_s is not None:
                lat.setdefault(r.model_id, []).append(r.latency_s)
            if r.outcome in FAIL_OUTCOMES:
                s.last_error = {"at": _iso(r.at), "error": (r.error or r.outcome)[:300]}
        for m, v in lat.items():
            out[m].p50, out[m].p90 = _pct(v, 0.5), _pct(v, 0.9)
        return out

    def states_all(self) -> dict[str, dict]:
        with self.lock:
            return {k: dict(v) for k, v in self.state.items()}

    def set_state(self, model_id: str, **fields) -> None:
        with self.lock:
            self.state.setdefault(model_id, {}).update(fields)

    def recent_fallbacks(self, limit: int = 30) -> list[dict]:
        with self.lock:
            rows = [r for r in self.rows if r.outcome in FAIL_OUTCOMES + ("skipped",) and
                    (r.fallback_to or r.outcome != "skipped")][-limit:]
        return [{"at": _iso(r.at), "profile": r.profile, "agent": r.agent, "failed": r.model_id,
                 "next": r.fallback_to, "outcome": r.outcome, "error": (r.error or "")[:300]} for r in reversed(rows)]

    def cache_get(self, key: str, max_age_s: float, now: float) -> dict | None:
        with self.lock:
            hit = self.cache.get(key)
        if hit and now - hit[0] <= max_age_s:
            return hit[1]
        return None

    def cache_put(self, key: str, profile: str, model_id: str, schema: str, value: Any, now: float) -> None:
        with self.lock:
            self.cache[key] = (now, {"model_id": model_id, "schema": schema, "value": value})
            if len(self.cache) > 2000:
                for k in sorted(self.cache, key=lambda k: self.cache[k][0])[:500]:
                    del self.cache[k]


class PgLedger(Ledger):
    """studio.ai_usage / ai_model_state / ai_cache (schema.sql), shared by the API and the worker. Reads are cached
    for a few seconds; every failure is logged and swallowed (the ledger never breaks a model call)."""

    COUNTS_TTL_S = 3.0
    STATES_TTL_S = 10.0

    def __init__(self, pool=None, url: str = ""):
        if pool is None:
            from psycopg.rows import dict_row
            from psycopg_pool import ConnectionPool

            pool = ConnectionPool(url, min_size=1, max_size=3, open=True,
                                  kwargs={"autocommit": True, "row_factory": dict_row, "prepare_threshold": None})
        self.pool = pool
        self._counts: tuple[float, dict] | None = None
        self._states: tuple[float, dict] | None = None
        self._writes = 0
        self.lock = threading.Lock()

    def _q(self, sql: str, args=(), fetch: bool = True):
        with self.pool.connection() as c:
            cur = c.execute(sql, args)
            return cur.fetchall() if fetch else None

    @staticmethod
    def _ts(ts: float) -> datetime:
        return datetime.fromtimestamp(ts, UTC)

    def record(self, rec: CallRecord) -> None:
        try:
            self._q("INSERT INTO studio.ai_usage(at,model_id,provider,profile,agent,user_id,outcome,sent,schema_ok,"
                    "latency_ms,tokens_in,tokens_out,cost_usd,error,fallback_to,hedged) VALUES "
                    "(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (self._ts(rec.at), rec.model_id, rec.provider, rec.profile, rec.agent, rec.user, rec.outcome,
                     rec.sent, rec.schema_ok, None if rec.latency_s is None else int(rec.latency_s * 1000),
                     rec.tokens_in, rec.tokens_out, rec.cost_usd, (rec.error or None) and rec.error[:500],
                     rec.fallback_to, rec.hedged), fetch=False)
        except Exception:
            log.exception("ai ledger write")
            return
        with self.lock:
            self._counts = None
            self._writes += 1
            prune = self._writes % 500 == 1
        if prune:
            self.prune(rec.at)

    def prune(self, now: float) -> None:
        try:
            self._q("DELETE FROM studio.ai_usage WHERE at < %s", (self._ts(now - 40 * 86400),), fetch=False)
            self._q("DELETE FROM studio.ai_cache WHERE at < %s", (self._ts(now - 2 * 86400),), fetch=False)
        except Exception:
            log.exception("ai ledger prune")

    def counts_all(self, now: float) -> dict[str, dict]:
        with self.lock:
            if self._counts and time.monotonic() - self._counts[0] < self.COUNTS_TTL_S:
                return self._counts[1]
        try:
            rows = self._q(
                "SELECT model_id, count(*) FILTER (WHERE sent AND at > %(m1)s) AS minute,"
                " count(*) FILTER (WHERE sent AND at >= %(d0)s) AS day, count(*) FILTER (WHERE sent) AS month,"
                " coalesce(sum(tokens_in) FILTER (WHERE at >= %(d0)s),0) AS tin,"
                " coalesce(sum(tokens_out) FILTER (WHERE at >= %(d0)s),0) AS tout,"
                " coalesce(sum(cost_usd) FILTER (WHERE at >= %(d0)s),0) AS spend"
                " FROM studio.ai_usage WHERE at >= %(m0)s GROUP BY model_id",
                {"m1": self._ts(now - 60), "d0": self._ts(day_start(now)), "m0": self._ts(month_start(now))})
        except Exception:
            log.exception("ai ledger counts")
            return self._counts[1] if self._counts else {}
        out = {r["model_id"]: {"minute": r["minute"], "day": r["day"], "month": r["month"],
                               "tokens_in_day": int(r["tin"]), "tokens_out_day": int(r["tout"]),
                               "spend_day": float(r["spend"])} for r in rows}
        with self.lock:
            self._counts = (time.monotonic(), out)
        return out

    def provider_spend_day(self, provider: str, now: float) -> float:
        return sum(c["spend_day"] for m, c in self.counts_all(now).items() if split_id(m)[0] == provider)

    def stats_all(self, since: float) -> dict[str, Stats]:
        try:
            rows = self._q(
                "SELECT model_id, count(*) FILTER (WHERE sent AND outcome <> 'cancelled') AS n,"
                " count(*) FILTER (WHERE sent AND outcome = 'ok') AS ok,"
                " count(*) FILTER (WHERE outcome IN ('error','timeout','schema_invalid','rate_limited')) AS errors,"
                " count(schema_ok) AS schema_n, count(*) FILTER (WHERE schema_ok) AS schema_ok,"
                " percentile_cont(0.5) WITHIN GROUP (ORDER BY latency_ms) FILTER (WHERE outcome='ok') AS p50,"
                " percentile_cont(0.9) WITHIN GROUP (ORDER BY latency_ms) FILTER (WHERE outcome='ok') AS p90"
                " FROM studio.ai_usage WHERE at >= %s GROUP BY model_id", (self._ts(since),))
            last = self._q(
                "SELECT DISTINCT ON (model_id) model_id, at, coalesce(error, outcome) AS error FROM studio.ai_usage"
                " WHERE at >= %s AND outcome IN ('error','timeout','schema_invalid','rate_limited')"
                " ORDER BY model_id, at DESC", (self._ts(since),))
        except Exception:
            log.exception("ai ledger stats")
            return {}
        errs = {r["model_id"]: {"at": r["at"].isoformat(timespec="seconds"), "error": (r["error"] or "")[:300]}
                for r in last}
        return {r["model_id"]: Stats(n=r["n"], ok=r["ok"], errors=r["errors"], schema_n=r["schema_n"],
                                     schema_ok=r["schema_ok"],
                                     p50=None if r["p50"] is None else float(r["p50"]) / 1000,
                                     p90=None if r["p90"] is None else float(r["p90"]) / 1000,
                                     last_error=errs.get(r["model_id"])) for r in rows}

    def states_all(self) -> dict[str, dict]:
        with self.lock:
            if self._states and time.monotonic() - self._states[0] < self.STATES_TTL_S:
                return self._states[1]
        try:
            rows = self._q("SELECT * FROM studio.ai_model_state")
        except Exception:
            log.exception("ai ledger states")
            return self._states[1] if self._states else {}
        out = {}
        for r in rows:
            d = dict(r)
            for k in ("paused_until", "open_until", "paused_at", "updated_at"):
                if d.get(k) is not None:
                    d[k] = d[k].timestamp()
            out[d.pop("model_id")] = d
        with self.lock:
            self._states = (time.monotonic(), out)
        return out

    def set_state(self, model_id: str, **fields) -> None:
        from psycopg.types.json import Jsonb

        cols = {k: v for k, v in fields.items() if k in (
            "paused", "paused_by", "paused_reason", "paused_at", "paused_until", "circuit", "open_until",
            "consecutive_failures", "opens", "rl")}
        for k in ("paused_at", "paused_until", "open_until"):
            if isinstance(cols.get(k), (int, float)):
                cols[k] = self._ts(cols[k])
        if "rl" in cols:
            cols["rl"] = Jsonb(cols["rl"])
        names = list(cols)
        sql = (f"INSERT INTO studio.ai_model_state(model_id,provider{''.join(',' + n for n in names)}) VALUES "
               f"(%s,%s{',%s' * len(names)}) ON CONFLICT (model_id) DO UPDATE SET updated_at=now()"
               + "".join(f", {n}=EXCLUDED.{n}" for n in names))
        try:
            self._q(sql, (model_id, split_id(model_id)[0], *[cols[n] for n in names]), fetch=False)
        except Exception:
            log.exception("ai ledger state")
        with self.lock:
            self._states = None

    def recent_fallbacks(self, limit: int = 30) -> list[dict]:
        try:
            rows = self._q(
                "SELECT at, profile, agent, model_id, fallback_to, outcome, error FROM studio.ai_usage"
                " WHERE outcome IN ('error','timeout','schema_invalid','rate_limited')"
                " OR (outcome = 'skipped' AND fallback_to IS NOT NULL) ORDER BY at DESC LIMIT %s", (limit,))
        except Exception:
            log.exception("ai ledger fallbacks")
            return []
        return [{"at": r["at"].isoformat(timespec="seconds"), "profile": r["profile"], "agent": r["agent"],
                 "failed": r["model_id"], "next": r["fallback_to"], "outcome": r["outcome"],
                 "error": (r["error"] or "")[:300]} for r in rows]

    def cache_get(self, key: str, max_age_s: float, now: float) -> dict | None:
        try:
            rows = self._q("SELECT model_id, schema, value FROM studio.ai_cache WHERE key=%s AND at >= %s",
                           (key, self._ts(now - max_age_s)))
        except Exception:
            log.exception("ai cache get")
            return None
        return dict(rows[0]) if rows else None

    def cache_put(self, key: str, profile: str, model_id: str, schema: str, value: Any, now: float) -> None:
        from psycopg.types.json import Jsonb

        try:
            self._q("INSERT INTO studio.ai_cache(key,profile,model_id,schema,value,at) VALUES (%s,%s,%s,%s,%s,%s)"
                    " ON CONFLICT (key) DO UPDATE SET model_id=EXCLUDED.model_id, value=EXCLUDED.value,"
                    " at=EXCLUDED.at", (key, profile, model_id, schema, Jsonb(value), self._ts(now)), fetch=False)
        except Exception:
            log.exception("ai cache put")


# ------------------------------------------------------------------ routing
@dataclass
class Plan:
    profile: str
    order: list[str]  # healthy (by score) then demoted (by score)
    status: dict[str, tuple[str, str | None]] = field(default_factory=dict)  # model -> (status, reason)
    preferred: str | None = None  # first by score ignoring health (what would run on a quiet day)


def configured_models(s: Settings) -> dict[str, dict]:
    """Every model / search provider the settings enable (with credentials), for the health screen and routing.
    id -> {"kind": "llm"|"search", "profiles": [...]}"""
    from .llm import AGENT_CHAINS

    out: dict[str, dict] = {}

    def add_chain(order, samba, deepinfra, auto_cli):
        order = list(order)
        if auto_cli and s.claude_cli_enabled and "claude" not in order:
            order.insert(0, "claude")
        for name in order:
            ids: list[str] = []
            if name == "claude" and s.claude_cli_enabled:
                ids = ["claude-cli"]
            elif name == "claude_bridge" and s.claude_search_url and s.claude_search_token:
                ids = ["claude-bridge"]
            elif name == "sambanova" and s.sambanova_api_key:
                ids = [f"sambanova:{m}" for m in samba]
            elif name == "deepinfra" and s.deepinfra_api_key:
                ids = [f"deepinfra:{m}" for m in deepinfra]
            for i in ids:
                out.setdefault(i, {"kind": "llm", "profiles": ["extract_json", "reason_score", "long_context"]})

    if s.llm_backend == "hosted":
        add_chain(s.llm_provider_order, s.sambanova_models, s.deepinfra_models, True)
        for spec in AGENT_CHAINS.values():
            kw = spec(s)
            add_chain(kw["order"], kw["sambanova_models"], kw["deepinfra_models"], kw.get("auto_cli", True))
    for name in dict.fromkeys((*s.search_providers, *s.hr_search_providers)):
        if name == "brave" and s.brave_api_key:
            out["search:brave"] = {"kind": "search", "profiles": ["search"]}
        elif name == "claude" and s.claude_search_url and s.claude_search_token:
            out["search:claude"] = {"kind": "search", "profiles": ["search"]}
    return out


_EXECUTOR = cf.ThreadPoolExecutor(max_workers=64, thread_name_prefix="ai-gw")


@dataclass
class _Attempt:
    mid: str
    ctx: Any
    t0: float
    deadline: float
    limiter: FairLimiter
    hedge: bool = False


class Gateway:
    """Process-wide router state (breakers, buckets, limiters) over a shared Ledger. See the module docstring."""

    def __init__(self, settings: Settings | None = None, ledger: Ledger | None = None, *,
                 clock: Callable[[], float] = time.time, mono: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep, executor: cf.Executor | None = None):
        self.s = settings or get_settings()
        self.ledger = ledger or MemoryLedger()
        self.clock, self.mono, self.sleep = clock, mono, sleep
        self.executor = executor or _EXECUTOR
        self.breakers: dict[str, CircuitBreaker] = {}
        self.buckets: dict[str, TokenBucket | None] = {}
        self.limiters: dict[str, FairLimiter] = {}
        self.models: dict[str, dict] = configured_models(self.s)
        self._stats: tuple[float, dict[str, Stats]] | None = None
        self._notified: dict[tuple, float] = {}
        self.lock = threading.Lock()
        self._restored = False

    # -------------------------------------------------------------- per-model state
    def register(self, mid: str, kind: str = "llm") -> None:
        with self.lock:
            self.models.setdefault(mid, {"kind": kind, "profiles": ["search"] if kind == "search" else
                                         ["extract_json", "reason_score", "long_context"]})

    def known_model(self, mid: str) -> bool:
        return mid in self.models or mid in self.ledger.states_all() or mid in self.ledger.counts_all(self.clock())

    def breaker(self, mid: str) -> CircuitBreaker:
        with self.lock:
            b = self.breakers.get(mid)
            if b is None:
                b = self.breakers[mid] = CircuitBreaker(clock=self.clock, on_change=lambda br, m=mid: self._persist(m, br))
                st = self.ledger.states_all().get(mid) or {}
                if st.get("circuit") == "open" and (st.get("open_until") or 0) > self.clock():
                    b.restore("open", st.get("open_until"), st.get("opens") or 1, st.get("consecutive_failures") or 0)
            return b

    def _persist(self, mid: str, b: CircuitBreaker) -> None:
        self.ledger.set_state(mid, circuit=b.state, open_until=b.open_until, opens=b.opens,
                              consecutive_failures=b.consecutive)

    def limits(self, mid: str) -> dict[str, float]:
        """window -> limit: minute / day / month (requests), budget_day (US$, provider-wide)."""
        s = self.s
        prov, _ = split_id(mid)
        out: dict[str, float] = {}
        if prov == "sambanova":
            out = {"minute": s.sambanova_rpm, "day": s.sambanova_rpd}
        elif mid == "claude-bridge":
            out = {"day": s.bridge_complete_max_per_day}
        elif mid == "search:claude":
            out = {"day": s.bridge_search_max_per_day}
        elif mid == "search:brave":
            out = {"month": s.brave_monthly_quota}
        elif prov == "deepinfra":
            out = {"budget_day": s.deepinfra_daily_budget_usd}
        over = s.ai_limits.get(mid, {})
        for k, v in over.items():
            key = {"rpm": "minute", "rpd": "day", "rpmonth": "month", "budget": "budget_day"}.get(k, k)
            out[key] = v
        return {k: v for k, v in out.items() if v and v > 0}

    def bucket(self, mid: str) -> TokenBucket | None:
        with self.lock:
            if mid not in self.buckets:
                rpm = self.limits(mid).get("minute")
                self.buckets[mid] = (TokenBucket(0.9 * rpm / 60.0, max(1.0, rpm / 6.0), clock=self.mono,
                                                 sleep=self.sleep) if rpm else None)
            return self.buckets[mid]

    def limiter(self, mid: str) -> FairLimiter:
        prov, _ = split_id(mid)
        key, cap = {"sambanova": (mid, self.s.ai_concurrency_sambanova),
                    "deepinfra": ("deepinfra", self.s.ai_concurrency_deepinfra),
                    "claude_bridge": ("claude_bridge", self.s.ai_concurrency_claude_bridge),
                    "claude_cli": ("claude_cli", 1), "brave": ("brave", 2),
                    "claude_search": ("claude_search", 1)}.get(prov, (prov, 4))
        with self.lock:
            if key not in self.limiters:
                self.limiters[key] = FairLimiter(cap)
            return self.limiters[key]

    def deadline(self, mid: str) -> float:
        prov, _ = split_id(mid)
        return {"sambanova": self.s.sambanova_timeout, "deepinfra": self.s.ai_deadline_deepinfra_s,
                "claude_bridge": self.s.ai_deadline_claude_s, "claude_cli": self.s.ai_deadline_claude_s}.get(prov, 60.0)

    # -------------------------------------------------------------- quota windows / status
    def windows(self, mid: str, counts: dict | None = None, state: dict | None = None) -> list[dict]:
        now = self.clock()
        counts = (self.ledger.counts_all(now).get(mid) or {}) if counts is None else counts
        state = (self.ledger.states_all().get(mid) or {}) if state is None else state
        rl = state.get("rl") or {}
        resets = {"minute": now - now % 60 + 60, "day": day_start(now) + 86400, "month": next_month(now),
                  "budget_day": day_start(now) + 86400}
        out = []
        for w, limit in self.limits(mid).items():
            if w == "budget_day":
                used: float = round(self.ledger.provider_spend_day(split_id(mid)[0], now), 4)
            else:
                used = int(counts.get(w, 0))
            src, reset_at = "ledger", resets[w]
            h = rl.get(w) or {}
            if h and (h.get("reset_at") or now + 1) > now:
                hl = h.get("limit") or limit
                hused = max(0, hl - h.get("remaining", hl))
                if hl and hused / hl > used / limit:
                    used, limit, src = hused, hl, "headers"
                    reset_at = h.get("reset_at") or reset_at
            out.append({"window": w, "used": used, "limit": limit,
                        "pct": round(100.0 * used / limit, 1) if limit else 0.0,
                        "resets_at": _iso(reset_at), "source": src, "_reset": reset_at})
        return out

    def status(self, mid: str, counts: dict | None = None, state: dict | None = None,
               windows: list[dict] | None = None) -> tuple[str, str | None]:
        state = (self.ledger.states_all().get(mid) or {}) if state is None else state
        now = self.clock()
        if state.get("paused") and (not state.get("paused_until") or state["paused_until"] > now):
            return "paused", "paused by an admin" + (f": {state['paused_reason']}" if state.get("paused_reason")
                                                    else "")
        if self.breaker(mid).current() == "open" or (  # here, or opened by another process (worker / API)
                state.get("circuit") == "open" and (state.get("open_until") or 0) > now):
            return "open", "not responding (circuit open)"
        wins = self.windows(mid, counts, state) if windows is None else windows
        worst = max(wins, key=lambda w: w["pct"], default=None)
        if worst is None:
            return "healthy", None
        what = {"minute": "per-minute limit", "day": "daily limit", "month": "monthly limit",
                "budget_day": "daily budget"}[worst["window"]]
        if worst["pct"] >= self.s.ai_skip_pct:
            return "skipped", f"at its {what} ({worst['pct']:.0f} %)"
        if worst["pct"] >= self.s.ai_demote_pct:
            return "demoted", f"near its {what} ({worst['pct']:.0f} %)"
        return "healthy", None

    # -------------------------------------------------------------- ordering
    def stats(self, fresh: bool = False) -> dict[str, Stats]:
        now = self.clock()
        with self.lock:
            cached = self._stats
        if not fresh and cached and now - cached[0] < self.s.ai_stats_ttl_s:
            return cached[1]
        st = self.ledger.stats_all(now - 3 * 86400)
        with self.lock:
            self._stats = (now, st)
        return st

    def score(self, mid: str, profile: str, prompt_tokens: int = 0, st: Stats | None = None) -> float:
        q0, lat0 = prior(profile, mid)
        st = st or Stats()
        schema = (st.schema_ok + SMOOTHING * 0.97) / (st.schema_n + SMOOTHING)
        ok = (st.ok + SMOOTHING * 0.95) / (st.n + SMOOTHING)
        p90 = st.p90 if (st.p90 is not None and st.n >= 5) else lat0
        quality = q0 * schema
        reliability = ok / (1 + p90 / LATENCY_REF_S)
        tin = prompt_tokens or 6000
        cost = 1 + estimate_cost(mid, tin, TYPICAL_OUTPUT_TOKENS.get(profile, 1500)) / COST_UNIT_USD \
            + SCARCITY.get(mid, 0.0)
        return quality * reliability / cost

    def plan(self, profile: str, names: list[str], prompt_tokens: int = 0, *, pins: tuple[str, ...] = (),
             static: bool | None = None) -> Plan:
        static = (self.s.ai_routing == "static") if static is None else static
        self.poll_bridge()
        allowed = {"extract_json": self.s.ai_profile_extract_json, "reason_score": self.s.ai_profile_reason_score,
                   "long_context": self.s.ai_profile_long_context}.get(profile) or ()
        cands = [n for n in names if not allowed or n in allowed] or list(names)
        now = self.clock()
        counts, states = self.ledger.counts_all(now), self.ledger.states_all()
        st = self.stats()
        pos = {n: i for i, n in enumerate(names)}
        if static:
            ranked = list(cands)
        else:
            sc = {n: self.score(n, profile, prompt_tokens, st.get(n)) * (1 + 0.02 * (len(names) - pos[n]) / len(names))
                  for n in cands}
            ranked = sorted(cands, key=lambda n: (-sc[n], pos[n]))
        pinned = [p for p in pins if p in ranked]
        ranked = pinned + [n for n in ranked if n not in pinned]
        plan = Plan(profile, [], preferred=ranked[0] if ranked else None)
        healthy, demoted = [], []
        need = prompt_tokens + OUTPUT_RESERVE_TOKENS
        for n in ranked:
            ctx = context_tokens(n)
            if prompt_tokens and ctx is not None and need > ctx:
                plan.status[n] = ("skipped", f"prompt too long for its {ctx // 1024}k context window")
                continue
            status, why = self.status(n, counts.get(n) or {}, states.get(n) or {})
            plan.status[n] = (status, why)
            if status == "healthy":
                healthy.append(n)
            elif status == "demoted":
                demoted.append(n)
        plan.order = healthy + demoted
        return plan

    # -------------------------------------------------------------- bridge counters
    _bridge_polled = 0.0

    def poll_bridge(self, wait: bool = False) -> None:
        """Refresh the Claude bridge's own daily counters (GET /healthz) as rate-limit state of claude-bridge and
        search:claude, at most once a minute, in a background thread (routing never waits for it)."""
        s = self.s
        if not (s.ai_bridge_poll and s.claude_search_url and s.claude_search_token):
            return
        now = self.mono()
        with self.lock:
            if now - self._bridge_polled < 60:
                return
            self._bridge_polled = now

        def run():
            import httpx

            try:
                r = httpx.get(s.claude_search_url.rstrip("/") + "/healthz", timeout=2, trust_env=False)
                d = r.json() if r.status_code == 200 else {}
            except Exception:  # noqa: BLE001 - the bridge being down shows up in the calls themselves
                return
            reset = day_start(self.clock()) + 86400
            if isinstance(d.get("complete_today"), int) and d.get("complete_max_per_day"):
                lim = int(d["complete_max_per_day"])
                self.ledger.set_state("claude-bridge", rl={"day": {"limit": lim, "reset_at": reset,
                                                                   "remaining": max(0, lim - d["complete_today"])}})
            if isinstance(d.get("today"), int) and d.get("max_per_day"):
                lim = int(d["max_per_day"])
                self.ledger.set_state("search:claude", rl={"day": {"limit": lim, "reset_at": reset,
                                                                   "remaining": max(0, lim - d["today"])}})

        if wait:
            run()
        else:
            threading.Thread(target=run, name="ai-gw-bridge-poll", daemon=True).start()

    # -------------------------------------------------------------- recording
    def record(self, rec: CallRecord) -> None:
        rec.at = rec.at or self.clock()
        if rec.cost_usd is None and (rec.tokens_in or rec.tokens_out):
            rec.cost_usd = round(estimate_cost(rec.model_id, rec.tokens_in, rec.tokens_out), 6)
        self.ledger.record(rec)

    def observe_headers(self, mid: str, headers: dict | None) -> None:
        rl = parse_rate_headers(headers, self.clock())
        if rl:
            self.ledger.set_state(mid, rl=rl)

    # -------------------------------------------------------------- feed messages
    def _notify(self, key: tuple, event: dict) -> None:
        """emit() once per (listener, key) per 10 min, so a run's feed says it once, not for every call."""
        from .llm import _LISTENER, emit

        fn = _LISTENER.get()
        if fn is None:
            return
        k = (id(fn),) + key
        now = self.mono()
        with self.lock:
            if now - self._notified.get(k, -1e9) < 600:
                return
            self._notified[k] = now
            if len(self._notified) > 2000:
                self._notified.clear()
        emit(event)

    def _reroute_events(self, plan: Plan) -> None:
        pref = plan.preferred
        if not pref or not plan.order or plan.order[0] == pref:
            return
        status, why = plan.status.get(pref, ("healthy", None))
        if status == "healthy":
            return
        nxt = plan.order[0]
        self._notify(("reroute", pref, status, nxt), {
            "type": "llm_rerouted", "skipped": pref, "next": nxt, "reason": status,
            "message": f"{full_label(pref)} {(why or status).split(' (')[0]} → using {full_label(nxt)}"})

    # -------------------------------------------------------------- the call
    def cache_key(self, profile: str, schema_name: str, schema_json: str, system: str, user: str) -> str:
        h = hashlib.sha256()
        for part in (profile, schema_name, schema_json, system, user):
            h.update(part.encode())
            h.update(b"\x00")
        return h.hexdigest()

    def hedge_delay(self, mid: str) -> float:
        st = self.stats().get(mid)
        base = st.p90 if (st and st.p90 is not None and st.n >= 5) else self.s.ai_hedge_delay_s
        return max(self.s.ai_hedge_min_s, min(self.s.ai_hedge_max_s, base))

    def complete(self, router, tier: str, system: str, user: str, schema, profile: str | None = None):
        """Route one call (see the module docstring). `profile` overrides the schema mapping (a prompt over
        LONG_CONTEXT_TOKENS is always long_context)."""
        from .llm import CallContext, LLMError, emit, note_provider

        schema_json = json.dumps(schema.model_json_schema(), sort_keys=True, ensure_ascii=False)
        tokens = estimate_tokens(system, user, schema_json)
        if profile in PROFILES and profile != "search" and tokens <= LONG_CONTEXT_TOKENS:
            pass
        else:
            profile = profile_for(schema.__name__, tier, tokens)
        names = [n for n, _ in router.backends]
        for n in names:
            self.register(n)
        backends = dict(router.backends)
        agent, uid = getattr(router, "agent", "default"), current_user()
        ttl = self.s.ai_cache_ttl_hours * 3600
        key = self.cache_key(profile, schema.__name__, schema_json, system, user) if ttl > 0 else None
        if key:
            hit = self.ledger.cache_get(key, ttl, self.clock())
            if hit and hit.get("model_id") in backends:
                try:
                    out = schema.model_validate(hit["value"])
                except Exception:  # noqa: BLE001 - schema changed since: ask again
                    out = None
                if out is not None:
                    name = hit["model_id"]
                    router.used.append((name, schema.__name__))
                    note_provider(name)
                    emit({"type": "llm_answered", "provider": name, "cached": True})
                    return out

        plan = self.plan(profile, names, tokens, pins=getattr(router, "pins", {}).get(profile, ()))
        self._reroute_events(plan)
        queue = list(plan.order)
        if not queue:
            why = "; ".join(f"{n}: {st[1] or st[0]}" for n, st in plan.status.items())
            raise LLMError(f"no model available for {profile} ({schema.__name__}): {why or 'none configured'}")
        errors: list[str] = []
        inflight: dict[cf.Future, _Attempt] = {}
        base = dict(profile=profile, agent=agent, user=uid)

        def skip(mid: str, why: str) -> None:
            self.record(CallRecord(mid, "skipped", sent=False, error=why, fallback_to=queue[0] if queue else None,
                                   **base))
            errors.append(f"{mid}: {why}")

        def start(hedge: bool = False) -> bool:
            while queue:
                mid = queue.pop(0)
                br = self.breaker(mid)
                if not br.allow():
                    skip(mid, "circuit open")
                    continue
                bucket = self.bucket(mid)
                if bucket is not None and not bucket.acquire(0.0 if hedge else self.s.ai_pacing_wait_s):
                    br.release()
                    if hedge:
                        queue.insert(0, mid)
                        return False
                    skip(mid, "paced: per-minute budget in use")
                    continue
                lim = self.limiter(mid)
                if not lim.acquire(uid, 0.0 if hedge else self.s.ai_queue_wait_s):
                    br.release()
                    if hedge:
                        queue.insert(0, mid)
                        return False
                    skip(mid, "concurrency queue full")
                    continue
                ctx = CallContext(self.s.ai_connect_timeout_s, self.deadline(mid))
                fut = self.executor.submit(contextvars.copy_context().run, _run_backend, backends[mid], ctx, tier,
                                           system, user, schema)
                t0 = self.mono()
                inflight[fut] = _Attempt(mid, ctx, t0, t0 + self.deadline(mid), lim, hedge)
                return True
            return False

        def fail(a: _Attempt, e: BaseException, outcome: str | None = None) -> None:
            outcome = outcome or classify(e)
            msg = f"{type(e).__name__}: {e}"[:300]
            self.breaker(a.mid).failure(hard=outcome == "rate_limited")
            nxt = next((x.mid for x in inflight.values()), None) or (queue[0] if queue else None)
            self.record(CallRecord(a.mid, outcome, schema_ok=False if outcome == "schema_invalid" else None,
                                   latency_s=self.mono() - a.t0, error=msg, fallback_to=nxt, hedged=a.hedge,
                                   **_meta(a.ctx), **base))
            self.observe_headers(a.mid, a.ctx.meta.get("headers"))
            errors.append(f"{a.mid}: {msg}")
            log.warning("LLM %s failed for %s (%s): %s", a.mid, schema.__name__, outcome, msg)
            emit({"type": "llm_fallback", "failed": a.mid, "next": nxt, "error": msg[:200]})

        winner: tuple[str, Any] | None = None
        hedged = False
        start()
        while inflight and winner is None:
            now = self.mono()
            wake = min(a.deadline for a in inflight.values())
            hedge_at = None
            if (router.interactive and self.s.ai_hedge and not hedged and queue and len(inflight) == 1):
                a0 = next(iter(inflight.values()))
                hedge_at = a0.t0 + self.hedge_delay(a0.mid)
                wake = min(wake, hedge_at)
            done, _ = cf.wait(list(inflight), timeout=max(0.0, wake - now), return_when=cf.FIRST_COMPLETED)
            for fut in done:
                a = inflight.pop(fut)
                a.limiter.release()
                try:
                    out = fut.result()
                except Exception as e:  # noqa: BLE001 - provider down / quota / invalid output -> next model
                    fail(a, e)
                    continue
                self.breaker(a.mid).success()
                self.record(CallRecord(a.mid, "ok", schema_ok=True, latency_s=self.mono() - a.t0, hedged=a.hedge,
                                       **_meta(a.ctx), **base))
                self.observe_headers(a.mid, a.ctx.meta.get("headers"))
                winner = (a.mid, out)
                break
            if winner is not None:
                break
            now = self.mono()
            for fut, a in list(inflight.items()):
                if now >= a.deadline:
                    inflight.pop(fut)
                    a.ctx.cancel()
                    a.limiter.release()
                    fail(a, DeadlineExceeded(f"no answer after {self.deadline(a.mid):.0f} s"), "timeout")
            if not inflight:
                start()
            elif hedge_at is not None and self.mono() >= hedge_at and not hedged:
                hedged = True
                slow = next(iter(inflight.values())).mid
                if start(hedge=True):
                    also = [x.mid for x in inflight.values() if x.hedge][-1]
                    self._notify(("hedge", slow, also), {
                        "type": "llm_hedged", "slow": slow, "also": also,
                        "message": f"{full_label(slow)} is slow → also asking {full_label(also)}"})
        # cancel the loser(s) of a hedge race
        for fut, a in inflight.items():
            a.ctx.cancel()
            fut.cancel()
            a.limiter.release()
            self.breaker(a.mid).release()
            self.record(CallRecord(a.mid, "cancelled", latency_s=self.mono() - a.t0, hedged=a.hedge,
                                   error="lost the hedge race", **base))
        inflight.clear()
        if winner is None:
            raise LLMError(f"all LLM backends failed for {schema.__name__}: " + " | ".join(errors))
        mid, out = winner
        router.used.append((mid, schema.__name__))
        log.info("LLM %s answered %s (%s)", mid, schema.__name__, profile)
        note_provider(mid)
        emit({"type": "llm_answered", "provider": mid})
        if key:
            try:
                self.ledger.cache_put(key, profile, mid, schema.__name__, out.model_dump(mode="json"), self.clock())
            except Exception:
                log.exception("ai cache put")
        return out

    # -------------------------------------------------------------- search providers
    def search_order(self, names: list[str]) -> tuple[list[str], dict[str, tuple[str, str | None]]]:
        """Search provider names (brave, claude) -> (order: healthy then demoted, status by name). Emits a reroute
        message when the first configured provider is demoted / skipped."""
        self.poll_bridge()
        status: dict[str, tuple[str, str | None]] = {}
        healthy, demoted = [], []
        now = self.clock()
        counts, states = self.ledger.counts_all(now), self.ledger.states_all()
        for n in names:
            mid = f"search:{n}"
            self.register(mid, "search")
            st = self.status(mid, counts.get(mid) or {}, states.get(mid) or {})
            status[n] = st
            (healthy if st[0] == "healthy" else demoted if st[0] == "demoted" else []).append(n)
        order = healthy + demoted
        if names and order and order[0] != names[0] and status[names[0]][0] != "healthy":
            first, why = names[0], status[names[0]][1] or status[names[0]][0]
            self._notify(("search", first, status[first][0]), {
                "type": "llm_rerouted", "skipped": f"search:{first}", "next": f"search:{order[0]}",
                "reason": status[first][0],
                "message": f"{full_label('search:' + first)} {why.split(' (')[0]} → using "
                           f"{full_label('search:' + order[0])}"})
        return order, status

    def record_search(self, name: str, *, ok: bool, latency_s: float, cached: bool, error: str | None = None,
                      headers: dict | None = None, next_name: str | None = None) -> None:
        mid = f"search:{name}"
        if not cached:
            br = self.breaker(mid)
            br.success() if ok else br.failure(hard="429" in (error or "") or "quota" in (error or "").lower())
        self.record(CallRecord(mid, "ok" if ok else classify(RuntimeError(error or "")), sent=not cached,
                               latency_s=latency_s, error=error, profile="search", user=current_user(),
                               fallback_to=None if ok else (f"search:{next_name}" if next_name else None)))
        self.observe_headers(mid, headers)

    # -------------------------------------------------------------- admin
    def pause(self, mid: str, *, by: str, reason: str = "", minutes: int | None = None) -> None:
        now = self.clock()
        self.ledger.set_state(mid, paused=True, paused_by=by, paused_reason=reason or None, paused_at=now,
                              paused_until=(now + minutes * 60) if minutes else None)

    def resume(self, mid: str, *, by: str) -> None:
        self.ledger.set_state(mid, paused=False, paused_by=by, paused_reason=None, paused_until=None)
        br = self.breaker(mid)
        br.restore("closed", None, 0, 0)
        self._persist(mid, br)

    def model_health(self, mid: str, *, counts=None, states=None, stats=None) -> dict:
        now = self.clock()
        counts = self.ledger.counts_all(now) if counts is None else counts
        states = self.ledger.states_all() if states is None else states
        stats = self.stats(fresh=True) if stats is None else stats
        c, stt, st = counts.get(mid) or {}, states.get(mid) or {}, stats.get(mid) or Stats()
        wins = self.windows(mid, c, stt)
        status, why = self.status(mid, c, stt, wins)
        br = self.breaker(mid)
        circuit = br.snapshot()
        if stt.get("circuit") == "open" and (stt.get("open_until") or 0) > now and circuit["state"] == "closed":
            circuit = {"state": "open", "open_until": _iso(stt["open_until"]),  # opened in another process
                       "consecutive_failures": stt.get("consecutive_failures") or 0}
            if status not in ("paused",):
                status, why = "open", "not responding (circuit open)"
        hot = [w for w in wins if w["pct"] >= self.s.ai_demote_pct]
        day = next((w for w in wins if w["window"] == "day"), None)
        nr = min((w["_reset"] for w in hot), default=None) or (day["_reset"] if day else None)
        prov, model = split_id(mid)
        info = self.models.get(mid) or {"kind": "search" if mid.startswith("search:") else "llm", "profiles": []}
        paused = bool(stt.get("paused")) and (not stt.get("paused_until") or stt["paused_until"] > now)
        return {
            "id": mid, "provider": prov, "model": model, "label": full_label(mid), "kind": info["kind"],
            "status": status, "status_reason": why, "paused": paused,
            "paused_by": stt.get("paused_by") if paused else None,
            "paused_until": _iso(stt.get("paused_until")) if paused else None,
            "circuit": circuit,
            "windows": [{k: v for k, v in w.items() if not k.startswith("_")} for w in wins],
            "usage_pct": max((w["pct"] for w in wins), default=0.0),
            "calls_24h": st.n, "errors_24h": st.errors,
            "error_rate": round(st.errors / st.n, 3) if st.n else 0.0,
            "schema_valid_rate": round(st.schema_ok / st.schema_n, 3) if st.schema_n else None,
            "latency_p50_s": None if st.p50 is None else round(st.p50, 1),
            "latency_p90_s": None if st.p90 is None else round(st.p90, 1),
            "tokens_in_today": int(c.get("tokens_in_day") or 0), "tokens_out_today": int(c.get("tokens_out_day") or 0),
            "spend_today_usd": round(float(c.get("spend_day") or 0), 4),
            "next_reset": _iso(nr), "context_tokens": context_tokens(mid), "profiles": info["profiles"],
            "last_error": st.last_error,
        }

    def health(self) -> dict:
        self.poll_bridge(wait=True)
        now = self.clock()
        counts, states = self.ledger.counts_all(now), self.ledger.states_all()
        stats = self.ledger.stats_all(now - 86400)
        ids = list(dict.fromkeys([*self.models, *states, *counts]))  # configured + seen in the shared ledger
        models = [self.model_health(m, counts=counts, states=states, stats=stats) for m in ids]
        providers: dict[str, dict] = {}
        for m in models:
            p = providers.setdefault(m["provider"], {
                "id": m["provider"], "label": PROVIDER_LABELS.get(m["provider"], m["provider"]),
                "concurrency": self.limiter(m["id"]).capacity,
                "spend_today_usd": 0.0,
                "budget_today_usd": self.s.deepinfra_daily_budget_usd if m["provider"] == "deepinfra" else None,
                "models": []})
            p["models"].append(m["id"])
            p["spend_today_usd"] = round(p["spend_today_usd"] + m["spend_today_usd"], 4)
        llm_ids = [m["id"] for m in models if m["kind"] == "llm"]
        profiles = {pr: self.plan(pr, llm_ids).order for pr in ("extract_json", "reason_score", "long_context")}
        profiles["search"] = [f"search:{n}" for n in self.search_order(
            [m["model"] for m in models if m["kind"] == "search"])[0]]
        return {"generated_at": _iso(now), "routing": "static" if self.s.ai_routing == "static" else "dynamic",
                "thresholds": {"demote_pct": self.s.ai_demote_pct, "skip_pct": self.s.ai_skip_pct},
                "providers": list(providers.values()), "models": models, "profiles": profiles,
                "recent_fallbacks": self.ledger.recent_fallbacks(30)}


def _meta(ctx) -> dict:
    m = ctx.meta
    return {"tokens_in": m.get("tokens_in"), "tokens_out": m.get("tokens_out"), "cost_usd": m.get("cost_usd")}


def _run_backend(backend, ctx, tier, system, user, schema):
    """Runs in a gateway worker thread (inside a copy of the caller's context)."""
    from .llm import _CALL, _USAGE

    _USAGE.set(None)  # the router records the winner in the caller's context, not every attempt
    _CALL.set(ctx)
    return backend.complete_json(tier, system, user, schema)


# ------------------------------------------------------------------ process singleton
_GATEWAYS: dict[str, Gateway] = {}
_GW_LOCK = threading.Lock()


def get_gateway(settings: Settings | None = None, db=None) -> Gateway:
    """One Gateway per process and database: PgLedger on DATABASE_URL (or the given Studio's pool) so the API and
    the worker share the usage ledger; MemoryLedger without a database."""
    s = settings or get_settings()
    key = s.database_url if s.database_url.startswith("postgres") else ("db" if db is not None else "")
    with _GW_LOCK:
        gw = _GATEWAYS.get(key)
        if gw is None:
            ledger: Ledger
            if db is not None:
                ledger = PgLedger(pool=db.pool)
            elif s.database_url.startswith("postgres"):
                try:
                    ledger = PgLedger(url=s.database_url)
                except Exception:
                    log.exception("ai ledger: Postgres unavailable, using an in-process ledger")
                    ledger = MemoryLedger()
            else:
                ledger = MemoryLedger()
            gw = _GATEWAYS[key] = Gateway(s, ledger)
        else:
            gw.s = s
            if db is not None and not (isinstance(gw.ledger, PgLedger) and gw.ledger.pool is db.pool):
                gw.ledger = PgLedger(pool=db.pool)
            gw.models.update({k: v for k, v in configured_models(s).items() if k not in gw.models})
        return gw


def reset_gateways() -> None:
    """Tests: forget every process gateway (and its breakers / cache)."""
    with _GW_LOCK:
        _GATEWAYS.clear()
