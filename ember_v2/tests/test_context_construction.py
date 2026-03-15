"""
Context Construction Package 测试
"""
import pytest
from datetime import datetime

from ember_v2.packages.context_construction import (
    ContextConstruction,
    Message,
    BuildOptions,
    TokenInfo
)


class TestContextConstructionBasic:
    """测试基础功能"""
    
    def test_init_default(self):
        """测试默认初始化"""
        ctx = ContextConstruction()
        
        assert ctx._window_size == 20
        assert ctx._system_prompt == ""
        assert len(ctx._history) == 0
    
    def test_init_with_params(self):
        """测试带参数初始化"""
        ctx = ContextConstruction(
            system_prompt="你是依鸣",
            window_size=10
        )
        
        assert ctx._window_size == 10
        assert ctx._system_prompt == "你是依鸣"
    
    def test_set_system_prompt(self):
        """测试设置系统提示"""
        ctx = ContextConstruction()
        ctx.set_system_prompt("新的人设")
        
        assert ctx.get_system_prompt() == "新的人设"


class TestMessageStorage:
    """测试消息存储"""
    
    def test_add_message(self):
        """测试添加消息"""
        ctx = ContextConstruction()
        ctx.add_message("user", "你好")
        ctx.add_message("assistant", "你好呀！")
        
        assert ctx.get_history_count() == 2
    
    def test_add_messages_batch(self):
        """测试批量添加消息"""
        ctx = ContextConstruction()
        messages = [
            {"role": "user", "content": "你好"},
            {"role": "assistant", "content": "你好呀！"},
            {"role": "user", "content": "今天怎么样？"}
        ]
        ctx.add_messages(messages)
        
        assert ctx.get_history_count() == 3
    
    def test_sliding_window(self):
        """测试滑动窗口"""
        ctx = ContextConstruction(window_size=5)
        
        # 添加 10 条消息
        for i in range(10):
            ctx.add_message("user", f"消息 {i}")
        
        # 应该只保留最后 5 条
        assert ctx.get_history_count() == 5
        
        # 检查是最新的 5 条
        recent = ctx.get_recent_messages()
        assert recent[0]["content"] == "消息 5"
        assert recent[4]["content"] == "消息 9"
    
    def test_get_recent_messages(self):
        """测试获取最近消息"""
        ctx = ContextConstruction()
        for i in range(5):
            ctx.add_message("user", f"消息 {i}")
        
        # 获取最近 3 条
        recent = ctx.get_recent_messages(k=3)
        assert len(recent) == 3
        assert recent[0]["content"] == "消息 2"
    
    def test_clear_history(self):
        """测试清空历史"""
        ctx = ContextConstruction()
        ctx.add_message("user", "测试")
        ctx.clear_history()
        
        assert ctx.get_history_count() == 0


class TestBuildContext:
    """测试上下文构建"""
    
    def test_build_simple(self):
        """测试简单构建"""
        ctx = ContextConstruction(system_prompt="你是助手")
        ctx.add_message("user", "你好")
        
        messages = ctx.build_simple()
        
        assert len(messages) == 2
        assert messages[0]["role"] == "system"
        assert messages[0]["content"] == "你是助手"
        assert messages[1]["role"] == "user"
    
    def test_build_with_dynamic_sections(self):
        """测试带动态段落构建"""
        ctx = ContextConstruction(system_prompt="你是助手")
        ctx.add_message("user", "你好")
        ctx.add_context_section("time", "现在是2024年3月15日")
        ctx.add_context_section("state", "心情：愉悦")
        
        messages = ctx.build()
        
        # system + time + state + user
        assert len(messages) == 4
        assert messages[1]["content"] == "现在是2024年3月15日"
        assert messages[2]["content"] == "心情：愉悦"
    
    def test_build_without_history(self):
        """测试不包含历史"""
        ctx = ContextConstruction(system_prompt="你是助手")
        ctx.add_message("user", "你好")
        ctx.add_context_section("time", "现在时间")
        
        options = BuildOptions(include_history=False)
        messages = ctx.build(options)
        
        # 只有 system + dynamic
        assert len(messages) == 2
    
    def test_build_with_history_limit(self):
        """测试限制历史条数"""
        ctx = ContextConstruction(system_prompt="你是助手")
        for i in range(10):
            ctx.add_message("user", f"消息 {i}")
        
        options = BuildOptions(history_limit=3)
        messages = ctx.build(options)
        
        # system + 3 条历史
        assert len(messages) == 4


