"""PDX mod linter. Discovers and runs lint checks from a mod's tools/lint/ directory."""

import hashlib
import importlib
import importlib.util
import inspect
import json
import multiprocessing
import os
import pkgutil
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from pdx_utilities.paths import find_mod_root_or_exit as find_mod_root


MANIFEST_PATH = ".claude/lint_manifest.json"


PRUNE_DIRS = {".git", ".claude", "__pycache__", ".gui_workspace"}


def load_manifest(mod_root: Path) -> dict:
    """State of the last runs: 'files' maps a path to [mtime, size, sha1 or None];
    'pending' maps a check to the paths it has not passed since they changed.
    A version 1 manifest (path -> mtime of the last full pass) loads as files
    with an unknown hash and nothing pending."""
    p = mod_root / MANIFEST_PATH
    data = {}
    if p.exists():
        try:
            data = json.loads(p.read_text())
        except Exception:
            data = {}
    if data.get("version") == 2:
        return data
    return {"version": 2, "files": {rel: [mtime, None, None] for rel, mtime in data.items()
                                    if isinstance(mtime, (int, float))},
            "pending": {}}


def save_manifest(mod_root: Path, manifest: dict):
    p = mod_root / MANIFEST_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(manifest, indent=1, sort_keys=True) + "\n")


def _sha1(path: Path) -> str | None:
    try:
        return hashlib.sha1(path.read_bytes()).hexdigest()
    except OSError:
        return None


def changed_files(mod_root: Path, manifest: dict,
                  exts: tuple[str, ...] = (".txt", ".gui", ".yml")) -> set[Path]:
    """Files whose content changed since the manifest saw them, and new files.
    Only a file with a new mtime or size is read; one rewritten byte for byte
    (a generator run) does not count. Updates manifest['files']."""
    files = manifest["files"]
    changed = set()
    for dirpath, dirs, names in os.walk(mod_root):
        # .git and .claude (agent worktrees) hold no mod content and about
        # half of all entries under the mod root.
        dirs[:] = [d for d in dirs if d not in PRUNE_DIRS]
        for name in names:
            if not name.endswith(exts):
                continue
            f = Path(dirpath) / name
            rel = str(f.relative_to(mod_root))
            st = f.stat()
            old = files.get(rel)
            if old and old[0] == st.st_mtime and old[1] in (None, st.st_size):
                if old[1] is None:
                    old[1] = st.st_size
                continue
            sha = _sha1(f)
            if not (old and old[2] is not None and old[2] == sha):
                changed.add(f)
            files[rel] = [st.st_mtime, st.st_size, sha]
    return changed


def discover_checks(mod_root: Path) -> list[tuple[str, callable]]:
    lint_dir = mod_root / "tools" / "lint"
    if not lint_dir.is_dir():
        return []

    tools_dir = str(mod_root / "tools")
    if tools_dir not in sys.path:
        sys.path.insert(0, tools_dir)

    # Force-reload the lint package so each mod gets its own modules
    for key in [k for k in sys.modules if k == "lint" or k.startswith("lint.")]:
        del sys.modules[key]

    checks = []
    try:
        import lint as lint_pkg
        for info in pkgutil.iter_modules([str(lint_dir)]):
            if info.name.startswith("_"):
                continue
            mod = importlib.import_module(f"lint.{info.name}")
            if hasattr(mod, "run"):
                checks.append((info.name, mod.run))
    except Exception as e:
        print(f"Error loading lint checks: {e}", file=sys.stderr)

    return checks


def _run_check(fn, mod_root: Path, changed: set[Path] | None) -> list[str]:
    try:
        if "changed" in inspect.signature(fn).parameters:
            return fn(mod_root, changed=changed) or []
        return fn(mod_root) or []
    except Exception as e:
        return [f"check crashed: {e}"]


def run_all(mod_root: Path, skip: set[str] | None = None,
            full: bool = False) -> dict[str, list[str]]:
    """Run the checks side by side, each in its own forked process. Each check
    gets the files it has not passed since they changed: a failing check keeps
    its files pending, and the other checks do not see them again."""
    skip = skip or set()
    checks = [(n, fn) for n, fn in discover_checks(mod_root) if n not in skip]

    if not checks:
        print("  No lint checks found in tools/lint/", file=sys.stderr)
        return {}

    manifest = load_manifest(mod_root)
    pending = manifest["pending"]
    new = changed_files(mod_root, manifest)
    for name, _fn in checks:
        pending[name] = sorted(set(pending.get(name, [])) | {str(f.relative_to(mod_root)) for f in new})
    if full:
        todo = {name: None for name, _fn in checks}
    else:
        if not any(pending[name] for name, _fn in checks):
            save_manifest(mod_root, manifest)
            return {}
        # files deleted since they changed drop out
        todo = {name: {mod_root / rel for rel in pending[name] if (mod_root / rel).exists()}
                for name, _fn in checks if pending[name]}

    results = {}
    ctx = multiprocessing.get_context("fork")
    with ProcessPoolExecutor(max_workers=min(len(todo), os.cpu_count() or 4), mp_context=ctx) as pool:
        futures = {name: pool.submit(_run_check, fn, mod_root, todo[name])
                   for name, fn in checks if name in todo}
        for name, fut in futures.items():
            errors = fut.result()
            if errors:
                results[name] = errors
            else:
                pending[name] = []
    save_manifest(mod_root, manifest)
    return results


def main():
    args = sys.argv[1:]
    full = "--full" in args
    args = [a for a in args if a != "--full"]

    skip = set()
    while "--skip" in args:
        idx = args.index("--skip")
        if idx + 1 < len(args):
            skip.add(args[idx + 1])
            args = args[:idx] + args[idx + 2:]
        else:
            args = args[:idx]

    if args:
        mod_root = Path(args[0]).resolve()
        if not (mod_root / ".metadata").is_dir():
            print(f"Warning: {mod_root} has no .metadata/ — might not be a mod root",
                  file=sys.stderr)
    else:
        mod_root = find_mod_root()

    label = "Linting (full)" if full else "Linting"
    print(f"{label}: {mod_root.name}")
    results = run_all(mod_root, skip=skip, full=full)

    if not results:
        print("  All checks passed.")
        return 0

    total = 0
    for name, errors in sorted(results.items()):
        print(f"\n  [{name}] ({len(errors)} issue{'s' if len(errors) != 1 else ''})")
        for err in errors:
            print(f"    {err}")
        total += len(errors)
    print(f"\n  {total} issue{'s' if total != 1 else ''} found.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
