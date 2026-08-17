import shutil
import subprocess
import unittest
from pathlib import Path
from unittest import mock

from scripts.audit_systemd import AuditError, audit_units, unit_exposure


PROJECT_ROOT = Path(__file__).resolve().parent.parent


class SystemdSecurityAuditTests(unittest.TestCase):
    @mock.patch("scripts.audit_systemd.subprocess.run")
    def test_parses_exposure_without_accepting_missing_score(self, run):
        run.return_value = subprocess.CompletedProcess(
            [],
            0,
            "Overall exposure level for example.service: 2.8 OK\n",
            "",
        )
        self.assertEqual(unit_exposure(Path("example.service")), 2.8)

        run.return_value = subprocess.CompletedProcess([], 0, "no score", "")
        with self.assertRaisesRegex(AuditError, "score missing"):
            unit_exposure(Path("example.service"))

    def test_repository_units_meet_security_threshold(self):
        if shutil.which("systemd-analyze") is None:
            self.skipTest("systemd-analyze is unavailable")
        results = audit_units(PROJECT_ROOT / "systemd", 3.0)
        self.assertEqual(set(results), {
            "arena-restream-supervisor.service",
            "arena-rtmp-auth.service",
            "arena-restream-manager.service",
        })
        self.assertTrue(all(score <= 3.0 for score in results.values()))


if __name__ == "__main__":
    unittest.main()
