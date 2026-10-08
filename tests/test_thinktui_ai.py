"""AI provider registry, credentials and settings; all endpoints are faked."""

import asyncio
import io
import json
import stat
from contextlib import nullcontext
from urllib import error

import pytest
from textual.widgets import Input, Select, Static

from thinktui import ai, credentials, screens
from thinktui.ai import (
    AIRequest,
    ClaudeCodeCLI,
    CodexCLI,
    ProviderConfig,
    config_for,
    create,
    parse_json_object,
    resolve,
    visible_text,
)
from thinktui.app import ThinkApp
from thinktui.core import Session
from thinktui.screens import Settings, Workspace
from thinktui.storage import Store


def fake_endpoint(monkeypatch, replies, streams=None):
    """Route ai._request (whole JSON) and ai._lines (streamed lines) by URL suffix; record every call."""
    calls = []

    def route(table, url, payload, headers):
        calls.append({"url": url, "payload": payload, "headers": headers or {}})
        for suffix, reply in table.items():
            if url.split("?")[0].endswith(suffix):
                return reply
        raise RuntimeError("Could not reach AI provider")

    def handler(url, payload=None, headers=None, timeout=120):
        return route(replies, url, payload, headers)

    def lines(url, payload, headers=None, timeout=120):
        yield from route(streams or {}, url, payload, headers)

    monkeypatch.setattr(ai, "_request", handler)
    monkeypatch.setattr(ai, "_lines", lines)
    return calls


REAL_REQUEST = ai._request  # captured before the autouse fixture disables the network
OLLAMA_TAGS = {"models": [{"name": "nomic-embed-text:latest"}, {"name": "qwen3:8b"}]}


def test_key_precedence_and_storage(isolated_ai, monkeypatch):
    assert credentials.get_key("openrouter", "OPENROUTER_API_KEY") == (None, "none")
    monkeypatch.setenv("OPENROUTER_API_KEY", "env-key")
    assert credentials.get_key("openrouter", "OPENROUTER_API_KEY") == ("env-key", "$OPENROUTER_API_KEY")
    assert credentials.set_key("openrouter", " ring-key ") == "keyring"
    assert isolated_ai.secrets[("thinktui", "openrouter")] == "ring-key"
    assert credentials.get_key("openrouter", "OPENROUTER_API_KEY") == ("ring-key", "keyring")
    assert credentials.set_key("openrouter", "temp", remember=False) == "session"
    assert credentials.get_key("openrouter")[0] == "temp"
    credentials.forget_key("openrouter")
    assert credentials.get_key("openrouter", "OPENROUTER_API_KEY")[1] == "$OPENROUTER_API_KEY"
    with pytest.raises(ValueError):
        credentials.set_key("openrouter", "   ")


def test_keys_fall_back_to_session_without_keyring(monkeypatch):
    monkeypatch.setattr(credentials, "_backend", lambda: None)
    assert credentials.set_key("openai", "k") == "session"
    assert credentials.get_key("openai") == ("k", "session")


def test_settings_validation_and_legacy_fallback(tmp_path):
    store = Store(tmp_path / "db.sqlite")
    store.set_setting("ai_provider", "openrouter")
    store.set_setting("ai.openrouter.model", "anthropic/claude-sonnet-4")
    store.set_setting("ai.custom.base_url", "https://llm.example.com/v1")
    for key, value in [
        ("ai.openrouter.api_key", "sk-secret"),
        ("ai.unknown.model", "x"),
        ("ai_provider", "chatgpt-web"),
        ("ai.custom.base_url", "file:///etc/passwd"),
    ]:
        with pytest.raises(ValueError):
            store.set_setting(key, value)
    store.set_setting("ollama_host", "http://gpu-box:11434")
    store.set_setting("ollama_model", "llama3")
    assert config_for(store, "ollama") == ProviderConfig("ollama", "http://gpu-box:11434", "llama3")
    assert config_for(store, "openrouter").model == "anthropic/claude-sonnet-4"
    assert config_for(store, "anthropic").base_url == "https://api.anthropic.com/v1"
    store.close()


