import cv2
import numpy as np
from io import BytesIO
from pathlib import Path
from PIL import Image
import OpenEXR
import Imath


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

    This function loads a 32-bit HDR or EXR environment map, applies Reinhard
    tone mapping, and produces a low dynamic range version suitable for previews.

    Args:
        input_path (str | Path): Path to the HDR or EXR image.
        gamma (float, optional): Gamma correction factor. Defaults to 2.4.
        intensity (float, optional): Reinhard tone-mapping intensity. Defaults to 0.5.
        light_adapt (float, optional): Light adaptation factor. Defaults to 0.0.
        color_adapt (float, optional): Color adaptation factor. Defaults to 0.0.
        as_image (bool, optional): If True, return a Pillow Image.
        as_bytes (bool, optional): If True, return JPEG bytes (e.g. for web display).

    Returns:
        Union[Image.Image, np.ndarray, bytes]:
            - Pillow Image if `as_image` is True.
            - NumPy array (H×W×3, uint8) if both flags are False.
            - JPEG byte stream if `as_bytes` is True.

    Raises:
        FileNotFoundError: If the HDR/EXR file cannot be loaded or is invalid.
    """
    input_path = Path(input_path)

    # Check file extension to determine loading method
    if input_path.suffix.lower() == '.exr':
        hdr = _load_exr(input_path)
    else:
        hdr = cv2.imread(str(input_path), cv2.IMREAD_UNCHANGED)
        if hdr is None:
            raise FileNotFoundError(f"Cannot read HDR image: {input_path}")

    # Ensure it's float32
    hdr = hdr.astype(np.float32)

    # Some .hdr files load as single-channel; convert to 3-channel if needed
    if hdr.ndim == 2:
        hdr = cv2.merge([hdr, hdr, hdr])
    elif hdr.shape[2] == 4:
        # Drop alpha if present
        hdr = hdr[:, :, :3]

    # Create tone mapping operator
    tonemap = cv2.createTonemapReinhard(
        gamma=gamma,
        intensity=intensity,
        light_adapt=light_adapt,
        color_adapt=color_adapt,
    )

    # Apply tone mapping safely
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

    # Get image dimensions
    header = exr_file.header()
    dw = header['dataWindow']
    width = dw.max.x - dw.min.x + 1
    height = dw.max.y - dw.min.y + 1

    # Read RGB channels
    FLOAT = Imath.PixelType(Imath.PixelType.FLOAT)
    channels = ['R', 'G', 'B']

    # Check which channels are available
    available_channels = header['channels'].keys()
    if not all(ch in available_channels for ch in channels):
        # Try Y channel for grayscale
        if 'Y' in available_channels:
            channels = ['Y', 'Y', 'Y']
        else:
            raise ValueError(
                f"EXR file missing RGB or Y channels: {input_path}")

    # Read channel data
    channel_data = [exr_file.channel(ch, FLOAT) for ch in channels]

    # Convert to numpy arrays
    r = np.frombuffer(channel_data[0], dtype=np.float32).reshape(height, width)
    g = np.frombuffer(channel_data[1], dtype=np.float32).reshape(height, width)
    b = np.frombuffer(channel_data[2], dtype=np.float32).reshape(height, width)

    # Stack as BGR (OpenCV format)
    bgr = np.stack([b, g, r], axis=2)

    return bgr
