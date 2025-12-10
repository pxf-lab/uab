from abc import ABC
from io import BytesIO
from pathlib import Path

import cv2
import Imath
import numpy as np
import OpenEXR
from PIL import Image


class Asset(ABC):
    """
    Core in‑memory representation of an asset used throughout the UI/presenter.

    Mirrors the fields stored in the backend database and exposed via the API.
    """

    def __init__(
        self,
        name: str,
        path: str,
        asset_id: int | None = None,
        description: str | None = None,
        preview_image_file_path: str | None = None,
        tags: list[str] | None = None,
        author: str | None = None,
        date_created: str | None = None,
        date_added: str | None = None,
    ):
        self.id = asset_id
        self.name = name
        self.path = path
        self.description = description
        self.preview_image_file_path = preview_image_file_path
        self.tags = tags or []
        self.author = author
        self.date_created = date_created
        self.date_added = date_added

    @classmethod
    def from_dict(cls, data: dict) -> "Asset":
        """
        Creates an Asset instance from a plain dictionary coming from the API or database.

        Args:
            data (dict): A dictionary containing asset fields. Keys should be compatible 
                with the backend model or API schema.

        Returns:
            Asset: An instance of the Asset class populated with values from the dictionary.

        Raises:
            ValueError: If the input data is None.
        """
        if data is None:
            raise ValueError("Cannot create Asset from None")

        return cls(
            name=data.get("name", ""),
            path=data.get("path", ""),
            asset_id=data.get("id"),
            description=data.get("description"),
            preview_image_file_path=data.get("preview_image_file_path"),
            tags=data.get("tags") or [],
            author=data.get("author"),
            date_created=data.get("date_created"),
            date_added=data.get("date_added"),
        )

    def to_dict(self) -> dict:
        """
        Converts this Asset into a serializable dictionary suitable for API calls.

        Returns:
            dict: A dictionary representation of this Asset object, with all core fields.
        """
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "path": self.path,
            "preview_image_file_path": self.preview_image_file_path,
            "tags": list(self.tags) if self.tags is not None else [],
            "author": self.author,
            "date_created": self.date_created,
            "date_added": self.date_added,
        }

    @classmethod
    def from_api_payload(cls, data: dict) -> "Asset":
        """
        Creates an Asset instance from an API or JSON payload.

        Args:
            data (dict): The dictionary representing the API or JSON payload.

        Returns:
            Asset: An instance of the Asset class.

        Notes:
            This method is currently a thin wrapper around from_dict, keeping the
            HTTP-boundary concept explicit for potential wire format divergence later.
        """
        return cls.from_dict(data)

    def to_api_payload(self, include_id: bool = False) -> dict:
        """
        Converts this Asset into a JSON‑serializable payload for API calls.

        Args:
            include_id (bool): Whether to include the `id` field in the payload.
                              Typically False for create, True for update.

        Returns:
            dict: A dictionary suitable for use as a FastAPI request body.
        """
        payload = self.to_dict()
        if not include_id:
            payload.pop("id", None)
        return payload


class Texture(Asset):
    def __init__(
        self,
        name: str,
        path: str,
        color_space: str = None,
        lods: dict[str, str] | None = None,
        current_lod: str | None = None,
    ):
        super().__init__(name, path)
        self.color_space = color_space
        self.lods = lods or {}
        self.current_lod = current_lod

    def add_lod(self, lod_level: str, lod_path: str) -> None:
        """Add or update a LOD level for this texture.

        Args:
            lod_level (str): The LOD level identifier (e.g., "0", "1", "2" or "high", "medium", "low").
            lod_path (str): The file path for this LOD level.
        """
        self.lods[lod_level] = lod_path

    def remove_lod(self, lod_level: str) -> bool:
        """Remove an LOD level from this texture.

        Args:
            lod_level (str): The LOD level identifier to remove.

        Returns:
            bool: True if the LOD was removed, False if it didn't exist.
        """
        if lod_level in self.lods:
            del self.lods[lod_level]
            # If we removed the current LOD, reset current_lod
            if self.current_lod == lod_level:
                self.current_lod = None
            return True
        return False


