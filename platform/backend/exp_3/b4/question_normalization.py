"""B4 question schema normalization and leakage-safe input views.

The original held-out file is intentionally never modified.  This module
normalizes both the ITE/ISN and iPAS record shapes into the B4 contract and
keeps answer-bearing fields separate from the retrieval view.
"""

from __future__ import annotations

import copy
import re
from collections import Counter
from typing import Any, Iterable


EXPECTED_OPTION_KEYS = ("A", "B", "C", "D")
ANSWER_RE = re.compile(r"^[A-D]$")


EXCLUDED_VISUAL_QUESTIONS: dict[str, dict[str, str]] = {
    "ISN-107-012": {
        "reason": "題目依賴網址列／憑證警告畫面，原評測輸入未保存圖片。",
        "visual_dependency": "browser address bar or certificate warning screenshot",
    },
    "ISN-107-021": {
        "reason": "題目依賴伺服器系統紀錄截圖，原評測輸入未保存圖片。",
        "visual_dependency": "server system log screenshot",
    },
    "ISN-107-022": {
        "reason": "題目依賴組織連外流量圖，原評測輸入未保存圖片。",
        "visual_dependency": "organization external traffic chart",
    },
    "IPAS-110-TEC-054": {
        "reason": "題目依賴登入頁面驗證圖片／CAPTCHA，原評測輸入未保存圖片。",
        "visual_dependency": "login verification image or CAPTCHA",
    },
    "IPAS-111-MGT-082": {
        "reason": "題目依賴密碼安全措施編號圖，原評測輸入未保存圖片。",
        "visual_dependency": "password security measure number diagram",
    },
    "IPAS-111-MGT-089": {
        "reason": "題目依賴 Kerberos 認證流程圖，原評測輸入未保存圖片。",
        "visual_dependency": "Kerberos authentication flow diagram",
    },
    "IPAS-113-MGT-021": {
        "reason": "題目依賴風險回應方式編號圖，原評測輸入未保存圖片。",
        "visual_dependency": "risk response method number diagram",
    },
    "IPAS-113-MGT-030": {
        "reason": "題目依賴生物辨識誤差指標圖，原評測輸入未保存圖片。",
        "visual_dependency": "biometric error metric diagram",
    },
}


def _text(value: Any, *, field: str, qid: str = "") -> str:
    if value is None:
        return ""
    result = str(value).strip()
    if not result:
        location = f" for {qid}" if qid else ""
        raise ValueError(f"{field} must be non-empty{location}")
    return result


def _canonical_source(record: dict[str, Any], qid: str) -> str:
    cert_type = str(record.get("cert_type") or "").strip().upper()
    source = str(record.get("source") or "").strip().lower()
    if cert_type == "ISN" or qid.upper().startswith("ISN-"):
        return "ISN"
    if source == "ipas" or qid.upper().startswith("IPAS-"):
        return "iPAS"
    if source:
        return source
    raise ValueError(f"cannot infer source for {qid}")


def normalize_question(record: dict[str, Any]) -> dict[str, Any]:
    """Normalize one source record into the B4 question contract."""

    if not isinstance(record, dict):
        raise TypeError("question record must be an object")

    qid = _text(record.get("qid") or record.get("id"), field="qid")
    source = _canonical_source(record, qid)
    stem = _text(record.get("stem"), field="stem", qid=qid)

    raw_options = record.get("options")
    if not isinstance(raw_options, dict):
        raise ValueError(f"options must be an object for {qid}")
    if set(raw_options) != set(EXPECTED_OPTION_KEYS):
        raise ValueError(
            f"options must contain exactly A-D for {qid}; got {sorted(raw_options)}"
        )
    options = {
        key: _text(raw_options[key], field=f"options.{key}", qid=qid)
        for key in EXPECTED_OPTION_KEYS
    }

    answer = _text(record.get("answer"), field="answer", qid=qid)
    if not ANSWER_RE.fullmatch(answer):
        raise ValueError(f"answer must match A-D for {qid}; got {answer!r}")

    raw_is_single = record.get("is_single")
    if raw_is_single is None:
        is_single = str(record.get("qtype") or "").strip().lower() == "single"
    elif isinstance(raw_is_single, bool):
        is_single = raw_is_single
    else:
        is_single = str(raw_is_single).strip().lower() in {"true", "1", "single"}
    if not is_single:
        raise ValueError(f"B4 formal input must be single-choice for {qid}")

    subject = str(record.get("subject") or record.get("cert_type") or "").strip()
    result: dict[str, Any] = {
        "qid": qid,
        "source": source,
        "subject": subject,
        "year": record.get("year"),
        "stem": stem,
        "options": options,
        "answer": answer,
        "is_single": True,
        "split_meta": copy.deepcopy(record.get("split_meta") or {}),
    }

    # Preserve non-answer provenance that is useful for auditing without
    # copying arbitrary source fields into the stable contract.
    for key in ("source_file", "raw_qno", "cert_type"):
        if key in record and record[key] is not None:
            result[key] = copy.deepcopy(record[key])
    return result


def normalize_question_set(records: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized = [normalize_question(record) for record in records]
    qids = [record["qid"] for record in normalized]
    duplicates = [qid for qid, count in Counter(qids).items() if count > 1]
    if duplicates:
        raise ValueError(f"duplicate qids: {sorted(duplicates)}")
    return normalized


def retrieval_view(question: dict[str, Any]) -> dict[str, Any]:
    """Return the only question fields allowed before model answering."""

    return {
        "qid": question["qid"],
        "source": question["source"],
        "subject": question.get("subject", ""),
        "year": question.get("year"),
        "stem": question["stem"],
        "options": {
            key: question["options"][key] for key in EXPECTED_OPTION_KEYS
        },
        "is_single": True,
    }
