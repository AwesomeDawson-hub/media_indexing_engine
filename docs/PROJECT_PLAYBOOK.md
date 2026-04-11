# Engineering Playbook — Media Indexing Engine

_This document explains how to safely develop, debug, and extend this project. It is written for both human engineers and AI assistants working on the codebase._

_Update this document as the project matures and new patterns, safety mechanisms, or common tasks emerge._

## Core Principle

_To be defined once implementation begins. This section should capture the overarching development philosophy as the project matures._

## High-Level Architecture

```
Upload / Import
      │
      ▼
Ingestion Pipeline
(validate, deduplicate, store)
      │
      ▼
AI Analysis Pipeline
(vision model → structured metadata)
      │
      ▼
Search Index
(vector embeddings + metadata)
      │
      ▼
REST API
      │
      ▼
Web UI
(upload, browse, search)
```

## Core Data Flow

_Detailed step-by-step flow will be documented as the pipeline is implemented._

1. User uploads files via web UI
2. Ingestion pipeline validates, deduplicates (hash-based), and stores files
3. AI analysis pipeline sends images to vision model and extracts structured metadata
4. Metadata and vector embeddings are indexed for search
5. User queries the search interface with natural language
6. API returns ranked results

## Safety Mechanisms

_Safety mechanisms will be documented here as they are implemented._

### Hash-Based Deduplication

**Purpose:** Prevent reprocessing identical files
**Implementation:** _TBD — WS-001_
**How it works:** SHA256 (or equivalent) hash of file content used as identity key

### Image Validation

**Purpose:** Prevent invalid or oversized files from reaching the AI API
**Implementation:** _TBD — WS-001 / WS-002_
**How it works:** _TBD_

### Same-Transaction Compatibility Mirrors

**Purpose:** Preserve stable API/frontend behavior while additive ARCH-002 tables become canonical.
**Implementation:** `src/analysis/writeback_operation_service.py`, `src/analysis/drive_mutation_service.py` — **P9-004**
**How it works:** Canonical write-back state is written to `WriteBackOperation` first, then mirrored onto `MediaItem.mutation_state`, error fields, attempt timestamps, and applied timestamps in the same transaction. This avoids trigger-based hidden logic and keeps legacy routes/tests stable while the backend state model becomes explicit.

## Safe Development Practices

### Do

- _To be populated as patterns emerge during implementation_
- Prefer additive bootstrap over hard failure when a new ARCH-002 model depends on legacy rows that may still exist. P9-004 uses this pattern to create missing `OriginAssetRef` rows for older item/test state before writing canonical `WriteBackOperation` records.

### Avoid

- _To be populated as anti-patterns are identified during implementation_

## Common Engineering Tasks

_Step-by-step guides will be added here as the codebase matures._

## Debugging Strategy

_Debugging procedures will be documented as the system is built._

## Performance Notes

_Performance characteristics and tuning guidance will be added as the system is tested._

## Instructions for AI Assistants

When helping with development:

1. Read `PROJECT_AI_CONTEXT.md` and this playbook before making changes
2. Follow the implementation order in the Phase 1 plan
3. Build each component to be independently testable
4. Document safety mechanisms in this file as they are implemented

## Document Ownership Note

This document owns **development practices, safety mechanisms, and operational guidance only**. It does not duplicate:
- Codebase structure → see `PROJECT_MAP.md`
- AI behavior rules → see `PROJECT_AI_CONTEXT.md`
- Current status or work tracking → see launcher `CURRENT_STATE.md` and `WORKSTREAMS.md`
