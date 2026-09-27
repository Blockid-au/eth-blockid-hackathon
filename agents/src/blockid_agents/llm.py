"""LLM access layer.

Every model call goes through the LiteLLM gateway on the AI VM, addressed by *tier* rather than
vendor model name, so models can be swapped in one config line (deploy/vm-ai/litellm-config.yaml):

    local      -> Qwen3.8-27B on vLLM (private data, bulk work, runs in batch mode)
    cloud      -> Claude Sonnet 5 (hard reasoning, contract review) — never receives PII
    cloud_max  -> Claude Opus 5.5 (final security review, escalations only)

With LLM_BACKEND=hosted (see `build_llm`) the cloud tiers bypass the gateway and run on a fallback
chain: the Claude CLI (headless `claude -p --json-schema`, when CLAUDE_CLI_ENABLED), then the providers
in LLM_PROVIDER_ORDER (default "sambanova,deepinfra"; "claude_bridge" adds the host bridge's Claude; providers
without a key are skipped). A backend
that fails, times out, is rate-limited or returns invalid output falls through to the next one. `local` always stays on the gateway,
so PII-handling agents never reach a hosted provider.

With LLM_BACKEND=hosted the chains are wrapped in `RoutedLLM` (ai_gateway.py, docs/PLAN-AI-GATEWAY.md §1): the env
lists above define the candidate pool; each call is routed by task profile (extract_json / reason_score /
long_context) with per-call deadlines, hedging, a circuit breaker per model, quota-aware demote/skip from the shared
usage ledger (studio.ai_usage), pacing, fair per-user concurrency caps and a 24 h result cache.

Outputs are always validated against a Pydantic schema; free-text answers are not accepted
anywhere a value flows into the valuation, the cap table or a transaction.
"""
from __future__ import annotations

import contextvars
import glob
import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
from typing import Callable, ClassVar, Literal, Protocol, TypeVar

from pydantic import BaseModel, ValidationError

from .config import Settings, get_settings

log = logging.getLogger(__name__)

Tier = Literal["local", "cloud", "cloud_max"]
T = TypeVar("T", bound=BaseModel)


class LLMError(RuntimeError):
    pass


class SchemaError(LLMError):
    """The model answered, but never with JSON matching the schema (after the repair retry)."""


class RateLimited(LLMError):
    """The provider refused for quota / rate reasons (429, 402, daily cap)."""


# ------------------------------------------------------------------ per-call context (ai_gateway)
class CallContext:
    """Set by the gateway around one backend call (in the worker thread that runs it). Adapters read the connect /
    total deadline from it, report usage (tokens, cost, rate-limit headers) into `meta`, and register closers so a
    call that lost a hedge race or passed its deadline is cancelled (its HTTP connection is closed)."""

    def __init__(self, connect_s: float = 10.0, deadline_s: float = 60.0):
        self.connect_s, self.deadline_s = connect_s, deadline_s
        self.meta: dict = {}
        self.cancelled = threading.Event()
        self._closers: list[Callable[[], None]] = []
        self._lock = threading.Lock()

    def on_cancel(self, fn: Callable[[], None]) -> None:
        with self._lock:
            if not self.cancelled.is_set():
                self._closers.append(fn)
                return
        _quiet(fn)

    def cancel(self) -> None:
        with self._lock:
            self.cancelled.set()
            closers, self._closers = self._closers, []
        for fn in closers:
            _quiet(fn)


def _quiet(fn: Callable[[], None]) -> None:
    try:
        fn()
    except Exception:  # noqa: BLE001 - closing a connection that is already gone
        log.debug("cancel hook failed", exc_info=True)


_CALL: contextvars.ContextVar[CallContext | None] = contextvars.ContextVar("llm_call", default=None)


def current_call() -> CallContext | None:
    return _CALL.get()


def _http_timeout(ctx: CallContext):
    import httpx

    return httpx.Timeout(ctx.deadline_s, connect=ctx.connect_s)


