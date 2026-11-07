"""Render output values as an HTML tree."""

from __future__ import annotations

import html
import json
from urllib.parse import quote

from model import CHECK_MARK, COPY_ICON, LINK_ICON, MASK, Output

# Badge wording follows OpenTofu's plan vocabulary.
_BADGE_LABELS = {"added": "created", "modified": "updated"}
CHANGE_HINT = (
    "Compared with the previous publish of this site. This shows differences between "
    "publishes, not exact apply times: several applies may have happened in between."
)


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


def _copy_button(value: object, label: str = "value") -> str:
    name = f"'{label}'" if label != "value" else label
    tip = _esc(f"Copy {name}" if _is_scalar(value) else f"Copy {name} as JSON")
    return (
        f'<button class="copy" type="button" title="{tip}" aria-label="{tip}" '
        f'data-done="{CHECK_MARK}" data-raw="{_esc(_raw_text(value))}">{COPY_ICON}</button>'
    )


def _render_node(key: str | None, value: object, depth: int) -> str:
    """One tree node: a leaf row, or a collapsible branch for maps and lists.

    ``key`` is ``None`` for list items, which get a bullet instead of an index so
    they can't be mistaken for map keys.
    """
    if key is None:
        label = '<span class="k item" aria-hidden="true">\u2022</span>'
        copy = _copy_button(value, "item")
    else:
        label = f'<span class="k">{_esc(key)}</span>'
        copy = _copy_button(value, key)
    if _is_scalar(value):
        body = _render_scalar(value)
    elif not value:
        body = f'<span class="empty">({"empty map" if isinstance(value, dict) else "empty list"})</span>'
    else:
        hint = f"{{{len(value)}}}" if isinstance(value, dict) else f"[{len(value)}]"
        open_attr = " open" if depth <= 1 else ""
        if key is None:
            label = ""
        return (
            f'<li><details{open_attr}><summary>{label}<span class="hint">{hint}</span>{copy}'
            f"</summary>{_render_children(value, depth + 1)}</details></li>"
        )
    return f'<li><div class="row">{label}<span class="v">{body}</span>{copy}</div></li>'


def _render_children(value: dict | list, depth: int) -> str:
    items = value.items() if isinstance(value, dict) else ((None, v) for v in value)
    return f'<ul class="tree" role="list">{"".join(_render_node(k if k is None else str(k), v, depth) for k, v in items)}</ul>'


def _render_value(value: object, depth: int = 0) -> str:
    if _is_scalar(value):
        return _render_scalar(value)
    if not value:
        return f'<span class="empty">({"empty map" if isinstance(value, dict) else "empty list"})</span>'
    return _render_children(value, depth)


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


def _link_button(url: str, label: str, cls: str = "copy", done: str = "") -> str:
    done_attr = f' data-done="{done}"' if done else ""
    return (
        f'<button class="{cls}" type="button" title="Copy shareable link" '
        f'aria-label="Copy shareable link" data-raw="{_esc(url)}"{done_attr}>{label}</button>'
    )


def _render_output(output: Output, share_url: str = "", change: str = "") -> str:
    if output.sensitive:
        body = f'<span class="sensitive"><span aria-hidden="true">{MASK}</span> <em>(sensitive)</em></span>'
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
    share = (
        _link_button(f"{share_url}#{quote(output.name)}", LINK_ICON, "copy anchor", CHECK_MARK)
        if share_url
        else ""
    )
    badge = (
        f' <span class="badge {change}" title="{_esc(CHANGE_HINT)}">{_BADGE_LABELS[change]}</span>'
        if change
        else ""
    )
    return (
        f'<section class="output" id="{_esc(output.name)}" '
        f'data-name="{_esc(output.name.lower())}" data-search="{_esc(search)}">'
        f'<h2>{share}<a href="#{_esc(output.name)}">{_esc(output.name)}</a>{badge}</h2>'
        f"{desc}{body}</section>"
    )
