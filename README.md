<p align="center">
  <img src="docs/hero.svg" alt="tofu-garnish: Tofu outputs, plated as a static page" width="800">
</p>

<p align="center">
  <a href="https://github.com/lowlydba/tofu-garnish/actions/workflows/ci.yml"><img alt="CI" src="https://img.shields.io/github/actions/workflow/status/lowlydba/tofu-garnish/ci.yml?branch=main&label=CI&logo=github"></a>
  <a href="LICENSE"><img alt="License" src="https://img.shields.io/github/license/lowlydba/tofu-garnish"></a>
  <a href="https://github.com/lowlydba/tofu-garnish/releases"><img alt="Release" src="https://img.shields.io/github/v/release/lowlydba/tofu-garnish?logo=github&sort=semver"></a>
  <a href="https://docs.zizmor.sh"><img alt="zizmor: pedantic" src="https://img.shields.io/badge/zizmor-pedantic-green?logo=githubactions&logoColor=white"></a>
  <img alt="Python" src="https://img.shields.io/badge/python-3.9%2B-blue?logo=python&logoColor=white">
</p>

# tofu-garnish 🌿

Turn OpenTofu/Terraform outputs into a simple, readable static page on your
repo's GitHub Pages — so engineers can find that ARN without running `tofu
output` or spelunking through state.

Plug-and-play with [dflook/terraform-github-actions][dflook]. Supports many
discrete applies (workspaces, accounts, tenants) publishing to one site
without clobbering each other.

---

This README follows the [Diátaxis](https://diataxis.fr/) framework:
[Tutorial](#tutorial) · [How-to guides](#how-to-guides) ·
[Reference](#reference) · [Explanation](#explanation)

## Tutorial

*Publish your Tofu outputs to GitHub Pages in about five minutes.*

### 1. Add a workflow

Create `.github/workflows/publish-outputs.yml`:

```yaml
name: Publish Tofu outputs

on:
  push:
    branches: [main]

permissions: {}

jobs:
  publish:
    runs-on: ubuntu-latest
    permissions:
      contents: write  # push the generated site to the Pages branch
    steps:
      - uses: actions/checkout@v7
        with:
          persist-credentials: false

      - name: Get outputs
        uses: dflook/terraform-output@v2
        id: tf-outputs
        with:
          path: my-terraform-config

      - name: Publish outputs page
        uses: lowlydba/tofu-garnish@v1
        id: garnish
        with:
          outputs-file: ${{ steps.tf-outputs.outputs.json_output_path }}
          title: My Stack Outputs
```

Push to `main` and let it run once — this creates the `gh-pages` branch.

### 2. Enable GitHub Pages for the branch

In your repository: **Settings → Pages → Build and deployment → Source →
Deploy from a branch**, then pick `gh-pages` / `/ (root)`.

### 3. Visit your page

Open the site URL shown in the Pages settings (also available as the
`page-url` action output on later runs). You'll see each output rendered as
a card: maps as key/value tables, lists of objects as proper columnar tables,
one copy button per row (nested values copy as pretty JSON), and a filter box
that matches names, keys, and values.

That's it. Every push regenerates and republishes the page.

## How-to guides

### Publish multiple workspaces, accounts, or tenants

Use the `workspaces` input — one `name=path` pair per line. Each workspace
gets its own page under `/<name>/`, plus a landing page linking them all:

```yaml
      - uses: lowlydba/tofu-garnish@v1
        with:
          title: Platform Outputs
          workspaces: |
            prod-us=prod-us-outputs.json
            prod-eu=prod-eu-outputs.json
            staging=staging-outputs.json
```

### Update one workspace without touching the others

Different applies for different tenants usually run in different workflows,
at different times. That's fine: in `workspaces` mode, each deploy only
overwrites the workspaces it names and rebuilds the landing page — everything
else already on the site is preserved. So the workflow that applies `prod-eu`
just publishes `prod-eu`:

```yaml
      - name: Get outputs
        uses: dflook/terraform-output@v2
        id: tf-outputs
        with:
          path: infra
          workspace: prod-eu

      - uses: lowlydba/tofu-garnish@v1
        with:
          title: Platform Outputs
          workspaces: |
            prod-eu=${{ steps.tf-outputs.outputs.json_output_path }}
