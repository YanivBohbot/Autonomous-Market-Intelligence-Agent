import { useRef, useState } from "react";
import { Room, RoomEvent, type RemoteTrack } from "livekit-client";
import { getLiveKitToken } from "../lib/api";

export function VoicePanel() {
  const [status, setStatus] = useState("idle");
  const [log, setLog] = useState<string[]>([]);
  const roomRef = useRef<Room | null>(null);
  const addLog = (m: string) => setLog((p) => [...p, m]);

  async function connect() {
    try {
      setStatus("fetching token…");
      const identity = "user-" + Math.random().toString(36).slice(2, 8);
      const room = "mi-voice-" + Math.random().toString(36).slice(2, 10);
      const { token, url } = await getLiveKitToken(identity, room);
      addLog(`got token, connecting to ${url}`);

      const lkRoom = new Room({ adaptiveStream: true, dynacast: true });
      roomRef.current = lkRoom;
      lkRoom.on(RoomEvent.TrackSubscribed, (track: RemoteTrack) => {
        if (track.kind === "audio") {
          const el = track.attach() as HTMLAudioElement;
          el.autoplay = true;
          (el as HTMLMediaElement).muted = false;
          el.volume = 1.0;
          document.body.appendChild(el);
          el.play().then(() => addLog("agent audio playing")).catch((e) => addLog("audio error: " + e.message));
        }
      });
      lkRoom.on(RoomEvent.Disconnected, () => { setStatus("disconnected"); addLog("room disconnected"); });

      await lkRoom.connect(url, token);
      await lkRoom.localParticipant.setMicrophoneEnabled(true);
      setStatus("connected — speak now");
      addLog("mic enabled");
    } catch (err) {
      setStatus("error");
      addLog("error: " + (err as Error).message);
    }
  }

  async function disconnect() {
    await roomRef.current?.disconnect();
    roomRef.current = null;
    setStatus("idle");
  }

  const connected = status.startsWith("connected");

  return (
    <div className="border-t border-terminal-border bg-terminal-panel p-3">
      <div className="mb-2 flex items-center gap-2">
        <button
          onClick={connect}
          disabled={connected}
          className="rounded bg-terminal-accent px-3 py-1 text-xs font-semibold text-terminal-bg disabled:opacity-50"
        >
          🎤 Connect
        </button>
        <button
          onClick={disconnect}
          disabled={!connected}
          className="rounded border border-terminal-border px-3 py-1 text-xs text-terminal-text disabled:opacity-50"
        >
          Disconnect
        </button>
        <span className="font-mono text-xs text-terminal-muted">{status}</span>
      </div>
      <div className="max-h-24 overflow-y-auto rounded bg-terminal-bg p-2 font-mono text-[11px] text-terminal-muted">
        {log.map((l, i) => <div key={i}>{l}</div>)}
      </div>
    </div>
  );
}
