"""
EventBus 异步事件总线测试
"""

import pytest
import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

from ember_v2.core.event_bus import (
    EventBus,
    Event,
    ErrorStrategy,
    EventRegistration,
    Subscription,
)


class TestEventBusInit:
    """测试 EventBus 初始化"""

    def test_init_default(self):
        """测试默认初始化"""
        bus = EventBus()

        assert bus.time_accel_factor == 1.0
        assert bus._emit_errors == True
        assert bus._debug == False

    def test_init_custom(self):
        """测试自定义初始化"""
        start = time.time() - 3600  # 1 小时前
        bus = EventBus(
            time_accel_factor=2.0, start_time=start, emit_errors=False, debug=True
        )

        assert bus.time_accel_factor == 2.0
        assert bus._emit_errors == False
        assert bus._debug == True

    def test_logical_time_normal(self):
        """测试正常时间流逝"""
        bus = EventBus(time_accel_factor=1.0)
        before = bus.logical_now
        time.sleep(0.1)
        after = bus.logical_now

        # 应该过去了约 0.1 秒
        assert after - before >= 0.09

    def test_logical_time_accelerated(self):
        """测试加速时间"""
        bus = EventBus(time_accel_factor=10.0)
        before = bus.logical_now
        time.sleep(0.1)
        after = bus.logical_now

        # 应该过去了约 1 秒（0.1 * 10）
        assert after - before >= 0.9


class TestEventRegistration:
    """测试事件注册"""

    def test_register_event(self):
        """测试注册事件"""
        bus = EventBus()
        bus.register(
            "user.input",
            publishers=["server"],
            subscribers=["brain", "state_manager"],
            description="用户输入事件",
        )

        reg = bus.get_registration("user.input")

        assert reg is not None
        assert reg.event_name == "user.input"
        assert "server" in reg.publishers
        assert "brain" in reg.subscribers
        assert reg.description == "用户输入事件"

    def test_list_events(self):
        """测试列出事件"""
        bus = EventBus()
        bus.register("user.input", ["server"], ["brain"])
        bus.register("system.tick", ["heartbeat"], ["state_manager"])

        events = bus.list_events()

        assert "user.input" in events
        assert "system.tick" in events

    def test_validate_registrations(self):
        """测试验证注册"""
        bus = EventBus()

        # 注册但没有订阅者
        bus.register("orphan.event", ["server"], [])

        # 有订阅者但没有注册
        bus.subscribe("unregistered.event", lambda e: None)

        warnings = bus.validate_registrations()

        assert len(warnings) == 2
        assert any("orphan.event" in w for w in warnings)
        assert any("unregistered.event" in w for w in warnings)


class TestSubscribe:
    """测试订阅功能"""

    def test_subscribe_async(self):
        """测试异步订阅"""
        bus = EventBus()

        async def handler(event):
            pass

        bus.subscribe("test.event", handler, subscriber_name="test_handler")

        assert "test.event" in bus._subscribers
        assert len(bus._subscribers["test.event"]) == 1
        assert bus._subscribers["test.event"][0].callback == handler

    def test_subscribe_sync(self):
        """测试同步订阅"""
        bus = EventBus()

        def handler(event):
            pass

        bus.subscribe("test.event", handler, subscriber_name="sync_handler")

        assert bus._subscribers["test.event"][0].callback == handler

    def test_subscribe_priority(self):
        """测试优先级排序"""
        bus = EventBus()

        async def handler1(event):
            pass

        async def handler2(event):
            pass

        async def handler3(event):
            pass

        bus.subscribe("test.event", handler1, priority=1)
        bus.subscribe("test.event", handler2, priority=10)
        bus.subscribe("test.event", handler3, priority=5)

        # 应该按优先级排序：handler2(10) > handler3(5) > handler1(1)
        assert bus._subscribers["test.event"][0].callback == handler2
        assert bus._subscribers["test.event"][1].callback == handler3
        assert bus._subscribers["test.event"][2].callback == handler1

    def test_unsubscribe(self):
        """测试取消订阅"""
        bus = EventBus()

        def handler(event):
            pass

        bus.subscribe("test.event", handler)
        assert len(bus._subscribers["test.event"]) == 1

        result = bus.unsubscribe("test.event", handler)

        assert result == True
        assert len(bus._subscribers["test.event"]) == 0

    def test_decorator_subscribe(self):
        """测试装饰器订阅"""
        bus = EventBus()

        @bus.on("test.event", subscriber_name="decorated")
        async def handler(event):
            pass

        assert len(bus._subscribers["test.event"]) == 1
        assert bus._subscribers["test.event"][0].subscriber_name == "decorated"


