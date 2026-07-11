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
import re
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
    description: str = ""


@dataclass
class Page:
    """Everything needed to render the page."""

    title: str
    outputs: list[Output] = field(default_factory=list)
    generated_at: str = ""
    back_href: str = ""


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


def parse_descriptions(text: str) -> dict[str, str]:
    """Parse output descriptions from ``tofu show -json`` configuration JSON.

    OpenTofu only: ``tofu show -json -module=DIR`` (or ``-config``) emits the
    configuration representation, whose ``root_module.outputs`` entries carry
    the ``description`` argument that ``tofu output -json`` drops. A plain
    ``{"name": "description"}`` map is accepted too.
    """
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise ValueError(f"descriptions input is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("descriptions input must be a JSON object")

    outputs = data.get("root_module", {}).get("outputs") if "root_module" in data else data
    if not isinstance(outputs, dict):
        return {}
    descriptions: dict[str, str] = {}
    for name, meta in outputs.items():
        if isinstance(meta, str):
            descriptions[name] = meta
        elif isinstance(meta, dict) and isinstance(meta.get("description"), str):
            descriptions[name] = meta["description"]
    return descriptions


def apply_descriptions(outputs: list[Output], descriptions: dict[str, str]) -> None:
    """Attach descriptions to matching outputs in place."""
    for output in outputs:
        output.description = descriptions.get(output.name, "")


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
    if output.description:
        search = f"{search} {output.description.lower()}"
    desc = f'<p class="desc">{_esc(output.description)}</p>' if output.description else ""
    return (
        f'<section class="output" id="{_esc(output.name)}" '
        f'data-name="{_esc(output.name.lower())}" data-search="{_esc(search)}">'
        f'<h2><a href="#{_esc(output.name)}">{_esc(output.name)}</a></h2>'
        f"{desc}{body}</section>"
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
.desc { color: var(--muted); font-size: 0.9rem; margin: -0.35rem 0 0.5rem; }
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
.back { margin: 0 0 0.25rem; font-size: 0.9rem; }
.back a, .ws h2 a { color: var(--accent); text-decoration: none; }
.back a:hover, .ws h2 a:hover { text-decoration: underline; }
section.ws p { color: var(--muted); margin: 0; }
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
    back = (
        f'<p class="back"><a href="{_esc(page.back_href)}">← all workspaces</a></p>'
        if page.back_href
        else ""
    )
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
{back}<h1>{_esc(page.title)}</h1>
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
# Multi-workspace site
# ---------------------------------------------------------------------------


def slugify(name: str) -> str:
    """Turn a workspace name into a safe directory name."""
    slug = re.sub(r"[^a-z0-9._-]+", "-", name.lower()).strip("-.")
    return slug or "workspace"


def parse_workspace_spec(spec: str) -> tuple[str, str]:
    """Parse a ``name=path`` workspace spec into its parts."""
    name, sep, path = spec.partition("=")
    name, path = name.strip(), path.strip()
    if not sep or not name or not path:
        raise ValueError(f"invalid workspace spec {spec!r}, expected 'name=path'")
    return name, path


def render_landing(
    title: str, workspaces: list[tuple[str, str, int, str]], generated_at: str
) -> str:
    """Render the landing page linking to per-workspace pages.

    ``workspaces`` is a list of ``(name, slug, output_count, updated)`` tuples.
    """
    sections = []
    for name, slug, count, updated in workspaces:
        noun = "output" if count == 1 else "outputs"
        meta = f"{count} {noun}" + (f" · updated {_esc(updated)}" if updated else "")
        sections.append(
            f'<section class="output ws" data-search="{_esc(name.lower())}">'
            f'<h2><a href="{_esc(slug)}/">{_esc(name)}</a></h2>'
            f"<p>{meta}</p></section>"
        )
    count = len(workspaces)
    noun = "workspace" if count == 1 else "workspaces"
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="generator" content="tofu-garnish {__version__}">
<title>{_esc(title)}</title>
<style>
{_CSS}</style>
</head>
<body>
<header>
<h1>{_esc(title)}</h1>
<p>{count} {noun} · generated {_esc(generated_at)}</p>
</header>
<main>
{"".join(sections)}
</main>
<footer>Generated by <a href="https://github.com/lowlydba/tofu-garnish">tofu-garnish</a>.</footer>
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


def _load_outputs_file(path_str: str) -> list[Output]:
    path = Path(path_str)
    if not path.is_file():
        raise ValueError(f"input file not found: {path}")
    return parse_outputs(path.read_text(encoding="utf-8"))


def _load_descriptions(args: argparse.Namespace) -> dict[str, str]:
    if not args.descriptions:
        return {}
    path = Path(args.descriptions)
    if not path.is_file():
        raise ValueError(f"descriptions file not found: {path}")
    return parse_descriptions(path.read_text(encoding="utf-8"))


def _run_single(args: argparse.Namespace) -> int:
    try:
        if args.input == "-":
            outputs = parse_outputs(sys.stdin.read())
        else:
            outputs = _load_outputs_file(args.input)
        apply_descriptions(outputs, _load_descriptions(args))
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


def _read_manifest(out_dir: Path) -> dict:
    """Read existing workspace entries from a site's manifest, if any."""
    manifest_path = out_dir / "manifest.json"
    if not manifest_path.is_file():
        return {}
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except ValueError:
        return {}
    workspaces = data.get("workspaces") if isinstance(data, dict) else None
    return workspaces if isinstance(workspaces, dict) else {}


def _run_workspaces(args: argparse.Namespace) -> int:
    generated_at = _now_utc()
    workspaces: list[tuple[str, str, list[Output]]] = []
    seen_slugs: dict[str, str] = {}
    try:
        descriptions = _load_descriptions(args)
        for spec in args.workspace:
            name, path = parse_workspace_spec(spec)
            slug = slugify(name)
            if slug in seen_slugs:
                raise ValueError(
                    f"workspace {name!r} clashes with {seen_slugs[slug]!r} "
                    f"(both map to directory {slug!r})"
                )
            seen_slugs[slug] = name
            outputs = _load_outputs_file(path)
            apply_descriptions(outputs, descriptions)
            workspaces.append((name, slug, outputs))
    except ValueError as exc:
        print(f"garnish: {exc}", file=sys.stderr)
        return 2

    out_dir = Path(args.output_dir)
    merged: dict[str, dict] = _read_manifest(out_dir) if args.merge else {}

    for name, slug, outputs in workspaces:
        page = Page(
            title=f"{args.title} · {name}",
            outputs=outputs,
            generated_at=generated_at,
            back_href="../",
        )
        ws_dir = out_dir / slug
        ws_dir.mkdir(parents=True, exist_ok=True)
        (ws_dir / "index.html").write_text(render_page(page), encoding="utf-8")
        merged[slug] = {"name": name, "outputs": len(outputs), "updated": generated_at}
        print(f"garnish: wrote {ws_dir / 'index.html'} ({len(outputs)} outputs)")

    entries = sorted(merged.items(), key=lambda kv: str(kv[1].get("name", kv[0])).lower())
    landing = render_landing(
        args.title,
        [
            (
                str(entry.get("name", slug)),
                slug,
                int(entry.get("outputs", 0)),
                str(entry.get("updated", "")),
            )
            for slug, entry in entries
        ],
        generated_at,
    )
    (out_dir / "index.html").write_text(landing, encoding="utf-8")
    manifest = {
        "generator": "tofu-garnish",
        "version": __version__,
        "title": args.title,
        "workspaces": dict(entries),
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"garnish: wrote {out_dir / 'index.html'} ({len(entries)} workspaces)")
    return 0


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
        "--workspace",
        action="append",
        default=[],
        metavar="NAME=PATH",
        help=(
            "Named outputs file, repeatable. When given, a page is generated "
            "per workspace under its own subdirectory, plus a landing page "
            "linking them. Overrides --input."
        ),
    )
    parser.add_argument(
        "--descriptions",
        default="",
        metavar="PATH",
        help=(
            "JSON file with output descriptions, as produced by OpenTofu's "
            "'tofu show -json -module=DIR' (or -config), or a plain "
            '{"name": "description"} map. OpenTofu only: Terraform\'s show '
            "command has no configuration mode. Applies to all workspaces."
        ),
    )
    parser.add_argument(
        "--merge",
        action="store_true",
        help=(
            "Preserve workspaces already recorded in the output directory's "
            "manifest.json, only overwriting the ones given via --workspace."
        ),
    )
    parser.add_argument(
        "--output-dir",
        default="site",
        help="Directory to write the site into (default: site).",
    )
    parser.add_argument(
        "--title",
        default="Tofu Outputs",
        help="Page title (default: 'Tofu Outputs').",
    )
    parser.add_argument("--version", action="version", version=__version__)
    args = parser.parse_args(argv)

    if args.merge and not args.workspace:
        print("garnish: --merge requires at least one --workspace", file=sys.stderr)
        return 2
    if args.workspace:
        return _run_workspaces(args)
    return _run_single(args)


if __name__ == "__main__":
    sys.exit(main())
