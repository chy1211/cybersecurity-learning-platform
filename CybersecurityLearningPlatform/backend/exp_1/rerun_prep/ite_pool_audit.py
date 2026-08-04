from __future__ import annotations

import json
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[6]
BACKEND = ROOT / "論文" / "交接" / "CybersecurityLearningPlatform" / "backend"
DATA_DIR = BACKEND / "exp_3" / "data"
SOURCE_DIR = DATA_DIR / "source"
REPORT_PATH = ROOT / "_tooling" / "rerun_test" / "ite_pool_audit.txt"

PRIMARY_FILES = {
    "question_bank_329": DATA_DIR / "question_bank_329.json",
    "ite_all_pool": SOURCE_DIR / "ite_all_pool.json",
    "ite_raw_pool": SOURCE_DIR / "ite_raw_pool.json",
}

ID_FIELDS = ("qid", "id", "question_id", "raw_qno")
TEXT_FIELDS = ("stem", "question", "question_text", "text")


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


def direct_json_files() -> list[Path]:
    paths: set[Path] = set()
    for folder in (DATA_DIR, SOURCE_DIR):
        if folder.exists():
            paths.update(folder.glob("*.json"))
    paths.update(PRIMARY_FILES.values())
    return sorted(paths, key=lambda p: str(p).lower())


