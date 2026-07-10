# pdx-lint

Lint runner for Paradox mods. Each mod defines its own checks as Python modules in its `tools/lint/` directory; pdx-lint discovers and runs them, tracks which files changed since the last clean pass, and reports findings. The runner is generic and carries no game-specific rules itself.

## Install

Self-contained Python script, no dependencies. Symlink it onto your PATH:

```bash
ln -s "$(pwd)/pdx-lint" ~/.local/bin/pdx-lint
```

## Usage

```bash
pdx-lint                    # lint files changed since the last clean pass
pdx-lint --full             # lint every file
pdx-lint /path/to/mod       # lint a specific mod
pdx-lint --skip check_name  # skip one check by module name
```

The mod root is found automatically via its `.metadata/` directory, so the tool can run from anywhere inside the mod. Exit code is nonzero when any check reports findings, which makes it usable as a commit or stop hook.

## Writing checks

A check is a Python module in `<mod>/tools/lint/` that exposes:

```python
def run(mod_root: Path, changed: set[Path] | None = None) -> list[str]:
    ...
```

Return one string per finding; an empty list means the check passed. When `changed` is provided the check should limit itself to those files.

## Incremental tracking

File modification times are recorded in `<mod>/.claude/lint_manifest.json` after a clean pass. The default run only rechecks files that changed since. `--full` ignores the manifest.

## Configuration

Per-mod settings live in `.pdx-lint.json` at the mod root, read by the checks that want them (for example format-skip prefixes for vendored files, or staleness definitions for generated files).
