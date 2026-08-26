import json
import tempfile
import unittest
from pathlib import Path

from app import rtmp_auth


class AuthorizePublishTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.config_path = Path(self.temporary_directory.name) / "config.json"
        self.config_path.write_text(
            json.dumps({
                "schema_version": 2,
                "fields": {
                    "15": {
                        "stream_key": "stream15",
                        "key": "correct-key",
                        "publish_auth_enabled": True,
                    },
                    "14": {
                        "stream_key": "stream14",
                        "publish_auth_enabled": False,
                    },
                },
            }),
            encoding="utf-8",
        )
        self.original_config_file = rtmp_auth.CONFIG_FILE
        rtmp_auth.CONFIG_FILE = self.config_path

    def tearDown(self):
        rtmp_auth.CONFIG_FILE = self.original_config_file
        self.temporary_directory.cleanup()

    def test_rejects_wrong_key(self):
        result = rtmp_auth.authorize_publish(
            "place15",
            "stream15",
            "",
            "wrong-key",
        )
        self.assertEqual(result, (403, "invalid_key"))

    def test_accepts_top_level_key(self):
        result = rtmp_auth.authorize_publish(
            "place15",
            "stream15",
            "",
            "correct-key",
        )
        self.assertEqual(result, (200, "authorized"))

    def test_accepts_args_fallback(self):
        result = rtmp_auth.authorize_publish(
            "place15",
            "stream15",
            "key=correct-key",
        )
        self.assertEqual(result, (200, "authorized"))

    def test_mediamtx_accepts_existing_public_url(self):
        result = rtmp_auth.authorize_mediamtx({
            "action": "publish",
            "protocol": "rtmp",
            "path": "place15/stream15",
            "query": "key=correct-key",
        })
        self.assertEqual(
            result,
            (
                200,
                "authorized",
                "place15",
                "stream15",
            ),
        )

    def test_mediamtx_rejects_wrong_key(self):
        result = rtmp_auth.authorize_mediamtx({
            "action": "publish",
            "protocol": "rtmp",
            "path": "place15/stream15",
            "query": "key=wrong-key",
        })
        self.assertEqual(
            result,
            (
                403,
                "invalid_key",
                "place15",
                "stream15",
            ),
        )

    def test_mediamtx_rejects_noncanonical_path(self):
        result = rtmp_auth.authorize_mediamtx({
            "action": "publish",
            "protocol": "rtmp",
            "path": "place15",
            "query": "key=correct-key",
        })
        self.assertEqual(
            result,
            (
                403,
                "invalid_path",
                "unknown",
                "unknown",
            ),
        )

    def test_rejects_wrong_stream(self):
        result = rtmp_auth.authorize_publish(
            "place15",
            "wrong-stream",
            "key=correct-key",
        )
        self.assertEqual(result, (403, "invalid_stream"))

    def test_preserves_legacy_mode(self):
        result = rtmp_auth.authorize_publish(
            "place14",
            "stream14",
            "",
        )
        self.assertEqual(result, (200, "legacy_allowed"))


if __name__ == "__main__":
    unittest.main()
