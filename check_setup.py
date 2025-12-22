"""Check if all required components are set up correctly"""
import sys
import os
from pathlib import Path

# Fix Windows console encoding
if sys.platform == "win32":
    import io
    if hasattr(sys.stdout, 'buffer'):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    if hasattr(sys.stderr, 'buffer'):
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

def check_playwright():
    """Check if Playwright and Chromium are installed"""
    try:
        from playwright.async_api import async_playwright
        import asyncio
        
        async def test():
            pw = await async_playwright().start()
            browser = await pw.chromium.launch(headless=True)
            await browser.close()
            await pw.stop()
        
        asyncio.run(test())
        print("✅ Playwright Chromium is installed and working")
        return True
    except Exception as e:
        print(f"❌ Playwright issue: {e}")
        print("   Fix: Run: python -m playwright install chromium")
        return False

def check_browser_server():
    """Check if browser MCP server is running"""
    try:
        import httpx
        import asyncio
        
        async def test():
            try:
                async with httpx.AsyncClient(timeout=3.0, follow_redirects=True) as client:
                    # Try to connect to the SSE endpoint
                    # SSE endpoints keep connections open, so we use stream and timeout quickly
                    async with client.stream("GET", "http://localhost:8100/sse", timeout=2.0) as response:
                        # If we get a response (even if it's streaming), server is reachable
                        status = response.status_code
                        # Read a bit to see if connection works
                        try:
                            await asyncio.wait_for(response.aread(), timeout=1.0)
                        except asyncio.TimeoutError:
                            # Timeout is OK for SSE - it means connection is open
                            pass
                        return status < 500
            except httpx.TimeoutException:
                # Timeout might mean server is keeping connection open (normal for SSE)
                return True
            except httpx.ConnectError:
                return False
        
        result = asyncio.run(test())
        if result:
            print("✅ Browser MCP server is running on port 8100")
            return True
        else:
            print("⚠️  Browser MCP server returned an error")
            return False
    except Exception as e:
        # Check if port is at least listening
        try:
            import socket
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1)
            result = sock.connect_ex(('localhost', 8100))
            sock.close()
            if result == 0:
                print("⚠️  Port 8100 is open but SSE endpoint may not be responding correctly")
                print(f"   Error: {e}")
                return False
        except:
            pass
        print("❌ Browser MCP server is NOT running")
        print("   Fix: Run in a separate terminal: uv run .\\browserMCP\\browser_mcp_sse.py")
        return False

def check_dependencies():
    """Check if required dependencies are installed"""
    required = ['playwright', 'psutil', 'patchright', 'posthog']
    missing = []
    
    for dep in required:
        try:
            __import__(dep)
            print(f"✅ {dep} is installed")
        except ImportError:
            print(f"❌ {dep} is missing")
            missing.append(dep)
    
    if missing:
        print(f"\n   Fix: Run: uv pip install {' '.join(missing)}")
        return False
    return True

def main():
    print("=" * 60)
    print("[CHECK] Checking Browser Automation Setup")
    print("=" * 60)
    print()
    
    all_ok = True
    
    print("1. Checking dependencies...")
    if not check_dependencies():
        all_ok = False
    print()
    
    print("2. Checking Playwright installation...")
    if not check_playwright():
        all_ok = False
    print()
    
    print("3. Checking browser MCP server...")
    if not check_browser_server():
        all_ok = False
    print()
    
    print("=" * 60)
    if all_ok:
        print("✅ All checks passed! You're ready to run the application.")
    else:
        print("❌ Some checks failed. Please fix the issues above.")
        print("\nQuick Start Guide:")
        print("1. Install missing dependencies: uv pip install <package>")
        print("2. Install Playwright browsers: python -m playwright install chromium")
        print("3. Start browser MCP server: uv run .\\browserMCP\\browser_mcp_sse.py")
        print("4. Then start main app: uv run .\\main.py")
    print("=" * 60)
    
    return 0 if all_ok else 1

if __name__ == "__main__":
    sys.exit(main())

