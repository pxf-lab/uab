from datetime import datetime
import numpy as np
from io import BytesIO
from pathlib import Path
from PIL import Image
import platform
import re
import OpenEXR
import Imath


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
    suffix = file_path.suffix.lower()

    # Extract metadata from EXR file headers
    if suffix == ".exr" and file_path.exists():
        try:
            exr_file = OpenEXR.InputFile(str(file_path))
            header = exr_file.header()

            # Extract resolution and add resolution tag
            try:
                dw = header["dataWindow"]
                width = dw.max.x - dw.min.x + 1
                height = dw.max.y - dw.min.y + 1
                max_dim = max(width, height)
                if max_dim >= 16384:
                    tags.append("16K")
                elif max_dim >= 8192:
                    tags.append("8K")
                elif max_dim >= 4096:
                    tags.append("4K")
                elif max_dim >= 2048:
                    tags.append("2K")
                elif max_dim >= 1024:
                    tags.append("1K")
            except (KeyError, AttributeError):
                pass

            try:
                channels = header["channels"]
                if channels:
                    # Check pixel type of first channel
                    first_channel = list(channels.values())[0]
                    pixel_type = first_channel.type
                    if pixel_type == Imath.PixelType(Imath.PixelType.HALF):
                        tags.append("Half Float")
                    elif pixel_type == Imath.PixelType(Imath.PixelType.FLOAT):
                        tags.append("32-bit Float")
                    elif pixel_type == Imath.PixelType(Imath.PixelType.UINT):
                        tags.append("UINT")
            except (KeyError, AttributeError, IndexError):
                pass

            exr_file.close()
        except Exception:
            # If EXR reading fails, fall back to filename parsing only
            pass

    # Common resolution patterns from filename (e.g., 1k, 2k, 4k, 8k, 16k)
    if not any(tag.endswith("K") for tag in tags):
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

    # Bit depth indicators from filename (e.g., 16bit, 32bit, half, float)
    # Only add if not already extracted from EXR header
    if not any("bit" in tag or "Float" in tag for tag in tags):
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
