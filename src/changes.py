"""Diff the outputs being published against the previous publish.

Only the previous ``outputs.json`` (and ``.garnish-state.json``, which records which
outputs were sensitive) is consulted. Sensitive values are never compared or
stored: they are tracked by name and masked state only.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from model import Output

STATE_FILE = ".garnish-state.json"
OUTPUTS_FILE = "outputs.json"


@dataclass
class Changes:
    """Outputs added, modified or removed since the previous publish."""

    added: list[str] = field(default_factory=list)
    modified: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    sensitive: list[str] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.added) + len(self.modified) + len(self.removed)

    def status(self, name: str) -> str:
        """``added``, ``modified`` or ``""`` for an output that is still present."""
        if name in self.added:
            return "added"
        if name in self.modified:
            return "modified"
        return ""


def _read_json(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _canonical(value: object) -> str:
    """Type-preserving form: Python's == treats True as 1 and False as 0."""
    return json.dumps(value, sort_keys=True)


def compute_changes(outputs: list[Output], previous_dir: str | Path) -> Changes | None:
    """Compare ``outputs`` with the previous publish found in ``previous_dir``.

    Returns ``None`` when there is no previous ``outputs.json`` to compare with
    (first publish), so nothing is flagged as new.
    """
    previous_dir = Path(previous_dir)
    prev_values = _read_json(previous_dir / OUTPUTS_FILE)
    if not isinstance(prev_values, dict):
        return None
    prev_meta = _read_json(previous_dir / STATE_FILE)
    prev_sensitive: set[str] | None = None
    if isinstance(prev_meta, dict) and isinstance(prev_meta.get("sensitive"), list):
        prev_sensitive = {str(n) for n in prev_meta["sensitive"]}

    changes = Changes(sensitive=sorted(o.name for o in outputs if o.sensitive))
    for output in outputs:
        name = output.name
        was_sensitive = prev_sensitive is not None and name in prev_sensitive
        existed = name in prev_values or was_sensitive
        if output.sensitive:
            if name in prev_values:
                changes.modified.append(name)
            elif not existed and prev_sensitive is not None:
                changes.added.append(name)
        elif not existed:
            changes.added.append(name)
        elif was_sensitive or _canonical(prev_values[name]) != _canonical(output.value):
            changes.modified.append(name)

    current = {o.name for o in outputs}
    gone = set(prev_values) | (prev_sensitive or set())
    changes.removed = sorted(gone - current)
    return changes


def state_json(outputs: list[Output]) -> str:
    """Internal state (not a public API): sensitive names, since outputs.json omits them."""
    return (
        json.dumps({"sensitive": sorted(o.name for o in outputs if o.sensitive)}, indent=2) + "\n"
    )
