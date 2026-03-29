from tools.base import BaseTool, ToolResult, ToolPermission
from duckduckgo_search import DDGS
import logging
import json

logger = logging.getLogger(__name__)

class WebSearchTool(BaseTool):
    """
    网页搜索工具，用于获取实时的现实世界信息、新闻和维基百科知识。
    核心优化：支持直接搜索，摆脱固定知识库限制。
    """
    
    name = "search_web"
    description = "搜索互联网以获取最新新闻、天气资讯或专业知识百科。当你遇到不知道的事情时调用。"
    short_description = "检索互联网最新信息"
    permission = ToolPermission.READONLY
    timeout = 15.0
    
    def __init__(self):
        super().__init__()
        self.parameters = {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "要搜索的关键词或问题，尽量精简提取核心实体"},
                "max_results": {"type": "integer", "description": "最大返回结果数，默认3"}
            },
            "required": ["query"]
        }
        self.examples = [
            {"scenario": "查询今日南京天气", "parameters": {"query": "南京 今日 天气"}},
            {"scenario": "了解大模型最新发布情况", "parameters": {"query": "AI LLM 最新发布 模型 2024"}},
        ]
        
    def execute(self, params: dict) -> ToolResult:
        query = params.get("query")
        max_results = params.get("max_results", 3)
        
        if not query:
            return ToolResult.fail("缺少搜索关键词 (query)")
            
        logger.info(f"[WebSearchTool] 正在搜索: {query}")
        try:
            results = []
            with DDGS() as ddgs:
                ddgs_gen = ddgs.text(query, max_results=max_results)
                if ddgs_gen:
                    for r in ddgs_gen:
                        results.append({
                            "title": r.get("title", ""),
                            "snippet": r.get("body", ""),
                            "link": r.get("href", "")
                        })
            
            if not results:
                return ToolResult.ok(data="未找到相关结果，可能该事件太新或关键词不准确。")
                
            return ToolResult.ok(data=results)
            
        except Exception as e:
            logger.error(f"[WebSearchTool] 搜索出错: {e}")
            return ToolResult.fail(f"搜索服务暂时不可用: {e}")
            
    def summarize_result(self, result: ToolResult, max_length: int = 500) -> str:
        if not result.success:
            return f"搜索失败: {result.error}"
            
        if isinstance(result.data, str):
            return result.data
            
        # 格式化搜索结果
        lines = ["互联网搜索结果摘要："]
        for idx, item in enumerate(result.data):
            lines.append(f"[{idx+1}] {item['title']}: {item['snippet']}")
            
        text = "\n".join(lines)
        if len(text) > max_length:
            text = text[:max_length] + "..."
            
        return text
