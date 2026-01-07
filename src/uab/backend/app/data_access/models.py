from sqlalchemy import Column, Integer, String, Text
from sqlalchemy.types import JSON
from .database import Base


class Asset(Base):
    __tablename__ = "assets"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    description = Column(Text, nullable=True)
    path = Column(String)
    preview_image_file_path = Column(String, nullable=True)
    tags = Column(JSON, nullable=True)
    author = Column(String, nullable=True)
    date_created = Column(String, nullable=True)
    date_added = Column(String, nullable=True)
    lods = Column(JSON, nullable=True)
    current_lod = Column(String, nullable=True)
    color_space = Column(String, nullable=True)

    def __repr__(self):
        return f"<Asset(id={self.id}, name='{self.name}')>"
