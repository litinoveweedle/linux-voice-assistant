import time
import logging

from linux_voice_assistant.media_player import MediaPlayer


"""Smoke test for low-level media playback."""

logging.basicConfig(level=logging.INFO)

player = MediaPlayer()

print("Loading media...")
player.play("https://icecast.radiofrance.fr/fip-midfi.mp3")

time.sleep(5)

print("Pausing...")
player.pause()
time.sleep(2)

print("Resuming...")
player.resume()
time.sleep(5)

print("Stopping...")
player.stop()

time.sleep(2)
print("Done.")
