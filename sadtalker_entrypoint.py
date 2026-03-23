#!/usr/bin/env python3
"""
Entrypoint for the SadTalker Docker container.
Accepts --source_image, --driven_audio, --result_dir, and optional flags.
Runs SadTalker inference on CPU and writes the output video to result_dir.
"""

import argparse
import os
import sys
import glob

def main():
    parser = argparse.ArgumentParser(description="SadTalker Docker inference")
    parser.add_argument("--source_image", required=True, help="Path to the avatar image")
    parser.add_argument("--driven_audio", required=True, help="Path to the speech audio file")
    parser.add_argument("--result_dir", required=True, help="Directory for output video")
    parser.add_argument("--enhancer", default="gfpgan", help="Face enhancer: gfpgan or none")
    parser.add_argument("--still", action="store_true", default=True,
                        help="Use still mode (less head motion, better for single photo)")
    parser.add_argument("--preprocess", default="crop", choices=["crop", "resize", "full"],
                        help="Preprocess mode for the face")
    parser.add_argument("--size", type=int, default=256, choices=[256, 512],
                        help="Output face resolution")
    args = parser.parse_args()

    # Validate inputs exist
    if not os.path.exists(args.source_image):
        print(f"ERROR: Source image not found: {args.source_image}", file=sys.stderr)
        sys.exit(1)
    if not os.path.exists(args.driven_audio):
        print(f"ERROR: Driven audio not found: {args.driven_audio}", file=sys.stderr)
        sys.exit(1)

    os.makedirs(args.result_dir, exist_ok=True)

    # Build the SadTalker inference command
    sadtalker_dir = "/app/SadTalker"
    sys.path.insert(0, sadtalker_dir)
    os.chdir(sadtalker_dir)

    # Set CPU device
    os.environ["CUDA_VISIBLE_DEVICES"] = ""

    cmd_args = [
        sys.executable, "inference.py",
        "--driven_audio", args.driven_audio,
        "--source_image", args.source_image,
        "--result_dir", args.result_dir,
        "--cpu",
    ]

    if args.still:
        cmd_args.append("--still")

    if args.enhancer and args.enhancer != "none":
        cmd_args.extend(["--enhancer", args.enhancer])

    cmd_args.extend(["--preprocess", args.preprocess])
    cmd_args.extend(["--size", str(args.size)])

    print(f"Running SadTalker inference (CPU mode) ...")
    print(f"  Image:  {args.source_image}")
    print(f"  Audio:  {args.driven_audio}")
    print(f"  Output: {args.result_dir}")
    print(f"  Size:   {args.size}")
    print(f"  Still:  {args.still}")
    print(f"  Enhance: {args.enhancer}")
    print()

    import subprocess
    result = subprocess.run(cmd_args, cwd=sadtalker_dir)

    if result.returncode != 0:
        print(f"ERROR: SadTalker inference failed with code {result.returncode}", file=sys.stderr)
        sys.exit(result.returncode)

    # Find the output video (SadTalker names it based on timestamp)
    output_files = sorted(
        glob.glob(os.path.join(args.result_dir, "**", "*.mp4"), recursive=True),
        key=os.path.getmtime,
        reverse=True,
    )

    if output_files:
        # Copy/rename the most recent output to a predictable name
        import shutil
        final_output = os.path.join(args.result_dir, "sadtalker_output.mp4")
        shutil.copy2(output_files[0], final_output)
        print(f"\nSADTALKER_OUTPUT:{final_output}")
    else:
        print("ERROR: No output video found after inference", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
