"""Raster reference and slot-asset generation entry points."""

from ..asset_generator import generate_assets
from ..paper_to_image.generator import generate_and_select

__all__ = ["generate_and_select", "generate_assets"]
