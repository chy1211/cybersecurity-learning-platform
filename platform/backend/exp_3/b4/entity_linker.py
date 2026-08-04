"""Precision-first entity linker for B4 (route 2: model-in-the-loop).

2026-07-12 redesign.  The human-calibrated semantic threshold/margin gate was
removed.  Linking now is:

    1. normalized exact match (unique)      -> accepted automatically
    2. approved alias (unique target)       -> accepted automatically
    3. otherwise (exact collision or no exact hit) -> the evaluated model
       chooses one node from a bounded embedding candidate set, or answers
       "none".  A choice outside the candidate set, or "none", stays
       ``unresolved`` (fail closed).

There is no per-dataset threshold tuning and no researcher gold-labeling.  The
candidate generator (a fixed embedding provider) and the model picker are both
injectable so the linker stays independent of Neo4j and of the LLM transport.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re
import unicodedata
from typing import Any, Callable, Iterable, Mapping


HYPHENS = "‐‑‒–—―−﹘﹣－"
HYPHEN_TRANSLATION = str.maketrans({char: "-" for char in HYPHENS})
SPACE_RE = re.compile(r"\s+")

VALID_ORIGINS = {"stem", "option_A", "option_B", "option_C", "option_D"}


def normalize_name(value: str) -> str:
    """Apply the B4 name normalization contract."""

    if value is None:
        return ""
    text = unicodedata.normalize("NFKC", str(value))
    text = text.translate(HYPHEN_TRANSLATION)
    text = SPACE_RE.sub(" ", text.strip())
    return text.casefold()


@dataclass(frozen=True)
class LinkerConfig:
    semantic_top_k: int = 5
    min_mention_chars: int = 2
    generic_terms: frozenset[str] = field(default_factory=frozenset)

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "LinkerConfig":
        semantic = value.get("semantic", {}) or {}
        generic_terms = value.get("generic_terms", ()) or ()
        return cls(
            semantic_top_k=int(semantic.get("top_k", 5)),
            min_mention_chars=int(value.get("min_mention_chars", 2)),
            generic_terms=frozenset(normalize_name(item) for item in generic_terms),
        )


# A candidate generator: (mention, top_k) -> iterable of {element_id, name, score, ...}
SemanticProvider = Callable[[str, int], Iterable[Mapping[str, Any]]]
# A model picker: (choice_request) -> chosen element_id or None.
NodePicker = Callable[[Mapping[str, Any]], "str | None"]


class EntityLinker:
    """Link mention strings with exact -> alias -> model-picked precedence."""

    def __init__(
        self,
        nodes: Iterable[Mapping[str, Any]],
        *,
        aliases: Mapping[str, str] | None = None,
        config: LinkerConfig | None = None,
        semantic_provider: SemanticProvider | None = None,
        node_picker: NodePicker | None = None,
    ) -> None:
        self.config = config or LinkerConfig()
        self.semantic_provider = semantic_provider
        self.node_picker = node_picker
        self.nodes = [self._node_copy(node) for node in nodes]
        self.nodes_by_id = {node["element_id"]: node for node in self.nodes}
        if len(self.nodes_by_id) != len(self.nodes):
            raise ValueError("KG node element_id values must be unique")

        self.name_index: dict[str, list[dict[str, Any]]] = {}
        for node in self.nodes:
            normalized = normalize_name(node["name"])
            if not normalized:
                raise ValueError(f"KG node {node['element_id']} has empty name")
            self.name_index.setdefault(normalized, []).append(node)

        self.alias_index: dict[str, str] = {}
        for alias, target_name in (aliases or {}).items():
            alias_key = normalize_name(alias)
            target_key = normalize_name(target_name)
            if not alias_key or not target_key:
                raise ValueError("alias and alias target must be non-empty")
            if alias_key in self.alias_index and self.alias_index[alias_key] != target_key:
                raise ValueError(f"alias maps to multiple targets: {alias}")
            self.alias_index[alias_key] = target_key

    @staticmethod
    def _node_copy(node: Mapping[str, Any]) -> dict[str, Any]:
        element_id = str(node.get("element_id") or node.get("id") or "").strip()
        name = str(node.get("name") or "").strip()
        if not element_id or not name:
            raise ValueError("each KG node needs element_id and name")
        result = {
            "element_id": element_id,
            "name": name,
        }
        if node.get("type") is not None:
            result["type"] = str(node["type"])
        return result

    def _generic_reason(self, normalized: str) -> str | None:
        if len(normalized) < self.config.min_mention_chars:
            return "mention is too short or generic"
        if normalized in self.config.generic_terms:
            return "mention is in the generic-term rejection list"
        return None

    @staticmethod
    def _candidate_view(node: Mapping[str, Any], score: float, rank: int) -> dict[str, Any]:
        result = {
            "element_id": node["element_id"],
            "name": node["name"],
            "score": float(score),
            "rank": rank,
        }
        if node.get("type") is not None:
            result["type"] = node["type"]
        return result

    def _result(
        self,
        *,
        qid: str,
        mention: str,
        origin: str,
        source_span: str,
        normalized: str,
        status: str,
        reason: str,
        matched_node: Mapping[str, Any] | None = None,
        candidates: list[dict[str, Any]] | None = None,
        needs_choice: bool = False,
        choice_kind: str | None = None,
    ) -> dict[str, Any]:
        record = {
            "qid": qid,
            "mention": mention,
            "origin": origin,
            "source_span": source_span,
            "normalized_mention": normalized,
            "status": status,
            "matched_node": dict(matched_node) if matched_node else None,
            "candidates": candidates or [],
            "decision_reason": reason,
        }
        if needs_choice:
            # Internal fields only present on records awaiting a model choice.
            record["needs_choice"] = True
            record["choice_kind"] = choice_kind
        return record

    def _semantic_candidates(self, mention: str) -> list[dict[str, Any]]:
        if self.semantic_provider is None:
            return []
        raw_candidates = list(self.semantic_provider(mention, self.config.semantic_top_k))
        ranked = sorted(
            (dict(candidate) for candidate in raw_candidates),
            key=lambda candidate: (
                -float(candidate.get("score", 0.0)),
                str(candidate.get("name", "")),
                str(candidate.get("element_id", candidate.get("id", ""))),
            ),
        )[: self.config.semantic_top_k]
        candidates: list[dict[str, Any]] = []
        rank = 1
        for candidate in ranked:
            element_id = str(candidate.get("element_id") or candidate.get("id") or "").strip()
            name = str(candidate.get("name") or "").strip()
            if not element_id or not name:
                continue
            node = self.nodes_by_id.get(element_id, {"element_id": element_id, "name": name})
            candidates.append(self._candidate_view(node, float(candidate.get("score", 0.0)), rank))
            rank += 1
        return candidates

    def propose(
        self,
        *,
        qid: str,
        mention: str,
        origin: str,
        source_span: str | None = None,
    ) -> dict[str, Any]:
        """Resolve everything that is deterministic; flag the rest for a model
        choice.  Any returned record with ``needs_choice`` is not yet final and
        must be passed to :meth:`finalize_choice` with the picked id.

        This performs at most one candidate-generation (embedding) call, so the
        pipeline can batch the actual model decision per question without
        re-embedding.
        """

        mention = str(mention or "").strip()
        if not mention:
            raise ValueError("mention must be non-empty")
        if origin not in VALID_ORIGINS:
            raise ValueError(f"invalid mention origin: {origin}")
        source_span = str(source_span if source_span is not None else mention)
        normalized = normalize_name(mention)

        generic_reason = self._generic_reason(normalized)
        if generic_reason:
            return self._result(
                qid=qid, mention=mention, origin=origin, source_span=source_span,
                normalized=normalized, status="rejected_generic", reason=generic_reason,
            )

        exact_nodes = self.name_index.get(normalized, [])
        if len(exact_nodes) == 1:
            node = exact_nodes[0]
            return self._result(
                qid=qid, mention=mention, origin=origin, source_span=source_span,
                normalized=normalized, status="exact", reason="normalized exact match",
                matched_node=node, candidates=[self._candidate_view(node, 1.0, 1)],
            )
        if len(exact_nodes) > 1:
            candidates = [
                self._candidate_view(node, 1.0, rank)
                for rank, node in enumerate(
                    sorted(exact_nodes, key=lambda item: (item["name"], item["element_id"])),
                    start=1,
                )
            ]
            return self._result(
                qid=qid, mention=mention, origin=origin, source_span=source_span,
                normalized=normalized, status="pending_choice",
                reason="normalized exact match collides; model must disambiguate",
                candidates=candidates, needs_choice=True, choice_kind="exact_ambiguous",
            )

        if normalized in self.alias_index:
            target_name = self.alias_index[normalized]
            alias_nodes = self.name_index.get(target_name, [])
            if len(alias_nodes) == 1:
                node = alias_nodes[0]
                return self._result(
                    qid=qid, mention=mention, origin=origin, source_span=source_span,
                    normalized=normalized, status="alias", reason="approved alias match",
                    matched_node=node, candidates=[self._candidate_view(node, 1.0, 1)],
                )
            reason = (
                "approved alias target is missing"
                if not alias_nodes
                else "approved alias target is ambiguous"
            )
            return self._result(
                qid=qid, mention=mention, origin=origin, source_span=source_span,
                normalized=normalized, status="unresolved", reason=reason,
            )

        candidates = self._semantic_candidates(mention)
        if not candidates:
            reason = (
                "no candidate generator configured"
                if self.semantic_provider is None
                else "candidate search returned no valid nodes"
            )
            return self._result(
                qid=qid, mention=mention, origin=origin, source_span=source_span,
                normalized=normalized, status="unresolved", reason=reason,
            )
        return self._result(
            qid=qid, mention=mention, origin=origin, source_span=source_span,
            normalized=normalized, status="pending_choice",
            reason="model must select among embedding candidates or reject",
            candidates=candidates, needs_choice=True, choice_kind="semantic",
        )

    def choice_request(self, proposed: Mapping[str, Any]) -> dict[str, Any]:
        """The exact payload a model needs to pick a node for a pending record."""

        return {
            "qid": proposed["qid"],
            "mention": proposed["mention"],
            "origin": proposed["origin"],
            "source_span": proposed["source_span"],
            "choice_kind": proposed.get("choice_kind"),
            "candidates": [
                {
                    "element_id": c["element_id"],
                    "name": c["name"],
                    **({"type": c["type"]} if "type" in c else {}),
                }
                for c in proposed.get("candidates", [])
            ],
        }

    def finalize_choice(
        self, proposed: Mapping[str, Any], chosen_element_id: str | None
    ) -> dict[str, Any]:
        """Turn a pending record + the model's pick into a final link record.

        Fail closed: ``None`` or an id outside the candidate set -> unresolved.
        Reuses the candidates already generated in :meth:`propose` (no
        re-embedding).
        """

        if not proposed.get("needs_choice"):
            return {k: v for k, v in proposed.items() if k not in {"needs_choice", "choice_kind"}}

        candidates = list(proposed.get("candidates", []))
        by_id = {c["element_id"]: c for c in candidates}
        base = dict(
            qid=proposed["qid"], mention=proposed["mention"], origin=proposed["origin"],
            source_span=proposed["source_span"], normalized=proposed["normalized_mention"],
            candidates=candidates,
        )
        chosen = str(chosen_element_id).strip() if chosen_element_id is not None else ""
        if not chosen:
            return self._result(**base, status="unresolved", reason="model selected no candidate")
        if chosen not in by_id:
            return self._result(
                **base, status="unresolved",
                reason="model selected an id outside the candidate set",
            )
        node = self.nodes_by_id.get(chosen, {"element_id": chosen, "name": by_id[chosen]["name"]})
        return self._result(
            **base, status="model_pick",
            reason="model selected a node from the bounded candidate set",
            matched_node=node,
        )

    def link(
        self,
        *,
        qid: str,
        mention: str,
        origin: str,
        source_span: str | None = None,
    ) -> dict[str, Any]:
        """Synchronous single-mention link.  Uses ``self.node_picker`` when a
        model choice is required; without a picker, a choice-requiring mention
        stays ``unresolved`` (fail closed).  Batch callers should use
        :meth:`propose` + :meth:`finalize_choice` instead."""

        proposed = self.propose(qid=qid, mention=mention, origin=origin, source_span=source_span)
        if not proposed.get("needs_choice"):
            return proposed
        if self.node_picker is None:
            base = dict(
                qid=proposed["qid"], mention=proposed["mention"], origin=proposed["origin"],
                source_span=proposed["source_span"], normalized=proposed["normalized_mention"],
                candidates=list(proposed.get("candidates", [])),
            )
            return self._result(
                **base, status="unresolved",
                reason="no model picker configured for an ambiguous or non-exact mention",
            )
        chosen = self.node_picker(self.choice_request(proposed))
        return self.finalize_choice(proposed, chosen)