def _note_usage(resp, headers=None) -> None:
    """Tokens / cost / rate-limit headers of one OpenAI-compatible response -> the current call's meta."""
    ctx = _CALL.get()
    if ctx is None:
        return
    u = getattr(resp, "usage", None)
    if u is not None:
        ctx.meta["tokens_in"] = getattr(u, "prompt_tokens", None)
        ctx.meta["tokens_out"] = getattr(u, "completion_tokens", None)
        cost = getattr(u, "estimated_cost", None)  # DeepInfra reports it
        if cost is None and isinstance(getattr(u, "model_extra", None), dict):
            cost = u.model_extra.get("estimated_cost")
        if cost is not None:
            ctx.meta["cost_usd"] = float(cost)
    if headers is not None:
        ctx.meta["headers"] = {k.lower(): v for k, v in dict(headers).items() if "ratelimit" in k.lower()}


# ------------------------------------------------------------------ which provider answered
# The graph sets a fresh list per step (see graph.build_site_valuation) and reads it back afterwards, so each
# valuation reports the providers that answered it (`llm_providers_used`), even in a long-lived worker.
_USAGE: contextvars.ContextVar[list[str] | None] = contextvars.ContextVar("llm_usage", default=None)
_LAST: contextvars.ContextVar[str] = contextvars.ContextVar("llm_last", default="")


def note_provider(name: str) -> None:
    _LAST.set(name)
    usage = _USAGE.get()
    if usage is not None:
        usage.append(name)


def last_provider() -> str:
    return _LAST.get()


def track_providers() -> tuple[list[str], contextvars.Token]:
    usage: list[str] = []
    return usage, _USAGE.set(usage)


def untrack_providers(token: contextvars.Token) -> None:
    _USAGE.reset(token)


# ------------------------------------------------------------------ progress listener (HR live feed)
# A job may set a listener for its thread / context (studio/hr_store.HrProgress): FallbackLLM and the search chain
# (tools/search.SearchChain) report which provider answered and every fallback, so the feed can say
# "Claude busy → using DeepSeek". Events: {"type": "llm_answered", "provider"} | {"type": "llm_fallback", "failed",
# "next", "error"} | {"type": "search_fallback", "failed", "next", "error"}. A listener must never raise.
_LISTENER: contextvars.ContextVar[Callable[[dict], None] | None] = contextvars.ContextVar("llm_listener",
                                                                                          default=None)


def set_listener(fn: Callable[[dict], None] | None) -> contextvars.Token:
    return _LISTENER.set(fn)


def reset_listener(token: contextvars.Token) -> None:
    _LISTENER.reset(token)


def emit(event: dict) -> None:
    fn = _LISTENER.get()
    if fn is None:
        return
    try:
        fn(event)
    except Exception:  # noqa: BLE001 - progress never breaks a model call
        log.exception("llm listener")


_LABELS = {"claude": "Claude", "claude-cli": "Claude", "claude-bridge": "Claude", "deepseek": "DeepSeek",
           "sambanova": "SambaNova", "deepinfra": "DeepInfra", "gateway": "the model gateway", "qwen": "Qwen",
           "llama": "Llama", "gpt": "GPT", "kimi": "Kimi", "glm": "GLM", "fake": "the test model"}


def provider_label(name: str | None) -> str:
    """Plain name for a provider id: "claude-cli" -> "Claude", "sambanova:DeepSeek-V3.1" -> "DeepSeek"."""
    n = (name or "").strip()
    if not n:
        return "the model"
    low = n.lower()
    model = low.split(":", 1)[1] if ":" in low else ""
    for key in ("deepseek", "qwen", "llama", "gpt", "kimi", "glm", "claude"):
        if key in model:
            return _LABELS[key]
    head = low.split(":", 1)[0]
    return _LABELS.get(head, _LABELS.get(head.split("-")[0], n))


def primary_provider(client, tier: str = "cloud") -> str | None:
    """Name of the backend that is tried first for `tier` (None when unknown)."""
    for _ in range(4):
        if isinstance(client, TierRouter):
            client = client.routes.get(tier)
        elif isinstance(client, RoutedLLM):
            return client.first()
        elif isinstance(client, FallbackLLM):
            return client.backends[0][0] if client.backends else None
        else:
            break
    return getattr(client, "name", None) or (type(client).__name__.removesuffix("LLM").lower() or None)


