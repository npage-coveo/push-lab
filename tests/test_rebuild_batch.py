import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, call, patch

from coveo_push_client import CoveoPushClient, PushScenario, make_dry_run_response
from pushlab import rebuild_scenarios


class RebuildBatchTests(unittest.TestCase):
    def test_rebuild_uses_batch_push_with_shared_ordering_id(self) -> None:
        client = Mock()
        client.set_source_status.return_value = make_dry_run_response(202, "status set")
        client.push_batch_scenarios.return_value = make_dry_run_response(202, "batched")
        client.delete_older_than.return_value = make_dry_run_response(202, "cleanup queued")

        scenarios = {
            "file://alpha": PushScenario(
                document_id="file://alpha",
                payload_body={"document_id": "file://alpha", "title": "Alpha"},
                push_a_file=False,
            ),
            "file://beta": PushScenario(
                document_id="file://beta",
                payload_body={"document_id": "file://beta", "title": "Beta"},
                push_a_file=False,
            ),
        }

        rebuild_scenarios(
            client,
            scenarios,
            ["file://beta", "file://alpha"],
            queue_delay=3,
            start_ordering_id=1000,
        )

        client.push_batch_scenarios.assert_called_once()
        pushed_scenarios = client.push_batch_scenarios.call_args.args[0]
        self.assertEqual(
            [scenario.document_id for scenario in pushed_scenarios],
            ["file://beta", "file://alpha"],
        )
        self.assertEqual(client.push_batch_scenarios.call_args.kwargs["ordering_id"], 1001)
        client.delete_older_than.assert_called_once_with(1001, queue_delay=3)

    def test_rebuild_calls_operations_in_correct_order(self) -> None:
        client = Mock()
        client.set_source_status.return_value = make_dry_run_response(202, "status set")
        client.push_batch_scenarios.return_value = make_dry_run_response(202, "batched")
        client.delete_older_than.return_value = make_dry_run_response(202, "cleanup queued")

        scenarios = {
            "file://doc": PushScenario(
                document_id="file://doc",
                payload_body={"document_id": "file://doc", "title": "Doc"},
                push_a_file=False,
            ),
        }

        rebuild_scenarios(client, scenarios, [], queue_delay=5, start_ordering_id=2000)

        expected_calls = [
            call.set_source_status("REBUILD"),
            call.push_batch_scenarios([scenarios["file://doc"]], ordering_id=2001),
            call.delete_older_than(2001, queue_delay=5),
            call.set_source_status("IDLE"),
        ]
        client.assert_has_calls(expected_calls)

    def test_rebuild_sets_idle_even_when_push_fails(self) -> None:
        client = Mock()
        client.set_source_status.return_value = make_dry_run_response(202, "status set")
        client.push_batch_scenarios.side_effect = RuntimeError("network failure")
        client.delete_older_than.return_value = make_dry_run_response(202, "cleanup queued")

        scenarios = {
            "file://doc": PushScenario(
                document_id="file://doc",
                payload_body={"document_id": "file://doc", "title": "Doc"},
                push_a_file=False,
            ),
        }

        with self.assertRaises(RuntimeError):
            rebuild_scenarios(client, scenarios, [], queue_delay=5, start_ordering_id=2000)

        client.set_source_status.assert_any_call("REBUILD")
        client.set_source_status.assert_any_call("IDLE")

    def test_rebuild_does_not_call_status_when_validation_fails(self) -> None:
        client = Mock()

        scenarios = {
            "file://doc": PushScenario(
                document_id="file://doc",
                payload_body={"document_id": "file://doc", "title": "Doc"},
                push_a_file=True,
                file_path=None,
                compression_type=None,
            ),
        }

        with self.assertRaises(SystemExit):
            rebuild_scenarios(client, scenarios, [], queue_delay=5, start_ordering_id=2000)

        client.set_source_status.assert_not_called()

    def test_batch_item_for_file_push_uses_generated_file_id_and_compression_type(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            file_path = Path(temp_dir) / "example.html"
            file_path.write_text("<html><body>Batch me</body></html>", encoding="utf-8")

            scenario = PushScenario(
                document_id="file://example.html",
                payload_body={
                    "document_id": "file://example.html",
                    "title": "Example",
                    "file_extension": ".html",
                    "content_type": "text/html",
                },
                push_a_file=True,
                file_path=str(file_path),
                compression_type="ZLib",
            )

            client = CoveoPushClient(
                org="org",
                source="source",
                api_key="token",
                log_dir=temp_dir,
                dry_run=True,
            )

            batch_document_body, batch_summary = client.build_batch_request([scenario])

        self.assertEqual(batch_document_body["addOrUpdate"][0]["documentId"], "file://example.html")
        self.assertEqual(batch_document_body["addOrUpdate"][0]["compressionType"], "ZLIB")
        self.assertEqual(
            batch_document_body["addOrUpdate"][0]["compressedBinaryDataFileId"],
            "<generated at runtime>",
        )
        self.assertEqual(batch_document_body["addOrUpdate"][0]["fileExtension"], ".html")
        self.assertEqual(batch_summary[0]["binary"]["compressionType"], "ZLIB")


class SetSourceStatusTests(unittest.TestCase):
    def test_dry_run_returns_dry_run_response(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            client = CoveoPushClient(
                org="org",
                source="source",
                api_key="token",
                log_dir=temp_dir,
                dry_run=True,
            )
            response = client.set_source_status("REBUILD")
            self.assertEqual(response.status_code, 202)
            self.assertIn("DRY RUN", response.text)

            log_path = client.log_path
            self.assertTrue(log_path.exists())
            import json
            entries = [json.loads(line) for line in log_path.read_text().splitlines()]
            self.assertTrue(any(
                e["payload"]["context"].get("operation") == "set_source_status"
                for e in entries
            ))

    def test_normalizes_lowercase_and_whitespace(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            client = CoveoPushClient(
                org="org",
                source="source",
                api_key="token",
                log_dir=temp_dir,
                dry_run=True,
            )
            response = client.set_source_status("  rebuild  ")
            self.assertEqual(response.status_code, 202)

    def test_unsupported_status_raises_value_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            client = CoveoPushClient(
                org="org",
                source="source",
                api_key="token",
                log_dir=temp_dir,
                dry_run=True,
            )
            with self.assertRaises(ValueError) as ctx:
                client.set_source_status("INVALID")
            self.assertIn("INVALID", str(ctx.exception))

    @patch("coveo_push_client.requests.request")
    def test_live_call_uses_correct_url_and_params(self, mock_request: Mock) -> None:
        mock_response = Mock()
        mock_response.status_code = 201
        mock_response.headers = {}
        mock_response.text = ""
        mock_response.reason = "Created"
        mock_request.return_value = mock_response

        with tempfile.TemporaryDirectory() as temp_dir:
            client = CoveoPushClient(
                org="my-org",
                source="my-source",
                api_key="my-key",
                log_dir=temp_dir,
                dry_run=False,
            )
            client.set_source_status("REFRESH")

        mock_request.assert_called_once()
        call_args = mock_request.call_args
        self.assertEqual(call_args.args[0], "POST")
        self.assertIn("/organizations/my-org/sources/my-source/status", call_args.args[1])
        self.assertEqual(call_args.kwargs["params"], {"statusType": "REFRESH"})


if __name__ == "__main__":
    unittest.main()
