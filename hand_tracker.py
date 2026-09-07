import cv2
import mediapipe as mp
from dataclasses import dataclass
from pathlib import Path

from mediapipe.tasks import python
from mediapipe.tasks.python import vision


@dataclass(frozen=True)
class HandObservation:
    landmarks: list[tuple[float, float, float]]
    handedness: str
    confidence: float

    def pixel_landmarks(self, width: int, height: int) -> list[tuple[int, int, int]]:
        return [
            (index, int(point[0] * width), int(point[1] * height))
            for index, point in enumerate(self.landmarks)
        ]

class HandTracker:
    CONNECTIONS = (
        (0, 1), (1, 2), (2, 3), (3, 4),
        (0, 5), (5, 6), (6, 7), (7, 8),
        (0, 9), (9, 10), (10, 11), (11, 12),
        (0, 13), (13, 14), (14, 15), (15, 16),
        (0, 17), (17, 18), (18, 19), (19, 20),
        (5, 9), (9, 13), (13, 17),
    )

    def __init__(
        self,
        model_path: Path,
        max_hands: int = 1,
        detection_confidence: float = 0.75,
        tracking_confidence: float = 0.75,
    ):
        base_options = python.BaseOptions(model_asset_path=str(model_path))
        options = vision.HandLandmarkerOptions(
            base_options=base_options,
            num_hands=max_hands,
            min_hand_detection_confidence=detection_confidence,
            min_hand_presence_confidence=tracking_confidence,
            min_tracking_confidence=tracking_confidence,
            running_mode=vision.RunningMode.VIDEO,
        )
        self.landmarker = vision.HandLandmarker.create_from_options(options)
        self._last_timestamp_ms = -1

    def process(self, image, timestamp_ms: int, draw: bool = True) -> HandObservation | None:
        timestamp_ms = max(timestamp_ms, self._last_timestamp_ms + 1)
        self._last_timestamp_ms = timestamp_ms
        rgb_image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        media_pipe_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb_image)
        results = self.landmarker.detect_for_video(media_pipe_image, timestamp_ms)
        if not results.hand_landmarks:
            return None

        landmarks = [(point.x, point.y, point.z) for point in results.hand_landmarks[0]]
        handedness = "Unknown"
        confidence = 0.0
        if results.handedness and results.handedness[0]:
            category = results.handedness[0][0]
            handedness = category.category_name or "Unknown"
            confidence = float(category.score or 0.0)

        observation = HandObservation(landmarks, handedness, confidence)
        if draw:
            self._draw(image, observation)
        return observation

    def _draw(self, image, observation: HandObservation) -> None:
        height, width, _ = image.shape
        points = observation.pixel_landmarks(width, height)
        for _, x, y in points:
            cv2.circle(image, (x, y), 4, (255, 0, 255), cv2.FILLED)
        for start, end in self.CONNECTIONS:
            cv2.line(
                image,
                (points[start][1], points[start][2]),
                (points[end][1], points[end][2]),
                (255, 0, 255),
                2,
            )

    def close(self) -> None:
        self.landmarker.close()
