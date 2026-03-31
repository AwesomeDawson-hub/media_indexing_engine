# Phase Plan: Phase 4 — Beta Operations & Commercial Foundations

## Metadata

| Field | Value |
|---|---|
| **Phase** | Phase 4 — Beta Operations & Commercial Foundations |
| **Project** | Media Indexing Engine |
| **Dependencies** | Phase 3 complete; AWS beta deployment path validated |
| **Estimated Size** | Large (6 workstreams) |
| **Created** | 2026-03-31 |
| **Status** | Approved |

---

## Objective

Phase 4 turns the current deployable product into a controlled beta SaaS that can support real testers, enforce usage limits, preserve user workflow state, track media sources, and prepare the system for paid plans and administrative operations.

This phase is intentionally split between:

1. **Beta usability and control** — fix the most visible UX gaps in Gallery and Sources, preserve state correctly, and introduce monthly processing enforcement before broader user onboarding.
2. **Operational account management** — add profile data, admin controls, source tracking, and account-plan structures so the system can support multiple real users safely.
3. **Commercial foundation** — measure per-image costs, enforce plan limits, and prepare billing groundwork so pricing can later be attached to real product behavior without reworking quota/account state.

Every workstream in Phase 4 must be implementable locally, validated locally, and deployed to the AWS EC2 beta environment only after passing its defined validation checklist.

---

## Scope

### In Scope
- Gallery UX updates: always-visible filters, image-dimensions filter, filter-state preservation, processing-status display cleanup
- Media detail reorganization into metadata vs. additional search data
- Sources-page confirmation flow showing selected count and remaining monthly quota before analysis starts
- Server-side monthly processing limits and plan-aware upload enforcement
- Protection of original capture date and geo-location when writing AI metadata into downloaded files
- Source registry model: saved sources, source-aware image ownership, archive/restore for deleted sources, local/manual source path
- Admin area for internal operators/admin users only
- User profile management and account metadata (name, phone, company, icon)
- Email uniqueness enforcement audit and hardening
- Plan and limit data model needed for monthly quotas and future billing
- Cost-per-image measurement methodology and plan-to-limit mapping
- Stripe test-mode billing groundwork for monthly plans
- OCR/text-in-image extraction added to searchable metadata
- Password reset/account recovery and verified email-change flow

### Out of Scope for Phase 4
- Product naming/domain procurement work itself (operator-owned; handled separately)
- Restoring HTTPS on a real domain (operational follow-up after domain selection)
- Live paid plan launch in production
- Full video analysis pipeline
- Face-recognition/name-training workflow
- Broad multi-connector rollout across every cloud source on day one
- Enterprise sales workflow beyond a "contact for pricing" placeholder

### Deferred Candidate Backlog (not Phase 4 exit criteria)
- Per-user video ingestion and analysis rights with actual video AI processing
- Facial recognition with labeled reference photos and named people matching
- Google Photos-specific ingestion after connector abstraction stabilizes

---

## Constraints

All prior constraints apply. Additionally for Phase 4:

- **Validation-first:** no workstream is deployed to AWS until backend tests, frontend build, and a manual local smoke path pass.
- **Deployment discipline:** after local validation, each workstream must be smoke-tested in the AWS beta environment before being considered complete.
- **User isolation remains mandatory:** all new list, filter, admin, and source queries must enforce user scoping at the DB layer unless the route is explicitly admin-only.
- **Quota enforcement must be server-side:** frontend disabling is advisory only; the backend must reject over-limit processing attempts.
- **Quota enforcement must be transactional:** quota reservations and consumption updates must be atomic so concurrent uploads cannot overrun monthly limits.
- **Metadata overwrite safety:** AI enrichment must never overwrite original capture date or geo-location metadata in downloaded files.
- **Soft delete for sources only:** deleting a source must not immediately hard-delete associated media.
- **External connectors must be abstraction-first:** source tracking/data model lands before broad connector count explodes.
- **Admin access must be explicit:** no admin UI should render for standard users.
- **Admin authorization must be backend-enforced:** UI hiding is not authorization; every admin route requires explicit RBAC checks.
- **Admin actions must be auditable:** changes to user identity, limits, account status, or plan state must generate a durable audit record.
- **Schema-changing beta deploys require safety steps:** before any AWS deploy with an Alembic migration, take a database backup, rehearse the migration locally against a prod-like snapshot when feasible, and document a rollback path.
- **Billing authority must be webhook-driven:** no plan entitlement is granted from frontend redirect state alone; billing state changes require verified, idempotent webhook processing.
- **Billing remains non-launch:** Stripe test mode and billing authority design may be implemented in Phase 4, but live paid subscriptions remain blocked until stable HTTPS/domain, webhook verification, and operational readiness are complete.
- **OCR must remain bounded:** OCR text must be stored separately from core visual metadata, capped to a defined maximum indexed length, and weighted conservatively so it does not swamp visual relevance.
- **Broader beta onboarding gate:** exposed secrets must be rotated and a real HTTPS domain attached before broader external beta onboarding.

