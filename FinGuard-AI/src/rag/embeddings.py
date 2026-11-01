"""Text -> vector. Default: Sentence Transformers (local, free).

Testing/offline ke liye: set FINGUARD_EMBEDDER=hash  (sirf pipeline test, asli semantic quality nahi)
"""
import hashlib
import os
import re

import numpy as np

MODEL_NAME = "all-MiniLM-L6-v2"
_model = None


def _hash_embed(texts, dim=384):
    stop = {"the", "a", "an", "of", "to", "and", "or", "is", "in", "on", "for", "by", "be", "as", "at", "with", "that", "this", "it", "are", "what", "who", "how", "does", "do"}
    out = np.zeros((len(texts), dim), dtype="float32")
    for i, t in enumerate(texts):
        for w in re.findall(r"[a-z0-9]+", t.lower()):
            if w in stop:
                continue
            h = int(hashlib.md5(w.encode()).hexdigest(), 16)
            out[i, h % dim] += 1.0 if (h >> 8) % 2 else -1.0
        n = np.linalg.norm(out[i])
        if n:
            out[i] /= n
    return out


def embed(texts):
    """List[str] -> List[List[float]] (normalized)."""
    if os.getenv("FINGUARD_EMBEDDER") == "hash":
        return _hash_embed(texts).tolist()
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer(MODEL_NAME)  # pehli baar ~90 MB download
    return _model.encode(texts, normalize_embeddings=True).tolist()