```

If several such workflows can run at the same moment, serialize the deploys
with a shared concurrency group:

```yaml
concurrency:
  group: tofu-garnish
  cancel-in-progress: false
```

### Use it without dflook actions

Pipe `tofu output -json` (or `terraform output -json`) to a file and point
the action at it:

```yaml
      - name: Export outputs
        run: tofu output -json > outputs.json
        working-directory: my-terraform-config

      - uses: lowlydba/tofu-garnish@v1
        with:
          outputs-file: outputs.json
```

Sensitive outputs are automatically masked on the page (see
[Explanation](#sensitive-values)).

### Pass outputs inline instead of a file

Any `dflook/terraform-output` step's outputs can be passed straight through
as JSON — complex values arrive as JSON-encoded strings and are unpacked
automatically:

```yaml
      - uses: lowlydba/tofu-garnish@v1
        with:
          outputs: ${{ toJson(steps.tf-outputs.outputs) }}
```

### Generate the HTML without deploying

Set `deploy: "false"` and do whatever you like with the site directory —
upload it elsewhere, attach it as an artifact, or serve it from another
host:

```yaml
      - uses: lowlydba/tofu-garnish@v1
        id: garnish
        with:
          outputs-file: outputs.json
          deploy: "false"

      - uses: actions/upload-artifact@v4
        with:
          name: outputs-page
          path: ${{ steps.garnish.outputs.site-dir }}
```

### Run the generator locally

The generator is a single stdlib-only Python script — no dependencies to
install:

```console
$ tofu output -json | python3 src/garnish.py --title "My Stack" --output-dir site
garnish: wrote site/index.html (7 outputs)
```

Multi-workspace sites work locally too, with `--workspace name=path`
(repeatable) and `--merge` to preserve workspaces already in the output
directory. Set `SOURCE_DATE_EPOCH` for a reproducible timestamp.

## Reference

### Action inputs

| Input          | Required | Default             | Description                                                                                                                                    |
| -------------- | -------- | ------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------- |
| `outputs-file` | no*      | —                   | Path to a JSON outputs file: the `json_output_path` file from `dflook/terraform-output`, or the output of `tofu output -json`.                   |
| `outputs`      | no*      | —                   | Inline JSON string of outputs, e.g. `toJson(steps.<id>.outputs)` from a `dflook/terraform-output` step. Ignored if `outputs-file` is set.        |
| `workspaces`   | no*      | —                   | Multiline `name=path` pairs for multi-workspace sites. Only the named workspaces are overwritten on deploy. Takes precedence over other inputs.  |
| `title`        | no       | `Tofu Outputs`      | Title shown on the generated page(s).                                                                                                            |
| `output-dir`   | no       | `tofu-garnish-site` | Where the site is written when `deploy` is `"false"`.                                                                                            |
| `deploy`       | no       | `"true"`            | Commit the site to the Pages branch. Set `"false"` to only generate HTML.                                                                        |
| `pages-branch` | no       | `gh-pages`          | Branch GitHub Pages serves from. Created automatically if missing.                                                                               |
| `github-token` | no       | `github.token`      | Token used to read and push the Pages branch (needs `contents: write`).                                                                          |

\* Exactly one of `workspaces`, `outputs-file`, or `outputs` must be
provided; the action fails if all are empty.

### Action outputs

| Output     | Description                                                        |
| ---------- | ------------------------------------------------------------------ |
| `page-url` | URL of the GitHub Pages site (empty when `deploy` is `"false"`).   |
| `site-dir` | Directory containing the generated `index.html`.                   |

### Accepted input formats

Format detection is automatic:

1. **`tofu output -json` / `terraform output -json`** — each output wrapped
   in `{"value": …, "type": …, "sensitive": …}`. Sensitive outputs are
   masked.
2. **Plain map** — `{"name": value, …}`, as written by the
   `json_output_path` file from `dflook/terraform-output`.
3. **String map** — `{"name": "value-or-JSON-string", …}`, as produced by
   `toJson(steps.<id>.outputs)`. Strings that look like JSON arrays/objects
   are decoded; primitive strings are left untouched.

### Site structure (workspaces mode)

```text
gh-pages
├── .nojekyll
├── index.html        # landing page listing all workspaces
├── manifest.json     # machine-readable workspace index (used for merging)
├── prod-us/index.html
└── staging/index.html
```

Workspace names are slugged for directory safety (`Prod US` → `prod-us/`);
two names that slug identically are rejected.

### Workflow requirements (when deploying)

* Job permission `contents: write` (or a `github-token` that has it).
* GitHub Pages source set to **Deploy from a branch** → your `pages-branch`.
* A shared `concurrency` group if multiple workflows may deploy at once.

### CLI reference

```text
usage: garnish [-h] [--input INPUT] [--workspace NAME=PATH] [--merge]
               [--output-dir OUTPUT_DIR] [--title TITLE] [--version]

