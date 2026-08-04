from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import pdfplumber


WORKSPACE_ROOT = Path(__file__).resolve().parents[6]
SOURCE_DIR = WORKSPACE_ROOT / "論文" / "SourceData"

SUBJECTS: dict[str, dict[str, str]] = {
    "mgmt": {
        "code": "MGT",
        "name": "資訊安全管理概論",
        "pdf": "108-113初級資訊安全工程師-資訊安全管理概論(混合檔).pdf",
    },
    "tech": {
        "code": "TEC",
        "name": "資訊安全技術",
        "pdf": "108-113初級資訊安全工程師-資訊安全技術(混合).pdf",
    },
}

ANSWER_PREFIX_RE = re.compile(r"^([A-D?])\s+(\d{1,2})[.)](?:\s+(.*)|$)")
QUESTION_RE = re.compile(r"^(?:[\u7686\u7d66\u5206\u5168\u9ad4\u9001]\s+)?(\d{1,2})[.)](?:\s+(.*)|$)")
OPTION_RE = re.compile(r"^(?:[A-D]\s+|[\u7686\u7d66\u5206\u5168\u9ad4\u9001]{1,2}\s+)?\(([A-D])\)\s*(.*)$")
STANDALONE_ANSWER_RE = re.compile(r"^[A-D]{1,4}$")
YEAR_DATE_RE = re.compile(r"(10[8-9]|11[0-3])\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日")
YEAR_RE = re.compile(r"(10[8-9]|11[0-3])\s*年")


def normalize_line(line: str) -> str:
    text = unicodedata.normalize("NFKC", line)
    text = text.replace("\u00a0", " ")
    return re.sub(r"\s+", " ", text).strip()


def is_noise_line(line: str) -> bool:
    if not line:
        return True
    if re.fullmatch(r"\d+", line):
        return True
    if "初級資訊安全工程師" in line:
        return True
    if re.match(r"^科目\s*\d", line):
        return True
    if "測驗日期" in line:
        return True
    if re.search(r"選擇題\s*50\s*題", line):
        return True
    return False


def detect_year(page_lines: list[str]) -> int | None:
    header = " ".join(normalize_line(line) for line in page_lines[:6])
    match = YEAR_DATE_RE.search(header) or YEAR_RE.search(header)
    return int(match.group(1)) if match else None


def join_parts(parts: list[str]) -> str:
    return re.sub(r"\s+", " ", " ".join(part.strip() for part in parts if part.strip())).strip()


def year_label(year: int | None) -> str:
    return str(year) if year is not None else "NULL"


def question_id(year: int | None, subject_code: str, serial: int) -> str:
    return f"IPAS-{year_label(year)}-{subject_code}-{serial:03d}"


def make_question(
    *,
    number: int,
    year: int | None,
    page: int | None,
    answer: str | None,
    raw_answer: str | None,
    first_stem: str,
    raw_line: str,
) -> dict[str, Any]:
    stem_lines = [first_stem] if first_stem else []
    return {
        "number": number,
        "year": year,
        "page": page,
        "answer": answer,
        "raw_answer": raw_answer,
        "stem_lines": stem_lines,
        "options": {"A": [], "B": [], "C": [], "D": []},
        "current_option": None,
        "raw_lines": [raw_line],
    }


def append_content(question: dict[str, Any], line: str) -> None:
    option_match = OPTION_RE.match(line)
    if option_match:
        option_key, option_text = option_match.groups()
        question["current_option"] = option_key
        if option_text:
            question["options"][option_key].append(option_text)
        question["raw_lines"].append(line)
        return

    if (
        question["answer"] is None
        and question["current_option"] is None
        and STANDALONE_ANSWER_RE.fullmatch(line)
    ):
        question["answer"] = line
        question["raw_answer"] = line
        question["raw_lines"].append(line)
        return

    current_option = question["current_option"]
    if current_option:
        question["options"][current_option].append(line)
    else:
        question["stem_lines"].append(line)
    question["raw_lines"].append(line)


