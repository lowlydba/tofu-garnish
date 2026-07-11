"""Tests for the tofu-garnish HTML generator."""

import json
from pathlib import Path

import pytest

import garnish
from garnish import MASK, Page, main, parse_outputs, render_page

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
