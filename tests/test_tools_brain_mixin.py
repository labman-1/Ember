"""
测试 ToolEnabledBrain Mixin

覆盖工具调用解析、集成到对话流程的功能。
"""
import pytest
from unittest.mock import Mock, MagicMock
from tools.brain_mixin import ToolEnabledBrain
from tools.base import ToolResult


class MockEventBus:
    """模拟 EventBus"""
    def __init__(self):
        self.subscribers = {}

    def subscribe(self, event_name, callback):
        self.subscribers[event_name] = callback

    def publish(self, event):
        pass


class TestToolEnabledBrain:
    """测试 ToolEnabledBrain Mixin"""

    @pytest.fixture
    def brain_mixin(self):
        mock_bus = MockEventBus()
        return ToolEnabledBrain(mock_bus, enable_default_tools=False)

    @pytest.fixture
    def brain_mixin_with_tools(self):
        mock_bus = MockEventBus()
        mixin = ToolEnabledBrain(mock_bus, enable_default_tools=True)
        return mixin

    def test_initialization(self, brain_mixin):
        """测试初始化"""
        assert brain_mixin.tool_registry is not None
        assert brain_mixin.tool_executor is not None
        assert len(brain_mixin.tool_registry) == 0  # 无默认工具

    def test_initialization_with_default_tools(self, brain_mixin_with_tools):
        """测试带默认工具的初始化"""
        assert len(brain_mixin_with_tools.tool_registry) > 0
        # 应该包含 time_tool、file_tool、note_tool 等
        assert "time_tool" in brain_mixin_with_tools.tool_registry

    def test_extract_tool_calls_single(self, brain_mixin):
        """测试提取单个工具调用"""
        text = '''<thought>需要获取时间</thought>
<tool_call>{"name": "time_tool", "parameters": {"format": "human"}}</tool_call>
现在几点了？'''

        calls = brain_mixin.extract_tool_calls(text)
        assert len(calls) == 1
        assert calls[0]["name"] == "time_tool"
        assert calls[0]["parameters"]["format"] == "human"

    def test_extract_tool_calls_multiple(self, brain_mixin):
        """测试提取多个工具调用"""
        text = '''<tool_call>{"name": "time_tool", "parameters": {}}</tool_call>
一些文本
<tool_call>{"name": "note_tool", "parameters": {"operation": "list"}}</tool_call>'''

        calls = brain_mixin.extract_tool_calls(text)
        assert len(calls) == 2
        assert calls[0]["name"] == "time_tool"
        assert calls[1]["name"] == "note_tool"

    def test_extract_tool_calls_invalid_json(self, brain_mixin):
        """测试提取无效的 JSON"""
        text = '<tool_call>{"invalid json}</tool_call>'
        calls = brain_mixin.extract_tool_calls(text)
        assert len(calls) == 0  # 应该忽略无效调用

    def test_extract_tool_calls_no_calls(self, brain_mixin):
        """测试无工具调用的文本"""
        text = "这是一段普通文本，没有任何工具调用"
        calls = brain_mixin.extract_tool_calls(text)
        assert len(calls) == 0

    def test_remove_tool_calls(self, brain_mixin):
        """测试移除工具调用标签"""
        text = '''<thought>思考内容</thought>
<tool_call>{"name": "time_tool"}</tool_call>
这是回复内容'''

        cleaned = brain_mixin.remove_tool_calls(text)
        assert "<tool_call>" not in cleaned
        assert "</tool_call>" not in cleaned
        assert "这是回复内容" in cleaned

    def test_check_explicit_tool_command(self, brain_mixin_with_tools):
        """测试显式工具命令检查"""
        result = brain_mixin_with_tools._check_explicit_tool_command("/time_tool")
        assert result is not None
        assert "time_tool" in result

    def test_check_explicit_tool_command_unknown(self, brain_mixin_with_tools):
        """测试未知工具命令"""
        result = brain_mixin_with_tools._check_explicit_tool_command("/unknown_tool")
        assert result is None  # 未知工具返回 None

    def test_check_explicit_tool_command_not_command(self, brain_mixin):
        """测试非命令输入"""
        result = brain_mixin._check_explicit_tool_command("这是普通消息")
        assert result is None

    def test_format_tool_results_for_prompt(self, brain_mixin):
        """测试格式化工具结果"""
        results = [
            {"tool_name": "time_tool", "result": ToolResult.ok(data="2024-01-01")},
            {"tool_name": "error_tool", "result": ToolResult.fail("出错了")},
        ]

        formatted = brain_mixin.format_tool_results_for_prompt(results)
        assert "[工具执行结果]" in formatted
        assert "2024-01-01" in formatted
        assert "失败" in formatted

    def test_format_empty_results(self, brain_mixin):
        """测试格式化空结果"""
        formatted = brain_mixin.format_tool_results_for_prompt([])
        assert formatted == ""

    def test_build_system_prompt_with_tools(self, brain_mixin_with_tools):
        """测试构建带工具的 system prompt"""
        base_prompt = "这是基础提示词"
        enhanced = brain_mixin_with_tools.build_system_prompt_with_tools(base_prompt)

        assert base_prompt in enhanced
        assert "你可以使用以下工具" in enhanced
        assert "time_tool" in enhanced

    def test_build_system_prompt_without_tools(self, brain_mixin):
        """测试无工具时的 system prompt"""
        base_prompt = "这是基础提示词"
        result = brain_mixin.build_system_prompt_with_tools(base_prompt)
        assert result == base_prompt  # 没有工具时不添加

    def test_get_tool_stats(self, brain_mixin_with_tools):
        """测试获取工具统计"""
        stats = brain_mixin_with_tools.get_tool_stats()
        assert "registry" in stats
        assert "executor" in stats

    def test_register_and_unregister_tool(self, brain_mixin):
        """测试注册和注销工具"""
        from tools.base import BaseTool, ToolResult, ToolPermission

        class MockCustomTool(BaseTool):
            name = "mock_custom_tool"
            description = "Test"
            parameters = {"type": "object", "properties": {}}
            permission = ToolPermission.READONLY

            def execute(self, params):
                return ToolResult.ok()

        # 注册
        brain_mixin.register_tool(MockCustomTool())
        assert "mock_custom_tool" in brain_mixin.tool_registry

        # 注销
        brain_mixin.unregister_tool("mock_custom_tool")
        assert "mock_custom_tool" not in brain_mixin.tool_registry


class TestToolEnabledBrainLimits:
    """测试工具调用限制"""

    @pytest.fixture
    def brain_mixin(self):
        mock_bus = MockEventBus()
        return ToolEnabledBrain(mock_bus, enable_default_tools=True)

    def test_max_tool_calls_per_turn(self, brain_mixin):
        """测试单次对话最大调用次数限制"""
        # 模拟多次调用
        calls = [{"name": "time_tool", "parameters": {}} for _ in range(5)]

        results = brain_mixin.execute_tool_calls(calls)

        # 最多执行 MAX_TOOL_CALLS_PER_TURN 次
        assert len(results) <= brain_mixin.MAX_TOOL_CALLS_PER_TURN + 1
        # 后面的调用应该返回限制错误
        if len(results) > brain_mixin.MAX_TOOL_CALLS_PER_TURN:
            assert "已达上限" in str(results[-1]["result"].error)
