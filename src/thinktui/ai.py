"""Opt-in AI assistance; network requests never affect calculations or user state.

Providers are isolated behind ``AIProvider``. The rest of ThinkTUI only sees ``connect()`` and
plain text answers (whole or streamed), never which backend, credential or transport was used.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import signal
import tempfile
import threading
from collections.abc import AsyncIterator, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Protocol
from urllib import error, parse, request

from . import credentials
from .core import Session

PROMPT_VERSION = "challenger/1.0"
SYSTEM = (
    "You are a structured-thinking challenger. Do not fabricate evidence. "
    "Distinguish facts from assumptions, state uncertainty, offer alternatives "
    "and disconfirming tests. Do not decide for the user. Keep it concise."
)
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}


@dataclass(frozen=True)
class AIRequest:
    question: str
    context: dict


class AIProvider(Protocol):
    async def complete(self, prompt: AIRequest) -> str: ...

    def stream(self, prompt: AIRequest) -> AsyncIterator[str]: ...

    async def preparing_note(self) -> str: ...

    async def models(self) -> list[str]: ...

    async def health_check(self) -> str: ...


@dataclass(frozen=True)
class Preset:
    id: str
    label: str
    kind: str  # off | ollama | openai (chat-completions compatible) | anthropic | claude_cli | codex_cli | cursor_cli
    base_url: str = ""
    key_env: str = ""
    key_required: bool = False
    default_model: str = ""
    note: str = ""


PRESETS: dict[str, Preset] = {
    p.id: p
    for p in (
        Preset("off", "Off", "off", note="AI disabled. All methods work without AI."),
        Preset(
            "ollama",
            "Ollama",
            "ollama",
            "http://localhost:11434",
            note="Runs models on this computer (or a remote Ollama host you enter). Leave model blank to use the first installed model.",
        ),
        Preset(
            "claude_code",
            "Claude subscription (Claude Code CLI)",
            "claude_cli",
            default_model="sonnet",
            note="Uses your Claude Pro/Max login through the official `claude` CLI. Install Claude Code, then press Sign in. ANTHROPIC_API_KEY is not passed through, so usage counts against your subscription.",
        ),
        Preset(
            "chatgpt",
            "ChatGPT subscription (Codex CLI)",
            "codex_cli",
            note="Uses your ChatGPT Plus/Pro/Team plan through OpenAI's official Codex CLI. Press Sign in with ChatGPT to log in in your browser. OPENAI_API_KEY is not passed through, so usage counts against your plan.",
        ),
        Preset(
            "cursor",
            "Cursor subscription (Cursor Agent CLI)",
            "cursor_cli",
            note="Uses your Cursor account via the official `agent` CLI in read-only Ask mode. Install Cursor CLI, then press Sign in. Cursor CLI may still read files outside the temporary workspace or use network tools; use only if you trust its configuration. No API key is passed through.",
        ),
        Preset(
            "anthropic",
            "Anthropic API (Claude)",
            "anthropic",
            "https://api.anthropic.com/v1",
            "ANTHROPIC_API_KEY",
            True,
            "claude-sonnet-5-5",
            "Pay-as-you-go Claude API key from console.anthropic.com.",
        ),
        Preset(
            "openai",
            "OpenAI API",
            "openai",
            "https://api.openai.com/v1",
            "OPENAI_API_KEY",
            True,
            "gpt-4.1-mini",
            "API key from platform.openai.com.",
        ),
        Preset(
            "openrouter",
            "OpenRouter",
            "openai",
            "https://openrouter.ai/api/v1",
            "OPENROUTER_API_KEY",
            True,
            "openrouter/auto",
            "One key for hundreds of models (Claude, GPT, Gemini, Llama…). Model ids look like anthropic/claude-sonnet-4.",
        ),
        Preset(
            "gemini",
            "Google Gemini",
            "openai",
            "https://generativelanguage.googleapis.com/v1beta/openai",
            "GEMINI_API_KEY",
            True,
            "gemini-2.5-flash",
            "API key from aistudio.google.com (OpenAI-compatible endpoint).",
        ),
        Preset("groq", "Groq", "openai", "https://api.groq.com/openai/v1", "GROQ_API_KEY", True),
        Preset(
            "mistral",
            "Mistral",
            "openai",
            "https://api.mistral.ai/v1",
            "MISTRAL_API_KEY",
            True,
            "mistral-small-latest",
        ),
        Preset(
            "deepseek",
            "DeepSeek",
            "openai",
            "https://api.deepseek.com/v1",
            "DEEPSEEK_API_KEY",
            True,
            "deepseek-chat",
        ),
        Preset("xai", "xAI (Grok)", "openai", "https://api.x.ai/v1", "XAI_API_KEY", True),
        Preset("together", "Together AI", "openai", "https://api.together.xyz/v1", "TOGETHER_API_KEY", True),
        Preset(
            "lmstudio",
            "LM Studio / llama.cpp / vLLM (local)",
            "openai",
            "http://localhost:1234/v1",
            note="Any local OpenAI-compatible server. Adjust the base URL to match your server.",
        ),
        Preset(
            "custom",
            "Custom OpenAI-compatible endpoint",
            "openai",
            note="Any service exposing /chat/completions. Enter its base URL (ending in /v1), model and key if needed.",
        ),
    )
}
PROVIDER_CHOICES = ["auto", *PRESETS]
EFFORT_LEVELS = ("", "low", "medium", "high")
# Wire formats are service-specific. OpenAI-compatible transport does NOT imply OpenAI reasoning parameters.
# Local/custom endpoints offer an explicit opt-in for servers that implement reasoning_effort.
EFFORT_STYLES = {
    "ollama": "ollama",
    "claude_code": "claude_cli",
    "chatgpt": "codex_cli",
    "anthropic": "anthropic",
    "openai": "reasoning_effort",
    "openrouter": "openrouter_reasoning",
    "groq": "reasoning_effort",
    "gemini": "gemini_thinking",
    "mistral": "reasoning_effort",
    "deepseek": "deepseek_thinking",
    "xai": "reasoning_effort",
    "together": "reasoning_effort",
    "lmstudio": "reasoning_effort",
    "custom": "reasoning_effort",
}
EFFORT_PROVIDERS = frozenset(EFFORT_STYLES)


def effort_levels(preset_id: str, model: str) -> tuple[str, ...]:
    """Supported controls for documented model families; unknown models remain default-only."""
    if preset_id not in EFFORT_PROVIDERS:
        return ("",)
    name = model.lower()
    if preset_id == "openai" and name.startswith(("gpt-4.1", "gpt-4o", "gpt-3.5")):
        return ("",)
    if preset_id == "groq" and name not in {"openai/gpt-oss-120b", "openai/gpt-oss-20b"}:
        return ("",)
    if preset_id == "gemini" and not name.startswith(("gemini-2.5-", "gemini-3")):
        return ("",)
    if preset_id == "mistral":
        return ("", "high") if name.startswith(("mistral-small-", "mistral-medium-3-5", "mistral-large-4")) else ("",)
    if preset_id == "deepseek":
        return ("", "high") if name.startswith(("deepseek-flash", "deepseek-v4-pro")) else ("",)
    if preset_id == "xai" and not name.startswith(("grok-4.5", "grok-4.6", "grok-4.7")):
        return ("",)
    if preset_id == "together" and name != "openai/gpt-oss-120b":
        return ("",)
    return EFFORT_LEVELS


AUTO_NOTE = "Uses local Ollama automatically whenever it is running; otherwise AI stays off."

# Pre-1.1 settings keys, still honoured when the per-provider keys are unset.
_LEGACY = {
    ("ollama", "base_url"): "ollama_host",
    ("ollama", "model"): "ollama_model",
    ("openai", "model"): "openai_model",
}


@dataclass(frozen=True)
class ProviderConfig:
    preset_id: str
    base_url: str
    model: str
    effort: str = ""  # empty = service default; never infer a level from the model name

    @property
    def preset(self) -> Preset:
        return PRESETS[self.preset_id]


def _safe_base_url(url: str) -> None:
    parts = parse.urlsplit(url)
    if parts.username or parts.password or not parts.hostname:
        raise ValueError("Provider URL must have a host and no embedded credentials")


def is_local_url(url: str) -> bool:
    return (parse.urlparse(url).hostname or "") in LOCAL_HOSTS


def is_local(config: ProviderConfig) -> bool:
    return config.preset.kind in {"ollama", "openai"} and bool(config.base_url) and is_local_url(config.base_url)


def sharing_destination(config: ProviderConfig) -> str:
    """Disclose remote host and provider without exposing URL credentials or query strings."""
    host = parse.urlparse(config.base_url).hostname
    return "LOCAL" if is_local(config) else f"REMOTE → {config.preset.label}" + (f" ({host})" if host else "")


def public_error(exc: Exception) -> str:
    """Show actionable provider failures without echoing arbitrary secret-bearing error text."""
    message = str(exc)
    safe = (
        "No API key",
        "not signed in",
        "Not signed in",
        "no models",
        "not found",
        "timed out",
        "unreadable response",
        "no answer",
        "AI is off",
        "No AI available",
        "No local Ollama chat model",
        "Could not reach AI provider",
        "Choose a model",
        "Unsupported thinking level",
        "HTTP ",
    )
    if "CLI failed" in message or "CLI not found" in message:
        return "Subscription CLI failed. Check Sign in and Test connection in Settings."
    return (
        message
        if any(part in message for part in safe)
        and not any(word in message.lower() for word in ("secret", "token", "password", "bearer"))
        else "Provider request failed; check Settings and provider logs"
    )


def remote_consent(store, config: ProviderConfig) -> bool:
    """Consent is tied to the destination, not a transferable global preference."""
    if is_local(config):
        return True
    allowed_url = store.setting(f"ai.{config.preset_id}.consent_url", config.preset.base_url)
    return store.setting(f"ai.{config.preset_id}.consent") == "yes" and allowed_url.rstrip(
        "/"
    ) == config.base_url.rstrip("/")


def describe(config: ProviderConfig) -> str:
    where = " / Local" if is_local(config) else ""
    return (
        f"{config.preset.label}{where}"
        + (f" · {config.model}" if config.model else "")
        + (f" · thinking {config.effort}" if config.effort else "")
    )


def selected_provider(store) -> str:
    value = store.setting("ai_provider", "auto")
    return value if value in PROVIDER_CHOICES else "auto"


def config_for(store, preset_id: str) -> ProviderConfig:
    preset = PRESETS[preset_id]

    def value(field: str, default: str) -> str:
        legacy = _LEGACY.get((preset_id, field))
        return store.setting(f"ai.{preset_id}.{field}") or (store.setting(legacy) if legacy else "") or default

    return ProviderConfig(
        preset_id,
        value("base_url", preset.base_url).rstrip("/"),
        value("model", preset.default_model),
        store.setting(f"ai.{preset_id}.effort"),
    )


def key_status(preset_id: str) -> str:
    preset = PRESETS[preset_id]
    if preset.kind in {"off", "ollama", "claude_cli", "codex_cli", "cursor_cli"}:
        return ""
    _, source = credentials.get_key(preset_id, preset.key_env)
    labels = {"session": "entered for this session only", "keyring": "saved in OS keyring", "none": "not set"}
    return "API key: " + labels.get(source, f"from environment {source}")


def context_for(session: Session) -> dict:
    """Whitelist shared context. Private notes and historical projects stay local."""
    return {
        "method": session.method_id,
        "problem": session.problem_statement,
        "objective": session.objective,
        "assumptions": session.assumptions,
        "state": session.method_state,
    }


def parse_json_object(text: str) -> dict:
    """Extract the first JSON object from a reply that may include code fences or prose."""
    try:
        value = json.loads(text)
    except ValueError:
        match = re.search(r"\{.*\}", text, re.S)
        if not match:
            raise ValueError("No JSON object in reply") from None
        value = json.loads(match.group(0))
    if not isinstance(value, dict):
        raise ValueError("Reply is not a JSON object")
    return value


def visible_text(text: str) -> str:
    """Text safe to show while streaming: complete <think> blocks dropped, an unfinished one hidden."""
    text = re.sub(r"<think>.*?</think>", "", text or "", flags=re.S)
    return text.split("<think>", 1)[0]


def _clean(text: str) -> str:
    """Drop visible <think> blocks some local models emit; hidden reasoning is never shown."""
    return visible_text(text).strip()


def _user_content(prompt: AIRequest) -> str:
    return json.dumps({"context": prompt.context, "request": prompt.question})


def _json(line: str) -> dict:
    try:
        value = json.loads(line)
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}


def _provider_error(event: dict) -> str:
    """Short provider-reported error text from a streamed event, if any."""
    err = event.get("error")
    if isinstance(err, dict):
        err = err.get("message")
    return str(err)[:200] if err else ""


_HTTP_HINTS = {
    401: "authentication failed; check the API key",
    403: "access denied; check the API key and account permissions",
    404: "not found; check the base URL and model name",
    429: "rate limited or out of credit",
}


@contextmanager
def _http_errors(url: str) -> Iterator[None]:
    try:
        yield
    except error.HTTPError as exc:
        # Status codes only: never include headers or response bodies that might echo secrets.
        hint = _HTTP_HINTS.get(exc.code, "provider returned an error")
        raise RuntimeError(f"AI request failed (HTTP {exc.code}: {hint})") from None
    except (error.URLError, TimeoutError, OSError):
        raise RuntimeError(f"Could not reach AI provider at {parse.urlparse(url).hostname}") from None
    except ValueError:
        raise RuntimeError("AI provider returned an unreadable response") from None


def _http(url: str, payload: dict | None, headers: dict[str, str] | None) -> request.Request:
    data = json.dumps(payload).encode() if payload is not None else None
    return request.Request(url, data=data, headers={"Content-Type": "application/json", **(headers or {})})


class _NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _open(url: str, payload: dict | None, headers: dict[str, str] | None, timeout: float):
    # Never proxy local prompts or forward credentials/prompt bodies on redirects.
    handlers = [_NoRedirect()]
    if is_local_url(url):
        handlers.append(request.ProxyHandler({}))
    return request.build_opener(*handlers).open(_http(url, payload, headers), timeout=timeout)


def _request(
    url: str, payload: dict | None = None, headers: dict[str, str] | None = None, timeout: float = 120
) -> dict:
    with _http_errors(url), _open(url, payload, headers, timeout) as response:
        return json.load(response)


def _lines(url: str, payload: dict, headers: dict[str, str] | None = None, timeout: float = 120) -> Iterator[str]:
    """Non-empty lines of a streamed (NDJSON or server-sent events) response."""
    with _http_errors(url), _open(url, payload, headers, timeout) as response:
        for raw in response:
            if line := raw.decode(errors="replace").strip():
                yield line


async def _call(*args, **kwargs) -> dict:
    return await asyncio.to_thread(_request, *args, **kwargs)


_DONE = object()


async def _stream(url: str, payload: dict, headers: dict[str, str] | None = None, timeout: float = 120):
    """Read ``_lines`` on a worker thread so the UI stays responsive; stopping the consumer stops reading."""
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()
    stop = threading.Event()

    def put(item) -> None:
        try:
            loop.call_soon_threadsafe(queue.put_nowait, item)
        except RuntimeError:  # event loop already closed
            pass

    def read() -> None:
        try:
            for line in _lines(url, payload, headers, timeout):
                if stop.is_set():
                    return
                put(line)
            put(_DONE)
        except Exception as exc:
            put(exc if isinstance(exc, RuntimeError) else RuntimeError("AI stream failed"))

    threading.Thread(target=read, daemon=True).start()
    try:
        while (item := await queue.get()) is not _DONE:
            if isinstance(item, Exception):
                raise item
            yield item
    finally:
        stop.set()


class _Provider:
    """Shared behaviour: ``complete`` collects ``stream``; health is a model listing."""

    async def stream(self, prompt: AIRequest) -> AsyncIterator[str]:
        raise NotImplementedError
        yield ""

    async def complete(self, prompt: AIRequest) -> str:
        answer = _clean("".join([chunk async for chunk in self.stream(prompt)]))
        if not answer:
            raise RuntimeError("AI provider returned no answer")
        return answer

    async def models(self) -> list[str]:
        return []

    async def preparing_note(self) -> str:
        """Optional hint about a slow start (e.g. a model loading into memory); never raises."""
        return ""

    async def health_check(self) -> str:
        models = await self.models()
        return f"Connected · {len(models)} model(s) available"


class Disabled(_Provider):
    async def stream(self, prompt: AIRequest) -> AsyncIterator[str]:
        raise RuntimeError("AI is off")
        yield ""

    async def health_check(self) -> str:
        return "AI is off"


class FakeAIProvider(_Provider):
    """Deterministic test double; never makes network requests."""

    def __init__(self, answer: str = "Check your assumptions.") -> None:
        self.answer = answer
        self.requests: list[AIRequest] = []

    async def stream(self, prompt: AIRequest) -> AsyncIterator[str]:
        self.requests.append(prompt)
        middle = len(self.answer) // 2
        yield self.answer[:middle]
        yield self.answer[middle:]

    async def models(self) -> list[str]:
        return ["fake"]


def _chat(prompt: AIRequest) -> list[dict]:
    return [{"role": "system", "content": SYSTEM}, {"role": "user", "content": _user_content(prompt)}]


class Ollama(_Provider):
    def __init__(self, host: str, model: str = "", effort: str = "") -> None:
        if not host.startswith(("http://", "https://")):
            raise RuntimeError("Ollama host must be an http(s) URL")
        _safe_base_url(host)
        self.host, self.model, self.effort = host.rstrip("/"), model, effort
        self.timeout = 300 if is_local_url(host) else 120  # first load of a large local model is slow

    async def models(self) -> list[str]:
        result = await _call(self.host + "/api/tags", timeout=10)
        models = result.get("models") if isinstance(result, dict) else None
        if not isinstance(models, list):
            raise RuntimeError("AI provider returned an unreadable response")
        return [m["name"] for m in models if isinstance(m, dict) and isinstance(m.get("name"), str)]

    async def _model(self) -> str:
        installed = await self.models()
        model = self.model or pick_ollama_model(installed)
        if not model:
            raise RuntimeError("Ollama has no local models installed; run `ollama pull <model>`")
        if is_local_url(self.host) and model.lower().split(":")[0].endswith("-cloud"):
            raise RuntimeError("Ollama cloud models require explicit remote consent; select a local model")
        if model not in installed and f"{model}:latest" not in installed:
            raise RuntimeError(
                f"Model {model} is not installed in Ollama; choose one of {', '.join(installed)} in Settings"
            )
        return model

    async def preparing_note(self) -> str:
        try:
            model = await self._model()
            loaded = await _call(self.host + "/api/ps", timeout=5)
        except RuntimeError:
            return ""
        names = {m.get("name") for m in loaded.get("models", [])} | {m.get("model") for m in loaded.get("models", [])}
        if model in names or f"{model}:latest" in names:
            return ""
        return f"loading {model} into memory; the first request can take a minute or more"

    async def complete(self, prompt: AIRequest) -> str:
        payload = {"model": await self._model(), "stream": False, "messages": _chat(prompt)}
        if self.effort:
            payload["think"] = self.effort
        result = await _call(self.host + "/api/chat", payload, timeout=self.timeout)
        return _clean(result["message"]["content"])

    async def stream(self, prompt: AIRequest) -> AsyncIterator[str]:
        payload = {"model": await self._model(), "stream": True, "messages": _chat(prompt)}
        if self.effort:
            payload["think"] = self.effort
        async for line in _stream(self.host + "/api/chat", payload, timeout=self.timeout):
            event = _json(line)
            if message := _provider_error(event):
                raise RuntimeError(f"Ollama error: {message}")
            if text := (event.get("message") or {}).get("content"):
                yield text


def pick_ollama_model(models: list[str]) -> str:
    chat = [m for m in models if "embed" not in m.lower() and not m.lower().split(":")[0].endswith("-cloud")]
    return (chat or [""])[0]


def _sse_data(line: str) -> dict | None:
    """Parsed ``data:`` payload of a server-sent event line; None for other lines or [DONE]."""
    if not line.startswith("data:"):
        return None
    data = line[5:].strip()
    return None if data == "[DONE]" else _json(data)


class OpenAICompatible(_Provider):
    """Chat Completions API: OpenAI, OpenRouter, Gemini, Groq, Mistral, LM Studio, vLLM and similar."""

    def __init__(
        self,
        base_url: str,
        model: str,
        key: str | None = None,
        headers: dict | None = None,
        effort: str = "",
        effort_style: str = "reasoning_effort",
    ) -> None:
        if not base_url.startswith(("http://", "https://")):
            raise RuntimeError("Base URL must be an http(s) URL")
        _safe_base_url(base_url)
        self.base, self.model, self.effort = base_url.rstrip("/"), model, effort
        self.effort_style = effort_style
        self.headers = {**({"Authorization": f"Bearer {key}"} if key else {}), **(headers or {})}
        self.timeout = 300 if is_local_url(base_url) else 120

    async def models(self) -> list[str]:
        result = await _call(self.base + "/models", headers=self.headers, timeout=15)
        return sorted(m["id"] for m in result.get("data", []) if isinstance(m, dict) and m.get("id"))

    def _payload(self, prompt: AIRequest, stream: bool) -> dict:
        if not self.model:
            raise RuntimeError("Choose a model in Settings")
        payload = {"model": self.model, "messages": _chat(prompt), **({"stream": True} if stream else {})}
        if self.effort:
            if self.effort_style == "openrouter_reasoning":
                payload["reasoning"] = {"effort": self.effort}
            elif self.effort_style == "gemini_thinking":
                config = (
                    {"thinking_budget": {"low": 1024, "medium": 8192, "high": 24576}[self.effort]}
                    if self.model.lower().startswith("gemini-2.5-")
                    else {"thinking_level": self.effort}
                )
                payload["extra_body"] = {"google": {"thinking_config": config}}
            elif self.effort_style == "deepseek_thinking":
                payload["thinking"] = {"type": "enabled"}
                payload["reasoning_effort"] = self.effort
            elif self.effort_style == "reasoning_effort":
                payload["reasoning_effort"] = self.effort
            else:
                raise ValueError("Unsupported thinking control for provider")
        return payload

    async def complete(self, prompt: AIRequest) -> str:
        result = await _call(self.base + "/chat/completions", self._payload(prompt, False), self.headers, self.timeout)
        try:
            return _clean(result["choices"][0]["message"]["content"])
        except (KeyError, IndexError, TypeError, AttributeError):
            raise RuntimeError("AI provider returned no answer") from None

    async def stream(self, prompt: AIRequest) -> AsyncIterator[str]:
        payload = self._payload(prompt, True)
        async for line in _stream(self.base + "/chat/completions", payload, self.headers, self.timeout):
            event = _sse_data(line)
            if event is None:
                continue
            if message := _provider_error(event):
                raise RuntimeError(f"AI provider error: {message}")
            choices = event.get("choices")
            if choices is not None and not isinstance(choices, list):
                raise RuntimeError("AI provider returned an unreadable response")
            for choice in choices or []:
                if not isinstance(choice, dict) or not isinstance(choice.get("delta", {}), dict):
                    raise RuntimeError("AI provider returned an unreadable response")
                text = (choice.get("delta") or {}).get("content")
                if text is not None and not isinstance(text, str):
                    raise RuntimeError("AI provider returned an unreadable response")
                if text:
                    yield text


class Anthropic(_Provider):
    VERSION = "2023-06-01"

    def __init__(self, base_url: str, model: str, key: str, effort: str = "") -> None:
        _safe_base_url(base_url)
        self.base, self.model, self.effort = base_url.rstrip("/"), model, effort
        self.headers = {"x-api-key": key, "anthropic-version": self.VERSION}

    async def models(self) -> list[str]:
        result = await _call(self.base + "/models?limit=100", headers=self.headers, timeout=15)
        return [m["id"] for m in result.get("data", []) if m.get("id")]

    def _payload(self, prompt: AIRequest, stream: bool) -> dict:
        if not self.model:
            raise RuntimeError("Choose a model in Settings")
        return {
            "model": self.model,
            "max_tokens": 2048,
            "system": SYSTEM,
            "messages": [{"role": "user", "content": _user_content(prompt)}],
            **({"thinking": {"type": "adaptive"}, "output_config": {"effort": self.effort}} if self.effort else {}),
            **({"stream": True} if stream else {}),
        }

    async def complete(self, prompt: AIRequest) -> str:
        result = await _call(self.base + "/messages", self._payload(prompt, False), self.headers)
        return _clean("".join(b.get("text", "") for b in result.get("content", []) if b.get("type") == "text"))

    async def stream(self, prompt: AIRequest) -> AsyncIterator[str]:
        async for line in _stream(self.base + "/messages", self._payload(prompt, True), self.headers):
            event = _sse_data(line)
            if event is None:
                continue
            if message := _provider_error(event):
                raise RuntimeError(f"Anthropic error: {message}")
            delta = event.get("delta") or {}
            if not isinstance(delta, dict):
                raise RuntimeError("AI provider returned an unreadable response")
            if event.get("type") == "content_block_delta" and delta.get("type") == "text_delta":
                text = delta.get("text", "")
                if not isinstance(text, str):
                    raise RuntimeError("AI provider returned an unreadable response")
                yield text


class SubscriptionCLI(_Provider):
    """Runs the user's own, officially installed and signed-in vendor CLI in a throwaway directory.

    ThinkTUI never reads the CLI's credential files; sign-in happens in the vendor's own login command.
    """

    name = ""
    binary_name = ""
    install_hint = ""
    drop_env: frozenset[str] = frozenset()

    def __init__(self, model: str = "", binary: str | None = None, effort: str = "") -> None:
        self.model, self.effort = model, effort
        self.binary = binary or shutil.which(self.binary_name)
        self.returncode: int | None = None

    def require_binary(self) -> str:
        if not self.binary:
            raise RuntimeError(f"{self.name} CLI not found. {self.install_hint}")
        return self.binary

    def environment(self) -> dict[str, str]:
        # Drop API credentials so the CLI uses the subscription login rather than billing an API key.
        allowed = {
            "HOME",
            "USER",
            "LOGNAME",
            "PATH",
            "SHELL",
            "LANG",
            "LC_ALL",
            "TERM",
            "TMPDIR",
            "APPDATA",
            "USERPROFILE",
            "SYSTEMROOT",
            "XDG_CONFIG_HOME",
            "XDG_DATA_HOME",
            "XDG_CACHE_HOME",
            "SSL_CERT_FILE",
            "SSL_CERT_DIR",
        }
        return {k: v for k, v in os.environ.items() if k in allowed and k not in self.drop_env}

    def login_command(self) -> list[str]:
        raise NotImplementedError

    async def _spawn(self, args: list[str], cwd: str, merge_stderr: bool = False):
        try:
            return await asyncio.create_subprocess_exec(
                *args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT if merge_stderr else asyncio.subprocess.DEVNULL,
                cwd=cwd,
                env=self.environment(),
                limit=2**24,  # stream-json lines can be large
                start_new_session=os.name == "posix",
            )
        except OSError:
            raise RuntimeError(f"Could not start the {self.name} CLI") from None

    async def _stop(self, proc) -> None:
        if proc.returncode is None:
            try:
                if hasattr(os, "killpg"):
                    os.killpg(proc.pid, signal.SIGKILL)
                else:
                    proc.kill()
            except (ProcessLookupError, PermissionError):
                if proc.returncode is None:
                    proc.kill()
            await proc.wait()

    async def _run(
        self, args: list[str], stdin: str = "", timeout: float = 300, merge_stderr: bool = False
    ) -> tuple[int, str]:
        with tempfile.TemporaryDirectory(prefix="thinktui-") as cwd:  # no project files visible to the CLI
            proc = await self._spawn(args, cwd, merge_stderr)
            try:
                out, _ = await asyncio.wait_for(proc.communicate(stdin.encode()), timeout)
            except TimeoutError:
                await self._stop(proc)
                raise RuntimeError(f"{self.name} CLI timed out") from None
            except (OSError, ValueError):
                await self._stop(proc)
                raise RuntimeError(f"{self.name} CLI returned an unreadable response") from None
            except asyncio.CancelledError:
                await self._stop(proc)
                raise
        return proc.returncode or 0, out.decode(errors="replace")

    async def _events(self, args: list[str], stdin: str, timeout: float = 300) -> AsyncIterator[dict]:
        """JSON events from the CLI's stdout as they arrive; the process is killed if the consumer stops."""
        with tempfile.TemporaryDirectory(prefix="thinktui-") as cwd:
            proc = await self._spawn(args, cwd)
            try:
                assert proc.stdin and proc.stdout
                async with asyncio.timeout(timeout):
                    if stdin:
                        proc.stdin.write(stdin.encode())
                        await proc.stdin.drain()
                    proc.stdin.close()
                    async for raw in proc.stdout:
                        if event := _json(raw.decode(errors="replace")):
                            yield event
                    await proc.wait()
            except TimeoutError:
                raise RuntimeError(f"{self.name} CLI timed out") from None
            except (OSError, ValueError):
                raise RuntimeError(f"{self.name} CLI returned an unreadable response") from None
            finally:
                await self._stop(proc)
                self.returncode = proc.returncode

    def _failed(self, detail: str = "") -> RuntimeError:
        detail = f": {detail[:200]}" if detail else ""
        return RuntimeError(f"{self.name} CLI failed{detail}. Use Sign in under Settings to check your login")


