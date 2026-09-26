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
import time
from typing import Callable, ClassVar, Literal, Protocol, TypeVar

from pydantic import BaseModel, ValidationError

from .config import Settings, get_settings

log = logging.getLogger(__name__)

Tier = Literal["local", "cloud", "cloud_max"]
T = TypeVar("T", bound=BaseModel)


class LLMError(RuntimeError):
    pass


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
    """Any OpenAI-compatible endpoint (LiteLLM gateway, DeepInfra, ...), models addressed per tier."""

    def __init__(self, base_url: str, api_key: str, models: dict[str, str], max_retries: int = 2, timeout: float = 600,
                 client=None):
        if client is None:
            from openai import OpenAI  # imported lazily so tests don't need network libs

            client = OpenAI(base_url=base_url, api_key=api_key or "none", timeout=timeout)
        self.client = client
        self.max_retries = max_retries
        self.models = models

    def complete_json(self, tier: Tier, system: str, user: str, schema: type[T]) -> T:
        messages = _json_messages(system, user, schema)
        last_err: Exception | None = None
        for attempt in range(self.max_retries + 1):
            resp = self.client.chat.completions.create(
                model=self.models[tier],
                messages=messages,
                response_format={"type": "json_object"},
                temperature=0.2,
            )
            text = resp.choices[0].message.content or ""
            try:
                return schema.model_validate_json(extract_json(text))
            except ValidationError as e:  # feed the error back once or twice, then fail loudly
                last_err = e
                log.warning("schema validation failed (attempt %s): %s", attempt + 1, e)
                messages = _fix_request(messages, text, e)
        raise LLMError(f"model output never matched {schema.__name__}: {last_err}")


class SambaNovaLLM(OpenAICompatLLM):
    """SambaNova Cloud (OpenAI-compatible). Fast and free, but per-model quotas and "high demand" 402s happen, so:
    short timeout, ONE retry (timeout / 5xx / invalid output), and a 429 parks the model for COOLDOWN_S so the
    chain falls through immediately instead of waiting. JSON mode (`response_format=json_object`) is used when
    the model accepts it; a 400 on it switches to prompt-only JSON, parsed robustly (think blocks / fences)."""

    COOLDOWN_S = 600
    _cooldown: ClassVar[dict[str, float]] = {}  # model -> monotonic deadline (shared by all instances in the process)

    def __init__(self, base_url: str, api_key: str, model: str, timeout: float = 60, client=None):
        if client is None:
            from openai import OpenAI

            client = OpenAI(base_url=base_url, api_key=api_key, timeout=timeout, max_retries=0)
        super().__init__(base_url, api_key, {"cloud": model, "cloud_max": model, "local": model}, 1, timeout, client)
        self.model = model
        self.json_mode = True

    def complete_json(self, tier: Tier, system: str, user: str, schema: type[T]) -> T:
        import openai

        until = self._cooldown.get(self.model, 0.0)
        if time.monotonic() < until:
            raise LLMError(f"sambanova {self.model} rate-limited (cooling down)")
        messages = _json_messages(system, user, schema)
        last_err: Exception | None = None
        for attempt in range(2):  # first try + one retry, then fall through to the next provider
            kw = {"response_format": {"type": "json_object"}} if self.json_mode else {}
            try:
                resp = self.client.chat.completions.create(model=self.model, messages=messages, temperature=0.2,
                                                           **kw)
            except openai.RateLimitError as e:
                self._cooldown[self.model] = time.monotonic() + self.COOLDOWN_S
                raise LLMError(f"sambanova {self.model} rate-limited: {e}") from e
            except openai.BadRequestError as e:
                if self.json_mode:  # JSON mode unsupported, or "Model did not output valid JSON"
                    self.json_mode = False
                    last_err = e
                    continue
                raise LLMError(f"sambanova {self.model} rejected the request: {e}") from e
            except (openai.APITimeoutError, openai.APIConnectionError, openai.InternalServerError) as e:
                last_err = e
                log.warning("sambanova %s attempt %s failed: %s", self.model, attempt + 1, e)
                continue
            except openai.APIStatusError as e:  # 401/403/404 etc.: no point retrying
                if e.status_code == 402:  # free credit used up / payment method required: park like a 429
                    self._cooldown[self.model] = time.monotonic() + self.COOLDOWN_S
                raise LLMError(f"sambanova {self.model} HTTP {e.status_code}: {e}") from e
            text = (resp.choices[0].message.content or "") if resp.choices else ""
            try:
                return schema.model_validate_json(extract_json(text))
            except ValidationError as e:
                last_err = e
                messages = _fix_request(messages, text, e)
        raise LLMError(f"sambanova {self.model} failed for {schema.__name__}: {last_err}")


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
            raise LLMError(f"claude CLI output did not match {schema.__name__}: {e}") from e


