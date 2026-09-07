import math
from typing import Sequence


Landmark = Sequence[float]
Landmarks = Sequence[Landmark]


def distance(a: Landmark, b: Landmark) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def joint_angle(a: Landmark, b: Landmark, c: Landmark) -> float:
    """Return the 2D angle ABC in degrees."""
    ab = (a[0] - b[0], a[1] - b[1])
    cb = (c[0] - b[0], c[1] - b[1])
    denominator = math.hypot(*ab) * math.hypot(*cb)
    if denominator == 0:
        return 0.0
    cosine = max(-1.0, min(1.0, (ab[0] * cb[0] + ab[1] * cb[1]) / denominator))
    return math.degrees(math.acos(cosine))


def palm_size(landmarks: Landmarks) -> float:
    """Return a scale value so thresholds work at different camera distances."""
    wrist_to_middle = distance(landmarks[0], landmarks[9])
    palm_width = distance(landmarks[5], landmarks[17])
    return max(wrist_to_middle, palm_width, 1e-6)


def palm_center(landmarks: Landmarks) -> tuple[float, float]:
    palm_ids = (0, 5, 9, 13, 17)
    return (
        sum(landmarks[index][0] for index in palm_ids) / len(palm_ids),
        sum(landmarks[index][1] for index in palm_ids) / len(palm_ids),
    )


def fingers_up(landmarks: Landmarks) -> list[int]:
    """Detect extended fingers without assuming a left or right hand orientation."""
    if len(landmarks) != 21:
        return [0, 0, 0, 0, 0]

    thumb_extended = (
        joint_angle(landmarks[2], landmarks[3], landmarks[4]) > 145
        and distance(landmarks[4], landmarks[9])
        > distance(landmarks[3], landmarks[9]) * 1.08
    )

    fingers = [int(thumb_extended)]
    for mcp, pip, tip in ((5, 6, 8), (9, 10, 12), (13, 14, 16), (17, 18, 20)):
        extended = (
            joint_angle(landmarks[mcp], landmarks[pip], landmarks[tip]) > 150
            and distance(landmarks[0], landmarks[tip])
            > distance(landmarks[0], landmarks[pip]) * 1.08
        )
        fingers.append(int(extended))
    return fingers
