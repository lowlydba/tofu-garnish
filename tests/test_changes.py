"""Tests for diffing outputs against the previous publish."""

import json

import garnish
from changes import compute_changes
from model import Output


def _prev(tmp_path, values, sensitive=None):
    (tmp_path / "outputs.json").write_text(json.dumps(values), encoding="utf-8")
    if sensitive is not None:
        (tmp_path / ".garnish-state.json").write_text(json.dumps({"sensitive": sensitive}))
    return tmp_path


def test_no_previous_returns_none(tmp_path):
    assert compute_changes([Output("a", 1)], tmp_path) is None


def test_added_modified_removed(tmp_path):
    prev = _prev(tmp_path, {"keep": 1, "edit": "x", "gone": 2})
    outs = [Output("keep", 1), Output("edit", "y"), Output("new", 3)]
    c = compute_changes(outs, prev)
    assert (c.added, c.modified, c.removed, c.count) == (["new"], ["edit"], ["gone"], 3)


def test_sensitive_never_compared_by_value(tmp_path):
    prev = _prev(tmp_path, {"a": 1}, sensitive=["secret", "old_secret"])
    outs = [Output("a", 1), Output("secret", "new-value", sensitive=True)]
    c = compute_changes(outs, prev)
    assert c.added == [] and c.modified == []
    assert c.removed == ["old_secret"]


def test_sensitive_added_and_masked_transition(tmp_path):
    prev = _prev(tmp_path, {"a": 1}, sensitive=[])
    outs = [Output("a", 1, sensitive=True), Output("s", "v", sensitive=True)]
    c = compute_changes(outs, prev)
    assert c.modified == ["a"] and c.added == ["s"]


def test_unsensitive_after_sensitive_is_modified(tmp_path):
    prev = _prev(tmp_path, {}, sensitive=["a"])
    assert compute_changes([Output("a", 1)], prev).modified == ["a"]


def test_missing_changes_json_does_not_flag_sensitive(tmp_path):
    prev = _prev(tmp_path, {"a": 1})
    outs = [Output("a", 1), Output("s", "v", sensitive=True)]
    assert compute_changes(outs, prev).count == 0


def test_bool_to_number_is_a_change(tmp_path):
    prev = _prev(tmp_path, {"flag": True, "n": 0, "nested": {"x": [False]}})
    outs = [Output("flag", 1), Output("n", False), Output("nested", {"x": [0]})]
    assert compute_changes(outs, prev).modified == ["flag", "n", "nested"]


def test_destroyed_cards_are_filterable(tmp_path):
    prev = tmp_path / "prev"
    prev.mkdir()
    _prev(prev, {"Gone": 1})
    src = tmp_path / "in.json"
    src.write_text(json.dumps({"a": 1}))
    out = tmp_path / "site"
    garnish.main(["--input", str(src), "--output-dir", str(out), "--previous-dir", str(prev)])
    html = (out / "index.html").read_text(encoding="utf-8")
    assert 'class="removed" data-search="gone"' in html
    assert "section.output, section.removed" in html


def test_cli_renders_badges_and_files(tmp_path):
    prev = tmp_path / "prev"
    prev.mkdir()
    _prev(prev, {"a": 1, "b": 2})
    src = tmp_path / "in.json"
    src.write_text(json.dumps({"a": 9, "c": 3}))
    out = tmp_path / "site"
    assert (
        garnish.main(["--input", str(src), "--output-dir", str(out), "--previous-dir", str(prev)])
        == 0
    )
    html = (out / "index.html").read_text(encoding="utf-8")
    assert "2 outputs changed" not in html and "3 outputs changed" in html
    assert 'class="badge added"' in html and 'class="badge modified"' in html
    assert ">created</span>" in html and ">updated</span>" in html
    assert "not exact apply times" in html
    assert 'class="badge destroyed"' in html
    changes = json.loads((out / ".garnish-state.json").read_text())
    assert changes == {"sensitive": []}


def test_no_previous_dir_has_no_badges(tmp_path):
    src = tmp_path / "in.json"
    src.write_text(json.dumps({"a": 1}))
    out = tmp_path / "site"
    garnish.main(["--input", str(src), "--output-dir", str(out)])
    assert "changed" not in (out / "index.html").read_text(encoding="utf-8")
