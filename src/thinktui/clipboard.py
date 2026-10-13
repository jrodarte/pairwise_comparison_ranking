"""Best-effort desktop clipboard bridge; terminal OSC 52 remains the fallback."""

import os
import shutil
import subprocess
import sys


def _command(read: bool) -> list[str] | None:
    if sys.platform == "darwin":
        candidates = [["pbpaste" if read else "pbcopy"]]
    elif sys.platform == "win32":
        # No shell, no command interpolation, and suppress command errors.
        script = (
            "[Console]::OutputEncoding=[Text.Encoding]::UTF8; [Console]::Out.Write((Get-Clipboard -Raw))"
            if read
            else "[Console]::InputEncoding=[Text.Encoding]::UTF8; Set-Clipboard -Value ([Console]::In.ReadToEnd())"
        )
        candidates = [["powershell.exe", "-NoProfile", "-Command", script]]
    elif os.environ.get("WAYLAND_DISPLAY"):
        candidates = [["wl-paste", "--no-newline"] if read else ["wl-copy"]]
    else:
        candidates = []
    if sys.platform.startswith("linux"):
        candidates += [
            ["xclip", "-selection", "clipboard", "-o" if read else "-i"],
            ["xsel", "--clipboard", "--output" if read else "--input"],
        ]
    return next((cmd for cmd in candidates if shutil.which(cmd[0])), None)


def read_clipboard() -> str | None:
    if cmd := _command(True):
        try:
            return subprocess.run(cmd, capture_output=True, timeout=1, check=True).stdout.decode("utf-8")
        except (OSError, subprocess.SubprocessError, UnicodeError):
            pass
    return None


def write_clipboard(text: str) -> None:
    if cmd := _command(False):
        try:
            subprocess.run(cmd, input=text.encode("utf-8"), capture_output=True, timeout=1, check=True)
        except (OSError, subprocess.SubprocessError):
            pass
