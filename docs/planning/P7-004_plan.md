# Workstream Plan: P7-004 — Source Mutation Completion States

## Metadata

| Field | Value |
|---|---|
| **Workstream** | P7-004 |
| **Phase** | Phase 7 — Post-Phase 6 User-Value Features |
| **Project** | Media Indexing Engine |
| **Dependencies** | P7-002 complete; P7-003 complete; `ARCH-002-reference-mode-storage.md` is the approved architectural basis for the storage pivot |
| **Estimated Size** | Large |
| **Created** | 2026-04-05 |
| **Status** | Revised after Auditor findings — awaiting operator review |

## Objective

Formalize and implement the rule that analysis is not the terminal success condition for media processing when the product expects source mutation. A processed item is only fully complete when the generated filename and required metadata have been applied to the source asset, or the system has explicitly recorded and surfaced why that source mutation is still pending or blocked.

This workstream defines the completion-state contract across three intake flows:

1. Google Drive processing
2. Browser drag-drop into the local working-folder flow
3. User-selected folder scan flow

## Scope

### In Scope

- Define canonical completion states for source mutation outcomes
- Define when analysis alone is insufficient to mark an item complete
- Add durable mutation-history tracking so the system knows what an image used to be before rename and metadata application
- Define per-flow mutation behavior for Google Drive, browser local working-folder intake, and user-selected folder scans
- Expand Google Drive from the completed P7-002 `drive.readonly` foundation to the writable permission model required for source mutation
- Surface completion state in Connections and item detail UX
- Define write-back orchestration expectations for immediate, pending, and blocked states
- Define the operator-approved fallback rule for cloud metadata write-back when embedded mutation is impossible, lossy, or intentionally deferred

### Out of Scope

- New source providers beyond the flows above
- Background device agent architecture
- Removing retained preview storage
- Final rollout of every storage-pivot workstream in one slice

## Locked Reconciliation Decisions

## 1. Google Drive Foundation vs P7-004 Mutation Contract

### Decision

P7-004 does include the Google Drive permission and source-mutation expansion needed to make Drive eligible for `fully_applied`.

### What stays true from P7-002

- P7-002 remains the completed read-only connector foundation
- root-only `My Drive` remains the starting container rule unless a later workstream expands it
- existing read-only Drive connectors remain valid for sync and analysis

### What P7-004 adds

- a writable Drive scope upgrade and re-consent path for mutation-capable sources
- Drive rename orchestration under the upgraded grant
- Drive embedded metadata write-back via rewrite-and-reupload
- state handling for older read-only connectors that cannot satisfy the mutation contract

### Required state rule

Any Google Drive source still authorized only with `drive.readonly` cannot reach `fully_applied` when source mutation is required. It must be classified as `blocked_writeback` until reauthorized with the upgraded writable grant.

## 2. Cloud Metadata Write-Back Fallback Rule

### Decision

Cloud metadata fallback is allowed only when it is explicitly approved per provider and writes the canonical metadata back to a source-side representation rather than leaving it only in AWS.

### Rule

For cloud sources:

- preferred path: embedded metadata write-back to the source bytes
- approved fallback path: provider-specific source-side metadata representation explicitly approved by the operator for that provider
- forbidden fallback path: app-only metadata persistence or permanent AWS original retention pretending to satisfy source mutation

### State consequences

- `fully_applied` requires rename success plus either successful embedded write-back or successful operator-approved source-side fallback
- `pending_writeback` applies when a safe rewrite/reupload or approved fallback write is queued and no user action is required
- `blocked_writeback` applies when writable permission is missing, no approved fallback exists, or the source-side mutation path is unsafe or terminally failed

### P7-004 provider-specific lock for Google Drive

Google Drive does not use fallback-only completion as its normal success path in this slice. P7-004 requires the real rewrite-and-reupload path for embedded metadata mutation after the Drive scope upgrade.

## Locked Completion-State Rules

## 1. Analysis Alone Is Not Completion

### Decision

Analysis success alone is insufficient to mark an item complete when the product requires source mutation.

### Rule

