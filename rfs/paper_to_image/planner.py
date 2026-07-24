from __future__ import annotations

import json
import re
import unicodedata
from typing import Any

from ..vlm_client import call_vlm_json, resolve_vlm_model, vlm_credentials_available
from .analyzer import evidence_excerpt


DEFAULT_PREFERENCES = {
    "summary": "Default paper-to-image preferences.",
    "figure_type": "method framework figure",
    "aspect_ratio": "16:9",
    "language": "English",
    "style_description": "clean academic illustration, restrained 2.5D, dense but readable",
    "preferred_flow": "left_to_right",
    "visual_density": "high",
    "preferred_palette": ["blue", "teal", "warm orange accent"],
    "avoid": ["cyberpunk", "commercial poster", "generic dashboard cards", "unrelated robots", "fake charts"],
    "must_show": [],
    "must_not_show": [],
}


def merge_preferences(raw: dict | None, aspect_ratio: str | None = None, language: str | None = None) -> dict:
    merged = dict(DEFAULT_PREFERENCES)
    if isinstance(raw, dict):
        merged.update(raw)
    if aspect_ratio:
        merged["aspect_ratio"] = aspect_ratio
    if language:
        merged["language"] = language
    merged["summary"] = "User and default preferences compiled for image generation."
    return merged


def _planner_prompt(parsed: dict, preferences: dict, paper_review: dict | None = None, evidence_max_chars: int = 58000) -> str:
    return f"""
# Summary

You are a paper-to-scientific-figure planner. Return JSON only.

Build a scientifically faithful plan for generating ONE complete raster framework figure from the supplied paper evidence. Do not create PPTX instructions. Do not invent stock modules such as encoder, retriever, memory, agent, reinforcement learning, knowledge base, or decoder unless supported by evidence.

Every important factual item must include one or more evidence_ids copied exactly from the supplied evidence labels. Mark uncertain fields as unknown. Use the paper's exact terminology.

Contract completeness rules:
- Treat Figure 1 and captions containing "overview", "framework", "architecture", or "pipeline" as high-priority evidence for the intended paper overview figure.
- Identify every major contribution pillar from the abstract and introduction. For system, dataset, or foundation-model papers, do not omit a data engine, dataset construction process, training loop, or deployment stage when it is a central contribution.
- Represent each separately named scientific component as a separate entity. Do not merge conditioning signals, special tokens, encoders, heads, inputs, or outputs into composite nodes when the paper names them independently.
- Give every input and output a stable id and include the boundary relations from input to the first processing entity and from the final processing entity to the output.
- Every relation endpoint must be an id declared in inputs, modules, outputs, or innovations.
- Include feedback and control edges explicitly instead of describing them only in prose.
- Before returning, check that every item in must_show is represented by a distinct entity or an explicit relation label.

Return this schema:
{{
  "summary": "Paper-to-image planning result.",
  "paper_summary": {{
    "summary": "Structured paper summary.",
    "title": "...",
    "paper_type": "method|system|dataset|benchmark|analysis|survey|application|unknown",
    "research_problem": {{"text": "...", "evidence_ids": ["E0001"]}},
    "central_claim": {{"text": "...", "evidence_ids": ["E0001"]}},
    "inputs": [{{"name": "...", "evidence_ids": ["E0001"]}}],
    "outputs": [{{"name": "...", "evidence_ids": ["E0001"]}}],
    "core_modules": [{{"id": "stable_id", "name": "exact paper term", "role": "...", "evidence_ids": ["E0001"]}}],
    "innovations": [{{"text": "...", "evidence_ids": ["E0001"]}}],
    "training_flow": [{{"step": "...", "evidence_ids": ["E0001"]}}],
    "inference_flow": [{{"step": "...", "evidence_ids": ["E0001"]}}],
    "terminology": {{"Exact Term": "required visible label"}},
    "unknowns": []
  }},
  "figure_specification": {{
    "summary": "Scientific contract for the figure.",
    "figure_goal": "...",
    "research_problem": {{"text": "...", "evidence_ids": ["E0001"]}},
    "central_claim": {{"text": "...", "evidence_ids": ["E0001"]}},
    "storyline": [],
    "must_show": [{{"text": "...", "evidence_ids": ["E0001"]}}],
    "modules": [{{"id": "...", "name": "...", "role": "...", "evidence_ids": ["E0001"]}}],
    "relations": [{{"source": "module_id", "target": "module_id", "type": "data_flow|control_flow|training_only|inference_only|comparison|feedback", "label": "", "evidence_ids": ["E0001"]}}],
    "inputs": [{{"id": "stable_input_id", "name": "exact paper term", "evidence_ids": ["E0001"]}}],
    "outputs": [{{"id": "stable_output_id", "name": "exact paper term", "evidence_ids": ["E0001"]}}],
    "innovations": [],
    "feedback_loops": [],
    "training_flow": [],
    "inference_flow": [],
    "topology": "linear|branch|feedback|multimodal|dense_multiframe|unknown",
    "required_labels": [],
    "visual_priorities": [],
    "terminology": {{}},
    "forbidden_inventions": [],
    "uncertainties": []
  }},
  "design_plan": {{
    "summary": "Information narrative for one complete image.",
    "reading_order": [],
    "groups": [],
    "innovation_emphasis": [],
    "preserve": [],
    "remove": []
  }},
  "layout_intent": {{
    "summary": "Layout intent for the image model.",
    "pattern": "left_to_right|two_stage|hub_and_spoke|loop|stacked|before_after",
    "canvas_ratio": "16:9",
    "regions": [{{"id": "...", "position": "left|center|right|top|bottom", "relative_size": "small|medium|large", "contains": []}}],
    "flow_description": "...",
    "whitespace": "..."
  }},
  "visual_metaphors": {{
    "summary": "Concrete visual objects for paper concepts.",
    "items": [{{"module_id": "...", "metaphor": "concrete visible objects", "must_show": [], "avoid_showing": []}}]
  }},
  "style_plan": {{
    "summary": "Image style contract.",
    "medium": "...",
    "palette": [],
    "viewpoint": "...",
    "line_and_shadow": "...",
    "visual_density": "...",
    "background": "...",
    "text_policy": "short exact labels only; no paragraphs, fake equations, fake axes, or invented numbers",
    "positive_reference_rules": [],
    "negative_reference_rules": []
  }}
}}

User preferences:
{json.dumps(preferences, ensure_ascii=False, indent=2)}

Universal structured paper review:
{json.dumps(paper_review or {}, ensure_ascii=False, indent=2)}

Paper evidence:
{evidence_excerpt(parsed, max_chars=evidence_max_chars)}
""".strip()


