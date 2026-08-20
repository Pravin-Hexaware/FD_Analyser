from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Iterable, Iterator

from azure.identity import DefaultAzureCredential
from azure.keyvault.secrets import SecretClient
from langchain_core.messages import AIMessage
from langchain_openai import AzureChatOpenAI
from openai import OpenAI

from config.settings import KEY_VAULT_URL


def _message_text(message: Any) -> str:
    content = getattr(message, "content", message)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                parts.append(str(item.get("text") or item.get("content") or item))
            else:
                parts.append(str(item))
        return "".join(parts)
    return str(content)


def _flatten_messages(messages: Iterable[Any]) -> str:
    return "\n\n".join(_message_text(message) for message in messages)


@dataclass
class GroqResponsesLLM:
    model: str
    api_key: str
    base_url: str = "https://api.groq.com/openai/v1"

    def __post_init__(self) -> None:
        self._client = OpenAI(api_key=self.api_key, base_url=self.base_url)

    def invoke(self, messages: list[Any], max_tokens: int = 8000) -> AIMessage:
        response = self._client.responses.create(
            model=self.model,
            input=_flatten_messages(messages),
            max_output_tokens=max_tokens,
        )
        output_text = getattr(response, "output_text", "") or ""
        return AIMessage(content=output_text)

    def stream(self, messages: list[Any], max_tokens: int = 8000) -> Iterator[AIMessage]:
        response = self.invoke(messages, max_tokens=max_tokens)
        text = response.content if isinstance(response.content, str) else str(response.content)
        chunk_size = 1000
        for index in range(0, len(text), chunk_size):
            yield AIMessage(content=text[index : index + chunk_size])


def get_llm_provider_name() -> str:
    return os.getenv("LLM_PROVIDER", "gpt5").strip().lower() or "gpt5"


def get_azure_chat_openai():
    key_vault_url = KEY_VAULT_URL
    credential = DefaultAzureCredential()
    kv_client = SecretClient(vault_url=key_vault_url, credential=credential)
    subscription_key = kv_client.get_secret("llm-api-key").value
    endpoint = kv_client.get_secret("llm-base-endpoint").value
    deployment = kv_client.get_secret("llm-5").value
    api_version = kv_client.get_secret("llm-41-version").value
    return AzureChatOpenAI(
        azure_deployment=deployment,
        openai_api_version=api_version,
        azure_endpoint=endpoint,
        api_key=subscription_key,
        streaming=True,
        temperature=0,
    )


def get_shared_llm():
    provider = get_llm_provider_name()
    if provider == "groq_gpt_oss":
        api_key = os.getenv("GROQ_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError("GROQ_API_KEY is required when LLM_PROVIDER=groq_gpt_oss")
        model = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b").strip() or "openai/gpt-oss-120b"
        return GroqResponsesLLM(model=model, api_key=api_key)
    return get_azure_chat_openai()