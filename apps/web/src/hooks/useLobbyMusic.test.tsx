import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { useLobbyMusic } from "./useLobbyMusic";

class FakeAudio {
  static instances: FakeAudio[] = [];
  static nextPlayError: Error | null = null;
  currentTime = 0;
  loop = false;
  muted = false;
  paused = true;
  preload = "";
  src: string;
  volume = 1;
  play = vi.fn(async () => {
    if (FakeAudio.nextPlayError) {
      const error = FakeAudio.nextPlayError;
      FakeAudio.nextPlayError = null;
      throw error;
    }
    this.paused = false;
  });
  pause = vi.fn(() => { this.paused = true; });

  constructor(src: string) {
    this.src = src;
    FakeAudio.instances.push(this);
  }
}

beforeEach(() => {
  FakeAudio.instances = [];
  FakeAudio.nextPlayError = null;
  vi.stubGlobal("Audio", FakeAudio);
  localStorage.clear();
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

test("starts at low volume only while the connected lobby is active", async () => {
  const { result, rerender } = renderHook(({ active }) => useLobbyMusic(active), {
    initialProps: { active: false },
  });

  expect(FakeAudio.instances).toHaveLength(0);
  rerender({ active: true });

  await waitFor(() => expect(result.current.status).toBe("playing"));
  expect(FakeAudio.instances).toHaveLength(1);
  expect(FakeAudio.instances[0].volume).toBe(0.14);
  expect(FakeAudio.instances[0].loop).toBe(true);
});

test("offers a user-gesture retry when browser autoplay is blocked", async () => {
  FakeAudio.nextPlayError = new DOMException("Autoplay blocked", "NotAllowedError");

  const { result } = renderHook(() => useLobbyMusic(true));
  await waitFor(() => expect(result.current.status).toBe("blocked"));
  await act(async () => result.current.toggle());
  await waitFor(() => expect(result.current.status).toBe("playing"));

  expect(FakeAudio.instances[0].play).toHaveBeenCalledTimes(2);
});

test("remembers mute preference and resumes after unmuting", async () => {
  localStorage.setItem("rolecall-lobby-music-muted:v1", "true");
  const { result } = renderHook(() => useLobbyMusic(true));

  await waitFor(() => expect(result.current.status).toBe("muted"));
  expect(FakeAudio.instances[0].play).not.toHaveBeenCalled();
  await act(async () => result.current.toggle());
  await waitFor(() => expect(result.current.status).toBe("playing"));
  expect(localStorage.getItem("rolecall-lobby-music-muted:v1")).toBe("false");
});

test("fades and stops before the meeting leaves the lobby", async () => {
  vi.useFakeTimers();
  const { result, rerender } = renderHook(({ active }) => useLobbyMusic(active), {
    initialProps: { active: true },
  });
  await act(async () => Promise.resolve());
  expect(result.current.status).toBe("playing");

  rerender({ active: false });
  act(() => vi.advanceTimersByTime(600));

  expect(FakeAudio.instances[0].pause).toHaveBeenCalled();
  expect(FakeAudio.instances[0].currentTime).toBe(0);
  expect(result.current.status).toBe("idle");
});