def _overview_figure_candidates(parsed: dict, limit: int = 4) -> list[dict[str, Any]]:
    positive = re.compile(r"\b(overview|framework|architecture|pipeline|procedure|approach|method|model|system|workflow)\b", re.IGNORECASE)
    negative = re.compile(r"\b(comparison|performance|result|ablation|visualization|qualitative|attention map|distribution)\b", re.IGNORECASE)
    ranked = []
    for index, item in enumerate(parsed.get("document_index", {}).get("figures", [])):
        caption = str(item.get("caption") or "").strip()
        if not caption:
            continue
        score = 0
        if positive.search(caption):
            score += 8
        if re.match(r"^(figure|fig\.)\s*[12]\b", caption, re.IGNORECASE):
            score += 5
        if 180 <= len(caption) <= 1400:
            score += 4
        score += min(5, len(re.findall(r"\b(?:uses?|takes?|feeds?|passes?|predicts?|produces?|outputs?|trains?|samples?|renders?|synthesizes?|optimizes?)\b", caption, re.IGNORECASE)))
        if negative.search(caption):
            score -= 7
        ranked.append((score, -index, item))
    return [item for _, _, item in sorted(ranked, reverse=True)[: max(1, int(limit))]]


def _fast_planner_prompt(parsed: dict, preferences: dict, evidence_max_chars: int = 36000) -> str:
    candidates = _overview_figure_candidates(parsed)
    return f"""
# Summary

You are compiling a scientific paper into a directed semantic graph for ONE framework figure. Return JSON only. Focus exclusively on scientific meaning; layout, illustration style, and image-generation wording will be compiled later by code.

Primary task:
1. Select the most information-rich method/architecture/framework figure caption from the candidates below. Figure 1 is not automatically best; prefer a caption that explicitly names components and directed operations.
2. Extract every separately named input, component, intermediate representation, conditioning signal, training-only objective, inference-only step, and output needed to reproduce that overview.
3. Use exact short paper terms as visible names. Do not replace "image encoder" with a prose description such as "network that extracts image features".
   A visible name must be copied verbatim from one of its cited evidence blocks. Preserve the paper's original language and writing system; never translate a Chinese, Japanese, Korean, or other non-English term because the user preference says English. If no concise source phrase exists, use the shortest verbatim source-language phrase. Relation labels must follow the same rule or be left blank.
4. Split compound outputs and branches into separate entities. If a component predicts class and box, create separate class and box outputs. If two encoders produce two embeddings, create both embeddings.
5. Preserve direction. Every relation endpoint must be a declared entity id. Include input boundary edges and final output edges.
6. Separate training and inference. Matching, losses, supervision, optimization, and feedback belong in training_flow or training-only entities; test-time classification, decoding, retrieval, rendering, or deployment belong in inference_flow.
7. Every factual item must cite evidence_ids copied exactly from the evidence. Unsupported details must be omitted and recorded under uncertainties.
8. Ignore baseline/comparison methods mentioned only to contrast with the proposed method. Never import terms from references, acknowledgements, bibliography, or result-only figures.

Return exactly this compact schema:
{{
  "summary": "Fast evidence-grounded semantic plan.",
  "paper_summary": {{
    "summary": "Structured paper summary.",
    "title": "...",
    "paper_type": "method|system|dataset|benchmark|analysis|survey|application|unknown",
    "research_problem": {{"text": "...", "evidence_ids": []}},
    "central_claim": {{"text": "...", "evidence_ids": []}},
    "inputs": [],
    "outputs": [],
    "core_modules": [],
    "innovations": [],
    "training_flow": [],
    "inference_flow": [],
    "terminology": {{}},
    "unknowns": []
  }},
  "figure_specification": {{
    "summary": "Scientific contract for the figure.",
    "figure_goal": "...",
    "research_problem": {{"text": "...", "evidence_ids": []}},
    "central_claim": {{"text": "...", "evidence_ids": []}},
    "storyline": [],
    "must_show": [],
    "inputs": [{{"id": "...", "name": "exact short term", "role": "input", "evidence_ids": []}}],
    "modules": [{{"id": "...", "name": "exact short term", "role": "module|intermediate|training_objective|conditioning", "evidence_ids": []}}],
    "outputs": [{{"id": "...", "name": "exact short term", "role": "output", "evidence_ids": []}}],
    "relations": [{{"source": "...", "target": "...", "type": "data_flow|encoding|conditioning|branch|alignment|prediction|training_objective|rendering_input|feedback", "label": "", "evidence_ids": []}}],
    "innovations": [],
    "feedback_loops": [],
    "training_flow": [],
    "inference_flow": [],
    "topology": "linear|branch|feedback|multimodal|dense_multiframe|unknown",
    "required_labels": [],
    "terminology": {{}},
    "forbidden_inventions": [],
    "uncertainties": []
  }}
}}

Candidate overview captions:
{json.dumps(candidates, ensure_ascii=False, indent=2)}

Extraction scope (do not claim coverage beyond this scope):
{json.dumps({key: parsed.get('extraction_report', {}).get(key) for key in ('pdf_type', 'semantic_scope', 'readable_page_ratio', 'ocr_pages', 'warnings')}, ensure_ascii=False, indent=2)}

User preferences relevant to explanatory wording only (never translate scientific labels away from the paper's source language):
{json.dumps({key: preferences.get(key) for key in ('language', 'must_show', 'must_not_show')}, ensure_ascii=False, indent=2)}

Prioritized paper evidence:
{evidence_excerpt(parsed, max_chars=evidence_max_chars)}
""".strip()


