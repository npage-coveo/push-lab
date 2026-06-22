# Coveo Push API Notes

Reference:

- Add or update an item:
  https://docs.coveo.com/en/12/api-reference/push-api#tag/Item/paths/~1organizations~1%7BorganizationId%7D~1sources~1%7BsourceId%7D~1documents/put
- Push API reference overview:
  https://docs.coveo.com/en/78/index-content/push-api-reference
- `compressedBinaryDataFileId` flow:
  https://docs.coveo.com/en/69/
- Delete old items:
  https://docs.coveo.com/en/12/api-reference/push-api#tag/Item/paths/~1organizations~1%7BorganizationId%7D~1sources~1%7BsourceId%7D~1documents~1olderthan/delete

## What matters for this repo

- The `documentId` is required and should be the item URI.
- In this harness, `payload_body.document_id` is the item URI sent to Coveo and the CLI lookup key. Local file resolution is separate: when `scenario_configuration.push_a_file` is true, the harness reads the local file from `scenario_configuration.file_path`.
- The Push API is the source of truth. Do not propose rejecting unknown scenario keys just because this harness does not model them explicitly; if we need a new API field, we should prefer adding support over adding stricter validation.
- When using `compressedBinaryDataFileId`, the request should include the `compressionType` query parameter.
- The official API reference shows region-specific roots:
  - US East: `https://api.cloud.coveo.com/push/v1`
  - Canada: `https://api-ca.cloud.coveo.com/push/v1`
  - Ireland: `https://api-eu.cloud.coveo.com/push/v1`
- For a single item body, Coveo expects one content input when content is present. This repo currently uses:
  - `data`
  - `compressedBinaryDataFileId`
  - no content field at all for metadata-only pushes
- Useful optional fields include:
  - `fileExtension`
  - `parentId`
  - arbitrary metadata key/value pairs
  - `permissions`
- `orderingId` is available as a query parameter, but Coveo warns that setting it manually is usually not recommended.
- For a true rebuild pattern, the items you push must receive `orderingId` values at or above the `olderthan` threshold you plan to use, otherwise the cleanup step can delete the items you just pushed.
- `queueDelay` defaults to 15 minutes and exists to give previously enqueued operations time to complete before the delete-older-than request is processed.
- For local testing, this harness lets you lower that default through `pushlab.yaml` with `default_queue_delay`. Setting it to `0` is useful when you want the `delete older than` request to appear in the Admin Console log browser without waiting 15 minutes.

## What this repo supports now

- Inline `data` pushes for HTML/text items
- File-container upload flow with `compressedBinaryDataFileId`
- `compressionType` query parameter for single-document file-container pushes, plus batch-item `compressionType` during rebuilds
- Metadata-only pushes with no `data` or `compressedBinaryDataFileId`
- Region override through `COVEO_PUSH_API_ROOT`
- Scenario metadata via `metadata`
- `parentId`
- `permissions`
- `orderingId`
- `clickableUri` and `printableUri`
- Source status updates (`POST /sources/{sourceId}/status?statusType=...`) during rebuild flows
- `delete older than` cleanup for rebuild flows
- Batch rebuild pushes through `PUT /documents/batch`
- Exponential backoff with jitter for transient HTTP/network failures
- JSONL payload logs for pushes, deletes, and source status changes
- Dry-run previews for push, delete, and rebuild flows

### Source status

The rebuild command brackets its API work with source status updates:

1. `POST .../sources/{sourceId}/status?statusType=REBUILD` — creates a rebuild activity
2. Batch push + delete older than
3. `POST .../sources/{sourceId}/status?statusType=IDLE` — marks the activity completed

Setting `IDLE` tells Coveo the harness has finished queuing its operations. It does not prove every item has completed all downstream indexing stages; Coveo processes the queued operations asynchronously after the status is set.

The `set_source_status` client method accepts `IDLE`, `INCREMENTAL`, `REBUILD`, and `REFRESH`.

## Still not modeled explicitly

- Inline `compressedBinaryData` in `scenarios.json`
- General-purpose batch add/update/delete bodies outside the rebuild flow

Those can be added later if we want to test those paths too.
