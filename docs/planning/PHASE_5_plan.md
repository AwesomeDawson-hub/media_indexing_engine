# Phase Plan: Phase 5 — Smart Curation & Connected Ingestion

## Metadata

| Field | Value |
|---|---|
| **Phase** | Phase 5 — Smart Curation & Connected Ingestion |
| **Project** | Media Indexing Engine |
| **Dependencies** | Phase 4 complete; active beta live at `https://vyzindex.com` |
| **Estimated Size** | Focused sprint (3 workstreams) |
| **Created** | 2026-04-02 |
| **Status** | Draft — awaiting operator review and workstream approval |

## Phase Objective

Phase 5 moves the product from "organized searchable library" to "actively helpful library" by tackling the two highest-value beta gaps: media clutter and manual ingestion friction. The phase adds smart curation for burst shots and near-duplicates, then introduces the first real connected ingestion path so sources can feed the system with less manual effort. This is the right next phase because Phase 4 delivered the operational foundations (accounts, quotas, sources, billing groundwork, OCR) and the beta now needs product leverage, not more internal infrastructure.

## Definition of Done

Phase 5 is complete when all of the following are true:

- Near-duplicate images can be detected and grouped per user without interfering with existing exact-dedup behavior.
- Users can see duplicate groups in the Gallery and view a recommended best image when AI scoring is available.
- The first connector-based ingestion path is live for beta users with safe credential handling, idempotent sync behavior, and observable sync status.
- All schema changes are delivered via Alembic migrations.
- New read/query paths preserve DB-layer `user_id` scoping per ADR-012.
- Local validation and AWS beta smoke validation are complete for every workstream.
- No framework replacement is introduced; the phase stays within FastAPI + PostgreSQL + ChromaDB + React/TypeScript unless a new ADR explicitly justifies otherwise.

## Workstream Order

1. `P5-001` — Near-Duplicate Detection Core
2. `P5-002` — AI Best-Photo Selection
3. `P5-003` — Connector Sync Foundation & First Connector

The order is intentional: `P5-002` depends on the grouping model from `P5-001`, and `P5-003` is kept last because it introduces the most operational risk and should build on the now-stable Source Registry from Phase 4.

## Workstreams

### P5-001: Near-Duplicate Detection Core

**Objective**

Detect visually similar images within a user's library, group them safely, and surface those groups in the Gallery so users can collapse clutter without changing the existing exact-dedup upload rules.

**Key design decisions / approach**

- Compute a perceptual hash (`pHash`) from the stored original image asset, not from AI-derived metadata.
- Store the perceptual hash as an asset-level technical signal, separate from semantic AI metadata. The preferred location is on `media_items` or a small curation-specific companion table, not inside the AI metadata blob.
- Similarity is always user-scoped; no cross-user grouping or lookup is allowed.
- Use Hamming-distance thresholding with conservative defaults and make the threshold a backend constant/config value rather than a user-facing tuning control in this phase.
- Backfill pHashes for existing media with a one-time offline or scripted pass so existing beta libraries participate in grouping.
- Gallery UI should expose duplicate groups without rewriting the primary browse/search information architecture.

**Acceptance criteria**

- New uploads receive a perceptual hash at ingest or shortly after ingest.
- Existing media can be backfilled safely.
- A user-scoped similarity query can return near-duplicate groups using a stable Hamming-distance threshold.
- Gallery shows a "similar photos" or equivalent grouping affordance without hiding unrelated assets.
- Exact duplicate blocking via content hash remains unchanged.
- Tests cover hash generation, threshold matching, user scoping, and backfill safety.

**Estimated complexity**

`M`

**Architect review before implementation begins**

`Yes` — required because the phase needs a deliberate decision on where pHash lives in the schema and how grouping is surfaced without fighting the existing Gallery/search model.

---

### P5-002: AI Best-Photo Selection

**Objective**

Within near-duplicate groups, rank visually similar images and recommend the strongest candidate so users can make faster curation decisions on burst shots and slight variants.

**Key design decisions / approach**

- Build only on groups created by `P5-001`; do not attempt global aesthetic ranking across the whole library.
- Run AI scoring only for eligible duplicate groups to control cost and latency.
- Store scoring output in a dedicated curation-oriented structure (for example, quality score, rationale, best-pick flag, computed_at) rather than overloading the core 13-field metadata schema.
- Keep the scoring explainable: the UI should show a short rationale such as sharpness / subject expression / framing rather than a raw opaque score only.
- Make best-pick recommendations advisory, not destructive. No automatic hiding, deletion, or archival in this phase.

