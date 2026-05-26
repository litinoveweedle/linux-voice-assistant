import logging
from importlib.util import find_spec
from typing import Callable, List, Optional, Union

from .player.base import AudioPlayer
from .player.libsound import LibSoundPlayer
from .player.state import PlayerState


_VALID_BACKENDS = ("auto", "mpv", "soundcard")


def _is_mpv_available() -> bool:
    """Return True if python-mpv appears importable in this environment."""
    return find_spec("mpv") is not None


def _create_mpv_player(device: str | None) -> AudioPlayer:
    from .player.libmpv import LibMpvPlayer

    return LibMpvPlayer(device=device)


class MediaPlayer:
    """
    Linux Voice Assistant SoundPlayer implementation.

    This class provides the SoundPlayer interface expected by LVA and
    delegates playback logic to either LibMpvPlayer or LibSoundPlayer.
    """

    def __init__(self, device: str | None = None, backend: str = "auto") -> None:
        self._log = logging.getLogger(self.__class__.__name__)
        self._requested_backend = backend.lower().strip()
        self._resolved_backend = "unknown"
        self._player = self._build_player(device=device, backend=backend)
        self._done_callback: Optional[Callable[[], None]] = None
        self._playlist: List[str] = []

        self._log.debug(
            "MediaPlayer initialized (device=%s, requested_backend=%s, resolved_backend=%s)",
            device,
            self._requested_backend,
            self._resolved_backend,
        )

    def _build_player(self, device: str | None, backend: str) -> AudioPlayer:
        backend_normalized = backend.lower().strip()
        if backend_normalized not in _VALID_BACKENDS:
            raise ValueError(f"Unsupported audio backend '{backend}'. Valid values: {', '.join(_VALID_BACKENDS)}")

        if backend_normalized == "soundcard":
            self._resolved_backend = "soundcard"
            self._log.info("Audio backend selected: soundcard")
            return LibSoundPlayer(device=device)

        if backend_normalized == "mpv":
            if not _is_mpv_available():
                raise RuntimeError("Audio backend 'mpv' requested, but python-mpv is not installed")
            self._log.info("Audio backend selected: mpv")
            try:
                self._resolved_backend = "mpv"
                return _create_mpv_player(device=device)
            except Exception as err:  # pylint: disable=broad-except
                raise RuntimeError("Audio backend 'mpv' requested, but libmpv is not available") from err

        # backend=auto
        if _is_mpv_available():
            try:
                player = _create_mpv_player(device=device)
                self._resolved_backend = "mpv"
                self._log.info("Audio backend auto-selected: mpv")
                return player
            except Exception:  # pylint: disable=broad-except
                self._log.info("Audio backend auto-fallback to soundcard (mpv unavailable at runtime)")

        self._resolved_backend = "soundcard"
        self._log.info("Audio backend auto-selected: soundcard (mpv unavailable)")
        return LibSoundPlayer(device=device)

    @property
    def requested_backend(self) -> str:
        return self._requested_backend

    @property
    def resolved_backend(self) -> str:
        return self._resolved_backend

    def play(
        self,
        url: Union[str, List[str]],
        done_callback: Optional[Callable[[], None]] = None,
        stop_first: bool = False,
    ) -> None:
        """
        Play a media URL.

        Args:
            url: Media URL or list of URLs for sequential playback.
            done_callback: Optional callback invoked when playback finishes.
            stop_first: Kept for API compatibility.
        """
        # Handle single URL vs list
        if isinstance(url, str):
            urls = [url]
        else:
            urls = list(url)  # Copy the list

        if not urls:
            self._log.warning("play() called with empty URL list")
            return

        # Track is changing - stop if needed
        if self._done_callback is not None:
            if self._player.state() != PlayerState.IDLE:
                self._log.debug("Stopping active playback before starting new media")
                self._player.stop(for_replacement=True)
            self._done_callback = None

        self._log.info("Playing %d URL(s): %s", len(urls), urls[0])

        # Store playlist and callback
        self._playlist = urls
        self._done_callback = done_callback

        # Start playing first URL
        next_url = self._playlist.pop(0)
        self._player.play(next_url, done_callback=self._on_track_finished, stop_first=stop_first)

    def _on_track_finished(self) -> None:
        """Called when a track finishes - plays next or invokes done callback."""
        if self._playlist:
            # More tracks to play
            next_url = self._playlist.pop(0)
            self._log.debug("Playing next URL from playlist: %s", next_url)
            self._player.play(next_url, done_callback=self._on_track_finished, stop_first=False)
        else:
            # Playlist finished
            callback = self._done_callback
            self._done_callback = None

            if callback:
                self._log.debug("Playlist finished, invoking done_callback")
                try:
                    callback()
                except Exception as e:
                    self._log.exception("Error in done_callback: %s", e)

    def pause(self) -> None:
        """Pause playback."""
        self._log.debug("pause() called")
        self._player.pause()

    def resume(self) -> None:
        """Resume playback."""
        self._log.debug("resume() called")
        self._player.resume()

    def stop(self) -> None:
        """Stop playback and invoke the done callback if present."""
        self._log.debug("stop() called")

        self._player.stop()

        if self._done_callback:
            self._log.debug("Invoking done_callback due to stop()")
            try:
                self._done_callback()
            finally:
                self._done_callback = None

    @property
    def is_playing(self) -> bool:
        """Check if the player is currently playing or paused."""
        state = self._player.state()
        return state in (PlayerState.PLAYING, PlayerState.PAUSED, PlayerState.LOADING)

    def set_volume(self, volume: float) -> None:
        """
        Set playback volume.

        Args:
            volume: Volume in percent (0.0-100.0).
        """
        self._log.debug("set_volume(volume=%.2f)", volume)
        self._player.set_volume(volume)

    def duck(self, factor: float = 0.5) -> None:
        """
        Temporarily reduce volume.

        Args:
            factor: Volume multiplier (0.0-1.0).
        """
        self._log.debug("duck(factor=%.2f)", factor)
        self._player.duck(factor)

    def unduck(self) -> None:
        """Restore volume after ducking."""
        self._log.debug("unduck() called")
        self._player.unduck()