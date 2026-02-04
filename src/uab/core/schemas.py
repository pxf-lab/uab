"""Composite type schemas for validation and UI hints.

The `CompositeAsset` model is intentionally flexible (it can contain either
`Asset` leaves or other `CompositeAsset` nodes). These schemas provide an
*optional* layer describing expected structure for a given `CompositeType`.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from uab.core.models import Asset, AssetType, CompositeAsset, CompositeType


@dataclass(frozen=True, slots=True)
class CompositeTypeSchema:
    """Schema defining the expected structure of a composite type."""

    composite_type: CompositeType

    # What type of children this composite can contain
    allowed_child_types: set[type]  # {Asset}, {CompositeAsset}, or {Asset, CompositeAsset}

    # For composites that contain other composites, what types are expected
    expected_child_composite_types: set[CompositeType] = field(default_factory=set)

    # Roles that MUST be present for the composite to be "complete"
    required_roles: set[str] = field(default_factory=set)

    # Roles that MAY be present (for UI hints, validation)
    optional_roles: set[str] = field(default_factory=set)

    # For leaf composites (contain Assets), what asset type is expected
    child_asset_type: AssetType | None = None

    # Human-readable description for UI
    description: str = ""

    @property
    def is_leaf_composite(self) -> bool:
        """True if this composite type contains only Assets (not other composites)."""
        return CompositeAsset not in self.allowed_child_types

    @property
    def all_known_roles(self) -> set[str]:
        """All roles this schema recognizes."""
        return self.required_roles | self.optional_roles

    def is_role_valid(self, role: str) -> bool:
        """Check if a role is recognized by this schema."""
        # Allow unknown roles when the schema doesn't specify any roles (extensibility).
        return role in self.all_known_roles or not self.all_known_roles


COMPOSITE_SCHEMAS: dict[CompositeType, CompositeTypeSchema] = {
    # Leaf composites (contain only Assets)
    CompositeType.TEXTURE: CompositeTypeSchema(
        composite_type=CompositeType.TEXTURE,
        allowed_child_types={Asset},
        child_asset_type=AssetType.TEXTURE,
        optional_roles={"1k", "2k", "4k", "8k", "16k"},
        description="Single texture map with multiple resolution LODs",
    ),
    CompositeType.MODEL: CompositeTypeSchema(
        composite_type=CompositeType.MODEL,
        allowed_child_types={Asset},
        child_asset_type=AssetType.MODEL,
        optional_roles={"lod0", "lod1", "lod2", "lod3", "proxy", "collision"},
        description="Single model with multiple LOD levels",
    ),
    CompositeType.HDRI: CompositeTypeSchema(
        composite_type=CompositeType.HDRI,
        allowed_child_types={Asset},
        child_asset_type=AssetType.HDRI,
        optional_roles={"1k", "2k", "4k", "8k", "16k"},
        description="Single HDRI with multiple resolution options",
    ),
    # Mid-level composites (contain other composites)
    CompositeType.MATERIAL: CompositeTypeSchema(
        composite_type=CompositeType.MATERIAL,
        allowed_child_types={CompositeAsset},
        expected_child_composite_types={CompositeType.TEXTURE},
        optional_roles={
            "diffuse",
            "base_color",
            "albedo",
            "normal",
            "nor_gl",
            "nor_dx",
            "roughness",
            "rough",
            "metallic",
            "metalness",
            "ao",
            "ambient_occlusion",
            "height",
            "displacement",
            "bump",
            "emissive",
            "emission",
            "opacity",
            "alpha",
            "arm",
        },
        description="PBR material composed of texture composites",
    ),
    CompositeType.HDRI_SET: CompositeTypeSchema(
        composite_type=CompositeType.HDRI_SET,
        allowed_child_types={CompositeAsset},
        expected_child_composite_types={CompositeType.HDRI},
        required_roles={"hdri"},
        optional_roles={"backplate", "preview"},
        description="HDRI environment with optional backplate",
    ),
    CompositeType.MODEL_SET: CompositeTypeSchema(
        composite_type=CompositeType.MODEL_SET,
        allowed_child_types={CompositeAsset},
        expected_child_composite_types={CompositeType.MODEL},
        optional_roles={"main", "detail", "proxy"},
        description="Multi-part model collection",
    ),
}


def get_schema(composite_type: CompositeType) -> CompositeTypeSchema:
    """Get the schema for a composite type."""
    return COMPOSITE_SCHEMAS.get(composite_type, COMPOSITE_SCHEMAS[CompositeType.SCENE])

