from __future__ import annotations

import unittest

from exp_3.exp_3_eval_batch import build_prompt


QUESTION = {
    "qid": "q1",
    "stem": "哪一項可以降低 SQL Injection 風險？",
    "options": {
        "A": "輸入驗證",
        "B": "停用日誌",
        "C": "共用帳號",
        "D": "移除權限",
    },
    "source": "ISN",
    "answer": "A",
    "rationale": "gold-secret-rationale-must-not-enter-prompt",
    "is_single": True,
}


class PromptContractTests(unittest.TestCase):
    def test_base_and_rag_share_everything_except_evidence_block(self):
        subgraph = {
            "subgraph": {
                "evidence": [
                    {"head": "SQL Injection", "relation": "mitigates", "tail": "輸入驗證"}
                ]
            }
        }
        base_system, base_user = build_prompt(QUESTION, "base", None)
        rag_system, rag_user = build_prompt(QUESTION, "rag", subgraph)
        self.assertEqual(base_system, rag_system)
        self.assertIn("Evidence set：[]", base_user)
        self.assertIn("SQL Injection", rag_user)
        for text in (base_user, rag_user):
            self.assertIn("輸入驗證", text)
            self.assertIn("停用日誌", text)
            self.assertIn("共用帳號", text)
            self.assertIn("移除權限", text)
            self.assertNotIn("gold-secret-rationale", text)


if __name__ == "__main__":
    unittest.main()
