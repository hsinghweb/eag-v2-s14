import os
import json
from pathlib import Path
from utils.utils import log_step, log_error, log_json_block
from google.genai.errors import ServerError
import re
from utils.json_parser import parse_llm_json
from agent.agentSession import DecisionSnapshot
from mcp_servers.multiMCP import MultiMCP
import ast
import time
from utils.utils import log_step
import asyncio
from typing import Any, Literal, Optional
from agent.agentSession import AgentSession
import uuid
from datetime import datetime
from agent.model_manager import ModelManager

class Decision:
    def __init__(self, decision_prompt_path: str, multi_mcp: MultiMCP, browser_decision_prompt_path: str = None, api_key: str | None = None, model: str = "gemini-2.5-flash-lite"):
        self.decision_prompt_path = decision_prompt_path
        self.browser_decision_prompt_path = browser_decision_prompt_path
        self.multi_mcp = multi_mcp
        self.model = ModelManager()
        
    def extract_latest_screenshot_path(self, decision_input: dict) -> Optional[str]:
        """Extract the latest SeraphineScreenshot path from the decision input data only"""
        try:
            # Convert decision input to JSON string to search through it
            decision_json = json.dumps(decision_input, indent=2)
            
            # Find all SeraphineScreenshot occurrences in the actual data
            screenshot_pattern = r'SeraphineScreenshot:\s*([^\n\r"]+)'
            matches = re.findall(screenshot_pattern, decision_json)
            
            if matches:
                # Return the last (most recent) screenshot path
                latest_path = matches[-1].strip()
                log_step(f"📸 Found latest screenshot in decision data: {latest_path}", symbol="🔍")
                return latest_path
            else:
                log_step("📸 No SeraphineScreenshot found in decision input data", symbol="🔍")
                return None
                
        except Exception as e:
            log_error(f"Error extracting screenshot path: {e}")
            return None
        
    async def run(self, decision_input: dict, session: Optional[AgentSession] = None) -> dict:
        route = decision_input.get("perception", {}).get("route", "decision")
        
        if route == "browserAgent":
            prompt_path = self.browser_decision_prompt_path
            log_step("🌐 Using BROWSER AGENT prompt", symbol="🔄")
        else:
            prompt_path = self.decision_prompt_path
            
        prompt_template = Path(prompt_path).read_text(encoding="utf-8")
        function_list_text = self.multi_mcp.tool_description_wrapper()
        tool_descriptions = "\n".join(f"- `{desc.strip()}`" for desc in function_list_text)
        tool_descriptions = "\n\n### The ONLY Available Tools\n\n---\n\n" + tool_descriptions
        full_prompt = f"{prompt_template.strip()}\n{tool_descriptions}\n\n```json\n{json.dumps(decision_input, indent=2)}\n```"

        # import pdb; pdb.set_trace()

        # Extract latest screenshot path from decision input data only
        screenshot_path = self.extract_latest_screenshot_path(decision_input)
        
        raw_text = ""
        try:
            log_step("[SENDING PROMPT TO DECISION...]", symbol="→")
            time.sleep(2)
            
            # Check if we have a screenshot to send
            if screenshot_path and os.path.exists(screenshot_path):
                log_step(f"📸 Sending prompt WITH image: {screenshot_path}", symbol="🖼️")
                from PIL import Image
                try:
                    image = Image.open(screenshot_path)
                    response = await self.model.generate_content(
                        contents=[full_prompt, image]
                    )
                except Exception as img_error:
                    log_error(f"📸 Error loading image {screenshot_path}: {img_error}")
                    log_step("📸 Falling back to text-only prompt", symbol="⚠️")
                    response = await self.model.generate_text(
                        prompt=full_prompt
                    )
            else:
                if screenshot_path:
                    log_step(f"📸 Screenshot path found but file doesn't exist: {screenshot_path}", symbol="⚠️")
                log_step("📸 Sending text-only prompt (no valid screenshot)", symbol="📝")
                response = await self.model.generate_text(
                    prompt=full_prompt
                )
                
            log_step("[RECEIVED OUTPUT FROM DECISION...]", symbol="←")

            output = parse_llm_json(response, required_keys=["plan_graph", "next_step_id", "code_variants"])

            if session:
                session.add_decision_snapshot(
                    DecisionSnapshot(
                        run_id=decision_input.get("run_id", str(uuid.uuid4())),
                        input=decision_input,
                        plan_graph=output["plan_graph"],
                        next_step_id=output["next_step_id"],
                        code_variants=output["code_variants"],
                        output=output,
                        timestamp=decision_input.get("timestamp"),
                        return_to=""
                    )
                )

            return output

        except ServerError as e:
            log_error(f"🚫 DECISION LLM ServerError: {e}")
            if session:
                session.add_decision_snapshot(
                    DecisionSnapshot(
                        run_id=decision_input.get("run_id", str(uuid.uuid4())),
                        input=decision_input,
                        plan_graph={},
                        next_step_id="",
                        code_variants={},
                        output={"error": "ServerError", "message": str(e)},
                        timestamp=decision_input.get("timestamp"),
                        return_to=""
                    )
                )
            return {
                "plan_graph": {},
                "next_step_id": "",
                "code_variants": {},
                "error": "Decision ServerError: LLM unavailable"
            }

        except Exception as e:
            log_error(f"🛑 DECISION ERROR: {str(e)}")
            if session:
                session.add_decision_snapshot(
                    DecisionSnapshot(
                        run_id=decision_input.get("run_id", str(uuid.uuid4())),
                        input=decision_input,
                        plan_graph={},
                        next_step_id="",
                        code_variants={},
                        output={"error": str(e), "raw_text": raw_text},
                        timestamp=decision_input.get("timestamp"),
                        return_to=""
                    )
                )
            return {
                "plan_graph": {},
                "next_step_id": "",
                "code_variants": {},
                "error": "Decision failed due to malformed response"
            }



