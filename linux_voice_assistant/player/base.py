from abc import ABC, abstractmethod
from typing import Callable, Optional

from linux_voice_assistant.player.state import PlayerState


class AudioPlayer(ABC):

    @abstractmethod
    def play(
        self,
        url: str,
        done_callback: Optional[Callable[[], None]] = None,
        stop_first: bool = False,
    ) -> None:
        pass

    @abstractmethod
    def pause(self) -> None:
        pass

    @abstractmethod
    def resume(self) -> None:
        pass

    @abstractmethod
    def stop(self, for_replacement: bool = False) -> None:
        pass

    @abstractmethod
    def set_volume(self, volume: float) -> None:
        pass

    @abstractmethod
    def duck(self, factor: float = 0.5) -> None:
        pass

    @abstractmethod
    def unduck(self) -> None:
        pass

    @abstractmethod
    def state(self) -> PlayerState:
        pass
