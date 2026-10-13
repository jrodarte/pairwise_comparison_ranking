"""Widgets for displaying untrusted user text without interpreting Rich markup."""

from rich.text import Text
from textual.widgets import DataTable as _DataTable
from textual.widgets import Label as _Label
from textual.widgets import Select as _Select
from textual.widgets import Static as _Static


class Static(_Static):
    def __init__(self, content="", *, markup=False, **kwargs):
        super().__init__(content, markup=markup, **kwargs)


class Label(_Label):
    def __init__(self, content="", *, markup=False, **kwargs):
        super().__init__(content, markup=markup, **kwargs)


class Select(_Select):
    """Textual's internal SelectCurrent otherwise interprets option strings as markup."""

    def __init__(self, options, **kwargs):
        super().__init__(self._literal_options(options), **kwargs)

    @staticmethod
    def _literal_options(options):
        return [(Text(label) if isinstance(label, str) else label, value) for label, value in options]

    def set_options(self, options):
        super().set_options(self._literal_options(options))


class DataTable(_DataTable):
    def add_row(self, *cells, height=1, key=None, label=None):
        return super().add_row(
            *(Text(cell) if isinstance(cell, str) else cell for cell in cells),
            height=height,
            key=key,
            label=Text(label) if isinstance(label, str) else label,
        )

    def add_column(self, label, *, width=None, key=None, default=None):
        return super().add_column(
            Text(label) if isinstance(label, str) else label, width=width, key=key, default=default
        )
