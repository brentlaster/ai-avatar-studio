# AI Avatar Studio v2 (API-Based)

Create professional talking avatar videos using ElevenLabs (voice cloning) + D-ID (face animation).

## How It Works

```
Source Video (.mp4)
       │
       ├──► [ffmpeg] ──► Voice Sample (.wav) ──► [ElevenLabs] ──► Cloned Voice ID
       │                                                                │
       ├──► [ffmpeg] ──► Avatar Frame (.png)         Script Text ──► [ElevenLabs TTS]
       │                        │                                       │
       │                        │                                 Speech Audio (.mp3)
       │                        │                                       │
       │                        └───────────► [D-ID Talks API] ◄───────┘
       │                                            │
       └────────────────────────────────► Avatar Video (.mp4)
```

## Quick Start

```bash
cd ai-avatar-studio-v2
./setup.sh
```

Add your API keys (edit `config.py` or set environment variables):

```bash
export ELEVENLABS_API_KEY=your-key-here
export DID_API_KEY=your-key-here
```

Launch:

```bash
source venv/bin/activate
python app.py
```

## Get API Keys

1. **ElevenLabs** — https://elevenlabs.io → Profile → API Key (free tier: 10k chars/month)
2. **D-ID** — https://studio.d-id.com → API tab → Generate Key (free trial: ~20 sec of video)

## v2 vs v1

| | v1 (Open Source) | v2 (API-Based) |
|---|---|---|
| Quality | Low (uncanny valley) | High (production-ready) |
| Setup | Complex (~3 GB models) | Simple (3 pip packages) |
| Dependencies | 20+ packages, patching | requests, gradio, ffmpeg |
| GPU needed | Yes (slow on CPU) | No (runs on server) |
| Cost | Free | Pay per use |
| Offline | Yes | No (needs internet) |

## Project Structure

```
ai-avatar-studio-v2/
├── app.py           # Gradio web UI
├── pipeline.py      # 5-step API pipeline
├── config.py        # API keys and settings
├── setup.sh         # One-time setup
├── requirements.txt # Python dependencies
├── outputs/         # Generated videos
└── temp/            # Intermediate files
```
