from abc import ABC


class Asset(ABC):
    def __init__(self, name: str, path: str):
        self.name = name
        self.path = path


class Texture(Asset):
    def __init__(self, name: str, path: str, color_space: str):
        super().__init__(name, path)
        self.color_space = color_space


class HDRI(Texture):
    def __init__(self, name: str, path: str, color_space: str):
        super().__init__(name, path, color_space)
