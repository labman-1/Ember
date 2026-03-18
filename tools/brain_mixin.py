"""
ToolEnabledBrain Mixin

扩展 Brain 类以支持工具调用功能。
使用 ToolCallProcessor 提供统一的工具处理能力。
"""

import logging
from typing import Optional
from tools.processor import ToolCallProcessor
from core.event_bus import EventBus, Event
from memory.memory_process import Hippocampus

logger = logging.getLogger(__name__)


class ToolEnabledBrain:
    """
    支持工具调用的 Brain 扩展 Mixin

    使用 ToolCallProcessor 提供统一的工具处理能力。

    使用方法:
        class Brain(ToolEnabledBrain):
            def __init__(self, event_bus, ...):
                ToolEnabledBrain.__init__(self, event_bus, hippocampus)
    """

    # 最大单次对话工具调用次数，防止循环
    MAX_TOOL_CALLS_PER_TURN = 5

    def __init__(
        self,
        event_bus: EventBus,
        hippocampus: Optional[Hippocampus] = None,
    ):
        """
        初始化工具支持

        Args:
            event_bus: 事件总线
            hippocampus: 海马体实例（用于记忆相关工具）
        """
        self.event_bus = event_bus
        self.hippocampus = hippocampus

        # 使用 ToolCallProcessor 提供统一的工具处理能力
        self.tool_processor = ToolCallProcessor.create_with_memory_tool(
            hippocampus, max_calls=self.MAX_TOOL_CALLS_PER_TURN
        )

        # 工具调用计数
        self._tool_call_count = 0
        self._tool_results_buffer: list[dict] = []

        # 订阅事件
        self.event_bus.subscribe("brain.tool_call", self._on_tool_call)

    @property
    def tool_registry(self):
        """兼容旧代码的属性"""
        return self.tool_processor.tool_registry

    @property
    def tool_executor(self):
        """兼容旧代码的属性"""
        return self.tool_processor.tool_executor

    def _on_tool_call(self, event: Event):
        """处理显式工具调用事件"""
        tool_name = event.data.get("tool_name")
        params = event.data.get("params", {})

        if tool_name:
            result = self.tool_processor.tool_executor.execute(tool_name, params)
            self.event_bus.publish(
                Event(
                    name="tool.result",
                    data={
                        "tool_name": tool_name,
                        "result": result,
                    },
                )
            )

    # ============ 委托给 ToolCallProcessor 的方法 ============

    def extract_tool_calls(self, text: str) -> list[dict]:
        """从文本中提取工具调用"""
        return self.tool_processor.extract_tool_calls(text)

    def remove_tool_calls(self, text: str) -> str:
        """从文本中移除工具调用标签"""
        return self.tool_processor.remove_tool_calls(text)

    def execute_tool_calls(
        self, calls: list[dict], caller: str = "Brain"
    ) -> list[dict]:
        """并行执行工具调用列表

        Args:
            calls: 工具调用列表
            caller: 调用来源标识
        """
        self._tool_call_count += len(calls)
        return self.tool_processor.execute_tool_calls(calls, caller=caller)

    def format_tool_results_for_prompt(self, results: list[dict]) -> str:
        """格式化工具结果为 prompt 文本"""
        return self.tool_processor.format_tool_results_for_prompt(results)

    def build_system_prompt_with_tools(self, base_prompt: str) -> str:
        """构建包含工具说明的 system prompt"""
        return self.tool_processor.build_system_prompt_with_tools(base_prompt)

    def get_tool_stats(self) -> dict:
        """获取工具调用统计"""
        return {
            "registry": self.tool_processor.tool_registry.get_stats(),
            "executor": self.tool_processor.tool_executor.get_stats(),
            "call_count": self._tool_call_count,
        }

    def register_tool(self, tool) -> bool:
        """注册工具"""
        return self.tool_processor.tool_registry.register(tool)

    def unregister_tool(self, name: str) -> bool:
        """注销工具"""
        return self.tool_processor.tool_registry.unregister(name)

    def reset_tool_state(self) -> None:
        """重置工具调用状态（每轮对话开始时应调用）"""
        self._tool_call_count = 0
        self._tool_results_buffer = []
