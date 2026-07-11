"""Tests for the Pages-branch publisher."""

import json
from pathlib import Path

import pytest

import publish
from publish import ApiError, generate_site
from publish import main as publish_main
from publish import publish as run_publish

FIXTURES = Path(__file__).parent / "fixtures"


class FakeApi:
    """In-memory stand-in for the GitHub Git Data API."""

    def __init__(self, tip=None, manifest=None, fail_pushes=0, page_url="https://ex.io/r/"):
        self.tip = tip
        self.manifest = manifest
        self.fail_pushes = fail_pushes
        self.page_url = page_url
        self.calls = []
        self.trees = {}
        self.commits = {}
        self.pushed = []

    def __call__(self, method, path, payload=None):
        self.calls.append((method, path))
        if method == "GET" and "/git/ref/heads/" in path:
            if not self.tip:
                raise ApiError(404, "no branch")
            return {"object": {"sha": self.tip}}
        if method == "GET" and "/contents/manifest.json" in path:
            if not self.manifest:
                raise ApiError(404, "no manifest")
            import base64

            return {"content": base64.b64encode(self.manifest.encode()).decode()}
        if method == "GET" and "/git/commits/" in path:
            return {"tree": {"sha": "basetree-" + path.rsplit("/", 1)[1]}}
        if method == "POST" and path.endswith("/git/trees"):
            sha = f"tree{len(self.trees)}"
            self.trees[sha] = payload
            return {"sha": sha}
        if method == "POST" and path.endswith("/git/commits"):
            sha = f"commit{len(self.commits)}".ljust(40, "0")
            self.commits[sha] = payload
            return {"sha": sha}
        if method in ("PATCH", "POST") and "/git/refs" in path:
            if self.fail_pushes > 0:
                self.fail_pushes -= 1
                raise ApiError(422, "not a fast forward")
            self.pushed.append(payload["sha"])
            self.tip = payload["sha"]
            return {}
        if method == "GET" and path.endswith("/pages"):
            if self.page_url is None:
                raise ApiError(404, "pages not configured")
            return {"html_url": self.page_url}
        raise AssertionError(f"unexpected API call: {method} {path}")

    @property
    def last_tree(self):
        return self.trees[max(self.trees)]


@pytest.fixture
def env(monkeypatch, tmp_path):
    """Baseline publish environment writing GITHUB_OUTPUT to a temp file."""
    out = tmp_path / "github_output.txt"
    out.write_text("", encoding="utf-8")
    monkeypatch.setenv("GITHUB_REPOSITORY", "octo/infra")
    monkeypatch.setenv("PAGES_BRANCH", "gh-pages")
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    monkeypatch.setenv("GARNISH_TITLE", "Test Site")
    for var in ("GARNISH_WORKSPACES", "GARNISH_OUTPUTS_FILE", "GARNISH_OUTPUTS"):
        monkeypatch.delenv(var, raising=False)
    return out


def outputs_of(env_file: Path) -> dict:
    pairs = [line.split("=", 1) for line in env_file.read_text().splitlines() if "=" in line]
    return dict(pairs)


# ---------------------------------------------------------------------------
# generate_site
# ---------------------------------------------------------------------------


