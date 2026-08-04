from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tools.build_clean_release import ReleaseBuildError, build_release, validate_release


class BuildCleanReleaseTests(unittest.TestCase):
    def test_allowlist_copy_excludes_private_and_generated_content(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source"
            output = root / "release"
            (source / "tools").mkdir(parents=True)
            (source / "CybersecurityLearningPlatform" / "backend").mkdir(parents=True)
            (source / "CybersecurityLearningPlatform" / "frontend" / "src").mkdir(parents=True)
            (source / "CybersecurityLearningPlatform" / "frontend" / "node_modules").mkdir(parents=True)
            (source / "README.md").write_text("public", encoding="utf-8")
            (source / "DATA_MANIFEST.md").write_text("public", encoding="utf-8")
            (source / "LICENSE").write_text("public", encoding="utf-8")
            (source / "CybersecurityLearningPlatform" / "backend" / "app.py").write_text(
                "print('ok')", encoding="utf-8"
            )
            (source / "CybersecurityLearningPlatform" / "backend" / ".env").write_text(
                "OPENAI_API_KEY=secret", encoding="utf-8"
            )
            (source / "CybersecurityLearningPlatform" / "frontend" / "src" / "App.jsx").write_text(
                "export default function App() {}", encoding="utf-8"
            )
            (source / "CybersecurityLearningPlatform" / "frontend" / "node_modules" / "x.js").write_text(
                "generated", encoding="utf-8"
            )

            result = build_release(source, output, max_file_bytes=1024 * 1024)

            self.assertTrue((output / "README.md").is_file())
            self.assertTrue((output / "CybersecurityLearningPlatform" / "backend" / "app.py").is_file())
            self.assertFalse((output / "CybersecurityLearningPlatform" / "backend" / ".env").exists())
            self.assertFalse((output / "CybersecurityLearningPlatform" / "frontend" / "node_modules").exists())
            self.assertGreater(result.copied_files, 0)
            self.assertEqual([], validate_release(output))

    def test_validation_rejects_forbidden_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            release = Path(temp_dir) / "release"
            forbidden = release / "CybersecurityLearningPlatform" / "backend" / "logs" / "request.log"
            forbidden.parent.mkdir(parents=True)
            forbidden.write_text("private", encoding="utf-8")

            errors = validate_release(release)

            self.assertTrue(any("FORBIDDEN_PATH" in error for error in errors))

    def test_build_fails_for_unapproved_oversized_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source"
            output = root / "release"
            (source / "CybersecurityLearningPlatform" / "backend").mkdir(parents=True)
            (source / "CybersecurityLearningPlatform" / "backend" / "app.py").write_bytes(b"x" * 32)

            with self.assertRaises(ReleaseBuildError):
                build_release(source, output, max_file_bytes=16)

    def test_migration_output_directory_and_backup_file_are_excluded(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source"
            output = root / "release"
            phase2 = source / "CybersecurityLearningPlatform" / "backend" / "exp_2" / "phase2"
            migration = phase2 / "_migration_output" / "run"
            migration.mkdir(parents=True)
            (phase2 / "migrate_analysis_properties.py").write_text("pass\n", encoding="utf-8")
            (migration / "analysis_properties_before.json").write_text("{}", encoding="utf-8")
            (migration / "migration_manifest.json").write_text("{}", encoding="utf-8")

            build_release(source, output)

            released_phase2 = output / "CybersecurityLearningPlatform" / "backend" / "exp_2" / "phase2"
            self.assertTrue((released_phase2 / "migrate_analysis_properties.py").is_file())
            self.assertFalse((released_phase2 / "_migration_output").exists())

    def test_relocated_analysis_backup_file_is_excluded(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source"
            output = root / "release"
            phase2 = source / "CybersecurityLearningPlatform" / "backend" / "exp_2" / "phase2"
            phase2.mkdir(parents=True)
            (phase2 / "analysis_properties_before.json").write_text("{}", encoding="utf-8")

            build_release(source, output)

            self.assertFalse(
                (output / "CybersecurityLearningPlatform" / "backend" / "exp_2" / "phase2" / "analysis_properties_before.json").exists()
            )

    def test_compound_backup_directory_and_pre_kg_snapshot_are_excluded(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source"
            output = root / "release"
            matchgpt = source / "CybersecurityLearningPlatform" / "backend" / "exp_1" / "MatchGPT"
            backups = matchgpt / "phase1_backups"
            backups.mkdir(parents=True)
            (matchgpt / "neo4j_backup_restore.py").write_text("pass\n", encoding="utf-8")
            (matchgpt / "pre_b22c_03schema_kg_20260711.json").write_text("{}", encoding="utf-8")
            (backups / "final_platform_kg.json").write_text("{}", encoding="utf-8")

            build_release(source, output)

            released_matchgpt = output / "CybersecurityLearningPlatform" / "backend" / "exp_1" / "MatchGPT"
            self.assertTrue((released_matchgpt / "neo4j_backup_restore.py").is_file())
            self.assertFalse((released_matchgpt / "pre_b22c_03schema_kg_20260711.json").exists())
            self.assertFalse((released_matchgpt / "phase1_backups").exists())

    def test_compound_backup_directory_is_excluded(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source"
            output = root / "release"
            backup = (
                source
                / "CybersecurityLearningPlatform"
                / "backend"
                / "exp_1"
                / "MatchGPT"
                / "phase1_backups"
                / "final_kg.json"
            )
            backup.parent.mkdir(parents=True)
            backup.write_text("{}", encoding="utf-8")

            build_release(source, output)

            self.assertFalse(
                (
                    output
                    / "CybersecurityLearningPlatform"
                    / "backend"
                    / "exp_1"
                    / "MatchGPT"
                    / "phase1_backups"
                ).exists()
            )

    def test_pre_b22c_graph_snapshot_is_excluded(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source"
            output = root / "release"
            snapshot = (
                source
                / "CybersecurityLearningPlatform"
                / "backend"
                / "exp_1"
                / "MatchGPT"
                / "pre_b22c_03schema_kg_20260711.json"
            )
            snapshot.parent.mkdir(parents=True)
            snapshot.write_text("{}", encoding="utf-8")

            build_release(source, output)

            self.assertFalse(
                (
                    output
                    / "CybersecurityLearningPlatform"
                    / "backend"
                    / "exp_1"
                    / "MatchGPT"
                    / "pre_b22c_03schema_kg_20260711.json"
                ).exists()
            )


if __name__ == "__main__":
    unittest.main()
