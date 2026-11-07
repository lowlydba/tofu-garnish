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
import json
import os
import posixpath
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote, unquote

from changes import STATE_FILE, compute_changes, state_json
from markdown import (
    _CONTROL_CHARS,
    _IMAGE_SUFFIXES,
    ASSETS_DIR,
    _docs_order,
    _md_href,
    _strip_back_link,
    doc_title,
    render_doc,
    render_docs_index,
    render_markdown,
)
from model import (
    DOCS_DIR,
    MASK,
    REPO_URL,
    Output,
    Page,
    Provenance,
    __version__,
    provenance_from_env,
    slugify,
)
from pages import render_landing, render_page
from parsing import apply_descriptions, outputs_json, parse_descriptions, parse_outputs

__all__ = [
    "MASK",
    "REPO_URL",
    "Page",
    "Provenance",
    "__version__",
    "_md_href",
    "apply_descriptions",
    "doc_title",
    "main",
    "parse_descriptions",
    "parse_outputs",
    "parse_workspace_spec",
    "provenance_from_env",
    "render_landing",
    "render_markdown",
    "render_page",
    "slugify",
]


def _build_docs(docs_dir: str, out_dir: Path, args: argparse.Namespace) -> list[tuple[str, str]]:
    """Render every ``*.md`` under ``docs_dir`` to ``<out>/docs/<slug>/index.html``.

    Also writes ``<out>/docs/index.html`` listing every page. Relative links
    resolve to other docs pages, mirroring the folder layout (``aws/setup.md``
    becomes ``docs/aws/setup/``); links to other repo files (such as the
    root README) point at the source repository when ``--source-url`` is set.
    Images inside the repository are copied to ``<out>/docs/.assets/`` and
    referenced from there; other image sources fall back to the source
    repository's raw file URL when ``--source-url`` is set.
    Returns ``(title, slug)`` pairs; ``README.md`` and ``index.md`` sort first.
    """
    root = Path(docs_dir)
    if not root.is_dir():
        raise ValueError(f"docs directory not found: {docs_dir}")
    pages: dict[str, tuple[str, str, str]] = {}
    for path in sorted(root.rglob("*.md")):
        slug = "/".join(slugify(part) for part in path.relative_to(root).with_suffix("").parts)
        if slug in pages:
            raise ValueError(
                f"docs page {path.name!r} clashes with another page (both map to {slug!r})"
            )
        text = path.read_text(encoding="utf-8")
        pages[slug] = (doc_title(text, path.stem), text, _repo_path(path))
    known = {repo_path: slug for slug, (_, _, repo_path) in pages.items()}

    def resolver_for(repo_path: str, depth: int):
        base = posixpath.dirname(repo_path)
        up = "../" * depth

        def resolve_image(link: str) -> str | None:
            path, query_sep, query = link.partition("?")
            decoded = unquote(path)
            if _CONTROL_CHARS.search(decoded):
                return "#"
            target = posixpath.normpath(posixpath.join(base, decoded))
            if target.startswith("..") or target.startswith("/") or Path(target).is_absolute():
                return None
            source = Path(target)
            real = source.resolve()
            if (
                source.suffix.lower() in _IMAGE_SUFFIXES
                and real.suffix.lower() in _IMAGE_SUFFIXES
                and source.is_file()
                and real.is_relative_to(Path.cwd().resolve())
            ):
                dest = docs_out / ASSETS_DIR / target
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, dest)
                return f"{up}../{ASSETS_DIR}/{quote(target)}{query_sep}{query}"
            if args.source_url:
                return f"{args.source_url.rstrip('/')}/raw/HEAD/{quote(target)}{query_sep}{query}"
            return None

        def resolve(link: str, image: bool = False) -> str | None:
            if image:
                return resolve_image(link)
            target = posixpath.normpath(posixpath.join(base, link))
            decoded = posixpath.normpath(posixpath.join(base, unquote(link)))
            if decoded in known:
                return f"{up}../{known[decoded]}/"
            if args.source_url and not target.startswith(".."):
                return f"{args.source_url.rstrip('/')}/blob/HEAD/{target}"
            return None

        return resolve

    docs_out = out_dir / DOCS_DIR
    for slug, (_, text, repo_path) in pages.items():
        text = _strip_back_link(text, posixpath.dirname(repo_path), known)
        page_dir = docs_out / slug
        page_dir.mkdir(parents=True, exist_ok=True)
        depth = slug.count("/")
        (page_dir / "index.html").write_text(
            render_doc(
                text,
                slug.rpartition("/")[2],
                args.title,
                args.source_url,
                not args.no_footer,
                resolver_for(repo_path, depth),
                depth,
            ),
            encoding="utf-8",
        )
        print(f"garnish: wrote {page_dir / 'index.html'}")
    ordered = sorted(pages.items(), key=lambda kv: _docs_order(kv[0], kv[1][0]))
    docs = [(title, slug) for slug, (title, _, _) in ordered]
    docs_out.mkdir(parents=True, exist_ok=True)
    (docs_out / "index.html").write_text(
        render_docs_index(docs, args.title, args.source_url, not args.no_footer), encoding="utf-8"
    )
    return docs


