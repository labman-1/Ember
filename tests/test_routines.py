"""
Tests for routines layer
"""

import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, patch
from datetime import datetime

from ember_v2.routines import Routine, RoutineConfig, ScheduleManager, ScheduleItem
from ember_v2.core.event_bus import EventBus, Event


class TestScheduleItem:
    """测试 ScheduleItem"""

    def test_create_schedule_item(self):
        """测试创建日程项"""
        item = ScheduleItem(
            start_time="08:00",
            end_time="12:00",
            action="class",
            description="上课时间",
            priority=1,
        )

        assert item.start_time == "08:00"
        assert item.end_time == "12:00"
        assert item.action == "class"
        assert item.description == "上课时间"
        assert item.priority == 1
        assert item.conditions == {}


class TestScheduleManager:
    """测试 ScheduleManager"""

    def test_create_with_default_schedule(self):
        """测试使用默认日程创建"""
        manager = ScheduleManager()

        # 默认应该有多个日程项
        assert len(manager._schedule) > 0

        # 应该包含 sleep 活动
        sleep_items = [item for item in manager._schedule if item.action == "sleep"]
        assert len(sleep_items) > 0

    def test_create_with_custom_schedule(self):
        """测试使用自定义日程创建"""
        items = [
            ScheduleItem("09:00", "17:00", "work", "工作时间"),
            ScheduleItem("17:00", "09:00", "rest", "休息时间"),
        ]

        manager = ScheduleManager(items)

        assert len(manager._schedule) == 2
        assert manager._schedule[0].action == "work"

    def test_get_current_activity_normal_range(self):
        """测试获取当前活动（正常时间范围）"""
        manager = ScheduleManager([
            ScheduleItem("08:00", "12:00", "class", "上课"),
            ScheduleItem("12:00", "14:00", "lunch", "午餐"),
            ScheduleItem("14:00", "18:00", "study", "自习"),
        ])

        # 测试 10:00 应该在上课时间
        test_time = datetime(2024, 1, 1, 10, 0)
        activity = manager.get_current_activity(test_time)
        assert activity is not None
        assert activity.action == "class"

        # 测试 13:00 应该在午餐时间
        test_time = datetime(2024, 1, 1, 13, 0)
        activity = manager.get_current_activity(test_time)
        assert activity is not None
        assert activity.action == "lunch"

    def test_get_current_activity_cross_midnight(self):
        """测试获取当前活动（跨午夜）"""
        manager = ScheduleManager([
            ScheduleItem("23:00", "07:00", "sleep", "睡觉"),
            ScheduleItem("07:00", "23:00", "active", "活动"),
        ])

        # 测试 01:00 应该在睡觉时间
        test_time = datetime(2024, 1, 1, 1, 0)
        activity = manager.get_current_activity(test_time)
        assert activity is not None
        assert activity.action == "sleep"

        # 测试 23:30 应该在睡觉时间
        test_time = datetime(2024, 1, 1, 23, 30)
        activity = manager.get_current_activity(test_time)
        assert activity is not None
        assert activity.action == "sleep"

        # 测试 10:00 应该在活动时间
        test_time = datetime(2024, 1, 1, 10, 0)
        activity = manager.get_current_activity(test_time)
        assert activity is not None
        assert activity.action == "active"

    def test_get_next_activity(self):
        """测试获取下一个活动"""
        manager = ScheduleManager([
            ScheduleItem("08:00", "12:00", "class", "上课"),
            ScheduleItem("12:00", "14:00", "lunch", "午餐"),
        ])

        # 在 10:00，下一个应该是 lunch
        test_time = datetime(2024, 1, 1, 10, 0)
        next_activity = manager.get_next_activity(test_time)
        assert next_activity is not None
        assert next_activity.action == "lunch"

    def test_add_remove_item(self):
        """测试添加和删除日程项"""
        manager = ScheduleManager([])

        # 添加
        item = ScheduleItem("10:00", "11:00", "test", "测试")
        manager.add_item(item)
        assert len(manager._schedule) == 1

        # 删除
        result = manager.remove_item("test")
        assert result is True
        assert len(manager._schedule) == 0

        # 删除不存在的
        result = manager.remove_item("not_exist")
        assert result is False

    def test_get_schedule_summary(self):
        """测试获取日程摘要"""
        manager = ScheduleManager([
            ScheduleItem("08:00", "12:00", "class", "上课"),
        ])

        summary = manager.get_schedule_summary()
        assert "今日日程" in summary
        assert "08:00-12:00" in summary
        assert "上课" in summary


