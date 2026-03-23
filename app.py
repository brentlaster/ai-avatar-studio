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
    AvatarConfig,
    OUTPUT_DIR,
)
from config import ELEVENLABS_API_KEY, DID_API_KEY


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
    if not ELEVENLABS_API_KEY or ELEVENLABS_API_KEY.startswith("your-"):
        issues.append("ElevenLabs API key not set")
    if not DID_API_KEY or DID_API_KEY.startswith("your-"):
        issues.append("D-ID API key not set (only needed for D-ID backend)")

    if issues:
        return f"**Note:** {', '.join(issues)}. Edit `config.py` or set environment variables."
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


def run_pipeline(
    source_video,
    script_text,
    avatar_image,
    selected_frame_ts,
    voice_mode,
    builtin_voice_id,
    voice_name,
    voice_model,
    voice_stability,
    voice_similarity,
    voice_style,
    voice_speaker_boost,
    video_backend,
    sadtalker_enhancer,
    sadtalker_still,
    sadtalker_size,
    sadtalker_preprocess,
    expression_scale,
    pose_style,
    audio_only_toggle,
    progress=gr.Progress(),
):
    """Gradio callback: runs the full pipeline."""
    if not script_text or not script_text.strip():
        raise gr.Error("Please enter a script for your avatar to speak.")

    if voice_mode == "Clone my voice (paid plan)" and source_video is None:
        raise gr.Error("Please upload a source video for voice cloning.")

    if not audio_only_toggle and source_video is None and avatar_image is None:
        raise gr.Error("Please upload a source video or avatar photo for video generation.")

    config = AvatarConfig(
        voice_model=voice_model,
        voice_stability=voice_stability,
        voice_similarity=voice_similarity,
        voice_style=voice_style,
        voice_speaker_boost=voice_speaker_boost,
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

    if voice_mode == "Use built-in voice (free tier)":
        if not builtin_voice_id or builtin_voice_id == "":
            raise gr.Error("Please select a built-in voice from the dropdown.")
        use_builtin = builtin_voice_id

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

    # =====================================================
    # TOP CONTROLS: Audio-only toggle + Preset selector
    # =====================================================
    with gr.Row():
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

                with gr.Accordion("SadTalker Settings", open=True) as sadtalker_accordion:
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

            with gr.Accordion("Voice Settings", open=True):
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
                """Show/hide video-related settings based on audio-only toggle."""
                return gr.update(visible=not is_audio_only)

            audio_only_toggle.change(
                fn=toggle_audio_only,
                inputs=[audio_only_toggle],
                outputs=[video_settings_group],
            )

            # Wire up the script file upload
            script_file.change(
                fn=on_script_file_upload,
                inputs=[script_file],
                outputs=[script_text, script_file_info],
            )

            # Wire up the preset selector
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

        # ---- Right column: Output ----
        with gr.Column(scale=1):
            gr.Markdown("### Output")
            output_video = gr.Video(label="Your Avatar Video / Audio")

            gr.Markdown(
                """
                ---
                **Tips:**
                - **Presets** at the top quickly configure voice + video settings
                - **Expressive** preset: head moves, face animates, voice has range
                - **Expression intensity** > 1.0 amplifies facial movements
                - **Pose style** 0-45 gives different head movement patterns — experiment!
                - Turn **still mode OFF** for natural head motion
                - **Full** preprocess keeps the whole frame (more natural than crop)
                - **Stability** 0.15-0.25 = dynamic voice; 0.50+ = consistent/flat
                - **Style** 0.60-0.75 adds strong emotion to speech
                - Drop a **.md** file to auto-strip Markdown for clean speech
                - **Audio Only** mode is great for long-form content (no video limits)
                """
            )

    generate_btn.click(
        fn=run_pipeline,
        inputs=[
            source_video,
            script_text,
            avatar_image,
            selected_frame_ts,
            voice_mode,
            builtin_voice_dropdown,
            voice_name,
            voice_model,
            voice_stability,
            voice_similarity,
            voice_style,
            voice_speaker_boost,
            video_backend,
            sadtalker_enhancer,
            sadtalker_still,
            sadtalker_size,
            sadtalker_preprocess,
            expression_scale,
            pose_style,
            audio_only_toggle,
        ],
        outputs=output_video,
    )


if __name__ == "__main__":
    demo.launch(
        server_name="0.0.0.0",
        server_port=7860,
        share=False,
        inbrowser=True,
    )
