import argparse
import json
from pathlib import Path
from typing import Dict, List, Tuple


def iter_json_files(validated_dir: Path):
    for path in validated_dir.rglob("*.json"):
        if path.is_file():
            yield path


def load_json_array(path: Path) -> List[dict]:
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
    except Exception:
        return []
    return []


def compare_record(record: dict) -> Tuple[bool, bool, bool, bool]:
    original = record.get("original_raw_triple")
    if not isinstance(original, dict):
        return False, False, False, False

    subject_changed = record.get("subject") != original.get("subject")
    relation_changed = record.get("relation") != original.get("relation")
    object_changed = record.get("object") != original.get("object")
    any_changed = subject_changed or relation_changed or object_changed
    return True, subject_changed, relation_changed, object_changed if any_changed else False


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Traverse Validated folder and compare original_raw_triple(subject/relation/object) "
            "against final subject/relation/object."
        )
    )
    parser.add_argument(
        "--validated-dir",
        default="Validated",
        help="Path to Validated directory (default: ./Validated relative to script).",
    )
    parser.add_argument(
        "--show-samples",
        type=int,
        default=10,
        help="Number of changed samples to print (default: 10).",
    )
    args = parser.parse_args()

    script_dir = Path(__file__).resolve().parent
    validated_dir = Path(args.validated_dir)
    if not validated_dir.is_absolute():
        validated_dir = (script_dir / validated_dir).resolve()

    if not validated_dir.exists():
        raise SystemExit(f"Validated directory not found: {validated_dir}")

    totals: Dict[str, int] = {
        "files": 0,
        "records": 0,
        "with_original_raw_triple": 0,
        "subject_changed": 0,
        "relation_changed": 0,
        "object_changed": 0,
        "any_changed": 0,
    }

    changed_samples = []

    for json_file in iter_json_files(validated_dir):
        totals["files"] += 1
        records = load_json_array(json_file)
        for idx, rec in enumerate(records):
            totals["records"] += 1
            has_original, subject_changed, relation_changed, object_changed = compare_record(rec)
            if not has_original:
                continue

            totals["with_original_raw_triple"] += 1

            if subject_changed:
                totals["subject_changed"] += 1
            if relation_changed:
                totals["relation_changed"] += 1
            if object_changed:
                totals["object_changed"] += 1

            any_changed = subject_changed or relation_changed or object_changed
            if any_changed:
                totals["any_changed"] += 1
                if len(changed_samples) < args.show_samples:
                    changed_samples.append(
                        {
                            "file": str(json_file.relative_to(validated_dir)),
                            "index": idx,
                            "subject_changed": subject_changed,
                            "relation_changed": relation_changed,
                            "object_changed": object_changed,
                            "original": {
                                "subject": rec.get("original_raw_triple", {}).get("subject"),
                                "relation": rec.get("original_raw_triple", {}).get("relation"),
                                "object": rec.get("original_raw_triple", {}).get("object"),
                            },
                            "final": {
                                "subject": rec.get("subject"),
                                "relation": rec.get("relation"),
                                "object": rec.get("object"),
                            },
                        }
                    )

    with_original = totals["with_original_raw_triple"]
    change_ratio = (totals["any_changed"] / with_original * 100) if with_original else 0.0

    print("=== Validated Change Summary ===")
    print(f"Validated dir: {validated_dir}")
    print(f"JSON files scanned: {totals['files']}")
    print(f"Total records: {totals['records']}")
    print(f"Records with original_raw_triple: {with_original}")
    print()
    print("Field-level changed counts:")
    print(f"- subject changed: {totals['subject_changed']}")
    print(f"- relation changed: {totals['relation_changed']}")
    print(f"- object changed: {totals['object_changed']}")
    print(f"- any of subject/relation/object changed: {totals['any_changed']} ({change_ratio:.2f}%)")

    if changed_samples:
        print()
        print(f"=== Changed Samples (max {args.show_samples}) ===")
        for i, sample in enumerate(changed_samples, start=1):
            print(f"[{i}] file={sample['file']} index={sample['index']}")
            print(
                "    changed_flags: "
                f"subject={sample['subject_changed']}, "
                f"relation={sample['relation_changed']}, "
                f"object={sample['object_changed']}"
            )
            print(f"    original: {sample['original']}")
            print(f"    final   : {sample['final']}")


if __name__ == "__main__":
    main()