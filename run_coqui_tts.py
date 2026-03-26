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


def trim_silence(frames: bytes, sample_width: int, threshold: int = 300,
                 min_silence_samples: int = 2400, trim_leading: bool = True,
                 trim_trailing: bool = True) -> bytes:
    """
    Trim leading and/or trailing silence from raw PCM audio frames.
    Removes XTTS artifacts: leading dead air before speech starts,
    and trailing warble/clicks after speech ends.

    Args:
        frames: Raw PCM audio bytes
        sample_width: Bytes per sample (2 for 16-bit)
        threshold: Amplitude below which audio is considered silent
        min_silence_samples: Consecutive silent samples needed to trigger trim
        trim_leading: If True, trim silence from the start
        trim_trailing: If True, trim silence from the end
    """
    if sample_width != 2:
        return frames

    n_samples = len(frames) // 2
    if n_samples == 0:
        return frames
    samples = struct.unpack(f'<{n_samples}h', frames)

    start = 0
    end = n_samples

    # Trim leading silence — walk forward to find where audio begins
    if trim_leading:
        silent_count = 0
        for i in range(n_samples):
            if abs(samples[i]) < threshold:
                silent_count += 1
            else:
                # Found audio. Trim everything before the silence run started,
                # but keep a tiny 50ms lead-in so speech doesn't feel clipped.
                # At 24kHz, 50ms = 1200 samples.
                start = max(0, i - 1200)
                break
        else:
            # Entire buffer is silent
            return b'\x00' * 4  # Return minimal silence

    # Trim trailing silence — walk backward
    if trim_trailing:
        silent_count = 0
        for i in range(n_samples - 1, start - 1, -1):
            if abs(samples[i]) < threshold:
                silent_count += 1
                if silent_count >= min_silence_samples:
                    end = i + min_silence_samples
                    break
            else:
                silent_count = 0
                end = i + 1
                break

    trimmed = samples[start:end]
    if len(trimmed) == 0:
        return b'\x00' * 4
    return struct.pack(f'<{len(trimmed)}h', *trimmed)


def trim_trailing_silence(frames: bytes, sample_width: int, threshold: int = 300,
                          min_silence_samples: int = 2400) -> bytes:
    """Legacy wrapper — trims both leading and trailing silence now."""
    return trim_silence(frames, sample_width, threshold, min_silence_samples,
                       trim_leading=True, trim_trailing=True)


