import cv2
import numpy as np
from io import BytesIO
from pathlib import Path
from PIL import Image
import OpenEXR
import Imath
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
    """Load an HDR/EXR image, tone-map it, and return a preview representation.

    Supports `.hdr` and `.exr` formats. Applies Reinhard tone mapping for
    a displayable preview image.

    Args:
        input_path (str | Path): Path to the HDR or EXR image.
        gamma (float, optional): Gamma correction factor. Defaults to 2.4.
        intensity (float, optional): Tone-mapping intensity. Defaults to 0.5.
        light_adapt (float, optional): Light adaptation factor. Defaults to 0.0.
        color_adapt (float, optional): Color adaptation factor. Defaults to 0.0.
        as_image (bool, optional): If True, return a Pillow Image.
        as_bytes (bool, optional): If True, return JPEG bytes.

    Returns:
        Union[Image.Image, np.ndarray, bytes]:
            - Pillow Image if `as_image` is True.
            - NumPy array (H×W×3, uint8) if both flags are False.
            - JPEG byte stream if `as_bytes` is True.

    Raises:
        FileNotFoundError: If the HDR/EXR file cannot be loaded or is invalid.
    """

    input_path = Path(input_path)
    ext = input_path.suffix.lower()

    if ext == ".exr":
        hdr = _load_exr(input_path)
    elif ext == ".hdr":
        hdr = _load_hdr(input_path)
    else:
        raise ValueError(f"Unsupported file extension: {ext}")

    # Create tone mapping operator
    tonemap = cv2.createTonemapReinhard(
        gamma=gamma,
        intensity=intensity,
        light_adapt=light_adapt,
        color_adapt=color_adapt,
    )

    # Apply tone mapping
    ldr = tonemap.process(hdr)

    # Convert to 8-bit RGB
    ldr_8bit = np.clip(ldr * 255, 0, 255).astype(np.uint8)
    ldr_rgb = cv2.cvtColor(ldr_8bit, cv2.COLOR_BGR2RGB)

    if as_bytes:
        img = Image.fromarray(ldr_rgb)
        buffer = BytesIO()
        img.save(buffer, format="JPEG", quality=85)
        return buffer.getvalue()

    if as_image:
        return Image.fromarray(ldr_rgb)

    return ldr_rgb


def _load_hdr(input_path: Path) -> np.ndarray:
    """Load an HDR file and return as BGR float32 numpy array.

    Args:
        input_path (Path): Path to the HDR file.

    Returns:
        np.ndarray: HDR image as BGR float32 array.
    """
    hdr = cv2.imread(str(input_path), cv2.IMREAD_UNCHANGED)
    if hdr is None:
        raise FileNotFoundError(f"Cannot read HDR image: {input_path}")

    hdr = hdr.astype(np.float32)

    # Handle cases where channels are missing or alpha present
    if hdr.ndim == 2:
        hdr = cv2.merge([hdr, hdr, hdr])
    elif hdr.shape[2] == 4:
        hdr = hdr[:, :, :3]

    return hdr


def _load_exr(input_path: Path) -> np.ndarray:
    """Load an EXR file and return as BGR float32 numpy array.

    Args:
        input_path (Path): Path to the EXR file.

    Returns:
        np.ndarray: BGR image as float32 (H×W×3).

    Raises:
        FileNotFoundError: If the EXR file cannot be loaded.
    """
    try:
        exr_file = OpenEXR.InputFile(str(input_path))
    except Exception as e:
        raise FileNotFoundError(f"Cannot read EXR image: {input_path}") from e

    header = exr_file.header()
    dw = header["dataWindow"]
    width = dw.max.x - dw.min.x + 1
    height = dw.max.y - dw.min.y + 1

    FLOAT = Imath.PixelType(Imath.PixelType.FLOAT)
    channels = ["R", "G", "B"]

    available_channels = header["channels"].keys()
    if not all(ch in available_channels for ch in channels):
        if "Y" in available_channels:
            channels = ["Y", "Y", "Y"]
        else:
            raise ValueError(
                f"EXR file missing RGB or Y channels: {input_path}"
            )

    # Read channel data
    channel_data = [exr_file.channel(ch, FLOAT) for ch in channels]
    r = np.frombuffer(channel_data[0], dtype=np.float32).reshape(height, width)
    g = np.frombuffer(channel_data[1], dtype=np.float32).reshape(height, width)
    b = np.frombuffer(channel_data[2], dtype=np.float32).reshape(height, width)

    # Stack as BGR (OpenCV convention)
    bgr = np.stack([b, g, r], axis=2)

    return bgr


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
