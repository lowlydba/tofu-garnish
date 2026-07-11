"""Tests for the tofu-garnish HTML generator."""

import json
from pathlib import Path

import pytest

import garnish
from garnish import (
    MASK,
    Page,
    main,
    parse_outputs,
    parse_workspace_spec,
    render_page,
    slugify,
)

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def render(text: str, title: str = "Test Outputs") -> str:
    return render_page(
        Page(title=title, outputs=parse_outputs(text), generated_at="2026-01-01 00:00 UTC")
    )


# ---------------------------------------------------------------------------
# Parsing: terraform/tofu output -json format
# ---------------------------------------------------------------------------


class TestParseTofuOutputJson:
    def test_names_and_values(self):
        outputs = {o.name: o for o in parse_outputs(fixture("tofu_output_json.json"))}
        assert outputs["cluster_endpoint"].value == "https://k8s.example.com:6443"
        assert outputs["instance_count"].value == 3
        assert outputs["is_production"].value is True
        assert outputs["vpc"].value["id"] == "vpc-01463b6b84e1454ce"
        assert len(outputs["subnets"].value) == 3

    def test_sensitive_flag(self):
        outputs = {o.name: o for o in parse_outputs(fixture("tofu_output_json.json"))}
        assert outputs["database_password"].sensitive is True
        assert outputs["cluster_endpoint"].sensitive is False

    def test_missing_sensitive_key_defaults_false(self):
        outputs = parse_outputs('{"a": {"value": 1}}')
        assert outputs[0].sensitive is False
        assert outputs[0].value == 1

    def test_sorted_by_name_case_insensitive(self):
        outputs = parse_outputs('{"Zeta": {"value": 1}, "alpha": {"value": 2}}')
        assert [o.name for o in outputs] == ["alpha", "Zeta"]


# ---------------------------------------------------------------------------
# Parsing: dflook json_output_path format (plain map)
# ---------------------------------------------------------------------------


class TestParseDflookFile:
    def test_plain_values(self):
        outputs = {o.name: o for o in parse_outputs(fixture("dflook_json_output_path.json"))}
        assert outputs["service_hostname"].value == "example.com"
        assert outputs["instance_count"].value == 3
        assert outputs["vpc"].value["tags"]["Team"] == "platform"

    def test_nothing_sensitive(self):
        outputs = parse_outputs(fixture("dflook_json_output_path.json"))
        assert not any(o.sensitive for o in outputs)


# ---------------------------------------------------------------------------
# Parsing: toJson(steps.<id>.outputs) format (all strings)
# ---------------------------------------------------------------------------


class TestParseDflookStepOutputs:
    def test_json_encoded_complex_values_are_decoded(self):
        outputs = {o.name: o for o in parse_outputs(fixture("dflook_step_outputs.json"))}
        assert outputs["queue_arns"].value == [
            "arn:aws:sqs:us-east-1:123456789012:orders",
            "arn:aws:sqs:us-east-1:123456789012:payments",
        ]
        assert outputs["vpc"].value["cidr_block"] == "10.0.0.0/16"

    def test_primitive_strings_stay_strings(self):
        outputs = {o.name: o for o in parse_outputs(fixture("dflook_step_outputs.json"))}
        assert outputs["listener_port"].value == "443"
        assert outputs["is_production"].value == "true"

    def test_malformed_json_ish_string_stays_string(self):
        outputs = parse_outputs('{"a": "{not json"}')
        assert outputs[0].value == "{not json"

    def test_braced_string_with_whitespace_is_decoded(self):
        outputs = parse_outputs('{"a": "  {\\"k\\": 1}  "}')
        assert outputs[0].value == {"k": 1}


# ---------------------------------------------------------------------------
# Parsing: errors and edge cases
# ---------------------------------------------------------------------------


