# Agent Context

This repository is a Push API test harness. Treat the Coveo Push API as the source of truth.

## Start Here

Use these steps to get oriented before changing code:

1. Read this file, then skim `README.md` for user-facing behavior.
2. Inspect the current worktree with `git status --short`.
3. Use the local virtualenv. The `./pushlab` wrapper executes `./.venv/bin/python`, so setup is:

   ```bash
   python3 -m venv .venv
   .venv/bin/pip install -r requirements.txt
   ```

4. Prefer tracked examples for dry runs and tests:

   ```bash
   ./pushlab --scenario-file scenarios.example.json list
   ./pushlab --dry-run --scenario-file scenarios.example.json rebuild
   .venv/bin/python -m unittest discover -s tests
   ```

Local runtime files are intentionally untracked: `.env`, `pushlab.yaml`, `scenarios.json`, `test-files/`, and `logs/`.

## Repo Map

- `pushlab.py`: CLI parsing and command orchestration.
- `coveo_push_client.py`: Push API request construction, validation, retries, dry-run logging, and client operations.
- `runtime_config.py`: local YAML/env/default configuration loading.
- `scenarios.example.json`: tracked scenario examples for safe local commands.
- `pushlab.config.example.yaml`: tracked config template.
- `docs/coveo-push-api-notes.md`: repo-specific notes from Coveo Push API references.
- `tests/`: unit tests. Use `unittest`, not pytest unless the repo adds it.

## Design Rules

Rules:
- Prefer API fidelity over convenience. If the API allows something, the tool should not reject it unless the tool literally cannot construct the request.
- Do not reject unknown scenario keys solely because this tool does not model them explicitly. Unknown-key rejection is not an improvement by default; the Push API is the source of truth and may support fields this harness has not named yet.
- Keep requests WYSIWYG from the scenario file. Do not infer missing fields such as `title`, `file_extension`, or `content_type`.
- Use `document_id` as the primary scenario identifier in CLI commands and internal lookups.
- Catch invalid or unsupported tool states with clean user-facing errors, but do not add stricter semantic rules than the API itself.
- When a constraint comes from this tool rather than the API, make that explicit in the error message.

Examples of tool-specific constraints:
- This tool currently expects each scenario to provide one of `file_path` or `data`.
- File-based pushes in this tool require `file_extension` because the file-container upload flow needs it.

## Implementation Notes

- CLI commands should select scenarios by `payload_body.document_id`.
- `payload_body` maps to the outgoing Push API document body; `scenario_configuration` is harness-only.
- Unknown `payload_body` keys should pass through to the API payload unless there is a concrete request-construction reason not to.
- Keep dry-run output useful. It should show the request shape without requiring credentials or network access.
- Use clean `ValueError` messages for invalid local harness state. Prefix tool-only limitations with `Tool constraint:` so users can distinguish them from API rules.
- Avoid broad rewrites. This is a small harness; keep changes close to the command/client/config/test area being touched.

## Validation

Run the focused command for the change, then the unit tests:

```bash
.venv/bin/python -m unittest discover -s tests
```

Useful smoke checks:

```bash
./pushlab --scenario-file scenarios.example.json list
./pushlab --dry-run --scenario-file scenarios.example.json push "file://examples/welcome.html"
./pushlab --dry-run --scenario-file scenarios.example.json rebuild
```
