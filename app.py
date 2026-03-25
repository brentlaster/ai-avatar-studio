"""
AI Avatar Studio v2 - Gradio Web UI
Hybrid version: ElevenLabs voice + D-ID or SadTalker video.
"""

import os
import re
import gradio as gr
from pathlib import Path
from pipeline import (
    create_avatar_video,
    create_audio_only,
    get_builtin_voices,
    extract_preview_frames,
    check_sadtalker_native,
    clone_voice,
    extract_audio_from_video,
    AvatarConfig,
    OUTPUT_DIR,
)
from presentation import generate_presentation, build_script_viewer_html
import config as _config
from config import set_api_key
import json
import shutil

# ---------------------------------------------------------------------------
# Last-used file persistence
# ---------------------------------------------------------------------------

_LAST_FILES_JSON = os.path.join(os.path.dirname(__file__), "temp", "last_files.json")
_LAST_FILES_DIR = os.path.join(os.path.dirname(__file__), "temp", "last_uploads")


def _ensure_dirs():
    os.makedirs(os.path.dirname(_LAST_FILES_JSON), exist_ok=True)
    os.makedirs(_LAST_FILES_DIR, exist_ok=True)


def _save_last_files(tab: str, files_dict: dict):
    """Persist file paths for a tab (avatar or presentation)."""
    _ensure_dirs()
    # Load existing
    data = {}
    if os.path.exists(_LAST_FILES_JSON):
        try:
            with open(_LAST_FILES_JSON, "r") as f:
                data = json.load(f)
        except Exception:
            data = {}

    # Copy files to persistent location so Gradio temp-dir cleanup doesn't delete them
    # Text values (like script_text) are saved as .txt files
    saved = {}
    for key, value in files_dict.items():
        if not value:
            continue
        if key.endswith("_text"):
            # It's a text value, not a file path — save as .txt
            dest = os.path.join(_LAST_FILES_DIR, f"{tab}_{key}.txt")
            try:
                with open(dest, "w", encoding="utf-8") as tf:
                    tf.write(value)
                saved[key] = dest
            except Exception:
                pass
        elif os.path.exists(value):
            dest = os.path.join(_LAST_FILES_DIR, f"{tab}_{key}_{os.path.basename(value)}")
            try:
                shutil.copy2(value, dest)
                saved[key] = dest
            except Exception:
                pass

    data[tab] = saved
    with open(_LAST_FILES_JSON, "w") as f:
        json.dump(data, f, indent=2)


def _load_last_files(tab: str) -> dict:
    """Load previously saved file paths (or text values) for a tab."""
    if not os.path.exists(_LAST_FILES_JSON):
        return {}
    try:
        with open(_LAST_FILES_JSON, "r") as f:
            data = json.load(f)
        result = {}
        for key, path in data.get(tab, {}).items():
            if not path or not os.path.exists(path):
                continue
            if key.endswith("_text"):
                # Read text content back from the saved .txt file
                with open(path, "r", encoding="utf-8") as tf:
                    result[key] = tf.read()
            else:
                result[key] = path
        return result
    except Exception:
        return {}


def _get_last_files_summary(tab: str) -> str:
    """Return a markdown summary of what files are saved."""
    files = _load_last_files(tab)
    if not files:
        return "No previously used files found."
    parts = []
    for key, path in files.items():
        name = os.path.basename(path)
        # Remove the tab_key_ prefix from displayed name
        display_name = name
        prefix = f"{tab}_{key}_"
        if display_name.startswith(prefix):
            display_name = display_name[len(prefix):]
        parts.append(f"**{key}**: {display_name}")
    return "Last used: " + " · ".join(parts)


# ---------------------------------------------------------------------------
# Presets for quick configuration
# ---------------------------------------------------------------------------

PRESETS = {
    "Expressive (recommended)": {
        "voice_stability": 0.20,
        "voice_similarity": 0.75,
        "voice_style": 0.65,
        "voice_speaker_boost": True,
        "sadtalker_still": False,
        "sadtalker_preprocess": "full",
        "sadtalker_size": "512",
        "sadtalker_enhancer": "GFPGAN",
        "expression_scale": 1.5,
        "pose_style": 0,
    },
    "Balanced": {
        "voice_stability": 0.35,
        "voice_similarity": 0.80,
        "voice_style": 0.45,
        "voice_speaker_boost": True,
        "sadtalker_still": False,
        "sadtalker_preprocess": "crop",
        "sadtalker_size": "256",
        "sadtalker_enhancer": "GFPGAN",
        "expression_scale": 1.2,
        "pose_style": 0,
    },
    "Conservative (stable)": {
        "voice_stability": 0.50,
        "voice_similarity": 0.85,
        "voice_style": 0.25,
        "voice_speaker_boost": True,
        "sadtalker_still": True,
        "sadtalker_preprocess": "crop",
        "sadtalker_size": "256",
        "sadtalker_enhancer": "GFPGAN",
        "expression_scale": 1.0,
        "pose_style": 0,
    },
    "Fast test (low quality)": {
        "voice_stability": 0.35,
        "voice_similarity": 0.75,
        "voice_style": 0.45,
        "voice_speaker_boost": True,
        "sadtalker_still": True,
        "sadtalker_preprocess": "crop",
        "sadtalker_size": "256",
        "sadtalker_enhancer": "None",
        "expression_scale": 1.0,
        "pose_style": 0,
    },
}


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def check_api_keys():
    """Return a status message about API key configuration."""
    issues = []
    if not _config.ELEVENLABS_API_KEY or _config.ELEVENLABS_API_KEY.startswith("your-"):
        issues.append("ElevenLabs API key not set")
    if not _config.DID_API_KEY or _config.DID_API_KEY.startswith("your-"):
        issues.append("D-ID API key not set (only needed for D-ID backend)")

    if issues:
        return f"**Note:** {', '.join(issues)}. Set them in the **Settings** tab, in `config.py`, or as environment variables."
    return "**API keys configured.** Ready to generate."


def check_sadtalker_status():
    """Check if native SadTalker conda environment is available."""
    if check_sadtalker_native():
        return "SadTalker: **ready** (native conda environment found)"
    return "SadTalker: **not set up yet** — run `bash setup_sadtalker_native.sh` first"


