"""Utility functions for UI layer."""

from io import BytesIO
from pathlib import Path
from typing import Optional

from PySide6.QtGui import QPixmap
import numpy as np
from PIL import Image
import OpenEXR
import Imath
import imageio.v3 as iio


def load_hdri_thumbnail(path: Path, max_size: int = 256) -> Optional[QPixmap]:
    """
    Load an HDR/EXR file and convert to a viewable QPixmap thumbnail.

    Args:
        path: Path to the HDR or EXR file
        max_size: Maximum dimension for the thumbnail

    Returns:
        QPixmap or None if loading fails
    """
    try:
        suffix = path.suffix.lower()

        if suffix == ".hdr":
            return _load_hdr_file(path, max_size)
        elif suffix == ".exr":
            return _load_exr_file(path, max_size)

        return None
    except ImportError:
        # If numpy/PIL not available, return None
        return None
    except Exception:
        return None


def _load_hdr_file(path: Path, max_size: int) -> Optional[QPixmap]:
    """Load a Radiance HDR file."""
    try:
        # Try imageio first (best HDR support)
        try:
            hdr_data = iio.imread(str(path))
        except ImportError:
            # Fallback: read raw HDR manually
            hdr_data = _read_hdr_manual(path)
            if hdr_data is None:
                return None

        # Ensure float32
        hdr_data = np.array(hdr_data, dtype=np.float32)

        # Experimentally good values for hdr files
        ldr_data = _tone_map_reinhard(hdr_data, 1.0, 0.02)

        # Convert to 8-bit
        ldr_8bit = np.clip(ldr_data * 255, 0, 255).astype(np.uint8)

        # Create PIL image
        ldr_img = Image.fromarray(ldr_8bit, mode="RGB")

        # Resize if needed
        if max(ldr_img.size) > max_size:
            ldr_img.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)

        # Convert to QPixmap
        return _pil_to_qpixmap(ldr_img)

    except Exception as e:
        print(f"Error loading HDR {path}: {e}")
        return None


def _read_hdr_manual(path: Path) -> Optional["np.ndarray"]:
    """Manually read a Radiance HDR file."""
    try:
        with open(path, "rb") as f:
            # Read header
            line = f.readline().decode("ascii", errors="ignore")
            if not line.startswith("#?RADIANCE") and not line.startswith("#?"):
                return None

            # Skip header lines until empty line
            width = height = 0
            while True:
                line = f.readline().decode("ascii", errors="ignore").strip()
                if not line:
                    break

            # Read resolution line
            res_line = f.readline().decode("ascii", errors="ignore").strip()
            parts = res_line.split()
            if len(parts) >= 4:
                if parts[0] == "-Y":
                    height = int(parts[1])
                    width = int(parts[3])
                elif parts[0] == "+Y":
                    height = int(parts[1])
                    width = int(parts[3])

            if width == 0 or height == 0:
                return None

            # Read pixel data (RLE encoded)
            data = np.zeros((height, width, 3), dtype=np.float32)

            for y in range(height):
                # Read scanline
                scanline = _read_hdr_scanline(f, width)
                if scanline is not None:
                    data[y] = scanline

            return data

    except Exception:
        return None