class TestGenerateSite:
    def test_outputs_file_mode(self, env, monkeypatch, tmp_path):
        monkeypatch.setenv("GARNISH_OUTPUTS_FILE", str(FIXTURES / "tofu_output_json.json"))
        site = tmp_path / "site"
        generate_site(str(site))
        assert "<title>Test Site</title>" in (site / "index.html").read_text(encoding="utf-8")

    def test_inline_outputs_mode(self, env, monkeypatch, tmp_path):
        monkeypatch.setenv("GARNISH_OUTPUTS", '{"host": "example.com"}')
        site = tmp_path / "site"
        generate_site(str(site))
        assert "example.com" in (site / "index.html").read_text(encoding="utf-8")

    def test_workspaces_mode_ignores_blank_lines(self, env, monkeypatch, tmp_path):
        monkeypatch.setenv(
            "GARNISH_WORKSPACES",
            f"\nprod={FIXTURES / 'tofu_output_json.json'}\n\n",
        )
        site = tmp_path / "site"
        generate_site(str(site))
        assert (site / "prod" / "index.html").is_file()
        assert (site / "manifest.json").is_file()

    def test_workspaces_merge_with_existing_manifest(self, env, monkeypatch, tmp_path):
        site = tmp_path / "site"
        site.mkdir()
        (site / "manifest.json").write_text(
            json.dumps({"workspaces": {"legacy": {"name": "legacy", "outputs": 1}}}),
            encoding="utf-8",
        )
        monkeypatch.setenv(
            "GARNISH_WORKSPACES", f"prod={FIXTURES / 'dflook_json_output_path.json'}"
        )
        generate_site(str(site))
        landing = (site / "index.html").read_text(encoding="utf-8")
        assert "legacy" in landing
        assert "prod" in landing

    def test_no_inputs_exits_1(self, env, capsys):
        with pytest.raises(SystemExit) as exc:
            generate_site("unused")
        assert exc.value.code == 1
        assert "must be provided" in capsys.readouterr().err

    def test_bad_input_propagates_exit_code(self, env, monkeypatch, tmp_path):
        monkeypatch.setenv("GARNISH_OUTPUTS", "{not json")
        with pytest.raises(SystemExit) as exc:
            generate_site(str(tmp_path / "site"))
        assert exc.value.code == 2


# ---------------------------------------------------------------------------
# publish
# ---------------------------------------------------------------------------


