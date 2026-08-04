import json
from pathlib import Path
import tempfile
import unittest

from exp_3.b4.semantic_index import (
    EmbeddingEndpointError,
    OpenAIEmbeddingClient,
    build_semantic_index,
    cosine_similarity,
)


class FakeEmbeddingClient:
    model = "fixed-test-model"

    def __init__(self, vectors):
        self.vectors = vectors
        self.calls = []

    def embed(self, texts):
        self.calls.append(list(texts))
        return [self.vectors[text] for text in texts]


class FakeResponse:
    status_code = 200

    def __init__(self, body):
        self.body = body

    def raise_for_status(self):
        return None

    def json(self):
        return self.body


class B4SemanticIndexTests(unittest.TestCase):
    def test_fixed_index_builds_and_reuses_cache(self):
        nodes = [
            {"element_id": "n2", "name": "SQL Injection", "type": "attack"},
            {"element_id": "n1", "name": "XSS", "type": "attack"},
        ]
        vectors = {"SQL Injection": [1.0, 0.0], "XSS": [0.0, 1.0]}
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_path = Path(temp_dir) / "semantic.json"
            first_client = FakeEmbeddingClient(vectors)
            first = build_semantic_index(nodes, client=first_client, cache_path=cache_path)
            self.assertEqual(first_client.calls, [["XSS", "SQL Injection"]])
            self.assertEqual(first.search("query", [0.9, 0.1], 2)[0]["element_id"], "n2")

            second_client = FakeEmbeddingClient(vectors)
            build_semantic_index(nodes, client=second_client, cache_path=cache_path)
            self.assertEqual(second_client.calls, [])
            payload = json.loads(cache_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["embedding_model"], "fixed-test-model")

    def test_cache_model_mismatch_is_hard_error(self):
        nodes = [{"element_id": "n1", "name": "SQL Injection"}]
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_path = Path(temp_dir) / "semantic.json"
            client = FakeEmbeddingClient({"SQL Injection": [1.0]})
            build_semantic_index(nodes, client=client, cache_path=cache_path)
            other = FakeEmbeddingClient({"SQL Injection": [1.0]})
            other.model = "another-model"
            with self.assertRaises(ValueError):
                build_semantic_index(nodes, client=other, cache_path=cache_path)

    def test_openai_client_orders_batch_and_rejects_bad_response(self):
        def request(url, **kwargs):
            self.assertTrue(url.endswith("/embeddings"))
            self.assertEqual(kwargs["json"]["model"], "fixed")
            return FakeResponse(
                {
                    "data": [
                        {"index": 1, "embedding": [2.0]},
                        {"index": 0, "embedding": [1.0]},
                    ]
                }
            )

        client = OpenAIEmbeddingClient(
            base_url="http://embedding/v1",
            model="fixed",
            request_fn=request,
        )
        self.assertEqual(client.embed(["a", "b"]), [[1.0], [2.0]])

        bad = OpenAIEmbeddingClient(
            base_url="http://embedding/v1",
            model="fixed",
            retries=1,
            request_fn=lambda *_args, **_kwargs: FakeResponse({"data": []}),
        )
        with self.assertRaises(EmbeddingEndpointError):
            bad.embed(["a"])

    def test_cosine_rejects_mismatched_dimensions(self):
        with self.assertRaises(ValueError):
            cosine_similarity([1.0], [1.0, 0.0])


if __name__ == "__main__":
    unittest.main()