def _compile_fast_plan(raw: dict, preferences: dict) -> dict:
    result = normalize_plan(raw, preferences)
    spec = result["figure_specification"]
    entities = [
        item
        for field in ("inputs", "modules", "outputs", "innovations")
        for item in (spec.get(field, []) if isinstance(spec.get(field), list) else [])
        if isinstance(item, dict)
    ]
    entity_ids = [str(item.get("id") or "") for item in entities if str(item.get("id") or "")]
    labels = [str(item.get("name") or item.get("text") or item.get("statement") or "").strip() for item in entities]
    labels = [value for value in labels if value]
    topology = str(spec.get("topology") or "unknown")
    pattern = {"feedback": "loop", "multimodal": "hub_and_spoke", "dense_multiframe": "stacked", "branch": "two_stage"}.get(topology, "left_to_right")
    result["design_plan"] = {
        "summary": "Deterministic information narrative compiled from the fast semantic graph.",
        "reading_order": entity_ids,
        "groups": [],
        "innovation_emphasis": [str(item.get("name") or item.get("text") or item.get("statement") or "") for item in spec.get("innovations", []) if isinstance(item, dict)],
        "preserve": labels,
        "remove": list(spec.get("forbidden_inventions", []) if isinstance(spec.get("forbidden_inventions"), list) else []),
    }
    result["layout_intent"] = {
        "summary": "Deterministic layout intent compiled from semantic topology.",
        "pattern": pattern,
        "canvas_ratio": preferences.get("aspect_ratio", "16:9"),
        "regions": [],
        "flow_description": "Render all declared directed relations without reversing arrows.",
        "whitespace": "moderate",
    }
    result["visual_metaphors"] = {
        "summary": "Minimal paper-grounded visual objects; exact labels and arrows are added as an editable overlay.",
        "items": [{"module_id": str(item.get("id") or ""), "metaphor": str(item.get("name") or "scientific module"), "must_show": [], "avoid_showing": []} for item in entities],
    }
    result["style_plan"] = {
        "summary": "Fast-path style contract.",
        "medium": preferences.get("style_description"),
        "palette": preferences.get("preferred_palette", []),
        "viewpoint": "front-facing academic diagram",
        "line_and_shadow": "crisp thin lines with restrained shadows",
        "visual_density": preferences.get("visual_density", "high"),
        "background": "clean light background",
        "text_policy": "background regions only; exact labels and arrows are supplied by overlay_spec.json",
        "positive_reference_rules": [],
        "negative_reference_rules": preferences.get("avoid", []),
    }
    return result


def _first_sentence(text: str) -> str:
    sentences = [item.strip() for item in re.split(r"(?<=[.!?。！？])\s+", text) if len(item.strip()) > 20]
    return sentences[0][:500] if sentences else text[:500].strip()


def _plausible_component_heading(value: str) -> bool:
    text = re.sub(r"^\d+(?:\.\d+)*\s*", "", str(value or "")).strip()
    low = text.casefold()
    if not 3 <= len(text) <= 72 or len(text.split()) > 9:
        return False
    if any(term in low for term in ("http", "www.", "acknowledg", "reference", "appendix", "picture credit", "et al.", "university", "institute")):
        return False
    if re.search(r"[π∑=·]|\([^)]*\d{4}[^)]*\)|\b(?:fig(?:ure)?|table)\s*\d", text, re.IGNORECASE):
        return False
    if text.count(",") >= 2 or text.count(":") >= 1:
        return False
    component_terms = ("architecture", "pipeline", "framework", "module", "encoder", "decoder", "backbone", "parser", "reasoner", "renderer", "retrieval", "generation", "refinement", "training", "inference", "data engine", "model")
    return any(term in low for term in component_terms)


