import subprocess
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
INSTALLER = PROJECT_ROOT / "scripts/install.sh"


class InstallerTests(unittest.TestCase):
    def test_restrictive_caller_umask_does_not_block_service_reads(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "node"
            result = subprocess.run(
                [
                    "bash",
                    "-c",
                    'umask 077; exec "$@"',
                    "installer-test",
                    str(INSTALLER),
                    "install",
                    "--target",
                    str(target),
                    "--skip-python-deps",
                    "--skip-system-check",
                    "--skip-service-user",
                ],
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)

            expected_modes = {
                target: 0o755,
                target / "app": 0o755,
                target / "app/restream_manager.py": 0o644,
                target / "logrotate": 0o755,
                target / "logrotate/arena-rtmp-node": 0o644,
                target / "mediamtx": 0o755,
                target / "mediamtx/mediamtx.yml.example": 0o644,
                target / "systemd/mediamtx.service": 0o644,
                target / "web": 0o755,
                target / "scripts": 0o755,
                target / "scripts/install.sh": 0o755,
                target / "scripts/__init__.py": 0o644,
                target / ".venv": 0o755,
                target / ".venv/bin": 0o755,
                target / ".venv/bin/python3": 0o755,
                target / "README.md": 0o644,
                target / "config/gunicorn.conf.py": 0o644,
                target / "config/node.env.example": 0o644,
                target / "config/nginx-render.example.json": 0o644,
                target / "config/restream-config.example.json": 0o644,
                target / "config/node.env": 0o600,
                target / "state/restream-config.json": 0o600,
            }
            for path, expected_mode in expected_modes.items():
                with self.subTest(path=path):
                    self.assertEqual(path.stat().st_mode & 0o777, expected_mode)

            for directory in (
                "app",
                "scripts",
                "tests",
            ):
                self.assertEqual(
                    list((target / directory).rglob("__pycache__")),
                    [],
                )
                self.assertEqual(list((target / directory).rglob("*.pyc")), [])


if __name__ == "__main__":
    unittest.main()
