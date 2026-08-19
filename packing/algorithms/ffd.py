from .base import PackingSolution, expanded_instances, make_placement, orientations_for
from .common import can_place, weight_allows
from .registry import registry


@registry.register(
    key="ffd_extreme_point",
    display_name="First Fit Decreasing (Extreme Point)",
    description="Places larger boxes first at deterministic candidate corners.",
    parameters={
        "candidate_limit": {
            "type": "integer",
            "default": 5000,
            "minimum": 100,
            "maximum": 20000,
            "description": "Maximum extreme-point candidates retained per step.",
        }
    },
)
def run_ffd(
    snapshot, parameters, cancel_check=lambda: False, progress=lambda value: None
):
    container = snapshot["container"]
    box_by_id = {str(box["id"]): box for box in snapshot["boxes"]}
    instances = expanded_instances(snapshot)
    instances.sort(
        key=lambda item: (
            -(item["length_mm"] * item["width_mm"] * item["height_mm"]),
            item["box_id"],
            item["instance_index"],
        )
    )
    placed, unplaced = [], []
    candidates = {(0, 0, 0)}
    current_weight = 0.0
    total = max(1, len(instances))

    for processed, instance in enumerate(instances, start=1):
        if cancel_check():
            raise InterruptedError("Packing job was cancelled.")
        if not weight_allows(
            current_weight, instance, container, parameters["respect_weight"]
        ):
            unplaced.append(instance)
            progress(round(processed * 100 / total))
            continue

        selected = None
        for point in sorted(candidates, key=lambda p: (p[2], p[1], p[0])):
            for orientation, size in orientations_for(
                instance, parameters["allow_rotation_global"]
            ):
                candidate = make_placement(instance, point, orientation, size)
                if can_place(
                    candidate,
                    placed,
                    container,
                    respect_stacking=parameters["respect_stacking"],
                    box_by_id=box_by_id,
                ):
                    selected = candidate
                    break
            if selected:
                break

        if not selected:
            unplaced.append(instance)
        else:
            placed.append(selected)
            current_weight += float(instance["weight_kg"])
            p, s = selected["position_mm"], selected["size_mm"]
            candidates.update(
                {
                    (p["x"] + s["length"], p["y"], p["z"]),
                    (p["x"], p["y"] + s["width"], p["z"]),
                    (p["x"], p["y"], p["z"] + s["height"]),
                }
            )
            candidates = {
                point
                for point in candidates
                if point[0] < container["length_mm"]
                and point[1] < container["width_mm"]
                and point[2] < container["height_mm"]
            }
            if len(candidates) > parameters["candidate_limit"]:
                candidates = set(
                    sorted(candidates, key=lambda p: (p[2], p[1], p[0]))[
                        : parameters["candidate_limit"]
                    ]
                )
        progress(round(processed * 100 / total))

    return PackingSolution(placed, unplaced)