def parse_questions_from_tagged_lines(
    tagged_lines: list[tuple[str, int | None, int | None]],
) -> list[dict[str, Any]]:
    questions: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None

    for line, year, page in tagged_lines:
        inline_match = ANSWER_PREFIX_RE.match(line)
        bare_match = QUESTION_RE.match(line) if not inline_match else None

        if inline_match:
            if current is not None:
                questions.append(current)
            raw_answer, number_text, first_stem = inline_match.groups()
            answer = raw_answer if raw_answer in "ABCD" else None
            current = make_question(
                number=int(number_text),
                year=year,
                page=page,
                answer=answer,
                raw_answer=raw_answer,
                first_stem=first_stem or "",
                raw_line=line,
            )
            continue

        if bare_match:
            if current is not None:
                questions.append(current)
            number_text, first_stem = bare_match.groups()
            current = make_question(
                number=int(number_text),
                year=year,
                page=page,
                answer=None,
                raw_answer=None,
                first_stem=first_stem or "",
                raw_line=line,
            )
            continue

        if current is not None:
            append_content(current, line)

    if current is not None:
        questions.append(current)

    return questions


def validate_question(question: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    answer = question.get("answer")
    options = {key: join_parts(parts) for key, parts in question["options"].items()}
    stem = join_parts(question["stem_lines"])

    problems: list[str] = []
    if not stem:
        problems.append("empty_stem")
    if not answer or not re.fullmatch(r"[A-D]{1,4}", answer):
        problems.append(f"bad_answer:{question.get('raw_answer') or 'missing'}")
    missing_options = [key for key in "ABCD" if not options.get(key)]
    if missing_options:
        problems.append("missing_options:" + "".join(missing_options))

    if problems:
        warning = (
            f"incomplete q={question.get('number')} year={year_label(question.get('year'))} "
            f"page={question.get('page')} reasons={','.join(problems)}"
        )
        return None, warning

    return {
        "source": "iPAS",
        "subject": "",
        "year": question["year"],
        "stem": stem,
        "options": options,
        "answer": answer,
        "qtype": "multiple" if len(answer) > 1 else "single",
        "_number": question["number"],
        "_raw_lines": question["raw_lines"],
    }, None


def records_from_questions(
    questions: list[dict[str, Any]],
    subject_key: str,
    *,
    start_serial: int = 1,
    per_year_serials: bool = True,
) -> tuple[list[dict[str, Any]], list[str]]:
    subject = SUBJECTS[subject_key]
    counters: defaultdict[tuple[int | None, str], int] = defaultdict(lambda: start_serial)
    serial = start_serial
    records: list[dict[str, Any]] = []
    warnings: list[str] = []

    for question in questions:
        base_record, warning = validate_question(question)
        if warning:
            warnings.append(warning)
            continue
        assert base_record is not None

        if per_year_serials:
            counter_key = (base_record["year"], subject["code"])
            current_serial = counters[counter_key]
            counters[counter_key] += 1
        else:
            current_serial = serial
            serial += 1

        record = {
            "id": question_id(base_record["year"], subject["code"], current_serial),
            "source": base_record["source"],
            "subject": subject["name"],
            "year": base_record["year"],
            "stem": base_record["stem"],
            "options": base_record["options"],
            "answer": base_record["answer"],
            "qtype": base_record["qtype"],
        }
        records.append(record)

    return records, warnings


def parse_records_from_lines(
    lines: list[str],
    *,
    subject_key: str,
    year: int | None,
    section_index: int = 1,
    start_serial: int = 1,
) -> tuple[list[dict[str, Any]], list[str]]:
    del section_index
    tagged = [
        (normalize_line(line), year, None)
        for line in lines
        if not is_noise_line(normalize_line(line))
    ]
    questions = parse_questions_from_tagged_lines(tagged)
    return records_from_questions(
        questions, subject_key, start_serial=start_serial, per_year_serials=False
    )


def subject_pdf_path(subject_key: str) -> Path:
    return SOURCE_DIR / SUBJECTS[subject_key]["pdf"]


def extract_tagged_lines(subject_key: str) -> tuple[list[tuple[str, int | None, int | None]], int]:
    path = subject_pdf_path(subject_key)
    if not path.exists():
        raise FileNotFoundError(path)

    tagged_lines: list[tuple[str, int | None, int | None]] = []
    with pdfplumber.open(path) as pdf:
        for page_index, page in enumerate(pdf.pages, start=1):
            text = page.extract_text(x_tolerance=1, y_tolerance=3) or ""
            raw_lines = text.splitlines()
            page_year = detect_year(raw_lines)
            for raw_line in raw_lines:
                line = normalize_line(raw_line)
                if is_noise_line(line):
                    continue
                tagged_lines.append((line, page_year, page_index))
        return tagged_lines, len(pdf.pages)


def extract_subject(subject_key: str) -> dict[str, Any]:
    tagged_lines, page_count = extract_tagged_lines(subject_key)
    questions = parse_questions_from_tagged_lines(tagged_lines)
    records, warnings = records_from_questions(questions, subject_key)
    return {
        "subject_key": subject_key,
        "page_count": page_count,
        "questions": questions,
        "records": records,
        "warnings": warnings,
    }


def distribution(records: list[dict[str, Any]]) -> dict[str, int]:
    counts = Counter(year_label(record["year"]) for record in records)
    return dict(sorted(counts.items(), key=lambda item: (item[0] == "NULL", item[0])))


def sample_block(questions: list[dict[str, Any]]) -> str:
    for question in questions:
        _, warning = validate_question(question)
        if not warning:
            return "\n".join(question["raw_lines"][:12])
    return "(無可用樣例)"


def format_stats_line(result: dict[str, Any]) -> str:
    records = result["records"]
    warnings = result["warnings"]
    return (
        f"{SUBJECTS[result['subject_key']]['name']}: pages={result['page_count']}, "
        f"question_candidates={len(result['questions'])}, valid_questions={len(records)}, "
        f"warnings={len(warnings)}, year_distribution={distribution(records)}"
    )


def build_report(results: dict[str, dict[str, Any]]) -> str:
    lines: list[str] = []
    lines.append("iPAS 混合 PDF 抽題器實測報告")
    lines.append("")
    lines.append("一、版面結構觀察")
    for key in ["mgmt", "tech"]:
        result = results[key]
        subject_name = SUBJECTS[key]["name"]
        lines.append("")
        lines.append(f"[{subject_name}]")
        lines.append(
            "pdfplumber 可保留題號與選項行。一般版型為「答案字母 題號. 題幹」同行，"
            "選項為 (A)~(D)；111 年 11 月 19 日版型為「題號. 題幹」後，答案字母以獨立行出現在選項前。"
        )
        lines.append("年度主要由頁眉中的民國年與測驗日期判定；PDF 開頭另有無年度頁眉區段，輸出 year=null。")
        lines.append("原文樣例：")
        lines.append(sample_block(result["questions"]))

    lines.append("")
    lines.append("二、全量 dry-run 統計")
    for key in ["mgmt", "tech"]:
        lines.append(format_stats_line(results[key]))

    lines.append("")
    lines.append("三、已知限制與異常")
    lines.append("1. 無年度頁眉的區段保留 year=null；其 id 年度段使用 NULL，例如 IPAS-NULL-MGT-001。")
    lines.append("2. 解析器只輸出 stem 非空、A-D 四選項齊全、answer 可判為 A-D 的題目。")
    lines.append("3. 跨頁題以題號起點到下一題起點之間的文字合併，可能保留 PDF 斷行造成的空白。")
    lines.append("4. 圖表題只抽文字，不抽圖形；需人工核對題意是否完整。")
    for key in ["mgmt", "tech"]:
        warnings = results[key]["warnings"]
        lines.append(f"{SUBJECTS[key]['name']} warnings={len(warnings)}")
        for warning in warnings[:20]:
            lines.append(f"  - {warning}")
        if len(warnings) > 20:
            lines.append(f"  - ... omitted {len(warnings) - 20} more")

    return "\n".join(lines) + "\n"


def write_json(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")


def write_report(path: Path, report: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(report, encoding="utf-8")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Extract iPAS PDF questions to JSON.")
    parser.add_argument("--subject", choices=["mgmt", "tech", "all"], default="all")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--out", default=None)
    parser.add_argument("--report", default=None)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    subject_keys = ["mgmt", "tech"] if args.subject == "all" else [args.subject]

    if args.out and len(subject_keys) != 1:
        print("ERROR out_requires_single_subject")
        return 2

    results = {key: extract_subject(key) for key in subject_keys}

    if args.out:
        records = results[subject_keys[0]]["records"]
        if args.limit is not None:
            records = records[: args.limit]
        write_json(Path(args.out), records)
        print(f"WROTE_JSON subject={subject_keys[0]} count={len(records)}")

    if args.report:
        report_results = results
        if args.subject != "all":
            all_results = {key: extract_subject(key) for key in ["mgmt", "tech"]}
            report_results = all_results
        write_report(Path(args.report), build_report(report_results))
        print("WROTE_REPORT")

    for key, result in results.items():
        print(
            f"SUMMARY subject={key} pages={result['page_count']} "
            f"candidates={len(result['questions'])} valid={len(result['records'])} "
            f"warnings={len(result['warnings'])}"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
