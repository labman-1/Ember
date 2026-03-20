"""
Neo4j 知识图谱导入器

负责导入 Neo4j 图数据库中的节点和关系
"""

import logging
import time
import re
from pathlib import Path

from archive.importers.base import BaseImporter, ImportResult
from config.settings import settings

logger = logging.getLogger(__name__)


class Neo4jImporter(BaseImporter):
    """Neo4j 知识图谱导入器"""

    name = "neo4j"
    description = "Neo4j 知识图谱导入器"

    # 连接重试配置
    MAX_RETRIES = 3
    RETRY_DELAY = 1.0

    def __init__(
        self,
        source_dir: str,
        uri: str = None,
        user: str = None,
        password: str = None,
        database: str = None,
    ):
        """
        初始化 Neo4j 导入器

        Args:
            source_dir: 源目录 (解压后的存档目录)
            uri: Neo4j URI
            user: 用户名
            password: 密码
            database: 数据库名称
        """
        super().__init__(source_dir)
        self.uri = uri or settings.NEO4J_URI
        self.user = user or settings.NEO4J_USER
        self.password = password or settings.NEO4J_PASSWORD
        self.database = database or getattr(settings, "NEO4J_DB", "neo4j")
        self.enabled = settings.ENABLE_NEO4J

    def _get_driver(self, retries: int = None):
        """
        获取 Neo4j 驱动，支持重试

        Args:
            retries: 重试次数

        Returns:
            Neo4j 驱动
        """
        from neo4j import GraphDatabase

        retries = retries or self.MAX_RETRIES
        last_error = None

        for attempt in range(retries):
            try:
                driver = GraphDatabase.driver(
                    self.uri,
                    auth=(self.user, self.password),
                )
                # 验证连接
                driver.verify_connectivity()
                self.logger.debug(f"Neo4j 连接成功 (尝试 {attempt + 1}/{retries})")
                return driver
            except Exception as e:
                last_error = e
                self.logger.warning(
                    f"Neo4j 连接失败 (尝试 {attempt + 1}/{retries}): {e}"
                )
                if attempt < retries - 1:
                    time.sleep(self.RETRY_DELAY)

        raise last_error

    def import_data(self) -> ImportResult:
        """导入 Neo4j 数据"""
        if not self.enabled:
            self.logger.info("Neo4j 未启用，跳过导入")
            return ImportResult(
                success=True,
                message="Neo4j 未启用",
                stats={"enabled": False},
            )

        try:
            from neo4j import GraphDatabase

            cypher_file = Path(self.source_dir) / "neo4j.cypher"
            if not cypher_file.exists():
                self.logger.info("没有 Neo4j 数据文件，跳过导入")
                return ImportResult(
                    success=True,
                    message="没有 Neo4j 数据",
                    stats={"enabled": True, "imported": False},
                )

            driver = self._get_driver()

            # 读取 Cypher 脚本
            with open(cypher_file, "r", encoding="utf-8") as f:
                cypher_content = f.read()

            stats = {"enabled": True, "nodes": 0, "relations": 0, "errors": 0}

            with driver.session(database=self.database) as session:
                # 清空现有数据
                self._clear_all(session)

                # 执行 Cypher 脚本
                stats = self._execute_cypher_script(session, cypher_content)

            driver.close()

            if stats["errors"] > 0:
                self.logger.warning(f"Neo4j 导入完成，但有 {stats['errors']} 个错误")

            self.logger.info(
                f"已导入 Neo4j 数据: {stats['nodes']} 节点, {stats['relations']} 关系"
            )

            return ImportResult(
                success=True,
                message=f"已导入 {stats['nodes']} 节点, {stats['relations']} 关系",
                stats=stats,
            )

        except ImportError:
            self.logger.warning("neo4j 库未安装，跳过导入")
            return ImportResult(
                success=True,
                message="neo4j 库未安装",
                stats={"enabled": False},
            )
        except Exception as e:
            self.logger.error(f"导入 Neo4j 数据失败: {e}")
            return ImportResult(success=False, error=str(e))

    # 批量导入配置
    BATCH_SIZE = 500  # 每批处理的节点/关系数

    def _clear_all(self, session):
        """清空所有节点和关系 (使用批量删除优化)"""
        try:
            # 使用 apoc.periodic.iterate 批量删除 (如果可用)
            # 否则使用普通删除
            result = session.run("MATCH (n) RETURN count(n) AS count")
            count = result.single()["count"]

            if count > 10000:
                # 大量数据时使用分批删除
                self.logger.info(f"清空 {count} 个节点，使用分批删除...")
                deleted = 0
                batch_size = 1000
                while deleted < count:
                    session.run(
                        "MATCH (n) WITH n LIMIT $limit DETACH DELETE n",
                        limit=batch_size,
                    )
                    deleted += batch_size
                    self.logger.debug(f"已删除 {min(deleted, count)}/{count} 节点")
            else:
                session.run("MATCH (n) DETACH DELETE n")

            self.logger.debug("已清空 Neo4j 数据")
        except Exception as e:
            self.logger.error(f"清空 Neo4j 数据失败: {e}")

    def _execute_cypher_script(self, session, cypher_content: str) -> dict:
        """
        执行 Cypher 脚本 (使用批量导入优化)

        Args:
            session: Neo4j session
            cypher_content: Cypher 脚本内容

        Returns:
            统计信息
        """
        stats = {"nodes": 0, "relations": 0, "errors": 0}

        # 解析节点和关系
        nodes, relations = self._parse_cypher_to_batches(cypher_content)

        # 批量创建节点
        if nodes:
            stats["nodes"] = self._batch_create_nodes(session, nodes)

        # 批量创建关系
        if relations:
            stats["relations"] = self._batch_create_relations(session, relations)

        return stats

    def _parse_cypher_to_batches(self, cypher_content: str) -> tuple:
        """
        解析 Cypher 脚本，提取节点和关系数据

        Returns:
            (nodes_list, relations_list)
        """
        import re

        nodes = []
        relations = []

        # 匹配 CREATE 语句
        # 节点: CREATE (label {props});
        node_pattern = r"CREATE \(([^)]+)\s+(\{[^}]+\})\);"
        # 关系: CREATE (a)-[:TYPE {props}]->(b);
        rel_pattern = r"CREATE \(([^)]+)\)-\[:(\w+)(?:\s+(\{[^}]+\}))?\]->\(([^)]+)\);"

        for line in cypher_content.split("\n"):
            line = line.strip()
            if not line or line.startswith("//"):
                continue

            # 尝试匹配关系
            rel_match = re.match(rel_pattern, line)
            if rel_match:
                from_node, rel_type, rel_props, to_node = rel_match.groups()
                relations.append(
                    {
                        "from": from_node,
                        "to": to_node,
                        "type": rel_type,
                        "props": self._parse_props(rel_props) if rel_props else {},
                    }
                )
                continue

            # 尝试匹配节点
            node_match = re.match(node_pattern, line)
            if node_match:
                labels, props = node_match.groups()
                nodes.append(
                    {"labels": labels.split(":"), "props": self._parse_props(props)}
                )

        return nodes, relations

    def _parse_props(self, props_str: str) -> dict:
        """解析属性字符串为字典"""
        import re

        if not props_str:
            return {}

        props = {}
        # 匹配 key: value 对
        pattern = r"(\w+):\s*'([^']*)'|\b(\w+):\s*(\d+\.?\d*)"
        for match in re.finditer(pattern, props_str):
            if match.group(1):
                props[match.group(1)] = match.group(2)
            elif match.group(3):
                val = match.group(4)
                if "." in val:
                    props[match.group(3)] = float(val)
                else:
                    props[match.group(3)] = int(val)

        return props

    def _batch_create_nodes(self, session, nodes: list) -> int:
        """批量创建节点"""
        created = 0

        for i in range(0, len(nodes), self.BATCH_SIZE):
            batch = nodes[i : i + self.BATCH_SIZE]

            # 使用 UNWIND 批量创建
            for node in batch:
                try:
                    labels_str = ":".join(node["labels"])
                    props = node["props"]

                    # 构建 Cypher
                    if props:
                        props_str = ", ".join([f"{k}: ${k}" for k in props.keys()])
                        cypher = f"CREATE (:{labels_str} {{{props_str}}})"
                        session.run(cypher, **props)
                    else:
                        cypher = f"CREATE (:{labels_str})"
                        session.run(cypher)

                    created += 1
                except Exception as e:
                    self.logger.warning(f"创建节点失败: {e}")

        self.logger.info(f"批量创建 {created} 个节点")
        return created

    def _batch_create_relations(self, session, relations: list) -> int:
        """批量创建关系"""
        created = 0

        for i in range(0, len(relations), self.BATCH_SIZE):
            batch = relations[i : i + self.BATCH_SIZE]

            for rel in batch:
                try:
                    props = rel["props"]
                    props_str = ""
                    params = {}

                    if props:
                        props_str = (
                            " {" + ", ".join([f"{k}: ${k}" for k in props.keys()]) + "}"
                        )
                        params = props

                    # 使用 MATCH 找到节点并创建关系
                    cypher = f"""
                    MATCH (a {{id: $from_id}}), (b {{id: $to_id}})
                    CREATE (a)-[:{rel['type']}{props_str}]->(b)
                    """
                    params["from_id"] = rel["from"]
                    params["to_id"] = rel["to"]

                    session.run(cypher, **params)
                    created += 1
                except Exception as e:
                    self.logger.warning(f"创建关系失败: {e}")

        self.logger.info(f"批量创建 {created} 个关系")
        return created

    def _parse_cypher_statements(self, cypher_content: str) -> list:
        """
        解析 Cypher 脚本为独立语句

        支持多行语句，以分号结尾

        Args:
            cypher_content: Cypher 脚本内容

        Returns:
            Cypher 语句列表
        """
        statements = []
        current_stmt = []
        in_string = False
        string_char = None

        lines = cypher_content.split("\n")

        for line in lines:
            # 跳过纯注释行
            stripped = line.strip()
            if stripped.startswith("//") and not in_string:
                continue

            # 处理字符串内的内容
            i = 0
            while i < len(line):
                char = line[i]

                # 处理字符串边界
                if char in ('"', "'") and (i == 0 or line[i - 1] != "\\"):
                    if not in_string:
                        in_string = True
                        string_char = char
                    elif char == string_char:
                        in_string = False
                        string_char = None

                i += 1

            current_stmt.append(line)

            # 检查语句是否结束 (分号且不在字符串内)
            if ";" in line and not in_string:
                # 找到分号位置
                stmt_text = "\n".join(current_stmt)
                # 按分号分割
                parts = stmt_text.split(";")
                for part in parts[:-1]:
                    part = part.strip()
                    if part and not part.startswith("//"):
                        statements.append(part + ";")
                # 保留最后一部分
                last_part = parts[-1].strip()
                current_stmt = [last_part] if last_part else []

        # 处理最后一个未结束的语句
        if current_stmt:
            last_stmt = "\n".join(current_stmt).strip()
            if last_stmt and not last_stmt.startswith("//"):
                statements.append(last_stmt)

        return statements
