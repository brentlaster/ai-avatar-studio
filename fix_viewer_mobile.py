#!/usr/bin/env python3
"""
Fix existing presentation viewer HTML files for mobile playback.

Mobile Safari and some Android browsers don't support video playback from
data: URIs. This script converts existing viewer HTML files to use Blob URLs
instead, and adds responsive CSS + viewport meta for mobile layout.

It also generates a *_mobile/ folder next to each viewer containing a tiny
HTML file + separate MP4 — suitable for Dropbox, iCloud, Google Drive, etc.
where the self-contained HTML is too large for mobile Safari to load.

Usage:
    python fix_viewer_mobile.py viewer1.html viewer2.html ...
    python fix_viewer_mobile.py outputs/*_viewer.html
    python fix_viewer_mobile.py --force outputs/*_viewer.html

Options:
    --force   Re-patch files that were already patched (e.g. to update
              the responsive CSS or playsinline attributes).

The original file is backed up as <name>_backup.html before patching.
"""

import re
import sys
import shutil
from pathlib import Path

# Current responsive CSS (single source of truth)
RESPONSIVE_CSS = """
@media (max-width: 768px) {
    body { height: auto; overflow-y: auto; }
    .container { flex-direction: column; height: auto; overflow-y: visible; }
    .video-panel { padding: 12px; flex: none; }
    .video-panel video { max-height: 35vh; width: 100%; }
    .script-panel { width: 100%; min-width: unset; max-height: none;
                     overflow-y: visible;
                     border-left: none; border-top: 2px solid #1a1a2e; }
    .speed-bar { flex-wrap: wrap; }
}
"""


def _extract_b64_from_data_uri(html: str) -> str | None:
    """Extract base64 video data from an unpatched file's <source> data URI."""
    m = re.search(
        r'<source\s+src="data:video/mp4;base64,([^"]+)"\s+type="video/mp4"\s*/?>',
        html,
    )
    return m.group(1) if m else None


def _extract_b64_from_js(html: str) -> str | None:
    """Extract base64 video data from an already-patched file's JS variable."""
    m = re.search(r'const videoB64 = "([A-Za-z0-9+/=]+)"', html)
    return m.group(1) if m else None


