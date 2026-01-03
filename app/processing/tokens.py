"""
Token counting using tiktoken.
Extracted from api.py - DO NOT MODIFY unless updating source.
"""
from app.logging_config import logger

# Initialize tiktoken encoder for accurate token counting (GPT-4/Claude compatible)
try:
    import tiktoken
    tiktoken_encoder = tiktoken.get_encoding("cl100k_base")
    logger.info("tiktoken encoder initialized (cl100k_base)")
except Exception as e:
    tiktoken_encoder = None
    logger.warning(f"tiktoken not available, using character-based estimation: {e}")


def count_tokens(text: str) -> int:
    """Count tokens using tiktoken for accurate estimation."""
    if tiktoken_encoder:
        return len(tiktoken_encoder.encode(text))
    # Fallback: ~4 chars per token
    return len(text) // 4