---

## ID Scheme

Phase 4 workstreams use the **`P4-XXX`** prefix.

---

## Workstreams

| ID | Name | Objective | Dependencies | Size |
|---|---|---|---|---|
| P4-001 | Gallery & Detail UX Continuity | Clean up Gallery filters, dimensions filters, status display, detail grouping, and state preservation | Phase 3 complete | M |
| P4-002 | Plans, Quotas & Analysis Confirmation | Add monthly processing limits, plan data model, source-page quota confirmation, and server-side enforcement | P4-001 preferred | M-L |
| P4-003 | Source Registry & Source-Aware Media | Track where media came from, persist multiple sources, support soft delete/archive/restore, and expose source-backed filtering once source records exist | P4-001 and P4-002 complete | M-L |
| P4-004 | Admin Console & User Profile Management | Add admin-only user management, backend RBAC, audited admin actions, self-service profile, verified email change, and account recovery | P4-002 complete | L |
| P4-005 | Billing Groundwork & Commercial Modeling | Measure image-processing cost, define plans in-app, and implement Stripe test-mode billing authority without enabling live paid launch | P4-002 and P4-004 complete | M |
| P4-006 | OCR Search Enrichment | Extract text from images, store it, and make it searchable/filterable as additional search data | P4-001 complete; P4-004 complete preferred | M |

---

## Workstream Sequencing

```
Phase 3 complete
      │
      ├──▶ P4-001 (Gallery UX)
      │         │
      │         ├──▶ P4-002 (Plans & Quotas)
      │         │         │
      │         │         ├──▶ P4-003 (Source Registry)
      │         │         │         │
      │         │         │         └──▶ source-backed filtering
      │         │         │
      │         │         └──▶ P4-004 (Admin & Profile)
      │         │                   │
      │         │                   ├──▶ P4-006 (OCR)
      │         │                   │
      │         │                   └──▶ P4-005 (Billing Groundwork)
      │         │
      │         └──▶ state continuity foundation complete
      │
      └──▶ Phase 4 beta-ready commercial foundation
```

Recommended order:

1. `P4-001` — visible UX debt first, because it affects every beta tester interaction and has no hidden dependency once the source filter is removed from scope.
2. `P4-002` — usage enforcement before inviting more users; it also defines the quota semantics that later plan and billing work must reuse.
3. `P4-003` — source persistence after quota/account semantics are defined, so source-aware confirmation and filtering are built on stable objects.
4. `P4-004` — admin controls and account recovery after plan/usage model exists.
5. `P4-006` — OCR enrichment after Gallery grouping is stable and admin/quota controls already protect beta operations.
6. `P4-005` — billing groundwork last, once plan limits, admin controls, and account lifecycle rules are real.

**Architect recommendation:** `P4-001` remains the correct first workstream. A prerequisite planning split is **not** required as long as the source filter is removed from `P4-001` and deferred to `P4-003`.

---

## Workstream Definitions

### P4-001: Gallery & Detail UX Continuity

**Objective:** Remove obvious beta-friction from Gallery and Media Detail so testers experience a stable, understandable browsing flow.

**Changes:**

1. Keep Gallery filters visible at all times; remove the "Show Filters" toggle.
2. Remove the "Source" button from the Gallery page because global navigation already exposes Sources.
3. Add image-dimensions filtering to Gallery. Support practical UX options rather than raw-only values (for example min/max width and height, or named dimension ranges).
4. Remove the "Completed" badge from items; only show a status badge when the item is actively processing.
5. Reorganize the Media Detail page into two sections:
   - Metadata
   - Additional Search Data
6. Preserve active Gallery filters, sort state, search query, and view mode when opening a detail page and returning back.

**Explicit non-goal:** `P4-001` does **not** introduce a persisted source filter. Source-backed filtering depends on `P4-003`.

**Exit criteria:**
- Gallery filters are always visible in browse and search modes.
- Detail navigation returns the user to the same Gallery state they left.
- Status badges only appear for in-progress items.
- New dimensions filters work in both browse and search contexts.

**Validation requirements:**
- Backend tests for any new filter params.
- Frontend build passes.
- Manual local smoke flow: set filters → open detail → return → state preserved.
- Manual AWS smoke flow on deployed beta after release.

---

### P4-002: Plans, Quotas & Analysis Confirmation

**Objective:** Introduce monthly processing controls and explicit user confirmation before analysis begins.

**Changes:**

