# How to Start Browser MCP Server

## Quick Start

**IMPORTANT:** The browser MCP server must be running **before** you start the main application.

### Step 1: Verify Setup (Recommended)

First, check if everything is set up correctly:

```powershell
cd D:\Himanshu\EAG-V2\eag-v2-s14
uv run python check_setup.py
```

This will verify:
- ✅ All dependencies are installed
- ✅ Playwright Chromium is installed
- ✅ Browser MCP server is running

### Step 2: Start Browser MCP Server

**Option A: Using the startup script (Easiest)**

```powershell
.\start_browser_server.ps1
```

**Option B: Manual start**

Open a **new terminal/PowerShell window** and run:

```powershell
cd D:\Himanshu\EAG-V2\eag-v2-s14
uv run .\browserMCP\browser_mcp_sse.py
```

You should see:
```
INFO:     Started server process [xxxxx]
INFO:     Waiting for application startup.
INFO:     Application startup complete.
INFO:     Uvicorn running on http://127.0.0.1:8100
```

**Keep this terminal open** - the server must stay running.

### Step 2: Start Main Application

In your **original terminal**, run:

```powershell
uv run .\main.py
```

The application will now connect to the browser MCP server and load browser tools.

## Verification

When you start the main application, you should see:
- ✅ Browser MCP server is running at http://localhost:8100/sse
- ✅ Loaded X tools: open_tab, search_google, input_text_by_index, ...

If you see warnings about missing browser tools, the server isn't running or didn't connect properly.

## Troubleshooting

### Port Already in Use
If you get `[WinError 10048]` (port already in use):
```powershell
# Find what's using port 8100
netstat -ano | findstr :8100

# Kill the process (replace PID with the number from above)
taskkill /PID <PID> /F
```

### Server Not Connecting
1. Make sure the browser MCP server terminal is still running
2. Check if port 8100 is listening: `netstat -ano | findstr :8100`
3. Restart both the browser server and main application

## Note

The browser MCP server provides these tools:
- `open_tab(url)` - Open a new browser tab
- `search_google(query)` - Search Google
- `go_to_url(url)` - Navigate to a URL
- `click_element_by_index(index)` - Click an element
- `input_text_by_index(index, text)` - Type text into an input
- And more...

Without the browser server running, these tools will not be available and you'll get `NameError` exceptions.

