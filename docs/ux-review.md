# Yeet UX review

Reference: `../fix-storage/src/ui/app.tsx`, especially `TopLine`, `Totals`,
`Categories`, `InsideHeader`, `ItemDetails`, and `BottomLine`.

## What makes the reference work

The dot meter is only one part of the design. A single screen connects disk
capacity, categories, folder contents, focused-item context, and the next action.
Color and weight communicate hierarchy; whitespace separates sections without
boxes. Keyboard hints change with the active pane and item.

Yeet already has the meter, adaptive tables, and cursor-driven highlighting.
Its remaining friction comes from disconnected workflows and dense screen chrome.
A decorative reskin alone would leave those problems in place.

## First pass implemented

- **Home (`yeet/ui/menu.py`):** small product heading, emphasis on free space,
  separate label and description tones, full-row focus, and workflow-specific
  guidance. Opening the menu still reads only disk capacity; it does not start
  an expensive disk scan.
- **Cleanup lists (`yeet/ui/selection.py`):** common product heading, fewer rules,
  focused-item path on taller terminals, and explicit Enter-to-review wording.
  Reveal is now advertised for the selectors that support it. Existing final
  deletion confirmations remain the next step after selection.
- **Explorer (`yeet/ui/explorer_render.py`):** common heading, muted breadcrumbs,
  focused-item path, deletion hint only when items are selected, and one compact
  line for sorting and hidden-item scope.
- **Shared language (`yeet/ui/chrome.py`, `yeet/ui/meter.py`):** consistent
  semantic colors and hints that fit whole key/action pairs into terminal cells.
  Short terminals drop extra context to preserve room for the focused row.

## Next improvements, in priority order

1. **Connect overview and exploration.** On wide terminals, keep a category or
   workflow list beside the contents rather than returning to a menu between
   tasks. Keep a stacked layout on narrow terminals. This is the biggest gap
   versus fix-storage and requires persistent navigation and scan state, beyond
   this first presentation pass.
2. **Add decision context.** Expand the focused row with measured share of the
   current scope, known activity dates, ownership, and the actual removal method.
   Carry trash/permanent state from handlers into the selector before
   displaying action-specific copy. Do not infer that a large or old item is junk.
3. **Extend in-screen scanning to cleanup workflows.** The explorer now streams
   directory batches. Other workflows should render incremental results with a clear
   measuring/complete/unreadable state. Preserve selection and cursor as results
   arrive. Avoid blocking the user's first interaction on a full scan.
4. **Complete the action loop.** Preserve the current list after cleanup, update
   measured totals, and show the actual reclaimed amount for the session. Offer
   restore only when the operation actually used trash.
5. **Add pointer interaction deliberately.** Row selection, breadcrumb jumps,
   and clickable key hints should invoke the same actions as keyboard controls.
   Enabling mouse support alone does not provide those interactions.

## Verification

The existing suite exercises all six interactive screens across six terminal
sizes, from 160×50 to 20×6, plus live resizing and the graphics renderer.
Before/after visual inspection uses deterministic example files and the character
meter fallback. It does not exercise real cleanup operations or real disk scans.

## Folder loading and rendering follow-up

- Removed the large startup logo; the welcome is a single line.
- Directory enumeration now runs off the UI thread and publishes batches. Folder
  sizes continue arriving in the background. Sorting preserves the focused path,
  and cancelled scan generations cannot overwrite the new directory.
- The folder meter groups loose files by stable types (Photos, Videos, Documents,
  etc.). Subdirectories are labeled Folders because their contents have not been
  recursively classified. List filters do not remove bytes from the inventory.
- This deliberately remains a **folder-scoped** meter. In fix-storage, the top
  meter remains the **whole-disk** category overview while the user drills into
  folders below it; it does not assign a new color to each large photo.
- With a cached parent size, unmeasured bytes stay unlit as results arrive.
  Without a known total, the bar explicitly reports **item progress**, revealing
  the measured category distribution by completed-item count. It does not claim
  that this count is a byte percentage or invent sizes for pending folders.
- Kitty graphics was already enabled for Ghostty. The work here reduces Python
  pixel conversion cost, removes the two-times-render-duration pacing penalty,
  and avoids waiting up to half a second for an old scan when navigating.
- Benchmark on this machine at 116 columns: roughly 30 ms/frame before, 19 ms
  after. These are raster/encoding measurements, not observed terminal FPS.
  Native Ghostty visual inspection was unavailable because the computer-use
  tool disallows access to that app.
