from __future__ import annotations

from collections import defaultdict, deque
from typing import Any


_SUPPORTED_TOPOLOGIES = {"linear", "branch", "multimodal", "feedback", "dense_multiframe"}
_FEEDBACK_TYPES = {"feedback_loop", "iteration", "iterate", "return_flow"}


def _label(item: dict[str, Any]) -> str:
    return str(item.get("name") or item.get("label") or item.get("title") or "").strip()


def _normalized(value: Any) -> str:
    return "".join(char for char in str(value or "").casefold() if char.isalnum())


def _visible_entities(specification: dict[str, Any]) -> list[dict[str, Any]]:
    required = {
        _normalized(value)
        for value in specification.get("required_labels", [])
        if str(value).strip()
    }
    entities: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    seen_labels: set[str] = set()
    for field in ("inputs", "modules", "outputs", "innovations"):
        values = specification.get(field, [])
        if not isinstance(values, list):
            continue
        for index, item in enumerate(values):
            if not isinstance(item, dict):
                continue
            label = _label(item)
            entity_id = str(item.get("id") or f"{field}_{index + 1}").strip()
            normalized_label = _normalized(label)
            if not label or not entity_id or entity_id in seen_ids or normalized_label in seen_labels:
                continue
            if required and normalized_label not in required:
                continue
            seen_ids.add(entity_id)
            seen_labels.add(normalized_label)
            entities.append({
                "id": entity_id,
                "label": label,
                "field": field,
                "role": str(item.get("role") or "").strip(),
                "order": len(entities),
            })
    return entities


def _visible_relations(specification: dict[str, Any], node_ids: set[str]) -> list[dict[str, str]]:
    relations: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    values = specification.get("relations", [])
    if not isinstance(values, list):
        return relations
    type_priority = {
        "feedback_loop": 0,
        "branch": 1,
        "conditioning": 2,
        "feature_flow": 3,
        "data_flow": 4,
    }
    candidates: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for item in values:
        if not isinstance(item, dict):
            continue
        source = str(item.get("source") or "").strip()
        target = str(item.get("target") or "").strip()
        if not source or not target or source == target or source not in node_ids or target not in node_ids:
            continue
        candidates[(source, target)].append({
            "source": source,
            "target": target,
            "type": str(item.get("type") or "data_flow").strip(),
            "label": str(item.get("label") or "").strip(),
        })
    for pair, items in candidates.items():
        if pair in seen:
            continue
        selected = sorted(items, key=lambda item: type_priority.get(item["type"], 9))[0]
        labels = [item["label"] for item in items if item["label"]]
        if labels:
            selected["label"] = labels[0]
        relations.append(selected)
        seen.add(pair)
    return relations


def _rank_nodes(nodes: list[dict[str, Any]], relations: list[dict[str, str]]) -> dict[str, int]:
    node_ids = [item["id"] for item in nodes]
    incoming: dict[str, set[str]] = {node_id: set() for node_id in node_ids}
    outgoing: dict[str, set[str]] = {node_id: set() for node_id in node_ids}
    forward_relations = [
        item for item in relations
        if item["type"] not in _FEEDBACK_TYPES
    ]
    for item in forward_relations:
        incoming[item["target"]].add(item["source"])
        outgoing[item["source"]].add(item["target"])

    indegree = {node_id: len(incoming[node_id]) for node_id in node_ids}
    order_lookup = {item["id"]: item["order"] for item in nodes}
    queue = deque(sorted((node_id for node_id in node_ids if indegree[node_id] == 0), key=order_lookup.get))
    ranks = {node_id: 0 for node_id in node_ids}
    visited: set[str] = set()
    while queue:
        source = queue.popleft()
        visited.add(source)
        for target in sorted(outgoing[source], key=order_lookup.get):
            ranks[target] = max(ranks[target], ranks[source] + 1)
            indegree[target] -= 1
            if indegree[target] == 0:
                queue.append(target)

    if len(visited) != len(node_ids):
        for _ in range(len(node_ids)):
            changed = False
            for item in forward_relations:
                candidate = min(len(node_ids) - 1, ranks[item["source"]] + 1)
                if candidate > ranks[item["target"]]:
                    ranks[item["target"]] = candidate
                    changed = True
            if not changed:
                break

    input_ids = {item["id"] for item in nodes if item["field"] == "inputs"}
    for node_id in input_ids:
        if not incoming[node_id]:
            ranks[node_id] = 0
    relations_by_source: dict[str, list[dict[str, str]]] = defaultdict(list)
    for relation in forward_relations:
        relations_by_source[relation["source"]].append(relation)
    for node in nodes:
        node_id = node["id"]
        outgoing_relations = relations_by_source.get(node_id, [])
        if incoming[node_id] or not outgoing_relations:
            continue
        if all(str(item.get("type") or "").casefold() == "conditioning" for item in outgoing_relations):
            target_rank = min(ranks[item["target"]] for item in outgoing_relations)
            ranks[node_id] = max(0, target_rank - 1)
    return ranks


