# Voice Agent — Setup Runbook

Real-time AI outbound calling on your own GPUs. Everything below is copy-paste.

```
Twilio (phone)  <->  server.py (FastAPI + Pipecat)
                          |-- STT : faster-whisper  (5090 #2)
                          |-- LLM : vLLM OpenAI API  (5090 #1)
                          |-- TTS : Kokoro           (5090 #3 / 3090)
campaign.py  --> Twilio REST --> dials contacts --> connects to server.py
```

## Prerequisites (one time)
- A Linux box with your NVIDIA GPUs, recent driver + CUDA 12.x.
- Python 3.10+.  `ffmpeg` installed.
- A **Twilio account** (you create this — needs your email + phone verify + a card).
  Trial accounts get free credit and can call *verified* numbers, enough to demo.
- For local testing so Twilio can reach your machine: **ngrok** (`ngrok http 7860`).

## Step 1 — Twilio (the part only you can do)
1. Sign up at https://www.twilio.com/try-twilio
2. In the Console, copy **Account SID** and **Auth Token**.
3. Buy a phone number (Phone Numbers → Buy a number, voice-enabled).
4. (Trial only) verify the number(s) you want to call under Verified Caller IDs.

## Step 2 — Install
```bash
cd voice
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pip install vllm            # heavy; ideally its own env/box with CUDA

# Download Kokoro model files into voice/ (one time):
wget https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files/kokoro-v0_19.onnx
wget https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files/voices.bin
```

## Step 3 — Configure
```bash
cp .env.example .env
# edit .env: paste Twilio creds + number, set PUBLIC_BASE_URL (ngrok URL)
```

## Step 4 — Start the three processes
```bash
# 1) LLM on a 5090 (OpenAI-compatible on :8000)
CUDA_VISIBLE_DEVICES=0 LLM_MODEL=Qwen/Qwen2.5-14B-Instruct bash run_vllm.sh

# 2) Voice server (STT+TTS load here; put them on other GPUs via CUDA_VISIBLE_DEVICES)
CUDA_VISIBLE_DEVICES=1 uvicorn server:app --host 0.0.0.0 --port 7860

# 3) Expose it so Twilio can reach it (local testing)
ngrok http 7860     # put the https URL into PUBLIC_BASE_URL in .env, restart server
```
Point your Twilio number's **Voice webhook** at `${PUBLIC_BASE_URL}/twiml` (POST) —
this makes *inbound* calls work. Outbound uses the same URL via campaign.py.

## Step 5 — Test one call
```bash
# dry run first (no dialing):
python campaign.py sample_contacts.csv --dry-run
# real (dials a verified number on trial):
python campaign.py sample_contacts.csv --max-concurrent 5
```
Call connects → you hear the AI greet → talk to it. That recording is your Upwork demo.

## Tuning / scaling
- **Slow replies?** switch LLM to `meta-llama/Llama-3.1-8B-Instruct`, lower max_tokens.
- **Robotic voice?** swap Kokoro for XTTS-v2 (voice cloning) in `tts_kokoro.py`.
- **More concurrent calls?** run extra vLLM replicas on the other 5090s/3090s (ports
  8001, 8002…) behind a load balancer; run multiple uvicorn workers for STT/TTS.
- **Go to production telephony:** move off Twilio to Telnyx/SIP for better per-minute margin.

## Compliance (do not skip)
- Only dial **consented / opted-in** contacts. Scrub against DNC. Implement the check
  in `campaign.py:should_dial()` before any real campaign.
- Respect calling hours (typically 8am–9pm local).
- Have the agent disclose it's an automated assistant if asked.
- This protects your client's brand, your phone numbers, and you legally.