_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.I)
_THINK = re.compile(r"<think>.*?</think>", re.S | re.I)


def extract_json(text: str) -> str:
    """Best-effort: the JSON object inside a reply that may carry <think> blocks, code fences or prose."""
    t = _THINK.sub("", text or "").strip()
    t = _FENCE.sub("", t).strip()
    if t.startswith("{"):
        try:
            json.loads(t)
            return t
        except json.JSONDecodeError:
            pass
    start = t.find("{")
    if start < 0:
        return t
    dec = json.JSONDecoder()
    for i in range(start, len(t)):  # first position where a complete object parses
        if t[i] != "{":
            continue
        try:
            obj, _ = dec.raw_decode(t[i:])
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            return json.dumps(obj)
    return t


class LLMClient(Protocol):
    def complete_json(self, tier: Tier, system: str, user: str, schema: type[T]) -> T: ...


def _json_messages(system: str, user: str, schema: type[BaseModel]) -> list[dict]:
    schema_json = json.dumps(schema.model_json_schema(), ensure_ascii=False)
    return [
        {"role": "system",
         "content": f"{system}\n\nReturn ONLY a JSON object that validates against this JSON Schema:\n{schema_json}"},
        {"role": "user", "content": user},
    ]


def _fix_request(messages: list[dict], text: str, err: Exception) -> list[dict]:
    return messages + [
        {"role": "assistant", "content": text},
        {"role": "user", "content": f"Invalid JSON for the schema: {err}. Return corrected JSON only."},
    ]


class OpenAICompatLLM:
    """Any OpenAI-compatible endpoint (LiteLLM gateway, DeepInfra, ...), models addressed per tier.

    Under the gateway (a CallContext is set) each call gets its own HTTP client with the call's connect / total
    deadline, closed on cancel; token usage and rate-limit headers are reported to the context."""

    def __init__(self, base_url: str, api_key: str, models: dict[str, str], max_retries: int = 2, timeout: float = 600,
                 client=None):
        self._conn = None
        if client is None:
            from openai import OpenAI  # imported lazily so tests don't need network libs

            client = OpenAI(base_url=base_url, api_key=api_key or "none", timeout=timeout)
            self._conn = (base_url, api_key or "none")
        self.client = client
        self.max_retries = max_retries
        self.models = models

    def _call_client(self):
        """(client, closer): a per-call client bound to the call's deadlines under the gateway, else the shared one."""
        ctx = _CALL.get()
        if ctx is None or self._conn is None:
            return self.client, None
        import httpx
        from openai import OpenAI

        http = httpx.Client(timeout=_http_timeout(ctx))
        ctx.on_cancel(http.close)
        return OpenAI(base_url=self._conn[0], api_key=self._conn[1], http_client=http, max_retries=0,
                      timeout=_http_timeout(ctx)), http.close

    def _create(self, client, **kw):
        raw = getattr(getattr(getattr(client, "chat", None), "completions", None), "with_raw_response", None)
        if raw is not None and _CALL.get() is not None:
            r = raw.create(**kw)
            resp = r.parse()
            _note_usage(resp, r.headers)
            return resp
        resp = client.chat.completions.create(**kw)
        _note_usage(resp)
        return resp

    def complete_json(self, tier: Tier, system: str, user: str, schema: type[T]) -> T:
        messages = _json_messages(system, user, schema)
        last_err: Exception | None = None
        client, close = self._call_client()
        try:
            for attempt in range(self.max_retries + 1):
                resp = self._create(client, model=self.models[tier], messages=messages,
                                    response_format={"type": "json_object"}, temperature=0.2)
                text = resp.choices[0].message.content or ""
                try:
                    return schema.model_validate_json(extract_json(text))
                except ValidationError as e:  # feed the error back once or twice, then fail loudly
                    last_err = e
                    log.warning("schema validation failed (attempt %s): %s", attempt + 1, e)
                    messages = _fix_request(messages, text, e)
        finally:
            if close:
                close()
        raise SchemaError(f"model output never matched {schema.__name__}: {last_err}")


