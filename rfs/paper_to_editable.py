"""Compatibility import for the paper-to-editable workflow.

New code should import from :mod:`rfs.workflows`.
"""

from .workflows.paper_to_editable import run_paper_to_editable

__all__ = ["run_paper_to_editable"]