class ClaudeCodeCLI(SubscriptionCLI):
    """Claude Pro/Max subscription via Claude Code's documented print mode."""

    name = "Claude Code"
    binary_name = "claude"
    install_hint = "Install Claude Code, then use Sign in under Settings"
    drop_env = frozenset({"ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"})
    MODELS = ["sonnet", "opus", "haiku", "fable"]

    def command(self, stream: bool = False) -> list[str]:
        output = ["stream-json", "--verbose", "--include-partial-messages"] if stream else ["json"]
        args = [self.require_binary(), "-p", "--output-format", *output, "--no-session-persistence"]
        args += ["--tools", "", "--strict-mcp-config", "--system-prompt", SYSTEM]
        return (
            args
            + ([f"--model={self.model}"] if self.model else [])
            + (["--effort", self.effort] if self.effort else [])
        )

    def login_command(self) -> list[str]:
        return [self.require_binary(), "auth", "login", "--claudeai"]

    async def complete(self, prompt: AIRequest) -> str:
        code, out = await self._run(self.command(), _user_content(prompt))
        data = _json(out)
        result = str(data.get("result") or "")
        if code or data.get("is_error") or not result:
            raise self._failed(result)
        return _clean(result)

    async def stream(self, prompt: AIRequest) -> AsyncIterator[str]:
        streamed, final = False, None
        async for event in self._events(self.command(stream=True), _user_content(prompt)):
            inner = event.get("event") or {}
            delta = inner.get("delta") or {}
            if event.get("type") == "stream_event" and delta.get("type") == "text_delta":
                streamed = True
                yield delta.get("text", "")
            elif event.get("type") == "result":
                final = event
        result = str((final or {}).get("result") or "")
        if final is None or final.get("is_error") or (self.returncode and not streamed):
            raise self._failed(result)
        if not streamed and result:
            yield result

    async def models(self) -> list[str]:
        return list(self.MODELS)

    async def health_check(self) -> str:
        code, out = await self._run([self.require_binary(), "auth", "status"], timeout=20)
        status = _json(out)
        if code or not status.get("loggedIn"):
            raise RuntimeError("Not signed in to Claude. Use Sign in")
        method = "Claude subscription" if status.get("authMethod") == "claude.ai" else status.get("authMethod")
        return f"Signed in to Claude Code ({method})"


