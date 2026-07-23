import unittest
from unittest.mock import patch

import requests

from rfs.vlm_client import call_vlm_json


class _Response:
    def raise_for_status(self):
        return None

    def json(self):
        return {"choices": [{"message": {"content": '{"ok": true}'}}]}


class VlmClientTests(unittest.TestCase):
    @patch("rfs.vlm_client.time.sleep", return_value=None)
    @patch("rfs.vlm_client.requests.post", side_effect=[requests.exceptions.SSLError("EOF during TLS"), _Response()])
    def test_retry_metadata_records_recovery_without_secrets(self, _post, _sleep):
        metadata = {}
        with patch.dict("os.environ", {"API_BASE": "https://example.test/v1", "API_KEY": "secret-token"}, clear=False):
            result = call_vlm_json("Return JSON", [], model="test-model", timeout=10, retries=1, call_metadata=metadata)

        self.assertTrue(result["ok"])
        self.assertEqual(metadata["attempts"], 2)
        self.assertEqual(metadata["retries_used"], 1)
        self.assertTrue(metadata["success"])
        self.assertEqual(metadata["failure_categories"], ["tls"])
        self.assertNotIn("secret-token", str(metadata))

    @patch("rfs.vlm_client.requests.post")
    def test_expired_deadline_skips_provider_call(self, post):
        metadata = {}
        with patch.dict("os.environ", {"API_BASE": "https://example.test/v1", "API_KEY": "secret-token"}, clear=False):
            with self.assertRaisesRegex(TimeoutError, "deadline budget exhausted"):
                call_vlm_json("Return JSON", [], model="test-model", timeout=30, retries=2, call_metadata=metadata, deadline_at=0.0)

        post.assert_not_called()
        self.assertEqual(metadata["attempts"], 0)
        self.assertEqual(metadata["retries_used"], 0)
        self.assertEqual(metadata["failure_categories"], ["timeout"])
        self.assertTrue(metadata["deadline_reached"])


if __name__ == "__main__":
    unittest.main()
