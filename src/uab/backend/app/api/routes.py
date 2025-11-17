"""API routes for browser CRUD operations."""

from typing import Dict, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from sqlalchemy import text, or_, and_
from ..data_access import models, database
from ..api.schemas import AssetBase, AssetResponse, AssetCreate, AssetUpdate

router = APIRouter(
    prefix="/assets",
    tags=["Assets"],
    responses={404: {"description": "Not found"}},
)

# -------------------------------------------------------------------------
# GET endpoints
# -------------------------------------------------------------------------


@router.get("/", response_model=list[AssetResponse])
def get_all_assets(db: Session = Depends(database.get_db)):
    """Return all assets."""
    return db.query(models.Asset).all()


@router.get("/search", response_model=list[AssetResponse])
def search_assets(
    name: Optional[str] = Query(
        None, description="Search by asset name (partial match)"),
    tags: Optional[str] = Query(
        None, description="Search by tags (comma-separated)"),
    db: Session = Depends(database.get_db),
):
    """
    Search assets by name and/or tags.

    - name: Partial match search on asset name (case-insensitive)
    - tags: Comma-separated list of tags to search for (matches JSON tags)
    """
    query = db.query(models.Asset)
    filters = []

    # Filter by name
    if name:
        filters.append(models.Asset.name.ilike(f"%{name}%"))

    # Filter by tags
    if tags:
        tag_list = [tag.strip() for tag in tags.split(",") if tag.strip()]
        if tag_list:
            tag_filters = []
            for tag in tag_list:
                # Use JSON string search for simplicity (SQLite JSON is text-based)
                tag_filters.append(models.Asset.tags.like(f'%"{tag}"%'))
            if tag_filters:
                filters.append(or_(*tag_filters))

    if filters:
        query = query.filter(and_(*filters))

    return query.all()


@router.get("/{asset_id}", response_model=AssetResponse)
def get_asset(asset_id: int, db: Session = Depends(database.get_db)):
    db_asset = db.query(models.Asset).filter(
        models.Asset.id == asset_id).first()
    if db_asset is None:
        raise HTTPException(
            status_code=404, detail=f"Asset with id `{asset_id}` not found")
    return db_asset

# -------------------------------------------------------------------------
# POST endpoint
# -------------------------------------------------------------------------


@router.post("/", response_model=AssetResponse, status_code=status.HTTP_201_CREATED)
def create_asset(asset: AssetCreate, db: Session = Depends(database.get_db)):
    """Create a new asset."""
    db_asset = models.Asset(
        name=asset.name,
        description=asset.description,
        path=asset.path,
        preview_image_file_path=asset.preview_image_file_path,
        tags=asset.tags,
        author=asset.author,
        date_created=asset.date_created,
        date_added=asset.date_added,
    )
    db.add(db_asset)
    db.commit()
    db.refresh(db_asset)
    return db_asset

# -------------------------------------------------------------------------
# PUT endpoint
# -------------------------------------------------------------------------


@router.put("/{asset_id}", response_model=AssetResponse)
def update_asset(asset_id: int, asset: AssetUpdate, db: Session = Depends(database.get_db)):
    """Update an existing asset by ID."""
    db_asset = db.query(models.Asset).filter(
        models.Asset.id == asset_id).first()
    if db_asset is None:
        raise HTTPException(
            status_code=404, detail=f"Asset with id `{asset_id}` not found")

    # Dynamically update only fields that were provided
    for field, value in asset.dict(exclude_unset=True).items():
        setattr(db_asset, field, value)

    db.commit()
    db.refresh(db_asset)
    return db_asset

# -------------------------------------------------------------------------
# DELETE endpoints
# -------------------------------------------------------------------------


@router.delete("/{asset_id}", response_model=AssetResponse)
def delete_asset(asset_id: int, db: Session = Depends(database.get_db)):
    """Delete an asset by ID."""
    db_asset = db.query(models.Asset).filter(
        models.Asset.id == asset_id).first()
    if db_asset is None:
        raise HTTPException(
            status_code=404, detail=f"Asset with id `{asset_id}` not found")

    db.delete(db_asset)
    db.commit()
    return db_asset


@router.delete(
    "/admin/clear-database",
    status_code=status.HTTP_200_OK,
    response_model=Dict[str, str],
)
def clear_database(db: Session = Depends(database.get_db)):
    """Delete all data from all tables."""
    try:
        table_names = [
            table.name for table in models.Base.metadata.sorted_tables]
        for table_name in reversed(table_names):
            db.execute(text(f"DELETE FROM {table_name}"))
        db.commit()
        return {"message": "Database cleared successfully."}
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to clear database: {e}",
        )