class CursorCLI(SubscriptionCLI):
    """Cursor account via the official Agent CLI in read-only Ask mode.

    Ask mode prevents edits, but the vendor CLI may use read/network tools. The CLI is
    run outside the project; no project files are supplied as workspace context.
    """

    name = "Cursor Agent"
    binary_name = "agent"
    install_hint = "Install Cursor CLI from https://cursor.com/docs/cli/installation, then use Sign in under Settings"
    drop_env = frozenset({"CURSOR_API_KEY"})

    def command(self, prompt: AIRequest) -> list[str]:
        args = [
            self.require_binary(),
            "--print",
            "--trust",  # only the empty temporary workspace is trusted
            "--mode",
            "ask",
            "--output-format",
            "stream-json",
            "--stream-partial-output",
        ]
        if self.model:
            args += ["--model", self.model]
        # Cursor documents a positional prompt for print mode (not stdin).
        return args + [f"{SYSTEM}\nAnswer directly; do not use tools or read files.\n\n{_user_content(prompt)}"]

    def login_command(self) -> list[str]:
        return [self.require_binary(), "login"]

    async def stream(self, prompt: AIRequest) -> AsyncIterator[str]:
        chunks = 0
        final = None
        async for event in self._events(self.command(prompt), ""):
            if event.get("type") == "assistant" and "timestamp_ms" in event and "model_call_id" not in event:
                message = event.get("message") or {}
                content = message.get("content") if isinstance(message, dict) else None
                if isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict) and isinstance(block.get("text"), str) and block["text"]:
                            chunks += 1
                            yield block["text"]
            elif event.get("type") == "result":
                final = event
        if self.returncode or final is None or final.get("is_error"):
            raise self._failed()
        if not chunks:
            text = final.get("result")
            if not isinstance(text, str) or not text:
                raise self._failed()
            yield text

    async def models(self) -> list[str]:
        code, out = await self._run([self.require_binary(), "models"], timeout=30)
        if code:
            raise self._failed()
        # `agent models` prints model names, one per line; never return status text as a model.
        return [line.strip() for line in out.splitlines() if line.strip()]

    async def health_check(self) -> str:
        code, out = await self._run([self.require_binary(), "status", "--format", "json"], timeout=20)
        status = _json(out)
        if code or not any(status.get(field) is True for field in ("authenticated", "isAuthenticated", "loggedIn")):
            raise RuntimeError("Not signed in to Cursor. Use Sign in")
        return "Signed in to Cursor Agent"