def load_voice_choices():
    """Fetch available ElevenLabs voices for the dropdown."""
    try:
        voices = get_builtin_voices()
        choices = [(f"{v['name']} ({v['category']})", v["voice_id"]) for v in voices]
        return choices
    except Exception:
        return [("(Could not load voices - check API key)", "")]


def strip_markdown(text: str) -> str:
    """
    Strip common Markdown formatting from text, leaving clean prose
    suitable for text-to-speech.
    """
    # Remove YAML front matter (--- ... ---)
    text = re.sub(r'^---\s*\n.*?\n---\s*\n', '', text, flags=re.DOTALL)

    # Remove HTML tags
    text = re.sub(r'<[^>]+>', '', text)

    # Remove images ![alt](url)
    text = re.sub(r'!\[([^\]]*)\]\([^)]+\)', r'\1', text)

    # Convert links [text](url) to just text
    text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)

    # Remove reference-style link definitions [label]: url
    text = re.sub(r'^\[[^\]]+\]:\s+.*$', '', text, flags=re.MULTILINE)

    # Remove headings (# ## ### etc.) but keep the text
    text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)

    # Remove bold/italic markers
    text = re.sub(r'\*{1,3}([^*]+)\*{1,3}', r'\1', text)
    text = re.sub(r'_{1,3}([^_]+)_{1,3}', r'\1', text)

    # Remove strikethrough
    text = re.sub(r'~~([^~]+)~~', r'\1', text)

    # Remove inline code backticks
    text = re.sub(r'`([^`]+)`', r'\1', text)

    # Remove code blocks (``` ... ```)
    text = re.sub(r'```[\s\S]*?```', '', text)

    # Remove blockquote markers
    text = re.sub(r'^>\s+', '', text, flags=re.MULTILINE)

    # Remove horizontal rules
    text = re.sub(r'^[-*_]{3,}\s*$', '', text, flags=re.MULTILINE)

    # Remove bullet/list markers (-, *, numbered)
    text = re.sub(r'^[\s]*[-*+]\s+', '', text, flags=re.MULTILINE)
    text = re.sub(r'^[\s]*\d+\.\s+', '', text, flags=re.MULTILINE)

    # Remove table formatting
    text = re.sub(r'\|', ' ', text)
    text = re.sub(r'^[\s]*[-:]+[\s]*$', '', text, flags=re.MULTILINE)

    # Collapse multiple blank lines into one
    text = re.sub(r'\n{3,}', '\n\n', text)

    return text.strip()


def read_script_file(file_path: str) -> str:
    """Read a script file and optionally strip markdown."""
    if file_path is None:
        return ""

    path = Path(file_path)
    try:
        content = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        content = path.read_text(encoding="latin-1")

    # Auto-strip markdown for .md files
    if path.suffix.lower() == ".md":
        content = strip_markdown(content)

    return content.strip()


def generate_frame_previews(source_video):
    """Extract preview frames from uploaded video."""
    if source_video is None:
        return [], gr.update(choices=[], visible=False)

    frames = extract_preview_frames(source_video, num_frames=6)
    if not frames:
        return [], gr.update(choices=[], visible=False)

    gallery_images = []
    choices = []
    for ts, path in frames:
        gallery_images.append((path, f"{ts:.1f}s"))
        choices.append((f"Frame at {ts:.1f}s", str(ts)))

    return gallery_images, gr.update(choices=choices, value=choices[0][1], visible=True)


def on_script_file_upload(file_path):
    """When a script file is dropped/uploaded, read it and populate the text box."""
    if file_path is None:
        return gr.update(), ""
    text = read_script_file(file_path)
    filename = Path(file_path).name
    suffix = Path(file_path).suffix.lower()
    if suffix == ".md":
        info = f"Loaded **{filename}** (Markdown stripped automatically)"
    else:
        info = f"Loaded **{filename}**"
    return gr.update(value=text), info


def apply_preset(preset_name):
    """Apply a preset configuration, returning updates for all affected controls."""
    p = PRESETS.get(preset_name, PRESETS["Expressive (recommended)"])
    return (
        gr.update(value=p["voice_stability"]),
        gr.update(value=p["voice_similarity"]),
        gr.update(value=p["voice_style"]),
        gr.update(value=p["voice_speaker_boost"]),
        gr.update(value=p["sadtalker_still"]),
        gr.update(value=p["sadtalker_preprocess"]),
        gr.update(value=p["sadtalker_size"]),
        gr.update(value=p["sadtalker_enhancer"]),
        gr.update(value=p["expression_scale"]),
        gr.update(value=p["pose_style"]),
    )


def _truncate_script_to_duration(script_text: str, max_length_label: str) -> str:
    """Truncate script text to approximately match a target duration.

    Uses ~150 words per minute / ~900 characters per minute as the estimate.
    Truncation happens at the last sentence boundary before the limit.
    """
    if not max_length_label or max_length_label == "No limit":
        return script_text

    # Parse minutes from the label
    import re as _re
    m = _re.search(r'(\d+)\s*minute', max_length_label)
    if not m:
        return script_text

    minutes = int(m.group(1))
    max_chars = minutes * 900  # ~150 words/min, avg 6 chars/word

    if len(script_text) <= max_chars:
        return script_text

    # Truncate at the last sentence boundary before the limit
    truncated = script_text[:max_chars]
    # Find last sentence-ending punctuation
    last_period = max(truncated.rfind('. '), truncated.rfind('.\n'),
                      truncated.rfind('? '), truncated.rfind('?\n'),
                      truncated.rfind('! '), truncated.rfind('!\n'))
    if last_period > max_chars * 0.5:
        truncated = truncated[:last_period + 1]

    print(f"      Script truncated to ~{minutes} min: {len(script_text):,} → {len(truncated):,} chars")
    return truncated


