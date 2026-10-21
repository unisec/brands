#!/usr/bin/env bash
# fill-missing.sh <slug> <upstream_name>
#
# Removes any symlinks inside integrations/<slug>/ then downloads from upstream
# only the canonical files (icon.png, icon@2x.png, logo.png, logo@2x.png) that
# are MISSING from the directory. Existing real files are left untouched.
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RAW="https://raw.githubusercontent.com/home-assistant/brands/master"
UA="unicontrol-brands-sync"

slug="${1:-}"
upstream="${2:-}"
if [ -z "$slug" ] || [ -z "$upstream" ]; then
  echo "Usage: $0 <slug> <upstream_name>" >&2
  exit 2
fi

dir="$REPO_ROOT/integrations/$slug"
[ -d "$dir" ] || { echo "no dir: $dir" >&2; exit 1; }

# Resolve upstream path (reuse logic by sourcing the sync script's functions).
# Simpler: just query the API inline.
AUTH_HEADER=""
[ -n "${GITHUB_TOKEN:-}" ] && AUTH_HEADER="Authorization: Bearer $GITHUB_TOKEN"

api_get() {
  local path="$1"
  if [ -n "$AUTH_HEADER" ]; then
    curl -sS -H "Accept: application/vnd.github+json" -H "User-Agent: $UA" -H "$AUTH_HEADER" "https://api.github.com/repos/home-assistant/brands/contents/$path"
  else
    curl -sS -H "Accept: application/vnd.github+json" -H "User-Agent: $UA" "https://api.github.com/repos/home-assistant/brands/contents/$path"
  fi
}

normalise() {
  python3 -c 'import os,sys; print(os.path.normpath(sys.argv[1]))' "$1"
}

resolve_remote() {
  local path="$1" i body type target resolved msg
  for i in 1 2 3 4 5 6; do
    body="$(api_get "$path")"
    [ -z "$body" ] && return 1
    msg="$(printf '%s' "$body" | jq -r '.message? // ""' 2>/dev/null)"
    [ "$msg" = "Not Found" ] && return 1
    type="$(printf '%s' "$body" | jq -r 'if type=="array" then "dir" else (.type // "unknown") end' 2>/dev/null)"
    if [ "$type" = "dir" ]; then printf '%s\n' "$path"; return 0; fi
    if [ "$type" = "symlink" ]; then
      resolved="$(printf '%s' "$body" | jq -r '.resolved_path // ""')"
      target="$(printf '%s' "$body" | jq -r '.target // ""')"
      if [ -n "$resolved" ]; then path="$resolved";
      elif [ -n "$target" ]; then path="$(normalise "$(dirname "$path")/$target")";
      else return 1; fi
      continue
    fi
    return 1
  done
  return 1
}

find_upstream() {
  local name="$1" cat resolved
  for cat in core_integrations core_brands custom_integrations; do
    resolved="$(resolve_remote "$cat/$name" 2>/dev/null)"
    [ -n "$resolved" ] && { printf '%s\n' "$resolved"; return 0; }
  done
  return 1
}

upstream_path="$(find_upstream "$upstream")"
if [ -z "$upstream_path" ] && [ "$upstream" != "$slug" ]; then
  upstream_path="$(find_upstream "$slug")"
fi
[ -z "$upstream_path" ] && { echo "SKIP $slug: upstream '$upstream' not found" >&2; exit 10; }

# Delete only canonical-named symlinks (FS or git-tracked).
GIT_SYMLINKS_TMP="$(mktemp)"
trap 'rm -f "$GIT_SYMLINKS_TMP"' EXIT
(cd "$REPO_ROOT" && git ls-tree -r HEAD) | awk '$1=="120000" {print $4}' > "$GIT_SYMLINKS_TMP"

for cf in icon.png "icon@2x.png" logo.png "logo@2x.png"; do
  p="$dir/$cf"
  if [ -L "$p" ]; then
    rm -f "$p"
  fi
  rel="integrations/$slug/$cf"
  if grep -Fxq "$rel" "$GIT_SYMLINKS_TMP" 2>/dev/null; then
    rm -f "$p"
  fi
done

download_api() {
  local path="$1" fname="$2" dest="$3" enc url http magic target new_dir new_file
  enc="${fname//@/%40}"
  url="https://api.github.com/repos/home-assistant/brands/contents/$path/$enc"
  if [ -n "$AUTH_HEADER" ]; then
    http="$(curl -sSL -o "$dest" -w '%{http_code}' -H "Accept: application/vnd.github.raw" -H "User-Agent: $UA" -H "$AUTH_HEADER" "$url")"
  else
    http="$(curl -sSL -o "$dest" -w '%{http_code}' -H "Accept: application/vnd.github.raw" -H "User-Agent: $UA" "$url")"
  fi
  [ "$http" = "200" ] || { rm -f "$dest"; return 1; }
  magic="$(xxd -l 4 -p "$dest" 2>/dev/null || true)"
  if [ "$magic" = "89504e47" ]; then
    return 0
  fi
  target="$(head -c 1024 "$dest" 2>/dev/null || true)"
  rm -f "$dest"
  if [ -n "$target" ] && [ "${#target}" -lt 512 ]; then
    local new_path
    new_path="$(normalise "$path/$target")"
    new_dir="$(dirname "$new_path")"
    new_file="$(basename "$new_path")"
    if [ "$new_dir/$new_file" != "$path/$fname" ]; then
      download_api "$new_dir" "$new_file" "$dest"
      return $?
    fi
  fi
  return 1
}

got=0
for fname in icon.png "icon@2x.png" logo.png "logo@2x.png"; do
  dest="$dir/$fname"
  if [ -f "$dest" ] && [ ! -L "$dest" ]; then
    rel="integrations/$slug/$fname"
    if ! grep -Fxq "$rel" "$GIT_SYMLINKS_TMP"; then
      continue
    fi
    rm -f "$dest"
  fi
  if download_api "$upstream_path" "$fname" "$dest"; then
    got=$((got + 1))
  fi
done
echo "FILL $slug <- $upstream_path (+$got files)"