class TestTemplates:
    """测试预设模板"""
    
    def test_build_for_dialogue(self):
        """测试对话模板"""
        ctx = ContextConstruction(system_prompt="你是依鸣")
        ctx.add_message("user", "你好")
        
        state = {
            "pleasure": 0.8,
            "arousal": 0.6,
            "dominance": 0.5
        }
        
        messages = ctx.build_for_dialogue(state=state, memory="昨天聊了算法")
        
        # system + time + state + memory + history
        assert len(messages) >= 4
        # 检查包含状态信息
        assert any("愉悦度" in m.get("content", "") for m in messages)
        # 检查包含记忆
        assert any("脑海闪现的记忆" in m.get("content", "") for m in messages)
    
    def test_build_for_idle(self):
        """测试闲置模板"""
        ctx = ContextConstruction(system_prompt="你是依鸣")
        
        state = {"pleasure": 0.5, "arousal": 0.3}
        messages = ctx.build_for_idle(state=state, idle_duration="2小时")
        
        # 闲置模板不包含历史
        assert len(messages) >= 3
        # 检查包含闲置时长
        assert any("已过去" in m.get("content", "") for m in messages)
    
    def test_build_for_state_update(self):
        """测试状态更新模板"""
        ctx = ContextConstruction(system_prompt="你是依鸣")
        
        state = {"pleasure": 0.5}
        messages = ctx.build_for_state_update(state, idle_duration="30分钟")
        
        assert len(messages) == 2
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"
        assert "已过去" in messages[1]["content"]


class TestDynamicSections:
    """测试动态段落管理"""
    
    def test_add_and_clear_sections(self):
        """测试添加和清空段落"""
        ctx = ContextConstruction()
        
        ctx.add_context_section("time", "时间内容")
        ctx.add_context_section("state", "状态内容")
        
        assert len(ctx._dynamic_sections) == 2
        
        ctx.clear_dynamic_sections()
        assert len(ctx._dynamic_sections) == 0
    
    def test_section_position_sorting(self):
        """测试段落排序"""
        ctx = ContextConstruction()
        
        # 添加时指定不同位置
        ctx.add_context_section("c", "第三个", position=3)
        ctx.add_context_section("a", "第一个", position=1)
        ctx.add_context_section("b", "第二个", position=2)
        
        # 检查排序
        names = [s.name for s in ctx._dynamic_sections]
        assert names == ["a", "b", "c"]
    
    def test_replace_section(self):
        """测试替换同名段落"""
        ctx = ContextConstruction()
        
        ctx.add_context_section("time", "旧时间")
        ctx.add_context_section("time", "新时间")
        
        assert len(ctx._dynamic_sections) == 1
        assert ctx._dynamic_sections[0].content == "新时间"


class TestTokenCount:
    """测试 Token 计数"""
    
    def test_simple_count(self):
        """测试简单估算"""
        ctx = ContextConstruction(system_prompt="你是助手")
        
        # 纯英文
        count_en = ctx.count_tokens("Hello world")
        assert count_en > 0
        
        # 纯中文
        count_cn = ctx.count_tokens("你好世界")
        assert count_cn > 0
    
    def test_token_info(self):
        """测试 Token 信息"""
        ctx = ContextConstruction(system_prompt="你是助手")
        ctx.add_message("user", "你好")
        ctx.add_context_section("time", "现在时间")
        
        info = ctx.get_token_info()
        
        assert info.system > 0
        assert info.history > 0
        assert info.dynamic > 0
        assert info.total == info.system + info.history + info.dynamic
    
    def test_custom_token_counter(self):
        """测试自定义计数器"""
        ctx = ContextConstruction()
        
        # 设置自定义计数器（简单返回长度）
        ctx.set_token_counter(lambda text: len(text))
        
        count = ctx.count_tokens("hello")
        assert count == 5


class TestCacheControl:
    """测试 Cache 标记"""
    
    def test_build_with_cache_control(self):
        """测试带 Cache 标记构建"""
        ctx = ContextConstruction(system_prompt="你是助手")
        ctx.add_message("user", "你好")
        
        messages = ctx.get_messages_for_cache(cache_static=True)
        
        # 检查第一条消息有 cache_control
        assert "cache_control" in messages[0]
        assert messages[0]["cache_control"]["type"] == "ephemeral"


class TestTimeFormatter:
    """测试时间格式化"""
    
    def test_default_time_format(self):
        """测试默认时间格式"""
        ctx = ContextConstruction()
        
        formatted = ctx._format_time(1709500800)  # 2024-03-04 00:00:00 UTC
        
        assert "年" in formatted
        assert "月" in formatted
    
    def test_custom_time_formatter(self):
        """测试自定义时间格式化"""
        ctx = ContextConstruction()
        
        ctx.set_time_formatter(lambda ts: f"时间戳: {ts}")
        
        formatted = ctx._format_time(12345)
        assert formatted == "时间戳: 12345"


class TestPeek:
    """测试预览功能"""
    
    def test_peek_empty(self):
        """测试空历史预览"""
        ctx = ContextConstruction()
        
        result = ctx.peek()
        assert "无历史消息" in result
    
    def test_peek_with_history(self):
        """测试有历史预览"""
        ctx = ContextConstruction()
        ctx.add_message("user", "这是一条很长的消息内容" * 10)
        ctx.add_message("assistant", "回复")
        
        result = ctx.peek(last_k=2)
        
        assert "user" in result
        assert "assistant" in result
        assert "..." in result  # 应该被截断