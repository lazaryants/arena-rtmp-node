import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import restream_manager
from app.config_store import ConfigStore


class ConfigApiTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.path = Path(self.temporary_directory.name) / "restream-config.json"
        self.store = ConfigStore(self.path)
        self.store.save({
            "fields": {
                "1": {
                    "name": "Place 1",
                    "enabled": True,
                    "stream_key": "stream1",
                    "key": "publish-key",
                    "publish_auth_enabled": True,
                    "restream_urls": [],
                },
            },
        })
        self.store_patch = patch.object(restream_manager, "CONFIG_STORE", self.store)
        self.store_patch.start()
        self.client = restream_manager.app.test_client()

    def tearDown(self):
        self.store_patch.stop()
        self.temporary_directory.cleanup()

    def test_rejects_invalid_destination_without_changing_config(self):
        original = self.path.read_bytes()
        response = self.client.post(
            "/api/restream-urls/1",
            json={"url": "https://not-an-rtmp-destination.example"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.path.read_bytes(), original)

    def test_valid_destination_is_persisted(self):
        response = self.client.post(
            "/api/restream-urls/1",
            json={"url": "rtmps://destination.example/live/token"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            self.store.load()["fields"]["1"]["restream_urls"],
            ["rtmps://destination.example/live/token"],
        )


if __name__ == "__main__":
    unittest.main()
