"""
DB Process 类型定义
"""

from dataclasses import dataclass, field
from typing import Optional, Any, AsyncContextManager
from enum import Enum


class ConnectionStatus(Enum):
    """连接状态"""

    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    RECONNECTING = "reconnecting"


@dataclass
class PoolStats:
    """连接池统计信息"""

    total_connections: int = 0
    idle_connections: int = 0
    busy_connections: int = 0
    max_connections: int = 0


@dataclass
class QueryResult:
    """查询结果"""

    rows: list[dict] = field(default_factory=list)
    row_count: int = 0
    last_insert_id: Optional[int] = None
    affected_rows: int = 0


@dataclass
class Transaction:
    """事务对象"""

    id: str
    is_active: bool = True

    async def commit(self) -> None:
        """提交事务"""
        ...

    async def rollback(self) -> None:
        """回滚事务"""
        ...


@dataclass
class VectorSearchResult:
    """向量搜索结果"""

    id: Any
    similarity: float
    data: dict = field(default_factory=dict)