1. Add per-user monthly image-processing limits to the data model.
2. Track monthly usage with explicit reservation and consumption semantics.
3. On Sources page, after file selection but before upload/analysis begins, show a confirmation prompt including:
   - count selected
   - remaining monthly allocation
   - warning that metadata will be overwritten by AI analysis
   - explicit note that original date and geo-location metadata are preserved
4. Disable or block confirmation when the selected count exceeds the remaining monthly allocation.
5. Enforce the same limit server-side so direct API calls cannot bypass the quota.
6. Define plan-limit fields that later billing work can use directly.

**Quota-accounting semantics (required):**

- **Counted event:** quota is consumed for each newly accepted analysis request for a user-owned media item.
- **Reservation timing:** quota is reserved transactionally on the backend before analysis work is enqueued.
- **Successful completion:** a reserved unit becomes consumed for the current calendar month when the analysis job completes successfully.
- **Failed analysis:** if analysis fails before success, the reserved unit is released so it does not reduce the user's monthly consumed total.
- **Duplicate uploads:** exact duplicates that do not create a new analysis request do not consume or reserve additional quota.
- **Re-analysis policy:** manual re-analysis consumes quota and must pass the same reservation check as first-time analysis.
- **Concurrency rule:** reservation and remaining-quota checks must happen atomically so concurrent upload requests cannot exceed the monthly limit.
- **Authority:** frontend quota displays are advisory; the backend reservation record is the source of truth.

**Implementation expectation:** this workstream should prefer a usage-ledger or reservation model over a single mutable counter so admin review, refunds, and future billing reconciliation remain possible.

**Exit criteria:**
- User cannot process beyond monthly allowance.
- Confirmation modal reflects actual remaining allowance.
- Backend rejects over-limit requests with a clear structured error.
- Metadata overwrite flow preserves date/time and geo-location values in output files.

**Validation requirements:**
- Backend tests for usage counting, monthly reset behavior, and over-limit rejection.
- Backend tests for reservation races / concurrent over-limit protection.
- Frontend tests or manual validation for disabled confirm state.
- Manual local smoke flow with under-limit and over-limit scenarios.
- AWS smoke flow with a test user account after deploy.

---

### P4-003: Source Registry & Source-Aware Media

**Objective:** Treat sources as first-class user objects so the system can remember where images came from and allow multiple saved sources.

**Changes:**

1. Add a `Source` data model with soft-delete/archive support.
2. Associate each media item with its originating source when applicable.
3. Display saved sources on the Sources page.
4. Support source archive/restore for deleted sources.
5. Allow users to name a source and persist it for reuse.
6. Support the **local/manual source** path as the only required concrete source type in Phase 4.
7. Expose source-backed filtering in Gallery and related APIs once persisted source records exist.

**Implementation note:**
This workstream should establish the durable source model and a connector-friendly abstraction, but **broad connector rollout is not a Phase 4 closeout requirement**. URL/web directory and cloud connectors remain future additive work after the source entity model is stable.

**Exit criteria:**
- A user can have multiple saved sources.
- Gallery source filter is backed by real persisted source data.
- Deleting a source archives it instead of destroying historical linkage.
- Archived sources can be restored.
- Local/manual source is fully supported end-to-end.

**Validation requirements:**
- DB migration and model tests for source relationships and soft delete.
- API tests for create/list/archive/restore flows.
- Manual local smoke flow with multiple sources and archive restore.
- AWS smoke flow after deploy.

---

### P4-004: Admin Console & User Profile Management

**Objective:** Add operational user management for admins and self-service profile management for standard users.

**Changes:**

1. Add a backend-enforced RBAC model with an explicit admin role.
2. Add an admin-only area visible only to authorized admin accounts.
3. Admin area shows for each user:
   - name
   - phone number
   - email
   - company name
   - current plan
   - monthly processing limit
   - processed image counts by month
   - account status
4. Admin actions:
   - change email address
   - disable account
   - change monthly processing limit
   - upload or update user icon
5. Record a durable audit trail for every admin action that changes user identity, status, limits, plan, or billing-relevant metadata.
6. Add a user Profile page for self-service updates of allowed profile fields (not plan selection).
7. Add a verified email-change flow rather than unrestricted silent email mutation.
8. Add password reset/account recovery for beta users.
9. Audit and enforce unique email addresses in the database and API.

**Authorization rules (required):**

- Admin UI visibility alone is insufficient; all admin APIs must reject non-admin users.
- Standard users may edit only their own explicitly allowed profile fields.
- Plan selection and billing state are never self-service in this workstream.
- Email change must require a verification or equivalent controlled confirmation flow.
- Admin changes must be attributable to the acting admin account.

