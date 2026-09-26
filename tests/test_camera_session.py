import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pyautogui

from gesture_engine import GestureFrame
from camera_session import CameraSession


def wait_until(predicate, timeout: float = 2.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


class BlockingCapture:
    def __init__(self, index: int) -> None:
        self.index = index
        self.read_started = threading.Event()
        self.allow_read_to_finish = threading.Event()
        self.release_started = threading.Event()
        self.allow_release_to_finish = threading.Event()
        self.released = threading.Event()

    def set(self, *_args) -> bool:
        return True

    def isOpened(self) -> bool:
        return True

    def read(self):
        self.read_started.set()
        self.allow_read_to_finish.wait(2.0)
        return False, None

    def release(self) -> None:
        self.release_started.set()
        self.allow_release_to_finish.wait(2.0)
        self.released.set()


class OneFrameCapture(BlockingCapture):
    def __init__(self, index: int) -> None:
        super().__init__(index)
        self._first = True

    def read(self):
        if self._first:
            self._first = False
            self.read_started.set()
            return True, np.zeros((480, 640, 3), dtype=np.uint8)
        return super().read()


class ClosedCapture:
    def __init__(self, index: int) -> None:
        self.released = threading.Event()

    def set(self, *_args) -> bool:
        return True

    def isOpened(self) -> bool:
        return False

    def release(self) -> None:
        self.released.set()


class FailingReleaseCapture(BlockingCapture):
    def release(self) -> None:
        self.release_started.set()
        raise RuntimeError("driver release failed")


class IdleTracker:
    def __init__(self, *_args, **_kwargs) -> None:
        pass

    def process(self, *_args, **_kwargs):
        return None

    def close(self) -> None:
        pass


class ActiveTracker(IdleTracker):
    class Observation:
        landmarks = [(0.5, 0.5, 0.0)] * 21

    def process(self, *_args, **_kwargs):
        return self.Observation()


class BlockingGestureEngine:
    entered = threading.Event()
    allow_update = threading.Event()

    def __init__(self) -> None:
        type(self).entered.clear()
        type(self).allow_update.clear()

    def update(self, *_args, **_kwargs):
        type(self).entered.set()
        type(self).allow_update.wait(2.0)
        return GestureFrame([0, 1, 0, 0, 0], cursor=(0.5, 0.5))

    def reset(self) -> None:
        pass


class FakeDesktop:
    def __init__(self) -> None:
        self.moves = []

    def move_cursor(self, point) -> None:
        self.moves.append(point)

    def left_click(self) -> None:
        pass

    def right_click(self) -> None:
        pass

    def scroll(self, _amount: int) -> None:
        pass


class FailSafeDesktop(FakeDesktop):
    def move_cursor(self, _point) -> None:
        raise pyautogui.FailSafeException("pointer reached corner")


class CameraSessionTests(unittest.TestCase):
    model_path = Path("hand_landmarker.task")

    def test_stop_is_nonblocking_and_release_finishes_state_transition(self) -> None:
        capture = BlockingCapture(0)
        with patch("camera_session.cv2.VideoCapture", return_value=capture), patch(
            "camera_session.HandTracker", ActiveTracker
        ):
            session = CameraSession(self.model_path)
            self.assertTrue(session.start(preview_only=True))
            self.assertTrue(wait_until(capture.read_started.is_set))

            session.stop()
            self.assertEqual(session.get_snapshot()["state"], "stopping")
            self.assertIsNone(session.get_snapshot()["image"])

            # A camera driver may still be inside read() or release(); the GUI
            # can return immediately and poll the stopping state.
            capture.allow_read_to_finish.set()
            self.assertTrue(wait_until(capture.release_started.is_set))
            self.assertEqual(session.get_snapshot()["state"], "stopping")
            capture.allow_release_to_finish.set()
            self.assertTrue(wait_until(lambda: session.get_snapshot()["state"] == "off"))
            self.assertTrue(capture.released.is_set())

    def test_stop_prevents_stale_frame_dispatch(self) -> None:
        capture = OneFrameCapture(0)
        desktop = FakeDesktop()
        with patch("camera_session.cv2.VideoCapture", return_value=capture), patch(
            "camera_session.HandTracker", ActiveTracker
        ), patch("camera_session.GestureEngine", BlockingGestureEngine), patch(
            "camera_session.DesktopController", return_value=desktop
        ):
            session = CameraSession(self.model_path)
            self.assertTrue(session.start())
            self.assertTrue(wait_until(BlockingGestureEngine.entered.is_set))

            session.stop()
            BlockingGestureEngine.allow_update.set()
            capture.allow_read_to_finish.set()
            capture.allow_release_to_finish.set()
            self.assertTrue(wait_until(lambda: session.get_snapshot()["state"] == "off"))
            self.assertEqual(desktop.moves, [])

    def test_camera_open_failure_releases_capture_and_reports_error(self) -> None:
        capture = ClosedCapture(0)
        with patch("camera_session.cv2.VideoCapture", return_value=capture), patch(
            "camera_session.HandTracker", IdleTracker
        ):
            session = CameraSession(self.model_path)
            self.assertTrue(session.start(preview_only=True))
            self.assertTrue(wait_until(lambda: session.get_snapshot()["state"] == "error"))

            snapshot = session.get_snapshot()
            self.assertIn("Could not open camera", snapshot["error"])
            self.assertIsNone(snapshot["image"])
            self.assertTrue(capture.released.is_set())
            event = session.queue.get(timeout=1.0)
            self.assertEqual(event["kind"], "error")

    def test_release_failure_stays_error_even_after_stop(self) -> None:
        capture = FailingReleaseCapture(0)
        with patch("camera_session.cv2.VideoCapture", return_value=capture), patch(
            "camera_session.HandTracker", IdleTracker
        ):
            session = CameraSession(self.model_path)
            self.assertTrue(session.start(preview_only=True))
            self.assertTrue(wait_until(capture.read_started.is_set))
            session.stop()
            capture.allow_read_to_finish.set()
            self.assertTrue(wait_until(lambda: session.get_snapshot()["state"] == "error"))

            snapshot = session.get_snapshot()
            self.assertIn("cleanup failed", snapshot["error"])
            events = []
            while not session.queue.empty():
                events.append(session.queue.get_nowait())
            self.assertTrue(any(event["kind"] == "error" for event in events))

    def test_failsafe_stops_worker_and_reports_error(self) -> None:
        capture = OneFrameCapture(0)
        desktop = FailSafeDesktop()
        with patch("camera_session.cv2.VideoCapture", return_value=capture), patch(
            "camera_session.HandTracker", ActiveTracker
        ), patch("camera_session.GestureEngine", BlockingGestureEngine), patch(
            "camera_session.DesktopController", return_value=desktop
        ):
            session = CameraSession(self.model_path)
            self.assertTrue(session.start())
            self.assertTrue(wait_until(BlockingGestureEngine.entered.is_set))
            BlockingGestureEngine.allow_update.set()
            capture.allow_read_to_finish.set()
            capture.allow_release_to_finish.set()
            self.assertTrue(wait_until(lambda: session.get_snapshot()["state"] == "error"))

            self.assertIn("fail-safe", session.get_snapshot()["error"])
            events = []
            while not session.queue.empty():
                events.append(session.queue.get_nowait())
            self.assertTrue(any(event["kind"] == "error" for event in events))

    def test_stop_blocks_stale_swipe_exit_event(self) -> None:
        session = CameraSession(self.model_path)
        session._generation = 1
        session._state = "stopping"
        session._dispatch_enabled = False
        frame = GestureFrame([1, 1, 1, 1, 1], exit_requested=True)

        session._dispatch_frame(frame, 1, False, False, FakeDesktop())

        self.assertTrue(session.queue.empty())

    def test_lifecycle_invalidates_old_events_without_clearing_queue(self) -> None:
        session = CameraSession(self.model_path)
        session._emit("info", "Before camera lifecycle change")
        old_event = session.get_snapshot()['event']

        session.stop()
        self.assertFalse(session.event_is_current(old_event))
        self.assertFalse(session.queue.empty())

        capture = ClosedCapture(0)
        with patch("camera_session.cv2.VideoCapture", return_value=capture), patch(
            "camera_session.HandTracker", IdleTracker
        ):
            self.assertTrue(session.start(preview_only=True))
            self.assertTrue(wait_until(lambda: session.get_snapshot()["state"] == "error"))

        events = []
        while not session.queue.empty():
            events.append(session.queue.get_nowait())
        self.assertIn(old_event, events)
        current_errors = [event for event in events if event["kind"] == "error"]
        self.assertTrue(current_errors)
        self.assertTrue(all(session.event_is_current(event) for event in current_errors))

    @patch("camera_session.launch_program", return_value=(True, "Program launched"))
    def test_snap_launches_selected_program_and_can_auto_stop(self, launch_program) -> None:
        session = CameraSession(self.model_path)
        selected = Path("C:/Tools/selected-program.exe")
        session.program_path = selected
        session._generation = 1
        session._event_epoch = 1
        session._state = "on"
        session._dispatch_enabled = True
        frame = GestureFrame([0, 0, 0, 0, 0], visual_snap_time=1.0)

        session._dispatch_frame(frame, 1, False, True, FakeDesktop(), 1)

        launch_program.assert_called_once_with(selected)
        self.assertEqual(session.get_snapshot()["state"], "stopping")

    def test_swipe_still_works_with_mouse_disabled(self):
        session = CameraSession(self.model_path)
        session._state = 'on'
        session._dispatch_enabled = True
        frame = GestureFrame([1, 1, 1, 1, 1], left_click=True, exit_requested=True)
        session._dispatch_frame(frame, 0, False, False, None)
        self.assertEqual(session.queue.get_nowait()['kind'], 'exit')


if __name__ == "__main__":
    unittest.main()
