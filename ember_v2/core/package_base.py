"""
Package 基类定义
"""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Optional
import yaml
import logging

logger = logging.getLogger(__name__)


class BasePackage(ABC):
    """
    所有 Package 的基类

    每个 Package 应该：
    1. 有独立的配置文件 (config.yaml)
    2. 有独立的数据目录
    3. 提供清晰的接口方法
    """

    def __init__(self, config_path: Optional[str] = None):
        """
        初始化 Package

        Args:
            config_path: 配置文件路径，默认为 Package 目录下的 config.yaml
        """
        self._name = self.__class__.__name__
        self._config: dict = {}
        self._logger = logging.getLogger(f"ember_v2.packages.{self._name}")

        # 加载配置
        if config_path:
            self._load_config(config_path)
        else:
            self._load_default_config()

    @property
    def name(self) -> str:
        """Package 名称"""
        return self._name

    @property
    def config(self) -> dict:
        """Package 配置"""
        return self._config

    def _load_config(self, config_path: str) -> None:
        """加载指定路径的配置文件"""
        path = Path(config_path)
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                self._config = yaml.safe_load(f) or {}
            self._logger.info(f"Loaded config from {config_path}")
        else:
            self._logger.warning(f"Config file not found: {config_path}")

    def _load_default_config(self) -> None:
        """加载默认配置文件（Package 目录下的 config.yaml）"""
        package_dir = Path(__file__).parent.parent / "packages" / self._name.lower()
        config_path = package_dir / "config.yaml"

        if config_path.exists():
            self._load_config(str(config_path))
        else:
            self._logger.info(f"No default config found for {self._name}")

    def get_data_path(self) -> Path:
        """获取 Package 数据目录"""
        data_path = Path(__file__).parent.parent.parent / "data" / self._name.lower()
        data_path.mkdir(parents=True, exist_ok=True)
        return data_path

    def get_config_value(self, key: str, default: Any = None) -> Any:
        """
        获取配置值，支持嵌套键（用 . 分隔）

        Args:
            key: 配置键，如 "models.small.name"
            default: 默认值

        Returns:
            配置值或默认值
        """
        keys = key.split(".")
        value = self._config

        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                return default

        return value
