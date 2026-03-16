"""
Ember 可拓展工具接口系统

提供AI角色与外部世界交互的能力，包括：
- 感知环境（时间、天气等）
- 执行操作（文件操作、笔记记录等）
- 记忆管理（显式记住/遗忘）
"""

from tools.base import (
    BaseTool,
    ToolResult,
    ToolPermission,
    ToolError,
    ToolTimeoutError,
    ToolPermissionError,
    ToolValidationError,
)
from tools.registry import ToolRegistry
from tools.executor import ToolExecutor
from tools.brain_mixin import ToolEnabledBrain
from tools.builtin import TimeTool, FileTool, NoteTool
from tools.builtin.memory_tools import RememberTool, ForgetTool, RecallCheckTool

__all__ = [
    # 基础类
    "BaseTool",
    "ToolResult",
    "ToolPermission",
    "ToolError",
    "ToolTimeoutError",
    "ToolPermissionError",
    "ToolValidationError",
    # 核心组件
    "ToolRegistry",
    "ToolExecutor",
    "ToolEnabledBrain",
    # 内置工具
    "TimeTool",
    "FileTool",
    "NoteTool",
    "RememberTool",
    "ForgetTool",
    "RecallCheckTool",
]
