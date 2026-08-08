[← Back to README](../README.md) · [Tutorial](tutorial.md) · [How-to guides](how-to-guides.md) · [Explanation](explanation.md)

# Reference

## Action inputs

| Input          | Required | Default             | Description                                                                                                                                    |
| -------------- | -------- | ------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------- |
| `outputs-file` | no*      | none                | Path to a JSON outputs file: the `json_output_path` file from `dflook/terraform-output`, or the output of `tofu output -json`.                   |
| `outputs`      | no*      | none                | Inline JSON string of outputs, e.g. `toJson(steps.<id>.outputs)` from a `dflook/terraform-output` step. Ignored if `outputs-file` is set.        |
| `workspaces`   | no*      | none                | Multiline `name=path` pairs for multi-workspace sites. Only the named workspaces are overwritten on deploy. Takes precedence over other inputs.  |
| `module-dir`   | no       | none                | **OpenTofu ≥ 1.10 only.** Root module directory; descriptions are extracted with `tofu show -json -module` and rendered on the page.             |
| `title`        | no       | `Tofu Outputs`      | Title shown on the generated page(s).                                                                                                            |
| `source-repo-url` | no    | current repository  | URL of the repo the outputs come from, rendered as a "source repository" link on each page. Set to `""` to omit the link.                        |
| `footer`       | no       | `"true"`            | Render the "Served with 💚 by 🌿 tofu-garnish" footer (links to this repo) on generated pages. Set `"false"` to omit it.                          |
| `outputs-json` | no       | `"true"`            | Write a machine-readable `outputs.json` next to each generated page (sensitive outputs omitted). Set `"false"` to publish HTML only.             |
| `output-dir`   | no       | `tofu-garnish-site` | Where the site is written when `deploy` is `"false"`.                                                                                            |
| `deploy`       | no       | `"true"`            | Commit the site to the Pages branch. Set `"false"` to only generate HTML.                                                                        |
| `pages-branch` | no       | `gh-pages`          | Branch GitHub Pages serves from. Created automatically if missing.                                                                               |
| `github-token` | no       | `github.token`      | Token used to read and push the Pages branch (needs `contents: write`).                                                                          |

\* Exactly one of `workspaces`, `outputs-file`, or `outputs` must be
provided; the action fails if all are empty.

## Action outputs

| Output     | Description                                                        |
| ---------- | ------------------------------------------------------------------ |
| `page-url` | URL of the GitHub Pages site (empty when `deploy` is `"false"`).   |
| `site-dir` | Directory containing the generated `index.html`.                   |

## Accepted input formats

Format detection is automatic:

1. **`tofu output -json` / `terraform output -json`**: each output wrapped
   in `{"value": …, "type": …, "sensitive": …}`. Sensitive outputs are
   masked.
2. **Plain map**: `{"name": value, …}`, as written by the
   `json_output_path` file from `dflook/terraform-output`.
3. **String map**: `{"name": "value-or-JSON-string", …}`, as produced by
   `toJson(steps.<id>.outputs)`. Strings that look like JSON arrays/objects
   are decoded; primitive strings are left untouched.

## Site structure (workspaces mode)

```text
gh-pages
├── .nojekyll
├── index.html        # landing page listing all workspaces
├── manifest.json     # machine-readable workspace index (used for merging)
├── prod-us/
│   ├── index.html
│   └── outputs.json  # machine-readable outputs for this workspace
└── staging/
    ├── index.html
    └── outputs.json
```

Workspace names are slugged for directory safety (`Prod US` → `prod-us/`);
two names that slug identically are rejected.

## Machine-readable outputs.json

Written next to every `index.html`, in single and workspaces mode (disable
with the `outputs-json` input or `--no-outputs-json`). The shape is a
contract:

* A single JSON object mapping output name → value, exactly as parsed from
  the input (nested values stay nested).
* Sensitive outputs are omitted entirely, not masked; placeholder strings in
  machine-readable output are an automation trap.
* Pretty-printed, UTF-8, trailing newline.

## Workflow requirements (when deploying)

* Job permission `contents: write` (or a `github-token` that has it).
* GitHub Pages source set to **Deploy from a branch** → your `pages-branch`.
* A shared `concurrency` group if multiple workflows may deploy at once.

## CLI reference

```text
usage: garnish [-h] [--input INPUT] [--workspace NAME=PATH] [--merge]
               [--output-dir OUTPUT_DIR] [--title TITLE] [--version]

--input       Path to a JSON outputs file, or '-' for stdin (default).
--workspace   Named outputs file, repeatable; builds a multi-workspace site.
--descriptions  JSON from OpenTofu's 'tofu show -json -module=DIR' (or a
                plain {"name": "description"} map); rendered under each
                output. OpenTofu only.
--merge       Preserve workspaces recorded in the output dir's manifest.json.
--output-dir  Directory to write the site into (default: site).
--title       Page title (default: 'Tofu Outputs').
```

Exit codes: `0` success, `2` bad input (missing file, invalid JSON,
non-object top level, bad workspace spec, or clashing workspace names).
