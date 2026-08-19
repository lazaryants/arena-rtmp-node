import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from app.config_migrations import ConfigMigrationError, migrate_config


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def legacy_config():
    return {
        "fields": {
            "3": {
                "name": "Place 3",
                "enabled": True,
                "stream_key": "stream3",
                "key": "publish-secret",
                "restream_url": "rtmps://one.example/live/private-one",
                "restream_urls": ["rtmp://two.example/live/private-two"],
                "rtmp_url": "rtmp://old.example/place3/stream3",
                "hls_url": "/hls/place3/stream3.m3u8",
            },
        },
    }


class ConfigMigrationTests(unittest.TestCase):
    def test_v0_to_v1_preserves_keys_and_destinations(self):
        original = legacy_config()
        unchanged = copy.deepcopy(original)
        migrated, original_version = migrate_config(original)

        self.assertEqual(original_version, 0)
        self.assertEqual(original, unchanged)
        self.assertEqual(migrated["schema_version"], 2)
        field = migrated["fields"]["3"]
        self.assertEqual(field["key"], "publish-secret")
        self.assertEqual(field["restream_urls"], [
            {
                "url": "rtmp://two.example/live/private-two",
                "audio_mode": "source",
            },
            {
                "url": "rtmps://one.example/live/private-one",
                "audio_mode": "source",
            },
        ])
        self.assertFalse(field["publish_auth_enabled"])
        self.assertNotIn("restream_url", field)
        self.assertNotIn("rtmp_url", field)
        self.assertNotIn("hls_url", field)

    def test_v1_to_v2_preserves_destinations_with_source_audio(self):
        config = {
            "schema_version": 1,
            "fields": {
                "1": {
                    "name": "Place 1",
                    "enabled": True,
                    "stream_key": "stream1",
                    "key": "secret",
                    "publish_auth_enabled": True,
                    "restream_urls": [
                        "rtmp://destination.example/live/private",
                    ],
                },
            },
        }
        migrated, original_version = migrate_config(config)
        self.assertEqual(original_version, 1)
        self.assertEqual(migrated["schema_version"], 2)
        self.assertEqual(migrated["fields"]["1"]["restream_urls"], [{
            "url": "rtmp://destination.example/live/private",
            "audio_mode": "source",
        }])

    def test_rejects_future_or_invalid_legacy_config(self):
        with self.assertRaisesRegex(ConfigMigrationError, "newer"):
            migrate_config({"schema_version": 3, "fields": {}})

        config = legacy_config()
        config["fields"]["3"]["restream_url"] = "https://invalid.example"
        with self.assertRaisesRegex(ConfigMigrationError, "RTMP or RTMPS"):
            migrate_config(config)

    def test_cli_check_is_read_only_and_apply_creates_protected_backup(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "restream-config.json"
            path.write_text(json.dumps(legacy_config()), encoding="utf-8")
            original = path.read_bytes()
            original_owner = (path.stat().st_uid, path.stat().st_gid)
            command = [
                sys.executable,
                str(PROJECT_ROOT / "scripts/migrate_config.py"),
                "--config",
                str(path),
            ]

            check = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(check.returncode, 2)
            self.assertEqual(path.read_bytes(), original)
            self.assertNotIn("publish-secret", check.stdout + check.stderr)

            apply = subprocess.run(command + ["--apply"], capture_output=True, text=True)
            self.assertEqual(apply.returncode, 0, apply.stderr)
            backups = list(path.parent.glob("restream-config.json.backup-v0-*"))
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0].read_bytes(), original)
            self.assertEqual(backups[0].stat().st_mode & 0o777, 0o600)
            self.assertEqual(json.loads(path.read_text())["schema_version"], 2)
            self.assertEqual((path.stat().st_uid, path.stat().st_gid), original_owner)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertNotIn("publish-secret", apply.stdout + apply.stderr)


if __name__ == "__main__":
    unittest.main()
