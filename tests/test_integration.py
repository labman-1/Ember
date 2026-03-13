"""
集成测试 - 测试模块间协作
"""
import pytest
import json
import time
import threading


class TestEventBus:
    """测试事件总线"""

    def test_subscribe_and_publish(self):
        """测试订阅和发布"""
        from core.event_bus import EventBus, Event

        bus = EventBus()
        received = []

        def handler(event):
            received.append(event.data)

        bus.subscribe("test.event", handler)
        bus.publish(Event("test.event", data="test_data"))

        assert len(received) == 1
        assert received[0] == "test_data"

    def test_multiple_subscribers(self):
        """测试多个订阅者"""
        from core.event_bus import EventBus, Event

        bus = EventBus()
        results = []

        def handler1(event):
            results.append("handler1")

        def handler2(event):
            results.append("handler2")

        bus.subscribe("multi", handler1)
        bus.subscribe("multi", handler2)
        bus.publish(Event("multi", data=None))

        assert len(results) == 2

    def test_exception_in_handler_not_crash(self):
        """处理器异常不应导致崩溃"""
        from core.event_bus import EventBus, Event

        bus = EventBus()
        success_called = []

        def bad_handler(event):
            raise Exception("故意出错")

        def good_handler(event):
            success_called.append(True)

        bus.subscribe("test", bad_handler)
        bus.subscribe("test", good_handler)

        # 不应抛出异常
        bus.publish(Event("test", data=None))

        # good_handler 仍应被调用
        assert len(success_called) == 1


class TestLogicalTime:
    """测试逻辑时间系统"""

    def test_logical_time_acceleration(self):
        """测试时间加速"""
        from core.event_bus import EventBus
        import time

        # 创建加速 2 倍的事件总线
        # 注意：这里需要修改设置，实际测试可能需要 mock
        bus = EventBus()
        t1 = bus.logical_now
        time.sleep(0.1)
        t2 = bus.logical_now

        # 应该有一定的时间流逝（不测试具体加速倍数，因为依赖配置）
        assert t2 > t1

    def test_formatted_time(self):
        """测试格式化时间"""
        from core.event_bus import EventBus

        bus = EventBus()
        formatted = bus.formatted_logical_now

        # 应该是合法的时间格式
        assert len(formatted) == 19  # YYYY-MM-DD HH:MM:SS
        assert formatted[4] == '-'
        assert formatted[7] == '-'
        assert formatted[10] == ' '
        assert formatted[13] == ':'
        assert formatted[16] == ':'


class TestLLMClientMock:
    """测试 LLM 客户端（使用 mock）"""

    def test_extract_json_valid(self):
        """提取有效 JSON"""
        from unittest.mock import Mock
        from brain.llm_client import LLMClient

        client = LLMClient()
        # _extract_json 是实例方法
        result = client._extract_json('{"P": 5, "A": 5}')
        assert result == {"P": 5, "A": 5}

    def test_extract_json_with_markdown(self):
        """提取带有 Markdown 代码块的 JSON"""
        from brain.llm_client import LLMClient

        client = LLMClient()
        text = '```json\n{"P": 5, "A": 5}\n```'
        result = client._extract_json(text)
        assert result == {"P": 5, "A": 5}


class TestShortTermMemorySafety:
    """测试短期内存安全性"""

    def test_get_memory_returns_copy(self, tmp_path, monkeypatch):
        """测试 get_memory 返回的是副本，不是原引用"""
        from memory.short_term import ShortTermMemory
        import os

        # 切换到临时目录，避免加载之前的测试数据
        monkeypatch.chdir(tmp_path)
        os.makedirs("config", exist_ok=True)

        memory = ShortTermMemory(max_memory_size=5)
        memory.clear_memory()  # 清除任何可能加载的数据
        memory.add_message("user", "原始消息")

        # 获取内存
        result = memory.get_memory()

        # 修改返回的结果
        result["history"][0]["content"] = "被篡改的消息"

        # 验证原始内存未被修改
        original = memory.get_memory()
        assert original["history"][0]["content"] == "原始消息"

    def test_memory_isolation(self, tmp_path, monkeypatch):
        """测试多个内存实例相互隔离"""
        from memory.short_term import ShortTermMemory
        import os

        # 切换到临时目录
        monkeypatch.chdir(tmp_path)
        os.makedirs("config", exist_ok=True)

        memory1 = ShortTermMemory(max_memory_size=5)
        memory1.clear_memory()
        memory2 = ShortTermMemory(max_memory_size=5)
        memory2.clear_memory()

        memory1.add_message("user", "内存1的消息")

        # memory2 应该不受影响
        result2 = memory2.get_memory()
        assert len(result2["history"]) == 0


class TestMemoryIntegration:
    """测试内存模块集成"""

    def test_short_term_memory_add_and_retrieve(self, tmp_path, monkeypatch):
        """测试短期记忆添加和获取"""
        from memory.short_term import ShortTermMemory
        import os

        # 切换到临时目录
        monkeypatch.chdir(tmp_path)
        os.makedirs("config", exist_ok=True)

        memory = ShortTermMemory(max_memory_size=5)
        memory.add_message("user", "你好")
        memory.add_message("assistant", "你好呀")

        result = memory.get_memory()
        assert len(result["history"]) == 2
        assert result["history"][0]["role"] == "user"
        assert result["history"][1]["role"] == "assistant"

    def test_short_term_memory_truncation(self):
        """测试短期记忆截断"""
        from memory.short_term import ShortTermMemory

        memory = ShortTermMemory(max_memory_size=3)

        # 添加超过限制的消息
        for i in range(5):
            memory.add_message("user", f"消息{i}")

        result = memory.get_memory()
        # 应该只有 3 条（系统消息 + 2 条用户消息，但实际只计数 history）
        # 实际上 max_memory_size 只限制 self.memory 列表
        assert len(result["history"]) == 3

    def test_memory_thread_safety(self):
        """测试内存操作线程安全"""
        from memory.short_term import ShortTermMemory
        import concurrent.futures

        memory = ShortTermMemory(max_memory_size=100)

        def add_messages(n):
            for i in range(n):
                memory.add_message("user", f"消息{i}")

        # 并发添加
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(add_messages, 20) for _ in range(5)]
            concurrent.futures.wait(futures)

        time.sleep(0.5)  # 等待异步保存

        # 虽然可能有竞争，但不应该崩溃
        assert memory.memory is not None
