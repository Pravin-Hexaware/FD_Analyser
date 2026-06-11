import urllib.parse
from urllib.parse import urlparse
from typing import TypedDict, Annotated, List, Optional

import feedparser
import requests
import urllib3
from azure.identity import DefaultAzureCredential
from azure.keyvault.secrets import SecretClient
from bs4 import BeautifulSoup
from googlenewsdecoder import gnewsdecoder
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from langchain_openai import AzureChatOpenAI
from langgraph.graph import StateGraph, END, add_messages
from langgraph.checkpoint.memory import MemorySaver
from markdownify import markdownify as md
import os
import json
import re
import trafilatura

OUTPUT_DIR = "outputs"
os.makedirs(OUTPUT_DIR, exist_ok=True)

def _sanitize_filename(name: str) -> str:
    # remove invalid filename characters
    name = re.sub(r'[\\/*?:"<>|]', "", name)
    name = name.strip()
    return name[:150] if len(name) > 150 else name

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def _get_page_title(html: str, fallback: Optional[str] = None) -> str:
    try:
        soup = BeautifulSoup(html, "html.parser")
        if soup.title and soup.title.string:
            title_text = soup.title.string.strip()
            if title_text:
                return title_text
    except Exception:
        pass

    if fallback:
        return fallback

    return "article"


def resolve_url(url: str) -> str:
    if "news.google.com" in url:
        result = gnewsdecoder(url, interval=0)
        if result.get("status") and result.get("decoded_url"):
            resolved = result["decoded_url"]
            return resolved.replace("m.economictimes.com", "economictimes.indiatimes.com")
        raise RuntimeError(f"Google News URL decode failed: {result}")
    return url


def get_html(url: str) -> tuple[str, str]:
    url = resolve_url(url)
    parsed = urlparse(url)
    origin = f"{parsed.scheme}://{parsed.netloc}/"

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": origin,
        "Connection": "keep-alive"
    }

    response = requests.get(
        url,
        headers=headers,
        timeout=30,
        verify=False,
        allow_redirects=True
    )

    response.raise_for_status()
    return response.text, response.url


def extract_trafilatura(html: str, url: str) -> Optional[str]:
    try:
        text = trafilatura.extract(
            html,
            url=url,
            output_format="markdown",
            favor_precision=True
        )
        return text.strip() if text else None
    except Exception:
        return None


def extract_fallback(html: str) -> Optional[str]:
    try:
        soup = BeautifulSoup(html, "html.parser")
    except Exception:
        return None

    for tag in soup(["script", "style", "noscript", "iframe", "header", "footer", "aside", "nav", "form"]):
        tag.decompose()

    selectors = [
        "article",
        ".article-body",
        ".story-content",
        ".post-content",
        "main",
        ".content",
        ".entry-content"
    ]

    for sel in selectors:
        node = soup.select_one(sel)
        if node:
            if md:
                return md(str(node))
            return node.get_text("\n\n", strip=True)

    paragraphs = soup.find_all("p")
    if paragraphs:
        return "\n\n".join(p.get_text(strip=True) for p in paragraphs if p.get_text(strip=True))

    return None


def scrape_article(url: str, title: Optional[str] = None, company: Optional[str] = None, published: Optional[str] = None) -> tuple[str, str, str]:
    html, final_url = get_html(url)
    page_title = title or _get_page_title(html, fallback=url)
    content = extract_trafilatura(html, final_url)
    if not content:
        content = extract_fallback(html)
    if not content:
        content = ""

    md_text = f"""# {page_title}

Published: {published}
Source: {final_url}

---

{content}
"""
    return md_text, page_title, final_url


def save_article_markdown(url: str, title: Optional[str] = None, company: Optional[str] = None, published: Optional[str] = None) -> str:
    md_text, page_title, final_url = scrape_article(url, title=title, company=company, published=published)
    filename = _sanitize_filename(page_title or final_url)
    if not filename:
        filename = "article"
    filepath = os.path.join(OUTPUT_DIR, f"{filename}.md")
    with open(filepath, "w", encoding="utf-8") as handle:
        handle.write(md_text)
    return filepath


