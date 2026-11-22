# yeet

Find what's taking up disk space, choose what to remove, and review it before deleting—all from your terminal.

Yeet includes an interactive disk explorer and focused scans for stale projects, large files, caches, build artifacts, and downloaded installers. macOS also gets Xcode cleanup and app leftover detection.

## Install

### macOS and Linux

```sh
curl -fsSL https://raw.githubusercontent.com/sohanmanju/yeet/master/install.sh | sh
```

The installer sets up [uv](https://docs.astral.sh/uv/) if needed, installs yeet in an isolated tool environment, and downloads Python 3.12 if it isn't available. You don't need Git, Homebrew, an existing Python installation, or sudo. It requires `curl` and internet access. It updates your shell profile when needed to make the command available; restart your terminal if `yeet` isn't found.

To inspect the installer first, download [install.sh](install.sh), read it, then run `sh install.sh`.

Already have uv? Install directly:

```sh
uv tool install --python 3.12 https://github.com/sohanmanju/yeet/archive/refs/heads/master.zip
uv tool update-shell
```

### Windows (PowerShell)

Install uv using its [official installer](https://docs.astral.sh/uv/getting-started/installation/):

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

Restart PowerShell, then install yeet:

```powershell
uv tool install --python 3.12 https://github.com/sohanmanju/yeet/archive/refs/heads/master.zip
uv tool update-shell
```

Restart PowerShell again if `yeet` isn't found.

### Update or uninstall

To update, rerun the macOS/Linux installer, or run this on any platform:

```sh
uv tool install --python 3.12 --upgrade https://github.com/sohanmanju/yeet/archive/refs/heads/master.zip
```

To uninstall:

```sh
uv tool uninstall yeet
```

This removes the tool environment and command. Configuration and cleanup history in `~/.config/yeet/` are retained.

## First run

```sh
yeet
```

Choose a workflow from the menu. Directory-based workflows let you choose where to scan; you can also supply a starting path:

```sh
yeet ~/Downloads
```

Browse results, select items, then review the paths and sizes before confirming deletion. The storage meter shows how space is distributed as measurements arrive. Ghostty 1.4+ and Kitty support the pixel canvas; other terminals use a text dot grid.

| Workflow | What it finds |
| --- | --- |
| Explore Disk | Files and folders, sorted by size |
| Stale Projects | Coding projects inactive for 90 days by default |
| Large Files | Files larger than 25 MB by default |
| System Caches | Known browser, package manager, IDE, and application caches |
| Project Artifacts | Build outputs and dependencies such as `node_modules`, `target`, `.next`, and `.venv` |
| Installer Cleanup | Downloaded installers and archives |
| App Leftovers (macOS) | Data associated with apps that are no longer installed |
| Xcode Cleanup (macOS) | Simulators, device support, Derived Data, archives, and documentation |
| History | Previous cleanup runs and their results |

## Common commands

Skip the menu by selecting a workflow:

```sh
yeet --workflow explore ~/Downloads
yeet --workflow projects --days 30 ~/Projects
yeet --workflow files --min-size 100 ~/Downloads
yeet --workflow caches --min-cache-size 10
yeet --workflow purge ~/Projects
```

Export scan results without deleting anything:

```sh
yeet --workflow files --json ~/Downloads
yeet --workflow caches --json
yeet --workflow purge --json ~/Projects
yeet ~/Downloads --export results.json
yeet ~/Downloads --export -
```

`--json` requires a workflow. `--export` exports a disk scan to a file, or to stdout with `-`.

```sh
yeet --history             # Recent cleanup runs
yeet --history --limit 50  # Show more history
yeet --help               # All options
yeet --version
```

## Keyboard controls

In the disk explorer:

| Key | Action |
| --- | --- |
| `↑` / `↓` or `k` / `j` | Move between items |
| `Enter` / `l` | Open a directory |
| `h` / `Backspace` | Go to the parent directory |
| `Space` | Toggle selection |
| `*` / `u` | Select all visible / deselect all |
| `d` | Review selected items for deletion |
| `f` / `a` / `c` | Filter by name / age / clear filter |
| `s` | Cycle sort mode |
| `t` | Toggle small items |
| `i` / `e` | Item info / file type breakdown |
| `o` | Open in the file manager |
| `B` / `b` | Bookmark this directory / jump to next bookmark |
| `~` / `/` | Jump to home / root |
| `g` / `G` | Jump to first / last item |
| `Ctrl+U` / `Ctrl+D` | Page up / down |
| `?` | Show help |
| `q` / `Esc` | Quit |

In workflow selection lists, use `Space` to select, `a` / `n` to select all / none, and `Enter` to review. Use `q` / `Esc` to cancel. Review screens use `Tab` or `←` / `→` to choose an action and `Enter` to activate it; Back is selected by default.

## Deletion and recovery

Yeet uses Trash by default when available. Moving files to Trash does **not** free their disk space until Trash is emptied. Results distinguish bytes moved to Trash from space reclaimed through permanent deletion.

If Trash is unavailable, permanent deletion requires explicit confirmation. Xcode cleanup uses permanent deletion. Built-in and configured protected paths remain blocked. Failed items appear in the results and stay selected for retry.

Scans are suggestions: review every selected path, particularly app leftovers and archives. Removing project dependencies or build outputs can require downloading or rebuilding them later. Yeet runs with your user's permissions; inaccessible locations are skipped. Run it as your normal user.

Cleanup history is stored in `~/.config/yeet/history.jsonl`.

## Configuration

Create `~/.config/yeet/config.toml` to override defaults. Omit any settings you don't need.

```toml
[explorer]
start_path = "~"
min_size_mb = 5
show_hidden = true

[deletion]
use_trash = true
confirm_delete = true

[scanner]
days_threshold = 90
large_file_mb = 25
cache_size_mb = 1

[cache]
enabled = true
max_age_hours = 24

[paths]
protected_paths = ["~/Documents/important"]
ignored_paths = []
bookmarks = ["~/Downloads", "~/Projects"]
```

`protected_paths` blocks deletion. `ignored_paths` excludes paths from disk explorer scans. Bookmarks are also saved when you press `B` in the explorer.

## Development

Requires [uv](https://docs.astral.sh/uv/getting-started/installation/) and Git.

```sh
git clone https://github.com/sohanmanju/yeet.git
cd yeet
uv sync --extra dev --python 3.12
uv run yeet --help
uv run pytest
```

To install your checkout as a command:

```sh
uv tool install --editable . --python 3.12
uv tool update-shell
```

The package supports Python 3.10+. Python 3.11+ is needed to read TOML configuration unless `tomli` is installed separately; the installer uses 3.12.

Bug reports, new cache locations, and contributions are welcome through [GitHub issues](https://github.com/sohanmanju/yeet/issues) and pull requests. See [CHANGELOG.md](CHANGELOG.md) for release history.

## License

[MIT](LICENSE). Built with [Rich](https://github.com/Textualize/rich) and [prompt_toolkit](https://github.com/prompt-toolkit/python-prompt-toolkit). See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) for additional attribution.
