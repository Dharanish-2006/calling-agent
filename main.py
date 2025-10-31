import asyncio
import websockets
import json
import base64
import requests
from pydub import AudioSegment
from io import BytesIO
import csv
import time

EXOTEL_SID = "cmp681"
EXOTEL_TOKEN = "c8b99a122c0a7c86fecabba8da9af43c45a9bab95506252d"
EXOTEL_VIRTUAL_NO = ""
AGENTSTREAM_APPLET_URL = "https://yourserver.com/agentstream_app"
CSV_FILE = "customers.csv"
DELAY_BETWEEN_CALLS = 5
LISTEN_HOST = "0.0.0.0"
LISTEN_PORT = 8765
CRM_ENDPOINT = "https://yourcrm.example.com/api/add_call_log"
VAPI_WS_URL = "wss://api.vapi.ai/realtime"
VAPI_API_KEY = "aac1b6ab-497f-40c5-9fa0-9d0d04e1cbef"

async def process_audio_with_vapi(audio_bytes, call_sid, caller):
    audio_reply_chunks = []
    audio_segment = AudioSegment.from_file(BytesIO(audio_bytes))
    wav_io = BytesIO()
    audio_segment.export(wav_io, format="wav")
    wav_data = wav_io.getvalue()
    async with websockets.connect(VAPI_WS_URL, extra_headers={"Authorization": f"Bearer {VAPI_API_KEY}"}) as ws:
        await ws.send(json.dumps({"type": "start_session"}))
        await ws.send(json.dumps({
            "type": "input_audio",
            "payload": base64.b64encode(wav_data).decode("utf-8")
        }))
        async for msg in ws:
            data = json.loads(msg)
            if data.get("type") == "output_audio":
                chunk = base64.b64decode(data["payload"])
                audio_reply_chunks.append(chunk)
            elif data.get("type") == "summary":
                summary_data = data["payload"]
                crm_payload = {
                    "call_sid": call_sid,
                    "phone": caller,
                    "summary": summary_data.get("summary", ""),
                    "transcript": summary_data.get("transcript", ""),
                    "intent": summary_data.get("intent", ""),
                    "scheduled_date": summary_data.get("scheduled_date", "")
                }
                requests.post(CRM_ENDPOINT, json=crm_payload)
                break
    return audio_reply_chunks

async def handle_exotel_ws(ws, path):
    try:
        async for msg in ws:
            data = json.loads(msg)
            if data.get("event") == "media":
                b64_audio = data["payload"]["audio"]
                audio_bytes = base64.b64decode(b64_audio)
                call_sid = data.get("payload", {}).get("call_sid", "unknown")
                caller = data.get("payload", {}).get("caller", "unknown")
                reply_chunks = await process_audio_with_vapi(audio_bytes, call_sid, caller)
                for chunk in reply_chunks:
                    b64_chunk = base64.b64encode(chunk).decode("utf-8")
                    out_msg = json.dumps({"event": "media", "payload": {"audio": b64_chunk}})
                    await ws.send(out_msg)
            elif data.get("event") == "dtmf":
                digit = data["payload"].get("digit")
                if digit == "1":
                    transfer_msg = json.dumps({"event": "transfer", "payload": {"target": "human_agent"}})
                    await ws.send(transfer_msg)
    except websockets.ConnectionClosed:
        pass

async def run_websocket_server():
    server = await websockets.serve(handle_exotel_ws, LISTEN_HOST, LISTEN_PORT)
    await asyncio.Future()

def make_exotel_call(phone):
    url = f"https://api.exotel.com/v1/Accounts/{EXOTEL_SID}/Calls/connect"
    payload = {
        "From": EXOTEL_VIRTUAL_NO,
        "To": phone,
        "CallerId": EXOTEL_VIRTUAL_NO,
        "Url": AGENTSTREAM_APPLET_URL
    }
    resp = requests.post(url, data=payload, auth=(EXOTEL_SID, EXOTEL_TOKEN))
    return resp.status_code

async def dial_customers():
    with open(CSV_FILE, newline='') as f:
        reader = csv.DictReader(f)
        for row in reader:
            phone = row["Phone"]
            status = make_exotel_call(phone)
            print(f"Called {phone} → {status}")
            await asyncio.sleep(DELAY_BETWEEN_CALLS)

async def main():
    server_task = asyncio.create_task(run_websocket_server())
    dial_task = asyncio.create_task(dial_customers())
    await asyncio.gather(server_task, dial_task)

if __name__ == "__main__":
    asyncio.run(main())
