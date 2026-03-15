"""
LLM Cleaning 类型定义
"""

from dataclasses import dataclass, field
from typing import Optional
from enum import Enum


class FixResult(Enum):
    """修复结果类型"""

    NO_CHANGE = "no_change"  # 无需修改
    FIXED = "fixed"  # 已修复
    UNFIXABLE = "unfixable"  # 无法修复


@dataclass
class ThoughtExtraction:
    """思考内容提取结果"""

    thought: str = ""  # 思考内容
    speech: str = ""  # 发言内容
    has_thought: bool = False  # 是否包含思考标签
    is_valid: bool = True  # 标签是否完整


@dataclass
class ValidationResult:
    """验证结果"""

    is_valid: bool = True
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    fixed_content: Optional[str] = None


@dataclass
class JSONExtraction:
    """JSON 提取结果"""

    success: bool = True
    data: Optional[dict] = None
    raw_content: str = ""
    error: Optional[str] = None


@dataclass
class CleaningResult:
    """清洗结果"""

    original: str = ""
    cleaned: str = ""
    thought: str = ""
    speech: str = ""
    changes: list[str] = field(default_factory=list)

    @property
    def has_changes(self) -> bool:
        """是否有修改"""
        return len(self.changes) > 0
