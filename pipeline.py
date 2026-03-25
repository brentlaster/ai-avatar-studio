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

import config as _config

# Re-export directory paths (these don't change at runtime)
OUTPUT_DIR = _config.OUTPUT_DIR
TEMP_DIR = _config.TEMP_DIR

# Docker image name for the SadTalker container
SADTALKER_IMAGE = "ai-avatar-studio-sadtalker"


@dataclass
class AvatarConfig:
    """Settings for the avatar generation pipeline."""
    # TTS engine: "elevenlabs" (API, paid) or "coqui_xtts" (local, free)
    tts_engine: str = "coqui_xtts"

    # ElevenLabs voice settings (only used when tts_engine="elevenlabs")
    voice_model: str = "eleven_multilingual_v2"
    voice_stability: float = 0.20       # lower = more expressive (0.0-1.0)
    voice_similarity: float = 0.75      # how close to the original voice (0.0-1.0)
    voice_style: float = 0.65           # style exaggeration - adds emotion (0.0-1.0)
    voice_speaker_boost: bool = True    # enhances clarity and presence

    # Coqui XTTS settings (only used when tts_engine="coqui_xtts")
    coqui_language: str = "en"          # language code for XTTS
    coqui_temperature: float = 0.75     # 0.1-1.0: lower = stable/monotone, higher = expressive
    coqui_repetition_penalty: float = 1.8  # 1.0-5.0: higher = fewer artifacts, less natural
    coqui_top_p: float = 0.95          # 0.5-1.0: breadth of sampling (higher = more varied)
    coqui_bass_boost_db: float = 1.0   # -3 to +6 dB: post-processing low-shelf EQ below 250Hz
    coqui_high_cut_db: float = -0.5    # -6 to +3 dB: post-processing high-shelf EQ above 4kHz
    coqui_speed: float = 1.0            # speech speed multiplier

    # Voice sample path for Coqui XTTS voice cloning
    voice_sample_path: Optional[str] = None

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
    _check_key("ELEVENLABS_API_KEY", _config.ELEVENLABS_API_KEY)

    url = "https://api.elevenlabs.io/v1/voices"
    headers = {"xi-api-key": _config.ELEVENLABS_API_KEY}
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
    _check_key("ELEVENLABS_API_KEY", _config.ELEVENLABS_API_KEY)

    print(f"[3/5] Cloning voice with ElevenLabs ...")

    url = "https://api.elevenlabs.io/v1/voices/add"
    headers = {"xi-api-key": _config.ELEVENLABS_API_KEY}

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

MAX_TTS_CHARS = 9500  # ElevenLabs limit is 10000; leave margin for safety


def _split_text_into_chunks(text: str, max_chars: int = MAX_TTS_CHARS) -> list:
    """
    Split text into chunks that fit within the ElevenLabs character limit.
    Splits on paragraph boundaries first, then sentence boundaries, to
    preserve natural speech flow. Never splits mid-sentence.
    """
    if len(text) <= max_chars:
        return [text]

    chunks = []
    remaining = text

    while remaining:
        if len(remaining) <= max_chars:
            chunks.append(remaining.strip())
            break

        # Try to split at a paragraph boundary (double newline)
        candidate = remaining[:max_chars]
        split_pos = candidate.rfind("\n\n")

        # If no paragraph break, try single newline
        if split_pos < max_chars // 2:
            split_pos = candidate.rfind("\n")

        # If no newline, try sentence endings (. ! ?)
        if split_pos < max_chars // 2:
            for sep in [". ", "! ", "? ", ".\n", "!\n", "?\n"]:
                pos = candidate.rfind(sep)
                if pos > split_pos:
                    split_pos = pos + 1  # include the punctuation

        # Last resort: split at the last space
        if split_pos < max_chars // 4:
            split_pos = candidate.rfind(" ")

        # Absolute last resort: hard cut
        if split_pos <= 0:
            split_pos = max_chars

        chunk = remaining[:split_pos].strip()
        if chunk:
            chunks.append(chunk)
        remaining = remaining[split_pos:].strip()

    return chunks


