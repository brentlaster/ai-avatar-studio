#!/usr/bin/env python3
"""
Wrapper script for SadTalker inference that patches the
torchvision.transforms.functional_tensor import error.

basicsr 1.4.2 imports from torchvision.transforms.functional_tensor,
which was removed in torchvision 0.17+. This wrapper creates a temporary
sitecustomize.py that patches sys.modules, then runs SadTalker's
inference.py in a subprocess with PYTHONPATH set so the patch loads first.

Usage (called by pipeline.py, not directly):
    python run_sadtalker.py --source_image IMG --driven_audio WAV --result_dir DIR [options]
"""

import sys
import os
import argparse
import glob
import shutil
import subprocess
import tempfile


def main():
    parser = argparse.ArgumentParser(description="SadTalker wrapper with torchvision patch")
    parser.add_argument("--source_image", required=True)
    parser.add_argument("--driven_audio", required=True)
    parser.add_argument("--result_dir", required=True)
    parser.add_argument("--enhancer", default=None)
    parser.add_argument("--still", action="store_true", default=False)
    parser.add_argument("--preprocess", default="crop")
    parser.add_argument("--size", type=int, default=256)
    parser.add_argument("--cpu", action="store_true", default=False)
    parser.add_argument("--expression_scale", type=float, default=1.0)
    parser.add_argument("--pose_style", type=int, default=0)
    args = parser.parse_args()

    # Validate inputs
    if not os.path.exists(args.source_image):
        print(f"ERROR: Source image not found: {args.source_image}", file=sys.stderr)
        sys.exit(1)
    if not os.path.exists(args.driven_audio):
        print(f"ERROR: Driven audio not found: {args.driven_audio}", file=sys.stderr)
        sys.exit(1)

    os.makedirs(args.result_dir, exist_ok=True)

    # Locate SadTalker
    script_dir = os.path.dirname(os.path.abspath(__file__))
    sadtalker_dir = os.path.join(script_dir, "SadTalker")

    if not os.path.exists(os.path.join(sadtalker_dir, "inference.py")):
        print(f"ERROR: SadTalker not found at {sadtalker_dir}", file=sys.stderr)
        sys.exit(1)

    # Create a temporary sitecustomize.py that patches the broken import.
    # Python auto-imports sitecustomize.py from any directory on PYTHONPATH.
    patch_dir = tempfile.mkdtemp(prefix="sadtalker_patch_")
    patch_file = os.path.join(patch_dir, "sitecustomize.py")
    with open(patch_file, "w") as f:
        f.write(
            "import sys\n"
            "import torchvision.transforms.functional as _F\n"
            "sys.modules['torchvision.transforms.functional_tensor'] = _F\n"
        )

    # Build inference command
    cmd = [
        sys.executable,
        os.path.join(sadtalker_dir, "inference.py"),
        "--driven_audio", os.path.abspath(args.driven_audio),
        "--source_image", os.path.abspath(args.source_image),
        "--result_dir", os.path.abspath(args.result_dir),
    ]

    if args.still:
        cmd.append("--still")
    if args.enhancer and args.enhancer.lower() != "none":
        cmd.extend(["--enhancer", args.enhancer])
    if args.cpu:
        cmd.append("--cpu")
    cmd.extend(["--preprocess", args.preprocess])
    cmd.extend(["--size", str(args.size)])
    cmd.extend(["--expression_scale", str(args.expression_scale)])
    cmd.extend(["--pose_style", str(args.pose_style)])

    # Set up environment with the patch directory first on PYTHONPATH
    env = os.environ.copy()
    existing_pythonpath = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = patch_dir + (":" + existing_pythonpath if existing_pythonpath else "")

    print("SadTalker Wrapper - Launching inference with torchvision patch ...")
    print(f"  Image:      {args.source_image}")
    print(f"  Audio:      {args.driven_audio}")
    print(f"  Output:     {args.result_dir}")
    print(f"  Size:       {args.size}")
    print(f"  Still:      {args.still}")
    print(f"  Enhance:    {args.enhancer}")
    print(f"  Expression: {args.expression_scale}x")
    print(f"  Pose style: {args.pose_style}")
    print(f"  CPU only:   {args.cpu}")
    print()

    try:
        result = subprocess.run(cmd, cwd=sadtalker_dir, env=env)
    finally:
        # Clean up the temp patch directory
        shutil.rmtree(patch_dir, ignore_errors=True)

    if result.returncode != 0:
        print(f"ERROR: SadTalker inference failed with code {result.returncode}", file=sys.stderr)
        sys.exit(result.returncode)

    # Find and report the output video
    output_files = sorted(
        glob.glob(os.path.join(args.result_dir, "**", "*.mp4"), recursive=True),
        key=os.path.getmtime,
        reverse=True,
    )

    if output_files:
        final_output = os.path.join(args.result_dir, "sadtalker_output.mp4")
        shutil.copy2(output_files[0], final_output)
        print(f"\nSADTALKER_OUTPUT:{final_output}")
    else:
        print("ERROR: No output video found after inference", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
