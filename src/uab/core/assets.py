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


class Texture(Asset):
    def __init__(self, name: str, path: str, color_space: str):
        super().__init__(name, path)
        self.color_space = color_space


class HDRI(Texture):
    def __init__(self, name: str, path: str, color_space: str):
        super().__init__(name, path, color_space)
