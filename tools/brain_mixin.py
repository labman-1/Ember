"""
ToolEnabledBrain Mixin

扩展 Brain 类以支持工具调用功能。
在对话循环中检测工具调用标签，执行工具并返回结果。
"""

import json
import logging
import re
from typing import Optional, List
from tools.base import ToolResult
from tools.registry import ToolRegistry
from tools.executor import ToolExecutor
from tools.builtin.memory_query_tool import MemoryQueryTool
from core.event_bus import EventBus, Event
from memory.memory_process import Hippocampus

logger = logging.getLogger(__name__)


class ToolEnabledBrain:
    """
    支持工具调用的 Brain 扩展 Mixin

    使用方法:
        class Brain(ToolEnabledBrain):
            def __init__(self, event_bus, ...):
                ToolEnabledBrain.__init__(self, event_bus)
    """

    TOOL_CALL_PATTERN = re.compile(
        r"<tool>\s*(.*?)\s*</tool>",
        re.DOTALL | re.IGNORECASE,
    )

    # 最大单次对话工具调用次数，防止循环
    MAX_TOOL_CALLS_PER_TURN = 3

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
        self.tool_registry = ToolRegistry()
        self.tool_executor = ToolExecutor(self.tool_registry)

        # 工具调用计数
        self._tool_call_count = 0
        self._tool_results_buffer: list[dict] = []

        # 自动注册内置工具
        self._register_builtin_tools()

        # 订阅事件
        self.event_bus.subscribe("brain.tool_call", self._on_tool_call)

    def _register_builtin_tools(self):
        """注册内置工具集"""
        # 记忆查询工具
        if self.hippocampus:
            self.tool_registry.register(MemoryQueryTool(hippocampus=self.hippocampus))
            logger.info("已注册内置工具: memory_query")

    def _on_tool_call(self, event: Event):
        """处理显式工具调用事件"""
        tool_name = event.data.get("tool_name")
        params = event.data.get("params", {})

        if tool_name:
            result = self.tool_executor.execute(tool_name, params)
            self.event_bus.publish(
                Event(
                    name="tool.result",
                    data={
                        "tool_name": tool_name,
                        "result": result,
                    },
                )
            )

    def extract_tool_calls(self, text: str) -> list[dict]:
        """
        从文本中提取工具调用（支持多种格式）

        Args:
            text: LLM 输出的文本

        Returns:
            工具调用列表 [{"name": str, "parameters": dict}]
        """
        calls = []

        for match in self.TOOL_CALL_PATTERN.finditer(text):
            try:
                call_data = json.loads(match.group(1))
                if "name" in call_data:
                    calls.append(
                        {
                            "name": call_data["name"],
                            "parameters": call_data.get("parameters", {}),
                        }
                    )
            except json.JSONDecodeError as e:
                logger.warning(f"JSON格式解析工具调用失败: {e}")

        return calls

    def remove_tool_calls(self, text: str) -> str:
        """
        从文本中移除工具调用标签

        Args:
            text: 原始文本

        Returns:
            清理后的文本
        """
        text = self.TOOL_CALL_PATTERN.sub("", text)
        return text.strip()

    def execute_tool_calls(self, calls: list[dict]) -> list[dict]:
        """
        执行工具调用列表

        Args:
            calls: 工具调用列表

        Returns:
            执行结果列表
        """
        results = []

        for call in calls:
            if self._tool_call_count >= self.MAX_TOOL_CALLS_PER_TURN:
                results.append(
                    {
                        "tool_name": call["name"],
                        "result": ToolResult.fail("单次对话工具调用次数已达上限"),
                    }
                )
                break

            self._tool_call_count += 1
            result = self.tool_executor.execute(call["name"], call["parameters"])
            results.append(
                {
                    "tool_name": call["name"],
                    "result": result,
                }
            )

        return results

    def format_tool_results_for_prompt(self, results: list[dict]) -> str:
        """
        格式化工具结果为 prompt 文本

        Args:
            results: 工具执行结果

        Returns:
            格式化后的文本
        """
        if not results:
            return ""

        lines = ["\n[工具执行结果]"]

        for item in results:
            tool_name = item["tool_name"]
            result = item["result"]

            if result.success:
                # 尝试使用工具的摘要方法
                tool = self.tool_registry.get(tool_name)
                if tool:
                    summary = tool.summarize_result(result, max_length=200)
                    lines.append(f"- {tool_name}: {summary}")
                else:
                    data_str = json.dumps(result.data, ensure_ascii=False, default=str)
                    if len(data_str) > 200:
                        data_str = data_str[:200] + "..."
                    lines.append(f"- {tool_name}: {data_str}")
            else:
                lines.append(f"- {tool_name}: 失败 - {result.error}")

        return "\n".join(lines)

    def build_system_prompt_with_tools(self, base_prompt: str) -> str:
        """
        构建包含工具说明的 system prompt

        Args:
            base_prompt: 基础 system prompt

        Returns:
            增强后的 system prompt
        """
        if len(self.tool_registry) == 0:
            return base_prompt

        tool_guidelines = self.tool_registry.get_tools_description_for_prompt(
            compact=True,
            include_examples=True,
        )

        return f"""{base_prompt}

{tool_guidelines}
"""

    def get_tool_stats(self) -> dict:
        """获取工具调用统计"""
        return {
            "registry": self.tool_registry.get_stats(),
            "executor": self.tool_executor.get_stats(),
        }

    def register_tool(self, tool) -> bool:
        """注册工具"""
        return self.tool_registry.register(tool)

    def unregister_tool(self, name: str) -> bool:
        """注销工具"""
        return self.tool_registry.unregister(name)

    def reset_tool_state(self) -> None:
        """
        重置工具调用状态（每轮对话开始时应调用）
        """
        self._tool_call_count = 0
        self._tool_results_buffer = []
