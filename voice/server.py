"""
Real-time AI voice agent server.

Twilio calls this server; audio streams in over a WebSocket (Twilio Media Streams).
The Pipecat pipeline does:  caller audio -> Whisper (STT) -> local LLM -> Kokoro (TTS) -> caller.

All inference runs on YOUR GPUs:
  - STT  : faster-whisper (in-process, CUDA)
  - LLM  : vLLM OpenAI-compatible server you run separately (see run_vllm.sh)
  - TTS  : Kokoro (in-process)

Run:  uvicorn server:app --host 0.0.0.0 --port 7860
Then point Twilio's number Voice webhook at  {PUBLIC_BASE_URL}/twiml
"""
import os
import json
from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, Request
from fastapi.responses import PlainTextResponse
from twilio.twiml.voice_response import VoiceResponse, Connect

from pipeline import build_pipeline_runner

load_dotenv()

app = FastAPI()

# System prompt = the agent's script/persona. Per-campaign scripts override this.
DEFAULT_SYSTEM_PROMPT = os.getenv(
    "AGENT_SYSTEM_PROMPT",
    "You are Ava, a friendly assistant calling on behalf of the client's business. "
    "Keep replies short and natural, like real phone speech. Confirm the appointment, "
    "answer brief questions, and offer to reschedule if needed. Never claim to be human "
    "if asked directly; say you're an automated assistant. End politely.",
)


@app.get("/health")
async def health():
    return {"ok": True}


@app.post("/twiml")
async def twiml(request: Request):
    """Twilio hits this when a call connects (inbound or outbound-originated).
    We return TwiML that opens a bidirectional Media Stream to /ws."""
    base = os.environ["PUBLIC_BASE_URL"].replace("https://", "").replace("http://", "")
    resp = VoiceResponse()
    connect = Connect()
    connect.stream(url=f"wss://{base}/ws")
    resp.append(connect)
    return PlainTextResponse(str(resp), media_type="application/xml")


@app.websocket("/ws")
async def ws(websocket: WebSocket):
    await websocket.accept()
    # First two Twilio messages establish the stream; grab the streamSid/callSid.
    start = json.loads(await websocket.receive_text())
    call = json.loads(await websocket.receive_text())
    stream_sid = call["start"]["streamSid"]
    call_sid = call["start"]["callSid"]

    runner = await build_pipeline_runner(
        websocket=websocket,
        stream_sid=stream_sid,
        call_sid=call_sid,
        system_prompt=DEFAULT_SYSTEM_PROMPT,
    )
    await runner.run()
