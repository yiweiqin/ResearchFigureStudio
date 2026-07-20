import unittest


class PackageBoundaryTests(unittest.TestCase):
    def test_stable_package_entry_points_are_importable(self):
        from rfs.analysis import parse_paper, plan_reference_layout
        from rfs.composition import compile_ppt, render_rebuild_preview
        from rfs.contracts import apply_paper_semantic_contract
        from rfs.evaluation import run_rebuild_visual_quality_check
        from rfs.generation import generate_and_select
        from rfs.planning import plan_paper_image
        from rfs.providers import call_vlm_json
        from rfs.workflows import run_paper_to_editable

        for value in (
            parse_paper,
            plan_reference_layout,
            compile_ppt,
            render_rebuild_preview,
            apply_paper_semantic_contract,
            run_rebuild_visual_quality_check,
            generate_and_select,
            plan_paper_image,
            call_vlm_json,
            run_paper_to_editable,
        ):
            self.assertTrue(callable(value))

    def test_legacy_imports_remain_compatible(self):
        from rfs.composition import compile_ppt as stable_compile
        from rfs.contracts import apply_paper_semantic_contract as stable_contract
        from rfs.paper_to_editable import run_paper_to_editable as legacy_workflow
        from rfs.ppt_compiler import compile_ppt as legacy_compile
        from rfs.semantic_contract import apply_paper_semantic_contract as legacy_contract
        from rfs.workflows import run_paper_to_editable as stable_workflow

        self.assertIs(legacy_compile, stable_compile)
        self.assertIs(legacy_contract, stable_contract)
        self.assertIs(legacy_workflow, stable_workflow)


if __name__ == "__main__":
    unittest.main()
