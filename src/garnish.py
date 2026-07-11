"""tofu-garnish: turn Tofu/Terraform outputs into a simple static HTML page.

Stdlib only. Accepts any of these JSON shapes and figures out which it is:

1. A plain map of output name -> value, as produced by the
   ``json_output_path`` output of ``dflook/terraform-output``.
2. The ``terraform output -json`` / ``tofu output -json`` format, where each
   output is ``{"value": ..., "type": ..., "sensitive": bool}``.
3. A map of output name -> string, where complex values are JSON-encoded
   strings, as produced by ``toJson(steps.<id>.outputs)`` on a
   ``dflook/terraform-output`` step.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

__version__ = "1.0.0"

MASK = "••••••••"


@dataclass
class Output:
    """A single normalized root-module output."""

    name: str
    value: object
    sensitive: bool = False


@dataclass
class Page:
    """Everything needed to render the page."""

    title: str
    outputs: list[Output] = field(default_factory=list)
    generated_at: str = ""


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def _looks_like_tf_output_json(data: dict) -> bool:
    """True for the ``terraform output -json`` wrapper format."""
    if not data:
        return False
    return all(isinstance(v, dict) and "value" in v for v in data.values())


def _maybe_decode_json_string(value: object) -> object:
    """Decode strings that are JSON-encoded arrays/objects.

    ``dflook/terraform-output`` step outputs encode complex types as JSON
    strings; primitives are left alone so ``"80"`` stays the string ``"80"``.
    """
    if isinstance(value, str):
        stripped = value.strip()
        if stripped[:1] in ("{", "["):
            try:
                return json.loads(stripped)
            except ValueError:
                return value
    return value


def parse_outputs(text: str) -> list[Output]:
    """Parse raw JSON text into a normalized, name-sorted list of outputs."""
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise ValueError(f"input is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(
            f"expected a JSON object mapping output names to values, got {type(data).__name__}"
        )

    outputs: list[Output] = []
    if _looks_like_tf_output_json(data):
        for name, meta in data.items():
            outputs.append(
                Output(
                    name=name,
                    value=meta["value"],
                    sensitive=bool(meta.get("sensitive", False)),
                )
            )
    else:
        for name, value in data.items():
            outputs.append(Output(name=name, value=_maybe_decode_json_string(value)))

    outputs.sort(key=lambda o: o.name.lower())
    return outputs


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def _render_scalar(value: object) -> str:
    """Render a leaf value as code."""
    if value is None:
        return '<span class="null">null</span>'
    text = ("true" if value else "false") if isinstance(value, bool) else str(value)
    return f"<code>{_esc(text)}</code>"


def _is_scalar(value: object) -> bool:
    return not isinstance(value, (dict, list))


def _raw_text(value: object) -> str:
    """Clipboard text for a value: plain text for scalars, pretty JSON otherwise."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if _is_scalar(value):
        return str(value)
    return json.dumps(value, indent=2)


def _copy_button(value: object) -> str:
    return (
        '<button class="copy" type="button" title="Copy value" '
        f'data-raw="{_esc(_raw_text(value))}">copy</button>'
    )


def _render_mapping(value: dict, depth: int) -> str:
    if not value:
        return '<span class="empty">(empty map)</span>'
    rows = []
    for k, v in value.items():
        act = f'<td class="act">{_copy_button(v)}</td>' if depth == 0 else ""
        rows.append(
            f'<tr><th scope="row">{_esc(k)}</th><td>{_render_value(v, depth + 1)}</td>{act}</tr>'
        )
    return f'<table class="kv"><tbody>{"".join(rows)}</tbody></table>'


