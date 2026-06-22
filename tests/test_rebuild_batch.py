import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from coveo_push_client import CoveoPushClient, PushScenario, make_dry_run_response
from pushlab import rebuild_scenarios


class RebuildBatchTests(unittest.TestCase):
    def test_rebuild_uses_batch_push_with_shared_ordering_id(self) -> None:
        client = Mock()
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


if __name__ == "__main__":
    unittest.main()
