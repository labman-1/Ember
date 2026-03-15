"""
LLM Cleaning Package
LLM 输出清洗处理器

功能:
- 思考标签修复与分离 (<thought>...</thought>)
- JSON 格式验证与修复
- 文本格式清洗
- LLM 输出标准化
"""

import re
import json
import logging
from typing import Optional, Tuple

from ember_v2.core.package_base import BasePackage
from ember_v2.core.types import PackageResponse

from .types import (
    ThoughtExtraction,
    ValidationResult,
    JSONExtraction,
    CleaningResult,
    FixResult,
)

logger = logging.getLogger(__name__)


class LLMCleaning(BasePackage):
    """
    LLM 输出清洗 Package

    功能:
    - 修复不完整的 <thought> 标签
    - 分离思考内容和发言内容
    - 提取和验证 JSON 格式
    - 清理格式问题
    """

    def __init__(self, config_path: Optional[str] = None):
        """
        初始化清洗处理器

        Args:
            config_path: 配置文件路径
        """
        super().__init__(config_path)

        # 从配置读取选项
        self._auto_fix_tags = self.get_config_value("auto_fix_tags", True)
        self._strict_json = self.get_config_value("strict_json", False)
        self._preserve_thought_in_output = self.get_config_value(
            "preserve_thought_in_output", False
        )

        self._logger.info("LLMCleaning initialized")

    # ==================== 思考标签处理 ====================

    def fix_thought_tags(self, text: str) -> Tuple[str, FixResult]:
        """
        修复不完整的 <thought> 标签

        常见问题：
        - </thought` (多了一个反引号)
        - </thought (缺少 >)
        - 只有 <thought> 没有 </thought>
        - 只有 </thought> 没有 <thought>

        Args:
            text: 原始文本

        Returns:
            (修复后的文本, 修复结果类型)
        """
        if not text:
            return text, FixResult.NO_CHANGE

        original_text = text

        # 1. 修复常见的错误格式
        # 修复 </thought` 或 </thought``
        text = re.sub(r'</thought[`\'"]+', "</thought>", text)

        # 修复 </thought 缺少 >
        text = re.sub(r"</thought([^>])", r"</thought>\1", text)
        text = re.sub(r"</thought$", "</thought>", text)

        # 修复 <thought 缺少 >
        text = re.sub(r"<thought([^>])", r"<thought>\1", text)
        text = re.sub(r"^<thought$", "<thought>", text)

        # 2. 检查标签配对
        open_tags = text.count("<thought>")
        close_tags = text.count("</thought>")

        # 如果有未闭合的 <thought>
        if open_tags > close_tags:
            last_open = text.rfind("<thought>")
            if last_open != -1:
                remaining = text[last_open:]

                if "</thought>" not in remaining:
                    next_para = re.search(r"\n\s*\n", remaining)
                    if next_para:
                        insert_pos = last_open + next_para.start()
                        text = text[:insert_pos] + "\n</thought>" + text[insert_pos:]
                    else:
                        text = text.rstrip() + "\n</thought>"
            self._logger.debug("Fixed unclosed <thought> tag")

        # 如果有未开启的 </thought>
        elif close_tags > open_tags:
            first_close = text.find("</thought>")
            if first_close != -1:
                prev_para = text.rfind("\n\n", 0, first_close)
                if prev_para == -1:
                    prev_para = 0
                else:
                    prev_para += 2

                text = text[:prev_para] + "<thought>\n" + text[prev_para:]
            self._logger.debug("Fixed unopened </thought> tag")

        if text != original_text:
            return text, FixResult.FIXED
        return text, FixResult.NO_CHANGE

    def remove_thought_content(self, text: str) -> str:
        """
        移除 <thought>...</thought> 标签及其内容

        Args:
            text: 原始文本

        Returns:
            移除 thought 内容后的文本
        """
        if not text:
            return text

        # 先修复标签
        text, _ = self.fix_thought_tags(text)

        # 移除完整的 thought 块
        text = re.sub(r"<thought>.*?</thought>", "", text, flags=re.DOTALL)

        # 清理可能残留的不完整标签
        text = re.sub(r"</?thought[^>]*>", "", text)

        # 清理多余的空行
        text = re.sub(r"\n\s*\n\s*\n", "\n\n", text)
        text = text.strip()

        return text

    def extract_thought_and_speech(self, text: str) -> ThoughtExtraction:
        """
        分离 thought 内容和 speech 内容

        Args:
            text: 原始文本

        Returns:
            ThoughtExtraction 包含 thought 和 speech
        """
        if not text:
            return ThoughtExtraction(
                thought="", speech="", has_thought=False, is_valid=True
            )

        # 先修复标签
        fixed_text, fix_result = self.fix_thought_tags(text)

        # 检查是否有 thought 标签
        has_thought = "<thought>" in fixed_text

        # 提取 thought 内容
        thought_match = re.search(r"<thought>([\s\S]*?)</thought>", fixed_text)
        thought = thought_match.group(1).strip() if thought_match else ""

        # 提取 speech 内容（移除 thought 部分）
        speech = self.remove_thought_content(fixed_text)

        # 检查标签是否完整
        open_count = fixed_text.count("<thought>")
        close_count = fixed_text.count("</thought>")
        is_valid = open_count == close_count

        return ThoughtExtraction(
            thought=thought, speech=speech, has_thought=has_thought, is_valid=is_valid
        )

    # ==================== JSON 处理 ====================

    def extract_json(self, text: str) -> JSONExtraction:
        """
        从文本中提取 JSON

        支持：
        - 纯 JSON 文本
        - 包含在 ```json ``` 代码块中的 JSON
        - 包含在 ``` ``` 代码块中的 JSON
        - 带有前后文本的 JSON

        Args:
            text: 原始文本

        Returns:
            JSONExtraction 包含提取结果
        """
        if not text:
            return JSONExtraction(
                success=False, data=None, raw_content="", error="Empty text"
            )

        original_text = text.strip()

        # 尝试多种方式提取
        json_str = None

        # 方法1: 尝试直接解析
        try:
            data = json.loads(original_text)
            return JSONExtraction(success=True, data=data, raw_content=original_text)
        except json.JSONDecodeError:
            pass

        # 方法2: 提取代码块中的 JSON
        code_block_patterns = [
            r"```json\s*([\s\S]*?)\s*```",
            r"```\s*([\s\S]*?)\s*```",
        ]

        for pattern in code_block_patterns:
            match = re.search(pattern, original_text)
            if match:
                json_str = match.group(1).strip()
                try:
                    data = json.loads(json_str)
                    return JSONExtraction(success=True, data=data, raw_content=json_str)
                except json.JSONDecodeError:
                    continue

        # 方法3: 查找第一个 { 到最后一个 }
        first_brace = original_text.find("{")
        last_brace = original_text.rfind("}")

        if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
            json_str = original_text[first_brace : last_brace + 1]
            try:
                data = json.loads(json_str)
                return JSONExtraction(success=True, data=data, raw_content=json_str)
            except json.JSONDecodeError:
                pass

        # 方法4: 尝试修复常见问题后再解析
        if json_str:
            fixed = self._try_fix_json(json_str)
            if fixed:
                try:
                    data = json.loads(fixed)
                    return JSONExtraction(success=True, data=data, raw_content=fixed)
                except json.JSONDecodeError:
                    pass

        return JSONExtraction(
            success=False,
            data=None,
            raw_content=original_text,
            error="Failed to extract valid JSON",
        )

    def _try_fix_json(self, text: str) -> Optional[str]:
        """
        尝试修复常见的 JSON 格式问题

        Args:
            text: 原始 JSON 文本

        Returns:
            修复后的 JSON 文本或 None
        """
        if not text:
            return None

        try:
            # 尝试使用 json_repair 库（如果可用）
            try:
                from json_repair import repair_json

                return repair_json(text)
            except ImportError:
                pass

            # 手动修复一些常见问题
            fixed = text

            # 修复单引号为双引号
            # 注意：这只是简单替换，可能不适用于所有情况
            if "'" in fixed and '"' not in fixed:
                fixed = fixed.replace("'", '"')

            # 修复末尾多余的逗号
            fixed = re.sub(r",\s*}", "}", fixed)
            fixed = re.sub(r",\s*]", "]", fixed)

            # 修复缺少引号的键名
            # fixed = re.sub(r'(\w+)\s*:', r'"\1":', fixed)

            return fixed

        except Exception as e:
            self._logger.debug(f"JSON fix attempt failed: {e}")
            return None

    def validate_json(
        self,
        text: str,
        required_keys: Optional[list] = None,
        optional_keys: Optional[list] = None,
    ) -> ValidationResult:
        """
        验证 JSON 格式和内容

        Args:
            text: 原始文本
            required_keys: 必须存在的键列表
            optional_keys: 可选的键列表

        Returns:
            ValidationResult 包含验证结果
        """
        errors = []
        warnings = []

        # 提取 JSON
        extraction = self.extract_json(text)

        if not extraction.success:
            return ValidationResult(
                is_valid=False,
                errors=[f"JSON 解析失败: {extraction.error}"],
                warnings=[],
                fixed_content=None,
            )

        data = extraction.data

        # 检查必需的键
        if required_keys:
            for key in required_keys:
                if key not in data:
                    errors.append(f"缺少必需的键: {key}")

        # 检查是否有未预期的键
        if required_keys or optional_keys:
            allowed_keys = set(required_keys or []) | set(optional_keys or [])
            for key in data.keys():
                if key not in allowed_keys:
                    warnings.append(f"未预期的键: {key}")

        return ValidationResult(
            is_valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
            fixed_content=json.dumps(data, ensure_ascii=False),
        )

    # ==================== 综合清洗 ====================

    def clean(
        self, text: str, remove_thought: bool = True, extract_json: bool = False
    ) -> PackageResponse[CleaningResult]:
        """
        综合清洗 LLM 输出

        Args:
            text: 原始文本
            remove_thought: 是否移除思考标签内容
            extract_json: 是否尝试提取 JSON

        Returns:
            PackageResponse 包含 CleaningResult
        """
        try:
            if not text:
                return PackageResponse(
                    success=True,
                    data=CleaningResult(original="", cleaned="", thought="", speech=""),
                )

            original = text
            changes = []

            # 1. 修复思考标签
            fixed_text, fix_result = self.fix_thought_tags(text)
            if fix_result == FixResult.FIXED:
                changes.append("修复了不完整的 <thought> 标签")

            # 2. 提取思考和发言内容
            extraction = self.extract_thought_and_speech(fixed_text)

            # 3. 决定最终输出内容
            if remove_thought:
                cleaned = extraction.speech
                changes.append("移除了思考内容")
            else:
                cleaned = fixed_text

            # 4. 清理格式问题
            # 移除多余的反引号
            if "```" in cleaned:
                cleaned = re.sub(r"```\s*", "", cleaned)
                changes.append("移除了代码块标记")

            # 清理多余的空行
            if re.search(r"\n{3,}", cleaned):
                cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
                changes.append("清理了多余的空行")

            # 5. 如果需要，尝试提取 JSON
            if extract_json:
                json_result = self.extract_json(cleaned)
                if json_result.success:
                    cleaned = json.dumps(json_result.data, ensure_ascii=False, indent=2)
                    changes.append("提取了 JSON 内容")

            cleaned = cleaned.strip()

            result = CleaningResult(
                original=original,
                cleaned=cleaned,
                thought=extraction.thought,
                speech=extraction.speech,
                changes=changes,
            )

            return PackageResponse(success=True, data=result)

        except Exception as e:
            self._logger.error(f"Cleaning error: {e}")
            return PackageResponse(success=False, error=str(e))

    # ==================== 便捷方法 ====================

    def validate_and_fix(self, text: str) -> str:
        """
        验证并修复 LLM 输出的格式问题
        主要用于在保存到数据库前进行格式校验

        Args:
            text: LLM 输出的原始文本

        Returns:
            修复后的文本
        """
        if not text:
            return text

        # 修复 thought 标签
        text, _ = self.fix_thought_tags(text)

        # 移除多余的反引号
        text = re.sub(r"```\s*", "", text)

        # 确保不会有多余的空行
        text = re.sub(r"\n{3,}", "\n\n", text)

        return text.strip()
