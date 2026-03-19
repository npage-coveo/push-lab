# Push API Playground

This repository is set up as a small Coveo Push API test harness.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
cp scenarios.example.json scenarios.json
```

Update `.env` with your values:

```env
COVEO_ORG=your-org-id
COVEO_SOURCE=your-source-id
COVEO_API_KEY=your-api-key
# Optional for non-US regions, for example:
# COVEO_PUSH_API_ROOT=https://api-ca.cloud.coveo.com/push/v1
```

## Commands

List scenarios:

```bash
./pushlab list
```

Push a scenario:

```bash
./pushlab push "file://test-files/ocr-pdf-in-iframe-test.html"
```

Preview a push without sending it:

```bash
./pushlab --dry-run push "file://test-files/ocr-pdf-in-iframe-test.html"
```

Push an inline HTML scenario:

```bash
./pushlab push "file://inline/hello-world.html"
```

Push with a temporary document ID override:

```bash
./pushlab push "file://test-files/ocr-pdf-in-iframe-test.html" --document-id "file://tmp/iframe-test.html"
```

Push with an explicit ordering ID:

```bash
./pushlab push "file://test-files/ocr-pdf-in-iframe-test.html" --ordering-id 1737058123456
```

Push multiple scenarios:

```bash
./pushlab push "file://test-files/ocr-pdf-in-iframe-test.html" "file://test-files/HarryPotter.pdf"
```

Delete a pushed scenario:

```bash
./pushlab delete "file://test-files/ocr-pdf-in-iframe-test.html"
```

Rebuild the source from `scenarios.json` and then delete stale items:

```bash
./pushlab rebuild
```

Rebuild selected scenarios with a shorter delete grace period:

```bash
./pushlab rebuild "file://test-files/ocr-pdf-in-iframe-test.html" "file://inline/hello-world.html" --queue-delay 1
```

Preview a rebuild and inspect the generated payload log:

```bash
./pushlab --dry-run rebuild
cat logs/payloads/*.jsonl
```

Use a different JSON file:

```bash
./pushlab --scenario-file custom-scenarios.json list
```

Use the tracked example fixtures without copying them:

```bash
./pushlab --scenario-file scenarios.example.json list
```

## Add a new test

1. Put the file in `test-files/` if needed.
2. Add a new entry to `scenarios.json`. Use `file_path` for file-based pushes, `data` for inline text, or omit both for metadata-only pushes. This repo does not support embedding compressed binary blobs directly in `scenarios.json`.
3. Run it by document ID with `./pushlab push "<document_id>"`.

The live `scenarios.json` and `test-files/` directories are intentionally local-only and ignored by git. Start from [scenarios.example.json](/home/npage/projects/push-api/scenarios.example.json) and [test-files.example](/home/npage/projects/push-api/test-files.example/README.md). You can run the tracked examples as-is with `--scenario-file scenarios.example.json`, or copy them into your own local `scenarios.json` and `test-files/` workspace.

Scenario selection uses `document_id`, since it is required by the API and unique by design. This tool avoids inferring fields so request bodies stay WYSIWYG from the scenario file. You can also pass a different file with `--scenario-file`.

`./pushlab list` now labels each scenario as valid or invalid so malformed entries are easy to spot before a push or rebuild.

Each run writes a JSONL payload log under `logs/payloads/` by default. You can change that with `--log-dir`.

See [`docs/coveo-push-api-notes.md`](/home/npage/projects/push-api/docs/coveo-push-api-notes.md) for repo-specific notes from the official Add or update an item reference.
