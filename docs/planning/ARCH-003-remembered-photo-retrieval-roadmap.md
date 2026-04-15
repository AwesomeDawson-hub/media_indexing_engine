# ARCH-003 — Remembered-Photo Retrieval Search Roadmap

## Architecture Assessment

The current search stack underperforms on highly specific remembered-photo queries because it is structurally optimized for broad semantic similarity over shallow metadata, not for compositional recall.

The main limitations in the current architecture are:

1. **Metadata is broad but shallow.**
   The current analysis schema captures `title`, `description`, `tags`, `objects`, `scenes`, `context`, `mood`, `people`, `people_count`, `orientation`, `colors`, `location_hint`, and `quality_notes`, but it does not explicitly model:
   - subject position (`left`, `center`, `foreground`, `background`)
   - subject relationships (`person holding ice cream`, `couple near window`)
   - subject attributes (`red shirt`, `smiling woman`, `hat`, `glasses`)
   - emotional expression at subject level
   - visual tonality / lighting / contrast beyond a single coarse `mood`
   - composition structure (`framed by window`, `backlit`, `close-up`, `wide establishing shot`)

2. **Analysis prompt encourages flattened summaries.**
   The current Anthropic prompt in the analysis provider asks for one compact JSON object with generic fields. That is useful for broad categorization, but it does not force the model to preserve fine-grained remembered-photo retrieval signals.

3. **Embedding text collapses structure into one flat document.**
   The indexing pipeline concatenates title, description, tags, objects, scenes, context, mood, colors, people, orientation, location, and OCR text into a simple stitched document. This loses important distinctions such as:
   - whole-image tone vs subject-specific attributes
   - global context vs spatially anchored facts
   - multiple people with different roles/positions
   - composition details that should be separately emphasized

4. **Retrieval is mostly single-stage vector recall.**
   Current search embeds the user query, fetches vector hits, then applies limited post-filters. This is effective for broad semantic retrieval, but weak for exact remembered queries because:
   - no structured retrieval layer can directly leverage attribute or composition fields
   - no reranking stage checks whether the top candidates really match the remembered description details
   - no query decomposition or narrowing exists for ambiguous remembered-photo descriptions

5. **Search UX gives limited disambiguation tools.**
   The current search filters cover broad dimensions like people, orientation, mood, MIME type, size, aspect ratio, and tags, but do not help the user iteratively refine remembered-photo queries using subject placement, relational clues, tone, or attribute facets.

6. **No explicit evaluation set exists for remembered-photo retrieval quality.**
   Current tests validate that search works, is scoped correctly, and returns results, but not that top-1 or top-5 quality improves for remembered-photo queries.

The architectural conclusion is that the product should not jump directly to a full multimodal retrieval rewrite. The first wave should enrich structured analysis and index construction so the current search architecture has more discriminative material to work with.

---

## Planning Strategy

The upgrade should be staged in additive layers, each with an approval and audit boundary:

1. **First improve representation** so the system actually captures the details remembered-photo queries depend on.
2. **Then improve indexing and ranking** so those richer signals influence retrieval.
3. **Then improve search UX** so users can narrow and disambiguate effectively.
4. **Only after those steps are proven** should the project consider multimodal/image-text embedding expansion.

This keeps schema evolution, analysis prompt changes, retrieval changes, UX changes, and evaluation changes separated enough to remain understandable, testable, and auditable.

The roadmap deliberately avoids a big-bang rewrite. It favors:

- additive schema evolution
- backfillable metadata improvements
- isolated retrieval/reranking upgrades
- measurable top-1 and top-5 evaluation gains on remembered-photo queries
- explicit Auditor gates before broader scope is unlocked

---

## Proposed Workstreams

### P12-002: Remembered-Photo Evaluation Baseline and Query Set

**Objective**

Create the evaluation foundation for remembered-photo retrieval so every later search-quality workstream can be measured against the same query set and scoring rules.

**Why now**

Without an agreed evaluation dataset, every retrieval improvement claim will be subjective. This workstream creates the contract for what “better search” means before schema or ranking changes begin.

**Dependencies**

- Current search implementation baseline (`WS-003` plus later additive search/filter work)
- Existing governance and validation discipline

**In scope**

- Define a curated remembered-photo query set covering:
  - subject attributes
  - spatial layout/composition
  - subject relationships
  - emotion/expression
  - visual tone / lighting / mood
  - ambiguous broad semantic queries for regression comparison
