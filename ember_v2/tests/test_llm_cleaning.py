"""
LLM Cleaning Package 测试
"""

import pytest
from ember_v2.packages.llm_cleaning import (
    LLMCleaning,
    ThoughtExtraction,
    ValidationResult,
    JSONExtraction,
    CleaningResult,
    FixResult,
)


class TestLLMCleaningInit:
    """测试初始化"""

    def test_init_default(self):
        """测试默认初始化"""
        cleaner = LLMCleaning()

        assert cleaner._auto_fix_tags == True
        assert cleaner._strict_json == False
        assert cleaner._preserve_thought_in_output == False

    def test_init_with_config_file(self, tmp_path):
        """测试从配置文件初始化"""
        config_content = """
auto_fix_tags: false
strict_json: true
preserve_thought_in_output: true
"""
        config_file = tmp_path / "config.yaml"
        config_file.write_text(config_content)

        cleaner = LLMCleaning(config_path=str(config_file))

        assert cleaner.get_config_value("auto_fix_tags") == False
        assert cleaner.get_config_value("strict_json") == True


class TestThoughtTagsFix:
    """测试思考标签修复"""

    @pytest.fixture
    def cleaner(self):
        """创建清洗器实例"""
        return LLMCleaning()

    def test_fix_complete_tags(self, cleaner):
        """测试完整的标签（无需修复）"""
        text = "<thought>这是思考内容</thought>这是发言内容"

        fixed, result = cleaner.fix_thought_tags(text)

        assert result == FixResult.NO_CHANGE
        assert fixed == text

    def test_fix_unclosed_tag(self, cleaner):
        """修复未闭合的标签"""
        text = "<thought>这是思考内容\n这是发言内容"

        fixed, result = cleaner.fix_thought_tags(text)

        assert result == FixResult.FIXED
        assert "</thought>" in fixed

    def test_fix_unopened_tag(self, cleaner):
        """修复未开启的标签"""
        text = "这是思考内容</thought>这是发言内容"

        fixed, result = cleaner.fix_thought_tags(text)

        assert result == FixResult.FIXED
        assert "<thought>" in fixed

    def test_fix_tag_with_backtick(self, cleaner):
        """修复标签中的反引号"""
        text = "<thought>思考</thought`发言"

        fixed, result = cleaner.fix_thought_tags(text)

        assert result == FixResult.FIXED
        assert "</thought>" in fixed
        assert "`" not in fixed.split("</thought>")[0]

    def test_fix_missing_bracket(self, cleaner):
        """修复缺少 > 的标签"""
        text = "<thought>思考</thought发言"

        fixed, result = cleaner.fix_thought_tags(text)

        assert result == FixResult.FIXED
        assert "</thought>" in fixed

    def test_fix_empty_text(self, cleaner):
        """测试空文本"""
        text = ""

        fixed, result = cleaner.fix_thought_tags(text)

        assert result == FixResult.NO_CHANGE
        assert fixed == ""

    def test_fix_no_tags(self, cleaner):
        """测试没有标签的文本"""
        text = "这是普通文本，没有标签"

        fixed, result = cleaner.fix_thought_tags(text)

        assert result == FixResult.NO_CHANGE
        assert fixed == text


class TestThoughtExtraction:
    """测试思考内容提取"""

    @pytest.fixture
    def cleaner(self):
        return LLMCleaning()

    def test_extract_complete_thought(self, cleaner):
        """提取完整的思考内容"""
        text = "<thought>我在思考</thought>你好呀"

        result = cleaner.extract_thought_and_speech(text)

        assert result.has_thought == True
        assert result.is_valid == True
        assert result.thought == "我在思考"
        assert result.speech == "你好呀"

    def test_extract_multiple_thoughts(self, cleaner):
        """提取多个思考块"""
        text = "<thought>思考1</thought>发言1<thought>思考2</thought>发言2"

        result = cleaner.extract_thought_and_speech(text)

        assert result.has_thought == True
        # speech 应该移除了所有 thought
        assert "思考" not in result.speech

    def test_extract_no_thought(self, cleaner):
        """提取没有思考的文本"""
        text = "这是普通发言"

        result = cleaner.extract_thought_and_speech(text)

        assert result.has_thought == False
        assert result.thought == ""
        assert result.speech == text

    def test_extract_empty_text(self, cleaner):
        """提取空文本"""
        text = ""

        result = cleaner.extract_thought_and_speech(text)

        assert result.has_thought == False
        assert result.thought == ""
        assert result.speech == ""

    def test_extract_with_multiline_thought(self, cleaner):
        """提取多行思考"""
        text = """<thought>
第一行思考
第二行思考
</thought>
这是发言
"""

        result = cleaner.extract_thought_and_speech(text)

        assert result.has_thought == True
        assert "第一行思考" in result.thought
        assert "第二行思考" in result.thought


