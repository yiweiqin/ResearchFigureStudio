"""Paper analysis and paper-to-image workflows."""

from .inspection import inspect_paper
from .preparation import prepare_paper_figure_contract, run_fast_framework_prompt
from .workflow import run_paper_to_image

__all__ = ["inspect_paper", "prepare_paper_figure_contract", "run_fast_framework_prompt", "run_paper_to_image"]
