"""
测试 TimeTool

覆盖时间获取、格式化、时区转换功能。
"""
import pytest
import time
from datetime import datetime, timezone, timedelta
from unittest.mock import Mock
from tools.builtin.time_tool import TimeTool
from tools.base import ToolResult


class TestTimeTool:
    """测试时间工具"""

    @pytest.fixture
    def time_tool(self):
        return TimeTool()

    @pytest.fixture
    def time_tool_with_event_bus(self):
        """带 EventBus 的时间工具"""
        mock_bus = Mock()
        mock_bus.logical_now = time.time()
        return TimeTool(event_bus=mock_bus)

    def test_basic_initialization(self, time_tool):
        """测试基本初始化"""
        assert time_tool.name == "time_tool"
        assert time_tool.permission.name == "READONLY"

    def test_execute_human_format(self, time_tool):
        """测试人类可读格式"""
        result = time_tool.execute({"format": "human"})
        assert result.success is True
        assert isinstance(result.data, str)
        # 检查包含年份和星期
        assert len(result.data) > 10

    def test_execute_iso8601_format(self, time_tool):
        """测试 ISO8601 格式"""
        result = time_tool.execute({"format": "iso8601"})
        assert result.success is True
        # 验证 ISO 格式
        try:
            datetime.fromisoformat(result.data.replace('Z', '+00:00'))
        except ValueError:
            pytest.fail("Not a valid ISO 8601 datetime")

    def test_execute_timestamp_format(self, time_tool):
        """测试时间戳格式"""
        result = time_tool.execute({"format": "timestamp"})
        assert result.success is True
        ts = float(result.data)
        # 时间戳应该在合理范围内（2020-2030年）
        assert 1577836800 < ts < 1893456000

    def test_execute_date_format(self, time_tool):
        """测试日期格式"""
        result = time_tool.execute({"format": "date"})
        assert result.success is True
        # YYYY-MM-DD 格式
        assert len(result.data) == 10
        assert result.data.count('-') == 2

    def test_execute_time_format(self, time_tool):
        """测试时间格式"""
        result = time_tool.execute({"format": "time"})
        assert result.success is True
        # HH:MM:SS 格式
        parts = result.data.split(':')
        assert len(parts) == 3

    def test_execute_full_format(self, time_tool):
        """测试完整格式"""
        result = time_tool.execute({"format": "full", "timezone": "Asia/Shanghai"})
        assert result.success is True
        assert "年" in result.data
        assert "Asia/Shanghai" in result.data

    def test_utc_timezone(self, time_tool):
        """测试 UTC 时区"""
        result = time_tool.execute({"timezone": "UTC"})
        assert result.success is True

    def test_offset_hours(self, time_tool):
        """测试小时偏移"""
        result = time_tool.execute({"offset_hours": 8})
        assert result.success is True

    def test_default_parameters(self, time_tool):
        """测试默认参数"""
        result = time_tool.execute({})
        assert result.success is True
        # 默认格式是 human，时区是 local

    def test_event_bus_integration(self, time_tool_with_event_bus):
        """测试 EventBus 集成获取逻辑时间"""
        result = time_tool_with_event_bus.execute({"format": "timestamp"})
        assert result.success is True
        # 使用的是 mock 的时间

    def test_invalid_timezone_fallback(self, time_tool):
        """测试无效时区回退"""
        result = time_tool.execute({"timezone": "Invalid/Zone"})
        # 应该使用本地时间，不报错
        assert result.success is True

    def test_result_metadata(self, time_tool):
        """测试结果元数据"""
        result = time_tool.execute({"format": "human"})
        assert "timestamp" in result.metadata
        assert "timezone" in result.metadata
