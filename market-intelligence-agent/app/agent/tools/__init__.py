from app.agent.tools.emails import send_email_tool
from app.agent.tools.mcp_clients.mcp_client import crm_tool

TOOLS = [send_email_tool, crm_tool]

__all__ = ["TOOLS", "send_email_tool", "crm_tool"]
