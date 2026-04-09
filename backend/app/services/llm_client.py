"""LLM client abstraction supporting multiple providers.

Providers:
- anthropic: Uses native anthropic SDK (best for vision/screenshots)
- openai: Uses openai SDK
- google: Uses openai SDK with Google's OpenAI-compatible endpoint
- custom: Uses openai SDK with user-provided base_url (vLLM, Ollama, LiteLLM, etc.)
"""

import base64
import json
import logging
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class LLMProvider(str, Enum):
    ANTHROPIC = "anthropic"
    OPENAI = "openai"
    GOOGLE = "google"
    CUSTOM = "custom"


# Default base URLs per provider
PROVIDER_BASE_URLS: dict[str, str] = {
    LLMProvider.ANTHROPIC: "https://api.anthropic.com",
    LLMProvider.OPENAI: "https://api.openai.com/v1",
    LLMProvider.GOOGLE: "https://generativelanguage.googleapis.com/v1beta/openai/",
}

# Default models per provider
PROVIDER_DEFAULT_MODELS: dict[str, str] = {
    LLMProvider.ANTHROPIC: "claude-sonnet-4-20250514",
    LLMProvider.OPENAI: "gpt-4o",
    LLMProvider.GOOGLE: "gemini-2.0-flash",
    LLMProvider.CUSTOM: "default",
}


@dataclass
class LLMConfig:
    provider: str = LLMProvider.ANTHROPIC
    api_key: str = ""
    model: str = ""
    base_url: str = ""
    temperature: float = 0.0

    def effective_model(self) -> str:
        return self.model or PROVIDER_DEFAULT_MODELS.get(self.provider, "default")

    def effective_base_url(self) -> str:
        return self.base_url or PROVIDER_BASE_URLS.get(self.provider, "")


class LLMClient:
    """Unified LLM client that dispatches to the correct SDK."""

    def __init__(self, config: LLMConfig):
        self.config = config
        self._anthropic_client = None
        self._openai_client = None

    def _get_anthropic_client(self):
        if self._anthropic_client is None:
            import anthropic
            self._anthropic_client = anthropic.AsyncAnthropic(api_key=self.config.api_key)
        return self._anthropic_client

    def _get_openai_client(self):
        if self._openai_client is None:
            import openai
            self._openai_client = openai.AsyncOpenAI(
                api_key=self.config.api_key,
                base_url=self.config.effective_base_url(),
            )
        return self._openai_client

    async def chat(self, messages: list[dict], images: list[bytes] | None = None) -> str:
        """Send a chat completion request. Returns the text response.

        Args:
            messages: List of {"role": "user"|"assistant"|"system", "content": "..."}
            images: Optional list of PNG screenshot bytes to include with the last user message
        """
        if self.config.provider == LLMProvider.ANTHROPIC:
            return await self._chat_anthropic(messages, images)
        else:
            return await self._chat_openai(messages, images)

    async def chat_json(self, messages: list[dict], images: list[bytes] | None = None) -> dict:
        """Send a chat completion request expecting JSON output."""
        # Add JSON instruction to system/last message
        json_hint = "\n\nRespond with valid JSON only. No markdown, no code fences."
        if messages and messages[-1]["role"] == "user":
            messages = [*messages[:-1], {**messages[-1], "content": messages[-1]["content"] + json_hint}]

        text = await self.chat(messages, images)

        # Strip potential markdown code fences
        text = text.strip()
        if text.startswith("```"):
            # Remove opening fence (```json, ```JSON, ``` etc.)
            first_newline = text.index("\n") if "\n" in text else len(text)
            text = text[first_newline + 1:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

        if not text:
            raise ValueError("LLM returned empty response (no JSON content)")

        return json.loads(text)

    async def _chat_anthropic(self, messages: list[dict], images: list[bytes] | None = None) -> str:
        client = self._get_anthropic_client()

        # Separate system message from conversation
        system_text = ""
        conversation = []
        for msg in messages:
            if msg["role"] == "system":
                system_text += msg["content"] + "\n"
            else:
                conversation.append(msg)

        # Attach images to the last user message
        if images and conversation:
            last = conversation[-1]
            if last["role"] == "user":
                content_blocks = []
                for img in images:
                    content_blocks.append({
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/png",
                            "data": base64.standard_b64encode(img).decode(),
                        },
                    })
                content_blocks.append({"type": "text", "text": last["content"]})
                conversation[-1] = {"role": "user", "content": content_blocks}

        kwargs = {
            "model": self.config.effective_model(),
            "max_tokens": 4096,
            "messages": conversation,
            "temperature": self.config.temperature,
        }
        if system_text.strip():
            kwargs["system"] = system_text.strip()

        response = await client.messages.create(**kwargs)
        return response.content[0].text

    async def _chat_openai(self, messages: list[dict], images: list[bytes] | None = None) -> str:
        client = self._get_openai_client()

        # Attach images to the last user message as base64 image_url
        formatted = list(messages)
        if images and formatted:
            last = formatted[-1]
            if last["role"] == "user":
                content_parts = []
                for img in images:
                    b64 = base64.standard_b64encode(img).decode()
                    content_parts.append({
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{b64}"},
                    })
                content_parts.append({"type": "text", "text": last["content"]})
                formatted[-1] = {"role": "user", "content": content_parts}

        kwargs = {
            "model": self.config.effective_model(),
            "messages": formatted,
            "temperature": self.config.temperature,
        }
        # OpenAI's newer models (o1, o3, gpt-4.1, etc.) require max_completion_tokens
        # instead of max_tokens. Detect which to use and cache the result.
        if not hasattr(self, "_use_legacy_max_tokens"):
            self._use_legacy_max_tokens = False
        if self._use_legacy_max_tokens:
            kwargs["max_tokens"] = 4096
        else:
            try:
                response = await client.chat.completions.create(
                    **kwargs, max_completion_tokens=4096,
                )
                return response.choices[0].message.content or ""
            except Exception as e:
                if "max_tokens" in str(e) or "max_completion_tokens" in str(e) or "unsupported_parameter" in str(e):
                    self._use_legacy_max_tokens = True
                    kwargs["max_tokens"] = 4096
                else:
                    raise
        response = await client.chat.completions.create(**kwargs)
        return response.choices[0].message.content or ""

    async def test_connection(self) -> dict:
        """Send a trivial prompt to verify the connection works.

        Returns: {"success": True} or {"success": False, "error": "..."}
        """
        try:
            result = await self.chat([
                {"role": "user", "content": "Reply with exactly: OK"}
            ])
            return {"success": True, "response": result.strip()[:100]}
        except Exception as e:
            logger.warning("LLM connection test failed: %s", e)
            return {"success": False, "error": str(e)}
