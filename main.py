import argparse
from pathlib import Path
import time

import cv2
import pyautogui

from gesture_engine import GestureEngine
from hand_tracker import HandTracker
from system_actions import DesktopController, find_codex_executable, launch_codex


PROJECT_DIR = Path(__file__).resolve().parent
MODEL_PATH = PROJECT_DIR / "hand_landmarker.task"
CAMERA_WIDTH = 640
CAMERA_HEIGHT = 480
PREVIEW_SIZE = (1600, 1200)
SNAP_LAUNCH_COOLDOWN = 3.0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Control Windows with MediaPipe hand gestures.")
    parser.add_argument("--headless", action="store_true", help="Hide the camera preview window.")
    parser.add_argument("--camera", type=int, default=0, help="Camera index. Default: 0")
    parser.add_argument("--preview-only", action="store_true", help="Recognize gestures without controlling the desktop.")
    parser.add_argument("--test-seconds", type=float, default=0, help="Stop automatically after this many seconds.")
    parser.add_argument("--snapshot", type=Path, help="Save a preview frame when the timed test finishes.")
    return parser.parse_args()


def draw_overlay(image, status: str, fingers: list[int] | None) -> None:
    height, width, _ = image.shape
    cv2.rectangle(image, (0, 0), (width, 84), (24, 24, 24), cv2.FILLED)
    cv2.putText(image, f"Gesture: {status}", (16, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.70, (91, 221, 255), 2)
    finger_text = "-" if fingers is None else "".join(str(value) for value in fingers)
    cv2.putText(image, f"Fingers: {finger_text}", (16, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.58, (220, 220, 220), 1)
    audio_text = "Snap: visual motion"
    cv2.putText(image, audio_text, (width - 270, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.48, (170, 255, 170), 1)
    cv2.putText(image, "ESC/Q: emergency stop", (width - 270, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.48, (170, 170, 255), 1)
    cv2.rectangle(image, (96, 96), (width - 96, height - 72), (255, 0, 255), 2)


def main() -> int:
    args = parse_args()
    if not MODEL_PATH.is_file():
        print(f"Hand landmark model was not found: {MODEL_PATH}")
        return 1

    codex_executable = find_codex_executable()
    if codex_executable:
        print(f"Codex: {codex_executable}")
    else:
        print("Codex executable was not found. Snap launch will remain inactive.")

    camera = cv2.VideoCapture(args.camera)
    camera.set(cv2.CAP_PROP_FRAME_WIDTH, CAMERA_WIDTH)
    camera.set(cv2.CAP_PROP_FRAME_HEIGHT, CAMERA_HEIGHT)
    camera.set(cv2.CAP_PROP_FPS, 30)
    if not camera.isOpened():
        camera.release()
        print(f"Could not open camera {args.camera}.")
        return 1

    tracker = HandTracker(MODEL_PATH)
    gestures = GestureEngine()
    desktop = DesktopController()
    last_codex_launch = -10.0
    snap_feedback_until = 0.0
    status = "Waiting for hand"
    fingers: list[int] | None = None
    started = time.monotonic()
    last_good_frame = started
    preview_opened = False

    print("Virtual Mouse is running.")
    print("Move: index finger | Left click: thumb-index pinch | Right click: hold thumb-middle pinch")
    print("Scroll: index + middle fingers, then move vertically")
    print("Launch Codex: finger snap | Exit: open-palm horizontal swipe | Emergency: ESC or Q")

    try:
        while True:
            success, image = camera.read()
            if not success:
                if time.monotonic() - last_good_frame > 3:
                    print("Camera stopped delivering frames. Exiting.")
                    break
                status = "Camera frame unavailable"
                time.sleep(0.01)
                continue

            image = cv2.flip(image, 1)
            now = time.monotonic()
            last_good_frame = now
            observation = tracker.process(image, int(now * 1000), draw=not args.headless)

            if observation is None:
                gestures.reset()
                status = "Waiting for hand"
                fingers = None
            else:
                frame = gestures.update(observation.landmarks, now)
                status = frame.status
                fingers = frame.fingers

                if frame.cursor is not None and not args.preview_only:
                    desktop.move_cursor(frame.cursor)
                if frame.left_click and not args.preview_only:
                    desktop.left_click()
                if frame.right_click and not args.preview_only:
                    desktop.right_click()
                if frame.scroll and not args.preview_only:
                    desktop.scroll(frame.scroll)
                if frame.visual_snap_time is not None:
                    snap_feedback_until = now + 1.0
                    if not args.preview_only and now - last_codex_launch >= SNAP_LAUNCH_COOLDOWN:
                        last_codex_launch = now
                        launched, message = launch_codex()
                        print(message)
                if frame.exit_requested and not args.preview_only:
                    print("Horizontal swipe detected. Exiting gesture controller.")
                    break

            if now < snap_feedback_until:
                status = "Snap detected"

            if not args.headless:
                if preview_opened and cv2.getWindowProperty("MediaPipe Gesture Controller", cv2.WND_PROP_VISIBLE) < 1:
                    break
                draw_overlay(image, status, fingers)
                image = cv2.resize(image, PREVIEW_SIZE, interpolation=cv2.INTER_LINEAR)
                cv2.imshow("MediaPipe Gesture Controller", image)
                preview_opened = True
                key = cv2.waitKey(1) & 0xFF
                if key in (27, ord("q")):
                    print("Emergency stop requested.")
                    break
            else:
                cv2.waitKey(1)
            if args.test_seconds > 0 and now - started >= args.test_seconds:
                if args.snapshot:
                    if args.headless:
                        draw_overlay(image, status, fingers)
                    if not cv2.imwrite(str(args.snapshot), image):
                        raise RuntimeError("Could not save preview snapshot")
                break
    except KeyboardInterrupt:
        print("Stopped from the terminal.")
    except pyautogui.FailSafeException:
        print("PyAutoGUI fail-safe activated. Gesture controller stopped.")
    finally:
        tracker.close()
        camera.release()
        cv2.destroyAllWindows()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