@pytest.mark.asyncio
async def test_auto_uses_local_ollama_and_first_chat_model(tmp_path, monkeypatch):
    store = Store(tmp_path / "db.sqlite")
    with pytest.raises(RuntimeError, match="start Ollama"):
        await resolve(store)
    calls = fake_endpoint(
        monkeypatch, {"/api/tags": OLLAMA_TAGS, "/api/chat": {"message": {"content": "<think>x</think>Hi"}}}
    )
    config = await resolve(store)
    assert config == ProviderConfig("ollama", "http://localhost:11434", "qwen3:8b")
    assert ai.is_local(config)
    assert await create(config).complete(AIRequest("q", {"problem": "p"})) == "Hi"
    assert calls[-1]["payload"]["model"] == "qwen3:8b"
    store.set_setting("ai_provider", "off")
    with pytest.raises(RuntimeError, match="AI is off"):
        await resolve(store)
    store.close()


@pytest.mark.asyncio
async def test_openai_compatible_and_anthropic_requests(isolated_ai, monkeypatch):
    calls = fake_endpoint(
        monkeypatch,
        {
            "/chat/completions": {"choices": [{"message": {"content": "Consider X"}}]},
            "/messages": {"content": [{"type": "text", "text": "Consider Y"}]},
            "/models": {"data": [{"id": "b"}, {"id": "a"}]},
        },
    )
    with pytest.raises(RuntimeError, match="OPENROUTER_API_KEY") as excinfo:
        create(ProviderConfig("openrouter", "https://openrouter.ai/api/v1", "openrouter/auto"))
    credentials.set_key("openrouter", "sk-or-1")
    router = create(ProviderConfig("openrouter", "https://openrouter.ai/api/v1", "openrouter/auto"))
    assert await router.complete(AIRequest("challenge", {"problem": "p"})) == "Consider X"
    assert calls[-1]["url"] == "https://openrouter.ai/api/v1/chat/completions"
    assert calls[-1]["headers"]["Authorization"] == "Bearer sk-or-1"
    assert calls[-1]["payload"]["messages"][0]["role"] == "system"
    assert await router.models() == ["a", "b"]
    claude = create(ProviderConfig("anthropic", "https://api.anthropic.com/v1", "claude-sonnet-5-5"), key="sk-ant")
    assert await claude.complete(AIRequest("challenge", {})) == "Consider Y"
    assert calls[-1]["headers"]["x-api-key"] == "sk-ant"
    assert calls[-1]["payload"]["system"] == ai.SYSTEM
    local = create(ProviderConfig("lmstudio", "http://localhost:1234/v1", "m"))
    await local.complete(AIRequest("q", {}))
    assert "Authorization" not in calls[-1]["headers"]
    assert "sk-" not in str(excinfo.value)


def test_http_errors_never_echo_secrets(monkeypatch):
    def refuse(req, timeout):
        raise error.HTTPError(req.full_url, 401, "Unauthorized", {}, io.BytesIO(b"bad key sk-123"))

    monkeypatch.setattr(ai.request, "urlopen", refuse)
    with pytest.raises(RuntimeError) as excinfo:
        REAL_REQUEST("https://api.example.com/v1/x?key=sk-123", {}, {"Authorization": "Bearer sk-123"})
    assert "HTTP 401" in str(excinfo.value) and "API key" in str(excinfo.value)
    assert "sk-123" not in str(excinfo.value)


def test_parse_json_object_tolerates_fences():
    assert parse_json_object('```json\n{"statement": "A"}\n```')["statement"] == "A"
    with pytest.raises(ValueError):
        parse_json_object("no json here")


def fake_cli(tmp_path, name: str, body: str):
    script = tmp_path / name
    script.write_text(f"#!/bin/sh\n{body}\n")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return str(script)


def fake_claude(tmp_path, body: str):
    script = tmp_path / "claude"
    script.write_text(f"#!/bin/sh\n{body}\n")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return str(script)


