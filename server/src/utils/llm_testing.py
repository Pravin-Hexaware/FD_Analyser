from typing import Any, cast

from azure.core.credentials import TokenCredential
from azure.identity import DefaultAzureCredential
from azure.ai.projects import AIProjectClient
from langchain_openai import ChatOpenAI

PROJECT_ENDPOINT = "https://bfs-to-dev-foundry.services.ai.azure.com/api/projects/FinBot"
MODEL_DEPLOYMENT = "gpt-4.1"

_project_client: AIProjectClient | None = None
_llm: Any = None


def get_openai_client() -> Any:
    """Return the authenticated OpenAI-compatible client for the FinBot project."""
    global _project_client
    if _project_client is None:
        raw_credential = DefaultAzureCredential()
        credential = cast(TokenCredential, raw_credential)
        _project_client = AIProjectClient(
            endpoint=PROJECT_ENDPOINT,
            credential=credential,
        )
    return _project_client.get_openai_client()


def get_azure_chat_openai() -> ChatOpenAI:
    """Return the shared LangChain model backed by the FinBot Foundry client."""
    global _llm
    if _llm is None:
        _llm = ChatOpenAI(
            model=MODEL_DEPLOYMENT,
            api_key="foundry-managed-credential",
            client=get_openai_client().chat.completions,
            streaming=True,
            temperature=0,
        )
    return _llm