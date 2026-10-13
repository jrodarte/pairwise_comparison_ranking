"""Curated Textual palettes. Keep widget colors in CSS bound to theme variables."""

from textual.theme import Theme

# name: primary, secondary, accent, foreground, background, surface, panel, warning, error
_PALETTES = {
    "thinktui": ("#83c6ba", "#577d90", "#e4bd83", "#e4e9ef", "#10151e", "#151e29", "#202c39", "#e4bd83", "#ca837f"),
    "catppuccin-mocha": (
        "#cba6f7",
        "#89b4fa",
        "#f9e2af",
        "#cdd6f4",
        "#1e1e2e",
        "#181825",
        "#313244",
        "#f9e2af",
        "#f38ba8",
    ),
    "tokyo-night": ("#7aa2f7", "#7dcfff", "#bb9af7", "#c0caf5", "#1a1b26", "#16161e", "#24283b", "#e0af68", "#f7768e"),
    "nord": ("#88c0d0", "#81a1c1", "#b48ead", "#eceff4", "#2e3440", "#3b4252", "#434c5e", "#ebcb8b", "#bf616a"),
    "dracula": ("#bd93f9", "#8be9fd", "#ffb86c", "#f8f8f2", "#282a36", "#21222c", "#343746", "#f1fa8c", "#ff5555"),
    "gruvbox-dark": ("#b8bb26", "#83a598", "#d79921", "#ebdbb2", "#282828", "#1d2021", "#3c3836", "#fabd2f", "#fb4934"),
    "solarized-dark": (
        "#2aa198",
        "#268bd2",
        "#b58900",
        "#eee8d5",
        "#002b36",
        "#073642",
        "#11434b",
        "#cb4b16",
        "#dc322f",
    ),
    "rose-pine": ("#c4a7e7", "#9ccfd8", "#f6c177", "#e0def4", "#191724", "#1f1d2e", "#26233a", "#f6c177", "#eb6f92"),
    "kanagawa": ("#7e9cd8", "#7fb4ca", "#c0a36e", "#dcd7ba", "#1f1f28", "#16161d", "#2a2a37", "#e6c384", "#c34043"),
    "everforest": ("#a7c080", "#7fbbb3", "#dbbc7f", "#d3c6aa", "#2d353b", "#232a2e", "#343f44", "#dfa000", "#e67e80"),
    "one-dark": ("#61afef", "#56b6c2", "#c678dd", "#abb2bf", "#282c34", "#21252b", "#353b45", "#e5c07b", "#e06c75"),
    "catppuccin-latte": (
        "#8839ef",
        "#1e66f5",
        "#df8e1d",
        "#303446",
        "#eff1f5",
        "#e6e9ef",
        "#dce0e8",
        "#df8e1d",
        "#d20f39",
    ),
}

THEMES = {
    name: Theme(
        name=name,
        primary=primary,
        secondary=secondary,
        accent=accent,
        foreground=foreground,
        background=background,
        surface=surface,
        panel=panel,
        warning=warning,
        error=error,
        success=primary,
        dark=name != "catppuccin-latte",
    )
    for name, (primary, secondary, accent, foreground, background, surface, panel, warning, error) in _PALETTES.items()
}
THEME_CHOICES = [(name.replace("-", " ").title(), name) for name in THEMES]
