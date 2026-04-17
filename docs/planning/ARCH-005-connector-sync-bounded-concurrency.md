# ARCH-005 — Connector Sync Throughput and Bounded Parallel Analysis

## Status

Architect planning note — future workstream proposal only.

This note does not change the active workstream. `P12-009` remains the current implementation and closeout focus. This note defines the recommended architecture and staged follow-on work if the operator wants to improve connector sync throughput without reopening the Phase 9 storage pivot.

## Historical Reason

The system became more serialized for an architectural reason, not by accident.

During the Phase 8 and Phase 9 storage pivot, the project removed transient and hidden app-retained connector originals as part of the ARCH-002 source-of-truth transition. Before that pivot, connector sync could tolerate looser overlap between import and downstream analysis because the app still had a more storage-centric recovery model. After `P9-001`, connector-ingested items are created directly as `storage_mode='reference'`, and `src/connectors/sync_service.py` now imports one object, reserves quota, persists source identity, and then awaits `analyze_connector_item(...)` inline before moving to the next object.

That change was intentionally accepted in ADR-031 as a short-term rollout tactic:

- close the zero-transient ingestion violation first
- avoid rebuilding retry semantics around hidden app-retained originals
- keep sync completion semantics simple while the system still lacked a separate source-refetch retry model for connector-ingested reference items

The current live code still reflects that decision explicitly:

- `src/connectors/sync_service.py` performs inline `await analyze_connector_item(...)` inside the per-object loop
- `src/analysis/processor.py` documents `analyze_connector_item()` as synchronous single-attempt analysis for connector-ingested reference-mode items
- analysis failure is isolated to the item, but sync throughput is effectively serialized by design

That historical reason was coherent and correct for the first zero-transient slice. It was a safe simplification while Phase 9 removed the architectural violation.

## Architectural Recommendation

The historical reason is no longer strong enough to preserve full inline serialization as a permanent rule.

It should remain a rejected long-term default because the original reason was rollout safety, not a durable throughput principle. The system now has the correct zero-transient and source-of-truth baseline, so the right next step is to reintroduce limited concurrency in a bounded way that does not weaken those guarantees.

### Recommendation

Reintroduce bounded concurrency now, but only for connector analysis after an item has been admitted into sync processing.

The narrowest safe first design is:

1. keep remote listing, idempotency checks, and run-level coordination serial
2. keep quota reservation explicit per item before analysis begins
3. allow only a small bounded number of admitted connector analyses to run concurrently
4. treat sync-run completion as "all admitted work settled," not merely "enumeration finished"
5. stop admitting new analysis work immediately on quota exhaustion, but drain already admitted work before finalizing the run

### Concurrency Boundary

Concurrency should apply only to connector analysis work in the first slice.

That means the first implementation should not attempt to parallelize:

- object listing
- idempotency comparison
- source-object skip decisions
- provider-wide enumeration
- connector configuration or run creation

The first implementation may overlap admitted item analysis tasks, but the sync coordinator should remain the single admission point.

### Why this boundary is the safest

- It preserves clear sync-run ownership and avoids turning the whole sync pipeline into a worker scheduler rewrite.
- It keeps quota behavior understandable because admission stays centralized.
- It keeps memory bounded because the coordinator can refuse to download and admit more analyzable items when the in-flight analysis window is full.
- It preserves the Phase 9 source-of-truth contract because no hidden retained-original replay path is introduced.

### Admission and Memory Rule

The coordinator must not build an unbounded backlog of downloaded bytes waiting for analysis slots.

The first slice should therefore enforce this rule:

- only admit a new analyzable connector item when an analysis slot is available
- do not prefetch a large queue of file bytes ahead of available worker capacity

This makes memory use roughly bounded by:

- `max_in_flight_connector_analyses`
- plus one coordinator-owned candidate item at most

That is the right first memory-control mechanism. A separate dynamic byte-budget scheduler is not required in the first slice.

### Configuration Recommendation

The first slice should be config-driven per environment, but tightly clamped.

Locked recommendation:

- add a dedicated connector-sync analysis concurrency setting
- default code path should remain conservative
- allowed effective range for the first rollout should be `1..3`
- operator rollout target should start at `2`
- expansion to `3` should require observed stability, not optimism

