"""
标签处理工具测试
"""
import pytest
from brain.tag_utils import fix_thought_tags, remove_thought_content, extract_thought_and_speech


class TestFixThoughtTags:
    """测试 thought 标签修复功能"""

    def test_fix_extra_backtick(self):
        """修复多余的反引号"""
        text = "<thought>思考中</thought`"
        result = fix_thought_tags(text)
        assert "</thought>" in result
        assert "</thought`" not in result

    def test_fix_missing_close_bracket(self):
        """修复缺少的右尖括号"""
        text = "<thought>思考中</thought 然后说话"
        result = fix_thought_tags(text)
        assert "</thought>" in result
        assert "</thought " not in result

    def test_fix_unclosed_tag(self):
        """修复未闭合的标签"""
        text = "<thought>思考中但没有结束"
        result = fix_thought_tags(text)
        assert "</thought>" in result

    def test_fix_unopened_close_tag(self):
        """修复没有开标签的闭标签"""
        text = "思考中</thought>"
        result = fix_thought_tags(text)
        assert "<thought>" in result

    def test_no_change_for_valid_tags(self):
        """有效标签不应被修改"""
        text = "<thought>思考</thought>\n回复内容"
        result = fix_thought_tags(text)
        assert result == text


class TestRemoveThoughtContent:
    """测试移除 thought 内容"""

    def test_remove_thought_block(self):
        """移除 thought 块"""
        text = "<thought>内心思考</thought>\n实际回复"
        result = remove_thought_content(text)
        assert "内心思考" not in result
        assert "实际回复" in result

    def test_handle_empty_text(self):
        """处理空文本"""
        assert remove_thought_content("") == ""
        # None 应该返回 None 或空字符串
        result = remove_thought_content(None)
        assert result is None or result == ""


class TestExtractThoughtAndSpeech:
    """测试分离 thought 和 speech"""

    def test_extract_both(self):
        """同时提取两者"""
        text = "<thought>内心想法</thought>\n说出口的话"
        thought, speech = extract_thought_and_speech(text)
        assert "内心想法" in thought
        assert "说出口的话" in speech
        assert "内心想法" not in speech

    def test_no_thought_tag(self):
        """没有 thought 标签时"""
        text = "只有回复内容"
        thought, speech = extract_thought_and_speech(text)
        assert thought == ""
        assert speech == text
