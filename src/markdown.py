"""Minimal Markdown renderer for docs pages."""

from __future__ import annotations

import html
import posixpath
import re
from pathlib import Path
from urllib.parse import unquote

from model import slugify
from pages import _asset, _document, _plural, _source_link
from tree import _esc

_SAFE_SCHEME = re.compile(r"^(https?|mailto):", re.I)
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f-\x9f]")
_ANY_SCHEME = re.compile(r"^[a-z][a-z0-9+.-]*:", re.I)
_MD_LINK = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")
_MD_TITLE = r"""(?:\s+(?:"[^"]*"|'[^']*'))?"""
_MD_IMAGE = rf"!\[((?:[^\]`]|`[^`]*`)*)\]\(([^)\s]+){_MD_TITLE}\)"
# Code spans and images are matched together, leftmost first, so image syntax
# inside a code span stays literal and backticks inside alt text stay intact.
_MD_TOKEN = re.compile(rf"(`[^`]+`)|{_MD_IMAGE}")
_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".avif"}
ASSETS_DIR = ".assets"
_MD_SEPARATOR = re.compile(r"^\s*\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)*\|?\s*$")
_MD_LIST_ITEM = re.compile(r"^\s*([-*+]|\d+\.)\s+(.*)")
_MD_MARKUP = re.compile(r"(?m)^\s*(#{1,6}\s+|[-*+]\s+|\d+\.\s+|>\s?)|[*`]|!?\[([^\]]*)\]\([^)]*\)")


def _md_href(href: str, resolve=None, image: bool = False) -> str:
    """Sanitize a link target and point relative links at docs pages or the source repo.

    ``resolve`` maps a relative path to a final href, or None to leave it as
    written; it receives ``image=True`` for image sources. Without it,
    ``*.md`` links point at sibling docs pages.
    """
    if _CONTROL_CHARS.search(href):
        return "#"
    if _ANY_SCHEME.match(href) and not _SAFE_SCHEME.match(href):
        return "#"
    if _ANY_SCHEME.match(href) or href.startswith(("#", "/")):
        return href
    path, hash_, frag = href.partition("#")
    if resolve is not None:
        resolved = resolve(path, image=True) if image else resolve(path)
        return (resolved if resolved is not None else path) + hash_ + frag
    if path.lower().endswith(".md") and not image:
        path = f"../{slugify(Path(unquote(path)).stem)}/"
    return path + hash_ + frag


def _md_img(alt: str, src: str, resolve=None) -> str:
    src = html.escape(_md_href(html.unescape(src), resolve, image=True))
    alt = html.escape(html.unescape(alt).replace("`", ""))
    return f'<img src="{src}" alt="{alt}" loading="lazy">'


def _md_inline(text: str, resolve=None) -> str:
    """Render inline Markdown: code, images, links, bold, italic. Input is escaped first."""
    stash: list[str] = []

    def hold(match: re.Match) -> str:
        if match[1]:
            stash.append(f"<code>{match[1][1:-1]}</code>")
        else:
            stash.append(_md_img(match[2], match[3], resolve))
        return f"\x00{len(stash) - 1}\x00"

    # Stashed so link, bold and italic markers never reach code or <img> attributes.
    text = _MD_TOKEN.sub(hold, html.escape(text.replace("\x00", ""), quote=False))
    text = _MD_LINK.sub(
        lambda m: f'<a href="{html.escape(_md_href(html.unescape(m[2]), resolve))}">{m[1]}</a>',
        text,
    )
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"<em>\1</em>", text)
    return re.sub(r"\x00(\d+)\x00", lambda m: stash[int(m[1])], text)


def _md_cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _heading_id(text: str, used: set[str]) -> str:
    """GitHub-style heading slug, suffixed with -1, -2, ... when repeated."""
    plain = _MD_MARKUP.sub(lambda mm: mm[2] or "", text).lower()
    base = re.sub(r"[^\w\- ]", "", plain).strip().replace(" ", "-") or "section"
    slug, n = base, 0
    while slug in used:
        n += 1
        slug = f"{base}-{n}"
    used.add(slug)
    return slug


