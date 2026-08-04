"""Model mention-extraction contract for B4 Step 1."""

from __future__ import annotations

import json
import re
import unicodedata
from typing import Any, Mapping


ALLOWED_ORIGINS = ("stem", "option_A", "option_B", "option_C", "option_D")
ORIGIN_TO_FIELD = {
    "stem": "stem",
    "option_A": ("options", "A"),
    "option_B": ("options", "B"),
    "option_C": ("options", "C"),
    "option_D": ("options", "D"),
}


class MentionExtractionError(ValueError):
    pass


def _extract_json_block(raw: str) -> str:
    text = str(raw or "").strip()
    if not text:
        raise MentionExtractionError("empty Step 1 response")
    fenced = re.search(r"```json\s*(.*?)\s*```", text, re.DOTALL | re.IGNORECASE)
    if fenced:
        return fenced.group(1)
    if text.startswith("{") and text.endswith("}"):
        return text
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        return match.group(0)
    raise MentionExtractionError("Step 1 response does not contain a JSON object")


_WHITESPACE_RE = re.compile(r"\s+")
# 連字號變體（U+2010..2015 等）與 CJK 引號，模型偶爾會把來源文字的變體
# 正規化成慣用符號（如非斷行連字號「‑」→「-」），逐字元比對前先折疊掉。
_DASH_RE = re.compile(r"[‐-―−]")
_QUOTE_RE = re.compile(r"[「」『』]")
# 原始題庫 PDF 逐頁抽取時，試卷頁尾（考試梯次/日期/頁碼）偶爾被誤植進題幹或
# 選項文字「中間」，把一個完整名詞從中截斷（如「OSI 模型(Open System
# Interconnection｜考試日期:109 年 5 月 30 日 第 2 頁,共 9 頁｜Reference
# Model)」）。這種頁尾樣式固定含「考試日期」＋「第N頁,共N頁」，比對前先整段
# 折疊掉，讓被截斷的名詞重新變成連續字串；不影響保存的原始 provenance 文字。
_EXAM_FOOTER_RE = re.compile(
    r"(?:\d+\s*年度第\s*\d+\s*次.{0,60}?)?"
    r"考試日期[:：]\s*\d+\s*年\s*\d+\s*月\s*\d+\s*日\s*"
    r"第\s*\d+\s*頁[,，]共\s*\d+\s*頁"
)


def _fold_for_match(text: str) -> str:
    """NFKC 折疊全半形變體、移除空白（來源題庫 PDF 抽取常見字中殘留空白，
    如「雲 端服務」）、折疊連字號變體與 CJK 引號、移除誤植的試卷頁尾雜訊，
    只用於 containment 判斷，不影響保存的原始 provenance 文字。"""

    folded = unicodedata.normalize("NFKC", text)
    folded = _EXAM_FOOTER_RE.sub("", folded)
    folded = _DASH_RE.sub("-", folded)
    folded = _QUOTE_RE.sub("", folded)
    return _WHITESPACE_RE.sub("", folded)


def _span_in_source(source_span: str, source: str) -> bool:
    if source_span in source:
        return True
    return _fold_for_match(source_span) in _fold_for_match(source)


def _resolve_generic_origin(question: Mapping[str, Any], source_span: str) -> str | None:
    """當模型回傳非法的泛化 origin（如 "options"）時，嘗試從四個選項中找出
    唯一包含該 source_span 的具體 origin。找不到或有歧義則回傳 None（交由
    呼叫端 fail closed），絕不臆測。stem 不在候選範圍內，因為泛化 origin
    的情境都是模型混淆選項，不會混淆題幹。"""

    matches = [
        origin for origin in ("option_A", "option_B", "option_C", "option_D")
        if _span_in_source(source_span, _source_text(question, origin))
    ]
    return matches[0] if len(matches) == 1 else None


def _source_text(question: Mapping[str, Any], origin: str) -> str:
    if origin == "stem":
        return str(question.get("stem") or "")
    group, key = ORIGIN_TO_FIELD[origin]
    return str((question.get(group) or {}).get(key) or "")


