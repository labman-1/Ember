"""
Ember 内置工具集

提供基础工具实现：
- TimeTool: 获取真实时间
- FileTool: 安全的文件操作
- NoteTool: 笔记记录系统
"""

from tools.builtin.time_tool import TimeTool
from tools.builtin.file_tool import FileTool
from tools.builtin.note_tool import NoteTool

__all__ = [
    "TimeTool",
    "FileTool",
    "NoteTool",
]