class CodexCLI(SubscriptionCLI):
    """ChatGPT plan access via OpenAI's Codex CLI (`codex login` uses the official Sign in with ChatGPT flow)."""

    name = "Codex"
    binary_name = "codex"
    install_hint = "Install it with `npm install -g @openai/codex`, then use Sign in under Settings"
    drop_env = frozenset({"OPENAI_API_KEY", "CODEX_API_KEY"})

    def command(self) -> list[str]:
        args = [self.require_binary(), "exec", "--json", "--skip-git-repo-check", "--ephemeral"]
        args += ["--sandbox", "read-only", "--ignore-user-config", "--ignore-rules", "--color", "never"]
        return (
            args
            + ([f"--model={self.model}"] if self.model else [])
            + (["-c", f'model_reasoning_effort="{self.effort}"'] if self.effort else [])
            + ["-"]
        )

    def login_command(self) -> list[str]:
        return [self.require_binary(), "login"]

    @staticmethod
    def instructions(prompt: AIRequest) -> str:
        return f"{SYSTEM}\nAnswer directly in text; do not run commands, read files or use tools.\n\n{_user_content(prompt)}"

    async def stream(self, prompt: AIRequest) -> AsyncIterator[str]:
        # Codex reports whole messages rather than tokens, so each agent message arrives as one chunk.
        messages = 0
        async for event in self._events(self.command(), self.instructions(prompt)):
            kind, item = event.get("type"), event.get("item") or {}
            if kind == "item.completed" and item.get("type") == "agent_message" and item.get("text"):
                yield ("\n\n" if messages else "") + item["text"]
                messages += 1
            elif kind in {"error", "turn.failed"}:
                raise self._failed(_provider_error(event) or str(event.get("message") or ""))
        if not messages:
            raise self._failed()

    async def models(self) -> list[str]:
        code, out = await self._run([self.require_binary(), "debug", "models"], timeout=30)
        catalog = _json(out).get("models") if not code else None
        return [m["slug"] for m in catalog or [] if isinstance(m, dict) and m.get("slug")]

    async def health_check(self) -> str:
        # `codex login status` reports on stderr.
        code, out = await self._run([self.require_binary(), "login", "status"], timeout=20, merge_stderr=True)
        if code or "logged in" not in out.lower():
            raise RuntimeError("Not signed in to ChatGPT. Use Sign in")
        return out.strip().splitlines()[0] if out.strip() else "Signed in"


