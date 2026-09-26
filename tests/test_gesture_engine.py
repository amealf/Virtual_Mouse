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
        closed = self.snap_hand(0.30)
        released = self.snap_hand(0.43)

        engine._update_snap(closed, 0.2, 2.0, GestureFrame([0, 0, 0, 0, 0]))
        result = GestureFrame([0, 0, 0, 0, 0])
        engine._update_snap(released, 0.2, 2.1, result)

        self.assertEqual(result.visual_snap_time, 2.1)
        self.assertFalse(result.right_click)

    @staticmethod
    def snap_hand(tip_y):
        points = landmarks_with_center(0.5, 0.5)
        points[0] = (0.5, 0.7, 0)
        points[4] = (0.5, 0.3, 0)
        points[12] = (0.5, tip_y, 0)
        return points

    def test_whole_hand_translation_is_not_snap(self):
        engine = GestureEngine()
        points = self.snap_hand(0.30)
        engine._update_snap(points, 0.2, 1.0, GestureFrame([]))
        moved = [(x + 0.2, y + 0.2, z) for x, y, z in points]
        result = GestureFrame([])
        engine._update_snap(moved, 0.2, 1.1, result)
        self.assertIsNone(result.visual_snap_time)

    def test_small_radial_change_is_not_snap(self):
        engine = GestureEngine()
        first = self.snap_hand(0.30)
        second = self.snap_hand(0.335)
        engine._update_snap(first, 0.2, 1.0, GestureFrame([]))
        result = GestureFrame([])
        engine._update_snap(second, 0.2, 1.08, result)
        self.assertIsNone(result.visual_snap_time)

    def test_slow_finger_folding_is_not_snap(self):
        engine = GestureEngine()
        for i in range(11):
            result = GestureFrame([])
            engine._update_snap(self.snap_hand(0.30 + i * 0.013), 0.2, 1 + i * 0.1, result)
            self.assertIsNone(result.visual_snap_time)

    def test_long_preparation_and_no_contact_still_allows_snap(self):
        engine = GestureEngine()
        for i in range(20):
            points = self.snap_hand(0.30)
            points[4] = (0.1, 0.5, 0)
            engine._update_snap(points, 0.2, 1 + i * 0.1, GestureFrame([]))
        result = GestureFrame([])
        engine._update_snap(self.snap_hand(0.43), 0.2, 3.0, result)
        self.assertIsNotNone(result.visual_snap_time)
        engine._update_snap(self.snap_hand(0.30), 0.2, 3.1, GestureFrame([]))
        repeated = GestureFrame([])
        engine._update_snap(self.snap_hand(0.43), 0.2, 3.2, repeated)
        self.assertIsNone(repeated.visual_snap_time)

    def test_open_palm_horizontal_swipe_requests_exit(self) -> None:
        engine = GestureEngine()
        fingers = [1, 1, 1, 1, 1]
        result = GestureFrame(fingers)

        engine._update_swipe(landmarks_with_center(0.20, 0.5), fingers, 0.10, 3.0, GestureFrame(fingers))
        engine._update_swipe(landmarks_with_center(0.33, 0.5), fingers, 0.10, 3.2, GestureFrame(fingers))
        engine._update_swipe(landmarks_with_center(0.50, 0.5), fingers, 0.10, 3.4, result)

        self.assertTrue(result.exit_requested)

    def test_swipe_can_cross_one_missing_frame_when_motion_is_preserved(self):
        engine = GestureEngine()
        fingers = [1, 1, 1, 1, 1]
        engine._update_swipe(landmarks_with_center(0.20, 0.5), fingers, 0.10, 3.0, GestureFrame(fingers))
        engine.reset(preserve_motion=True)
        result = GestureFrame(fingers)
        engine._update_swipe(landmarks_with_center(0.50, 0.5), fingers, 0.10, 3.13, result)
        self.assertTrue(result.exit_requested)

    def test_open_palm_middle_pinch_does_not_right_click(self):
        engine = GestureEngine()
        landmarks = landmarks_with_center(0.5, 0.5)
        open_palm = [1, 1, 1, 1, 1]
        engine._update_middle_pinch(0.2, landmarks, 0.2, 1.0, GestureFrame(open_palm), fingers=open_palm)
        result = GestureFrame(open_palm)
        engine._update_middle_pinch(0.2, landmarks, 0.2, 1.5, result, fingers=open_palm)
        self.assertFalse(result.right_click)


if __name__ == "__main__":
    unittest.main()
