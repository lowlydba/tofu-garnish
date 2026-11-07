"""Parse Tofu/Terraform output JSON and descriptions."""

from __future__ import annotations

import json

from model import Output


def _looks_like_tf_output_json(data: dict) -> bool:
    """True for the ``terraform output -json`` wrapper format."""
    if not data:
        return False
    return all(isinstance(v, dict) and "value" in v for v in data.values())


def _maybe_decode_json_string(value: object) -> object:
    """Decode strings that are JSON-encoded arrays/objects.

    ``dflook/terraform-output`` step outputs encode complex types as JSON
    strings; primitives are left alone so ``"80"`` stays the string ``"80"``.
    """
    if isinstance(value, str):
        stripped = value.strip()
        if stripped[:1] in ("{", "["):
            try:
                return json.loads(stripped)
            except ValueError:
                return value
    return value


def parse_outputs(text: str) -> list[Output]:
    """Parse raw JSON text into a normalized, name-sorted list of outputs."""
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise ValueError(f"input is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(
            f"expected a JSON object mapping output names to values, got {type(data).__name__}"
        )

    outputs: list[Output] = []
    if _looks_like_tf_output_json(data):
        for name, meta in data.items():
            outputs.append(
                Output(
                    name=name,
                    value=meta["value"],
                    sensitive=bool(meta.get("sensitive", False)),
                )
            )
    else:
        for name, value in data.items():
            outputs.append(Output(name=name, value=_maybe_decode_json_string(value)))

    outputs.sort(key=lambda o: o.name.lower())
    return outputs


def parse_descriptions(text: str) -> dict[str, str]:
    """Parse output descriptions from ``tofu show -json`` configuration JSON.

    OpenTofu only: ``tofu show -json -module=DIR`` (or ``-config``) emits the
    configuration representation, whose ``root_module.outputs`` entries carry
    the ``description`` argument that ``tofu output -json`` drops. A plain
    ``{"name": "description"}`` map is accepted too.
    """
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise ValueError(f"descriptions input is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("descriptions input must be a JSON object")

    outputs = data.get("root_module", {}).get("outputs") if "root_module" in data else data
    if not isinstance(outputs, dict):
        return {}
    descriptions: dict[str, str] = {}
    for name, meta in outputs.items():
        if isinstance(meta, str):
            descriptions[name] = meta
        elif isinstance(meta, dict) and isinstance(meta.get("description"), str):
            descriptions[name] = meta["description"]
    return descriptions


def apply_descriptions(outputs: list[Output], descriptions: dict[str, str]) -> None:
    """Attach descriptions to matching outputs in place."""
    for output in outputs:
        output.description = descriptions.get(output.name, "")


def outputs_json(outputs: list[Output]) -> str:
    """Machine-readable ``outputs.json``: a plain name -> value map.

    Sensitive outputs are omitted entirely rather than masked; a placeholder
    string in machine-readable output is an automation trap.
    """
    data = {o.name: o.value for o in outputs if not o.sensitive}
    return json.dumps(data, indent=2) + "\n"
