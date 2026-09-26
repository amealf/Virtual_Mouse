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
    SNAP_MAX_SECONDS = 0.22
    SNAP_MIN_TRAVEL_RATIO = 0.32
    SNAP_MIN_SPEED = 3.0
    SNAP_MIN_RADIAL_DROP = 0.24
    SNAP_MIN_START_RADIUS = 0.58
    SNAP_MAX_START_RADIUS = 1.80
    SNAP_MAX_END_RADIUS = 0.55
    SNAP_MIN_NEAR_PREP_FRAMES = 3
    SNAP_COOLDOWN_SECONDS = 0.55
    SWIPE_WINDOW_SECONDS = 0.55
    SWIPE_MIN_DISTANCE = 0.22
    SWIPE_MIN_PALM_RATIO = 0.60
    SWIPE_MIN_SPEED = 0.65
    SWIPE_MAX_VERTICAL_RATIO = 0.80
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
        self._snap_history = deque()
        self._last_snap_time = -10.0

    def update(self, landmarks, now: float) -> GestureFrame:
        finger_state = fingers_up(landmarks)
        result = GestureFrame(fingers=finger_state)
        scale = palm_size(landmarks)
        thumb_index_ratio = distance(landmarks[4], landmarks[8]) / scale
        thumb_middle_ratio = distance(landmarks[4], landmarks[12]) / scale

        self._update_index_pinch(thumb_index_ratio, now, result, fingers=finger_state)
        self._update_middle_pinch(thumb_middle_ratio, landmarks, scale, now, result, fingers=finger_state)
        self._update_snap(landmarks, scale, now, result, fingers=finger_state)
        self._update_swipe(landmarks, finger_state, scale, now, result)
        self._update_scroll(landmarks, finger_state, result)

        if finger_state == [0, 1, 0, 0, 0] and thumb_index_ratio > self.PINCH_RELEASE_RATIO:
            result.cursor = (landmarks[8][0], landmarks[8][1])
            result.status = "Move"

        if result.visual_snap_time is not None:
            result.left_click = result.right_click = False
            result.cursor = None
            result.scroll = 0
            result.status = "Snap detected"
        elif result.left_click:
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

    def reset(self, preserve_motion: bool = False) -> None:
        """Reset transient gesture state.

        ``preserve_motion`` is useful when a video frame briefly loses the
        hand during a fast movement.  The time windows in the motion
        detectors expire stale entries on the next observed frame, so this
        keeps a short swipe or snap trajectory without keeping click holds.
        """
        self._index_pinch_started = None
        self._index_click_fired = False
        self._middle_pinch_started = None
        self._middle_pinch_start_point = None
        self._middle_click_fired = False
        if not preserve_motion:
            self._swipe_history.clear()
        self._last_scroll_y = None
        if not preserve_motion:
            self._snap_history.clear()

    def _update_index_pinch(
        self,
        ratio: float,
        now: float,
        result: GestureFrame,
        fingers: list[int] | None = None,
    ) -> None:
        # A standard left-click pinch keeps the other three fingers folded.
        # This gate prevents an open hand or a transitioning snap from
        # producing a desktop click when MediaPipe briefly mislabels a tip.
        click_shape = fingers is None or not any(fingers[2:])
        if ratio <= self.PINCH_CLOSE_RATIO:
            if self._index_pinch_started is None:
                self._index_pinch_started = now
                self._index_click_fired = False
            if (
                now - self._index_pinch_started >= self.LEFT_CLICK_HOLD_SECONDS
                and not self._index_click_fired
                and now - self._last_click_time >= 0.30
                and click_shape
            ):
                result.left_click = True
                self._index_click_fired = True
                self._last_click_time = now
        elif ratio >= self.PINCH_RELEASE_RATIO:
            self._index_pinch_started = None
            self._index_click_fired = False

    def _update_middle_pinch(
        self,
        ratio: float,
        landmarks,
        scale: float,
        now: float,
        result: GestureFrame,
        fingers: list[int] | None = None,
    ) -> None:
        middle_tip = (landmarks[12][0], landmarks[12][1])
        # A right-click pinch keeps index, ring, and pinky folded.  This also
        # blocks the long open-palm/fist transitions present in recorded
        # swipe clips from firing a mouse action.
        click_shape = fingers is None or not any((fingers[1], fingers[3], fingers[4]))
        if ratio <= self.PINCH_CLOSE_RATIO:
            if self._middle_pinch_started is None:
                self._middle_pinch_started = now
                self._middle_pinch_start_point = middle_tip
                self._middle_click_fired = False
            if (
                now - self._middle_pinch_started >= self.RIGHT_CLICK_HOLD_SECONDS
                and not self._middle_click_fired
                and now - self._last_click_time >= 0.30
                and click_shape
            ):
                result.right_click = True
                self._middle_click_fired = True
                self._last_click_time = now
            return

        if ratio < self.PINCH_RELEASE_RATIO or self._middle_pinch_started is None:
            return

        self._middle_pinch_started = None
        self._middle_pinch_start_point = None
        self._middle_click_fired = False

    def _update_snap(
        self,
        landmarks,
        scale: float,
        now: float,
        result: GestureFrame,
        fingers: list[int] | None = None,
    ) -> None:
        # Express the fingertip in a palm-attached frame: whole-hand translation
        # and in-plane rotation should not count as finger movement.
        origin = landmarks[9]
        axis_x = origin[0] - landmarks[0][0]
        axis_y = origin[1] - landmarks[0][1]
        length = (axis_x * axis_x + axis_y * axis_y) ** 0.5
        if length < 1e-6:
            self._snap_history.clear()
            return
        ux, uy = axis_x / length, axis_y / length
        dx = (landmarks[12][0] - origin[0]) / scale
        dy = (landmarks[12][1] - origin[1]) / scale
        point = (dx * uy - dy * ux, dx * ux + dy * uy)
        radius = distance(point, (0, 0))
        near_thumb = distance(landmarks[4], landmarks[12]) / scale < 0.65
        while self._snap_history and now - self._snap_history[0][0] > self.SNAP_MAX_SECONDS:
            self._snap_history.popleft()
        if now - self._last_snap_time < self.SNAP_COOLDOWN_SECONDS:
            # Do not allow a motion that happened during the cooldown to be
            # reported late after the cooldown expires.
            self._snap_history.clear()
            self._snap_history.append((now, point, radius, near_thumb))
            return
        if fingers is None or (len(fingers) >= 3 and fingers[0] == 1 and fingers[2] == 0):
            history = list(self._snap_history)
            # A real snap in the supplied recordings has a loaded middle
            # finger near the thumb for a short preparation run immediately
            # before release.  This rejects open-palm waves and broad hand
            # rotations that happen to shorten the radius.
            if fingers is not None:
                near_prep_frames = 0
                for _, _, _, was_near_thumb in reversed(history):
                    if not was_near_thumb:
                        break
                    near_prep_frames += 1
                if near_prep_frames < self.SNAP_MIN_NEAR_PREP_FRAMES:
                    self._snap_history.append((now, point, radius, near_thumb))
                    return
            for timestamp, old_point, old_radius, was_near_thumb in history:
                elapsed = now - timestamp
                travel = distance(point, old_point)
                # A fast inward middle-finger stroke, optionally beginning near
                # the thumb. No exact contact frame or microphone is required.
                if (
                    elapsed >= 0.015
                    and travel >= self.SNAP_MIN_TRAVEL_RATIO
                    and travel / elapsed >= self.SNAP_MIN_SPEED
                    and old_radius >= self.SNAP_MIN_START_RADIUS
                    and old_radius <= self.SNAP_MAX_START_RADIUS
                    and old_radius - radius >= self.SNAP_MIN_RADIAL_DROP
                    and radius <= self.SNAP_MAX_END_RADIUS
                    and (was_near_thumb or old_radius >= 0.7)
                ):
                    result.visual_snap_time = now
                    self._last_snap_time = now
                    self._snap_history.clear()
                    break
        self._snap_history.append((now, point, radius, near_thumb))

    def _update_swipe(self, landmarks, fingers: list[int], scale: float, now: float, result: GestureFrame) -> None:
        if not all(fingers[1:]):
            self._swipe_history.clear()
            return

        center_x, center_y = palm_center(landmarks)
        self._swipe_history.append((now, center_x, center_y))
        while self._swipe_history and now - self._swipe_history[0][0] > self.SWIPE_WINDOW_SECONDS:
            self._swipe_history.popleft()
        if len(self._swipe_history) < 2:
            return

        # A fast hand can disappear for a few frames because of motion blur.
        # Evaluate each recent anchor, especially the latest one, instead of
        # requiring the oldest sample to span the complete movement.
        required_distance = max(self.SWIPE_MIN_DISTANCE, scale * self.SWIPE_MIN_PALM_RATIO)
        for start_time, start_x, start_y in reversed(self._swipe_history):
            elapsed = now - start_time
            if elapsed <= 1e-6:
                continue
            horizontal_distance = abs(center_x - start_x)
            vertical_distance = abs(center_y - start_y)
            speed = horizontal_distance / elapsed
            if (
                horizontal_distance >= required_distance
                and speed >= self.SWIPE_MIN_SPEED
                and vertical_distance <= horizontal_distance * self.SWIPE_MAX_VERTICAL_RATIO
            ):
                result.exit_requested = True
                self._swipe_history.clear()
                break

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