class TestEmit:
    """测试事件发布"""

    @pytest.mark.asyncio
    async def test_emit_fire_and_forget(self):
        """测试广播模式（不等待）"""
        bus = EventBus()
        called = []

        async def handler(event):
            called.append(event.data)

        bus.subscribe("test.event", handler)

        result = await bus.emit("test.event", {"msg": "hello"})

        # 广播模式返回 None
        assert result is None
        # 但订阅者确实被调用了
        assert called == [{"msg": "hello"}]

    @pytest.mark.asyncio
    async def test_emit_wait_all(self):
        """测试等待全部模式"""
        bus = EventBus()

        async def handler1(event):
            return f"handler1: {event.data}"

        async def handler2(event):
            return f"handler2: {event.data}"

        bus.subscribe("test.event", handler1)
        bus.subscribe("test.event", handler2)

        results = await bus.emit("test.event", "hello", wait_all=True)

        assert results is not None
        assert len(results) == 2
        assert "handler1: hello" in results
        assert "handler2: hello" in results

    @pytest.mark.asyncio
    async def test_emit_sync_subscriber(self):
        """测试同步订阅者"""
        bus = EventBus()
        called = []

        def sync_handler(event):
            called.append(f"sync: {event.data}")

        bus.subscribe("test.event", sync_handler)

        await bus.emit("test.event", "hello")

        assert called == ["sync: hello"]

    @pytest.mark.asyncio
    async def test_emit_no_subscribers(self):
        """测试没有订阅者"""
        bus = EventBus()

        # 不应该抛出异常
        await bus.emit("unknown.event", {"data": "test"})

        result = await bus.emit("unknown.event", {"data": "test"}, wait_all=True)
        assert result == []

    @pytest.mark.asyncio
    async def test_emit_with_source(self):
        """测试事件来源"""
        bus = EventBus()
        received = []

        async def handler(event):
            received.append(event.source)

        bus.subscribe("test.event", handler)

        await bus.emit("test.event", "data", source="test_module")

        assert received == ["test_module"]


class TestErrorHandling:
    """测试错误处理"""

    @pytest.mark.asyncio
    async def test_error_strategy_continue(self):
        """测试继续策略"""
        bus = EventBus(emit_errors=False)
        results = []

        async def failing_handler(event):
            raise ValueError("I failed!")

        async def normal_handler(event):
            results.append("called")
            return "success"

        bus.subscribe(
            "test.event", failing_handler, error_strategy=ErrorStrategy.CONTINUE
        )
        bus.subscribe(
            "test.event", normal_handler, error_strategy=ErrorStrategy.CONTINUE
        )

        # 不应该抛出异常
        await bus.emit("test.event", "data")

        # 正常的订阅者应该被调用
        assert results == ["called"]

    @pytest.mark.asyncio
    async def test_error_strategy_raise(self):
        """测试抛出策略"""
        bus = EventBus(emit_errors=False)

        async def failing_handler(event):
            raise ValueError("I failed!")

        bus.subscribe("test.event", failing_handler, error_strategy=ErrorStrategy.RAISE)

        with pytest.raises(ValueError, match="I failed!"):
            await bus.emit("test.event", "data")

    @pytest.mark.asyncio
    async def test_error_event_emitted(self):
        """测试错误事件发送"""
        bus = EventBus(emit_errors=True)
        error_events = []

        async def failing_handler(event):
            raise ValueError("Test error")

        async def error_handler(event):
            error_events.append(event.data)

        bus.subscribe("test.event", failing_handler)
        bus.subscribe("system.error", error_handler)

        await bus.emit("test.event", "data")

        # 应该发送了错误事件
        assert len(error_events) == 1
        assert error_events[0]["original_event"] == "test.event"
        assert "Test error" in error_events[0]["error"]


class TestMiddleware:
    """测试中间件"""

    @pytest.mark.asyncio
    async def test_middleware(self):
        """测试中间件执行"""
        bus = EventBus()
        logs = []

        @bus.middleware
        async def logging_middleware(event, next):
            logs.append(f"before: {event.name}")
            result = await next(event)
            logs.append(f"after: {event.name}")
            return result

        async def handler(event):
            logs.append("handler")

        bus.subscribe("test.event", handler)

        await bus.emit("test.event", "data")

        assert logs == ["before: test.event", "handler", "after: test.event"]

    @pytest.mark.asyncio
    async def test_multiple_middlewares(self):
        """测试多个中间件（执行顺序）"""
        bus = EventBus()
        logs = []

        async def middleware1(event, next):
            logs.append("m1_before")
            result = await next(event)
            logs.append("m1_after")
            return result

        async def middleware2(event, next):
            logs.append("m2_before")
            result = await next(event)
            logs.append("m2_after")
            return result

        bus.add_middleware(middleware1)
        bus.add_middleware(middleware2)

        async def handler(event):
            logs.append("handler")

        bus.subscribe("test.event", handler)

        await bus.emit("test.event", "data")

        # 中间件按添加顺序的逆序执行（洋葱模型）
        assert logs == ["m1_before", "m2_before", "handler", "m2_after", "m1_after"]


class TestStats:
    """测试统计功能"""

    def test_get_stats(self):
        """测试获取统计"""
        bus = EventBus(time_accel_factor=2.0)
        bus.register("test.event", ["server"], ["brain"])
        bus.subscribe("test.event", lambda e: None)
        bus.subscribe("test.event", lambda e: None)
        bus.subscribe("other.event", lambda e: None)

        stats = bus.get_stats()

        assert stats["registered_events"] == 1
        assert stats["total_subscriptions"] == 3
        assert stats["events_with_subscribers"] == 2
        assert stats["middlewares"] == 0
        assert stats["time_accel_factor"] == 2.0
