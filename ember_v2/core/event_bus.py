"""
异步事件总线

功能：
- 发布模式：广播（Fire-and-Forget）+ 等待全部（Wait-All）
- 订阅者类型：自动检测同步/异步
- 错误处理：策略配置 + 自动发送错误事件
- 调试功能：事件注册表 + 中间件
- 逻辑时间：支持时间加速
"""

import asyncio
import inspect
import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from typing import (
    Any,
    Callable,
    Dict,
    List,
    Optional,
    Union,
    Awaitable,
    TypeVar,
    Generic,
)
from functools import wraps

logger = logging.getLogger(__name__)

T = TypeVar("T")


class ErrorStrategy(Enum):
    """错误处理策略"""

    CONTINUE = "continue"  # 继续执行其他订阅者，记录日志
    RAISE = "raise"  # 立即抛出异常
    IGNORE = "ignore"  # 静默忽略


@dataclass
class Event:
    """事件对象"""

    name: str
    data: Any = None
    timestamp: float = field(default_factory=time.time)
    source: Optional[str] = None  # 事件来源

    def __repr__(self):
        return f"Event({self.name}, source={self.source})"


@dataclass
class EventRegistration:
    """事件注册信息"""

    event_name: str
    publishers: List[str] = field(default_factory=list)
    subscribers: List[str] = field(default_factory=list)
    description: str = ""


@dataclass
class Subscription:
    """订阅信息"""

    callback: Callable
    subscriber_name: str
    error_strategy: ErrorStrategy = ErrorStrategy.CONTINUE
    priority: int = 0  # 优先级，数值越大越先执行


