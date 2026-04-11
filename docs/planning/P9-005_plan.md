# P9-005 Plan — Local Working-Folder Intake and Eliminate App-Retained Browser Originals

## Metadata

| Field | Value |
|---|---|
| **Phase** | Phase 9 — ARCH-002 Gap Remediation |
| **Project** | Media Indexing Engine |
| **Workstream** | P9-005 |
| **Created** | 2026-04-10 |
| **Author** | Architect |
| **Status** | Locked implementation plan — current approval gate; ready for Auditor pass and operator approval |
| **Dependencies** | P9-001 complete; P9-002 complete; P9-003 complete; P9-004 complete; `ARCH-002-reference-mode-storage.md`; `PHASE_9_arch002_gap_remediation_plan.md`; `P7-004_plan.md` |

## Objective

Finish the remaining ARCH-002 browser/local intake gap by removing the current permanent app-retained original path for ordinary browser upload and drag-drop flows.

After P9-005:

- browser-local intake must be working-folder-first
- new browser/local items must not create permanent AWS-retained originals
- local-folder items must be represented as source-aware records, not `app_upload` retained-origin records
- unsupported browsers must fail into an explicit unsupported/onboarding path rather than silently reverting to server-retained originals

This workstream is still Phase 9 work because it closes a real remaining ARCH-002 boundary violation under the clarified operator rule that permanent app-retained browser uploads are not acceptable steady-state product behavior.

---

## Architect Decision Summary

## Q1 — What browser/local intake modes remain valid?

### Locked decision

The product keeps only one valid ordinary browser/local intake mode in this workstream:

1. **No-install local working-folder intake**

Ordinary browser drag-drop or file selection must **not** create a new permanent AWS-retained original.

### Consequence

- the current retained-original `app_upload` browser path is no longer an acceptable default product behavior
- new browser/local processing must be modeled as source-aware local intake, not server-owned upload retention
- there is no separate equivalent transient client-side intake alternative in P9-005; unsupported environments are blocked into explicit unsupported/onboarding behavior instead

## Q2 — Is working-folder selection mandatory?

### Locked decision

Yes. A user-selected local working/export folder is mandatory before local drag-drop processing is enabled.

### Why this is the correct boundary

- the approved ARCH-002 policy explicitly requires working-folder-first local intake
- without a selected local folder, drag-drop would either have no durable local source target or would fall back to the disallowed AWS-retained original model
- making folder selection mandatory keeps the local source-of-truth on the user's device rather than inside app storage

### Consequence

- drag-drop/file-picker local processing UI must stay disabled until the folder prerequisite is satisfied
- the UI must explain that originals are placed into the selected local folder on the user's device rather than retained permanently in AWS
- unsupported browsers or environments that cannot satisfy the working-folder prerequisite must not process local files at all

## Q3 — How should new browser/local items be modeled?

### Locked decision

New browser/local items created through this flow must be modeled as **local working-folder source records**, not `app_upload` retained-origin records.

### Canonical record shape

- `Source.source_type = 'local_folder'`
- `MediaItem.storage_mode = 'reference'`
- `MediaItem.storage_path = NULL`
- `OriginAssetRef.provider_type = 'local_folder'`
- `OriginAssetRef.app_storage_path = NULL`
- `OriginAssetRef.local_file_fingerprint` populated
- `OriginAssetRef.locator_snapshot` stores non-authoritative local origin hints such as browser-reported relative path or folder label when available
- `PreviewAsset` remains the canonical retained preview record

### Consequence

- `provider_type='app_upload'` becomes a historical compatibility state only
- no ordinary browser/local flow may create new `OriginAssetRef(provider_type='app_upload')` rows after P9-005 lands

## Q4 — May the backend still receive bytes from the browser?

### Locked decision

Yes, but only as **transient analysis input**.

The backend may receive file bytes uploaded from the browser for validation, preview generation, pHash, analysis, and indexing, but it must not call `file_store.save()` for the original as part of the normal browser/local intake flow.

### Consequence

- the intake contract becomes: local file placed on user device first, bytes sent transiently for processing second, app-retained preview/metadata/search state third
- retry and re-analysis for these items cannot depend on app-retained originals and must instead depend on user re-supply or local-folder re-confirmation

## Q5 — What happens in unsupported browsers or capability failures?

