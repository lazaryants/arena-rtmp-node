import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from app.restream_state import DesiredRestreamStore
from app.restream_supervisor import (
    ATTEMPT_WINDOW_SECONDS,
    CIRCUIT_COOLDOWN_SECONDS,
    HEALTHY_RESET_SECONDS,
    RestreamSupervisor,
)


def field():
    return {
        "stream_key": "stream10",
        "restream_urls": [{
            "url": "rtmps://destination.example/live/private",
            "audio_mode": "none",
        }],
    }


class DesiredRestreamStoreTests(unittest.TestCase):
    def test_missing_file_is_an_empty_set(self):
        with tempfile.TemporaryDirectory() as directory:
            store = DesiredRestreamStore(Path(directory) / "desired.json")
            self.assertEqual(store.load(), set())

    def test_updates_are_atomic_sorted_and_private(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state/restream-desired.json"
            store = DesiredRestreamStore(path)
            store.update({(10, 0), (2, 1)}, True)

            self.assertEqual(store.load(), {(2, 1), (10, 0)})
            self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), {
                "schema_version": 1,
                "active": [
                    {"field_id": 2, "url_index": 1},
                    {"field_id": 10, "url_index": 0},
                ],
            })
            self.assertEqual(list(path.parent.glob("*.tmp")), [])

            store.update({(2, 1)}, False)
            self.assertEqual(store.load(), {(10, 0)})

    def test_rejects_invalid_or_duplicate_entries(self):
        invalid_documents = (
            {"schema_version": 2, "active": []},
            {"schema_version": 1, "active": [{"field_id": 0, "url_index": 0}]},
            {
                "schema_version": 1,
                "active": [
                    {"field_id": 10, "url_index": 0},
                    {"field_id": 10, "url_index": 0},
                ],
            },
        )
        for document in invalid_documents:
            with self.subTest(document=document):
                with tempfile.TemporaryDirectory() as directory:
                    path = Path(directory) / "desired.json"
                    path.write_text(json.dumps(document), encoding="utf-8")
                    with self.assertRaises(ValueError):
                        DesiredRestreamStore(path).load()


class RestreamRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        root = Path(self.directory.name)
        self.settings = SimpleNamespace(
            desired_restreams_file=root / "state/restream-desired.json",
            mediamtx_api_url="http://127.0.0.1:9997",
        )
        self.supervisor = RestreamSupervisor(self.settings)
        self.supervisor.fields = mock.Mock(return_value={"10": field()})
        self.supervisor.process = mock.Mock(return_value=None)
        self.supervisor._start_selected = mock.Mock(return_value={
            "success": True,
            "started": [0],
            "already_running": [],
        })
        self.supervisor.source_ready = mock.Mock(return_value=True)

    def tearDown(self):
        self.directory.cleanup()

    def activate(self):
        self.supervisor.desired.update({(10, 0)}, True)

    def test_manual_start_persists_desired_state_before_launch(self):
        def check_state(*args):
            self.assertEqual(self.supervisor.desired.load(), {(10, 0)})
            return {"success": True, "started": [0], "already_running": []}

        self.supervisor._start_selected.side_effect = check_state
        result = self.supervisor.start(10, 0)
        self.assertTrue(result["success"])

    def test_manual_stop_clears_desired_state_before_termination(self):
        self.activate()

        def check_state(*args):
            self.assertEqual(self.supervisor.desired.load(), set())
            return {"success": True, "stopped": [0], "not_running": []}

        self.supervisor._stop_selected = mock.Mock(side_effect=check_state)
        result = self.supervisor.stop(10, 0)
        self.assertTrue(result["success"])

    def test_missing_source_waits_without_spawning(self):
        self.activate()
        self.supervisor.source_ready.return_value = False

        self.supervisor.monitor_once(now=100)
        self.supervisor.monitor_once(now=109)

        self.supervisor._start_selected.assert_not_called()
        self.assertEqual(
            self.supervisor.recovery[(10, 0)]["next_attempt"],
            110,
        )

    def test_restarts_after_source_returns(self):
        self.activate()
        self.supervisor.source_ready.side_effect = [False, True]

        self.supervisor.monitor_once(now=100)
        self.supervisor.monitor_once(now=109)
        self.supervisor.monitor_once(now=110)

        self.supervisor._start_selected.assert_called_once_with(
            10,
            self.supervisor.fields.return_value["10"],
            [0],
        )
        self.assertEqual(
            self.supervisor.recovery[(10, 0)]["next_attempt"],
            115,
        )

    def test_failed_process_uses_bounded_backoff(self):
        self.activate()
        for now in (0, 4, 5, 14, 15, 34, 35, 64, 65):
            self.supervisor.monitor_once(now=now)

        self.assertEqual(self.supervisor._start_selected.call_count, 5)
        self.assertEqual(
            self.supervisor.recovery[(10, 0)]["next_attempt"],
            125,
        )

    def test_attempt_limit_opens_a_cooldown(self):
        self.activate()
        for now in (0, 5, 15, 35, 65, 125, 185, 245, 305, 365):
            self.supervisor.monitor_once(now=now)
        self.assertEqual(self.supervisor._start_selected.call_count, 10)

        self.supervisor.monitor_once(now=425)

        self.assertEqual(self.supervisor._start_selected.call_count, 10)
        self.assertEqual(
            self.supervisor.recovery[(10, 0)]["next_attempt"],
            425 + CIRCUIT_COOLDOWN_SECONDS,
        )

    def test_healthy_process_resets_failure_history(self):
        self.activate()
        self.supervisor.process.return_value = object()
        record = self.supervisor._recovery_record((10, 0))
        record["failure_count"] = 4
        record["attempts"].extend([1, 2, 3])

        self.supervisor.monitor_once(now=100)
        self.supervisor.monitor_once(now=100 + HEALTHY_RESET_SECONDS)

        self.assertEqual(record["failure_count"], 0)
        self.assertEqual(list(record["attempts"]), [])
        self.supervisor._start_selected.assert_not_called()

    def test_invalid_configured_target_is_pruned(self):
        self.supervisor.desired.update({(10, 1)}, True)
        self.supervisor.monitor_once(now=0)
        self.assertEqual(self.supervisor.desired.load(), set())

    def test_old_attempts_leave_the_rate_limit_window(self):
        self.activate()
        record = self.supervisor._recovery_record((10, 0))
        record["attempts"].extend(range(10))
        record["next_attempt"] = ATTEMPT_WINDOW_SECONDS

        self.supervisor.monitor_once(now=ATTEMPT_WINDOW_SECONDS)

        self.supervisor._start_selected.assert_called_once()


if __name__ == "__main__":
    unittest.main()
