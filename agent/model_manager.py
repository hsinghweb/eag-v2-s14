import os
import json
import yaml
import requests
import asyncio
import random
from pathlib import Path
from google import genai
from google.genai.errors import ServerError
from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).parent.parent
MODELS_JSON = ROOT / "config" / "models.json"
PROFILE_YAML = ROOT / "config" / "profiles.yaml"

class ModelManager:
    def __init__(self):
        self.config = json.loads(MODELS_JSON.read_text())
        self.profile = yaml.safe_load(PROFILE_YAML.read_text())

        self.text_model_key = self.profile["llm"]["text_generation"]
        self.model_info = self.config["models"][self.text_model_key]
        self.model_type = self.model_info["type"]

        # ✅ Gemini initialization with new library
        if self.model_type == "gemini":
            api_key = os.getenv("GEMINI_API_KEY")
            self.client = genai.Client(api_key=api_key)

    async def generate_text(self, prompt: str) -> str:
        if self.model_type == "gemini":
            return await self._gemini_generate(prompt)

        elif self.model_type == "ollama":
            return await self._ollama_generate(prompt)

        raise NotImplementedError(f"Unsupported model type: {self.model_type}")

    async def generate_content(self, contents: list) -> str:
        """Generate content with support for text and images"""
        if self.model_type == "gemini":
            return await self._gemini_generate_content(contents)
        elif self.model_type == "ollama":
            # Ollama doesn't support images, fall back to text-only
            text_content = ""
            for content in contents:
                if isinstance(content, str):
                    text_content += content
            return await self._ollama_generate(text_content)
        
        raise NotImplementedError(f"Unsupported model type: {self.model_type}")

    def _extract_retry_delay(self, error: Exception) -> float:
        """Extract retry delay from Gemini API error response"""
        try:
            error_str = str(error)
            # Look for retry delay in error message: "Please retry in 47.452700763s"
            import re
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

    async def _gemini_generate(self, prompt: str, max_retries: int = 3) -> str:
        """Generate text with automatic retry on rate limit errors"""
        last_error = None
        
        for attempt in range(max_retries):
            try:
                # ✅ CORRECT: Use truly async method
                response = await self.client.aio.models.generate_content(
                    model=self.model_info["model"],
                    contents=prompt
                )
                return response.text.strip()

            except ServerError as e:
                error_str = str(e)
                # Check if it's a 429 rate limit error
                if '429' in error_str or 'RESOURCE_EXHAUSTED' in error_str or 'quota' in error_str.lower():
                    retry_delay = self._extract_retry_delay(e)
                    
                    if retry_delay is None:
                        # Default exponential backoff: 2^attempt seconds with jitter
                        retry_delay = (2 ** attempt) + random.uniform(0, 1)
                    else:
                        # Add small jitter to server-suggested delay
                        retry_delay += random.uniform(0, 2)
                    
                    if attempt < max_retries - 1:
                        print(f"⚠️  Rate limit exceeded (attempt {attempt + 1}/{max_retries}). Retrying in {retry_delay:.1f}s...")
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
                # ✅ Handle other potential errors
                raise RuntimeError(f"Gemini generation failed: {str(e)}")
        
        # Should not reach here, but just in case
        raise RuntimeError(f"Gemini generation failed after {max_retries} attempts: {str(last_error)}")

    async def _gemini_generate_content(self, contents: list, max_retries: int = 3) -> str:
        """Generate content with support for text and images using Gemini, with retry on rate limits"""
        last_error = None
        
        for attempt in range(max_retries):
            try:
                # ✅ Use async method with contents array (text + images)
                response = await self.client.aio.models.generate_content(
                    model=self.model_info["model"],
                    contents=contents
                )
                return response.text.strip()

            except ServerError as e:
                error_str = str(e)
                # Check if it's a 429 rate limit error
                if '429' in error_str or 'RESOURCE_EXHAUSTED' in error_str or 'quota' in error_str.lower():
                    retry_delay = self._extract_retry_delay(e)
                    
                    if retry_delay is None:
                        # Default exponential backoff: 2^attempt seconds with jitter
                        retry_delay = (2 ** attempt) + random.uniform(0, 1)
                    else:
                        # Add small jitter to server-suggested delay
                        retry_delay += random.uniform(0, 2)
                    
                    if attempt < max_retries - 1:
                        print(f"⚠️  Rate limit exceeded (attempt {attempt + 1}/{max_retries}). Retrying in {retry_delay:.1f}s...")
                        await asyncio.sleep(retry_delay)
                        last_error = e
                        continue
                    else:
                        raise RuntimeError(
                            f"Gemini content generation failed after {max_retries} attempts due to rate limiting. "
                            f"Last error: {error_str}. Please wait and try again later."
                        )
                else:
                    # Not a rate limit error, raise immediately
                    raise e
            except Exception as e:
                # ✅ Handle other potential errors
                raise RuntimeError(f"Gemini content generation failed: {str(e)}")
        
        # Should not reach here, but just in case
        raise RuntimeError(f"Gemini content generation failed after {max_retries} attempts: {str(last_error)}")

    async def _ollama_generate(self, prompt: str) -> str:
        try:
            # ✅ Use aiohttp for truly async requests
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.model_info["url"]["generate"],
                    json={"model": self.model_info["model"], "prompt": prompt, "stream": False}
                ) as response:
                    response.raise_for_status()
                    result = await response.json()
                    return result["response"].strip()
        except Exception as e:
            raise RuntimeError(f"Ollama generation failed: {str(e)}")
