"""
DB Process Package 测试
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestDBProcessInit:
    """测试初始化"""

    def test_init_with_env_vars(self, monkeypatch):
        """测试从环境变量初始化"""
        monkeypatch.setenv("PG_HOST", "localhost")
        monkeypatch.setenv("PG_PORT", "5432")
        monkeypatch.setenv("PG_USER", "test_user")
        monkeypatch.setenv("PG_PASSWORD", "test_pass")
        monkeypatch.setenv("PG_DB", "test_db")

        from ember_v2.packages.db_process import DBProcess

        db = DBProcess()

        assert db._host == "localhost"
        assert db._port == 5432
        assert db._user == "test_user"
        assert db._password == "test_pass"
        assert db._database == "test_db"

    def test_init_with_config_file(self, tmp_path):
        """测试从配置文件初始化"""
        config_content = """
database:
  host: config_host
  port: 5433
  user: config_user
  password: config_pass
  database: config_db

pool:
  min_size: 10
  max_size: 50
"""
        config_file = tmp_path / "config.yaml"
        config_file.write_text(config_content)

        from ember_v2.packages.db_process import DBProcess

        db = DBProcess(config_path=str(config_file))

        assert db.get_config_value("database.host") == "config_host"
        assert db.get_config_value("pool.min_size") == 10


class TestDBProcessConnection:
    """测试连接管理"""

    @pytest.mark.asyncio
    async def test_connect_success(self, monkeypatch):
        """测试连接成功"""
        from ember_v2.packages.db_process import DBProcess

        # Mock asyncpg
        mock_pool = AsyncMock()
        mock_pool.get_size = MagicMock(return_value=5)
        mock_pool.get_idle_size = MagicMock(return_value=3)

        mock_asyncpg = MagicMock()
        mock_asyncpg.create_pool = AsyncMock(return_value=mock_pool)

        with patch.dict("sys.modules", {"asyncpg": mock_asyncpg}):
            db = DBProcess()
            result = await db.connect()

            assert result.success
            assert db.is_connected

    @pytest.mark.asyncio
    async def test_connect_failure(self, monkeypatch):
        """测试连接失败"""
        from ember_v2.packages.db_process import DBProcess

        mock_asyncpg = MagicMock()
        mock_asyncpg.create_pool = AsyncMock(
            side_effect=Exception("Connection refused")
        )

        with patch.dict("sys.modules", {"asyncpg": mock_asyncpg}):
            db = DBProcess()
            result = await db.connect()

            assert not result.success
            assert "Connection refused" in result.error

    @pytest.mark.asyncio
    async def test_disconnect(self):
        """测试断开连接"""
        from ember_v2.packages.db_process import DBProcess

        mock_pool = AsyncMock()

        db = DBProcess()
        db._pool = mock_pool
        db._is_connected = True

        await db.disconnect()

        mock_pool.close.assert_called_once()
        assert not db.is_connected


class TestDBProcessBasicOps:
    """测试基础操作"""

    @pytest.fixture
    def mock_db(self):
        """创建 Mock 数据库实例"""
        from ember_v2.packages.db_process import DBProcess

        db = DBProcess()
        db._pool = AsyncMock()
        db._is_connected = True
        return db

    @pytest.mark.asyncio
    async def test_execute(self, mock_db):
        """测试执行 SQL"""
        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(return_value="UPDATE 5")
        mock_db._pool.acquire = MagicMock(
            return_value=AsyncMock(__aenter__=AsyncMock(return_value=mock_conn))
        )

        result = await mock_db.execute(
            "UPDATE users SET name = $1 WHERE id = $2", ("test", 1)
        )

        assert result.success
        assert result.data == 5

    @pytest.mark.asyncio
    async def test_fetch_one(self, mock_db):
        """测试查询单条"""
        mock_row = MagicMock()
        mock_row.__iter__ = lambda self: iter([("id", 1), ("name", "test")])
        mock_row.keys = lambda: ["id", "name"]
        mock_row.__getitem__ = lambda self, key: {"id": 1, "name": "test"}[key]

        # 创建一个可以转换为 dict 的 mock
        class MockRecord(dict):
            pass

        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(
            return_value=MockRecord({"id": 1, "name": "test"})
        )
        mock_db._pool.acquire = MagicMock(
            return_value=AsyncMock(__aenter__=AsyncMock(return_value=mock_conn))
        )

        result = await mock_db.fetch_one("SELECT * FROM users WHERE id = $1", (1,))

        assert result.success
        assert result.data == {"id": 1, "name": "test"}

    @pytest.mark.asyncio
    async def test_fetch_all(self, mock_db):
        """测试查询多条"""

        class MockRecord(dict):
            pass

        mock_rows = [
            MockRecord({"id": 1, "name": "user1"}),
            MockRecord({"id": 2, "name": "user2"}),
        ]

        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(return_value=mock_rows)
        mock_db._pool.acquire = MagicMock(
            return_value=AsyncMock(__aenter__=AsyncMock(return_value=mock_conn))
        )

        result = await mock_db.fetch_all("SELECT * FROM users")

        assert result.success
        assert len(result.data) == 2
        assert result.data[0]["name"] == "user1"

    @pytest.mark.asyncio
    async def test_fetch_value(self, mock_db):
        """测试查询单个值"""
        mock_conn = AsyncMock()
        mock_conn.fetchval = AsyncMock(return_value=42)
        mock_db._pool.acquire = MagicMock(
            return_value=AsyncMock(__aenter__=AsyncMock(return_value=mock_conn))
        )

        result = await mock_db.fetch_value("SELECT COUNT(*) FROM users")

        assert result.success
        assert result.data == 42


class TestDBProcessTransaction:
    """测试事务"""

    @pytest.mark.asyncio
    async def test_transaction_context(self):
        """测试事务上下文管理器"""
        from ember_v2.packages.db_process import DBProcess

        db = DBProcess()
        db._pool = AsyncMock()
        db._is_connected = True

        mock_conn = AsyncMock()
        mock_transaction = AsyncMock()
        mock_transaction.__aenter__ = AsyncMock()
        mock_transaction.__aexit__ = AsyncMock()
        mock_conn.transaction = MagicMock(return_value=mock_transaction)

        db._pool.acquire = MagicMock(
            return_value=AsyncMock(__aenter__=AsyncMock(return_value=mock_conn))
        )

        async with db.transaction() as tx:
            pass  # 模拟事务操作

        # 验证事务被正确调用
        mock_conn.transaction.assert_called_once()

    @pytest.mark.asyncio
    async def test_execute_in_transaction(self):
        """测试事务中执行多条语句"""
        from ember_v2.packages.db_process import DBProcess

        db = DBProcess()
        db._pool = AsyncMock()
        db._is_connected = True

        mock_conn = AsyncMock()
        mock_transaction = AsyncMock()
        mock_transaction.__aenter__ = AsyncMock()
        mock_transaction.__aexit__ = AsyncMock()
        mock_conn.transaction = MagicMock(return_value=mock_transaction)
        mock_conn.execute = AsyncMock()

        db._pool.acquire = MagicMock(
            return_value=AsyncMock(__aenter__=AsyncMock(return_value=mock_conn))
        )

        statements = [
            ("INSERT INTO users (name) VALUES ($1)", ("user1",)),
            ("UPDATE stats SET count = count + 1", ()),
        ]

        result = await db.execute_in_transaction(statements)

        assert result.success


class TestDBProcessVector:
    """测试向量操作"""

    @pytest.fixture
    def mock_db(self):
        """创建 Mock 数据库实例"""
        from ember_v2.packages.db_process import DBProcess

        db = DBProcess()
        db._pool = AsyncMock()
        db._is_connected = True
        return db

    @pytest.mark.asyncio
    async def test_insert_embedding(self, mock_db):
        """测试插入向量"""
        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(return_value="INSERT 1")
        mock_db._pool.acquire = MagicMock(
            return_value=AsyncMock(__aenter__=AsyncMock(return_value=mock_conn))
        )

        embedding = [0.1, 0.2, 0.3, 0.4, 0.5]
        result = await mock_db.insert_embedding(
            table="embeddings",
            id_column="id",
            id_value=1,
            embedding_column="vector",
            embedding=embedding,
        )

        # 验证 SQL 被调用
        mock_conn.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_search_similar(self, mock_db):
        """测试向量搜索"""

        class MockRecord(dict):
            pass

        mock_rows = [
            MockRecord({"id": 1, "content": "text1", "similarity": 0.95}),
            MockRecord({"id": 2, "content": "text2", "similarity": 0.85}),
        ]

        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(return_value=mock_rows)
        mock_db._pool.acquire = MagicMock(
            return_value=AsyncMock(__aenter__=AsyncMock(return_value=mock_conn))
        )

        query_embedding = [0.1, 0.2, 0.3, 0.4, 0.5]
        result = await mock_db.search_similar(
            table="embeddings",
            embedding_column="vector",
            query_embedding=query_embedding,
            limit=5,
        )

        assert result.success
        assert len(result.data) == 2
        assert result.data[0].similarity == 0.95


class TestDBProcessBatch:
    """测试批量操作"""

    @pytest.fixture
    def mock_db(self):
        """创建 Mock 数据库实例"""
        from ember_v2.packages.db_process import DBProcess

        db = DBProcess()
        db._pool = AsyncMock()
        db._is_connected = True
        return db

    @pytest.mark.asyncio
    async def test_insert_batch(self, mock_db):
        """测试批量插入"""

        class MockRecord(dict):
            pass

        mock_rows = [MockRecord({"id": 1}), MockRecord({"id": 2})]

        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(return_value=mock_rows)
        mock_db._pool.acquire = MagicMock(
            return_value=AsyncMock(__aenter__=AsyncMock(return_value=mock_conn))
        )

        data = [{"name": "user1", "age": 20}, {"name": "user2", "age": 25}]

        result = await mock_db.insert_batch("users", data, returning="id")

        assert result.success
        assert len(result.data) == 2

    @pytest.mark.asyncio
    async def test_insert_batch_empty(self, mock_db):
        """测试空批量插入"""
        result = await mock_db.insert_batch("users", [])

        assert result.success
        assert result.data == []


class TestDBProcessUtils:
    """测试工具方法"""

    @pytest.fixture
    def mock_db(self):
        """创建 Mock 数据库实例"""
        from ember_v2.packages.db_process import DBProcess

        db = DBProcess()
        db._pool = AsyncMock()
        db._is_connected = True
        return db

    @pytest.mark.asyncio
    async def test_table_exists_true(self, mock_db):
        """测试表存在"""
        mock_conn = AsyncMock()
        mock_conn.fetchval = AsyncMock(return_value=True)
        mock_db._pool.acquire = MagicMock(
            return_value=AsyncMock(__aenter__=AsyncMock(return_value=mock_conn))
        )

        result = await mock_db.table_exists("users")

        assert result.success
        assert result.data == True

    @pytest.mark.asyncio
    async def test_health_check(self, mock_db):
        """测试健康检查"""
        mock_conn = AsyncMock()
        mock_conn.fetchval = AsyncMock(return_value=1)
        mock_db._pool.acquire = MagicMock(
            return_value=AsyncMock(__aenter__=AsyncMock(return_value=mock_conn))
        )

        result = await mock_db.health_check()

        assert result.success
        assert result.data == True

    @pytest.mark.asyncio
    async def test_get_pool_stats(self):
        """测试获取连接池统计"""
        from ember_v2.packages.db_process import DBProcess

        db = DBProcess()
        db._pool = MagicMock()
        db._pool.get_size = MagicMock(return_value=10)
        db._pool.get_idle_size = MagicMock(return_value=7)

        stats = await db.get_pool_stats()

        assert stats.total_connections == 10
        assert stats.idle_connections == 7
