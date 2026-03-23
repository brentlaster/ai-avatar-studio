"""
AI Avatar Studio v2 - Configuration
Add your API keys here or set them as environment variables.
"""

import os

# ---------------------------------------------------------------------------
# ElevenLabs (Voice Cloning + Text-to-Speech)
# Sign up: https://elevenlabs.io  →  Profile  →  API Key
# Free tier: 10,000 characters/month
# ---------------------------------------------------------------------------
ELEVENLABS_API_KEY = os.environ.get("ELEVENLABS_API_KEY", "your-elevenlabs-api-key-here")

# ---------------------------------------------------------------------------
# D-ID (Talking Head Video Generation)
# Sign up: https://studio.d-id.com  →  API tab  →  Generate API Key
# Free trial: ~20 seconds of video
# ---------------------------------------------------------------------------
DID_API_KEY = os.environ.get("DID_API_KEY", "your-d-id-api-key-here")

# ---------------------------------------------------------------------------
# General settings
# ---------------------------------------------------------------------------
OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "outputs")
TEMP_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "temp")

os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(TEMP_DIR, exist_ok=True)