def _render_uniform_list(value: list, depth: int) -> str:
    """Render a list of mappings as a columnar table with one copy button per row."""
    columns: list[str] = []
    for item in value:
        for key in item:
            if key not in columns:
                columns.append(key)
    head = "".join(f'<th scope="col">{_esc(c)}</th>' for c in columns)
    if depth == 0:
        head += '<th scope="col" class="act"></th>'
    body_rows = []
    for item in value:
        cells = "".join(
            f"<td>{_render_value(item[c], depth + 1)}</td>"
            if c in item
            else '<td><span class="empty">—</span></td>'
            for c in columns
        )
        if depth == 0:
            cells += f'<td class="act">{_copy_button(item)}</td>'
        body_rows.append(f"<tr>{cells}</tr>")
    return (
        '<table class="grid"><thead><tr>'
        f"{head}</tr></thead><tbody>{''.join(body_rows)}</tbody></table>"
    )


def _render_list(value: list, depth: int) -> str:
    if not value:
        return '<span class="empty">(empty list)</span>'
    if all(isinstance(item, dict) for item in value):
        return _render_uniform_list(value, depth)
    items = "".join(
        f"<li>{_render_value(v, depth + 1)}"
        + (f" {_copy_button(v)}" if depth == 0 else "")
        + "</li>"
        for v in value
    )
    return f'<ol class="seq">{items}</ol>'


def _render_value(value: object, depth: int = 0) -> str:
    if _is_scalar(value):
        return _render_scalar(value)
    if isinstance(value, dict):
        return _render_mapping(value, depth)
    return _render_list(value, depth)


def _search_terms(value: object):
    """Yield all keys and scalar leaf values within a value, for filtering."""
    if isinstance(value, dict):
        for k, v in value.items():
            yield str(k)
            yield from _search_terms(v)
    elif isinstance(value, list):
        for v in value:
            yield from _search_terms(v)
    else:
        yield _raw_text(value)


def _render_output(output: Output) -> str:
    if output.sensitive:
        body = f'<span class="sensitive">{MASK} <em>(sensitive)</em></span>'
        search = output.name.lower()
    elif _is_scalar(output.value):
        # A top-level scalar is its own "row": value plus one copy button.
        body = (
            f'<span class="scalar">{_render_scalar(output.value)}'
            f"{_copy_button(output.value)}</span>"
        )
        search = f"{output.name} {_raw_text(output.value)}".lower()
    else:
        body = _render_value(output.value)
        search = " ".join([output.name, *_search_terms(output.value)]).lower()
    return (
        f'<section class="output" id="{_esc(output.name)}" '
        f'data-name="{_esc(output.name.lower())}" data-search="{_esc(search)}">'
        f'<h2><a href="#{_esc(output.name)}">{_esc(output.name)}</a></h2>'
        f"{body}</section>"
    )


_CSS = """\
:root { color-scheme: light dark; --border: #d0d7de; --muted: #656d76; --accent: #1a7f37; }
@media (prefers-color-scheme: dark) { :root { --border: #30363d; --muted: #8b949e; --accent: #3fb950; } }
* { box-sizing: border-box; }
body { font-family: system-ui, sans-serif; max-width: 60rem; margin: 0 auto; padding: 1rem 1.5rem 4rem; line-height: 1.5; }
header h1 { margin-bottom: 0.25rem; }
header p { color: var(--muted); margin-top: 0; }
#filter { width: 100%; padding: 0.5rem 0.75rem; font-size: 1rem; border: 1px solid var(--border); border-radius: 6px; margin: 0.5rem 0 1rem; background: transparent; color: inherit; }
section.output { border: 1px solid var(--border); border-radius: 6px; padding: 0.75rem 1rem; margin: 0.75rem 0; overflow-x: auto; }
section.output h2 { margin: 0 0 0.5rem; font-size: 1.05rem; }
section.output h2 a { color: var(--accent); text-decoration: none; }
section.output h2 a:hover { text-decoration: underline; }
table { border-collapse: collapse; width: 100%; margin: 0.25rem 0; }
th, td { border: 1px solid var(--border); padding: 0.3rem 0.6rem; text-align: left; vertical-align: top; font-size: 0.9rem; }
table.kv > tbody > tr > th { width: 30%; font-weight: 600; }
td.act, th.act { width: 1%; white-space: nowrap; text-align: center; }
code { font-family: ui-monospace, monospace; font-size: 0.9em; overflow-wrap: anywhere; }
ol.seq { margin: 0.25rem 0; padding-left: 1.5rem; }
.scalar { display: inline-flex; align-items: baseline; gap: 0.5rem; max-width: 100%; }
button.copy { font-size: 0.7rem; border: 1px solid var(--border); border-radius: 4px; background: transparent; color: var(--muted); cursor: pointer; padding: 0.1rem 0.4rem; }
button.copy:hover { color: inherit; }
.empty, .null { color: var(--muted); font-style: italic; }
.sensitive { color: var(--muted); }
footer { margin-top: 2rem; color: var(--muted); font-size: 0.85rem; }
.no-match { color: var(--muted); font-style: italic; display: none; }
"""

