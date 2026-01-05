# Changelog

All notable changes to yeet will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.0] - 2025-01-05

### Added

#### Disk Explorer (New Feature)
- **Interactive disk explorer** - Browse your filesystem by size with a tree-style interface
- **Keyboard-driven navigation** with vim-style keybindings (j/k/h/l)
- **Breadcrumb navigation** showing your current path
- **Lazy loading** of directory sizes with background calculation
- **Multi-select across directories** - select items in different folders before batch delete
- **Filter by name** (`f`) - quickly find items matching a pattern
- **Filter by age** (`a`) - show only items older than N days
- **File type breakdown** (`e`) - see size distribution by file extension
- **Item info panel** (`i`) - detailed information about selected item
- **Help overlay** (`?`) - full keyboard shortcuts reference

#### Move to Trash
- **Safe deletion by default** - items are moved to system trash instead of permanent deletion
- Works on macOS (Finder trash), Linux (freedesktop.org spec), and Windows (send2trash)
- Can be recovered from trash if deleted by mistake
- Configurable via `~/.config/yeet/config.toml`

#### Configuration File
- New `~/.config/yeet/config.toml` for persistent settings
- Configure: start path, size thresholds, trash behavior, cache settings
- Settings are remembered across sessions

#### Export to JSON
- Export scan results with `--export results.json`
- Use `--export -` to output to stdout for scripting
- Includes file sizes, paths, modification dates, and percentages

#### Xcode Cleanup (macOS)
- Clean **Simulator Runtimes** - often 5-10+ GB each
- Clean Device Support files
- Clean Derived Data
- Clean Archives
- Clean Documentation Cache
- Clean Device Logs
- Smart detection of "latest" versions to keep

### Improved

#### Performance
- **5x faster directory size calculation** - now uses native `du` command instead of Python file walking
- **Parallel size calculation** - uses thread pool for concurrent directory scanning
- **Prioritized loading** - visible items load first for instant feedback
- **Persistent size cache** - sizes are cached to `~/.cache/yeet/sizes.json` for faster subsequent scans
- **LRU cache eviction** - bounded memory usage (max 10,000 cached entries)

#### Sparse File Handling
- Fixed incorrect size reporting for sparse files (VM disk images, etc.)
- Now reports actual disk usage instead of apparent file size
- Correctly handles OrbStack, Docker, and other VM disk images

#### User Experience
- **Real-time UI updates** - sizes appear as they're calculated, no need to press keys
- **Page navigation** - Ctrl+U/D or Page Up/Down to move quickly through large lists
- **Go to top/bottom** - `g` and `G` keys
- **Select all/none** - `*` to select all visible, `u` to deselect all
- **Quit warning** - warns if you have items selected before quitting
- **Clean shutdown** - no more hanging on exit, all background processes are terminated

#### Code Quality
- Fixed critical bug: XcodeScanResults properties were misplaced in wrong class
- Fixed bug: "Open in Finder" now works correctly when filter is active
- Removed ~90 lines of dead/unused code
- Bounded history size (max 100 entries) to prevent memory leaks
- Proper cleanup of circular references

### Fixed
- Fixed 16 TB size display bug caused by sparse files (OrbStack VM images)
- Fixed UI not refreshing when background size calculation completes
- Fixed application hanging on exit due to running `du` processes
- Fixed quit warning never being displayed
- Fixed "Open in Finder" opening wrong item when filter is active
- Fixed `datetime.fromtimestamp()` called on already-datetime object

### Removed
- Removed size bar visualization (was not useful with large size disparities)
- Removed percentage column (same reason)

## [0.1.0] - 2024-12-XX

### Added
- Initial release
- Stale Projects Scanner
- Large File Scanner  
- System Cache Scanner (60+ cache locations)
- Cross-platform support (macOS, Linux, Windows)
- Interactive selection with keyboard navigation
