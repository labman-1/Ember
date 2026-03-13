"""
心跳机制测试
"""
import pytest
import time
import threading
from unittest.mock import Mock, patch, MagicMock


class TestHeartbeat:
    """测试心跳时钟"""

    def test_heartbeat_initialization(self):
        """测试心跳初始化"""
        from core.heartbeat import Heartbeat
        from core.event_bus import EventBus

        event_bus = EventBus()
        interval = 1  # 1秒间隔用于测试

        heartbeat = Heartbeat(event_bus, interval)

        assert heartbeat.event_bus == event_bus
        assert heartbeat.interval == interval
        assert heartbeat._thread is None
        assert heartbeat._stop_event is not None

    def test_heartbeat_starts_and_stops(self):
        """测试心跳启动和停止"""
        from core.heartbeat import Heartbeat
        from core.event_bus import EventBus

        event_bus = EventBus()
        heartbeat = Heartbeat(event_bus, 0.1)  # 100ms间隔

        # 启动心跳
        heartbeat.start()
        assert heartbeat._thread is not None
        assert heartbeat._thread.is_alive()

        # 停止心跳
        heartbeat.stop()
        assert not heartbeat._thread.is_alive()

    def test_heartbeat_publishes_events(self):
        """测试心跳发布事件"""
        from core.heartbeat import Heartbeat
        from core.event_bus import EventBus, Event

        event_bus = EventBus()
        received_events = []

        def capture_event(event):
            if event.name == "system.tick":
                received_events.append(event)

        event_bus.subscribe("system.tick", capture_event)

        heartbeat = Heartbeat(event_bus, 0.05)  # 50ms间隔

        # 启动并等待几个 tick
        heartbeat.start()
        time.sleep(0.2)  # 等待约4个 tick
        heartbeat.stop()

        # 应该收到一些事件
        assert len(received_events) >= 2

    def test_heartbeat_in_thread(self):
        """测试心跳在独立线程运行"""
        from core.heartbeat import Heartbeat
        from core.event_bus import EventBus
        import threading

        event_bus = EventBus()
        heartbeat = Heartbeat(event_bus, 0.1)

        heartbeat.start()
        main_thread = threading.current_thread()

        # 心跳应该在不同线程
        assert heartbeat._thread != main_thread
        assert heartbeat._thread.is_alive()

        heartbeat.stop()

    def test_multiple_start_calls(self):
        """测试多次调用 start"""
        from core.heartbeat import Heartbeat
        from core.event_bus import EventBus

        event_bus = EventBus()
        heartbeat = Heartbeat(event_bus, 0.1)

        heartbeat.start()
        first_thread = heartbeat._thread

        # 再次调用 start 不应该创建新线程
        heartbeat.start()
        second_thread = heartbeat._thread

        assert first_thread == second_thread

        heartbeat.stop()

    def test_stop_without_start(self):
        """测试未启动就停止"""
        from core.heartbeat import Heartbeat
        from core.event_bus import EventBus

        event_bus = EventBus()
        heartbeat = Heartbeat(event_bus, 0.1)

        # 不应该抛出异常
        heartbeat.stop()
        assert heartbeat._thread is None or not heartbeat._thread.is_alive()
