import ast
import asyncio
import time
import builtins
import textwrap
import re
import os
import json
from datetime import datetime
from pathlib import Path
import traceback
from utils.utils import log_json_block, log_step, log_error, log_json_block
from agent.agentSession import ExecutionSnapshot

ALLOWED_MODULES = {
    "math", "random", "re", "datetime", "time", "collections", "itertools",
    "statistics", "string", "functools", "operator", "json", "pprint", "copy",
    "typing", "uuid", "hashlib", "base64", "hmac", "struct", "decimal", "fractions"
}

SAFE_BUILTINS = [
    # Core types and structure
    "bool", "int", "float", "str", "list", "dict", "set", "tuple", "complex",
    
    # Iteration and collection helpers
    "range", "enumerate", "zip", "map", "filter", "reversed", "next",
    
    # Logic and math
    "abs", "round", "divmod", "pow", "sum", "min", "max", "all", "any",
    
    # String and character
    "ord", "chr", "len", "sorted",
    
    # Type inspection
    "isinstance", "issubclass", "type", "id",
    
    # Functional
    "callable", "hash", "format",
    
    # Import-related
    "__import__",

    # Output and utility
    "print", "locals", "globals", "repr"
]

MAX_FUNCTIONS = 20
TIMEOUT_PER_FUNCTION = 50

class KeywordStripper(ast.NodeTransformer):
    """Rewrite all function calls to remove keyword args and keep only values as positional."""
    def visit_Call(self, node):
        self.generic_visit(node)
        if node.keywords:
            # Convert all keyword arguments into positional args (discard names)
            for kw in node.keywords:
                node.args.append(kw.value)
            node.keywords = []
        return node


# ───────────────────────────────────────────────────────────────
# AST TRANSFORMER: auto-await known async MCP tools
# ───────────────────────────────────────────────────────────────
class AwaitTransformer(ast.NodeTransformer):
    def __init__(self, async_funcs):
        self.async_funcs = async_funcs

    def visit_Call(self, node):
        self.generic_visit(node)
        if isinstance(node.func, ast.Name) and node.func.id in self.async_funcs:
            return ast.Await(value=node)
        return node



def fix_unterminated_triple_quotes(code: str) -> str:
    import re
    triple_quotes = re.findall(r'''"""''', code)
    if len(triple_quotes) % 2 != 0:
        log_error("Fixing unterminated triple-quoted string...", symbol="⚠️ ")
        return code + '\n"""'
    return code


def build_safe_globals(mcp_funcs: dict, multi_mcp=None, session_id: str = None) -> dict:
    safe_globals = {
        "__builtins__": {
            k: getattr(builtins, k) for k in SAFE_BUILTINS
        },
        **mcp_funcs,
    }

    for module in ALLOWED_MODULES:
        safe_globals[module] = __import__(module)

    safe_globals["final_answer"] = lambda x: safe_globals.setdefault("result_holder", x)

    if session_id:
        safe_globals.update(load_session_vars(session_id))

    if multi_mcp:
        async def parallel(*tool_calls):
            coros = [multi_mcp.function_wrapper(tool_name, *args) for tool_name, *args in tool_calls]
            return await asyncio.gather(*coros)
        safe_globals["parallel"] = parallel

    # Allow both direct access (`urls`) and schema-style (`globals_schema.get("urls", "")`)
    safe_globals["globals_schema"] = {
        k: v for k, v in safe_globals.items() if k not in {"__builtins__", "final_answer", "parallel"}
    }

    return safe_globals


def save_session_vars(session_id: str, variables: dict):
    os.makedirs("action/sandbox_state", exist_ok=True)
    path = f"action/sandbox_state/{session_id}.json"

    # Load existing vars if any
    try:
        with open(path, "r", encoding="utf-8") as f:
            existing = json.load(f)
    except FileNotFoundError:
        existing = {}

    # Merge
    merged = {**existing, **variables}

    with open(path, "w", encoding="utf-8") as f:
        json.dump(merged, f, indent=2, ensure_ascii=False)


