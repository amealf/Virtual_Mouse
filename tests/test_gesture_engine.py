import unittest

from gesture_engine import GestureEngine, GestureFrame


def landmarks_with_center(x: float, y: float) -> list[tuple[float, float, float]]:
    landmarks = [(x, y, 0.0) for _ in range(21)]
    return landmarks


class GestureEngineTests(unittest.TestCase):
    def test_middle_pinch_hold_fires_one_right_click(self) -> None:
        engine = GestureEngine()
        landmarks = landmarks_with_center(0.5, 0.5)

        first = GestureFrame([0, 0, 0, 0, 0])
        engine._update_middle_pinch(0.2, landmarks, 0.2, 1.0, first)
        held = GestureFrame([0, 0, 0, 0, 0])
        engine._update_middle_pinch(0.2, landmarks, 0.2, 1.41, held)
        repeated = GestureFrame([0, 0, 0, 0, 0])
        engine._update_middle_pinch(0.2, landmarks, 0.2, 1.50, repeated)

        self.assertFalse(first.right_click)
        self.assertTrue(held.right_click)
        self.assertFalse(repeated.right_click)

    def test_fast_middle_pinch_release_creates_visual_snap(self) -> None:
        engine = GestureEngine()
        closed = landmarks_with_center(0.5, 0.5)
        released = landmarks_with_center(0.5, 0.5)
        released[12] = (0.60, 0.5, 0.0)

        engine._update_middle_pinch(0.2, closed, 0.2, 2.0, GestureFrame([0, 0, 0, 0, 0]))
        result = GestureFrame([0, 0, 0, 0, 0])
        engine._update_middle_pinch(0.6, released, 0.2, 2.2, result)

        self.assertEqual(result.visual_snap_time, 2.2)
        self.assertFalse(result.right_click)

    def test_open_palm_horizontal_swipe_requests_exit(self) -> None:
        engine = GestureEngine()
        fingers = [1, 1, 1, 1, 1]
        result = GestureFrame(fingers)

        engine._update_swipe(landmarks_with_center(0.20, 0.5), fingers, 0.10, 3.0, GestureFrame(fingers))
        engine._update_swipe(landmarks_with_center(0.33, 0.5), fingers, 0.10, 3.2, GestureFrame(fingers))
        engine._update_swipe(landmarks_with_center(0.50, 0.5), fingers, 0.10, 3.4, result)

        self.assertTrue(result.exit_requested)


if __name__ == "__main__":
    unittest.main()
