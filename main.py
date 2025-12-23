from utils.utils import log_step, log_error
import asyncio
import yaml
from dotenv import load_dotenv
from mcp_servers.multiMCP import MultiMCP
from agent.agent_loop3 import AgentLoop  # 🆕 Use loop3
from pprint import pprint
import httpx

BANNER = """
──────────────────────────────────────────────────────
🔸  Agentic Query Assistant  🔸
Type your question and press Enter.
Type 'exit' or 'quit' to leave.
──────────────────────────────────────────────────────
"""

async def interactive() -> None:
    log_step(BANNER, symbol="")
    log_step('Loading MCP Servers...', symbol="📥")

    # Load MCP server configs
    with open("config/mcp_server_config.yaml", "r") as f:
        profile = yaml.safe_load(f)
        mcp_servers_list = profile.get("mcp_servers", [])
        configs = list(mcp_servers_list)
    
    # Check if browser MCP server is running (SSE endpoints need special handling)
    browser_server_config = next((c for c in configs if c.get("id") == "webbrowsing"), None)
    if browser_server_config:
        browser_url = browser_server_config.get("script", "")
        if browser_url.startswith("http"):
            try:
                # For SSE endpoints, use stream to check connectivity (they keep connections open)
                async with httpx.AsyncClient(timeout=3.0) as client:
                    try:
                        async with client.stream("GET", browser_url) as response:
                            # If we get a response (even if streaming), server is reachable
                            if response.status_code < 500:
                                log_step(f"✅ Browser MCP server is running at {browser_url}", symbol="✅")
                            else:
                                log_step(f"⚠️  Browser MCP server returned error {response.status_code}", symbol="⚠️")
                    except httpx.TimeoutException:
                        # Timeout is OK for SSE - it means the server accepted the connection
                        # and is keeping it open (which is expected behavior)
                        log_step(f"✅ Browser MCP server is running at {browser_url} (SSE connection open)", symbol="✅")
                    except httpx.ConnectError:
                        log_step(f"⚠️  Browser MCP server not reachable at {browser_url}. Start it with: uv run .\\browserMCP\\browser_mcp_sse.py", symbol="⚠️")
            except Exception as e:
                # For other exceptions, just warn but don't fail (SSE servers are optional)
                log_step(f"⚠️  Could not verify browser MCP server at {browser_url}. If server is running, connection will be attempted anyway. Error: {type(e).__name__}", symbol="⚠️")

    # Initialize MultiMCP dispatcher
    multi_mcp = MultiMCP(server_configs=configs)
    await multi_mcp.initialize()
    
    # Log loaded tools for debugging
    all_tools = multi_mcp.get_all_tools()
    tool_names = [tool.name for tool in all_tools]
    log_step(f"Loaded {len(tool_names)} tools: {', '.join(tool_names[:10])}{'...' if len(tool_names) > 10 else ''}", symbol="✅")
    
    # Check if browser tools are available
    browser_tools = ['open_tab', 'search_google', 'input_text_by_index', 'click_element_by_index']
    missing_browser_tools = [tool for tool in browser_tools if tool not in tool_names]
    if missing_browser_tools:
        log_step(f"⚠️  Browser tools not available: {', '.join(missing_browser_tools)}. Make sure browser MCP server is running on port 8100.", symbol="⚠️")

    # Create a single persistent AgentLoop instance
    loop = AgentLoop(
        perception_prompt="prompts/perception_prompt.txt",
        decision_prompt="prompts/decision_prompt.txt",
        browser_decision_prompt="prompts/browser_decision_prompt.txt",
        summarizer_prompt="prompts/summarizer_prompt.txt",
        multi_mcp=multi_mcp,
        strategy="exploratory"
    )

    conversation_history = []  # stores (query, response) tuples

    try:
        while True:
            print("\n\n")
            query = input("📝  You: ").strip()
            if query.lower() in {"exit", "quit"}:
                log_step("Goodbye!", symbol="👋")
                break

            # Construct context string from past rounds
            context_prefix = ""
            for idx, (q, r) in enumerate(conversation_history, start=1):
                context_prefix += f"Query {idx}: {q}\nResponse {idx}: {r}\n"

            full_query = context_prefix + f"Query {len(conversation_history)+1}: {query}"

            try:
                response = await loop.run(full_query)  # 🔄 stateless loop sees full pseudo-history
                conversation_history.append((query, response.strip()))
                log_step("Agent Resting now", symbol="😴")
            except Exception as e:
                if "Unknown SSE event" in str(e):
                    pass  # suppress event noise like ping
                else:
                    log_error("Agent failed", e)

            follow = input("Continue? (press Enter) or type 'exit': ").strip()
            if follow.lower() in {"exit", "quit"}:
                log_step("Goodbye!", symbol="👋")
                break
    finally:
        await multi_mcp.shutdown()

if __name__ == "__main__":
    load_dotenv()
    asyncio.run(interactive())