class SambaNovaLLM(OpenAICompatLLM):
    """SambaNova Cloud (OpenAI-compatible). Fast and free, but per-model quotas and "high demand" 402s happen, so:
    short timeout, ONE retry (timeout / 5xx / invalid output), and a 429 parks the model for COOLDOWN_S so the
    chain falls through immediately instead of waiting. JSON mode (`response_format=json_object`) is used when
    the model accepts it; a 400 on it switches to prompt-only JSON, parsed robustly (think blocks / fences).

    Under the gateway (park=False) the parking and the transient retry are the gateway's job (circuit breaker,
    deadlines, next model); only the schema-repair retry stays here."""

    COOLDOWN_S = 600
    _cooldown: ClassVar[dict[str, float]] = {}  # model -> monotonic deadline (shared by all instances in the process)

    def __init__(self, base_url: str, api_key: str, model: str, timeout: float = 60, client=None, park: bool = True):
        own = client is None
        if client is None:
            from openai import OpenAI

            client = OpenAI(base_url=base_url, api_key=api_key, timeout=timeout, max_retries=0)
        super().__init__(base_url, api_key, {"cloud": model, "cloud_max": model, "local": model}, 1, timeout, client)
        if own:
            self._conn = (base_url, api_key)
        self.model = model
        self.json_mode = True
        self.park = park

    def complete_json(self, tier: Tier, system: str, user: str, schema: type[T]) -> T:
        client, close = self._call_client()
        try:
            return self._complete(client, schema, system, user)
        finally:
            if close:
                close()

    def _complete(self, client, schema: type[T], system: str, user: str) -> T:
        import openai

        until = self._cooldown.get(self.model, 0.0)
        if self.park and time.monotonic() < until:
            raise RateLimited(f"sambanova {self.model} rate-limited (cooling down)")
        messages = _json_messages(system, user, schema)
        last_err: Exception | None = None
        schema_failed = False
        for attempt in range(2):  # first try + one retry, then fall through to the next provider
            kw = {"response_format": {"type": "json_object"}} if self.json_mode else {}
            try:
                resp = self._create(client, model=self.model, messages=messages, temperature=0.2, **kw)
            except openai.RateLimitError as e:
                if self.park:
                    self._cooldown[self.model] = time.monotonic() + self.COOLDOWN_S
                _note_error_headers(e)
                raise RateLimited(f"sambanova {self.model} rate-limited: {e}") from e
            except openai.BadRequestError as e:
                if self.json_mode:  # JSON mode unsupported, or "Model did not output valid JSON"
                    self.json_mode = False
                    last_err = e
                    continue
                raise LLMError(f"sambanova {self.model} rejected the request: {e}") from e
            except (openai.APITimeoutError, openai.APIConnectionError, openai.InternalServerError) as e:
                if not self.park:  # gateway: the deadline / breaker / next model handle it
                    raise LLMError(f"sambanova {self.model} {type(e).__name__}: {e}") from e
                last_err = e
                log.warning("sambanova %s attempt %s failed: %s", self.model, attempt + 1, e)
                continue
            except openai.APIStatusError as e:  # 401/403/404 etc.: no point retrying
                if e.status_code == 402:  # free credit used up / payment method required: park like a 429
                    if self.park:
                        self._cooldown[self.model] = time.monotonic() + self.COOLDOWN_S
                    raise RateLimited(f"sambanova {self.model} HTTP 402: {e}") from e
                raise LLMError(f"sambanova {self.model} HTTP {e.status_code}: {e}") from e
            text = (resp.choices[0].message.content or "") if resp.choices else ""
            try:
                return schema.model_validate_json(extract_json(text))
            except ValidationError as e:
                last_err, schema_failed = e, True
                messages = _fix_request(messages, text, e)
        err = SchemaError if schema_failed else LLMError
        raise err(f"sambanova {self.model} failed for {schema.__name__}: {last_err}")


def _note_error_headers(e: Exception) -> None:
    ctx = _CALL.get()
    resp = getattr(e, "response", None)
    if ctx is not None and resp is not None:
        ctx.meta["headers"] = {k.lower(): v for k, v in resp.headers.items() if "ratelimit" in k.lower()}


