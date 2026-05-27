# AgentCore Browser SDK Surface

Captured: 2026-05-27  
Package: `bedrock-agentcore==1.11.0`  
Import path: `from bedrock_agentcore.tools.browser_client import BrowserClient`

## `__init__` signature

```
(self, region: str, integration_source: Optional[str] = None) -> None
```

## Public methods and attributes

```
['create_browser', 'delete_browser', 'generate_live_view_url', 'generate_ws_headers',
 'get_browser', 'get_session', 'identifier', 'list_browsers', 'list_sessions',
 'release_control', 'session_id', 'start', 'stop', 'take_control', 'update_stream']
```

## Notes for Task 2 (`session_manager.py`)

- Constructor takes `region: str` (required) and `integration_source: Optional[str]`.
- `start` / `stop` manage the browser lifecycle.
- `generate_ws_headers` is the key method for obtaining WebSocket auth headers
  (needed to proxy browser sessions to the agent's Playwright client).
- `session_id` and `identifier` are instance attributes that identify the live session.
- `get_session` / `list_sessions` support session-level introspection.
- `take_control` / `release_control` support HITL-style hand-off.
- `generate_live_view_url` produces a URL for a human to observe the browser in real time.
- `update_stream` and `list_browsers` / `get_browser` / `create_browser` / `delete_browser`
  are management-plane helpers.
