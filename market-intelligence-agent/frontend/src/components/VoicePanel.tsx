import { useRef, useState } from "react";
import { Room, RoomEvent, type RemoteTrack } from "livekit-client";
import { getLiveKitToken } from "../lib/api";

type VoiceStatus = "idle" | "connecting" | "connected" | "disconnected" | "error";

export function VoicePanel() {
  const [status, setStatus] = useState<VoiceStatus>("idle");
  const [log, setLog] = useState<string[]>([]);
  const roomRef = useRef<Room | null>(null);
  const addLog = (m: string) => setLog((p) => [...p.slice(-20), m]); // keep last 20

  async function connect() {
    try {
      setStatus("connecting");
      const identity = "user-" + Math.random().toString(36).slice(2, 8);
      const room = "mi-voice-" + Math.random().toString(36).slice(2, 10);
      const { token, url } = await getLiveKitToken(identity, room);
      addLog(`connecting to ${url}`);

      const lkRoom = new Room({ adaptiveStream: true, dynacast: true });
      roomRef.current = lkRoom;

      lkRoom.on(RoomEvent.TrackSubscribed, (track: RemoteTrack) => {
        if (track.kind === "audio") {
          const el = track.attach() as HTMLAudioElement;
          el.autoplay = true;
          (el as HTMLMediaElement).muted = false;
          el.volume = 1.0;
          document.body.appendChild(el);
          el
            .play()
            .then(() => addLog("agent audio streaming"))
            .catch((e) => addLog("audio error: " + e.message));
        }
      });

      lkRoom.on(RoomEvent.Disconnected, () => {
        setStatus("disconnected");
        addLog("disconnected from room");
      });

      await lkRoom.connect(url, token);
      await lkRoom.localParticipant.setMicrophoneEnabled(true);
      setStatus("connected");
      addLog("mic enabled — speak now");
    } catch (err) {
      setStatus("error");
      addLog("error: " + (err as Error).message);
    }
  }

  async function disconnect() {
    await roomRef.current?.disconnect();
    roomRef.current = null;
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
