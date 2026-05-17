"""Streamlit helper that embeds the LiveKit JS client as a components.html panel."""
import os
import streamlit.components.v1 as components

API_URL = os.environ.get("API_URL", "http://127.0.0.1:8000")

_HTML_TEMPLATE = """
<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <script src="https://cdn.jsdelivr.net/npm/livekit-client@2.5.5/dist/livekit-client.umd.min.js"></script>
  <style>
    body {{ font-family: system-ui, sans-serif; margin: 0; padding: 0.5rem; }}
    .row {{ display: flex; gap: 0.5rem; align-items: center; }}
    button {{ font-size: 1rem; padding: 0.5rem 1rem; cursor: pointer; }}
    button:disabled {{ opacity: 0.5; cursor: not-allowed; }}
    #status {{ margin-left: 0.5rem; color: #555; font-size: 0.9rem; }}
    #log {{
      margin-top: 0.75rem; padding: 0.5rem; background: #f4f4f4;
      border-radius: 6px; min-height: 80px; max-height: 180px;
      overflow-y: auto; white-space: pre-wrap; font-size: 0.85rem;
    }}
  </style>
</head>
<body>
  <div class="row">
    <button id="connect">🎤 Connect</button>
    <button id="disconnect" disabled>Disconnect</button>
    <span id="status">idle</span>
  </div>
  <div id="log"></div>

  <script>
    const TOKEN_URL = "{api_url}/livekit/token";
    const log = (m) => {{
      const el = document.getElementById("log");
      el.textContent += m + "\\n";
      el.scrollTop = el.scrollHeight;
    }};
    const setStatus = (s) => document.getElementById("status").textContent = s;
    let room = null;

    document.getElementById("connect").onclick = async () => {{
      try {{
        setStatus("fetching token...");
        const res = await fetch(TOKEN_URL, {{
          method: "POST",
          headers: {{ "Content-Type": "application/json" }},
          body: JSON.stringify({{
            identity: "user-" + Math.random().toString(36).slice(2, 8),
            // Unique room per session so stale agent participants from a
            // previous Connect don't prevent LiveKit from dispatching the
            // worker to a "new" room.
            room: "mi-voice-" + Math.random().toString(36).slice(2, 10)
          }}),
        }});
        if (!res.ok) throw new Error("token endpoint returned " + res.status);
        const {{ token, url }} = await res.json();
        log("got token, connecting to " + url);

        room = new LivekitClient.Room({{ adaptiveStream: true, dynacast: true }});
        room.on(LivekitClient.RoomEvent.TrackSubscribed, (track) => {{
          if (track.kind === "audio") {{
            const el = track.attach();
            el.autoplay = true;
            el.playsInline = true;
            el.muted = false;
            el.volume = 1.0;
            document.body.appendChild(el);
            // Force playback in case Chrome's autoplay policy blocked it.
            // The Connect click is a user gesture so play() should succeed.
            el.play().then(() => log("agent audio playing")).catch((e) => log("audio play error: " + e.message));
          }}
        }});
        room.on(LivekitClient.RoomEvent.Disconnected, () => {{
          setStatus("disconnected");
          log("room disconnected");
        }});

        await room.connect(url, token);
        await room.localParticipant.setMicrophoneEnabled(true);
        setStatus("connected — speak now");
        log("mic enabled");
        document.getElementById("connect").disabled = true;
        document.getElementById("disconnect").disabled = false;
      }} catch (err) {{
        setStatus("error");
        log("error: " + err.message);
      }}
    }};

    document.getElementById("disconnect").onclick = async () => {{
      if (room) {{ await room.disconnect(); }}
      document.getElementById("connect").disabled = false;
      document.getElementById("disconnect").disabled = true;
      setStatus("idle");
    }};
  </script>
</body>
</html>
"""


def render_voice_panel(height: int = 320) -> None:
    """Embed the LiveKit voice client in the current Streamlit container."""
    html = _HTML_TEMPLATE.format(api_url=API_URL)
    components.html(html, height=height)