def rel(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def get_id(record: dict[str, Any]) -> str:
    for field in ID_FIELDS:
        value = record.get(field)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def get_stem(record: dict[str, Any]) -> str:
    for field in TEXT_FIELDS:
        value = record.get(field)
        if value is not None:
            return str(value)
    return ""


def normalize_stem(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value)
    normalized = normalized.lower()
    normalized = re.sub(r"\s+", "", normalized)
    normalized = re.sub(r"[，,。．.、；;：:！？!?（）()\[\]【】「」『』\"'`~\-—_]", "", normalized)
    return normalized


def id_prefix(qid: str) -> str:
    if not qid:
        return "(missing)"
    match = re.match(r"^([A-Za-z]+-)", qid)
    if match:
        return match.group(1).upper()
    match = re.match(r"^([A-Za-z]+)", qid)
    if match:
        return match.group(1).upper()
    return "(other)"


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
    if re.search(r"[,;、/\\s]", text):
        return [part for part in re.split(r"[,;、/\\s]+", text) if part]
    letters = re.fullmatch(r"[A-Za-z]+", text)
    if letters and len(text) > 1:
        return list(text)
    return [text]


def classify_type(record: dict[str, Any]) -> tuple[str, str]:
    if "is_single" in record:
        value = record.get("is_single")
        if isinstance(value, bool):
            return ("單選" if value else "複選", "is_single")
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in {"true", "1", "yes", "single", "單選"}:
                return ("單選", "is_single")
            if lowered in {"false", "0", "no", "multiple", "複選"}:
                return ("複選", "is_single")

    tokens = answer_tokens(record.get("answer"))
    if len(tokens) == 1:
        return ("單選", "answer_inferred")
    if len(tokens) > 1:
        return ("複選", "answer_inferred")
    return ("未知", "answer_inferred")


def type_name(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int) and not isinstance(value, bool):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "str"
    if isinstance(value, list):
        if not value:
            return "list[empty]"
        inner = Counter(type_name(item) for item in value)
        return "list[" + ", ".join(f"{k}:{v}" for k, v in sorted(inner.items())) + "]"
    if isinstance(value, dict):
        return "dict"
    return type(value).__name__


def first_text(value: str, limit: int = 20) -> str:
    compact = re.sub(r"\s+", " ", value).strip()
    return compact[:limit]


def counter_lines(counter: Counter[str]) -> list[str]:
    if not counter:
        return ["  （無）"]
    return [f"  - {key}: {value}" for key, value in sorted(counter.items())]


def duplicate_values(records: Iterable[dict[str, Any]], getter) -> dict[str, int]:
    counts = Counter(getter(record) for record in records)
    return {key: value for key, value in sorted(counts.items()) if key and value > 1}


def format_id_list(ids: Iterable[str], max_items: int = 25) -> str:
    items = sorted(ids)
    if not items:
        return "（無）"
    shown = ", ".join(items[:max_items])
    if len(items) > max_items:
        shown += f", ...（另 {len(items) - max_items} 筆）"
    return shown


def file_summary(path: Path, records: list[dict[str, Any]]) -> list[str]:
    ids = [get_id(record) for record in records]
    prefixes = Counter(id_prefix(qid) for qid in ids)
    type_by_method = Counter()
    type_total = Counter()
    field_counter = Counter()
    missing_by_field = Counter()

    union_fields: set[str] = set()
    for record in records:
        union_fields.update(record.keys())
    for record in records:
        for field in union_fields:
            if field not in record:
                missing_by_field[field] += 1
            else:
                field_counter[field] += 1
        label, method = classify_type(record)
        type_total[label] += 1
        type_by_method[f"{method}:{label}"] += 1

    sample = records[0] if records else {}
    sample_types = {field: type_name(sample.get(field)) for field in sorted(sample.keys())}
    dup_ids = duplicate_values(records, get_id)
    dup_stems = duplicate_values(records, lambda r: normalize_stem(get_stem(r)))

    lines = [
        f"### {path.name}",
        f"- 路徑: {rel(path)}",
        f"- 題數: {len(records)}",
        "- id 前綴分佈:",
        *counter_lines(prefixes),
        "- 題型分佈:",
        *counter_lines(type_total),
        "- 題型判定欄位/方法:",
        *counter_lines(type_by_method),
        f"- 欄位名清單: {', '.join(sorted(union_fields)) if union_fields else '（無）'}",
        f"- 範例欄位型別: {json.dumps(sample_types, ensure_ascii=False, sort_keys=True)}",
        f"- 重複 id: {len(dup_ids)} 組" + (f"；{json.dumps(dup_ids, ensure_ascii=False)}" if dup_ids else ""),
        f"- 題幹正規化後重複: {len(dup_stems)} 組" + (f"；{json.dumps(dup_stems, ensure_ascii=False)}" if dup_stems else ""),
    ]
    missing = {key: value for key, value in sorted(missing_by_field.items()) if value}
    lines.append(f"- 缺欄位統計: {json.dumps(missing, ensure_ascii=False, sort_keys=True) if missing else '（無）'}")
    return lines


def compare_sets(
    name_a: str,
    records_a: list[dict[str, Any]],
    name_b: str,
    records_b: list[dict[str, Any]],
) -> list[str]:
    ids_a = {get_id(record) for record in records_a if get_id(record)}
    ids_b = {get_id(record) for record in records_b if get_id(record)}
    stems_a = {normalize_stem(get_stem(record)) for record in records_a if normalize_stem(get_stem(record))}
    stems_b = {normalize_stem(get_stem(record)) for record in records_b if normalize_stem(get_stem(record))}

    id_intersection = ids_a & ids_b
    a_only = ids_a - ids_b
    b_only = ids_b - ids_a
    stem_intersection = stems_a & stems_b

    method = "id(qid) 比對"
    if not id_intersection and stem_intersection:
        method = "id 無交集，改用題幹 NFKC/去空白標點/lower 正規化比對"

    return [
        f"### {name_a} vs {name_b}",
        f"- 比對方法: {method}；同時計算題幹正規化交集作備援檢查",
        f"- id 交集: {len(id_intersection)}",
        f"- {name_a} only: {len(a_only)}；{format_id_list(a_only)}",
        f"- {name_b} only: {len(b_only)}；{format_id_list(b_only)}",
        f"- 題幹正規化交集: {len(stem_intersection)}",
        f"- 題幹正規化 {name_a} only: {len(stems_a - stems_b)}",
        f"- 題幹正規化 {name_b} only: {len(stems_b - stems_a)}",
    ]


def source_value(record: dict[str, Any]) -> str:
    value = record.get("source")
    return "" if value is None else str(value).strip()


def cert_value(record: dict[str, Any]) -> str:
    value = record.get("cert_type")
    return "" if value is None else str(value).strip()


def is_custom_anchor(record: dict[str, Any]) -> bool:
    qid = get_id(record)
    return (
        id_prefix(qid) == "CUSTOM-"
        or source_value(record).lower() == "custom"
        or cert_value(record).lower() == "custom"
    )


def cert_subject(record: dict[str, Any]) -> str:
    cert = cert_value(record).upper()
    if cert in {"ISN", "ISK"}:
        return cert
    prefix = id_prefix(get_id(record)).rstrip("-")
    if prefix in {"ISN", "ISK"}:
        return prefix
    return "其他"


def exact_condition_report(
    name: str,
    selected_ids: set[str],
    anchor_ids: set[str],
    official_ids_in_qb: set[str],
) -> tuple[bool, list[str]]:
    hit_anchor = selected_ids & anchor_ids
    missed_anchor = anchor_ids - selected_ids
    false_kill = selected_ids & official_ids_in_qb
    exact = not missed_anchor and not false_kill and selected_ids == anchor_ids
    lines = [
        f"- {name}",
        f"  - 命中自製題: {len(hit_anchor)}",
        f"  - 漏掉自製題: {len(missed_anchor)}；{format_id_list(missed_anchor)}",
        f"  - 誤殺官方題: {len(false_kill)}；{format_id_list(false_kill)}",
        f"  - 條件是否恰好等於自製題集合: {'是' if exact else '否'}",
    ]
    return exact, lines


def anchor_analysis(qb: list[dict[str, Any]], official_pool: list[dict[str, Any]]) -> list[str]:
    official_pool_ids = {get_id(record) for record in official_pool if get_id(record)}
    qb_ids = {get_id(record) for record in qb if get_id(record)}
    prefix_custom_ids = {get_id(record) for record in qb if id_prefix(get_id(record)) == "CUSTOM-"}
    source_custom_ids = {get_id(record) for record in qb if source_value(record).lower() == "custom"}
    cert_custom_ids = {get_id(record) for record in qb if cert_value(record).lower() == "custom"}
    null_origin_ids = {
        get_id(record)
        for record in qb
        if record.get("source_file") is None and record.get("raw_qno") is None
    }
    anchor_records = [record for record in qb if is_custom_anchor(record)]
    anchor_ids = {get_id(record) for record in anchor_records}
    official_ids_in_qb = qb_ids - anchor_ids
    official_like_pool_gaps = {
        get_id(record)
        for record in qb
        if get_id(record) in official_ids_in_qb and get_id(record) not in official_pool_ids
    }

    all_official_unique_ids_present = official_pool_ids <= qb_ids
    custom_conditions_agree = prefix_custom_ids == source_custom_ids == cert_custom_ids == null_origin_ids == anchor_ids

    candidate_sets: list[tuple[str, set[str]]] = [
        ("條件 A：qid startswith 'CUSTOM-'", prefix_custom_ids),
        ("條件 B：source == 'custom'", source_custom_ids),
        ("條件 C：cert_type == 'custom'", cert_custom_ids),
        ("條件 D：source_file is null and raw_qno is null", null_origin_ids),
        ("條件 E：qid not in unique ite_all_pool.qid", {get_id(record) for record in qb if get_id(record) not in official_pool_ids}),
    ]

    lines = [
        "## 自製錨點題識別結論",
        "- 識別基準: `question_bank_329.json` 中 `qid` 前綴為 `CUSTOM-`、`source=custom`、`cert_type=custom` 的題目互相吻合，視為自製錨點題；`ite_all_pool.json` 用於檢查官方題池覆蓋，但因其 qid 有重複，不能單獨當作錨點條件。",
        f"- 官方 pool 題數: {len(official_pool)}；唯一 qid 數: {len(official_pool_ids)}",
        f"- question_bank id 數: {len(qb_ids)}",
        f"- 官方 pool 唯一 qid 是否全數存在於 question_bank: {'是' if all_official_unique_ids_present else '否'}",
        f"- CUSTOM/source/cert_type/null-origin 四條件是否一致: {'是' if custom_conditions_agree else '否'}",
        f"- 自製錨點題數: {len(anchor_records)}",
        "- 自製錨點題清單（id；題幹前 20 字）:",
    ]
    if anchor_records:
        for record in sorted(anchor_records, key=get_id):
            lines.append(f"  - {get_id(record)}；{first_text(get_stem(record), 20)}")
    else:
        lines.append("  （無）")

    lines.append("- 候選機器條件驗證:")
    exact_conditions: list[str] = []
    for name, selected in candidate_sets:
        exact, condition_lines = exact_condition_report(name, selected, anchor_ids, official_ids_in_qb)
        lines.extend(condition_lines)
        if exact:
            exact_conditions.append(name)

    if exact_conditions:
        recommended = "條件 A：qid startswith 'CUSTOM-'"
        lines.append(f"- 建議過濾條件: {recommended}")
    else:
        lines.append("- 建議過濾條件: 無單一候選條件可達成命中自製題且 0 誤殺；請以本節候選清單人工覆核後再切分。")
    lines.append(f"- 官方 pool id 異常造成的官方題缺口（非錨點）: {len(official_like_pool_gaps)}；{format_id_list(official_like_pool_gaps)}")
    lines.append("- 一行虛擬碼: `is_anchor = q.qid.startswith('CUSTOM-')`; `keep_for_split = not is_anchor`")
    return lines


def official_cross_table(qb: list[dict[str, Any]]) -> list[str]:
    table: dict[str, Counter[str]] = defaultdict(Counter)
    for record in qb:
        if is_custom_anchor(record):
            continue
        subject = cert_subject(record)
        qtype, _ = classify_type(record)
        table[subject][qtype] += 1

    subjects = sorted(table.keys())
    types = ["單選", "複選", "未知"]
    lines = [
        "## 官方題科目 x 單/複選交叉計數",
        "| 科目 | 單選 | 複選 | 未知 | 合計 |",
        "|---|---:|---:|---:|---:|",
    ]
    for subject in subjects:
        total = sum(table[subject].values())
        lines.append(
            f"| {subject} | {table[subject]['單選']} | {table[subject]['複選']} | {table[subject]['未知']} | {total} |"
        )
    grand = Counter()
    for subject in subjects:
        grand.update(table[subject])
    lines.append(f"| 合計 | {grand['單選']} | {grand['複選']} | {grand['未知']} | {sum(grand.values())} |")
    return lines


def build_report() -> str:
    paths = direct_json_files()
    loaded: dict[Path, list[dict[str, Any]]] = {}
    for path in paths:
        loaded[path] = load_json_records(path)

    missing_primary = [name for name, path in PRIMARY_FILES.items() if path not in loaded]
    if missing_primary:
        raise FileNotFoundError(f"missing primary files: {missing_primary}")

    qb = loaded[PRIMARY_FILES["question_bank_329"]]
    all_pool = loaded[PRIMARY_FILES["ite_all_pool"]]
    raw_pool = loaded[PRIMARY_FILES["ite_raw_pool"]]

    lines: list[str] = [
        "# ITE 題池盤點報告",
        "",
        "## 執行範圍",
        f"- 讀取 JSON 檔數: {len(paths)}",
        "- 納入規則: `backend/exp_3/data/*.json` 與 `backend/exp_3/data/source/*.json` 的直接 JSON 檔；不遞迴讀取子資料夾。",
        "- 比對原則: 優先使用 qid/id 類欄位；另以題幹 NFKC、去空白與常見標點、lower 後的字串作備援交集檢查。",
        "",
        "## 各檔題數、id 樣態、題型與欄位結構",
    ]

    for path in paths:
        lines.extend(file_summary(path, loaded[path]))
        lines.append("")

    lines.append("## question_bank_329 與 pool 檔交集/差集")
    lines.extend(compare_sets("question_bank_329", qb, "ite_all_pool", all_pool))
    lines.append("")
    lines.extend(compare_sets("question_bank_329", qb, "ite_raw_pool", raw_pool))
    lines.append("")

    lines.extend(anchor_analysis(qb, all_pool))
    lines.append("")
    lines.extend(official_cross_table(qb))
    lines.append("")

    all_paths_by_name = {path.name: path for path in paths}
    extra_paths = [path for path in paths if path not in PRIMARY_FILES.values()]
    lines.append("## 其他同夾 JSON")
    if extra_paths:
        for path in extra_paths:
            lines.append(f"- {path.name}: {len(loaded[path])} 題；路徑 {rel(path)}")
    else:
        lines.append("- （無）")

    lines.append("")
    lines.append("## 重要異常摘要")
    for path in paths:
        records = loaded[path]
        dup_ids = duplicate_values(records, get_id)
        dup_stems = duplicate_values(records, lambda r: normalize_stem(get_stem(r)))
        missing_id = sum(1 for record in records if not get_id(record))
        missing_stem = sum(1 for record in records if not get_stem(record))
        lines.append(
            f"- {path.name}: 重複 id {len(dup_ids)} 組；重複題幹 {len(dup_stems)} 組；缺 id {missing_id}；缺題幹 {missing_stem}"
        )

    return "\n".join(lines) + "\n"


def main() -> int:
    report = build_report()
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(report, encoding="utf-8")
    print("OK report=_tooling/rerun_test/ite_pool_audit.txt")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
