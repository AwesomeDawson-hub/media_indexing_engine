# P7-001 — Collections

**Phase:** 7 (Post-Phase 6 user-value features)
**Status:** In Progress
**Created:** 2026-04-05

## Objective

Allow users to organise media items into named collections (albums). A collection is a user-owned, named group of media items with an optional description. Items can belong to multiple collections.

## Scope

### In scope
- Create, list, rename, delete collections
- Add / remove items from a collection
- Collections page listing all user collections (name, cover image, item count)
- Collection detail page showing items in grid (same card as gallery)
- "Add to Collection" button on gallery grid (via selection bar) and on MediaDetailPage
- Nav link to Collections

### Out of scope (deferred)
- Shared / public collections
- Collection ordering / drag-and-drop sort
- Collection cover image override (auto-uses first item)

## Data Model

```
collections
  id            UUID PK
  user_id       UUID FK → users.id (cascade delete)
  name          VARCHAR(200) NOT NULL
  description   VARCHAR(1000) NULL
  created_at    TIMESTAMP DEFAULT now()
  UNIQUE (user_id, name)

collection_items
  id              UUID PK
  collection_id   UUID FK → collections.id (cascade delete)
  media_item_id   UUID FK → media_items.id (cascade delete)
  added_at        TIMESTAMP DEFAULT now()
  UNIQUE (collection_id, media_item_id)
```

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | /api/v1/collections | Create collection |
| GET | /api/v1/collections | List user collections |
| GET | /api/v1/collections/{id} | Get collection + items |
| PATCH | /api/v1/collections/{id} | Rename / update description |
| DELETE | /api/v1/collections/{id} | Delete collection |
| POST | /api/v1/collections/{id}/items | Add items (batch) |
| DELETE | /api/v1/collections/{id}/items | Remove items (batch) |

## Frontend Pages

- `/collections` — CollectionsPage: grid of collection cards (cover thumbnail, name, count)
- `/collections/:id` — CollectionDetailPage: same gallery grid as GalleryPage, back button, collection name heading, edit/delete controls

## Key Decisions

- Collections are purely organisational — no re-analysis or re-index on add/remove
- Cover image = first added item's thumbnail (no override in this phase)
- Max 100 collections per user (enforced at create time)
- Max 500 items per collection (enforced at add time)
- Deleting a collection does NOT delete the media items
- Removing an item from a collection does NOT delete the media item

## Alembic Migration

Single migration: `c0d1e2f3a4b5` — creates `collections` and `collection_items` tables.