- Define evaluation labels for top-1, top-5, and “acceptable in top-5 but not top-1” outcomes
- Define a repeatable offline evaluation harness or script boundary for scoring retrieval quality
- Define success metrics and reporting format for all later workstreams
- Capture a frozen baseline using the current architecture before later improvements begin

**Out of scope**

- Metadata schema changes
- Retrieval logic changes
- UI changes
- Multimodal retrieval

**Validation**

- Baseline evaluation set exists and can be rerun consistently
- Metrics are produced for current search behavior, including at minimum:
  - top-1 hit rate
  - top-5 hit rate
  - query-class breakdown by category
- Auditor can verify that later workstreams are using the same benchmark set rather than moving the goalposts

**Auditor focus**

- Is the benchmark query set broad enough to cover remembered-photo retrieval rather than only broad semantic queries?
- Are the scoring rules explicit and stable?
- Does the workstream avoid sneaking in retrieval changes before the baseline is locked?

**Expected user impact**

- No immediate user-facing change
- Creates the foundation for trustworthy search-quality claims later

### P12-003: Richer Search Metadata Schema and Extraction Contract

**Objective**

Extend the metadata contract so the system can explicitly represent composition, subject attributes, relationships, emotional expression, and visual tonality needed for remembered-photo queries.

**Why now**

The current metadata contract is the main bottleneck. Better ranking or embeddings cannot recover information that was never extracted or stored.

**Dependencies**

- `P12-002` baseline evaluation contract
- Current analysis pipeline and metadata storage baseline

**In scope**

- Additive schema evolution for richer search-oriented metadata, for example:
  - composition/layout summary
  - subject regions or coarse spatial descriptors
  - subject attribute descriptors
  - subject relationship descriptors
  - per-subject emotion/expression summary where reliable
  - image tonality / lighting / contrast / warmth descriptors
- Update analysis result schema and prompt contract so these fields are explicitly requested and validated
- Keep the new schema additive rather than destructive
- Define field normalization rules so stored values are consistent enough for later retrieval logic

**Out of scope**

- Retrieval/ranking changes beyond storing/indexing the new fields
- Final UX refinement
- Multimodal embeddings
- Fine-grained detection boxes or segmentation systems

**Validation**

- New fields validate cleanly in the analysis schema
- Focused tests cover parsing, normalization, and persistence
- Sample analysis outputs show the new fields are materially more specific than the current broad summary
- Existing search behavior does not regress before retrieval changes land

**Auditor focus**

- Are the new fields additive and bounded rather than an uncontrolled ontology explosion?
- Are subject/composition/emotion/tone fields explicit enough to support later retrieval work?
- Does the schema remain implementation-realistic for the current AI provider rather than pretending to be a full vision graph?

**Expected user impact**

- Limited immediate impact by itself
- Enables later workstreams to retrieve remembered-photo details much more accurately

### P12-004: Composition-Aware Index Text and Structured Search Signals

**Objective**

Upgrade embedding/index text construction so richer metadata is preserved in a more search-effective structure rather than flattened into an undifferentiated text block.

**Why now**

Once richer metadata exists, the next low-risk improvement is to make the current text-embedding retrieval layer use it better before adding reranking complexity.

**Dependencies**

- `P12-003` richer metadata contract
- Existing indexing and vector-store architecture

**In scope**

- Rework embedding text construction to emphasize:
  - global scene/context
  - composition/layout
  - subject-specific attributes
  - subject relationships
  - emotion/expression
  - tonality / lighting / mood
- Define a structured text template rather than a simple stitched list
- Add selective weighting/repetition strategy only if justified and documented
- Add targeted metadata fields to the vector-store metadata payload when useful for later filtering or reranking
- Define a reindex/backfill strategy for existing items

**Out of scope**

- Full reranking layer
- UI changes
- Multimodal embeddings
- Destructive index replacement without backfill plan

**Validation**

- Reindex/backfill path is documented and testable
- Offline benchmark from `P12-002` shows measurable gains in top-1 and/or top-5 on remembered-photo queries
- No regression on broad semantic retrieval classes beyond agreed tolerance

**Auditor focus**

- Does the new embedding text preserve structural distinctions instead of just adding more verbosity?
- Is the reindex plan safe, additive, and operationally clear?
- Are retrieval gains measured rather than inferred?

**Expected user impact**

- More specific queries start surfacing better candidates without any visible product-flow change

### P12-005: Hybrid Recall and Lightweight Reranking for Remembered Queries

