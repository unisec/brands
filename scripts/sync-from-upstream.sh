#!/usr/bin/env bash
# sync-from-upstream.sh
#
# Pulls icon.png / icon@2x.png / logo.png / logo@2x.png for a given slug from
# home-assistant/brands (resolving its symlinks remotely), writing them into
# integrations/<slug>/.
#
# Usage:
#   scripts/sync-from-upstream.sh <slug> <upstream_name>
#
# Lookup order: core_integrations -> core_brands -> custom_integrations.
# Follows a chain of symlinks remotely until a real directory is found,
# then downloads only the 4 canonical files that actually exist upstream.
#
# Requires: curl, jq
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
API="https://api.github.com/repos/home-assistant/brands/contents"
RAW="https://raw.githubusercontent.com/home-assistant/brands/master"
UA="unicontrol-brands-sync"

AUTH_HEADER=""
if [ -n "${GITHUB_TOKEN:-}" ]; then
  AUTH_HEADER="Authorization: Bearer $GITHUB_TOKEN"
fi

api_get() {
  local path="$1"
  if [ -n "$AUTH_HEADER" ]; then
    curl -sS -H "Accept: application/vnd.github+json" -H "User-Agent: $UA" -H "$AUTH_HEADER" "$API/$path"
  else
    curl -sS -H "Accept: application/vnd.github+json" -H "User-Agent: $UA" "$API/$path"
  fi
}

# Normalise a path like "a/b/../c" -> "a/c" (POSIX, no filesystem touch).
normalise_path() {
  local p="$1"
  local -a out=()
  local IFS=/
  for part in $p; do
    case "$part" in
      ''|'.') ;;
      '..')
        if [ "${#out[@]}" -gt 0 ]; then
          unset 'out[${#out[@]}-1]'
        fi
        ;;
      *) out+=("$part") ;;
    esac
  done
  local joined=""
  for part in "${out[@]}"; do
    if [ -z "$joined" ]; then joined="$part"; else joined="$joined/$part"; fi
  done
  echo "$joined"
}

# resolve_remote <path>  -> prints final directory path upstream, or empty.
resolve_remote() {
  local path="$1"
  local i
  for i in 1 2 3 4 5 6; do
    local body type target resolved
    body="$(api_get "$path")"
    if [ -z "$body" ]; then return 1; fi
    local msg
    msg="$(printf '%s' "$body" | jq -r '.message? // ""' 2>/dev/null || true)"
    if [ "$msg" = "Not Found" ]; then return 1; fi
    type="$(printf '%s' "$body" | jq -r 'if type=="array" then "dir" else (.type // "unknown") end' 2>/dev/null || echo "unknown")"
    if [ "$type" = "dir" ]; then
      printf '%s\n' "$path"
      return 0
    fi
    if [ "$type" = "symlink" ]; then
      resolved="$(printf '%s' "$body" | jq -r '.resolved_path // ""' 2>/dev/null || true)"
      target="$(printf '%s' "$body" | jq -r '.target // ""' 2>/dev/null || true)"
      if [ -n "$resolved" ]; then
        path="$resolved"
      elif [ -n "$target" ]; then
        local parent new
        parent="$(dirname "$path")"
        new="$parent/$target"
        path="$(normalise_path "$new")"
      else
        return 1
      fi
      continue
    fi
    # Not a dir/symlink or something unknown; give up on this chain.
    return 1
  done
  return 1
}

find_upstream() {
  local name="$1" cat resolved
  for cat in core_integrations core_brands custom_integrations; do
    resolved="$(resolve_remote "$cat/$name" 2>/dev/null || true)"
    if [ -n "$resolved" ]; then
      printf '%s\n' "$resolved"
      return 0
    fi
  done
  return 1
}

download_one() {
  local upstream_path="$1" fname="$2" dest="$3"
  # Use the Contents API with Accept: raw. GitHub resolves blob symlinks
  # server-side and returns the actual file bytes (unlike raw.githubusercontent
  # which returns the symlink target as text for mode 120000 blobs).
  local enc_fname url http
  enc_fname="${fname//@/%40}"
  url="$API/$upstream_path/$enc_fname"
  if [ -n "$AUTH_HEADER" ]; then
    http="$(curl -sSL -o "$dest" -w '%{http_code}' \
      -H "Accept: application/vnd.github.raw" \
      -H "User-Agent: $UA" \
      -H "$AUTH_HEADER" \
      "$url")"
  else
    http="$(curl -sSL -o "$dest" -w '%{http_code}' \
      -H "Accept: application/vnd.github.raw" \
      -H "User-Agent: $UA" \
      "$url")"
  fi
  if [ "$http" = "200" ]; then
    # Sanity check: first bytes should be PNG magic (89 50 4E 47)
    local magic
    magic="$(xxd -l 4 -p "$dest" 2>/dev/null || true)"
    if [ "$magic" = "89504e47" ]; then
      return 0
    fi
    # Not a PNG — probably still a symlink target string. Try to follow it.
    local target
    target="$(head -c 1024 "$dest" 2>/dev/null || true)"
    rm -f "$dest"
    if [ -n "$target" ] && [ "${#target}" -lt 512 ]; then
      # Resolve relative to upstream_path.
      local new_path
      new_path="$(normalise_path "$upstream_path/$target")"
      # Avoid infinite loops: only retry once at a different path.
      if [ "$new_path" != "$upstream_path/$fname" ]; then
        # new_path may already include the filename; split.
        local new_dir new_file
        new_dir="$(dirname "$new_path")"
        new_file="$(basename "$new_path")"
        download_one "$new_dir" "$new_file" "$dest"
        return $?
      fi
    fi
    return 1
  fi
  rm -f "$dest"
  return 1
}

main() {
  local slug="${1:-}" upstream_name="${2:-}"
  if [ -z "$slug" ] || [ -z "$upstream_name" ]; then
    echo "Usage: $0 <slug> <upstream_name>" >&2
    exit 2
  fi
  local upstream_path
  upstream_path="$(find_upstream "$upstream_name")"
  if [ -z "$upstream_path" ] && [ "$upstream_name" != "$slug" ]; then
    upstream_path="$(find_upstream "$slug")"
    if [ -n "$upstream_path" ]; then
      echo "INFO $slug: fell back to upstream '$slug' (asked '$upstream_name')" >&2
    fi
  fi
  if [ -z "$upstream_path" ]; then
    echo "SKIP $slug: upstream '$upstream_name' not found" >&2
    return 10
  fi
  local dest_dir="$REPO_ROOT/integrations/$slug"
  mkdir -p "$dest_dir"
  local got=0 fname tmp
  for fname in icon.png "icon@2x.png" logo.png "logo@2x.png"; do
    tmp="$dest_dir/.$fname.tmp"
    if download_one "$upstream_path" "$fname" "$tmp"; then
      mv "$tmp" "$dest_dir/$fname"
      got=$((got + 1))
    fi
  done
  if [ "$got" = 0 ]; then
    echo "FAIL $slug: no files downloaded from $upstream_path" >&2
    return 11
  fi
  echo "OK $slug <- $upstream_path ($got files)"
}

main "$@"
