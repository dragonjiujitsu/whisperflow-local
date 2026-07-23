import plistlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from whisperflow_local import autostart
from whisperflow_local.paths import BUNDLE_ID


class AutostartTests(unittest.TestCase):
    def test_development_login_item_has_no_repository_working_directory(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(
            autostart, "_path", return_value=Path(temp) / "agent.plist"
        ):
            path = Path(autostart.install())
            payload = plistlib.loads(path.read_bytes())
            mode = path.stat().st_mode & 0o777
        self.assertEqual(payload["Label"], BUNDLE_ID)
        self.assertNotIn("WorkingDirectory", payload)
        self.assertEqual(payload["ProgramArguments"][1:], ["-m", "whisperflow_local", "run"])
        self.assertEqual(mode, 0o600)


if __name__ == "__main__":
    unittest.main()
