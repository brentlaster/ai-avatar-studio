#!/usr/bin/env python3
"""
Coqui XTTS v2 wrapper — runs in the sadtalker conda environment (Python 3.10)
so the main app can stay on Python 3.12.

Called via subprocess from pipeline.py, similar to run_sadtalker.py.

Usage:
    python run_coqui_tts.py \
        --text "Hello world" \
        --speaker_wav /path/to/voice_sample.wav \
        --output /path/to/output.wav \
        [--language en] \
        [--text_file /path/to/script.txt]

Either --text or --text_file must be provided.
If --text_file is given, it takes precedence over --text.
"""

import argparse
import os
import sys
import json
import re
import wave
import struct


def split_text_into_chunks(text: str, max_chars: int = 220) -> list:
    """
    Split text into chunks that fit within XTTS's ~250 char limit.
    Splits on sentence boundaries (. ! ?) first, then on commas/semicolons,
    then hard-wraps if a single sentence is still too long.
    """
    # Split into sentences (keep the delimiter attached)
    sentences = re.split(r'(?<=[.!?])\s+', text.strip())

    chunks = []
    current = ""

    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue

        # If adding this sentence stays under limit, append it
        if len(current) + len(sentence) + 1 <= max_chars:
            current = f"{current} {sentence}".strip() if current else sentence
        else:
            # Flush current chunk if non-empty
            if current:
                chunks.append(current)
                current = ""

            # If the sentence itself fits, start a new chunk with it
            if len(sentence) <= max_chars:
                current = sentence
            else:
                # Sentence is too long — split on commas/semicolons
                parts = re.split(r'(?<=[,;])\s+', sentence)
                for part in parts:
                    part = part.strip()
                    if not part:
                        continue
                    if len(current) + len(part) + 1 <= max_chars:
                        current = f"{current} {part}".strip() if current else part
                    else:
                        if current:
                            chunks.append(current)
                        # Hard-wrap if even a single clause is too long
                        if len(part) <= max_chars:
                            current = part
                        else:
                            # Last resort: split at word boundaries
                            words = part.split()
                            current = ""
                            for word in words:
                                if len(current) + len(word) + 1 <= max_chars:
                                    current = f"{current} {word}".strip() if current else word
                                else:
                                    if current:
                                        chunks.append(current)
                                    current = word
    if current:
        chunks.append(current)

    return chunks


def trim_trailing_silence(frames: bytes, sample_width: int, threshold: int = 300, min_silence_samples: int = 2400) -> bytes:
    """
    Trim trailing silence/noise from raw PCM audio frames.
    This removes the XTTS "tail artifacts" (warble, clicks) that appear
    at the end of generated chunks.
    """
    if sample_width == 2:
        # 16-bit PCM
        n_samples = len(frames) // 2
        samples = struct.unpack(f'<{n_samples}h', frames)

        # Walk backward to find where actual audio ends
        end = n_samples
        silent_count = 0
        for i in range(n_samples - 1, -1, -1):
            if abs(samples[i]) < threshold:
                silent_count += 1
                if silent_count >= min_silence_samples:
                    end = i + min_silence_samples
                    break
            else:
                silent_count = 0
                end = i + 1
                break

        trimmed = samples[:end]
        return struct.pack(f'<{len(trimmed)}h', *trimmed)
    else:
        return frames


def make_silence(duration_ms: int, sample_rate: int = 24000, sample_width: int = 2, channels: int = 1) -> bytes:
    """Generate silent PCM audio frames."""
    n_samples = int(sample_rate * duration_ms / 1000) * channels
    return b'\x00' * (n_samples * sample_width)


def concatenate_wavs(wav_paths: list, output_path: str):
    """Concatenate multiple WAV files with short silence gaps and tail trimming."""
    if len(wav_paths) == 1:
        import shutil
        shutil.move(wav_paths[0], output_path)
        return

    # Read all WAV data
    params = None
    all_frames = []
    for wp in wav_paths:
        with wave.open(wp, 'rb') as wf:
            if params is None:
                params = wf.getparams()
            raw = wf.readframes(wf.getnframes())
            # Trim trailing silence/artifacts from each chunk
            trimmed = trim_trailing_silence(raw, params.sampwidth)
            all_frames.append(trimmed)

    # Create a short silence gap (150ms) between chunks for natural pacing
    gap = make_silence(150, params.framerate, params.sampwidth, params.nchannels)

    # Write combined with gaps
    with wave.open(output_path, 'wb') as out:
        out.setparams(params)
        for i, frames in enumerate(all_frames):
            out.writeframes(frames)
            if i < len(all_frames) - 1:
                out.writeframes(gap)


