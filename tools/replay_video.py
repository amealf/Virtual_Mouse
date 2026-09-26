"""Replay recorded videos through the hand tracker and gesture engine.

This tool is intentionally offline: it reads an MP4, runs MediaPipe, writes
landmarks and gesture events, and never imports or calls any desktop action
module.  It is useful for regression checks against recorded gestures.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Iterable

import cv2

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from gesture_engine import GestureEngine
from hand_tracker import HandTracker


DEFAULT_MODEL = ROOT / "hand_landmarker.task"


def _json_float(value: float | None) -> float | None:
    return None if value is None else round(float(value), 6)


def _frame_event(frame, frame_index: int, timestamp: float) -> dict:
    return {
        "frame": frame_index,
        "time": round(timestamp, 4),
        "status": frame.status,
        "fingers": frame.fingers,
        "left_click": bool(frame.left_click),
        "right_click": bool(frame.right_click),
        "scroll": int(frame.scroll),
        "visual_snap": frame.visual_snap_time is not None,
        "exit_requested": bool(frame.exit_requested),
        "cursor": None if frame.cursor is None else [_json_float(v) for v in frame.cursor],
    }


def _observation_record(observation) -> dict:
    if observation is None:
        return {"hand": None}
    return {
        "hand": {
            "handedness": observation.handedness,
            "confidence": _json_float(observation.confidence),
            "landmarks": [
                [_json_float(point[0]), _json_float(point[1]), _json_float(point[2])]
                for point in observation.landmarks
            ],
        }
    }


def _write_jsonl(path: Path, records: Iterable[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")))
            handle.write("\n")


def _grid_size(count: int) -> tuple[int, int]:
    columns = min(4, max(1, math.ceil(math.sqrt(count))))
    rows = math.ceil(count / columns)
    return columns, rows


def make_contact_sheet(
    video_path: Path,
    output_path: Path,
    model_path: Path,
    sample_count: int = 16,
    tile_size: tuple[int, int] = (480, 270),
) -> dict:
    """Write a contact sheet with tracker points and sample timestamps."""
    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        raise RuntimeError(f"Could not open video: {video_path}")
    fps = float(capture.get(cv2.CAP_PROP_FPS) or 30.0)
    frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
    indices = [
        min(frame_count - 1, round(i * (frame_count - 1) / max(sample_count - 1, 1)))
        for i in range(sample_count)
    ] if frame_count else []
    tracker = HandTracker(model_path, max_hands=1)
    samples = []
    try:
        for index in indices:
            capture.set(cv2.CAP_PROP_POS_FRAMES, index)
            ok, image = capture.read()
            if not ok:
                continue
            observation = tracker.process(image, int(index / fps * 1000), draw=True)
            timestamp = index / fps
            cv2.rectangle(image, (0, 0), (image.shape[1], 44), (24, 24, 24), cv2.FILLED)
            text = f"{video_path.name}  {timestamp:05.2f}s  hand={'yes' if observation else 'no'}"
            cv2.putText(image, text, (14, 29), cv2.FONT_HERSHEY_SIMPLEX, 0.62, (220, 240, 255), 2)
            samples.append(cv2.resize(image, tile_size, interpolation=cv2.INTER_AREA))
    finally:
        tracker.close()
        capture.release()

    if not samples:
        raise RuntimeError(f"No frames could be sampled from {video_path}")
    columns, rows = _grid_size(len(samples))
    sheet = 255 * __import__("numpy").ones((rows * tile_size[1], columns * tile_size[0], 3), dtype="uint8")
    for offset, image in enumerate(samples):
        row, column = divmod(offset, columns)
        sheet[row * tile_size[1] : (row + 1) * tile_size[1], column * tile_size[0] : (column + 1) * tile_size[0]] = image
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(output_path), sheet):
        raise RuntimeError(f"Could not write contact sheet: {output_path}")
    return {
        "video": str(video_path),
        "fps": fps,
        "frame_count": frame_count,
        "duration": round(frame_count / fps, 4) if fps else None,
        "samples": len(samples),
        "output": str(output_path),
    }


def replay_video(video_path: Path, output_dir: Path, model_path: Path) -> dict:
    """Run a video through MediaPipe and GestureEngine with no side effects."""
    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        raise RuntimeError(f"Could not open video: {video_path}")
    fps = float(capture.get(cv2.CAP_PROP_FPS) or 30.0)
    frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
    tracker = HandTracker(model_path, max_hands=1)
    engine = GestureEngine()
    records = []
    event_records = []
    previous_status = None
    index = 0
    try:
        while True:
            ok, image = capture.read()
            if not ok:
                break
            timestamp = index / fps
            observation = tracker.process(image, int(timestamp * 1000), draw=False)
            if observation is None:
                # Motion blur can hide the hand for a few frames during a
                # swipe or snap.  Preserve only the short motion histories;
                # click holds are cleared by GestureEngine.reset().
                engine.reset(preserve_motion=True)
                frame = None
            else:
                frame = engine.update(observation.landmarks, timestamp)
            record = {
                "frame": index,
                "time": round(timestamp, 4),
                **_observation_record(observation),
                "gesture": None if frame is None else _frame_event(frame, index, timestamp),
            }
            records.append(record)
            if frame is not None:
                event = _frame_event(frame, index, timestamp)
                if (
                    event["status"] != previous_status
                    or event["left_click"]
                    or event["right_click"]
                    or event["visual_snap"]
                    or event["exit_requested"]
                ):
                    event_records.append(event)
                previous_status = event["status"]
            else:
                previous_status = "Waiting for hand"
            index += 1
    finally:
        tracker.close()
        capture.release()

    output_dir.mkdir(parents=True, exist_ok=True)
    landmarks_path = output_dir / f"{video_path.stem}.landmarks.jsonl"
    events_path = output_dir / f"{video_path.stem}.events.json"
    _write_jsonl(landmarks_path, records)
    events_path.write_text(json.dumps(event_records, ensure_ascii=False, indent=2), encoding="utf-8")
    counts = {
        "snap": sum(1 for event in event_records if event["visual_snap"]),
        "swipe_exit": sum(1 for event in event_records if event["exit_requested"]),
        "left_click": sum(1 for event in event_records if event["left_click"]),
        "right_click": sum(1 for event in event_records if event["right_click"]),
    }
    return {
        "video": str(video_path),
        "fps": fps,
        "frame_count": frame_count,
        "processed_frames": index,
        "duration": round(index / fps, 4) if fps else None,
        "hand_frames": sum(1 for record in records if record["hand"] is not None),
        "counts": counts,
        "landmarks": str(landmarks_path),
        "events": str(events_path),
        "event_records": event_records,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Offline MediaPipe gesture replay")
    parser.add_argument("videos", nargs="+", type=Path)
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--output-dir", type=Path, default=ROOT / ".artifacts" / "video-replay")
    parser.add_argument("--contact-sheet", action="store_true")
    parser.add_argument("--sample-count", type=int, default=16)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.model.is_file():
        raise SystemExit(f"Hand landmark model was not found: {args.model}")
    summaries = []
    for video_path in args.videos:
        if not video_path.is_file():
            raise SystemExit(f"Video was not found: {video_path}")
        if args.contact_sheet:
            contact_path = args.output_dir / f"{video_path.stem}.contact-sheet.png"
            make_contact_sheet(video_path, contact_path, args.model, args.sample_count)
        summaries.append(replay_video(video_path, args.output_dir, args.model))
    summary_path = args.output_dir / "summary.json"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summaries, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summaries, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