def fix_viewer_html(filepath: str, force: bool = False) -> bool:
    """
    Patch a single viewer HTML file for mobile compatibility.
    Returns True if the file was patched, False if skipped.
    """
    path = Path(filepath)
    if not path.exists():
        print(f"  SKIP  {filepath} (file not found)")
        return False

    html = path.read_text(encoding="utf-8")
    already_patched = "URL.createObjectURL" in html

    if already_patched and not force:
        print(f"  SKIP  {filepath} (already patched — use --force to re-patch)")
        return False

    # Extract the base64 video data from whichever format is present
    video_b64 = _extract_b64_from_data_uri(html)
    if not video_b64:
        video_b64 = _extract_b64_from_js(html)
    if not video_b64:
        print(f"  SKIP  {filepath} (no base64 video data found)")
        return False

    label = "RE-PATCH" if already_patched else "PATCH"

    # Back up the original (only if no backup exists yet)
    backup_path = path.with_stem(path.stem + "_backup")
    if not backup_path.exists():
        shutil.copy2(path, backup_path)
        print(f"  BACKUP {backup_path.name}")

    # --- Start with a clean slate for previously-patched files ---
    if already_patched:
        # Remove the old Blob URL loader block
        html = re.sub(
            r'// Convert base64 video to Blob URL.*?\n\n',
            '',
            html,
            flags=re.DOTALL,
        )
        # Remove old loading message div
        html = re.sub(
            r'\s*<div id="loadingMsg"[^>]*>.*?</div>',
            '',
            html,
        )
        # Remove old @media block
        html = re.sub(
            r'\n@media \(max-width: 768px\) \{.*?\}\n',
            '\n',
            html,
            flags=re.DOTALL,
        )
        # Reset video tag to plain version (remove old playsinline variants)
        html = re.sub(
            r'<video\s+id="vid"\s+[^>]*>',
            '<video id="vid" controls>',
            html,
        )

    # --- Apply all patches ---

    # 1. Viewport meta tag
    if '<meta name="viewport"' not in html:
        html = html.replace(
            '<meta charset="UTF-8">',
            '<meta charset="UTF-8">\n<meta name="viewport" content="width=device-width, initial-scale=1">',
        )

    # 2. Replace <video> tag (handles both data-URI source and plain tag)
    html = re.sub(
        r'<video\s+id="vid"\s+controls\s*>.*?</video>',
        '<video id="vid" controls playsinline webkit-playsinline></video>\n'
        '        <div id="loadingMsg" style="color:#7a8ba8;font-size:13px;margin-top:8px;">Loading video...</div>',
        html,
        flags=re.DOTALL,
    )

    # 3. Responsive CSS — remove any existing @media block first, then add fresh
    html = re.sub(
        r'\n@media \(max-width: 768px\) \{.*?\}\n',
        '\n',
        html,
        flags=re.DOTALL,
    )
    html = html.replace("</style>", RESPONSIVE_CSS + "</style>")

    # 4. Reduce desktop max video height
    html = html.replace("max-height: 80vh", "max-height: 70vh")

    # 5. Blob URL loader at the start of <script>
    blob_loader = f'''
// Convert base64 video to Blob URL for mobile compatibility
// (mobile Safari does not support data: URIs on <video> elements)
const videoB64 = "{video_b64}";
const loadMsg = document.getElementById("loadingMsg");
const vid = document.getElementById("vid");

// Force inline playback on iOS — the JS property (camelCase) is what
// iOS actually checks; the HTML attribute alone is not always enough,
// especially in WebViews (Mail, Files, Messages).
vid.playsInline = true;
vid.setAttribute("playsinline", "");
vid.setAttribute("webkit-playsinline", "");

try {{
    const byteChars = atob(videoB64);
    const len = byteChars.length;
    const bytes = new Uint8Array(len);
    for (let i = 0; i < len; i++) bytes[i] = byteChars.charCodeAt(i);
    const blob = new Blob([bytes], {{ type: "video/mp4" }});
    const blobUrl = URL.createObjectURL(blob);
    vid.src = blobUrl;
    if (loadMsg) loadMsg.style.display = "none";
}} catch(e) {{
    if (loadMsg) loadMsg.textContent = "Error loading video: " + e.message;
    console.error("Video blob creation failed:", e);
}}

'''
    # Only add if not already present (clean-slate step above should have removed it)
    if "const videoB64" not in html:
        html = html.replace("<script>\n", "<script>\n" + blob_loader, 1)

    # 6. Remove the original "const vid" line that the unpatched file has
    #    (the blob loader now declares it earlier to set playsInline before src)
    #    Use a regex that matches the standalone line but NOT the one inside the blob loader
    html = re.sub(
        r'\n(const segs = )',
        r'\nconst segs = ',
        html,
    )
    # Remove duplicate: if "const vid" appears twice (once in blob loader, once in original)
    # keep only the first occurrence
    vid_lines = list(re.finditer(r'^const vid = document\.getElementById\("vid"\);$', html, re.MULTILINE))
    if len(vid_lines) > 1:
        # Remove the second (original) occurrence
        second = vid_lines[1]
        html = html[:second.start()] + html[second.end():]
        # Clean up any resulting blank lines
        html = re.sub(r'\n{3,}', '\n\n', html)

    # Write patched file
    path.write_text(html, encoding="utf-8")
    size_mb = path.stat().st_size / (1024 * 1024)
    print(f"  {label}  {filepath} ({size_mb:.1f} MB)")
    return True


