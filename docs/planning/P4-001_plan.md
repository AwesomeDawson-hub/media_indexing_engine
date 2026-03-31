# Workstream Plan: P4-001 — Gallery & Detail UX Continuity

## Metadata

| Field | Value |
|---|---|
| **Workstream** | P4-001 |
| **Phase** | Phase 4 — Beta Operations & Commercial Foundations |
| **Project** | Media Indexing Engine |
| **Dependencies** | Phase 3 complete; revised Phase 4 plan approved |
| **Estimated Size** | Medium |
| **Created** | 2026-03-31 |
| **Status** | Approved |

## Objective

Remove the most visible Gallery and Media Detail UX friction before broader beta onboarding. This workstream stabilizes browse/search continuity, keeps filtering controls visible, simplifies status presentation, and reorganizes detail-page information so users can move through the product without losing context.

## Scope

### In Scope

- Keep Gallery filters visible at all times in both browse and search modes
- Remove the Gallery-level "Source" button because Sources already exists in global navigation
- Add Gallery image-dimensions filtering with a practical UX shape
- Remove the "Completed" status badge so only active/in-progress states are visually emphasized
- Reorganize Media Detail into two sections:
  - Metadata
  - Additional Search Data
- Preserve Gallery state when navigating to a Media Detail page and back:
  - search query
  - active filters
  - sort choice
  - page number where feasible
  - grid/list view mode
- Any backend/API changes required to support the dimensions-filter UX and stable state restoration
- Local validation and AWS beta smoke validation after local success

### Explicit Non-Goals

- **No source-backed Gallery filter in this workstream.** Persisted source filtering is deferred to `P4-003`.
- No source data model, source relationships, or source archive/restore behavior
- No monthly quota enforcement, usage accounting, or confirmation modal changes (`P4-002`)
- No admin, profile, email-change, or account-recovery work (`P4-004`)
- No billing, Stripe, or commercial entitlement logic (`P4-005`)
- No OCR extraction or OCR-driven search changes (`P4-006`)
- No broad visual redesign or new information architecture beyond the specific continuity fixes listed here

## Constraints

- **State continuity over novelty:** preserve user context across navigation without introducing new data-model dependencies.
- **No hidden dependency on sources:** any UI affordance that requires persisted source records is out of scope.
- **User isolation remains mandatory:** any new browse/search query behavior must continue enforcing `user_id` at the DB layer per ADR-012.
- **Query parameter compatibility:** state preservation should prefer URL/search-param driven state where practical so refresh and back navigation stay predictable.
- **No schema change unless truly required:** prefer frontend/router/query-state solutions and existing API fields where possible.
- **Deploy discipline:** do not deploy to AWS beta until local validation passes.

## Dependencies and Boundaries

### Upstream Dependencies

- `P3-001` delivered the unified Gallery page, dimensions in API responses, and current browse/search filtering surface.
- `P3-003` delivered multi-select state handling in Gallery; this workstream must not regress it.
- Post-Phase-3 bug fix `fd5013e` corrected first-search relevance behavior in `GalleryPage.tsx`; this workstream must preserve that behavior.

### Downstream Dependencies

- `P4-002` will reuse the Gallery/Sources continuity expectations but must not be implemented here.
- `P4-003` will add persisted source-backed filtering later; `P4-001` must not fake or partially introduce it.

## Detailed Changes

### Change 1: Filters Always Visible

**Goal:** remove the hide/show filter toggle and keep the filtering controls visible in both browse and search states.

**Implementation expectations:**
- Remove the "Show Filters" interaction if it still exists in the Gallery surface.
- Ensure the filter section renders consistently in browse and search modes.
- Preserve existing filter behavior for orientation, aspect ratio, people, file type, mood, sort, and any dimensions controls.

### Change 2: Remove Gallery Source Button

**Goal:** eliminate redundant navigation from Gallery to Sources.

**Implementation expectations:**
- Remove the Gallery page button/link labeled "Source" if present.
- Do not remove the global Sources navigation entry.
- Do not replace this with a source-backed filter; that belongs to `P4-003`.

### Change 3: Dimensions Filtering UX

**Goal:** let users narrow results by image dimensions in a way that is understandable and implementable with the current backend stack.

**Preferred implementation direction:**
- Use practical min/max width and height controls, or a small number of named size buckets, rather than exposing raw database internals.
- Keep the control shape consistent between browse mode and search mode.
- If backend query params are needed, they must remain user-scoped and compatible with the existing `/api/v1/media` and `/api/v1/search` filtering approach.

**Boundary:** this is dimensions filtering only. It must not expand into source semantics or quota-aware UX.

### Change 4: Status Badge Simplification

**Goal:** reduce visual noise in Gallery.

