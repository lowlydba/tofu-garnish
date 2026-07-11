#!/usr/bin/env bash
# Generate the tofu-garnish site into $1.
# Expects GARNISH_SCRIPT, GARNISH_TITLE and one of GARNISH_WORKSPACES,
# GARNISH_OUTPUTS_FILE or GARNISH_OUTPUTS in the environment.
set -euo pipefail

site_dir="$1"

if [ -n "${GARNISH_WORKSPACES:-}" ]; then
  args=()
  while IFS= read -r line; do
    [ -z "${line// /}" ] && continue
    args+=(--workspace "$line")
  done <<< "$GARNISH_WORKSPACES"
  python3 "$GARNISH_SCRIPT" "${args[@]}" --merge \
    --output-dir "$site_dir" \
    --title "$GARNISH_TITLE"
elif [ -n "${GARNISH_OUTPUTS_FILE:-}" ]; then
  python3 "$GARNISH_SCRIPT" \
    --input "$GARNISH_OUTPUTS_FILE" \
    --output-dir "$site_dir" \
    --title "$GARNISH_TITLE"
elif [ -n "${GARNISH_OUTPUTS:-}" ]; then
  printf '%s' "$GARNISH_OUTPUTS" | python3 "$GARNISH_SCRIPT" \
    --output-dir "$site_dir" \
    --title "$GARNISH_TITLE"
else
  echo "::error::one of 'workspaces', 'outputs-file' or 'outputs' must be provided" >&2
  exit 1
fi
