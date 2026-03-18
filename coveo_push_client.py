import mimetypes
import os
import random
import time
import zlib
from dataclasses import dataclass
from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any

import requests
from requests import Response
from dotenv import load_dotenv


DEFAULT_ROOT = "https://api.cloud.coveo.com/push/v1"
RESERVED_METADATA_FIELDS = frozenset(
    {
        "documentId",
        "title",
        "fileExtension",
        "contentType",
        "clickableUri",
        "printableUri",
        "parentId",
        "permissions",
        "data",
        "compressedBinaryDataFileId",
    }
)


@dataclass(frozen=True)
class PushScenario:
    document_id: str
    title: str
    file_extension: str
    file_path: str | None = None
    data: str | None = None
    compression_type: str = "ZLib"
    content_type: str | None = None
    clickable_uri: str | None = None
    printable_uri: str | None = None
    parent_id: str | None = None
    ordering_id: int | None = None
    permissions: list[dict[str, Any]] | None = None
    metadata: dict[str, Any] | None = None


class CoveoPushClient:
    def __init__(
        self,
        org: str,
        source: str,
        api_key: str,
        root: str = DEFAULT_ROOT,
        max_retries: int = 5,
        backoff_base_seconds: float = 1.0,
        log_dir: str = "logs/payloads",
        dry_run: bool = False,
    ) -> None:
        self.org = org
        self.source = source
        self.root = root.rstrip("/")
        self.headers = {"Authorization": f"Bearer {api_key}"}
        self.max_retries = max_retries
        self.backoff_base_seconds = backoff_base_seconds
        self.dry_run = dry_run
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.log_path = self.log_dir / f"{datetime.now(UTC).strftime('%Y-%m-%d')}.jsonl"

    @classmethod
    def from_env(
        cls,
        max_retries: int = 5,
        backoff_base_seconds: float = 1.0,
        log_dir: str = "logs/payloads",
        dry_run: bool = False,
    ) -> "CoveoPushClient":
        load_dotenv()

        org = os.getenv("COVEO_ORG")
        source = os.getenv("COVEO_SOURCE")
        api_key = os.getenv("COVEO_API_KEY")
        root = os.getenv("COVEO_PUSH_API_ROOT", DEFAULT_ROOT)

        if not org or not source or not api_key:
            raise RuntimeError("COVEO_ORG, COVEO_SOURCE, and COVEO_API_KEY must be set in .env")

        return cls(
            org=org,
            source=source,
            api_key=api_key,
            root=root,
            max_retries=max_retries,
            backoff_base_seconds=backoff_base_seconds,
            log_dir=log_dir,
            dry_run=dry_run,
        )

    def create_file_container(self, file_extension: str) -> dict:
        response = self.request_with_retry(
            "POST",
            f"{self.root}/organizations/{self.org}/files",
            headers={**self.headers, "Content-Type": "application/json"},
            params={"fileExtension": file_extension},
            json={},
            timeout=30,
        )
        response.raise_for_status()
        return response.json()

    def upload_compressed_file(
        self, upload_uri: str, required_headers: dict, compressed_bytes: bytes
    ) -> None:
        response = self.request_with_retry(
            "PUT",
            upload_uri,
            data=compressed_bytes,
            headers=required_headers,
            timeout=120,
        )
        response.raise_for_status()

    def push_scenario(self, scenario: PushScenario) -> requests.Response:
        validate_push_scenario(scenario)
        document, params, binary_info = self.build_push_request(scenario)
        self.log_event(
            "push",
            {
                "scenario": scenario.title,
                "url": f"{self.root}/organizations/{self.org}/sources/{self.source}/documents",
                "params": build_push_params(scenario, params),
                "json": document,
                "binary": binary_info,
                "dry_run": self.dry_run,
            },
        )

        if self.dry_run:
            return make_dry_run_response(202, "DRY RUN: push skipped")

        response = self.request_with_retry(
            "PUT",
            f"{self.root}/organizations/{self.org}/sources/{self.source}/documents",
            headers={**self.headers, "Content-Type": "application/json"},
            params=build_push_params(scenario, params),
            json=document,
            timeout=30,
        )
        response.raise_for_status()
        return response

    def delete_document(self, document_id: str) -> requests.Response:
        if not document_id or not document_id.strip():
            raise ValueError("document_id must be a non-empty string")
        self.log_event(
            "delete",
            {
                "documentId": document_id,
                "url": f"{self.root}/organizations/{self.org}/sources/{self.source}/documents",
                "params": {"documentId": document_id},
                "dry_run": self.dry_run,
            },
        )
        if self.dry_run:
            return make_dry_run_response(202, "DRY RUN: delete skipped")

        response = self.request_with_retry(
            "DELETE",
            f"{self.root}/organizations/{self.org}/sources/{self.source}/documents",
            headers=self.headers,
            params={"documentId": document_id},
            timeout=30,
        )
        response.raise_for_status()
        return response

    def delete_older_than(self, ordering_id: int, queue_delay: int = 15) -> requests.Response:
        self.log_event(
            "delete_older_than",
            {
                "orderingId": ordering_id,
                "queueDelay": queue_delay,
                "url": f"{self.root}/organizations/{self.org}/sources/{self.source}/documents/olderthan",
                "params": {"orderingId": ordering_id, "queueDelay": queue_delay},
                "dry_run": self.dry_run,
            },
        )
        if self.dry_run:
            return make_dry_run_response(202, "DRY RUN: delete older than skipped")

        response = self.request_with_retry(
            "DELETE",
            f"{self.root}/organizations/{self.org}/sources/{self.source}/documents/olderthan",
            headers={**self.headers, "Accept": "application/json"},
            params={"orderingId": ordering_id, "queueDelay": queue_delay},
            json={},
            timeout=30,
        )
        response.raise_for_status()
        return response

    def request_with_retry(self, method: str, url: str, **kwargs: Any) -> Response:
        retryable_statuses = {429, 500, 502, 503, 504}
        last_error: Exception | None = None

        for attempt in range(self.max_retries + 1):
            try:
                response = requests.request(method, url, **kwargs)
                if response.status_code not in retryable_statuses:
                    return response

                if attempt == self.max_retries:
                    return response

                delay_seconds = compute_retry_delay(
                    response.headers.get("Retry-After"),
                    attempt,
                    self.backoff_base_seconds,
                )
            except requests.RequestException as error:
                last_error = error
                if attempt == self.max_retries:
                    raise
                delay_seconds = compute_retry_delay(
                    None,
                    attempt,
                    self.backoff_base_seconds,
                )

            time.sleep(delay_seconds)

        if last_error:
            raise last_error

        raise RuntimeError("request_with_retry exhausted unexpectedly")

    def build_push_request(self, scenario: PushScenario) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        document = {
            "documentId": scenario.document_id,
            "title": scenario.title,
            "fileExtension": scenario.file_extension,
            "contentType": scenario.content_type or guess_content_type(scenario),
        }

        if scenario.clickable_uri:
            document["clickableUri"] = scenario.clickable_uri
        if scenario.printable_uri:
            document["printableUri"] = scenario.printable_uri
        if scenario.parent_id:
            document["parentId"] = scenario.parent_id
        if scenario.permissions:
            document["permissions"] = scenario.permissions
        if scenario.metadata:
            conflicting_keys = RESERVED_METADATA_FIELDS.intersection(scenario.metadata)
            if conflicting_keys:
                conflicts = ", ".join(sorted(conflicting_keys))
                raise ValueError(
                    f"Scenario '{describe_scenario(scenario)}' metadata contains reserved field(s): {conflicts}"
                )
            document.update(scenario.metadata)

        params: dict[str, Any] = {"documentId": scenario.document_id}
        binary_info: dict[str, Any] = {}

        if scenario.data is not None:
            document["data"] = scenario.data
            binary_info["mode"] = "inline_data"
            binary_info["dataLength"] = len(scenario.data)
            return document, params, binary_info

        if not scenario.file_path:
            raise RuntimeError("Scenario must define one of file_path or data")

        file_path = Path(scenario.file_path)
        with file_path.open("rb") as input_file:
            raw_bytes = input_file.read()

        compressed_bytes = zlib.compress(raw_bytes, level=9)
        binary_info = {
            "mode": "file_container",
            "filePath": scenario.file_path,
            "rawBytes": len(raw_bytes),
            "compressedBytes": len(compressed_bytes),
        }

        if self.dry_run:
            document["compressedBinaryDataFileId"] = "<generated at runtime>"
            params["compressionType"] = scenario.compression_type
            return document, params, binary_info

        file_container = self.create_file_container(scenario.file_extension)
        self.log_event(
            "create_file_container",
            {
                "scenario": scenario.title,
                "url": f"{self.root}/organizations/{self.org}/files",
                "params": {"fileExtension": scenario.file_extension},
                "response": {"fileId": file_container["fileId"]},
            },
        )
        self.upload_compressed_file(
            file_container["uploadUri"],
            file_container.get("requiredHeaders", {}),
            compressed_bytes,
        )
        self.log_event(
            "upload_compressed_file",
            {
                "scenario": scenario.title,
                "uploadUri": file_container["uploadUri"],
                "requiredHeaders": file_container.get("requiredHeaders", {}),
                "binary": binary_info,
            },
        )
        document["compressedBinaryDataFileId"] = file_container["fileId"]
        params["compressionType"] = scenario.compression_type
        return document, params, binary_info

    def log_event(self, event_type: str, payload: dict[str, Any]) -> None:
        entry = {
            "timestamp": datetime.now(UTC).isoformat(),
            "event": event_type,
            "organization": self.org,
            "source": self.source,
            "payload": payload,
        }
        with self.log_path.open("a", encoding="utf-8") as log_file:
            log_file.write(json.dumps(entry, ensure_ascii=True) + "\n")