--input       Path to a JSON outputs file, or '-' for stdin (default).
--workspace   Named outputs file, repeatable; builds a multi-workspace site.
--merge       Preserve workspaces recorded in the output dir's manifest.json.
--output-dir  Directory to write the site into (default: site).
--title       Page title (default: 'Tofu Outputs').
```

Exit codes: `0` success, `2` bad input (missing file, invalid JSON,
non-object top level, bad workspace spec, or clashing workspace names).

## Explanation

### Why does this exist?

Complex, dynamic Tofu configurations are great for platform teams and
terrible as a lookup surface. When an application engineer just needs the
queue ARN or the VPC ID, "clone the repo, init the backend, run
`tofu output`" is a lot of ceremony. tofu-garnish gives outputs a stable,
human-readable URL that is regenerated on every apply.

### Why not just publish the JSON?

Raw `output -json` is noisy: values are buried in `value`/`type`/`sensitive`
wrappers, nested objects become walls of braces, and nothing is scannable.
tofu-garnish flattens that into structure-aware HTML: maps become key/value
tables, lists of similar objects become columnar tables (one row per subnet,
one column per attribute), and every top-level row gets a single copy button
— plain text for scalars, pretty JSON for anything nested. It's
deliberately KISS — self-contained HTML files, no framework, no build
step, dark-mode via `prefers-color-scheme`, and a few lines of vanilla JS
for filtering and copying.

### Why a Pages branch instead of `deploy-pages` artifacts?

Artifact-based Pages deployments are atomic: every deploy replaces the whole
site. That forces every apply workflow to gather *all* workspaces' outputs
(matrix fan-in) even when only one tenant changed. Committing to a Pages
branch instead makes updates incremental: the action writes only the files
for the workspaces you named (via the Git Data API's `base_tree`, through
`actions/github-script` — no clone, no credential juggling) and everything
else on the branch is preserved. Push races between concurrent tenant
deploys are retried against the fresh branch tip.

### <a name="sensitive-values"></a>How are sensitive values handled?

When the input is in `output -json` format, any output flagged
`"sensitive": true` is rendered as a masked placeholder — the value never
reaches the HTML, the copy buttons, or the filter index. **Caveat:** the
other two input formats carry no sensitivity metadata, so tofu-garnish
cannot know what to mask; and either way, your Pages site is as public as
your repo. Don't publish outputs you wouldn't commit to the README.

### Security posture

The action is a composite of a stdlib-only Python script plus
`actions/github-script` pinned to a full commit SHA. All user-controlled
values are passed through environment variables (never interpolated into
shell), all rendered content is HTML-escaped, and the token is only ever
handled by github-script's Octokit client. CI runs [zizmor][zizmor] with the
**pedantic** persona over every workflow and the action itself.

## Development

```console
$ pip install pytest pytest-cov ruff
$ python -m pytest --cov      # tests + coverage gate
$ ruff check . && ruff format --check .
$ zizmor --persona pedantic . # security audit
```

## License

[MIT](LICENSE)

[dflook]: https://github.com/dflook/terraform-github-actions
[zizmor]: https://docs.zizmor.sh
