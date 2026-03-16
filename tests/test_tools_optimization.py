"""
工具系统优化测试

验证 Phase 1-3 的优化实现：
1. Token 消耗优化
2. 动态工具选择
3. 意图识别
4. 多格式工具调用解析
5. 插件系统
"""
import pytest
from tools import (
    BaseTool, ToolResult, ToolPermission,
    ToolRegistry, ToolSelector, ToolIntentRecognizer,
    ToolPluginManager, create_tool_template,
    needs_tool, ToolIntent, get_tool_selector
)
from tools.builtin import TimeTool, FileTool, NoteTool
from tools.brain_mixin import ToolEnabledBrain


class TestCompactDescriptions:
    """测试精简工具描述"""

    def test_compact_description_shorter_than_full(self):
        """精简描述应该比完整描述短"""
        tool = TimeTool()
        full = tool.get_tool_description_for_prompt()
        compact = tool.get_compact_prompt_description()
        assert len(compact) < len(full)
        assert tool.name in compact

    def test_compact_description_format(self):
        """精简描述格式正确"""
        tool = TimeTool()
        compact = tool.get_compact_prompt_description()
        assert compact.startswith(f"- {tool.name}:")

    def test_examples_text(self):
        """示例文本生成正确"""
        tool = TimeTool()
        examples = tool.get_examples_text()
        if tool.examples:
            assert "示例:" in examples
            assert "tool_call" in examples


class TestRegistryCompactMode:
    """测试注册中心精简模式"""

    def test_compact_mode_reduces_tokens(self):
        """精简模式减少token消耗"""
        registry = ToolRegistry()
        registry.register(TimeTool())
        registry.register(FileTool())
        registry.register(NoteTool())

        full = registry.get_tools_description_for_prompt(compact=False)
        compact = registry.get_tools_description_for_prompt(compact=True)

        assert len(compact) < len(full)
        assert "【可用工具】" in compact

    def test_dynamic_tool_selection(self):
        """动态工具选择只返回指定工具"""
        registry = ToolRegistry()
        registry.register(TimeTool())
        registry.register(FileTool())

        selected = registry.get_tools_description_for_prompt(
            tool_names=["time_tool"],
            compact=True
        )
        assert "time_tool" in selected
        assert "file_tool" not in selected


class TestToolSelector:
    """测试动态工具选择器"""

    def test_select_time_tool_for_time_query(self):
        """时间查询选择时间工具"""
        selector = ToolSelector()
        available = ["time_tool", "remember_tool", "file_tool"]

        selected = selector.select_tools("现在几点了？", available)
        assert "time_tool" in selected

    def test_select_memory_tool_for_memory_query(self):
        """记忆查询选择记忆工具"""
        selector = ToolSelector()
        available = ["time_tool", "remember_tool", "recall_check_tool"]

        selected = selector.select_tools("记得我喜欢咖啡吗？", available)
        assert "recall_check_tool" in selected or "remember_tool" in selected

    def test_no_tools_for_casual_chat(self):
        """闲聊不选择工具"""
        selector = ToolSelector()
        available = ["time_tool", "remember_tool"]

        selected = selector.select_tools("今天天气不错", available, min_relevance=0.5)
        assert len(selected) == 0

    def test_max_tools_limit(self):
        """最大工具数量限制"""
        selector = ToolSelector()
        available = ["time_tool", "remember_tool", "file_tool", "note_tool"]

        selected = selector.select_tools("时间和笔记", available, max_tools=2)
        assert len(selected) <= 2


class TestIntentRecognizer:
    """测试意图识别器"""

    def test_definitely_needs_tool_for_time(self):
        """明确需要工具的时间查询"""
        recognizer = ToolIntentRecognizer()
        result = recognizer.recognize("现在几点了？")

        assert result.intent == ToolIntent.DEFINITELY_NEEDS_TOOL
        assert recognizer.needs_tool("现在几点了？")

    def test_no_tool_needed_for_greeting(self):
        """问候不需要工具"""
        recognizer = ToolIntentRecognizer()
        result = recognizer.recognize("你好")

        assert result.intent == ToolIntent.NO_TOOL_NEEDED
        assert not recognizer.needs_tool("你好")

    def test_no_tool_needed_for_thanks(self):
        """感谢不需要工具"""
        recognizer = ToolIntentRecognizer()

        assert not recognizer.needs_tool("谢谢")
        assert not recognizer.needs_tool("哈哈")
        assert not recognizer.needs_tool("好的")

    def test_suggested_tools_for_memory(self):
        """记忆查询建议相关工具"""
        recognizer = ToolIntentRecognizer()
        result = recognizer.recognize("记住我喜欢咖啡")

        assert "remember_tool" in result.suggested_tools