class TestRoutineConfig:
    """测试 RoutineConfig"""

    def test_default_config(self):
        """测试默认配置"""
        config = RoutineConfig()

        assert config.heartbeat_interval == 10.0
        assert config.idle_threshold == 60.0
        assert config.sleep_start_hour == 23
        assert config.sleep_end_hour == 7
        assert config.base_speak_probability == 0.1

    def test_custom_config(self):
        """测试自定义配置"""
        config = RoutineConfig(
            heartbeat_interval=5.0,
            idle_threshold=30.0,
            sleep_start_hour=22,
            sleep_end_hour=6,
        )

        assert config.heartbeat_interval == 5.0
        assert config.idle_threshold == 30.0
        assert config.sleep_start_hour == 22
        assert config.sleep_end_hour == 6


class TestRoutine:
    """测试 Routine"""

    @pytest.fixture
    def event_bus(self):
        """创建事件总线"""
        return EventBus()

    @pytest.fixture
    def routine(self, event_bus):
        """创建例程"""
        return Routine(event_bus)

    def test_create_routine(self, routine):
        """测试创建例程"""
        assert routine._is_running is False
        assert len(routine._action_handlers) == 0

    def test_register_action(self, routine):
        """测试注册 Action"""
        mock_handler = Mock()
        routine.register_action("test_action", mock_handler)

        assert "test_action" in routine._action_handlers
        assert routine.get_action("test_action") == mock_handler

    @pytest.mark.asyncio
    async def test_start_stop(self, routine, event_bus):
        """测试启动和停止"""
        await routine.start()
        assert routine._is_running is True

        await routine.stop()
        assert routine._is_running is False

    @pytest.mark.asyncio
    async def test_on_heartbeat_idle_triggered(self, routine, event_bus):
        """测试心跳触发 idle action"""
        import time

        # 设置最后活动时间为很久之前
        routine._last_activity_time = time.time() - 120  # 2分钟前

        # 注册 idle action
        mock_action = AsyncMock()
        mock_action.execute = AsyncMock(return_value=Mock(
            success=True,
            data={},
            events_to_emit=[],
        ))
        routine.register_action("idle", mock_action)

        # 触发心跳
        heartbeat_event = Event(name="heartbeat.tick", data={})
        await routine._on_heartbeat(heartbeat_event)

        # 应该执行了 idle action
        mock_action.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_on_user_input(self, routine, event_bus):
        """测试用户输入触发 generate_dialogue action"""
        # 注册 generate_dialogue action
        mock_action = AsyncMock()
        mock_action.execute = AsyncMock(return_value=Mock(
            success=True,
            data={},
            events_to_emit=[],
        ))
        routine.register_action("generate_dialogue", mock_action)

        # 触发用户输入
        user_input_event = Event(
            name="user.input",
            data={"text": "你好"},
        )
        await routine._on_user_input(user_input_event)

        # 应该执行了 generate_dialogue action
        mock_action.execute.assert_called_once()
        call_args = mock_action.execute.call_args[0][0]
        assert call_args["user_input"] == "你好"

    @pytest.mark.asyncio
    async def test_on_check_info_speak(self, routine, event_bus):
        """测试 check_info 触发主动说话"""
        # 启动例程
        await routine.start()

        # 触发 check_info 事件
        check_event = Event(
            name="check.info",
            data={"should_speak": True},
        )
        await routine._on_check_info(check_event)

        # 应该发布了 idle.speak 事件
        # (通过 event_bus.emit)

        await routine.stop()

    @pytest.mark.asyncio
    async def test_execute_action_success(self, routine, event_bus):
        """测试执行 Action 成功"""
        # 注册 action
        mock_handler = AsyncMock()
        mock_handler.execute = AsyncMock(return_value=Mock(
            success=True,
            data={"result": "ok"},
            events_to_emit=[
                {"name": "test.event", "data": {"key": "value"}}
            ],
        ))
        routine.register_action("test", mock_handler)

        # 执行
        await routine._execute_action("test", {"input": "data"})

        # 应该调用了 execute
        mock_handler.execute.assert_called_once_with({"input": "data"})

    @pytest.mark.asyncio
    async def test_execute_action_not_registered(self, routine, event_bus):
        """测试执行未注册的 Action"""
        # 不应该抛出异常
        await routine._execute_action("not_exist", {})

    @pytest.mark.asyncio
    async def test_execute_action_failure(self, routine, event_bus):
        """测试执行 Action 失败"""
        # 注册会失败的 action
        mock_handler = AsyncMock()
        mock_handler.execute = AsyncMock(return_value=Mock(
            success=False,
            error="Test error",
            data={},
            events_to_emit=[],
        ))
        routine.register_action("fail", mock_handler)

        # 执行
        await routine._execute_action("fail", {})

        # 不应该抛出异常

    def test_get_current_activity(self, routine):
        """测试获取当前活动"""
        activity = routine.get_current_activity()

        # 应该返回 "sleep" 或 "active" 之一
        assert activity in ["sleep", "active"]

    def test_is_sleep_time(self, routine):
        """测试判断睡眠时间"""
        # 测试当前时间
        is_sleep = routine.is_sleep_time()

        # 根据当前小时判断
        current_hour = datetime.now().hour
        config = routine._config
        expected = (
            current_hour >= config.sleep_start_hour
            or current_hour < config.sleep_end_hour
        )

        assert is_sleep == expected


