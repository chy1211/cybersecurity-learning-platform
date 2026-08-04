import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve()
BACKEND_DIR = SCRIPT_PATH.parents[2]
ETL_01 = BACKEND_DIR / "ETL_module" / "01_chunk_data.py"
QUESTIONS_SCRIPT = SCRIPT_PATH.parent / "questions_to_corpus.py"


def load_etl_01():
    spec = importlib.util.spec_from_file_location("etl_01_chunk_data", ETL_01)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class NoTokenize:
    def encode(self, text):
        raise AssertionError("question corpus chunks must not be re-tokenized")

    def decode(self, tokens, skip_special_tokens=True):
        raise AssertionError("question corpus chunks must not be re-tokenized")


class RerunPrepTests(unittest.TestCase):
    def test_question_corpus_schema_is_forwarded_as_one_chunk_per_question(self):
        etl = load_etl_01()
        with tempfile.TemporaryDirectory() as td:
            corpus_path = Path(td) / "questions_corpus.json"
            corpus = {
                "corpus_type": "question_chunks_v1",
                "chunks": [
                    {
                        "source_id": "question_Q001",
                        "source_file": "questions_corpus.json",
                        "text": "Question: X\nAnswer: A",
                    },
                    {
                        "source_id": "question_Q002",
                        "source_file": "questions_corpus.json",
                        "text": "Question: Y\nAnswer: B",
                    },
                ],
            }
            corpus_path.write_text(
                json.dumps(corpus, ensure_ascii=False), encoding="utf-8"
            )

            chunks = etl.chunk_file(str(corpus_path), NoTokenize())

        self.assertEqual([c["source_id"] for c in chunks], ["question_Q001", "question_Q002"])
        self.assertEqual([c["source_file"] for c in chunks], ["questions_corpus.json", "questions_corpus.json"])
        self.assertEqual(chunks[0]["text"], "Question: X\nAnswer: A")

    def test_manifest_and_multiple_source_dirs_resolve_pdf_and_json_inputs(self):
        etl = load_etl_01()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            dir_a = root / "a"
            dir_b = root / "b"
            dir_a.mkdir()
            dir_b.mkdir()
            pdf = dir_a / "one.pdf"
            json_file = dir_b / "two.json"
            ignored = dir_b / "three.txt"
            pdf.write_bytes(b"%PDF-1.4\n")
            json_file.write_text("{}", encoding="utf-8")
            ignored.write_text("ignore", encoding="utf-8")
            manifest = root / "manifest.txt"
            manifest.write_text(str(json_file) + "\n" + str(ignored) + "\n", encoding="utf-8")

            files = etl.resolve_input_files(
                source_dirs=[str(dir_a) + "," + str(dir_b)],
                manifest_path=str(manifest),
                script_dir=str(root),
            )

        self.assertEqual([Path(p).name for p in files], ["one.pdf", "two.json", "two.json"])

    def test_questions_to_corpus_cli_writes_question_chunk_schema(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            input_path = root / "questions.json"
            output_path = root / "questions_corpus.json"
            input_path.write_text(
                json.dumps(
                    [
                        {
                            "qid": "Q001",
                            "stem": "Which control protects data?",
                            "options": {"A": "Encryption", "B": "Guessing"},
                            "answer": "A",
                            "is_single": True,
                        },
                        {
                            "id": "Q002",
                            "stem": "Pick defenses.",
                            "options": ["Firewall", "Malware"],
                            "answer": ["A"],
                        },
                    ],
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(QUESTIONS_SCRIPT),
                    "--input",
                    str(input_path),
                    "--output",
                    str(output_path),
                    "--limit",
                    "2",
                ],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            data = json.loads(output_path.read_text(encoding="utf-8"))

        self.assertEqual(data["corpus_type"], "question_chunks_v1")
        self.assertEqual([c["source_id"] for c in data["chunks"]], ["question_Q001", "question_Q002"])
        self.assertIn("Correct Answer: A", data["chunks"][0]["text"])
        self.assertIn("A. Encryption", data["chunks"][0]["text"])


if __name__ == "__main__":
    unittest.main()
