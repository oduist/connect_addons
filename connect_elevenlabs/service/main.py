import json
import traceback
import os
from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from elevenlabs import ElevenLabs
from elevenlabs.conversational_ai.conversation import Conversation, ConversationInitiationData
from twilio_audio_interface import TwilioAudioInterface
import uvicorn

# Load environment variables
load_dotenv()

# Initialize FastAPI app
app = FastAPI()

# Initialize ElevenLabs client
eleven_labs_client = ElevenLabs(api_key=os.getenv("ELEVENLABS_API_KEY"))


@app.get("/")
async def root():
    return {"message": "Twilio-ElevenLabs Integration Server"}


@app.api_route("/agent/ping", methods=["GET", "POST"])
async def agent_ping():
    return True


@app.websocket("/twilio/stream/{call_sid}/{agent_id}")
async def handle_media_stream(websocket: WebSocket, call_sid: str, agent_id: str):
    await websocket.accept()
    audio_interface = TwilioAudioInterface(websocket)
    conversation = None

    config = ConversationInitiationData(dynamic_variables={"call_sid": call_sid})

    try:
        conversation = Conversation(
            client=eleven_labs_client,
            agent_id=agent_id,
            config=config,
            requires_auth=False,
            audio_interface=audio_interface,
            callback_agent_response=lambda text: print(f"Agent said: {text}"),
            callback_user_transcript=lambda text: print(f"User said: {text}"),
        )

        conversation.start_session()
        print("Conversation session started")

        async for message in websocket.iter_text():
            if not message:
                continue

            try:
                data = json.loads(message)
                await audio_interface.handle_twilio_message(data)
            except Exception as e:
                print(f"Error processing message: {str(e)}")
                traceback.print_exc()

    except WebSocketDisconnect:
        print("WebSocket disconnected")
    finally:
        if conversation:
            print("Ending conversation session...")
            conversation.end_session()
            conversation.wait_for_session_end()


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=48000)
