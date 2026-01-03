"""
Text chunking and batching using LangChain.
Extracted from api.py - DO NOT MODIFY unless updating source.
"""
from langchain_text_splitters import MarkdownTextSplitter

from app.processing.tokens import count_tokens

# Initialize markdown splitter with langchain
markdown_splitter = MarkdownTextSplitter(
    chunk_size=2000,        # Target chunk size in characters
    chunk_overlap=200,      # Overlap between chunks for context
)


def split_markdown_into_paragraphs(markdown: str) -> list[str]:
    """
    Split markdown into meaningful chunks using langchain's MarkdownTextSplitter.
    Preserves markdown structure (headers, code blocks, lists) while chunking.
    """
    if not markdown or not markdown.strip():
        return []

    # Use langchain's markdown-aware splitter
    chunks = markdown_splitter.split_text(markdown)

    # Filter out empty chunks
    return [chunk.strip() for chunk in chunks if chunk.strip()]


def create_smart_batches(chunks: list[str], max_batch_size: int = 32, max_tokens_per_batch: int = 8000) -> list[list[str]]:
    """
    Create intelligent batches for efficient API calls.
    Groups chunks into batches considering both count and token limits.
    Uses tiktoken for accurate token counting.
    """
    if not chunks:
        return []

    batches = []
    current_batch = []
    current_token_count = 0

    for chunk in chunks:
        chunk_tokens = count_tokens(chunk)

        # Check if adding this chunk would exceed limits
        if (len(current_batch) >= max_batch_size or
            (current_batch and current_token_count + chunk_tokens > max_tokens_per_batch)):

            # Save current batch and start new one
            if current_batch:
                batches.append(current_batch)
                current_batch = []
                current_token_count = 0

        # Add chunk to current batch
        current_batch.append(chunk)
        current_token_count += chunk_tokens

    # Add final batch
    if current_batch:
        batches.append(current_batch)

    return batches
