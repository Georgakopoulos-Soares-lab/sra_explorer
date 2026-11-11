"""Embeds search text the same way Automations/create_embeddings.py embedded
the bioprojects, so query and project vectors can be compared.

Keep MODEL_NAME and MAX_SEQ_LENGTH in sync with that script. Vectors are
L2-normalised there and here, so cosine similarity is a plain dot product.

The model (~440 MB) downloads from Hugging Face on first use and is cached
in ~/.cache/huggingface.
"""

import functools
import logging
import os
import threading

MODEL_NAME = "pritamdeka/BioBERT-mnli-snli-scinli-scitail-mednli-stsb"
EMBEDDING_DIM = 768
MAX_SEQ_LENGTH = 512

logger = logging.getLogger(__name__)

_model = None
_lock = threading.Lock()
# Held while encoding: the model's tokenizer can't be used from two threads
# at once, and concurrent batches would share the same CPU threads anyway.
encode_lock = threading.Lock()


def get_model():
    global _model
    with _lock:
        if _model is None:
            # Imported here so the app starts quickly; torch takes a few seconds.
            import torch
            from sentence_transformers import SentenceTransformer

            torch.set_num_threads(int(os.getenv("EMBEDDING_THREADS", "4")))
            model = SentenceTransformer(MODEL_NAME, device="cpu")
            model.max_seq_length = MAX_SEQ_LENGTH
            model.eval()
            _model = model
        return _model


# Cached: the results and their tag summary embed the same search text.
@functools.lru_cache(maxsize=256)
def embed(text: str) -> list[float]:
    model = get_model()
    with encode_lock:
        vec = model.encode(text, normalize_embeddings=True, convert_to_numpy=True)
    return vec.tolist()


def warm_model() -> None:
    """Load the model ahead of the first search. Run in a background thread."""
    try:
        get_model()
    except Exception:
        logger.exception("Could not load the embedding model %s", MODEL_NAME)