@pytest.mark.asyncio
async def test_claude_subscription_cli(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-api")
    log = tmp_path / "args.txt"
    binary = fake_claude(
        tmp_path,
        f'printf "%s|" "$@" > {log}; echo "key=$ANTHROPIC_API_KEY" >> {log}; cat >> {log}; '
        'echo \'{"type":"result","is_error":false,"result":"Question the vendor timeline"}\'',
    )
    provider = ClaudeCodeCLI("opus", binary)
    answer = await provider.complete(AIRequest("challenge", {"problem": "migrate"}))
    assert answer == "Question the vendor timeline"
    recorded = log.read_text()
    assert "-p|--output-format|json|" in recorded and "--tools||" in recorded and "--model|opus|" in recorded
    assert "key=\n" in recorded  # API key stripped so the subscription login is used
    assert '"problem": "migrate"' in recorded  # context sent on stdin, not argv
    failing = ClaudeCodeCLI("", fake_claude(tmp_path, 'echo \'{"is_error":true,"result":"Not logged in"}\'; exit 1'))
    with pytest.raises(RuntimeError, match="Not logged in"):
        await failing.complete(AIRequest("q", {}))
    monkeypatch.setattr(ai.shutil, "which", lambda _name: None)
    with pytest.raises(RuntimeError, match="not found"):
        await ClaudeCodeCLI("").complete(AIRequest("q", {}))


@pytest.mark.asyncio
async def test_settings_screen_saves_provider_and_key_outside_database(tmp_path, isolated_ai, monkeypatch):
    fake_endpoint(monkeypatch, {"/models": {"data": [{"id": "anthropic/claude-sonnet-4"}, {"id": "openai/gpt-4o"}]}})
    store = Store(tmp_path / "settings.db")
    app = ThinkApp(store=store, initial="settings")
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, Settings)
        assert screen.query_one("#provider", Select).value == "auto"
        screen.query_one("#provider", Select).value = "openrouter"
        await pilot.pause()
        assert screen.query_one("#base-url", Input).value == "https://openrouter.ai/api/v1"
        assert screen.query_one("#key-box").display
        assert "not set" in str(screen.query_one("#key-status", Static).render())
        screen.query_one("#api-key", Input).value = "sk-or-secret"
        screen.action_refresh_models()
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert "2 model(s)" in str(screen.query_one("#models-status", Static).render())
        screen.query_one("#models", Select).value = "openai/gpt-4o"
        await pilot.pause()
        assert screen.query_one("#model", Input).value == "openai/gpt-4o"
        screen.query_one("#consent", Select).value = "yes"
        await pilot.press("ctrl+s")
        await pilot.pause()
    assert store.setting("ai_provider") == "openrouter"
    assert store.setting("ai.openrouter.model") == "openai/gpt-4o"
    assert isolated_ai.secrets[("thinktui", "openrouter")] == "sk-or-secret"
    store.close()
    assert b"sk-or-secret" not in (tmp_path / "settings.db").read_bytes()


@pytest.mark.asyncio
async def test_challenge_works_with_local_ollama_without_consent(tmp_path, monkeypatch):
    calls = fake_endpoint(
        monkeypatch,
        {"/api/tags": OLLAMA_TAGS},
        {"/api/chat": [json.dumps({"message": {"content": c}}) for c in ("What if ", "demand is lower?")]},
    )
    store = Store(tmp_path / "ws.db")
    session = Session(store.new_project("Decision"), "premortem", "Launch", notes="private notes")
    store.save(session, "Created")
    app = ThinkApp(store=store)
    async with app.run_test() as pilot:
        app.open_session(session)
        await pilot.pause()
        assert isinstance(app.screen, Workspace)
        await pilot.press("ctrl+k")
        await app.workers.wait_for_complete()
        await pilot.pause()
        text = str(app.screen.query_one("#ai-response", Static).render())
        assert "What if demand is lower?" in text
        assert "✓ Answer received from Ollama / Local · qwen3:8b" in str(
            app.screen.query_one("#ai-status", Static).render()
        )
    chat = [c for c in calls if c["url"].endswith("/api/chat")][0]
    assert "private notes" not in json.dumps(chat["payload"])
    assert session.method_state == store.load(session.id).method_state
    store.close()


