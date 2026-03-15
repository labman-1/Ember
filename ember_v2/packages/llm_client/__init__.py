"""
LLM Client Package

支持大/小模型的流式/非流式调用，以及 API/本地 Embedding
"""

from .client import LLMClient
from .types import (
    ModelSize,
    EmbeddingMode,
    ChatRequest,
    ChatResponse,
    StreamChunk,
    EmbeddingRequest,
    EmbeddingResult,
    EmbeddingResponse,
)

__all__ = [
    "LLMClient",
    "ModelSize",
    "EmbeddingMode",
    "ChatRequest",
    "ChatResponse",
    "StreamChunk",
    "EmbeddingRequest",
    "EmbeddingResult",
    "EmbeddingResponse",
]