**Objective**

Introduce a bounded second-stage retrieval improvement so top candidates better match detailed remembered-photo descriptions.

**Why now**

After representation and index text improve, the next likely bottleneck is ranking precision. Single-stage vector retrieval is still too weak for queries that require matching several specific clues simultaneously.

**Dependencies**

- `P12-002` benchmark set
- `P12-003` richer metadata
- `P12-004` improved index text/backfill

**In scope**

- Evaluate and implement a bounded hybrid recall strategy such as:
  - vector recall plus structured metadata constraints
  - vector recall plus lexical/field-aware scoring contribution
- Add a lightweight reranking stage over a small candidate set using the richer metadata fields
- Query decomposition only if needed to support ranking logic, not as a full query-understanding rewrite
- Keep the reranking boundary explicit and auditable

**Out of scope**

- Full search engine replacement
- Dense multimodal retrieval
- Arbitrary learned ranking pipelines that are hard to audit
- Broad faceted search UX redesign

**Validation**

- Demonstrable improvement in top-1 and top-5 benchmark metrics for remembered-photo queries
- Candidate set size and latency remain within acceptable product limits
- Focused tests cover reranking contract and fallback behavior

**Auditor focus**

- Is reranking bounded, explainable, and operationally safe?
- Does the workstream avoid becoming an oversized search-system rewrite?
- Are latency and quality trade-offs explicitly measured?

**Expected user impact**

- Specific remembered-photo queries return better first-page ordering and fewer semantically related but compositionally wrong results

### P12-006: Search Narrowing and Disambiguation UX

**Objective**

Add user-facing narrowing and refinement tools that help people express remembered-photo intent and disambiguate near misses.

**Why now**

Backend retrieval improvements alone will not fully solve remembered-photo retrieval. Users also need better refinement tools than the current broad filters.

**Dependencies**

- `P12-002` benchmark language about remembered-photo tasks
- Preferably `P12-004` and `P12-005` so the new UI can expose real backend distinctions

**In scope**

- Add search refinement UX around concepts such as:
  - subject count / group vs solo
  - foreground/background emphasis
  - left/center/right placement where supported by metadata
  - visual tone / brightness / warmth / mood
  - expression / emotion where supported
  - relationship or interaction cues when available
- Add guided narrowing or suggested refinements based on returned result diversity
- Improve result presentation so users can see why an item matched

**Out of scope**

- Full natural-language conversational search assistant
- Large frontend IA rewrite
- New analysis schema expansion unrelated to remembered-photo refinement

**Validation**

- UX flows show users can narrow from a broad remembered query to a more specific result set
- User testing or structured internal evaluation confirms refinement usefulness
- Existing simple search flow remains intact and understandable

**Auditor focus**

- Does the UX expose real retrieval capabilities rather than fake controls?
- Is the refinement model additive and comprehensible?
- Does the workstream preserve the simple “just search” baseline for casual users?

**Expected user impact**

- Users can recover from imperfect first results and steer the search toward the remembered photo more effectively

### P12-007: Search Metadata Backfill and Reindex Operations

**Objective**

Operationalize backfill and reindex so existing libraries benefit from the new search-quality architecture without requiring destructive resets.

**Why now**

Search improvements are only product-real if historical content can be upgraded safely and predictably.

**Dependencies**

- `P12-003` richer schema
- `P12-004` new index text
- Any retrieval changes that require reindexing or recomputed search text

**In scope**

- Define backfill jobs/scripts for new metadata fields
- Define index rebuild/reindex strategy for existing items
- Define idempotent operational controls, batching, dry-run mode, and progress visibility
- Define how incomplete or failed backfill items are surfaced and retried

**Out of scope**

- New retrieval architecture changes
- Frontend search UX redesign
- New provider support

**Validation**

- Backfill/reindex path is rerunnable and idempotent
- Operational validation covers partial failure recovery
- Benchmark sample after backfill confirms old items benefit from the new signals

**Auditor focus**

- Is backfill safe, observable, and reversible enough for real datasets?
- Are batch controls, dry-run, and failure handling explicit?
- Does the operational plan avoid requiring destructive reprocessing?

**Expected user impact**

- Existing libraries gain the same search-quality improvements as newly analyzed content

### P12-008: Multimodal Retrieval Evaluation Gate

**Objective**

Decide whether multimodal image-text embeddings should be added after earlier waves, based on measured remaining gaps rather than enthusiasm.

**Why now**