This is better than a hard-coded fixed fanout because local dev, staging, and production may need different safe starting points. It is also better than provider-specific or quota-aware tuning in the first slice because that would overcomplicate the initial rollout.

### Quota Recommendation

Quota admission should remain per-item and explicit.

Locked first-slice behavior:

1. reserve quota before spawning each analysis task
2. if reservation fails, stop admitting any further candidate objects in that run
3. keep already admitted tasks running to completion
4. finalize the run only after those admitted tasks settle
5. mark the run `completed_with_errors` with an aggregated summary that quota exhaustion stopped further admission

This preserves the current "stop on quota exhaustion" principle while making in-flight work completion explicit.

### Sync-Run Completion Recommendation

Sync-run completion must mean all admitted analysis tasks have reached a terminal outcome.

The run must not be marked completed just because enumeration ended while analysis tasks are still in flight.

Locked first-slice rule:

- the coordinator may enumerate and admit work incrementally
- but before writing the final `SyncRun.status` and `completed_at`, it must await every admitted task and aggregate its outcome

### Failure Surfacing Recommendation

Failures should be surfaced at two levels in the first slice:

1. per-item outcome
2. sync-run aggregated summary

The first slice should not introduce a new connector health-state subsystem.

Instead:

- each admitted item must still land in an explicit terminal result path
- analysis failures must be aggregated into sync-run counters and summary text
- `Source.connector_status` may continue using the current coarse `configured` versus `error` behavior

This is intentionally narrow. Better operator health modeling can come later if the rollout proves a real need.

### Mutation and Write-Back Contention Recommendation

Drive rename and metadata embed happen inside `analyze_connector_item()` today. The first slice should keep that behavior inside the same bounded analysis task rather than creating a second independent mutation fanout.

At a concurrency target of `2`, and optionally `3` only after evidence, that is an acceptable first operational boundary. A separate write-back scheduler is not required in the initial slice.

## Explicit Non-Goals

This proposal does not authorize the following:

- no reopening of Phase 9 or ARCH-002 source-of-truth rules
- no hidden or transient app-retained originals for connector items
- no whole-pipeline parallel rewrite of connector sync
- no provider-neutral adaptive scheduling system in the first slice
- no source-refetch retry redesign in the first slice
- no new connector health model or alerting subsystem in the first slice
- no UI redesign for sync monitoring in the first slice
- no attempt to parallelize object listing across providers or folders

## Proposed Workstreams

The work should be split into two ordered workstreams.

`P12-010` is the narrow implementation slice. `P12-011` should remain conditional follow-up only if the first slice proves stable and worth expanding.

## P12-010 — Bounded Connector Analysis Concurrency Foundation

### Objective

Reintroduce limited concurrent connector analysis during sync while preserving zero-transient storage, centralized quota admission, per-item failure isolation, and accurate sync-run completion semantics.

### Why now

The current inline-await model was accepted as a temporary safety tactic. It is now the main throughput bottleneck in connector sync, and the codebase has enough architectural maturity to support a small bounded admission model without reopening Phase 9.

### In scope

- keep a single sync coordinator in `sync_service`
- add a bounded in-flight analysis worker model for connector-ingested items
- centralize admission so quota is reserved before task creation
- prevent unbounded downloaded-bytes backlog by tying admission to available worker slots
- return structured analysis outcomes to the coordinator so sync-run counts and summaries reflect analysis results, not just import/download results
- require run-finalization drain behavior for all admitted tasks
- add focused tests for bounded concurrency, drain-on-finish, and quota-stop semantics
- add minimal operator-visible logging for admitted, completed, failed, and quota-stopped counts

### Out of scope

- no parallel listing or provider enumeration
- no provider-specific concurrency policy
- no byte-budget scheduler beyond the slot-based bound
- no new retry model for failed connector analysis
- no background queue subsystem for connector sync
- no UI changes for sync progress
- no new source health-state taxonomy

### Validation

- focused tests proving the worker cap is enforced
- focused tests proving sync run does not complete before admitted tasks finish
- focused tests proving quota exhaustion stops further admission but drains admitted tasks
- focused tests proving analysis failure increments run failure accounting and preserves per-item isolation
- focused tests proving no storage-path or hidden-original regression is introduced
- manual or scripted soak run against a small Drive source with concurrency set to `2`