def post_process_audio(wav_path: str, sample_rate: int = 24000,
                       bass_boost_db: float = 1.0, high_cut_db: float = -0.5):
    """
    Post-process XTTS output to sound more natural.

    Based on spectral analysis comparing real voice vs XTTS output:
    - Real voice:  bass=23.3%, flatness=0.0005, HNR=0.79
    - XTTS output: bass=19.0%, flatness=0.131,  HNR=0.56

    Applies:
    1. Low-shelf EQ boost (+3dB below 250Hz) to restore bass/chest warmth
    2. Gentle high-shelf cut (-2dB above 4kHz) to reduce synthetic brightness
    3. Spectral noise gate to reduce buzzy artifacts (high flatness)
    """
    import numpy as np
    from scipy import signal as scipy_signal

    # Read WAV
    with wave.open(wav_path, 'rb') as wf:
        params = wf.getparams()
        n_frames = wf.getnframes()
        raw = wf.readframes(n_frames)

    # Convert to float
    n_samples = len(raw) // 2
    samples = np.array(struct.unpack(f'<{n_samples}h', raw), dtype=np.float64)
    samples /= 32768.0  # Normalize to [-1, 1]

    sr = sample_rate

    # --- 1. Low-shelf EQ: boost bass below 250Hz ---
    bass_gain_db = bass_boost_db
    bass_freq = 250.0
    bass_gain = 10 ** (bass_gain_db / 20.0)  # ~1.41

    # Design a 2nd-order low-shelf filter using bilinear transform
    w0 = 2.0 * np.pi * bass_freq / sr
    A = bass_gain
    alpha = np.sin(w0) / 2.0 * np.sqrt(2.0)  # Q=0.707 for gentle slope

    b0 =     A * ((A + 1) - (A - 1) * np.cos(w0) + 2 * np.sqrt(A) * alpha)
    b1 = 2 * A * ((A - 1) - (A + 1) * np.cos(w0))
    b2 =     A * ((A + 1) - (A - 1) * np.cos(w0) - 2 * np.sqrt(A) * alpha)
    a0 =          (A + 1) + (A - 1) * np.cos(w0) + 2 * np.sqrt(A) * alpha
    a1 =    -2 * ((A - 1) + (A + 1) * np.cos(w0))
    a2 =          (A + 1) + (A - 1) * np.cos(w0) - 2 * np.sqrt(A) * alpha

    bass_b = np.array([b0, b1, b2]) / a0
    bass_a = np.array([a0, a1, a2]) / a0

    samples = scipy_signal.lfilter(bass_b, bass_a, samples)

    # --- 2. High-shelf EQ: cut above 4kHz ---
    high_freq = 4000.0
    A_h = 10 ** (high_cut_db / 20.0)

    w0_h = 2.0 * np.pi * high_freq / sr
    alpha_h = np.sin(w0_h) / 2.0 * np.sqrt(2.0)

    b0_h = A_h * ((A_h + 1) + (A_h - 1) * np.cos(w0_h) + 2 * np.sqrt(A_h) * alpha_h)
    b1_h = -2 * A_h * ((A_h - 1) + (A_h + 1) * np.cos(w0_h))
    b2_h = A_h * ((A_h + 1) + (A_h - 1) * np.cos(w0_h) - 2 * np.sqrt(A_h) * alpha_h)
    a0_h =        (A_h + 1) - (A_h - 1) * np.cos(w0_h) + 2 * np.sqrt(A_h) * alpha_h
    a1_h =  2 *  ((A_h - 1) - (A_h + 1) * np.cos(w0_h))
    a2_h =        (A_h + 1) - (A_h - 1) * np.cos(w0_h) - 2 * np.sqrt(A_h) * alpha_h

    high_b = np.array([b0_h, b1_h, b2_h]) / a0_h
    high_a = np.array([a0_h, a1_h, a2_h]) / a0_h

    samples = scipy_signal.lfilter(high_b, high_a, samples)

    # --- 3. Spectral subtraction + harmonic enhancement ---
    # Previous approach (flatness-based noise gate) didn't move the needle
    # on spectral flatness (0.131→0.127, target 0.0005) and hurt HNR/dynamics.
    #
    # New approach:
    # a) Spectral subtraction: estimate noise floor from low-energy frames,
    #    then subtract it from all frames (standard speech enhancement)
    # b) Harmonic enhancement: detect harmonic peaks in each frame and
    #    gently boost them relative to inter-harmonic noise
    n_fft = 2048
    hop = 512
    window = np.hanning(n_fft)

    # Pad signal
    pad_len = n_fft - (len(samples) % hop)
    if pad_len == n_fft:
        pad_len = 0
    padded = np.concatenate([samples, np.zeros(pad_len)]) if pad_len > 0 else samples.copy()

    # STFT
    n_frames_stft = (len(padded) - n_fft) // hop + 1
    stft = np.zeros((n_fft // 2 + 1, n_frames_stft), dtype=complex)
    for i in range(n_frames_stft):
        frame = padded[i * hop:i * hop + n_fft] * window
        spectrum = np.fft.rfft(frame)
        stft[:, i] = spectrum

    mag = np.abs(stft)
    phase = np.angle(stft)
    eps = 1e-10

    # --- 3a. Spectral subtraction ---
    # Estimate noise floor from the quietest 15% of frames
    frame_energies = np.sum(mag ** 2, axis=0)
    energy_threshold = np.percentile(frame_energies, 15)
    noise_frames = mag[:, frame_energies <= energy_threshold]
    if noise_frames.shape[1] > 0:
        noise_floor = np.mean(noise_frames, axis=1)
    else:
        noise_floor = np.min(mag, axis=1)

    # Subtract noise floor with over-subtraction factor and spectral floor
    # Reduced from 1.5→1.0 and raised floor from 0.08→0.15 to prevent
    # wiping out quiet speech onsets (which caused audible dropouts)
    over_sub = 1.0  # Gentle noise removal (was 1.5)
    spectral_floor = 0.15  # Keep at least 15% of original magnitude (was 0.08)

    mag_clean = np.copy(mag)
    for i in range(n_frames_stft):
        subtracted = mag[:, i] - over_sub * noise_floor
        floor = spectral_floor * mag[:, i]
        mag_clean[:, i] = np.maximum(subtracted, floor)

    # --- 3b. Harmonic enhancement ---
    # For voiced frames, identify harmonic peaks and boost them
    freq_bins = np.fft.rfftfreq(n_fft, d=1.0 / sr)

    for i in range(n_frames_stft):
        frame_mag = mag_clean[:, i]
        frame_energy = np.sum(frame_mag ** 2)
        if frame_energy < energy_threshold * 0.5:
            continue  # Skip very quiet frames

        # Estimate F0 from spectrum peak in voice range (80-300Hz)
        voice_mask = (freq_bins >= 80) & (freq_bins <= 300)
        voice_region = frame_mag.copy()
        voice_region[~voice_mask] = 0
        if np.max(voice_region) < eps:
            continue
        f0_idx = np.argmax(voice_region)
        f0_est = freq_bins[f0_idx]
        if f0_est < 80:
            continue

        # Create harmonic mask: boost bins near harmonics of F0
        harmonic_boost = np.ones_like(frame_mag)
        for h in range(1, 16):  # First 15 harmonics
            harmonic_freq = f0_est * h
            if harmonic_freq > sr / 2:
                break
            # Find bins within ±1 bin of the harmonic
            harmonic_bin = int(round(harmonic_freq / (sr / n_fft)))
            lo = max(0, harmonic_bin - 1)
            hi = min(len(frame_mag) - 1, harmonic_bin + 1)
            # Boost harmonic bins by 1.15x (subtle)
            harmonic_boost[lo:hi + 1] = 1.15

        mag_clean[:, i] *= harmonic_boost

    # Reconstruct
    stft_clean = mag_clean * np.exp(1j * phase)

    # Inverse STFT (overlap-add)
    output = np.zeros(len(padded))
    window_sum = np.zeros(len(padded))
    for i in range(n_frames_stft):
        frame = np.fft.irfft(stft_clean[:, i], n=n_fft) * window
        output[i * hop:i * hop + n_fft] += frame
        window_sum[i * hop:i * hop + n_fft] += window ** 2

    # Normalize by window overlap
    window_sum[window_sum < 1e-8] = 1.0
    output /= window_sum
    output = output[:len(samples)]

    # --- Loudness normalization with dynamic range compression ---
    # XTTS v2 outputs are typically very quiet (~-38 dBFS RMS) compared to
    # real voice recordings (~-20 dBFS RMS). Simple RMS scaling + peak limiting
    # fails because high crest factor (peak/RMS ratio) causes the limiter to
    # crush volume back down. Solution: compress dynamics first, then normalize.

    # Step 1: Soft-knee compressor to tame peaks
    # Process in short blocks to apply gain reduction smoothly
    block_size = int(0.01 * sr)  # 10ms blocks
    threshold_db = -20.0  # Start compressing above this level
    ratio = 4.0  # 4:1 compression ratio above threshold
    threshold_amp = 10 ** (threshold_db / 20.0)

    for start in range(0, len(output), block_size):
        end = min(start + block_size, len(output))
        block = output[start:end]
        block_peak = np.max(np.abs(block)) + eps
        if block_peak > threshold_amp:
            # How far above threshold in dB
            excess_db = 20.0 * np.log10(block_peak / threshold_amp)
            # Compressed excess
            compressed_excess_db = excess_db / ratio
            # Target peak
            target_peak_db = threshold_db + compressed_excess_db
            target_peak_amp = 10 ** (target_peak_db / 20.0)
            gain = target_peak_amp / block_peak
            output[start:end] *= gain

    # Step 2: RMS normalization to target loudness
    target_rms = 0.1  # ≈ -20 dBFS, matches typical voice recording levels
    output_rms = np.sqrt(np.mean(output ** 2)) + 1e-10
    if output_rms > 1e-8:
        output *= target_rms / output_rms

    # Step 3: Final peak limiter (should barely activate after compression)
    peak = np.max(np.abs(output))
    if peak > 0.95:
        output *= 0.95 / peak

    # Convert back to int16 and write
    output_int16 = np.clip(output * 32768.0, -32768, 32767).astype(np.int16)
    raw_out = struct.pack(f'<{len(output_int16)}h', *output_int16)

    with wave.open(wav_path, 'wb') as wf_out:
        wf_out.setparams(params)
        wf_out.writeframes(raw_out)

    print(f"[Coqui XTTS] Post-processed: bass {bass_boost_db:+.1f}dB, high {high_cut_db:+.1f}dB, spectral subtraction, harmonic enhancement")


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


def _load_model(args):
    """Load XTTS v2 model, apply GPU acceleration and inference params. Returns tts object."""
    print("[Coqui XTTS] Loading XTTS v2 model ...")

    # --- PyTorch 2.6+ compatibility fix ---
    import torch
    _original_torch_load = torch.load
    def _patched_torch_load(*a, **kw):
        kw["weights_only"] = False
        return _original_torch_load(*a, **kw)
    torch.load = _patched_torch_load
    print("[Coqui XTTS] Patched torch.load for PyTorch 2.6+ compatibility")

    try:
        from TTS.api import TTS
    except ImportError:
        print("ERROR: Coqui TTS not installed. Install with: pip install TTS", file=sys.stderr)
        sys.exit(1)

    tts = TTS("tts_models/multilingual/multi-dataset/xtts_v2")

    # Try GPU acceleration
    try:
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

    # --- Tune inference parameters ---
    try:
        model = tts.synthesizer.tts_model
        if hasattr(model, 'config') and hasattr(model.config, 'model_args'):
            model.config.model_args.temperature = args.temperature
            model.config.model_args.repetition_penalty = args.repetition_penalty
            model.config.model_args.top_k = 80
            model.config.model_args.top_p = args.top_p
            model.config.model_args.length_penalty = 1.0
            print(f"[Coqui XTTS] Set inference params: temperature={args.temperature}, "
                  f"repetition_penalty={args.repetition_penalty}, top_p={args.top_p}")
    except Exception as e:
        print(f"[Coqui XTTS] Could not set inference params: {e}")

    return tts


def generate_one(tts, text: str, speaker_wav: str, language: str, output_path: str, args):
    """Generate speech for a single text, handling chunking, concatenation, and post-processing."""
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)

    chunks = split_text_into_chunks(text, max_chars=220)
    print(f"[Coqui XTTS] Split into {len(chunks)} chunk(s)")

    if len(chunks) == 1:
        print(f"[Coqui XTTS] Generating speech ({len(chunks[0])} chars) ...")
        tts.tts_to_file(
            text=chunks[0],
            speaker_wav=speaker_wav,
            language=language,
            file_path=output_path,
        )
    else:
        chunk_paths = []
        tmp_dir = os.path.join(os.path.dirname(os.path.abspath(output_path)), "_tts_chunks")
        os.makedirs(tmp_dir, exist_ok=True)

        for i, chunk in enumerate(chunks):
            chunk_path = os.path.join(tmp_dir, f"chunk_{i:04d}.wav")
            print(f"[Coqui XTTS] Chunk {i+1}/{len(chunks)} ({len(chunk)} chars): {chunk[:60]}...")
            tts.tts_to_file(
                text=chunk,
                speaker_wav=speaker_wav,
                language=language,
                file_path=chunk_path,
            )
            if os.path.exists(chunk_path):
                chunk_paths.append(chunk_path)
            else:
                print(f"WARNING: Chunk {i+1} failed to generate, skipping.", file=sys.stderr)

        if not chunk_paths:
            print("ERROR: No audio chunks were generated.", file=sys.stderr)
            return False

        print(f"[Coqui XTTS] Concatenating {len(chunk_paths)} chunks ...")
        concatenate_wavs(chunk_paths, output_path)

        for cp in chunk_paths:
            try:
                os.remove(cp)
            except Exception:
                pass
        try:
            os.rmdir(tmp_dir)
        except Exception:
            pass

    if os.path.exists(output_path):
        try:
            post_process_audio(output_path, sample_rate=24000,
                               bass_boost_db=args.bass_boost_db,
                               high_cut_db=args.high_cut_db)
        except Exception as e:
            print(f"[Coqui XTTS] Post-processing skipped: {e}")

        size_kb = os.path.getsize(output_path) / 1024
        print(f"[Coqui XTTS] Success! Output: {output_path} ({size_kb:.1f} KB)")
        return True
    else:
        print("ERROR: Output file was not created.", file=sys.stderr)
        return False


def main():
    parser = argparse.ArgumentParser(description="Coqui XTTS v2 TTS wrapper")
    parser.add_argument("--text", type=str, default="", help="Text to speak")
    parser.add_argument("--text_file", type=str, default="", help="Path to text file (overrides --text)")
    parser.add_argument("--speaker_wav", type=str, required=True, help="Path to voice sample WAV")
    parser.add_argument("--output", type=str, required=True, help="Output audio file path (.wav)")
    parser.add_argument("--language", type=str, default="en", help="Language code (default: en)")
    parser.add_argument("--temperature", type=float, default=0.75, help="Expressiveness (0.1-1.0)")
    parser.add_argument("--repetition_penalty", type=float, default=1.8, help="Artifact control (1.0-5.0)")
    parser.add_argument("--top_p", type=float, default=0.95, help="Sampling breadth (0.5-1.0)")
    parser.add_argument("--bass_boost_db", type=float, default=1.0, help="Post-processing bass EQ dB")
    parser.add_argument("--high_cut_db", type=float, default=-0.5, help="Post-processing high-shelf EQ dB")
    parser.add_argument("--batch_json", type=str, default="",
                        help="Path to JSON file for batch mode: [{\"text_file\": ..., \"output\": ...}, ...]. "
                             "Model loads once and generates all items sequentially. Much faster for "
                             "multiple segments (e.g., presentation slides).")
    args = parser.parse_args()

    # ----------------------------------------------------------------
    # BATCH MODE: load model once, generate multiple outputs
    # ----------------------------------------------------------------
    if args.batch_json and os.path.exists(args.batch_json):
        with open(args.batch_json, "r", encoding="utf-8") as f:
            batch_items = json.load(f)

        print(f"[Coqui XTTS] BATCH MODE: {len(batch_items)} items to generate")
        print(f"[Coqui XTTS] Speaker WAV: {args.speaker_wav}")

        if not os.path.exists(args.speaker_wav):
            print(f"ERROR: Speaker WAV not found: {args.speaker_wav}", file=sys.stderr)
            sys.exit(1)

        # Load model ONCE
        tts = _load_model(args)

        results = {"success": [], "failed": []}
        for i, item in enumerate(batch_items):
            text_file = item.get("text_file", "")
            output = item.get("output", "")
            label = item.get("label", f"item {i+1}")

            if not text_file or not os.path.exists(text_file):
                print(f"\n[Coqui XTTS] Batch {i+1}/{len(batch_items)}: SKIPPED (text_file missing: {text_file})")
                results["failed"].append(output)
                continue

            with open(text_file, "r", encoding="utf-8") as tf:
                text = tf.read().strip()

            if not text:
                print(f"\n[Coqui XTTS] Batch {i+1}/{len(batch_items)}: SKIPPED (empty text)")
                results["failed"].append(output)
                continue

            print(f"\n[Coqui XTTS] Batch {i+1}/{len(batch_items)} — {label} ({len(text):,} chars)")
            ok = generate_one(tts, text, args.speaker_wav, args.language, output, args)
            if ok:
                results["success"].append(output)
            else:
                results["failed"].append(output)

        # Write results JSON so the caller knows what succeeded
        results_path = args.batch_json.replace(".json", "_results.json")
        with open(results_path, "w") as rf:
            json.dump(results, rf, indent=2)

        print(f"\n[Coqui XTTS] Batch complete: {len(results['success'])} succeeded, "
              f"{len(results['failed'])} failed")
        if results["failed"]:
            sys.exit(1)
        sys.exit(0)

    # ----------------------------------------------------------------
    # SINGLE MODE: original behavior
    # ----------------------------------------------------------------
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

    tts = _load_model(args)

    ok = generate_one(tts, text, args.speaker_wav, args.language, args.output, args)
    if not ok:
        sys.exit(1)


if __name__ == "__main__":
    main()