class TestPublish:
    def test_creates_branch_when_missing(self, env, monkeypatch):
        monkeypatch.setenv("GARNISH_OUTPUTS_FILE", str(FIXTURES / "tofu_output_json.json"))
        api = FakeApi(tip=None)
        assert run_publish(api=api, sleep=lambda _: None) == 0
        assert api.pushed
        create_ref = [(m, p) for m, p in api.calls if p.endswith("/git/refs")]
        assert create_ref
        assert "base_tree" not in api.last_tree
        commit = api.commits[max(api.commits)]
        assert commit["parents"] == []

    def test_updates_existing_branch_with_base_tree(self, env, monkeypatch):
        monkeypatch.setenv("GARNISH_OUTPUTS_FILE", str(FIXTURES / "tofu_output_json.json"))
        api = FakeApi(tip="a" * 40)
        assert run_publish(api=api, sleep=lambda _: None) == 0
        assert api.last_tree["base_tree"] == "basetree-" + "a" * 40
        commit = api.commits[max(api.commits)]
        assert commit["parents"] == ["a" * 40]

    def test_tree_contains_site_files(self, env, monkeypatch):
        monkeypatch.setenv("GARNISH_WORKSPACES", f"prod={FIXTURES / 'tofu_output_json.json'}")
        api = FakeApi(tip=None)
        assert run_publish(api=api, sleep=lambda _: None) == 0
        paths = sorted(entry["path"] for entry in api.last_tree["tree"])
        assert paths == [".nojekyll", "index.html", "manifest.json", "prod/index.html"]

    def test_discrete_update_merges_remote_manifest(self, env, monkeypatch):
        monkeypatch.setenv(
            "GARNISH_WORKSPACES", f"staging={FIXTURES / 'dflook_json_output_path.json'}"
        )
        manifest = json.dumps(
            {"workspaces": {"prod": {"name": "prod", "outputs": 7, "updated": "x"}}}
        )
        api = FakeApi(tip="b" * 40, manifest=manifest)
        assert run_publish(api=api, sleep=lambda _: None) == 0
        landing = next(e for e in api.last_tree["tree"] if e["path"] == "index.html")
        assert '<a href="prod/">prod</a>' in landing["content"]
        assert '<a href="staging/">staging</a>' in landing["content"]
        # prod's page is preserved via base_tree, not re-uploaded
        assert not any(e["path"] == "prod/index.html" for e in api.last_tree["tree"])

    def test_manifest_not_fetched_without_workspaces(self, env, monkeypatch):
        monkeypatch.setenv("GARNISH_OUTPUTS_FILE", str(FIXTURES / "tofu_output_json.json"))
        api = FakeApi(tip="c" * 40)
        assert run_publish(api=api, sleep=lambda _: None) == 0
        assert not any("manifest.json" in p for _, p in api.calls)

    def test_missing_remote_manifest_is_fine(self, env, monkeypatch):
        monkeypatch.setenv("GARNISH_WORKSPACES", f"prod={FIXTURES / 'tofu_output_json.json'}")
        api = FakeApi(tip="f" * 40, manifest=None)
        assert run_publish(api=api, sleep=lambda _: None) == 0
        assert any("manifest.json" in p for _, p in api.calls)

    def test_manifest_fetch_error_propagates(self, env, monkeypatch):
        monkeypatch.setenv("GARNISH_WORKSPACES", f"prod={FIXTURES / 'tofu_output_json.json'}")
        api = FakeApi(tip="a" * 40)
        original = api.__call__

        def flaky(method, path, payload=None):
            if "manifest.json" in path:
                raise ApiError(500, "server error")
            return original(method, path, payload)

        with pytest.raises(ApiError, match="500"):
            run_publish(api=flaky, sleep=lambda _: None)

    def test_push_race_retries_and_succeeds(self, env, monkeypatch):
        monkeypatch.setenv("GARNISH_OUTPUTS_FILE", str(FIXTURES / "tofu_output_json.json"))
        api = FakeApi(tip="d" * 40, fail_pushes=2)
        sleeps = []
        assert run_publish(api=api, sleep=sleeps.append) == 0
        assert len(api.pushed) == 1
        assert sleeps == [1, 2]

    def test_push_exhaustion_fails(self, env, monkeypatch, capsys):
        monkeypatch.setenv("GARNISH_OUTPUTS_FILE", str(FIXTURES / "tofu_output_json.json"))
        api = FakeApi(tip="e" * 40, fail_pushes=99)
        assert run_publish(api=api, sleep=lambda _: None) == 1
        assert "failed to push" in capsys.readouterr().err

    def test_outputs_page_url_and_site_dir(self, env, monkeypatch):
        monkeypatch.setenv("GARNISH_OUTPUTS_FILE", str(FIXTURES / "tofu_output_json.json"))
        api = FakeApi(tip=None)
        assert run_publish(api=api, sleep=lambda _: None) == 0
        outputs = outputs_of(env)
        assert outputs["page-url"] == "https://ex.io/r/"
        assert Path(outputs["site-dir"], "index.html").is_file()

    def test_pages_not_configured_gives_empty_url(self, env, monkeypatch):
        monkeypatch.setenv("GARNISH_OUTPUTS_FILE", str(FIXTURES / "tofu_output_json.json"))
        api = FakeApi(tip=None, page_url=None)
        assert run_publish(api=api, sleep=lambda _: None) == 0
        assert outputs_of(env)["page-url"] == ""

    def test_unexpected_api_error_propagates(self, env, monkeypatch):
        monkeypatch.setenv("GARNISH_OUTPUTS_FILE", str(FIXTURES / "tofu_output_json.json"))

        def api(method, path, payload=None):
            raise ApiError(500, "boom")

        with pytest.raises(ApiError):
            run_publish(api=api, sleep=lambda _: None)


# ---------------------------------------------------------------------------
# main (deploy switch)
# ---------------------------------------------------------------------------


class TestMain:
    def test_deploy_false_generates_to_output_dir(self, env, monkeypatch, tmp_path):
        site = tmp_path / "out"
        monkeypatch.setenv("GARNISH_DEPLOY", "false")
        monkeypatch.setenv("GARNISH_OUTPUT_DIR", str(site))
        monkeypatch.setenv("GARNISH_OUTPUTS_FILE", str(FIXTURES / "tofu_output_json.json"))
        assert publish_main() == 0
        assert (site / "index.html").is_file()
        assert outputs_of(env)["site-dir"] == str(site)

    def test_deploy_true_publishes(self, env, monkeypatch):
        monkeypatch.setenv("GARNISH_DEPLOY", "true")
        monkeypatch.setenv("GARNISH_OUTPUTS_FILE", str(FIXTURES / "tofu_output_json.json"))
        api = FakeApi(tip=None)
        monkeypatch.setattr(publish, "_default_api", api)
        monkeypatch.setattr(publish.time, "sleep", lambda _: None)
        assert publish_main() == 0
        assert api.pushed
