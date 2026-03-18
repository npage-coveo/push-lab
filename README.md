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
./pushlab push "A guide to self-testing for COVID-19: Information for patients"
```

Preview a push without sending it:

```bash
./pushlab --dry-run push "A guide to self-testing for COVID-19: Information for patients"
```

Push an inline HTML scenario:

```bash
./pushlab push "Inline HTML Test"
```

Push with a temporary document ID override:

```bash
./pushlab push "A guide to self-testing for COVID-19: Information for patients" --document-id "file://tmp/iframe-test.html"
```

Push with an explicit ordering ID:

```bash
./pushlab push "A guide to self-testing for COVID-19: Information for patients" --ordering-id 1737058123456
```

Push multiple scenarios:

```bash
./pushlab push "A guide to self-testing for COVID-19: Information for patients" "Quotes from Harry Potter"
```

Delete a pushed scenario:

```bash
./pushlab delete "A guide to self-testing for COVID-19: Information for patients"
```

Rebuild the source from `scenarios.json` and then delete stale items:

```bash
./pushlab rebuild
```

Rebuild selected scenarios with a shorter delete grace period:

```bash
./pushlab rebuild "A guide to self-testing for COVID-19: Information for patients" "Inline HTML Test" --queue-delay 1
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
2. Add a new entry to `scenarios.json`. Use `file_path` for file-based pushes or `data` for inline text. This repo does not support embedding compressed binary blobs directly in `scenarios.json`.
3. Run it by title with `./pushlab push "<title>"`.

The live `scenarios.json` and `test-files/` directories are intentionally local-only and ignored by git. Start from [scenarios.example.json](/home/npage/projects/push-api/scenarios.example.json) and [test-files.example](/home/npage/projects/push-api/test-files.example/README.md). You can run the tracked examples as-is with `--scenario-file scenarios.example.json`, or copy them into your own local `scenarios.json` and `test-files/` workspace.

Titles are the scenario identifiers, so they must stay unique. You can also pass a different file with `--scenario-file`.

`./pushlab list` now labels each scenario as valid or invalid so malformed entries are easy to spot before a push or rebuild.

Each run writes a JSONL payload log under `logs/payloads/` by default. You can change that with `--log-dir`.

See [`docs/coveo-push-api-notes.md`](/home/npage/projects/push-api/docs/coveo-push-api-notes.md) for repo-specific notes from the official Add or update an item reference.