def _repo_path(path: Path) -> str:
    """POSIX path of ``path`` relative to the working directory (the repo root in Actions)."""
    return Path(os.path.relpath(path)).as_posix()


def parse_workspace_spec(spec: str) -> tuple[str, str]:
    """Parse a ``name=path`` workspace spec into its parts."""
    name, sep, path = spec.partition("=")
    name, path = name.strip(), path.strip()
    if not sep or not name or not path:
        raise ValueError(f"invalid workspace spec {spec!r}, expected 'name=path'")
    return name, path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _now() -> datetime:
    """Current UTC time, honoring SOURCE_DATE_EPOCH for reproducible builds."""
    epoch = os.environ.get("SOURCE_DATE_EPOCH")
    if epoch:
        return datetime.fromtimestamp(int(epoch), tz=UTC)
    return datetime.now(tz=UTC)


def _now_utc() -> str:
    return _now().strftime("%Y-%m-%d %H:%M UTC")


def _parse_updated(entry: dict) -> str:
    """ISO timestamp for a manifest workspace entry.

    Manifests written before ``updated_at`` existed only carry the display
    string; parse it so preserved workspaces still sort and age correctly.
    """
    updated_at = str(entry.get("updated_at", ""))
    if updated_at:
        return updated_at
    try:
        dt = datetime.strptime(str(entry.get("updated", "")), "%Y-%m-%d %H:%M UTC")
    except ValueError:
        return ""
    return dt.replace(tzinfo=UTC).isoformat()


def _load_outputs_file(path_str: str) -> list[Output]:
    path = Path(path_str)
    if not path.is_file():
        raise ValueError(f"input file not found: {path}")
    return parse_outputs(path.read_text(encoding="utf-8"))


def _load_descriptions(path_str: str) -> dict[str, str]:
    if not path_str:
        return {}
    path = Path(path_str)
    if not path.is_file():
        raise ValueError(f"descriptions file not found: {path}")
    return parse_descriptions(path.read_text(encoding="utf-8"))


def _share_base(url: str) -> str:
    """Normalize the public site URL to end in exactly one slash, or ''."""
    url = url.strip().rstrip("/")
    return f"{url}/" if url else ""


