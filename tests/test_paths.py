from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from whisperflow_local.paths import APP_SUPPORT_NAME, BUNDLE_ID, AppPaths


class AppPathsTests(unittest.TestCase):
    def test_paths_follow_macos_conventions(self) -> None:
        paths = AppPaths.discover(Path("/Users/example"))
        self.assertEqual(
            paths.support,
            Path("/Users/example/Library/Application Support") / APP_SUPPORT_NAME,
        )
        self.assertEqual(
            paths.cache, Path("/Users/example/Library/Caches") / BUNDLE_ID
        )
        self.assertEqual(
            paths.logs, Path("/Users/example/Library/Logs") / APP_SUPPORT_NAME
        )

    def test_no_path_depends_on_repository_working_directory(self) -> None:
        paths = AppPaths.discover(Path("/Users/example"))
        for value in (
            paths.settings, paths.models, paths.recovery, paths.metrics
        ):
            self.assertNotIn("Developer/whisperflow-local", str(value))

    def test_ensure_creates_private_directories(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            paths = AppPaths.discover(Path(temp)).ensure()
            self.assertTrue(paths.support.is_dir())
            self.assertTrue(paths.cache.is_dir())
            self.assertTrue(paths.logs.is_dir())
            self.assertTrue(paths.models.is_dir())
            self.assertTrue(paths.recovery.is_dir())

    def test_bundle_identifier_is_stable_and_reverse_dns(self) -> None:
        self.assertEqual(BUNDLE_ID, "com.shawnvanbrunt.whisperflow-local")
        self.assertGreaterEqual(BUNDLE_ID.count("."), 2)


if __name__ == "__main__":
    unittest.main()
