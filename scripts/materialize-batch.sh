#!/usr/bin/env bash
# materialize-batch.sh
#
# Input (TSV on stdin or $1):
#   <slug>\t<upstream_name>\t<canonical_slug>
#
# For each unique canonical_slug:
#   - Clean out any FS/git symlinks inside integrations/<canonical_slug>/.
#   - If the dir still has at least one real canonical file (icon.png / ...),
#     only fill in whatever is missing from upstream (<upstream_name>).
#   - Otherwise download the full set from upstream.
# For every slug != canonical_slug, replace whatever is at integrations/<slug>
# with a relative symlink pointing to the canonical slug inside integrations/.
#
# Requires: scripts/sync-from-upstream.sh, scripts/fill-missing.sh
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SYNC="$REPO_ROOT/scripts/sync-from-upstream.sh"
FILL="$REPO_ROOT/scripts/fill-missing.sh"

input="${1:--}"
tmp="$(mktemp)"
state_dir="$(mktemp -d)"
trap 'rm -rf "$tmp" "$state_dir"' EXIT

if [ "$input" = "-" ]; then
  cat > "$tmp"
else
  cat "$input" > "$tmp"
fi

cd "$REPO_ROOT"

# Cache of git-tracked symlinks (mode 120000). We treat these as symlinks even
# if the local checkout has them as plain text files.
GIT_SYMLINKS_FILE="$(mktemp)"
git ls-tree -r HEAD | awk '$1=="120000" {print $4}' > "$GIT_SYMLINKS_FILE"

is_git_symlink() {
  grep -Fxq "$1" "$GIT_SYMLINKS_FILE"
}

# Remove every FS/git symlink inside a dir (not recursive, just top level).
# Preserves non-canonical real files (dark_*, icon.txt, REMOVAL_NOTE, …) and
# non-canonical git-symlinks (restoring those is left for another pass).
clean_symlinks_in_dir() {
  local dir="$1" child name
  [ -d "$dir" ] || return 0
  for child in "$dir"/* "$dir"/.*; do
    [ -e "$child" ] || [ -L "$child" ] || continue
    case "$child" in */.|*/..) continue ;; esac
    name="$(basename "$child")"
    case "$name" in
      icon.png|'icon@2x.png'|logo.png|'logo@2x.png') ;;
      *) continue ;;
    esac
    if [ -L "$child" ]; then
      rm -f "$child"
      continue
    fi
    local rel="${child#$REPO_ROOT/}"
    if is_git_symlink "$rel"; then
      rm -f "$child"
    fi
  done
}

canonical_has_real_file() {
  local dir="$1" f
  for f in icon.png "icon@2x.png" logo.png "logo@2x.png"; do
    local p="$dir/$f"
    [ -L "$p" ] && continue
    [ -f "$p" ] || continue
    local rel="${p#$REPO_ROOT/}"
    if is_git_symlink "$rel"; then
      continue
    fi
    return 0
  done
  return 1
}

while IFS=$'\t' read -r slug upstream canonical; do
  [ -z "${slug:-}" ] && continue
  case "$slug" in \#*) continue ;; esac
  canonical="${canonical:-$slug}"

  state_file="$state_dir/$(printf '%s' "$canonical" | tr '/' '_')"
  if [ ! -f "$state_file" ]; then
    target_dir="integrations/$canonical"
    # If the canonical path itself is a symlink (FS or git), nuke it so we can
    # make a real directory.
    if [ -L "$target_dir" ]; then
      rm -f "$target_dir"
    elif [ ! -d "$target_dir" ] && is_git_symlink "$target_dir"; then
      rm -f "$target_dir"
    fi
    mkdir -p "$target_dir"
    clean_symlinks_in_dir "$target_dir"

    if canonical_has_real_file "$target_dir"; then
      "$FILL" "$canonical" "$upstream"
      echo "1" > "$state_file"
    else
      if "$SYNC" "$canonical" "$upstream"; then
        echo "1" > "$state_file"
      else
        echo "0" > "$state_file"
        echo "WARN canonical '$canonical' (upstream '$upstream') failed; skipping variants" >&2
        continue
      fi
    fi
  fi

  if [ "$(cat "$state_file")" != "1" ]; then
    continue
  fi

  if [ "$slug" != "$canonical" ]; then
    variant="integrations/$slug"
    if [ -L "$variant" ] || [ -e "$variant" ]; then
      rm -rf "$variant"
    fi
    (cd integrations && ln -s "$canonical" "$slug")
    echo "LINK $slug -> $canonical"
  fi
done < "$tmp"

rm -f "$GIT_SYMLINKS_FILE"
