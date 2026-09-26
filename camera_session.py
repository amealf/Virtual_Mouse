"""Threaded camera capture and gesture-dispatch session.

The GUI owns a :class:`CameraSession` but never owns ``VideoCapture`` or the
MediaPipe landmarker.  Keeping both objects on one daemon worker makes camera
shutdown predictable and lets a hotkey disable desktop actions immediately,
even while the camera driver is finishing ``release()``.
"""

from __future__ import annotations

from pathlib import Path
import queue
import threading
import time
from typing import Any

import cv2
import pyautogui

from gesture_engine import GestureEngine, GestureFrame
from hand_tracker import HandTracker
from system_actions import DesktopController, launch_program


CAMERA_WIDTH = 640
CAMERA_HEIGHT = 480
CAMERA_FPS = 30


class CameraSession:
    """Own one camera worker and the state needed by a camera-control UI.

    ``start`` and ``stop`` are safe to call from a GUI thread.  ``stop`` only
    signals the worker and returns; it never waits for a camera driver.  The
    state therefore remains ``"stopping"`` until the worker has released its
    capture object and completed its MediaPipe cleanup.
    """

    VALID_STATES = frozenset(("off", "starting", "on", "stopping", "error"))

    def __init__(self, model_path: Path, camera_index: int = 0) -> None:
        self.model_path = Path(model_path)
        self.camera_index = int(camera_index)
        # The GUI may set this to any user-selected executable before calling
        # start().  None disables the snap launch action.
        self.program_path: Path | None = None

        # Events are status notifications rather than a frame transport.  Keep
        # a finite queue so a paused GUI cannot retain an unbounded history.
        self.queue: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=64)
        # ``events`` keeps the desktop panel's polling code readable while
        # ``queue`` remains the documented public name.
        self.events = self.queue

        self._state = "off"
        self._status = "Camera off"
        self._error = ""
        self._image: Any | None = None
        self._last_event: dict[str, Any] | None = None

        self._lock = threading.RLock()
        # Every desktop action goes through this lock.  stop() takes it before
        # disabling dispatch, so an action either finishes before stop returns
        # or is skipped after dispatch has been disabled.
        self._dispatch_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._generation = 0
        self._event_epoch = 0
        self._dispatch_enabled = False
        self._preview_only = False
        self._mouse_enabled = False
        self._auto_off_after_action = False
        self._fatal_error: str | None = None
        self._fps: float | None = None
        self._fps_frame_count = 0
        self._fps_started_at: float | None = None

    @property
    def is_running(self) -> bool:
        """Whether a worker is still active, including during camera stop."""

        with self._lock:
            return self._state in ("starting", "on", "stopping")

    @property
    def fps(self) -> float | None:
        """Measured capture rate, or ``None`` before the first frame."""

        with self._lock:
            return self._fps

    def start(self, preview_only: bool = False, auto_off_after_action: bool = False, mouse_enabled: bool = True) -> bool:
        """Start a worker if the session is currently idle.

        The return value indicates that a worker was scheduled.  Camera-open
        errors are reported asynchronously through ``get_snapshot`` and
        ``queue`` because opening a camera can block on a Windows driver.
        """

        with self._lock:
            if self._state in ("starting", "on", "stopping"):
                return False

            self._generation += 1
            generation = self._generation
            self._event_epoch += 1
            event_epoch = self._event_epoch
            self._stop_event = threading.Event()
            self._dispatch_enabled = True
            self._preview_only = bool(preview_only)
            self._mouse_enabled = bool(mouse_enabled)
            self._auto_off_after_action = bool(auto_off_after_action)
            self._image = None
            self._last_event = None
            self._error = ""
            self._fatal_error = None
            self._status = "Starting camera"
            self._state = "starting"
            self._fps = None
            self._fps_frame_count = 0
            self._fps_started_at = None
            worker = threading.Thread(
                target=self._worker_main,
                args=(generation, event_epoch),
                name="MediaPipeCameraSession",
                daemon=True,
            )
            self._thread = worker

        worker.start()
        return True

    def stop(self) -> None:
        """Request camera shutdown without waiting for the worker.

        Retained frames are discarded immediately for privacy.  The worker
        finishes the driver cleanup in the background and then changes state to
        ``"off"`` (or leaves an actual failure in ``"error"``).
        """

        # Serialize with an in-flight desktop operation.  This short critical
        # section is the guarantee that no OS action can occur after stop()
        # returns, even if the worker was between two gesture actions.
        with self._dispatch_lock:
            with self._lock:
                if self._state in ("off", "error"):
                    self._event_epoch += 1
                    self._dispatch_enabled = False
                    self._image = None
                    self._last_event = None
                    if self._state == "error":
                        self._state = "off"
                        self._status = "Camera off"
                        self._error = ""
                    return

                self._dispatch_enabled = False
                self._event_epoch += 1
                self._image = None
                self._last_event = None
                self._status = "Stopping camera"
                self._state = "stopping"
                self._stop_event.set()

    def close(self) -> None:
        """Release the session resources by requesting a stop."""

        self.stop()

    def event_is_current(self, event: dict[str, Any] | None) -> bool:
        """Return whether an event belongs to the current camera epoch.

        Stopping or starting the session advances the epoch.  Events stay in
        the bounded queue so diagnostics are not lost, while a GUI can ignore
        notifications produced before the latest lifecycle boundary.
        """

        if not isinstance(event, dict):
            return False
        with self._lock:
            return (
                event.get("epoch") == self._event_epoch
                and event.get("generation") == self._generation
            )

    def get_snapshot(self) -> dict[str, Any]:
        """Return an atomic copy of the UI-visible camera state."""

        with self._lock:
            image = self._image.copy() if self._image is not None else None
            snapshot: dict[str, Any] = {
                "state": self._state,
                "image": image,
                "status": self._status,
                "error": self._error,
            }
            if self._last_event is not None:
                snapshot["event"] = dict(self._last_event)
            return snapshot

    def _emit(
        self,
        kind: str,
        message: str,
        *,
        generation: int | None = None,
        epoch: int | None = None,
    ) -> None:
        with self._lock:
            if generation is None:
                generation = self._generation
            if epoch is None:
                epoch = self._event_epoch
        event = {
            "kind": kind,
            "message": message,
            "generation": generation,
            "epoch": epoch,
        }
        try:
            self.queue.put_nowait(event)
        except queue.Full:
            # Preserve the newest UI information when a consumer is paused.
            try:
                self.queue.get_nowait()
            except queue.Empty:
                pass
            try:
                self.queue.put_nowait(event)
            except queue.Full:
                pass
        with self._lock:
            if generation == self._generation and epoch == self._event_epoch:
                self._last_event = event

    def _set_status(self, status: str, generation: int) -> bool:
        with self._lock:
            if generation != self._generation or self._state == "stopping":
                return False
            self._status = status
            return True

    def _set_image(self, image: Any, generation: int) -> bool:
        with self._lock:
            if generation != self._generation or self._state == "stopping":
                return False
            self._image = image.copy()
            return True

    def _dispatch_action(
        self,
        generation: int,
        action,
        event_epoch: int | None = None,
    ) -> tuple[bool, Any]:
        """Run one desktop action only while dispatch remains enabled."""

        if event_epoch is None:
            with self._lock:
                event_epoch = self._event_epoch
        with self._dispatch_lock:
            with self._lock:
                if (
                    not self._dispatch_enabled
                    or generation != self._generation
                    or self._state == "stopping"
                ):
                    return False, None
            try:
                return True, action()
            except pyautogui.FailSafeException as exc:
                message = "PyAutoGUI fail-safe activated. Camera stopped."
                self._emit(
                    "error",
                    message,
                    generation=generation,
                    epoch=event_epoch,
                )
                # _dispatch_action owns _dispatch_lock here; request the stop
                # under the state lock instead of calling stop(), which would
                # wait on the same lock and deadlock the worker.
                with self._lock:
                    if generation == self._generation and self._state not in ("off", "error"):
                        self._dispatch_enabled = False
                        self._image = None
                        self._status = "Stopping camera"
                        self._state = "stopping"
                        self._fatal_error = message
                        self._stop_event.set()
                return False, exc
            except Exception as exc:  # OS automation errors are session errors.
                self._emit(
                    "error",
                    f"Desktop action failed: {exc}",
                    generation=generation,
                    epoch=event_epoch,
                )
                return False, exc

    def _dispatch_frame(
        self,
        frame: GestureFrame,
        generation: int,
        preview_only: bool,
        auto_off_after_action: bool,
        desktop: DesktopController | None,
        event_epoch: int | None = None,
    ) -> None:
        """Apply one gesture frame while honoring privacy and stop settings."""

        if event_epoch is None:
            with self._lock:
                event_epoch = self._event_epoch
        if frame.visual_snap_time is not None:
            self._emit(
                "gesture",
                "Snap detected",
                generation=generation,
                epoch=event_epoch,
            )
            if preview_only:
                return
            ok, result = self._dispatch_action(
                generation,
                lambda: launch_program(self.program_path),
                event_epoch,
            )
            if not ok:
                return
            launched, message = result
            self._emit("info", message, generation=generation, epoch=event_epoch)
            if launched and auto_off_after_action:
                self.stop()
            return

        if preview_only:
            # A preview may display gesture status but never call pyautogui or
            # launch an application, including for a swipe-exit frame.
            return

        click_succeeded = False
        if desktop is not None and frame.cursor is not None:
            self._dispatch_action(
                generation,
                lambda: desktop.move_cursor(frame.cursor),
                event_epoch,
            )
        if desktop is not None and frame.left_click:
            ok, _ = self._dispatch_action(generation, desktop.left_click, event_epoch)
            click_succeeded = click_succeeded or ok
        if desktop is not None and frame.right_click:
            ok, _ = self._dispatch_action(generation, desktop.right_click, event_epoch)
            click_succeeded = click_succeeded or ok
        if desktop is not None and frame.scroll:
            self._dispatch_action(
                generation,
                lambda: desktop.scroll(frame.scroll),
                event_epoch,
            )

        if frame.exit_requested:
            self._dispatch_action(
                generation,
                lambda: self._emit(
                    "exit",
                    "Horizontal swipe detected",
                    generation=generation,
                    epoch=event_epoch,
                ),
                event_epoch,
            )

        # Clicks are discrete actions and can turn the camera off when the GUI
        # asks for one-shot behavior.  Cursor motion and continuous scroll do
        # not trigger this setting.
        if auto_off_after_action and click_succeeded:
            self.stop()

    def _worker_main(self, generation: int, event_epoch: int) -> None:
        cap = None
        tracker = None
        gestures = None
        desktop: DesktopController | None = None
        failure: str | None = None

        with self._lock:
            preview_only = self._preview_only
            mouse_enabled = self._mouse_enabled
            auto_off_after_action = self._auto_off_after_action

        try:
            gestures = GestureEngine()
            cap = cv2.VideoCapture(self.camera_index)
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, CAMERA_WIDTH)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CAMERA_HEIGHT)
            cap.set(cv2.CAP_PROP_FPS, CAMERA_FPS)
            if not cap.isOpened():
                raise RuntimeError(f"Could not open camera {self.camera_index}.")

            tracker = HandTracker(self.model_path, max_hands=1)
            if not preview_only and mouse_enabled:
                desktop = DesktopController()

            with self._lock:
                if generation != self._generation or self._stop_event.is_set():
                    # stop() already moved the public state to stopping.
                    pass
                elif self._state == "starting":
                    self._state = "on"
                    self._status = "Waiting for hand"
                    self._emit(
                        "info",
                        "Camera started",
                        generation=generation,
                        epoch=event_epoch,
                    )

            while not self._stop_event.is_set():
                success, image = cap.read()
                if not success:
                    if self._stop_event.is_set():
                        break
                    raise RuntimeError("Camera frame unavailable.")

                image = cv2.flip(image, 1)
                now = time.monotonic()
                with self._lock:
                    if self._fps_started_at is None:
                        self._fps_started_at = now
                    self._fps_frame_count += 1
                    elapsed = now - self._fps_started_at
                    if elapsed >= 0.5:
                        self._fps = self._fps_frame_count / elapsed
                        self._fps_frame_count = 0
                        self._fps_started_at = now
                observation = tracker.process(
                    image,
                    int(now * 1000),
                    draw=True,
                )

                if observation is None:
                    gestures.reset(preserve_motion=True)
                    status = "Waiting for hand"
                else:
                    frame = gestures.update(observation.landmarks, now)
                    status = frame.status
                    self._dispatch_frame(
                        frame,
                        generation,
                        preview_only,
                        auto_off_after_action,
                        desktop,
                        event_epoch,
                    )

                if not self._set_status(status, generation):
                    break
                if not self._set_image(image, generation):
                    break
        except Exception as exc:
            failure = str(exc)
        finally:
            # Close MediaPipe before releasing the camera.  Both cleanup calls
            # are attempted even when the first one fails.
            cleanup_error: str | None = None
            if tracker is not None:
                try:
                    tracker.close()
                except Exception as exc:
                    cleanup_error = f"Hand tracker cleanup failed: {exc}"
            if cap is not None:
                try:
                    cap.release()
                except Exception as exc:
                    cleanup_error = f"Camera cleanup failed: {exc}"

            with self._lock:
                current = generation == self._generation
                stopped = self._stop_event.is_set() or self._state == "stopping"
                fatal_error = self._fatal_error
                if current:
                    self._image = None
                    self._thread = None
                    self._dispatch_enabled = False
                    if cleanup_error is not None:
                        self._state = "error"
                        self._error = cleanup_error
                        self._status = "Camera error"
                    elif fatal_error is not None:
                        self._state = "error"
                        self._error = fatal_error
                        self._status = "Camera error"
                    elif failure is not None and not stopped:
                        self._state = "error"
                        self._error = failure
                        self._status = "Camera error"
                    else:
                        self._state = "off"
                        self._error = ""
                        self._status = "Camera off"

            if cleanup_error is not None:
                self._emit(
                    "error",
                    cleanup_error,
                    generation=generation,
                    epoch=event_epoch,
                )
            elif failure is not None and not stopped:
                self._emit(
                    "error",
                    failure,
                    generation=generation,
                    epoch=event_epoch,
                )
            elif not stopped:
                # A worker ending without a stop request is unexpected, but
                # keeping this information in the queue makes it visible to a
                # GUI without pretending it was a user action.
                self._emit(
                    "info",
                    "Camera stopped",
                    generation=generation,
                    epoch=event_epoch,
                )


__all__ = ["CameraSession"]
