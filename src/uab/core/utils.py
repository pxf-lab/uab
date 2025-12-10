from datetime import datetime
import cv2
import numpy as np
from io import BytesIO
from pathlib import Path
from PIL import Image
import platform


def is_macos() -> bool:
    """Check if the current operating system is macOS.

    Returns:
        bool: True if running on macOS, False otherwise.
    """
    return platform.system() == "Darwin"


def get_modifier_key() -> str:
    """Get the appropriate modifier key for keyboard shortcuts based on the OS.

    Returns:
        str: "Cmd" for macOS, "Ctrl" for Linux and Windows.
    """
    return "Cmd" if is_macos() else "Ctrl"


def hdri_to_pixmap_format(
    input_path: str | Path,
    gamma: float = 2.4,
    intensity: float = 0.5,
    light_adapt: float = 0.0,
    color_adapt: float = 0.0,
    as_image: bool = True,
    as_bytes: bool = False,
) -> Image.Image | np.ndarray | bytes:
    """
    DEPRECATED

    This function is deprecated. Use `HDRI.render_from_exr` or `HDRI.render_from_hdr`
    """

    # Temporary backward compatibility
    from uab.core.assets import HDRI

    input_path = Path(input_path)
    ext = input_path.suffix.lower()

    if ext == ".exr":
        return HDRI.render_from_exr(
            input_path=input_path,
            gamma=gamma,
            intensity=intensity,
            light_adapt=light_adapt,
            color_adapt=color_adapt,
            as_image=as_image,
            as_bytes=as_bytes,
        )
    elif ext == ".hdr":
        return HDRI.render_from_hdr(
            input_path=input_path,
            gamma=gamma,
            intensity=intensity,
            light_adapt=light_adapt,
            color_adapt=color_adapt,
            as_image=as_image,
            as_bytes=as_bytes,
        )
    else:
        raise ValueError(f"Unsupported file extension: {ext}")


def file_name_to_display_name(file_path: Path) -> str:
    """Convert a file name to a display name.

    Args:
        file_name (str): The file name to convert.

    Returns:
        str: The display name.
    """
    name = file_path.stem
    name = name.replace("_", " ").replace("-", " ").replace(".", " ")
    return name.title()


def tags_from_file_name(file_path: Path) -> list[str]:
    """Extract tags from a file name.

    Args:
        file_path (Path): The file path to extract tags from.

    Returns:
        list[str]: The tags.
    """
    # TODO: consider what data can be extracted from file name and/or file metadata
    pass


def is_valid_date(date: str) -> str:
    """Check if a date is valid.

    Args:
        date (str): The date to check.

    Returns:
        bool: True if the date is valid, False otherwise.
    """
    try:
        datetime.strptime(date, "%Y-%m-%d")
        return True
    except ValueError:
        return False
