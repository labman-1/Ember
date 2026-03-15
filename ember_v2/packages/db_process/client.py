"""
DB Process Package
PostgreSQL 数据库处理器

功能:
- 连接池管理
- 并发执行支持
- 事务支持
- 向量操作 (pgvector)
- 批量操作
"""

import os
import asyncio
import logging
from typing import Optional, List, Dict, Any, Tuple, AsyncGenerator
from contextlib import asynccontextmanager

from ember_v2.core.package_base import BasePackage
from ember_v2.core.types import PackageResponse

from .types import PoolStats, QueryResult, VectorSearchResult

logger = logging.getLogger(__name__)


class DBProcess(BasePackage):
    """
    PostgreSQL 数据库处理器

    特性:
    - 自动连接池管理
    - 异步并发执行
    - 事务支持
    - pgvector 向量操作
    - 自动重连机制
    """

    def __init__(self, config_path: Optional[str] = None):
        """
        初始化数据库处理器

        Args:
            config_path: 配置文件路径
        """
        super().__init__(config_path)

        # 从环境变量或配置读取数据库连接信息
        self._host = os.getenv("PG_HOST") or self.get_config_value(
            "database.host", "localhost"
        )
        self._port = int(
            os.getenv("PG_PORT") or self.get_config_value("database.port", 5432)
        )
        self._user = os.getenv("PG_USER") or self.get_config_value(
            "database.user", "postgres"
        )
        self._password = os.getenv("PG_PASSWORD") or self.get_config_value(
            "database.password", ""
        )
        self._database = os.getenv("PG_DB") or self.get_config_value(
            "database.database", "ember_db"
        )

        # 连接池配置
        self._min_pool_size = self.get_config_value("pool.min_size", 5)
        self._max_pool_size = self.get_config_value("pool.max_size", 20)
        self._pool_timeout = self.get_config_value("pool.timeout", 30)
        self._idle_timeout = self.get_config_value("pool.idle_timeout", 300)

        # 连接池
        self._pool = None
        self._is_connected = False

        self._logger.info(
            f"DBProcess initialized for {self._host}:{self._port}/{self._database}"
        )

    async def connect(self) -> PackageResponse[bool]:
        """
        建立数据库连接，初始化连接池

        Returns:
            PackageResponse 包含连接结果
        """
        try:
            import asyncpg

            self._pool = await asyncpg.create_pool(
                host=self._host,
                port=self._port,
                user=self._user,
                password=self._password,
                database=self._database,
                min_size=self._min_pool_size,
                max_size=self._max_pool_size,
                timeout=self._pool_timeout,
            )

            self._is_connected = True
            self._logger.info("Database connection pool created successfully")

            return PackageResponse(success=True, data=True)

        except Exception as e:
            self._logger.error(f"Failed to create connection pool: {e}")
            return PackageResponse(success=False, error=str(e))

    async def disconnect(self) -> None:
        """关闭连接池"""
        if self._pool:
            await self._pool.close()
            self._pool = None
            self._is_connected = False
            self._logger.info("Database connection pool closed")

    async def ensure_connected(self) -> None:
        """确保已连接"""
        if not self._is_connected or not self._pool:
            result = await self.connect()
            if not result.success:
                raise ConnectionError(f"Database connection failed: {result.error}")

    @property
    def is_connected(self) -> bool:
        """是否已连接"""
        return self._is_connected

    # ==================== 基础操作 ====================

    async def execute(
        self, sql: str, params: Tuple = (), timeout: Optional[float] = None
    ) -> PackageResponse[int]:
        """
        执行 SQL 语句（INSERT, UPDATE, DELETE）

        Args:
            sql: SQL 语句
            params: 参数元组
            timeout: 超时时间

        Returns:
            PackageResponse 包含影响行数
        """
        try:
            await self.ensure_connected()

            async with self._pool.acquire(timeout=timeout) as conn:
                result = await conn.execute(sql, *params)

                # 解析影响行数 (如 "UPDATE 5")
                affected = 0
                if result:
                    parts = result.split()
                    if len(parts) >= 2:
                        try:
                            affected = int(parts[1])
                        except ValueError:
                            pass

                return PackageResponse(success=True, data=affected)

        except Exception as e:
            self._logger.error(f"Execute error: {e}\nSQL: {sql}")
            return PackageResponse(success=False, error=str(e))

    async def fetch_one(
        self, sql: str, params: Tuple = (), timeout: Optional[float] = None
    ) -> PackageResponse[Optional[Dict]]:
        """
        查询单条记录

        Args:
            sql: SQL 语句
            params: 参数元组
            timeout: 超时时间

        Returns:
            PackageResponse 包含单条记录（字典）或 None
        """
        try:
            await self.ensure_connected()

            async with self._pool.acquire(timeout=timeout) as conn:
                row = await conn.fetchrow(sql, *params)

                if row is None:
                    return PackageResponse(success=True, data=None)

                # 转换为字典
                return PackageResponse(success=True, data=dict(row))

        except Exception as e:
            self._logger.error(f"Fetch one error: {e}\nSQL: {sql}")
            return PackageResponse(success=False, error=str(e))

    async def fetch_all(
        self, sql: str, params: Tuple = (), timeout: Optional[float] = None
    ) -> PackageResponse[List[Dict]]:
        """
        查询多条记录

        Args:
            sql: SQL 语句
            params: 参数元组
            timeout: 超时时间

        Returns:
            PackageResponse 包含记录列表
        """
        try:
            await self.ensure_connected()

            async with self._pool.acquire(timeout=timeout) as conn:
                rows = await conn.fetch(sql, *params)

                # 转换为字典列表
                result = [dict(row) for row in rows]
                return PackageResponse(success=True, data=result)

        except Exception as e:
            self._logger.error(f"Fetch all error: {e}\nSQL: {sql}")
            return PackageResponse(success=False, error=str(e))

    async def fetch_value(
        self, sql: str, params: Tuple = (), timeout: Optional[float] = None
    ) -> PackageResponse[Any]:
        """
        查询单个值

        Args:
            sql: SQL 语句
            params: 参数元组
            timeout: 超时时间

        Returns:
            PackageResponse 包含单个值
        """
        try:
            await self.ensure_connected()

            async with self._pool.acquire(timeout=timeout) as conn:
                value = await conn.fetchval(sql, *params)
                return PackageResponse(success=True, data=value)

        except Exception as e:
            self._logger.error(f"Fetch value error: {e}\nSQL: {sql}")
            return PackageResponse(success=False, error=str(e))

    # ==================== 事务支持 ====================

    @asynccontextmanager
    async def transaction(self) -> AsyncGenerator[Any, None]:
        """
        事务上下文管理器

        用法:
            async with db.transaction() as tx:
                await tx.execute("INSERT INTO ...")
                await tx.execute("UPDATE ...")
            # 自动 commit 或 rollback

        Yields:
            数据库连接（带事务）
        """
        await self.ensure_connected()

        async with self._pool.acquire() as conn:
            async with conn.transaction():
                yield conn

    async def execute_in_transaction(
        self, statements: List[Tuple[str, Tuple]]
    ) -> PackageResponse[bool]:
        """
        在事务中执行多条语句

        Args:
            statements: [(sql, params), ...] 语句列表

        Returns:
            PackageResponse 包含执行结果
        """
        try:
            await self.ensure_connected()

            async with self._pool.acquire() as conn:
                async with conn.transaction():
                    for sql, params in statements:
                        await conn.execute(sql, *params)

            return PackageResponse(success=True, data=True)

        except Exception as e:
            self._logger.error(f"Transaction error: {e}")
            return PackageResponse(success=False, error=str(e))

    # ==================== 向量操作 ====================

    async def create_vector_extension(self) -> PackageResponse[bool]:
        """
        创建 pgvector 扩展

        Returns:
            PackageResponse 包含执行结果
        """
        return await self.execute("CREATE EXTENSION IF NOT EXISTS vector;")

    async def insert_embedding(
        self,
        table: str,
        id_column: str,
        id_value: Any,
        embedding_column: str,
        embedding: List[float],
        additional_data: Optional[Dict] = None,
    ) -> PackageResponse[bool]:
        """
        插入向量

        Args:
            table: 表名
            id_column: ID 列名
            id_value: ID 值
            embedding_column: 向量列名
            embedding: 向量数据
            additional_data: 额外数据

        Returns:
            PackageResponse 包含执行结果
        """
        try:
            await self.ensure_connected()

            # 构建向量字符串
            embedding_str = "[" + ",".join(str(x) for x in embedding) + "]"

            if additional_data:
                columns = [id_column, embedding_column] + list(additional_data.keys())
                values = [id_value, embedding_str] + list(additional_data.values())
                placeholders = ", ".join(["$" + str(i + 1) for i in range(len(values))])
                columns_str = ", ".join(columns)
                sql = f"INSERT INTO {table} ({columns_str}) VALUES ({placeholders})"
                params = tuple(values)
            else:
                sql = f"INSERT INTO {table} ({id_column}, {embedding_column}) VALUES ($1, $2)"
                params = (id_value, embedding_str)

            result = await self.execute(sql, params)
            return result

        except Exception as e:
            self._logger.error(f"Insert embedding error: {e}")
            return PackageResponse(success=False, error=str(e))

    async def search_similar(
        self,
        table: str,
        embedding_column: str,
        query_embedding: List[float],
        limit: int = 10,
        filter_sql: Optional[str] = None,
        columns: Optional[List[str]] = None,
    ) -> PackageResponse[List[VectorSearchResult]]:
        """
        向量相似度搜索

        Args:
            table: 表名
            embedding_column: 向量列名
            query_embedding: 查询向量
            limit: 返回数量限制
            filter_sql: 额外的 WHERE 条件
            columns: 返回的列名列表

        Returns:
            PackageResponse 包含搜索结果列表
        """
        try:
            await self.ensure_connected()

            # 构建向量字符串
            embedding_str = "[" + ",".join(str(x) for x in query_embedding) + "]"

            # 构建查询
            select_columns = ", ".join(columns) if columns else "*"

            sql = f"""
                SELECT {select_columns}, 
                       1 - ({embedding_column} <=> $1::vector) as similarity
                FROM {table}
            """

            if filter_sql:
                sql += f" WHERE {filter_sql}"

            sql += f" ORDER BY {embedding_column} <=> $1::vector LIMIT {limit}"

            async with self._pool.acquire() as conn:
                rows = await conn.fetch(sql, embedding_str)

                results = []
                for row in rows:
                    row_dict = dict(row)
                    similarity = row_dict.pop("similarity", 0)
                    results.append(
                        VectorSearchResult(
                            id=row_dict.get("id"), similarity=similarity, data=row_dict
                        )
                    )

                return PackageResponse(success=True, data=results)

        except Exception as e:
            self._logger.error(f"Vector search error: {e}")
            return PackageResponse(success=False, error=str(e))

    # ==================== 批量操作 ====================

    async def insert_batch(
        self, table: str, data: List[Dict], returning: Optional[str] = None
    ) -> PackageResponse[List[Any]]:
        """
        批量插入

        Args:
            table: 表名
            data: 数据字典列表
            returning: RETURNING 子句（如 "id"）

        Returns:
            PackageResponse 包含插入的 ID 列表
        """
        if not data:
            return PackageResponse(success=True, data=[])

        try:
            await self.ensure_connected()

            # 获取列名
            columns = list(data[0].keys())
            columns_str = ", ".join(columns)

            # 构建批量插入语句
            values_placeholders = []
            flat_values = []
            placeholder_idx = 1

            for row in data:
                row_placeholders = []
                for col in columns:
                    row_placeholders.append(f"${placeholder_idx}")
                    flat_values.append(row[col])
                    placeholder_idx += 1
                values_placeholders.append("(" + ", ".join(row_placeholders) + ")")

            sql = f"INSERT INTO {table} ({columns_str}) VALUES {', '.join(values_placeholders)}"

            if returning:
                sql += f" RETURNING {returning}"

            async with self._pool.acquire() as conn:
                if returning:
                    rows = await conn.fetch(sql, *flat_values)
                    result = [row[returning] for row in rows]
                else:
                    await conn.execute(sql, *flat_values)
                    result = []

            return PackageResponse(success=True, data=result)

        except Exception as e:
            self._logger.error(f"Batch insert error: {e}")
            return PackageResponse(success=False, error=str(e))

    async def execute_batch(
        self, statements: List[Tuple[str, Tuple]]
    ) -> PackageResponse[int]:
        """
        批量执行 SQL 语句（不在事务中）

        Args:
            statements: [(sql, params), ...] 语句列表

        Returns:
            PackageResponse 包含执行成功的语句数量
        """
        success_count = 0

        for sql, params in statements:
            result = await self.execute(sql, params)
            if result.success:
                success_count += 1

        return PackageResponse(success=True, data=success_count)

    # ==================== 工具方法 ====================

    async def table_exists(self, table_name: str) -> PackageResponse[bool]:
        """
        检查表是否存在

        Args:
            table_name: 表名

        Returns:
            PackageResponse 包含是否存在
        """
        sql = """
            SELECT EXISTS (
                SELECT FROM information_schema.tables 
                WHERE table_name = $1
            )
        """
        result = await self.fetch_value(sql, (table_name,))
        return result

    async def get_pool_stats(self) -> PoolStats:
        """
        获取连接池统计信息

        Returns:
            PoolStats 连接池状态
        """
        if not self._pool:
            return PoolStats()

        return PoolStats(
            total_connections=self._pool.get_size(),
            idle_connections=self._pool.get_idle_size(),
            max_connections=self._max_pool_size,
        )

    async def health_check(self) -> PackageResponse[bool]:
        """
        健康检查

        Returns:
            PackageResponse 包含是否健康
        """
        try:
            await self.ensure_connected()
            result = await self.fetch_value("SELECT 1")
            if result.success:
                return PackageResponse(success=True, data=result.data == 1)
            return PackageResponse(success=False, error=result.error)
        except Exception as e:
            return PackageResponse(success=False, error=str(e))
