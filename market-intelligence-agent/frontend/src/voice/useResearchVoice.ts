import { useCallback, useEffect, useRef, useState } from "react";

import {
  createResearchVoiceSession,
  getResearchVoiceState,
  submitResearchVoiceDecision,
} from "./voiceApi";
import type {
  VoiceActivityEvent,
  VoiceDecision,
  VoiceDecisionResult,
  VoicePendingApproval,
  VoicePhase,
} from "./types";

const POLL_INTERVAL_MS = 500;
const ICE_TIMEOUT_MS = 10_000;
const CLOSE_TIMEOUT_MS = 15_000;

async function waitForIceGathering(peer: RTCPeerConnection): Promise<void> {
  if (peer.iceGatheringState === "complete") return;
  await new Promise<void>((resolve, reject) => {
    const onChange = () => {
      if (peer.iceGatheringState === "complete") {
        clearTimeout(timeout);
        peer.removeEventListener("icegatheringstatechange", onChange);
        resolve();
      }
    };
    const timeout = window.setTimeout(() => {
      peer.removeEventListener("icegatheringstatechange", onChange);
      reject(new Error("Voice connection timed out"));
    }, ICE_TIMEOUT_MS);
    peer.addEventListener("icegatheringstatechange", onChange);
  });
}

function microphoneError(error: unknown): string {
  if (error instanceof DOMException && error.name === "NotAllowedError") {
    return "Microphone access is required";
  }
  return error instanceof Error ? error.message : "Voice connection failed";
}

