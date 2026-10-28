"""Publish a tofu-garnish site to a GitHub Pages branch.

Stdlib only. Uses the GitHub Git Data API so no clone or git credential
plumbing is needed: creating a tree with ``base_tree`` set to the branch tip
preserves every file already on the branch and only overwrites the files
this run generates. Push races between concurrent deploys are retried
against the fresh branch tip.

Driven entirely by environment variables (set by action.yml):

* ``GARNISH_WORKSPACES`` / ``GARNISH_OUTPUTS_FILE`` / ``GARNISH_OUTPUTS`` --
  what to generate (same precedence as the action inputs).
* ``GARNISH_TITLE`` -- page title.
* ``GARNISH_SOURCE_URL`` -- repository URL rendered as a link-back on pages.
* ``GARNISH_FOOTER`` -- "true" to render the tofu-garnish footer.
* ``GARNISH_OUTPUTS_JSON`` -- "true" to write outputs.json next to each page.
* ``GARNISH_DOCS_DIR`` -- directory of Markdown files rendered as docs pages.
* ``GARNISH_DEPLOY`` -- "true" to publish; anything else only generates
  into ``GARNISH_OUTPUT_DIR``.
* ``GARNISH_OUTPUT_DIR`` -- site directory when not deploying.
* ``GARNISH_SITE_PATH`` -- branch subdirectory to publish under (e.g. a PR
  preview); empty publishes at the branch root.
* ``GARNISH_REMOVE`` -- "true" to delete ``GARNISH_SITE_PATH`` from the branch
  instead of publishing.
* ``PAGES_BRANCH`` -- branch to publish to (created if missing).
* ``GARNISH_TOKEN`` -- token with contents write access.
* ``GITHUB_REPOSITORY`` / ``GITHUB_API_URL`` / ``GITHUB_OUTPUT`` -- standard
  Actions environment. ``GITHUB_SHA`` / ``GITHUB_RUN_ID`` /
  ``GITHUB_SERVER_URL`` additionally feed the provenance links garnish
  renders in each page's meta line.
"""

from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

import garnish

COMMIT_MESSAGE = "tofu-garnish: update outputs site [skip ci]"
PUSH_ATTEMPTS = 3


class ApiError(Exception):
    """A GitHub API call failed."""

    def __init__(self, status: int, message: str):
        super().__init__(f"GitHub API error {status}: {message}")
        self.status = status


def _default_api(method: str, path: str, payload: dict | None = None) -> dict:  # pragma: no cover
    """Minimal GitHub REST client on urllib (exercised by CI integration)."""
    url = os.environ["GITHUB_API_URL"].rstrip("/") + path
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {os.environ['GARNISH_TOKEN']}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": f"tofu-garnish/{garnish.__version__}",
            **({"Content-Type": "application/json"} if data else {}),
        },
    )
    try:
        with urllib.request.urlopen(request) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise ApiError(exc.code, exc.read().decode("utf-8", "replace")) from exc


