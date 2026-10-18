"""Black-box check of a running demo deployment (local or public).

    uv run python deploy/demo/smoke.py --base-url https://localhost \
        --user demo --password '...' --insecure

Prints one PASS/FAIL line per check; exits 0 only if every check passes.
"""

import argparse
import sys
import time

import httpx

SPA_PATHS = ["/research", "/briefing", "/clients", "/reports", "/data", "/clients/1", "/reports/1"]
API_PATHS = ["/data/clients", "/conversations"]


def _auth_required(client: httpx.Client, auth) -> str | None:
    r = client.get("/health")
    return None if r.status_code == 401 else f"expected 401 without auth, got {r.status_code}"


def _auth_accepted(client: httpx.Client, auth) -> str | None:
    r = client.get("/health", auth=auth)
    if r.status_code != 200:
        return f"expected 200, got {r.status_code}"
    return None if r.json().get("status") == "ok" else f"unexpected body {r.text[:100]}"


def _spa_routes(client: httpx.Client, auth) -> str | None:
    for path in SPA_PATHS:
        r = client.get(path, auth=auth)
        ctype = r.headers.get("content-type", "")
        if r.status_code != 200 or not ctype.startswith("text/html") or '<div id="root">' not in r.text:
            return f"{path}: status={r.status_code} content-type={ctype!r}"
    return None


def _api_routes(client: httpx.Client, auth) -> str | None:
    for path in API_PATHS:
        r = client.get(path, auth=auth)
        ctype = r.headers.get("content-type", "")
        if r.status_code != 200 or not ctype.startswith("application/json"):
            return f"{path}: status={r.status_code} content-type={ctype!r}"
    return None


def _stream_is_incremental(client: httpx.Client, auth) -> str | None:
    body = {"query": "What is the current price of MSFT?", "thread_id": f"smoke_{int(time.time())}"}
    arrivals: list[float] = []
    saw_done = False
    with client.stream("POST", "/stream", json=body, auth=auth) as r:
        if r.status_code != 200:
            return f"status {r.status_code}"
        for chunk in r.iter_text():
            if not chunk:
                continue
            if "event: done" in chunk:
                saw_done = True
                break
            now = time.monotonic()
            if not arrivals or now - arrivals[-1] >= 0.05:
                arrivals.append(now)
    if not saw_done:
        return "stream ended without an 'event: done' line"
    if len(arrivals) < 3:
        return f"only {len(arrivals)} distinct chunk arrivals before done (response buffered?)"
    return None


def _voice_origin_allowed(client: httpx.Client, auth, base_url: str) -> str | None:
    body = {"sdp": "v=0 invalid", "thread_id": f"desk_smoke_{int(time.time())}", "surface": "research"}
    r = client.post("/gptlive/session", json=body, auth=auth, headers={"Origin": base_url})
    return "origin rejected (403): check VOICE_ALLOWED_ORIGINS" if r.status_code == 403 else None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--user", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--insecure", action="store_true", help="accept a self-signed certificate")
    args = parser.parse_args()

    base_url = args.base_url.rstrip("/")
    auth = (args.user, args.password)
    checks = [
        ("auth_required", lambda c: _auth_required(c, auth)),
        ("auth_accepted", lambda c: _auth_accepted(c, auth)),
        ("spa_routes", lambda c: _spa_routes(c, auth)),
        ("api_routes", lambda c: _api_routes(c, auth)),
        ("stream_is_incremental", lambda c: _stream_is_incremental(c, auth)),
        ("voice_origin_allowed", lambda c: _voice_origin_allowed(c, auth, base_url)),
    ]

    failed = 0
    with httpx.Client(base_url=base_url, verify=not args.insecure, timeout=120) as client:
        for name, check in checks:
            try:
                error = check(client)
            except Exception as exc:  # connection refused, timeout, bad JSON...
                error = f"{type(exc).__name__}: {exc}"
            if error:
                failed += 1
                print(f"FAIL {name}: {error}")
            else:
                print(f"PASS {name}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
