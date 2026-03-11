from openai import OpenAI
import logging
import re
import json
from config.settings import settings

logger = logging.getLogger(__name__)


class LLMClient:
    def __init__(self):
        self.large_client = OpenAI(
            api_key=settings.LARGE_LLM.api_key,
            base_url=settings.LARGE_LLM.base_url,
        )
        self.small_client = OpenAI(
            api_key=settings.SMALL_LLM.api_key,
            base_url=settings.SMALL_LLM.base_url,
        )
        self.embedding_client = OpenAI(
            api_key=settings.EMBEDDING_MODEL.api_key,
            base_url=settings.EMBEDDING_MODEL.base_url,
        )

    def _extract_json(self, content):
        """Extract JSON from potential markdown code blocks."""
        if not content:
            return None

        # Try to find JSON block
        json_pattern = r"```(?:json)?\s*([\s\S]*?)\s*```"
        match = re.search(json_pattern, content)
        if match:
            content = match.group(1)

        content = content.strip()
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            # If standard parsing fails, try cleaning some common issues or just return None
            logger.error(
                f"Failed to parse extracted content as JSON: {content[:100]}..."
            )
            return None

    def one_chat(self, model_config, messages):
        client = (
            self.large_client
            if model_config == settings.LARGE_LLM
            else self.small_client
        )

        try:
            response = client.chat.completions.create(
                model=model_config.name,
                messages=messages,
                extra_body={"enable_thinking": False},
                stream=False,
                temperature=0.7,
            )
            full_response = response.choices[0].message.content
            return full_response
        except Exception as e:
            logger.error(f"OneChat Error: {e}")
            return None

    def stream_chat(self, model_config, messages):
        client = (
            self.large_client
            if model_config == settings.LARGE_LLM
            else self.small_client
        )

        try:
            response = client.chat.completions.create(
                model=model_config.name,
                messages=messages,
                extra_body={"enable_thinking": False},
                stream=True,
                temperature=0.7,
            )

            for chunk in response:
                reasoning = getattr(chunk.choices[0].delta, "reasoning_content", None)
                if reasoning:
                    yield f"{reasoning}"

                content = chunk.choices[0].delta.content
                if content is not None:
                    yield content

        except Exception as e:
            yield f"[Error]: {str(e)}"
            logger.error(f"Streaming Chat Error: {e}")

    def get_embedding(self, model_config, text: str):
        client = self.embedding_client
        try:
            response = client.embeddings.create(
                model=model_config.name,
                input=text,
                dimensions=1536,
            )
            embedding = response.data[0].embedding
            return embedding
        except Exception as e:
            logger.error(f"Get Embedding Error: {e}")
            return None
