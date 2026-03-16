"""
文件工具

提供安全的文件读写操作，限制在项目目录内，防止路径遍历攻击。
"""
import os
import logging
from pathlib import Path
from typing import Optional
from tools.base import BaseTool, ToolResult, ToolPermission

logger = logging.getLogger(__name__)


class FileTool(BaseTool):
    """
    安全的文件操作工具

    支持读写文本文件，限制在沙箱目录内操作，防止路径遍历攻击。
    """

    name = "file_tool"
    description = "读写文件内容，可用于记录持久化信息或读取已有文件"
    permission = ToolPermission.READWRITE
    timeout = 10.0

    parameters = {
        "type": "object",
        "properties": {
            "operation": {
                "type": "string",
                "description": "操作类型: 'read' 读取, 'write' 写入, 'append' 追加, 'exists' 检查存在",
                "enum": ["read", "write", "append", "exists", "list"],
            },
            "path": {
                "type": "string",
                "description": "文件路径（相对于沙箱目录或绝对路径）",
            },
            "content": {
                "type": "string",
                "description": "写入内容（write/append 操作必需）",
            },
            "encoding": {
                "type": "string",
                "description": "文件编码",
                "default": "utf-8",
            },
        },
        "required": ["operation", "path"],
    }

    def __init__(self, sandbox_dir: Optional[str] = None):
        """
        初始化文件工具

        Args:
            sandbox_dir: 沙箱目录，文件操作限制在此目录内
                        默认为项目目录下的 "data/files/"
        """
        super().__init__()

        if sandbox_dir:
            self.sandbox_dir = Path(sandbox_dir).resolve()
        else:
            # 默认沙箱目录：项目根目录下的 data/files/
            self.sandbox_dir = Path("./data/files").resolve()

        # 确保沙箱目录存在
        self.sandbox_dir.mkdir(parents=True, exist_ok=True)

        logger.info(f"FileTool 沙箱目录: {self.sandbox_dir}")

    def execute(self, params: dict) -> ToolResult:
        """
        执行文件操作

        Args:
            params: {
                "operation": "read" | "write" | "append" | "exists" | "list",
                "path": str,
                "content": str (write/append 必需),
                "encoding": str (默认 utf-8)
            }

        Returns:
            ToolResult: 操作结果
        """
        operation = params.get("operation")
        path_str = params.get("path", "")
        encoding = params.get("encoding", "utf-8")

        try:
            # 安全检查：路径遍历防护
            safe_path = self._resolve_safe_path(path_str)
            if safe_path is None:
                return ToolResult.fail(
                    f"路径越界: '{path_str}' 不在允许的沙箱目录内",
                    security_blocked=True
                )

            # 执行操作
            if operation == "read":
                return self._read_file(safe_path, encoding)
            elif operation == "write":
                content = params.get("content", "")
                return self._write_file(safe_path, content, encoding, append=False)
            elif operation == "append":
                content = params.get("content", "")
                return self._write_file(safe_path, content, encoding, append=True)
            elif operation == "exists":
                exists = safe_path.exists()
                return ToolResult.ok(
                    data={"exists": exists, "is_file": safe_path.is_file() if exists else False, "is_dir": safe_path.is_dir() if exists else False},
                    path=str(safe_path)
                )
            elif operation == "list":
                return self._list_directory(safe_path)
            else:
                return ToolResult.fail(f"未知操作: {operation}")

        except Exception as e:
            logger.exception(f"FileTool 执行失败: {operation}")
            return ToolResult.fail(f"文件操作失败: {str(e)}")

    def _resolve_safe_path(self, path_str: str) -> Optional[Path]:
        """
        解析并验证路径安全

        Args:
            path_str: 输入路径

        Returns:
            安全路径或 None（如果路径越界）
        """
        # 处理绝对路径
        if os.path.isabs(path_str):
            target = Path(path_str).resolve()
        else:
            target = (self.sandbox_dir / path_str).resolve()

        # 安全检查：确保路径在沙箱目录内
        try:
            # 使用 relative_to 检查路径关系
            target.relative_to(self.sandbox_dir)
            return target
        except ValueError:
            # 路径不在沙箱目录内
            logger.warning(f"路径遍历尝试被阻止: {path_str}")
            return None

    def _read_file(self, path: Path, encoding: str) -> ToolResult:
        """读取文件内容"""
        if not path.exists():
            return ToolResult.fail(f"文件不存在: {path.name}", not_found=True)

        if not path.is_file():
            return ToolResult.fail(f"路径不是文件: {path.name}", not_a_file=True)

        try:
            content = path.read_text(encoding=encoding)
            return ToolResult.ok(
                data=content,
                path=str(path),
                size=len(content),
                lines=content.count('\n') + 1
            )
        except UnicodeDecodeError:
            return ToolResult.fail("文件编码错误，无法以文本方式读取", encoding_error=True)
        except Exception as e:
            return ToolResult.fail(f"读取失败: {str(e)}")

    def _write_file(self, path: Path, content: str, encoding: str, append: bool) -> ToolResult:
        """写入文件内容"""
        # 确保父目录存在
        path.parent.mkdir(parents=True, exist_ok=True)

        mode = "a" if append else "w"
        try:
            with open(path, mode, encoding=encoding) as f:
                f.write(content)

            return ToolResult.ok(
                data=f"{'追加' if append else '写入'}成功",
                path=str(path),
                bytes_written=len(content.encode(encoding))
            )
        except Exception as e:
            return ToolResult.fail(f"写入失败: {str(e)}")

    def _list_directory(self, path: Path) -> ToolResult:
        """列出目录内容"""
        if not path.exists():
            return ToolResult.fail(f"目录不存在: {path.name}", not_found=True)

        if not path.is_dir():
            return ToolResult.fail(f"路径不是目录: {path.name}", not_a_directory=True)

        try:
            items = []
            for item in path.iterdir():
                item_info = {
                    "name": item.name,
                    "type": "directory" if item.is_dir() else "file",
                    "size": item.stat().st_size if item.is_file() else None,
                }
                items.append(item_info)

            # 排序：目录在前，按名称排序
            items.sort(key=lambda x: (0 if x["type"] == "directory" else 1, x["name"]))

            return ToolResult.ok(
                data=items,
                path=str(path),
                count=len(items)
            )
        except Exception as e:
            return ToolResult.fail(f"列出目录失败: {str(e)}")
