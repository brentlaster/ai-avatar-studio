# AI Avatar Studio v2 — Project Context & Session Notes

> **Purpose:** Reference file for continuing development in a new chat session.
> **Last updated:** March 23, 2026

---

## What This Project Is

An AI Avatar Studio (inspired by HeyGen.com) that generates talking avatar videos and presentation recordings using the user's cloned voice. Built with a Gradio web UI.

**Owner:** BC (bclaster927@gmail.com) — also goes by Brent Laster, runs TechUpSkills training courses.

---

## Architecture Overview

```
app.py (Gradio UI, Python 3.12, base conda env)
  ├── pipeline.py (core pipeline: TTS dispatch, video generation)
  │     ├── Coqui XTTS v2 → subprocess call to run_coqui_tts.py (tts conda env, Python 3.10)
  │     ├── ElevenLabs API → direct HTTP calls (currently quota exceeded)
  │     ├── SadTalker → subprocess call to run_sadtalker.py (sadtalker conda env, Python 3.10)
  │     └── D-ID API → direct HTTP calls
  ├── presentation.py (presentation recording: PPTX→slides→narrated video)
  ├── config.py (API keys, runtime config)
  └── run_coqui_tts.py (standalone TTS wrapper for Coqui XTTS v2)
```

### Key Design Decisions

- **Separate conda environments** are required because:
  - The main app runs on Python 3.12 (Gradio, etc.)
  - Coqui TTS requires Python < 3.12 → `tts` conda env (Python 3.10)
  - SadTalker needs PyTorch 2.2.0 → `sadtalker` conda env (Python 3.10)
- **Subprocess wrapper pattern**: Both SadTalker and Coqui TTS are invoked via `subprocess.run()` using the Python binary from their respective conda envs. The main app finds the right Python with `_find_conda_python_for_env()` in pipeline.py.
- **File-based text passing**: Long scripts are written to temp .txt files and passed via `--text_file` arg to avoid shell escaping issues.

---

## File Inventory

| File | Purpose |
|------|---------|
| `app.py` | Gradio web UI — 3 tabs: Avatar Mode, Presentation Mode, Settings |
| `pipeline.py` | Core pipeline: TTS dispatch, voice cloning, video generation |
| `presentation.py` | PPTX → slide images → narrated video pipeline |
| `config.py` | API keys (ElevenLabs, D-ID), runtime `set_api_key()` |
| `run_coqui_tts.py` | Subprocess wrapper for Coqui XTTS v2 (runs in `tts` env) |
| `run_sadtalker.py` | Subprocess wrapper for SadTalker (runs in `sadtalker` env) |
| `sadtalker_entrypoint.py` | SadTalker entry point |
| `setup.sh` | Master setup script (calls sub-scripts) |
| `setup_sadtalker_native.sh` | Sets up `sadtalker` conda env |
| `setup_tts.sh` | Sets up `tts` conda env with Coqui TTS |
| `start.sh` | Single startup script — handles conda activation, launches app |
| `requirements.txt` | Pip dependencies for the base env |
| `temp/last_files.json` | Persisted "last used files" for the Use Last Files feature |
| `temp/last_uploads/` | Copies of last-used uploaded files |

---

## Important Technical Details

### Coqui XTTS v2 Constraints & Fixes

1. **250-character limit per inference call**: XTTS truncates audio silently if text > ~250 chars. `run_coqui_tts.py` has `split_text_into_chunks()` that splits at sentence boundaries (max 220 chars), generates each chunk separately, then concatenates WAV files.

2. **PyTorch 2.6 `weights_only=True` breaking change**: `torch.load` defaults changed, breaking Coqui's model loading. Fixed with a monkey-patch in `run_coqui_tts.py` that forces `weights_only=False` before any TTS imports.

3. **`transformers` library compatibility**: `BeamSearchScorer` was removed in `transformers >= 4.45`, breaking Coqui's `stream_generator.py`. Fixed by pinning `transformers>=4.33,<4.45` in `setup_tts.sh`.

4. **`torchcodec` dependency**: Required by `torchaudio` for loading WAV files. Must be installed in the `tts` env: `pip install torchcodec`.

5. **Harmless warnings to ignore**:
   - `UserWarning: An output with one or more elements was resized` (PyTorch stft deprecation)
   - `The attention mask is not set and cannot be inferred` (GPT-2 tokenizer quirk in XTTS)