def _read_hdr_scanline(f, width: int) -> Optional["np.ndarray"]:
    """Read a single HDR scanline (handles RLE encoding)."""
    # Check for new RLE format
    rgbe = f.read(4)
    if len(rgbe) < 4:
        return None

    if rgbe[0] == 2 and rgbe[1] == 2:
        # New RLE format
        scanline_width = (rgbe[2] << 8) | rgbe[3]
        if scanline_width != width:
            return None

        # Read each channel separately
        channels = []
        for _ in range(4):
            channel = []
            while len(channel) < width:
                b = f.read(1)
                if not b:
                    return None
                count = b[0]
                if count > 128:
                    # Run
                    count -= 128
                    val = f.read(1)
                    if not val:
                        return None
                    channel.extend([val[0]] * count)
                else:
                    # Non-run
                    vals = f.read(count)
                    if len(vals) < count:
                        return None
                    channel.extend(vals)
            channels.append(np.array(channel[:width], dtype=np.uint8))

        # Convert RGBE to float RGB
        r, g, b, e = channels
        scale = np.power(2.0, e.astype(np.float32) - 128.0 - 8.0)
        scale[e == 0] = 0

        rgb = np.zeros((width, 3), dtype=np.float32)
        rgb[:, 0] = r * scale
        rgb[:, 1] = g * scale
        rgb[:, 2] = b * scale

        return rgb
    else:
        # Old format - uncompressed RGBE
        f.seek(-4, 1)  # Go back
        scanline = np.zeros((width, 3), dtype=np.float32)
        for x in range(width):
            rgbe = f.read(4)
            if len(rgbe) < 4:
                break
            if rgbe[3] != 0:
                scale = 2.0 ** (rgbe[3] - 128 - 8)
                scanline[x, 0] = rgbe[0] * scale
                scanline[x, 1] = rgbe[1] * scale
                scanline[x, 2] = rgbe[2] * scale
        return scanline


def _load_exr_file(path: Path, max_size: int) -> Optional[QPixmap]:
    """Load an OpenEXR file."""
    try:
        exr_file = OpenEXR.InputFile(str(path))
        header = exr_file.header()

        # Get dimensions
        dw = header["dataWindow"]
        width = dw.max.x - dw.min.x + 1
        height = dw.max.y - dw.min.y + 1

        # Read RGB channels
        pt = Imath.PixelType(Imath.PixelType.FLOAT)

        # Try common channel names
        channels = header["channels"]
        if "R" in channels:
            r_str = exr_file.channel("R", pt)
            g_str = exr_file.channel("G", pt)
            b_str = exr_file.channel("B", pt)
        elif "r" in channels:
            r_str = exr_file.channel("r", pt)
            g_str = exr_file.channel("g", pt)
            b_str = exr_file.channel("b", pt)
        else:
            return None

        # Convert to numpy arrays
        r = np.frombuffer(r_str, dtype=np.float32).reshape(height, width)
        g = np.frombuffer(g_str, dtype=np.float32).reshape(height, width)
        b = np.frombuffer(b_str, dtype=np.float32).reshape(height, width)

        hdr_data = np.stack([r, g, b], axis=-1)

        # Tone map, experimentally good values for exr files
        ldr_data = _tone_map_reinhard(hdr_data, 1.0, 2.2)

        # Convert to 8-bit
        ldr_8bit = np.clip(ldr_data * 255, 0, 255).astype(np.uint8)

        # Create PIL image
        ldr_img = Image.fromarray(ldr_8bit, mode="RGB")

        # Resize if needed
        if max(ldr_img.size) > max_size:
            ldr_img.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)

        return _pil_to_qpixmap(ldr_img)

    except Exception:
        return None


def _tone_map_reinhard(hdr: "np.ndarray", gamma: float, exposure: float) -> "np.ndarray":
    """Apply Reinhard tone mapping to HDR data."""
    # Apply exposure
    hdr = hdr * exposure

    # Reinhard tone mapping: L / (1 + L)
    luminance = 0.2126 * hdr[:, :, 0] + 0.7152 * \
        hdr[:, :, 1] + 0.0722 * hdr[:, :, 2]
    luminance = np.maximum(luminance, 1e-6)

    # Tone map
    ldr = hdr / (1 + luminance[:, :, np.newaxis])

    # Gamma correction
    ldr = np.power(np.clip(ldr, 0, 1), 1 / gamma)

    return ldr


def _pil_to_qpixmap(img: "Image.Image") -> QPixmap:
    """Convert a PIL Image to QPixmap."""
    # Ensure RGB mode
    if img.mode != "RGB":
        img = img.convert("RGB")

    # Convert to bytes
    buffer = BytesIO()
    img.save(buffer, format="PNG")
    buffer.seek(0)

    # Load into QPixmap
    pixmap = QPixmap()
    pixmap.loadFromData(buffer.read())

    return pixmap
