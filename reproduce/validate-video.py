#!/usr/bin/env python3
"""Validate one Cosmos3-Super MP4 against the technical-output gate.

Requires ffmpeg and ffprobe on PATH. The gate requires a complete decode,
1280x720 geometry, exactly 189 frames, 24 fps, a duration near 7.875 seconds,
visible spatial detail, and change across sampled frames.
"""
import argparse
import json
import shutil
import statistics
import subprocess
import sys

EXPECTED = {
    "width": 1280,
    "height": 720,
    "fps": 24.0,
    "frames": 189,
    "min_seconds": 7.80,
    "max_seconds": 7.95,
}
SAMPLE_PIXELS = 32 * 32


def run(cmd, *, binary=False):
    return subprocess.run(cmd, capture_output=True, text=not binary, timeout=180)


def fail_result(errors, stream=None, samples=None):
    return {"valid": False, "errors": errors, "stream": stream, "sampled_frames": samples}


def validate(path):
    errors = []
    for executable in ("ffmpeg", "ffprobe"):
        if shutil.which(executable) is None:
            errors.append({"check": "dependency", "detail": f"{executable} not found"})
    if errors:
        return fail_result(errors)

    decoded = run(["ffmpeg", "-v", "error", "-i", path, "-map", "0:v:0", "-f", "null", "-"])
    if decoded.returncode != 0 or decoded.stderr.strip():
        errors.append({"check": "decode", "detail": decoded.stderr.strip() or "nonzero exit"})

    probed = run([
        "ffprobe", "-v", "error", "-select_streams", "v:0", "-count_frames",
        "-show_entries", "stream=width,height,avg_frame_rate,nb_read_frames,duration",
        "-of", "json", path,
    ])
    stream = None
    if probed.returncode != 0:
        errors.append({"check": "ffprobe", "detail": probed.stderr.strip() or "nonzero exit"})
    else:
        try:
            streams = json.loads(probed.stdout).get("streams", [])
            stream = streams[0] if streams else None
        except json.JSONDecodeError as exc:
            errors.append({"check": "ffprobe", "detail": str(exc)})
    if not stream:
        errors.append({"check": "stream", "detail": "no video stream"})
    else:
        if (stream.get("width"), stream.get("height")) != (EXPECTED["width"], EXPECTED["height"]):
            errors.append({"check": "geometry", "detail": f"{stream.get('width')}x{stream.get('height')}"})
        try:
            numer, denom = stream["avg_frame_rate"].split("/", 1)
            fps = float(numer) / float(denom)
            if abs(fps - EXPECTED["fps"]) > 0.001:
                errors.append({"check": "fps", "detail": fps})
        except (KeyError, ValueError, ZeroDivisionError) as exc:
            errors.append({"check": "fps", "detail": str(exc)})
        try:
            frames = int(stream["nb_read_frames"])
            if frames != EXPECTED["frames"]:
                errors.append({"check": "frames", "detail": frames})
        except (KeyError, TypeError, ValueError) as exc:
            errors.append({"check": "frames", "detail": str(exc)})
        try:
            duration = float(stream["duration"])
            if not EXPECTED["min_seconds"] <= duration <= EXPECTED["max_seconds"]:
                errors.append({"check": "duration", "detail": duration})
        except (KeyError, TypeError, ValueError) as exc:
            errors.append({"check": "duration", "detail": str(exc)})

    sampled = run([
        "ffmpeg", "-v", "error", "-i", path,
        "-vf", "select='eq(n,0)+eq(n,47)+eq(n,94)+eq(n,141)+eq(n,188)',scale=32:32,format=gray",
        "-vsync", "0", "-f", "rawvideo", "-",
    ], binary=True)
    samples = []
    if sampled.returncode != 0:
        detail = sampled.stderr.decode("utf-8", errors="replace").strip()
        errors.append({"check": "sampling", "detail": detail or "nonzero exit"})
    elif len(sampled.stdout) != 5 * SAMPLE_PIXELS:
        errors.append({"check": "sampling", "detail": f"expected {5 * SAMPLE_PIXELS} bytes, got {len(sampled.stdout)}"})
    else:
        frames = [sampled.stdout[i:i + SAMPLE_PIXELS] for i in range(0, len(sampled.stdout), SAMPLE_PIXELS)]
        for frame in frames:
            samples.append({
                "mean_luma": round(statistics.mean(frame), 3),
                "spatial_stdev": round(statistics.pstdev(frame), 3),
            })
        if max(s["spatial_stdev"] for s in samples) < 1.0:
            errors.append({"check": "blank", "detail": "all sampled frames lack spatial detail"})
        diffs = [statistics.mean(abs(a - b) for a, b in zip(frames[0], frame)) for frame in frames[1:]]
        if max(diffs, default=0.0) < 0.5:
            errors.append({"check": "frozen", "detail": "sampled frames do not change"})

    return {"valid": not errors, "errors": errors, "stream": stream, "sampled_frames": samples}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("video")
    parser.add_argument("--json", action="store_true", help="print machine-readable result")
    args = parser.parse_args()
    result = validate(args.video)
    if args.json:
        print(json.dumps(result, sort_keys=True))
    elif result["valid"]:
        st = result["stream"]
        print(f"VALID {args.video}: {st['width']}x{st['height']}, {st['avg_frame_rate']} fps, {st['nb_read_frames']} frames")
    else:
        print(f"INVALID {args.video}: {result['errors']}")
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    sys.exit(main())