**Acceptance criteria**

- Eligible near-duplicate groups can be scored asynchronously.
- One image in a group can be marked as the recommended best pick.
- Gallery and/or Media Detail can display the recommendation and a brief rationale.
- Scoring is cached/persisted so repeated view loads do not re-trigger AI work unnecessarily.
- Failed or skipped scoring does not block the duplicate-group experience.
- Tests cover group eligibility rules, persistence, display payloads, and failure handling.

**Estimated complexity**

`M`

**Architect review before implementation begins**

`No additional review required once P5-001 is accepted` — this workstream may proceed directly if it follows the P5-001 grouping model and keeps recommendations advisory.

---

### P5-003: Connector Sync Foundation & First Connector

**Objective**

Extend the existing Source Registry into a real connected-ingestion system by adding sync state, incremental import behavior, and one production-ready connector path for beta use.

**Key design decisions / approach**

- Keep the workstream narrowly scoped to the connector foundation plus one connector, not a full multi-connector rollout.
- Preferred first connector: **S3-compatible bucket sync**. It fits the current hosted architecture, avoids OAuth/UI complexity, and aligns with the product's existing S3-compatible storage direction.
- Add explicit sync-run records and per-source sync state so operators and users can see what happened during import attempts.
- Credentials/config must be stored encrypted or otherwise protected according to existing deployment constraints; never plaintext in code or logs.
- Sync behavior must be idempotent and reuse the existing content-hash dedup pipeline rather than inventing a parallel ingest path.
- Phase 5 should support operator- or user-triggered sync plus a connector-ready foundation; fully general background scheduling across many connector types is deferred.

**Acceptance criteria**

- Source records can represent one connected source type beyond `manual`.
- A beta user can configure the first connector and trigger a sync successfully.
- Sync imports new objects through the existing ingestion pipeline and respects exact dedup/quota rules.
- Sync status/history is visible enough to debug failures.
- Secret/config handling is secure and excluded from logs/responses.
- Tests cover connector config validation, user scoping, idempotent re-sync behavior, and failure reporting.

**Estimated complexity**

`L`

**Architect review before implementation begins**

`Yes` — required because this workstream touches source schema extension, secrets handling, sync state, and the boundary between manual upload flows and automated ingestion.

## Deferred Items

- **Google Drive connector** — deferred because OAuth, token refresh, and provider-specific API behavior would over-expand a focused sprint.
- **Dropbox connector** — deferred for the same reason as Google Drive; it should build on the connector foundation, not precede it.
- **Local watched folders** — deferred because a hosted web app cannot safely watch a user's local filesystem without an additional agent or bridge component.
- **Full multi-connector scheduler/orchestration layer** — deferred until one connector proves the sync model and failure semantics.
- **Cross-user similarity search** — excluded because it conflicts with the project's strict user-isolation guarantees and is not needed for beta value.
- **Video duplicate detection or best-pick scoring** — deferred because the product remains image-first and video analysis is still outside the near-term roadmap.

## Risks and Open Questions

| Risk / Question | Why it matters | Affected workstream(s) |
|---|---|---|
| Where should pHash live in the schema? | Storing it in the wrong layer will create long-term coupling between binary-asset signals and AI metadata. | `P5-001` |
| What Hamming threshold is good enough for real user libraries? | Too low misses useful groupings; too high creates false groups and user distrust. | `P5-001` |
| How expensive should AI best-pick scoring be allowed to become? | Unbounded scoring can create real API cost and latency during beta. | `P5-002` |
| How should best-pick scoring behave when group membership changes after new uploads? | Re-ranking policy affects storage model and user trust in recommendations. | `P5-002` |
| What is the minimum viable sync visibility model? | Without sync-run history and actionable failures, beta users will treat connectors as unreliable. | `P5-003` |
| How should connector secrets be stored and rotated? | This is a security-sensitive area and must satisfy OWASP-style secret-handling expectations. | `P5-003` |
| Do we need scheduled sync in Phase 5 or is manual sync sufficient? | This determines whether the workstream stays sprint-sized or balloons into job orchestration. | `P5-003` |

## Notes

- Phase 5 intentionally avoids framework replacement. If connector scheduling pressure pushes the team toward a dedicated worker/scheduler architecture, that requires an ADR and likely belongs in a later phase rather than inside this sprint.
- The phase is purposely product-facing: it improves curation quality and ingest convenience for real beta users on `https://vyzindex.com` without reopening the large operational surface already delivered in Phase 4.