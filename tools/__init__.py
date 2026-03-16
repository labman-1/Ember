"""
Ember 可拓展工具接口系统

提供AI角色与外部世界交互的能力，包括：
- 感知环境（时间、天气等）
- 执行操作（文件操作、笔记记录等）
- 记忆管理（显式记住/遗忘）
- 动态工具选择
- 意图识别
- 插件化工具注册
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
from tools.selector import ToolSelector, get_tool_selector
from tools.intent import (
    ToolIntentRecognizer,
    get_intent_recognizer,
    needs_tool,
    ToolIntent,
    IntentResult,
)
from tools.plugin import (
    ToolPluginManager,
    get_plugin_manager,
    auto_discover_tools,
    create_tool_template,
)
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
    # 动态选择
    "ToolSelector",
    "get_tool_selector",
    # 意图识别
    "ToolIntentRecognizer",
    "get_intent_recognizer",
    "needs_tool",
    "ToolIntent",
    "IntentResult",
    # 插件系统
    "ToolPluginManager",
    "get_plugin_manager",
    "auto_discover_tools",
    "create_tool_template",
    # 内置工具
    "TimeTool",
    "FileTool",
    "NoteTool",
    "RememberTool",
    "ForgetTool",
    "RecallCheckTool",
]