The system may mark AI analysis as complete, but the media item itself is not in the terminal success state until the required filename and metadata mutation have either:

- succeeded at the source, or
- been explicitly classified as pending or blocked and surfaced as such

### Consequence

The platform needs at least two orthogonal state dimensions:

- analysis state
- source-mutation completion state

## 2. Canonical Completion States

Every processed item that requires source mutation must end each orchestration attempt in exactly one of these states:

### `fully_applied`

- analysis completed successfully
- target filename was applied at the source when required
- required metadata write-back was applied at the source when required, either through embedded mutation or an operator-approved source-side fallback mode
- mutation history was written successfully
- no outstanding source-mutation action remains

### `pending_writeback`

- analysis completed successfully
- desired filename and metadata payload are known
- the system has queued or is retrying the required source mutation
- no user action is currently required to continue
- item is not considered terminally complete yet

Examples:
- Google Drive rewrite-and-reupload job still running
- provider-side transient failure eligible for retry
- immediate follow-up mutation job queued after analysis

### `blocked_writeback`

- analysis completed successfully
- required source mutation could not proceed to completion
- user action, capability limitation, or terminal failure is preventing completion
- item is not considered terminally complete yet

Examples:
- Google Drive auth expired
- provider permissions insufficient for rename or rewrite
- browser local flow lost folder access and needs re-selection
- file cannot be rematched confidently after rescan

## 3. Required Mutation-History Tracking

Every source-mutation-aware flow must persist enough history to answer:

- what the file was first called when the system saw it
- what it was called immediately before the latest rename
- what it is called now after the latest successful rename
- what metadata payload was last successfully written back
- when each successful or failed mutation attempt happened

### Minimum required fields

- `first_seen_source_filename`
- `prior_source_filename`
- `current_source_filename`
- `source_filename_applied_at`
- `last_successful_metadata_writeback_at`
- `last_successful_metadata_payload_hash` or equivalent revision marker
- `mutation_state`
- `last_mutation_error_code`
- `last_mutation_error_message` or operator-safe summary
- `last_mutation_attempted_at`
- source-specific locator snapshot or relative-path hint where relevant
- fingerprint fields required to rematch local files later

## Flow Rules

## 1. Google Drive Processing

### Happy path

1. User connects Drive and initiates processing.
2. System fetches bytes transiently from Drive.
3. System computes metadata, preview, and target filename.
4. If the source still holds the P7-002 read-only grant, the system must require reconnect / re-consent before source mutation can complete.
5. Under the upgraded writable Drive grant, the system attempts source rename immediately after analysis and then runs the metadata rewrite-and-reupload path.
6. If rename and metadata rewrite succeed, item becomes `fully_applied`.

### `pending_writeback`

Use when:

- the provider-side rewrite/reupload path is queued or retrying under the upgraded writable grant
- access token refresh succeeded but the mutation step has not yet completed
- the system expects a successful retry without further user action

### `blocked_writeback`

Use when:

- the Drive connector is still authorized only with the old `drive.readonly` grant and needs reconnect / re-consent
- Drive auth must be reconnected
- provider permissions do not allow the required mutation
- the Drive file no longer exists
- the source-specific mutation path reaches terminal failure

### Required mutation history

- original Drive filename on first import
- prior filename before each successful rename
- current filename after rename
- Drive file ID and revision/version snapshot where available
- last successful metadata payload written back

## 2. Browser Drag-Drop into Local Working-Folder Flow

### Happy path

1. User selects a local working/export folder.
2. User drags image(s) into the app.
3. Browser places the file into the selected local working folder when supported.
4. System analyzes the file and computes metadata plus target filename.
5. While current folder access is still granted, the system attempts local rename and metadata write-back immediately.
6. If those changes succeed, item becomes `fully_applied`.

### `pending_writeback`

Use sparingly here. It is valid only when:

- the system is still within the current user-granted folder session
- the write-back step has been queued immediately and no user intervention is yet required

This is expected to be brief, not long-lived.

### `blocked_writeback`

Use when:

- browser folder access is no longer granted
- browser capability is insufficient for the mutation path
- the file is no longer at the expected location in the granted folder
- the user must reselect the folder before mutation can continue