def parse_agent_json(message_content: str) -> dict:
    try:
        return json.loads(message_content)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", message_content, re.S)
        if match:
            return json.loads(match.group())
        raise


def process_results(message_content: str) -> list[str]:
    parsed = parse_agent_json(message_content)
    results = parsed.get("results", [])
    file_paths = []
    for idx, item in enumerate(results, start=1):
        url = item.get("url")
        reason = item.get("reason")
        if not url:
            continue

        print(f"Scraping {idx}/{len(results)}: {url}")
        try:
            saved_path = save_article_markdown(url, title=None, company=None, published=None)
            file_paths.append(saved_path)
            print(f"Saved markdown: {saved_path}")
        except Exception as exc:
            print(f"Failed to scrape {url}: {exc}")

    return file_paths

def get_azure_chat_openai():
    key_vault_url = "https://fstodevazureopenai.vault.azure.net/"

    credential = DefaultAzureCredential()
    kv_client = SecretClient(vault_url=key_vault_url, credential=credential)

    subscription_key = kv_client.get_secret("llm-api-key").value
    endpoint = kv_client.get_secret("llm-base-endpoint").value
    deployment = kv_client.get_secret("llm-41").value
    api_version = kv_client.get_secret("llm-41-version").value

    llm = AzureChatOpenAI(
        azure_deployment=deployment,
        api_version=api_version,
        azure_endpoint=endpoint,
        api_key=subscription_key,
        streaming=True,
        temperature=0,
    )
    return llm


llm = get_azure_chat_openai()


@tool
def fetch_news(query: str, limit: int = 50):
    """Fetch relevant news articles for a query from Google News RSS."""

    url = f"https://news.google.com/rss/search?q={urllib.parse.quote(query)}&hl=en-IN&gl=IN&ceid=IN:en"
    feed = feedparser.parse(url)

    results = []
    for entry in feed.entries[:limit]:
        results.append({
            "title": entry.get("title", ""),
            "summary": entry.get("summary", ""),
            "url": entry.get("link", "")
        })
    return results


tools = [fetch_news]
llm = get_azure_chat_openai().bind_tools(tools)


class State(TypedDict):
    messages: Annotated[List, add_messages]


def agent_node(state: State):

    system_prompt = SystemMessage(content="""
    You are a News Agent.

    Instructions:
    1. When the user provides a query, ALWAYS use the `fetch_news` tool.
    2. Analyze the 'title' and 'summary' of EACH retrieved article against the user's query.
    3. Filter out all irrelevant articles.
    4. Return ONLY the relevant articles.

    Output Format (STRICT JSON ONLY):
    - Do NOT include any explanation, notes, or extra text.
    - Do NOT include markdown.
    - Return a valid JSON object with this structure:

    {
      "results": [
        {
          "url": "<article_url>",
          "reason": "<short reason why it is relevant>"
        }
      ]
    }

    Rules:
    - Include ONLY relevant articles.
    - If no relevant articles are found, return:
      { "results": [] }
    - Ensure valid JSON (no trailing commas, proper quotes).
    """)

    return {"messages": [llm.invoke([system_prompt] + state["messages"])]}


def tool_node(state: State):
    msg = state["messages"][-1]
    tool_results = []
    for tc in msg.tool_calls:
        result = fetch_news.invoke(tc["args"])
        tool_results.append(ToolMessage(content=str(result), tool_call_id=tc["id"]))
    return {"messages": tool_results}


builder = StateGraph(State)
builder.add_node("agent", agent_node)
builder.add_node("tools", tool_node)
builder.add_edge("tools", "agent")
builder.add_conditional_edges("agent", lambda s: "tools" if s["messages"][-1].tool_calls else END)
builder.set_entry_point("agent")

app = builder.compile(checkpointer=MemorySaver())


if __name__ == "__main__":
    thread_id = "news-filter-session"
    query = ("show me financials of hexaware last quarter")
    result = app.invoke(
        {"messages": [HumanMessage(content=query)]},
        config={"configurable": {"thread_id": thread_id}}
    )

    output_message = result["messages"][-1].content
    print(output_message)
    saved_files = process_results(output_message)
    if saved_files:
        print("\nMarkdown files created:")
        for path in saved_files:
            print(path)
    else:
        print("No markdown files were created.")