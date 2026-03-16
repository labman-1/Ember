"""
测试 FileTool

覆盖文件读写、路径安全（防止路径遍历）功能。
"""
import os
import pytest
import tempfile
from pathlib import Path
from tools.builtin.file_tool import FileTool
from tools.base import ToolResult, ToolPermission


class TestFileTool:
    """测试文件工具"""

    @pytest.fixture
    def temp_dir(self):
        """创建临时目录"""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    @pytest.fixture
    def file_tool(self, temp_dir):
        return FileTool(sandbox_dir=temp_dir)

    def test_initialization(self, temp_dir):
        """测试初始化"""
        tool = FileTool(sandbox_dir=temp_dir)
        assert tool.name == "file_tool"
        assert tool.permission == ToolPermission.READWRITE
        assert tool.sandbox_dir == Path(temp_dir).resolve()

    def test_default_sandbox_creation(self):
        """测试默认沙箱目录创建"""
        tool = FileTool()  # 使用默认路径
        assert tool.sandbox_dir.exists()

    def test_write_file(self, file_tool):
        """测试写入文件"""
        result = file_tool.execute({
            "operation": "write",
            "path": "test.txt",
            "content": "Hello, World!"
        })
        assert result.success is True
        assert "写入成功" in result.data

    def test_read_file(self, file_tool):
        """测试读取文件"""
        # 先写入
        file_tool.execute({
            "operation": "write",
            "path": "test.txt",
            "content": "Test content"
        })
        # 再读取
        result = file_tool.execute({
            "operation": "read",
            "path": "test.txt"
        })
        assert result.success is True
        assert result.data == "Test content"

    def test_read_nonexistent_file(self, file_tool):
        """测试读取不存在的文件"""
        result = file_tool.execute({
            "operation": "read",
            "path": "nonexistent.txt"
        })
        assert result.success is False
        assert "不存在" in result.error

    def test_append_file(self, file_tool):
        """测试追加文件"""
        file_tool.execute({
            "operation": "write",
            "path": "append_test.txt",
            "content": "First line"
        })
        result = file_tool.execute({
            "operation": "append",
            "path": "append_test.txt",
            "content": "\nSecond line"
        })
        assert result.success is True

        # 验证内容
        read_result = file_tool.execute({
            "operation": "read",
            "path": "append_test.txt"
        })
        assert "First line" in read_result.data
        assert "Second line" in read_result.data

    def test_exists_check(self, file_tool):
        """测试文件存在检查"""
        file_tool.execute({
            "operation": "write",
            "path": "exists_test.txt",
            "content": "test"
        })
        result = file_tool.execute({
            "operation": "exists",
            "path": "exists_test.txt"
        })
        assert result.success is True
        assert result.data["exists"] is True
        assert result.data["is_file"] is True

    def test_exists_not_found(self, file_tool):
        """测试文件不存在检查"""
        result = file_tool.execute({
            "operation": "exists",
            "path": "not_found.txt"
        })
        assert result.success is True
        assert result.data["exists"] is False

    def test_list_directory(self, file_tool, temp_dir):
        """测试列出目录"""
        # 创建一些文件
        Path(temp_dir).joinpath("file1.txt").write_text("1")
        Path(temp_dir).joinpath("file2.txt").write_text("2")
        Path(temp_dir).joinpath("subdir").mkdir()

        result = file_tool.execute({
            "operation": "list",
            "path": "."
        })
        assert result.success is True
        assert len(result.data) >= 3
        # 目录应该排在前面
        assert result.data[0]["type"] == "directory"

    def test_nested_directory_operations(self, file_tool, temp_dir):
        """测试嵌套目录操作"""
        result = file_tool.execute({
            "operation": "write",
            "path": "nested/dir/file.txt",
            "content": "nested content"
        })
        assert result.success is True
        assert Path(temp_dir).joinpath("nested/dir/file.txt").exists()


class TestFileToolSecurity:
    """测试 FileTool 安全功能"""

    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    @pytest.fixture
    def file_tool(self, temp_dir):
        return FileTool(sandbox_dir=temp_dir)

    def test_path_traversal_blocked(self, file_tool):
        """测试路径遍历攻击被阻止"""
        result = file_tool.execute({
            "operation": "read",
            "path": "../../../etc/passwd"
        })
        assert result.success is False
        assert "路径越界" in result.error

    def test_absolute_path_outside_sandbox(self, file_tool, temp_dir):
        """测试沙箱外的绝对路径"""
        outside_path = str(Path(temp_dir).parent / "outside.txt")
        result = file_tool.execute({
            "operation": "read",
            "path": outside_path
        })
        assert result.success is False
        assert "路径越界" in result.error

    def test_double_dot_traversal(self, file_tool):
        """测试双点号遍历"""
        result = file_tool.execute({
            "operation": "write",
            "path": "subdir/../../escape.txt",
            "content": "escaped"
        })
        assert result.success is False

    @pytest.mark.skipif(
        os.name == 'nt',
        reason="Windows requires admin privileges to create symlinks"
    )
    def test_symlink_attack(self, file_tool, temp_dir):
        """测试符号链接攻击防护"""
        # 创建指向沙箱外的符号链接
        outside_file = Path(temp_dir).parent / "secret.txt"
        outside_file.write_text("secret")

        link_path = Path(temp_dir) / "link"
        link_path.symlink_to(outside_file)

        result = file_tool.execute({
            "operation": "read",
            "path": "link"
        })
        # 应该解析到真实路径并检查是否在沙箱内
        # symlink 被 resolve() 解析后，真实路径在沙箱外，应被拒绝
        assert result.success is False or "路径越界" in str(result.error)