def _heuristic_plan(parsed: dict, preferences: dict, paper_review: dict | None = None) -> dict:
    if paper_review and paper_review.get("modules"):
        review_modules = [item for item in (list(paper_review.get("modules", [])) + list(paper_review.get("research_objects", [])) + list(paper_review.get("concepts", []))) if item.get("evidence_ids")][:16]
        modules = [{"id": str(item.get("id")), "name": str(item.get("visible_label") or item.get("statement") or item.get("id")), "role": str(item.get("visual_role") or "module"), "evidence_ids": list(item.get("evidence_ids", []))} for item in review_modules]
        relations = [{"source": str(item.get("source_id") or item.get("source") or ""), "target": str(item.get("target_id") or item.get("target") or ""), "type": str(item.get("relation_type") or item.get("type") or "data_flow"), "label": str(item.get("statement") or "")[:48], "evidence_ids": list(item.get("evidence_ids", []))} for item in paper_review.get("relations", []) if (item.get("source_id") or item.get("source")) and (item.get("target_id") or item.get("target")) and item.get("evidence_ids")]
        terminology = {str(item.get("statement")): str(item.get("visible_label") or item.get("statement")) for item in paper_review.get("terminology", []) if str(item.get("statement") or "").strip()}
        title = str(paper_review.get("paper_identity", {}).get("title") or parsed.get("source_name"))
        research_questions = paper_review.get("research_questions", [])
        claims = paper_review.get("central_claims", [])
        figure_goal = str((claims or research_questions or [{"statement": "Explain the paper method faithfully."}])[0].get("statement"))
        innovations = [item for item in paper_review.get("innovations", []) if item.get("evidence_ids")]
        forbidden = [str(item.get("statement")) for item in paper_review.get("forbidden_inventions", [])]
        inputs = [item for item in paper_review.get("inputs", []) if item.get("evidence_ids")]
        outputs = [item for item in paper_review.get("outputs", []) if item.get("evidence_ids")]
        known_modalities = ["image", "text", "audio", "depth", "thermal", "imu", "video"]
        expanded_inputs = []
        for item in inputs:
            statement = str(item.get("visible_label") or item.get("name") or item.get("statement") or "")
            present = [term for term in known_modalities if re.search(rf"\b{term}(?:s)?\b", statement, re.IGNORECASE)]
            if len(present) >= 3:
                for term in present:
                    expanded_inputs.append({"id": f"input_{term}", "name": term.upper() if term == "imu" else term.title(), "role": "input modality", "evidence_ids": list(item.get("evidence_ids", []))})
            else:
                expanded_inputs.append(item)
        inputs = expanded_inputs
        if modules:
            relation_pairs = {(item["source"], item["target"]) for item in relations}
            for item in inputs:
                input_id = str(item.get("id") or "")
                if input_id and (input_id, modules[0]["id"]) not in relation_pairs:
                    relations.append({"source": input_id, "target": modules[0]["id"], "type": "data_flow", "label": "encoding", "evidence_ids": list(item.get("evidence_ids", []))})
            if outputs and innovations:
                output_id = str(outputs[0].get("id") or "")
                innovation_id = str(innovations[0].get("id") or "")
                if output_id and innovation_id and (output_id, innovation_id) not in relation_pairs:
                    relations.append({"source": output_id, "target": innovation_id, "type": "enables", "label": "emergent alignment", "evidence_ids": list(innovations[0].get("evidence_ids", []))})
        return {
            "summary": "Paper-review-grounded fallback planning result.",
            "paper_summary": {"summary": "Structured paper summary derived from paper_review.json.", "title": title, "paper_type": paper_review.get("paper_identity", {}).get("paper_type", "unknown"), "research_problem": (research_questions or [{}])[0], "central_claim": (claims or [{}])[0], "inputs": inputs, "outputs": outputs, "core_modules": modules, "innovations": innovations, "training_flow": paper_review.get("workflows", {}).get("training", []), "inference_flow": paper_review.get("workflows", {}).get("inference", []), "terminology": terminology, "unknowns": paper_review.get("unknowns", [])},
            "figure_specification": {"summary": "Scientific contract derived from universal paper review.", "figure_goal": figure_goal, "storyline": [item["id"] for item in modules], "must_show": [{"text": item["name"], "evidence_ids": item["evidence_ids"]} for item in modules], "modules": modules, "relations": relations, "inputs": inputs, "outputs": outputs, "innovations": innovations, "visual_priorities": [item["name"] for item in modules if item["role"] in {"module", "innovation"}], "terminology": terminology, "forbidden_inventions": forbidden},
            "design_plan": {"summary": "Paper-review-grounded information narrative.", "reading_order": [item["id"] for item in modules], "groups": [], "innovation_emphasis": [item.get("statement") for item in innovations], "preserve": [item["name"] for item in modules], "remove": forbidden},
            "layout_intent": {"summary": "Layout intent awaiting template selection.", "pattern": "left_to_right", "canvas_ratio": preferences.get("aspect_ratio", "auto"), "regions": [], "flow_description": "Follow the selected reference template while preserving paper relations.", "whitespace": "reference-matched"},
            "visual_metaphors": {"summary": "Concrete visual metaphors grounded in review roles.", "items": [{"module_id": item["id"], "metaphor": f"dense academic visual scene for {item['name']}", "must_show": [item["name"]], "avoid_showing": forbidden} for item in modules]},
            "style_plan": {"summary": "Style plan will inherit the selected reference template.", "medium": preferences.get("style_description"), "palette": preferences.get("preferred_palette", []), "viewpoint": "reference-matched academic diagram", "line_and_shadow": "reference-derived", "visual_density": preferences.get("visual_density", "high"), "background": "clean light background", "text_policy": "Image2 renders only exact short labels from the whitelist.", "positive_reference_rules": [], "negative_reference_rules": preferences.get("avoid", [])},
        }
    evidence = parsed["evidence"]
    headings = parsed.get("headings", [])
    first = evidence[0]
    title = next((line.strip() for line in first["text"].splitlines() if 10 <= len(line.strip()) <= 180), parsed["source_name"])
    generic = {"abstract", "introduction", "related work", "method", "methods", "experiments", "results", "conclusion", "references"}
    names = [item for item in headings if item.lower() not in generic and _plausible_component_heading(item)][:6]
    if len(names) < 3:
        names = ["Research Input", "Core Method", "Research Output"]
    modules = []
    for index, name in enumerate(names):
        evidence_id = evidence[min(index, len(evidence) - 1)]["id"]
        modules.append({"id": f"module_{index + 1:02d}", "name": name, "role": "paper-derived stage requiring VLM verification", "evidence_ids": [evidence_id]})
    relations = [
        {"source": modules[index]["id"], "target": modules[index + 1]["id"], "type": "data_flow", "label": "", "evidence_ids": list(dict.fromkeys(modules[index]["evidence_ids"] + modules[index + 1]["evidence_ids"]))}
        for index in range(len(modules) - 1)
    ]
    central = _first_sentence(first["text"])
    return {
        "summary": "Heuristic paper-to-image planning result; scientific details require review.",
        "paper_summary": {
            "summary": "Heuristic structured paper summary.",
            "title": title,
            "paper_type": "unknown",
            "research_problem": {"text": central, "evidence_ids": [first["id"]]},
            "central_claim": {"text": "unknown", "evidence_ids": []},
            "inputs": [],
            "outputs": [],
            "core_modules": modules,
            "innovations": [],
            "training_flow": [],
            "inference_flow": [],
            "terminology": {item["name"]: item["name"] for item in modules},
            "unknowns": ["central claim", "training flow", "inference flow", "innovations"],
        },
        "figure_specification": {
            "summary": "Heuristic scientific contract for the figure.",
            "figure_goal": "Summarize the paper's main flow without inventing unsupported details.",
            "storyline": [item["name"] for item in modules],
            "must_show": [{"text": item["name"], "evidence_ids": item["evidence_ids"]} for item in modules],
            "modules": modules,
            "relations": relations,
            "inputs": [],
            "outputs": [],
            "innovations": [],
            "visual_priorities": [item["name"] for item in modules],
            "terminology": {item["name"]: item["name"] for item in modules},
            "forbidden_inventions": ["unsupported external knowledge base", "unsupported reinforcement learning", "unsupported agent or memory module"],
        },
        "design_plan": {
            "summary": "Heuristic left-to-right information narrative.",
            "reading_order": [item["id"] for item in modules],
            "groups": [],
            "innovation_emphasis": [],
            "preserve": [item["name"] for item in modules],
            "remove": ["unsupported generic AI decorations"],
        },
        "layout_intent": {
            "summary": "Heuristic layout intent.",
            "pattern": preferences.get("preferred_flow") or "left_to_right",
            "canvas_ratio": preferences.get("aspect_ratio", "16:9"),
            "regions": [{"id": item["id"], "position": "left" if index == 0 else "right" if index == len(modules) - 1 else "center", "relative_size": "medium", "contains": [item["id"]]} for index, item in enumerate(modules)],
            "flow_description": "A clear left-to-right scientific pipeline.",
            "whitespace": "moderate",
        },
        "visual_metaphors": {
            "summary": "Concrete fallback visual metaphors.",
            "items": [{"module_id": item["id"], "metaphor": f"dense academic mini-scene representing {item['name']}", "must_show": ["paper-specific structure", "visible process cue"], "avoid_showing": ["generic robot", "fake chart"]} for item in modules],
        },
        "style_plan": {
            "summary": "Style plan compiled from user preferences.",
            "medium": preferences.get("style_description"),
            "palette": preferences.get("preferred_palette", []),
            "viewpoint": "front-facing academic diagram",
            "line_and_shadow": "crisp thin lines with restrained soft shadows",
            "visual_density": preferences.get("visual_density", "high"),
            "background": "clean light background",
            "text_policy": "short exact labels only; no paragraphs, fake equations, fake axes, or invented numbers",
            "positive_reference_rules": [],
            "negative_reference_rules": preferences.get("avoid", []),
        },
    }


