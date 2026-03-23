"""
AI Avatar Studio v2 - Hybrid Pipeline
Uses ElevenLabs for voice cloning/TTS.
Video generation via D-ID (API, metered) or SadTalker (Docker, unlimited free).
"""

import os
import time
import json
import base64
import shutil
import subprocess
import requests
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional

from config import (
    ELEVENLABS_API_KEY,
    DID_API_KEY,
    OUTPUT_DIR,
    TEMP_DIR,
)

# Docker image name for the SadTalker container
SADTALKER_IMAGE = "ai-avatar-studio-sadtalker"


@dataclass
class AvatarConfig:
    """Settings for the avatar generation pipeline."""
    # ElevenLabs voice settings
    voice_model: str = "eleven_multilingual_v2"
    voice_stability: float = 0.20       # lower = more expressive (0.0-1.0)
    voice_similarity: float = 0.75      # how close to the original voice (0.0-1.0)
    voice_style: float = 0.65           # style exaggeration - adds emotion (0.0-1.0)
    voice_speaker_boost: bool = True    # enhances clarity and presence

    # Video backend: "did" (API) or "sadtalker" (local Docker, free)
    video_backend: str = "sadtalker"

    # D-ID settings (only used when video_backend="did")
    expression: str = "neutral"

    # SadTalker settings (only used when video_backend="sadtalker")
    sadtalker_enhancer: str = "gfpgan"   # "gfpgan" or "none"
    sadtalker_still: bool = False        # False = allow head motion for natural look
    sadtalker_preprocess: str = "full"   # "full" keeps whole frame for natural movement
    sadtalker_size: int = 512            # 512 for more facial detail
    sadtalker_expression_scale: float = 1.5  # expression intensity multiplier (default 1.0)
    sadtalker_pose_style: int = 0            # head movement pattern (0-45)


# ===========================================================================
# Step 1: Extract audio from video (for voice sample)
# ===========================================================================

def extract_audio_from_video(video_path: str, output_path: Optional[str] = None) -> str:
    """Extract audio from a video file using ffmpeg."""
    video_path = Path(video_path)
    if output_path is None:
        output_path = os.path.join(TEMP_DIR, f"{video_path.stem}_voice_sample.wav")

    cmd = [
        "ffmpeg", "-y",
        "-i", str(video_path),
        "-vn", "-acodec", "pcm_s16le",
        "-ar", "22050", "-ac", "1",
        output_path,
    ]

    print("[1/5] Extracting audio from video ...")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg failed:\n{result.stderr}")

    print(f"      Audio saved to {output_path}")
    return output_path


# ===========================================================================
# Step 2: Extract a still frame for the avatar image
# ===========================================================================

def extract_frame_from_video(
    video_path: str, timestamp: float = 1.0, output_path: Optional[str] = None
) -> str:
    """Grab a single frame from the video."""
    video_path = Path(video_path)
    if output_path is None:
        output_path = os.path.join(TEMP_DIR, f"{video_path.stem}_avatar.png")

    cmd = [
        "ffmpeg", "-y",
        "-ss", str(timestamp),
        "-i", str(video_path),
        "-frames:v", "1", "-q:v", "2",
        output_path,
    ]

    print(f"[2/5] Extracting avatar frame at t={timestamp}s ...")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"Frame extraction failed:\n{result.stderr}")

    print(f"      Frame saved to {output_path}")
    return output_path