def build_step1_input(question: Mapping[str, Any]) -> dict[str, Any]:
    """Return the only question content Step 1 may receive."""

    return {
        "stem": str(question.get("stem") or ""),
        "options": {
            key: str((question.get("options") or {}).get(key) or "")
            for key in "ABCD"
        },
    }


def parse_mention_payload(raw: str | Mapping[str, Any], question: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and normalize a model Step 1 response.

    The response must contain subclaims with mention objects.  A mention is
    accepted only when its source span is an actual substring of the stated
    stem or option.  No legacy bare ``entities`` list is accepted here,
    because it cannot provide the required provenance.
    """

    if isinstance(raw, Mapping):
        payload = dict(raw)
    else:
        try:
            payload = json.loads(_extract_json_block(raw))
        except json.JSONDecodeError as exc:
            raise MentionExtractionError(f"invalid Step 1 JSON: {exc.msg}") from exc
    if not isinstance(payload, dict):
        raise MentionExtractionError("Step 1 payload must be an object")

    raw_subclaims = payload.get("sub_claims")
    if not isinstance(raw_subclaims, list):
        raise MentionExtractionError("Step 1 payload must contain sub_claims array")

    subclaims: list[dict[str, Any]] = []
    mentions: list[dict[str, Any]] = []
    for subclaim_index, raw_subclaim in enumerate(raw_subclaims):
        if not isinstance(raw_subclaim, dict):
            raise MentionExtractionError(f"sub_claims[{subclaim_index}] must be an object")
        subclaim_id = str(raw_subclaim.get("subclaim_id", subclaim_index)).strip()
        text = str(raw_subclaim.get("text") or raw_subclaim.get("sentence") or "").strip()
        if not text:
            raise MentionExtractionError(f"sub_claims[{subclaim_index}] has empty text")
        raw_mentions = raw_subclaim.get("mentions")
        if not isinstance(raw_mentions, list):
            raise MentionExtractionError(
                f"sub_claims[{subclaim_index}] must contain mentions array"
            )
        normalized_mentions: list[dict[str, Any]] = []
        for mention_index, raw_mention in enumerate(raw_mentions):
            if not isinstance(raw_mention, dict):
                raise MentionExtractionError(
                    f"sub_claims[{subclaim_index}].mentions[{mention_index}] must be an object"
                )
            mention_text = str(raw_mention.get("text") or "").strip()
            origin = str(raw_mention.get("origin") or "").strip()
            source_span = str(raw_mention.get("source_span") or "").strip()
            if not mention_text or not source_span:
                raise MentionExtractionError("mention text and source_span are required")
            if origin not in ALLOWED_ORIGINS:
                # 模型偶爾會用泛化的 "options" 取代 option_A/B/C/D；在不放寬
                # provenance 要求的前提下，只針對這個已知的泛化別名，逐一比對
                # 四個選項找出唯一相符的具體 origin，找不到或有歧義（多個選項
                # 都含此 span）一律照原本邏輯 fail closed，不猜。其他任何非法
                # origin（如模型自創的 option_E）維持直接拒絕。
                resolved = (
                    _resolve_generic_origin(question, source_span)
                    if origin == "options" else None
                )
                if resolved is None:
                    raise MentionExtractionError(f"invalid mention origin: {origin}")
                origin = resolved
            source = _source_text(question, origin)
            if not _span_in_source(source_span, source):
                raise MentionExtractionError(
                    f"source_span is not present in {origin}: {source_span!r}"
                )
            normalized = {
                "text": mention_text,
                "origin": origin,
                "source_span": source_span,
                "subclaim_id": subclaim_id,
                "mention_index": mention_index,
            }
            normalized_mentions.append(normalized)
            mentions.append(normalized)
        subclaims.append(
            {
                "subclaim_id": subclaim_id,
                "text": text,
                "mentions": normalized_mentions,
            }
        )
    return {"sub_claims": subclaims, "mentions": mentions}
