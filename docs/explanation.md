[← Back to README](../README.md) · [Tutorial](tutorial.md) · [How-to guides](how-to-guides.md) · [Reference](reference.md)

# Explanation

## Why does this exist?

Complex, dynamic Tofu configurations are great for platform teams and
terrible as a lookup surface. When an application engineer just needs the
queue ARN or the VPC ID, "clone the repo, init the backend, run
`tofu output`" is a lot of ceremony. tofu-garnish gives outputs a stable,
human-readable URL that is regenerated on every apply.

## Why not just publish the JSON?

Raw `output -json` is noisy: values are buried in `value`/`type`/`sensitive`
wrappers, nested objects become walls of braces, and nothing is scannable.
tofu-garnish flattens that into structure-aware HTML: maps become key/value
tables, lists of similar objects become columnar tables (one row per subnet,
one column per attribute), and every top-level row gets a single copy button
(plain text for scalars, pretty JSON for anything nested). It's
deliberately KISS: self-contained HTML files, no framework, no build
step, dark-mode via `prefers-color-scheme`, and a few lines of vanilla JS
for filtering and copying.

The HTML page is for humans, not a replacement for automation, so
tofu-garnish also writes a clean `outputs.json` next to each page: the same
name-to-value map, minus the `value`/`type`/`sensitive` wrappers and minus
sensitive outputs entirely. A script that just needs `vpc_id` can hit the
JSON directly (see [Reference](reference.md#machine-readable-outputsjson)),
no HTML parsing required.

## Why a Pages branch instead of `deploy-pages` artifacts?

Artifact-based Pages deployments are atomic: every deploy replaces the whole
site. That forces every apply workflow to gather *all* workspaces' outputs
(matrix fan-in) even when only one tenant changed. Committing to a Pages
branch instead makes updates incremental: the action writes only the files
for the workspaces you named (via the Git Data API's `base_tree`, with no
clone and no git credential juggling) and everything else on the branch is
preserved. Push races between concurrent tenant deploys are retried
against the fresh branch tip.

## Why "OpenTofu only" for descriptions?

The `description` argument on `output` blocks never makes it into
`output -json` or state; it exists only in configuration. OpenTofu 1.10
added configuration inspection to `show` (`-config` and `-module=DIR`
modes); `-module` even works as a pure static parse, with no init, state,
or providers. Terraform has no equivalent, and parsing HCL ourselves would
violate the KISS budget. This is a Tofu-focused project, so the feature
follows the Tofu toolchain.

## <a name="sensitive-values"></a>How are sensitive values handled?

When the input is in `output -json` format, any output flagged
`"sensitive": true` is rendered as a masked placeholder; the value never
reaches the HTML, the copy buttons, or the filter index. **Caveat:** the
other two input formats carry no sensitivity metadata, so tofu-garnish
cannot know what to mask; and either way, your Pages site is as public as
your repo. Don't publish outputs you wouldn't commit to the README.

## Security posture

The whole action is two stdlib-only Python scripts: no third-party actions,
no npm, no shell logic beyond one `python3` invocation. All user-controlled
values are passed through environment variables (never interpolated into
shell), all rendered content is HTML-escaped, and the token is only sent as
an Authorization header to the GitHub API. CI runs [zizmor][zizmor] with the
**pedantic** persona over every workflow and the action itself.

[zizmor]: https://docs.zizmor.sh
