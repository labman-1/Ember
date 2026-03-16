"""
ToolEnabledBrain Mixin

扩展 Brain 类以支持工具调用功能。
在对话循环中检测工具调用意图，管理工具调用上下文。
"""
import json
import logging
import re
import threading
from typing import Optional, Any, List
from tools.base import ToolResult
from tools.registry import ToolRegistry
from tools.executor import ToolExecutor
from tools.selector import ToolSelector, get_tool_selector
from tools.intent import ToolIntentRecognizer, get_intent_recognizer, ToolIntent
from tools.builtin.time_tool import TimeTool
from tools.builtin.file_tool import FileTool
from tools.builtin.note_tool import NoteTool
from tools.builtin.memory_tools import RememberTool, RecallCheckTool
from core.event_bus import EventBus, Event
from memory.memory_process import Hippocampus
from memory.short_term import ShortTermMemory
from persona.state_manager import StateManager

logger = logging.getLogger(__name__)


class ToolEnabledBrain:
    """
    支持工具调用的 Brain 扩展 Mixin

    使用方法:
        class MyBrain(Brain, ToolEnabledBrain):
            def __init__(self, event_bus, state_manager, memory, hippocampus):
                Brain.__init__(self, event_bus, state_manager, memory, hippocampus)
                ToolEnabledBrain.__init__(self, event_bus)
    """

    # 工具调用标签的正则表达式 - 支持多种格式
    # 格式1: OpenAI风格代码块
    FUNCTION_CALL_PATTERN = re.compile(
        r'```tool_call\s*\n(.*?)\n```',
        re.DOTALL | re.IGNORECASE
    )

    # 格式2: XML标签（严格格式）
    XML_TOOL_PATTERN = re.compile(
        r'<tool_call>\s*<name>(.*?)</name>\s*<parameters>(.*?)</parameters>\s*</tool_call>',
        re.DOTALL | re.IGNORECASE
    )

    # 格式3: JSON格式（保留现有格式）
    JSON_TOOL_PATTERN = re.compile(
        r'<tool_call>\s*(\{.*?\})\s*</tool_call>',
        re.DOTALL | re.IGNORECASE
    )

    # 向后兼容：保留原名
    TOOL_CALL_PATTERN = JSON_TOOL_PATTERN

    # 最大单次对话工具调用次数，防止循环
    MAX_TOOL_CALLS_PER_TURN = 3

    def __init__(
        self,
        event_bus: EventBus,
        hippocampus: Optional[Hippocampus] = None,
        enable_default_tools: bool = True,
        enable_dynamic_selection: bool = True,
        enable_intent_recognition: bool = True,
    ):
        """
        初始化工具支持

        Args:
            event_bus: 事件总线
            hippocampus: 海马体实例（用于记忆工具）
            enable_default_tools: 是否启用默认工具集
            enable_dynamic_selection: 是否启用动态工具选择
            enable_intent_recognition: 是否启用意图识别
        """
        self.event_bus = event_bus
        self.hippocampus = hippocampus
        self.tool_registry = ToolRegistry()
        self.tool_executor = ToolExecutor(self.tool_registry)

        # 动态工具选择（创建独立实例，避免全局单例的线程安全问题）
        self.enable_dynamic_selection = enable_dynamic_selection
        self.tool_selector = ToolSelector() if enable_dynamic_selection else None

        # 意图识别
        self.enable_intent_recognition = enable_intent_recognition
        self.intent_recognizer = get_intent_recognizer() if enable_intent_recognition else None

        # 工具调用统计
        self._tool_call_count = 0
        self._tool_results_buffer: list[dict] = []
        self._selected_tools_for_current_turn: Optional[List[str]] = None  # 动态选择的工具

        # 如果启用默认工具，注册它们
        if enable_default_tools:
            self._register_default_tools()


        # 订阅事件
        self.event_bus.subscribe("brain.tool_call", self._on_tool_call)

    def _register_default_tools(self):
        """注册默认工具集"""
        # Phase 1 基础工具
        self.tool_registry.register(TimeTool(self.event_bus))
        self.tool_registry.register(FileTool())
        self.tool_registry.register(NoteTool())

        # 记忆管理工具（需要 hippocampus）
        if self.hippocampus:
            self.tool_registry.register(RememberTool(hippocampus=self.hippocampus))
            self.tool_registry.register(RecallCheckTool())

        logger.info(f"已注册 {len(self.tool_registry)} 个默认工具")

        # 更新选择器可用工具列表
        if self.tool_selector:
            self.tool_selector.set_available_tools(self.tool_registry.list_tools())

    def _on_tool_call(self, event: Event):
        """处理显式工具调用事件"""
        tool_name = event.data.get("tool_name")
        params = event.data.get("params", {})

        if tool_name:
            result = self.tool_executor.execute(tool_name, params)
            self.event_bus.publish(
                Event(name="tool.result", data={
                    "tool_name": tool_name,
                    "result": result,
                })
            )

    def process_with_tools(
        self,
        user_message: str,
        memory: ShortTermMemory,
        state_manager: StateManager,
        base_process_func: Any,
    ) -> str:
        """
        处理带工具支持的对话（支持意图识别和动态工具选择）

        Args:
            user_message: 用户输入
            memory: 短期记忆
            state_manager: 状态管理器
            base_process_func: 基础处理函数（Brain.process_dialogue 的原始逻辑）

        Returns:
            最终回复文本
        """
        self._tool_call_count = 0
        self._tool_results_buffer = []

        # 检查是否是显式工具命令（如 /time）
        explicit_tool_result = self._check_explicit_tool_command(user_message)
        if explicit_tool_result:
            return explicit_tool_result

        # 意图识别：检查是否需要工具
        if self.enable_intent_recognition and self.intent_recognizer:
            intent_result = self.intent_recognizer.recognize(user_message)
            logger.debug(f"工具意图识别: {intent_result.intent.name}, 置信度={intent_result.confidence:.2f}")

            if intent_result.intent == ToolIntent.NO_TOOL_NEEDED:
                # 不需要工具，跳过工具处理
                return base_process_func(user_message)

        # 动态工具选择：确定要注入哪些工具说明
        self._selected_tools_for_current_turn = None
        if self.enable_dynamic_selection and self.tool_selector:
            available_tools = self.tool_registry.list_tools()
            self._selected_tools_for_current_turn = self.tool_selector.select_tools(
                user_message,
                available_tools,
                max_tools=3
            )
            logger.debug(f"动态工具选择: 选中={self._selected_tools_for_current_turn}")

        # 正常处理流程，但注入工具说明
        return base_process_func(user_message)

    def _check_explicit_tool_command(self, message: str) -> Optional[str]:
        """
        检查是否是显式工具命令

        支持格式:
        - /tool_name param1 param2
        - /time
        - /note create "title" "content"

        Returns:
            如果是工具命令，返回执行结果；否则返回 None
        """
        message = message.strip()

        # 检查是否以 / 开头
        if not message.startswith('/'):
            return None

        # 解析命令
        parts = message[1:].split(maxsplit=1)
        if not parts:
            return None

        tool_name = parts[0]
        args_str = parts[1] if len(parts) > 1 else ""

        # 查找工具
        tool = self.tool_registry.get(tool_name)
        if not tool:
            return None  # 不是已知工具命令

        # 构建参数
        params = self._parse_tool_args(args_str, tool.parameters)

        # 执行工具
        result = self.tool_executor.execute(tool_name, params)

        if result.success:
            return f"[{tool_name}] {result.data}"
        else:
            return f"[{tool_name}] 错误: {result.error}"

    def _parse_tool_args(self, args_str: str, params_schema: dict) -> dict:
        """解析工具参数字符串"""
        params = {}
        properties = params_schema.get("properties", {})

        # 简单解析：尝试按空格分割，支持引号
        if args_str:
            # 尝试作为 JSON 解析
            try:
                params = json.loads(args_str)
            except json.JSONDecodeError:
                # 简化的命令行解析
                current_key = None
                current_value = []

                for part in args_str.split():
                    if '=' in part and not current_key:
                        key, value = part.split('=', 1)
                        params[key] = value.strip('"\'')
                    else:
                        # 默认第一个参数是 operation 或 content
                        if "operation" in properties and "operation" not in params:
                            params["operation"] = part
                        elif "content" in properties and "content" not in params:
                            params["content"] = part

        return params

    def extract_tool_calls(self, text: str) -> list[dict]:
        """
        从文本中提取工具调用（支持多种格式）

        Args:
            text: LLM 输出的文本

        Returns:
            工具调用列表 [{"name": str, "parameters": dict}]
        """
        calls = []

        # 格式1: 尝试代码块格式 ```tool_call
        for match in self.FUNCTION_CALL_PATTERN.finditer(text):
            try:
                call_data = json.loads(match.group(1))
                if "name" in call_data:
                    calls.append({
                        "name": call_data["name"],
                        "parameters": call_data.get("parameters", {}),
                    })
            except json.JSONDecodeError as e:
                logger.debug(f"代码块格式解析失败: {e}")

        # 格式2: 尝试XML格式 <tool_call><name>...</name><parameters>...</parameters></tool_call>
        for match in self.XML_TOOL_PATTERN.finditer(text):
            try:
                name = match.group(1).strip()
                params_str = match.group(2).strip()
                params = json.loads(params_str) if params_str else {}
                calls.append({"name": name, "parameters": params})
            except json.JSONDecodeError as e:
                logger.debug(f"XML格式解析失败: {e}")

        # 格式3: 尝试JSON格式 <tool_call>{"name": ..., "parameters": ...}</tool_call>
        for match in self.JSON_TOOL_PATTERN.finditer(text):
            try:
                call_data = json.loads(match.group(1))
                if "name" in call_data:
                    calls.append({
                        "name": call_data["name"],
                        "parameters": call_data.get("parameters", {}),
                    })
            except json.JSONDecodeError as e:
                logger.warning(f"JSON格式解析工具调用失败: {e}")

        return calls

    def remove_tool_calls(self, text: str) -> str:
        """
        从文本中移除工具调用标签（支持所有格式）

        Args:
            text: 原始文本

        Returns:
            清理后的文本
        """
        # 移除代码块格式
        text = self.FUNCTION_CALL_PATTERN.sub('', text)
        # 移除XML格式
        text = self.XML_TOOL_PATTERN.sub('', text)
        # 移除JSON格式
        text = self.JSON_TOOL_PATTERN.sub('', text)
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
                results.append({
                    "tool_name": call["name"],
                    "result": ToolResult.fail("单次对话工具调用次数已达上限"),
                })
                break

            self._tool_call_count += 1
            result = self.tool_executor.execute(call["name"], call["parameters"])
            results.append({
                "tool_name": call["name"],
                "result": result,
            })

        return results

    def format_tool_results_for_prompt(self, results: list[dict], use_summarization: bool = True) -> str:
        """
        格式化工具结果为 prompt 文本（支持摘要）

        Args:
            results: 工具执行结果
            use_summarization: 是否使用工具自带的摘要方法

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
                if use_summarization and tool:
                    summary = tool.summarize_result(result, max_length=200)
                    lines.append(f"- {tool_name}: {summary}")
                else:
                    # 回退到简单JSON序列化（截断）
                    data_str = json.dumps(result.data, ensure_ascii=False, default=str)
                    if len(data_str) > 200:
                        data_str = data_str[:200] + "..."
                    lines.append(f"- {tool_name}: {data_str}")
            else:
                lines.append(f"- {tool_name}: 失败 - {result.error}")

        return "\n".join(lines)

    def build_system_prompt_with_tools(
        self,
        base_prompt: str,
        compact: bool = True,
        selected_tools: Optional[List[str]] = None
    ) -> str:
        """
        构建包含工具说明的 system prompt（支持精简模式和动态工具选择）

        Args:
            base_prompt: 基础 system prompt
            compact: 是否使用精简描述（节省token）
            selected_tools: 要包含的工具名称列表，None表示使用动态选择的工具

        Returns:
            增强后的 system prompt
        """
        if len(self.tool_registry) == 0:
            return base_prompt

        # 如果没有指定工具列表，使用动态选择的工具
        if selected_tools is None and self._selected_tools_for_current_turn is not None:
            selected_tools = self._selected_tools_for_current_turn

        tool_guidelines = self.tool_registry.get_tools_description_for_prompt(
            compact=compact,
            include_examples=True,
            tool_names=selected_tools
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

    def register_tool(self, tool):
        """便捷方法：注册工具"""
        result = self.tool_registry.register(tool)
        # 同步更新选择器的可用工具列表
        if result and self.tool_selector:
            self.tool_selector.set_available_tools(self.tool_registry.list_tools())
        return result

    def unregister_tool(self, name: str):
        """便捷方法：注销工具"""
        result = self.tool_registry.unregister(name)
        # 同步更新选择器的可用工具列表
        if result and self.tool_selector:
            self.tool_selector.set_available_tools(self.tool_registry.list_tools())
        return result