def build_decision_input(ctx, query, p_out, strategy):
    completed_steps = [ctx.steps[n].__dict__ for n in ctx.steps if ctx.steps[n].status == "completed"]
    
    # DEBUG: Print what we're seeing
    print(f"🔍 DEBUG - completed_steps: {[step.get('index') for step in completed_steps]}")
    
    real_completed_steps = [step for step in completed_steps if step.get('index') != 'ROOT']
    
    print(f"🔍 DEBUG - real_completed_steps: {[step.get('index') for step in real_completed_steps]}")
    
    plan_mode = "initial" if len(real_completed_steps) == 0 else "mid_session"
    
    print(f"🔍 DEBUG - plan_mode: {plan_mode}")
    
    # 🔥 NEW: DETERMINISTIC PROMPT TRIMMING
    step_count = len(real_completed_steps)
    
    # Base decision input
    decision_input = {
        "current_time": datetime.utcnow().isoformat(),
        "plan_mode": plan_mode,
        "planning_strategy": strategy,
        "original_query": query,
        "perception": p_out,
        "plan_graph": {},
    }
    
    # 🎯 SMART TRIMMING BASED ON STEP COUNT
    if step_count <= 1:  # Only steps 0, 1 get full context  
        # Send everything
        decision_input.update({
            "completed_steps": completed_steps,
            "failed_steps": [ctx.steps[n].__dict__ for n in ctx.failed_nodes],
            "globals_schema": {
                k: {
                    "type": type(v).__name__,
                    "preview": str(v)[:500] + ("…" if len(str(v)) > 500 else "")
                } for k, v in ctx.globals.items()
            }
        })
        print(f"📊 FULL CONTEXT: Step {step_count} - sending complete data")
    else:  # Step 2+ get trimmed
        # Start trimming
        print(f"✂️ TRIMMING: Step {step_count} - applying smart compression")
        
        # 1. 🗑️ TRIM GLOBALS: Only keep latest page state + essential vars
        trimmed_globals = trim_globals_schema(ctx.globals, step_count)
        
        # 2. 📝 TRIM COMPLETED STEPS: Compress to essential outcomes only  
        trimmed_completed_steps = compress_completed_steps(completed_steps)
        
        # 3. ⚠️ TRIM FAILED STEPS: Just count, not full details
        failed_count = len([ctx.steps[n].__dict__ for n in ctx.failed_nodes])
        
        decision_input.update({
            "completed_steps": trimmed_completed_steps,
            "failed_steps_count": failed_count,  # Just the count
            "globals_schema": trimmed_globals,
            "_trimming_applied": True,  # Flag for debugging
            "_original_step_count": step_count
        })
        
        print(f"📉 COMPRESSION APPLIED: {step_count} steps → compressed format")
    
    return decision_input