class TestParseErrors:
    def test_invalid_json(self):
        with pytest.raises(ValueError, match="not valid JSON"):
            parse_outputs("{nope")

    def test_non_object_top_level(self):
        with pytest.raises(ValueError, match="expected a JSON object"):
            parse_outputs('["a", "b"]')

    def test_empty_object_is_ok(self):
        assert parse_outputs("{}") == []

    def test_mixed_wrapper_and_plain_treated_as_plain(self):
        # Not every value has a "value" key -> plain map format.
        outputs = {o.name: o for o in parse_outputs('{"a": {"value": 1}, "b": 2}')}
        assert outputs["a"].value == {"value": 1}
        assert outputs["b"].value == 2


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


class TestRenderScalars:
    def test_string_value(self):
        html = render('{"host": "example.com"}')
        assert "<code>example.com</code>" in html

    def test_bool_and_null(self):
        html = render('{"flag": true, "nothing": null}')
        assert "<code>true</code>" in html
        assert '<span class="null">null</span>' in html

    def test_number(self):
        html = render('{"count": 42}')
        assert "<code>42</code>" in html

    def test_copy_button_on_top_level_scalar(self):
        html = render('{"host": "example.com"}')
        assert html.count('<button class="copy"') == 1
        assert 'data-raw="example.com"' in html


class TestCopyButtons:
    def test_one_button_per_map_row(self):
        html = render('{"vpc": {"id": "vpc-123", "cidr": "10.0.0.0/16"}}')
        assert html.count('<button class="copy"') == 2

    def test_no_buttons_on_nested_leaves(self):
        # tags is nested inside vpc: its inner rows get no buttons, but the
        # vpc row's button copies the whole tags-containing structure.
        html = render('{"vpc": {"id": "vpc-123", "tags": {"Team": "platform"}}}')
        assert html.count('<button class="copy"') == 2

    def test_one_button_per_grid_row(self):
        html = render('{"subnets": [{"id": "s-1"}, {"id": "s-2"}, {"id": "s-3"}]}')
        assert html.count('<button class="copy"') == 3

    def test_row_button_copies_nested_json(self):
        html = render('{"vpc": {"tags": {"Team": "platform"}}}')
        # data-raw on the vpc row holds pretty JSON including nested leaves.
        assert "&quot;Team&quot;: &quot;platform&quot;" in html

    def test_scalar_list_items_get_buttons(self):
        html = render('{"arns": ["arn:a", "arn:b"]}')
        assert html.count('<button class="copy"') == 2
        assert 'data-raw="arn:a"' in html

    def test_bool_and_null_raw_text(self):
        html = render('{"flag": true, "nothing": null}')
        assert 'data-raw="true"' in html
        assert 'data-raw="null"' in html


class TestRenderNested:
    def test_map_becomes_kv_table(self):
        html = render('{"vpc": {"id": "vpc-123", "cidr": "10.0.0.0/16"}}')
        assert '<table class="kv">' in html
        assert '<th scope="row">id</th>' in html
        assert "<code>vpc-123</code>" in html

    def test_deeply_nested_map(self):
        html = render('{"a": {"b": {"c": "leaf"}}}')
        assert html.count('<table class="kv">') == 2
        assert "<code>leaf</code>" in html

    def test_list_of_scalars_becomes_ordered_list(self):
        html = render('{"arns": ["arn:a", "arn:b"]}')
        assert '<ol class="seq">' in html
        assert "<code>arn:a</code>" in html

    def test_list_of_objects_becomes_columnar_table(self):
        html = render(fixture("tofu_output_json.json"))
        assert '<table class="grid">' in html
        assert '<th scope="col">az</th>' in html
        assert "<code>subnet-053008016a2c1768c</code>" in html

    def test_ragged_list_of_objects_fills_missing_cells(self):
        html = render('{"items": [{"a": 1}, {"b": 2}]}')
        assert '<th scope="col">a</th>' in html
        assert '<th scope="col">b</th>' in html
        assert '<span class="empty">—</span>' in html

    def test_mixed_list_falls_back_to_ordered_list(self):
        html = render('{"items": [{"a": 1}, "plain"]}')
        assert '<ol class="seq">' in html
        assert '<table class="grid">' not in html

    def test_empty_containers(self):
        html = render('{"m": {}, "l": []}')
        assert "(empty map)" in html
        assert "(empty list)" in html


