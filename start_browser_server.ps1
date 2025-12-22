# PowerShell script to start the browser MCP server
Write-Host "Starting Browser MCP Server..." -ForegroundColor Green
Write-Host "Keep this window open while using the application." -ForegroundColor Yellow
Write-Host ""

# Change to project directory
Set-Location $PSScriptRoot

# Start the server
uv run .\browserMCP\browser_mcp_sse.py