def get_video_duration(video_path: str) -> float:
    """Get the duration of a video in seconds using ffprobe."""
    cmd = [
        "ffprobe", "-v", "quiet",
        "-show_entries", "format=duration",
        "-of", "csv=p=0",
        str(video_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        return 10.0
    try:
        return float(result.stdout.strip())
    except ValueError:
        return 10.0


def extract_preview_frames(video_path: str, num_frames: int = 6) -> list:
    """
    Extract multiple candidate frames evenly spaced through the video.
    Returns a list of (timestamp, image_path) tuples for preview selection.
    """
    video_path_obj = Path(video_path)
    duration = get_video_duration(video_path)

    start = 0.5
    end = max(duration - 0.5, 1.0)
    if num_frames == 1:
        timestamps = [start]
    else:
        step = (end - start) / (num_frames - 1)
        timestamps = [round(start + i * step, 2) for i in range(num_frames)]

    frames = []
    for ts in timestamps:
        out_path = os.path.join(TEMP_DIR, f"{video_path_obj.stem}_preview_{ts:.2f}s.png")
        cmd = [
            "ffmpeg", "-y",
            "-ss", str(ts),
            "-i", str(video_path),
            "-frames:v", "1", "-q:v", "2",
            out_path,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0 and os.path.exists(out_path):
            frames.append((ts, out_path))

    return frames


# ===========================================================================
# Step 3: Clone voice OR use a built-in voice
# ===========================================================================

def get_builtin_voices() -> list:
    """
    Fetch available voices from ElevenLabs.
    Returns a list of dicts with 'voice_id', 'name', and 'category'.
    """
    _check_key("ELEVENLABS_API_KEY", ELEVENLABS_API_KEY)

    url = "https://api.elevenlabs.io/v1/voices"
    headers = {"xi-api-key": ELEVENLABS_API_KEY}
    resp = requests.get(url, headers=headers)

    if resp.status_code != 200:
        raise RuntimeError(f"Failed to fetch voices ({resp.status_code}):\n{resp.text}")

    voices = resp.json().get("voices", [])
    return [
        {
            "voice_id": v["voice_id"],
            "name": v["name"],
            "category": v.get("category", "unknown"),
        }
        for v in voices
    ]


def clone_voice(voice_sample_path: str, voice_name: str = "My Avatar Voice") -> str:
    """
    Upload a voice sample to ElevenLabs and create a cloned voice.
    Returns the voice_id for use in text-to-speech.
    Requires a paid ElevenLabs subscription.
    """
    _check_key("ELEVENLABS_API_KEY", ELEVENLABS_API_KEY)

    print(f"[3/5] Cloning voice with ElevenLabs ...")

    url = "https://api.elevenlabs.io/v1/voices/add"
    headers = {"xi-api-key": ELEVENLABS_API_KEY}

    with open(voice_sample_path, "rb") as f:
        files = [("files", (Path(voice_sample_path).name, f, "audio/wav"))]
        data = {
            "name": voice_name,
            "description": "Voice cloned by AI Avatar Studio",
        }
        resp = requests.post(url, headers=headers, data=data, files=files)

    if resp.status_code != 200:
        raise RuntimeError(
            f"ElevenLabs voice clone failed ({resp.status_code}):\n{resp.text}"
        )

    voice_id = resp.json()["voice_id"]
    print(f"      Voice cloned! ID: {voice_id}")
    return voice_id


# ===========================================================================
# Step 4: Generate speech from script using cloned voice
# ===========================================================================

def generate_speech(
    script_text: str,
    voice_id: str,
    config: AvatarConfig = AvatarConfig(),
    output_path: Optional[str] = None,
) -> str:
    """
    Generate speech audio from text using a cloned ElevenLabs voice.
    Returns path to the generated audio file.
    """
    _check_key("ELEVENLABS_API_KEY", ELEVENLABS_API_KEY)

    if output_path is None:
        output_path = os.path.join(TEMP_DIR, "cloned_speech.mp3")

    print(f"[4/5] Generating speech ...")
    print(f"      Script: \"{script_text[:80]}{'...' if len(script_text) > 80 else ''}\"")

    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
    headers = {
        "xi-api-key": ELEVENLABS_API_KEY,
        "Content-Type": "application/json",
    }
    payload = {
        "text": script_text,
        "model_id": config.voice_model,
        "voice_settings": {
            "stability": config.voice_stability,
            "similarity_boost": config.voice_similarity,
            "style": config.voice_style,
            "use_speaker_boost": config.voice_speaker_boost,
        },
    }

    resp = requests.post(url, headers=headers, json=payload)

    if resp.status_code != 200:
        raise RuntimeError(
            f"ElevenLabs TTS failed ({resp.status_code}):\n{resp.text}"
        )

    with open(output_path, "wb") as f:
        f.write(resp.content)

    print(f"      Speech saved to {output_path}")
    return output_path


# ===========================================================================
# Step 5a: Generate talking head video with D-ID (API, metered)
# ===========================================================================

def _did_headers(content_type: Optional[str] = None) -> dict:
    """Build D-ID authorization headers."""
    headers = {
        "Authorization": f"Basic {DID_API_KEY}",
        "accept": "application/json",
    }
    if content_type:
        headers["Content-Type"] = content_type
    return headers


def _upload_image_to_did(image_path: str) -> str:
    """Upload an image to D-ID's temporary storage."""
    _check_key("DID_API_KEY", DID_API_KEY)
    url = "https://api.d-id.com/images"
    headers = _did_headers()
    suffix = Path(image_path).suffix.lower()
    mime = "image/png" if suffix == ".png" else "image/jpeg"
    with open(image_path, "rb") as f:
        files = {"image": (Path(image_path).name, f, mime)}
        resp = requests.post(url, headers=headers, files=files)
    if resp.status_code not in (200, 201):
        raise RuntimeError(f"D-ID image upload failed ({resp.status_code}):\n{resp.text}")
    image_url = resp.json().get("url", "")
    print(f"      Image uploaded to D-ID: {image_url[:80]}...")
    return image_url


def _upload_audio_to_did(audio_path: str) -> str:
    """Upload an audio file to D-ID's temporary storage."""
    _check_key("DID_API_KEY", DID_API_KEY)
    url = "https://api.d-id.com/audios"
    headers = _did_headers()
    suffix = Path(audio_path).suffix.lower()
    mime_types = {".mp3": "audio/mpeg", ".wav": "audio/wav", ".m4a": "audio/mp4"}
    mime = mime_types.get(suffix, "audio/mpeg")
    with open(audio_path, "rb") as f:
        files = {"audio": (Path(audio_path).name, f, mime)}
        resp = requests.post(url, headers=headers, files=files)
    if resp.status_code not in (200, 201):
        raise RuntimeError(f"D-ID audio upload failed ({resp.status_code}):\n{resp.text}")
    audio_url = resp.json().get("url", "")
    print(f"      Audio uploaded to D-ID: {audio_url[:80]}...")
    return audio_url


def _generate_video_did(
    image_path: str,
    audio_path: str,
    config: AvatarConfig,
    output_path: str,
) -> str:
    """Generate talking head video using D-ID API."""
    _check_key("DID_API_KEY", DID_API_KEY)

    print(f"[5/5] Generating talking head video with D-ID ...")

    print("      Uploading image to D-ID ...")
    image_url = _upload_image_to_did(image_path)
    print("      Uploading audio to D-ID ...")
    audio_url = _upload_audio_to_did(audio_path)

    url = "https://api.d-id.com/talks"
    headers = _did_headers("application/json")
    payload = {
        "source_url": image_url,
        "script": {
            "type": "audio",
            "audio_url": audio_url,
        },
        "config": {
            "result_format": "mp4",
        },
    }

    resp = requests.post(url, headers=headers, json=payload)
    if resp.status_code not in (200, 201):
        raise RuntimeError(f"D-ID create talk failed ({resp.status_code}):\n{resp.text}")

    talk_id = resp.json()["id"]
    print(f"      Talk created (ID: {talk_id}). Waiting for render ...")

    poll_url = f"https://api.d-id.com/talks/{talk_id}"
    poll_headers = _did_headers()
    max_wait = 600
    elapsed = 0
    poll_interval = 5

    while elapsed < max_wait:
        time.sleep(poll_interval)
        elapsed += poll_interval
        resp = requests.get(poll_url, headers=poll_headers)
        if resp.status_code != 200:
            raise RuntimeError(f"D-ID poll failed ({resp.status_code}):\n{resp.text}")
        status = resp.json().get("status")
        print(f"      Status: {status} ({elapsed}s elapsed)")
        if status == "done":
            result_url = resp.json()["result_url"]
            break
        elif status in ("failed", "rejected"):
            error = resp.json().get("error", "Unknown error")
            raise RuntimeError(f"D-ID video generation failed: {error}")
    else:
        raise TimeoutError("D-ID video generation timed out after 10 minutes")

    print(f"      Downloading video ...")
    video_resp = requests.get(result_url)
    with open(output_path, "wb") as f:
        f.write(video_resp.content)

    print(f"      Video saved to {output_path}")
    return output_path


# ===========================================================================
# Step 5b: Generate talking head video with SadTalker (native conda, free)
# ===========================================================================

def _find_conda_python() -> Optional[str]:
    """Find the Python executable in the 'sadtalker' conda environment."""
    # Try conda info to find the envs directory
    try:
        result = subprocess.run(
            ["conda", "info", "--envs"],
            capture_output=True, text=True, timeout=10,
        )
        for line in result.stdout.strip().splitlines():
            line = line.strip()
            if line.startswith("#") or not line:
                continue
            # Lines look like:  sadtalker    /Users/foo/miniconda3/envs/sadtalker
            # or:               sadtalker *  /Users/foo/miniconda3/envs/sadtalker
            parts = line.split()
            if parts[0] == "sadtalker":
                env_path = parts[-1]  # last token is the path
                python_path = os.path.join(env_path, "bin", "python")
                if os.path.exists(python_path):
                    return python_path
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    # Fallback: check common conda locations
    for base in [
        os.path.expanduser("~/miniconda3"),
        os.path.expanduser("~/anaconda3"),
        os.path.expanduser("~/opt/miniconda3"),
        os.path.expanduser("~/opt/anaconda3"),
        "/opt/miniconda3",
        "/opt/anaconda3",
    ]:
        python_path = os.path.join(base, "envs", "sadtalker", "bin", "python")
        if os.path.exists(python_path):
            return python_path

    return None


def check_sadtalker_native() -> bool:
    """Check if the native SadTalker conda environment is set up."""
    python_path = _find_conda_python()
    if python_path is None:
        return False

    # Also check that SadTalker is cloned
    project_dir = Path(__file__).parent.resolve()
    sadtalker_dir = project_dir / "SadTalker"
    return sadtalker_dir.exists() and (sadtalker_dir / "inference.py").exists()


def check_sadtalker_docker() -> bool:
    """Check if the SadTalker Docker image is built and Docker is available."""
    try:
        result = subprocess.run(
            ["docker", "images", "-q", SADTALKER_IMAGE],
            capture_output=True, text=True, timeout=10,
        )
        return result.returncode == 0 and result.stdout.strip() != ""
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _convert_audio_to_wav(audio_path: str) -> str:
    """Convert audio to WAV format for SadTalker if needed."""
    audio_path_resolved = Path(audio_path).resolve()
    if audio_path_resolved.suffix.lower() == ".wav":
        return str(audio_path_resolved)

    wav_path = os.path.join(TEMP_DIR, "speech_for_sadtalker.wav")
    print("      Converting audio to WAV for SadTalker ...")
    conv_result = subprocess.run(
        ["ffmpeg", "-y", "-i", str(audio_path_resolved), "-ar", "16000", "-ac", "1", wav_path],
        capture_output=True, text=True,
    )
    if conv_result.returncode != 0:
        raise RuntimeError(f"Audio conversion failed:\n{conv_result.stderr}")
    return wav_path


def _generate_video_sadtalker(
    image_path: str,
    audio_path: str,
    config: AvatarConfig,
    output_path: str,
) -> str:
    """Generate talking head video using SadTalker natively via conda."""

    print(f"[5/5] Generating talking head video with SadTalker (native) ...")

    python_path = _find_conda_python()
    if python_path is None:
        raise RuntimeError(
            "SadTalker conda environment not found.\n"
            "Please run the setup script first:\n"
            "  bash setup_sadtalker_native.sh"
        )

    project_dir = Path(__file__).parent.resolve()
    sadtalker_dir = project_dir / "SadTalker"

    if not sadtalker_dir.exists():
        raise RuntimeError(
            f"SadTalker not found at {sadtalker_dir}.\n"
            "Please run: bash setup_sadtalker_native.sh"
        )

    # Convert audio if needed
    wav_path = _convert_audio_to_wav(audio_path)
    image_path_resolved = str(Path(image_path).resolve())

    # Build result dir
    result_dir = os.path.join(TEMP_DIR, "sadtalker_native_output")
    os.makedirs(result_dir, exist_ok=True)

    # Use the wrapper script that patches torchvision.transforms.functional_tensor
    # (basicsr 1.4.2 imports from it, but it was removed in torchvision 0.17+)
    wrapper_script = str(project_dir / "run_sadtalker.py")

    cmd = [
        python_path,
        wrapper_script,
        "--driven_audio", wav_path,
        "--source_image", image_path_resolved,
        "--result_dir", result_dir,
    ]

    if config.sadtalker_still:
        cmd.append("--still")

    if config.sadtalker_enhancer and config.sadtalker_enhancer.lower() != "none":
        cmd.extend(["--enhancer", config.sadtalker_enhancer.lower()])

    cmd.extend(["--preprocess", config.sadtalker_preprocess])
    cmd.extend(["--size", str(config.sadtalker_size)])
    cmd.extend(["--expression_scale", str(config.sadtalker_expression_scale)])
    cmd.extend(["--pose_style", str(config.sadtalker_pose_style)])

    # Don't pass --cpu so SadTalker can auto-detect MPS (Apple Silicon GPU).
    # MPS acceleration can be 5-10x faster than CPU for the face renderer.
    # If MPS causes issues, the user can fall back by adding --cpu manually.

    print(f"      Python:     {python_path}")
    print(f"      Image:      {image_path_resolved}")
    print(f"      Audio:      {wav_path}")
    print(f"      Still:      {config.sadtalker_still}")
    print(f"      Enhance:    {config.sadtalker_enhancer}")
    print(f"      Expression: {config.sadtalker_expression_scale}x")
    print(f"      Pose style: {config.sadtalker_pose_style}")
    print(f"      Running natively via wrapper (torchvision patch applied) ...")

    result = subprocess.run(cmd, cwd=str(project_dir), timeout=7200)  # 2 hours max

    if result.returncode != 0:
        raise RuntimeError(
            f"SadTalker inference failed (exit code {result.returncode}).\n"
            "Check the terminal output above for details."
        )

    # Find the output video
    output_videos = sorted(
        Path(result_dir).glob("**/*.mp4"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )

    if output_videos:
        shutil.copy2(str(output_videos[0]), output_path)
    else:
        raise RuntimeError(
            "SadTalker finished but no output video was found.\n"
            f"Check {result_dir} for any output files."
        )

    print(f"      Video saved to {output_path}")
    return output_path


# ===========================================================================
# Step 5: Unified video generation dispatcher
# ===========================================================================

def generate_talking_video(
    image_path: str,
    audio_path: str,
    config: AvatarConfig = AvatarConfig(),
    output_path: Optional[str] = None,
) -> str:
    """
    Generate a talking head video using the configured backend.
    - "did":       D-ID cloud API (metered, requires paid plan)
    - "sadtalker": SadTalker native via conda (free, unlimited, fast)
    """
    if output_path is None:
        output_path = os.path.join(OUTPUT_DIR, "avatar_video.mp4")

    if config.video_backend == "did":
        return _generate_video_did(image_path, audio_path, config, output_path)
    elif config.video_backend == "sadtalker":
        return _generate_video_sadtalker(image_path, audio_path, config, output_path)
    else:
        raise ValueError(
            f"Unknown video backend: {config.video_backend}. "
            "Use 'did' or 'sadtalker'."
        )


# ===========================================================================
# Audio-only mode (no video generation)
# ===========================================================================

def create_audio_only(
    source_video: str,
    script_text: str,
    config: AvatarConfig = AvatarConfig(),
    voice_name: str = "My Avatar Voice",
    use_builtin_voice: Optional[str] = None,
    output_path: Optional[str] = None,
) -> str:
    """
    Generate only the cloned speech audio — no video.
    Ideal for long-form content (audiobooks, courses, podcasts)
    where you want unlimited output without D-ID costs.
    """
    if output_path is None:
        output_path = os.path.join(OUTPUT_DIR, "avatar_speech.mp3")

    print("=" * 60)
    print("  AI Avatar Studio v2 - Audio-Only Mode")
    print("=" * 60)

    if use_builtin_voice:
        print(f"[1/2] Using built-in ElevenLabs voice: {use_builtin_voice}")
        voice_id = use_builtin_voice
    else:
        voice_sample = extract_audio_from_video(source_video)
        voice_id = clone_voice(voice_sample, voice_name)

    speech_audio = generate_speech(script_text, voice_id, config, output_path)

    print("=" * 60)
    print(f"  Done! Your speech audio: {speech_audio}")
    print("=" * 60)

    return speech_audio


# ===========================================================================
# Full pipeline
# ===========================================================================

def create_avatar_video(
    source_video: str,
    script_text: str,
    config: AvatarConfig = AvatarConfig(),
    avatar_image: Optional[str] = None,
    frame_timestamp: float = 1.0,
    voice_name: str = "My Avatar Voice",
    use_builtin_voice: Optional[str] = None,
) -> str:
    """
    End-to-end pipeline:
      1. Extract audio (voice sample) from source video
      2. Extract a still frame (or use provided image)
      3. Clone the voice with ElevenLabs (or use a built-in voice)
      4. Generate speech from the script
      5. Create talking head video with D-ID or SadTalker

    Returns the path to the final avatar video.
    """
    print("=" * 60)
    print(f"  AI Avatar Studio v2 - {config.video_backend.upper()} Backend")
    print("=" * 60)

    # Step 2 - Get avatar image
    if avatar_image is None:
        avatar_image = extract_frame_from_video(source_video, timestamp=frame_timestamp)

    # Step 3 - Get voice ID (clone or built-in)
    if use_builtin_voice:
        print(f"[3/5] Using built-in ElevenLabs voice: {use_builtin_voice}")
        voice_id = use_builtin_voice
    else:
        voice_sample = extract_audio_from_video(source_video)
        voice_id = clone_voice(voice_sample, voice_name)

    # Step 4 - Generate speech
    speech_audio = generate_speech(script_text, voice_id, config)

    # Step 5 - Generate video
    output_video = generate_talking_video(avatar_image, speech_audio, config)

    print("=" * 60)
    print(f"  Done! Your avatar video: {output_video}")
    print("=" * 60)

    return output_video


# ===========================================================================
# Utilities
# ===========================================================================

def _check_key(name: str, value: str):
    """Verify an API key is configured."""
    if not value or value.startswith("your-"):
        raise ValueError(
            f"{name} is not configured.\n"
            f"Set it in config.py or as an environment variable:\n"
            f"  export {name}=your-actual-key"
        )


# ===========================================================================
# CLI entry point
# ===========================================================================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="AI Avatar Studio v2 - Hybrid avatar video generation"
    )
    parser.add_argument("--video", required=True, help="Path to your source video")
    parser.add_argument("--script", required=True, help="Text for the avatar to speak")
    parser.add_argument("--image", default=None, help="Optional avatar photo")
    parser.add_argument("--frame-time", type=float, default=1.0)
    parser.add_argument("--voice-name", default="My Avatar Voice")
    parser.add_argument("--voice-model", default="eleven_multilingual_v2")
    parser.add_argument("--stability", type=float, default=0.35)
    parser.add_argument("--similarity", type=float, default=0.80)
    parser.add_argument("--style", type=float, default=0.45)
    parser.add_argument("--backend", default="sadtalker",
                        choices=["did", "sadtalker"],
                        help="Video backend: 'did' (API) or 'sadtalker' (local Docker)")
    parser.add_argument("--audio-only", action="store_true",
                        help="Generate speech audio only, no video")

    args = parser.parse_args()

    cfg = AvatarConfig(
        voice_model=args.voice_model,
        voice_stability=args.stability,
        voice_similarity=args.similarity,
        voice_style=args.style,
        video_backend=args.backend,
    )

    if args.audio_only:
        create_audio_only(
            source_video=args.video,
            script_text=args.script,
            config=cfg,
            voice_name=args.voice_name,
        )
    else:
        create_avatar_video(
            source_video=args.video,
            script_text=args.script,
            config=cfg,
            avatar_image=args.image,
            frame_timestamp=args.frame_time,
            voice_name=args.voice_name,
        )
