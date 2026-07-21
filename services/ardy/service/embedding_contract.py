"""Sealed text-embedding contract shared by ARDY cache and runtime code."""

from __future__ import annotations

import hashlib


EMBEDDING_SCHEMA_VERSION = 1
ARDY_SOURCE_COMMIT = "693f74d13b3d04a0a22ce127ee79c929dd89756b"
BASE_ENCODER_REPOSITORY = "McGill-NLP/LLM2Vec-Meta-Llama-3-8B-Instruct-mntp"
SUPERVISED_ENCODER_REPOSITORY = (
    "McGill-NLP/LLM2Vec-Meta-Llama-3-8B-Instruct-mntp-supervised"
)
UPSTREAM_LLAMA_REPOSITORY = "meta-llama/Meta-Llama-3-8B-Instruct"
EMBEDDING_WIDTH = 4096

# These are deliberately physical, neutral descriptions. Arbitrary prompts never
# cross the public Fay/Unreal boundary or enter the normal ARDY service.
APPROVED_EMBEDDING_PROMPTS = {
    "idle": (
        "A person stands naturally with subtle breathing and small relaxed "
        "weight shifts."
    ),
    "listen": (
        "A person stands attentively and listens with calm, subtle "
        "conversational body movement."
    ),
    "explain": (
        "A person explains something naturally using relaxed conversational "
        "hand and arm gestures."
    ),
}
APPROVED_EMBEDDING_BEHAVIORS = tuple(sorted(APPROVED_EMBEDDING_PROMPTS))


def prompt_sha256(behavior: str) -> str:
    """Return the reviewed prompt digest for a sealed behavior."""

    return hashlib.sha256(APPROVED_EMBEDDING_PROMPTS[behavior].encode("utf-8")).hexdigest()