_JS = """\
document.getElementById('filter').addEventListener('input', function () {
  var q = this.value.trim().toLowerCase();
  var any = false;
  document.querySelectorAll('section.output').forEach(function (s) {
    var show = !q || s.dataset.search.indexOf(q) !== -1;
    s.style.display = show ? '' : 'none';
    if (show) { any = true; }
  });
  document.getElementById('no-match').style.display = any ? 'none' : 'block';
});
document.addEventListener('click', function (e) {
  if (!e.target.matches('button.copy')) { return; }
  navigator.clipboard.writeText(e.target.dataset.raw).then(function () {
    e.target.textContent = 'copied!';
    setTimeout(function () { e.target.textContent = 'copy'; }, 1200);
  });
});
"""


def render_page(page: Page) -> str:
    """Render the full, self-contained HTML document."""
    if page.outputs:
        sections = "".join(_render_output(o) for o in page.outputs)
    else:
        sections = '<p class="empty">No outputs found.</p>'
    count = len(page.outputs)
    noun = "output" if count == 1 else "outputs"
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="generator" content="tofu-garnish {__version__}">
<title>{_esc(page.title)}</title>
<style>
{_CSS}</style>
</head>
<body>
<header>
<h1>{_esc(page.title)}</h1>
<p>{count} {noun} · generated {_esc(page.generated_at)}</p>
</header>
<input id="filter" type="search" placeholder="Filter outputs by name or value…" aria-label="Filter outputs by name or value">
<main>
{sections}
<p id="no-match" class="no-match">No outputs match the filter.</p>
</main>
<footer>Generated by <a href="https://github.com/lowlydba/tofu-garnish">tofu-garnish</a>.</footer>
<script>
{_JS}</script>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _now_utc() -> str:
    """Current UTC time, honoring SOURCE_DATE_EPOCH for reproducible builds."""
    epoch = os.environ.get("SOURCE_DATE_EPOCH")
    if epoch:
        dt = datetime.fromtimestamp(int(epoch), tz=timezone.utc)
    else:
        dt = datetime.now(tz=timezone.utc)
    return dt.strftime("%Y-%m-%d %H:%M UTC")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="garnish",
        description="Generate a static HTML page from Tofu/Terraform outputs.",
    )
    parser.add_argument(
        "--input",
        default="-",
        help="Path to a JSON outputs file, or '-' for stdin (default).",
    )
    parser.add_argument(
        "--output-dir",
        default="site",
        help="Directory to write index.html into (default: site).",
    )
    parser.add_argument(
        "--title",
        default="Tofu Outputs",
        help="Page title (default: 'Tofu Outputs').",
    )
    parser.add_argument("--version", action="version", version=__version__)
    args = parser.parse_args(argv)

    if args.input == "-":
        text = sys.stdin.read()
    else:
        path = Path(args.input)
        if not path.is_file():
            print(f"garnish: input file not found: {path}", file=sys.stderr)
            return 2
        text = path.read_text(encoding="utf-8")

    try:
        outputs = parse_outputs(text)
    except ValueError as exc:
        print(f"garnish: {exc}", file=sys.stderr)
        return 2

    page = Page(title=args.title, outputs=outputs, generated_at=_now_utc())
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / "index.html"
    out_file.write_text(render_page(page), encoding="utf-8")
    print(f"garnish: wrote {out_file} ({len(outputs)} outputs)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