### Locked decision

Unsupported browsers and failed local-folder capability checks must produce an **explicit unsupported/onboarding outcome**, not an AWS-retention fallback.

### Allowed outcomes

- explain that local no-install processing is unavailable in this browser/environment
- direct the user to a supported browser for local working-folder intake
- direct the user to a supported cloud-source onboarding path

### Rejected outcome

- silently reverting to permanent app-retained upload storage

## Q6 — Does P9-005 unify local-browser execution into the durable P9-004 operation engine?

### Locked decision

No.

P9-005 keeps local rename/metadata application on the existing client-mediated mutation-reporting path from P7-004.

### Consequence

- P9-005 is about intake/storage-boundary correction, not a local executor rewrite
- when local folder access is available, the browser may still attempt rename/metadata application and report the outcome through the existing mutation-result contract
- deeper unification with the durable operation engine is out of scope for this slice

---

## Locked Scope

## 1. Replace retained-original browser intake with working-folder-first intake

- remove product behavior that treats ordinary browser local intake as app-retained original upload
- require a selected local working/export folder before drag-drop local processing is enabled
- ensure newly created local items are source-aware `local_folder` items, not `app_upload` items
- do not allow ordinary browser/local processing through any equivalent transient fallback when the working-folder prerequisite is unavailable

## 2. Keep original processing bytes transient

- backend may validate, hash, generate preview, compute pHash, analyze, and index from transient browser-supplied bytes
- backend must not persist the original into app storage for this flow

## 3. Persist only retained preview/search/metadata state

- retain preview/thumbnail assets
- retain metadata, vectors, source linkage, origin hints, and mutation history
- do not retain the original permanently in app storage

## 4. Introduce explicit unsupported-browser behavior

- if the required browser file-system capabilities are unavailable, local processing must be blocked with a clear explanation
- supported fallback is cloud-source onboarding or supported-browser retry, not AWS-retained upload fallback
- there is no equivalent transient client-side processing escape hatch in unsupported environments for this workstream

## 5. Preserve historical compatibility without creating new debt

- historical `app_upload` rows remain readable and searchable
- no destructive migration deletes historical originals in this slice
- all new browser/local intake must avoid creating additional historical retained-original debt

---

## Service and UX Changes

## 1. Frontend intake gate

The Add Media / local intake UX must:

- require local folder selection before enabling drag-drop local processing
- clearly label the flow as local working-folder intake
- explain that originals are stored on the user's device, not permanently in AWS
- surface unsupported-browser messaging when folder writing/selection capabilities are unavailable
- prevent drag-drop/file-picker local processing entirely when the working-folder prerequisite cannot be satisfied

## 2. Local source creation and linkage

The frontend/backend intake contract must ensure:

- local working-folder items are linked to a `Source` with `source_type='local_folder'`
- a stable local fingerprint is persisted so the item can later be re-linked for source-side mutation
- non-authoritative local origin hints are persisted for better user re-confirmation UX

## 3. Backend intake path split

The backend must split the current browser upload behavior into:

- a local working-folder transient-processing path for ordinary browser/local intake
- no ordinary browser/local fallback path when working-folder prerequisites are unavailable

### Locked rule

No ordinary browser/local route may call `file_store.save()` for the original after P9-005.

If working-folder prerequisites are unavailable, the route must fail into explicit unsupported/onboarding behavior rather than accepting intake through an alternative transient browser path.

## 4. Re-analysis and retry semantics

For local-folder items created through P9-005:

- re-analysis must not assume `storage_path`
- when original bytes are required again, the user must re-confirm or re-supply through the local-folder flow
- any current route that cannot safely support that contract must return a controlled source-aware/local-reconfirmation requirement rather than silently using retained originals

## 5. Mutation/write-back boundary

Keep the existing local-browser mutation reporting contract:

- browser attempts local rename/metadata write when folder access exists
- backend records state using the existing mutation-result flow
- P9-005 does not move local execution into `WriteBackOperation`

---

## Compatibility Rules

## Historical `app_upload` rows

Historical app-retained upload rows are compatibility data in this slice.

### Locked treatment

- do not delete or mutate historical originals automatically
- do not rewrite all historical items to `local_folder`
- preserve existing read/search behavior for those rows
- stop creating new rows in that shape for ordinary browser/local intake

