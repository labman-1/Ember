"""
Context Construction 类型定义
"""
from dataclasses import dataclass, field
from typing import Optional, Literal
from enum import Enum


class SectionType(Enum):
    """上下文分段类型"""
    TIME = "time"
    STATE = "state"
    MEMORY = "memory"
    INSTRUCTION = "instruction"
    CUSTOM = "custom"


@dataclass
class Message:
    """消息"""
    role: Literal["system", "user", "assistant"]
    content: str
    
    def to_dict(self) -> dict:
        return {"role": self.role, "content": self.content}


@dataclass
class ContextSection:
    """上下文段落"""
    name: str
    content: str
    position: int = 0  # 用于排序，数字越小越靠前
    
    def format(self) -> str:
        """格式化为文本"""
        return self.content


@dataclass
class BuildOptions:
    """构建选项"""
    include_history: bool = True
    history_limit: Optional[int] = None  # None 表示使用窗口大小
    include_cache_control: bool = False
    cache_static_prefix: bool = True
    cache_dynamic_sections: bool = False


@dataclass
class TokenInfo:
    """Token 信息"""
    total: int = 0
    system: int = 0
    history: int = 0
    dynamic: int = 0