#!/usr/bin/env python3
"""
A keyboard-first image reviewer for image-scraper output.

Install:
    python -m pip install PySide6

Examples:
    python image_viewer.py
    python image_viewer.py output
    python image_viewer.py output --good-output-directory good --bad-output-directory bad
    python image_viewer.py output --group-by-style
    python image_viewer.py output --style "Flat AI Ultra"
"""

# TODO add zoom-pan with mouse: click-and-drag to pan, scroll to zoom

from __future__ import annotations

import argparse
import json
import random
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeyEvent, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

IMAGE_EXTENSIONS = {
    ".avif",
    ".bmp",
    ".gif",
    ".heic",
    ".jpeg",
    ".jpg",
    ".png",
    ".tif",
    ".tiff",
    ".webp",
}

# only view non-upscaled jpg images
IMAGE_EXTENSIONS = {
    ".jpg",
}

UPSCALED_IMAGE_EXTENSION = ".upscaled.png"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Review images with the keyboard; move rated images into good/ or bad/."
    )
    parser.add_argument(
        "input_directory", nargs="?", default="output",
        help="Directory to scan recursively (default: output).",
    )
    parser.add_argument(
        "--good-output-directory", default="good",
        help="Destination for good images (default: good).",
    )
    parser.add_argument(
        "--bad-output-directory", default="bad",
        help="Destination for bad images (default: bad).",
    )
    parser.add_argument(
        "--group-by-style", action="store_true",
        help="Present styles in sorted order, randomizing images within each style.",
    )
    parser.add_argument(
        "--style",
        help="Only review images whose sibling prompt.json contains this style (case-insensitive).",
    )
    parser.add_argument(
        "--seed", type=int,
        help="Optional random seed, for reproducible ordering.",
    )
    return parser.parse_args()


def nested_style_values(obj: Any):
    """Yield string values of any JSON key named 'style', at any nesting depth."""
    if isinstance(obj, dict):
        for key, value in obj.items():
            if str(key).casefold() == "style" and isinstance(value, str):
                yield value.strip()
            yield from nested_style_values(value)
    elif isinstance(obj, list):
        for value in obj:
            yield from nested_style_values(value)


def read_style(image_path: Path) -> str:
    """Read the style from the prompt.json beside an image; tolerate unknown schemas."""
    prompt_path = image_path.parent / "prompt.json"
    try:
        with prompt_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        values = [value for value in nested_style_values(data) if value]
        # Usually there is one style. If there are multiple nested "style" fields,
        # use the first one encountered in JSON insertion order.
        return values[0] if values else "(no style)"
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return "(no style)"


@dataclass
class ImageItem:
    path: Path
    relative_path: Path
    style: str


def is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def collect_images(
    input_dir: Path,
    good_dir: Path,
    bad_dir: Path,
    style_filter: str | None,
    group_by_style: bool,
    seed: int | None,
) -> list[ImageItem]:
    if not input_dir.is_dir():
        raise SystemExit(f"Input directory does not exist or is not a directory: {input_dir}")

    input_resolved = input_dir.resolve()
    excluded_roots = [p.resolve() for p in (good_dir, bad_dir)]

    items: list[ImageItem] = []
    for path in input_dir.rglob("*"):
        if not path.is_file() or path.suffix.casefold() not in IMAGE_EXTENSIONS:
            continue
        if str(path).endswith(UPSCALED_IMAGE_EXTENSION):
            continue
        resolved = path.resolve()
        # Avoid accidentally re-ingesting destinations if they are inside input_dir.
        if any(is_relative_to(resolved, dest) for dest in excluded_roots):
            continue
        try:
            relative = path.relative_to(input_dir)
        except ValueError:
            relative = resolved.relative_to(input_resolved)

        style = read_style(path)
        if style_filter and style.casefold() != style_filter.casefold():
            continue
        items.append(ImageItem(path=path, relative_path=relative, style=style))

    rng = random.Random(seed)
    if group_by_style:
        groups: dict[str, list[ImageItem]] = {}
        for item in items:
            groups.setdefault(item.style, []).append(item)
        ordered: list[ImageItem] = []
        for style in sorted(groups, key=str.casefold):
            group = groups[style]
            rng.shuffle(group)
            ordered.extend(group)
        return ordered

    rng.shuffle(items)
    return items


