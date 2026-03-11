import logging
import re
from collections import defaultdict
from neo4j import GraphDatabase
from core.event_bus import EventBus, Event
from config.settings import settings

logger = logging.getLogger(__name__)


class Neo4jGraphMemory:
    def __init__(self, event_bus: EventBus):
        self.event_bus = event_bus
        self.driver = None
        self.enabled = settings.ENABLE_NEO4J
        self.db_name = getattr(settings, "NEO4J_DB", "neo4j")

        if self.enabled:
            self._connect()
            if self.driver:
                self._ensure_constraints()

    def _connect(self):
        try:
            self.driver = GraphDatabase.driver(
                settings.NEO4J_URI, auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD)
            )
            self.driver.verify_connectivity()
            logger.info("Connected to Neo4j")
        except Exception as e:
            self.enabled = False
            logger.error(f"Neo4j connection failed: {e}")

    def _ensure_constraints(self):
        query = "CREATE CONSTRAINT entity_name_unique IF NOT EXISTS FOR (n:Entity) REQUIRE n.name IS UNIQUE"
        try:
            with self.driver.session(database=self.db_name) as session:
                session.run(query)
        except Exception as e:
            logger.error(f"Failed to create constraints: {e}")

    def _is_ready(self):
        return self.enabled and self.driver

    def _safe_label(self, label: str):
        return re.sub(r"[^a-zA-Z0-9_]", "", label)

    def upsert_entity(self, entity_type: str, properties: dict):
        if not self._is_ready() or "name" not in properties:
            return None

        safe_type = self._safe_label(entity_type)

        def _upsert_tx(tx):
            query = f"""
            MERGE (e:Entity {{name: $name}})
            SET e:{safe_type}, e += $props
            RETURN elementId(e) AS eid
            """
            result = tx.run(query, name=properties["name"], props=properties)
            record = result.single()
            return record["eid"] if record else None

        with self.driver.session(database=self.db_name) as session:
            return session.execute_write(_upsert_tx)

    def create_relationship(
        self, from_name: str, to_name: str, rel_type: str, props: dict = None
    ):
        if not self._is_ready():
            return None

        safe_rel = self._safe_label(rel_type)

        def _rel_tx(tx):
            query = f"""
            MATCH (a:Entity {{name: $from_name}}), (b:Entity {{name: $to_name}})
            MERGE (a)-[r:{safe_rel}]->(b)
            SET r += $props
            RETURN elementId(r) AS rid
            """
            result = tx.run(
                query, from_name=from_name, to_name=to_name, props=props or {}
            )
            record = result.single()
            return record["rid"] if record else None

        with self.driver.session(database=self.db_name) as session:
            return session.execute_write(_rel_tx)

    def delete_relationship(self, from_name: str, to_name: str, rel_type: str):
        if not self._is_ready():
            return
        safe_rel = self._safe_label(rel_type)

        def _del_rel_tx(tx):
            query = f"MATCH (a:Entity {{name: $from_name}})-[r:{safe_rel}]->(b:Entity {{name: $to_name}}) DELETE r"
            tx.run(query, from_name=from_name, to_name=to_name)

        with self.driver.session(database=self.db_name) as session:
            session.execute_write(_del_rel_tx)

    def delete_entity(self, name: str):
        if not self._is_ready():
            return

        def _del_entity_tx(tx):
            query = "MATCH (e:Entity {name: $name}) DETACH DELETE e"
            tx.run(query, name=name)

        with self.driver.session(database=self.db_name) as session:
            session.execute_write(_del_entity_tx)

    def query_entities(self, entity_type: str = "Entity", limit: int = 50):
        if not self._is_ready():
            return []
        safe_type = self._safe_label(entity_type)

        def _query_tx(tx):
            query = f"MATCH (e:{safe_type}) RETURN elementId(e) AS eid, properties(e) as props LIMIT $limit"
            result = tx.run(query, limit=limit)
            return [record.data() for record in result]

        with self.driver.session(database=self.db_name) as session:
            return session.execute_read(_query_tx)

    def get_entity_relationships(self, name: str, direction: str = "out"):
        if not self._is_ready():
            return []

        def _rels_tx(tx):
            if direction == "out":
                query = """
                MATCH (e:Entity {name: $name})-[r]->(related)
                RETURN type(r) AS rel_type, 'out' AS direction, 
                       related.name AS target, properties(related) AS properties
                """
            elif direction == "in":
                query = """
                MATCH (related)-[r]->(e:Entity {name: $name})
                RETURN type(r) AS rel_type, 'in' AS direction,
                       related.name AS source, properties(related) AS properties
                """
            else:
                query = """
                MATCH (e:Entity {name: $name})-[r]-(related)
                RETURN type(r) AS rel_type,
                       CASE WHEN startNode(r) = e THEN 'out' ELSE 'in' END AS direction,
                       related.name AS other, properties(related) AS properties
                """
            result = tx.run(query, name=name)
            return [record.data() for record in result]

        with self.driver.session(database=self.db_name) as session:
            return session.execute_read(_rels_tx)

    def find_path(self, from_name: str, to_name: str, max_depth: int = 3):
        if not self._is_ready():
            return {"nodes": [], "relationships": []}

        def _path_tx(tx):
            query = f"""
            MATCH p=shortestPath((a:Entity {{name: $from_name}})-[*..{int(max_depth)}]-(b:Entity {{name: $to_name}}))
            RETURN [n IN nodes(p) | n.name] AS names,
                   [r IN relationships(p) | type(r)] AS rel_types
            """
            result = tx.run(query, from_name=from_name, to_name=to_name)
            record = result.single()
            return record if record else {"names": [], "rel_types": []}

        with self.driver.session(database=self.db_name) as session:
            res = session.execute_read(_path_tx)
            return {"nodes": res["names"], "relationships": res["rel_types"]}

    def get_context_for_entity(self, name: str, hops: int = 2):
        if not self._is_ready():
            return []

        def _context_tx(tx):
            query = f"""
            MATCH (center:Entity {{name: $name}})-[*1..{int(hops)}]-(neighbor:Entity)
            RETURN DISTINCT neighbor.name AS name, labels(neighbor) AS labels
            LIMIT 30
            """
            result = tx.run(query, name=name)
            return [record.data() for record in result]

        with self.driver.session(database=self.db_name) as session:
            return session.execute_read(_context_tx)

    def batch_upsert_entities(self, entities: list):
        if not self._is_ready() or not entities:
            return []
        results = []
        for entity in entities:
            eid = self.upsert_entity(
                entity.get("type", "Entity"), entity.get("properties", {})
            )
            results.append(eid)
        return results

    def batch_create_relationships(self, relationships: list):
        if not self._is_ready() or not relationships:
            return []

        def _batch_rel_tx(tx, rel_group, r_type):
            safe_rel = self._safe_label(r_type)
            query = f"""
            UNWIND $batch AS item
            MATCH (a:Entity {{name: item.from}}), (b:Entity {{name: item.to}})
            MERGE (a)-[r:{safe_rel}]->(b)
            SET r += item.props
            RETURN elementId(r) as rid
            """
            res = tx.run(query, batch=rel_group)
            return [rec["rid"] for rec in res]

        groups = defaultdict(list)
        for r in relationships:
            groups[r["type"]].append(
                {"from": r["from"], "to": r["to"], "props": r.get("properties", {})}
            )

        all_rids = []
        with self.driver.session(database=self.db_name) as session:
            for r_type, group in groups.items():
                rids = session.execute_write(_batch_rel_tx, group, r_type)
                all_rids.extend(rids)
        return all_rids

    def close(self):
        if self.driver:
            self.driver.close()
            logger.info("Neo4j connection closed")
