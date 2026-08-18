import tempfile
import unittest
from pathlib import Path

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

    def tearDown(self):
        self.temporary_directory.cleanup()

    def test_role_hierarchy(self):
        self.assertTrue(role_allows("admin", "viewer"))
        self.assertTrue(role_allows("manager", "operator"))
        self.assertTrue(role_allows("operator", "operator"))
        self.assertFalse(role_allows("operator", "manager"))
        self.assertFalse(role_allows("viewer", "operator"))
        self.assertFalse(role_allows("unknown", "viewer"))

    def test_create_authenticate_and_disable_user(self):
        self.store.set_user("andrey", "long-test-password", "admin")
        self.assertEqual(
            self.store.authenticate("andrey", "long-test-password"),
            {"username": "andrey", "role": "admin"},
        )
        self.assertIsNone(
            self.store.authenticate("andrey", "wrong-password"),
        )
        self.store.disable_user("andrey")
        self.assertIsNone(
            self.store.authenticate("andrey", "long-test-password"),
        )

    def test_password_hash_is_not_exposed(self):
        self.store.set_user("manager", "long-test-password", "manager")
        users = self.store.public_users()
        self.assertEqual(
            users,
            [{"username": "manager", "role": "manager", "enabled": True}],
        )
        self.assertNotIn("long-test-password", self.path.read_text())

    def test_short_password_is_rejected_without_file(self):
        with self.assertRaises(UserStoreError):
            self.store.set_user("viewer", "short", "viewer")
        self.assertFalse(self.path.exists())

    def test_all_supported_roles_can_be_stored(self):
        for role in ROLES:
            self.store.set_user(role, f"password-for-{role}", role)
        self.assertEqual(len(self.store.public_users()), len(ROLES))


if __name__ == "__main__":
    unittest.main()
