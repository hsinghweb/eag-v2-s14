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
from google.genai.errors import ServerError
from dotenv import load_dotenv
import asyncio
import os
import random
import re

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

def extract_retry_delay(error: Exception) -> float:
    """Extract retry delay from Gemini API error response"""
    try:
        error_str = str(error)
        # Look for retry delay in error message: "Please retry in 47.452700763s"
        match = re.search(r'retry in ([\d.]+)s', error_str, re.IGNORECASE)
        if match:
            return float(match.group(1))
        
        # Try to parse from error details if available
        if hasattr(error, 'error') and isinstance(error.error, dict):
            details = error.error.get('details', [])
            for detail in details:
                if detail.get('@type') == 'type.googleapis.com/google.rpc.RetryInfo':
                    retry_delay = detail.get('retryDelay', '')
                    # Parse duration string like "47s" or "47.452700763s"
                    match = re.search(r'([\d.]+)s', retry_delay)
                    if match:
                        return float(match.group(1))
    except Exception:
        pass
    return None

async def generate_with_retry(prompt: str, max_retries: int = 3) -> str:
    """Generate content with automatic retry on rate limit errors"""
    client = get_client()
    last_error = None
    
    for attempt in range(max_retries):
        try:
            # Run synchronous call in thread pool to avoid blocking event loop
            def _generate():
                return client.models.generate_content(
                    model="gemini-2.5-flash-lite",
                    contents=prompt
                )
            response = await asyncio.to_thread(_generate)
            return response.candidates[0].content.parts[0].text
            
        except ServerError as e:
            error_str = str(e)
            # Check if it's a 429 rate limit error
            if '429' in error_str or 'RESOURCE_EXHAUSTED' in error_str or 'quota' in error_str.lower():
                retry_delay = extract_retry_delay(e)
                
                if retry_delay is None:
                    # Default exponential backoff: 2^attempt seconds with jitter
                    retry_delay = (2 ** attempt) + random.uniform(0, 1)
                else:
                    # Add small jitter to server-suggested delay
                    retry_delay += random.uniform(0, 2)
                
                if attempt < max_retries - 1:
                    mcp_log("WARN", f"Rate limit exceeded (attempt {attempt + 1}/{max_retries}). Retrying in {retry_delay:.1f}s...")
                    await asyncio.sleep(retry_delay)
                    last_error = e
                    continue
                else:
                    raise RuntimeError(
                        f"Gemini generation failed after {max_retries} attempts due to rate limiting. "
                        f"Last error: {error_str}. Please wait and try again later."
                    )
            else:
                # Not a rate limit error, raise immediately
                raise e
        except Exception as e:
            # Check if it's a rate limit error in the exception message
            error_str = str(e)
            if '429' in error_str or 'RESOURCE_EXHAUSTED' in error_str or 'quota' in error_str.lower():
                retry_delay = extract_retry_delay(e)
                
                if retry_delay is None:
                    retry_delay = (2 ** attempt) + random.uniform(0, 1)
                else:
                    retry_delay += random.uniform(0, 2)
                
                if attempt < max_retries - 1:
                    mcp_log("WARN", f"Rate limit exceeded (attempt {attempt + 1}/{max_retries}). Retrying in {retry_delay:.1f}s...")
                    await asyncio.sleep(retry_delay)
                    last_error = e
                    continue
            raise RuntimeError(f"Gemini generation failed: {str(e)}")
    
    # Should not reach here, but just in case
    raise RuntimeError(f"Gemini generation failed after {max_retries} attempts: {str(last_error)}")


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

        # Use retry-enabled generation function
        raw = await generate_with_retry(full_prompt)
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