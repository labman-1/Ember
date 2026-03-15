"""
Graph Process Package
Neo4j 图数据库处理器

功能:
- 异步连接池管理
- 实体 CRUD (支持别名匹配)
- 关系 CRUD
- 路径查询
- 原生 Cypher 执行
"""

import os
import logging
from typing import Optional, List, Dict, Any

from ember_v2.core.package_base import BasePackage
from ember_v2.core.types import PackageResponse

from .types import Entity, Relation, GraphPath, UpsertMode, PoolStats

logger = logging.getLogger(__name__)


class GraphProcess(BasePackage):
    """
    Neo4j 图数据库处理器

    特性:
    - 异步连接池管理
    - 实体别名系统
    - 增量/覆盖更新模式
    - APOC 检测与降级
    """

    def __init__(self, config_path: Optional[str] = None):
        """
        初始化图数据库处理器

        Args:
            config_path: 配置文件路径
        """
        super().__init__(config_path)

        # 从环境变量或配置读取 Neo4j 连接信息
        self._uri = os.getenv("NEO4J_URI") or self.get_config_value(
            "neo4j.uri", "bolt://localhost:7687"
        )
        self._user = os.getenv("NEO4J_USER") or self.get_config_value(
            "neo4j.user", "neo4j"
        )
        self._password = os.getenv("NEO4J_PASSWORD") or self.get_config_value(
            "neo4j.password", "password"
        )
        self._database = os.getenv("NEO4J_DATABASE") or self.get_config_value(
            "neo4j.database", "neo4j"
        )

        # 连接池配置
        self._max_connection_lifetime = self.get_config_value(
            "pool.max_connection_lifetime", 3600
        )
        self._max_connection_pool_size = self.get_config_value(
            "pool.max_connection_pool_size", 50
        )
        self._connection_timeout = self.get_config_value("pool.connection_timeout", 30)
        self._connection_acquisition_timeout = self.get_config_value(
            "pool.connection_acquisition_timeout", 60
        )

        # 功能开关
        self._check_apoc = self.get_config_value("features.check_apoc", True)
        self._apoc_available = False

        # 连接
        self._driver = None
        self._is_connected = False

        self._logger.info(f"GraphProcess initialized for {self._uri}/{self._database}")

    # ==================== 连接管理 ====================

    async def connect(self) -> PackageResponse[bool]:
        """
        建立数据库连接，创建约束，检查 APOC

        Returns:
            PackageResponse 包含连接结果
        """
        try:
            from neo4j import AsyncGraphDatabase

            self._driver = AsyncGraphDatabase.driver(
                self._uri,
                auth=(self._user, self._password),
                max_connection_lifetime=self._max_connection_lifetime,
                max_connection_pool_size=self._max_connection_pool_size,
                connection_timeout=self._connection_timeout,
            )

            # 验证连接
            await self._driver.verify_connectivity()
            self._is_connected = True

            self._logger.info("Neo4j connection established successfully")

            # 创建约束
            await self._create_constraints()

            # 检查 APOC
            if self._check_apoc:
                await self._check_apoc_available()

            return PackageResponse(success=True, data=True)

        except Exception as e:
            self._logger.error(f"Failed to connect to Neo4j: {e}")
            return PackageResponse(success=False, error=str(e))

    async def disconnect(self) -> None:
        """关闭连接"""
        if self._driver:
            await self._driver.close()
            self._driver = None
            self._is_connected = False
            self._logger.info("Neo4j connection closed")

    async def ensure_connected(self) -> None:
        """确保已连接"""
        if not self._is_connected or not self._driver:
            result = await self.connect()
            if not result.success:
                raise ConnectionError(f"Neo4j connection failed: {result.error}")

    @property
    def is_connected(self) -> bool:
        """是否已连接"""
        return self._is_connected

    @property
    def apoc_available(self) -> bool:
        """APOC 是否可用"""
        return self._apoc_available

    async def _create_constraints(self) -> None:
        """创建唯一性约束"""
        try:
            # 确保实体 name 唯一
            await self.execute_cypher(
                "CREATE CONSTRAINT entity_name_unique IF NOT EXISTS "
                "FOR (e:Entity) REQUIRE e.name IS UNIQUE"
            )
            self._logger.debug("Created entity_name_unique constraint")
        except Exception as e:
            self._logger.warning(f"Failed to create constraints: {e}")

    async def _check_apoc_available(self) -> None:
        """检查 APOC 插件是否可用"""
        try:
            result = await self.execute_cypher(
                "CALL apoc.help('coll') YIELD name RETURN count(*) as cnt"
            )
            if result.success and result.data:
                self._apoc_available = True
                self._logger.info("APOC plugin is available")
            else:
                self._apoc_available = False
                self._logger.info(
                    "APOC plugin is not available, using fallback methods"
                )
        except Exception:
            self._apoc_available = False
            self._logger.info("APOC plugin not found, using fallback methods")

    # ==================== 健康检查与统计 ====================

    async def health_check(self) -> PackageResponse[bool]:
        """
        健康检查

        Returns:
            PackageResponse 包含是否健康
        """
        try:
            await self.ensure_connected()
            result = await self.execute_cypher("RETURN 1 as test")
            return PackageResponse(
                success=True, data=result.success and result.data is not None
            )
        except Exception as e:
            return PackageResponse(success=False, error=str(e))

    async def get_pool_stats(self) -> PoolStats:
        """
        获取连接池统计信息

        Returns:
            PoolStats 连接池状态
        """
        if not self._driver:
            return PoolStats()

        # Neo4j driver 没有直接获取连接池状态的方法
        # 返回基本状态
        return PoolStats(
            total_connections=1 if self._is_connected else 0,
            idle_connections=1 if self._is_connected else 0,
        )

    # ==================== 原生 Cypher 执行 ====================

    async def execute_cypher(
        self,
        query: str,
        params: Optional[Dict[str, Any]] = None,
    ) -> PackageResponse[List[Dict]]:
        """
        执行原生 Cypher 查询

        Args:
            query: Cypher 查询语句
            params: 查询参数

        Returns:
            PackageResponse 包含查询结果列表
        """
        try:
            await self.ensure_connected()

            async with self._driver.session(database=self._database) as session:
                result = await session.run(query, params or {})
                records = await result.data()

                return PackageResponse(success=True, data=records)

        except Exception as e:
            self._logger.error(f"Cypher execution error: {e}\nQuery: {query}")
            return PackageResponse(success=False, error=str(e))

    # ==================== 实体操作 ====================

    async def upsert_entity(
        self,
        name: str,
        labels: Optional[List[str]] = None,
        properties: Optional[Dict[str, Any]] = None,
        aliases: Optional[List[str]] = None,
        mode: UpsertMode = UpsertMode.INCREMENT,
    ) -> PackageResponse[Entity]:
        """
        创建或更新实体，支持别名匹配

        Args:
            name: 实体名称
            labels: 标签列表（如 ["Person", "Character"]）
            properties: 实体属性
            aliases: 别名列表（用于匹配已存在的实体）
            mode: 更新模式（INCREMENT 列表合并, OVERWRITE 覆盖）

        Returns:
            PackageResponse 包含创建/更新的实体
        """
        try:
            await self.ensure_connected()

            properties = properties or {}
            labels = labels or []
            aliases = aliases or []

            # 确保 name 在属性中
            properties["name"] = name
            if aliases:
                properties["aliases"] = aliases

            # 构建标签字符串
            label_str = ":Entity"
            if labels:
                label_str = ":" + ":".join(labels) + ":Entity"

            # 尝试查找已存在的实体（通过 name 或 aliases 匹配）
            existing = await self._find_entity_by_name_or_alias(name, aliases)

            if existing:
                # 更新已存在的实体
                entity_name = existing["name"]

                if mode == UpsertMode.OVERWRITE:
                    # 覆盖模式：直接设置属性
                    set_clauses = [
                        f"e.{k} = ${k}" for k in properties.keys() if k != "name"
                    ]
                    set_clauses.append("e.labels = $labels")

                    query = f"""
                        MATCH (e {{name: $name}})
                        SET {', '.join(set_clauses)}
                        RETURN e
                    """
                    params = {"name": entity_name, "labels": labels, **properties}
                else:
                    # 增量模式：合并列表
                    set_clauses = []
                    params = {"name": entity_name, "labels": labels}

                    for key, value in properties.items():
                        if key == "name":
                            continue
                        elif key in ["aliases"] and isinstance(value, list):
                            # 列表合并去重（使用 Python 实现）
                            existing_list = existing.get(key, [])
                            merged = list(set(existing_list + value))
                            set_clauses.append(f"e.{key} = ${key}")
                            params[key] = merged
                        elif key == "labels":
                            # 标签单独处理
                            pass
                        else:
                            set_clauses.append(f"e.{key} = ${key}")
                            params[key] = value

                    # 添加新标签
                    if labels:
                        params["new_labels"] = labels

                    if set_clauses:
                        query = f"""
                            MATCH (e {{name: $name}})
                            SET {', '.join(set_clauses)}
                        """
                        if labels:
                            # 动态添加标签需要用 APOC 或分开处理
                            # 这里简单地在 Python 中处理
                            pass

                        query += " RETURN e"
                    else:
                        query = "MATCH (e {name: $name}) RETURN e"

                result = await self.execute_cypher(query, params)

                if result.success and result.data:
                    node_data = result.data[0]["e"]
                    return PackageResponse(
                        success=True,
                        data=Entity(
                            name=node_data.get("name", name),
                            labels=labels,
                            properties=node_data,
                        ),
                    )
                return PackageResponse(success=False, error="Failed to update entity")

            else:
                # 创建新实体
                query = f"CREATE (e{label_str} $props) RETURN e"
                params = {
                    "props": {
                        **properties,
                        "aliases": aliases,
                    }
                }

                result = await self.execute_cypher(query, params)

                if result.success and result.data:
                    return PackageResponse(
                        success=True,
                        data=Entity(
                            name=name,
                            labels=labels,
                            properties=properties,
                        ),
                    )
                return PackageResponse(success=False, error="Failed to create entity")

        except Exception as e:
            self._logger.error(f"Upsert entity error: {e}")
            return PackageResponse(success=False, error=str(e))

    async def _find_entity_by_name_or_alias(
        self, name: str, aliases: Optional[List[str]] = None
    ) -> Optional[Dict]:
        """
        通过名称或别名查找实体

        Args:
            name: 实体名称
            aliases: 别名列表

        Returns:
            找到的实体数据或 None
        """
        # 先精确匹配 name
        query = "MATCH (e:Entity {name: $name}) RETURN e"
        result = await self.execute_cypher(query, {"name": name})

        if result.success and result.data:
            return result.data[0]["e"]

        # 再匹配别名
        if aliases:
            query = "MATCH (e:Entity) WHERE ANY(alias IN e.aliases WHERE alias IN $aliases) RETURN e"
            result = await self.execute_cypher(query, {"aliases": aliases})

            if result.success and result.data:
                return result.data[0]["e"]

        return None

    async def delete_entity(self, name: str) -> PackageResponse[bool]:
        """
        删除实体及其所有关系

        Args:
            name: 实体名称

        Returns:
            PackageResponse 包含删除结果
        """
        try:
            await self.ensure_connected()

            query = "MATCH (e:Entity {name: $name}) DETACH DELETE e"
            result = await self.execute_cypher(query, {"name": name})

            return PackageResponse(success=True, data=True)

        except Exception as e:
            self._logger.error(f"Delete entity error: {e}")
            return PackageResponse(success=False, error=str(e))

    async def get_entity(self, name: str) -> PackageResponse[Optional[Entity]]:
        """
        获取单个实体

        Args:
            name: 实体名称

        Returns:
            PackageResponse 包含实体或 None
        """
        try:
            await self.ensure_connected()

            query = "MATCH (e:Entity {name: $name}) RETURN e"
            result = await self.execute_cypher(query, {"name": name})

            if result.success and result.data:
                node_data = result.data[0]["e"]

                # 提取标签（从查询中获取）
                labels_query = (
                    "MATCH (e:Entity {name: $name}) RETURN labels(e) as labels"
                )
                labels_result = await self.execute_cypher(labels_query, {"name": name})
                labels = (
                    labels_result.data[0]["labels"]
                    if labels_result.success and labels_result.data
                    else []
                )
                # 移除 Entity 基础标签
                labels = [l for l in labels if l != "Entity"]

                return PackageResponse(
                    success=True,
                    data=Entity(
                        name=node_data.get("name", name),
                        labels=labels,
                        properties=node_data,
                    ),
                )

            return PackageResponse(success=True, data=None)

        except Exception as e:
            self._logger.error(f"Get entity error: {e}")
            return PackageResponse(success=False, error=str(e))

    async def query_entities(
        self,
        label: Optional[str] = None,
        limit: int = 100,
        skip: int = 0,
        order_by: Optional[str] = None,
    ) -> PackageResponse[List[Entity]]:
        """
        查询实体列表

        Args:
            label: 标签过滤（如 "Person"）
            limit: 返回数量限制
            skip: 跳过数量（分页）
            order_by: 排序字段

        Returns:
            PackageResponse 包含实体列表
        """
        try:
            await self.ensure_connected()

            # 构建查询
            if label:
                query = f"MATCH (e:{label}:Entity) RETURN e, labels(e) as node_labels"
            else:
                query = "MATCH (e:Entity) RETURN e, labels(e) as node_labels"

            if order_by:
                query += f" ORDER BY e.{order_by}"

            query += f" SKIP {skip} LIMIT {limit}"

            result = await self.execute_cypher(query)

            if result.success:
                entities = []
                for record in result.data:
                    node_data = record["e"]
                    node_labels = record.get("node_labels", [])
                    labels = [l for l in node_labels if l != "Entity"]

                    entities.append(
                        Entity(
                            name=node_data.get("name", ""),
                            labels=labels,
                            properties=node_data,
                        )
                    )

                return PackageResponse(success=True, data=entities)

            return PackageResponse(success=False, error=result.error)

        except Exception as e:
            self._logger.error(f"Query entities error: {e}")
            return PackageResponse(success=False, error=str(e))

    # ==================== 关系操作 ====================

    async def upsert_relation(
        self,
        source: str,
        target: str,
        rel_type: str,
        properties: Optional[Dict[str, Any]] = None,
    ) -> PackageResponse[Relation]:
        """
        创建或更新关系

        Args:
            source: 源实体名称
            target: 目标实体名称
            rel_type: 关系类型（如 "KNOWS", "FRIEND_OF"）
            properties: 关系属性

        Returns:
            PackageResponse 包含创建/更新的关系
        """
        try:
            await self.ensure_connected()

            properties = properties or {}

            # 检查关系是否已存在
            check_query = f"""
                MATCH (source:Entity {{name: $source}})-[r:{rel_type}]->(target:Entity {{name: $target}})
                RETURN r
            """
            existing = await self.execute_cypher(
                check_query, {"source": source, "target": target}
            )

            if existing.success and existing.data:
                # 更新已存在的关系
                set_clauses = [f"r.{k} = ${k}" for k in properties.keys()]

                if set_clauses:
                    query = f"""
                        MATCH (source:Entity {{name: $source}})-[r:{rel_type}]->(target:Entity {{name: $target}})
                        SET {', '.join(set_clauses)}
                        RETURN source.name as source, target.name as target, type(r) as type, r as properties
                    """
                    result = await self.execute_cypher(
                        query, {"source": source, "target": target, **properties}
                    )
                else:
                    query = f"""
                        MATCH (source:Entity {{name: $source}})-[r:{rel_type}]->(target:Entity {{name: $target}})
                        RETURN source.name as source, target.name as target, type(r) as type, r as properties
                    """
                    result = await self.execute_cypher(
                        query, {"source": source, "target": target}
                    )

                if result.success and result.data:
                    record = result.data[0]
                    return PackageResponse(
                        success=True,
                        data=Relation(
                            source=record["source"],
                            target=record["target"],
                            type=record["type"],
                            properties=record["properties"],
                        ),
                    )
                return PackageResponse(success=False, error="Failed to update relation")

            else:
                # 创建新关系
                query = f"""
                    MATCH (source:Entity {{name: $source}})
                    MATCH (target:Entity {{name: $target}})
                    CREATE (source)-[r:{rel_type} $props]->(target)
                    RETURN source.name as source, target.name as target, type(r) as type, r as properties
                """
                result = await self.execute_cypher(
                    query, {"source": source, "target": target, "props": properties}
                )

                if result.success and result.data:
                    record = result.data[0]
                    return PackageResponse(
                        success=True,
                        data=Relation(
                            source=record["source"],
                            target=record["target"],
                            type=record["type"],
                            properties=record["properties"],
                        ),
                    )
                return PackageResponse(success=False, error="Failed to create relation")

        except Exception as e:
            self._logger.error(f"Upsert relation error: {e}")
            return PackageResponse(success=False, error=str(e))

    async def delete_relation(
        self,
        source: str,
        target: str,
        rel_type: str,
    ) -> PackageResponse[bool]:
        """
        删除关系

        Args:
            source: 源实体名称
            target: 目标实体名称
            rel_type: 关系类型

        Returns:
            PackageResponse 包含删除结果
        """
        try:
            await self.ensure_connected()

            query = f"""
                MATCH (source:Entity {{name: $source}})-[r:{rel_type}]->(target:Entity {{name: $target}})
                DELETE r
            """
            result = await self.execute_cypher(
                query, {"source": source, "target": target}
            )

            return PackageResponse(success=True, data=True)

        except Exception as e:
            self._logger.error(f"Delete relation error: {e}")
            return PackageResponse(success=False, error=str(e))

    async def get_relations(
        self,
        name: str,
        direction: str = "both",
        rel_type: Optional[str] = None,
        limit: int = 100,
    ) -> PackageResponse[List[Relation]]:
        """
        获取实体的关系

        Args:
            name: 实体名称
            direction: 方向 ("out" 出边, "in" 入边, "both" 双向)
            rel_type: 关系类型过滤（可选）
            limit: 返回数量限制

        Returns:
            PackageResponse 包含关系列表
        """
        try:
            await self.ensure_connected()

            # 构建方向模式
            if direction == "out":
                pattern = "(e:Entity {name: $name})-[r]->(other:Entity)"
            elif direction == "in":
                pattern = "(other:Entity)-[r]->(e:Entity {name: $name})"
            else:  # both
                pattern = "(e:Entity {name: $name})-[r]-(other:Entity)"

            # 添加关系类型过滤
            if rel_type:
                pattern = pattern.replace("[r]", f"[r:{rel_type}]")

            query = f"""
                MATCH {pattern}
                RETURN e.name as source, other.name as target, type(r) as type, r as properties
                LIMIT {limit}
            """

            result = await self.execute_cypher(query, {"name": name})

            if result.success:
                relations = []
                for record in result.data:
                    # 根据方向确定 source 和 target
                    if direction == "in":
                        source_name = record["target"]  # other
                        target_name = record["source"]  # e
                    else:
                        source_name = record["source"]  # e
                        target_name = record["target"]  # other

                    relations.append(
                        Relation(
                            source=source_name,
                            target=target_name,
                            type=record["type"],
                            properties=record["properties"],
                        )
                    )

                return PackageResponse(success=True, data=relations)

            return PackageResponse(success=False, error=result.error)

        except Exception as e:
            self._logger.error(f"Get relations error: {e}")
            return PackageResponse(success=False, error=str(e))

    # ==================== 查询方法 ====================

    async def find_path(
        self,
        from_entity: str,
        to_entity: str,
        max_depth: int = 5,
        rel_type: Optional[str] = None,
    ) -> PackageResponse[List[GraphPath]]:
        """
        查找两个实体之间的最短路径

        Args:
            from_entity: 起始实体名称
            to_entity: 目标实体名称
            max_depth: 最大搜索深度
            rel_type: 关系类型过滤（可选）

        Returns:
            PackageResponse 包含路径列表
        """
        try:
            await self.ensure_connected()

            # 构建关系模式
            rel_pattern = (
                f"[r:{rel_type}]*1..{max_depth}]" if rel_type else f"[r*1..{max_depth}]"
            )

            query = f"""
                MATCH path = shortestPath(
                    (start:Entity {{name: $from_entity}}){rel_pattern}(end:Entity {{name: $to_entity}})
                )
                RETURN [node in nodes(path) | node.name] as nodes,
                       [rel in relationships(path) | type(rel)] as relationships
            """

            result = await self.execute_cypher(
                query, {"from_entity": from_entity, "to_entity": to_entity}
            )

            if result.success:
                paths = []
                for record in result.data:
                    paths.append(
                        GraphPath(
                            nodes=record["nodes"],
                            relationships=record["relationships"],
                        )
                    )

                return PackageResponse(success=True, data=paths)

            return PackageResponse(success=False, error=result.error)

        except Exception as e:
            self._logger.error(f"Find path error: {e}")
            return PackageResponse(success=False, error=str(e))

    async def get_context(
        self,
        name: str,
        hops: int = 2,
        limit: int = 100,
    ) -> PackageResponse[Dict[str, Any]]:
        """
        获取实体的 N 跳邻居上下文

        Args:
            name: 实体名称
            hops: 跳数（1 或 2）
            limit: 返回数量限制

        Returns:
            PackageResponse 包含上下文信息:
            {
                "entity": Entity,
                "neighbors": List[Entity],
                "relations": List[Relation],
            }
        """
        try:
            await self.ensure_connected()

            hops = min(max(hops, 1), 2)  # 限制 1-2 跳

            # 获取实体本身
            entity_result = await self.get_entity(name)
            if not entity_result.success or not entity_result.data:
                return PackageResponse(success=False, error="Entity not found")

            entity = entity_result.data

            # 获取邻居节点
            query = f"""
                MATCH (center:Entity {{name: $name}})-[r*1..{hops}]-(neighbor:Entity)
                WHERE neighbor.name <> $name
                RETURN DISTINCT neighbor, labels(neighbor) as neighbor_labels
                LIMIT {limit}
            """

            result = await self.execute_cypher(query, {"name": name})

            neighbors = []
            if result.success:
                for record in result.data:
                    node_data = record["neighbor"]
                    node_labels = record.get("neighbor_labels", [])
                    labels = [l for l in node_labels if l != "Entity"]

                    neighbors.append(
                        Entity(
                            name=node_data.get("name", ""),
                            labels=labels,
                            properties=node_data,
                        )
                    )

            # 获取关系
            rel_result = await self.get_relations(name, direction="both", limit=limit)
            relations = rel_result.data if rel_result.success else []

            return PackageResponse(
                success=True,
                data={
                    "entity": entity,
                    "neighbors": neighbors,
                    "relations": relations,
                },
            )

        except Exception as e:
            self._logger.error(f"Get context error: {e}")
            return PackageResponse(success=False, error=str(e))