### Required mutation history

- first seen filename at intake
- prior filename before rename
- current filename after rename
- remembered local origin hint
- relative path inside the selected folder when available
- file fingerprint used for later rematch

## 3. User-Selected Folder Scan Flow

### Happy path

1. User selects a folder to scan.
2. System scans eligible images and computes metadata plus target filenames.
3. If the originals are reachable inside current granted access, the system attempts immediate rename and metadata write-back.
4. If mutations succeed, items become `fully_applied`.

### `pending_writeback`

Use when:

- immediate mutation jobs are still running within the currently granted folder-access session
- retryable failures are in progress and do not yet require user action

### `blocked_writeback`

Use when:

- the file is not found at the remembered location during current granted access
- the system cannot rematch the file confidently by fingerprint
- the user must reselect the containing folder
- browser capability blocks the mutation path

### Required mutation history

- first seen filename during scan
- prior filename before each successful rename
- current filename after rename
- folder label and relative-path hint when available
- file fingerprint and rematch history

## State Transition Guidance

### Allowed high-level transitions

- `analysis_complete` -> `fully_applied`
- `analysis_complete` -> `pending_writeback`
- `analysis_complete` -> `blocked_writeback`
- `pending_writeback` -> `fully_applied`
- `pending_writeback` -> `blocked_writeback`
- `blocked_writeback` -> `pending_writeback` when the user or system resolves the blocker
- `blocked_writeback` -> `fully_applied` when a retried mutation succeeds directly

### Prohibited simplification

Do not collapse `pending_writeback` and `blocked_writeback` into a generic warning state. They represent materially different product behavior.

## Implementation Workstreams Inside P7-004

### Step 1: Completion-State Data Model

**Goal:** add the durable state and history model required for source mutation completion.

**Expected outputs:**
- fields or tables for completion state
- source mutation history
- per-item mutation timestamps and errors

### Step 2: Google Drive Completion-State Orchestration

**Goal:** enforce the new contract on the Drive flow.

**Expected outputs:**
- writable-scope upgrade and re-consent path for existing Drive connectors
- immediate post-analysis rename attempt
- rewrite/reupload write-back path state handling
- `fully_applied` / `pending_writeback` / `blocked_writeback` behavior
- explicit blocked behavior for legacy read-only Drive grants

### Step 3: Browser Local Working-Folder Completion-State Orchestration

**Goal:** apply the same contract to browser-local flows.

**Expected outputs:**
- immediate source mutation while current folder access exists
- blocked state when folder re-selection is required
- fingerprint-based rematch flow

### Step 4: Completion-State UX

**Goal:** surface mutation state clearly.

**Expected outputs:**
- Connections status updates
- item-detail status updates
- action messaging for blocked and pending cases
- filename-history visibility where appropriate

### Step 5: Validation and Regression Coverage

**Goal:** ensure completion states are enforced consistently across flows.

**Required coverage:**
- analysis success without source mutation does not falsely mark `fully_applied`
- pending states retry correctly
- blocked states surface the correct user action
- mutation history persists original and prior filenames
- local rematch relies on fingerprint rather than filename alone

## Acceptance Criteria

- Analysis alone is insufficient to mark a source-mutation-required item complete.
- Each intake flow can classify items as `fully_applied`, `pending_writeback`, or `blocked_writeback`.
- Google Drive processing preserves filename and metadata mutation history.
- P7-002 read-only Drive connectors are explicitly reconciled: they remain valid for sync and analysis but are `blocked_writeback` until reauthorized with the writable grant required by P7-004.
- P7-004 defines an operator-approved cloud metadata fallback rule that forbids app-only or permanent-AWS-original fallback from counting as source mutation success.
- Browser drag-drop into the local working-folder flow preserves local mutation history and correctly blocks when folder access is lost.
- User-selected folder scan flow preserves rematch history and blocks when confident source rematch is not possible.
- Connections and item detail expose mutation state clearly enough that the user understands whether the source image has actually been updated.

## Next Gate

Operator reviews and approves this completion-state contract before any Engineer implementation work for the storage pivot begins.