def _concatenate_audio_files(audio_paths: list, output_path: str) -> str:
    """Concatenate multiple audio files into one using ffmpeg."""
    if len(audio_paths) == 1:
        shutil.copy2(audio_paths[0], output_path)
        return output_path

    # Create a temporary file list for ffmpeg concat
    list_path = os.path.join(TEMP_DIR, "audio_concat_list.txt")
    with open(list_path, "w") as f:
        for path in audio_paths:
            # ffmpeg concat requires escaped single quotes in paths
            escaped = path.replace("'", "'\\''")
            f.write(f"file '{escaped}'\n")

    cmd = [
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0",
        "-i", list_path,
        "-c", "copy",
        output_path,
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        # If copy codec fails (different formats), try re-encoding
        cmd_reencode = [
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0",
            "-i", list_path,
            "-acodec", "libmp3lame", "-q:a", "2",
            output_path,
        ]
        result = subprocess.run(cmd_reencode, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"Audio concatenation failed:\n{result.stderr}")

    # Clean up chunk files
    for path in audio_paths:
        try:
            os.remove(path)
        except OSError:
            pass

    return output_path


def generate_speech(
    script_text: str,
    voice_id: str,
    config: AvatarConfig = AvatarConfig(),
    output_path: Optional[str] = None,
) -> str:
    """
    Generate speech audio from text.
    Dispatches to ElevenLabs (API) or Coqui XTTS (local, free) based on
    config.tts_engine.  Returns path to the generated audio file.
    """
    if config.tts_engine == "coqui_xtts":
        return _generate_speech_coqui(script_text, config, output_path)
    else:
        return _generate_speech_elevenlabs(script_text, voice_id, config, output_path)


# ---------------------------------------------------------------------------
# Coqui XTTS v2 — local, free, voice-cloning TTS
# Runs via subprocess in the sadtalker conda env (Python 3.10)
# because Coqui TTS requires Python < 3.12.
# ---------------------------------------------------------------------------

def _generate_speech_coqui(
    script_text: str,
    config: AvatarConfig,
    output_path: Optional[str] = None,
) -> str:
    """
    Generate speech using Coqui XTTS v2 with voice cloning.
    Runs in the sadtalker conda environment via run_coqui_tts.py wrapper.
    Requires a voice sample WAV file (config.voice_sample_path).
    Free, unlimited, runs entirely locally.
    """
    if output_path is None:
        output_path = os.path.join(TEMP_DIR, "cloned_speech.wav")

    # Ensure output has .wav extension (Coqui outputs WAV natively)
    if not output_path.endswith(".wav"):
        output_path = os.path.splitext(output_path)[0] + ".wav"

    voice_sample = config.voice_sample_path
    if not voice_sample or not os.path.exists(voice_sample):
        raise ValueError(
            "Coqui XTTS requires a voice sample for cloning.\n"
            "Please upload a source video or provide a voice sample."
        )

    # Find the TTS conda env Python (dedicated 'tts' env preferred)
    python_path = _find_tts_python()
    if python_path is None:
        raise RuntimeError(
            "No compatible conda environment found for Coqui TTS.\n"
            "Create one with:\n"
            "  conda create -n tts python=3.10 -y\n"
            "  conda activate tts\n"
            "  pip install TTS torch torchvision torchaudio\n"
            '  pip install "transformers>=4.33,<4.45"\n'
            "  conda activate base"
        )

    project_dir = Path(__file__).parent.resolve()
    wrapper_script = str(project_dir / "run_coqui_tts.py")

    print(f"[4/5] Generating speech with Coqui XTTS v2 ...")
    print(f"      Script length: {len(script_text):,} characters")
    print(f"      Voice sample: {voice_sample}")
    print(f"      Language: {config.coqui_language}")

    # XTTS v2 works best with shorter segments
    MAX_COQUI_CHARS = 3000

    chunks = _split_text_into_chunks(script_text, max_chars=MAX_COQUI_CHARS)

    if len(chunks) > 1:
        print(f"      Splitting into {len(chunks)} chunks for XTTS ...")

    chunk_paths = []
    for i, chunk in enumerate(chunks):
        if len(chunks) > 1:
            print(f"      Generating chunk {i + 1}/{len(chunks)} ({len(chunk):,} chars) ...")

        if len(chunks) == 1:
            chunk_out = output_path
        else:
            chunk_out = os.path.join(TEMP_DIR, f"coqui_chunk_{i:03d}.wav")

        # Write text to a temp file (avoids shell escaping issues with long text)
        text_file = os.path.join(TEMP_DIR, f"coqui_text_{i:03d}.txt")
        with open(text_file, "w", encoding="utf-8") as f:
            f.write(chunk)

        cmd = [
            python_path,
            wrapper_script,
            "--text_file", text_file,
            "--speaker_wav", voice_sample,
            "--output", chunk_out,
            "--language", config.coqui_language,
            "--temperature", str(config.coqui_temperature),
            "--repetition_penalty", str(config.coqui_repetition_penalty),
            "--top_p", str(config.coqui_top_p),
            "--bass_boost_db", str(config.coqui_bass_boost_db),
            "--high_cut_db", str(config.coqui_high_cut_db),
        ]

        print(f"      Running: {python_path} run_coqui_tts.py ...")
        result = subprocess.run(cmd, cwd=str(project_dir), timeout=600)

        if result.returncode != 0:
            raise RuntimeError(
                f"Coqui XTTS failed on chunk {i + 1} (exit code {result.returncode}).\n"
                "Check the terminal output above for details.\n"
                "Make sure TTS is installed: conda activate tts && pip install TTS"
            )

        # Clean up text file
        try:
            os.remove(text_file)
        except OSError:
            pass

        if len(chunks) > 1:
            chunk_paths.append(chunk_out)

    if len(chunks) > 1:
        print(f"      Concatenating {len(chunk_paths)} audio chunks ...")
        _concatenate_audio_files(chunk_paths, output_path)

    print(f"      Speech saved to {output_path}")
    return output_path


def _generate_speech_coqui_batch(
    items: list,
    config: AvatarConfig,
) -> list:
    """
    Batch-generate speech for multiple text segments using Coqui XTTS v2.

    Loads the model ONCE and processes all items sequentially — much faster
    than spawning a separate subprocess per segment (saves ~15-20s model
    load time per item for presentations with many slides).

    Args:
        items: List of dicts with keys:
            - "text": the script text to synthesize
            - "output_path": where to save the .wav file
            - "label": optional label for logging (e.g., "Slide 3")
        config: AvatarConfig with voice_sample_path and Coqui params set.

    Returns:
        List of output paths that were successfully generated.
    """
    voice_sample = config.voice_sample_path
    if not voice_sample or not os.path.exists(voice_sample):
        raise ValueError("Coqui XTTS requires a voice sample for cloning.")

    python_path = _find_tts_python()
    if python_path is None:
        raise RuntimeError("No compatible conda environment found for Coqui TTS.")

    project_dir = Path(__file__).parent.resolve()
    wrapper_script = str(project_dir / "run_coqui_tts.py")

    # Write batch JSON file
    batch_dir = os.path.join(TEMP_DIR, "_batch")
    os.makedirs(batch_dir, exist_ok=True)

    batch_items = []
    for i, item in enumerate(items):
        text = item["text"]
        output_path = item["output_path"]
        label = item.get("label", f"item {i+1}")

        # Ensure .wav extension
        if not output_path.endswith(".wav"):
            output_path = os.path.splitext(output_path)[0] + ".wav"
            item["output_path"] = output_path

        # Write text to temp file
        text_file = os.path.join(batch_dir, f"batch_text_{i:03d}.txt")
        with open(text_file, "w", encoding="utf-8") as f:
            f.write(text)

        batch_items.append({
            "text_file": text_file,
            "output": output_path,
            "label": label,
        })

    batch_json_path = os.path.join(batch_dir, "batch.json")
    with open(batch_json_path, "w") as f:
        import json as _json
        _json.dump(batch_items, f, indent=2)

    print(f"[Coqui XTTS Batch] Generating {len(batch_items)} segments in one model load ...")

    cmd = [
        python_path,
        wrapper_script,
        "--speaker_wav", voice_sample,
        "--output", os.path.join(batch_dir, "unused.wav"),  # Required arg, not used in batch mode
        "--language", config.coqui_language,
        "--temperature", str(config.coqui_temperature),
        "--repetition_penalty", str(config.coqui_repetition_penalty),
        "--top_p", str(config.coqui_top_p),
        "--bass_boost_db", str(config.coqui_bass_boost_db),
        "--high_cut_db", str(config.coqui_high_cut_db),
        "--batch_json", batch_json_path,
    ]

    result = subprocess.run(cmd, cwd=str(project_dir), timeout=1800)  # 30min timeout for large batches

    # Read results
    results_path = batch_json_path.replace(".json", "_results.json")
    success_paths = []
    if os.path.exists(results_path):
        import json as _json
        with open(results_path) as rf:
            results = _json.load(rf)
        success_paths = results.get("success", [])
        failed = results.get("failed", [])
        if failed:
            print(f"[Coqui XTTS Batch] WARNING: {len(failed)} items failed")
    elif result.returncode != 0:
        raise RuntimeError(f"Coqui XTTS batch failed (exit code {result.returncode})")

    # Clean up temp text files
    for item in batch_items:
        try:
            os.remove(item["text_file"])
        except OSError:
            pass
    for f_path in [batch_json_path, results_path]:
        try:
            os.remove(f_path)
        except OSError:
            pass
    try:
        os.rmdir(batch_dir)
    except OSError:
        pass

    return success_paths


# ---------------------------------------------------------------------------
# ElevenLabs TTS — API-based, paid
# ---------------------------------------------------------------------------

def _generate_speech_elevenlabs(
    script_text: str,
    voice_id: str,
    config: AvatarConfig = AvatarConfig(),
    output_path: Optional[str] = None,
) -> str:
    """
    Generate speech audio from text using a cloned ElevenLabs voice.
    Automatically chunks long scripts (>10K chars) and concatenates the results.
    Returns path to the generated audio file.
    """
    _check_key("ELEVENLABS_API_KEY", _config.ELEVENLABS_API_KEY)

    if output_path is None:
        output_path = os.path.join(TEMP_DIR, "cloned_speech.mp3")

    print(f"[4/5] Generating speech with ElevenLabs ...")
    print(f"      Script length: {len(script_text):,} characters")
    print(f"      Script: \"{script_text[:80]}{'...' if len(script_text) > 80 else ''}\"")

    chunks = _split_text_into_chunks(script_text)

    if len(chunks) > 1:
        print(f"      Long script detected — splitting into {len(chunks)} chunks")

    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
    headers = {
        "xi-api-key": _config.ELEVENLABS_API_KEY,
        "Content-Type": "application/json",
    }

    chunk_paths = []
    for i, chunk in enumerate(chunks):
        if len(chunks) > 1:
            print(f"      Generating chunk {i + 1}/{len(chunks)} ({len(chunk):,} chars) ...")

        payload = {
            "text": chunk,
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
                f"ElevenLabs TTS failed on chunk {i + 1} ({resp.status_code}):\n{resp.text}"
            )

        if len(chunks) == 1:
            # Single chunk — write directly to output
            with open(output_path, "wb") as f:
                f.write(resp.content)
        else:
            # Multiple chunks — save to temp files for later concatenation
            chunk_path = os.path.join(TEMP_DIR, f"speech_chunk_{i:03d}.mp3")
            with open(chunk_path, "wb") as f:
                f.write(resp.content)
            chunk_paths.append(chunk_path)

    if len(chunks) > 1:
        print(f"      Concatenating {len(chunk_paths)} audio chunks ...")
        _concatenate_audio_files(chunk_paths, output_path)

    print(f"      Speech saved to {output_path}")
    return output_path


# ===========================================================================
# Step 5a: Generate talking head video with D-ID (API, metered)
# ===========================================================================

def _did_headers(content_type: Optional[str] = None) -> dict:
    """Build D-ID authorization headers."""
    headers = {
        "Authorization": f"Basic {_config.DID_API_KEY}",
        "accept": "application/json",
    }
    if content_type:
        headers["Content-Type"] = content_type
    return headers


def _upload_image_to_did(image_path: str) -> str:
    """Upload an image to D-ID's temporary storage."""
    _check_key("DID_API_KEY", _config.DID_API_KEY)
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
    _check_key("DID_API_KEY", _config.DID_API_KEY)
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
    _check_key("DID_API_KEY", _config.DID_API_KEY)

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

def _find_conda_python_for_env(env_name: str = "sadtalker") -> Optional[str]:
    """Find the Python executable in a named conda environment."""
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
            parts = line.split()
            if parts[0] == env_name:
                env_path = parts[-1]
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
        python_path = os.path.join(base, "envs", env_name, "bin", "python")
        if os.path.exists(python_path):
            return python_path

    return None


def _find_conda_python() -> Optional[str]:
    """Find the Python executable in the 'sadtalker' conda environment."""
    return _find_conda_python_for_env("sadtalker")


def _find_tts_python() -> Optional[str]:
    """Find Python for TTS — uses dedicated 'tts' env, falls back to 'sadtalker'."""
    # Prefer the dedicated tts env (has compatible PyTorch >= 2.4)
    path = _find_conda_python_for_env("tts")
    if path:
        return path
    # Fallback to sadtalker env (may have version conflicts)
    return _find_conda_python_for_env("sadtalker")


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
    ext = ".wav" if config.tts_engine == "coqui_xtts" else ".mp3"
    if output_path is None:
        output_path = os.path.join(OUTPUT_DIR, f"avatar_speech{ext}")

    print("=" * 60)
    print(f"  AI Avatar Studio v2 - Audio-Only Mode ({config.tts_engine})")
    print("=" * 60)

    voice_id = ""
    if config.tts_engine == "coqui_xtts":
        # Coqui XTTS uses the voice sample directly — extract it from video
        if not config.voice_sample_path:
            voice_sample = extract_audio_from_video(source_video)
            config.voice_sample_path = voice_sample
        print(f"[1/2] Using Coqui XTTS voice cloning from: {config.voice_sample_path}")
    elif use_builtin_voice:
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
    print(f"  AI Avatar Studio v2 - {config.video_backend.upper()} / {config.tts_engine}")
    print("=" * 60)

    # Step 2 - Get avatar image
    if avatar_image is None:
        avatar_image = extract_frame_from_video(source_video, timestamp=frame_timestamp)

    # Step 3 - Get voice ID (clone or built-in)
    voice_id = ""
    if config.tts_engine == "coqui_xtts":
        # Coqui XTTS uses the voice sample directly
        if not config.voice_sample_path:
            voice_sample = extract_audio_from_video(source_video)
            config.voice_sample_path = voice_sample
        print(f"[3/5] Using Coqui XTTS voice cloning from: {config.voice_sample_path}")
    elif use_builtin_voice:
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