class GatewayLLM(OpenAICompatLLM):
    """OpenAI-compatible client pointed at the LiteLLM gateway."""

    def __init__(self, settings: Settings | None = None, max_retries: int = 2):
        self.s = settings or get_settings()
        super().__init__(
            self.s.llm_gateway_url,
            self.s.llm_gateway_key,
            {"local": self.s.model_local, "cloud": self.s.model_cloud, "cloud_max": self.s.model_cloud_max},
            max_retries,
        )

    def complete_json(self, tier: Tier, system: str, user: str, schema: type[T]) -> T:
        out = super().complete_json(tier, system, user, schema)
        note_provider(f"gateway:{self.models[tier]}")
        return out


def find_claude_cli(configured: str = "") -> str:
    """Explicit path, then $PATH, then the binary bundled with the VS Code / Antigravity extension."""
    if configured:
        return configured
    found = shutil.which("claude")
    if found:
        return found
    home = os.path.expanduser("~")
    bundled = sorted(
        glob.glob(f"{home}/.*-server/extensions/anthropic.claude-code-*/resources/native-binary/claude")
        + glob.glob(f"{home}/.vscode/extensions/anthropic.claude-code-*/resources/native-binary/claude")
    )
    if bundled:
        return bundled[-1]
    raise LLMError("Claude CLI not found: install it or set CLAUDE_CLI_PATH")


class ClaudeCliLLM:
    """Headless Claude Code (`claude -p`) with structured output enforced by --json-schema.

    Runs with no tools, no MCP servers, no user/project settings and an isolated working
    directory, so the model can only read the prompt and return JSON — nothing else.
    """

    def __init__(self, models: dict[str, str], cli_path: str = "", timeout: float = 300, runner=subprocess.run):
        self.models = models
        self.cli_path = cli_path
        self.timeout = timeout
        self.runner = runner

    def complete_json(self, tier: Tier, system: str, user: str, schema: type[T]) -> T:
        cmd = [
            find_claude_cli(self.cli_path), "-p",
            "--output-format", "json",
            "--model", self.models[tier],
            "--tools", "",
            "--strict-mcp-config",
            "--setting-sources", "",
            "--no-session-persistence",
            "--system-prompt", system,
            "--json-schema", json.dumps(schema.model_json_schema(), ensure_ascii=False),
        ]
        with tempfile.TemporaryDirectory(prefix="blockid-claude-") as cwd:
            try:
                proc = self.runner(cmd, input=user, capture_output=True, text=True, timeout=self.timeout, cwd=cwd)
            except subprocess.TimeoutExpired as e:
                raise LLMError(f"claude CLI timed out after {self.timeout}s") from e
        try:
            out = json.loads(proc.stdout)
        except json.JSONDecodeError as e:
            raise LLMError(f"claude CLI exit {proc.returncode}: {(proc.stderr or proc.stdout)[:500]}") from e
        if proc.returncode != 0 or out.get("is_error") or out.get("structured_output") is None:
            raise LLMError(f"claude CLI failed ({out.get('subtype')}): {str(out.get('result'))[:500]}")
        log.info("claude CLI %s -> %s, cost $%s", self.models[tier], schema.__name__, out.get("total_cost_usd"))
        try:
            return schema.model_validate(out["structured_output"])
        except ValidationError as e:
            raise SchemaError(f"claude CLI output did not match {schema.__name__}: {e}") from e