@pytest.mark.asyncio
async def test_remote_provider_requires_consent(tmp_path, monkeypatch):
    calls = fake_endpoint(monkeypatch, {})
    credentials.set_key("openai", "sk-test")
    store = Store(tmp_path / "ws.db")
    store.set_setting("ai_provider", "openai")
    session = Session(store.new_project("Decision"), "premortem", "Launch")
    store.save(session, "Created")
    app = ThinkApp(store=store)
    async with app.run_test() as pilot:
        app.open_session(session)
        await pilot.pause()
        await pilot.press("ctrl+k")
        await app.workers.wait_for_complete()
        await pilot.pause()
    assert calls == []
    store.close()


PROMPT = AIRequest("q", {"problem": "p"})


async def collect(provider, prompt=PROMPT):
    return [chunk async for chunk in provider.stream(prompt)]


@pytest.mark.asyncio
async def test_http_streaming_for_each_api_format(isolated_ai, monkeypatch):
    calls = fake_endpoint(
        monkeypatch,
        {"/api/tags": OLLAMA_TAGS},
        {
            "/api/chat": [
                '{"message":{"content":"<think>hm"}}',
                '{"message":{"content":"</think>A"}}',
                '{"done":true}',
            ],
            "/chat/completions": [
                ": keep-alive",
                'data: {"choices":[{"delta":{"role":"assistant"}}]}',
                'data: {"choices":[{"delta":{"content":"B1"}}]}',
                'data: {"choices":[{"delta":{"content":"B2"}}]}',
                "data: [DONE]",
            ],
            "/messages": [
                "event: message_start",
                'data: {"type":"message_start","message":{}}',
                'data: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"C1"}}',
                'data: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"C2"}}',
                'data: {"type":"message_stop"}',
            ],
        },
    )
    ollama = create(ProviderConfig("ollama", "http://localhost:11434", ""))
    assert visible_text("".join(await collect(ollama))) == "A"
    assert calls[-1]["payload"]["stream"] is True and calls[-1]["payload"]["model"] == "qwen3:8b"
    router = create(ProviderConfig("openrouter", "https://openrouter.ai/api/v1", "m"), key="k")
    assert await collect(router) == ["B1", "B2"]
    claude = create(ProviderConfig("anthropic", "https://api.anthropic.com/v1", "claude-sonnet-5-5"), key="k")
    assert await collect(claude) == ["C1", "C2"]
    assert calls[-1]["payload"]["stream"] is True


@pytest.mark.asyncio
async def test_stream_errors_and_thread_bridge(monkeypatch):
    fake_endpoint(
        monkeypatch,
        {},
        {
            "/chat/completions": [
                'data: {"choices":[{"delta":{"content":"x"}}]}',
                'data: {"error":{"message":"quota exceeded"}}',
            ]
        },
    )
    provider = create(ProviderConfig("lmstudio", "http://localhost:1234/v1", "m"))
    chunks = []
    with pytest.raises(RuntimeError, match="quota exceeded"):
        async for chunk in provider.stream(AIRequest("q", {})):
            chunks.append(chunk)
    assert chunks == ["x"]

    def broken(*_args, **_kwargs):
        yield "data: first"
        raise RuntimeError("Could not reach AI provider at example")

    monkeypatch.setattr(ai, "_lines", broken)
    received = []
    with pytest.raises(RuntimeError, match="Could not reach"):
        async for line in ai._stream("https://example/v1", {}):
            received.append(line)
    assert received == ["data: first"]


def test_visible_text_hides_unfinished_reasoning():
    assert visible_text("<think>a</think>Answer <think>still going") == "Answer "
    assert visible_text("plain") == "plain"