def status_label(store) -> str:
    choice = selected_provider(store)
    if choice == "off":
        return "Off"
    if choice == "auto":
        return "Auto (local Ollama when running)"
    return describe(config_for(store, choice))


def create(config: ProviderConfig, key: str | None = None) -> AIProvider:
    """Build a provider; ``key`` overrides stored credentials (used to test a key before saving)."""
    preset = config.preset
    if config.effort not in effort_levels(preset.id, config.model):
        raise ValueError("Unsupported thinking level for provider model; use Provider default")
    if preset.kind == "off":
        return Disabled()
    if preset.kind == "ollama":
        return Ollama(config.base_url or preset.base_url, config.model, config.effort)
    if preset.kind == "claude_cli":
        return ClaudeCodeCLI(config.model, effort=config.effort)
    if preset.kind == "codex_cli":
        return CodexCLI(config.model, effort=config.effort)
    if preset.kind == "cursor_cli":
        return CursorCLI(config.model)
    key = key or credentials.get_key(preset.id, preset.key_env)[0]
    if preset.key_required and not key:
        hint = f" or set {preset.key_env}" if preset.key_env else ""
        raise RuntimeError(f"No API key for {preset.label}. Add one in Settings{hint}")
    if not config.base_url:
        raise RuntimeError(f"Set a base URL for {preset.label} in Settings")
    if preset.kind == "anthropic":
        return Anthropic(config.base_url, config.model, key or "", config.effort)
    headers = {"X-Title": "ThinkTUI"} if preset.id == "openrouter" else None
    style = EFFORT_STYLES.get(preset.id, "")
    return OpenAICompatible(config.base_url, config.model, key, headers, config.effort, style)