class TestSensitive:
    def test_sensitive_value_is_masked(self):
        html = render(fixture("tofu_output_json.json"))
        assert MASK in html
        assert "(sensitive)" in html

    def test_sensitive_raw_value_never_appears(self):
        html = render(fixture("tofu_output_json.json"))
        assert "s3cr3t-hunter2" not in html

    def test_sensitive_output_has_no_copy_button(self):
        html = render('{"pw": {"value": "shh", "sensitive": true}}')
        assert '<button class="copy"' not in html


class TestEscaping:
    def test_value_is_escaped(self):
        html = render(json.dumps({"xss": "<script>alert(1)</script>"}))
        assert "<script>alert(1)" not in html
        assert "&lt;script&gt;" in html

    def test_output_name_is_escaped(self):
        html = render(json.dumps({'<img src=x onerror="a">': "v"}))
        assert "<img" not in html

    def test_nested_keys_are_escaped(self):
        html = render(json.dumps({"m": {"<b>k</b>": "<i>v</i>"}}))
        assert "<b>" not in html
        assert "<i>" not in html

    def test_title_is_escaped(self):
        html = render('{"a": 1}', title="<script>bad</script>")
        assert "<script>bad" not in html


class TestPageChrome:
    def test_title_count_and_timestamp(self):
        html = render('{"a": 1, "b": 2}', title="My Stack")
        assert "<title>My Stack</title>" in html
        assert "2 outputs" in html
        assert "2026-01-01 00:00 UTC" in html

    def test_singular_output_count(self):
        html = render('{"a": 1}')
        assert "1 output ·" in html

    def test_empty_outputs_message(self):
        html = render("{}")
        assert "No outputs found." in html

    def test_filter_input_and_script_present(self):
        html = render('{"a": 1}')
        assert 'id="filter"' in html
        assert "<script>" in html

    def test_sections_have_lowercase_data_name_for_filtering(self):
        html = render('{"VPC_Id": "vpc-1"}')
        assert 'data-name="vpc_id"' in html

    def test_data_search_includes_scalar_value(self):
        html = render('{"host": "EXAMPLE.com"}')
        assert 'data-search="host example.com"' in html

    def test_data_search_includes_nested_keys_and_leaves(self):
        html = render('{"vpc": {"tags": {"Team": "Platform"}}, "subnets": [{"id": "s-1"}]}')
        assert 'data-search="vpc tags team platform"' in html
        assert 'data-search="subnets id s-1"' in html

    def test_data_search_excludes_sensitive_values(self):
        html = render('{"pw": {"value": "TopSecret", "sensitive": true}}')
        assert 'data-search="pw"' in html
        assert "topsecret" not in html.lower()

    def test_outputs_sorted_alphabetically_in_page(self):
        html = render('{"zebra": 1, "Apple": 2}')
        assert html.index('id="Apple"') < html.index('id="zebra"')


# ---------------------------------------------------------------------------
# Description convention (<name>_desc / <name>_description)
# ---------------------------------------------------------------------------