class HDRI(Texture):
    def __init__(self, name: str, path: str, color_space: str = None):
        super().__init__(name, path, color_space)
        # remove the dot from the file type
        self.file_type = super().path.suffix.upper()[1:]

    @staticmethod
    def _load_hdr(input_path: Path) -> np.ndarray:
        """Load an HDR file and return as a BGR float32 numpy array.

        Args:
            input_path (Path): Path to the HDR image file.

        Returns:
            np.ndarray: Loaded image as a BGR float32 numpy array.

        Raises:
            FileNotFoundError: If the HDR image cannot be read.
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

    @staticmethod
    def _load_exr(input_path: Path) -> np.ndarray:
        """Load an EXR file and return as a BGR float32 numpy array.

        Args:
            input_path (Path): Path to the EXR image file.

        Returns:
            np.ndarray: Loaded image as a BGR float32 numpy array.

        Raises:
            FileNotFoundError: If the EXR image cannot be opened.
            ValueError: If needed channels are missing in the EXR.
        """
        try:
            exr_file = OpenEXR.InputFile(str(input_path))
        except Exception as e:  # pragma: no cover - defensive
            raise FileNotFoundError(
                f"Cannot read EXR image: {input_path}") from e

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
        r = np.frombuffer(
            channel_data[0], dtype=np.float32).reshape(height, width)
        g = np.frombuffer(
            channel_data[1], dtype=np.float32).reshape(height, width)
        b = np.frombuffer(
            channel_data[2], dtype=np.float32).reshape(height, width)

        # Stack as BGR (OpenCV convention)
        bgr = np.stack([b, g, r], axis=2)
        return bgr

    @staticmethod
    def _tone_map(
        hdr: np.ndarray,
        gamma: float = 2.4,
        intensity: float = 0.5,
        light_adapt: float = 0.0,
        color_adapt: float = 0.0,
    ) -> np.ndarray:
        """Apply Reinhard tone mapping and return an 8-bit RGB image.

        Args:
            hdr (np.ndarray): The input HDR image, BGR float32 numpy array.
            gamma (float, optional): Gamma correction value. Defaults to 2.4.
            intensity (float, optional): Intensity for tone mapping. Defaults to 0.5.
            light_adapt (float, optional): Light adaptation. Defaults to 0.0.
            color_adapt (float, optional): Color adaptation. Defaults to 0.0.

        Returns:
            np.ndarray: Tone-mapped 8-bit RGB numpy array.
        """
        tonemap = cv2.createTonemapReinhard(
            gamma=gamma,
            intensity=intensity,
            light_adapt=light_adapt,
            color_adapt=color_adapt,
        )
        ldr = tonemap.process(hdr)

        # Convert to 8-bit RGB
        ldr_8bit = np.clip(ldr * 255, 0, 255).astype(np.uint8)
        ldr_rgb = cv2.cvtColor(ldr_8bit, cv2.COLOR_BGR2RGB)
        return ldr_rgb

    @classmethod
    def _render_from_file(
        cls,
        input_path: str | Path,
        gamma: float = 2.4,
        intensity: float = 0.5,
        light_adapt: float = 0.0,
        color_adapt: float = 0.0,
        as_image: bool = True,
        as_bytes: bool = False,
    ):
        """Render an HDR or EXR image file to a tone-mapped RGB preview.

        Args:
            input_path (str | Path): The path to the input .hdr or .exr file.
            gamma (float, optional): Gamma correction value. Defaults to 2.4.
            intensity (float, optional): Intensity for tone mapping. Defaults to 0.5.
            light_adapt (float, optional): Light adaptation. Defaults to 0.0.
            color_adapt (float, optional): Color adaptation. Defaults to 0.0.
            as_image (bool, optional): If True, return as PIL Image. Defaults to True.
            as_bytes (bool, optional): If True, return as JPEG bytes. Defaults to False.

        Returns:
            Image.Image | np.ndarray | bytes: Preview as PIL Image (default), numpy array, or bytes.

        Raises:
            ValueError: If the file extension is not supported.
        """
        input_path = Path(input_path)
        ext = input_path.suffix.lower()

        if ext == ".exr":
            hdr = cls._load_exr(input_path)
        elif ext == ".hdr":
            hdr = cls._load_hdr(input_path)
        else:
            raise ValueError(f"Unsupported file extension: {ext}")

        ldr_rgb = cls._tone_map(
            hdr,
            gamma=gamma,
            intensity=intensity,
            light_adapt=light_adapt,
            color_adapt=color_adapt,
        )

        if as_bytes:
            img = Image.fromarray(ldr_rgb)
            buffer = BytesIO()
            img.save(buffer, format="JPEG", quality=85)
            return buffer.getvalue()

        if as_image:
            return Image.fromarray(ldr_rgb)

        return ldr_rgb

    @staticmethod
    def render_from_hdr(
        input_path: str | Path,
        gamma: float = 2.4,
        intensity: float = 0.5,
        light_adapt: float = 0.0,
        color_adapt: float = 0.0,
        as_image: bool = True,
        as_bytes: bool = False,
    ):
        """Render a preview from an .hdr file using tone mapping.

        Args:
            input_path (str | Path): Path to the .hdr file.
            gamma (float, optional): Gamma correction value. Defaults to 2.4.
            intensity (float, optional): Intensity for tone mapping. Defaults to 0.5.
            light_adapt (float, optional): Light adaptation. Defaults to 0.0.
            color_adapt (float, optional): Color adaptation. Defaults to 0.0.
            as_image (bool, optional): If True, return as PIL Image. Defaults to True.
            as_bytes (bool, optional): If True, return as JPEG bytes. Defaults to False.

        Returns:
            Image.Image | np.ndarray | bytes: Preview as PIL Image (default), numpy array, or bytes.
        """
        return HDRI._render_from_file(
            input_path=input_path,
            gamma=gamma,
            intensity=intensity,
            light_adapt=light_adapt,
            color_adapt=color_adapt,
            as_image=as_image,
            as_bytes=as_bytes,
        )

    @staticmethod
    def render_from_exr(
        input_path: str | Path,
        gamma: float = 2.4,
        intensity: float = 0.5,
        light_adapt: float = 0.0,
        color_adapt: float = 0.0,
        as_image: bool = True,
        as_bytes: bool = False,
    ):
        """Render a preview from an .exr file using tone mapping.

        Args:
            input_path (str | Path): Path to the .exr file.
            gamma (float, optional): Gamma correction value. Defaults to 2.4.
            intensity (float, optional): Intensity for tone mapping. Defaults to 0.5.
            light_adapt (float, optional): Light adaptation. Defaults to 0.0.
            color_adapt (float, optional): Color adaptation. Defaults to 0.0.
            as_image (bool, optional): If True, return as PIL Image. Defaults to True.
            as_bytes (bool, optional): If True, return as JPEG bytes. Defaults to False.

        Returns:
            Image.Image | np.ndarray | bytes: Preview as PIL Image (default), numpy array, or bytes.
        """
        return HDRI._render_from_file(
            input_path=input_path,
            gamma=gamma,
            intensity=intensity,
            light_adapt=light_adapt,
            color_adapt=color_adapt,
            as_image=as_image,
            as_bytes=as_bytes,
        )

    def render_pixmap(
        self,
        gamma: float = 2.4,
        intensity: float = 0.5,
        light_adapt: float = 0.0,
        color_adapt: float = 0.0,
        as_image: bool = True,
        as_bytes: bool = False,
    ):
        """Render a preview for this HDRI object's own file path.

        Args:
            gamma (float, optional): Gamma correction value. Defaults to 2.4.
            intensity (float, optional): Intensity for tone mapping. Defaults to 0.5.
            light_adapt (float, optional): Light adaptation. Defaults to 0.0.
            color_adapt (float, optional): Color adaptation. Defaults to 0.0.
            as_image (bool, optional): If True, return as PIL Image. Defaults to True.
            as_bytes (bool, optional): If True, return as JPEG bytes. Defaults to False.

        Returns:
            Image.Image | np.ndarray | bytes: Preview as PIL Image (default), numpy array, or bytes.
        """
        return self._render_from_file(
            input_path=self.path,
            gamma=gamma,
            intensity=intensity,
            light_adapt=light_adapt,
            color_adapt=color_adapt,
            as_image=as_image,
            as_bytes=as_bytes,
        )
