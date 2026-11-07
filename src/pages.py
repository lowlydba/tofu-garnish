"""Render the output page, landing page and shared page chrome."""

from __future__ import annotations

from pathlib import Path

from model import CHECK_MARK, DOCS_DIR, LINK_ICON, REPO_URL, Page, Provenance, __version__
from tree import CHANGE_HINT, _esc, _link_button, _render_output

_ASSETS = Path(__file__).resolve().parent / "assets"


def _asset(*names: str) -> str:
    """Concatenate bundled CSS/JS files from ``src/assets`` (shipped next to this script)."""
    return "".join((_ASSETS / name).read_text(encoding="utf-8") for name in names)


def _plural(count: int, noun: str) -> str:
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"


def _source_link(source_url: str) -> str:
    """Meta-line fragment linking back to the repo the outputs come from."""
    if not source_url:
        return ""
    return f' · <a class="src" href="{_esc(source_url)}">source repository</a>'


def _absolute(base: str, href: str) -> str:
    """Resolve ``href`` against the public site URL when one is configured."""
    return f"{base}{href}" if href else ""


def _json_link(json_href: str) -> str:
    """Meta-line fragment linking to the machine-readable outputs.json."""
    if not json_href:
        return ""
    return f' · <a class="src" href="{_esc(json_href)}">JSON</a>'


def _share_fragment(share_url: str) -> str:
    """Meta-line fragment with a button copying the page's shareable URL."""
    if not share_url:
        return ""
    return " · " + _link_button(share_url, LINK_ICON, "copy anchor", CHECK_MARK)


def _provenance_html(provenance: Provenance | None) -> str:
    """Meta-line fragment linking the commit and workflow run behind a publish."""
    if provenance is None:
        return ""
    fragment = (
        f' · commit <a class="src" href="{_esc(provenance.commit_url)}">'
        f"{_esc(provenance.commit_sha[:7])}</a>"
    )
    if provenance.run_url:
        fragment += f' · <a class="src" href="{_esc(provenance.run_url)}">workflow run</a>'
    return fragment