def run_pipeline(
    source_video,
    script_text,
    avatar_image,
    selected_frame_ts,
    tts_engine,
    voice_mode,
    builtin_voice_id,
    voice_name,
    voice_model,
    voice_stability,
    voice_similarity,
    voice_style,
    voice_speaker_boost,
    coqui_temperature,
    coqui_repetition_penalty,
    coqui_top_p,
    coqui_bass_boost,
    coqui_high_cut,
    video_backend,
    sadtalker_enhancer,
    sadtalker_still,
    sadtalker_size,
    sadtalker_preprocess,
    expression_scale,
    pose_style,
    audio_only_toggle,
    max_length_label,
    progress=gr.Progress(),
):
    """Gradio callback: runs the full pipeline."""
    if not script_text or not script_text.strip():
        raise gr.Error("Please enter a script for your avatar to speak.")

    # Apply max length truncation
    script_text = _truncate_script_to_duration(script_text.strip(), max_length_label)

    # Determine TTS engine key from display label
    tts_key = "coqui_xtts" if "Coqui" in (tts_engine or "") else "elevenlabs"

    if tts_key == "elevenlabs" and voice_mode == "Clone my voice (paid plan)" and source_video is None:
        raise gr.Error("Please upload a source video for voice cloning.")

    if tts_key == "coqui_xtts" and source_video is None:
        raise gr.Error("Please upload a source video — Coqui XTTS needs a voice sample for cloning.")

    if not audio_only_toggle and source_video is None and avatar_image is None:
        raise gr.Error("Please upload a source video or avatar photo for video generation.")

    # Extract voice sample for Coqui XTTS
    voice_sample = None
    if tts_key == "coqui_xtts" and source_video:
        voice_sample = extract_audio_from_video(source_video)

    config = AvatarConfig(
        tts_engine=tts_key,
        voice_model=voice_model,
        voice_stability=voice_stability,
        voice_similarity=voice_similarity,
        voice_style=voice_style,
        voice_speaker_boost=voice_speaker_boost,
        coqui_temperature=float(coqui_temperature),
        coqui_repetition_penalty=float(coqui_repetition_penalty),
        coqui_top_p=float(coqui_top_p),
        coqui_bass_boost_db=float(coqui_bass_boost),
        coqui_high_cut_db=float(coqui_high_cut),
        voice_sample_path=voice_sample,
        video_backend=video_backend.lower(),
        sadtalker_enhancer=sadtalker_enhancer.lower() if sadtalker_enhancer else "gfpgan",
        sadtalker_still=sadtalker_still,
        sadtalker_size=int(sadtalker_size) if sadtalker_size else 512,
        sadtalker_preprocess=sadtalker_preprocess.lower() if sadtalker_preprocess else "full",
        sadtalker_expression_scale=expression_scale,
        sadtalker_pose_style=pose_style,
    )

    img_path = avatar_image if avatar_image else None
    use_builtin = None

    frame_ts = 1.0
    if selected_frame_ts:
        try:
            frame_ts = float(selected_frame_ts)
        except (ValueError, TypeError):
            frame_ts = 1.0

    if tts_key == "elevenlabs" and voice_mode == "Use built-in voice (free tier)":
        if not builtin_voice_id or builtin_voice_id == "":
            raise gr.Error("Please select a built-in voice from the dropdown.")
        use_builtin = builtin_voice_id

    # Save last-used files for "Use Last Files" button
    _save_last_files("avatar", {
        "source_video": source_video or "",
        "script_text": script_text.strip() if script_text else "",
        "avatar_image": avatar_image or "",
    })

    progress(0.1, desc="Starting pipeline ...")

    try:
        if audio_only_toggle:
            output_path = create_audio_only(
                source_video=source_video if source_video else "",
                script_text=script_text.strip(),
                config=config,
                voice_name=voice_name,
                use_builtin_voice=use_builtin,
            )
            return output_path
        else:
            output_path = create_avatar_video(
                source_video=source_video if source_video else "",
                script_text=script_text.strip(),
                config=config,
                avatar_image=img_path,
                frame_timestamp=frame_ts,
                voice_name=voice_name,
                use_builtin_voice=use_builtin,
            )
            return output_path
    except ValueError as e:
        raise gr.Error(str(e))
    except Exception as e:
        raise gr.Error(f"Pipeline error: {str(e)}")


# ---------------------------------------------------------------------------
# Build the Gradio UI
# ---------------------------------------------------------------------------

