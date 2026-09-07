from collections import deque
from dataclasses import dataclass

from utils import distance, fingers_up, palm_center, palm_size


@dataclass
class GestureFrame:
    fingers: list[int]
    status: str = "Tracking"
    cursor: tuple[float, float] | None = None
    left_click: bool = False
    right_click: bool = False
    scroll: int = 0
    visual_snap_time: float | None = None
    exit_requested: bool = False


class GestureEngine:
    """Temporal gesture recognizer built from MediaPipe hand landmarks."""

    PINCH_CLOSE_RATIO = 0.32
    PINCH_RELEASE_RATIO = 0.48
    LEFT_CLICK_HOLD_SECONDS = 0.12
    RIGHT_CLICK_HOLD_SECONDS = 0.40
    SNAP_MAX_SECONDS = 0.34
    SNAP_MIN_TRAVEL_RATIO = 0.32
    SWIPE_WINDOW_SECONDS = 0.55
    SWIPE_MIN_DISTANCE = 0.22
    SWIPE_MIN_PALM_RATIO = 1.25
    SWIPE_MIN_SPEED = 0.65
    SCROLL_MIN_DELTA = 0.012

    def __init__(self) -> None:
        self._index_pinch_started: float | None = None
        self._index_click_fired = False
        self._middle_pinch_started: float | None = None
        self._middle_pinch_start_point: tuple[float, float] | None = None
        self._middle_click_fired = False
        self._swipe_history: deque[tuple[float, float, float]] = deque()
        self._last_scroll_y: float | None = None
        self._last_click_time = -10.0

    def update(self, landmarks, now: float) -> GestureFrame:
        finger_state = fingers_up(landmarks)
        result = GestureFrame(fingers=finger_state)
        scale = palm_size(landmarks)
        thumb_index_ratio = distance(landmarks[4], landmarks[8]) / scale
        thumb_middle_ratio = distance(landmarks[4], landmarks[12]) / scale

        self._update_index_pinch(thumb_index_ratio, now, result)
        self._update_middle_pinch(thumb_middle_ratio, landmarks, scale, now, result)
        self._update_swipe(landmarks, finger_state, scale, now, result)
        self._update_scroll(landmarks, finger_state, result)

        if finger_state == [0, 1, 0, 0, 0] and thumb_index_ratio > self.PINCH_RELEASE_RATIO:
            result.cursor = (landmarks[8][0], landmarks[8][1])
            result.status = "Move"

        if result.left_click:
            result.status = "Left click"
        elif result.right_click:
            result.status = "Right click"
        elif result.visual_snap_time is not None:
            result.status = "Snap detected"
        elif result.scroll:
            result.status = "Scroll"
        elif result.exit_requested:
            result.status = "Swipe exit"
        return result

    def reset(self) -> None:
        self._index_pinch_started = None
        self._index_click_fired = False
        self._middle_pinch_started = None
        self._middle_pinch_start_point = None
        self._middle_click_fired = False
        self._swipe_history.clear()
        self._last_scroll_y = None

    def _update_index_pinch(self, ratio: float, now: float, result: GestureFrame) -> None:
        if ratio <= self.PINCH_CLOSE_RATIO:
            if self._index_pinch_started is None:
                self._index_pinch_started = now
                self._index_click_fired = False
            if (
                now - self._index_pinch_started >= self.LEFT_CLICK_HOLD_SECONDS
                and not self._index_click_fired
                and now - self._last_click_time >= 0.30
            ):
                result.left_click = True
                self._index_click_fired = True
                self._last_click_time = now
        elif ratio >= self.PINCH_RELEASE_RATIO:
            self._index_pinch_started = None
            self._index_click_fired = False

    def _update_middle_pinch(self, ratio: float, landmarks, scale: float, now: float, result: GestureFrame) -> None:
        middle_tip = (landmarks[12][0], landmarks[12][1])
        if ratio <= self.PINCH_CLOSE_RATIO:
            if self._middle_pinch_started is None:
                self._middle_pinch_started = now
                self._middle_pinch_start_point = middle_tip
                self._middle_click_fired = False
            if (
                now - self._middle_pinch_started >= self.RIGHT_CLICK_HOLD_SECONDS
                and not self._middle_click_fired
                and now - self._last_click_time >= 0.30
            ):
                result.right_click = True
                self._middle_click_fired = True
                self._last_click_time = now
            return

        if ratio < self.PINCH_RELEASE_RATIO or self._middle_pinch_started is None:
            return

        duration = now - self._middle_pinch_started
        start_point = self._middle_pinch_start_point or middle_tip
        travel_ratio = distance(start_point, middle_tip) / scale
        if (
            not self._middle_click_fired
            and duration <= self.SNAP_MAX_SECONDS
            and travel_ratio >= self.SNAP_MIN_TRAVEL_RATIO
        ):
            result.visual_snap_time = now

        self._middle_pinch_started = None
        self._middle_pinch_start_point = None
        self._middle_click_fired = False

    def _update_swipe(self, landmarks, fingers: list[int], scale: float, now: float, result: GestureFrame) -> None:
        if not all(fingers[1:]):
            self._swipe_history.clear()
            return

        center_x, center_y = palm_center(landmarks)
        self._swipe_history.append((now, center_x, center_y))
        while self._swipe_history and now - self._swipe_history[0][0] > self.SWIPE_WINDOW_SECONDS:
            self._swipe_history.popleft()
        if len(self._swipe_history) < 3:
            return

        start_time, start_x, start_y = self._swipe_history[0]
        elapsed = now - start_time
        horizontal_distance = abs(center_x - start_x)
        vertical_distance = abs(center_y - start_y)
        required_distance = max(self.SWIPE_MIN_DISTANCE, scale * self.SWIPE_MIN_PALM_RATIO)
        speed = horizontal_distance / max(elapsed, 1e-6)
        if (
            horizontal_distance >= required_distance
            and speed >= self.SWIPE_MIN_SPEED
            and vertical_distance <= horizontal_distance * 0.65
        ):
            result.exit_requested = True
            self._swipe_history.clear()

    def _update_scroll(self, landmarks, fingers: list[int], result: GestureFrame) -> None:
        if fingers != [0, 1, 1, 0, 0]:
            self._last_scroll_y = None
            return

        _, center_y = palm_center(landmarks)
        if self._last_scroll_y is None:
            self._last_scroll_y = center_y
            return

        delta = center_y - self._last_scroll_y
        self._last_scroll_y = center_y
        if abs(delta) < self.SCROLL_MIN_DELTA:
            return
        result.scroll = max(-8, min(8, round(-delta * 140)))
