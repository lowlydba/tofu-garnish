"""Shared constants, data classes and small helpers."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

__version__ = "1.0.0"

REPO_URL = "https://github.com/lowlydba/tofu-garnish"

# Site subdirectory holding rendered docs pages; reserved, so no workspace may use it.
DOCS_DIR = "docs"

MASK = "••••••••"
LINK_ICON = "\U0001f517"
CHECK_MARK = "\u2713"
COPY_ICON = (
    '<svg viewBox="0 0 16 16" width="12" height="12" fill="currentColor" aria-hidden="true">'
    '<path d="M0 6.75C0 5.784.784 5 1.75 5h1.5a.75.75 0 0 1 0 1.5h-1.5a.25.25 0 0 0-.25.25v7.5'
    "c0 .138.112.25.25.25h7.5a.25.25 0 0 0 .25-.25v-1.5a.75.75 0 0 1 1.5 0v1.5A1.75 1.75 0 0 1 "
    '9.25 16h-7.5A1.75 1.75 0 0 1 0 14.25Z"/>'
    '<path d="M5 1.75C5 .784 5.784 0 6.75 0h7.5C15.216 0 16 .784 16 1.75v7.5A1.75 1.75 0 0 1 '
    "14.25 11h-7.5A1.75 1.75 0 0 1 5 9.25Zm1.75-.25a.25.25 0 0 0-.25.25v7.5c0 .138.112.25.25.25"
    'h7.5a.25.25 0 0 0 .25-.25v-7.5a.25.25 0 0 0-.25-.25Z"/></svg>'
)


@dataclass
class Output:
    """A single normalized root-module output."""

    name: str
    value: object
    sensitive: bool = False
    description: str = ""


@dataclass(frozen=True)
class Provenance:
    """Commit and workflow run that produced a publish."""

    commit_sha: str
    commit_url: str
    run_url: str = ""


@dataclass
class Page:
    """Everything needed to render the page."""

    title: str
    outputs: list[Output] = field(default_factory=list)
    generated_at: str = ""
    back_href: str = ""
    source_url: str = ""
    footer: bool = True
    json_href: str = ""
    provenance: Provenance | None = None
    share_url: str = ""
    docs: list[tuple[str, str]] = field(default_factory=list)


def provenance_from_env() -> Provenance | None:
    """Build provenance from the standard Actions environment, if present.

    Requires ``GITHUB_SHA``, ``GITHUB_REPOSITORY`` and ``GITHUB_SERVER_URL``;
    outside Actions (plain CLI use) these are absent and provenance is
    omitted. The run link additionally needs ``GITHUB_RUN_ID``.
    """
    sha = os.environ.get("GITHUB_SHA", "")
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    server = os.environ.get("GITHUB_SERVER_URL", "").rstrip("/")
    if not (sha and repo and server):
        return None
    run_id = os.environ.get("GITHUB_RUN_ID", "")
    return Provenance(
        commit_sha=sha,
        commit_url=f"{server}/{repo}/commit/{sha}",
        run_url=f"{server}/{repo}/actions/runs/{run_id}" if run_id else "",
    )


def slugify(name: str) -> str:
    """Turn a workspace name into a safe directory name."""
    slug = re.sub(r"[^a-z0-9._-]+", "-", name.lower()).strip("-.")
    return slug or "workspace"
