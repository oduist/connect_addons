import asyncio
import json
import httpx
import logging
import traceback
import os
from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from aio_odoorpc import AsyncOdooRPC
from elevenlabs import ElevenLabs
from elevenlabs.conversational_ai.conversation import ClientTools, Conversation, ConversationInitiationData
from twilio_audio_interface import TwilioAudioInterface
import uvicorn

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

# Initialize FastAPI app
app = FastAPI()

# Initialize ElevenLabs client
eleven_labs_client = ElevenLabs(api_key=os.getenv("ELEVENLABS_API_KEY"))


# Odoo connection
class OdooConnection:
    odoo = None

    async def login(self):
        try:
            odoo_user = os.getenv('ODOO_USER')
            password = os.getenv('ODOO_PASSWORD')
            url = os.getenv('ODOO_URL')
            db = os.getenv('ODOO_DB')
            logger.info('Connecting to Odoo at %s', url)
            session = httpx.AsyncClient(base_url=url + '/jsonrpc', follow_redirects=True)
            self.odoo = AsyncOdooRPC(database=db, username_or_uid=odoo_user ,
                                password=password, http_client=session)
            logged = await self.odoo.login()
            if not logged:
                logger.error('Cannot login. Check user and password.')
                return False
            logger.info('Connected to Odoo.')
            return True
        except Exception as e:
            if 'Somehow the response id differs from the request id' in str(e):
                logger.error('HTTPS redirection issue, use 308 Permanent Redirect.')
            elif 'FATAL:  database' in str(e):
                logger.error('Database %s does not exist.', db)
            elif 'Expecting value: line 1 column 1 (char 0)' in str(e):
                logger.error('Cannot connect to Odoo, check if it is running.')
            else:
                logger.error('Odoo connect error: %s', e)

    async def get_call_info(self, call_id):
        call_data = await self.odoo.execute_kw(
            model_name='connect.call',
            method='get_call_data_by_id',
            args=call_id,
            kwargs={}
        )
        logger.info('Call data: %s', call_data)
        return call_data


async def odoo_query(params):
    logger.info('Odoo query params: %s', params)
    try:
        odoo_connection = OdooConnection()
        await odoo_connection.login()
        model = params.get('model')
        res_id = params.get('number')
        if not (model or res_id):
            return 'Parameters not set!'
        res = await odoo_connection.odoo.execute_kw(
            model_name=model,
            method='search_read',
            args=[['id', '=', res_id]],
            kwargs={'fields': ['name', 'description', 'date_deadline']}
        )
        if not res:
            return 'Nothing was found'
        else:
            logger.info('Result: %s', res)
            return json.dumps(res[0])
    except Exception as e:
        logger.error('Odoo query error: %s', e)
        return 'Error calling the tool: {}'.format(e)


async def odoo_execute(params):
    logger.info('Odoo execute params: %s', params)
    try:
        odoo_connection = OdooConnection()
        await odoo_connection.login()
        model = params.pop('model', False)
        method = params.get('number', False)
        if not (model or method):
            return 'Required parameters are not set!'
        res = await odoo_connection.odoo.execute_kw(
            model_name=model,
            method=method,
            args=params,
            kwargs={}
        )
        logger.info('Result: %s', res)
        return json.dumps(res)
    except Exception as e:
        logger.error('Odoo execute error: %s', e)
        return 'Error calling the tool: {}'.format(e)

async def transfer_to_extension(params):
    logger.info('Transfer params: %s', params)
    try:
        odoo_connection = OdooConnection()
        await odoo_connection.login()
        res = await odoo_connection.odoo.execute_kw(
            model_name='connect.elevenlabs_agent',
            method='transfer',
            args=params,
            kwargs={}
        )
        logger.info('Result: %s', res)
        return json.dumps(res)
    except Exception as e:
        logger.error('Odoo execute error: %s', e)
        return 'Error calling the tool: {}'.format(e)


client_tools = ClientTools()
client_tools.register('transfer_to_extension', transfer_to_extension, is_async=True)


@app.get("/")
async def root():
    return {"message": "Twilio-ElevenLabs Integration Server"}


@app.api_route("/agent/ping", methods=["GET", "POST"])
async def agent_ping():
    # Test Odoo connection.
    odoo = OdooConnection()
    await odoo.login()
    return True


@app.websocket("/twilio/stream/{agent_id}/{call_id}/{channel_sid}")
async def handle_media_stream(websocket: WebSocket, agent_id: str, call_id: str, channel_sid: str):
    # Set some defaults required by prompt and tools.
    call_info = {
        'partner_id': False,
        'partner_phone': '',
        'call_id': call_id,
        'channel_sid': channel_sid,
        'greeting_name': 'Dear customer', # Default name.
        'system_error_message': '', # Empty
    }
    odoo = OdooConnection()
    try:
        await odoo.login()
        call_info.update(await odoo.get_call_info(call_id))
    except Exception:
        logger.exception('Get call data error:')
        call_info['system_error_message'] = 'Oops! Something went wrong. Please reach out to our support team.'
        call_info['system_error'] = True

    logger.info('Call info: {}'.format(json.dumps(call_info, indent=2)))
    await websocket.accept()
    audio_interface = TwilioAudioInterface(websocket)
    conversation = None

    config = ConversationInitiationData(
        dynamic_variables=call_info,
        conversation_config_override={
            'agent': {'language': call_info.get('partner_language', 'en')}
        }
    )
    try:
        conversation = Conversation(
            client=eleven_labs_client,
            agent_id=agent_id,
            config=config,
            requires_auth=False,
            client_tools=client_tools,
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
