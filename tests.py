# tests.py

import importlib
import pytest
import os

def must_import(path: str):
    try:
        return importlib.import_module(path)
    except Exception as e:
        pytest.fail(f"Could not import '{path}': {e}")

def is_callable(mod, name: str):
    assert hasattr(mod, name), f"'{mod.__name__}' missing '{name}'"
    fn = getattr(mod, name)
    assert callable(fn), f"'{mod.__name__}.{name}' is not callable"
    return fn

def test_modules_and_core_functions():

    build_index = must_import("train_model.build_index")
    search_engine = must_import("train_model.search_engine")
    is_callable(build_index, "build_index")
    is_callable(search_engine, "search_primary_and_recommendations")


    query_intent = must_import("genAI.query_intent")
    mail_generation = must_import("genAI.mail_generation")
    is_callable(query_intent, "parse_intent_with_gemini")
    is_callable(mail_generation, "generate_order_email_content")

def test_embedding_and_indexes():
    build_index = must_import("train_model.build_index")
    emb_dir = getattr(build_index, "EMB_DIR", "embeddings")
    idx_dir = getattr(build_index, "IDX_DIR", "indexes")

    ids_path = os.path.join(emb_dir, "ids.npy")
    vecs_path = os.path.join(emb_dir, "clip_image_vectors.npy")
    faiss_path = os.path.join(idx_dir, "faiss_clip.index")

    if all(os.path.exists(p) for p in (ids_path, vecs_path, faiss_path)):
        assert os.path.isfile(ids_path)
        assert os.path.isfile(vecs_path)
        assert os.path.isfile(faiss_path)
    else:
        pytest.skip("Embeddings/index artifacts not present in this environment.")


def test_genai():
    """Call real functions (no mocking). Only validate return types/shapes."""
    query_intent = must_import("genAI.query_intent")
    mail_generation = must_import("genAI.mail_generation")

    data, err = query_intent.parse_intent_with_gemini(
        "men red tshirt under 800", {}
    )

    assert (data is None or isinstance(data, dict)), "data must be dict or None"
    assert (err is None or isinstance(err, str)), "err must be str or None"
    if isinstance(data, dict):
        assert "filters" in data and isinstance(data["filters"], dict)
        assert "normalized_query" in data and isinstance(data["normalized_query"], str)
        assert "strict" in data and isinstance(data["strict"], bool)

    order = {
        "order_id": "O-1",
        "created_at": "2025-08-11",
        "customer_name": "Test User",
        "address": "123 Test St\nCity",
        "subtotal": 999,
        "discount_amount": 0,
        "total": 999,
        "items": [{"title": "Red Tee", "size": "M", "qty": 1, "price": 999}],
    }
    content, err2 = mail_generation.generate_order_email_content(order, returning=False)

    assert isinstance(content, dict), "content must be a dict"
    for k in ("subject", "text", "html"):
        assert k in content and isinstance(content[k], str) and content[k].strip(), f"{k} required"
    assert (err2 is None or isinstance(err2, str)), "err must be str or None"

