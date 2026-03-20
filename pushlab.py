import argparse
import json
from dataclasses import replace
from pathlib import Path
import time

import requests

from coveo_push_client import CoveoPushClient, PushScenario, validate_push_scenario
from runtime_config import DEFAULT_CONFIG_PATH, RuntimeConfig, load_runtime_config


def build_parser(defaults: RuntimeConfig) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run Coveo Push API test scenarios.")
    parser.add_argument(
        "--config",
        default=DEFAULT_CONFIG_PATH,
        help="YAML file containing runtime defaults",
    )
    parser.add_argument(
        "--scenario-file",
        default=defaults.scenario_file,
        help="JSON file containing scenario definitions",
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=defaults.max_retries,
        help="Maximum retries for transient Push API failures",
    )
    parser.add_argument(
        "--backoff-base-seconds",
        type=float,
        default=defaults.backoff_base_seconds,
        help="Base delay in seconds for exponential backoff",
    )
    parser.add_argument(
        "--log-dir",
        default=defaults.log_dir,
        help="Directory where JSONL payload logs are written",
    )
    parser.add_argument(
        "--request-timeout-seconds",
        type=int,
        default=defaults.request_timeout_seconds,
        help="Timeout in seconds for standard Push API requests",
    )
    parser.add_argument(
        "--upload-timeout-seconds",
        type=int,
        default=defaults.upload_timeout_seconds,
        help="Timeout in seconds for file-container uploads",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview actions and write payload logs without making live API calls",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("list", help="List available scenarios")

    push_parser = subparsers.add_parser("push", help="Push one or more scenarios")
    push_parser.add_argument("scenarios", nargs="+", help="Scenario document_id value(s) to push")
    add_push_overrides(push_parser)

    delete_parser = subparsers.add_parser("delete", help="Delete one pushed document")
    delete_parser.add_argument("scenario", help="Scenario document_id value to delete")
    delete_parser.add_argument("--document-id", help="Override the document ID for deletion")

    rebuild_parser = subparsers.add_parser(
        "rebuild",
        help="Push the current scenarios and then delete items older than the rebuild baseline",
    )
    rebuild_parser.add_argument(
        "scenarios",
        nargs="*",
        help="Scenario document_id value(s) to rebuild. If omitted, all scenarios from the JSON file are used.",
    )
    rebuild_parser.add_argument(
        "--queue-delay",
        type=int,
        default=defaults.default_queue_delay,
        help="Grace period in minutes for the delete older-than request",
    )
    rebuild_parser.add_argument(
        "--start-ordering-id",
        type=int,
        help="Optional starting orderingId. Defaults to the current Unix time in milliseconds.",
    )
    return parser


def add_push_overrides(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--document-id", help="Override the document ID for this run")
    parser.add_argument("--title", help="Override the document title for this run")
    parser.add_argument("--clickable-uri", help="Override the clickable URI for this run")
    parser.add_argument("--printable-uri", help="Override the printable URI for this run")
    parser.add_argument("--ordering-id", type=int, help="Override the orderingId query parameter")


def load_scenarios(
    json_path: str | None = None,
) -> dict[str, PushScenario]:
    scenario_file = Path(json_path) if json_path else Path("scenarios.json")
    if not scenario_file.exists():
        example_hint = ""
        if not json_path and Path("scenarios.example.json").exists():
            example_hint = (
                " Copy scenarios.example.json to scenarios.json, or pass "
                "--scenario-file scenarios.example.json."
            )
        raise FileNotFoundError(f"Scenario file not found: {scenario_file}.{example_hint}")

    with scenario_file.open("r", encoding="utf-8") as input_file:
        raw_scenarios = json.load(input_file)

    if not isinstance(raw_scenarios, list):
        raise ValueError(f"Scenario file must contain a JSON array: {scenario_file}")

    scenarios: dict[str, PushScenario] = {}
    for index, item in enumerate(raw_scenarios, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"Scenario #{index} must be a JSON object")

        scenario_configuration = item.get("scenario_configuration")
        payload_body = item.get("payload_body")
        if not isinstance(scenario_configuration, dict):
            raise ValueError(
                f"Scenario #{index} must contain a scenario_configuration object"
            )
        if not isinstance(payload_body, dict):
            raise ValueError(f"Scenario #{index} must contain a payload_body object")

        if "push_a_file" not in scenario_configuration:
            raise ValueError(
                f"Scenario #{index} is missing required field(s): scenario_configuration.push_a_file"
            )
        push_a_file = scenario_configuration["push_a_file"]
        if not isinstance(push_a_file, bool):
            raise ValueError(
                f"Scenario #{index} has invalid scenario_configuration.push_a_file: expected bool"
            )

        document_id = payload_body.get("document_id")
        if document_id is None:
            scenario_label = payload_body.get("title") or payload_body.get("name") or f"#{index}"
            raise ValueError(
                f"Scenario {scenario_label!r} is missing required field(s): payload_body.document_id"
            )

        scenario = PushScenario(
            document_id=document_id,
            payload_body=dict(payload_body),
            push_a_file=push_a_file,
            file_path=scenario_configuration.get("file_path"),
            compression_type=scenario_configuration.get("compression_type"),
            ordering_id=scenario_configuration.get("ordering_id"),
        )
        if scenario.document_id in scenarios:
            raise ValueError(f"Duplicate scenario document_id '{scenario.document_id}' in {scenario_file}")
        scenarios[scenario.document_id] = scenario

    return scenarios


def main() -> None:
    config_path = parse_config_path()
    try:
        defaults = load_runtime_config(config_path)
    except (FileNotFoundError, ValueError) as error:
        raise SystemExit(str(error)) from error

    parser = build_parser(defaults)
    args = parser.parse_args()
    try:
        scenarios = load_scenarios(args.scenario_file)
    except (FileNotFoundError, ValueError, json.JSONDecodeError) as error:
        raise SystemExit(str(error)) from error
    client = CoveoPushClient.from_env(
        max_retries=args.max_retries,
        backoff_base_seconds=args.backoff_base_seconds,
        log_dir=args.log_dir,
        request_timeout_seconds=args.request_timeout_seconds,
        upload_timeout_seconds=args.upload_timeout_seconds,
        dry_run=args.dry_run,
    )

    if args.command == "list":
        for document_id, scenario in sorted(scenarios.items()):
            location = describe_scenario_location(scenario)
            try:
                validate_push_scenario(scenario)
                status = "valid"
            except ValueError as error:
                status = f"invalid: {error}"
            title = scenario.title or "<no title>"
            print(f"{document_id}: {title} [{location}] ({status})")
        print(f"Payload log: {client.log_path}")
        return

    if args.command == "push":
        try:
            push_scenarios(client, scenarios, args.scenarios, args)
        except requests.HTTPError as error:
            raise SystemExit(format_http_error(error, client.log_path)) from error
        return

    if args.command == "delete":
        scenario = resolve_scenario(scenarios, args.scenario)
        document_id = args.document_id or scenario.document_id
        try:
            response = client.delete_document(document_id)
        except requests.HTTPError as error:
            raise SystemExit(format_http_error(error, client.log_path)) from error
        except ValueError as error:
            raise SystemExit(str(error)) from error
        print(f"Deleted {document_id}: {response.status_code} {response.text}")
        print(f"Payload log: {client.log_path}")
        return

    if args.command == "rebuild":
        try:
            rebuild_scenarios(client, scenarios, args.scenarios, args.queue_delay, args.start_ordering_id)
        except requests.HTTPError as error:
            raise SystemExit(format_http_error(error, client.log_path)) from error
        print(f"Payload log: {client.log_path}")
        return

    parser.error(f"unknown command: {args.command}")


def resolve_scenario(scenarios: dict[str, PushScenario], document_id: str) -> PushScenario:
    scenario = scenarios.get(document_id)
    if not scenario:
        available = ", ".join(sorted(scenarios))
        raise SystemExit(f"unknown scenario document_id '{document_id}'. Available: {available}")
    return scenario


def parse_config_path() -> str | None:
    bootstrap_parser = argparse.ArgumentParser(add_help=False)
    bootstrap_parser.add_argument("--config", default=None)
    bootstrap_args, _ = bootstrap_parser.parse_known_args()
    return bootstrap_args.config


def apply_push_overrides(scenario: PushScenario, args: argparse.Namespace) -> PushScenario:
    payload_body = dict(scenario.payload_body)
    if args.document_id:
        payload_body["document_id"] = args.document_id
    if args.title:
        payload_body["title"] = args.title
    if args.clickable_uri:
        payload_body["clickable_uri"] = args.clickable_uri
    if args.printable_uri:
        payload_body["printable_uri"] = args.printable_uri

    return replace(
        scenario,
        document_id=args.document_id or scenario.document_id,
        payload_body=payload_body,
        ordering_id=args.ordering_id if args.ordering_id is not None else scenario.ordering_id,
    )


def describe_scenario_location(scenario: PushScenario) -> str:
    if scenario.data is not None:
        return "inline data"
    if scenario.push_a_file:
        return f"local file via scenario_configuration.file_path: {scenario.file_path}"
    return "no payload source"


def validate_scenarios_or_exit(scenarios: list[PushScenario]) -> None:
    errors: list[str] = []
    for scenario in scenarios:
        try:
            validate_push_scenario(scenario)
        except ValueError as error:
            errors.append(str(error))

    if errors:
        raise SystemExit("\n".join(errors))


def format_http_error(error: requests.HTTPError, log_path: Path) -> str:
    response = error.response
    if response is None:
        return f"{error}\nCheck payload logs in {log_path.parent}"

    response_text = response.text.strip() or "<empty response body>"
    return (
        f"Push API request failed: {response.status_code} {response.reason}\n"
        f"Response: {response_text}\n"
        f"Check payload logs in {log_path.parent}"
    )


def push_scenarios(
    client: CoveoPushClient,
    scenarios: dict[str, PushScenario],
    scenario_document_ids: list[str],
    args: argparse.Namespace,
) -> None:
    selected_scenarios = [
        apply_push_overrides(resolve_scenario(scenarios, document_id), args)
        for document_id in scenario_document_ids
    ]
    validate_scenarios_or_exit(selected_scenarios)

    for scenario in selected_scenarios:
        response = client.push_scenario(scenario)
        print(f"Pushed {scenario.document_id}: {response.status_code} {response.text}")
    print(f"Payload log: {client.log_path}")


def rebuild_scenarios(
    client: CoveoPushClient,
    scenarios: dict[str, PushScenario],
    selected_document_ids: list[str],
    queue_delay: int,
    start_ordering_id: int | None,
) -> None:
    ordered_document_ids = selected_document_ids or list(scenarios.keys())
    base_ordering_id = start_ordering_id or int(time.time() * 1000)
    rebuild_floor = base_ordering_id + 1
    selected_scenarios = [
        replace(resolve_scenario(scenarios, document_id), ordering_id=base_ordering_id + index + 1)
        for index, document_id in enumerate(ordered_document_ids)
    ]
    validate_scenarios_or_exit(selected_scenarios)

    for scenario in selected_scenarios:
        response = client.push_scenario(scenario)
        print(
            f"Pushed {scenario.document_id} with orderingId {scenario.ordering_id}: "
            f"{response.status_code} {response.text}"
        )

    delete_response = client.delete_older_than(rebuild_floor, queue_delay=queue_delay)
    print(
        f"Queued delete older than {rebuild_floor} with queueDelay={queue_delay}: "
        f"{delete_response.status_code} {delete_response.text}"
    )


if __name__ == "__main__":
    main()