def _layout_nodes(nodes: list[dict[str, Any]], ranks: dict[str, int]) -> list[dict[str, Any]]:
    layers: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for item in nodes:
        layers[ranks[item["id"]]].append(item)
    compact_ranks = {rank: index for index, rank in enumerate(sorted(layers))}
    layer_count = max(1, len(compact_ranks))
    node_width = min(0.16, max(0.115, 0.72 / layer_count))
    x_start, x_end = 0.07, 0.93
    positioned: list[dict[str, Any]] = []
    for original_rank in sorted(layers):
        layer_index = compact_ranks[original_rank]
        items = sorted(layers[original_rank], key=lambda item: (item["field"] == "innovations", item["field"] == "outputs", item["order"]))
        count = len(items)
        center_x = (x_start + x_end) / 2 if layer_count == 1 else x_start + layer_index * (x_end - x_start) / (layer_count - 1)
        node_height = min(0.16, max(0.075, 0.66 / max(count, 1)))
        if count == 1:
            centers_y = [0.50]
        else:
            y_start, y_end = 0.15, 0.85
            centers_y = [y_start + index * (y_end - y_start) / (count - 1) for index in range(count)]
        for item, center_y in zip(items, centers_y):
            x = max(0.015, min(0.985 - node_width, center_x - node_width / 2))
            positioned.append({
                **item,
                "rank": layer_index,
                "bbox_percent": {
                    "x": round(x, 6),
                    "y": round(max(0.06, center_y - node_height / 2), 6),
                    "w": round(node_width, 6),
                    "h": round(node_height, 6),
                },
            })
    return positioned


def _connector_path(
    source: dict[str, Any],
    target: dict[str, Any],
    relation_type: str,
    source_port_fraction: float = 0.5,
    target_port_fraction: float = 0.5,
) -> tuple[list[list[float]], str]:
    source_box = source["bbox_percent"]
    target_box = target["bbox_percent"]
    source_center = (source_box["x"] + source_box["w"] / 2, source_box["y"] + source_box["h"] / 2)
    target_center = (target_box["x"] + target_box["w"] / 2, target_box["y"] + target_box["h"] / 2)
    is_return = relation_type in _FEEDBACK_TYPES or target["rank"] <= source["rank"]
    if is_return:
        route_y = 0.95 if source_center[1] >= 0.42 or target_center[1] >= 0.42 else 0.05
        source_anchor_y = source_box["y"] + source_box["h"] if route_y > 0.5 else source_box["y"]
        target_anchor_y = target_box["y"] + target_box["h"] if route_y > 0.5 else target_box["y"]
        return ([
            [round(source_center[0], 6), round(source_anchor_y, 6)],
            [round(source_center[0], 6), route_y],
            [round(target_center[0], 6), route_y],
            [round(target_center[0], 6), round(target_anchor_y, 6)],
        ], "outer_feedback")
    if source["rank"] == target["rank"]:
        if source_center[1] <= target_center[1]:
            start = [source_center[0], source_box["y"] + source_box["h"]]
            end = [target_center[0], target_box["y"]]
        else:
            start = [source_center[0], source_box["y"]]
            end = [target_center[0], target_box["y"] + target_box["h"]]
        return ([[round(value, 6) for value in start], [round(value, 6) for value in end]], "vertical")
    start = [source_box["x"] + source_box["w"], source_box["y"] + source_port_fraction * source_box["h"]]
    end = [target_box["x"], target_box["y"] + target_port_fraction * target_box["h"]]
    if target["rank"] - source["rank"] > 1:
        lane_y = max(0.035, min(0.965, min(source_box["y"], target_box["y"]) - 0.045))
        if lane_y < 0.055:
            lane_y = min(0.965, max(source_box["y"] + source_box["h"], target_box["y"] + target_box["h"]) + 0.045)
        return ([
            [round(value, 6) for value in start],
            [round(start[0] + 0.025, 6), round(start[1], 6)],
            [round(start[0] + 0.025, 6), round(lane_y, 6)],
            [round(end[0] - 0.025, 6), round(lane_y, 6)],
            [round(end[0] - 0.025, 6), round(end[1], 6)],
            [round(value, 6) for value in end],
        ], "bypass_orthogonal")
    if abs(start[1] - end[1]) < 0.025:
        return ([[round(value, 6) for value in start], [round(value, 6) for value in end]], "straight")
    lane_fraction = 0.20 + 0.60 * (0.65 * target_port_fraction + 0.35 * source_port_fraction)
    mid_x = start[0] + (end[0] - start[0]) * lane_fraction
    return ([
        [round(value, 6) for value in start],
        [round(mid_x, 6), round(start[1], 6)],
        [round(mid_x, 6), round(end[1], 6)],
        [round(value, 6) for value in end],
    ], "orthogonal")


