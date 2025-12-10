"""Pydantic models for API request/response."""

from pydantic import BaseModel
from typing import Optional, List, Dict


class AssetBase(BaseModel):
    name: str
    description: Optional[str] = None
    path: str
    preview_image_file_path: Optional[str] = None
    tags: Optional[List[str]] = None
    author: Optional[str] = None
    date_created: Optional[str] = None
    date_added: Optional[str] = None
    lods: Optional[Dict[str, str]] = None
    current_lod: Optional[str] = None
    color_space: Optional[str] = None


class AssetCreate(AssetBase):
    """Request model for creating a new asset."""
    pass


class AssetUpdate(BaseModel):
    """Partial update model for assets."""
    name: Optional[str] = None
    description: Optional[str] = None
    path: Optional[str] = None
    preview_image_file_path: Optional[str] = None
    tags: Optional[List[str]] = None
    author: Optional[str] = None
    date_created: Optional[str] = None
    date_added: Optional[str] = None
    lods: Optional[Dict[str, str]] = None
    current_lod: Optional[str] = None
    color_space: Optional[str] = None


class AssetResponse(AssetBase):
    id: int

    class Config:
        orm_mode = True
