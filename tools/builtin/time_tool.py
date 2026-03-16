"""
时间工具

提供获取当前时间、时区转换、时间格式化等功能。
支持逻辑时间（Ember的时间系统）和真实时间。
"""
import time
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional
from tools.base import BaseTool, ToolResult, ToolPermission

logger = logging.getLogger(__name__)


class TimeTool(BaseTool):
    """
    获取当前时间信息

    支持多种时间格式和时区，返回格式化的时间字符串或时间戳。
    """

    name = "time_tool"
    description = "获取当前时间信息，支持多种格式和时区转换"
    short_description = "获取当前时间、日期信息"
    permission = ToolPermission.READONLY
    timeout = 5.0

    examples = [
        {
            "user": "现在几点了？",
            "parameters": {"format": "human"}
        },
        {
            "user": "今天的日期是？",
            "parameters": {"format": "date"}
        },
    ]

    parameters = {
        "type": "object",
        "properties": {
            "format": {
                "type": "string",
                "description": "时间格式，支持 'iso8601', 'timestamp', 'human', 'date', 'time', 'full'",
                "enum": ["iso8601", "timestamp", "human", "date", "time", "full"],
                "default": "human",
            },
            "timezone": {
                "type": "string",
                "description": "时区，如 'Asia/Shanghai', 'UTC', 'local'",
                "default": "local",
            },
            "offset_hours": {
                "type": "integer",
                "description": "相对于UTC的偏移小时数（覆盖timezone设置）",
            },
        },
    }

    def __init__(self, event_bus=None):
        """
        初始化时间工具

        Args:
            event_bus: 可选的 EventBus 实例，用于获取逻辑时间
        """
        super().__init__()
        self.event_bus = event_bus

    def execute(self, params: dict) -> ToolResult:
        """
        执行时间查询

        Args:
            params: {
                "format": "human" | "iso8601" | "timestamp" | "date" | "time" | "full",
                "timezone": "Asia/Shanghai" | "UTC" | "local" | ...,
                "offset_hours": int (可选)
            }

        Returns:
            ToolResult: 包含格式化时间的字符串
        """
        try:
            format_type = params.get("format", "human")
            timezone_str = params.get("timezone", "local")
            offset_hours = params.get("offset_hours")

            # 获取时间（优先使用逻辑时间）
            if self.event_bus:
                timestamp = self.event_bus.logical_now
            else:
                timestamp = time.time()

            # 处理时区
            if offset_hours is not None:
                tz = timezone(timedelta(hours=offset_hours))
            elif timezone_str == "UTC":
                tz = timezone.utc
            elif timezone_str == "local":
                tz = None  # 使用本地时间
            else:
                # 尝试解析时区字符串（简化处理）
                tz = self._parse_timezone(timezone_str)
                # 如果解析失败，回退到本地时间并归一化时区字符串
                if tz is None:
                    timezone_str = "local"

            # 转换为 datetime
            if tz:
                dt = datetime.fromtimestamp(timestamp, tz)
            else:
                dt = datetime.fromtimestamp(timestamp)

            # 格式化输出
            result = self._format_time(dt, format_type, timezone_str)

            return ToolResult.ok(
                data=result,
                timestamp=timestamp,
                timezone=str(tz) if tz else "local",
            )

        except Exception as e:
            logger.exception("TimeTool 执行失败")
            return ToolResult.fail(f"获取时间失败: {str(e)}")

    def _parse_timezone(self, timezone_str: str) -> Optional[timezone]:
        """解析时区字符串（简化实现）"""
        # 常见时区映射
        tz_offsets = {
            "Asia/Shanghai": 8,
            "Asia/Tokyo": 9,
            "Asia/Seoul": 9,
            "Asia/Singapore": 8,
            "Europe/London": 0,
            "Europe/Paris": 1,
            "Europe/Berlin": 1,
            "America/New_York": -5,
            "America/Los_Angeles": -8,
            "America/Chicago": -6,
            "Australia/Sydney": 11,
        }

        offset = tz_offsets.get(timezone_str)
        if offset is not None:
            return timezone(timedelta(hours=offset))

        # 尝试解析 "+08:00" 或 "-05:00" 格式
        try:
            if timezone_str.startswith(("+", "-")):
                hours = int(timezone_str[:3])
                return timezone(timedelta(hours=hours))
        except ValueError:
            pass

        return None

    def _format_time(self, dt: datetime, format_type: str, timezone_str: str) -> str:
        """根据格式类型格式化时间"""
        if format_type == "iso8601":
            return dt.isoformat()

        elif format_type == "timestamp":
            return str(dt.timestamp())

        elif format_type == "date":
            return dt.strftime("%Y-%m-%d")

        elif format_type == "time":
            return dt.strftime("%H:%M:%S")

        elif format_type == "full":
            weekday = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"][dt.weekday()]
            return dt.strftime(f"%Y年%m月%d日 {weekday} %H:%M:%S ({timezone_str})")

        else:  # human
            weekday = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"][dt.weekday()]
            return dt.strftime(f"%Y-%m-%d {weekday} %H:%M")