class ImageViewer(QMainWindow):
    def __init__(
        self,
        items: list[ImageItem],
        input_dir: Path,
        good_dir: Path,
        bad_dir: Path,
        group_by_style: bool,
        style_filter: str | None,
    ):
        super().__init__()
        self.items = items
        self.input_dir = input_dir
        self.good_dir = good_dir
        self.bad_dir = bad_dir
        self.group_by_style = group_by_style
        self.style_filter = style_filter
        self.index = 0
        self.current_pixmap: QPixmap | None = None
        self.history: list[tuple[Path, Path]] = []  # (destination, original source)

        self.setWindowTitle("Image Reviewer")
        self.resize(1200, 850)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self.image_label = QLabel("No images to review")
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setMinimumSize(320, 240)
        # self.image_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self.image_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.image_label.setStyleSheet("QLabel { background: #171717; color: #dddddd; }")

        self.info_label = QLabel()
        self.info_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.info_label.setWordWrap(True)

        self.previous_button = QPushButton("← Previous")
        self.good_button = QPushButton("👍 Good  (↑ / E)")
        self.bad_button = QPushButton("👎 Bad  (↓ / D)")
        self.skip_button = QPushButton("Skip  (→ / F)")
        self.undo_button = QPushButton("Undo rating  (U)")
        self.open_button = QPushButton("Open directory…")

        self.previous_button.clicked.connect(self.previous_image)
        self.good_button.clicked.connect(lambda: self.rate_current("good"))
        self.bad_button.clicked.connect(lambda: self.rate_current("bad"))
        self.skip_button.clicked.connect(self.next_image)
        self.undo_button.clicked.connect(self.undo_rating)
        self.open_button.clicked.connect(self.choose_directory)

        controls = QHBoxLayout()
        for widget in (
            self.previous_button, self.good_button, self.bad_button,
            self.skip_button, self.undo_button, self.open_button,
        ):
            controls.addWidget(widget)

        layout = QVBoxLayout()
        layout.addWidget(self.image_label, 1)
        layout.addWidget(self.info_label)
        layout.addLayout(controls)

        central = QWidget()
        central.setLayout(layout)
        self.setCentralWidget(central)

        self.statusBar().showMessage(
            "↑/E = good   ↓/D = bad   →/Space = skip   ← = previous   U = undo   Esc = quit"
        )
        self.show_current()

    def show_current(self):
        if not self.items:
            self.current_pixmap = None
            self.image_label.setPixmap(QPixmap())
            self.image_label.setText("No matching images left to review.")
            self.info_label.setText(
                f"Reviewed/matched: 0 images\nInput: {self.input_dir}"
            )
            self.setWindowTitle("Image Reviewer — finished")
            self.good_button.setEnabled(False)
            self.bad_button.setEnabled(False)
            self.skip_button.setEnabled(False)
            self.previous_button.setEnabled(False)
            return

        self.index = max(0, min(self.index, len(self.items) - 1))
        item = self.items[self.index]
        pixmap = QPixmap(str(item.path))
        if pixmap.isNull():
            self.current_pixmap = None
            self.image_label.setPixmap(QPixmap())
            self.image_label.setText(f"Could not load image:\n{item.path}")
        else:
            self.current_pixmap = pixmap
            self.update_scaled_image()

        self.info_label.setText(
            f"{self.index + 1} / {len(self.items)}    "
            f"Style: {item.style}\n{item.path}"
        )
        self.setWindowTitle(f"Image Reviewer — {self.index + 1}/{len(self.items)} — {item.path.name}")
        self.previous_button.setEnabled(self.index > 0)
        self.good_button.setEnabled(True)
        self.bad_button.setEnabled(True)
        self.skip_button.setEnabled(True)

    def update_scaled_image(self):
        if self.current_pixmap is None:
            return

        available = self.image_label.contentsRect().size()
        if available.width() <= 0 or available.height() <= 0:
            return

        scaled = self.current_pixmap.scaled(
            available,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.image_label.setPixmap(scaled)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.update_scaled_image()

    def next_image(self):
        if self.items and self.index < len(self.items) - 1:
            self.index += 1
            self.show_current()
        elif self.items:
            self.statusBar().showMessage("End of queue — rate this image or press ← to go back.", 3000)

    def previous_image(self):
        if self.items and self.index > 0:
            self.index -= 1
            self.show_current()

    def rate_current(self, rating: str):
        if not self.items:
            return
        item = self.items[self.index]
        destination_root = self.good_dir if rating == "good" else self.bad_dir
        destination = destination_root / item.relative_path
        source = item.path

        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists():
                QMessageBox.warning(
                    self, "Destination already exists",
                    f"Refusing to overwrite an existing file:\n{destination}",
                )
                return
            shutil.move(str(source), str(destination))
        except OSError as exc:
            QMessageBox.critical(self, "Could not move image", str(exc))
            return

        self.history.append((destination, source))
        self.items.pop(self.index)
        if self.index >= len(self.items):
            self.index = max(0, len(self.items) - 1)
        self.statusBar().showMessage(f"Marked {rating}: {item.relative_path}", 2500)
        self.show_current()

    def undo_rating(self):
        if not self.history:
            self.statusBar().showMessage("Nothing to undo.", 2000)
            return
        destination, source = self.history[-1]
        if not destination.exists():
            QMessageBox.warning(self, "Cannot undo", f"Rated file is missing:\n{destination}")
            return
        if source.exists():
            QMessageBox.warning(
                self, "Cannot undo",
                f"The original path is already occupied; refusing to overwrite:\n{source}",
            )
            return
        try:
            source.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(destination), str(source))
        except OSError as exc:
            QMessageBox.critical(self, "Could not undo rating", str(exc))
            return

        self.history.pop()
        try:
            relative = source.relative_to(self.input_dir)
        except ValueError:
            relative = Path(source.name)
        restored = ImageItem(source, relative, read_style(source))
        self.items.insert(min(self.index, len(self.items)), restored)
        self.show_current()
        self.statusBar().showMessage("Last rating undone.", 2000)

    def choose_directory(self):
        chosen = QFileDialog.getExistingDirectory(self, "Choose image directory", str(self.input_dir))
        if chosen:
            QMessageBox.information(
                self, "Change input directory",
                "To keep the queue and relative paths consistent, restart the app with:\n\n"
                f'python {Path(sys.argv[0]).name} "{chosen}"',
            )

    def keyPressEvent(self, event: QKeyEvent):
        key = event.key()
        if key in (Qt.Key.Key_Up, Qt.Key.Key_E):
            self.rate_current("good")
        elif key in (Qt.Key.Key_Down, Qt.Key.Key_D):
            self.rate_current("bad")
        elif key in (Qt.Key.Key_Right, Qt.Key.Key_F):
            self.next_image()
        elif key in (Qt.Key.Key_Left, Qt.Key.Key_S):
            # self.previous_image()
            self.undo_rating()
        # elif key == Qt.Key.Key_U:
        #     self.undo_rating()
        elif key == Qt.Key.Key_Escape or key == Qt.Key.Key_Q:
            self.close()
        elif key in (Qt.Key.Key_Plus, Qt.Key.Key_Equal):
            self.zoom(1.15)
        elif key in (Qt.Key.Key_Minus, Qt.Key.Key_Underscore):
            self.zoom(1 / 1.15)
        elif key == Qt.Key.Key_0:
            self.update_scaled_image()
        else:
            super().keyPressEvent(event)

    def zoom(self, factor: float):
        # Zoom is implemented by scaling the source pixmap to a virtual size,
        # while retaining the fit-to-window behavior for the normal workflow.
        if self.current_pixmap is None:
            return
        current = self.image_label.pixmap()
        if current is None or current.isNull():
            return
        size = current.size() * factor
        self.image_label.setPixmap(
            self.current_pixmap.scaled(
                size,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )


def main() -> int:
    args = parse_args()
    input_dir = Path(args.input_directory).expanduser()
    good_dir = Path(args.good_output_directory).expanduser()
    bad_dir = Path(args.bad_output_directory).expanduser()

    if good_dir.resolve() == bad_dir.resolve():
        print("Error: good and bad output directories must be different.", file=sys.stderr)
        return 2
    if input_dir.resolve() in (good_dir.resolve(), bad_dir.resolve()):
        print("Error: output directories must not be the same as the input directory.", file=sys.stderr)
        return 2

    try:
        items = collect_images(
            input_dir, good_dir, bad_dir,
            args.style, args.group_by_style, args.seed,
        )
    except SystemExit as exc:
        print(exc, file=sys.stderr)
        return 2

    if not items:
        print(f"No matching images found in {input_dir}", file=sys.stderr)

    app = QApplication(sys.argv[:1])
    app.setApplicationName("Image Reviewer")
    window = ImageViewer(
        items, input_dir, good_dir, bad_dir,
        args.group_by_style, args.style,
    )

    # window.show()
    window.showFullScreen()

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
