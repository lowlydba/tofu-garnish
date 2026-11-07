[← Back to README](../README.md) · [Tutorial](tutorial.md) · [Reference](reference.md) · [Explanation](explanation.md) · [Writing outputs.tf](writing-outputs.md)

# How-to guides

## Publish multiple workspaces, accounts, or tenants

Use the `workspaces` input, one `name=path` pair per line. Each workspace
gets its own page under `/<name>/`, plus a landing page linking them all.
The landing page lists workspaces most recently updated first, each with a
relative age ("updated 3 days ago"):

```yaml
      - uses: lowlydba/tofu-garnish@v1
        with:
          title: Platform Outputs
          workspaces: |
            prod-us=prod-us-outputs.json
            prod-eu=prod-eu-outputs.json
            staging=staging-outputs.json
```

## Update one workspace without touching the others

Different applies for different tenants usually run in different workflows,
at different times. That's fine: in `workspaces` mode, each deploy only
overwrites the workspaces it names and rebuilds the landing page; everything
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

## Show output descriptions on the page (OpenTofu only)

Tofu drops the `description` argument from `output -json`, but
`tofu show -json -module=<dir>` can extract it straight from your module
source with no init, state, or providers needed. Point `module-dir` at your
root module and descriptions appear under each output name (and become
filterable):

```yaml
      - uses: lowlydba/tofu-garnish@v1
        with:
          outputs-file: outputs.json
          module-dir: my-terraform-config
```

> [!NOTE]
> Requires `tofu` ≥ 1.10 on the runner's PATH. Terraform's `show` command
> has no configuration mode; omit `module-dir` and the page simply renders
> without descriptions. YMMV.

## Use it without dflook actions

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
[Explanation](explanation.md#how-are-sensitive-values-handled)).

## Pass outputs inline instead of a file

Any `dflook/terraform-output` step's outputs can be passed straight through
as JSON; complex values arrive as JSON-encoded strings and are unpacked
automatically:

```yaml
      - uses: lowlydba/tofu-garnish@v1
        with:
          outputs: ${{ toJson(steps.tf-outputs.outputs) }}
```

## Consume outputs from scripts and other pipelines

Every generated page has a machine-readable `outputs.json` next to it: a
plain `{"name": value}` map with sensitive outputs omitted. That makes the
Pages site a stable outputs endpoint, no repo clone or state access needed:

```console
$ curl -s https://org.github.io/infra/prod-eu/outputs.json | jq -r .vpc_id
vpc-01463b6b84e1454ce
```

Single-workspace sites serve it at the site root (`/outputs.json`). The
shape is documented in
[Reference](reference.md#machine-readable-outputsjson). Don't want it? Set
the `outputs-json` input to `"false"`.

## Show what changed since the last publish

Set `show-changes: "true"` and each page compares its outputs with the `outputs.json` already on the Pages branch. Outputs that are new get a "created" pill, changed values get "updated", and outputs that disappeared get a "destroyed" card at the bottom. The meta line gains an "N outputs changed" count.

```yaml
      - uses: lowlydba/tofu-garnish@v1
        with:
          outputs-file: outputs.json
          show-changes: "true"
```

The comparison is against the previous publish only, so it shows differences between publishes, not exact apply times. The first publish has nothing to compare against and shows no pills. Sensitive outputs are compared by name only, never by value. This needs `outputs-json` left on.

## Publish a preview for each pull request

Publish every pull request to its own folder on the Pages branch and delete it when the PR closes. Other files on the branch are untouched, so previews sit next to your real site.

Publish on each push:

```yaml
name: Preview
on:
  pull_request:
    types: [opened, synchronize, reopened]

concurrency:
  group: tofu-garnish-preview-${{ github.event.pull_request.number }}
  cancel-in-progress: false

jobs:
  preview:
    # Fork tokens can't push to the Pages branch
    if: github.event.pull_request.head.repo.full_name == github.repository
    runs-on: ubuntu-latest
    permissions:
      contents: write
    steps:
      # ...plan or apply your staging config and write outputs.json
      - uses: lowlydba/tofu-garnish@v1
        id: garnish
        with:
          outputs-file: outputs.json
          title: Preview (PR ${{ github.event.pull_request.number }})
          site-path: pr-preview/${{ github.event.pull_request.number }}
          show-changes: "true"
```

Remove it when the PR closes, with no path filter so cleanup always runs:

```yaml
name: Preview cleanup
on:
  pull_request:
    types: [closed]

concurrency:
  group: tofu-garnish-preview-${{ github.event.pull_request.number }}
  cancel-in-progress: false

jobs:
  cleanup:
    if: github.event.pull_request.head.repo.full_name == github.repository
    runs-on: ubuntu-latest
    permissions:
      contents: write
    steps:
      - uses: lowlydba/tofu-garnish@v1
        with:
          remove: "true"
          site-path: pr-preview/${{ github.event.pull_request.number }}
```

* Both workflows share a concurrency group per PR number, so a cleanup never races a late publish.
* The `page-url` output is the preview's URL; post it with `gh pr comment --edit-last --create-if-none` to keep a single comment per PR.
* With `show-changes`, each push is compared with the previous push of the same preview, so reviewers see what moved since the last build.
* This repository runs exactly this setup: see `.github/workflows/preview.yml` and `.github/workflows/preview-cleanup.yml`.

## Generate the HTML without deploying

Set `deploy: "false"` and do whatever you like with the site directory:
upload it elsewhere, attach it as an artifact, or serve it from another
host.

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

## Run the generator locally

The generator is a single stdlib-only Python script with no dependencies to
install:

```console
$ tofu output -json | python3 src/garnish.py --title "My Stack" --output-dir site
garnish: wrote site/index.html (7 outputs)
```

Multi-workspace sites work locally too, with `--workspace name=path`
(repeatable) and `--merge` to preserve workspaces already in the output
directory. Set `SOURCE_DATE_EPOCH` for a reproducible timestamp.

No infrastructure handy? The repo ships provider-less example configs that
produce realistic outputs:

```console
$ tofu -chdir=examples/demo init && tofu -chdir=examples/demo apply -auto-approve
$ tofu -chdir=examples/demo output -json | python3 src/garnish.py --output-dir site
```

CI applies these with real OpenTofu and runs the action on the result, and
the demo workflow publishes them to this repo's Pages.
