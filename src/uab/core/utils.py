from datetime import datetime
import cv2
import numpy as np
from io import BytesIO
from pathlib import Path
from PIL import Image
import platform
import re


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

    tags = []
    file_name = file_path.stem.lower()

    # Common resolution patterns (e.g., 1k, 2k, 4k, 8k, 16k)
    resolution_pattern = r'\b(\d+)k\b'
    resolution_match = re.search(resolution_pattern, file_name)
    if resolution_match:
        tags.append(f"{resolution_match.group(1)}K")

    # Common time of day keywords
    time_keywords = {
        'day': 'Day',
        'night': 'Night',
        'dawn': 'Dawn',
        'dusk': 'Dusk',
        'sunset': 'Sunset',
        'sunrise': 'Sunrise',
        'noon': 'Noon',
        'midday': 'Midday',
        'morning': 'Morning',
        'evening': 'Evening',
        'afternoon': 'Afternoon',
    }
    for keyword, tag in time_keywords.items():
        if keyword in file_name:
            tags.append(tag)
            break  # Only add one time tag

    # Common environment/weather keywords
    environment_keywords = {
        'outdoor': 'Outdoor',
        'indoor': 'Indoor',
        'studio': 'Studio',
        'sunny': 'Sunny',
        'cloudy': 'Cloudy',
        'overcast': 'Overcast',
        'foggy': 'Foggy',
        'rainy': 'Rainy',
        'stormy': 'Stormy',
        'clear': 'Clear',
        'urban': 'Urban',
        'nature': 'Nature',
        'forest': 'Forest',
        'beach': 'Beach',
        'desert': 'Desert',
        'mountain': 'Mountain',
        'city': 'City',
        'canyon': 'Canyon',
        'lake': 'Lake',
        'ocean': 'Ocean',
    }
    for keyword, tag in environment_keywords.items():
        if keyword in file_name:
            tags.append(tag)

    # Projection type indicators
    if 'latlong' in file_name or 'lat_long' in file_name:
        tags.append('LatLong')
    elif 'equirectangular' in file_name or 'equi' in file_name:
        tags.append('Equirectangular')
    elif 'cubemap' in file_name or 'cube' in file_name:
        tags.append('Cubemap')

    # Bit depth indicators (e.g., 16bit, 32bit, half, float)
    bit_depth_pattern = r'\b(\d+)bit\b'
    bit_depth_match = re.search(bit_depth_pattern, file_name)
    if bit_depth_match:
        tags.append(f"{bit_depth_match.group(1)}-bit")

    return tags


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
