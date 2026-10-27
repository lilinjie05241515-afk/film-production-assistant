"""Explicit asset labels and derived views; never infer labels from names or kinds."""

ASSET_TYPES = ("character", "scene", "prop", "other", "unclassified")


def validate_asset_type(value):
    if not isinstance(value, str) or value not in ASSET_TYPES:
        raise ValueError("asset_type 必须为 character/scene/prop/other/unclassified")
    return value


def asset_type_view(metadata):
    """Old missing or unknown values remain untouched in stored metadata."""
    value = metadata.get("asset_type") if isinstance(metadata, dict) else None
    return value if isinstance(value, str) and value in ASSET_TYPES else "unclassified"


def add_asset_views(snapshot, category_of):
    """Decorate each exact version separately, preserving all approval views."""
    for key in ("artifacts", "approved_artifacts", "pending_candidates", "current_content"):
        for artifact in snapshot.get(key, []):
            if category_of(artifact) == "asset":
                artifact["asset_type"] = asset_type_view(artifact.get("metadata"))
    for media in snapshot.get("media", []):
        media["asset_type"] = asset_type_view(media.get("metadata"))
        media.setdefault("classification_revision", 0)
    images = [media for media in snapshot.get("media", []) if media.get("kind") == "image"]
    summary = {"by_type": {kind: {"artifacts": 0, "media": 0} for kind in ASSET_TYPES},
               "artifact_count": 0, "media_count": len(images),
               "artifact_scope": "latest_versions", "media_scope": "registered_images",
               "approval_inferred": False}
    for artifact in snapshot.get("artifacts", []):
        if category_of(artifact) == "asset":
            summary["by_type"][artifact["asset_type"]]["artifacts"] += 1
            summary["artifact_count"] += 1
    for media in images:
        summary["by_type"][media["asset_type"]]["media"] += 1
    snapshot["asset_summary"] = summary