def build_review_grounded_plan(parsed: dict, preferences: dict, paper_review: dict) -> dict:
    """Compile a deterministic figure plan from an evidence-validated paper review."""
    return normalize_plan(_heuristic_plan(parsed, preferences, paper_review=paper_review), preferences)


def _ensure_summary(value: Any, fallback: str) -> dict:
    data = value if isinstance(value, dict) else {}
    data.setdefault("summary", fallback)
    return data


def normalize_plan(raw: dict, preferences: dict) -> dict:
    result = raw if isinstance(raw, dict) else {}
    result.setdefault("summary", "Paper-to-image planning result.")
    result["paper_summary"] = _ensure_summary(result.get("paper_summary"), "Structured paper summary.")
    result["figure_specification"] = _ensure_summary(result.get("figure_specification"), "Scientific contract for the figure.")
    result["design_plan"] = _ensure_summary(result.get("design_plan"), "Information narrative for the figure.")
    result["layout_intent"] = _ensure_summary(result.get("layout_intent"), "Layout intent for the image model.")
    result["visual_metaphors"] = _ensure_summary(result.get("visual_metaphors"), "Concrete visual metaphors.")
    result["style_plan"] = _ensure_summary(result.get("style_plan"), "Image style contract.")
    result["layout_intent"].setdefault("canvas_ratio", preferences.get("aspect_ratio", "16:9"))
    return result


def plan_fast_paper_contract(
    parsed: dict,
    preferences: dict,
    mode: str = "vlm",
    model: str | None = None,
    timeout_seconds: int = 45,
    retries: int = 2,
    evidence_max_chars: int = 36000,
    deadline_at: float | None = None,
) -> tuple[dict, dict]:
    prompt = _fast_planner_prompt(parsed, preferences, evidence_max_chars=evidence_max_chars)
    metadata: dict[str, Any] = {"requested_mode": mode, "mode": mode, "model": None, "warning": None, "prompt": prompt, "provider": {}}
    if mode == "vlm" and vlm_credentials_available():
        resolved = resolve_vlm_model("RFS_FAST_FRAMEWORK_MODEL", "RFS_PAPER_TO_IMAGE_MODEL", "RFS_PAPER_PLANNER_MODEL", explicit_model=model)
        try:
            raw = call_vlm_json(
                prompt,
                [],
                model=resolved,
                timeout=max(10, int(timeout_seconds)),
                retries=max(0, int(retries)),
                call_metadata=metadata["provider"],
                deadline_at=deadline_at,
            )
            metadata["model"] = resolved
            return _compile_fast_plan(raw, preferences), metadata
        except Exception as exc:
            metadata.update({"mode": "heuristic_after_vlm_failure", "warning": str(exc), "model": resolved})
    elif mode == "vlm":
        metadata.update({"mode": "heuristic_without_credentials", "warning": "API_BASE and API_KEY/GEMINI_API_KEY are required for VLM planning"})
    return normalize_plan(_heuristic_plan(parsed, preferences), preferences), metadata


def plan_paper_image(parsed: dict, preferences: dict, mode: str = "vlm", model: str | None = None, reference_images: list[str] | None = None, paper_review: dict | None = None, timeout_seconds: int = 240, retries: int = 1, evidence_max_chars: int = 58000, deadline_at: float | None = None) -> tuple[dict, dict]:
    prompt = _planner_prompt(parsed, preferences, paper_review=paper_review, evidence_max_chars=evidence_max_chars)
    metadata = {"requested_mode": mode, "mode": mode, "model": None, "warning": None, "prompt": prompt, "provider": {}}
    if mode == "vlm" and vlm_credentials_available():
        resolved = resolve_vlm_model("RFS_PAPER_TO_IMAGE_MODEL", "RFS_PAPER_PLANNER_MODEL", explicit_model=model)
        try:
            raw = call_vlm_json(prompt, reference_images or [], model=resolved, timeout=max(10, int(timeout_seconds)), retries=max(0, int(retries)), call_metadata=metadata["provider"], deadline_at=deadline_at)
            metadata["model"] = resolved
            return normalize_plan(raw, preferences), metadata
        except Exception as exc:
            metadata.update({"mode": "heuristic_after_vlm_failure", "warning": str(exc), "model": resolved})
    elif mode == "vlm":
        metadata.update({"mode": "heuristic_without_credentials", "warning": "API_BASE and API_KEY/GEMINI_API_KEY are required for VLM planning"})
    return normalize_plan(_heuristic_plan(parsed, preferences, paper_review=paper_review), preferences), metadata


def collect_visible_labels(spec: dict, limit: int = 24) -> list[str]:
    labels: list[str] = []
    normalized_labels: set[str] = set()

    def add(value: object) -> None:
        if isinstance(value, dict):
            value = value.get("visible_label") or value.get("name") or value.get("text") or value.get("statement")
        label = str(value or "").strip()
        normalized = re.sub(r"[^\w\u4e00-\u9fff]+", "", label.casefold())
        if label and len(label) <= 64 and normalized and normalized not in normalized_labels:
            labels.append(label)
            normalized_labels.add(normalized)

    for item in spec.get("required_labels", []) if isinstance(spec.get("required_labels"), list) else []:
        add(item)
    terminology = spec.get("terminology", {})
    if isinstance(terminology, dict):
        for value in terminology.values():
            add(value)
    elif isinstance(terminology, list):
        for item in terminology:
            add(item)
    for field in ("inputs", "modules", "outputs"):
        for item in spec.get(field, []) if isinstance(spec.get(field), list) else []:
            add(item)
    for relation in spec.get("relations", []) if isinstance(spec.get("relations"), list) else []:
        if isinstance(relation, dict):
            add(relation.get("label"))
    return labels[: max(1, int(limit))]


