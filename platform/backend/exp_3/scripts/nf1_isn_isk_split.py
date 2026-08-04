"""Split NF1 eval results by ISN vs ISK and compute per-model Δ (graph_rag − llm_only)."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
QB_PATH = ROOT / "data" / "question_bank_329.json"
EVAL_DIR = ROOT / "data" / "eval_results"

MODELS = ["e4b", "gptoss", "gemma31b", "llama70b"]
MODEL_LABEL = {
    "e4b": "Gemma-4-e4b-it",
    "gptoss": "GPT-OSS-20B",
    "gemma31b": "Gemma-4-31b",
    "llama70b": "Llama-3.3-70B",
}


def load_qb():
    with open(QB_PATH, "r", encoding="utf-8") as f:
        return {q["qid"]: q for q in json.load(f)}


def acc(rows, key):
    if not rows:
        return None
    correct = sum(1 for r in rows if r[key].get("correct"))
    return 100.0 * correct / len(rows)


def main():
    qb = load_qb()

    print(f"{'Model':<18} {'Slice':<14} {'n':>4} {'LLM%':>7} {'+RAG%':>7} {'Δpp':>7}")
    print("-" * 64)

    for m in MODELS:
        with open(EVAL_DIR / f"eval_{m}_NF1.json", "r", encoding="utf-8") as f:
            ev = json.load(f)
        # join with qb
        joined = []
        for qid, e in ev.items():
            q = qb.get(qid)
            if not q:
                continue
            joined.append({"qid": qid, "cert_type": q["cert_type"], "is_single": q["is_single"],
                           "llm_only": e["llm_only"], "graph_rag": e["graph_rag"]})

        # slices
        slices = {
            "ISN all":      [r for r in joined if r["cert_type"] == "ISN"],
            "ISN single":   [r for r in joined if r["cert_type"] == "ISN" and r["is_single"]],
            "ISN multi":    [r for r in joined if r["cert_type"] == "ISN" and not r["is_single"]],
            "ISK all":      [r for r in joined if r["cert_type"] == "ISK"],
            "ISK single":   [r for r in joined if r["cert_type"] == "ISK" and r["is_single"]],
            "ISK multi":    [r for r in joined if r["cert_type"] == "ISK" and not r["is_single"]],
        }

        for name, rows in slices.items():
            n = len(rows)
            llm = acc(rows, "llm_only")
            rag = acc(rows, "graph_rag")
            delta = (rag - llm) if (llm is not None and rag is not None) else None
            print(f"{MODEL_LABEL[m]:<18} {name:<14} {n:>4} {llm:>7.2f} {rag:>7.2f} {delta:>+7.2f}")
        print()


if __name__ == "__main__":
    main()