def generate_mobile_version(filepath: str) -> bool:
    """
    Extract the base64 video from a viewer HTML (patched or unpatched),
    decode it to a .mp4 file, and generate a mobile-friendly HTML viewer
    that references the video via a relative path.

    Creates a *_mobile/ folder next to the viewer HTML containing:
      - <name>.mp4        (the decoded video)
      - <name>_viewer.html (tiny HTML that references the MP4)

    Returns True if the mobile version was created, False if skipped.
    """
    path = Path(filepath)
    if not path.exists():
        return False

    html = path.read_text(encoding="utf-8")

    # Extract base64 from either format
    video_b64 = _extract_b64_from_data_uri(html) or _extract_b64_from_js(html)
    if not video_b64:
        print(f"  SKIP-MOBILE  {filepath} (no base64 video data found)")
        return False

    # Determine output folder
    stem = path.stem.replace("_viewer", "").replace("_backup", "")
    mobile_dir = path.parent / f"{stem}_mobile"
    mobile_dir.mkdir(exist_ok=True)

    # Decode base64 → MP4
    import base64
    mp4_filename = f"{stem}.mp4"
    mp4_path = mobile_dir / mp4_filename
    if not mp4_path.exists():
        print(f"  DECODE {mp4_filename} ...")
        mp4_bytes = base64.b64decode(video_b64)
        mp4_path.write_bytes(mp4_bytes)

    # Extract segment data from the HTML for the script panel
    import html as html_mod
    seg_data = []
    for m in re.finditer(
        r'<div class="seg" id="seg-(\d+)" data-start="([^"]+)" data-end="([^"]+)">\s*'
        r'<div class="seg-header">\s*Slide (\d+)',
        html,
    ):
        idx, start, end, slide = m.group(1), m.group(2), m.group(3), m.group(4)
        seg_data.append({
            "idx": int(idx),
            "start": float(start),
            "end": float(end),
            "slide": int(slide),
        })

    # Extract segment text blocks
    text_blocks = re.findall(
        r'<div class="seg-text">(.*?)</div>',
        html,
        re.DOTALL,
    )

    # Extract notes blocks (may not exist in older viewers)
    notes_blocks = re.findall(
        r'<div class="seg-notes">.*?<span class="seg-notes-label">Slide Notes</span>(.*?)</div></div>',
        html,
        re.DOTALL,
    )

    # Check for notes bar
    has_notes_bar = "notesBar" in html

    # Build notes bar HTML
    if has_notes_bar:
        notes_bar_html = (
            '<div class="notes-bar empty" id="notesBar">'
            '<div class="notes-bar-label">Slide Notes</div>'
            '<div class="notes-bar-text placeholder" id="notesText">'
            'Notes will appear here as the presentation plays</div></div>'
        )
    else:
        notes_bar_html = ""

    # Build segment HTML and JS notes data
    seg_blocks = ""
    notes_js_entries = []
    for i, sd in enumerate(seg_data):
        text_html = text_blocks[i].strip() if i < len(text_blocks) else ""
        notes_html_block = ""
        notes_raw = ""
        if i < len(notes_blocks):
            notes_raw = notes_blocks[i].strip()
            notes_html_block = (
                f'<div class="seg-notes">'
                f'<span class="seg-notes-label">Slide Notes</span>'
                f'{notes_raw}</div>'
            )
        js_notes = notes_raw.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "")
        notes_js_entries.append(
            f'{{start:{sd["start"]},end:{sd["end"]},slide:{sd["slide"]},notes:"{js_notes}"}}'
        )
        start_min = int(sd["start"] // 60)
        start_sec = int(sd["start"] % 60)
        seg_blocks += f'''
        <div class="seg" id="seg-{i}" data-start="{sd['start']}" data-end="{sd['end']}">
            <div class="seg-header">
                Slide {sd['slide']}
                <span class="seg-time">{start_min}:{start_sec:02d}</span>
            </div>
            <div class="seg-text">{text_html}</div>
            {notes_html_block}
        </div>'''
    notes_js_array = ",".join(notes_js_entries)

    total_duration = seg_data[-1]["end"] if seg_data else 0
    total_min = int(total_duration // 60)
    total_sec = int(total_duration % 60)

    mobile_html = f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Presentation Viewer — {len(seg_data)} slides, {total_min}m {total_sec}s</title>
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
       background: #1a1a2e; color: #e0e0e0; }}
.container {{ display: flex; height: 100vh; }}
.video-panel {{ flex: 1; display: flex; flex-direction: column; align-items: center;
               justify-content: center; padding: 20px; background: #16213e; }}
.video-panel video {{ max-width: 100%; max-height: 70vh; border-radius: 8px;
                      box-shadow: 0 4px 20px rgba(0,0,0,0.5); }}
.video-panel h2 {{ color: #a0c4ff; margin-bottom: 12px; font-size: 14px;
                   letter-spacing: 1px; text-transform: uppercase; }}
.speed-bar {{ display: flex; gap: 6px; margin-top: 14px; align-items: center; }}
.speed-bar span {{ font-size: 12px; color: #7a8ba8; margin-right: 4px; }}
.speed-btn {{ background: rgba(255,255,255,0.08); border: 1px solid #334155;
              color: #94a3b8; padding: 5px 12px; border-radius: 6px; cursor: pointer;
              font-size: 13px; transition: all 0.15s; }}
.speed-btn:hover {{ background: rgba(255,255,255,0.15); color: #e0e0e0; }}
.speed-btn.active {{ background: #539cff; color: #fff; border-color: #539cff; }}
.script-panel {{ width: 420px; min-width: 350px; overflow-y: auto; padding: 20px;
                background: #0f3460; border-left: 2px solid #1a1a2e; }}
.script-panel h2 {{ color: #a0c4ff; margin-bottom: 16px; font-size: 14px;
                    letter-spacing: 1px; text-transform: uppercase;
                    position: sticky; top: 0; background: #0f3460; padding: 8px 0; z-index: 1; }}
.seg {{ padding: 14px 16px; margin-bottom: 10px; border-radius: 8px;
        border-left: 3px solid transparent; transition: all 0.3s ease;
        cursor: pointer; background: rgba(255,255,255,0.03); }}
.seg:hover {{ background: rgba(255,255,255,0.08); }}
.seg.active {{ background: rgba(83,156,255,0.15); border-left-color: #539cff; }}
.seg-header {{ font-weight: 600; color: #539cff; margin-bottom: 6px;
              display: flex; justify-content: space-between; align-items: center; font-size: 13px; }}
.seg-time {{ font-weight: 400; color: #7a8ba8; font-size: 12px; }}
.seg-text {{ font-size: 14px; line-height: 1.6; color: #c8d6e5; }}
.seg.active .seg-text {{ color: #f0f0f0; }}
.seg-notes {{ margin-top: 10px; padding: 10px 12px; background: rgba(251,191,36,0.12);
              border: 1px solid rgba(251,191,36,0.3); border-radius: 6px;
              font-size: 13px; line-height: 1.55; color: #fde68a; }}
.seg-notes-label {{ display: block; font-size: 11px; font-weight: 600;
                    text-transform: uppercase; letter-spacing: 0.5px;
                    color: #fbbf24; margin-bottom: 4px; }}
.notes-bar {{ width: 100%; margin-top: 14px; padding: 12px 16px;
             background: rgba(251,191,36,0.10); border: 1px solid rgba(251,191,36,0.25);
             border-radius: 8px; min-height: 48px; max-height: 120px; overflow-y: auto;
             transition: opacity 0.3s ease; }}
.notes-bar.empty {{ opacity: 0.4; }}
.notes-bar-label {{ font-size: 11px; font-weight: 600; text-transform: uppercase;
                    letter-spacing: 0.5px; color: #fbbf24; margin-bottom: 4px; }}
.notes-bar-text {{ font-size: 13px; line-height: 1.5; color: #fde68a; }}
.notes-bar-text.placeholder {{ color: #7a8ba8; font-style: italic; }}
.script-panel::-webkit-scrollbar {{ width: 6px; }}
.script-panel::-webkit-scrollbar-track {{ background: transparent; }}
.script-panel::-webkit-scrollbar-thumb {{ background: #475569; border-radius: 3px; }}
@media (max-width: 768px) {{
    body {{ height: auto; overflow-y: auto; }}
    .container {{ flex-direction: column; height: auto; overflow-y: visible; }}
    .video-panel {{ padding: 12px; flex: none; }}
    .video-panel video {{ max-height: 35vh; width: 100%; }}
    .script-panel {{ width: 100%; min-width: unset; max-height: none;
                     overflow-y: visible;
                     border-left: none; border-top: 2px solid #1a1a2e; }}
    .speed-bar {{ flex-wrap: wrap; }}
    .notes-bar {{ max-height: 100px; }}
}}
</style>
</head>
<body>
<div class="container">
    <div class="video-panel">
        <h2>Presentation</h2>
        <video id="vid" controls playsinline webkit-playsinline>
            <source src="{mp4_filename}" type="video/mp4">
        </video>
        <div class="speed-bar">
            <span>Speed:</span>
            <button class="speed-btn" data-speed="0.5">0.5x</button>
            <button class="speed-btn" data-speed="0.75">0.75x</button>
            <button class="speed-btn active" data-speed="1">1x</button>
            <button class="speed-btn" data-speed="1.25">1.25x</button>
            <button class="speed-btn" data-speed="1.5">1.5x</button>
            <button class="speed-btn" data-speed="2">2x</button>
        </div>
        {notes_bar_html}
    </div>
    <div class="script-panel" id="scriptPanel">
        <h2>Speaker Script</h2>
{seg_blocks}
    </div>
</div>
<script>
const vid = document.getElementById("vid");
vid.playsInline = true;
const segs = document.querySelectorAll(".seg");
const panel = document.getElementById("scriptPanel");
const notesBar = document.getElementById("notesBar");
const notesText = document.getElementById("notesText");
const notesData = [{notes_js_array}];

document.querySelectorAll(".speed-btn").forEach(btn => {{
    btn.addEventListener("click", () => {{
        const speed = parseFloat(btn.dataset.speed);
        vid.playbackRate = speed;
        document.querySelectorAll(".speed-btn").forEach(b => b.classList.remove("active"));
        btn.classList.add("active");
    }});
}});

segs.forEach(s => {{
    s.addEventListener("click", () => {{
        vid.currentTime = parseFloat(s.dataset.start);
        vid.play();
    }});
}});

let lastNotesSlide = -1;
vid.addEventListener("timeupdate", () => {{
    const t = vid.currentTime;
    let activeEl = null;
    segs.forEach(s => {{
        const start = parseFloat(s.dataset.start);
        const end = parseFloat(s.dataset.end);
        if (t >= start && t < end) {{
            s.classList.add("active");
            activeEl = s;
        }} else {{
            s.classList.remove("active");
        }}
    }});
    if (activeEl) {{
        const panelRect = panel.getBoundingClientRect();
        const elRect = activeEl.getBoundingClientRect();
        const offset = elRect.top - panelRect.top - panelRect.height / 3;
        if (Math.abs(offset) > 20) {{
            panel.scrollBy({{ top: offset, behavior: "smooth" }});
        }}
    }}
    if (notesBar && notesText) {{
        const nd = notesData.find(n => t >= n.start && t < n.end);
        const slideNum = nd ? nd.slide : -1;
        if (slideNum !== lastNotesSlide) {{
            lastNotesSlide = slideNum;
            if (nd && nd.notes) {{
                notesBar.classList.remove("empty");
                notesText.classList.remove("placeholder");
                notesText.innerHTML = "<strong>Slide " + nd.slide + ":</strong> " + nd.notes;
            }} else {{
                notesBar.classList.add("empty");
                notesText.classList.add("placeholder");
                notesText.innerHTML = nd ? "No notes for slide " + nd.slide : "Notes will appear here as the presentation plays";
            }}
        }}
    }}
}});
</script>
</body>
</html>'''

    viewer_html_path = mobile_dir / f"{stem}_viewer.html"
    viewer_html_path.write_text(mobile_html, encoding="utf-8")

    html_kb = viewer_html_path.stat().st_size / 1024
    mp4_mb = mp4_path.stat().st_size / (1024 * 1024)
    print(f"  MOBILE {mobile_dir}/")
    print(f"         HTML:  {viewer_html_path.name} ({html_kb:.0f} KB)")
    print(f"         Video: {mp4_filename} ({mp4_mb:.1f} MB)")
    return True


def main():
    if len(sys.argv) < 2 or (len(sys.argv) == 2 and sys.argv[1] == "--force"):
        print("Usage: python fix_viewer_mobile.py [--force] <viewer.html> [viewer2.html ...]")
        print("       python fix_viewer_mobile.py [--force] outputs/*_viewer.html")
        print()
        print("Options:")
        print("  --force   Re-patch files that were already patched")
        sys.exit(1)

    force = "--force" in sys.argv
    files = [f for f in sys.argv[1:] if f != "--force"]

    fixed = 0
    mobile = 0
    for f in files:
        if fix_viewer_html(f, force=force):
            fixed += 1
        if generate_mobile_version(f):
            mobile += 1

    print(f"\nDone: {fixed} file(s) patched, {mobile} mobile version(s) created, "
          f"{len(files) - fixed} skipped.")
    if fixed:
        print("Originals backed up as *_backup.html (first run only)")
    if mobile:
        print("Mobile folders contain HTML + MP4 — upload both files to Dropbox/iCloud/etc.")


if __name__ == "__main__":
    main()
