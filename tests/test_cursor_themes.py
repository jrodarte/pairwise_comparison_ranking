"""Cursor's official CLI boundary and palette persistence, without external services."""

import json
import stat

import pytest
from textual.widgets import Select

from thinktui import ai
from thinktui.ai import AIRequest, CursorCLI, ProviderConfig, create
from thinktui.app import ThinkApp
from thinktui.screens import Settings
from thinktui.storage import Store
from thinktui.themes import THEMES


def fake_agent(tmp_path, body):
    script = tmp_path / "agent"
    script.write_text("#!/bin/sh\n" + body + "\n")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return str(script)


@pytest.mark.asyncio
async def test_cursor_cli_stream_login_models_and_no_api_key(tmp_path, monkeypatch):
    monkeypatch.setenv("CURSOR_API_KEY", "private-api-key")
    log = tmp_path / "args.txt"
    events = [
        {"type": "assistant", "timestamp_ms": 1, "message": {"content": [{"text": "Check "}]}},
        {"type": "assistant", "timestamp_ms": 2, "message": {"content": [{"text": "assumptions"}]}},
        {"type": "assistant", "message": {"content": [{"text": "Check assumptions"}]}},
        {"type": "result", "result": "Check assumptions"},
    ]
    body = (
        f'printf "%s|" "$@" > {log}; echo "key=$CURSOR_API_KEY" >> {log}; '
        'case "$1" in '
        "status) echo '{\"authenticated\":true}';; "
        'models) printf "auto\\ngpt-5\\n";; '
        "*) " + "; ".join(f"echo '{json.dumps(event)}'" for event in events) + ";; esac"
    )
    binary = fake_agent(tmp_path, body)
    monkeypatch.setattr(ai.shutil, "which", lambda name: binary if name == "agent" else None)
    provider = create(ProviderConfig("cursor", "", "gpt-5"))
    assert isinstance(provider, CursorCLI)
    assert await provider.complete(AIRequest("challenge", {"problem": "pricing"})) == "Check assumptions"
    recorded = log.read_text()
    assert recorded.startswith("--print|--trust|--mode|ask|--output-format|stream-json|--stream-partial-output|")
    assert "--model|gpt-5|" in recorded and '"problem": "pricing"' in recorded
    assert "key=\n" in recorded and "private-api-key" not in recorded
    assert await provider.models() == ["auto", "gpt-5"]
    assert await provider.health_check() == "Signed in to Cursor Agent"
    assert provider.login_command() == [binary, "login"]


@pytest.mark.asyncio
async def test_cursor_cli_no_result_or_signed_out(tmp_path):
    binary = fake_agent(tmp_path, 'echo \'{"type":"result","is_error":true}\'')
    with pytest.raises(RuntimeError, match="CLI failed"):
        await CursorCLI(binary=binary).complete(AIRequest("q", {}))
    binary = fake_agent(tmp_path, "echo '{\"authenticated\":false}'")
    with pytest.raises(RuntimeError, match="Not signed in"):
        await CursorCLI(binary=binary).health_check()


@pytest.mark.asyncio
async def test_cursor_settings_require_consent_and_hide_key(tmp_path):
    store = Store(tmp_path / "cursor.db")
    app = ThinkApp(store=store, initial="settings")
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        screen.query_one("#provider", Select).value = "cursor"
        await pilot.pause()
        assert screen.query_one("#signin").display
        assert not screen.query_one("#key-box").display
        assert not screen.query_one("#url-box").display
        assert "Cursor" in str(screen.query_one("#signin").label)
        screen.query_one("#consent", Select).value = "yes"
        await pilot.press("ctrl+s")
        await pilot.pause()
    assert store.setting("ai_provider") == "cursor"
    assert store.setting("ai.cursor.consent") == "yes"
    store.close()


@pytest.mark.asyncio
async def test_theme_preview_save_restart_and_cancel(tmp_path):
    assert len(THEMES) == 12
    store = Store(tmp_path / "themes.db")
    with pytest.raises(ValueError, match="Unsupported theme"):
        store.set_setting("theme", "unknown")
    app = ThinkApp(store=store, initial="settings")
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.theme == "thinktui"
        original_background = app.screen.styles.background
        for name, palette in THEMES.items():
            app.screen.query_one("#theme", Select).value = name
            await pilot.pause()
            assert app.theme == name
            assert app.screen.styles.background.hex == palette.background.upper()
        app.screen.query_one("#theme", Select).value = "nord"
        await pilot.pause()
        assert app.theme == "nord" and store.setting("theme") == ""
        assert app.screen.styles.background != original_background
        await pilot.press("escape")
        await pilot.pause()
        assert app.theme == "thinktui"
        app.switch_screen(Settings())
        await pilot.pause()
        app.screen.query_one("#theme", Select).value = "catppuccin-latte"
        await pilot.pause()
        await pilot.press("ctrl+s")
        await pilot.pause()
        assert app.theme == "catppuccin-latte"
        assert store.setting("theme") == "catppuccin-latte"
    app = ThinkApp(store=store)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.theme == "catppuccin-latte"
    store.close()