Multimodal retrieval may eventually help, but it should be justified only after the lower-risk metadata and ranking improvements are measured.

**Dependencies**

- `P12-002` evaluation set
- Evidence from `P12-003` through `P12-007`

**In scope**

- Evaluate whether earlier waves materially improved remembered-photo retrieval enough
- Identify residual failure categories that text/metadata/reranking still miss
- Run a bounded proof-of-value assessment for multimodal retrieval only if those residual gaps justify it
- Define clear go/no-go criteria before any production adoption plan

**Out of scope**

- Immediate production rollout of multimodal retrieval as a default first-wave solution
- Search-stack rewrite around multimodal-first assumptions

**Validation**

- Comparison between metadata-first improved stack and candidate multimodal approach on the same evaluation set
- Explicit cost, latency, operational complexity, and quality trade-off analysis

**Auditor focus**

- Is multimodal retrieval being introduced because the evidence justifies it, or just because it is fashionable?
- Are the residual failure categories real and documented?

**Expected user impact**

- None in the decision gate itself
- Potential later benefit only if prior stages plateau and the evidence supports expansion

---

## Recommended Sequence

The recommended order is:

1. **P12-002 — Remembered-Photo Evaluation Baseline and Query Set**
   This must come first so later improvements can be measured credibly.

2. **P12-003 — Richer Search Metadata Schema and Extraction Contract**
   This is the highest-leverage improvement because retrieval cannot use information the system never extracts.

3. **P12-004 — Composition-Aware Index Text and Structured Search Signals**
   This is the lowest-risk way to improve retrieval quality after richer metadata exists.

4. **P12-005 — Hybrid Recall and Lightweight Reranking for Remembered Queries**
   This should happen only after the metadata and index-text upgrades are measured, so the reranker is not compensating for a weak representation layer.

5. **P12-006 — Search Narrowing and Disambiguation UX**
   This is most effective once the backend can expose richer distinctions and refinement paths.

6. **P12-007 — Search Metadata Backfill and Reindex Operations**
   This can begin as soon as the earlier schema/index changes stabilize, but it should be treated as its own operational workstream so rollout risk is explicit.

7. **P12-008 — Multimodal Retrieval Evaluation Gate**
   This is intentionally late. It should be a measured decision gate, not the first move.

The sequencing principle is simple: **measure first, enrich representation second, improve retrieval third, improve refinement UX fourth, and consider multimodal only after earlier gains are proven or exhausted.**

---

## What To Defer

These items should not be attempted in the first wave:

1. Full multimodal image-text embedding rollout as the primary retrieval system.
2. Search-engine replacement or big-bang rewrite of the existing vector-search architecture.
3. Fine-grained detection/segmentation pipelines or box-level scene graphs.
4. Unbounded ontology expansion for every conceivable visual concept.
5. Mixing schema redesign, reranking, UX overhaul, and multimodal retrieval into one oversized workstream.
6. Claiming quality improvement without a frozen remembered-photo benchmark set.

Multimodal/image-text embeddings belong **in a later wave**, specifically only after the metadata-first and retrieval/reranking improvements have been evaluated on the remembered-photo benchmark. They do not belong in step one under current risk constraints.

---

## Success Criteria

The roadmap should be considered successful only if the product shows measurable gains on remembered-photo retrieval rather than just broader semantic search.

At minimum, success should be measured by:

1. **Top-1 retrieval quality**
   - improved proportion of remembered-photo queries where the intended image is the first result

2. **Top-5 retrieval quality**
   - improved proportion of remembered-photo queries where the intended image appears in the top five results

3. **Category-level gains**
   - measurable improvement for:
     - composition/spatial queries
     - subject attribute/detail queries
     - relationship queries
     - emotion/expression queries
     - tonality/lighting/mood queries

4. **User refinement effectiveness**
   - users can narrow an initially broad or imperfect remembered query into the desired photo more reliably

5. **Operational safety**
   - schema changes are additive
   - reindex/backfill paths are auditable and rerunnable
   - no destructive rewrite is required to realize first-wave gains

6. **Auditability**
   - every workstream has an explicit validation package and closeout checkpoint before the next one unlocks

---

## Recommended Next Architect Step

If this roadmap direction is accepted, the next concrete Architect action should be:

- lock `P12-002 — Remembered-Photo Evaluation Baseline and Query Set` as the first implementation-ready workstream

That creates the benchmark contract needed to evaluate every subsequent search-quality improvement objectively.