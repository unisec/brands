#!/usr/bin/env python3
"""Build a TSV plan for materialising broken/old symlinks into upstream files.

Walks integrations/ and, for every symlink (dir or file), resolves the chain
locally until it finds either:
  * a plain directory (become canonical, use its basename as upstream name), or
  * a reference ending at ../core_brands/<name> or ../../core_brands/<name>/...
    (use <name> as upstream name; make the directory itself canonical because
    there is no corresponding real local dir).

Output lines:
  <slug>\t<upstream_name>\t<canonical_slug>

For symlinked files (level-2), the output targets the *parent* integration
directory as a whole: the entire parent dir is rewritten with upstream data.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INT = ROOT / "integrations"


def resolve_chain(start: Path, max_hops: int = 8):
    """Follow symlinks (relative to each hop's parent). Returns (final_path, upstream_name).

    upstream_name is set when the chain terminates at a core_brands reference;
    otherwise None (meaning the final target is a real local dir).
    """
    current = start
    for _ in range(max_hops):
        if current.is_symlink():
            raw = os.readlink(current)
            # Resolve relative to the symlink's parent
            new_target = (current.parent / raw)
            # Detect core_brands reference BEFORE normalising, since the
            # resolved path won't exist locally.
            parts = Path(raw).parts
            if "core_brands" in parts:
                idx = parts.index("core_brands")
                if idx + 1 < len(parts):
                    upstream = parts[idx + 1]
                    return current, upstream
            current = new_target
            # Normalise path (strip ..)
            try:
                current = Path(os.path.normpath(str(current)))
            except Exception:
                pass
            continue
        return current, None
    return current, None


def plan_dir_symlink(link: Path):
    """A directory-level symlink: integrations/<slug> -> something."""
    slug = link.name
    final, upstream_from_chain = resolve_chain(link)
    if upstream_from_chain:
        # Chain leads to core_brands. Canonical becomes this slug (no local real dir).
        return (slug, upstream_from_chain, slug)
    # Chain terminates at a real local path.
    try:
        rel = final.relative_to(INT)
    except ValueError:
        # Target lives outside integrations/ and is not core_brands: unknown.
        return None
    canonical_slug = rel.parts[0]
    canonical_dir = INT / canonical_slug
    if not canonical_dir.exists():
        # Broken chain
        return (slug, canonical_slug, canonical_slug)  # upstream == canonical, will try upstream
    if canonical_dir.is_symlink():
        # Shouldn't happen after chain resolution, treat defensively
        return (slug, canonical_slug, canonical_slug)
    # Real local dir — use canonical_slug as both upstream lookup name and canonical slug.
    return (slug, canonical_slug, canonical_slug)


def plan_file_symlinks(parent: Path):
    """A directory containing file-level symlinks; we rebuild the whole dir."""
    slug = parent.name
    # Find any file symlink pointing to core_brands.
    upstream = None
    for child in parent.iterdir():
        if child.is_symlink():
            raw = os.readlink(child)
            parts = Path(raw).parts
            if "core_brands" in parts:
                idx = parts.index("core_brands")
                if idx + 1 < len(parts):
                    upstream = parts[idx + 1]
                    break
    if upstream is None:
        return None
    return (slug, upstream, slug)


def main():
    plans = []
    # Directory-level symlinks
    for entry in sorted(INT.iterdir()):
        if entry.is_symlink():
            res = plan_dir_symlink(entry)
            if res:
                plans.append(res)

    # File-level symlinks (parents collected uniquely)
    file_sym_parents = set()
    for entry in INT.iterdir():
        if entry.is_dir() and not entry.is_symlink():
            try:
                for child in entry.iterdir():
                    if child.is_symlink():
                        file_sym_parents.add(entry)
                        break
            except PermissionError:
                pass
    for parent in sorted(file_sym_parents):
        res = plan_file_symlinks(parent)
        if res:
            plans.append(res)

    # Deduplicate (slug may appear in both passes; keep first).
    seen = set()
    out = []
    for p in plans:
        if p[0] in seen:
            continue
        seen.add(p[0])
        out.append(p)

    # Prefer sharing: if upstream == <another plan's slug> OR a dir that
    # resolves to the same upstream brand, collapse to that canonical.
    # Simple heuristic: group by upstream; the canonical is the first slug
    # that matches upstream exactly (or the shortest slug in the group).
    from collections import defaultdict
    buckets = defaultdict(list)
    for slug, upstream, canonical in out:
        buckets[upstream].append((slug, upstream, canonical))

    final = []
    for upstream, items in buckets.items():
        # Pick canonical: prefer slug == upstream, else shortest slug.
        slugs = [i[0] for i in items]
        preferred = None
        for s in slugs:
            if s == upstream:
                preferred = s
                break
        if preferred is None:
            # Also consider existing real local dir with same name as upstream.
            if (INT / upstream).exists() and not (INT / upstream).is_symlink():
                preferred = upstream
        if preferred is None:
            preferred = min(slugs, key=len)
        for slug, up, _canonical in items:
            final.append((slug, upstream, preferred))

    # Keep original ordering by slug
    final_by_slug = {t[0]: t for t in final}
    for slug, upstream, canonical in [final_by_slug[s] for s, _, _ in out]:
        print(f"{slug}\t{upstream}\t{canonical}")


if __name__ == "__main__":
    main()
