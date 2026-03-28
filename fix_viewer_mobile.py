#!/usr/bin/env python3
"""
Fix existing presentation viewer HTML files for mobile playback.

Mobile Safari and some Android browsers don't support video playback from
data: URIs. This script converts existing viewer HTML files to use Blob URLs
instead, and adds responsive CSS + viewport meta for mobile layout.

Usage:
    python fix_viewer_mobile.py viewer1.html viewer2.html ...
    python fix_viewer_mobile.py outputs/*_viewer.html

The original file is backed up as <name>_backup.html before patching.
"""

import re
import sys
import shutil
from pathlib import Path


def fix_viewer_html(filepath: str) -> bool:
    """
    Patch a single viewer HTML file for mobile compatibility.
    Returns True if the file was patched, False if skipped.
    """
    path = Path(filepath)
    if not path.exists():
        print(f"  SKIP  {filepath} (file not found)")
        return False

    html = path.read_text(encoding="utf-8")

    # Check if already patched (has Blob URL loader)
    if "URL.createObjectURL" in html:
        print(f"  SKIP  {filepath} (already patched)")
        return False

    # Find the data URI in the source tag
    data_uri_match = re.search(
        r'<source\s+src="data:video/mp4;base64,([^"]+)"\s+type="video/mp4"\s*/?>',
        html,
    )
    if not data_uri_match:
        print(f"  SKIP  {filepath} (no base64 video data URI found)")
        return False

    video_b64 = data_uri_match.group(1)

    # Back up the original
    backup_path = path.with_stem(path.stem + "_backup")
    shutil.copy2(path, backup_path)
    print(f"  BACKUP {backup_path.name}")

    # 1. Add viewport meta tag if missing
    if '<meta name="viewport"' not in html:
        html = html.replace(
            '<meta charset="UTF-8">',
            '<meta charset="UTF-8">\n<meta name="viewport" content="width=device-width, initial-scale=1">',
        )

    # 2. Replace <video> with data URI → plain <video> with playsinline
    #    Handle both <source .../> and <source ...></source> variants
    html = re.sub(
        r'<video\s+id="vid"\s+controls\s*>.*?</video>',
        '<video id="vid" controls playsinline webkit-playsinline></video>\n'
        '        <div id="loadingMsg" style="color:#7a8ba8;font-size:13px;margin-top:8px;">Loading video...</div>',
        html,
        flags=re.DOTALL,
    )

    # 3. Add responsive CSS before </style>
    responsive_css = """
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
    if "@media" not in html:
        html = html.replace("</style>", responsive_css + "</style>")

    # 4. Reduce max video height for desktop too (leave room for controls)
    html = html.replace("max-height: 80vh", "max-height: 70vh")

    # 5. Add Blob URL loader at the start of the <script> block
    blob_loader = f'''
// Convert base64 video to Blob URL for mobile compatibility
// (mobile Safari does not support data: URIs on <video> elements)
const videoB64 = "{video_b64}";
const loadMsg = document.getElementById("loadingMsg");
try {{
    const byteChars = atob(videoB64);
    const len = byteChars.length;
    const bytes = new Uint8Array(len);
    for (let i = 0; i < len; i++) bytes[i] = byteChars.charCodeAt(i);
    const blob = new Blob([bytes], {{ type: "video/mp4" }});
    const blobUrl = URL.createObjectURL(blob);
    document.getElementById("vid").src = blobUrl;
    if (loadMsg) loadMsg.style.display = "none";
}} catch(e) {{
    if (loadMsg) loadMsg.textContent = "Error loading video: " + e.message;
    console.error("Video blob creation failed:", e);
}}

'''
    html = html.replace("<script>\n", "<script>\n" + blob_loader, 1)

    # Write patched file
    path.write_text(html, encoding="utf-8")
    size_mb = path.stat().st_size / (1024 * 1024)
    print(f"  FIXED {filepath} ({size_mb:.1f} MB)")
    return True


def main():
    if len(sys.argv) < 2:
        print("Usage: python fix_viewer_mobile.py <viewer.html> [viewer2.html ...]")
        print("       python fix_viewer_mobile.py outputs/*_viewer.html")
        sys.exit(1)

    files = sys.argv[1:]
    fixed = 0
    for f in files:
        if fix_viewer_html(f):
            fixed += 1

    print(f"\nDone: {fixed} file(s) patched, {len(files) - fixed} skipped.")
    if fixed:
        print("Originals backed up as *_backup.html")


if __name__ == "__main__":
    main()
