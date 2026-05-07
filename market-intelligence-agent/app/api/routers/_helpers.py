def get_action_description(last_msg) -> str:
    action_desc = last_msg.content
    if not action_desc and hasattr(last_msg, "tool_calls") and last_msg.tool_calls:
        tc = last_msg.tool_calls[0]
        action_desc = f"Exécuter : {tc['name']} ({tc['args']})"
    return action_desc