### Why automatic migration is rejected here

There is no safe server-side way to invent a replacement user-device source of truth for existing app-retained originals. Automatic destructive migration would risk data loss or false source linkage.

## `app_upload` provider type

`provider_type='app_upload'` remains valid only for historical compatibility rows already in the system.

### Locked rule

Engineer must not use `provider_type='app_upload'` for newly created ordinary browser/local items.

## Existing API compatibility

This slice should preserve existing successful response contracts where practical, but it may change local-intake preconditions and failure modes because the working-folder prerequisite is now mandatory.

---

## Migration and Rollout Strategy

## Schema policy

Prefer reusing the additive Phase 8/9 model already in place.

### Locked default

P9-005 should not add a new top-level persistent subsystem unless implementation proves an unavoidable gap.

The existing additive structures are expected to be sufficient:

- `Source`
- `MediaItem`
- `OriginAssetRef`
- `PreviewAsset`
- `SourceMutationHistory`

## Data migration policy

No destructive backfill of historical `app_upload` originals in this slice.

### Allowed operational add-on

Engineer may add a non-destructive audit/report script that counts historical `app_upload` rows and identifies which ones still retain originals, but that script must not delete user data.

## Rollout rule

The intake gate must change before or with the backend path change so the product cannot keep creating fresh retained-original browser items after rollout.

---

## Required Tests and Validation

Target: 12-20 new or updated tests. Existing 444 passed, 1 skipped baseline must continue to pass except where direct precondition changes require intentional test rewrites for local intake.

## Backend tests

1. ordinary browser/local intake does not call `file_store.save()` for the original
2. newly created local working-folder item persists `storage_mode='reference'` and `storage_path is NULL`
3. newly created local working-folder item creates `OriginAssetRef(provider_type='local_folder')`
4. newly created local working-folder item persists `local_file_fingerprint`
5. newly created local working-folder item creates `PreviewAsset`
6. ordinary browser/local intake no longer creates `provider_type='app_upload'`
7. re-analysis/download paths for the new local-folder flow do not assume retained originals and return the correct controlled outcome when re-confirmation is needed

## Frontend / route contract tests

8. local drag-drop processing is rejected when no working folder has been selected
9. unsupported-browser local intake shows explicit unsupported/onboarding outcome rather than falling back to retained upload
10. local intake path sends the required local-folder metadata for backend persistence
11. mutation-result flow for local items remains compatible after the intake rewrite

## Compatibility tests

12. historical `app_upload` items remain readable/searchable
13. historical `app_upload` items are not rewritten automatically during normal startup or migration
14. historical `app_upload` items do not block new local-folder item creation

## Validation expectations

- focused tests for the new local working-folder path must pass
- all existing Phase 9 regression suites must still pass unless an assertion is intentionally updated for the new mandatory local-folder precondition
- full backend regression baseline must be re-established before closeout

---

## Explicit Out of Scope

- destructive migration or deletion of historical `app_upload` originals
- inventing a live desktop agent or watched-folder daemon
- full unification of local-browser execution into the P9-004 durable operation engine
- broad connector/provider expansion beyond the existing Phase 9 scope
- capability history or additional durable capability subsystems beyond what P9-004 already introduced
- redesigning the Google Drive path that already closed in P9-004

---

## Documents That Must Be Updated Before Engineer Handoff

1. `docs/CURRENT_STATE.md`
2. `docs/WORKSTREAMS.md`
3. `docs/PROJECT_HANDOFF.md`
4. `docs/planning/PHASE_9_arch002_gap_remediation_plan.md`
5. `docs/planning/ARCH-002-reference-mode-storage.md`
6. `docs/DECISION_LOG.md`

---

## Architect Verdict

P9-005 is required because the clarified operator rule forbids permanent app-retained browser originals, and the current implementation still creates that retained-original path for ordinary browser/local intake.

The correct fix is not a full local execution redesign. It is a boundary correction:

1. require working-folder-first local intake
2. process browser-supplied bytes transiently
3. persist only preview/metadata/search/source-aware origin state
4. eliminate the ordinary `app_upload` retained-original creation path
5. preserve historical rows safely without creating new retained-original debt

That is the smallest implementation-ready slice that closes the remaining ARCH-002 browser/local intake gap while building directly on the Phase 8 and Phase 9 additive model already in place.