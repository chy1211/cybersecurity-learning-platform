import argparse
import json
import re
from pathlib import Path


CORPUS_TYPE = "question_chunks_v1"
LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def parse_args(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, help="Input question JSON file.")
    parser.add_argument("--output", required=True, help="Output corpus JSON file.")
    parser.add_argument("--limit", type=int, help="Optional number of questions to convert.")
    return parser.parse_args(argv)


def load_questions(path):
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("questions", "items", "data"):
            value = data.get(key)
            if isinstance(value, list):
                return value
        if all(isinstance(value, dict) for value in data.values()):
            return list(data.values())
    raise ValueError("Unsupported question JSON structure.")


def normalize_options(options):
    if isinstance(options, dict):
        return [(str(key), str(value)) for key, value in sorted(options.items())]
    if isinstance(options, list):
        return [(LETTERS[idx], str(value)) for idx, value in enumerate(options)]
    return []


def normalize_answers(answer):
    if isinstance(answer, list):
        answers = answer
    elif isinstance(answer, str) and "," in answer:
        answers = [part.strip() for part in answer.split(",")]
    else:
        answers = [answer]
    return [str(item).strip() for item in answers if str(item).strip()]


def safe_id(value, index):
    raw = str(value or f"question_{index:04d}")
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", raw).strip("_")
    return safe or f"question_{index:04d}"


def render_question(question, index):
    qid = question.get("qid") or question.get("id") or f"question_{index:04d}"
    stem = str(question.get("stem", "")).strip()
    options = normalize_options(question.get("options", {}))
    answers = normalize_answers(question.get("answer", ""))
    option_lookup = {key: value for key, value in options}
    answer_parts = []
    for answer in answers:
        if answer in option_lookup:
            answer_parts.append(f"{answer}. {option_lookup[answer]}")
        else:
            answer_parts.append(answer)

    if question.get("is_single") is True:
        question_type = "single"
    elif question.get("is_single") is False:
        question_type = "multiple"
    elif str(question.get("qtype", "")).lower() in ("single", "multiple"):
        # iPAS 記錄用 qtype 欄位（無 is_single）；正規化為 single/multiple
        question_type = str(question.get("qtype")).lower()
    else:
        question_type = "unspecified"

    lines = [
        f"Question ID: {qid}",
        f"Question Type: {question_type}",
        "Stem:",
        stem,
        "Options:",
    ]
    lines.extend(f"{key}. {value}" for key, value in options)
    lines.extend([
        "Correct Answer: " + "; ".join(answer_parts),
    ])
    return "\n".join(lines).strip()


def build_corpus(questions, output_name, limit=None):
    selected = questions[:limit] if limit is not None else questions
    chunks = []
    for index, question in enumerate(selected, start=1):
        qid = question.get("qid") or question.get("id") or f"question_{index:04d}"
        chunks.append({
            "source_id": f"question_{safe_id(qid, index)}",
            "source_file": output_name,
            "text": render_question(question, index),
        })
    return {
        "corpus_type": CORPUS_TYPE,
        "version": 1,
        "chunks": chunks,
    }


def main(argv=None):
    args = parse_args(argv)
    input_path = Path(args.input)
    output_path = Path(args.output)
    questions = load_questions(input_path)
    corpus = build_corpus(questions, output_path.name, args.limit)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(corpus, f, ensure_ascii=False, indent=2)

    print(f"questions_written={len(corpus['chunks'])}")
    print(f"chunks_written={len(corpus['chunks'])}")


if __name__ == "__main__":
    main()
