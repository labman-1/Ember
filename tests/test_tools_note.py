"""
测试 NoteTool

覆盖笔记创建、读取、搜索功能。
"""
import pytest
import tempfile
from pathlib import Path
from tools.builtin.note_tool import NoteTool
from tools.base import ToolPermission


class TestNoteTool:
    """测试笔记工具"""

    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    @pytest.fixture
    def note_tool(self, temp_dir):
        return NoteTool(notes_dir=temp_dir)

    def test_initialization(self, temp_dir):
        """测试初始化"""
        tool = NoteTool(notes_dir=temp_dir)
        assert tool.name == "note_tool"
        assert tool.permission == ToolPermission.READWRITE

    def test_create_note_basic(self, note_tool):
        """测试创建基本笔记"""
        result = note_tool.execute({
            "operation": "create",
            "note_id": "test_note",
            "title": "Test Title",
            "content": "Test content here"
        })
        assert result.success is True
        assert result.data["title"] == "Test Title"

    def test_create_note_auto_id(self, note_tool):
        """测试自动生成笔记ID"""
        result = note_tool.execute({
            "operation": "create",
            "title": "Auto ID Test",
            "content": "Content"
        })
        assert result.success is True
        assert "note_id" in result.data
        assert result.data["note_id"].endswith('.md')

    def test_create_note_with_tags(self, note_tool):
        """测试带标签的笔记"""
        result = note_tool.execute({
            "operation": "create",
            "note_id": "tagged_note",
            "title": "Tagged",
            "content": "Content",
            "tags": ["important", "work"]
        })
        assert result.success is True
        assert result.data["tags"] == ["important", "work"]

    def test_read_note(self, note_tool):
        """测试读取笔记"""
        note_tool.execute({
            "operation": "create",
            "note_id": "readable_note",
            "title": "Readable",
            "content": "This is the content"
        })

        result = note_tool.execute({
            "operation": "read",
            "note_id": "readable_note"
        })
        assert result.success is True
        assert result.data["title"] == "Readable"
        assert "This is the content" in result.data["content"]

    def test_read_nonexistent_note(self, note_tool):
        """测试读取不存在的笔记"""
        result = note_tool.execute({
            "operation": "read",
            "note_id": "does_not_exist"
        })
        assert result.success is False

    def test_search_notes(self, note_tool):
        """测试搜索笔记"""
        note_tool.execute({
            "operation": "create",
            "note_id": "note1",
            "title": "Python Programming",
            "content": "Learn Python basics",
            "tags": ["coding"]
        })
        note_tool.execute({
            "operation": "create",
            "note_id": "note2",
            "title": "JavaScript Guide",
            "content": "Learn JS basics",
            "tags": ["coding", "web"]
        })
        note_tool.execute({
            "operation": "create",
            "note_id": "note3",
            "title": "Cooking Recipe",
            "content": "How to cook pasta"
        })

        result = note_tool.execute({
            "operation": "search",
            "query": "Python"
        })
        assert result.success is True
        assert len(result.data) >= 1
        # Python 应该在标题中匹配，分数较高
        python_notes = [n for n in result.data if "Python" in n["title"]]
        assert len(python_notes) > 0

    def test_search_by_tag(self, note_tool):
        """测试按标签搜索"""
        note_tool.execute({
            "operation": "create",
            "note_id": "tagged1",
            "title": "Tagged Note",
            "content": "Content",
            "tags": ["special"]
        })

        result = note_tool.execute({
            "operation": "search",
            "query": "special"
        })
        assert result.success is True
        assert len(result.data) >= 1

    def test_list_notes(self, note_tool):
        """测试列出笔记"""
        for i in range(3):
            note_tool.execute({
                "operation": "create",
                "title": f"Note {i}",
                "content": f"Content {i}"
            })

        result = note_tool.execute({
            "operation": "list"
        })
        assert result.success is True
        assert len(result.data) >= 3

    def test_list_notes_with_limit(self, note_tool):
        """测试列出笔记（带限制）"""
        for i in range(5):
            note_tool.execute({
                "operation": "create",
                "title": f"Note {i}",
                "content": f"Content {i}"
            })

        result = note_tool.execute({
            "operation": "list",
            "limit": 2
        })
        assert result.success is True
        assert len(result.data) <= 2

    def test_delete_note(self, note_tool):
        """测试删除笔记"""
        note_tool.execute({
            "operation": "create",
            "note_id": "to_delete",
            "title": "Delete Me",
            "content": "Content"
        })

        result = note_tool.execute({
            "operation": "delete",
            "note_id": "to_delete"
        })
        assert result.success is True

        # 确认已删除
        read_result = note_tool.execute({
            "operation": "read",
            "note_id": "to_delete"
        })
        assert read_result.success is False

    def test_delete_nonexistent_note(self, note_tool):
        """测试删除不存在的笔记"""
        result = note_tool.execute({
            "operation": "delete",
            "note_id": "does_not_exist"
        })
        assert result.success is False
        assert "不存在" in result.error

    def test_create_empty_content_fails(self, note_tool):
        """测试创建空内容笔记失败"""
        result = note_tool.execute({
            "operation": "create",
            "title": "Empty",
            "content": ""
        })
        assert result.success is False
        assert "不能为空" in result.error

    def test_search_empty_query_fails(self, note_tool):
        """测试空搜索词失败"""
        result = note_tool.execute({
            "operation": "search",
            "query": ""
        })
        assert result.success is False

    def test_note_file_format(self, note_tool, temp_dir):
        """测试笔记文件格式"""
        note_tool.execute({
            "operation": "create",
            "note_id": "format_test",
            "title": "Format Test",
            "content": "The actual content",
            "tags": ["test", "format"]
        })

        # 读取原始文件
        file_path = Path(temp_dir) / "format_test.md"
        content = file_path.read_text('utf-8')

        # 检查 frontmatter
        assert content.startswith("---")
        assert "title: Format Test" in content
        assert "tags:" in content
        assert "The actual content" in content
