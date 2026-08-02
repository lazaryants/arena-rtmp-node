import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
INSTALLER = PROJECT_ROOT / "scripts/install.sh"
UPDATER = PROJECT_ROOT / "scripts/update.sh"


class UpdateScriptTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.target = self.root / "node"
        self.backups = self.root / "backups"
        install = subprocess.run(
            [
                str(INSTALLER),
                "install",
                "--target",
                str(self.target),
                "--skip-python-deps",
                "--skip-system-check",
                "--skip-service-user",
            ],
            capture_output=True,
            text=True,
        )
        self.assertEqual(install.returncode, 0, install.stderr)

        installed_venv = self.target / ".venv"
        subprocess.run(
            ["find", str(installed_venv), "-depth", "-delete"],
            check=True,
        )
        installed_venv.symlink_to(Path(sys.prefix), target_is_directory=True)

        self.legacy = {
            "fields": {
                "3": {
                    "name": "Place 3",
                    "enabled": True,
                    "stream_key": "stream3",
                    "key": "publish-secret",
                    "restream_url": "rtmps://destination.example/live/private",
                },
            },
        }
        self.config = self.target / "state/restream-config.json"
        self.config.write_text(json.dumps(self.legacy), encoding="utf-8")
        self.node_env = self.target / "config/node.env"
        self.node_env.write_text(
            "CRICKET_RTMP_PUBLIC_HOST=private.example\n",
            encoding="utf-8",
        )

    def tearDown(self):
        self.temporary_directory.cleanup()

    def update_command(self, *extra):
        return [
            str(UPDATER),
            "apply",
            "--confirm",
            "UPDATE",
            "--target",
            str(self.target),
            "--backup-root",
            str(self.backups),
            "--skip-services",
            "--skip-ownership",
            *extra,
        ]

    def test_check_is_read_only_and_apply_preserves_private_config(self):
        original = self.config.read_bytes()
        check = subprocess.run(
            [
                str(UPDATER),
                "check",
                "--target",
                str(self.target),
                "--backup-root",
                str(self.backups),
                "--skip-services",
                "--skip-ownership",
            ],
            capture_output=True,
            text=True,
        )
        self.assertEqual(check.returncode, 0, check.stderr)
        self.assertEqual(self.config.read_bytes(), original)

        apply = subprocess.run(
            self.update_command(),
            capture_output=True,
            text=True,
        )
        self.assertEqual(apply.returncode, 0, apply.stderr)
        migrated = json.loads(self.config.read_text(encoding="utf-8"))
        self.assertEqual(migrated["schema_version"], 1)
        self.assertEqual(migrated["fields"]["3"]["key"], "publish-secret")
        self.assertEqual(
            self.node_env.read_text(encoding="utf-8"),
            "CRICKET_RTMP_PUBLIC_HOST=private.example\n",
        )
        self.assertNotIn("publish-secret", apply.stdout + apply.stderr)
        backup_directories = list(self.backups.glob("update-*"))
        self.assertEqual(len(backup_directories), 1)
        self.assertEqual(backup_directories[0].stat().st_mode & 0o777, 0o700)

    def test_apply_requires_literal_confirmation_before_changes(self):
        original = self.config.read_bytes()
        result = subprocess.run(
            [
                str(UPDATER),
                "apply",
                "--target",
                str(self.target),
                "--backup-root",
                str(self.backups),
                "--skip-services",
                "--skip-ownership",
            ],
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("--confirm UPDATE", result.stderr)
        self.assertEqual(self.config.read_bytes(), original)
        self.assertFalse(self.backups.exists())

    def test_failed_health_check_restores_code_config_and_units(self):
        systemd_dir = self.root / "systemd"
        fake_bin = self.root / "bin"
        systemd_dir.mkdir()
        fake_bin.mkdir()
        for unit in ("restream-manager.service", "rtmp-auth.service"):
            (systemd_dir / unit).write_text(f"old {unit}\n", encoding="utf-8")

        version_file = self.target / "app/version.py"
        version_file.write_text(
            version_file.read_text(encoding="utf-8")
            + "\nOLD_ROLLBACK_MARKER = True\n",
            encoding="utf-8",
        )
        (fake_bin / "systemctl").write_text(
            "#!/usr/bin/env bash\n"
            "if [[ \"$1\" == is-active && "
            "( \"$3\" == restream-manager.service || "
            "\"$3\" == rtmp-auth.service ) ]]; then exit 0; fi\n"
            "if [[ \"$1\" == is-active ]]; then exit 3; fi\n"
            "exit 0\n",
            encoding="utf-8",
        )
        (fake_bin / "curl").write_text("#!/usr/bin/env bash\nexit 1\n", encoding="utf-8")
        (fake_bin / "sleep").write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
        for executable in fake_bin.iterdir():
            executable.chmod(0o700)

        environment = os.environ.copy()
        environment["PATH"] = f"{fake_bin}:{environment['PATH']}"
        result = subprocess.run(
            [
                str(UPDATER),
                "apply",
                "--confirm",
                "UPDATE",
                "--target",
                str(self.target),
                "--backup-root",
                str(self.backups),
                "--systemd-dir",
                str(systemd_dir),
                "--skip-ownership",
            ],
            capture_output=True,
            text=True,
            env=environment,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Rollback completed", result.stderr)
        self.assertIn("OLD_ROLLBACK_MARKER", version_file.read_text(encoding="utf-8"))
        self.assertEqual(json.loads(self.config.read_text(encoding="utf-8")), self.legacy)
        self.assertFalse((systemd_dir / "cricket-restream-supervisor.service").exists())
        self.assertEqual(
            (systemd_dir / "restream-manager.service").read_text(encoding="utf-8"),
            "old restream-manager.service\n",
        )


if __name__ == "__main__":
    unittest.main()
