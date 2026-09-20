import { useRef, useState } from "react";
import { API_BASE } from "../lib/api";

type VoiceStatus = "idle" | "connecting" | "connected" | "disconnected" | "error";

interface VoicePanelProps {
  threadId: string;
}

export function VoicePanel({ threadId }: VoicePanelProps) {
  const [status, setStatus] = useState<VoiceStatus>("idle");
  const [log, setLog] = useState<string[]>([]);
  const pcRef = useRef<RTCPeerConnection | null>(null);
  const dcRef = useRef<RTCDataChannel | null>(null);
  const audioElRef = useRef<HTMLAudioElement | null>(null);
  const addLog = (m: string) => setLog((p) => [...p.slice(-20), m]); // keep last 20

  async function connect() {
    try {
      setStatus("connecting");
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });

      const pc = new RTCPeerConnection();
      pcRef.current = pc;

      const audioEl = document.createElement("audio");
      audioEl.autoplay = true;
      audioElRef.current = audioEl;
      pc.ontrack = (e) => {
        audioEl.srcObject = e.streams[0];
        document.body.appendChild(audioEl);
        audioEl
          .play()
          .then(() => addLog("agent audio playing"))
          .catch((err) => addLog("audio play error: " + err.message));
      };

      stream.getTracks().forEach((track) => pc.addTrack(track, stream));

      const dc = pc.createDataChannel("oai-events");
      dcRef.current = dc;
      dc.onmessage = (e) => handleDataChannelEvent(e.data);
      dc.onopen = () => addLog("data channel open — captions live");

      pc.onconnectionstatechange = () => {
        if (pc.connectionState === "disconnected" || pc.connectionState === "failed") {
          setStatus("disconnected");
          addLog("connection " + pc.connectionState);
        }
      };

      const offer = await pc.createOffer();
      await pc.setLocalDescription(offer);

      const res = await fetch(`${API_BASE}/gptlive/session`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ sdp: offer.sdp, thread_id: threadId }),
      });
      if (!res.ok) throw new Error(`session endpoint returned ${res.status}`);
      const { session_id, sdp } = await res.json();
      addLog(`session ${session_id} created, connecting`);

      await pc.setRemoteDescription({ type: "answer", sdp });
      setStatus("connected");
      addLog("mic enabled — speak now");
    } catch (err) {
      setStatus("error");
      addLog("error: " + (err as Error).message);
    }
  }

  function handleDataChannelEvent(raw: string) {
    let event: { type?: string; reason?: string; error?: unknown };
    try {
      event = JSON.parse(raw);
    } catch {
      return;
    }
    switch (event.type) {
      case "session.closed":
        addLog("session closed: " + event.reason);
        break;
      case "error":
        addLog("live error: " + JSON.stringify(event.error));
        break;
    }
  }

  async function disconnect() {
    pcRef.current?.close();
    pcRef.current = null;
    dcRef.current = null;
    audioElRef.current?.remove();
    audioElRef.current = null;
    setStatus("idle");
    addLog("disconnected");
  }

  const isConnected = status === "connected";
  const isConnecting = status === "connecting";

  const statusConfig: Record<VoiceStatus, { label: string; color: string }> = {
    idle: { label: "idle", color: "text-terminal-muted" },
    connecting: { label: "connecting…", color: "text-terminal-warn" },
    connected: { label: "live", color: "text-terminal-accent" },
    disconnected: { label: "disconnected", color: "text-terminal-muted" },
    error: { label: "error", color: "text-terminal-danger" },
  };

  const { label, color } = statusConfig[status];

  return (
    <div className="border-t border-terminal-border bg-terminal-panel">
      <div className="flex items-center gap-3 px-4 py-2.5">
        {/* Status indicator */}
        <div className="flex items-center gap-1.5">
          <span
            className={`h-1.5 w-1.5 rounded-full ${
              isConnected ? "bg-terminal-accent animate-pulse" : "bg-terminal-border"
            }`}
          />
          <span className={`font-mono text-[10px] uppercase tracking-wider ${color}`}>
            voice {label}
          </span>
        </div>

        {/* Controls */}
        <div className="flex items-center gap-2 ml-auto">
          <button
            onClick={connect}
            disabled={isConnected || isConnecting}
            className="flex items-center gap-1.5 rounded-lg border border-terminal-border bg-terminal-bg px-3 py-1.5 font-mono text-xs text-terminal-text transition-all hover:border-terminal-accent hover:text-terminal-accent disabled:cursor-not-allowed disabled:opacity-40"
          >
            <span>🎤</span>
            {isConnecting ? "Connecting…" : "Connect"}
          </button>
          <button
            onClick={disconnect}
            disabled={!isConnected}
            className="rounded-lg border border-terminal-border px-3 py-1.5 font-mono text-xs text-terminal-muted transition-all hover:border-terminal-danger hover:text-terminal-danger disabled:cursor-not-allowed disabled:opacity-40"
          >
            Disconnect
          </button>
        </div>
      </div>

      {/* Log */}
      {log.length > 0 && (
        <div className="border-t border-terminal-border/50 max-h-20 overflow-y-auto px-4 py-2">
          {log.map((l, i) => (
            <div key={i} className="font-mono text-[10px] text-terminal-muted leading-5">
              <span className="text-terminal-border mr-2">›</span>
              {l}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