def _run_single(args: argparse.Namespace) -> int:
    try:
        if args.input == "-":
            outputs = parse_outputs(sys.stdin.read())
        else:
            outputs = _load_outputs_file(args.input)
        apply_descriptions(outputs, _load_descriptions(args.descriptions))
    except ValueError as exc:
        print(f"garnish: {exc}", file=sys.stderr)
        return 2

    out_dir = Path(args.output_dir)
    changes = compute_changes(outputs, args.previous_dir) if args.previous_dir else None
    try:
        docs = _build_docs(args.docs_dir, out_dir, args) if args.docs_dir else []
    except ValueError as exc:
        print(f"garnish: {exc}", file=sys.stderr)
        return 2

    page = Page(
        title=args.title,
        outputs=outputs,
        generated_at=_now_utc(),
        source_url=args.source_url,
        footer=not args.no_footer,
        json_href="" if args.no_outputs_json else "outputs.json",
        provenance=provenance_from_env(),
        share_url=_share_base(args.site_url),
        docs=docs,
        changes=changes,
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / "index.html"
    out_file.write_text(render_page(page), encoding="utf-8")
    if not args.no_outputs_json:
        (out_dir / "outputs.json").write_text(outputs_json(outputs), encoding="utf-8")
        (out_dir / STATE_FILE).write_text(state_json(outputs), encoding="utf-8")
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


def _read_manifest_docs(out_dir: Path) -> list[tuple[str, str]]:
    """Read the docs pages recorded in a site's manifest, if any."""
    manifest_path = out_dir / "manifest.json"
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        return [(str(d["title"]), str(d["slug"])) for d in data.get("docs", [])]
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return []


def _run_workspaces(args: argparse.Namespace) -> int:
    now = _now()
    generated_at = now.strftime("%Y-%m-%d %H:%M UTC")
    generated_iso = now.isoformat()
    provenance = provenance_from_env()
    share_base = _share_base(args.site_url)
    workspaces: list[tuple[str, str, list[Output]]] = []
    seen_slugs: dict[str, str] = {}
    try:
        descriptions = _load_descriptions(args.descriptions)
        for spec in args.workspace:
            name, path = parse_workspace_spec(spec)
            slug = slugify(name)
            if slug == DOCS_DIR:
                raise ValueError(f"workspace {name!r} maps to {DOCS_DIR!r}, which is reserved")
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
    try:
        if args.docs_dir:
            docs = _build_docs(args.docs_dir, out_dir, args)
        else:
            docs = _read_manifest_docs(out_dir) if args.merge else []
    except ValueError as exc:
        print(f"garnish: {exc}", file=sys.stderr)
        return 2

    for name, slug, outputs in workspaces:
        changes = (
            compute_changes(outputs, Path(args.previous_dir) / slug) if args.previous_dir else None
        )
        page = Page(
            title=f"{args.title} · {name}",
            outputs=outputs,
            generated_at=generated_at,
            back_href="../",
            source_url=args.source_url,
            footer=not args.no_footer,
            json_href="" if args.no_outputs_json else "outputs.json",
            provenance=provenance,
            share_url=f"{share_base}{slug}/" if share_base else "",
            docs=docs,
            changes=changes,
        )
        ws_dir = out_dir / slug
        ws_dir.mkdir(parents=True, exist_ok=True)
        (ws_dir / "index.html").write_text(render_page(page), encoding="utf-8")
        if not args.no_outputs_json:
            (ws_dir / "outputs.json").write_text(outputs_json(outputs), encoding="utf-8")
            (ws_dir / STATE_FILE).write_text(state_json(outputs), encoding="utf-8")
        merged[slug] = {
            "name": name,
            "outputs": len(outputs),
            "updated": generated_at,
            "updated_at": generated_iso,
        }
        print(f"garnish: wrote {ws_dir / 'index.html'} ({len(outputs)} outputs)")

    for entry in merged.values():
        entry["updated_at"] = _parse_updated(entry)
    # Recency first; stable sort keeps the name order for equal timestamps.
    entries = sorted(merged.items(), key=lambda kv: str(kv[1].get("name", kv[0])).lower())
    entries.sort(key=lambda kv: str(kv[1].get("updated_at", "")), reverse=True)
    landing = render_landing(
        args.title,
        [
            (
                str(entry.get("name", slug)),
                slug,
                int(entry.get("outputs", 0)),
                str(entry.get("updated", "")),
                str(entry.get("updated_at", "")),
            )
            for slug, entry in entries
        ],
        generated_at,
        source_url=args.source_url,
        footer=not args.no_footer,
        provenance=provenance,
        share_url=share_base,
        docs=docs,
    )
    (out_dir / "index.html").write_text(landing, encoding="utf-8")
    manifest = {
        "generator": "tofu-garnish",
        "version": __version__,
        "title": args.title,
        "workspaces": dict(entries),
        "docs": [{"title": title, "slug": slug} for title, slug in docs],
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
    parser.add_argument(
        "--source-url",
        default="",
        metavar="URL",
        help=(
            "URL of the repository the outputs come from. When set, a "
            "'source repository' link is rendered on every page."
        ),
    )
    parser.add_argument(
        "--site-url",
        default="",
        metavar="URL",
        help=(
            "Public base URL the site is reachable at (e.g. a custom domain "
            "such as https://labs.example.org/my-repo). When set, pages get "
            "'copy link' buttons that copy URLs under it instead of the "
            "address in the browser bar."
        ),
    )
    parser.add_argument(
        "--no-footer",
        action="store_true",
        help="Omit the tofu-garnish footer from generated pages.",
    )
    parser.add_argument(
        "--no-outputs-json",
        action="store_true",
        help="Skip writing the machine-readable outputs.json next to each page.",
    )
    parser.add_argument(
        "--docs-dir",
        default="",
        metavar="DIR",
        help=(
            "Directory of Markdown files rendered as docs pages under "
            "/docs/<name>/ and linked from the landing page and every output page."
        ),
    )
    parser.add_argument(
        "--previous-dir",
        default="",
        metavar="DIR",
        help=(
            "Directory holding the previous publish's outputs.json (and "
            ".garnish-state.json), laid out like the site. When set, outputs added, "
            "modified or removed since then are flagged."
        ),
    )
    parser.add_argument("--version", action="version", version=__version__)
    args = parser.parse_args(argv)

    if args.merge and not args.workspace:
        print("garnish: --merge requires at least one --workspace", file=sys.stderr)
        return 2
    if args.workspace:
        return _run_workspaces(args)
    return _run_single(args)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