class ClaudeBridgeLLM:
    """The host bridge's POST /complete (deploy/search-bridge): headless Claude with no tools and our JSON schema,
    billed to the signed-in Claude subscription. Any bridge failure (cap reached, timeout, CLI error) parks it for
    COOLDOWN_S so the chain falls through to the next provider without waiting (park=False under the gateway: the
    circuit breaker and the quota ledger decide instead)."""

    COOLDOWN_S = 600

    def __init__(self, url: str, token: str, timeout: float = 260, transport=None, park: bool = True):
        import httpx

        self.url = url.rstrip("/") + "/complete"
        self.headers = {"X-Bridge-Token": token, "Accept": "application/json"}
        self.transport = transport
        self.http = httpx.Client(timeout=timeout, transport=transport, trust_env=False, headers=self.headers)
        self.until = 0.0
        self.park = park

    def _park(self) -> None:
        if self.park:
            self.until = time.monotonic() + self.COOLDOWN_S

    def complete_json(self, tier: Tier, system: str, user: str, schema: type[T]) -> T:
        import httpx

        if self.park and time.monotonic() < self.until:
            raise LLMError("claude bridge cooling down")
        ctx = _CALL.get()
        http, close = self.http, None
        if ctx is not None:  # own connection with the call's deadlines, closed on cancel
            http = httpx.Client(timeout=_http_timeout(ctx), transport=self.transport, trust_env=False,
                                headers=self.headers)
            ctx.on_cancel(http.close)
            close = http.close
        try:
            try:
                r = http.post(self.url, json={"system": system, "user": user,
                                              "schema": schema.model_json_schema()})
            except httpx.HTTPError as e:
                self._park()
                raise LLMError(f"claude bridge unreachable: {type(e).__name__}") from e
        finally:
            if close:
                close()
        if r.status_code != 200:
            if r.status_code in (401, 404, 429) or r.status_code >= 500:
                self._park()
            err = RateLimited if r.status_code == 429 else LLMError
            raise err(f"claude bridge HTTP {r.status_code}: {r.text[:300]}")
        data = r.json()
        log.info("claude bridge %s -> %s, $%s (subscription)", data.get("model"), schema.__name__, data.get("cost_usd"))
        if ctx is not None:
            ctx.meta["notional_cost_usd"] = data.get("cost_usd")
        try:
            return schema.model_validate(data.get("structured_output"))
        except ValidationError as e:
            raise SchemaError(f"claude bridge output did not match {schema.__name__}: {e}") from e


class FallbackLLM:
    """Try each backend in order; the first valid answer wins. Every failure is logged."""

    def __init__(self, backends: list[tuple[str, LLMClient]]):
        self.backends = backends
        self.used: list[tuple[str, str]] = []  # (backend name, schema) for each successful call

    def complete_json(self, tier: Tier, system: str, user: str, schema: type[T]) -> T:
        errors = []
        for i, (name, backend) in enumerate(self.backends):
            try:
                out = backend.complete_json(tier, system, user, schema)
            except Exception as e:  # CLI down, quota, network, invalid output -> next backend
                log.warning("LLM backend %s failed for %s: %s", name, schema.__name__, e)
                errors.append(f"{name}: {e}")
                nxt = self.backends[i + 1][0] if i + 1 < len(self.backends) else None
                emit({"type": "llm_fallback", "failed": name, "next": nxt, "error": f"{type(e).__name__}: {e}"[:200]})
                continue
            self.used.append((name, schema.__name__))
            log.info("LLM %s answered %s", name, schema.__name__)
            note_provider(name)
            emit({"type": "llm_answered", "provider": name})
            return out
        raise LLMError(f"all LLM backends failed for {schema.__name__}: " + " | ".join(errors))


class TierRouter:
    """Route each tier to its own client."""

    def __init__(self, routes: dict[str, LLMClient]):
        self.routes = routes

    def complete_json(self, tier: Tier, system: str, user: str, schema: type[T], profile: str | None = None) -> T:
        """`profile` (ai_gateway task profile, e.g. "extract_json") is passed to a gateway-routed client; other
        clients route by schema / tier as before."""
        route = self.routes[tier]
        if profile and isinstance(route, RoutedLLM):
            return route.complete_json(tier, system, user, schema, profile=profile)
        return route.complete_json(tier, system, user, schema)


