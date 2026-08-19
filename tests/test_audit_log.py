import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from jinja2 import FileSystemLoader

from app import restream_manager
from app.access_control import UserStore
from app.audit_log import AuditLog


class AuditLogTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.path = self.root / "audit.jsonl"
        self.audit = AuditLog(
            self.path,
            max_bytes=1024,
            backup_count=2,
        )

    def tearDown(self):
        self.temporary_directory.cleanup()

    def test_record_is_private_and_sensitive_fields_are_removed(self):
        self.audit.append(
            actor="andrey",
            role="admin",
            action="destination.update",
            outcome="success",
            target={"field_id": 1, "url": "rtmp://secret/live/key"},
            details={
                "password": "NeverStoreThis!",
                "note": "sent to rtmp://secret/live/key",
                "status": 200,
            },
        )

        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        raw = self.path.read_text(encoding="utf-8")
        self.assertNotIn("NeverStoreThis", raw)
        self.assertNotIn("rtmp://secret", raw)
        record = json.loads(raw)
        self.assertNotIn("url", record["target"])
        self.assertNotIn("password", record["details"])
        self.assertEqual(record["details"]["note"], "sent to [redacted]")

    def test_recent_filters_and_limits_records(self):
        for actor, action, outcome in (
            ("andrey", "user.create", "success"),
            ("manager", "destination.update", "success"),
            ("andrey", "session.login", "failure"),
        ):
            self.audit.append(
                actor=actor,
                role="admin",
                action=action,
                outcome=outcome,
            )

        self.assertEqual(
            len(self.audit.recent(actor="andrey")),
            2,
        )
        self.assertEqual(
            self.audit.recent(outcome="failure")[0]["action"],
            "session.login",
        )
        self.assertEqual(len(self.audit.recent(limit=1)), 1)
        timestamp = self.audit.recent(limit=1)[0]["timestamp"]
        self.assertEqual(
            len(self.audit.recent(since=timestamp, until=timestamp)),
            1,
        )
        with self.assertRaises(ValueError):
            self.audit.recent(since="not-a-time")

    def test_refuses_directory_owned_by_another_user(self):
        different_uid = self.root.stat().st_uid + 1
        with (
            patch("app.audit_log.os.geteuid", return_value=different_uid),
            self.assertRaises(PermissionError),
        ):
            self.audit.append(
                actor="root-test",
                role="admin",
                action="test.action",
                outcome="success",
            )
        self.assertFalse(self.path.exists())

    def test_rotation_bounds_current_file(self):
        audit = AuditLog(
            self.path,
            max_bytes=260,
            backup_count=2,
        )
        for index in range(8):
            audit.append(
                actor="andrey",
                role="admin",
                action="test.action",
                outcome="success",
                details={"sequence": index},
            )

        self.assertTrue(self.path.exists())
        self.assertTrue(
            self.path.with_name("audit.jsonl.1").exists()
        )
        self.assertLessEqual(
            len(list(self.root.glob("audit.jsonl*"))),
            3,
        )


class AuditApiTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        root = Path(self.temporary_directory.name)
        self.store = UserStore(root / "users.json")
        self.audit = AuditLog(root / "audit.jsonl")
        self.store.set_user(
            "andrey",
            "Admin-test-password!",
            "admin",
        )
        self.client = restream_manager.app.test_client()
        self.settings = SimpleNamespace(rbac_enabled=True)
        self.templates = (
            Path(__file__).resolve().parents[1]
            / "app"
            / "templates"
        )

    def tearDown(self):
        self.temporary_directory.cleanup()

    def patches(self):
        return (
            patch.object(restream_manager, "SETTINGS", self.settings),
            patch.object(restream_manager, "USER_STORE", self.store),
            patch.object(restream_manager, "AUDIT_LOG", self.audit),
            patch.object(
                restream_manager.app,
                "jinja_loader",
                FileSystemLoader(self.templates),
            ),
        )

    def authenticate(self, username="andrey", token="test-token"):
        with self.client.session_transaction() as browser_session:
            browser_session["username"] = username
            browser_session["csrf_token"] = token
        return {"X-CSRF-Token": token}

    def test_login_success_and_failure_are_audited(self):
        first, second, third, fourth = self.patches()
        with first, second, third, fourth:
            failed = self.client.post(
                "/login",
                data={
                    "username": "andrey",
                    "password": "wrong",
                },
            )
            succeeded = self.client.post(
                "/login",
                data={
                    "username": "andrey",
                    "password": "Admin-test-password!",
                },
            )

        self.assertEqual(failed.status_code, 200)
        self.assertEqual(succeeded.status_code, 302)
        records = self.audit.recent(action="session.login")
        self.assertEqual(
            {record["outcome"] for record in records},
            {"success", "failure"},
        )

    def test_state_change_audit_never_contains_password(self):
        first, second, third, fourth = self.patches()
        with first, second, third, fourth:
            headers = self.authenticate()
            response = self.client.post(
                "/api/users",
                json={
                    "username": "operator",
                    "password": "Operator-password!",
                    "role": "operator",
                },
                headers=headers,
            )

        self.assertEqual(response.status_code, 201)
        raw = self.audit.path.read_text(encoding="utf-8")
        self.assertNotIn("Operator-password!", raw)
        record = self.audit.recent(action="user.create")[0]
        self.assertEqual(record["actor"], "andrey")
        self.assertEqual(
            record["target"]["username"],
            "operator",
        )
        self.assertEqual(record["outcome"], "success")

    def test_rejected_state_change_is_audited(self):
        first, second, third, fourth = self.patches()
        with first, second, third, fourth:
            self.authenticate()
            response = self.client.post(
                "/api/users",
                json={
                    "username": "operator",
                    "password": "Operator-password!",
                    "role": "operator",
                },
            )

        self.assertEqual(response.status_code, 403)
        record = self.audit.recent(action="user.create")[0]
        self.assertEqual(record["outcome"], "failure")
        self.assertEqual(record["details"]["status"], 403)
        self.assertEqual(
            record["details"]["reason"],
            "Invalid CSRF token",
        )

    def test_manager_cannot_read_audit_page_or_api(self):
        self.store.set_user(
            "manager",
            "Manager-password!",
            "manager",
        )
        first, second, third, fourth = self.patches()
        with first, second, third, fourth:
            self.authenticate("manager")
            api_response = self.client.get("/api/audit")
            page_response = self.client.get("/audit/")

        self.assertEqual(api_response.status_code, 403)
        self.assertEqual(page_response.status_code, 403)


if __name__ == "__main__":
    unittest.main()
