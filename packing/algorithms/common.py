from .base import overlaps


def candidate_is_supported(candidate, placed, box_by_id):
    position = candidate["position_mm"]
    if position["z"] == 0:
        return True

    size = candidate["size_mm"]
    base_area = size["length"] * size["width"]
    supported_area = 0
    supports = []
    for other in placed:
        op, os = other["position_mm"], other["size_mm"]
        if op["z"] + os["height"] != position["z"]:
            continue
        x_overlap = max(
            0,
            min(position["x"] + size["length"], op["x"] + os["length"])
            - max(position["x"], op["x"]),
        )
        y_overlap = max(
            0,
            min(position["y"] + size["width"], op["y"] + os["width"])
            - max(position["y"], op["y"]),
        )
        area = x_overlap * y_overlap
        if area:
            supports.append((other, area))
            supported_area += area

    if supported_area < base_area:
        return False

    candidate_box = box_by_id[candidate["box_id"]]
    candidate_weight = float(candidate_box["weight_kg"])
    for support, area in supports:
        support_box = box_by_id[support["box_id"]]
        if not support_box.get("is_stackable", True):
            return False
        max_load = support_box.get("max_load_kg")
        allocated_weight = candidate_weight * area / supported_area
        if max_load is not None and allocated_weight > float(max_load):
            return False
    return True


def can_place(candidate, placed, container, *, respect_stacking=False, box_by_id=None):
    position, size = candidate["position_mm"], candidate["size_mm"]
    if (
        position["x"] < 0
        or position["y"] < 0
        or position["z"] < 0
        or position["x"] + size["length"] > container["length_mm"]
        or position["y"] + size["width"] > container["width_mm"]
        or position["z"] + size["height"] > container["height_mm"]
    ):
        return False
    if any(overlaps(candidate, other) for other in placed):
        return False
    if respect_stacking and not candidate_is_supported(candidate, placed, box_by_id):
        return False
    return True


def weight_allows(current_weight, instance, container, respect_weight):
    capacity = container.get("max_weight_kg")
    return not (
        respect_weight
        and capacity not in (None, 0, 0.0, "0", "0.000")
        and current_weight + float(instance["weight_kg"]) > float(capacity)
    )
