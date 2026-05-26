import logging
import os
import tempfile
import threading
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import urlparse
from urllib.request import urlopen

import numpy as np
import soundcard as sc
import soundfile as sf

from linux_voice_assistant.player.base import AudioPlayer
from linux_voice_assistant.player.state import PlayerState


class LibSoundPlayer(AudioPlayer):
    """
    SoundPlayer implementation for Linux Voice Assistant.

    Responsibilities:
    - playback control
    - thread-safe state management
    - volume handling with ducking support
    """

    def __init__(self, device: Optional[str] = None) -> None:
        self._log = logging.getLogger(self.__class__.__name__)
        self._state: PlayerState = PlayerState.IDLE
        self._state_lock = threading.Lock()

        # Volume handling
        self._user_volume: float = 100.0  # 0.0 – 100.0
        self._duck_factor: float = 1.0  # 0.0 – 1.0

        self._device = device
        self._play_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._pause_event = threading.Event()
        self._temp_file: Optional[str] = None

        self._current_source: Optional[str] = None

        # Callback Handling
        self._done_callback: Optional[Callable[[], None]] = None

    # -------- Playback control --------

    def play(
        self,
        url: str,
        done_callback: Optional[Callable[[], None]] = None,
        stop_first: bool = True,
    ) -> None:
        """
        Start playback of a media URL.

        Args:
            url: Media URL or local file path.
            done_callback: Optional callback invoked when playback finishes.
            stop_first: If True, start playback in paused state.
        """
        with self._state_lock:
            self._log.debug("play: current_state=%s", self._state)
            self._done_callback = done_callback
            self._current_source = url
            self._set_state(PlayerState.LOADING)

        self.stop(for_replacement=True)

        with self._state_lock:
            self._done_callback = done_callback
            self._current_source = url
            self._set_state(PlayerState.PAUSED if stop_first else PlayerState.LOADING)

        self._stop_event.clear()
        if stop_first:
            self._pause_event.set()
        else:
            self._pause_event.clear()

        self._play_thread = threading.Thread(target=self._playback_worker, args=(url,), daemon=True)
        self._play_thread.start()

    def pause(self) -> None:
        """Pause playback."""
        with self._state_lock:
            self._pause_event.set()
            self._set_state(PlayerState.PAUSED)

    def resume(self) -> None:
        """Resume playback if paused."""
        self._log.debug("resume() called")
        with self._state_lock:
            self._pause_event.clear()
            self._set_state(PlayerState.PLAYING)

    def stop(self, for_replacement: bool = False) -> None:
        """
        Stop playback.

        If called for track replacement, clears the callback to prevent
        it from being invoked during the transition.
        """
        self._log.debug("stop() called")
        self._stop_event.set()

        current_thread = self._play_thread
        if current_thread and current_thread.is_alive() and threading.current_thread() is not current_thread:
            current_thread.join(timeout=1.0)

        with self._state_lock:
            if for_replacement:
                # Clear callback to prevent invocation during track transition
                self._done_callback = None
            self._set_state(PlayerState.IDLE)

        self._cleanup_temp_file()

    def state(self) -> PlayerState:
        """Return the current player state."""
        with self._state_lock:
            return self._state

    # -------- Volume / Ducking --------

    def set_volume(self, volume: float) -> None:
        """
        Set user volume.

        Args:
            volume: Volume level (0.0–100.0).
        """
        self._log.debug("set_volume(volume=%.2f)", volume)
        with self._state_lock:
            self._user_volume = max(0.0, min(100.0, float(volume)))

    def duck(self, factor: float = 0.5) -> None:
        """
        Reduce volume temporarily by a ducking factor.

        Args:
            factor: Ducking factor (0.0–1.0).
        """
        self._log.debug("duck(factor=%.2f)", factor)
        with self._state_lock:
            self._duck_factor = max(0.0, min(1.0, float(factor)))

    def unduck(self) -> None:
        """Restore volume to the user-defined level."""
        self._log.debug("unduck() called")
        with self._state_lock:
            self._duck_factor = 1.0

    # -------- Internal helpers --------

    def _effective_volume_scalar(self) -> float:
        with self._state_lock:
            effective = (self._user_volume * self._duck_factor) / 100.0
        return max(0.0, min(1.0, effective))

    def _resolve_source(self, source: str) -> str:
        parsed = urlparse(source)
        if parsed.scheme in ("http", "https"):
            suffix = Path(parsed.path).suffix or ".audio"
            with urlopen(source, timeout=30) as response:
                with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp_file:
                    temp_file.write(response.read())
                    self._temp_file = temp_file.name
                    return temp_file.name

        return source

    def _cleanup_temp_file(self) -> None:
        if self._temp_file and os.path.exists(self._temp_file):
            try:
                os.unlink(self._temp_file)
            except OSError:
                pass
        self._temp_file = None

    def _select_speaker(self):
        if self._device is not None:
            return sc.get_speaker(self._device)

        return sc.default_speaker()

    def _playback_worker(self, source: str) -> None:
        callback: Optional[Callable[[], None]] = None

        try:
            path = self._resolve_source(source)
            speaker = self._select_speaker()

            with sf.SoundFile(path) as audio_file:
                with speaker.player(samplerate=audio_file.samplerate, channels=audio_file.channels) as player:
                    with self._state_lock:
                        if self._state != PlayerState.PAUSED:
                            self._set_state(PlayerState.PLAYING)

                    while not self._stop_event.is_set():
                        if self._pause_event.is_set():
                            if self._stop_event.wait(timeout=0.05):
                                break
                            continue

                        chunk = audio_file.read(4096, dtype="float32", always_2d=True)
                        if chunk.size == 0:
                            break

                        volume = self._effective_volume_scalar()
                        if volume != 1.0:
                            chunk = chunk * np.float32(volume)

                        player.play(chunk)

                    callback = self._done_callback if not self._stop_event.is_set() else None

            with self._state_lock:
                self._set_state(PlayerState.IDLE)
                self._done_callback = None
        except Exception:  # pylint: disable=broad-except
            self._log.exception("Playback failed")
            with self._state_lock:
                self._set_state(PlayerState.ERROR)
                self._done_callback = None
        finally:
            self._stop_event.clear()
            self._pause_event.clear()
            self._cleanup_temp_file()

        if callback is not None:
            try:
                callback()
            except RuntimeError:
                pass

    def _set_state(self, new_state: PlayerState) -> None:
        """Update internal player state."""
        self._state = new_state
