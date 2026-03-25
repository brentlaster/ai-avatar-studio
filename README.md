# AI Avatar Studio v2

A local AI-powered tool for generating talking avatar videos and narrated presentation recordings using your cloned voice. Built with a Gradio web UI.

---

## Quick Start

**First time? Run setup (takes 10-15 minutes):**

```bash
cd ai-avatar-studio-v2
bash setup.sh
```

**Start the app:**

```bash
bash start.sh
```

The app opens in your browser at `http://localhost:7860`. That's it. You don't need to activate any conda environments manually — `start.sh` handles everything.

---

## What It Does

The app has three tabs:

### Tab 1: Avatar Mode

Creates a talking avatar video (or audio-only) from a source video and a script. Your voice is cloned from the video, and the avatar's lips are synced to the generated speech.

**Inputs:**
- **Source Video** — upload a video of yourself speaking (used for voice cloning and optionally as the avatar face)
- **Script** — type/paste text or upload a `.txt`/`.md` file. Markdown files are auto-stripped for clean speech
- **Avatar Photo** (optional) — overrides the video frame as the avatar face

**Key Options:**
- **TTS Engine** — choose between Coqui XTTS v2 (free, local, clones your voice) or ElevenLabs (paid API, higher quality)
- **Audio Only Mode** — generates speech without video (faster, good for long content)
- **Max Length** — limit the generated video duration. Options: No limit (default), 1 minute, 2 minutes, 5 minutes, 10 minutes, 30 minutes. The script is automatically truncated at sentence boundaries to fit the target duration (~900 characters per minute estimate). Useful for generating quick samples before committing to a full-length video.
- **Quick Preset** — pre-configured combinations of voice + video settings:
  - *Expressive (recommended)* — dynamic voice, full movement
  - *Balanced* — moderate settings
  - *Conservative (stable)* — consistent voice, less head motion
  - *Fast test (low quality)* — quick preview, lower quality

**Video Backend Options (SadTalker):**
- **Face enhancer** — GFPGAN improves quality but takes longer
- **Still mode** — less head motion (on) vs. more expression (off)
- **Preprocess** — `full` = natural movement, `crop` = tighter face focus, `resize` = simple resize
- **Output face resolution** — 256 (faster) or 512 (better quality)
- **Expression intensity** — 0.5 to 3.0 (1.0 = default, higher = more expressive facial movement)
- **Pose style** — 0 to 45 (different head movement patterns — experiment!)

**ElevenLabs Voice Settings** *(only apply when using ElevenLabs TTS engine):*
- **Stability** — lower (0.15-0.25) = more expressive/dynamic, higher (0.50+) = more consistent
- **Similarity** — how close to the original voice (0.75-0.85 is typical)
- **Style exaggeration** — adds emotion (0.60-0.75 for dynamic, 0.20 for clean/professional)
- **Speaker boost** — enhances clarity and presence

**Coqui XTTS Voice Settings** *(only apply when using Coqui XTTS v2 engine):*
- **Temperature** (0.1–1.0, default 0.75) — controls pitch variation and expressiveness. Lower = stable/monotone, higher = more natural intonation. Going above 0.85 may introduce instability.
- **Repetition penalty** (1.0–5.0, default 1.8) — reduces repeated artifacts and gibberish. Higher values make speech more consistent but can flatten prosody. Below 1.5 may produce artifacts.
- **Top P** (0.5–1.0, default 0.95) — sampling breadth. Higher = more varied/natural speech, lower = more predictable. Values below 0.8 can sound monotone.
- **Bass boost** (-3 to +6 dB, default +1.0) — post-processing low-shelf EQ below 250Hz. Positive values add warmth and chest resonance. Set to 0 to disable.
- **High shelf** (-6 to +3 dB, default -0.5) — post-processing high-shelf EQ above 4kHz. Negative values reduce synthetic brightness/thinness. Set to 0 to disable.

### Tab 2: Presentation Mode

Creates a narrated presentation video from a PowerPoint deck and a speaker script. Each slide is shown full-screen while your cloned voice narrates the corresponding section.

