from pathlib import Path
from typing import List, Tuple

import cv2
import numpy as np
import pandas as pd
from nptyping import NDArray
from skimage.measure import EllipseModel

XCenter = float
YCenter = float
A = float
B = float
Theta = float
EllipseParmas = Tuple[XCenter, YCenter, A, B, Theta]

Area = float

Color = Tuple[int, int, int]
CS = int

Model = str
Bodyparts = str
Coordinate = str
DLCKey = Tuple[Model, Bodyparts, Coordinate]


def fit_ellipse(points: NDArray[2, float]) -> EllipseParmas:
    points = points[~np.isnan(points).any(axis=1), :]
    m = EllipseModel()
    m.estimate(points)
    return tuple(m.params)


def calc_ellipse_area(params: EllipseParmas) -> float:
    _, _, a, b, _ = params
    return np.pi * a * b


def draw_ellipse(frame: NDArray, params: EllipseParmas, color: Color,
                 thickness: int):
    xc, yc, a, b, theta = params
    angle = 180. * theta / np.pi
    cv2.ellipse(frame, ((xc, yc), (2 * a, 2 * b), angle),
                color,
                thickness=thickness)


def is_coordinate(key: DLCKey):
    return "x" in key or "y" in key


def extract_key_of_bodyparts(data: pd.DataFrame,
                             bodyparts: Bodyparts) -> List[DLCKey]:
    coords = list(filter(is_coordinate, data.keys()))
    return list(filter(lambda key: bodyparts in key[1], coords))


def reshape2fittable(data: pd.DataFrame) -> NDArray[3, float]:
    nrow, ncol = data.shape
    return np.array(data).reshape(nrow, -1, 2)


def as_output_filename(video_path: Path):
    parent = video_path.parents[1]
    filepath_without_extension = parent.joinpath("area").joinpath(
        video_path.stem)
    return str(filepath_without_extension) + ".csv"


def is_marked(frame: NDArray, position: Tuple[int, int],
              color_range: Tuple[Color, Color]) -> int:
    x, y = position
    color = frame[x, y, :]
    lcolor, ucolor = color_range
    for comp in zip(color, lcolor, ucolor):
        c, l, u = comp
        if not (l <= c and c <= u):
            return 0
    return 1


def to_video_path(h5path: Path) -> str:
    stem = h5path.stem.split("DLC")[0]
    return str(h5path.parents[1].joinpath("videos").joinpath(stem)) + ".MP4"


if __name__ == '__main__':
    from argparse import ArgumentParser

    parser = ArgumentParser()
    parser.add_argument("-f", "--files", nargs="+", required=True)
    parser.add_argument("-o", "--output", default=False)
    parser.add_argument("-s", "--show", default=True)

    args = parser.parse_args()

    create_video = args.output
    show_video = args.show
    h5s = args.files

    for h5 in h5s:
        video = to_video_path(Path(h5))
        print(f"start processing {video}")

        tracked_data = pd.read_hdf(h5)
        cap = cv2.VideoCapture(str(video))
        nframe = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

        if create_video:
            fourcc = cv2.VideoWriter_fourcc(*"MP4v")
            width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            fps = cap.get(cv2.CAP_PROP_FPS)
            writer = cv2.VideoWriter(
                f"./data/videos/{Path(video).stem}-ellipse.MP4", fourcc, fps,
                (width, height))

        pupil_keys = extract_key_of_bodyparts(tracked_data, "pupil")

        pupil_data = reshape2fittable(tracked_data[pupil_keys])

        results: List[Tuple[Area, Area, XCenter, YCenter, CS]] = []
        for i in range(nframe):
            if i % 5000 == 0:
                print(f"Processing {i}-th frame")

            ret, frame = cap.read()

            pupil_params = fit_ellipse(pupil_data[i])

            pupil_area = calc_ellipse_area(pupil_params)
            pupil_x, pupil_y, _, _, _ = pupil_params
            cs_on = is_marked(frame, (10, 10), ((0, 0, 235), (20, 20, 255)))

            results.append((pupil_area, pupil_x, pupil_y, cs_on))

            if show_video:
                draw_ellipse(frame, pupil_params, (0, 255, 255), 1)
                # draw_ellipse(frame, eyelid_params, (0, 255, 0), 1)

            if create_video:
                writer.write(frame)

            if show_video:
                cv2.imshow("video", frame)
                if cv2.waitKey(1) % 0xFF == ord("q"):
                    cv2.destroyAllWindows()
                    cap.release()
                    break

        if create_video:
            writer.release()
        output = pd.DataFrame(
            results, columns=["pupil-area", "pupil-x", "pupil-y", "cs"])
        output_path = as_output_filename(Path(video))
        output.to_csv(output_path, index=False)