def collect_visual_relations(spec: dict) -> list[dict[str, str]]:
    entities = {
        str(item.get("id")): str(item.get("visible_label") or item.get("name") or item.get("text") or item.get("statement") or item.get("id"))
        for field in ("inputs", "modules", "outputs", "innovations")
        for item in (spec.get(field, []) if isinstance(spec.get(field), list) else [])
        if isinstance(item, dict) and item.get("id")
    }
    repeatable = {re.sub(r"[^\w\u4e00-\u9fff]+", "", str(value).casefold()) for value in spec.get("repeatable_labels", []) if str(value).strip()} if isinstance(spec.get("repeatable_labels"), list) else set()
    shared_ids = {
        item_id for item_id, label in entities.items()
        if re.sub(r"[^\w\u4e00-\u9fff]+", "", label.casefold()) in repeatable
    }
    grouped: dict[tuple[str, str], dict[str, object]] = {}
    for relation in spec.get("relations", []) if isinstance(spec.get("relations"), list) else []:
        if not isinstance(relation, dict):
            continue
        source, target = str(relation.get("source") or ""), str(relation.get("target") or "")
        if not source or not target or source == target or source in shared_ids or target in shared_ids:
            continue
        entry = grouped.setdefault((source, target), {"types": [], "labels": []})
        relation_type = str(relation.get("type") or "data_flow")
        if relation_type not in entry["types"]:
            entry["types"].append(relation_type)
        label = str(relation.get("label") or "").strip()
        if label and label not in entry["labels"]:
            entry["labels"].append(label)
    priority = ("feedback_loop", "evaluation", "revision_input", "feedback", "conditioning", "data_flow", "prediction", "generation_input")
    result: list[dict[str, str]] = []
    for (source, target), entry in grouped.items():
        types = list(entry["types"])
        relation_type = next((value for value in priority if value in types), types[0] if types else "data_flow")
        result.append({
            "source": source,
            "source_label": entities.get(source, source),
            "target": target,
            "target_label": entities.get(target, target),
            "type": relation_type,
            "label": str(entry["labels"][0]) if entry["labels"] else "",
        })
    return result


def _topology_specific_prompt_rules(spec: dict) -> str:
    topology = str(spec.get("topology") or "unknown")
    normalized_labels = {
        re.sub(r"[^\w\u4e00-\u9fff]+", "", str(item.get("name") or item.get("label") or item.get("title") or "").casefold())
        for field in ("inputs", "modules", "outputs", "innovations")
        for item in (spec.get(field, []) if isinstance(spec.get(field), list) else [])
        if isinstance(item, dict)
    }
    feedback_signature = {
        "inputx", "generate", "initialoutput", "feedback", "selffeedback", "refine", "refinedoutput", "modelm",
    }
    dense_signature = {
        "promptablesegmentationtask", "segmentanythingmodel", "dataengine", "image", "prompt",
        "imageencoder", "promptencoder", "maskdecoder", "validsegmentationmask",
        "assistedmanual", "semiautomatic", "fullyautomatic", "sa1b",
    }
    if topology == "feedback" and feedback_signature.issubset(normalized_labels):
        return """Feedback-loop topology hard rules:
- Keep one top-row forward chain: input x -> Generate -> Initial Output -> FEEDBACK.
- Initial Output must have exactly two distinct outgoing arrows: one to FEEDBACK and one directly to REFINE.
- FEEDBACK must produce Self-Feedback, and Self-Feedback must have its own distinct outgoing arrow into REFINE.
- REFINE must therefore receive exactly two visually separate incoming arrows: Initial Output -> REFINE and Self-Feedback -> REFINE. Do not merge them upstream and do not redirect either arrow to the other source node.
- The connector labeled iterate must start at Refined output and terminate only at FEEDBACK. Its arrowhead must visibly touch the FEEDBACK boundary.
- Model M is a reusable badge inside Generate, FEEDBACK, and/or REFINE; it is not a separate flow node and must not receive extra arrows.
- Forbidden connectors: Initial Output -> Self-Feedback; Refined output -> Generate; REFINE -> Self-Feedback; Self-Feedback -> FEEDBACK; FEEDBACK -> REFINE as a shortcut that omits the visible Self-Feedback node.
- Preserve the supplied blueprint's two-row geometry and right-side return loop. Do not rearrange the loop into a different circular or bottom-return layout."""
    if topology == "feedback":
        return """Feedback-loop topology hard rules:
- Follow only the declared nodes and directed relations in the scientific contract.
- Keep the forward path and return path visually separate, with the return arrowhead touching its declared target.
- Preserve every declared intermediate feedback artifact; do not shortcut across it.
- If two declared sources enter one refinement node, draw two visibly distinct incoming arrows.
- Do not introduce Self-Refine-specific labels, shared-model badges, or connector names unless they are present in the contract."""
    if topology == "dense_multiframe" and dense_signature.issubset(normalized_labels):
        return """Dense multi-frame topology hard rules:
- Preserve exactly three macro panels: Promptable Segmentation Task, Segment Anything Model, and Data Engine.
- Image must connect only to Image Encoder; Prompt must connect only to Prompt Encoder.
- Image Encoder and Prompt Encoder must each have a separate directed arrow into Mask Decoder. Do not chain one encoder through the other.
- Mask Decoder must connect directly to Valid Segmentation Mask inside the model panel.
- Data Engine must be a separate vertical chain: Assisted-manual -> Semi-automatic -> Fully Automatic -> SA-1B.
- Draw the Segment Anything Model -> Data Engine annotation-support relation as a distinct high-level container-to-container arrow, visually separate from the mask-prediction path.
- Forbidden connectors: Prompt -> Image Encoder; Image -> Prompt Encoder; Image Encoder -> Prompt Encoder; Prompt Encoder -> Image Encoder; Fully Automatic -> Valid Segmentation Mask; Mask Decoder -> Data Engine as a replacement for the required container-level support arrow.
- Do not let any Data Engine stage enter Valid Segmentation Mask, and do not let the model inference path enter SA-1B."""
    if topology == "dense_multiframe":
        return """Dense multi-frame topology hard rules:
- Preserve the declared macro-panel grouping and every directed cross-panel relation.
- Keep independent input branches separate until their declared convergence node.
- Keep panel-local output paths separate from dataset, training, or data-engine paths.
- Draw high-level container-to-container relations separately from internal module arrows.
- Do not introduce SAM-specific encoders, masks, data-engine stages, or dataset labels unless they are present in the contract."""
    return "No additional topology-specific rules. Follow the directed connector checklist exactly."


