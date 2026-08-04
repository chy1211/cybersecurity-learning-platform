from __future__ import annotations

import tempfile
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

from tools.check_release_ready import ReleaseChecker


class ReleaseCheckerTests(unittest.TestCase):
    def _minimal_release(self, root: Path) -> None:
        required_files = {
            "README.md": "public",
            "DATA_MANIFEST.md": "public",
            "LICENSE": "license",
            ".gitignore": (
                ".env\nnode_modules/\n"
                "platform/backend/ETL_module/Chunks/\n"
                "platform/graphify-out/\n"
                "platform/backend/exp_1/MatchGPT/phase1_backups/\n"
                "platform/backend/exp_3/cache/\n"
                "platform/backend/exp_2/phase2/_migration_output/\n"
            ),
            "docs/prompts/README.md": "public",
            "ontology/schema.csv": "a,b\n",
            "platform/backend/.env.example": "OPENAI_API_KEY=<your_api_key>\nNEO4J_PASSWORD=<your_password>\n",
            "platform/backend/ETL_module/Validated/item.json": "{}",
            "platform/backend/exp_1/main.py": "pass\n",
            "platform/backend/exp_2/main.py": "pass\n",
            "platform/backend/exp_3/main.py": "pass\n",
            "platform/frontend/src/App.jsx": "export default function App() {}",
        }
        for relative, content in required_files.items():
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")

    def test_clean_minimal_release_passes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "release"
            self._minimal_release(root)

            result = ReleaseChecker(root).run(check_git=False)

            self.assertEqual([], result.errors)

    def test_forbidden_directory_and_secret_are_errors(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "release"
            self._minimal_release(root)
            secret = root / "platform" / "backend" / "logs" / "request.log"
            secret.parent.mkdir(parents=True)
            secret.write_text("OPENAI_API_KEY=sk-" + "x" * 32, encoding="utf-8")

            result = ReleaseChecker(root).run(check_git=False)

            self.assertTrue(any("FORBIDDEN_PATH" in error for error in result.errors))
            self.assertTrue(any("SECRET_LIKE_VALUE" in error for error in result.errors))

    def test_migration_output_and_backup_are_hard_failures(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "release"
            self._minimal_release(root)
            backup = (
                root
                / "platform"
                / "backend"
                / "exp_2"
                / "phase2"
                / "_migration_output"
                / "run"
                / "analysis_properties_before.json"
            )
            backup.parent.mkdir(parents=True)
            backup.write_text("{}", encoding="utf-8")

            result = ReleaseChecker(root).run(check_git=False)

            self.assertTrue(any("FORBIDDEN_PATH" in error for error in result.errors))
            self.assertTrue(any("_migration_output" in error for error in result.errors))

    def test_relocated_analysis_backup_is_a_hard_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "release"
            self._minimal_release(root)
            backup = root / "platform" / "backend" / "exp_2" / "analysis_properties_before.json"
            backup.parent.mkdir(parents=True, exist_ok=True)
            backup.write_text("{}", encoding="utf-8")

            result = ReleaseChecker(root).run(check_git=False)

            self.assertTrue(any("analysis_properties_before.json" in error for error in result.errors))

    def test_large_text_is_not_loaded_for_general_text_checks(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "release"
            self._minimal_release(root)
            large = root / "platform" / "backend" / "exp_3" / "large.json"
            large.write_text("{\"payload\":\"" + "x" * (2 * 1024 * 1024) + "\"}", encoding="utf-8")

            result = ReleaseChecker(root).run(check_git=False)

            self.assertTrue(any("TEXT_SCAN_SKIPPED_SIZE" in warning for warning in result.warnings))

    def test_direct_execution_does_not_create_forbidden_bytecode(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "release"
            self._minimal_release(root)
            source_tools = Path(__file__).resolve().parents[1]
            target_tools = root / "tools"
            target_tools.mkdir()
            shutil.copy2(source_tools / "build_clean_release.py", target_tools)
            shutil.copy2(source_tools / "check_release_ready.py", target_tools)

            result = subprocess.run(
                [sys.executable, str(target_tools / "check_release_ready.py")],
                cwd=root,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )

            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertFalse((target_tools / "__pycache__").exists())


if __name__ == "__main__":
    unittest.main()
