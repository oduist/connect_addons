import asyncio
from typing import Callable
import queue
import threading
import base64
from elevenlabs.conversational_ai.conversation import AudioInterface


class TwilioAudioInterface(AudioInterface):
    def __init__(self, websocket):
        self.websocket = websocket
        self.output_queue = queue.Queue()
        self.should_stop = threading.Event()
        self.stream_sid = None
        self.input_callback = None
        self.output_thread = None

    def start(self, input_callback: Callable[[bytes], None]):
        self.input_callback = input_callback
        self.output_thread = threading.Thread(target=self._output_thread)
        self.output_thread.start()

    def stop(self):
        self.should_stop.set()
        if self.output_thread:
            self.output_thread.join(timeout=5.0)
        self.stream_sid = None

    def output(self, audio: bytes):
        self.output_queue.put(audio)

    def interrupt(self):
        try:
            while True:
                _ = self.output_queue.get(block=False)
        except queue.Empty:
            pass
        asyncio.run(self._send_clear_message_to_twilio())

    async def handle_twilio_message(self, data):
        try:
            if data["event"] == "start":
                self.stream_sid = data["start"]["streamSid"]
                print(f"Started stream with stream_sid: {self.stream_sid}")
                print("---data: ", data)
            if data["event"] == "media":
                audio_data = base64.b64decode(data["media"]["payload"])
                if self.input_callback:
                    self.input_callback(audio_data)
        except Exception as e:
            print(f"Error in input_callback: {e}")

    def _output_thread(self):
        while not self.should_stop.is_set():
            asyncio.run(self._send_audio_to_twilio())

    async def _send_audio_to_twilio(self):
        try:
            audio = self.output_queue.get(timeout=0.2)
            audio_payload = base64.b64encode(audio).decode("utf-8")
            audio_delta = {
                "event": "media",
                "streamSid": self.stream_sid,
                "media": {"payload": audio_payload},
            }
            await self.websocket.send_json(audio_delta)
        except queue.Empty:
            pass
        except Exception as e:
            print(f"Error sending audio: {e}")

    async def _send_clear_message_to_twilio(self):
        try:
            clear_message = {"event": "clear", "streamSid": self.stream_sid}
            await self.websocket.send_json(clear_message)
        except Exception as e:
            print(f"Error sending clear message to Twilio: {e}")