class RoutedLLM(FallbackLLM):
    """A cloud chain run through the AI gateway (ai_gateway.Gateway.complete): `backends` is the configured pool in
    env order (LLM_PROVIDER_ORDER / *_MODELS, or the agent's HR_* lists); each call is routed by task profile with
    deadlines, hedging (interactive=True), circuit breakers, quota demote/skip, pacing, the fair per-user queue and
    the result cache. `pins`: profile -> model ids tried first when healthy (HR: Claude for reason_score)."""

    def __init__(self, backends: list[tuple[str, LLMClient]], gateway=None, *, agent: str = "default",
                 interactive: bool = True, pins: dict[str, tuple[str, ...]] | None = None):
        super().__init__(backends)
        self.gateway = gateway
        self.agent = agent
        self.interactive = interactive
        self.pins = {k: tuple(v) for k, v in (pins or {}).items()}

    def _gw(self):
        if self.gateway is None:
            from .ai_gateway import get_gateway

            self.gateway = get_gateway()
        return self.gateway

    def complete_json(self, tier: Tier, system: str, user: str, schema: type[T], profile: str | None = None) -> T:
        try:
            return self._gw().complete(self, tier, system, user, schema, profile=profile)
        except LLMError:
            raise
        except Exception:  # noqa: BLE001 - a gateway bug must never stop the work: plain chain in env order
            log.exception("AI gateway error; falling back to the plain chain")
            return FallbackLLM.complete_json(self, tier, system, user, schema)

    def first(self, profile: str = "extract_json") -> str | None:
        """The model the next `profile` call would try first (None when nothing is available)."""
        try:
            order = self._gw().plan(profile, [n for n, _ in self.backends], 0, pins=self.pins.get(profile, ())).order
        except Exception:  # noqa: BLE001 - only used for progress messages
            log.exception("gateway plan")
            return self.backends[0][0] if self.backends else None
        return order[0] if order else None


def cloud_chain(s: Settings, *, order: tuple[str, ...] | list[str] | None = None,
                sambanova_models: tuple[str, ...] | None = None, deepinfra_models: tuple[str, ...] | None = None,
                auto_cli: bool = True, park: bool = True) -> list[tuple[str, LLMClient]]:
    """Cloud-tier fallback chain: Claude CLI (if enabled) first unless LLM_PROVIDER_ORDER places "claude"
    elsewhere, then the providers in LLM_PROVIDER_ORDER. Providers without credentials are skipped.

    Per-agent override (see AGENT_CHAINS / build_agent_llms): `order` / `sambanova_models` / `deepinfra_models`
    replace the global settings; auto_cli=False adds the Claude CLI only where `order` lists "claude".
    park=False (the gateway): no per-backend 10-min parking / transient retry — the gateway's breaker, deadlines and
    ledger decide; the transports' own timeouts are the per-provider deadlines."""
    order = list(s.llm_provider_order if order is None else order)
    samba = s.sambanova_models if sambanova_models is None else sambanova_models
    deepinfra = s.deepinfra_models if deepinfra_models is None else deepinfra_models
    if auto_cli and s.claude_cli_enabled and "claude" not in order:
        order.insert(0, "claude")
    chain: list[tuple[str, LLMClient]] = []
    for name in order:
        if name == "claude" and s.claude_cli_enabled:
            chain.append((
                "claude-cli",
                ClaudeCliLLM({"cloud": s.claude_model_cloud, "cloud_max": s.claude_model_cloud_max},
                             s.claude_cli_path, s.claude_cli_timeout if park else
                             min(s.claude_cli_timeout, s.ai_deadline_claude_s + 5)),
            ))
        elif name == "claude_bridge" and s.claude_search_url and s.claude_search_token:
            chain.append(("claude-bridge",
                          ClaudeBridgeLLM(s.claude_search_url, s.claude_search_token,
                                          s.claude_complete_timeout if park else s.ai_deadline_claude_s, park=park)))
        elif name == "sambanova" and s.sambanova_api_key:
            for m in samba:
                chain.append((f"sambanova:{m}",
                              SambaNovaLLM(s.sambanova_base_url, s.sambanova_api_key, m, s.sambanova_timeout,
                                           park=park)))
        elif name == "deepinfra" and s.deepinfra_api_key:
            for m in deepinfra:
                chain.append((
                    f"deepinfra:{m}",
                    OpenAICompatLLM(s.deepinfra_base_url, s.deepinfra_api_key, {"cloud": m, "cloud_max": m},
                                    max_retries=1, timeout=300 if park else s.ai_deadline_deepinfra_s),
                ))
        elif name not in ("claude", "claude_bridge", "sambanova", "deepinfra"):
            log.warning("unknown LLM provider %r in LLM_PROVIDER_ORDER (ignored)", name)
    return chain


