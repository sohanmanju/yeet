# Untangle decision log

The starting tree includes uncommitted cleanup-journey work. Preserve that work
and its behavior. Baseline: `uv run pytest -q`, 178 passed. Both optional comment
and test cleanup were selected.

## Decisions and problems

1. Separate stable scan models and formatting from filesystem operations. Keep
   the old `utils` import surface for compatibility, but use explicit owners
   internally. Make project activity selection one rule.
   - `utils.py` mixes every workflow's data models with deletion, trash and OS
     launching; consumers import unrelated platform behavior.
   - `Project.days_stale`, `last_activity`, and `activity_type` repeat the same
     timestamp precedence.
   - Handlers still use the deprecated `scanner.py` facade.
2. Share apparent-byte traversal, while retaining allocated-byte `du` measurement
   and project-specific dependency exclusions as separate policies.
   - Cache, Xcode, installer, leftovers and purge repeat file walking/stat logic.
   - Project detection repeats marker knowledge; git and non-git requirements
     intentionally differ today. Record that distinction explicitly.
   - `DiskExplorer.DANGEROUS_PATHS` duplicates safety roots, but its warning depth
     differs from the deletion block policy.
   - Explorer deletion edits `_size_cache` to invalidate ancestor totals.
3. Define configuration section/key mappings once for loading and saving.
   - `Config.load` and `save` separately enumerate the same fields.
   - String and list serialization differ despite both being TOML strings.
4. Make terminal page hosts an explicit interface; separate classification and
   theme data from rendering.
   - Journey pages call host `_get_content`, branch on `hasattr(move)`, and reach
     into explorer `_get_display_items`.
   - Failure rendering parses the English prefix of a note.
   - Screens import full meter/pixel rendering machinery for theme values.
   - File classification lives in the meter renderer.
   - Explorer keyboard handlers independently decide whether keys enter filter
     text or execute commands, leaving some commands active during text input.
5. Give workflow navigation and outcome accounting clear owners.
   - Session navigation recreates results/empty pages inside directory-cancel
     branches and depends on variables from separate branches.
   - Session and explorer repeat deletion outcome/history arithmetic.
   - CLI export validation and dispatch repeat the same branch.
   - Workflow aliases, selector convenience wrappers, explorer rendering
     forwarding methods, and cache batch wrapper have no production callers.
6. Clean comments and tests after preserving the regression safety net.
   - Many inline comments repeat nearby statements.
   - Cache deletion test uses a fixed directory in the repository and a wrapper
     used only by the test; exercise the actual deletion operation in isolation.
   - Keep behavior tests for real terminal layout, safety, serialization and
     filesystem scanning. Remove assertions that merely freeze obsolete internal
     attributes and rewrite tests coupled to removed forwarding methods.

## Special cases retained by design

- OS trash backends, optional Windows dependency, simctl runtime deletion, and
  caches retaining their parent reflect external filesystem/tool requirements.
- Permission failures and unavailable metadata are expected during scans; retain
  targeted fallbacks, without swallowing unrelated programming errors.
- Directory/whole-system/default-root scans have different entry requirements.
- Latest Xcode versions are excluded from bulk selection; manual choice remains.
- Graphics fallback, compact layouts, terminal geometry polling and animation
  frame pacing reflect terminal capabilities and available space.

## Verification

Completed all decisions above. Additional findings resolved during follow-up:

- `XcodeScanner` now derives latest versions from discovered items, grouped by
  category and platform, instead of carrying duplicate version registries.
- `DiskExplorer` kills and reaps timed-out `du` processes before untracking them.
- `json_output.disk_scan_payload` owns the actual export contract: positive-size
  entries, descending size order, and percentage of parent. Removed the competing
  unused schema while preserving stdout and file export behavior.
- CLI export validation has one path, with the existing requirement that JSON
  mode specify a workflow. CLI scanner defaults derive from configuration defaults.
- Shared deletion execution and history accounting live in `handlers/common.py`;
  the explorer no longer imports the scan session just to execute deletions.
- Removed unused workflow aliases, selector wrappers, rendering forwarders, cache
  batch wrapper, and `safety.is_ignored_path`. Retained `utils` and `scanner` as
  compatibility import surfaces; production modules use the actual owners.
- Tests use isolated cache fixtures, intercept history writes, verify platform
  behavior rather than return types, and exercise real terminal input modes.
  Removed the test that scanned actual system caches merely to inspect types.

Final verification:

- `uv run pytest -q`: **199 passed** (baseline: 178).
- `uvx ruff check --select F yeet tests`: passed.
- `uvx ruff format --check yeet tests`: 74 files formatted.
- `git diff --check`: passed.
- `uv run yeet --help`: passed; command options and defaults preserved.
- AST import graph: no cycles, no production imports of compatibility facades.
- Scanner/model audit plus independent UI/core cross-audits: no remaining
  worthwhile structural findings after removal of the unused safety helper.

The exceptions listed above remain because they express actual platform,
measurement, safety, or terminal requirements. Public OS operation boundaries
return errors as outcomes so one failed deletion does not lose the rest of a run.
No separate bug hunt or UI redesign was performed. Tests cover intended behavior;
real destructive OS operations were not exercised against user data.


## Strict-review follow-up

Resolved all three findings from the subsequent maintainability review:

- Inline journey pages now obtain focus identity from their host and match
  outcomes by path. Standalone pages retain their own inventory and cursor;
  inline rendering no longer builds and discards that standalone presentation.
  Outcome messages have a separate line before the path so long paths cannot
  consume the error text.
- Disk size cache reads, writes, snapshots and invalidation are synchronized.
  Invalidating, clearing, or stopping measurements advances a generation;
  older measurements cannot publish cache entries afterward. Cache loading also
  checks its generation before committing a validated batch.
- Scanner adapters return typed `ScanBatch` values, including explicit counts,
  errors, serialized payload and review notes. `RootPolicy` replaces interacting
  directory/default-location flags. Selection capture and restoration belong to
  `SelectionEngine` and use paths instead of exposing row-index conventions to
  the workflow runner.

Regression checks cover inline focus on both selector and explorer hosts,
reordered outcomes, long paths, measurements completing after invalidation or
clear, restored selection after inventory reordering, all root policies, and all
seven scanner adapters. Final suite: **216 passed**. Ruff undefined-name/unused
import checks, formatting checks and `git diff --check` pass.

## Test-pruning follow-up

Removed the obsolete removed-flag check, duplicate bookmark/version coverage,
redundant cursor-layout coverage, a mocked cache-candidate test superseded by real
container discovery, and direct export checks superseded by actual CLI exports.
Removed test-only sorting conveniences and selector/explorer rendering forwarders.

Reworked retained checks to observe scan results, JSON files/stdout, terminal
commands, focused paths, selection snapshots, and rendered messages rather than
helper calls, internal indices, worker fields, or object identity. Real cache
fixtures now verify durable data is excluded on all supported platforms. Config
round trips retain multiple bookmarks. Configured-protection tests disable the
built-in temporary-root protection so it cannot mask regressions. The disk filter
fixture now separates files by allocated disk size. Removed assertions whose
results were fixed by the test harness itself.

Retained the framebuffer reference hashes: they protect visual parity with the
external reference renderer, rather than deriving expectations from this code.
Retained permission, concurrency, terminal-resize, deletion and serialization
coverage for their distinct observable behavior.

Verification: `uv run pytest -q` — **210 passed**. Ruff F checks, formatting checks,
and `git diff --check` pass.
