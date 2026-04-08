# Workstream Plan: P7-007 — Folder-Scoped Sync (Recursive Drive Traversal)

## Metadata

| Field | Value |
|---|---|
| **Workstream** | P7-007 |
| **Phase** | Phase 7 — Post-Phase 6 User-Value Features |
| **Project** | Media Indexing Engine |
| **Dependencies** | P7-002 (Drive connector), P7-006 (auto-sync scheduler) |
| **Estimated Size** | Small/Medium |
| **Created** | 2026-04-07 |
| **Status** | Completed |
| **Commit** | TBD |

## Objective

Ensure that when a user configures a Google Drive sync folder, the sync job
collects images **at all depths** within that folder — not just its immediate
children.

Prior to this workstream the `GoogleDriveConnector` queried
`'{folder_id}' in parents`, which returns only direct children of the
selected folder.  A typical photo library is organised in dated sub-folders
(e.g. `Photos/2024/January/`), so this single-level query silently missed the
vast majority of images.

## Problem Statement

The Drive Files API v3 does not support an `in ancestors` query operator that
would allow recursive listing in one call.  Code-level recursion is the only
reliable approach: list images and sub-folders at the current level, then
recurse into each sub-folder.

## Scope

### In Scope

- Refactor `GoogleDriveConnector.list_objects()` to perform BFS recursive
  traversal when `_folder_id` is set (P7-007).
- Keep flat (single-query) behaviour when no folder is scoped (all of My
  Drive) — unchanged from P7-002.
- Add `_list_in_folder()` helper (single level, paginated).
- Add `_collect_recursive()` helper (BFS, depth-limited).
- Add `_build_remote_object()` static helper (extracted from inline item loop).
- Add `_MAX_FOLDER_DEPTH = 10` guard to prevent runaway recursion on
  pathological folder structures.
- Per-item `max_keys` enforcement so the cap is respected across pages.
- Tests (9 new):
  - `test_list_objects_no_folder_uses_flat_query` — unchanged root behaviour
  - `test_list_objects_with_folder_recurses_into_subfolders` — core feature
  - `test_list_objects_recursive_respects_max_keys` — cap enforcement
  - `test_list_objects_depth_limit_stops_infinite_recursion` — depth guard
  - `test_drive_configure_sets_folder` — configure endpoint core path
  - `test_drive_configure_resets_to_root` — reset to root
  - `test_drive_configure_no_connector_404` — missing connector guard
  - `test_drive_configure_invalid_collection_404` — invalid collection guard
  - `test_drive_configure_wrong_user_404` — user-scoping guard

### Out of Scope

- UI changes (folder browser UI was already complete from P7-002b)
- New Drive API surface
- Pagination of sub-folder listing beyond pageSize=200

## Implementation Notes

### Recursive traversal design

```
list_objects(max_keys):
  if _folder_id is None:
    _list_in_folder(None, ...)   # flat search, unchanged
  else:
    _collect_recursive(_folder_id, depth=0, ...)

_collect_recursive(folder_id, depth):
  if depth > _MAX_FOLDER_DEPTH or len(results) >= max_keys: return
  _list_in_folder(folder_id, ...)  # images at this level
  for subfolder in list_subfolders(folder_id):
    _collect_recursive(subfolder.id, depth+1)
```

`_list_in_folder` uses the same `_BASE_QUERY` with `'{folder_id}' in parents`
for image files.  Sub-folders are listed with a separate query:
```
'{folder_id}' in parents and mimeType='application/vnd.google-apps.folder' and trashed=false
```

### Files modified

| File | Change |
|---|---|
| `src/connectors/google_drive_connector.py` | Refactored `list_objects`; added helpers |
| `tests/test_google_drive_connector.py` | 9 new tests (sections 14 & 15) |

### Files unchanged

The Drive connector's `target_folder_id` infrastructure (model, migration,
factory, configure endpoint, frontend UI) was fully built in P7-002b.  P7-007
only fixes the sync enumeration behaviour.

## Acceptance Criteria

- [x] `list_objects` with `folder_id` set recurses into sub-folders
- [x] `list_objects` without `folder_id` behaves identically to pre-P7-007
- [x] Depth guard prevents infinite recursion
- [x] `max_keys` cap respected per item across paginated responses
- [x] All 344 tests passing (335 pre-P7-007 + 9 new)
- [x] Configure endpoint tests cover core CRUD, scoping, and 404 guards
