import os
import json
import httpx
from pydantic import BaseModel, Field
from typing import Optional
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
JIRA_URL   = os.environ.get("JIRA_URL", "").rstrip("/")
JIRA_EMAIL = os.environ.get("JIRA_EMAIL", "")
JIRA_TOKEN = os.environ.get("JIRA_TOKEN", "")

mcp = FastMCP(
    "jira_mcp",
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=False
    )
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def jira_get(path: str, params: dict = {}) -> dict:
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.get(
            f"{JIRA_URL}/rest/api/3{path}",
            auth=(JIRA_EMAIL, JIRA_TOKEN),
            headers={"Accept": "application/json"},
            params=params,
        )
        r.raise_for_status()
        return r.json()


def get_text(node) -> str:
    """Extract plain text from Jira's ADF rich text format."""
    if not node: return ""
    if isinstance(node, str): return node
    if node.get("type") == "text": return node.get("text", "")
    return " ".join(get_text(c) for c in node.get("content", [])).strip()


def handle_error(e: Exception) -> str:
    if isinstance(e, httpx.HTTPStatusError):
        return f"Error: Jira API returned {e.response.status_code}. Check your credentials and project key."
    if isinstance(e, httpx.TimeoutException):
        return "Error: Request timed out. Please try again."
    return f"Error: {str(e)}"

# ---------------------------------------------------------------------------
# Input models
# ---------------------------------------------------------------------------

class SearchInput(BaseModel):
    search: Optional[str] = Field(default=None, description="Optional text to search for in issue names/descriptions.")

# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

@mcp.tool(
    name="jira_get_issues",
    annotations={"readOnlyHint": True, "destructiveHint": False}
)
async def jira_get_issues(params: SearchInput) -> str:
    """Get Jira issues from project DP. Optionally filter by search text.

    Args:
        params: SearchInput with optional search string.

    Returns:
        JSON list of issues with key, name, and description.
    """
    try:
        jql = f'project = DP AND text ~ "{params.search}" ORDER BY updated DESC' \
              if params.search else "project = DP ORDER BY updated DESC"
        data = await jira_get("/search/jql", {"jql": jql, "maxResults": 25, "fields": "summary,description"})
        issues = [
            {
                "key": i["key"],
                "name": i["fields"].get("summary", ""),
                "description": get_text(i["fields"].get("description")),
            }
            for i in data.get("issues", [])
        ]
        return json.dumps(issues, indent=2)
    except Exception as e:
        return handle_error(e)

# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8080))
    app = mcp.streamable_http_app()
    uvicorn.run(app, host="0.0.0.0", port=port, forwarded_allow_ips="*")