import { act, cleanup as rtlCleanup, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useResearchVoice } from "./useResearchVoice";

class FakeTrack {
  stopped = false;
  stop() {
    this.stopped = true;
  }
}

class FakeStream {
  track = new FakeTrack();
  getTracks() {
    return [this.track] as unknown as MediaStreamTrack[];
  }
}

class FakeDataChannel {
  readyState: RTCDataChannelState = "open";
  sent: string[] = [];
  closed = false;
  onmessage: ((event: MessageEvent) => void) | null = null;
  onopen: (() => void) | null = null;
  onclose: (() => void) | null = null;

  send(value: string) {
    this.sent.push(value);
  }
  close() {
    this.closed = true;
    this.readyState = "closed";
  }
  emit(payload: object) {
    this.onmessage?.({ data: JSON.stringify(payload) } as MessageEvent);
  }
}

class FakePeerConnection {
  static initialIceState: RTCIceGatheringState = "complete";
  actions: string[] = [];
  channel = new FakeDataChannel();
  connectionState: RTCPeerConnectionState = "new";
  iceGatheringState = FakePeerConnection.initialIceState;
  localDescription: RTCSessionDescriptionInit | null = null;
  remoteDescription: RTCSessionDescriptionInit | null = null;
  ontrack: ((event: RTCTrackEvent) => void) | null = null;
  onconnectionstatechange: (() => void) | null = null;
  closed = false;
  private iceListeners = new Set<() => void>();

  addTrack() {
    this.actions.push("track");
  }
  createDataChannel() {
    this.actions.push("data-channel");
    return this.channel as unknown as RTCDataChannel;
  }
  async createOffer() {
    this.actions.push("offer");
    return { type: "offer" as const, sdp: "offer-sdp" };
  }
  async setLocalDescription(description: RTCSessionDescriptionInit) {
    this.localDescription = description;
  }
  async setRemoteDescription(description: RTCSessionDescriptionInit) {
    this.remoteDescription = description;
  }
  addEventListener(type: string, listener: () => void) {
    if (type === "icegatheringstatechange") this.iceListeners.add(listener);
  }
  removeEventListener(type: string, listener: () => void) {
    if (type === "icegatheringstatechange") this.iceListeners.delete(listener);
  }
  completeIce() {
    this.iceGatheringState = "complete";
    this.iceListeners.forEach((listener) => listener());
  }
  failConnection() {
    this.connectionState = "failed";
    this.onconnectionstatechange?.();
  }
  close() {
    this.closed = true;
    this.connectionState = "closed";
  }
}

function jsonResponse(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: vi.fn().mockResolvedValue(body),
    text: vi.fn().mockResolvedValue(JSON.stringify(body)),
  } as unknown as Response;
}

