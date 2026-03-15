"""
LLM Client 类型定义
"""

from dataclasses import dataclass, field
from typing import Optional, AsyncIterator, Literal
from enum import Enum

from ember_v2.core.types import PackageResponse, TokenUsage


class ModelSize(Enum):
    """模型大小枚举"""

    SMALL = "small"
    LARGE = "large"


class EmbeddingMode(Enum):
    """Embedding 模式枚举"""

    API = "api"
    LOCAL = "local"


@dataclass
class ChatRequest:
    """聊天请求"""

    messages: list[dict]
    model_size: ModelSize = ModelSize.LARGE
    stream: bool = False
    temperature: Optional[float] = None
    timeout: Optional[int] = None
    extra_body: dict = field(default_factory=dict)


@dataclass
class ChatResponse:
    """聊天响应"""

    content: str
    usage: Optional[TokenUsage] = None
    model: str = ""
    finish_reason: str = ""


@dataclass
class StreamChunk:
    """流式响应块"""

    content: str
    reasoning: Optional[str] = None
    is_finished: bool = False
    finish_reason: str = ""


@dataclass
class EmbeddingRequest:
    """Embedding 请求"""

    texts: list[str]
    mode: EmbeddingMode = EmbeddingMode.API
    dimension: Optional[int] = None  # 输出维度，None 表示模型默认


@dataclass
class EmbeddingResult:
    """Embedding 结果"""

    embedding: list[float]
    model: str = ""
    dimension: int = 0


@dataclass
class EmbeddingResponse:
    """Embedding 响应"""

    embeddings: list[list[float]]
    model: str = ""
    dimension: int = 0