def trim_globals_schema(globals_dict: dict, step_count: int) -> dict:
    """
    🔥 DETERMINISTIC GLOBALS TRIMMING
    Keep only: latest page state (FULL) + memory + essential execution context
    Drop: old page states (historical data)
    """
    trimmed = {}
    
    # Always keep memory (usually small)
    if "memory" in globals_dict:
        trimmed["memory"] = {
            "type": type(globals_dict["memory"]).__name__,
            "preview": str(globals_dict["memory"])[:200] + ("…" if len(str(globals_dict["memory"])) > 200 else "")
        }
    
    # Find the latest page state (highest step number)
    page_states = {k: v for k, v in globals_dict.items() if k.startswith("page_state_")}
    
    if page_states:
        # Get the most recent page state only
        latest_key = max(page_states.keys(), key=lambda x: x.split("_")[-1])
        
        # 🎯 KEEP LATEST PAGE STATE COMPLETELY INTACT - THIS IS CURRENT CONTEXT!
        trimmed[latest_key] = {
            "type": type(page_states[latest_key]).__name__,
            "preview": str(page_states[latest_key])  # NO TRUNCATION!
        }
        print(f"🎯 GLOBALS: Kept FULL {latest_key}, dropped {len(page_states)-1} old page states")
    
    # Keep any other essential variables (non-page-state)  
    essential_vars = {k: v for k, v in globals_dict.items() 
                     if not k.startswith("page_state_") and k != "memory"}
    
    for k, v in essential_vars.items():
        trimmed[k] = {
            "type": type(v).__name__,
            "preview": str(v)[:300] + ("…" if len(str(v)) > 300 else "")
        }
    
    # Add execution summary for context
    trimmed["_execution_summary"] = {
        "type": "str", 
        "preview": f"Completed {step_count} steps successfully. Previous page states available but trimmed for efficiency."
    }
    
    return trimmed


def compress_completed_steps(completed_steps: list) -> list:
    """
    📝 COMPRESS COMPLETED STEPS 
    Keep essential info: step ID, description, status, key outcome
    Remove: full results, detailed perception, verbose data
    """
    compressed = []
    original_size = sum(len(str(step)) for step in completed_steps)

    
    for step in completed_steps:
        # Extract only essential information
        essential_step = {
            "index": step.get("index"),
            "description": step.get("description", "")[:100],  # Truncate long descriptions
            "status": step.get("status"),
            "type": step.get("type")
        }
        
        # Add key outcome summary instead of full result
        result = step.get("result")
        if result:
            if isinstance(result, dict):
                # For page states, just indicate success + page type
                if any(k.startswith("page_state_") for k in result.keys()):
                    essential_step["outcome"] = "page_interaction_successful"
                else:
                    essential_step["outcome"] = "data_extracted"
            else:
                essential_step["outcome"] = "action_completed"
        
        # Keep error info if present (important for decision making)
        if step.get("error"):
            essential_step["error"] = str(step.get("error"))[:200]
            
        compressed.append(essential_step)

    compressed_size = sum(len(str(step)) for step in compressed)
    reduction_pct = ((original_size - compressed_size) / original_size) * 100 if original_size > 0 else 0
    
    
    print(f"📦 STEPS: Compressed {len(completed_steps)} steps, reduced size {reduction_pct:.1f}%")
    return compressed