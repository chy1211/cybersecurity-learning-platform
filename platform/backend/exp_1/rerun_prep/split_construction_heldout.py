from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import random
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


WORKSPACE_ROOT = Path(__file__).resolve().parents[6]
DEFAULT_ITE = (
    WORKSPACE_ROOT
    / "論文"
    / "交接"
    / "platform"
    / "backend"
    / "exp_3"
    / "data"
    / "question_bank_329.json"
)
DEFAULT_OUTDIR = WORKSPACE_ROOT / "_tooling" / "rerun_test"

CONSTRUCTION = "construction"
HELDOUT = "heldout"


@dataclass(frozen=True)
class SplitInput:
    record: dict[str, Any]
    item_id: str
    source: str
    strata_key: str
    normalized_stem: str


@dataclass(frozen=True)
class SplitOutputItem:
    record: dict[str, Any]
    item_id: str
    source: str
    strata_key: str
    normalized_stem: str
    side: str


@dataclass(frozen=True)
class SplitResult:
    items: list[SplitOutputItem]
    strata_rows: list[dict[str, Any]]
    duplicate_groups: list[dict[str, Any]]
    duplicate_split_violations: int


def load_json_records(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, list):
        records = data
    elif isinstance(data, dict):
        list_values = [value for value in data.values() if isinstance(value, list)]
        if len(list_values) != 1:
            raise ValueError(f"cannot identify record list in {path}")
        records = list_values[0]
    else:
        raise ValueError(f"unsupported JSON top-level type in {path}: {type(data).__name__}")

    if not all(isinstance(item, dict) for item in records):
        raise ValueError(f"not every record is an object in {path}")
    return records


def md5_file(path: Path) -> str:
    digest = hashlib.md5()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_path_list(values: Iterable[str] | None) -> list[Path]:
    paths: list[Path] = []
    for value in values or []:
        for part in str(value).split(","):
            stripped = part.strip()
            if stripped:
                paths.append(Path(stripped))
    return paths


def normalize_stem_for_grouping(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).lower()
    return "".join(ch for ch in text if unicodedata.category(ch)[0] in {"L", "N"})


def round_half_up(value: float) -> int:
    return int(math.floor(value + 0.5))


def target_count(total: int, ratio: float) -> int:
    return round_half_up(total * ratio)


def answer_tokens(answer: Any) -> list[str]:
    if answer is None:
        return []
    if isinstance(answer, list):
        return [str(item).strip() for item in answer if str(item).strip()]
    if isinstance(answer, dict):
        return [str(item).strip() for item in answer.values() if str(item).strip()]

    text = str(answer).strip()
    if not text:
        return []
    if re.search(r"[,;、/\s]", text):
        return [part for part in re.split(r"[,;、/\s]+", text) if part]
    if re.fullmatch(r"[A-Za-z]+", text) and len(text) > 1:
        return list(text)
    return [text]


