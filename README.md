# pdx-lint

PDX mod linter. Discovers and runs lint checks from a mod's tools/lint/ directory.

Each mod defines its own checks as Python modules with a run(mod_root) function.
This tool provides the runner framework: incremental file tracking, CLI, output.

Usage:
    pdx-lint                    # lint changed files in current mod
    pdx-lint --full             # lint all files
    pdx-lint /path/to/mod       # lint specific mod
    pdx-lint --skip check_name  # skip a check

## Install

Self-contained Python 3.9+ script, no dependencies. Symlink or copy it onto your PATH:

```bash
ln -s "$(pwd)/pdx-lint" ~/.local/bin/pdx-lint
```