@pytest.mark.asyncio
async def test_claude_cli_streams_text_deltas(tmp_path):
    events = [
        {"type": "system", "subtype": "init"},
        {
            "type": "stream_event",
            "event": {"type": "content_block_delta", "delta": {"type": "thinking_delta", "thinking": "secret"}},
        },
        {
            "type": "stream_event",
            "event": {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "Hello "}},
        },
        {
            "type": "stream_event",
            "event": {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "world"}},
        },
        {"type": "result", "is_error": False, "result": "Hello world"},
    ]
    log = tmp_path / "args.txt"
    body = f'printf "%s|" "$@" > {log}; cat > /dev/null; ' + "; ".join(f"echo '{json.dumps(e)}'" for e in events)
    provider = ClaudeCodeCLI("haiku", fake_cli(tmp_path, "claude", body))
    assert await collect(provider) == ["Hello ", "world"]
    assert "--output-format|stream-json|--verbose|--include-partial-messages|" in log.read_text()
    assert provider.login_command()[1:] == ["auth", "login", "--claudeai"]
    status = ClaudeCodeCLI(
        "", fake_cli(tmp_path, "claude2", """echo '{"loggedIn": true, "authMethod": "claude.ai"}'""")
    )
    assert "Claude subscription" in await status.health_check()
    signed_out = ClaudeCodeCLI("", fake_cli(tmp_path, "claude3", """echo '{"loggedIn": false}'; exit 1"""))
    with pytest.raises(RuntimeError, match="Not signed in"):
        await signed_out.health_check()