def compile_image_prompt(plan: dict, preferences: dict, candidate_variant: int = 1, selected_template: dict | None = None) -> str:
    spec = plan["figure_specification"]
    design = plan["design_plan"]
    layout = plan["layout_intent"]
    metaphors = plan["visual_metaphors"]
    style = plan["style_plan"]
    template = selected_template or {}
    semantic_plan = template.get("semantic_plan", {}) if isinstance(template.get("semantic_plan"), dict) else {}
    labels = collect_visible_labels(spec)
    repeatable_labels = [str(value).strip() for value in spec.get("repeatable_labels", []) if str(value).strip()] if isinstance(spec.get("repeatable_labels"), list) else []
    repeatable_normalized = {re.sub(r"[^\w\u4e00-\u9fff]+", "", value.casefold()) for value in repeatable_labels}
    numbered_labels = "\n".join(
        f"{index}. {label}" + (" (may repeat to show evidence-supported component reuse)" if re.sub(r"[^\w\u4e00-\u9fff]+", "", label.casefold()) in repeatable_normalized else "")
        for index, label in enumerate(labels, start=1)
    )
    visual_relations = collect_visual_relations(spec)
    connector_checklist = "\n".join(
        f"{index}. {item['source_label']} -> {item['target_label']} [{item['type']}]" + (f" label: {item['label']}" if item["label"] else "")
        for index, item in enumerate(visual_relations, start=1)
    )
    topology_specific_rules = _topology_specific_prompt_rules(spec)
    return f"""
# Summary

Create one complete publication-quality scientific framework figure as a raster image.

Candidate variant: {candidate_variant}.
Scientific goal: {spec.get('figure_goal')}.
Target canvas ratio: {preferences.get('aspect_ratio', '16:9')}.
Text language: {preferences.get('language', 'English')}.

Scientific contract:
{json.dumps(spec, ensure_ascii=False, indent=2)}

Information narrative:
{json.dumps(design, ensure_ascii=False, indent=2)}

Layout intent:
{json.dumps(layout, ensure_ascii=False, indent=2)}

Concrete visual metaphors:
{json.dumps(metaphors, ensure_ascii=False, indent=2)}

Style contract:
{json.dumps(style, ensure_ascii=False, indent=2)}

Reference-derived content-free template contract:
{json.dumps({key: template.get(key) for key in ['template_id', 'panels', 'connectors', 'visual_density', 'style', 'selection']}, ensure_ascii=False, indent=2)}

Paper-grounded semantic blueprint geometry:
{json.dumps(semantic_plan if semantic_plan.get('applied') else {"applied": False}, ensure_ascii=False, indent=2)}

Exact visible label whitelist (render these exactly and do not invent alternatives):
{json.dumps(labels, ensure_ascii=False)}

Mandatory visible label checklist:
{numbered_labels}

Every checklist item must appear at least once as clearly readable text in the completed figure. Labels explicitly marked as repeatable may appear more than once only to show reuse of the same paper-supported component; every other label must appear exactly once. An icon, symbol, equation variable, or unlabeled output card does not satisfy a checklist item. Reserve enough width for long labels and place each output label beside or inside its output node.

Mandatory directed connector checklist:
{connector_checklist}

Every connector above must be visible with the stated direction. Do not bypass an intermediate module, do not replace two required inputs with one shortcut arrow, and do not add direct source-to-output paths that are absent from this checklist. Shared component labels may repeat as visual badges without adding extra implementation-level arrows.

Topology-specific rendering rules:
{topology_specific_rules}

Forbidden copied reference terms:
{json.dumps(template.get('forbidden_copy_terms', []), ensure_ascii=False)}

Hard requirements:
- Preserve every paper-supported core module and relation.
- Use the exact short labels listed in terminology when labels are necessary.
- Make arrows unambiguous and follow the specified source-to-target direction.
- Emphasize the paper's actual innovation rather than generic AI decoration.
- Use a clean academic composition with dense but readable information hierarchy.
- Keep all major objects complete and inside the canvas; avoid large blank margins.
- Do not invent datasets, mechanisms, formulas, metrics, modules, or results.
- Do not render paragraphs, citations, fake equations, fake axes, fake charts, or invented numbers.
- Avoid commercial-poster styling, cyberpunk effects, unrelated robots, generic brains, and repeated dashboard cards.
- Treat the supplied blueprint as a hard macro-layout guide, but replace all reference content with this paper's content.
- When semantic blueprint geometry is supplied, preserve every node bounding box, layer assignment, connector path, and arrow direction; visual decoration may change but graph geometry may not.
- Template panels are macro spatial regions, not an exact limit on the number of scientific content nodes inside those regions.
- Every visible scientific word must come from the exact label whitelist; do not paraphrase labels.
- Render every mandatory visible label at least once; repeat only labels explicitly marked as evidence-supported shared components, and never replace an output label with an icon-only node.
- Keep separately named scientific components as separately editable nodes; do not collapse special tokens, embeddings, heads, inputs, or outputs into composite labels.
- Include explicit input-boundary and output-boundary connectors.
""".strip()


