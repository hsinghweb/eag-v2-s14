from mcp.server.fastmcp import FastMCP, Context
import httpx
from bs4 import BeautifulSoup
from typing import List, Dict, Optional, Any
from dataclasses import dataclass
import urllib.parse
import sys
import traceback
from datetime import datetime, timedelta
import time
import re
from pydantic import BaseModel, Field
from models import SearchInput, UrlInput, URLListOutput, SummaryInput
from models import PythonCodeOutput
from tools.web_tools_async import smart_web_extract
from tools.switch_search_method import smart_search
from mcp.types import TextContent
from google import genai
from dotenv import load_dotenv
import asyncio
import os
import random

# Fix Windows encoding issues
if sys.platform == "win32":
    # Set stdout/stderr to UTF-8 on Windows
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    if hasattr(sys.stderr, 'reconfigure'):
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')

load_dotenv()

# Initialize FastMCP server
mcp = FastMCP("ddg-search")

# Initialize Gemini client lazily to avoid crashes on import
_client = None
def get_client():
    global _client
    if _client is None:
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY environment variable is not set")
        _client = genai.Client(api_key=api_key)
    return _client


# Duckduck not responding? Check this: https://html.duckduckgo.com/html?q=Model+Context+Protocol
@mcp.tool()
async def web_search_urls(input: SearchInput, ctx: Context) -> URLListOutput:
    """Search the web using multiple engines (DuckDuckGo, Bing, Ecosia, etc.) and return a list of relevant result URLs"""

    try:
        urls = await smart_search(input.query, input.max_results)
        # Ensure all URLs are properly encoded strings
        encoded_urls = []
        for url in urls:
            try:
                # Try to encode/decode to ensure it's valid UTF-8
                if isinstance(url, str):
                    url.encode('utf-8', errors='replace').decode('utf-8')
                    encoded_urls.append(url)
                else:
                    encoded_urls.append(str(url).encode('utf-8', errors='replace').decode('utf-8'))
            except Exception as url_err:
                # If encoding fails, use a safe representation
                encoded_urls.append(f"[encoding_error: {str(url_err)}]")
        return URLListOutput(result=encoded_urls)
    except Exception as e:
        error_msg = str(e).encode('utf-8', errors='replace').decode('utf-8')
        traceback.print_exc(file=sys.stderr)
        return URLListOutput(result=[f"[error] {error_msg}"])


@mcp.tool()
async def webpage_url_to_raw_text(url: str) -> dict:
    """Extract readable text from a webpage"""
    try:
        result = await asyncio.wait_for(smart_web_extract(url), timeout=25)
        return {
            "content": [
                TextContent(
                    type="text",
                    text=f"[{result.get('best_text_source', '')}] " + result.get("best_text", "")[:3000]
                )
            ]
        }
    except asyncio.TimeoutError:
        return {
            "content": [
                TextContent(
                    type="text",
                    text="[error] Timed out while extracting web content"
                )
            ]
        }


@mcp.tool()
async def webpage_url_to_llm_summary(input: SummaryInput, ctx: Context) -> dict:
    """Summarize the webpage using a custom prompt if provided, otherwise fallback to default."""
    try:
        result = await asyncio.wait_for(smart_web_extract(input.url), timeout=25)
        text = result.get("best_text", "")[:3000]

        if not text.strip():
            return {
                "content": [
                    TextContent(
                        type="text",
                        text="[error] Empty or unreadable content from webpage."
                    )
                ]
            }

        clean_text = text.encode("utf-8", errors="replace").decode("utf-8").strip()

        prompt = input.prompt or (
            "Summarize this text as best as possible. Keep important entities and values intact. "
            "Only reply back in summary, and not extra description."
        )

        full_prompt = f"{prompt.strip()}\n\n[text below]\n{clean_text}"

        client = get_client()
        response = client.models.generate_content(
            model="gemini-2.5-flash-lite",
            contents=full_prompt
        )

        raw = response.candidates[0].content.parts[0].text
        summary = raw.encode("utf-8", errors="replace").decode("utf-8").strip()

        return {
            "content": [
                TextContent(
                    type="text",
                    text=summary
                )
            ]
        }

    except asyncio.TimeoutError:
        return {
            "content": [
                TextContent(
                    type="text",
                    text="[error] Timed out while extracting web content."
                )
            ]
        }

    except Exception as e:
        return {
            "content": [
                TextContent(
                    type="text",
                    text=f"[error] {str(e)}"
                )
            ]
        }


def mcp_log(level: str, message: str) -> None:
    sys.stderr.write(f"{level}: {message}\n")
    sys.stderr.flush()


if __name__ == "__main__":
    try:
        sys.stderr.write("mcp_server_3.py READY\n")
        sys.stderr.flush()
        if len(sys.argv) > 1 and sys.argv[1] == "dev":
            mcp.run()  # Run without transport for dev server
        else:
            mcp.run(transport="stdio")  # Run with stdio for direct execution
    except Exception as e:
        sys.stderr.write(f"Fatal error in mcp_server_3.py: {e}\n")
        sys.stderr.write(traceback.format_exc())
        sys.stderr.flush()
        sys.exit(1)