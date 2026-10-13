"""Actionable, opt-in setup gate shared by AI entry points.

Nothing is sent until destination consent and subscription login are checked. The
vendor's own CLI handles login from Settings; this screen never requests credentials.
"""

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button

from .ai import PRESETS, SubscriptionCLI, remote_consent, selected_provider
from .safe_widgets import Label, Static


class AISetupRequired(Exception):
    def __init__(self, kind: str, provider: str) -> None:
        self.kind = kind
        self.provider = provider
        super().__init__(f"{kind} required for {provider}")


async def require_ai_setup(store, provider, config) -> None:
    """Check prerequisites before any prompt or analysis context reaches the provider."""
    if not remote_consent(store, config):
        raise AISetupRequired("consent", config.preset.label)
    if isinstance(provider, SubscriptionCLI):
        try:
            await provider.health_check()
        except Exception:
            # CLI errors can include credential-bearing output. Never echo it.
            raise AISetupRequired("sign_in", config.preset.label) from None


class AISetupDialog(ModalScreen[None]):
    DEFAULT_CSS = """
    AISetupDialog { align: center middle; background: $background 80%; }
    AISetupDialog .ai-setup-dialog { width: 75%; max-width: 75; height: auto;
        border: round $primary; background: $panel; padding: 2 3; }
    AISetupDialog .actions { height: auto; }
    """
    BINDINGS = [("escape", "close", "Not now")]

    def __init__(self, issue: AISetupRequired) -> None:
        super().__init__()
        self.issue = issue

    def compose(self) -> ComposeResult:
        sign_in = self.issue.kind == "sign_in"
        key = self.issue.kind == "api_key"
        with Vertical(classes="ai-setup-dialog"):
            yield Label(
                "Sign in required" if sign_in else "API key required" if key else "Permission required", classes="hero"
            )
            yield Static(
                (
                    f"{self.issue.provider} is not signed in (or its login could not be checked). "
                    "Open Settings, press Sign in, then Test connection."
                    if sign_in
                    else f"Add or replace the API key for {self.issue.provider} in Settings and Save. "
                    "No usable answer was received."
                    if key
                    else f"Before sharing with {self.issue.provider}, open Settings, set Allow sending content to Yes "
                    "and Save. Nothing was sent."
                ),
                markup=False,
            )
            with Horizontal(classes="actions"):
                yield Button("Not now", id="setup-cancel")
                yield Button("Open Settings", id="setup-settings", variant="primary")

    def on_mount(self) -> None:
        self.query_one("#setup-settings", Button).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "setup-settings":
            from .screens import Settings

            focus = (
                "#signin"
                if self.issue.kind == "sign_in"
                else "#api-key"
                if self.issue.kind == "api_key"
                else "#consent"
            )
            self.dismiss(None)

            def open_settings() -> None:
                self.app.switch_screen(Settings())
                self.app.call_after_refresh(lambda: self.app.screen.query_one(focus).focus())

            self.app.call_after_refresh(open_settings)
        else:
            self.dismiss(None)

    def action_close(self) -> None:
        self.dismiss(None)


def prompt_ai_setup(app, issue: AISetupRequired) -> None:
    app.push_screen(AISetupDialog(issue))


def prompt_missing_key(app, exc: Exception) -> bool:
    """Offer Settings for a missing/rejected API key, without reflecting provider output."""
    choice = selected_provider(app.store)
    preset = PRESETS.get(choice)
    if preset is None or preset.kind not in {"openai", "anthropic"}:
        return False
    # _http_errors emits this fixed text from the status code, never a provider body.
    # A 403 can mean policy, permissions or billing and is not necessarily a bad key.
    missing = str(exc).startswith("No API key for ")
    rejected = str(exc) == "AI request failed (HTTP 401: authentication failed; check the API key)"
    if not isinstance(exc, RuntimeError) or not (missing or rejected):
        return False
    prompt_ai_setup(app, AISetupRequired("api_key", preset.label))
    return True