with gr.Blocks(
    title="AI Avatar Studio v2",
    theme=gr.themes.Soft(primary_hue="blue"),
) as demo:

    gr.Markdown(
        f"""
        # AI Avatar Studio v2

        Create a talking avatar video or clone-voice audio using
        **ElevenLabs** (voice) and your choice of video backend.

        {check_api_keys()}

        {check_sadtalker_status()}
        """
    )

    with gr.Tabs():

        # ==============================================================
        # TAB 1: Avatar Mode (existing functionality)
        # ==============================================================
        with gr.TabItem("Avatar Mode"):
            with gr.Row():
                tts_engine_selector = gr.Radio(
                    choices=[
                        "Coqui XTTS v2 (free, local voice cloning)",
                        "ElevenLabs (API, paid)",
                    ],
                    value="Coqui XTTS v2 (free, local voice cloning)",
                    label="TTS Engine",
                )
                audio_only_toggle = gr.Checkbox(
                    label="Audio Only Mode  (generate speech without video — fast, no limits)",
                    value=False,
                    elem_id="audio-only-toggle",
                )
                preset_selector = gr.Dropdown(
                    choices=list(PRESETS.keys()),
                    value="Expressive (recommended)",
                    label="Quick Preset",
                    interactive=True,
                )
                max_length = gr.Dropdown(
                    choices=[
                        "No limit",
                        "1 minute (~150 words)",
                        "2 minutes (~300 words)",
                        "5 minutes (~750 words)",
                        "10 minutes (~1,500 words)",
                        "30 minutes (~4,500 words)",
                    ],
                    value="No limit",
                    label="Max Length",
                    interactive=True,
                )

            with gr.Row():
                use_last_btn_avatar = gr.Button("📂 Use Last Files", size="sm")
                last_files_info_avatar = gr.Markdown(_get_last_files_summary("avatar"))

            gr.Markdown("---")

            with gr.Row():
                # ---- Left column: Inputs ----
                with gr.Column(scale=1):
                    gr.Markdown("### Inputs")

                    source_video = gr.Video(
                        label="Source Video (for voice cloning and/or avatar frame)",
                        sources=["upload"],
                    )

                    # --- Script Section ---
                    gr.Markdown("### Script")

                    script_file = gr.File(
                        label="Drop a script file here (.txt, .md, or .text)",
                        file_types=[".txt", ".md", ".text", ".rst"],
                        type="filepath",
                    )
                    script_file_info = gr.Markdown("")

                    script_text = gr.Textbox(
                        label="Script text",
                        placeholder=(
                            "Type or paste your script here ...\n"
                            "Or drag & drop a .txt / .md file above (Markdown is auto-stripped)."
                        ),
                        lines=8,
                        max_lines=30,
                    )

                    avatar_image = gr.Image(
                        label="Avatar Photo (optional - overrides frame from video)",
                        type="filepath",
                        sources=["upload"],
                    )

                    # --- Frame Preview ---
                    gr.Markdown("### Frame Preview")
                    gr.Markdown(
                        "*Upload a video above, then click **Preview Frames** "
                        "to pick the best frame (eyes open, good expression).*"
                    )
                    preview_btn = gr.Button("Preview Frames", size="sm")
                    frame_gallery = gr.Gallery(
                        label="Candidate frames",
                        columns=3, rows=2, height="auto", object_fit="contain",
                    )
                    selected_frame_ts = gr.Dropdown(
                        label="Selected frame",
                        choices=[], visible=False, interactive=True,
                    )
                    preview_btn.click(
                        fn=generate_frame_previews,
                        inputs=[source_video],
                        outputs=[frame_gallery, selected_frame_ts],
                    )

                    # --- Video Backend (hidden in audio-only mode) ---
                    video_settings_group = gr.Group(visible=True)
                    with video_settings_group:
                        gr.Markdown("### Video Backend")
                        video_backend = gr.Radio(
                            choices=["SadTalker", "D-ID"],
                            value="SadTalker",
                            label="Video generation engine",
                        )

                        with gr.Accordion("SadTalker Settings", open=True):
                            sadtalker_enhancer = gr.Radio(
                                choices=["GFPGAN", "None"],
                                value="GFPGAN",
                                label="Face enhancer (GFPGAN improves quality, takes longer)",
                            )
                            sadtalker_still = gr.Checkbox(
                                label="Still mode (less head motion — turn OFF for more expression)",
                                value=False,
                            )
                            sadtalker_preprocess = gr.Radio(
                                choices=["full", "crop", "resize"],
                                value="full",
                                label="Preprocess (full = natural movement, crop = tighter face)",
                            )
                            sadtalker_size = gr.Radio(
                                choices=["256", "512"],
                                value="512",
                                label="Output face resolution",
                            )
                            expression_scale = gr.Slider(
                                minimum=0.5, maximum=3.0, value=1.5, step=0.1,
                                label="Expression intensity (1.0 = default, higher = more expressive)",
                            )
                            pose_style = gr.Slider(
                                minimum=0, maximum=45, value=0, step=1,
                                label="Pose style (0-45 — different head movement patterns, try a few!)",
                            )

                    # --- Voice Section ---
                    gr.Markdown("### Voice")
                    voice_mode = gr.Radio(
                        choices=[
                            "Use built-in voice (free tier)",
                            "Clone my voice (paid plan)",
                        ],
                        value="Clone my voice (paid plan)",
                        label="Voice mode",
                    )

                    builtin_voice_dropdown = gr.Dropdown(
                        choices=load_voice_choices(),
                        label="Built-in voice",
                        interactive=True, visible=False,
                    )
                    refresh_voices_btn = gr.Button(
                        "Refresh voice list", size="sm", visible=False,
                    )

                    with gr.Accordion("ElevenLabs Voice Settings", open=False):
                        gr.Markdown("*These settings only apply when using the ElevenLabs TTS engine.*")
                        voice_model = gr.Dropdown(
                            choices=[
                                ("Multilingual v2 (best quality)", "eleven_multilingual_v2"),
                                ("Turbo v2.5 (faster, natural English)", "eleven_turbo_v2_5"),
                                ("Monolingual v1 (English only, classic)", "eleven_monolingual_v1"),
                            ],
                            value="eleven_multilingual_v2",
                            label="Voice model",
                            interactive=True,
                        )
                        voice_name = gr.Textbox(
                            label="Clone voice name (for ElevenLabs library)",
                            value="My Avatar Voice",
                        )
                        voice_stability = gr.Slider(
                            minimum=0.0, maximum=1.0, value=0.20, step=0.05,
                            label="Stability (lower = more expressive, higher = more consistent)",
                        )
                        voice_similarity = gr.Slider(
                            minimum=0.0, maximum=1.0, value=0.75, step=0.05,
                            label="Similarity (how close to the original voice)",
                        )
                        voice_style = gr.Slider(
                            minimum=0.0, maximum=1.0, value=0.65, step=0.05,
                            label="Style exaggeration (adds emotion and dynamics)",
                        )
                        voice_speaker_boost = gr.Checkbox(
                            label="Speaker boost (enhances clarity and presence)",
                            value=True,
                        )

                    with gr.Accordion("Coqui XTTS Voice Settings", open=False):
                        gr.Markdown("*These settings only apply when using the Coqui XTTS v2 engine.*")
                        coqui_temperature = gr.Slider(
                            minimum=0.1, maximum=1.0, value=0.75, step=0.05,
                            label="Temperature (expressiveness)",
                            info="Lower = stable/monotone, higher = expressive/varied pitch",
                        )
                        coqui_repetition_penalty = gr.Slider(
                            minimum=1.0, maximum=5.0, value=1.8, step=0.1,
                            label="Repetition penalty",
                            info="Higher = fewer artifacts but less natural prosody",
                        )
                        coqui_top_p = gr.Slider(
                            minimum=0.5, maximum=1.0, value=0.95, step=0.05,
                            label="Top P (sampling breadth)",
                            info="Higher = more varied/natural, lower = more consistent",
                        )
                        coqui_bass_boost = gr.Slider(
                            minimum=-3.0, maximum=6.0, value=1.0, step=0.5,
                            label="Bass boost (dB)",
                            info="Post-processing EQ below 250Hz. Adds warmth/chest resonance.",
                        )
                        coqui_high_cut = gr.Slider(
                            minimum=-6.0, maximum=3.0, value=-0.5, step=0.5,
                            label="High shelf (dB)",
                            info="Post-processing EQ above 4kHz. Negative = reduce brightness/thinness.",
                        )

                    generate_btn = gr.Button(
                        "Generate",
                        variant="primary",
                        size="lg",
                    )

                    # --- Dynamic UI toggles ---
                    def toggle_voice_ui(mode):
                        is_builtin = mode == "Use built-in voice (free tier)"
                        return (
                            gr.update(visible=is_builtin),
                            gr.update(visible=is_builtin),
                        )

                    voice_mode.change(
                        fn=toggle_voice_ui,
                        inputs=[voice_mode],
                        outputs=[builtin_voice_dropdown, refresh_voices_btn],
                    )

                    def refresh_voices():
                        return gr.update(choices=load_voice_choices())

                    refresh_voices_btn.click(
                        fn=refresh_voices,
                        outputs=[builtin_voice_dropdown],
                    )

                    def toggle_audio_only(is_audio_only):
                        return gr.update(visible=not is_audio_only)

                    audio_only_toggle.change(
                        fn=toggle_audio_only,
                        inputs=[audio_only_toggle],
                        outputs=[video_settings_group],
                    )

                    script_file.change(
                        fn=on_script_file_upload,
                        inputs=[script_file],
                        outputs=[script_text, script_file_info],
                    )

                    preset_selector.change(
                        fn=apply_preset,
                        inputs=[preset_selector],
                        outputs=[
                            voice_stability,
                            voice_similarity,
                            voice_style,
                            voice_speaker_boost,
                            sadtalker_still,
                            sadtalker_preprocess,
                            sadtalker_size,
                            sadtalker_enhancer,
                            expression_scale,
                            pose_style,
                        ],
                    )

                    # --- "Use Last Files" handler ---
                    def load_last_avatar_files():
                        files = _load_last_files("avatar")
                        summary = _get_last_files_summary("avatar")
                        return (
                            gr.update(value=files.get("source_video")),
                            gr.update(value=files.get("script_text", "")),
                            gr.update(value=files.get("avatar_image")),
                            summary,
                        )

                    use_last_btn_avatar.click(
                        fn=load_last_avatar_files,
                        outputs=[source_video, script_text, avatar_image, last_files_info_avatar],
                    )

                # ---- Right column: Output ----
                with gr.Column(scale=1):
                    gr.Markdown("### Output")
                    output_video = gr.Video(label="Your Avatar Video / Audio")

                    gr.Markdown(
                        """
                        ---
                        **Tips:**
                        - **Presets** at the top quickly configure voice + video settings
                        - **Expression intensity** > 1.0 amplifies facial movements
                        - **Pose style** 0-45 gives different head movement patterns
                        - **Stability** 0.15-0.25 = dynamic voice; 0.50+ = consistent
                        - **Style** 0.60-0.75 adds strong emotion to speech
                        - Drop a **.md** file to auto-strip Markdown for clean speech
                        - **Audio Only** mode is great for long-form content
                        """
                    )

            generate_btn.click(
                fn=run_pipeline,
                inputs=[
                    source_video,
                    script_text,
                    avatar_image,
                    selected_frame_ts,
                    tts_engine_selector,
                    voice_mode,
                    builtin_voice_dropdown,
                    voice_name,
                    voice_model,
                    voice_stability,
                    voice_similarity,
                    voice_style,
                    voice_speaker_boost,
                    coqui_temperature,
                    coqui_repetition_penalty,
                    coqui_top_p,
                    coqui_bass_boost,
                    coqui_high_cut,
                    video_backend,
                    sadtalker_enhancer,
                    sadtalker_still,
                    sadtalker_size,
                    sadtalker_preprocess,
                    expression_scale,
                    pose_style,
                    audio_only_toggle,
                    max_length,
                ],
                outputs=output_video,
            )

        # ==============================================================
        # TAB 2: Presentation Mode
        # ==============================================================
        with gr.TabItem("Presentation Mode"):
            gr.Markdown(
                """
                ### Presentation Recorder

                Upload a **PowerPoint deck** and a **speaker script** with `[SLIDE N]`
                markers. Each slide will be displayed as a full-screen image while your
                cloned voice narrates the corresponding section.

                **Script format:**
                ```
                [SLIDE 1]
                Welcome everyone! Today we'll be talking about context engineering...

                [SLIDE 2]
                Let's start with the key insight. As you can see on this slide...

                [SLIDE 3]
                Moving on to the data. These numbers show a clear trend...
                ```
                """
            )

            with gr.Row():
                use_last_btn_pres = gr.Button("📂 Use Last Files", size="sm")
                last_files_info_pres = gr.Markdown(_get_last_files_summary("presentation"))

            with gr.Row():
                with gr.Column(scale=1):
                    pres_source_video = gr.Video(
                        label="Source Video (for voice cloning)",
                        sources=["upload"],
                    )

                    pres_pptx_file = gr.File(
                        label="PowerPoint Deck (.pptx)",
                        file_types=[".pptx"],
                        type="filepath",
                    )

                    pres_script_file = gr.File(
                        label="Speaker Script (.md or .txt with [SLIDE N] markers)",
                        file_types=[".txt", ".md", ".text"],
                        type="filepath",
                    )
                    pres_script_info = gr.Markdown("")

                    pres_script_text = gr.Textbox(
                        label="Speaker script",
                        placeholder=(
                            "[SLIDE 1]\n"
                            "Welcome everyone! Today we'll talk about...\n\n"
                            "[SLIDE 2]\n"
                            "Let's start with the first topic..."
                        ),
                        lines=12,
                        max_lines=40,
                    )

                    # TTS engine for presentation mode
                    pres_tts_engine = gr.Radio(
                        choices=[
                            "Coqui XTTS v2 (free, local voice cloning)",
                            "ElevenLabs (API, paid)",
                        ],
                        value="Coqui XTTS v2 (free, local voice cloning)",
                        label="TTS Engine",
                    )

                    # ElevenLabs-specific voice settings (hidden when using Coqui)
                    pres_elevenlabs_settings = gr.Group(visible=False)
                    with pres_elevenlabs_settings:
                        pres_voice_mode = gr.Radio(
                            choices=[
                                "Use built-in voice (free tier)",
                                "Clone my voice (paid plan)",
                            ],
                            value="Clone my voice (paid plan)",
                            label="ElevenLabs Voice mode",
                        )

                        pres_builtin_voice = gr.Dropdown(
                            choices=load_voice_choices(),
                            label="Built-in voice",
                            interactive=True, visible=False,
                        )

                    with gr.Accordion("ElevenLabs Voice Settings", open=False):
                        gr.Markdown("*These settings only apply when using the ElevenLabs TTS engine.*")
                        pres_voice_model = gr.Dropdown(
                            choices=[
                                ("Multilingual v2 (best quality)", "eleven_multilingual_v2"),
                                ("Turbo v2.5 (faster, natural English)", "eleven_turbo_v2_5"),
                                ("Monolingual v1 (English only, classic)", "eleven_monolingual_v1"),
                            ],
                            value="eleven_multilingual_v2",
                            label="Voice model",
                            interactive=True,
                        )
                        pres_voice_name = gr.Textbox(
                            label="Clone voice name",
                            value="My Presentation Voice",
                        )
                        pres_stability = gr.Slider(
                            minimum=0.0, maximum=1.0, value=0.50, step=0.05,
                            label="Stability (higher = cleaner, fewer filler words)",
                        )
                        pres_similarity = gr.Slider(
                            minimum=0.0, maximum=1.0, value=0.80, step=0.05,
                            label="Similarity",
                        )
                        pres_style = gr.Slider(
                            minimum=0.0, maximum=1.0, value=0.20, step=0.05,
                            label="Style exaggeration (lower = fewer um's and uh's)",
                        )
                        pres_speaker_boost = gr.Checkbox(
                            label="Speaker boost",
                            value=True,
                        )

                    with gr.Accordion("Coqui XTTS Voice Settings", open=False):
                        gr.Markdown("*These settings only apply when using the Coqui XTTS v2 engine.*")
                        pres_coqui_temperature = gr.Slider(
                            minimum=0.1, maximum=1.0, value=0.75, step=0.05,
                            label="Temperature (expressiveness)",
                            info="Lower = stable/monotone, higher = expressive/varied pitch",
                        )
                        pres_coqui_repetition_penalty = gr.Slider(
                            minimum=1.0, maximum=5.0, value=1.8, step=0.1,
                            label="Repetition penalty",
                            info="Higher = fewer artifacts but less natural prosody",
                        )
                        pres_coqui_top_p = gr.Slider(
                            minimum=0.5, maximum=1.0, value=0.95, step=0.05,
                            label="Top P (sampling breadth)",
                            info="Higher = more varied/natural, lower = more consistent",
                        )
                        pres_coqui_bass_boost = gr.Slider(
                            minimum=-3.0, maximum=6.0, value=1.0, step=0.5,
                            label="Bass boost (dB)",
                            info="Post-processing EQ below 250Hz. Adds warmth/chest resonance.",
                        )
                        pres_coqui_high_cut = gr.Slider(
                            minimum=-6.0, maximum=3.0, value=-0.5, step=0.5,
                            label="High shelf (dB)",
                            info="Post-processing EQ above 4kHz. Negative = reduce brightness/thinness.",
                        )

                    with gr.Row():
                        pres_start_slide = gr.Number(
                            label="Start slide (optional)",
                            value=0,
                            precision=0,
                            minimum=0,
                            info="0 = from beginning",
                        )
                        pres_end_slide = gr.Number(
                            label="End slide (optional)",
                            value=0,
                            precision=0,
                            minimum=0,
                            info="0 = to end",
                        )

                    with gr.Row():
                        pres_output_name = gr.Textbox(
                            label="Output name (optional)",
                            placeholder="e.g. context-engineering-talk",
                            info="Letters, numbers, dashes. Used for the video filename and viewer URL.",
                            scale=3,
                        )
                        pres_overwrite = gr.Checkbox(
                            label="Overwrite if exists",
                            value=False,
                            scale=1,
                        )

                    pres_generate_btn = gr.Button(
                        "Generate Presentation Video",
                        variant="primary",
                        size="lg",
                    )

                    # Toggle ElevenLabs settings visibility based on TTS engine
                    def toggle_pres_tts_engine(engine):
                        is_elevenlabs = "ElevenLabs" in (engine or "")
                        return gr.update(visible=is_elevenlabs)

                    pres_tts_engine.change(
                        fn=toggle_pres_tts_engine,
                        inputs=[pres_tts_engine],
                        outputs=[pres_elevenlabs_settings],
                    )

                    # Toggle voice UI within ElevenLabs settings
                    def toggle_pres_voice(mode):
                        return gr.update(visible=mode == "Use built-in voice (free tier)")

                    pres_voice_mode.change(
                        fn=toggle_pres_voice,
                        inputs=[pres_voice_mode],
                        outputs=[pres_builtin_voice],
                    )

                    # Wire up script file upload (with markdown stripping)
                    def on_pres_script_upload(file_path):
                        if file_path is None:
                            return gr.update(), ""
                        text = read_script_file(file_path)
                        filename = Path(file_path).name
                        suffix = Path(file_path).suffix.lower()
                        # For presentation scripts, DON'T strip [SLIDE N] markers
                        # Re-read raw if it's an .md file (strip_markdown would remove them)
                        if suffix == ".md":
                            raw = Path(file_path).read_text(encoding="utf-8")
                            # Only strip markdown OUTSIDE of [SLIDE N] markers
                            # Actually, keep it simple: for presentation mode, don't strip
                            # markdown at all since the [SLIDE N] markers matter
                            text = raw.strip()
                            info = f"Loaded **{filename}** (keeping [SLIDE N] markers intact)"
                        else:
                            info = f"Loaded **{filename}**"
                        return gr.update(value=text), info

                    pres_script_file.change(
                        fn=on_pres_script_upload,
                        inputs=[pres_script_file],
                        outputs=[pres_script_text, pres_script_info],
                    )

                    # --- "Use Last Files" handler for Presentation ---
                    def load_last_pres_files():
                        files = _load_last_files("presentation")
                        summary = _get_last_files_summary("presentation")
                        return (
                            gr.update(value=files.get("source_video")),
                            gr.update(value=files.get("pptx_file")),
                            gr.update(value=files.get("script_text", "")),
                            summary,
                        )

                    use_last_btn_pres.click(
                        fn=load_last_pres_files,
                        outputs=[pres_source_video, pres_pptx_file, pres_script_text, last_files_info_pres],
                    )

                # ---- Right column: Output ----
                with gr.Column(scale=1):
                    gr.Markdown("### Presentation Output")
                    pres_output_video = gr.Video(label="Your Presentation Recording", elem_id="pres-video")
                    gr.HTML(value="""
<div style="display:flex;gap:6px;align-items:center;padding:8px 0;">
  <span style="font-size:13px;color:#6b7280;margin-right:4px;">Speed:</span>
  <button onclick="document.querySelectorAll('#pres-video video').forEach(v=>v.playbackRate=0.5);this.parentNode.querySelectorAll('button').forEach(b=>b.style.background='#374151');this.style.background='#2563eb'" style="background:#374151;color:#d1d5db;border:1px solid #4b5563;padding:4px 10px;border-radius:5px;cursor:pointer;font-size:12px">0.5x</button>
  <button onclick="document.querySelectorAll('#pres-video video').forEach(v=>v.playbackRate=0.75);this.parentNode.querySelectorAll('button').forEach(b=>b.style.background='#374151');this.style.background='#2563eb'" style="background:#374151;color:#d1d5db;border:1px solid #4b5563;padding:4px 10px;border-radius:5px;cursor:pointer;font-size:12px">0.75x</button>
  <button onclick="document.querySelectorAll('#pres-video video').forEach(v=>v.playbackRate=1);this.parentNode.querySelectorAll('button').forEach(b=>b.style.background='#374151');this.style.background='#2563eb'" style="background:#2563eb;color:#d1d5db;border:1px solid #4b5563;padding:4px 10px;border-radius:5px;cursor:pointer;font-size:12px">1x</button>
  <button onclick="document.querySelectorAll('#pres-video video').forEach(v=>v.playbackRate=1.25);this.parentNode.querySelectorAll('button').forEach(b=>b.style.background='#374151');this.style.background='#2563eb'" style="background:#374151;color:#d1d5db;border:1px solid #4b5563;padding:4px 10px;border-radius:5px;cursor:pointer;font-size:12px">1.25x</button>
  <button onclick="document.querySelectorAll('#pres-video video').forEach(v=>v.playbackRate=1.5);this.parentNode.querySelectorAll('button').forEach(b=>b.style.background='#374151');this.style.background='#2563eb'" style="background:#374151;color:#d1d5db;border:1px solid #4b5563;padding:4px 10px;border-radius:5px;cursor:pointer;font-size:12px">1.5x</button>
  <button onclick="document.querySelectorAll('#pres-video video').forEach(v=>v.playbackRate=2);this.parentNode.querySelectorAll('button').forEach(b=>b.style.background='#374151');this.style.background='#2563eb'" style="background:#374151;color:#d1d5db;border:1px solid #4b5563;padding:4px 10px;border-radius:5px;cursor:pointer;font-size:12px">2x</button>
</div>
""")
                    pres_viewer_link = gr.HTML(value="")
                    pres_script_viewer = gr.HTML(value="", label="Script Viewer")

                    gr.Markdown(
                        """
                        ---
                        **How it works:**
                        1. Your .pptx slides are converted to high-res images
                        2. Each `[SLIDE N]` section is narrated with your cloned voice
                        3. Each slide is shown full-screen while its narration plays
                        4. All segments are joined into one continuous video

                        **Tips:**
                        - Long scripts are automatically chunked (ElevenLabs 10K char limit)
                        - Use natural paragraph breaks in your script for better pacing
                        - The `[SLIDE N]` number must match the actual slide number in your deck
                        - You can skip slides — only referenced slides appear in the video
                        """
                    )

            # --- Presentation Mode callback ---
            def run_presentation(
                source_video,
                pptx_file,
                script_text,
                tts_engine,
                voice_mode,
                builtin_voice_id,
                voice_name,
                voice_model,
                stability,
                similarity,
                style,
                speaker_boost,
                pres_coqui_temp,
                pres_coqui_rep_pen,
                pres_coqui_tp,
                pres_coqui_bass,
                pres_coqui_high,
                start_slide,
                end_slide,
                output_name,
                overwrite,
                progress=gr.Progress(),
            ):
                if not script_text or not script_text.strip():
                    raise gr.Error("Please enter or upload a speaker script with [SLIDE N] markers.")

                if pptx_file is None:
                    raise gr.Error("Please upload a PowerPoint deck (.pptx).")

                tts_key = "coqui_xtts" if "Coqui" in (tts_engine or "") else "elevenlabs"

                if source_video is None:
                    if tts_key == "coqui_xtts":
                        raise gr.Error("Please upload a source video — Coqui XTTS needs a voice sample for cloning.")
                    elif voice_mode == "Clone my voice (paid plan)":
                        raise gr.Error("Please upload a source video for voice cloning.")

                # Extract voice sample for Coqui XTTS
                voice_sample = None
                if tts_key == "coqui_xtts" and source_video:
                    voice_sample = extract_audio_from_video(source_video)

                config = AvatarConfig(
                    tts_engine=tts_key,
                    voice_model=voice_model,
                    voice_stability=stability,
                    voice_similarity=similarity,
                    voice_style=style,
                    voice_speaker_boost=speaker_boost,
                    coqui_temperature=float(pres_coqui_temp),
                    coqui_repetition_penalty=float(pres_coqui_rep_pen),
                    coqui_top_p=float(pres_coqui_tp),
                    coqui_bass_boost_db=float(pres_coqui_bass),
                    coqui_high_cut_db=float(pres_coqui_high),
                    voice_sample_path=voice_sample,
                )

                # Save last-used files for "Use Last Files" button
                _save_last_files("presentation", {
                    "source_video": source_video or "",
                    "pptx_file": pptx_file or "",
                    "script_text": script_text.strip() if script_text else "",
                })

                progress(0.05, desc="Setting up voice ...")

                try:
                    voice_id = ""
                    if tts_key == "coqui_xtts":
                        # Coqui XTTS doesn't need a voice_id — it uses voice_sample_path
                        print(f"Using Coqui XTTS with voice sample: {voice_sample}")
                    elif voice_mode == "Use built-in voice (free tier)":
                        if not builtin_voice_id:
                            raise gr.Error("Please select a built-in voice.")
                        voice_id = builtin_voice_id
                    else:
                        voice_sample_el = extract_audio_from_video(source_video)
                        voice_id = clone_voice(voice_sample_el, voice_name)

                    progress(0.1, desc="Starting presentation generation ...")

                    # Build custom output path from user-provided name
                    custom_output = None
                    if output_name and output_name.strip():
                        import re as _re
                        safe_name = _re.sub(r'[^a-zA-Z0-9_-]', '-', output_name.strip())
                        safe_name = _re.sub(r'-+', '-', safe_name).strip('-')
                        if safe_name:
                            candidate = os.path.join(OUTPUT_DIR, f"{safe_name}.mp4")
                            if os.path.exists(candidate) and not overwrite:
                                # Auto-number: find next available name
                                n = 2
                                while os.path.exists(os.path.join(OUTPUT_DIR, f"{safe_name}-{n}.mp4")):
                                    n += 1
                                safe_name = f"{safe_name}-{n}"
                                print(f"      Output name already exists, using: {safe_name}")
                            custom_output = os.path.join(OUTPUT_DIR, f"{safe_name}.mp4")

                    # Parse slide range (0 = no limit)
                    s_start = int(start_slide) if start_slide else 0
                    s_end = int(end_slide) if end_slide else 0

                    output_path = generate_presentation(
                        pptx_path=pptx_file,
                        script_text=script_text.strip(),
                        voice_id=voice_id,
                        config=config,
                        output_path=custom_output,
                        progress_callback=lambda pct, desc: progress(pct, desc=desc),
                        start_slide=s_start,
                        end_slide=s_end,
                    )

                    # Load timeline data and build the in-app script viewer
                    viewer_html = ""
                    timeline_path = os.path.splitext(output_path)[0] + "_timeline.json"
                    if os.path.exists(timeline_path):
                        try:
                            with open(timeline_path, "r", encoding="utf-8") as tf:
                                timeline = json.load(tf)
                            viewer_html = build_script_viewer_html(timeline)
                        except Exception as e:
                            print(f"Warning: Could not build script viewer: {e}")

                    # Build viewer link — serve via Gradio's /file= proxy
                    # and also show the local file path for direct browser access.
                    standalone_path = os.path.splitext(output_path)[0] + "_viewer.html"
                    viewer_link_html = ""
                    if os.path.exists(standalone_path):
                        fname = os.path.basename(standalone_path)
                        viewer_link_html = (
                            f'<div style="padding:12px 16px;background:#f0f9ff;border:1px solid #bae6fd;'
                            f'border-radius:8px;margin:8px 0;">'
                            f'<div style="font-weight:600;color:#0369a1;margin-bottom:6px;">'
                            f'Presentation Viewer</div>'
                            f'<a href="/file={standalone_path}" target="_blank" download="{fname}" '
                            f'style="display:inline-block;background:#2563eb;color:#fff;'
                            f'padding:8px 16px;border-radius:6px;text-decoration:none;'
                            f'font-weight:500;font-size:13px;margin-bottom:8px;">'
                            f'Download Viewer HTML</a>'
                            f'<div style="font-size:12px;color:#475569;margin-top:8px;">'
                            f'Or open directly in your browser:<br>'
                            f'<code style="background:#e2e8f0;padding:4px 8px;border-radius:4px;'
                            f'font-size:11px;word-break:break-all;display:inline-block;margin-top:4px;">'
                            f'file://{standalone_path}</code></div>'
                            f'</div>'
                        )

                    return output_path, viewer_link_html, viewer_html

                except ValueError as e:
                    raise gr.Error(str(e))
                except Exception as e:
                    raise gr.Error(f"Presentation error: {str(e)}")

            pres_generate_btn.click(
                fn=run_presentation,
                inputs=[
                    pres_source_video,
                    pres_pptx_file,
                    pres_script_text,
                    pres_tts_engine,
                    pres_voice_mode,
                    pres_builtin_voice,
                    pres_voice_name,
                    pres_voice_model,
                    pres_stability,
                    pres_similarity,
                    pres_style,
                    pres_speaker_boost,
                    pres_coqui_temperature,
                    pres_coqui_repetition_penalty,
                    pres_coqui_top_p,
                    pres_coqui_bass_boost,
                    pres_coqui_high_cut,
                    pres_start_slide,
                    pres_end_slide,
                    pres_output_name,
                    pres_overwrite,
                ],
                outputs=[pres_output_video, pres_viewer_link, pres_script_viewer],
            )

        # ==============================================================
        # TAB 3: Settings (API Keys)
        # ==============================================================
        with gr.TabItem("Settings"):
            gr.Markdown(
                """
                ### API Keys

                Enter your API keys here. They take effect immediately for all
                subsequent generation runs in this session. You can also set them
                permanently in `config.py` or as environment variables.
                """
            )

            with gr.Row():
                with gr.Column(scale=1):
                    elevenlabs_key_input = gr.Textbox(
                        label="ElevenLabs API Key",
                        placeholder="Enter your ElevenLabs API key ...",
                        value=_config.ELEVENLABS_API_KEY if not _config.ELEVENLABS_API_KEY.startswith("your-") else "",
                        type="password",
                        interactive=True,
                    )
                    gr.Markdown(
                        "*Sign up at [elevenlabs.io](https://elevenlabs.io) → Profile → API Key*"
                    )

                with gr.Column(scale=1):
                    did_key_input = gr.Textbox(
                        label="D-ID API Key (only needed for D-ID video backend)",
                        placeholder="Enter your D-ID API key ...",
                        value=_config.DID_API_KEY if not _config.DID_API_KEY.startswith("your-") else "",
                        type="password",
                        interactive=True,
                    )
                    gr.Markdown(
                        "*Sign up at [studio.d-id.com](https://studio.d-id.com) → API tab → Generate API Key*"
                    )

            save_keys_btn = gr.Button("Save API Keys", variant="primary")
            api_key_status = gr.Markdown(check_api_keys())

            def save_api_keys(el_key, did_key):
                """Save API keys entered in the UI to the runtime config."""
                msgs = []
                if el_key and el_key.strip():
                    set_api_key("ELEVENLABS_API_KEY", el_key.strip())
                    msgs.append("ElevenLabs key saved")
                if did_key and did_key.strip():
                    set_api_key("DID_API_KEY", did_key.strip())
                    msgs.append("D-ID key saved")

                if msgs:
                    status = check_api_keys()
                    return f"{status}\n\n*Updated: {', '.join(msgs)}.*"
                return check_api_keys()

            save_keys_btn.click(
                fn=save_api_keys,
                inputs=[elevenlabs_key_input, did_key_input],
                outputs=[api_key_status],
            )


if __name__ == "__main__":
    demo.launch(
        server_name="0.0.0.0",
        server_port=7860,
        share=False,
        inbrowser=True,
        allowed_paths=[OUTPUT_DIR],
    )