def guess_content_type(scenario: PushScenario) -> str:
    guessed = None
    if scenario.file_path:
        guessed, _ = mimetypes.guess_type(str(Path(scenario.file_path)))
        if guessed:
            return guessed

    if scenario.data is not None and scenario.file_extension.lower() in {".html", ".htm"}:
        return "text/html"

    if scenario.data is not None and scenario.file_extension.lower() in {".txt", ".text"}:
        return "text/plain"

    file_extension = scenario.file_extension
    extension_map = {
        ".html": "text/html",
        ".pdf": "application/pdf",
        ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    }
    return extension_map.get(file_extension.lower(), "application/octet-stream")


def build_push_params(scenario: PushScenario, base_params: dict[str, Any] | None = None) -> dict[str, Any]:
    params: dict[str, Any] = dict(base_params or {"documentId": scenario.document_id})
    if scenario.ordering_id is not None:
        params["orderingId"] = scenario.ordering_id
    return params


def describe_scenario(scenario: PushScenario) -> str:
    if scenario.title.strip():
        return scenario.title
    if scenario.document_id.strip():
        return scenario.document_id
    return "<unnamed scenario>"


def validate_push_scenario(scenario: PushScenario) -> None:
    errors: list[str] = []

    if not scenario.document_id.strip():
        errors.append("document_id must be a non-empty string")
    if not scenario.title.strip():
        errors.append("title must be a non-empty string")
    if not scenario.file_extension.strip():
        errors.append("file_extension must be a non-empty string")

    has_data = scenario.data is not None
    has_file = bool(scenario.file_path)
    if has_data and has_file:
        errors.append("define either file_path or data, not both")
    elif not has_data and not has_file:
        errors.append("define one of file_path or data")

    if scenario.file_path:
        file_path = Path(scenario.file_path)
        if not file_path.is_file():
            errors.append(f"file_path does not exist: {scenario.file_path}")

    if scenario.metadata is not None and not isinstance(scenario.metadata, dict):
        errors.append("metadata must be an object when provided")

    if errors:
        joined = "; ".join(errors)
        raise ValueError(f"Scenario '{describe_scenario(scenario)}' is invalid: {joined}")


def compute_retry_delay(retry_after_header: str | None, attempt: int, base_seconds: float) -> float:
    if retry_after_header:
        try:
            return max(float(retry_after_header), 0)
        except ValueError:
            pass

    backoff = base_seconds * (2**attempt)
    jitter = random.uniform(0, backoff * 0.25)
    return backoff + jitter


def make_dry_run_response(status_code: int, text: str) -> Response:
    response = Response()
    response.status_code = status_code
    response._content = text.encode("utf-8")
    return response