def main():
    parser = argparse.ArgumentParser(description="Coqui XTTS v2 TTS wrapper")
    parser.add_argument("--text", type=str, default="", help="Text to speak")
    parser.add_argument("--text_file", type=str, default="", help="Path to text file (overrides --text)")
    parser.add_argument("--speaker_wav", type=str, required=True, help="Path to voice sample WAV")
    parser.add_argument("--output", type=str, required=True, help="Output audio file path (.wav)")
    parser.add_argument("--language", type=str, default="en", help="Language code (default: en)")
    args = parser.parse_args()

    # Get the text to synthesize
    if args.text_file and os.path.exists(args.text_file):
        with open(args.text_file, "r", encoding="utf-8") as f:
            text = f.read().strip()
    elif args.text:
        text = args.text
    else:
        print("ERROR: No text provided. Use --text or --text_file.", file=sys.stderr)
        sys.exit(1)

    if not text:
        print("ERROR: Text is empty.", file=sys.stderr)
        sys.exit(1)

    if not os.path.exists(args.speaker_wav):
        print(f"ERROR: Speaker WAV not found: {args.speaker_wav}", file=sys.stderr)
        sys.exit(1)

    print(f"[Coqui XTTS] Text length: {len(text):,} characters")
    print(f"[Coqui XTTS] Speaker WAV: {args.speaker_wav}")
    print(f"[Coqui XTTS] Language: {args.language}")
    print(f"[Coqui XTTS] Output: {args.output}")

    # Import and load model
    print("[Coqui XTTS] Loading XTTS v2 model ...")

    # --- PyTorch 2.6+ compatibility fix ---
    # PyTorch 2.6 changed torch.load to weights_only=True by default,
    # which breaks Coqui TTS checkpoint loading (it uses pickle-based
    # custom classes like XttsConfig, BaseDatasetConfig, etc.).
    # The XTTS model is from Coqui's official repo, so this is safe.
    import torch
    _original_torch_load = torch.load
    def _patched_torch_load(*args, **kwargs):
        kwargs["weights_only"] = False
        return _original_torch_load(*args, **kwargs)
    torch.load = _patched_torch_load
    print("[Coqui XTTS] Patched torch.load for PyTorch 2.6+ compatibility")

    try:
        from TTS.api import TTS
    except ImportError:
        print(
            "ERROR: Coqui TTS not installed in this environment.\n"
            "Install with: pip install TTS",
            file=sys.stderr,
        )
        sys.exit(1)

    tts = TTS("tts_models/multilingual/multi-dataset/xtts_v2")

    # Try GPU acceleration
    try:
        import torch
        if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            tts = tts.to("mps")
            print("[Coqui XTTS] Using MPS (Apple Silicon GPU)")
        elif torch.cuda.is_available():
            tts = tts.to("cuda")
            print("[Coqui XTTS] Using CUDA GPU")
        else:
            print("[Coqui XTTS] Using CPU")
    except Exception:
        print("[Coqui XTTS] Using CPU (GPU detection failed)")

    # Generate speech — split into <=220 char chunks (XTTS limit is ~250)
    os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)

    chunks = split_text_into_chunks(text, max_chars=220)
    print(f"[Coqui XTTS] Split into {len(chunks)} chunk(s)")

    # --- Tune XTTS inference parameters for better quality ---
    # Adjust temperature and repetition_penalty on the model config
    # BEFORE calling tts_to_file(). This keeps the high-level API's
    # correct sample-rate handling while reducing warble/artifacts.
    #
    # temperature: Controls randomness of the generated speech.
    #   - Default ~0.65-0.75 can produce robotic/Max Headroom warble
    #   - 0.3 was too constrained → nasal/thin
    #   - 0.5 was better but still slightly robotic
    #   - 0.55 adds a touch more natural variation
    # repetition_penalty: Reduces repeated artifacts and gibberish.
    #   - Default 2.0 allows too many artifacts
    #   - 10.0 was too aggressive
    #   - 3.0 is a gentler constraint that avoids over-regularization
    # length_penalty: Encourages complete, well-paced utterances.
    try:
        model = tts.synthesizer.tts_model
        if hasattr(model, 'config') and hasattr(model.config, 'model_args'):
            model.config.model_args.temperature = 0.55
            model.config.model_args.repetition_penalty = 3.0
            model.config.model_args.top_k = 50
            model.config.model_args.top_p = 0.85
            model.config.model_args.length_penalty = 1.0
            print("[Coqui XTTS] Set inference params: temperature=0.55, repetition_penalty=3.0, top_k=50, top_p=0.85")
        elif hasattr(model, 'inference'):
            print("[Coqui XTTS] Model config structure not as expected, using defaults")
    except Exception as e:
        print(f"[Coqui XTTS] Could not set inference params: {e}")

    if len(chunks) == 1:
        # Single chunk — generate directly to output
        print(f"[Coqui XTTS] Generating speech ({len(chunks[0])} chars) ...")
        tts.tts_to_file(
            text=chunks[0],
            speaker_wav=args.speaker_wav,
            language=args.language,
            file_path=args.output,
        )
    else:
        # Multiple chunks — generate each, then concatenate
        import tempfile
        chunk_paths = []
        tmp_dir = os.path.join(os.path.dirname(os.path.abspath(args.output)), "_tts_chunks")
        os.makedirs(tmp_dir, exist_ok=True)

        for i, chunk in enumerate(chunks):
            chunk_path = os.path.join(tmp_dir, f"chunk_{i:04d}.wav")
            print(f"[Coqui XTTS] Chunk {i+1}/{len(chunks)} ({len(chunk)} chars): {chunk[:60]}...")
            tts.tts_to_file(
                text=chunk,
                speaker_wav=args.speaker_wav,
                language=args.language,
                file_path=chunk_path,
            )
            if os.path.exists(chunk_path):
                chunk_paths.append(chunk_path)
            else:
                print(f"WARNING: Chunk {i+1} failed to generate, skipping.", file=sys.stderr)

        if not chunk_paths:
            print("ERROR: No audio chunks were generated.", file=sys.stderr)
            sys.exit(1)

        print(f"[Coqui XTTS] Concatenating {len(chunk_paths)} chunks ...")
        concatenate_wavs(chunk_paths, args.output)

        # Clean up chunk files
        for cp in chunk_paths:
            try:
                os.remove(cp)
            except Exception:
                pass
        try:
            os.rmdir(tmp_dir)
        except Exception:
            pass

    if os.path.exists(args.output):
        size_kb = os.path.getsize(args.output) / 1024
        print(f"[Coqui XTTS] Success! Output: {args.output} ({size_kb:.1f} KB)")
    else:
        print("ERROR: Output file was not created.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
