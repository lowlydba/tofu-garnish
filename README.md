<p align="center">
  <img src="docs/hero.svg" alt="tofu-garnish: Tofu outputs, plated as a static page" width="800">
</p>

<p align="center">
  <a href="https://github.com/lowlydba/tofu-garnish/actions/workflows/ci.yml"><img alt="CI" src="https://img.shields.io/github/actions/workflow/status/lowlydba/tofu-garnish/ci.yml?branch=main&label=CI&logo=github"></a>
  <a href="LICENSE"><img alt="License" src="https://img.shields.io/github/license/lowlydba/tofu-garnish"></a>
  <a href="https://github.com/lowlydba/tofu-garnish/releases"><img alt="Release" src="https://img.shields.io/github/v/release/lowlydba/tofu-garnish?logo=github&sort=semver"></a>
  <a href="https://docs.zizmor.sh"><img alt="zizmor: pedantic" src="https://img.shields.io/badge/zizmor-pedantic-green?logo=githubactions&logoColor=white"></a>
  <img alt="Python" src="https://img.shields.io/badge/python-3.10%2B-blue?logo=python&logoColor=white">
</p>

# tofu-garnish

Turn OpenTofu/Terraform outputs into a simple, readable static page on your
repo's GitHub Pages, so engineers can find that ARN without running `tofu
output` or spelunking through state.

**[👉 See it in action: live demo site][demo]**

* 🔒 dependency-free (two stdlib-only Python scripts, no third-party actions)
* 🍽️ structure-aware HTML: tables, not JSON walls
* 🏢 discrete multi-workspace publishing without clobbering
* 🙈 sensitive outputs masked automatically
* 🔌 plug-and-play with [dflook/terraform-github-actions][dflook]

---

Docs follow the [Diátaxis](https://diataxis.fr/) framework. Each section
below is a quick scan; follow the link for the full page.

## Tutorial

Add a workflow step after you pull your outputs:

```yaml
steps:
  - uses: lowlydba/tofu-garnish@v1
    with:
      outputs-file: ${{ steps.tf-outputs.outputs.json_output_path }}
      title: My Stack Outputs
```

Push to `main`, then set **Settings → Pages → Deploy from a branch →
`gh-pages`**. Every later push regenerates and republishes the page.

**[Full tutorial →](docs/tutorial.md)**

## How-to guides

* [Publish multiple workspaces, accounts, or tenants](docs/how-to-guides.md#publish-multiple-workspaces-accounts-or-tenants)
  with the `workspaces` input, one page per workspace plus a landing page.
* [Use it without dflook actions](docs/how-to-guides.md#use-it-without-dflook-actions):
  pipe `tofu output -json` to a file and point the action at it.
* [Consume outputs from scripts and other pipelines](docs/how-to-guides.md#consume-outputs-from-scripts-and-other-pipelines)
  via the machine-readable `outputs.json` next to every page.
* [Run the generator locally](docs/how-to-guides.md#run-the-generator-locally)
  with `python3 src/garnish.py`, no Action required.

**[Full how-to guides →](docs/how-to-guides.md)**

## Reference

| Input          | Required | Default             | Description                                   |
| -------------- | -------- | -------------------- | ---------------------------------------------- |
| `outputs-file` | no*      | none                  | Path to a JSON outputs file.                   |
| `workspaces`   | no*      | none                  | Multiline `name=path` pairs for multi-workspace sites. |
| `title`        | no       | `Tofu Outputs`        | Title shown on the generated page(s).          |
| `deploy`       | no       | `"true"`              | Set `"false"` to only generate HTML.           |

\* Exactly one of `workspaces`, `outputs-file`, or `outputs` must be
provided.

**[Full reference →](docs/reference.md)** (all inputs/outputs, accepted
input formats, site structure, CLI flags)

## Explanation

Complex, dynamic Tofu configurations are great for platform teams and
terrible as a lookup surface. tofu-garnish gives outputs a stable,
human-readable URL, flattening the raw `value`/`type`/`sensitive` JSON
into structure-aware HTML instead of a wall of braces.

**[Full explanation →](docs/explanation.md)** (design rationale, sensitive
value handling, security posture)

## Development

```console
$ pip install pytest pytest-cov ruff
$ python -m pytest --cov      # tests + coverage gate
$ ruff check . && ruff format --check .
$ zizmor --persona pedantic . # security audit
```

[dflook]: https://github.com/dflook/terraform-github-actions
[demo]: https://lowlydba.github.io/tofu-garnish/
