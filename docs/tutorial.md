[← Back to README](../README.md) · [How-to guides](how-to-guides.md) · [Reference](reference.md) · [Explanation](explanation.md)

# Tutorial

*Publish your Tofu outputs to GitHub Pages in about five minutes.*

## 1. Add a workflow

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

Push to `main` and let it run once. This creates the `gh-pages` branch.

## 2. Enable GitHub Pages for the branch

In your repository: **Settings → Pages → Build and deployment → Source →
Deploy from a branch**, then pick `gh-pages` / `/ (root)`.

## 3. Visit your page

Open the site URL shown in the Pages settings (also available as the
`page-url` action output on later runs).

Expected result:

- Each output rendered as a card: maps as key/value tables, lists of
  objects as columnar tables.
- One copy button per row; nested values copy as pretty JSON.
- A filter box that matches names, keys, and values.
- Sensitive outputs masked.
- A meta line linking the commit and workflow run that produced the page.

That's it. Every push regenerates and republishes the page.