def compile_semantic_blueprint(
    specification: dict[str, Any] | None,
    *,
    max_nodes: int = 16,
) -> dict[str, Any]:
    specification = specification if isinstance(specification, dict) else {}
    topology = str(specification.get("topology") or "unknown")
    nodes = _visible_entities(specification)
    if topology not in _SUPPORTED_TOPOLOGIES:
        return {"summary": "Generic semantic blueprint not applicable to this topology.", "applied": False, "topology": topology, "nodes": [], "connectors": [], "reason": "unsupported_topology"}
    if len(nodes) < 2:
        return {"summary": "Generic semantic blueprint requires at least two visible entities.", "applied": False, "topology": topology, "nodes": [], "connectors": [], "reason": "too_few_nodes"}
    if len(nodes) > max(2, int(max_nodes)):
        return {"summary": "Generic semantic blueprint skipped because the visible contract is too dense for one raster guide.", "applied": False, "topology": topology, "nodes": [], "connectors": [], "reason": "too_many_nodes", "node_count": len(nodes)}

    node_ids = {item["id"] for item in nodes}
    relations = _visible_relations(specification, node_ids)
    if not relations:
        return {"summary": "Generic semantic blueprint requires at least one declared relation.", "applied": False, "topology": topology, "nodes": [], "connectors": [], "reason": "no_relations"}

    ranks = _rank_nodes(nodes, relations)
    positioned = _layout_nodes(nodes, ranks)
    by_id = {item["id"]: item for item in positioned}
    incoming_groups: dict[str, list[dict[str, str]]] = defaultdict(list)
    outgoing_groups: dict[str, list[dict[str, str]]] = defaultdict(list)
    for relation in relations:
        incoming_groups[relation["target"]].append(relation)
        outgoing_groups[relation["source"]].append(relation)
    connectors = []
    for index, relation in enumerate(relations, start=1):
        incoming = incoming_groups[relation["target"]]
        outgoing = outgoing_groups[relation["source"]]
        target_index = incoming.index(relation)
        source_index = outgoing.index(relation)
        target_fraction = (target_index + 1) / (len(incoming) + 1)
        source_fraction = (source_index + 1) / (len(outgoing) + 1)
        path, route_style = _connector_path(
            by_id[relation["source"]],
            by_id[relation["target"]],
            relation["type"],
            source_port_fraction=source_fraction,
            target_port_fraction=target_fraction,
        )
        connectors.append({
            "id": f"semantic_connector_{index:02d}",
            **relation,
            "path_percent": path,
            "route_style": route_style,
        })
    return {
        "summary": "Paper-grounded semantic graph compiled into normalized node and connector geometry.",
        "applied": True,
        "topology": topology,
        "node_count": len(positioned),
        "connector_count": len(connectors),
        "nodes": positioned,
        "connectors": connectors,
        "source": "figure_specification",
    }