def validate_plan_grounding(plan: dict, parsed: dict) -> dict:
    evidence_items = [item for item in parsed.get("evidence", []) if isinstance(item, dict) and item.get("id")]
    valid_evidence = {item["id"] for item in evidence_items}
    evidence_text = {str(item["id"]): str(item.get("text") or "") for item in evidence_items}
    all_evidence_text = " ".join(evidence_text.values())
    errors: list[str] = []
    warnings: list[str] = []
    spec = plan.get("figure_specification", {})

    def normalized_term(value: str) -> str:
        return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", value).casefold()).strip()

    def script_counts(value: str) -> tuple[int, int]:
        cjk = sum(
            "\u3400" <= char <= "\u9fff"
            or "\u3040" <= char <= "\u30ff"
            or "\uac00" <= char <= "\ud7af"
            for char in value
        )
        latin = sum(("a" <= char.casefold() <= "z") for char in value)
        return cjk, latin

    def latin_language(value: str) -> str | None:
        folded = "".join(char for char in unicodedata.normalize("NFKD", value.casefold()) if not unicodedata.combining(char))
        words = re.findall(r"[a-z]{2,}", folded)
        profiles = {
            "english": {"the", "and", "that", "with", "from", "this", "we", "our", "for", "into", "method", "results"},
            "spanish": {"el", "la", "los", "las", "un", "una", "que", "con", "para", "por", "del", "este", "esta", "metodo", "resultados", "relaciones"},
            "french": {"le", "la", "les", "un", "une", "des", "que", "avec", "pour", "dans", "cette", "methode", "resultats", "relations"},
            "german": {"der", "die", "das", "den", "dem", "ein", "eine", "und", "mit", "fur", "von", "diese", "methode", "ergebnisse"},
            "portuguese": {"o", "os", "as", "um", "uma", "que", "com", "para", "por", "este", "esta", "metodo", "resultados", "relacoes"},
        }
        scores = {name: sum(word in markers for word in words) for name, markers in profiles.items()}
        language, score = max(scores.items(), key=lambda item: item[1])
        if language == "english" or score < 5 or score < scores["english"] + 2:
            return None
        return language

    detected_latin_language = latin_language(all_evidence_text)

    def english_label_ratio(value: str) -> float | None:
        tokens = re.findall(r"[A-Za-z]{3,}", value)
        if not tokens:
            return None
        try:
            import wordninja

            known_words = wordninja.DEFAULT_LANGUAGE_MODEL._wordcost
        except Exception:
            return None
        known = sum(token.casefold() in known_words or token.casefold() in {"encoder", "decoder", "embedding", "transformer"} for token in tokens)
        return known / len(tokens)

    def validate_visible_label(location: str, label: str, evidence_ids: list[str], *, fallback_text: str = "") -> None:
        value = str(label or "").strip()
        if not value:
            return
        source = " ".join(evidence_text.get(str(evidence_id), "") for evidence_id in evidence_ids).strip() or fallback_text
        if not source or normalized_term(value) in normalized_term(source):
            return
        label_cjk, label_latin = script_counts(value)
        source_cjk, source_latin = script_counts(source)
        changed_from_cjk = source_cjk >= 2 and label_cjk == 0 and label_latin >= 2
        changed_from_latin = source_latin >= 4 and source_cjk == 0 and label_cjk >= 2 and label_latin == 0
        if changed_from_cjk or changed_from_latin:
            errors.append(f"{location} visible label changes the source writing system and is not verbatim evidence: {value}")
            return
        if detected_latin_language and normalized_term(value) not in normalized_term(all_evidence_text):
            ratio = english_label_ratio(value)
            if ratio is not None and ratio >= 0.8:
                errors.append(f"{location} visible label appears translated from {detected_latin_language} and is not verbatim evidence: {value}")

    modules = spec.get("modules") if isinstance(spec.get("modules"), list) else []
    if not modules:
        errors.append("figure_specification.modules is empty")
    module_ids: set[str] = set()
    for index, module in enumerate(modules):
        if not isinstance(module, dict):
            errors.append(f"module {index + 1} is not an object")
            continue
        module_id = str(module.get("id") or "").strip()
        if not module_id:
            errors.append(f"module {index + 1} has no id")
        elif module_id in module_ids:
            errors.append(f"duplicate module id: {module_id}")
        else:
            module_ids.add(module_id)
        evidence_ids = module.get("evidence_ids") if isinstance(module.get("evidence_ids"), list) else []
        if not evidence_ids:
            errors.append(f"module {module_id or index + 1} has no evidence_ids")
        invalid = [item for item in evidence_ids if item not in valid_evidence]
        if invalid:
            errors.append(f"module {module_id or index + 1} references unknown evidence ids: {invalid}")
        validate_visible_label(f"module {module_id or index + 1}", str(module.get("name") or module.get("visible_label") or ""), evidence_ids)

    endpoint_ids = set(module_ids)
    for field in ("inputs", "outputs", "innovations"):
        for index, item in enumerate(spec.get(field) if isinstance(spec.get(field), list) else []):
            if not isinstance(item, dict):
                continue
            endpoint_id = str(item.get("id") or item.get("name") or item.get("visible_label") or item.get("text") or "").strip()
            if endpoint_id:
                endpoint_ids.add(endpoint_id)
            evidence_ids = item.get("evidence_ids") if isinstance(item.get("evidence_ids"), list) else []
            if not evidence_ids:
                errors.append(f"{field}[{index}] has no evidence_ids")
            invalid = [value for value in evidence_ids if value not in valid_evidence]
            if invalid:
                errors.append(f"{field}[{index}] references unknown evidence ids: {invalid}")
            validate_visible_label(f"{field}[{index}]", str(item.get("name") or item.get("visible_label") or item.get("text") or ""), evidence_ids)

    relations = spec.get("relations") if isinstance(spec.get("relations"), list) else []
    for index, relation in enumerate(relations):
        if not isinstance(relation, dict):
            errors.append(f"relation {index + 1} is not an object")
            continue
        source = str(relation.get("source") or "").strip()
        target = str(relation.get("target") or "").strip()
        if source not in endpoint_ids or target not in endpoint_ids:
            errors.append(f"relation {index + 1} has unknown endpoint: {source} -> {target}")
        evidence_ids = relation.get("evidence_ids") if isinstance(relation.get("evidence_ids"), list) else []
        if not evidence_ids:
            errors.append(f"relation {source} -> {target} has no evidence_ids")
        invalid = [item for item in evidence_ids if item not in valid_evidence]
        if invalid:
            errors.append(f"relation {source} -> {target} references unknown evidence ids: {invalid}")
        validate_visible_label(f"relation {source} -> {target}", str(relation.get("label") or ""), evidence_ids)

    terminology = spec.get("terminology") if isinstance(spec.get("terminology"), dict) else {}
    for source_term, visible_label in terminology.items():
        validate_visible_label(f"terminology[{source_term}]", str(visible_label or ""), [], fallback_text=all_evidence_text)

    for field in ("must_show", "innovations"):
        items = spec.get(field) if isinstance(spec.get(field), list) else []
        for index, item in enumerate(items):
            if not isinstance(item, dict):
                continue
            evidence_ids = item.get("evidence_ids") if isinstance(item.get("evidence_ids"), list) else []
            invalid = [value for value in evidence_ids if value not in valid_evidence]
            if invalid:
                errors.append(f"{field}[{index}] references unknown evidence ids: {invalid}")

    for field in ("research_problem", "central_claim"):
        item = spec.get(field)
        if not isinstance(item, dict):
            errors.append(f"figure_specification.{field} is missing")
            continue
        text = str(item.get("text") or item.get("statement") or "").strip()
        evidence_ids = item.get("evidence_ids") if isinstance(item.get("evidence_ids"), list) else []
        explicitly_unknown = item.get("status") == "unknown" or text.casefold() == "unknown" or "require" in text.casefold() and "review" in text.casefold()
        if not explicitly_unknown and not evidence_ids:
            errors.append(f"figure_specification.{field} has no evidence_ids")
        invalid = [value for value in evidence_ids if value not in valid_evidence]
        if invalid:
            errors.append(f"figure_specification.{field} references unknown evidence ids: {invalid}")

    return {
        "summary": "Scientific grounding and relation-contract validation.",
        "ok": not errors,
        "module_count": len(modules),
        "relation_count": len(relations),
        "evidence_count": len(valid_evidence),
        "errors": errors,
        "warnings": warnings,
        "detected_source_language": detected_latin_language or "unknown_or_english",
    }