def load_session_vars(session_id: str) -> dict:
    try:
        with open(f"action/sandbox_state/{session_id}.json", "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def count_function_calls(code: str) -> int:
    tree = ast.parse(code)
    return sum(isinstance(node, ast.Call) for node in ast.walk(tree))


def make_tool_proxy(tool_name: str, mcp):
    async def _tool_fn(*args):
        return await mcp.function_wrapper(tool_name, *args)
    return _tool_fn

async def run_user_code(code: str, multi_mcp, session_id: str = "default_session") -> dict:
    start_time = time.perf_counter()
    start_timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def is_json_serializable(value):
        return isinstance(value, (str, int, float, bool, type(None), list, dict))

    try:
        func_count = count_function_calls(code)
        if func_count > MAX_FUNCTIONS:
            return {
                "status": "error",
                "error": f"Too many functions ({func_count} > {MAX_FUNCTIONS})",
                "execution_time": start_timestamp,
                "total_time": str(round(time.perf_counter() - start_time, 3))
            }

        tool_funcs = {
            tool.name: make_tool_proxy(tool.name, multi_mcp)
            for tool in multi_mcp.get_all_tools()
        }
        
        # Log available tools for debugging
        if not tool_funcs:
            log_error("⚠️  No tools available! Check MCP server connections.", symbol="⚠️")
        else:
            tool_names = list(tool_funcs.keys())
            browser_tools = ['open_tab', 'search_google', 'input_text_by_index', 'click_element_by_index']
            available_browser_tools = [t for t in browser_tools if t in tool_names]
            if available_browser_tools:
                log_step(f"✅ Browser tools available: {', '.join(available_browser_tools)}", symbol="✅")
            else:
                log_error(f"⚠️  Browser tools NOT available. Make sure browser MCP server is running on port 8100.", symbol="⚠️")
                log_error(f"   Available tools: {', '.join(tool_names[:10])}{'...' if len(tool_names) > 10 else ''}", symbol="   ")

        sandbox = build_safe_globals(tool_funcs, multi_mcp, session_id)
        local_vars = {}

        log_step(f"[CODE:]: {code}", symbol="🐍")

        cleaned_code = fix_unterminated_triple_quotes(textwrap.dedent(code.strip()))
        tree = ast.parse(cleaned_code)

        # ─── AST Transformations ─────────────────────────────────────
        tree = KeywordStripper().visit(tree)
        tree = AwaitTransformer(set(tool_funcs)).visit(tree)

        # Rewrite return <varname> → return {"varname": varname}
        new_body = []
        return_found = False
        for node in tree.body:
            if isinstance(node, ast.Return):
                return_found = True
                if isinstance(node.value, ast.Name):
                    varname = node.value.id
                    new_body.append(
                        ast.Return(
                            value=ast.Dict(
                                keys=[ast.Constant(value=varname)],
                                values=[ast.Name(id=varname, ctx=ast.Load())]
                            )
                        )
                    )
                else:
                    new_body.append(node)
            else:
                new_body.append(node)

        # If return is missing but 'result' exists, add `return result`
        has_result_var = any(
            isinstance(node, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == "result" for t in node.targets)
            for node in new_body
        )
        result_vars = {
            node.targets[0].id
            for node in tree.body
            if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name)
        }

        if not return_found and "result" in result_vars:
            new_body.append(ast.Return(value=ast.Name(id="result", ctx=ast.Load())))


        ast.fix_missing_locations(tree)
        tree.body = new_body
        ast.fix_missing_locations(tree)

        # ─── Wrap as async def __main() ──────────────────────────────
        func_def = ast.AsyncFunctionDef(
            name="__main",
            args=ast.arguments(posonlyargs=[], args=[], kwonlyargs=[], kw_defaults=[], defaults=[]),
            body=tree.body,
            decorator_list=[]
        )
        wrapper = ast.Module(body=[func_def], type_ignores=[])
        ast.fix_missing_locations(wrapper)
        

        compiled = compile(wrapper, filename="<user_code>", mode="exec")
        exec(compiled, sandbox, local_vars)

        # ─── Execute and collect result ──────────────────────────────
        timeout = max(3, func_count * TIMEOUT_PER_FUNCTION)
        returned = await asyncio.wait_for(local_vars["__main"](), timeout=timeout)

        result_value = {}
        

        def serialize_result(v):
            if isinstance(v, (str, int, float, bool, type(None), list, dict)):
                return v
            elif hasattr(v, "success") and hasattr(v, "content") and hasattr(v, "error"):
                # Handle ActionResultOutput from MCP tools
                if not v.success:
                    return f"Error executing tool: {v.error}"
                return v.content if v.content else "Success"
            elif hasattr(v, "content") and isinstance(v.content, list):
                return "\n".join(x.text for x in v.content if hasattr(x, "text"))
            else:
                return str(v)

        if isinstance(returned, dict) and list(returned.keys()) == ["result"]:
            result_value = {"result": serialize_result(returned["result"])}
        if isinstance(returned, dict):
            result_value = {k: serialize_result(v) for k, v in returned.items()}
            
            # Check for MCP tool failures or error messages
            for v in result_value.values():
                if isinstance(v, str) and (
                    v.lower().startswith("error executing tool") or
                    v.lower().startswith("error:") or
                    "failed" in v.lower()
                ):
                    return {
                        "status": "error", 
                        "error": v,
                        "execution_time": start_timestamp,
                        "total_time": str(round(time.perf_counter() - start_time, 3))
                    }
            
            # Check if any MCP tool returned success=False
            for k, v in returned.items():
                if hasattr(v, "success") and not v.success:
                    error_msg = v.error if hasattr(v, "error") and v.error else f"Tool {k} failed"
                    return {
                        "status": "error",
                        "error": error_msg,
                        "execution_time": start_timestamp,
                        "total_time": str(round(time.perf_counter() - start_time, 3))
                    }

        else:
            result_value = {"result": serialize_result(returned)}

        # import pdb; pdb.set_trace()

        

        log_json_block("Executor result", result_value)

        save_session_vars(session_id, result_value)
        # import pdb; pdb.set_trace()

        return {
            "status": "success",
            "result": result_value,
            "raw": result_value,
            "execution_time": start_timestamp,
            "total_time": str(round(time.perf_counter() - start_time, 3))
        }

    except asyncio.TimeoutError:
        return {
            "status": "error",
            "error": f"Execution timed out after {func_count * TIMEOUT_PER_FUNCTION} seconds",
            "execution_time": start_timestamp,
            "total_time": str(round(time.perf_counter() - start_time, 3))
        }
    except UnboundLocalError as e:
        # Handle UnboundLocalError - variable accessed before assignment
        error_msg = str(e)
        tb = traceback.format_exc()
        
        # Try to extract variable name from error
        var_match = re.search(r"local variable '(\w+)' referenced before assignment", error_msg)
        if var_match:
            var_name = var_match.group(1)
            suggestion = (
                f"UnboundLocalError: Variable '{var_name}' was accessed before being assigned a value.\n"
                f"This usually happens when:\n"
                f"  1. A tool call failed and the result wasn't checked before use\n"
                f"  2. The variable is used in a conditional that didn't execute\n"
                f"  3. The tool returned an error instead of expected data\n\n"
                f"💡 Fix: Always check if tool calls succeeded and handle errors:\n"
                f"   result = await tool_name(...)\n"
                f"   if isinstance(result, str) and result.startswith('[error]'):\n"
                f"       # Handle error case\n"
                f"   else:\n"
                f"       # Use result safely\n"
            )
        else:
            suggestion = (
                f"UnboundLocalError: A variable was accessed before being assigned.\n"
                f"Check your code to ensure all variables are assigned before use."
            )
        
        log_error(f"UnboundLocalError: {error_msg}", symbol="❌")
        return {
            "status": "error",
            "error": f"{suggestion}\n\nOriginal error: {error_msg}",
            "traceback": tb,
            "execution_time": start_timestamp,
            "total_time": str(round(time.perf_counter() - start_time, 3))
        }
    except NameError as e:
        # Special handling for missing browser tools
        error_msg = str(e)
        if any(tool in error_msg for tool in ['open_tab', 'search_google', 'input_text_by_index', 'click_element_by_index']):
            return {
                "status": "error",
                "error": f"{type(e).__name__}: {error_msg}\n\n⚠️  Browser tools are not available. Make sure the browser MCP server is running:\n   uv run .\\browserMCP\\browser_mcp_sse.py",
                "execution_time": start_timestamp,
                "total_time": str(round(time.perf_counter() - start_time, 3))
            }
        return {
            "status": "error",
            "error": f"{type(e).__name__}: {error_msg}\n\n💡 This usually means a function or variable name is misspelled or not defined.",
            "traceback": traceback.format_exc(),
            "execution_time": start_timestamp,
            "total_time": str(round(time.perf_counter() - start_time, 3))
        }
    except ValueError as e:
        # Better handling for ValueError (often from tool argument mismatches)
        error_msg = str(e)
        tb = traceback.format_exc()
        
        if "expects" in error_msg and "args" in error_msg:
            suggestion = (
                f"ValueError: Tool argument mismatch.\n"
                f"{error_msg}\n\n"
                f"💡 Fix: Check the tool's expected arguments and provide them in the correct order."
            )
        else:
            suggestion = f"ValueError: {error_msg}"
        
        log_error(f"ValueError: {error_msg}", symbol="❌")
        return {
            "status": "error",
            "error": suggestion,
            "traceback": tb,
            "execution_time": start_timestamp,
            "total_time": str(round(time.perf_counter() - start_time, 3))
        }
    except AttributeError as e:
        # Handle AttributeError - often from data extraction on dynamic websites
        error_msg = str(e)
        tb = traceback.format_exc()
        
        # Try to extract attribute name from error
        attr_match = re.search(r"'(\w+)'", error_msg)
        if attr_match:
            attr_name = attr_match.group(1)
            suggestion = (
                f"AttributeError: '{attr_name}' attribute not found.\n\n"
                f"This often happens when:\n"
                f"  1. Extracting data from dynamic websites (real estate, e-commerce)\n"
                f"  2. The page structure changed or content hasn't loaded yet\n"
                f"  3. Trying to access attributes on None/empty objects\n\n"
                f"💡 Fix strategies:\n"
                f"  - Wait for page to load: use `wait(3)` after navigation\n"
                f"  - Check if object exists before accessing: `if result and hasattr(result, '{attr_name}'):`\n"
                f"  - Use `get_comprehensive_markdown()` to see actual page content\n"
                f"  - Try extracting raw text first, then parse patterns\n"
                f"  - Scroll to reveal content: `scroll_down(500)`\n"
                f"  - Take screenshot to verify page state: `take_screenshot()`\n\n"
                f"Original error: {error_msg}"
            )
        else:
            suggestion = (
                f"AttributeError: An attribute was accessed that doesn't exist.\n\n"
                f"This often happens with dynamic websites where content loads via JavaScript.\n"
                f"Try waiting longer, checking if objects exist, or extracting raw text instead.\n\n"
                f"Original error: {error_msg}"
            )
        
        log_error(f"AttributeError: {error_msg}", symbol="❌")
        return {
            "status": "error",
            "error": suggestion,
            "traceback": tb,
            "execution_time": start_timestamp,
            "total_time": str(round(time.perf_counter() - start_time, 3))
        }
    except Exception as e:
        print("⚠️ Code execution error:\n", traceback.format_exc())
        error_msg = str(e)
        tb = traceback.format_exc()
        
        # Check for Playwright browser executable errors
        if "Executable doesn't exist" in error_msg or "chrome.exe" in error_msg:
            return {
                "status": "error",
                "error": f"{type(e).__name__}: {error_msg}\n\n⚠️  Playwright browser executable not found. Run: python -m playwright install chromium",
                "execution_time": start_timestamp,
                "total_time": str(round(time.perf_counter() - start_time, 3))
            }
        
        # Check for tool-related errors
        if "Tool" in error_msg or "tool" in error_msg.lower():
            suggestion = (
                f"{type(e).__name__}: {error_msg}\n\n"
                f"💡 This might be a tool execution error. Check:\n"
                f"  1. Tool name is correct\n"
                f"  2. Arguments match the tool's expected format\n"
                f"  3. Tool returned valid data (not an error message)"
            )
        else:
            suggestion = f"{type(e).__name__}: {error_msg}"
        
        return {
            "status": "error",
            "error": suggestion,
            "traceback": tb,
            "execution_time": start_timestamp,
            "total_time": str(round(time.perf_counter() - start_time, 3))
        }
