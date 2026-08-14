from functools import lru_cache

from src.db.supabase_client import get_client

# Multilingual (not all-MiniLM-L6-v2, which is English-only) since campaigns
# now carry a per-campaign target_language -- novelty-check/retrieval need to
# work correctly across languages for the same user. Also 384-dim, so no
# schema change needed.
EMBEDDING_MODEL_NAME = "paraphrase-multilingual-MiniLM-L12-v2"


@lru_cache(maxsize=1)
def _model():
    # Lazy + cached: loading the model reads weights from disk (or downloads
    # them once), so this must not happen at import time or on every call.
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(EMBEDDING_MODEL_NAME)


def embed_text(text: str) -> list[float]:
    return _model().encode(text, convert_to_numpy=True).tolist()


def write_embedding(
    user_id: str,
    campaign_id: str,
    round_number: int,
    content_type: str,
    content_text: str,
    *,
    outcome_reward: float | None = None,
) -> None:
    row = {
        "user_id": user_id,
        "campaign_id": campaign_id,
        "round_number": round_number,
        "content_type": content_type,
        "content_text": content_text,
        "outcome_reward": outcome_reward,
        "embedding": embed_text(content_text),
    }
    get_client().table("embeddings").insert(row).execute()


def retrieve_similar(user_id: str, content_type: str, query_text: str, *, k: int = 3) -> list[dict]:
    result = get_client().rpc(
        "match_embeddings",
        {
            "query_embedding": embed_text(query_text),
            "match_user_id": user_id,
            "match_content_type": content_type,
            "match_count": k,
        },
    ).execute()
    return result.data or []


def novelty_score(user_id: str, candidate_text: str) -> float:
    """Similarity (0-1) to this user's single closest past creative. 0.0 if
    they have no creative history yet -- meaning definitely novel."""
    matches = retrieve_similar(user_id, "creative", candidate_text, k=1)
    return matches[0]["similarity"] if matches else 0.0
