#!/usr/bin/env python3
"""
Fix existing presentation viewer HTML files for mobile playback.

Mobile Safari and some Android browsers don't support video playback from
data: URIs. This script converts existing viewer HTML files to use Blob URLs
instead, and adds responsive CSS + viewport meta for mobile layout.

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
    for f in files:
        if fix_viewer_html(f, force=force):
            fixed += 1

    print(f"\nDone: {fixed} file(s) patched, {len(files) - fixed} skipped.")
    if fixed:
        print("Originals backed up as *_backup.html (first run only)")


if __name__ == "__main__":
    main()