**Exit criteria:**
- Non-admin users never see admin UI/routes.
- Non-admin users cannot access admin APIs even by direct request.
- Admin can inspect and update user operational fields.
- Standard users can update their own profile info.
- Email uniqueness is guaranteed by both DB constraint and API behavior.
- Password reset/account recovery works for beta users.
- Admin actions are audit logged.

**Validation requirements:**
- Backend auth/authorization tests.
- Migration tests for any new user/account fields.
- Frontend build passes.
- Manual local admin + non-admin smoke flows.
- AWS smoke flow using at least one admin and one non-admin account.

---

### P4-005: Billing Groundwork & Commercial Modeling

**Objective:** Connect usage to modeled subscription plans and implement billing authority groundwork without enabling live paid launch during Phase 4.

**Changes:**

1. Measure approximate per-image processing cost across the current pipeline.
2. Encode plan tiers in the system:
   - Basic: 500/month
   - Advanced: 1,500/month
   - Premium: 5,000/month
   - Enterprise: contact path
3. Integrate Stripe (or equivalent) in **test mode only** for recurring monthly subscription groundwork.
4. Map subscription state to plan entitlements and monthly limits.
5. Define account-plan status handling for delinquent/cancelled billing states.
6. Implement verified, idempotent webhook processing as the only authority for billing-state transitions.

**Explicit Phase 4 boundary:** this workstream does **not** enable real paid subscriptions for production users. Live commercialization remains blocked until the system has a stable HTTPS domain, verified webhook delivery, and operator approval to launch billing.

**Exit criteria:**
- Cost model exists and is documented well enough to validate plan pricing.
- Stripe recurring subscription flow works in test mode.
- Plan entitlements are applied automatically from subscription state.
- Usage limits and admin views reflect the active plan.
- Frontend redirect state alone cannot grant entitlements; webhook events are the source of truth.

**Validation requirements:**
- Test-mode Stripe integration validation.
- Webhook signature verification and idempotency tests.
- Backend tests for plan/limit transitions.
- Manual local billing flow in Stripe test mode.
- AWS smoke validation using test-mode keys only.

---

### P4-006: OCR Search Enrichment

**Objective:** Extract readable text from images and add it to search/index metadata.

**Changes:**

1. Add OCR extraction to the analysis pipeline or post-analysis enrichment flow.
2. Store detected text separately from core visual metadata.
3. Surface OCR text under "Additional Search Data" in Media Detail.
4. Include OCR text in the searchable/indexed data path.
5. Cap the maximum stored/indexed OCR text length to prevent oversized payloads and noisy search vectors.
6. Weight OCR text conservatively in search/index composition so it improves recall without overwhelming visual metadata relevance.

**Constraints:**

- OCR text must remain a separate field/class of metadata, not merged into title/description.
- OCR text remains subject to the same DB-layer user isolation and API scoping rules as all other searchable data.
- OCR should be treated as potentially sensitive extracted content; only the owning user (or authorized admin) may view it.
- If OCR quality is low or empty, the pipeline should preserve search quality rather than forcing noisy text into the index.

**Exit criteria:**
- Text present in images becomes searchable.
- OCR text is visible in Media Detail under the correct grouping.
- Search relevance still behaves sensibly when OCR text is present.
- OCR text length caps and weighting rules are implemented and verified.

**Validation requirements:**
- Unit/integration tests using images with known text.
- Search tests verifying OCR text retrieval.
- Manual local smoke flow with OCR-positive images.
- AWS smoke validation after deploy.

---

## Phase 4 Exit Criteria

Phase 4 is complete when:

- [ ] Gallery and Media Detail preserve state and show the new UX structure.
- [ ] Monthly image-processing limits are enforced server-side.
- [ ] Source tracking exists as a first-class persistent concept.
- [ ] Admin users can manage accounts and standard users can maintain profiles.
- [ ] Plan limits exist in code and can be enforced per user.
- [ ] OCR text is added to additional search data and search retrieval.
- [ ] Schema-changing beta deploys in this phase were backed up, rehearsed, and rolled out with documented rollback paths.
- [ ] Every completed workstream has local validation plus AWS beta smoke validation recorded.

---

## Architectural Decisions to Record During Phase 4

Expected ADRs as workstreams begin:

- **ADR-013:** Monthly processing quota uses explicit backend reservation/consumption semantics, including duplicate and re-analysis handling.
- **ADR-014:** Source entities become first-class records with archive/restore lifecycle semantics and local/manual source as the Phase 4 required path.
- **ADR-015:** Admin access is backend-enforced RBAC with durable audit logging for privileged actions.
- **ADR-016:** Billing state is webhook-driven, signature-verified, idempotent, and test-mode only in Phase 4.
- **ADR-017:** OCR text is stored separately from primary metadata, length-limited, weighted conservatively, and included in search indexing.
- **ADR-018:** Account recovery and verified email change are required account-lifecycle controls for beta operations.
