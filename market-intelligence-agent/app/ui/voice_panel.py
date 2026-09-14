"""Streamlit helper that connects the browser to a GPT-Live voice session
over WebRTC, proxying the SDP offer through our own backend so the OpenAI
API key never reaches the browser.

The WebRTC data channel receives every Live server event by default
(OpenAI's `allowed_server_events` defaults to allow-all unless the session
config restricts it, which we don't) — so live captions are read straight
off that data channel, no backend relay needed."""
import os
import streamlit.components.v1 as components

API_URL = os.environ.get("API_URL", "http://127.0.0.1:8000")

_HTML_TEMPLATE = """
<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <style>
    body {{ font-family: system-ui, sans-serif; margin: 0; padding: 0.5rem; direction: auto; }}
    .row {{ display: flex; gap: 0.5rem; align-items: center; }}
    button {{ font-size: 1rem; padding: 0.5rem 1rem; cursor: pointer; }}
    button:disabled {{ opacity: 0.5; cursor: not-allowed; }}
    #status {{ margin-left: 0.5rem; color: #555; font-size: 0.9rem; }}
    #captions {{
      margin-top: 0.75rem; padding: 0.5rem; background: #eef6ff;
      border-radius: 6px; min-height: 3.2rem; font-size: 1rem;
      unicode-bidi: plaintext;
    }}
    #captions .you {{ color: #0b5; font-weight: 600; }}
    #captions .line {{ margin-bottom: 0.25rem; }}
    #log {{
      margin-top: 0.5rem; padding: 0.5rem; background: #f4f4f4;
      border-radius: 6px; min-height: 60px; max-height: 140px;
      overflow-y: auto; white-space: pre-wrap; font-size: 0.8rem; color: #666;
    }}
  </style>
</head>
<body>
  <div class="row">
    <button id="connect">🎤 Connect</button>
    <button id="disconnect" disabled>Disconnect</button>
    <span id="status">idle</span>
  </div>
  <div id="captions"></div>
  <div id="log"></div>

  <script>
    const SESSION_URL = "{api_url}/gptlive/session";
    const log = (m) => {{
      const el = document.getElementById("log");
      el.textContent += m + "\\n";
      el.scrollTop = el.scrollHeight;
    }};
    const setStatus = (s) => document.getElementById("status").textContent = s;
    let pc = null;
    let dc = null;

    // --- Live caption for what the mic heard from you. The agent's reply
    // is deliberately NOT shown here — it's pushed by the backend into
    // app.py's main chat (via /voice/{{thread_id}}/transcript) as one
    // finished block once the turn is done, not as it streams. ---
    const captionsEl = document.getElementById("captions");
    let youBuffer = "";

    const renderCaptions = () => {{
      captionsEl.innerHTML =
        (youBuffer ? '<div class="line"><span class="you">You:</span> ' + youBuffer + '</div>' : '');
    }};

    const handleDataChannelEvent = (raw) => {{
      let event;
      try {{ event = JSON.parse(raw); }} catch (e) {{ return; }}
      switch (event.type) {{
        case "session.input_transcript.delta":
          youBuffer += event.delta;
          renderCaptions();
          break;
        case "session.delegation.created":
          // The user's turn just ended — push it to the log and clear.
          if (youBuffer) log("You: " + youBuffer);
          youBuffer = "";
          renderCaptions();
          break;
        case "session.closed":
          log("session closed: " + event.reason);
          break;
        case "error":
          log("live error: " + JSON.stringify(event.error));
          break;
      }}
    }};

    document.getElementById("connect").onclick = async () => {{
      try {{
        setStatus("requesting mic...");
        const stream = await navigator.mediaDevices.getUserMedia({{ audio: true }});

        pc = new RTCPeerConnection();
        const audioEl = document.createElement("audio");
        audioEl.autoplay = true;
        audioEl.playsInline = true;
        pc.ontrack = (e) => {{
          audioEl.srcObject = e.streams[0];
          document.body.appendChild(audioEl);
          audioEl.play().then(() => log("agent audio playing")).catch((err) => log("audio play error: " + err.message));
        }};
        stream.getTracks().forEach((track) => pc.addTrack(track, stream));

        dc = pc.createDataChannel("oai-events");
        dc.onmessage = (e) => handleDataChannelEvent(e.data);
        dc.onopen = () => log("data channel open — captions live");

        const offer = await pc.createOffer();
        await pc.setLocalDescription(offer);

        setStatus("creating session...");
        const res = await fetch(SESSION_URL, {{
          method: "POST",
          headers: {{ "Content-Type": "application/json" }},
          body: JSON.stringify({{ sdp: offer.sdp, thread_id: "{thread_id}" }}),
        }});
        if (!res.ok) throw new Error("session endpoint returned " + res.status);
        const {{ session_id, sdp }} = await res.json();
        log("session " + session_id + " created, connecting");

        await pc.setRemoteDescription({{ type: "answer", sdp: sdp }});
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
      if (pc) {{ pc.close(); pc = null; }}
      dc = null;
      youBuffer = "";
      agentBuffer = "";
      renderCaptions();
      document.getElementById("connect").disabled = false;
      document.getElementById("disconnect").disabled = true;
      setStatus("idle");
    }};
  </script>
</body>
</html>
"""


def render_voice_panel(thread_id: str, height: int = 380) -> None:
    """Embed the GPT-Live WebRTC voice client in the current Streamlit container.

    `thread_id` is sent to `/gptlive/session` so the backend worker uses it
    for the LangGraph checkpointer *and* for the transcript store that
    `app.py` polls to mirror the voice conversation into the main chat.
    """
    html = _HTML_TEMPLATE.format(api_url=API_URL, thread_id=thread_id)
    components.html(html, height=height)
