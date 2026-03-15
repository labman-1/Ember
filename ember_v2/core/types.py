"""
通用类型定义
"""

from dataclasses import dataclass, field
from typing import Any, Generic, TypeVar, Optional
from enum import Enum

T = TypeVar("T")


class ModelType(Enum):
    """模型类型枚举"""

    SMALL = "small"
    LARGE = "large"
    EMBEDDING = "embedding"


@dataclass
class ModelConfig:
    """模型配置"""

    name: str
    api_key: str
    base_url: str
    timeout: int = 30
    max_retries: int = 3
    temperature: float = 0.7

    # 本地模型配置（仅 embedding）
    local_enabled: bool = False
    local_model_name: str = ""


@dataclass
class PackageResponse(Generic[T]):
    """
    Package 标准返回格式

    Attributes:
        success: 操作是否成功
        data: 返回的数据
        error: 错误信息
        metadata: 元数据（耗时、token统计等）
    """

    success: bool
    data: Optional[T] = None
    error: Optional[str] = None
    metadata: dict = field(default_factory=dict)

    def is_ok(self) -> bool:
        """快捷判断是否成功"""
        return self.success


@dataclass
class TokenUsage:
    """Token 使用统计"""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


@dataclass
class LLMResponse:
    """LLM 响应数据"""

    content: str
    usage: Optional[TokenUsage] = None
    model: str = ""
    finish_reason: str = ""


@dataclass
class EmbeddingResponse:
    """Embedding 响应数据"""

    embeddings: list[list[float]]
    model: str = ""
    dimension: int = 0