**Inputs:**
- **Source Video** — for voice cloning (same as Avatar Mode)
- **PowerPoint Deck** — upload a `.pptx` file
- **Speaker Script** — a `.md` or `.txt` file with `[SLIDE N]` markers
- **Output name** (optional) — give your presentation a custom name (e.g. `context-engineering-talk`). Used for the video filename and viewer URL. See [Output Naming](#output-naming) below.
- **Overwrite if exists** — when checked, reusing the same name replaces the existing files. When unchecked (default), a number is auto-appended (e.g. `context-engineering-talk-2.mp4`)
- **Start slide** (optional) — set the first slide number to generate (0 = start from the beginning). Useful for generating a specific section of your presentation without re-rendering the whole thing.
- **End slide** (optional) — set the last slide number to generate (0 = go through to the end). Combined with Start slide, lets you render any contiguous range of slides.

**Script format:**

```
[SLIDE 1]
Welcome everyone! Today we'll be talking about context engineering...

[SLIDE 2]
Let's start with the key insight. As you can see on this slide...

[SLIDE 3]
Moving on to the data. These numbers show a clear trend...
```

The script also supports titled markers like `## [SLIDE 3 — "Title Here"]`.

**How it works:**
1. Slides are converted to high-quality images via LibreOffice
2. Each `[SLIDE N]` section is narrated with your cloned voice
3. Each slide is shown full-screen with a 0.5-second visual lead-in before the narration begins (so the viewer sees the slide before the voice starts)
4. All segments are joined into one continuous video

**Script parsing rules:**
- Text before the first `[SLIDE]` marker is ignored (metadata, headers, etc.)
- Everything after the last `[SLIDE N]` section that hits a markdown heading (`#`) or horizontal rule (`---`) is ignored — so appendix sections like "Timing and Pacing Guide" or "Key Changes" won't be narrated
- Stage directions like `*[PAUSE]*`, `*[GESTURE at diagram]*`, `*[Skip]*` are automatically removed
- Markdown formatting (bold, italic, headers, code blocks, links) is stripped for clean speech
- Em-dashes (`—`) are converted to natural pauses
- Tildes (`~60`) are converted to "about 60"
- Smart/curly quotes are normalized to straight quotes
- Quote boundaries (e.g. `"Fix the bug." The model`) get clean sentence breaks to avoid TTS gibberish
- Metadata lines (`Duration:`, `Target pace:`, etc.) are removed
- `[SLIDE N]` references in prose (like changelogs) are ignored — only markers at the start of a line are parsed

**Presentation Voice Settings (recommended defaults for Coqui XTTS):**
- Temperature: 0.75, Repetition penalty: 1.8, Top P: 0.95, Bass boost: +1dB, High shelf: -0.5dB. These are tunable in the "Coqui XTTS Voice Settings" accordion in the UI. Audio is also post-processed with spectral subtraction and harmonic enhancement.

**Presentation Voice Settings (recommended defaults for ElevenLabs):**
- Stability: 0.50 (cleaner, fewer filler words)
- Similarity: 0.80
- Style: 0.20 (lower = fewer um's and uh's)

### Tab 3: Settings

Enter API keys for ElevenLabs and D-ID. Keys take effect immediately for the current session. You can also set them permanently in `config.py` or as environment variables.

---

## Presentation Output Features

After generating a presentation, you get several outputs:

### Video Player + Speed Control

The generated video plays directly in the app. Below the video player, there's a row of **playback speed buttons** (0.5x through 2x) — click any to change the playback rate in real time. The active speed is highlighted in blue.

### In-App Script Viewer

A scrollable script panel appears below the video showing each slide's narration text with timestamps (start time, end time, and duration). This is a light-themed, readable panel embedded directly in the Gradio UI.

### Standalone Presentation Viewer

A self-contained HTML file is generated alongside each presentation video. This viewer shows the video on the left with a synced, auto-scrolling script panel on the right. As the video plays, the current slide's narration is highlighted and the script auto-scrolls to follow.

**How to access it:**
- After generation, a blue link panel appears with a **"Download Viewer HTML"** button
- The local file path is also displayed — you can copy/paste it into your browser's address bar
- The HTML file is fully self-contained (the video is embedded inside it) so you can share it or open it anywhere

**Standalone viewer features:**
- Click any slide section in the script to jump to that point in the video
- Playback speed controls (0.5x through 2x) below the video
- Auto-highlighting of the current slide's narration
- Auto-scrolling script panel that follows playback

### Output Naming

- **Custom name**: Type a name like `context-engineering-talk` in the "Output name" field. Your files are saved as:
  - `outputs/context-engineering-talk.mp4` (video)
  - `outputs/context-engineering-talk_viewer.html` (standalone viewer)
  - `outputs/context-engineering-talk_timeline.json` (timeline data)

- **Auto-numbering (default)**: If a file with that name already exists and "Overwrite if exists" is unchecked, the app automatically appends a number: `context-engineering-talk-2.mp4`, then `context-engineering-talk-3.mp4`, etc. Previous versions are preserved.

- **Overwrite mode**: Check "Overwrite if exists" to replace existing files with the same name. Useful when iterating on the same presentation.

- **No name**: Leave the field blank and files default to `presentation.mp4` (always overwrites).

---

## Use Last Files Button

Both Avatar Mode and Presentation Mode have a **"Use Last Files"** button at the top. Every time you generate, the app saves your uploaded files (video, PPTX, script, avatar image). Next time you launch, click the button and everything is pre-filled. Files persist across app restarts.

---

## TTS Engines

### Coqui XTTS v2 (default, free)

- Runs locally on your machine — no API key needed
- Clones your voice from a short audio/video sample
- First run downloads a ~2 GB model (cached after that)
- Uses Apple Silicon GPU (MPS) when available, falls back to CPU
- Text is automatically chunked at ~220 characters per inference call (XTTS limit)
- Chunks are concatenated with 150ms silence gaps and trailing silence trimming for natural pacing
- Inference parameters are auto-tuned for quality:
  - `temperature=0.55` — balances natural variation with consistency
  - `repetition_penalty=3.0` — reduces repeated artifacts and gibberish
  - `top_k=50`, `top_p=0.85` — constrains sampling for cleaner output
- Quality is good but not as polished as ElevenLabs

**Voice quality tips for Coqui XTTS:**
- Use a clean, clear voice sample (10-30 seconds of speech, minimal background noise)
- Longer samples generally produce better cloning
- The WAV extracted from your source video is used as the reference — if the video audio is noisy, the clone quality suffers
- Audio post-processing is applied automatically: +3dB low-shelf EQ (bass warmth below 250Hz), -2dB high-shelf cut (reduces synthetic brightness above 4kHz), and a spectral noise gate (attenuates buzzy/robotic frames). These settings were tuned via spectral analysis comparing real recorded speech against XTTS output.

### ElevenLabs (paid API)

- Cloud-based, higher quality voice synthesis
- Requires an API key (set in Settings tab or `config.py`)
- Free tier: 10,000 characters/month
- Supports multiple voice models: Multilingual v2, Turbo v2.5, Monolingual v1
- 10,000 character limit per API request (auto-chunked)

---

## Setup Details

### Prerequisites

- **macOS** (tested on Apple Silicon)
- **Homebrew** — for installing system tools
- **Miniconda or Anaconda** — for managing Python environments

### What `setup.sh` Installs

1. **System tools** (via Homebrew):
   - `ffmpeg` — audio/video processing
   - `LibreOffice` — high-quality PPTX slide rendering
   - `poppler` (pdftoppm) — PDF to image conversion

2. **Python app dependencies** (in base env):
   - `gradio`, `requests`, `ffmpeg-python`, `python-pptx`, `Pillow`

3. **SadTalker conda env** (`sadtalker`, Python 3.10):
   - PyTorch 2.2.0 + SadTalker for talking head video generation

4. **Coqui TTS conda env** (`tts`, Python 3.10):
   - PyTorch (latest) + Coqui TTS for voice cloning
   - `transformers` pinned to `>=4.33,<4.45` (compatibility fix)
   - `torchcodec` for audio file loading

### Conda Environments

| Environment | Python | Purpose |
|-------------|--------|---------|
| `base` | 3.12 | Main app (Gradio UI) |
| `tts` | 3.10 | Coqui XTTS v2 voice cloning |
| `sadtalker` | 3.10 | SadTalker talking head video |

These are separate because SadTalker needs PyTorch 2.2.0 while Coqui TTS needs PyTorch 2.4+. You never need to activate them manually — the app calls them via subprocess.

### Manual Fixes (if needed)

If the `tts` conda env has issues:

```bash
conda activate tts
pip install "transformers>=4.33,<4.45"
pip install torchcodec
conda activate base
```

To completely rebuild the `tts` env:

```bash
conda env remove -n tts
bash setup_tts.sh
```

To completely rebuild the `sadtalker` env:

```bash
conda env remove -n sadtalker
bash setup_sadtalker_native.sh
```

---

## File Structure

```
ai-avatar-studio-v2/
  app.py                    # Gradio web UI (3 tabs)
  pipeline.py               # Core pipeline: TTS dispatch, video generation
  presentation.py           # PPTX → narrated video pipeline + viewers
  config.py                 # API keys, output/temp directories
  run_coqui_tts.py          # Subprocess wrapper for Coqui XTTS v2
  run_sadtalker.py          # Subprocess wrapper for SadTalker
  sadtalker_entrypoint.py   # SadTalker entry point
  start.sh                  # Start the app (handles conda activation)
  setup.sh                  # Full setup (calls sub-scripts)
  setup_sadtalker_native.sh # SadTalker conda env setup
  setup_tts.sh              # Coqui TTS conda env setup
  requirements.txt          # Base env pip dependencies
  PROJECT_CONTEXT.md        # Detailed developer context notes
  README.md                 # This file
  SadTalker/                # SadTalker source code (cloned by setup)
  outputs/                  # Generated videos, viewers, and timelines
  temp/                     # Working files (cleaned between runs)
    last_files.json         # Persisted "Use Last Files" data
    last_uploads/           # Copies of last-used uploaded files
```

---

## Troubleshooting

**App won't start / "gradio not found":**
Run `bash setup.sh` first, or manually: `pip install gradio requests ffmpeg-python python-pptx Pillow`

**"Coqui XTTS failed" errors:**
Check that the `tts` conda env exists: `conda env list`. If not, run `bash setup_tts.sh`. If it exists but has issues, see "Manual Fixes" above.

**Voice sounds robotic or has a "Max Headroom" warble:**
The app applies both inference tuning (temperature=0.68, repetition_penalty=2.0, top_p=0.92) and audio post-processing (bass EQ boost, high-shelf cut, spectral noise gate) to minimize this. Some residual synthetic quality is an inherent XTTS v2 limitation. Things that help: use a longer, cleaner voice sample (10-30s of clear speech); ensure your source video has minimal background noise; try generating the same content multiple times (XTTS output varies slightly each run). For the most natural results, consider ElevenLabs as an alternative TTS engine.

**Voice sounds truncated (cuts off mid-sentence):**
This was a known issue with XTTS's 250-character limit. It should be fixed — `run_coqui_tts.py` auto-chunks text at 220 characters. If you still hear truncation, check the terminal output for chunk counts.

**"soffice not found" in Presentation Mode:**
Install LibreOffice: `brew install --cask libreoffice && brew install poppler`

**Presentation narrates appendix/metadata sections:**
The parser stops at non-`[SLIDE]` markdown headings after the last slide. If content is still leaking through, check that meta-sections start with a `#` heading or `---` rule.

**Slides seem late / narration starts before the slide appears:**
Each slide now has a 0.5-second visual lead-in before the narration begins. If timing still feels off, this is usually due to video player buffering on the first play — try playing the video a second time.

**Old script is being used instead of the new one:**
The temp directories are cleaned at the start of each run. Make sure the text in the "Speaker script" text box shows the correct content before hitting Generate.

**Playback speed buttons don't work:**
The speed buttons use JavaScript to target the Gradio video player element by its `id`. If you're using a very old browser, try Chrome or Firefox. The buttons work on the video that's currently loaded — if no video is loaded yet, they won't do anything until one is.

**Standalone viewer shows "about:blank#blocked":**
This happens if you try to open a `file://` URL from within the Gradio web page (browsers block this for security). Instead, download the HTML file using the "Download Viewer HTML" button, then double-click it from your file manager. Or copy the `file://` path shown and paste it directly into a new browser tab's address bar.

**PyTorch warnings in terminal (stft resize, attention mask):**
These are harmless. The only warning that matters is "text length exceeds character limit of 250" — if you see that, the chunking isn't working properly.

**"python: command not found" after conda commands:**
Always use `conda activate base` (not `conda deactivate`) to return to the base environment.

---

## API Keys (Optional)

Only needed if using ElevenLabs or D-ID (not needed for Coqui XTTS + SadTalker):

- **ElevenLabs**: Sign up at [elevenlabs.io](https://elevenlabs.io) → Profile → API Key
- **D-ID**: Sign up at [studio.d-id.com](https://studio.d-id.com) → API tab → Generate API Key

Set them in the app's Settings tab, in `config.py`, or as environment variables:

```bash
export ELEVENLABS_API_KEY="your-key-here"
export DID_API_KEY="your-key-here"
```
