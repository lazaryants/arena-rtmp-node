import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from jinja2 import FileSystemLoader

from app import restream_manager

from app.audit_log import AuditLog
from app.access_control import (
    ROLES,
    UserStore,
    UserStoreError,
    role_allows,
)


class AccessControlTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.path = Path(self.temporary_directory.name) / "users.json"
        self.store = UserStore(self.path)
        self.audit = AuditLog(
            Path(self.temporary_directory.name) / "audit.jsonl"
        )
        self.audit_patch = patch.object(
            restream_manager,
            "AUDIT_LOG",
            self.audit,
        )
        self.audit_patch.start()

    def tearDown(self):
        self.audit_patch.stop()
        self.temporary_directory.cleanup()

    def test_role_hierarchy(self):
        self.assertTrue(role_allows("admin", "viewer"))
        self.assertTrue(role_allows("manager", "operator"))
        self.assertTrue(role_allows("operator", "operator"))
        self.assertFalse(role_allows("operator", "manager"))
        self.assertFalse(role_allows("viewer", "operator"))
        self.assertFalse(role_allows("unknown", "viewer"))

    def test_create_authenticate_and_disable_user(self):
        self.store.set_user("andrey", "Long-test-password", "admin")
        self.assertEqual(
            self.store.authenticate("andrey", "Long-test-password"),
            {"username": "andrey", "role": "admin"},
        )
        self.assertIsNone(
            self.store.authenticate("andrey", "wrong-password"),
        )
        self.store.disable_user("andrey")
        self.assertIsNone(
            self.store.authenticate("andrey", "Long-test-password"),
        )

    def test_password_hash_is_not_exposed(self):
        self.store.set_user("manager", "Long-test-password", "manager")
        users = self.store.public_users()
        self.assertEqual(
            users,
            [{"username": "manager", "role": "manager", "enabled": True}],
        )
        self.assertNotIn("Long-test-password", self.path.read_text())

    def test_short_password_is_rejected_without_file(self):
        with self.assertRaises(UserStoreError):
            self.store.set_user("viewer", "short", "viewer")
        self.assertFalse(self.path.exists())

    def test_eight_character_mixed_case_special_password_is_accepted(self):
        self.store.set_user("viewer", "Abcdef!?", "viewer")
        self.assertIsNotNone(
            self.store.authenticate("viewer", "Abcdef!?"),
        )

    def test_password_requires_lowercase_uppercase_and_special(self):
        invalid_passwords = (
            "Abcdef!",
            "ABCDEFG!",
            "abcdefg!",
            "Abcdefgh",
            "Abc defG",
        )
        for password in invalid_passwords:
            with self.subTest(password=password):
                with self.assertRaises(UserStoreError):
                    self.store.set_user("viewer", password, "viewer")

    def test_all_supported_roles_can_be_stored(self):
        for role in ROLES:
            self.store.set_user(role, f"Password-for-{role}", role)
        self.assertEqual(len(self.store.public_users()), len(ROLES))

    def test_safe_monitoring_reads_require_only_viewer_role(self):
        for path in (
            "/api/config/fields",
            "/api/config/fields/status",
        ):
            with self.subTest(path=path):
                with restream_manager.app.test_request_context(
                    path,
                    method="GET",
                ):
                    self.assertEqual(
                        restream_manager.minimum_role_for_request(),
                        "viewer",
                    )

    def test_configuration_writes_and_full_config_remain_admin_only(self):
        requests = (
            ("GET", "/api/config/fields/all"),
            ("POST", "/api/config/fields"),
            ("PUT", "/api/config/fields/1"),
            ("POST", "/api/config/fields/1/rotate-key"),
            ("DELETE", "/api/config/fields/1"),
        )
        for method, path in requests:
            with self.subTest(method=method, path=path):
                with restream_manager.app.test_request_context(
                    path,
                    method=method,
                ):
                    self.assertEqual(
                        restream_manager.minimum_role_for_request(),
                        "admin",
                    )

    def test_public_monitoring_endpoints_bypass_login(self):
        paths = (
            "/api/config/fields",
            "/api/config/fields/status",
            "/api/node/metrics",
        )
        with patch.object(
            restream_manager,
            "SETTINGS",
            SimpleNamespace(rbac_enabled=True),
        ):
            for path in paths:
                with self.subTest(path=path):
                    with restream_manager.app.test_request_context(path):
                        self.assertIsNone(
                            restream_manager.app.preprocess_request()
                        )

    def test_unauthenticated_api_is_rejected_when_enabled(self):
        with (
            patch.object(
                restream_manager,
                "SETTINGS",
                SimpleNamespace(rbac_enabled=True),
            ),
            patch.object(restream_manager, "USER_STORE", self.store),
        ):
            response = restream_manager.app.test_client().get("/api/status")

        self.assertEqual(response.status_code, 401)
        self.assertEqual(
            response.get_json()["message"],
            "Authentication required",
        )

    def test_manager_cannot_open_admin_configuration(self):
        self.store.set_user("manager", "Long-test-password", "manager")
        client = restream_manager.app.test_client()

        with (
            patch.object(
                restream_manager,
                "SETTINGS",
                SimpleNamespace(rbac_enabled=True),
            ),
            patch.object(restream_manager, "USER_STORE", self.store),
        ):
            with client.session_transaction() as browser_session:
                browser_session["username"] = "manager"
            response = client.get("/api/config/fields/all")

        self.assertEqual(response.status_code, 403)
        self.assertEqual(
            response.get_json()["message"],
            "Insufficient permissions",
        )

    def test_login_creates_session_without_exposing_role_cookie(self):
        self.store.set_user("operator", "Long-test-password", "operator")
        client = restream_manager.app.test_client()

        with (
            patch.object(
                restream_manager,
                "SETTINGS",
                SimpleNamespace(rbac_enabled=True),
            ),
            patch.object(restream_manager, "USER_STORE", self.store),
        ):
            response = client.post(
                "/login",
                data={
                    "username": "operator",
                    "password": "Long-test-password",
                    "next": "/admin/",
                },
            )
            session_response = client.get("/api/session")

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "/admin/")
        self.assertEqual(session_response.status_code, 200)
        self.assertEqual(session_response.get_json()["role"], "operator")

    def test_mutating_request_requires_valid_csrf_token(self):
        self.store.set_user("operator", "Long-test-password", "operator")
        client = restream_manager.app.test_client()

        template_directory = Path(__file__).resolve().parents[1] / (
            "app/templates"
        )
        with (
            patch.object(
                restream_manager,
                "SETTINGS",
                SimpleNamespace(rbac_enabled=True),
            ),
            patch.object(restream_manager, "USER_STORE", self.store),
            patch.object(
                restream_manager.app,
                "jinja_loader",
                FileSystemLoader(template_directory),
            ),
        ):
            with client.session_transaction() as browser_session:
                browser_session["username"] = "operator"
                browser_session["csrf_token"] = "expected-token"

            rejected = client.post("/logout")
            accepted = client.post(
                "/logout",
                data={"csrf_token": "expected-token"},
            )

        self.assertEqual(rejected.status_code, 403)
        self.assertEqual(accepted.status_code, 302)

    def test_operator_page_does_not_expose_destination_url(self):
        secret_url = "rtmp://destination.example/live/secret"
        self.store.set_user("operator", "Long-test-password", "operator")
        client = restream_manager.app.test_client()
        settings = SimpleNamespace(
            rbac_enabled=True,
            pid_file=lambda *_args: "/tmp/missing.pid",
            log_file=lambda *_args: "/tmp/missing.log",
            progress_file=lambda *_args: "/tmp/missing.progress",
        )

        template_directory = Path(__file__).resolve().parents[1] / (
            "app/templates"
        )
        with (
            patch.object(restream_manager, "SETTINGS", settings),
            patch.object(restream_manager, "USER_STORE", self.store),
            patch.object(
                restream_manager.app,
                "jinja_loader",
                FileSystemLoader(template_directory),
            ),
            patch.object(
                restream_manager,
                "get_fields",
                return_value={
                    1: {
                        "name": "Field 1",
                        "urls": [{
                            "url": secret_url,
                            "audio_mode": "silent",
                        }],
                    },
                },
            ),
        ):
            with client.session_transaction() as browser_session:
                browser_session["username"] = "operator"
            response = client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertNotIn(secret_url, response.get_data(as_text=True))
        self.assertIn(
            "Configured destination",
            response.get_data(as_text=True),
        )
        self.assertIn(
            "Silent AAC",
            response.get_data(as_text=True),
        )

    def test_user_cli_runs_without_project_pythonpath(self):
        project_root = Path(__file__).resolve().parents[1]
        environment = os.environ.copy()
        environment.pop("PYTHONPATH", None)
        environment["ARENA_RTMP_ROOT"] = self.temporary_directory.name
        result = subprocess.run(
            [
                sys.executable,
                str(project_root / "scripts/manage_users.py"),
                "set",
                "cli-admin",
                "--role",
                "admin",
                "--password-stdin",
            ],
            input="Long-cli-password\n",
            text=True,
            capture_output=True,
            cwd="/tmp",
            env=environment,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

        listed = subprocess.run(
            [
                sys.executable,
                str(project_root / "scripts/manage_users.py"),
                "list",
            ],
            text=True,
            capture_output=True,
            cwd="/tmp",
            env=environment,
            check=False,
        )
        self.assertEqual(listed.returncode, 0, listed.stderr)
        self.assertEqual(
            json.loads(listed.stdout),
            [{
                "username": "cli-admin",
                "role": "admin",
                "enabled": True,
            }],
        )


if __name__ == "__main__":
    unittest.main()
