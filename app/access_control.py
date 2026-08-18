"""Role-based access control and persistent user credentials."""

import json
import os
import tempfile
from pathlib import Path

from werkzeug.security import check_password_hash, generate_password_hash


ROLES = ("viewer", "operator", "manager", "admin")
ROLE_LEVEL = {role: level for level, role in enumerate(ROLES)}
CURRENT_USERS_SCHEMA_VERSION = 1


class UserStoreError(ValueError):
    """The user database is missing, invalid, or cannot be updated."""


def role_allows(actual_role, minimum_role):
    """Return whether actual_role includes minimum_role permissions."""
    return (
        actual_role in ROLE_LEVEL
        and minimum_role in ROLE_LEVEL
        and ROLE_LEVEL[actual_role] >= ROLE_LEVEL[minimum_role]
    )


class UserStore:
    """Atomic JSON user storage with password hashes only."""

    def __init__(self, path):
        self.path = Path(path)

    def load(self):
        if not self.path.exists():
            return {
                "schema_version": CURRENT_USERS_SCHEMA_VERSION,
                "users": {},
            }
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise UserStoreError("User database cannot be read") from error
        self.validate(payload)
        return payload

    @staticmethod
    def validate(payload):
        if not isinstance(payload, dict):
            raise UserStoreError("User database must be an object")
        if payload.get("schema_version") != CURRENT_USERS_SCHEMA_VERSION:
            raise UserStoreError("Unsupported user database schema")
        users = payload.get("users")
        if not isinstance(users, dict):
            raise UserStoreError("User database users must be an object")
        for username, account in users.items():
            if (
                not isinstance(username, str)
                or not username
                or len(username) > 64
                or not username.replace("-", "").replace("_", "").isalnum()
            ):
                raise UserStoreError("Invalid username")
            if not isinstance(account, dict):
                raise UserStoreError("Invalid user account")
            if account.get("role") not in ROLES:
                raise UserStoreError("Invalid user role")
            if not isinstance(account.get("password_hash"), str):
                raise UserStoreError("Invalid password hash")
            if not isinstance(account.get("enabled", True), bool):
                raise UserStoreError("Invalid enabled flag")

    def save(self, payload):
        self.validate(payload)
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{self.path.name}.",
            dir=self.path.parent,
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as target:
                json.dump(payload, target, ensure_ascii=False, indent=2)
                target.write("\n")
                target.flush()
                os.fsync(target.fileno())
            os.chmod(temporary_name, 0o600)
            os.replace(temporary_name, self.path)
        except Exception:
            try:
                os.unlink(temporary_name)
            except OSError:
                pass
            raise

    def set_user(self, username, password, role, enabled=True):
        username = username.strip()
        if role not in ROLES:
            raise UserStoreError("Invalid user role")
        if len(password) < 8:
            raise UserStoreError("Password must contain at least 8 characters")
        if not any(character.islower() for character in password):
            raise UserStoreError(
                "Password must contain at least one lowercase letter"
            )
        if not any(character.isupper() for character in password):
            raise UserStoreError(
                "Password must contain at least one uppercase letter"
            )
        if not any(
            not character.isalnum() and not character.isspace()
            for character in password
        ):
            raise UserStoreError(
                "Password must contain at least one special character"
            )
        payload = self.load()
        payload["users"][username] = {
            "password_hash": generate_password_hash(password),
            "role": role,
            "enabled": bool(enabled),
        }
        self.save(payload)

    def disable_user(self, username):
        payload = self.load()
        account = payload["users"].get(username)
        if account is None:
            raise UserStoreError("User not found")
        account["enabled"] = False
        self.save(payload)

    def authenticate(self, username, password):
        account = self.load()["users"].get(username)
        if (
            not account
            or not account.get("enabled", True)
            or not check_password_hash(account["password_hash"], password)
        ):
            return None
        return {
            "username": username,
            "role": account["role"],
        }

    def current_account(self, username):
        account = self.load()["users"].get(username)
        if not account or not account.get("enabled", True):
            return None
        return {
            "username": username,
            "role": account["role"],
        }

    def public_users(self):
        payload = self.load()
        return [
            {
                "username": username,
                "role": account["role"],
                "enabled": account.get("enabled", True),
            }
            for username, account in sorted(payload["users"].items())
        ]