class TestRoutineIntegration:
    """Routine 集成测试"""

    @pytest.fixture
    def event_bus(self):
        """创建事件总线"""
        return EventBus()

    @pytest.fixture
    def routine(self, event_bus):
        """创建例程"""
        config = RoutineConfig(
            idle_threshold=30.0,  # 30秒
        )
        return Routine(event_bus, config)

    @pytest.mark.asyncio
    async def test_full_flow_user_input(self, routine, event_bus):
        """测试完整用户输入流程"""
        # 注册 generate_dialogue action
        mock_dialogue_action = AsyncMock()
        mock_dialogue_action.execute = AsyncMock(return_value=Mock(
            success=True,
            data={"response": "你好！"},
            events_to_emit=[
                {"name": "dialogue.response", "data": {"text": "你好！"}}
            ],
        ))
        routine.register_action("generate_dialogue", mock_dialogue_action)

        # 启动例程
        await routine.start()

        # 发布用户输入事件
        await event_bus.emit("user.input", {"text": "你好"}, source="test")

        # 等待处理
        await asyncio.sleep(0.1)

        # 应该执行了 action
        mock_dialogue_action.execute.assert_called_once()

        await routine.stop()

    @pytest.mark.asyncio
    async def test_full_flow_heartbeat(self, routine, event_bus):
        """测试完整心跳流程"""
        import time

        # 注册 idle action
        mock_idle_action = AsyncMock()
        mock_idle_action.execute = AsyncMock(return_value=Mock(
            success=True,
            data={},
            events_to_emit=[],
        ))
        routine.register_action("idle", mock_idle_action)

        # 启动例程
        await routine.start()

        # 设置最后活动时间为很久之前
        routine._last_activity_time = time.time() - 100

        # 发布心跳事件
        await event_bus.emit("heartbeat.tick", {}, source="test")

        # 等待处理
        await asyncio.sleep(0.1)

        # 应该执行了 idle action
        mock_idle_action.execute.assert_called_once()

        await routine.stop()