def _dump_module_descriptions(module_dir: str) -> str:
    """Run OpenTofu to extract output descriptions from a module's config.

    OpenTofu only: relies on ``tofu show -json -module=DIR`` (OpenTofu
    >= 1.10), which statically parses the module source without init, state,
    or providers. Terraform has no equivalent mode.
    """
    result = subprocess.run(
        ["tofu", "show", "-json", f"-module={module_dir}"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(
            "::error::'tofu show -json -module' failed; module-dir requires "
            f"OpenTofu >= 1.10 on PATH: {result.stderr.strip()}",
            file=sys.stderr,
        )
        raise SystemExit(1)
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as handle:
        handle.write(result.stdout)
        return handle.name


def generate_site(site_dir: str) -> None:
    """Run the garnish generator into ``site_dir`` based on the environment."""
    workspaces = os.environ.get("GARNISH_WORKSPACES", "")
    outputs_file = os.environ.get("GARNISH_OUTPUTS_FILE", "")
    outputs = os.environ.get("GARNISH_OUTPUTS", "")
    module_dir = os.environ.get("GARNISH_MODULE_DIR", "")
    title = os.environ.get("GARNISH_TITLE", "Tofu Outputs")
    source_url = os.environ.get("GARNISH_SOURCE_URL", "")
    site_url = os.environ.get("GARNISH_SITE_URL", "")
    footer = os.environ.get("GARNISH_FOOTER", "true")
    write_outputs_json = os.environ.get("GARNISH_OUTPUTS_JSON", "true")
    docs_dir = os.environ.get("GARNISH_DOCS_DIR", "")

    argv = ["--output-dir", site_dir, "--title", title]
    if docs_dir:
        argv += ["--docs-dir", docs_dir]
    if source_url:
        argv += ["--source-url", source_url]
    if site_url:
        argv += ["--site-url", site_url]
    if footer != "true":
        argv.append("--no-footer")
    if write_outputs_json != "true":
        argv.append("--no-outputs-json")
    if module_dir:
        argv += ["--descriptions", _dump_module_descriptions(module_dir)]
    if workspaces.strip():
        for line in workspaces.splitlines():
            if line.strip():
                argv += ["--workspace", line.strip()]
        argv.append("--merge")
    elif outputs_file:
        argv += ["--input", outputs_file]
    elif outputs:
        with tempfile.NamedTemporaryFile(
            "w", suffix=".json", delete=False, encoding="utf-8"
        ) as handle:
            handle.write(outputs)
            argv += ["--input", handle.name]
    else:
        print(
            "::error::one of 'workspaces', 'outputs-file' or 'outputs' must be provided",
            file=sys.stderr,
        )
        raise SystemExit(1)

    code = garnish.main(argv)
    if code != 0:
        raise SystemExit(code)


def _site_prefix() -> str:
    """Branch subdirectory the site is published under ('' for the root)."""
    parts = [p for p in os.environ.get("GARNISH_SITE_PATH", "").replace("\\", "/").split("/") if p]
    if any(p in (".", "..") for p in parts):
        print("::error::site-path must not contain '.' or '..' segments", file=sys.stderr)
        raise SystemExit(1)
    return "/".join(parts)


def _collect_files(site_dir: Path, prefix: str = "") -> list[dict]:
    """Build Git tree entries for every file under ``site_dir``."""
    base = f"{prefix}/" if prefix else ""
    return [
        {
            "path": base + path.relative_to(site_dir).as_posix(),
            "mode": "100644",
            "type": "blob",
            "content": path.read_text(encoding="utf-8"),
        }
        for path in sorted(site_dir.rglob("*"))
        if path.is_file()
    ]


def _branch_tip(api, repo: str, branch: str) -> str | None:
    try:
        ref = api("GET", f"/repos/{repo}/git/ref/heads/{branch}")
        return ref["object"]["sha"]
    except ApiError as exc:
        if exc.status == 404:
            return None
        raise


def _seed_manifest(api, repo: str, branch: str, site_dir: Path, prefix: str = "") -> None:
    """Copy the branch's manifest.json into ``site_dir`` so --merge sees it."""
    base = f"{prefix}/" if prefix else ""
    try:
        data = api("GET", f"/repos/{repo}/contents/{base}manifest.json?ref={branch}")
    except ApiError as exc:
        if exc.status == 404:
            return
        raise
    content = base64.b64decode(data.get("content", "") or "")
    (site_dir / "manifest.json").write_bytes(content)


def _set_output(name: str, value: str) -> None:
    output_path = os.environ.get("GITHUB_OUTPUT")
    if output_path:
        with open(output_path, "a", encoding="utf-8") as handle:
            handle.write(f"{name}={value}\n")


def publish(api=None, sleep=None) -> int:
    """Generate the site and commit it to the Pages branch."""
    api = api or _default_api
    sleep = sleep or time.sleep
    repo = os.environ["GITHUB_REPOSITORY"]
    branch = os.environ["PAGES_BRANCH"]
    merge_mode = bool(os.environ.get("GARNISH_WORKSPACES", "").strip())
    prefix = _site_prefix()

    def build(tip):
        site_dir = Path(tempfile.mkdtemp(prefix="tofu-garnish-"))
        if tip and merge_mode:
            _seed_manifest(api, repo, branch, site_dir, prefix)
        generate_site(str(site_dir))
        (site_dir / ".nojekyll").write_text("", encoding="utf-8")
        _set_output("site-dir", str(site_dir))
        return _collect_files(site_dir, prefix)

    if not _commit_with_retry(api, sleep, repo, branch, build):
        return 1

    try:
        pages = api("GET", f"/repos/{repo}/pages")
        url = pages.get("html_url") or ""
        if url and prefix:
            url = f"{url.rstrip('/')}/{prefix}/"
        _set_output("page-url", url)
    except ApiError:
        _set_output("page-url", "")
    return 0


def _commit_with_retry(api, sleep, repo: str, branch: str, build) -> bool:
    """Commit ``build(tip)`` tree entries onto the branch, retrying push races.

    ``build`` receives the current branch tip (or None) and returns Git tree
    entries; an empty list means there is nothing to commit.
    """
    for attempt in range(1, PUSH_ATTEMPTS + 1):
        tip = _branch_tip(api, repo, branch)
        entries = build(tip)
        if not entries:
            print("publish: nothing to commit")
            return True
        try:
            payload: dict = {"tree": entries}
            if tip:
                commit = api("GET", f"/repos/{repo}/git/commits/{tip}")
                payload["base_tree"] = commit["tree"]["sha"]
            tree = api("POST", f"/repos/{repo}/git/trees", payload)
            new_commit = api(
                "POST",
                f"/repos/{repo}/git/commits",
                {
                    "message": COMMIT_MESSAGE,
                    "tree": tree["sha"],
                    "parents": [tip] if tip else [],
                },
            )
            if tip:
                api(
                    "PATCH",
                    f"/repos/{repo}/git/refs/heads/{branch}",
                    {"sha": new_commit["sha"]},
                )
            else:
                api(
                    "POST",
                    f"/repos/{repo}/git/refs",
                    {"ref": f"refs/heads/{branch}", "sha": new_commit["sha"]},
                )
            print(f"publish: pushed {new_commit['sha'][:7]} to '{branch}'")
            return True
        except ApiError as exc:
            if attempt == PUSH_ATTEMPTS:
                print(f"::error::failed to push to '{branch}': {exc}", file=sys.stderr)
                return False
            print(f"publish: push conflicted (attempt {attempt}), retrying: {exc}")
            sleep(attempt)
    return False  # pragma: no cover


def remove(api=None, sleep=None) -> int:
    """Delete everything under ``site-path`` from the Pages branch."""
    api = api or _default_api
    sleep = sleep or time.sleep
    repo = os.environ["GITHUB_REPOSITORY"]
    branch = os.environ["PAGES_BRANCH"]
    prefix = _site_prefix()
    if not prefix:
        print(
            "::error::remove requires 'site-path' (refusing to wipe the site root)", file=sys.stderr
        )
        return 1

    def build(tip):
        if not tip:
            return []
        commit = api("GET", f"/repos/{repo}/git/commits/{tip}")
        tree = api("GET", f"/repos/{repo}/git/trees/{commit['tree']['sha']}?recursive=1")
        return [
            {"path": item["path"], "mode": item["mode"], "type": "blob", "sha": None}
            for item in tree.get("tree", [])
            if item.get("type") == "blob" and item["path"].startswith(f"{prefix}/")
        ]

    return 0 if _commit_with_retry(api, sleep, repo, branch, build) else 1


def main() -> int:
    if os.environ.get("GARNISH_REMOVE", "false") == "true":
        return remove()
    if os.environ.get("GARNISH_DEPLOY", "true") == "true":
        return publish()
    site_dir = os.environ.get("GARNISH_OUTPUT_DIR", "tofu-garnish-site")
    generate_site(site_dir)
    _set_output("site-dir", site_dir)
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
