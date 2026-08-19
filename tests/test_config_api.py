import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlparse

from app import restream_manager
from app.config_store import ConfigStore


class ConfigApiTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.path = Path(self.temporary_directory.name) / "restream-config.json"
        self.store = ConfigStore(self.path)
        self.store.save({
            "schema_version": 2,
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

    def test_full_config_includes_complete_camera_publish_url(self):
        response = self.client.get("/api/config/fields/all")

        self.assertEqual(response.status_code, 200)
        field = response.get_json()["1"]
        parsed = urlparse(field["publish_url"])
        self.assertEqual(parsed.scheme, "rtmp")
        self.assertEqual(parsed.hostname, "rtmp.arena76.top")
        self.assertEqual(parsed.path, "/place1/stream1")
        self.assertEqual(parse_qs(parsed.query), {"key": ["publish-key"]})

    def test_server_side_key_rotation_revokes_old_key(self):
        response = self.client.post("/api/config/fields/1/rotate-key")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        stored_key = self.store.load()["fields"]["1"]["key"]
        self.assertTrue(payload["success"])
        self.assertEqual(payload["key"], stored_key)
        self.assertNotEqual(stored_key, "publish-key")
        self.assertGreaterEqual(len(stored_key), 32)
        self.assertEqual(
            parse_qs(urlparse(payload["publish_url"]).query),
            {"key": [stored_key]},
        )
        self.assertNotIn(
            "publish-key",
            response.get_data(as_text=True),
        )

    def test_generic_update_cannot_replace_publish_key(self):
        original = self.path.read_bytes()
        response = self.client.put(
            "/api/config/fields/1",
            json={"key": "browser-generated-key"},
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(
            response.get_json()["message"],
            "Use the dedicated key rotation endpoint",
        )

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
            [{
                "url": "rtmps://destination.example/live/token",
                "audio_mode": "source",
            }],
        )

    def test_destination_audio_mode_is_persisted(self):
        response = self.client.post(
            "/api/restream-urls/1",
            json={
                "url": "rtmp://destination.example/live/token",
                "audio_mode": "silent",
            },
        )
        self.assertEqual(response.status_code, 200)
        destination = self.store.load()["fields"]["1"]["restream_urls"][0]
        self.assertEqual(destination["audio_mode"], "silent")

    def test_invalid_audio_mode_is_rejected_without_stopping(self):
        with patch.object(restream_manager, "stop_restream") as stop:
            response = self.client.post(
                "/api/restream-urls/1",
                json={
                    "url": "rtmp://destination.example/live/token",
                    "audio_mode": "surround",
                },
            )
        self.assertEqual(response.status_code, 400)
        stop.assert_not_called()

    def test_log_tail_is_bounded_and_returns_complete_last_lines(self):
        log_path = Path(self.temporary_directory.name) / "large.log"
        log_path.write_text(
            ("old-line\n" * 30000)
            + "recent-one\n"
            + "recent-two\n",
            encoding="utf-8",
        )

        lines = restream_manager.read_log_tail(
            log_path,
            line_count=2,
            max_bytes=1024,
        )

        self.assertEqual(lines, ["recent-one", "recent-two"])

    def fake_ffmpeg_process(self, create_time):
        process = Mock()
        process.is_running.return_value = True
        process.status.return_value = restream_manager.psutil.STATUS_RUNNING
        process.name.return_value = "ffmpeg"
        process.create_time.return_value = create_time
        return process

    def test_process_is_starting_before_media_progress_arrives(self):
        pid_file = Path(self.temporary_directory.name) / "restream.pid"
        progress_file = Path(self.temporary_directory.name) / "restream.progress"
        pid_file.write_text("321", encoding="utf-8")
        process = self.fake_ffmpeg_process(create_time=95)

        with (
            patch.object(restream_manager.psutil, "Process", return_value=process),
            patch.object(restream_manager.time, "time", return_value=100),
        ):
            status = restream_manager.get_process_status(
                pid_file,
                include_resources=False,
                progress_file=progress_file,
            )

        self.assertEqual(status["status"], "starting")

    def test_process_is_running_only_with_fresh_media_progress(self):
        pid_file = Path(self.temporary_directory.name) / "restream.pid"
        progress_file = Path(self.temporary_directory.name) / "restream.progress"
        pid_file.write_text("321", encoding="utf-8")
        progress_file.write_text(
            "total_size=4096\nout_time_us=1000000\nprogress=continue\n",
            encoding="utf-8",
        )
        process = self.fake_ffmpeg_process(create_time=50)

        with (
            patch.object(restream_manager.psutil, "Process", return_value=process),
            patch.object(restream_manager.time, "time", return_value=100),
            patch.object(restream_manager.os.path, "getmtime", return_value=99),
        ):
            status = restream_manager.get_process_status(
                pid_file,
                include_resources=False,
                progress_file=progress_file,
            )

        self.assertEqual(status["status"], "running")

    def test_process_without_recent_media_progress_is_error(self):
        pid_file = Path(self.temporary_directory.name) / "restream.pid"
        progress_file = Path(self.temporary_directory.name) / "restream.progress"
        pid_file.write_text("321", encoding="utf-8")
        progress_file.write_text(
            "total_size=4096\nout_time_us=1000000\nprogress=continue\n",
            encoding="utf-8",
        )
        process = self.fake_ffmpeg_process(create_time=50)

        with (
            patch.object(restream_manager.psutil, "Process", return_value=process),
            patch.object(restream_manager.time, "time", return_value=100),
            patch.object(restream_manager.os.path, "getmtime", return_value=80),
        ):
            status = restream_manager.get_process_status(
                pid_file,
                include_resources=False,
                progress_file=progress_file,
            )

        self.assertEqual(status["status"], "error")
        self.assertEqual(status["reason"], "No recent media output")

    @patch.object(restream_manager, "get_process_status")
    def test_status_snapshot_is_dynamic_and_does_not_expose_urls(
        self,
        mocked_status,
    ):
        self.store.save({
            "schema_version": 2,
            "fields": {
                "1": {
                    "name": "Place 1",
                    "enabled": True,
                    "stream_key": "stream1",
                    "key": "publish-key",
                    "publish_auth_enabled": True,
                    "restream_urls": [{
                        "url": "rtmp://destination.example/live/private-token",
                        "audio_mode": "none",
                    }],
                },
            },
        })
        mocked_status.return_value = {
            "status": "running",
            "pid": 123,
            "uptime": 42,
            "cpu": 1.5,
            "memory": 24.0,
        }

        response = self.client.get("/api/status")
        payload = response.get_json()
        serialized = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload["success"])
        self.assertEqual(payload["fields"]["1"]["running_count"], 1)
        self.assertEqual(
            payload["fields"]["1"]["destinations"][0]["status"],
            "running",
        )
        self.assertNotIn("private-token", serialized)
        self.assertNotIn("publish-key", serialized)


if __name__ == "__main__":
    unittest.main()