**Implementation expectations:**
- Do not show a badge for items that are fully completed.
- Continue showing badges for states that require user awareness, such as processing or error.
- Keep behavior consistent between grid and list presentations.

### Change 5: Media Detail Grouping

**Goal:** make the Media Detail page easier to understand by separating core metadata from extra search-oriented data.

**Required grouping:**
- **Metadata** — core user-facing media description fields
- **Additional Search Data** — supplementary information that supports retrieval rather than primary labeling

**Boundary:** this workstream reorganizes presentation only. It must not redefine the Phase 4 OCR model or add new metadata fields.

### Change 6: Return-to-Gallery State Preservation

**Goal:** when a user opens a detail page from Gallery and returns, they land back in the same browse/search context.

**Required state to preserve:**
- query string / search term
- active filters
- sort order
- view mode (grid/list)
- page number where the current routing structure allows it cleanly

**Implementation expectations:**
- Prefer URL-driven state for navigation continuity.
- Avoid brittle in-memory-only behavior that breaks on refresh or browser back.
- Preserve existing corrected search-submit behavior from the post-Phase-3 fix.

## Files Likely Affected

These are expected touchpoints, not a mandatory exhaustive list:

- `frontend/src/pages/GalleryPage.tsx`
- `frontend/src/pages/MediaDetailPage.tsx`
- `frontend/src/components/Layout.tsx` (only if redundant button/nav cleanup lives there)
- `frontend/src/api/client.ts` (if filter wiring changes)
- `src/api/routes/media.py` (only if dimensions filtering needs backend adjustment)
- `src/api/routes/search.py` or search service layers (only if dimensions-filter parity requires small adjustments)

## Security and Architectural Guardrails

- Any new or adjusted browse/search query must continue enforcing `MediaItem.user_id == user_id` at the database layer.
- No admin-only or quota-sensitive behavior should be introduced indirectly through this UI workstream.
- Do not add source identifiers, source joins, or placeholder source filters that imply `P4-003` is partially complete.
- Do not add local-only state hacks that make AWS beta behavior diverge from local behavior.

## Validation Requirements

### Automated Validation

- Backend tests for any new or changed filter parameters
- Backend tests for user-scoped filtering if query behavior changes
- Frontend build passes
- Existing tests continue to pass

### Manual Local Smoke Flow

1. Open Gallery in browse mode
2. Apply several filters and a sort option
3. Switch grid/list view if available
4. Open a media item from the filtered result set
5. Return to Gallery
6. Confirm query/filter/sort/view state is preserved
7. Repeat in search mode with an active query
8. Confirm completed items do not show unnecessary badges
9. Confirm dimensions filter affects results sensibly in both browse and search modes

### Manual AWS Beta Smoke Flow

After local validation passes and deployment is complete:

1. Repeat the browse-mode state preservation flow in AWS beta
2. Repeat the search-mode state preservation flow in AWS beta
3. Confirm filters are always visible
4. Confirm no broken navigation to Sources
5. Confirm no regression in first-search relevance sorting

## Deployment Checklist

- [ ] Relevant backend tests pass locally
- [ ] Frontend build passes locally
- [ ] Manual local smoke checklist completed
- [ ] No schema migration required, or if one is introduced unexpectedly it follows the Phase 4 migration safety rules
- [ ] AWS beta deploy performed only after local validation passes
- [ ] AWS smoke checklist completed
- [ ] Any doc updates required by closeout are identified

## Rollback Expectations

- If the new state-preservation approach causes navigation regressions, revert to the last known-good Gallery/detail navigation behavior from Phase 3.
- If dimensions filtering introduces incorrect result sets or user-isolation risk, disable only the new dimensions UX and preserve the rest of the continuity fixes.
- If AWS beta shows state divergence not seen locally, roll back the deployment and investigate before re-release.

This workstream should remain low-risk and reversible. It must not introduce irreversible data-model changes.

## Exit Criteria

- [ ] Filters are always visible in Gallery browse and search modes
- [ ] The redundant Gallery Source button is removed
- [ ] Dimensions filtering works in both browse and search contexts
- [ ] Only active/in-progress items show status badges
- [ ] Media Detail clearly separates Metadata from Additional Search Data
- [ ] Returning from Media Detail restores the user to the same Gallery context
- [ ] Local validation is complete
- [ ] AWS beta smoke validation is complete
- [ ] No source-backed filtering behavior was introduced in this workstream

## Notes for Engineer

- Keep the implementation narrow. If a change appears to require persisted source records, stop and leave it for `P4-003`.
- Prefer the smallest set of backend changes needed to support the UX continuity goals.
- Treat this as a stabilization pass, not a redesign pass.