class TestDescriptionConvention:
    def test_desc_suffix_folds_into_base_output(self):
        outputs = parse_outputs(
            '{"bucket_arn": "arn:aws:s3:::b", "bucket_arn_desc": "ARN of the default bucket"}'
        )
        assert [o.name for o in outputs] == ["bucket_arn"]
        assert outputs[0].description == "ARN of the default bucket"

    def test_description_suffix_also_works(self):
        outputs = parse_outputs('{"vpc": {"id": "v-1"}, "vpc_description": "Main VPC"}')
        assert [o.name for o in outputs] == ["vpc"]
        assert outputs[0].description == "Main VPC"

    def test_orphan_desc_stays_a_normal_output(self):
        outputs = parse_outputs('{"lonely_desc": "no base output"}')
        assert [o.name for o in outputs] == ["lonely_desc"]
        assert outputs[0].description == ""

    def test_non_string_desc_not_folded(self):
        outputs = parse_outputs('{"a": 1, "a_desc": {"not": "a string"}}')
        assert [o.name for o in outputs] == ["a", "a_desc"]

    def test_sensitive_desc_not_folded(self):
        outputs = parse_outputs(
            '{"a": {"value": 1}, "a_desc": {"value": "shh", "sensitive": true}}'
        )
        assert [o.name for o in outputs] == ["a", "a_desc"]

    def test_works_in_tf_output_json_format(self):
        outputs = parse_outputs(
            '{"host": {"value": "example.com"}, "host_desc": {"value": "Public hostname"}}'
        )
        assert [o.name for o in outputs] == ["host"]
        assert outputs[0].description == "Public hostname"

    def test_description_rendered_and_escaped(self):
        html = render('{"a": 1, "a_desc": "The <b>answer</b>"}')
        assert '<p class="desc">The &lt;b&gt;answer&lt;/b&gt;</p>' in html
        assert "<b>answer</b>" not in html

    def test_description_included_in_search_index(self):
        html = render('{"a": 1, "a_desc": "Findable Phrase"}')
        assert "findable phrase" in html

    def test_no_desc_paragraph_without_description(self):
        html = render('{"a": 1}')
        assert '<p class="desc">' not in html


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