def render_markdown(text: str, resolve=None) -> str:
    """Render a practical Markdown subset to HTML.

    Supports headings, paragraphs, fenced code, flat lists, blockquotes,
    tables, rules, and inline code/links/bold/italic. Raw HTML is escaped.
    """
    lines = text.replace("\r\n", "\n").split("\n")
    out: list[str] = []
    para: list[str] = []
    used_ids: set[str] = set()

    def inline(value: str) -> str:
        return _md_inline(value, resolve)

    def flush() -> None:
        if para:
            out.append(f"<p>{inline(' '.join(para))}</p>")
            para.clear()

    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if stripped.startswith("```"):
            flush()
            i += 1
            code = []
            while i < len(lines) and not lines[i].strip().startswith("```"):
                code.append(lines[i])
                i += 1
            out.append(f"<pre><code>{_esc(chr(10).join(code))}</code></pre>")
        elif not stripped:
            flush()
        elif m := re.match(r"^(#{1,6})\s+(.*?)\s*#*\s*$", stripped):
            flush()
            level = len(m[1])
            slug = _heading_id(m[2], used_ids)
            out.append(
                f'<h{level} id="{slug}">{inline(m[2])}'
                f'<a class="anchor" href="#{slug}" aria-label="Copy link to this section">#</a>'
                f"</h{level}>"
            )
        elif re.match(r"^([-*_])(\s*\1){2,}$", stripped):
            flush()
            out.append("<hr>")
        elif _MD_LIST_ITEM.match(line):
            flush()
            tag = "ol" if line.lstrip()[0].isdigit() else "ul"
            items = []
            while i < len(lines) and (item := _MD_LIST_ITEM.match(lines[i])):
                items.append(f"<li>{inline(item[2])}</li>")
                i += 1
            out.append(f"<{tag}>{''.join(items)}</{tag}>")
            continue
        elif stripped.startswith(">"):
            flush()
            quote_lines = []
            while i < len(lines) and lines[i].strip().startswith(">"):
                quote_lines.append(lines[i].strip().lstrip(">").strip())
                i += 1
            out.append(f"<blockquote><p>{inline(' '.join(quote_lines))}</p></blockquote>")
            continue
        elif "|" in stripped and i + 1 < len(lines) and _MD_SEPARATOR.match(lines[i + 1]):
            flush()
            head = "".join(f"<th>{inline(c)}</th>" for c in _md_cells(stripped))
            rows = []
            i += 2
            while i < len(lines) and "|" in lines[i]:
                cells = "".join(f"<td>{inline(c)}</td>" for c in _md_cells(lines[i]))
                rows.append(f"<tr>{cells}</tr>")
                i += 1
            out.append(
                f"<table><thead><tr>{head}</tr></thead><tbody>{''.join(rows)}</tbody></table>"
            )
            continue
        else:
            para.append(stripped)
        i += 1
    flush()
    return "\n".join(out) + "\n"


def doc_title(text: str, fallback: str) -> str:
    """Title of a docs page: its first H1, else ``fallback``."""
    for line in text.splitlines():
        if m := re.match(r"^#\s+(.*?)\s*#*\s*$", line.strip()):
            return _MD_MARKUP.sub(lambda mm: mm[2] or "", m[1]).strip() or fallback
    return fallback


def render_doc(
    text: str,
    fallback_title: str,
    site_title: str,
    source_url: str = "",
    footer: bool = True,
    resolve=None,
    depth: int = 0,
) -> str:
    """Render a Markdown docs page with links back to the docs index and site root.

    ``depth`` is the number of folders between the page and the docs root.
    """
    title = doc_title(text, fallback_title)
    up = "../" * depth
    header = (
        f'<p class="back"><a href="{up}../../">← {_esc(site_title)}</a>'
        f' · <a class="src" href="{up}../">All docs</a>{_source_link(source_url)}</p>\n'
    )
    return _document(
        f"{title} · {site_title}",
        header,
        f'<article class="doc">\n{render_markdown(text, resolve)}</article>\n',
        footer=footer,
        script=_asset("doc-anchor.js"),
    )


def _folder_line(slug: str) -> str:
    folder = slug.rpartition("/")[0]
    return f"<p>{_esc(folder)}/</p>" if folder else ""


def render_docs_index(
    docs: list[tuple[str, str]], site_title: str, source_url: str = "", footer: bool = True
) -> str:
    """Render the filterable index of every docs page, showing each page's folder."""
    sections = "".join(
        f'<section class="output ws" data-search="{_esc(title.lower())} {_esc(slug)}">'
        f'<h2><a href="{_esc(slug)}/">{_esc(title)}</a></h2>'
        f"{_folder_line(slug)}</section>"
        for title, slug in docs
    )
    header = (
        f'<p class="back"><a href="../">← {_esc(site_title)}</a></p>\n'
        f"<h1>Docs</h1>\n<p>{_plural(len(docs), 'page')}{_source_link(source_url)}</p>\n"
        '<input id="filter" type="search" placeholder="Filter docs…" aria-label="Filter docs">\n'
        '<p id="filter-status" class="sr-only" role="status"></p>\n'
    )
    main = f'{sections}\n<p id="no-match" class="no-match">No docs match the filter.</p>\n'
    return _document(
        f"Docs · {site_title}", header, main, script=_asset("filter.js"), footer=footer
    )


_BACK_LINK = re.compile(r"\A\[←[^\]]*\]\(([^)\s]+)\)(?:[ \t]*·[ \t]*)?")


def _strip_back_link(text: str, base: str, known: dict[str, str]) -> str:
    """Drop a leading ``[← Back ...](target)`` link whose target is not a docs page.

    Such links serve repo browsing (for example back to the root README); the
    rendered page already links back to the docs index.
    """
    match = _BACK_LINK.match(text)
    if not match:
        return text
    if posixpath.normpath(posixpath.join(base, unquote(match.group(1)))) in known:
        return text
    return text[match.end() :]


def _docs_order(slug: str, title: str) -> tuple[bool, str, bool, str]:
    """Root pages before folders; within a folder, readme/index first, then by title."""
    folder, _, leaf = slug.rpartition("/")
    return (bool(folder), folder, leaf not in ("readme", "index"), title.lower())