### Presentation Pipeline (presentation.py)

- `extract_slides_as_images()`: Converts PPTX to images via LibreOffice headless + pdftoppm. Has `_find_soffice()` for macOS app bundle paths. Falls back to python-pptx + Pillow if LibreOffice unavailable.
- `clean_narration_text()`: Strips markdown from narration scripts. Key behaviors:
  - Code blocks removed first
  - `*[PAUSE]*` stage directions → comma (not ellipsis, avoids dead air)
  - All bracketed stage directions removed
  - Bold/italic stripping runs 3 passes for nested cases
  - Table formatting, reference-style links removed
- LibreOffice installed via `brew install --cask libreoffice && brew install poppler`

### Voice Quality Settings (for ElevenLabs)

- Presentation defaults tuned to reduce filler words: stability=0.50, similarity=0.80, style=0.20
- Avatar defaults are more expressive: stability=0.20, similarity=0.75, style=0.65

### "Use Last Files" Feature (added March 23, 2026)

- Both Avatar and Presentation tabs have a "Use Last Files" button
- Files are copied to `temp/last_uploads/` on each Generate run (survives Gradio temp cleanup)
- Paths stored in `temp/last_files.json`
- Text fields (script_text) saved as .txt files, file fields saved as copies
- `_save_last_files()`, `_load_last_files()`, `_get_last_files_summary()` in app.py

### Script Parsing & Temp Dir Cleanup (fixed March 23, 2026)

- `presentation.py` now **cleans temp dirs** (`presentation_slides/`, `presentation_segments/`) via `shutil.rmtree` before each new run — prevents stale audio/video from previous runs bleeding through
- `parse_slide_script()` now **stops after "Thank You" slides** — detects "thank you", "thanks for", "q&a", "questions?" in slide markers or first 200 chars of narration
- `_find_script_end()` **truncates meta-sections** before parsing: detects markdown headings like `# Timing and Pacing Guide`, `# Key Changes`, `# Notes`, `# Appendix`, `# References`, etc. and stops before them
- Both features prevent the TTS from narrating appendix/meta content

### Dynamic API Key Loading

- `config.py` has `set_api_key()` for runtime updates from the Settings tab
- All modules use `import config as _config` (not `from config import KEY`) so runtime changes propagate

---

## Conda Environments

| Env | Python | Key Packages | Purpose |
|-----|--------|-------------|---------|
| `base` | 3.12 | gradio, ffmpeg-python, Pillow, python-pptx | Main app |
| `tts` | 3.10 | TTS (Coqui), torch (latest), transformers<4.45, torchcodec | Voice cloning |
| `sadtalker` | 3.10 | torch 2.2.0, SadTalker deps | Talking head video |

---

## Setup & Run

**Fresh setup:**
```bash
cd ai-avatar-studio-v2
bash setup.sh          # installs everything (calls setup_sadtalker_native.sh and setup_tts.sh)
```

**Start the app:**
```bash
bash start.sh          # handles conda activation, launches Gradio on port 7860
```

**Fix existing tts env (if needed):**
```bash
conda activate tts
pip install "transformers>=4.33,<4.45"
pip install torchcodec
conda activate base
```

---

## ElevenLabs Status

ElevenLabs API quota is **exceeded** as of this session. The app defaults to Coqui XTTS v2 for free local voice cloning. ElevenLabs is still available as an option in the UI if credits are replenished.

---

## Known Issues / Future Work

- Coqui XTTS voice quality may not match ElevenLabs — it's a local model vs. cloud API
- MPS (Apple Silicon GPU) acceleration for XTTS may have issues — falls back to CPU gracefully
- The `start.sh` script uses `conda shell.bash hook` — if user's default shell is zsh, conda init needs to be set up for zsh too
- SadTalker video generation is slow (several minutes per video)
- No automated tests yet

---

## User's Mac Environment

- macOS (Apple Silicon)
- Miniconda installed at `/Users/developer/miniconda3`
- Project lives in OneDrive: `/Users/developer/Library/CloudStorage/OneDrive-Personal/aia-capstone-starter/ai-avatar-studio-v2/`
- LibreOffice installed via Homebrew (app bundle at `/Applications/LibreOffice.app/Contents/MacOS/soffice`)
- Poppler (pdftoppm) installed via Homebrew
