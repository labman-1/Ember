"""
Graph Process 类型定义
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class UpsertMode(str, Enum):
    """更新模式"""

    INCREMENT = "increment"  # 增量：列表合并去重
    OVERWRITE = "overwrite"  # 覆盖：完全替换


@dataclass
class Entity:
    """实体"""

    name: str
    labels: list[str] = field(default_factory=list)
    properties: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "labels": self.labels,
            "properties": self.properties,
        }


@dataclass
class Relation:
    """关系"""

    source: str
    target: str
    type: str
    properties: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "source": self.source,
            "target": self.target,
            "type": self.type,
            "properties": self.properties,
        }


@dataclass
class GraphPath:
    """图路径"""

    nodes: list[str] = field(default_factory=list)
    relationships: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "nodes": self.nodes,
            "relationships": self.relationships,
        }


@dataclass
class PoolStats:
    """连接池统计"""

    total_connections: int = 0
    idle_connections: int = 0