async def detect_ollama(base_url: str = "http://localhost:11434") -> list[str] | None:
    """Installed model names when an Ollama server answers quickly, else None."""
    try:
        result = await _call(base_url.rstrip("/") + "/api/tags", timeout=1.5)
    except RuntimeError:
        return None
    models = result.get("models") if isinstance(result, dict) else None
    if not isinstance(models, list):
        return None
    return [m["name"] for m in models if isinstance(m, dict) and isinstance(m.get("name"), str)]


async def resolve(store) -> ProviderConfig:
    """Concrete provider configuration; 'auto' means local Ollama when reachable."""
    choice = selected_provider(store)
    if choice == "off":
        raise RuntimeError("AI is off; choose a provider in Settings")
    if choice != "auto":
        return config_for(store, choice)
    config = config_for(store, "ollama")
    models = await detect_ollama(config.base_url)
    if not models:
        raise RuntimeError("No AI available: start Ollama (with a pulled model) or choose a provider in Settings")
    installed = {name.removesuffix(":latest"): name for name in models}
    model = installed.get(config.model.removesuffix(":latest")) or pick_ollama_model(models)
    if not model or model.lower().split(":")[0].endswith("-cloud"):
        raise RuntimeError("No local Ollama chat model available; cloud models require explicit remote consent")
    return ProviderConfig("ollama", config.base_url, model, config.effort)


async def connect(store) -> tuple[AIProvider, ProviderConfig]:
    config = await resolve(store)
    return create(config), config
