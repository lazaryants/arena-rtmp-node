import json
import tempfile
import unittest
from pathlib import Path

from app.config_store import ConfigStore, ConfigValidationError, validate_config


def valid_config():
    return {
        "fields": {
            "1": {
                "name": "Place 1",
                "emoji": "🏟️",
                "enabled": True,
                "stream_key": "stream1",
                "key": "publish-key",
                "publish_auth_enabled": True,
                "restream_urls": [
                    "rtmps://destination.example/live/private-token",
                ],
            },
        },
    }


class ConfigStoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.path = Path(self.temporary_directory.name) / "config/restream-config.json"
        self.store = ConfigStore(self.path)

    def tearDown(self):
        self.temporary_directory.cleanup()

    def test_atomic_save_round_trip_and_permissions(self):
        config = valid_config()
        self.store.save(config)

        self.assertEqual(self.store.load(), config)
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        temporary_files = list(self.path.parent.glob(f".{self.path.name}.*.tmp"))
        self.assertEqual(temporary_files, [])

    def test_invalid_update_does_not_replace_existing_file(self):
        self.store.save(valid_config())
        original = self.path.read_bytes()
        invalid = valid_config()
        invalid["fields"]["1"]["restream_urls"] = ["https://not-rtmp.example"]

        with self.assertRaises(ConfigValidationError):
            self.store.save(invalid)

        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(self.store.load(), valid_config())

    def test_publish_auth_requires_key(self):
        config = valid_config()
        del config["fields"]["1"]["key"]
        with self.assertRaisesRegex(ConfigValidationError, "key is required"):
            validate_config(config)

    def test_rejects_unknown_fields_and_ids(self):
        config = valid_config()
        config["fields"]["17"] = config["fields"].pop("1")
        with self.assertRaisesRegex(ConfigValidationError, "invalid field ID"):
            validate_config(config)

        config = valid_config()
        config["fields"]["1"]["unexpected"] = True
        with self.assertRaisesRegex(ConfigValidationError, "unsupported keys"):
            validate_config(config)

    def test_serialized_file_is_valid_json(self):
        self.store.save(valid_config())
        json.loads(self.path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