def boolish_single(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes", "single", "單選"}:
            return True
        if lowered in {"false", "0", "no", "multiple", "複選"}:
            return False
    raise ValueError(f"cannot classify is_single={value!r}")


def ite_strata_key(record: dict[str, Any]) -> str:
    cert_type = str(record.get("cert_type") or "UNKNOWN")
    qtype = "single" if boolish_single(record.get("is_single")) else "multiple"
    return f"ITE|cert={cert_type}|type={qtype}"


def ipas_question_type(record: dict[str, Any]) -> str:
    qtype = str(record.get("qtype") or "").strip().lower()
    if qtype in {"single", "單選"}:
        return "single"
    if qtype in {"multiple", "multi", "複選"}:
        return "multiple"
    return "multiple" if len(answer_tokens(record.get("answer"))) > 1 else "single"


def ipas_year_label(year: Any) -> str:
    if year is None:
        return "SAMPLE"
    text = str(year).strip()
    return text if text and text.lower() not in {"null", "none"} else "SAMPLE"


def ipas_strata_key(record: dict[str, Any], *, include_qtype: bool) -> str:
    subject = str(record.get("subject") or "UNKNOWN")
    year = ipas_year_label(record.get("year"))
    base = f"iPAS|subject={subject}|year={year}"
    if include_qtype:
        base += f"|type={ipas_question_type(record)}"
    return base


def get_record_id(record: dict[str, Any]) -> str:
    for key in ("qid", "id", "question_id", "raw_qno"):
        value = record.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    raise ValueError("record has no usable id field")


def get_stem(record: dict[str, Any]) -> str:
    value = record.get("stem")
    if value is None:
        raise ValueError(f"record {get_record_id(record)} has no stem")
    return str(value)


def prepare_ite_records(path: Path) -> tuple[list[SplitInput], list[dict[str, Any]]]:
    records = load_json_records(path)
    prepared: list[SplitInput] = []
    excluded_custom: list[dict[str, Any]] = []

    for record in records:
        qid = get_record_id(record)
        if qid.startswith("CUSTOM-"):
            excluded_custom.append(record)
            continue
        if not (qid.startswith("ISN-") or qid.startswith("ISK-")):
            raise ValueError(f"unexpected ITE qid prefix: {qid}")

        normalized = normalize_stem_for_grouping(get_stem(record))
        if not normalized:
            raise ValueError(f"empty normalized stem for {qid}")
        prepared.append(
            SplitInput(
                record=record,
                item_id=qid,
                source="ITE",
                strata_key=ite_strata_key(record),
                normalized_stem=normalized,
            )
        )

    if path.name == "question_bank_329.json":
        assert len(excluded_custom) == 10, (
            "question_bank_329.json must contain exactly 10 CUSTOM anchor questions; "
            f"found {len(excluded_custom)}"
        )

    return prepared, excluded_custom


def prepare_ipas_records(paths: list[Path]) -> list[SplitInput]:
    all_records: list[dict[str, Any]] = []
    for path in paths:
        all_records.extend(load_json_records(path))

    include_qtype = any(ipas_question_type(record) == "multiple" for record in all_records)
    prepared: list[SplitInput] = []
    seen_ids: set[str] = set()
    for record in all_records:
        item_id = get_record_id(record)
        if item_id in seen_ids:
            raise ValueError(f"duplicate iPAS id: {item_id}")
        seen_ids.add(item_id)

        normalized = normalize_stem_for_grouping(get_stem(record))
        if not normalized:
            raise ValueError(f"empty normalized stem for {item_id}")
        prepared.append(
            SplitInput(
                record=record,
                item_id=item_id,
                source="iPAS",
                strata_key=ipas_strata_key(record, include_qtype=include_qtype),
                normalized_stem=normalized,
            )
        )
    return prepared


def make_strata_rows(
    items: list[SplitOutputItem],
    ratio: float,
) -> list[dict[str, Any]]:
    totals = Counter(item.strata_key for item in items)
    construction_counts = Counter(
        item.strata_key for item in items if item.side == CONSTRUCTION
    )
    heldout_counts = Counter(item.strata_key for item in items if item.side == HELDOUT)

    rows: list[dict[str, Any]] = []
    for strata_key in sorted(totals):
        total = totals[strata_key]
        construction = construction_counts[strata_key]
        heldout = heldout_counts[strata_key]
        target = target_count(total, ratio)
        rows.append(
            {
                "strata_key": strata_key,
                "total": total,
                "target_construction": target,
                "construction": construction,
                "heldout": heldout,
                "delta_from_target": construction - target,
            }
        )
    return rows


def assign_splits(records: list[SplitInput], *, ratio: float, seed: int) -> SplitResult:
    if not 0 < ratio < 1:
        raise ValueError("--ratio must be between 0 and 1")

    groups: dict[str, list[SplitInput]] = defaultdict(list)
    for record in records:
        groups[record.normalized_stem].append(record)

    strata_totals = Counter(record.strata_key for record in records)
    strata_targets = {
        strata_key: target_count(total, ratio)
        for strata_key, total in sorted(strata_totals.items())
    }

    rng = random.Random(seed)
    group_order = sorted(groups)
    rng.shuffle(group_order)

    construction_counts: Counter[str] = Counter()
    side_by_group: dict[str, str] = {}

    for group_key in group_order:
        group_items = groups[group_key]
        group_counts = Counter(item.strata_key for item in group_items)
        affected = sorted(group_counts)
        build_score = sum(
            abs(
                construction_counts[strata_key]
                + group_counts[strata_key]
                - strata_targets[strata_key]
            )
            for strata_key in affected
        )
        hold_score = sum(
            abs(construction_counts[strata_key] - strata_targets[strata_key])
            for strata_key in affected
        )

        if build_score < hold_score:
            side = CONSTRUCTION
        elif build_score > hold_score:
            side = HELDOUT
        else:
            side = CONSTRUCTION if rng.random() < ratio else HELDOUT

        side_by_group[group_key] = side
        if side == CONSTRUCTION:
            for strata_key, count in group_counts.items():
                construction_counts[strata_key] += count

    output_items = [
        SplitOutputItem(
            record=item.record,
            item_id=item.item_id,
            source=item.source,
            strata_key=item.strata_key,
            normalized_stem=item.normalized_stem,
            side=side_by_group[item.normalized_stem],
        )
        for item in records
    ]

    duplicate_groups: list[dict[str, Any]] = []
    duplicate_split_violations = 0
    for group_key in sorted(groups):
        group_items = groups[group_key]
        if len(group_items) <= 1:
            continue
        sides = {side_by_group[group_key]}
        if len(sides) > 1:
            duplicate_split_violations += 1
        duplicate_groups.append(
            {
                "side": side_by_group[group_key],
                "size": len(group_items),
                "ids": sorted(item.item_id for item in group_items),
                "strata": dict(
                    sorted(Counter(item.strata_key for item in group_items).items())
                ),
            }
        )

    return SplitResult(
        items=output_items,
        strata_rows=make_strata_rows(output_items, ratio),
        duplicate_groups=duplicate_groups,
        duplicate_split_violations=duplicate_split_violations,
    )


def record_with_split_meta(item: SplitOutputItem, *, seed: int, ratio: float) -> dict[str, Any]:
    record = copy.deepcopy(item.record)
    record["split_meta"] = {
        "seed": seed,
        "ratio": ratio,
        "strata_key": item.strata_key,
    }
    return record


def sorted_output_records(
    items: Iterable[SplitOutputItem],
    *,
    seed: int,
    ratio: float,
) -> list[dict[str, Any]]:
    return [
        record_with_split_meta(item, seed=seed, ratio=ratio)
        for item in sorted(items, key=lambda item: (item.source, item.strata_key, item.item_id))
    ]


def write_json(path: Path, records: list[dict[str, Any]]) -> None:
    path.write_text(
        json.dumps(records, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(WORKSPACE_ROOT))
    except ValueError:
        return str(path)


def report_lines(
    *,
    result: SplitResult,
    seed: int,
    ratio: float,
    input_paths: list[Path],
    excluded_custom: list[dict[str, Any]],
    construction_count: int,
    heldout_count: int,
) -> list[str]:
    lines = [
        "# Construction/Heldout Split Report",
        "",
        f"SEED={seed}",
        f"RATIO={ratio}",
        "ROUNDING_RULE=round_half_up(total * ratio), counted by question record; duplicate-stem groups are assigned atomically.",
        f"TOTAL_CONSTRUCTION={construction_count}",
        f"TOTAL_HELDOUT={heldout_count}",
        "",
        "## Input MD5",
    ]
    for path in input_paths:
        lines.append(f"- {rel(path)} md5={md5_file(path)}")

    custom_ids = sorted(get_record_id(record) for record in excluded_custom)
    lines.extend(
        [
            "",
            "## Excluded CUSTOM",
            f"CUSTOM_EXCLUDED_COUNT={len(custom_ids)}",
            "CUSTOM_EXCLUDED_IDS=" + (", ".join(custom_ids) if custom_ids else "(none)"),
            "",
            "## Strata Counts",
            "| strata_key | total | target_construction | construction | heldout | delta_from_target |",
            "|---|---:|---:|---:|---:|---:|",
        ]
    )
    for row in result.strata_rows:
        lines.append(
            "| {strata_key} | {total} | {target_construction} | {construction} | {heldout} | {delta_from_target} |".format(
                **row
            )
        )

    lines.extend(
        [
            "",
            "## Duplicate Stem Groups",
            f"DUP_GROUPS_TOTAL={len(result.duplicate_groups)}",
            f"DUP_GROUPS_SPLIT_VIOLATION={result.duplicate_split_violations}",
        ]
    )
    for idx, group in enumerate(result.duplicate_groups, start=1):
        strata_text = "; ".join(
            f"{key}:{value}" for key, value in sorted(group["strata"].items())
        )
        lines.append(
            f"- group={idx} side={group['side']} size={group['size']} strata={strata_text} ids={', '.join(group['ids'])}"
        )

    return lines


def run_split(
    *,
    ite_path: Path,
    ipas_paths: list[Path],
    ratio: float,
    seed: int,
    outdir: Path,
    tag: str,
) -> tuple[Path, Path, Path, SplitResult]:
    outdir.mkdir(parents=True, exist_ok=True)

    ite_records, excluded_custom = prepare_ite_records(ite_path)
    ipas_records = prepare_ipas_records(ipas_paths)
    all_records = ite_records + ipas_records
    result = assign_splits(all_records, ratio=ratio, seed=seed)

    construction_items = [item for item in result.items if item.side == CONSTRUCTION]
    heldout_items = [item for item in result.items if item.side == HELDOUT]

    construction_path = outdir / f"construction_set{tag}.json"
    heldout_path = outdir / f"heldout_test_set{tag}.json"
    report_path = outdir / f"split_report{tag}.txt"

    write_json(
        construction_path,
        sorted_output_records(construction_items, seed=seed, ratio=ratio),
    )
    write_json(
        heldout_path,
        sorted_output_records(heldout_items, seed=seed, ratio=ratio),
    )
    report_path.write_text(
        "\n".join(
            report_lines(
                result=result,
                seed=seed,
                ratio=ratio,
                input_paths=[ite_path, *ipas_paths],
                excluded_custom=excluded_custom,
                construction_count=len(construction_items),
                heldout_count=len(heldout_items),
            )
        )
        + "\n",
        encoding="utf-8",
    )
    return construction_path, heldout_path, report_path, result


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create reproducible construction/heldout splits for ITE and iPAS."
    )
    parser.add_argument("--ite", type=Path, default=DEFAULT_ITE)
    parser.add_argument("--ipas", action="append", default=[])
    parser.add_argument("--ratio", type=float, default=0.7)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--outdir", type=Path, default=DEFAULT_OUTDIR)
    parser.add_argument("--tag", default="")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    ipas_paths = parse_path_list(args.ipas)
    construction_path, heldout_path, report_path, result = run_split(
        ite_path=args.ite,
        ipas_paths=ipas_paths,
        ratio=args.ratio,
        seed=args.seed,
        outdir=args.outdir,
        tag=args.tag,
    )
    construction_count = sum(1 for item in result.items if item.side == CONSTRUCTION)
    heldout_count = sum(1 for item in result.items if item.side == HELDOUT)
    print(
        "OK "
        f"construction={construction_count} "
        f"heldout={heldout_count} "
        f"files={construction_path.name},{heldout_path.name},{report_path.name}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
