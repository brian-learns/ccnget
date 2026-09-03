"""Output formatting and typed exit codes for the ccnget CLI.

Every JSON-producing subcommand (lookup, extent, surt-browse, surt-prefix)
builds a plain dict and hands it to :func:`emit`. The output mode is
resolved from the ``--json`` / ``--compact`` / ``--table`` / ``--select``
flags, falling back to:

- interactive TTY on stdout -> Rich table (colors auto-detected by Rich)
- piped stdout              -> pretty JSON

``--select`` applies jq-style dot-notation traversal to the output dict and
prints the raw extracted value (JSON for dict/list, bare text otherwise),
ignoring the other output flags.

Exit codes (Printing Press convention):

- 0 success (an empty result set is success)
- 2 usage error (bad flags, bad ``--select`` path, config error)
- 3 not found (no index match for the requested URL)
- 5 API error (network failure, non-JSON response, server error)
"""

from __future__ import annotations

import json
import re
import sys
from typing import Any, Callable, NoReturn

from rich.console import Console
from rich.table import Table

CONSOLE: Console = Console()
ERR_CONSOLE: Console = Console(stderr=True)

EXIT_OK: int = 0
EXIT_USAGE: int = 2
EXIT_NOT_FOUND: int = 3
EXIT_API: int = 5


class SelectError(Exception):
    """Raised when a --select dot-path does not resolve to a value."""


def is_interactive() -> bool:
    """Return True when stdout is attached to an interactive terminal."""
    return bool(sys.stdout.isatty())


def _coerce_int(value: str) -> int | None:
    """Parse a non-negative integer selector segment, else None."""
    if value.isdigit():
        return int(value)
    try:
        as_int = int(value)
    except ValueError:
        return None
    return as_int if as_int >= 0 else None


def apply_select(data: Any, path: str) -> Any:
    """Extract a value from *data* using a dot-notation path.

    A bare name (``url``) or an index (``0``) indexes the top level;
    deeper segments walk dicts and lists in order. When a segment is a
    non-numeric name and the current value is a list of dicts, the name
    is mapped over every item, producing a list (``results.warc_path``).
    """
    target: Any = data
    for part in path.split("."):
        index = _coerce_int(part)
        try:
            if isinstance(target, list):
                if index is not None:
                    target = target[index]
                else:
                    target = [item[part] for item in target]
            elif isinstance(target, dict):
                if index is not None:
                    key = next((k for k in target if str(k) == part), None)
                    if key is None:
                        raise SelectError(f"key {part} not found in {sorted(target)}")
                    target = target[key]
                else:
                    target = target[part]
            else:
                raise SelectError(f"cannot traverse into {type(target).__name__} with '{part}'")
        except (KeyError, IndexError) as exc:
            raise SelectError(f"segment '{part}' not found in path '{path}': {exc}") from None
    return target


# ANSI escape sequences interpreted by terminals (CSI, OSC, and single-char
# Fe/Fn sequences). Stripped from raw --select output so untrusted result
# values cannot inject terminal control sequences.
_ANSI_RE = re.compile(
    r"\x1b\[[0-9;?]*[ -/]*[@-~]"  # CSI
    r"|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)"  # OSC
    r"|\x1b[@-Z\\-_]"  # two-char sequences
)


def _select_value_to_text(value: Any) -> str:
    """Render an extracted --select value: JSON for containers, bare text for scalars."""
    if isinstance(value, (dict, list)):
        return json.dumps(value, indent=2)
    return _ANSI_RE.sub("", str(value))


def _entry_row(entry: dict[str, Any]) -> list[str]:
    """One capture entry as table cell strings (extra fields appended as key=value)."""
    cells = [
        str(entry.get("surt_key", "")),
        str(entry.get("timestamp", "")),
        str(entry.get("warc_path", "")),
        str(entry.get("offset", "")),
        str(entry.get("length", "")),
    ]
    extras = {k: v for k, v in entry.items() if k not in {"surt_key", "timestamp", "warc_path", "offset", "length"}}
    cells.append(" ".join(f"{k}={v!s}" for k, v in extras.items()))
    return cells


