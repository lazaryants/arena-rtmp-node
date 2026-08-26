import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app.restream_supervisor import RestreamSupervisor
from app.supervisor_client import SupervisorClient, SupervisorUnavailable


class _FakeSocket:
    def __init__(self):
        self.sent = b""
        self.response = b'{"success":true,"message":"ok"}\n'

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def settimeout(self, timeout):
        self.timeout = timeout

    def connect(self, path):
        self.path = path

    def sendall(self, value):
        self.sent += value

    def recv(self, size):
        response, self.response = self.response, b""
        return response


class SupervisorClientTests(unittest.TestCase):
    def test_client_sends_only_identifiers(self):
        fake_socket = _FakeSocket()
        with mock.patch("app.supervisor_client.socket.socket", return_value=fake_socket):
            result = SupervisorClient("/run/supervisor.sock").request("start", 3, 1)

        self.assertTrue(result["success"])
        self.assertEqual(json.loads(fake_socket.sent), {
            "action": "start",
            "field_id": 3,
            "url_index": 1,
        })

    def test_unavailable_socket_has_safe_error(self):
        with tempfile.TemporaryDirectory() as directory:
            client = SupervisorClient(Path(directory) / "missing.sock")
            with self.assertRaisesRegex(SupervisorUnavailable, "unavailable"):
                client.request("stop", 1)


class SupervisorValidationTests(unittest.TestCase):
    def setUp(self):
        self.supervisor = RestreamSupervisor()

    def test_source_uses_local_mediamtx_without_stream_key(self):
        settings = mock.Mock(
            local_rtmp_origin="rtmp://127.0.0.1:19350",
        )
        supervisor = RestreamSupervisor(settings)

        self.assertEqual(
            supervisor.source_url(6, "stream6"),
            "rtmp://127.0.0.1:19350/place6",
        )

    def test_source_mapping_supports_future_places(self):
        settings = mock.Mock(
            local_rtmp_origin="rtmp://127.0.0.1:19350",
        )
        supervisor = RestreamSupervisor(settings)

        self.assertEqual(
            supervisor.source_url(16, "stream16"),
            "rtmp://127.0.0.1:19350/place16",
        )

    def test_ffmpeg_audio_modes_copy_video_without_transcoding(self):
        settings = mock.Mock(
            ffmpeg_bin=Path("/usr/bin/ffmpeg"),
            local_rtmp_origin="rtmp://127.0.0.1",
        )
        supervisor = RestreamSupervisor(settings)
        progress = Path("/run/restream.progress")
        source = "rtmp://127.0.0.1/place1/stream1"
        destination_url = "rtmps://destination.example/live/private"

        source_command = supervisor.ffmpeg_command(
            source,
            {"url": destination_url, "audio_mode": "source"},
            progress,
        )
        self.assertIn("-c", source_command)
        self.assertIn("copy", source_command)
        self.assertIn("0:a:0?", source_command)

        silent_command = supervisor.ffmpeg_command(
            source,
            {"url": destination_url, "audio_mode": "silent"},
            progress,
        )
        self.assertIn("anullsrc=channel_layout=stereo:sample_rate=48000", silent_command)
        self.assertIn("-c:v", silent_command)
        self.assertIn("copy", silent_command)
        self.assertIn("-c:a", silent_command)
        self.assertIn("aac", silent_command)
        self.assertIn("-shortest", silent_command)

        no_audio_command = supervisor.ffmpeg_command(
            source,
            {"url": destination_url, "audio_mode": "none"},
            progress,
        )
        self.assertIn("-an", no_audio_command)
        self.assertIn("-c:v", no_audio_command)
        self.assertIn("copy", no_audio_command)

    def test_rejects_invalid_requests_before_dispatch(self):
        for request in (
            {"action": "shell", "field_id": 1},
            {"action": "start", "field_id": 0},
            {"action": "start", "field_id": True},
            {"action": "delete_destination", "field_id": 1},
        ):
            with self.subTest(request=request):
                with self.assertRaises(ValueError):
                    self.supervisor.handle(request)

    def test_dispatches_delete_without_destination_data(self):
        with mock.patch.object(
            self.supervisor,
            "delete_destination",
            return_value={"success": True},
        ) as delete:
            result = self.supervisor.handle({
                "action": "delete_destination",
                "field_id": 4,
                "url_index": 2,
            })
        self.assertTrue(result["success"])
        delete.assert_called_once_with(4, 2)


if __name__ == "__main__":
    unittest.main()