### Auditor focus

- no drift against ADR-031 or ARCH-002 zero-transient rules
- no hidden retained-original replay path
- no fire-and-forget connector analysis tasks after sync-run completion
- sync-run counters and status reflect admitted task outcomes accurately
- quota stop semantics are deterministic and auditable
- memory remains bounded by slot-based admission rather than unbounded byte prefetch

### Rollout notes

- implement behind a dedicated connector analysis concurrency setting
- keep the default effective setting conservative
- first beta rollout should use `2`
- raise to `3` only if logs and operator validation show stable memory use, stable Drive behavior, and acceptable mutation contention
- if instability appears, the operator must be able to return to `1` without code changes

## P12-011 — Connector Sync Tuning and Operator Visibility Hardening

### Objective

Only after P12-010 proves stable, add the minimal second-stage controls needed to tune throughput safely across environments and providers.

### Why now

This workstream should happen only if the first slice demonstrates clear throughput value and exposes real operational pressure points that justify additional controls.

### In scope

- refine the configuration surface for per-environment safe limits
- add optional provider-specific caps if real throttling evidence exists
- add optional aggregated run-summary fields or logs that improve operator diagnosis
- add optional memory-safety refinement if slot-based admission alone proves insufficient in practice

### Out of scope

- no general-purpose distributed worker system
- no connector-wide adaptive autoscaling
- no whole-pipeline async rewrite
- no retry-contract redesign beyond narrow tuning needs
- no expansion to non-Drive provider semantics by assumption

### Validation

- soak validation comparing concurrency `1` versus `2` and optionally `3`
- operator review of memory use, throttling frequency, and mutation/write-back contention
- regression confirmation that quota and completion semantics from P12-010 remain unchanged

### Auditor focus

- tuning remains bounded and explainable
- provider-specific behavior is evidence-based rather than speculative
- no drift from the narrow `P12-010` contract

### Rollout notes

- this slice is optional
- only start it if the operator wants more headroom after the first bounded rollout

## Risks

Main technical and operational risks:

1. analysis-outcome accounting drift
   - the current sync flow already logs analysis exceptions as non-fatal, but it does not treat them as a first-class aggregated sync outcome. concurrency will make that ambiguity more dangerous unless the worker returns a structured result.

2. premature fanout growth
   - the biggest architectural risk is not bounded concurrency itself; it is allowing the first slice to become a generalized parallel sync rewrite.

3. memory spikes from queued bytes
   - if the coordinator downloads too far ahead of available slots, throughput gains will come with avoidable memory pressure.

4. upstream throttling
   - even small fanout can surface Drive throttling or transient API instability if admission is not conservative.

5. mutation contention
   - Drive rename and metadata embed currently run inside analysis completion. increased overlap can expose sequencing or rate-limit issues that were hidden by serialization.

6. misleading run completion
   - if sync-run terminal status is written before all admitted tasks settle, operator trust in sync history will degrade quickly.

## Recommended First Slice

The narrowest safe implementation plan is `P12-010` with these locked decisions:

1. add a dedicated connector analysis concurrency setting with an allowed first-slice range of `1..3`
2. keep one sync coordinator and one admission path
3. admit work only when a slot is available
4. reserve quota before spawning each analysis task
5. have each admitted task return a structured terminal result to the coordinator
6. stop new admission immediately on quota exhaustion
7. drain in-flight tasks before finalizing the run
8. keep Drive rename and metadata embed inside the bounded task
9. ship with operational rollback to `1`

This first slice should target a rollout value of `2`, not `3`.

## Decision

Go.

We should reintroduce bounded concurrent connector analysis during sync, but only through the narrow admission-controlled design above.

The historical synchronous-inline choice was justified as a temporary Phase 9 rollout tactic. It should not be preserved unchanged as a long-term architectural rule.

The correct next move is a conservative first implementation that overlaps only admitted connector analysis tasks, starts at an operator-safe fanout of `2`, preserves explicit quota and completion semantics, and keeps the whole change reversible by configuration.