class EventBus:
    """
    异步事件总线

    使用示例:

    ```python
    # 创建事件总线
    bus = EventBus(time_accel_factor=1.0)

    # 注册事件（可选，用于调试和文档）
    bus.register("user.input",
        publishers=["server"],
        subscribers=["brain", "state_manager"]
    )

    # 订阅事件
    async def on_user_input(event: Event):
        print(f"收到用户输入: {event.data}")

    bus.subscribe("user.input", on_user_input, subscriber_name="brain")

    # 发布事件（广播模式）
    await bus.emit("user.input", {"text": "你好"})

    # 发布事件（等待全部）
    results = await bus.emit("validate", data, wait_all=True)
    ```
    """

    def __init__(
        self,
        time_accel_factor: float = 1.0,
        start_time: Optional[float] = None,
        emit_errors: bool = True,
        debug: bool = False,
    ):
        """
        初始化事件总线

        Args:
            time_accel_factor: 时间加速因子
            start_time: 逻辑时间起始点（Unix 时间戳），默认为当前时间
            emit_errors: 是否自动发送错误事件
            debug: 是否启用调试模式（详细日志）
        """
        self._subscribers: Dict[str, List[Subscription]] = defaultdict(list)
        self._registrations: Dict[str, EventRegistration] = {}
        self._middlewares: List[Callable] = []

        # 时间管理
        self._time_accel_factor = time_accel_factor
        self._base_logical_time = start_time if start_time is not None else time.time()
        self._real_start_time = time.time()

        # 配置
        self._emit_errors = emit_errors
        self._debug = debug

        self._logger = logging.getLogger(f"{__name__}.EventBus")

    # ==================== 时间管理 ====================

    @property
    def time_accel_factor(self) -> float:
        """时间加速因子"""
        return self._time_accel_factor

    @time_accel_factor.setter
    def time_accel_factor(self, value: float):
        self._time_accel_factor = value

    @property
    def logical_now(self) -> float:
        """当前逻辑时间（Unix 时间戳）"""
        real_elapsed = time.time() - self._real_start_time
        logical_time = self._base_logical_time + (
            real_elapsed * self._time_accel_factor
        )
        return logical_time

    @property
    def formatted_logical_now(self) -> str:
        """格式化的当前逻辑时间"""
        return self.format_logical_time(self.logical_now)

    def format_logical_time(
        self, logical_time: float, fmt: str = "%Y-%m-%d %H:%M:%S"
    ) -> str:
        """格式化逻辑时间"""
        return time.strftime(fmt, time.localtime(logical_time))

    # ==================== 事件注册 ====================

    def register(
        self,
        event_name: str,
        publishers: Optional[List[str]] = None,
        subscribers: Optional[List[str]] = None,
        description: str = "",
    ) -> None:
        """
        注册事件（用于文档和调试）

        Args:
            event_name: 事件名称
            publishers: 发布者列表
            subscribers: 订阅者列表
            description: 事件描述
        """
        self._registrations[event_name] = EventRegistration(
            event_name=event_name,
            publishers=publishers or [],
            subscribers=subscribers or [],
            description=description,
        )

        if self._debug:
            self._logger.debug(f"Registered event: {event_name}")

    def get_registration(self, event_name: str) -> Optional[EventRegistration]:
        """获取事件注册信息"""
        return self._registrations.get(event_name)

    def list_events(self) -> List[str]:
        """列出所有已注册的事件"""
        return list(self._registrations.keys())

    # ==================== 订阅管理 ====================

    def subscribe(
        self,
        event_name: str,
        callback: Callable,
        subscriber_name: str = "",
        error_strategy: ErrorStrategy = ErrorStrategy.CONTINUE,
        priority: int = 0,
    ) -> None:
        """
        订阅事件

        Args:
            event_name: 事件名称
            callback: 回调函数（同步或异步）
            subscriber_name: 订阅者名称（用于调试）
            error_strategy: 错误处理策略
            priority: 优先级（数值越大越先执行）
        """
        subscription = Subscription(
            callback=callback,
            subscriber_name=subscriber_name or callback.__name__,
            error_strategy=error_strategy,
            priority=priority,
        )

        self._subscribers[event_name].append(subscription)
        # 按优先级排序
        self._subscribers[event_name].sort(key=lambda s: s.priority, reverse=True)

        if self._debug:
            self._logger.debug(
                f"Subscribed '{subscriber_name}' to '{event_name}' "
                f"with priority={priority}, error_strategy={error_strategy.value}"
            )

    def unsubscribe(self, event_name: str, callback: Callable) -> bool:
        """
        取消订阅

        Returns:
            是否成功取消
        """
        subscribers = self._subscribers.get(event_name, [])
        for i, sub in enumerate(subscribers):
            if sub.callback == callback:
                subscribers.pop(i)
                return True
        return False

    def clear_subscribers(self, event_name: Optional[str] = None) -> None:
        """清除订阅者"""
        if event_name:
            self._subscribers[event_name] = []
        else:
            self._subscribers.clear()

    # ==================== 中间件 ====================

    def middleware(self, func: Callable) -> Callable:
        """
        注册中间件（装饰器方式）

        使用示例:
        ```python
        @bus.middleware
        async def logging_middleware(event, next):
            print(f"Before: {event.name}")
            result = await next(event)
            print(f"After: {event.name}")
            return result
        ```
        """
        self._middlewares.append(func)
        return func

    def add_middleware(self, func: Callable) -> None:
        """添加中间件"""
        self._middlewares.append(func)

    # ==================== 事件发布 ====================

    async def emit(
        self,
        event_name: str,
        data: Any = None,
        source: Optional[str] = None,
        wait_all: bool = False,
    ) -> Optional[List[Any]]:
        """
        发布事件

        Args:
            event_name: 事件名称
            data: 事件数据
            source: 事件来源
            wait_all: 是否等待所有订阅者完成

        Returns:
            wait_all=True 时返回所有订阅者的返回值列表
            wait_all=False 时返回 None
        """
        event = Event(name=event_name, data=data, source=source)

        if self._debug:
            self._logger.debug(f"Emitting event: {event_name} from {source}")

        subscribers = self._subscribers.get(event_name, [])

        if not subscribers:
            if self._debug:
                self._logger.debug(f"No subscribers for event: {event_name}")
            return [] if wait_all else None

        # 构建执行链
        async def execute_all(evt: Event) -> List[Any]:
            """执行所有订阅者"""
            results = []
            for sub in subscribers:
                try:
                    result = await self._execute_callback(sub, evt)
                    results.append(result)
                except Exception as e:
                    await self._handle_error(sub, evt, e)
                    if sub.error_strategy == ErrorStrategy.RAISE:
                        raise
            return results

        # 应用中间件
        handler = execute_all
        for middleware in reversed(self._middlewares):
            handler = self._wrap_middleware(middleware, handler)

        # 执行
        try:
            results = await handler(event)
            return results if wait_all else None
        except Exception as e:
            self._logger.error(f"Event {event_name} failed: {e}")
            raise

    async def _execute_callback(self, subscription: Subscription, event: Event) -> Any:
        """执行回调（自动检测同步/异步）"""
        callback = subscription.callback

        if inspect.iscoroutinefunction(callback):
            # 异步函数
            return await callback(event)
        else:
            # 同步函数，在线程池中执行
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(None, callback, event)

    def _wrap_middleware(self, middleware: Callable, handler: Callable) -> Callable:
        """包装中间件"""

        async def wrapped(event: Event):
            # next() 函数，让中间件调用
            async def next_fn(evt: Event = event):
                return await handler(evt)

            if inspect.iscoroutinefunction(middleware):
                return await middleware(event, next_fn)
            else:
                # 同步中间件
                return middleware(event, next_fn)

        return wrapped

    async def _handle_error(
        self, subscription: Subscription, event: Event, error: Exception
    ) -> None:
        """处理订阅者错误"""
        self._logger.error(
            f"Error in subscriber '{subscription.subscriber_name}' "
            f"for event '{event.name}': {error}"
        )

        # 发送错误事件
        if self._emit_errors:
            try:
                error_event = Event(
                    name="system.error",
                    data={
                        "original_event": event.name,
                        "original_data": event.data,
                        "subscriber": subscription.subscriber_name,
                        "error": str(error),
                        "error_type": type(error).__name__,
                    },
                    source="event_bus",
                )
                # 直接执行，避免递归中间件
                for sub in self._subscribers.get("system.error", []):
                    try:
                        await self._execute_callback(sub, error_event)
                    except Exception as e:
                        self._logger.error(f"Error in error handler: {e}")
            except Exception as e:
                self._logger.error(f"Failed to emit error event: {e}")

    # ==================== 便捷方法 ====================

    def on(
        self,
        event_name: str,
        subscriber_name: str = "",
        error_strategy: ErrorStrategy = ErrorStrategy.CONTINUE,
        priority: int = 0,
    ):
        """
        装饰器方式订阅事件

        使用示例:
        ```python
        @bus.on("user.input", subscriber_name="brain")
        async def handle_user_input(event: Event):
            print(event.data)
        ```
        """

        def decorator(func: Callable) -> Callable:
            self.subscribe(
                event_name=event_name,
                callback=func,
                subscriber_name=subscriber_name,
                error_strategy=error_strategy,
                priority=priority,
            )
            return func

        return decorator

    # ==================== 检查和调试 ====================

    def validate_registrations(self) -> List[str]:
        """
        验证事件注册，返回警告列表

        检查：
        1. 有订阅者但未注册的事件
        2. 已注册但没有订阅者的事件
        """
        warnings = []

        # 检查未注册的订阅
        for event_name in self._subscribers:
            if event_name not in self._registrations and event_name != "system.error":
                warnings.append(
                    f"Event '{event_name}' has subscribers but not registered"
                )

        # 检查没有订阅者的注册
        for event_name, reg in self._registrations.items():
            if event_name not in self._subscribers or not self._subscribers[event_name]:
                if reg.publishers:  # 有发布者但没有订阅者
                    warnings.append(
                        f"Event '{event_name}' is registered but has no subscribers"
                    )

        return warnings

    def get_stats(self) -> Dict[str, Any]:
        """获取事件总线统计信息"""
        return {
            "registered_events": len(self._registrations),
            "total_subscriptions": sum(
                len(subs) for subs in self._subscribers.values()
            ),
            "events_with_subscribers": len(
                [k for k, v in self._subscribers.items() if v]
            ),
            "middlewares": len(self._middlewares),
            "logical_time": self.formatted_logical_now,
            "time_accel_factor": self._time_accel_factor,
        }
