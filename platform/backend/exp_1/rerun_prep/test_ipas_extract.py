import unittest

import ipas_extract


class ParseRecordsFromLinesTests(unittest.TestCase):
    def test_parses_inline_answer_question(self):
        lines = [
            "A 1. First line of stem?",
            "continued stem",
            "(A) option a",
            "(B) option b",
            "(C) option c",
            "(D) option d",
        ]

        records, warnings = ipas_extract.parse_records_from_lines(
            lines, subject_key="mgmt", year=108, section_index=1, start_serial=1
        )

        self.assertEqual([], warnings)
        self.assertEqual(1, len(records))
        item = records[0]
        self.assertEqual("IPAS-108-MGT-001", item["id"])
        self.assertEqual("A", item["answer"])
        self.assertEqual("First line of stem? continued stem", item["stem"])
        self.assertEqual(
            {"A": "option a", "B": "option b", "C": "option c", "D": "option d"},
            item["options"],
        )

    def test_parses_standalone_answer_before_options(self):
        lines = [
            "1. Stem starts here",
            "B",
            "stem continues",
            "(A) option a",
            "(B) option b",
            "(C) option c",
            "(D) option d",
        ]

        records, warnings = ipas_extract.parse_records_from_lines(
            lines, subject_key="tech", year=111, section_index=1, start_serial=1
        )

        self.assertEqual([], warnings)
        self.assertEqual(1, len(records))
        item = records[0]
        self.assertEqual("IPAS-111-TEC-001", item["id"])
        self.assertEqual("B", item["answer"])
        self.assertEqual("Stem starts here stem continues", item["stem"])
        self.assertEqual("option b", item["options"]["B"])

    def test_reports_incomplete_question(self):
        lines = [
            "C 1. Stem",
            "(A) option a",
            "(B) option b",
        ]

        records, warnings = ipas_extract.parse_records_from_lines(
            lines, subject_key="mgmt", year=None, section_index=1, start_serial=1
        )

        self.assertEqual([], records)
        self.assertEqual(1, len(warnings))
        self.assertIn("incomplete", warnings[0])

    def test_parses_options_with_prefixed_answer_column_artifact(self):
        lines = [
            "A 1. Stem",
            "B (A) option a",
            "C (B) option b",
            "C (C) option c",
            "C (D) option d",
        ]

        records, warnings = ipas_extract.parse_records_from_lines(
            lines, subject_key="tech", year=111, section_index=1, start_serial=1
        )

        self.assertEqual([], warnings)
        self.assertEqual(1, len(records))
        self.assertEqual("option a", records[0]["options"]["A"])
        self.assertEqual("option d", records[0]["options"]["D"])

    def test_parses_options_with_cjk_grading_note_prefix(self):
        lines = [
            "D 1. Stem",
            "皆 (A) option a",
            "給 (B) option b",
            "分 (C) option c",
            "(D) option d",
        ]

        records, warnings = ipas_extract.parse_records_from_lines(
            lines, subject_key="mgmt", year=109, section_index=1, start_serial=1
        )

        self.assertEqual([], warnings)
        self.assertEqual(1, len(records))
        self.assertEqual("option a", records[0]["options"]["A"])
        self.assertEqual("option c", records[0]["options"]["C"])

    def test_does_not_treat_decimal_version_line_as_question_start(self):
        lines = [
            "A 1. Stem",
            "(A) option a",
            "3.5.30729) continuation text",
            "(B) option b",
            "(C) option c",
            "(D) option d",
        ]

        records, warnings = ipas_extract.parse_records_from_lines(
            lines, subject_key="tech", year=112, section_index=1, start_serial=1
        )

        self.assertEqual([], warnings)
        self.assertEqual(1, len(records))
        self.assertIn("3.5.30729", records[0]["options"]["A"])

    def test_reports_grading_note_prefixed_question_without_answer(self):
        lines = [
            "皆 1. Stem",
            "給 continuation",
            "分",
            "(A) option a",
            "(B) option b",
            "(C) option c",
            "(D) option d",
        ]

        records, warnings = ipas_extract.parse_records_from_lines(
            lines, subject_key="tech", year=112, section_index=1, start_serial=1
        )

        self.assertEqual([], records)
        self.assertEqual(1, len(warnings))
        self.assertIn("bad_answer", warnings[0])


if __name__ == "__main__":
    unittest.main()
