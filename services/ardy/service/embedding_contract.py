"""Sealed text-embedding contract shared by ARDY cache and runtime code."""

from __future__ import annotations

import hashlib

from motion_catalog import GENERATED_BEHAVIORS, REVIEWED_PROMPTS
from pose_protocol import SOURCE_REVISION


EMBEDDING_SCHEMA_VERSION = 2
ARDY_SOURCE_COMMIT = SOURCE_REVISION
BASE_ENCODER_REPOSITORY = "McGill-NLP/LLM2Vec-Meta-Llama-3-8B-Instruct-mntp"
SUPERVISED_ENCODER_REPOSITORY = (
    "McGill-NLP/LLM2Vec-Meta-Llama-3-8B-Instruct-mntp-supervised"
)
UPSTREAM_LLAMA_REPOSITORY = "meta-llama/Meta-Llama-3-8B-Instruct"
ENCODER_REVISIONS = {
    UPSTREAM_LLAMA_REPOSITORY: "8afb486c1db24fe5011ec46dfbe5b5dccdb575c2",
    BASE_ENCODER_REPOSITORY: "31474e395ada192e8ed1586db6be79fb3b70c9c0",
    SUPERVISED_ENCODER_REPOSITORY: "baa8ebf04a1c2500e61288e7dad65e8ae42601a7",
}
EMBEDDING_WIDTH = 4096

# These are deliberately physical, neutral descriptions from the shared,
# reviewed catalog. Arbitrary prompts never cross the public Fay/Unreal
# boundary or enter the normal ARDY service.
APPROVED_EMBEDDING_PROMPTS = dict(REVIEWED_PROMPTS)
APPROVED_EMBEDDING_BEHAVIORS = GENERATED_BEHAVIORS


def prompt_sha256(behavior: str) -> str:
    """Return the reviewed prompt digest for a sealed behavior."""

    return hashlib.sha256(APPROVED_EMBEDDING_PROMPTS[behavior].encode("utf-8")).hexdigest()