def build_llm(settings: Settings | None = None) -> LLMClient:
    """LLM_BACKEND=gateway (default): everything via LiteLLM.
    LLM_BACKEND=hosted: local -> gateway; cloud/cloud_max -> `cloud_chain` (Claude CLI / SambaNova / DeepInfra)
    routed by the AI gateway (RoutedLLM)."""
    s = settings or get_settings()
    if s.llm_backend == "gateway":
        return GatewayLLM(s)
    if s.llm_backend != "hosted":
        raise LLMError(f"unknown LLM_BACKEND {s.llm_backend!r}")
    from .ai_gateway import get_gateway

    chain = cloud_chain(s, park=not s.ai_gateway)
    if not chain:
        raise LLMError("LLM_BACKEND=hosted needs the Claude CLI, SAMBANOVA_API_KEY or DEEPINFRA_API_KEY")
    log.info("cloud LLM pool: %s", ", ".join(n for n, _ in chain))
    hosted = (RoutedLLM(chain, get_gateway(s), agent="default", interactive=True) if s.ai_gateway
              else FallbackLLM(chain))
    return TierRouter({"local": GatewayLLM(s), "cloud": hosted, "cloud_max": hosted})


# Agents with their own cloud chain (LLM_BACKEND=hosted only). Every other agent uses build_llm's chain.
# people_analyst: HR_LLM_PROVIDER_ORDER / HR_SAMBANOVA_MODELS / HR_DEEPINFRA_MODELS (docs/LLM-ROUTING.md);
# its reason_score calls (team review) try HR_REASON_SCORE_MODELS (default Claude via the bridge) first.
AGENT_CHAINS: dict[str, Callable[[Settings], dict]] = {
    "people_analyst": lambda s: {"order": s.hr_llm_provider_order, "sambanova_models": s.hr_sambanova_models,
                                 "deepinfra_models": s.hr_deepinfra_models, "auto_cli": False},
}
AGENT_PINS: dict[str, Callable[[Settings], dict]] = {
    "people_analyst": lambda s: {"reason_score": s.hr_reason_score_models},
}


def build_agent_llms(settings: Settings | None = None) -> dict[str, LLMClient]:
    """agent name -> its own client (Deps.agent_llm). Empty with LLM_BACKEND=gateway (the gateway routes by tier).
    The cloud tiers go to the agent's chain; `local` stays on the gateway exactly like build_llm."""
    s = settings or get_settings()
    if s.llm_backend != "hosted":
        return {}
    from .ai_gateway import get_gateway

    out: dict[str, LLMClient] = {}
    for agent, spec in AGENT_CHAINS.items():
        chain = cloud_chain(s, **spec(s), park=not s.ai_gateway)
        if not chain:
            log.warning("no LLM provider configured for agent %s; it uses the default chain", agent)
            continue
        log.info("%s LLM pool: %s", agent, ", ".join(n for n, _ in chain))
        pins = AGENT_PINS.get(agent, lambda _s: {})(s)
        hosted = (RoutedLLM(chain, get_gateway(s), agent=agent, interactive=True, pins=pins) if s.ai_gateway
                  else FallbackLLM(chain))
        out[agent] = TierRouter({"local": GatewayLLM(s), "cloud": hosted, "cloud_max": hosted})
    return out


class FakeLLM:
    """Deterministic stand-in for tests and offline demos.

    `handlers` maps a schema class to a function (system, user) -> schema instance.
    Every call is recorded so tests can assert which tier handled which data.
    """

    def __init__(self, handlers: dict[type[BaseModel], Callable[[str, str], BaseModel]]):
        self.handlers = handlers
        self.calls: list[tuple[Tier, str]] = []
        self.name = "fake"

    def complete_json(self, tier: Tier, system: str, user: str, schema: type[T]) -> T:
        self.calls.append((tier, schema.__name__))
        if schema not in self.handlers:
            raise LLMError(f"FakeLLM has no handler for {schema.__name__}")
        out = self.handlers[schema](system, user)
        note_provider(self.name)
        return schema.model_validate(out.model_dump())