export function useResearchVoice(threadId: string, enabled: boolean) {
  const [phase, setPhase] = useState<VoicePhase>("disconnected");
  const [active, setActive] = useState(false);
  const [events, setEvents] = useState<VoiceActivityEvent[]>([]);
  const [pending, setPending] = useState<VoicePendingApproval | null>(null);
  const [error, setError] = useState<string | null>(null);

  const peerRef = useRef<RTCPeerConnection | null>(null);
  const channelRef = useRef<RTCDataChannel | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const pollRef = useRef<ReturnType<typeof window.setInterval> | null>(null);
  const forceCloseRef = useRef<ReturnType<typeof window.setTimeout> | null>(null);
  const afterRef = useRef(0);
  const activeRef = useRef(false);
  const cleanedRef = useRef(true);
  const closeSentRef = useRef(false);
  const finalizingRef = useRef(false);
  const pollInFlightRef = useRef(false);

  const cleanup = useCallback(
    (
      nextPhase: VoicePhase = "disconnected",
      nextError?: string,
      sendClose = false,
    ) => {
      if (cleanedRef.current) return;
      cleanedRef.current = true;

      const channel = channelRef.current;
      if (
        sendClose &&
        channel?.readyState === "open" &&
        !closeSentRef.current
      ) {
        channel.send(JSON.stringify({ type: "session.close" }));
        closeSentRef.current = true;
      }
      if (pollRef.current !== null) window.clearInterval(pollRef.current);
      if (forceCloseRef.current !== null) window.clearTimeout(forceCloseRef.current);
      pollRef.current = null;
      forceCloseRef.current = null;
      pollInFlightRef.current = false;

      streamRef.current?.getTracks().forEach((track) => track.stop());
      streamRef.current = null;
      channel?.close();
      channelRef.current = null;
      peerRef.current?.close();
      peerRef.current = null;

      const audio = audioRef.current;
      if (audio) {
        audio.pause();
        audio.srcObject = null;
        audio.remove();
      }
      audioRef.current = null;
      finalizingRef.current = false;
      activeRef.current = false;
      setActive(false);
      setPhase(nextPhase);
      if (nextError !== undefined) setError(nextError);
    },
    [],
  );

  const pollState = useCallback(async () => {
    if (!activeRef.current || pollInFlightRef.current) return;
    pollInFlightRef.current = true;
    try {
      const state = await getResearchVoiceState(threadId, afterRef.current);
      afterRef.current = Math.max(afterRef.current, state.sequence);
      if (state.events.length) {
        setEvents((current) => {
          const bySequence = new Map(current.map((item) => [item.sequence, item]));
          state.events.forEach((item) => bySequence.set(item.sequence, item));
          return [...bySequence.values()].sort((a, b) => a.sequence - b.sequence);
        });
      }
      setPending(state.pending);
      setPhase(state.phase);
      if (state.error) setError(state.error);
    } catch (pollError) {
      setError(
        pollError instanceof Error ? pollError.message : "Voice state failed",
      );
    } finally {
      pollInFlightRef.current = false;
    }
  }, [threadId]);

  const startPolling = useCallback(() => {
    if (pollRef.current !== null) return;
    pollRef.current = window.setInterval(() => {
      void pollState();
    }, POLL_INTERVAL_MS);
  }, [pollState]);

  const start = useCallback(async () => {
    if (!enabled || activeRef.current) return;
    cleanedRef.current = false;
    closeSentRef.current = false;
    finalizingRef.current = false;
    afterRef.current = 0;
    setEvents([]);
    setPending(null);
    setError(null);
    setPhase("connecting");
    activeRef.current = true;
    setActive(true);

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;
      const peer = new RTCPeerConnection();
      peerRef.current = peer;

      const audio = document.createElement("audio");
      audio.autoplay = true;
      audioRef.current = audio;
      peer.ontrack = (event) => {
        audio.srcObject = event.streams[0];
        if (!audio.isConnected) document.body.appendChild(audio);
        void audio.play().catch(() => {
          setError("Audio playback failed");
        });
      };

      const channel = peer.createDataChannel("oai-events");
      channelRef.current = channel;
      channel.onmessage = (event) => {
        let message: { type?: string };
        try {
          message = JSON.parse(String(event.data));
        } catch {
          return;
        }
        if (message.type === "session.started") {
          setPhase("listening");
          startPolling();
        } else if (message.type === "session.closed") {
          cleanup("disconnected");
        } else if (message.type === "error") {
          cleanup("error", "Voice connection failed");
        }
      };
      channel.onclose = () => {
        if (activeRef.current && !finalizingRef.current) {
          cleanup("error", "Voice session disconnected");
        }
      };

      peer.onconnectionstatechange = () => {
        if (
          peer.connectionState === "failed" ||
          peer.connectionState === "disconnected"
        ) {
          cleanup("error", "Voice session disconnected");
        }
      };

      stream.getTracks().forEach((track) => peer.addTrack(track, stream));
      const offer = await peer.createOffer();
      await peer.setLocalDescription(offer);
      await waitForIceGathering(peer);
      const localSdp = peer.localDescription?.sdp;
      if (!localSdp) throw new Error("Voice offer is missing SDP");
      const session = await createResearchVoiceSession(threadId, localSdp);
      await peer.setRemoteDescription({ type: "answer", sdp: session.sdp });
    } catch (startError) {
      const message = microphoneError(startError);
      cleanup("error", message);
    }
  }, [cleanup, enabled, startPolling, threadId]);

  const end = useCallback(() => {
    if (!activeRef.current || finalizingRef.current) return;
    finalizingRef.current = true;
    setPhase("disconnected");
    const channel = channelRef.current;
    if (channel?.readyState === "open" && !closeSentRef.current) {
      channel.send(JSON.stringify({ type: "session.close" }));
      closeSentRef.current = true;
    }
    forceCloseRef.current = window.setTimeout(() => {
      cleanup("disconnected");
    }, CLOSE_TIMEOUT_MS);
  }, [cleanup]);

  const submitDecision = useCallback(
    async (
      interruptId: string,
      decisions: VoiceDecision[],
    ): Promise<VoiceDecisionResult> => {
      const result = await submitResearchVoiceDecision(
        threadId,
        interruptId,
        decisions,
      );
      setPending(null);
      return result;
    },
    [threadId],
  );

  useEffect(() => {
    if (!enabled && activeRef.current) {
      cleanup("disconnected", undefined, true);
    }
  }, [cleanup, enabled]);

  useEffect(
    () => () => {
      cleanup("disconnected", undefined, true);
    },
    [cleanup, threadId],
  );

  return {
    phase,
    active,
    events,
    pending,
    error,
    start,
    end,
    submitDecision,
  };
}
