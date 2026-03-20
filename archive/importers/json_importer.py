"""
JSON 文件导入器

负责导入配置文件数据 (state.json, chat_memory.json)
"""

import json
import shutil
from pathlib import Path
from typing import Optional
import logging

from archive.importers.base import BaseImporter, ImportResult

logger = logging.getLogger(__name__)


class JsonImporter(BaseImporter):
    """JSON 配置文件导入器"""

    name = "json"
    description = "JSON 配置文件导入器"

    # 需要导入的配置文件
    CONFIG_FILES = [
        ("state.json", "state.json"),
        ("chat_memory.json", "chat_memory.json"),
    ]

    def __init__(self, source_dir: str, config_dir: str = "./config"):
        """
        初始化 JSON 导入器

        Args:
            source_dir: 源目录 (解压后的存档目录)
            config_dir: 配置文件目标目录
        """
        super().__init__(source_dir)
        self.config_dir = config_dir

    def import_data(self) -> ImportResult:
        """导入 JSON 配置文件"""
        try:
            imported_files = []
            stats = {"files_count": 0}

            for source_name, target_name in self.CONFIG_FILES:
                source_path = Path(self.source_dir) / source_name
                target_path = Path(self.config_dir) / target_name

                if source_path.exists():
                    # 备份现有文件
                    if target_path.exists():
                        backup_path = target_path.with_suffix(".json.bak")
                        shutil.copy2(target_path, backup_path)
                        self.logger.debug(f"已备份: {target_name}")

                    # 复制文件
                    shutil.copy2(source_path, target_path)
                    imported_files.append(target_name)
                    stats["files_count"] += 1

                    self.logger.debug(f"已导入: {source_name} -> {target_name}")
                else:
                    self.logger.warning(f"源文件不存在，跳过: {source_name}")

            return ImportResult(
                success=True,
                message=f"已导入 {stats['files_count']} 个配置文件",
                data=imported_files,
                stats=stats,
            )

        except Exception as e:
            self.logger.error(f"导入 JSON 文件失败: {e}")
            return ImportResult(success=False, error=str(e))

    def import_state(self) -> Optional[dict]:
        """仅导入状态数据"""
        try:
            source_path = Path(self.source_dir) / "state.json"
            if source_path.exists():
                with open(source_path, "r", encoding="utf-8") as f:
                    state = json.load(f)

                # 写入目标位置
                target_path = Path(self.config_dir) / "state.json"
                with open(target_path, "w", encoding="utf-8") as f:
                    json.dump(state, f, ensure_ascii=False, indent=2)

                return state
            return None
        except Exception as e:
            self.logger.error(f"导入状态文件失败: {e}")
            return None

    def import_chat_memory(self) -> Optional[list]:
        """仅导入短期记忆数据"""
        try:
            source_path = Path(self.source_dir) / "chat_memory.json"
            if source_path.exists():
                with open(source_path, "r", encoding="utf-8") as f:
                    memory = json.load(f)

                # 写入目标位置
                target_path = Path(self.config_dir) / "chat_memory.json"
                with open(target_path, "w", encoding="utf-8") as f:
                    json.dump(memory, f, ensure_ascii=False, indent=2)

                return memory
            return []
        except Exception as e:
            self.logger.error(f"导入短期记忆文件失败: {e}")
            return None
