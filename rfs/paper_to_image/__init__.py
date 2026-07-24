"""Paper analysis and paper-to-image workflows."""

from .inspection import inspect_paper
from .editable_ppt import build_semantic_figure_program, compile_semantic_ppt
from .preparation import prepare_paper_figure_contract, run_fast_framework_prompt
from .workflow import run_paper_to_image

__all__ = ["build_semantic_figure_program", "compile_semantic_ppt", "inspect_paper", "prepare_paper_figure_contract", "run_fast_framework_prompt", "run_paper_to_image"]