class ClaudeBridgeLLM:
    """The host bridge's POST /complete (deploy/search-bridge): headless Claude with no tools and our JSON schema,
    billed to the signed-in Claude subscription. Any bridge failure (cap reached, timeout, CLI error) parks it for
    COOLDOWN_S so the chain falls through to the next provider without waiting."""

    COOLDOWN_S = 600

    def __init__(self, url: str, token: str, timeout: float = 260, transport=None):
        import httpx

        self.url = url.rstrip("/") + "/complete"
        self.http = httpx.Client(timeout=timeout, transport=transport, trust_env=False,
                                 headers={"X-Bridge-Token": token, "Accept": "application/json"})
        self.until = 0.0

    def complete_json(self, tier: Tier, system: str, user: str, schema: type[T]) -> T:
        import httpx

        if time.monotonic() < self.until:
            raise LLMError("claude bridge cooling down")
        try:
            r = self.http.post(self.url, json={"system": system, "user": user, "schema": schema.model_json_schema()})
        except httpx.HTTPError as e:
            self.until = time.monotonic() + self.COOLDOWN_S
            raise LLMError(f"claude bridge unreachable: {type(e).__name__}") from e
        if r.status_code != 200:
            if r.status_code in (401, 404, 429) or r.status_code >= 500:
                self.until = time.monotonic() + self.COOLDOWN_S
            raise LLMError(f"claude bridge HTTP {r.status_code}: {r.text[:300]}")
        data = r.json()
        log.info("claude bridge %s -> %s, $%s (subscription)", data.get("model"), schema.__name__, data.get("cost_usd"))
        try:
            return schema.model_validate(data.get("structured_output"))
        except ValidationError as e:
            raise LLMError(f"claude bridge output did not match {schema.__name__}: {e}") from e


class FallbackLLM:
    """Try each backend in order; the first valid answer wins. Every failure is logged."""

    def __init__(self, backends: list[tuple[str, LLMClient]]):
        self.backends = backends
        self.used: list[tuple[str, str]] = []  # (backend name, schema) for each successful call

    def complete_json(self, tier: Tier, system: str, user: str, schema: type[T]) -> T:
        errors = []
        for name, backend in self.backends:
            try:
                out = backend.complete_json(tier, system, user, schema)
            except Exception as e:  # CLI down, quota, network, invalid output -> next backend
                log.warning("LLM backend %s failed for %s: %s", name, schema.__name__, e)
                errors.append(f"{name}: {e}")
                continue
            self.used.append((name, schema.__name__))
            log.info("LLM %s answered %s", name, schema.__name__)
            note_provider(name)
            return out
        raise LLMError(f"all LLM backends failed for {schema.__name__}: " + " | ".join(errors))


class TierRouter:
    """Route each tier to its own client."""

    def __init__(self, routes: dict[str, LLMClient]):
        self.routes = routes

    def complete_json(self, tier: Tier, system: str, user: str, schema: type[T]) -> T:
        return self.routes[tier].complete_json(tier, system, user, schema)


def cloud_chain(s: Settings) -> list[tuple[str, LLMClient]]:
    """Cloud-tier fallback chain: Claude CLI (if enabled) first unless LLM_PROVIDER_ORDER places "claude"
    elsewhere, then the providers in LLM_PROVIDER_ORDER. Providers without credentials are skipped."""
    order = list(s.llm_provider_order)
    if s.claude_cli_enabled and "claude" not in order:
        order.insert(0, "claude")
    chain: list[tuple[str, LLMClient]] = []
    for name in order:
        if name == "claude" and s.claude_cli_enabled:
            chain.append((
                "claude-cli",
                ClaudeCliLLM({"cloud": s.claude_model_cloud, "cloud_max": s.claude_model_cloud_max},
                             s.claude_cli_path, s.claude_cli_timeout),
            ))
        elif name == "claude_bridge" and s.claude_search_url and s.claude_search_token:
            chain.append(("claude-bridge",
                          ClaudeBridgeLLM(s.claude_search_url, s.claude_search_token, s.claude_complete_timeout)))
        elif name == "sambanova" and s.sambanova_api_key:
            for m in s.sambanova_models:
                chain.append((f"sambanova:{m}",
                              SambaNovaLLM(s.sambanova_base_url, s.sambanova_api_key, m, s.sambanova_timeout)))
        elif name == "deepinfra" and s.deepinfra_api_key:
            for m in s.deepinfra_models:
                chain.append((
                    f"deepinfra:{m}",
                    OpenAICompatLLM(s.deepinfra_base_url, s.deepinfra_api_key, {"cloud": m, "cloud_max": m},
                                    max_retries=1, timeout=300),
                ))
        elif name not in ("claude", "claude_bridge", "sambanova", "deepinfra"):
            log.warning("unknown LLM provider %r in LLM_PROVIDER_ORDER (ignored)", name)
    return chain


def build_llm(settings: Settings | None = None) -> LLMClient:
    """LLM_BACKEND=gateway (default): everything via LiteLLM.
    LLM_BACKEND=hosted: local -> gateway; cloud/cloud_max -> `cloud_chain` (Claude CLI / SambaNova / DeepInfra)."""
    s = settings or get_settings()
    if s.llm_backend == "gateway":
        return GatewayLLM(s)
    if s.llm_backend != "hosted":
        raise LLMError(f"unknown LLM_BACKEND {s.llm_backend!r}")

    chain = cloud_chain(s)
    if not chain:
        raise LLMError("LLM_BACKEND=hosted needs the Claude CLI, SAMBANOVA_API_KEY or DEEPINFRA_API_KEY")
    log.info("cloud LLM chain: %s", ", ".join(n for n, _ in chain))
    hosted = FallbackLLM(chain)
    return TierRouter({"local": GatewayLLM(s), "cloud": hosted, "cloud_max": hosted})


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
