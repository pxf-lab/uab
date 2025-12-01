from abc import ABC


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
        Create an Asset from a plain dictionary coming from the API / DB.

        Expects keys compatible with the backend model / API schema.
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
        Convert this Asset into a serialisable dictionary suitable for API calls.
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


class Texture(Asset):
    def __init__(self, name: str, path: str, color_space: str):
        super().__init__(name, path)
        self.color_space = color_space


class HDRI(Texture):
    def __init__(self, name: str, path: str, color_space: str):
        super().__init__(name, path, color_space)