class TestMultiFormatToolCallParsing:
    """测试多格式工具调用解析"""

    def setup_method(self):
        class MockBrain(ToolEnabledBrain):
            def __init__(self):
                self._tool_call_count = 0
                self._tool_results_buffer = []
        self.brain = MockBrain()

    def test_parse_json_format(self):
        """解析JSON格式"""
        text = '<tool_call>{"name": "time_tool", "parameters": {"format": "human"}}</tool_call>'
        calls = self.brain.extract_tool_calls(text)

        assert len(calls) == 1
        assert calls[0]["name"] == "time_tool"
        assert calls[0]["parameters"]["format"] == "human"

    def test_parse_code_block_format(self):
        """解析代码块格式"""
        text = '''```tool_call
{"name": "time_tool", "parameters": {"format": "human"}}
```'''
        calls = self.brain.extract_tool_calls(text)

        assert len(calls) == 1
        assert calls[0]["name"] == "time_tool"

    def test_parse_xml_format(self):
        """解析XML格式"""
        text = '<tool_call><name>time_tool</name><parameters>{"format": "human"}</parameters></tool_call>'
        calls = self.brain.extract_tool_calls(text)

        assert len(calls) == 1
        assert calls[0]["name"] == "time_tool"

    def test_remove_tool_calls(self):
        """移除工具调用标签"""
        text = 'Hello <tool_call>{"name": "x"}</tool_call> world'
        cleaned = self.brain.remove_tool_calls(text)

        assert "<tool_call>" not in cleaned
        assert "Hello" in cleaned
        assert "world" in cleaned


class TestToolResultSummarization:
    """测试工具结果摘要"""

    def test_summarize_string_result(self):
        """摘要字符串结果"""
        tool = TimeTool()
        result = ToolResult.ok(data="2024-01-01 12:00")

        summary = tool.summarize_result(result)
        assert "2024-01-01 12:00" in summary

    def test_summarize_dict_result(self):
        """摘要字典结果"""
        tool = TimeTool()
        result = ToolResult.ok(data={"message": "Success", "count": 5})

        summary = tool.summarize_result(result)
        assert "Success" in summary

    def test_summarize_list_result(self):
        """摘要列表结果"""
        tool = TimeTool()
        result = ToolResult.ok(data=[1, 2, 3, 4, 5])

        summary = tool.summarize_result(result)
        assert "5条数据" in summary

    def test_summarize_failure(self):
        """摘要失败结果"""
        tool = TimeTool()
        result = ToolResult.fail("Something went wrong")

        summary = tool.summarize_result(result)
        assert "失败" in summary or "Something went wrong" in summary


class TestPluginManager:
    """测试插件管理器"""

    def test_discover_tools_from_directory(self, tmp_path):
        """从目录发现工具"""
        plugin_dir = tmp_path / "tools" / "plugins"
        plugin_dir.mkdir(parents=True)

        # 创建测试工具文件
        tool_file = plugin_dir / "test_tool.py"
        tool_file.write_text('''
from tools.base import BaseTool, ToolResult, ToolPermission

class TestTool(BaseTool):
    name = "test_plugin_tool"
    description = "A test tool"
    short_description = "Test tool"
    permission = ToolPermission.READONLY

    parameters = {"type": "object", "properties": {}}

    def execute(self, params):
        return ToolResult.ok(data="test")
''')

        manager = ToolPluginManager(str(plugin_dir))
        tools = manager.discover_tools()

        assert len(tools) == 1
        assert tools[0].name == "test_plugin_tool"

    def test_create_tool_template(self, tmp_path):
        """创建工具模板"""
        path = create_tool_template("weather_tool", str(tmp_path))

        assert path.exists()
        content = path.read_text(encoding="utf-8")
        assert "class WeatherTool" in content
        assert 'name = "weather_tool"' in content


class TestIntegration:
    """集成测试"""

    def test_full_workflow_with_dynamic_selection(self):
        """完整流程：动态选择 + 意图识别"""
        # 创建注册中心
        registry = ToolRegistry()
        registry.register(TimeTool())
        registry.register(FileTool())
        registry.register(NoteTool())

        # 用户查询
        user_message = "现在几点了？"

        # 步骤1: 意图识别
        recognizer = ToolIntentRecognizer()
        if not recognizer.needs_tool(user_message):
            pytest.skip("Should need tool")

        # 步骤2: 动态工具选择
        selector = get_tool_selector()
        selector.set_available_tools(registry.list_tools())
        selected = selector.select_tools(user_message, registry.list_tools())

        assert "time_tool" in selected

        # 步骤3: 生成精简描述
        tool_desc = registry.get_tools_description_for_prompt(
            tool_names=selected,
            compact=True
        )

        assert "time_tool" in tool_desc
        assert "file_tool" not in tool_desc  # 未被选择的工具不应出现


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