describe("useResearchVoice", () => {
  let stream: FakeStream;
  let peers: FakePeerConnection[];
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    stream = new FakeStream();
    peers = [];
    fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal(
      "RTCPeerConnection",
      class extends FakePeerConnection {
        constructor() {
          super();
          peers.push(this);
        }
      },
    );
    Object.defineProperty(navigator, "mediaDevices", {
      configurable: true,
      value: { getUserMedia: vi.fn().mockResolvedValue(stream) },
    });
    vi.spyOn(HTMLMediaElement.prototype, "play").mockResolvedValue();
    vi.spyOn(HTMLMediaElement.prototype, "pause").mockImplementation(() => undefined);
  });

  afterEach(() => {
    rtlCleanup();
    FakePeerConnection.initialIceState = "complete";
    vi.useRealTimers();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("keeps text available when microphone permission is denied", async () => {
    Object.defineProperty(navigator, "mediaDevices", {
      configurable: true,
      value: {
        getUserMedia: vi.fn().mockRejectedValue(new DOMException("denied", "NotAllowedError")),
      },
    });
    const { result } = renderHook(() => useResearchVoice("thread-1", true));

    await act(async () => result.current.start());

    expect(result.current.active).toBe(false);
    expect(result.current.phase).toBe("error");
    expect(result.current.error).toBe("Microphone access is required");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("creates the data channel before the offer and waits for session.started", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse({ session_id: "session-1", sdp: "answer-sdp" }),
    );
    const { result } = renderHook(() => useResearchVoice("thread-1", true));

    await act(async () => result.current.start());

    expect(peers[0].actions.indexOf("data-channel")).toBeLessThan(
      peers[0].actions.indexOf("offer"),
    );
    const [, request] = fetchMock.mock.calls[0];
    expect(JSON.parse(request.body)).toEqual({
      sdp: "offer-sdp",
      thread_id: "thread-1",
      surface: "research",
    });
    expect(result.current.phase).toBe("connecting");
    act(() => peers[0].channel.emit({ type: "session.started" }));
    expect(result.current.phase).toBe("listening");
  });

  it("waits for ICE gathering to complete before posting the offer", async () => {
    FakePeerConnection.initialIceState = "gathering";
    fetchMock.mockResolvedValueOnce(
      jsonResponse({ session_id: "session-1", sdp: "answer-sdp" }),
    );
    const { result } = renderHook(() => useResearchVoice("thread-1", true));

    let startPromise!: Promise<void>;
    act(() => {
      startPromise = result.current.start();
    });
    await waitFor(() => expect(peers).toHaveLength(1));
    expect(fetchMock).not.toHaveBeenCalled();

    act(() => peers[0].completeIce());
    await act(async () => startPromise);

    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("polls incremental state using the last sequence", async () => {
    vi.useFakeTimers();
    fetchMock
      .mockResolvedValueOnce(jsonResponse({ session_id: "session-1", sdp: "answer-sdp" }))
      .mockResolvedValueOnce(
        jsonResponse({
          phase: "analyzing",
          sequence: 4,
          events: [
            {
              sequence: 4,
              run_id: "run-1",
              kind: "specialist_started",
              name: "rag_agent",
              tool_call_id: null,
              duration_ms: null,
              message: null,
            },
          ],
          pending: null,
          error: null,
        }),
      );
    const { result } = renderHook(() => useResearchVoice("thread-1", true));
    await act(async () => result.current.start());
    act(() => peers[0].channel.emit({ type: "session.started" }));

    await act(async () => vi.advanceTimersByTimeAsync(500));

    expect(fetchMock.mock.calls[1][0]).toBe("/voice/thread-1/state?after=0");
    expect(result.current.phase).toBe("analyzing");
    expect(result.current.events).toHaveLength(1);
    expect(result.current.events[0].name).toBe("rag_agent");
  });

  it("surfaces a server 409 and cleans up the microphone", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse({ detail: "Another turn is active for this thread." }, 409),
    );
    const { result } = renderHook(() => useResearchVoice("thread-1", true));

    await act(async () => result.current.start());

    expect(result.current.active).toBe(false);
    expect(result.current.error).toBe("Another turn is active for this thread.");
    expect(stream.track.stopped).toBe(true);
    expect(peers[0].closed).toBe(true);
  });

  it("keeps media alive after End until session.closed, then cleans up once", async () => {
    vi.useFakeTimers();
    fetchMock.mockResolvedValueOnce(
      jsonResponse({ session_id: "session-1", sdp: "answer-sdp" }),
    );
    const { result, unmount } = renderHook(() => useResearchVoice("thread-1", true));
    await act(async () => result.current.start());

    act(() => result.current.end());

    expect(peers[0].channel.sent).toEqual([JSON.stringify({ type: "session.close" })]);
    expect(stream.track.stopped).toBe(false);
    expect(result.current.active).toBe(true);

    act(() => peers[0].channel.emit({ type: "session.closed" }));
    expect(stream.track.stopped).toBe(true);
    expect(peers[0].channel.closed).toBe(true);
    expect(peers[0].closed).toBe(true);
    expect(result.current.active).toBe(false);

    unmount();
    expect(peers[0].channel.sent).toHaveLength(1);
  });

  it("forces cleanup after 15 seconds when session.closed never arrives", async () => {
    vi.useFakeTimers();
    fetchMock.mockResolvedValueOnce(
      jsonResponse({ session_id: "session-1", sdp: "answer-sdp" }),
    );
    const { result } = renderHook(() => useResearchVoice("thread-1", true));
    await act(async () => result.current.start());

    act(() => result.current.end());
    await act(async () => vi.advanceTimersByTimeAsync(15_000));

    expect(result.current.active).toBe(false);
    expect(stream.track.stopped).toBe(true);
  });

  it("cleans up on connection loss and unmount", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse({ session_id: "session-1", sdp: "answer-sdp" }),
    );
    const { result, unmount } = renderHook(() => useResearchVoice("thread-1", true));
    await act(async () => result.current.start());

    act(() => peers[0].failConnection());

    expect(result.current.error).toBe("Voice session disconnected");
    expect(result.current.active).toBe(false);
    expect(stream.track.stopped).toBe(true);
    unmount();
    expect(peers[0].channel.closed).toBe(true);
  });

  it("accumulates input transcript deltas into liveCaption and clears on delegation", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ session_id: "s1", sdp: "answer-sdp" }));
    const { result } = renderHook(() => useResearchVoice("thread-1", true));
    await act(async () => result.current.start());

    act(() => peers[0].channel.emit({ type: "session.input_transcript.delta", delta: "Which clients " }));
    act(() => peers[0].channel.emit({ type: "session.input_transcript.delta", delta: "are concentrated?" }));
    expect(result.current.liveCaption).toBe("Which clients are concentrated?");

    act(() => peers[0].channel.emit({ type: "session.delegation.created" }));
    expect(result.current.liveCaption).toBe("");
  });

  it("ignores empty deltas", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ session_id: "s1", sdp: "answer-sdp" }));
    const { result } = renderHook(() => useResearchVoice("thread-1", true));
    await act(async () => result.current.start());

    act(() => peers[0].channel.emit({ type: "session.input_transcript.delta", delta: "" }));
    act(() => peers[0].channel.emit({ type: "session.input_transcript.delta" }));
    expect(result.current.liveCaption).toBe("");
  });

  it("clears caption on cleanup", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ session_id: "s1", sdp: "answer-sdp" }));
    const { result } = renderHook(() => useResearchVoice("thread-1", true));
    await act(async () => result.current.start());
    act(() => peers[0].channel.emit({ type: "session.input_transcript.delta", delta: "half a sent" }));

    act(() => peers[0].channel.emit({ type: "session.closed" }));
    expect(result.current.liveCaption).toBe("");
  });
});
