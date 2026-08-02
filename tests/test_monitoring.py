import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from app.monitoring import health_snapshot, metrics_snapshot
from app.settings import Settings


class MonitoringTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.hls_root = self.root / "hls"
        self.hls_root.mkdir()
        self.ffmpeg = self.root / "ffmpeg"
        self.ffmpeg.write_text("#!/bin/sh\n", encoding="utf-8")
        self.ffmpeg.chmod(0o755)

        environment = {
            "CRICKET_RTMP_ROOT": str(self.root),
            "CRICKET_RTMP_HLS_ROOT": str(self.hls_root),
            "CRICKET_RTMP_FFMPEG": str(self.ffmpeg),
            "CRICKET_RTMP_STAT_URL": "http://127.0.0.1:8090/stat",
        }
        with patch.dict(os.environ, environment, clear=True):
            self.settings = Settings()

        self.settings.config_file.parent.mkdir(parents=True)
        self.settings.config_file.write_text(
            json.dumps({
                "fields": {
                    "1": {
                        "enabled": True,
                        "stream_key": "stream1",
                        "key": "publish-secret",
                        "publish_auth_enabled": True,
                        "restream_urls": [
                            "rtmp://destination.example/live/private-token",
                        ],
                    },
                },
            }),
            encoding="utf-8",
        )

        place1 = self.hls_root / "place1"
        place1.mkdir()
        segment = place1 / "stream1-1.ts"
        segment.write_bytes(b"segment")
        os.utime(segment, (time.time(), time.time()))

    def tearDown(self):
        self.temporary_directory.cleanup()

    @patch("app.monitoring.rtmp_snapshot")
    def test_metrics_are_safe_and_report_active_hls(self, mocked_rtmp):
        mocked_rtmp.return_value = {
            "reachable": True,
            "active_streams": 1,
            "clients": 1,
            "applications": {"place1": {"streams": 1, "clients": 1}},
        }
        metrics = metrics_snapshot(self.settings)
        serialized = json.dumps(metrics)

        self.assertEqual(metrics["hls"]["places"]["1"]["state"], "active")
        self.assertEqual(metrics["config"]["publish_auth_enabled_places"], 1)
        self.assertNotIn("publish-secret", serialized)
        self.assertNotIn("private-token", serialized)
        self.assertNotIn("restream_urls", serialized)

    @patch("app.monitoring.rtmp_snapshot")
    def test_health_is_ok_when_dependencies_are_ready(self, mocked_rtmp):
        mocked_rtmp.return_value = {"reachable": True}
        health = health_snapshot(self.settings)
        self.assertEqual(health["status"], "ok")
        self.assertTrue(all(check["ok"] for check in health["checks"].values()))


if __name__ == "__main__":
    unittest.main()
