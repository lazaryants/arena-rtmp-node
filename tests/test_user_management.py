import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from jinja2 import FileSystemLoader

from app import restream_manager
from app.access_control import UserStore
from app.audit_log import AuditLog


class UserManagementTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.users_file = (
            Path(self.temporary_directory.name) / "users.json"
        )
        self.store = UserStore(self.users_file)
        self.store.set_user(
            "andrey",
            "Admin-test-password!",
            "admin",
        )
        self.client = restream_manager.app.test_client()
        self.settings = SimpleNamespace(rbac_enabled=True)
        self.audit_patch = patch.object(
            restream_manager,
            "AUDIT_LOG",
            AuditLog(
                Path(self.temporary_directory.name) / "audit.jsonl"
            ),
        )
        self.audit_patch.start()
        self.template_directory = (
            Path(__file__).resolve().parents[1]
            / "app"
            / "templates"
        )

    def tearDown(self):
        self.audit_patch.stop()
        self.temporary_directory.cleanup()

    def authenticated_client(self, username="andrey", token="test-token"):
        with self.client.session_transaction() as browser_session:
            browser_session["username"] = username
            browser_session["csrf_token"] = token
        return {"X-CSRF-Token": token}

    def patches(self):
        return (
            patch.object(restream_manager, "SETTINGS", self.settings),
            patch.object(restream_manager, "USER_STORE", self.store),
            patch.object(
                restream_manager.app,
                "jinja_loader",
                FileSystemLoader(self.template_directory),
            ),
        )

    def test_store_mutations_preserve_safe_account_metadata(self):
        self.store.set_user("operator", "Operator-password!", "operator")
        self.store.set_role("operator", "manager")
        self.store.set_enabled("operator", False)
        self.store.reset_password("operator", "Replacement-password!")

        self.assertEqual(
            self.store.public_user("operator"),
            {
                "username": "operator",
                "role": "manager",
                "enabled": False,
            },
        )
        self.store.set_enabled("operator", True)
        self.assertIsNotNone(
            self.store.authenticate("operator", "Replacement-password!")
        )

    def test_admin_can_create_and_list_user_without_hash(self):
        with self.patches()[0], self.patches()[1], self.patches()[2]:
            headers = self.authenticated_client()
            created = self.client.post(
                "/api/users",
                json={
                    "username": "manager",
                    "password": "Manager-password!",
                    "role": "manager",
                },
                headers=headers,
            )
            listed = self.client.get("/api/users")

        self.assertEqual(created.status_code, 201)
        payload = listed.get_json()
        self.assertTrue(payload["success"])
        self.assertIn(
            {
                "username": "manager",
                "role": "manager",
                "enabled": True,
            },
            payload["users"],
        )
        self.assertNotIn("password_hash", str(payload))

    def test_manager_cannot_access_users_api_or_page(self):
        self.store.set_user("manager", "Manager-password!", "manager")
        with self.patches()[0], self.patches()[1], self.patches()[2]:
            self.authenticated_client("manager")
            api_response = self.client.get("/api/users")
            page_response = self.client.get("/users/")

        self.assertEqual(api_response.status_code, 403)
        self.assertEqual(page_response.status_code, 403)

    def test_last_enabled_admin_cannot_be_disabled_or_demoted(self):
        with self.patches()[0], self.patches()[1], self.patches()[2]:
            headers = self.authenticated_client()
            disabled = self.client.put(
                "/api/users/andrey/enabled",
                json={"enabled": False},
                headers=headers,
            )
            demoted = self.client.put(
                "/api/users/andrey/role",
                json={"role": "manager"},
                headers=headers,
            )

        self.assertEqual(disabled.status_code, 400)
        self.assertEqual(demoted.status_code, 400)
        self.assertEqual(
            self.store.public_user("andrey")["role"],
            "admin",
        )
        self.assertTrue(self.store.public_user("andrey")["enabled"])

    def test_admin_cannot_disable_current_account(self):
        self.store.set_user(
            "second-admin",
            "Second-admin-password!",
            "admin",
        )
        with self.patches()[0], self.patches()[1], self.patches()[2]:
            headers = self.authenticated_client()
            response = self.client.put(
                "/api/users/andrey/enabled",
                json={"enabled": False},
                headers=headers,
            )

        self.assertEqual(response.status_code, 400)
        self.assertIn("own account", response.get_json()["message"])

    def test_disabling_another_user_revokes_current_account_lookup(self):
        self.store.set_user("operator", "Operator-password!", "operator")
        with self.patches()[0], self.patches()[1], self.patches()[2]:
            headers = self.authenticated_client()
            response = self.client.put(
                "/api/users/operator/enabled",
                json={"enabled": False},
                headers=headers,
            )

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(self.store.current_account("operator"))


if __name__ == "__main__":
    unittest.main()
