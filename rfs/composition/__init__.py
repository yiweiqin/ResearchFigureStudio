"""Deterministic editable-figure composition and preview rendering."""

from .pptx import compile_ppt
from .preview import render_rebuild_preview

__all__ = ["compile_ppt", "render_rebuild_preview"]
