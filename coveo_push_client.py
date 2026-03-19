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
    title: str | None = None
    file_extension: str | None = None
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
        request_timeout_seconds: int = 30,
        upload_timeout_seconds: int = 120,
        dry_run: bool = False,
    ) -> None:
        self.org = org
        self.source = source
        self.root = root.rstrip("/")
        self.headers = {"Authorization": f"Bearer {api_key}"}
        self.max_retries = max_retries
        self.backoff_base_seconds = backoff_base_seconds
        self.request_timeout_seconds = request_timeout_seconds
        self.upload_timeout_seconds = upload_timeout_seconds
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
        request_timeout_seconds: int = 30,
        upload_timeout_seconds: int = 120,
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
            request_timeout_seconds=request_timeout_seconds,
            upload_timeout_seconds=upload_timeout_seconds,
            dry_run=dry_run,
        )

    def create_file_container(self, file_extension: str) -> dict:
        response = self.request_with_retry(
            "POST",
            f"{self.root}/organizations/{self.org}/files",
            headers={**self.headers, "Content-Type": "application/json"},
            params={"fileExtension": file_extension},
            json={},
            timeout=self.request_timeout_seconds,
            log_context={"operation": "create_file_container", "fileExtension": file_extension},
        )
        response.raise_for_status()
        return response.json()

    def upload_compressed_file(
        self,
        upload_uri: str,
        required_headers: dict,
        compressed_bytes: bytes,
        log_context: dict[str, Any] | None = None,
    ) -> None:
        response = self.request_with_retry(
            "PUT",
            upload_uri,
            data=compressed_bytes,
            headers=required_headers,
            timeout=self.upload_timeout_seconds,
            log_context=log_context,
        )
        response.raise_for_status()

    def push_scenario(self, scenario: PushScenario) -> requests.Response:
        validate_push_scenario(scenario)
        document, params, binary_info = self.build_push_request(scenario)
        request_params = build_push_params(scenario, params)
        request_headers = {**self.headers, "Content-Type": "application/json"}
        request_url = f"{self.root}/organizations/{self.org}/sources/{self.source}/documents"
        log_context = {
            "operation": "push",
            "documentId": scenario.document_id,
            "title": scenario.title,
            "binary": binary_info,
        }

        if self.dry_run:
            response = make_dry_run_response(202, "DRY RUN: push skipped")
            self.log_http_exchange(
                request={
                    "method": "PUT",
                    "url": request_url,
                    "headers": sanitize_headers(request_headers),
                    "params": request_params,
                    "json": document,
                    "timeout": self.request_timeout_seconds,
                },
                response=response,
                context={**log_context, "dry_run": True},
            )
            return response

        response = self.request_with_retry(
            "PUT",
            request_url,
            headers=request_headers,
            params=request_params,
            json=document,
            timeout=self.request_timeout_seconds,
            log_context=log_context,
        )
        response.raise_for_status()
        return response

    def delete_document(self, document_id: str) -> requests.Response:
        if not document_id or not document_id.strip():
            raise ValueError("document_id must be a non-empty string")
        request_url = f"{self.root}/organizations/{self.org}/sources/{self.source}/documents"
        request_params = {"documentId": document_id}
        log_context = {"operation": "delete_document", "documentId": document_id}
        if self.dry_run:
            response = make_dry_run_response(202, "DRY RUN: delete skipped")
            self.log_http_exchange(
                request={
                    "method": "DELETE",
                    "url": request_url,
                    "headers": sanitize_headers(self.headers),
                    "params": request_params,
                    "timeout": self.request_timeout_seconds,
                },
                response=response,
                context={**log_context, "dry_run": True},
            )
            return response

        response = self.request_with_retry(
            "DELETE",
            request_url,
            headers=self.headers,
            params=request_params,
            timeout=self.request_timeout_seconds,
            log_context=log_context,
        )
        response.raise_for_status()
        return response

    def delete_older_than(self, ordering_id: int, queue_delay: int = 15) -> requests.Response:
        request_url = f"{self.root}/organizations/{self.org}/sources/{self.source}/documents/olderthan"
        request_headers = {**self.headers, "Accept": "application/json"}
        request_params = {"orderingId": ordering_id, "queueDelay": queue_delay}
        request_json = {}
        log_context = {
            "operation": "delete_older_than",
            "orderingId": ordering_id,
            "queueDelay": queue_delay,
        }
        if self.dry_run:
            response = make_dry_run_response(202, "DRY RUN: delete older than skipped")
            self.log_http_exchange(
                request={
                    "method": "DELETE",
                    "url": request_url,
                    "headers": sanitize_headers(request_headers),
                    "params": request_params,
                    "json": request_json,
                    "timeout": self.request_timeout_seconds,
                },
                response=response,
                context={**log_context, "dry_run": True},
            )
            return response

        response = self.request_with_retry(
            "DELETE",
            request_url,
            headers=request_headers,
            params=request_params,
            json=request_json,
            timeout=self.request_timeout_seconds,
            log_context=log_context,
        )
        response.raise_for_status()
        return response

    def request_with_retry(
        self,
        method: str,
        url: str,
        log_context: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> Response:
        retryable_statuses = {429, 500, 502, 503, 504}
        last_error: Exception | None = None

        for attempt in range(self.max_retries + 1):
            request_payload = build_request_log_payload(method, url, kwargs, attempt)
            try:
                response = requests.request(method, url, **kwargs)
                self.log_http_exchange(
                    request=request_payload,
                    response=response,
                    context=log_context,
                )
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
                self.log_http_exchange(
                    request=request_payload,
                    response=None,
                    context=log_context,
                    error=error,
                )
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
        document: dict[str, Any] = {"documentId": scenario.document_id}

        if scenario.title is not None:
            document["title"] = scenario.title
        if scenario.file_extension is not None:
            document["fileExtension"] = scenario.file_extension
        if scenario.content_type is not None:
            document["contentType"] = scenario.content_type

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
                    f"Tool constraint: scenario '{describe_scenario(scenario)}' metadata contains reserved field(s) this harness cannot place inside metadata: {conflicts}"
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
            binary_info["mode"] = "metadata_only"
            return document, params, binary_info

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

        if not scenario.file_extension:
            raise ValueError(
                f"Tool constraint: scenario '{describe_scenario(scenario)}' must define file_extension for file_path pushes"
            )
        file_container = self.create_file_container(scenario.file_extension)
        self.upload_compressed_file(
            file_container["uploadUri"],
            file_container.get("requiredHeaders", {}),
            compressed_bytes,
            log_context={
                "operation": "upload_compressed_file",
                "documentId": scenario.document_id,
                "title": scenario.title,
                "binary": binary_info,
                "fileId": file_container["fileId"],
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

    def log_http_exchange(
        self,
        request: dict[str, Any],
        response: Response | None,
        context: dict[str, Any] | None = None,
        error: Exception | None = None,
    ) -> None:
        payload: dict[str, Any] = {
            "request": request,
            "context": context or {},
        }
        if response is not None:
            payload["response"] = {
                "status_code": response.status_code,
                "reason": response.reason,
                "headers": dict(response.headers),
                "text": response.text,
            }
        if error is not None:
            payload["error"] = {
                "type": type(error).__name__,
                "message": str(error),
            }
        self.log_event("http_exchange", payload)

def build_push_params(scenario: PushScenario, base_params: dict[str, Any] | None = None) -> dict[str, Any]:
    params: dict[str, Any] = dict(base_params or {"documentId": scenario.document_id})
    if scenario.ordering_id is not None:
        params["orderingId"] = scenario.ordering_id
    return params


def describe_scenario(scenario: PushScenario) -> str:
    if scenario.document_id.strip():
        return scenario.document_id
    if scenario.title and scenario.title.strip():
        return scenario.title
    return "<unnamed scenario>"


def sanitize_headers(headers: dict[str, Any] | None) -> dict[str, Any]:
    sanitized: dict[str, Any] = {}
    for key, value in (headers or {}).items():
        if key.lower() == "authorization":
            sanitized[key] = "<redacted>"
        else:
            sanitized[key] = value
    return sanitized


def summarize_request_data(data: Any) -> Any:
    if isinstance(data, (bytes, bytearray)):
        return {
            "type": "bytes",
            "length": len(data),
        }
    return data


def build_request_log_payload(
    method: str,
    url: str,
    kwargs: dict[str, Any],
    attempt: int,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "method": method,
        "url": url,
        "attempt": attempt + 1,
    }

    if "headers" in kwargs:
        payload["headers"] = sanitize_headers(kwargs.get("headers"))
    if "params" in kwargs:
        payload["params"] = kwargs.get("params")
    if "json" in kwargs:
        payload["json"] = kwargs.get("json")
    if "data" in kwargs:
        payload["data"] = summarize_request_data(kwargs.get("data"))
    if "timeout" in kwargs:
        payload["timeout"] = kwargs.get("timeout")

    return payload


def validate_push_scenario(scenario: PushScenario) -> None:
    errors: list[str] = []

    if not scenario.document_id.strip():
        errors.append("API-invalid: document_id must be a non-empty string")

    has_data = scenario.data is not None
    has_file = bool(scenario.file_path)
    if has_data and has_file:
        errors.append("Tool constraint: define either file_path or data, not both")
    if has_file and not scenario.file_extension:
        errors.append("Tool constraint: file_extension is required for file_path pushes in this tool")

    if scenario.file_path:
        file_path = Path(scenario.file_path)
        if not file_path.is_file():
            errors.append(f"Tool constraint: file_path does not exist on disk: {scenario.file_path}")

    if scenario.metadata is not None and not isinstance(scenario.metadata, dict):
        errors.append("Tool constraint: metadata must be an object when provided")

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
