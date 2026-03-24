"""
AI Avatar Studio v2 - Configuration
Add your API keys here or set them as environment variables.
Keys can also be set at runtime via the Gradio UI.
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


def set_api_key(name: str, value: str):
    """Update an API key at runtime (called from the Gradio UI)."""
    import config
    if name == "ELEVENLABS_API_KEY":
        config.ELEVENLABS_API_KEY = value
    elif name == "DID_API_KEY":
        config.DID_API_KEY = value

# ---------------------------------------------------------------------------
# General settings
# ---------------------------------------------------------------------------
OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "outputs")
TEMP_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "temp")

os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(TEMP_DIR, exist_ok=True)
