"""
Pipecat pipeline wiring: Twilio media stream <-> STT <-> LLM <-> TTS.

This is the latency-critical path. Targets:
  - STT partials streaming, endpointing ~500ms silence
  - LLM first-token < 300ms (small model, vLLM, short context)
  - TTS first-audio < 200ms (streaming)

If replies feel slow: shrink the LLM (Llama-3.1-8B), cap max_tokens, and make sure
vLLM is warm. If speech sounds robotic: switch TTS to XTTS-v2 or StyleTTS2.
"""
import os

from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.aggregators.openai_llm_context import OpenAILLMContext
from pipecat.serializers.twilio import TwilioFrameSerializer
from pipecat.transports.network.fastapi_websocket import (
    FastAPIWebsocketTransport,
    FastAPIWebsocketParams,
)
from pipecat.audio.vad.silero import SileroVADAnalyzer

# Services. Whisper STT and OpenAI-compatible LLM ship with Pipecat.
from pipecat.services.whisper.stt import WhisperSTTService
from pipecat.services.openai.llm import OpenAILLMService

from tts_kokoro import KokoroTTSService


async def build_pipeline_runner(websocket, stream_sid, call_sid, system_prompt):
    serializer = TwilioFrameSerializer(stream_sid=stream_sid, call_sid=call_sid)

    transport = FastAPIWebsocketTransport(
        websocket=websocket,
        params=FastAPIWebsocketParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            add_wav_header=False,
            vad_analyzer=SileroVADAnalyzer(),  # detects when caller stops talking
            serializer=serializer,
        ),
    )

    stt = WhisperSTTService(
        model=os.getenv("WHISPER_MODEL", "distil-large-v3"),
        device=os.getenv("WHISPER_DEVICE", "cuda"),
        compute_type=os.getenv("WHISPER_COMPUTE_TYPE", "float16"),
    )

    # Point the OpenAI client at your local vLLM server — no cloud calls.
    llm = OpenAILLMService(
        api_key=os.getenv("LLM_API_KEY", "local"),
        base_url=os.getenv("LLM_BASE_URL", "http://localhost:8000/v1"),
        model=os.getenv("LLM_MODEL", "Qwen/Qwen2.5-14B-Instruct"),
    )

    tts = KokoroTTSService(voice=os.getenv("TTS_VOICE", "af_heart"))

    context = OpenAILLMContext(
        messages=[{"role": "system", "content": system_prompt}],
    )
    context_aggregator = llm.create_context_aggregator(context)

    pipeline = Pipeline([
        transport.input(),
        stt,
        context_aggregator.user(),
        llm,
        tts,
        transport.output(),
        context_aggregator.assistant(),
    ])

    task = PipelineTask(
        pipeline,
        params=PipelineParams(allow_interruptions=True, enable_metrics=True),
    )

    # Greet immediately on connect so there's no dead air.
    @transport.event_handler("on_client_connected")
    async def on_connected(_transport, _client):
        await task.queue_frames([context_aggregator.user().get_context_frame()])

    return PipelineRunner().run and _Runner(task)


class _Runner:
    """Tiny adapter so server.py can `await runner.run()`."""
    def __init__(self, task):
        self._task = task

    async def run(self):
        await PipelineRunner().run(self._task)
