"""
笔记工具

提供个人笔记系统，AI可以记录和查询笔记。
笔记以文件形式存储，支持标签和搜索。
"""
import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Optional, List
from tools.base import BaseTool, ToolResult, ToolPermission
from tools.builtin.file_tool import FileTool

logger = logging.getLogger(__name__)


class NoteTool(BaseTool):
    """
    笔记管理工具

    提供笔记的创建、读取、搜索和删除功能。
    笔记以 Markdown 格式存储，支持 YAML frontmatter 元数据。
    """

    name = "note_tool"
    description = "管理个人笔记，支持记录、查询和搜索"
    short_description = "创建和管理笔记"
    permission = ToolPermission.READWRITE
    timeout = 10.0

    examples = [
        {
            "user": "帮我记个笔记",
            "parameters": {"operation": "create", "title": "待办事项", "content": "记得买牛奶", "tags": ["生活"]}
        },
        {
            "user": "查看我的笔记",
            "parameters": {"operation": "list"}
        },
    ]

    parameters = {
        "type": "object",
        "properties": {
            "operation": {
                "type": "string",
                "description": "操作: 'create' 创建, 'read' 读取, 'search' 搜索, 'list' 列出, 'delete' 删除",
                "enum": ["create", "read", "search", "list", "delete"],
            },
            "note_id": {
                "type": "string",
                "description": "笔记ID或文件名（create/read/delete 必需）",
            },
            "title": {
                "type": "string",
                "description": "笔记标题（create 可选）",
            },
            "content": {
                "type": "string",
                "description": "笔记内容（create 必需）",
            },
            "tags": {
                "type": "array",
                "items": {"type": "string"},
                "description": "标签列表（create 可选）",
            },
            "query": {
                "type": "string",
                "description": "搜索关键词（search 必需）",
            },
            "limit": {
                "type": "integer",
                "description": "返回结果数量限制",
                "default": 10,
            },
        },
        "required": ["operation"],
    }

    def __init__(self, notes_dir: Optional[str] = None):
        """
        初始化笔记工具

        Args:
            notes_dir: 笔记存储目录，默认为项目目录下的 "data/notes/"
        """
        super().__init__()

        if notes_dir:
            self.notes_dir = Path(notes_dir).resolve()
        else:
            self.notes_dir = Path("./data/notes").resolve()

        self.notes_dir.mkdir(parents=True, exist_ok=True)
        self.index_file = self.notes_dir / ".index.json"

        # 内部使用 FileTool 进行文件操作
        self._file_tool = FileTool(str(self.notes_dir))

        logger.info(f"NoteTool 笔记目录: {self.notes_dir}")

    def execute(self, params: dict) -> ToolResult:
        """
        执行笔记操作

        Args:
            params: 操作参数

        Returns:
            ToolResult: 操作结果
        """
        operation = params.get("operation")

        try:
            if operation == "create":
                return self._create_note(params)
            elif operation == "read":
                return self._read_note(params)
            elif operation == "search":
                return self._search_notes(params)
            elif operation == "list":
                return self._list_notes(params)
            elif operation == "delete":
                return self._delete_note(params)
            else:
                return ToolResult.fail(f"未知操作: {operation}")

        except Exception as e:
            logger.exception(f"NoteTool 执行失败: {operation}")
            return ToolResult.fail(f"笔记操作失败: {str(e)}")

    def _create_note(self, params: dict) -> ToolResult:
        """创建笔记"""
        content = params.get("content", "")
        if not content:
            return ToolResult.fail("笔记内容不能为空")

        # 生成或验证 note_id
        note_id = params.get("note_id")
        if note_id:
            # 清理文件名
            note_id = re.sub(r'[^\w\-_.]', '_', note_id)
            if not note_id.endswith('.md'):
                note_id += '.md'
        else:
            # 自动生成文件名
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            title = params.get("title", "untitled")
            title_slug = re.sub(r'[^\w\-]', '_', title)[:30]
            note_id = f"{timestamp}_{title_slug}.md"

        title = params.get("title", "无标题")
        tags = params.get("tags", [])
        created_at = datetime.now().isoformat()

        # 构建 Markdown 内容
        frontmatter = f"""---
title: {title}
created_at: {created_at}
tags: {json.dumps(tags, ensure_ascii=False)}
---

"""
        full_content = frontmatter + content

        # 写入文件
        file_path = self.notes_dir / note_id
        result = self._file_tool._write_file(file_path, full_content, "utf-8", append=False)

        if result.success:
            return ToolResult.ok(
                data={
                    "note_id": note_id,
                    "title": title,
                    "created_at": created_at,
                    "tags": tags,
                },
                message="笔记创建成功"
            )
        else:
            return result

    def _sanitize_note_id(self, note_id: str) -> str:
        """
        清理和校验笔记ID

        - 移危险字符
        - 确保.md后缀
        - 防止路径遍历
        """
        if not note_id:
            return ""
        # 清理文件名：只允许字母数字、下划线、连字符、点
        note_id = re.sub(r'[^\w\-_.]', '_', note_id)
        if not note_id.endswith('.md'):
            note_id += '.md'
        return note_id

    def _resolve_safe_path(self, note_id: str) -> tuple[Optional[Path], Optional[str]]:
        """
        解析并验证安全路径

        Returns:
            (path, error_msg) - 如果error_msg不为空，则路径不安全
        """
        safe_note_id = self._sanitize_note_id(note_id)
        if not safe_note_id:
            return None, "笔记ID不能为空"

        file_path = (self.notes_dir / safe_note_id).resolve()

        # 路径遍历检查：确保解析后的路径仍在notes_dir内
        try:
            file_path.relative_to(self.notes_dir.resolve())
        except ValueError:
            return None, f"非法路径: {note_id}"

        return file_path, None

    def _read_note(self, params: dict) -> ToolResult:
        """读取笔记"""
        note_id = params.get("note_id", "")

        file_path, error = self._resolve_safe_path(note_id)
        if error:
            return ToolResult.fail(error, security_blocked=True)

        result = self._file_tool._read_file(file_path, "utf-8")

        if not result.success:
            return result

        # 解析笔记内容
        content = result.data
        metadata, body = self._parse_note(content)

        return ToolResult.ok(
            data={
                "note_id": note_id,
                "title": metadata.get("title", "无标题"),
                "created_at": metadata.get("created_at", ""),
                "tags": metadata.get("tags", []),
                "content": body,
            }
        )

    def _search_notes(self, params: dict) -> ToolResult:
        """搜索笔记"""
        query = params.get("query", "").lower()
        limit = params.get("limit", 10)

        if not query:
            return ToolResult.fail("搜索关键词不能为空")

        results = []

        # 遍历所有笔记文件
        for note_file in self.notes_dir.glob("*.md"):
            if note_file.name.startswith('.'):
                continue

            try:
                content = note_file.read_text("utf-8")
                metadata, body = self._parse_note(content)

                # 搜索标题、标签和内容
                score = 0
                title = metadata.get("title", "")
                tags = metadata.get("tags", [])

                if query in title.lower():
                    score += 10
                if any(query in tag.lower() for tag in tags):
                    score += 5
                if query in body.lower():
                    score += 1

                if score > 0:
                    # 提取匹配的上下文
                    context = self._extract_context(body, query)

                    results.append({
                        "note_id": note_file.name,
                        "title": title,
                        "tags": tags,
                        "created_at": metadata.get("created_at", ""),
                        "score": score,
                        "context": context,
                    })

            except Exception as e:
                logger.warning(f"读取笔记失败 {note_file}: {e}")
                continue

        # 按分数排序并限制数量
        results.sort(key=lambda x: x["score"], reverse=True)
        results = results[:limit]

        return ToolResult.ok(
            data=results,
            total_found=len(results),
            query=query
        )

    def _list_notes(self, params: dict) -> ToolResult:
        """列出所有笔记"""
        limit = params.get("limit", 50)
        notes = []

        for note_file in sorted(self.notes_dir.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True):
            if note_file.name.startswith('.'):
                continue

            try:
                content = note_file.read_text("utf-8")
                metadata, _ = self._parse_note(content)

                notes.append({
                    "note_id": note_file.name,
                    "title": metadata.get("title", "无标题"),
                    "tags": metadata.get("tags", []),
                    "created_at": metadata.get("created_at", ""),
                    "modified_at": datetime.fromtimestamp(note_file.stat().st_mtime).isoformat(),
                })
            except Exception as e:
                logger.warning(f"读取笔记失败 {note_file}: {e}")
                continue

        return ToolResult.ok(
            data=notes[:limit],
            total_count=len(notes)
        )

    def _delete_note(self, params: dict) -> ToolResult:
        """删除笔记"""
        note_id = params.get("note_id", "")
        if not note_id:
            return ToolResult.fail("必须指定笔记ID")

        file_path, error = self._resolve_safe_path(note_id)
        if error:
            return ToolResult.fail(error, security_blocked=True)

        if not file_path.exists():
            return ToolResult.fail(f"笔记不存在: {note_id}", not_found=True)

        try:
            file_path.unlink()
            return ToolResult.ok(
                data={"deleted": file_path.name},
                message="笔记已删除"
            )
        except Exception as e:
            return ToolResult.fail(f"删除失败: {str(e)}")

    def _parse_note(self, content: str) -> tuple[dict, str]:
        """解析笔记，分离 frontmatter 和正文"""
        metadata = {}
        body = content

        # 检查是否有 YAML frontmatter
        if content.startswith('---'):
            parts = content.split('---', 2)
            if len(parts) >= 3:
                frontmatter_text = parts[1].strip()
                body = parts[2].strip()

                # 简单解析 YAML（简化实现）
                for line in frontmatter_text.split('\n'):
                    if ':' in line:
                        key, value = line.split(':', 1)
                        key = key.strip()
                        value = value.strip()

                        # 尝试解析 JSON 数组
                        if value.startswith('['):
                            try:
                                value = json.loads(value)
                            except json.JSONDecodeError:
                                pass

                        metadata[key] = value

        return metadata, body

    def _extract_context(self, text: str, query: str, context_chars: int = 100) -> str:
        """提取关键词周围的上下文"""
        idx = text.lower().find(query)
        if idx == -1:
            return text[:200] + "..." if len(text) > 200 else text

        start = max(0, idx - context_chars)
        end = min(len(text), idx + len(query) + context_chars)

        context = text[start:end]
        if start > 0:
            context = "..." + context
        if end < len(text):
            context = context + "..."

        return context