def _capture_table(title: str, entries: list[dict[str, Any]]) -> Table:
    """Rich table for lookup / surt-prefix style capture lists."""
    table = Table(title=title, header_style="bold cyan")
    table.add_column("SURT key", style="bold", overflow="fold")
    table.add_column("Timestamp", style="dim")
    table.add_column("WARC path", overflow="fold")
    table.add_column("Offset", justify="right", style="dim")
    table.add_column("Length", justify="right", style="dim")
    table.add_column("Extra", style="dim")
    for entry in entries:
        table.add_row(*_entry_row(entry))
    return table


def render_lookup(title: str, payload: dict[str, Any]) -> None:
    """Human view for lookup-style output (url + capture list)."""
    if payload["results"]:
        CONSOLE.print(_capture_table(title, payload["results"]))
    else:
        CONSOLE.print(f"[yellow]No captures found for {payload['url']}[/yellow]")


def render_extent(payload: dict[str, Any]) -> None:
    """Human view for the extent endpoint (index statistics)."""
    table = Table(title="Index extent", header_style="bold cyan")
    table.add_column("Field", style="bold")
    table.add_column("Value", overflow="fold")
    table.add_row("files", str(payload["file_extent"]))
    table.add_row("oldest", payload["file_oldest"])
    table.add_row("newest", payload["file_newest"])
    CONSOLE.print(table)


def render_surt_browse(payload: dict[str, Any]) -> None:
    """Human view for one hop of the SURT host tree."""
    pattern = payload["pattern"] or "(root)"
    header = Table(title=f"Browse {pattern}")
    header.add_column("Field", style="bold")
    header.add_column("Value")
    header.add_row("entries under pattern", str(payload["count"]))
    header.add_row("total entries in index", str(payload["total_entries"]))
    header.add_row(
        "children (shown / total)",
        f"{len(payload['children'])} / {payload['total_children']}",
    )
    if payload.get("next_offset") is not None:
        header.add_row("next page", f"--offset {payload['next_offset']}")
    CONSOLE.print(header)

    children = payload["children"]
    if children:
        tree = Table(title="Children", header_style="bold cyan")
        tree.add_column("Pattern", style="bold", overflow="fold")
        tree.add_column("Entries", justify="right")
        for name, count in children.items():
            tree.add_row(name, str(count))
        CONSOLE.print(tree)
    else:
        CONSOLE.print("[yellow]No children at this level[/yellow]")


def emit(
    payload: dict[str, Any],
    renderer: Callable[[dict[str, Any]], None],
    *,
    json_flag: bool = False,
    compact: bool = False,
    table_flag: bool = False,
    select: str | None = None,
) -> int:
    """Print *payload* in the requested output mode.

    Mode precedence: ``--select`` > explicit flag (--json/--compact/--table)
    > TTY default (interactive -> table, piped -> pretty JSON).

    Parameters
    ----------
    payload : dict
        The JSON-serialisable output dict for the command.
    renderer : callable
        Function(payload) that draws the human table view.
    json_flag : bool
        ``--json``: pretty-printed JSON.
    compact : bool
        ``--compact``: minified single-line JSON.
    table_flag : bool
        ``--table``: force the human table view.
    select : str | None
        ``--select`` dot-path; raw value printed, no envelope.

    Returns
    -------
    int
        EXIT_OK on success, EXIT_USAGE when --select cannot be resolved.
    """
    if select is not None:
        try:
            value = apply_select(payload, select)
        except (SelectError, KeyError, IndexError, TypeError) as exc:
            fail(f"selector '{select}' not found in output: {exc}", EXIT_USAGE, machine=True)
            return EXIT_USAGE
        print(_select_value_to_text(value))
        return EXIT_OK

    if compact:
        print(json.dumps(payload, separators=(",", ":")))
    elif json_flag:
        print(json.dumps(payload, indent=2))
    elif table_flag or is_interactive():
        renderer(payload)
    else:
        print(json.dumps(payload, indent=2))
    return EXIT_OK


def fail(message: str, code: int, *, machine: bool = False) -> NoReturn:
    """Report an error and exit with a typed code.

    Machine mode (JSON/compact/agent context) writes a one-line JSON object
    to stderr; otherwise a colored one-line message is shown.
    """
    if machine:
        # Plain print: Rich would wrap long lines at the terminal width,
        # which would break the one-line JSON contract.
        print(
            json.dumps({"status": "error", "code": code, "error": message}, separators=(",", ":")),
            file=sys.stderr,
        )
    else:
        ERR_CONSOLE.print(f"[bold red]ccnget: error ({code}):[/bold red] {message}")
    sys.exit(code)
