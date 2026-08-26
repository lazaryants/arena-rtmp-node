import base64
import hashlib
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlparse


PROJECT_ROOT = Path(__file__).resolve().parent.parent
RENDERER = (
    PROJECT_ROOT
    / "scripts/render_mediamtx_compat.py"
)
MAIN_EXAMPLE = (
    PROJECT_ROOT
    / "mediamtx/mediamtx.yml.example"
)


class MediaMtxCompatibilityRendererTests(
    unittest.TestCase
):
    def setUp(self):
        self.temporary_directory = (
            tempfile.TemporaryDirectory()
        )
        self.root = Path(
            self.temporary_directory.name
        )
        self.output = self.root / "private"

    def tearDown(self):
        self.temporary_directory.cleanup()

    def render(self):
        return subprocess.run(
            [
                sys.executable,
                str(RENDERER),
                "--main-config",
                str(MAIN_EXAMPLE),
                "--output-dir",
                str(self.output),
            ],
            capture_output=True,
            text=True,
        )

    def test_renders_matching_private_credentials(self):
        result = self.render()
        self.assertEqual(
            result.returncode,
            0,
            result.stderr,
        )

        main_path = self.output / "mediamtx.yml"
        ingress_path = self.output / "ingress.yml"
        main = main_path.read_text(encoding="utf-8")
        ingress = ingress_path.read_text(
            encoding="utf-8"
        )

        hash_match = re.search(
            r"pass: 'sha256:([A-Za-z0-9+/=]+)'",
            main,
        )
        destination_match = re.search(
            r"dest: "
            r"'(rtmp://127\.0\.0\.1:19350/"
            r"place1\?[^']+)'",
            ingress,
        )

        self.assertIsNotNone(hash_match)
        self.assertIsNotNone(destination_match)

        query = parse_qs(
            urlparse(
                destination_match.group(1)
            ).query
        )
        password = query["pass"][0]

        expected_hash = base64.b64encode(
            hashlib.sha256(
                password.encode("utf-8")
            ).digest()
        ).decode("ascii")

        self.assertEqual(
            hash_match.group(1),
            expected_hash,
        )
        self.assertNotIn(password, main)
        self.assertNotIn(
            password,
            result.stdout + result.stderr,
        )
        self.assertEqual(
            ingress.count(
                '  "place'
            ),
            16,
        )
        self.assertEqual(
            ingress.count(
                "    forward:\n"
            ),
            16,
        )
        self.assertEqual(
            main_path.stat().st_mode & 0o777,
            0o600,
        )
        self.assertEqual(
            ingress_path.stat().st_mode & 0o777,
            0o600,
        )
        self.assertEqual(
            self.output.stat().st_mode & 0o777,
            0o700,
        )

    def test_refuses_to_overwrite_private_outputs(self):
        first = self.render()
        self.assertEqual(
            first.returncode,
            0,
            first.stderr,
        )

        before = {
            path.name: path.read_bytes()
            for path in self.output.iterdir()
        }

        second = self.render()

        self.assertNotEqual(second.returncode, 0)
        self.assertIn(
            "output files already exist",
            second.stderr,
        )

        after = {
            path.name: path.read_bytes()
            for path in self.output.iterdir()
        }
        self.assertEqual(after, before)


if __name__ == "__main__":
    unittest.main()
