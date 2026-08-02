import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent


class SystemdUnitTests(unittest.TestCase):
    def read_unit(self, name):
        return (PROJECT_ROOT / "systemd" / name).read_text(encoding="utf-8")

    def assert_common_sandbox(self, content):
        for directive in (
            "User=cricket-rtmp",
            "Group=cricket-rtmp",
            "NoNewPrivileges=true",
            "PrivateDevices=true",
            "PrivateTmp=true",
            "PrivateMounts=true",
            "ProtectHostname=true",
            "ProtectProc=invisible",
            "ProtectSystem=strict",
            "ProtectHome=true",
            "RestrictNamespaces=true",
            "RestrictRealtime=true",
            "RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6",
            "SystemCallArchitectures=native",
            "MemoryDenyWriteExecute=true",
            "RemoveIPC=true",
            "CapabilityBoundingSet=",
            "AmbientCapabilities=",
        ):
            self.assertIn(directive, content)
        self.assertNotIn("User=root", content)

    def test_manager_has_sandbox_and_only_expected_writable_paths(self):
        content = self.read_unit("restream-manager.service")
        self.assert_common_sandbox(content)
        writable = [
            line
            for line in content.splitlines()
            if line.startswith("ReadWritePaths=")
        ]
        self.assertEqual(writable, [
            "ReadWritePaths=/opt/cricket-rtmp-node/state",
        ])
        self.assertNotIn("ReadWritePaths=/opt/cricket-rtmp-node/config", content)
        self.assertIn("Wants=cricket-restream-supervisor.service", content)

    def test_supervisor_owns_only_logs_and_runtime_state(self):
        content = self.read_unit("cricket-restream-supervisor.service")
        self.assert_common_sandbox(content)
        writable = [
            line
            for line in content.splitlines()
            if line.startswith("ReadWritePaths=")
        ]
        self.assertEqual(writable, [
            "ReadWritePaths=/opt/cricket-rtmp-node/logs",
            "ReadWritePaths=/opt/cricket-rtmp-node/run",
        ])
        self.assertNotIn("ReadWritePaths=/opt/cricket-rtmp-node/state", content)

    def test_auth_has_sandbox_and_no_writable_path_exception(self):
        content = self.read_unit("rtmp-auth.service")
        self.assert_common_sandbox(content)
        self.assertNotIn("ReadWritePaths=", content)


if __name__ == "__main__":
    unittest.main()