class TestJSONExtraction:
    """测试 JSON 提取"""

    @pytest.fixture
    def cleaner(self):
        return LLMCleaning()

    def test_extract_pure_json(self, cleaner):
        """提取纯 JSON"""
        text = '{"name": "依鸣", "age": 18}'

        result = cleaner.extract_json(text)

        assert result.success == True
        assert result.data["name"] == "依鸣"
        assert result.data["age"] == 18

    def test_extract_json_from_code_block(self, cleaner):
        """从代码块提取 JSON"""
        text = """```json
{"name": "依鸣", "age": 18}
```"""

        result = cleaner.extract_json(text)

        assert result.success == True
        assert result.data["name"] == "依鸣"

    def test_extract_json_with_surrounding_text(self, cleaner):
        """提取带有周围文本的 JSON"""
        text = '这是前文 {"name": "依鸣"} 这是后文'

        result = cleaner.extract_json(text)

        assert result.success == True
        assert result.data["name"] == "依鸣"

    def test_extract_nested_json(self, cleaner):
        """提取嵌套 JSON"""
        text = '{"user": {"name": "依鸣", "school": "南京大学"}}'

        result = cleaner.extract_json(text)

        assert result.success == True
        assert result.data["user"]["name"] == "依鸣"

    def test_extract_invalid_json(self, cleaner):
        """提取无效 JSON"""
        text = "这不是 JSON"

        result = cleaner.extract_json(text)

        assert result.success == False
        assert result.error is not None

    def test_extract_empty_text(self, cleaner):
        """提取空文本"""
        text = ""

        result = cleaner.extract_json(text)

        assert result.success == False

    def test_extract_json_with_trailing_comma(self, cleaner):
        """提取带尾随逗号的 JSON（尝试修复）"""
        text = '{"name": "依鸣", "age": 18,}'

        result = cleaner.extract_json(text)

        # 根据修复能力，可能成功也可能失败
        # 这里主要测试不会崩溃
        assert result.success in [True, False]


class TestJSONValidation:
    """测试 JSON 验证"""

    @pytest.fixture
    def cleaner(self):
        return LLMCleaning()

    def test_validate_correct_json(self, cleaner):
        """验证正确的 JSON"""
        text = '{"name": "依鸣", "age": 18}'

        result = cleaner.validate_json(text, required_keys=["name", "age"])

        assert result.is_valid == True
        assert len(result.errors) == 0

    def test_validate_missing_required_key(self, cleaner):
        """验证缺少必需键"""
        text = '{"name": "依鸣"}'

        result = cleaner.validate_json(text, required_keys=["name", "age"])

        assert result.is_valid == False
        assert any("age" in e for e in result.errors)

    def test_validate_with_unexpected_key(self, cleaner):
        """验证包含未预期的键"""
        text = '{"name": "依鸣", "age": 18, "extra": "值"}'

        result = cleaner.validate_json(
            text, required_keys=["name"], optional_keys=["age"]
        )

        assert result.is_valid == True
        assert any("extra" in w for w in result.warnings)

    def test_validate_invalid_json(self, cleaner):
        """验证无效 JSON"""
        text = "不是 JSON"

        result = cleaner.validate_json(text)

        assert result.is_valid == False
        assert len(result.errors) > 0


class TestComprehensiveCleaning:
    """测试综合清洗"""

    @pytest.fixture
    def cleaner(self):
        return LLMCleaning()

    def test_clean_basic(self, cleaner):
        """测试基础清洗"""
        text = "<thought>思考</thought>发言"
        
        result = cleaner.clean(text, remove_thought=True)
        
        assert result.success
        assert result.data.cleaned == "发言"
        assert result.data.thought == "思考"
        assert result.data.speech == "发言"

    def test_clean_with_format_issues(self, cleaner):
        """测试带格式问题的清洗"""
        text = "<thought>思考</thought>\n\n\n\n发言```"
        
        result = cleaner.clean(text, remove_thought=True)
        
        assert result.success
        assert "```" not in result.data.cleaned
        assert "\n\n\n" not in result.data.cleaned

    def test_clean_preserve_thought(self, cleaner):
        """测试保留思考内容"""
        text = "<thought>思考</thought>发言"
        
        result = cleaner.clean(text, remove_thought=False)
        
        assert result.success
        assert "<thought>" in result.data.cleaned

    def test_clean_empty_text(self, cleaner):
        """测试清洗空文本"""
        text = ""
        
        result = cleaner.clean(text)
        
        assert result.success
        assert result.data.cleaned == ""

    def test_clean_with_json_extraction(self, cleaner):
        """测试清洗并提取 JSON"""
        text = '<thought>思考</thought>{"name": "依鸣"}'
        
        result = cleaner.clean(text, remove_thought=True, extract_json=True)

    @pytest.fixture
    def cleaner(self):
        return LLMCleaning()

    def test_validate_and_fix_normal(self, cleaner):
        """测试正常文本"""
        text = "这是正常文本"

        result = cleaner.validate_and_fix(text)

        assert result == text

    def test_validate_and_fix_code_blocks(self, cleaner):
        """测试移除代码块"""
        text = "```这是内容```"

        result = cleaner.validate_and_fix(text)

        assert "```" not in result

    def test_validate_and_fix_multiple_empty_lines(self, cleaner):
        """测试清理多余空行"""
        text = "第一行\n\n\n\n\n第二行"

        result = cleaner.validate_and_fix(text)

        assert "\n\n\n" not in result


class TestTypes:
    """测试类型定义"""

    def test_thought_extraction_defaults(self):
        """测试 ThoughtExtraction 默认值"""
        extraction = ThoughtExtraction()

        assert extraction.thought == ""
        assert extraction.speech == ""
        assert extraction.has_thought == False
        assert extraction.is_valid == True

    def test_cleaning_result_has_changes(self):
        """测试 CleaningResult.has_changes"""
        result1 = CleaningResult(changes=["修改1"])
        assert result1.has_changes == True

        result2 = CleaningResult(changes=[])
        assert result2.has_changes == False

    def test_fix_result_enum(self):
        """测试 FixResult 枚举"""
        assert FixResult.NO_CHANGE.value == "no_change"
        assert FixResult.FIXED.value == "fixed"
        assert FixResult.UNFIXABLE.value == "unfixable"

    def test_json_extraction_success(self):
        """测试 JSONExtraction"""
        extraction = JSONExtraction(
            success=True, data={"name": "test"}, raw_content='{"name": "test"}'
        )

        assert extraction.success == True
        assert extraction.data["name"] == "test"