def _document(title: str, header: str, main: str, script: str = "", footer: bool = True) -> str:
    """Wrap header/main content in the shared HTML shell."""
    script_tag = f"<script>\n{script}</script>\n" if script else ""
    footer_tag = (
        "<footer>Served with \U0001f49a by "
        f'\U0001f33f <a class="src" href="{REPO_URL}">tofu-garnish</a>.</footer>\n'
        if footer
        else ""
    )
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="generator" content="tofu-garnish {__version__}">
<link rel="icon" href="data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 100 100%22><text y=%22.9em%22 font-size=%2290%22>\U0001f33f</text></svg>">
<title>{_esc(title)}</title>
<style>
{_asset("garnish.css")}</style>
</head>
<body>
<!-- 🌿 Psst, you found the garnish. View-source people are our favorite people. We hope you enjoy your tofu. 🧈 -->
<header>
{header}</header>
<main>
{main}</main>
{footer_tag}{script_tag}</body>
</html>
"""


def _docs_nav(docs: list[tuple[str, str]], prefix: str = "") -> str:
    """Single link to the docs index, which scales regardless of page count."""
    if not docs:
        return ""
    return (
        f'<nav class="docs" aria-label="Documentation"><a href="{_esc(prefix)}{DOCS_DIR}/">'
        f"Docs ({len(docs)})</a></nav>\n"
    )


def render_page(page: Page) -> str:
    """Render the full, self-contained HTML document."""
    changes = page.changes
    changed = f" · {_plural(changes.count, 'output')} changed" if changes and changes.count else ""
    if page.outputs:
        sections = "".join(
            _render_output(o, page.share_url, changes.status(o.name) if changes else "")
            for o in page.outputs
        )
    else:
        sections = '<p class="empty">No outputs found.</p>'
    if changes and changes.removed:
        sections += "".join(
            f'<section class="removed" title="{_esc(CHANGE_HINT)}"><h2>{_esc(name)} '
            '<span class="badge destroyed">destroyed</span></h2></section>'
            for name in changes.removed
        )
    back = (
        f'<p class="back"><a href="{_esc(page.back_href)}">← all workspaces</a></p>'
        if page.back_href
        else ""
    )
    header = (
        f"{back}<h1>{_esc(page.title)}</h1>\n"
        f"<p>{_plural(len(page.outputs), 'output')}{changed} · generated {_esc(page.generated_at)}"
        f"{_provenance_html(page.provenance)}{_source_link(page.source_url)}"
        f"{_json_link(_absolute(page.share_url, page.json_href))}"
        f"{_share_fragment(page.share_url)}</p>\n"
        f"{_docs_nav(page.docs, page.back_href)}"
        '<input id="filter" type="search" placeholder="Filter outputs by name or value…"'
        ' aria-label="Filter outputs by name or value">\n'
        '<p id="filter-status" class="sr-only" role="status"></p>\n'
    )
    main = f'{sections}\n<p id="no-match" class="no-match">No outputs match the filter.</p>\n'
    return _document(
        page.title, header, main, script=_asset("filter.js", "copy.js"), footer=page.footer
    )


def _landing_actions(source_url: str, share_url: str, docs: list[tuple[str, str]]) -> str:
    """Primary landing actions as one quiet row, keeping the subtitle to a single fact line."""
    items = []
    if docs:
        items.append(f'<a class="act" href="{DOCS_DIR}/">Docs ({len(docs)})</a>')
    if source_url:
        items.append(f'<a class="act" href="{_esc(source_url)}">Source</a>')
    if share_url:
        items.append(_link_button(share_url, LINK_ICON, "copy anchor", CHECK_MARK))
    if not items:
        return ""
    return f'<nav class="actions" aria-label="Site links">{"".join(items)}</nav>\n'


def _provenance_details(provenance: Provenance | None) -> str:
    """Commit and run links tucked behind a disclosure, since few visitors need them."""
    if provenance is None:
        return ""
    links = (
        f'<a class="src" href="{_esc(provenance.commit_url)}">'
        f"commit {_esc(provenance.commit_sha[:7])}</a>"
    )
    if provenance.run_url:
        links += f' · <a class="src" href="{_esc(provenance.run_url)}">workflow run</a>'
    return f'<details class="prov"><summary>Build details</summary><p>{links}</p></details>\n'


def render_landing(
    title: str,
    workspaces: list[tuple[str, str, int, str, str]],
    generated_at: str,
    source_url: str = "",
    footer: bool = True,
    provenance: Provenance | None = None,
    share_url: str = "",
    docs: list[tuple[str, str]] | None = None,
) -> str:
    """Render the landing page linking to per-workspace pages.

    ``workspaces`` is a list of ``(name, slug, output_count, updated,
    updated_at)`` tuples; ``updated`` is the display string and ``updated_at``
    the ISO timestamp the client rewrites into a relative age.
    """
    sections = []
    for name, slug, count, updated, updated_at in workspaces:
        stamp = ""
        if updated and updated_at:
            stamp = (
                f' · updated <time datetime="{_esc(updated_at)}" title="{_esc(updated)}">'
                f"{_esc(updated)}</time>"
            )
        elif updated:
            stamp = f" · updated {_esc(updated)}"
        sections.append(
            f'<section class="output ws" data-search="{_esc(name.lower())}">'
            f'<h2><a href="{_esc(slug)}/">{_esc(name)}</a></h2>'
            f"<p>{_plural(count, 'output')}{stamp}</p></section>"
        )
    actions = _landing_actions(source_url, share_url, docs or [])
    header = (
        f"<h1>{_esc(title)}</h1>\n"
        f"<p>{_plural(len(workspaces), 'workspace')} · generated {_esc(generated_at)}</p>\n"
        f"{actions}{_provenance_details(provenance)}"
    )
    return _document(
        title,
        header,
        "".join(sections) + "\n",
        script=_asset("relative-time.js", "copy.js"),
        footer=footer,
    )
