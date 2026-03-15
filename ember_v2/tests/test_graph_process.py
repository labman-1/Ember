"""
Graph Process Package 测试
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestGraphProcessInit:
    """测试初始化"""

    def test_init_with_env_vars(self, monkeypatch):
        """测试从环境变量初始化"""
        monkeypatch.setenv("NEO4J_URI", "bolt://test-host:7687")
        monkeypatch.setenv("NEO4J_USER", "test_user")
        monkeypatch.setenv("NEO4J_PASSWORD", "test_pass")
        monkeypatch.setenv("NEO4J_DATABASE", "test_db")

        from ember_v2.packages.graph_process import GraphProcess

        graph = GraphProcess()

        assert graph._uri == "bolt://test-host:7687"
        assert graph._user == "test_user"
        assert graph._password == "test_pass"
        assert graph._database == "test_db"

    def test_init_with_config_file(self, tmp_path):
        """测试从配置文件初始化"""
        config_content = """
neo4j:
  uri: "bolt://config-host:7687"
  user: "config_user"
  password: "config_pass"
  database: "config_db"

pool:
  max_connection_lifetime: 7200
  max_connection_pool_size: 100

features:
  check_apoc: false
"""
        config_file = tmp_path / "config.yaml"
        config_file.write_text(config_content)

        from ember_v2.packages.graph_process import GraphProcess

        graph = GraphProcess(config_path=str(config_file))

        assert graph.get_config_value("neo4j.uri") == "bolt://config-host:7687"
        assert graph.get_config_value("pool.max_connection_pool_size") == 100
        assert graph.get_config_value("features.check_apoc") == False

    def test_default_values(self):
        """测试默认值"""
        from ember_v2.packages.graph_process import GraphProcess

        graph = GraphProcess()

        assert graph._uri == "bolt://localhost:7687"
        assert graph._user == "neo4j"
        assert graph._database == "neo4j"
        assert graph._max_connection_pool_size == 50
        assert graph._connection_timeout == 30


class TestGraphProcessConnection:
    """测试连接管理"""

    @pytest.fixture
    def mock_driver(self):
        """创建 Mock Neo4j 驱动"""
        driver = AsyncMock()
        driver.verify_connectivity = AsyncMock()
        driver.close = AsyncMock()
        return driver

    @pytest.fixture
    def mock_session(self):
        """创建 Mock 会话"""
        session = AsyncMock()
        result = AsyncMock()
        result.data = AsyncMock(return_value=[])
        session.run = AsyncMock(return_value=result)
        return session

    @pytest.mark.asyncio
    async def test_connect_success(self, monkeypatch, mock_driver, mock_session):
        """测试连接成功"""
        from ember_v2.packages.graph_process import GraphProcess

        # Mock neo4j driver
        mock_driver_class = MagicMock(return_value=mock_driver)
        mock_driver.verify_connectivity = AsyncMock()
        
        # Mock session for constraint creation
        mock_driver.session = MagicMock(
            return_value=AsyncMock(__aenter__=AsyncMock(return_value=mock_session))
        )

        mock_neo4j = MagicMock()
        mock_neo4j.AsyncGraphDatabase = MagicMock()
        mock_neo4j.AsyncGraphDatabase.driver = MagicMock(return_value=mock_driver)

        with patch.dict("sys.modules", {"neo4j": mock_neo4j}):
            graph = GraphProcess()
            result = await graph.connect()

            assert result.success
            assert graph.is_connected

    @pytest.mark.asyncio
    async def test_connect_failure(self, monkeypatch):
        """测试连接失败"""
        from ember_v2.packages.graph_process import GraphProcess

        mock_neo4j = MagicMock()
        mock_neo4j.AsyncGraphDatabase = MagicMock()
        mock_neo4j.AsyncGraphDatabase.driver = MagicMock(
            side_effect=Exception("Connection refused")
        )

        with patch.dict("sys.modules", {"neo4j": mock_neo4j}):
            graph = GraphProcess()
            result = await graph.connect()

            assert not result.success
            assert "Connection refused" in result.error

    @pytest.mark.asyncio
    async def test_disconnect(self):
        """测试断开连接"""
        from ember_v2.packages.graph_process import GraphProcess

        mock_driver = AsyncMock()

        graph = GraphProcess()
        graph._driver = mock_driver
        graph._is_connected = True

        await graph.disconnect()

        mock_driver.close.assert_called_once()
        assert not graph.is_connected

    @pytest.mark.asyncio
    async def test_ensure_connected(self, monkeypatch):
        """测试确保连接"""
        from ember_v2.packages.graph_process import GraphProcess

        mock_driver = AsyncMock()
        mock_driver.verify_connectivity = AsyncMock()
        mock_session = AsyncMock()
        mock_result = AsyncMock()
        mock_result.data = AsyncMock(return_value=[])
        mock_session.run = AsyncMock(return_value=mock_result)
        mock_driver.session = MagicMock(
            return_value=AsyncMock(__aenter__=AsyncMock(return_value=mock_session))
        )

        mock_neo4j = MagicMock()
        mock_neo4j.AsyncGraphDatabase = MagicMock()
        mock_neo4j.AsyncGraphDatabase.driver = MagicMock(return_value=mock_driver)

        with patch.dict("sys.modules", {"neo4j": mock_neo4j}):
            graph = GraphProcess()
            
            # 未连接时应该自动连接
            await graph.ensure_connected()
            
            assert graph.is_connected


class TestGraphProcessCypher:
    """测试 Cypher 执行"""

    @pytest.fixture
    def mock_graph(self):
        """创建 Mock GraphProcess 实例"""
        from ember_v2.packages.graph_process import GraphProcess

        graph = GraphProcess()
        graph._driver = AsyncMock()
        graph._is_connected = True
        return graph

    @pytest.mark.asyncio
    async def test_execute_cypher_success(self, mock_graph):
        """测试成功执行 Cypher"""
        mock_result = AsyncMock()
        mock_result.data = AsyncMock(return_value=[{"name": "依鸣", "age": 18}])

        mock_session = AsyncMock()
        mock_session.run = AsyncMock(return_value=mock_result)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock()

        mock_graph._driver.session = MagicMock(return_value=mock_session)

        result = await mock_graph.execute_cypher(
            "MATCH (n:Person) WHERE n.name = $name RETURN n",
            {"name": "依鸣"}
        )

        assert result.success
        assert len(result.data) == 1
        assert result.data[0]["name"] == "依鸣"

    @pytest.mark.asyncio
    async def test_execute_cypher_error(self, mock_graph):
        """测试 Cypher 执行错误"""
        mock_session = AsyncMock()
        mock_session.run = AsyncMock(side_effect=Exception("Syntax error"))
        
        # 创建正确的 async context manager mock
        async_context = AsyncMock()
        async_context.__aenter__ = AsyncMock(return_value=mock_session)
        async_context.__aexit__ = AsyncMock(return_value=None)
        
        mock_graph._driver.session = MagicMock(return_value=async_context)

        result = await mock_graph.execute_cypher("INVALID CYPHER")

        assert not result.success
        assert "Syntax error" in result.error

    @pytest.mark.asyncio
    async def test_execute_cypher_empty_result(self, mock_graph):
        """测试空结果"""
        mock_result = AsyncMock()
        mock_result.data = AsyncMock(return_value=[])

        mock_session = AsyncMock()
        mock_session.run = AsyncMock(return_value=mock_result)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock()

        mock_graph._driver.session = MagicMock(return_value=mock_session)

        result = await mock_graph.execute_cypher("MATCH (n:NotFound) RETURN n")

        assert result.success
        assert result.data == []


class TestGraphProcessEntity:
    """测试实体操作"""

    @pytest.fixture
    def mock_graph(self):
        """创建 Mock GraphProcess 实例"""
        from ember_v2.packages.graph_process import GraphProcess

        graph = GraphProcess()
        graph._driver = AsyncMock()
        graph._is_connected = True
        return graph

    @pytest.mark.asyncio
    async def test_upsert_entity_create_new(self, mock_graph):
        """测试创建新实体"""
        # Mock 查找结果为空（不存在）
        mock_find_result = AsyncMock()
        mock_find_result.data = AsyncMock(return_value=[])

        # Mock 创建结果
        mock_create_result = AsyncMock()
        mock_create_result.data = AsyncMock(return_value=[
            {"e": {"name": "依鸣", "aliases": ["Yiming"]}}
        ])

        call_count = 0

        async def mock_run(query, params=None):
            nonlocal call_count
            call_count += 1
            if "MATCH" in query:
                return mock_find_result
            else:
                return mock_create_result

        mock_session = AsyncMock()
        mock_session.run = mock_run
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock()

        mock_graph._driver.session = MagicMock(return_value=mock_session)

        from ember_v2.packages.graph_process import UpsertMode

        result = await mock_graph.upsert_entity(
            name="依鸣",
            labels=["Person", "Character"],
            properties={"age": 18, "school": "南京大学"},
            aliases=["Yiming"],
            mode=UpsertMode.OVERWRITE
        )

        assert result.success
        assert result.data.name == "依鸣"

    @pytest.mark.asyncio
    async def test_upsert_entity_update_existing(self, mock_graph):
        """测试更新已存在的实体"""
        # Mock 查找到已存在的实体
        mock_find_result = AsyncMock()
        mock_find_result.data = AsyncMock(return_value=[
            {"e": {"name": "依鸣", "age": 17, "aliases": ["Yiming"]}}
        ])

        # Mock 更新结果
        mock_update_result = AsyncMock()
        mock_update_result.data = AsyncMock(return_value=[
            {"e": {"name": "依鸣", "age": 18, "aliases": ["Yiming", "依鸣酱"]}}
        ])

        async def mock_run(query, params=None):
            if "MATCH" in query and "RETURN" in query and "CREATE" not in query:
                return mock_find_result
            return mock_update_result

        mock_session = AsyncMock()
        mock_session.run = mock_run
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock()

        mock_graph._driver.session = MagicMock(return_value=mock_session)

        from ember_v2.packages.graph_process import UpsertMode

        result = await mock_graph.upsert_entity(
            name="依鸣",
            properties={"age": 18},
            aliases=["依鸣酱"],
            mode=UpsertMode.INCREMENT
        )

        assert result.success

    @pytest.mark.asyncio
    async def test_find_entity_by_name(self, mock_graph):
        """测试通过名称查找实体"""
        mock_result = AsyncMock()
        mock_result.data = AsyncMock(return_value=[
            {"e": {"name": "依鸣", "age": 18}}
        ])

        mock_session = AsyncMock()
        mock_session.run = AsyncMock(return_value=mock_result)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock()

        mock_graph._driver.session = MagicMock(return_value=mock_session)

        result = await mock_graph._find_entity_by_name_or_alias("依鸣")

        assert result is not None
        assert result["name"] == "依鸣"

    @pytest.mark.asyncio
    async def test_find_entity_by_alias(self, mock_graph):
        """测试通过别名查找实体"""
        # 名称查找失败
        mock_name_result = AsyncMock()
        mock_name_result.data = AsyncMock(return_value=[])

        # 别名查找成功
        mock_alias_result = AsyncMock()
        mock_alias_result.data = AsyncMock(return_value=[
            {"e": {"name": "依鸣", "aliases": ["Yiming"]}}
        ])

        call_count = 0

        async def mock_run(query, params=None):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return mock_name_result
            return mock_alias_result

        mock_session = AsyncMock()
        mock_session.run = mock_run
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock()

        mock_graph._driver.session = MagicMock(return_value=mock_session)

        result = await mock_graph._find_entity_by_name_or_alias("Yiming", ["Yiming"])

        assert result is not None
        assert result["name"] == "依鸣"


class TestGraphProcessHealthCheck:
    """测试健康检查"""

    @pytest.fixture
    def mock_graph(self):
        """创建 Mock GraphProcess 实例"""
        from ember_v2.packages.graph_process import GraphProcess

        graph = GraphProcess()
        graph._driver = AsyncMock()
        graph._is_connected = True
        return graph

    @pytest.mark.asyncio
    async def test_health_check_success(self, mock_graph):
        """测试健康检查成功"""
        mock_result = AsyncMock()
        mock_result.data = AsyncMock(return_value=[{"test": 1}])

        mock_session = AsyncMock()
        mock_session.run = AsyncMock(return_value=mock_result)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock()

        mock_graph._driver.session = MagicMock(return_value=mock_session)

        result = await mock_graph.health_check()

        assert result.success
        assert result.data == True

    @pytest.mark.asyncio
    async def test_health_check_failure(self):
        """测试健康检查失败"""
        from ember_v2.packages.graph_process import GraphProcess

        graph = GraphProcess()
        graph._driver = None
        graph._is_connected = False

        result = await graph.health_check()

        assert result.success == False

    @pytest.mark.asyncio
    async def test_get_pool_stats_connected(self, mock_graph):
        """测试获取连接池状态（已连接）"""
        stats = await mock_graph.get_pool_stats()

        assert stats.total_connections == 1
        assert stats.idle_connections == 1

    @pytest.mark.asyncio
    async def test_get_pool_stats_disconnected(self):
        """测试获取连接池状态（未连接）"""
        from ember_v2.packages.graph_process import GraphProcess

        graph = GraphProcess()
        graph._driver = None
        graph._is_connected = False

        stats = await graph.get_pool_stats()

        assert stats.total_connections == 0
        assert stats.idle_connections == 0


class TestGraphProcessAPOC:
    """测试 APOC 功能"""

    @pytest.fixture
    def mock_graph(self):
        """创建 Mock GraphProcess 实例"""
        from ember_v2.packages.graph_process import GraphProcess

        graph = GraphProcess()
        graph._driver = AsyncMock()
        graph._is_connected = True
        return graph

    @pytest.mark.asyncio
    async def test_check_apoc_available(self, mock_graph):
        """测试 APOC 可用"""
        mock_result = AsyncMock()
        mock_result.data = AsyncMock(return_value=[{"cnt": 5}])

        mock_session = AsyncMock()
        mock_session.run = AsyncMock(return_value=mock_result)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock()

        mock_graph._driver.session = MagicMock(return_value=mock_session)

        await mock_graph._check_apoc_available()

        assert mock_graph.apoc_available == True

    @pytest.mark.asyncio
    async def test_check_apoc_not_available(self, mock_graph):
        """测试 APOC 不可用"""
        mock_result = AsyncMock()
        mock_result.data = AsyncMock(return_value=[])

        mock_session = AsyncMock()
        mock_session.run = AsyncMock(return_value=mock_result)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock()

        mock_graph._driver.session = MagicMock(return_value=mock_session)

        await mock_graph._check_apoc_available()

        assert mock_graph.apoc_available == False


class TestGraphProcessTypes:
    """测试类型定义"""

    def test_entity_to_dict(self):
        """测试 Entity 转字典"""
        from ember_v2.packages.graph_process import Entity

        entity = Entity(
            name="依鸣",
            labels=["Person", "Character"],
            properties={"age": 18, "school": "南京大学"}
        )

        result = entity.to_dict()

        assert result["name"] == "依鸣"
        assert result["labels"] == ["Person", "Character"]
        assert result["properties"]["age"] == 18

    def test_relation_to_dict(self):
        """测试 Relation 转字典"""
        from ember_v2.packages.graph_process import Relation

        relation = Relation(
            source="依鸣",
            target="南京大学",
            type="就读于",
            properties={"since": 2023}
        )

        result = relation.to_dict()

        assert result["source"] == "依鸣"
        assert result["target"] == "南京大学"
        assert result["type"] == "就读于"

    def test_upsert_mode_enum(self):
        """测试 UpsertMode 枚举"""
        from ember_v2.packages.graph_process import UpsertMode

        assert UpsertMode.INCREMENT.value == "increment"
        assert UpsertMode.OVERWRITE.value == "overwrite"

    def test_pool_stats(self):
        """测试 PoolStats"""
        from ember_v2.packages.graph_process import PoolStats

        stats = PoolStats(
            total_connections=10,
            idle_connections=5
        )

        assert stats.total_connections == 10
        assert stats.idle_connections == 5