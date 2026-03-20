# Push API Playground

This repository is a small Coveo Push API test harness.

Basic commands:

```bash
./pushlab push "<document_id>"
./pushlab rebuild
```

## Setup

The `./pushlab` wrapper runs `./.venv/bin/python`, so create the virtualenv in `.venv`.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
cp scenarios.example.json scenarios.json
cp pushlab.config.example.yaml pushlab.yaml
```

Update `.env` with your values:

```env
COVEO_ORG=your-org-id
COVEO_SOURCE=your-source-id
COVEO_API_KEY=your-api-key
# Optional for non-US regions, for example:
# COVEO_PUSH_API_ROOT=https://api-ca.cloud.coveo.com/push/v1
```

Optional: update `pushlab.yaml` to change local runtime defaults such as retries, timeouts, queue delay, log path, and scenario file. `pushlab.config.example.yaml` is only a tracked template; the tool automatically reads `pushlab.yaml` when that file exists. CLI flags still override the YAML values for a single run.

## Commands

List scenarios:

```bash
./pushlab list
```

Use the tracked example fixtures without copying them:

```bash
./pushlab --scenario-file scenarios.example.json list
```

Push a file-backed scenario by `payload_body.document_id`:

```bash
./pushlab --scenario-file scenarios.example.json push "file://examples/welcome.html"
```

Preview a push without sending it:

```bash
./pushlab --dry-run --scenario-file scenarios.example.json push "file://examples/welcome.html"
```

Push the inline example scenario:

```bash
./pushlab --scenario-file scenarios.example.json push "file://examples/inline-example.html"
```

Push with a temporary document ID override:

```bash
./pushlab --scenario-file scenarios.example.json push "file://examples/inline-example.html" --document-id "file://tmp/inline-example.html"
```

Push with an explicit ordering ID:

```bash
./pushlab --scenario-file scenarios.example.json push "file://examples/welcome.html" --ordering-id 1737058123456
```

Push multiple scenarios:

```bash
./pushlab --scenario-file scenarios.example.json push "file://examples/welcome.html" "file://examples/inline-example.html"
```

Delete a pushed scenario:

```bash
./pushlab --scenario-file scenarios.example.json delete "file://examples/welcome.html"
```

Rebuild the source from the scenario file and then delete stale items:

```bash
./pushlab --scenario-file scenarios.example.json rebuild
```

Rebuild selected scenarios with a shorter delete grace period:

```bash
./pushlab --scenario-file scenarios.example.json rebuild "file://examples/welcome.html" "file://examples/inline-example.html" --queue-delay 1
```

Preview a rebuild and inspect the generated payload log:

```bash
./pushlab --dry-run --scenario-file scenarios.example.json rebuild
cat logs/payloads/*.jsonl
```

Use a different JSON file:

```bash
./pushlab --scenario-file custom-scenarios.json list
```

Use a different YAML config file:

```bash
./pushlab --config custom-pushlab.yaml list
```

## Scenario Format

Each scenario now has two sections:

```json
{
  "scenario_configuration": {
    "push_a_file": true,
    "file_path": "test-files/example.pdf",
    "compression_type": "ZLib"
  },
  "payload_body": {
    "document_id": "file://examples/example.pdf",
    "title": "Example PDF"
  }
}
```

What each section means:

- `scenario_configuration`: harness-only settings
- `payload_body`: the item body fields the harness turns into the Push API document payload

Required fields:

- `scenario_configuration.push_a_file`
- `payload_body.document_id`

Rules:

- the CLI uses `payload_body.document_id` to select scenarios
- if `push_a_file` is `true`, `scenario_configuration.file_path` is required
- if `push_a_file` is `true`, `scenario_configuration.compression_type` is required
- if `push_a_file` is `false`, `scenario_configuration.file_path` is ignored
- `scenario_configuration.file_path` is never sent to the Push API
- only `payload_body` fields are sent to the Push API body, plus generated fields such as `compressedBinaryDataFileId`
- this harness does not infer `document_id`, `title`, `content_type`, `file_extension`, or other payload fields

How content mode works:

- file push: `push_a_file: true`; the harness reads the local file from `scenario_configuration.file_path`
- inline push: `push_a_file: false` and `payload_body.data` is present
- metadata-only push: `push_a_file: false` and `payload_body.data` is omitted

Notes on payload fields:

- `payload_body.document_id` is mapped to Push API `documentId`
- `payload_body.file_extension` is mapped to `fileExtension` when provided
- `payload_body.content_type` is mapped to `contentType` when provided
- `payload_body.clickable_uri` is mapped to `clickableUri` when provided
- `payload_body.printable_uri` is mapped to `printableUri` when provided
- `payload_body.parent_id` is mapped to `parentId` when provided
- `payload_body.metadata`, when provided, is expanded into top-level fields in the outgoing payload
- unknown `payload_body` keys are passed through as-is

`./pushlab list` labels each scenario as valid or invalid so malformed entries are easy to spot before a push or rebuild.

Each run writes a JSONL payload log under `logs/payloads/` by default. You can change that with `--log-dir`.

## Add A New Test

1. Put the file in `test-files/` if needed.
2. Add a new entry to `scenarios.json`.
3. Put harness-only settings in `scenario_configuration`.
4. Put Push API body fields in `payload_body`.
5. Run it by document ID with `./pushlab push "<payload_body.document_id>"`.

The live `scenarios.json` and `test-files/` directories are intentionally local-only and ignored by git. Start from [scenarios.example.json](/home/npage/projects/tools/push-lab/scenarios.example.json) and [test-files.example/README.md](/home/npage/projects/tools/push-lab/test-files.example/README.md). You can run the tracked examples as-is with `--scenario-file scenarios.example.json`, or copy them into your own local `scenarios.json` and `test-files/` workspace.

## Runtime Defaults

Runtime defaults live in `pushlab.yaml` when that file exists. Start from [pushlab.config.example.yaml](/home/npage/projects/tools/push-lab/pushlab.config.example.yaml).

How config loading works:

- `pushlab.config.example.yaml` is a tracked example file and is not read automatically
- `pushlab.yaml` is the local file the tool reads by default when it exists
- if `pushlab.yaml` is missing, built-in defaults are used
- `--config custom-pushlab.yaml` overrides the default config file path for that run
- CLI flags override YAML values for the current command

Supported settings:

- `scenario_file`
- `max_retries`
- `backoff_base_seconds`
- `log_dir`
- `default_queue_delay`
- `request_timeout_seconds`
- `upload_timeout_seconds`

When testing `delete older than` flows, set `default_queue_delay: 0` in `pushlab.yaml` or pass `--queue-delay 0`. That avoids waiting 15 minutes to see the operation appear in the Admin Console log browser.

See [docs/coveo-push-api-notes.md](/home/npage/projects/tools/push-lab/docs/coveo-push-api-notes.md) for repo-specific notes from the official Add or update an item reference.