@pytest.mark.asyncio
async def test_chatgpt_subscription_via_codex(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai")
    log = tmp_path / "codex.txt"
    events = [
        {"type": "thread.started", "thread_id": "t"},
        {"type": "item.completed", "item": {"type": "reasoning", "text": "hidden"}},
        {"type": "item.completed", "item": {"type": "agent_message", "text": "Test the churn assumption."}},
        {"type": "turn.completed", "usage": {}},
    ]
    script = (
        f'case "$1 $2" in "login status") echo "Logged in using ChatGPT";; '
        f"\"debug models\") echo '{json.dumps({'models': [{'slug': 'gpt-a'}, {'slug': 'gpt-b'}]})}';; "
        f'*) printf "%s|" "$@" > {log}; echo "key=$OPENAI_API_KEY" >> {log}; cat >> {log}; '
        + "; ".join(f"echo '{json.dumps(e)}'" for e in events)
        + ";; esac"
    )
    binary = fake_cli(tmp_path, "codex", script)
    monkeypatch.setattr(ai.shutil, "which", lambda name: binary if name == "codex" else None)
    provider = create(ProviderConfig("chatgpt", "", "gpt-b"))
    assert isinstance(provider, CodexCLI)
    assert await provider.complete(AIRequest("challenge", {"problem": "pricing"})) == "Test the churn assumption."
    recorded = log.read_text()
    assert recorded.startswith("exec|--json|--skip-git-repo-check|--ephemeral|--sandbox|read-only|")
    assert "--model|gpt-b|-|" in recorded and "key=\n" in recorded and '"problem": "pricing"' in recorded
    assert await provider.models() == ["gpt-a", "gpt-b"]
    assert await provider.health_check() == "Logged in using ChatGPT"
    assert provider.login_command() == [binary, "login"]
    failing = CodexCLI(
        "",
        fake_cli(
            tmp_path,
            "codex2",
            """cat >/dev/null; echo '{"type":"turn.failed","error":{"message":"usage limit reached"}}'""",
        ),
    )
    with pytest.raises(RuntimeError, match="usage limit reached"):
        await failing.complete(AIRequest("q", {}))


class SlowProvider:
    def __init__(self):
        self.cancelled = False
        self.release = asyncio.Event()

    async def preparing_note(self):
        return "loading m into memory; the first request can take a minute or more"

    async def stream(self, prompt):
        await self.release.wait()  # simulates a cold model before the first token
        yield "Partial thought"
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            self.cancelled = True
            raise
        yield "never"


@pytest.mark.asyncio
async def test_stop_ai_cancels_stream_and_keeps_partial(tmp_path, monkeypatch):
    slow = SlowProvider()

    async def fake_connect(store):
        return slow, ProviderConfig("ollama", "http://localhost:11434", "m")

    monkeypatch.setattr(screens, "connect", fake_connect)
    store = Store(tmp_path / "ws.db")
    session = Session(store.new_project("Decision"), "premortem", "Launch")
    store.save(session, "Created")
    app = ThinkApp(store=store)
    async with app.run_test() as pilot:
        app.open_session(session)
        await pilot.pause()
        await pilot.press("ctrl+k")
        await pilot.pause()
        status = app.screen.query_one("#ai-status", Static)
        assert "loading m into memory" in str(status.render()) and "Ctrl+G stops" in str(status.render())
        assert app.screen.query_one("#challenge").disabled and not app.screen.query_one("#stop-ai").disabled
        status.started -= 20  # pretend the cold load has taken a while
        status.tick()
        assert "still working" in str(status.render()) and "20s" in str(status.render())
        slow.release.set()
        for _ in range(20):
            await pilot.pause()
            if "Partial thought" in str(app.screen.query_one("#ai-response", Static).render()):
                break
        assert "receiving answer · 2 words" in str(status.render())
        assert "streaming" in str(app.screen.query_one("#ai-response", Static).render())
        await pilot.press("ctrl+g")
        await app.workers.wait_for_complete()
        await pilot.pause()
        text = str(app.screen.query_one("#ai-response", Static).render())
        assert "stopped" in str(app.screen.query_one("#ai-status", Static).render())
        assert not app.screen.query_one("#challenge").disabled and app.screen.query_one("#stop-ai").disabled
    assert "Partial thought" in text and "never" not in text
    assert slow.cancelled
    store.close()


@pytest.mark.asyncio
async def test_settings_sign_in_runs_vendor_login(tmp_path, monkeypatch):
    binary = fake_cli(tmp_path, "codex", 'echo "Logged in using ChatGPT"')
    monkeypatch.setattr(ai.shutil, "which", lambda name: binary if name == "codex" else None)
    ran = []
    monkeypatch.setattr(screens.subprocess, "run", lambda command, **kwargs: ran.append((command, kwargs["env"])))
    store = Store(tmp_path / "settings.db")
    app = ThinkApp(store=store, initial="settings")
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        screen.query_one("#provider", Select).value = "chatgpt"
        await pilot.pause()
        assert screen.query_one("#signin").display and not screen.query_one("#key-box").display
        assert "ChatGPT" in str(screen.query_one("#signin").label)
        await pilot.press("ctrl+l")  # headless terminal cannot suspend: user is told the command instead
        await pilot.pause()
        assert ran == []
        monkeypatch.setattr(type(app), "suspend", lambda self: nullcontext())
        await pilot.press("ctrl+l")
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert ran and ran[0][0] == [binary, "login"] and "OPENAI_API_KEY" not in ran[0][1]
        assert "Logged in using ChatGPT" in str(screen.query_one("#test-result", Static).render())
    store.close()


@pytest.mark.asyncio
async def test_ollama_reports_cold_model_load(monkeypatch):
    replies = {"/api/tags": OLLAMA_TAGS, "/api/ps": {"models": []}}
    fake_endpoint(monkeypatch, replies)
    ollama = create(ProviderConfig("ollama", "http://localhost:11434", "qwen3:8b"))
    assert "loading qwen3:8b into memory" in await ollama.preparing_note()
    replies["/api/ps"] = {"models": [{"name": "qwen3:8b", "model": "qwen3:8b"}]}
    assert await ollama.preparing_note() == ""
    fake_endpoint(monkeypatch, {})  # server unreachable: no note, the request itself reports the error
    assert await ollama.preparing_note() == ""