class TestCli:
    def test_file_input_writes_index_html(self, tmp_path, capsys):
        out = tmp_path / "site"
        rc = main(
            [
                "--input",
                str(FIXTURES / "tofu_output_json.json"),
                "--output-dir",
                str(out),
                "--title",
                "CLI Test",
            ]
        )
        assert rc == 0
        html = (out / "index.html").read_text(encoding="utf-8")
        assert "<title>CLI Test</title>" in html
        assert "7 outputs" in capsys.readouterr().out

    def test_stdin_input(self, tmp_path, monkeypatch):
        monkeypatch.setattr("sys.stdin", __import__("io").StringIO('{"a": "b"}'))
        out = tmp_path / "site"
        assert main(["--output-dir", str(out)]) == 0
        assert "<code>b</code>" in (out / "index.html").read_text(encoding="utf-8")

    def test_creates_nested_output_dirs(self, tmp_path):
        out = tmp_path / "deeply" / "nested" / "site"
        rc = main(
            ["--input", str(FIXTURES / "dflook_json_output_path.json"), "--output-dir", str(out)]
        )
        assert rc == 0
        assert (out / "index.html").is_file()

    def test_missing_input_file(self, tmp_path, capsys):
        rc = main(["--input", str(tmp_path / "nope.json"), "--output-dir", str(tmp_path)])
        assert rc == 2
        assert "not found" in capsys.readouterr().err

    def test_invalid_json_exit_code(self, tmp_path, capsys):
        bad = tmp_path / "bad.json"
        bad.write_text("{nope", encoding="utf-8")
        rc = main(["--input", str(bad), "--output-dir", str(tmp_path / "site")])
        assert rc == 2
        assert "not valid JSON" in capsys.readouterr().err

    def test_default_title(self, tmp_path):
        out = tmp_path / "site"
        main(["--input", str(FIXTURES / "dflook_json_output_path.json"), "--output-dir", str(out)])
        assert "<title>Tofu Outputs</title>" in (out / "index.html").read_text(encoding="utf-8")

    def test_source_date_epoch_reproducibility(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SOURCE_DATE_EPOCH", "0")
        out = tmp_path / "site"
        main(["--input", str(FIXTURES / "dflook_json_output_path.json"), "--output-dir", str(out)])
        html = (out / "index.html").read_text(encoding="utf-8")
        assert "1970-01-01 00:00 UTC" in html

    def test_version_flag(self, capsys):
        with pytest.raises(SystemExit) as exc:
            main(["--version"])
        assert exc.value.code == 0
        assert garnish.__version__ in capsys.readouterr().out


# ---------------------------------------------------------------------------
# Multi-workspace mode
# ---------------------------------------------------------------------------


class TestSlugify:
    @pytest.mark.parametrize(
        ("name", "expected"),
        [
            ("prod", "prod"),
            ("Prod US-East 1", "prod-us-east-1"),
            ("tenant/acme corp", "tenant-acme-corp"),
            ("v1.2_x", "v1.2_x"),
            ("///", "workspace"),
            ("..", "workspace"),
        ],
    )
    def test_slugs(self, name, expected):
        assert slugify(name) == expected


class TestWorkspaceSpec:
    def test_parses_name_and_path(self):
        assert parse_workspace_spec("prod=out/prod.json") == ("prod", "out/prod.json")

    def test_strips_whitespace(self):
        assert parse_workspace_spec("  prod = out.json ") == ("prod", "out.json")

    def test_path_may_contain_equals(self):
        assert parse_workspace_spec("a=b=c") == ("a", "b=c")

    @pytest.mark.parametrize("spec", ["noequals", "=path", "name=", "="])
    def test_invalid_specs(self, spec):
        with pytest.raises(ValueError, match="invalid workspace spec"):
            parse_workspace_spec(spec)


class TestMultiWorkspaceCli:
    def _run(self, tmp_path, *specs):
        out = tmp_path / "site"
        rc = main(
            ["--output-dir", str(out), "--title", "Acme Outputs"]
            + [arg for spec in specs for arg in ("--workspace", spec)]
        )
        return rc, out

    def test_builds_landing_and_per_workspace_pages(self, tmp_path):
        rc, out = self._run(
            tmp_path,
            f"prod={FIXTURES / 'tofu_output_json.json'}",
            f"staging={FIXTURES / 'dflook_json_output_path.json'}",
        )
        assert rc == 0
        landing = (out / "index.html").read_text(encoding="utf-8")
        assert "2 workspaces" in landing
        assert '<a href="prod/">prod</a>' in landing
        assert '<a href="staging/">staging</a>' in landing
        assert "7 outputs" in landing
        prod = (out / "prod" / "index.html").read_text(encoding="utf-8")
        assert "<title>Acme Outputs · prod</title>" in prod
        assert "vpc-01463b6b84e1454ce" in prod

    def test_workspace_pages_link_back_to_landing(self, tmp_path):
        rc, out = self._run(tmp_path, f"prod={FIXTURES / 'tofu_output_json.json'}")
        assert rc == 0
        page = (out / "prod" / "index.html").read_text(encoding="utf-8")
        assert '<a href="../">← all workspaces</a>' in page

    def test_single_mode_has_no_back_link(self, tmp_path):
        out = tmp_path / "site"
        main(["--input", str(FIXTURES / "tofu_output_json.json"), "--output-dir", str(out)])
        assert "all workspaces" not in (out / "index.html").read_text(encoding="utf-8")

    def test_names_are_slugged_and_escaped(self, tmp_path):
        rc, out = self._run(tmp_path, f"Prod US East={FIXTURES / 'dflook_json_output_path.json'}")
        assert rc == 0
        landing = (out / "index.html").read_text(encoding="utf-8")
        assert '<a href="prod-us-east/">Prod US East</a>' in landing
        assert (out / "prod-us-east" / "index.html").is_file()

    def test_duplicate_slug_fails(self, tmp_path, capsys):
        rc, _ = self._run(
            tmp_path,
            f"prod={FIXTURES / 'tofu_output_json.json'}",
            f"PROD={FIXTURES / 'dflook_json_output_path.json'}",
        )
        assert rc == 2
        assert "clashes" in capsys.readouterr().err

    def test_invalid_spec_fails(self, tmp_path, capsys):
        rc, _ = self._run(tmp_path, "just-a-name")
        assert rc == 2
        assert "invalid workspace spec" in capsys.readouterr().err

    def test_missing_workspace_file_fails(self, tmp_path, capsys):
        rc, _ = self._run(tmp_path, f"prod={tmp_path / 'nope.json'}")
        assert rc == 2
        assert "not found" in capsys.readouterr().err

    def test_workspace_overrides_input(self, tmp_path):
        out = tmp_path / "site"
        rc = main(
            [
                "--input",
                str(tmp_path / "does-not-exist.json"),
                "--workspace",
                f"prod={FIXTURES / 'dflook_json_output_path.json'}",
                "--output-dir",
                str(out),
            ]
        )
        assert rc == 0
        assert (out / "prod" / "index.html").is_file()

    def test_sensitive_masked_in_workspace_pages(self, tmp_path):
        rc, out = self._run(tmp_path, f"prod={FIXTURES / 'tofu_output_json.json'}")
        assert rc == 0
        page = (out / "prod" / "index.html").read_text(encoding="utf-8")
        assert "s3cr3t-hunter2" not in page
        assert MASK in page

    def test_writes_manifest(self, tmp_path):
        rc, out = self._run(tmp_path, f"prod={FIXTURES / 'tofu_output_json.json'}")
        assert rc == 0
        manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
        assert manifest["workspaces"]["prod"]["name"] == "prod"
        assert manifest["workspaces"]["prod"]["outputs"] == 7
        assert manifest["workspaces"]["prod"]["updated"]

    def test_landing_sorted_by_name(self, tmp_path):
        rc, out = self._run(
            tmp_path,
            f"zeta={FIXTURES / 'dflook_json_output_path.json'}",
            f"Alpha={FIXTURES / 'dflook_json_output_path.json'}",
        )
        assert rc == 0
        landing = (out / "index.html").read_text(encoding="utf-8")
        assert landing.index(">Alpha</a>") < landing.index(">zeta</a>")


class TestMergeMode:
    def _run(self, out, *specs, merge=True):
        argv = ["--output-dir", str(out)]
        if merge:
            argv.append("--merge")
        argv += [arg for spec in specs for arg in ("--workspace", spec)]
        return main(argv)

    def test_merge_preserves_other_workspaces(self, tmp_path):
        out = tmp_path / "site"
        assert self._run(out, f"prod={FIXTURES / 'tofu_output_json.json'}") == 0
        assert self._run(out, f"staging={FIXTURES / 'dflook_json_output_path.json'}") == 0
        landing = (out / "index.html").read_text(encoding="utf-8")
        assert '<a href="prod/">prod</a>' in landing
        assert '<a href="staging/">staging</a>' in landing
        assert (out / "prod" / "index.html").is_file()
        manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
        assert set(manifest["workspaces"]) == {"prod", "staging"}

    def test_merge_overwrites_same_workspace(self, tmp_path):
        out = tmp_path / "site"
        assert self._run(out, f"prod={FIXTURES / 'tofu_output_json.json'}") == 0
        assert self._run(out, f"prod={FIXTURES / 'dflook_json_output_path.json'}") == 0
        manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
        assert manifest["workspaces"]["prod"]["outputs"] == 4
        landing = (out / "index.html").read_text(encoding="utf-8")
        assert landing.count("<section") == 1

    def test_without_merge_landing_drops_previous(self, tmp_path):
        out = tmp_path / "site"
        assert self._run(out, f"prod={FIXTURES / 'tofu_output_json.json'}") == 0
        assert (
            self._run(out, f"staging={FIXTURES / 'dflook_json_output_path.json'}", merge=False) == 0
        )
        landing = (out / "index.html").read_text(encoding="utf-8")
        assert "prod" not in landing

    def test_corrupt_manifest_is_ignored(self, tmp_path):
        out = tmp_path / "site"
        out.mkdir()
        (out / "manifest.json").write_text("{nope", encoding="utf-8")
        assert self._run(out, f"prod={FIXTURES / 'dflook_json_output_path.json'}") == 0
        manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
        assert set(manifest["workspaces"]) == {"prod"}

    def test_landing_shows_updated_timestamp(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SOURCE_DATE_EPOCH", "0")
        out = tmp_path / "site"
        assert self._run(out, f"prod={FIXTURES / 'dflook_json_output_path.json'}") == 0
        landing = (out / "index.html").read_text(encoding="utf-8")
        assert "updated 1970-01-01 00:00 UTC" in landing

    def test_merge_requires_workspace(self, capsys):
        assert main(["--merge"]) == 2
        assert "requires at least one --workspace" in capsys.readouterr().err
