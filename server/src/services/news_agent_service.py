import urllib.parse
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse
from typing import TypedDict, Annotated, List, Optional

import feedparser
import requests
import time
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
import json
import re

import trafilatura

from config.settings import KEY_VAULT_URL, MARKDOWN_DIR

MARKDOWN_BASE = MARKDOWN_DIR
MARKDOWN_BASE.mkdir(parents=True, exist_ok=True)

def _sanitize_filename(name: str) -> str:
    # remove invalid filename characters
    name = re.sub(r'[\\/*?:"<>|]', "", name)
    name = name.strip()
    return name[:150] if len(name) > 150 else name


def _normalize_company_folder_name(company_name: Optional[str]) -> str:
    if not company_name:
        return "UNKNOWN_COMPANY"
    normalized = company_name.strip().upper().replace("&", "AND")
    normalized = re.sub(r"[^A-Z0-9_]+", "_", normalized)
    normalized = re.sub(r"_+", "_", normalized).strip("_")
    return normalized or "UNKNOWN_COMPANY"

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def _get_page_title(html: str, fallback: Optional[str] = None) -> str:
    try:
        soup = BeautifulSoup(html, "html.parser")
        if soup.title and soup.title.string:
            title_text = soup.title.string.strip()
            if title_text:
                return title_text
    except Exception as e:
        print(e)

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

    if not published:
        try:
            soup = BeautifulSoup(html, "html.parser")
            date_meta = None
            for meta in soup.find_all("meta"):
                name = (meta.get("name") or "").lower()
                prop = (meta.get("property") or "").lower()
                if prop in ["article:published_time", "og:published_time", "og:updated_time"] or name in ["pubdate", "publishdate", "published_time", "date", "dc.date", "dc.date.issued"]:
                    date_meta = meta.get("content") or meta.get("value")
                    if date_meta:
                        published = date_meta.strip()
                        break
        except Exception as e:
            print(f"Error scraping article: {e}")

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

    safe_company_name = _normalize_company_folder_name(company)
    today = datetime.now().strftime("%Y%m%d")
    company_dir = MARKDOWN_BASE / safe_company_name / today
    company_dir.mkdir(parents=True, exist_ok=True)

    filepath = company_dir / f"{filename}.md"
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


def process_results(message_content: str, company_name: Optional[str] = None) -> list[str]:
    parsed = parse_agent_json(message_content)
    results = parsed.get("results", [])[:3]
    file_paths = []
    for idx, item in enumerate(results, start=1):
        url = item.get("url")
        title = item.get("title")
        published = item.get("published")
        if not url:
            continue

        print(f"Scraping {idx}/{len(results)}: {url}")
        try:
            saved_path = save_article_markdown(url, title=title, company=company_name, published=published)
            file_paths.append(saved_path)
            print(f"Saved markdown: {saved_path}")
        except Exception as exc:
            print(f"Failed to scrape {url}: {exc}")

    return file_paths

def get_azure_chat_openai():
    key_vault_url = KEY_VAULT_URL

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


_llm_client = get_azure_chat_openai()


def _parse_entry_published(entry: dict) -> str:
    published = entry.get("published") or entry.get("updated") or ""
    if not published:
        parsed = entry.get("published_parsed") or entry.get("updated_parsed")
        if parsed:
            try:
                published = datetime.fromtimestamp(time.mktime(parsed)).isoformat()
            except Exception:
                published = ""
    return published


@tool
def fetch_news(query: str, limit: int = 5):
    """Fetch relevant news articles for a query from Google News RSS."""

    limit = min(limit, 3)
    url = f"https://news.google.com/rss/search?q={urllib.parse.quote(query)}&hl=en-IN&gl=IN&ceid=IN:en"
    feed = feedparser.parse(url)

    results = []
    for entry in feed.entries[:limit]:
        results.append({
            "title": entry.get("title", ""),
            "summary": entry.get("summary", ""),
            "url": entry.get("link", ""),
            "published": _parse_entry_published(entry)
        })
    return results


tools = [fetch_news]
llm = _llm_client.bind_tools(tools)


class State(TypedDict):
    messages: Annotated[List, add_messages]


def agent_node(state: State):

    system_prompt = SystemMessage(content="""
    You are a News Agent.

    Instructions:
    1. When the user provides a query, ALWAYS use the `fetch_news` tool.
    2. Analyze the 'title', 'summary', and 'published' values of EACH retrieved article against the user's query.
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
          "title": "<article_title>",
          "published": "<published_date_or_empty>",
          "reason": "<short reason why it is relevant>"
        }
      ]
    }

    Rules:
    - Return AT MOST 3 results.
    - Include ONLY the top 3 most relevant articles.
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
        tool_results.append(ToolMessage(content=json.dumps(result), tool_call_id=tc["id"]))
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