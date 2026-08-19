import random

from .base import PackingSolution, expanded_instances, make_placement, orientations_for
from .common import can_place, weight_allows
from .registry import registry


def instance_priority(instance):
    dimensions = (
        instance["length_mm"],
        instance["width_mm"],
        instance["height_mm"],
    )
    return (
        -(dimensions[0] * dimensions[1] * dimensions[2]),
        -max(dimensions),
        -float(instance["weight_kg"]),
        instance["box_id"],
        instance["instance_index"],
    )


def overlap_length(first_start, first_end, second_start, second_end):
    return max(0, min(first_end, second_end) - max(first_start, second_start))


def contact_area(candidate, placed, container):
    position, size = candidate["position_mm"], candidate["size_mm"]
    x, y, z = position["x"], position["y"], position["z"]
    length, width, height = size["length"], size["width"], size["height"]
    area = 0

    if x == 0 or x + length == container["length_mm"]:
        area += width * height
    if y == 0 or y + width == container["width_mm"]:
        area += length * height
    if z == 0 or z + height == container["height_mm"]:
        area += length * width

    for other in placed:
        other_position = other["position_mm"]
        other_size = other["size_mm"]
        ox, oy, oz = (
            other_position["x"],
            other_position["y"],
            other_position["z"],
        )
        other_length, other_width, other_height = (
            other_size["length"],
            other_size["width"],
            other_size["height"],
        )

        y_overlap = overlap_length(y, y + width, oy, oy + other_width)
        z_overlap = overlap_length(z, z + height, oz, oz + other_height)
        if x + length == ox or ox + other_length == x:
            area += y_overlap * z_overlap

        x_overlap = overlap_length(x, x + length, ox, ox + other_length)
        if y + width == oy or oy + other_width == y:
            area += x_overlap * z_overlap

        if z + height == oz or oz + other_height == z:
            area += x_overlap * y_overlap

    return area


def placement_score(candidate, placed, container, prefer_contact):
    position, size = candidate["position_mm"], candidate["size_mm"]
    right = position["x"] + size["length"]
    back = position["y"] + size["width"]
    top = position["z"] + size["height"]
    maximum_x = max(
        [
            right,
            *[item["position_mm"]["x"] + item["size_mm"]["length"] for item in placed],
        ]
    )
    maximum_y = max(
        [
            back,
            *[item["position_mm"]["y"] + item["size_mm"]["width"] for item in placed],
        ]
    )
    maximum_z = max(
        [
            top,
            *[item["position_mm"]["z"] + item["size_mm"]["height"] for item in placed],
        ]
    )
    bounding_volume = maximum_x * maximum_y * maximum_z
    gaps = (
        container["length_mm"] - right,
        container["width_mm"] - back,
        container["height_mm"] - top,
    )
    contact = contact_area(candidate, placed, container) if prefer_contact else 0
    return (
        bounding_volume,
        -contact,
        -min(gaps),
        sum(gaps),
        maximum_z,
        position["z"],
        position["y"],
        position["x"],
        candidate["orientation"],
    )


def point_inside_placement(point, placement):
    position, size = placement["position_mm"], placement["size_mm"]
    return (
        position["x"] <= point[0] < position["x"] + size["length"]
        and position["y"] <= point[1] < position["y"] + size["width"]
        and position["z"] <= point[2] < position["z"] + size["height"]
    )


def updated_candidates(candidates, placement, placed, container, limit):
    position, size = placement["position_mm"], placement["size_mm"]
    x, y, z = position["x"], position["y"], position["z"]
    right, back, top = x + size["length"], y + size["width"], z + size["height"]
    candidates.update(
        {
            (right, y, z),
            (x, back, z),
            (x, y, top),
            (right, back, z),
            (right, y, top),
            (x, back, top),
        }
    )
    candidates = {
        point
        for point in candidates
        if point[0] < container["length_mm"]
        and point[1] < container["width_mm"]
        and point[2] < container["height_mm"]
        and not any(point_inside_placement(point, item) for item in placed)
    }
    if len(candidates) > limit:
        candidates = set(
            sorted(candidates, key=lambda point: (point[2], point[1], point[0]))[:limit]
        )
    return candidates


def decode_best_fit(
    snapshot,
    parameters,
    instances,
    *,
    cancel_check,
    progress,
    rng=None,
    placement_rcl_size=1,
):
    container = snapshot["container"]
    box_by_id = {str(box["id"]): box for box in snapshot["boxes"]}
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

        choices = []
        points = sorted(candidates, key=lambda point: (point[2], point[1], point[0]))
        for point in points[: parameters["candidate_limit"]]:
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
                    choices.append(
                        (
                            placement_score(
                                candidate,
                                placed,
                                container,
                                parameters["prefer_contact"],
                            ),
                            candidate,
                        )
                    )

        if not choices:
            unplaced.append(instance)
        else:
            choices.sort(key=lambda choice: choice[0])
            restricted = choices[: min(placement_rcl_size, len(choices))]
            selected = restricted[0][1] if rng is None else rng.choice(restricted)[1]
            placed.append(selected)
            current_weight += float(instance["weight_kg"])
            candidates = updated_candidates(
                candidates,
                selected,
                placed,
                container,
                parameters["candidate_limit"],
            )
        progress(round(processed * 100 / total))

    return PackingSolution(placed, unplaced)


def solution_key(solution):
    packed_volume = sum(
        placement["size_mm"]["length"]
        * placement["size_mm"]["width"]
        * placement["size_mm"]["height"]
        for placement in solution.placements
    )
    maximum_height = max(
        (
            placement["position_mm"]["z"] + placement["size_mm"]["height"]
            for placement in solution.placements
        ),
        default=0,
    )
    return packed_volume, len(solution.placements), -maximum_height


def randomized_order(instances, rng, rcl_size):
    remaining = sorted(instances, key=instance_priority)
    ordered = []
    while remaining:
        window = min(rcl_size, len(remaining))
        ordered.append(remaining.pop(rng.randrange(window)))
    return ordered


@registry.register(
    key="best_fit_extreme_point",
    display_name="Best Fit Extreme Point",
    description=(
        "Evaluates every feasible candidate and favors low, compact placements with "
        "strong surface contact."
    ),
    parameters={
        "candidate_limit": {
            "type": "integer",
            "default": 350,
            "minimum": 25,
            "maximum": 5000,
            "description": "Maximum extreme-point candidates evaluated per box.",
        },
        "prefer_contact": {
            "type": "boolean",
            "default": True,
            "description": "Favor placements touching walls and neighboring boxes.",
        },
    },
)
def run_best_fit(
    snapshot, parameters, cancel_check=lambda: False, progress=lambda value: None
):
    instances = sorted(expanded_instances(snapshot), key=instance_priority)
    return decode_best_fit(
        snapshot,
        parameters,
        instances,
        cancel_check=cancel_check,
        progress=progress,
    )


@registry.register(
    key="grasp_extreme_point",
    display_name="GRASP Extreme Point",
    description=(
        "Runs reproducible randomized best-fit constructions and keeps the layout with "
        "the greatest packed volume."
    ),
    parameters={
        "iterations": {
            "type": "integer",
            "default": 8,
            "minimum": 2,
            "maximum": 100,
            "description": "Number of randomized construction attempts.",
        },
        "seed": {
            "type": "integer",
            "default": 42,
            "minimum": 0,
            "maximum": 2147483647,
            "description": "Random seed for reproducible results.",
        },
        "order_rcl_size": {
            "type": "integer",
            "default": 4,
            "minimum": 1,
            "maximum": 30,
            "description": "Restricted candidate list size for box ordering.",
        },
        "placement_rcl_size": {
            "type": "integer",
            "default": 3,
            "minimum": 1,
            "maximum": 20,
            "description": "Number of top placements eligible for random selection.",
        },
        "candidate_limit": {
            "type": "integer",
            "default": 120,
            "minimum": 25,
            "maximum": 2000,
            "description": "Maximum extreme-point candidates evaluated per box.",
        },
        "prefer_contact": {
            "type": "boolean",
            "default": True,
            "description": "Favor placements touching walls and neighboring boxes.",
        },
    },
)
def run_grasp(
    snapshot, parameters, cancel_check=lambda: False, progress=lambda value: None
):
    instances = expanded_instances(snapshot)
    best = None
    iterations = parameters["iterations"]

    for iteration in range(iterations):
        if cancel_check():
            raise InterruptedError("Packing job was cancelled.")
        rng = random.Random(parameters["seed"] + iteration)
        ordered = randomized_order(instances, rng, parameters["order_rcl_size"])
        solution = decode_best_fit(
            snapshot,
            parameters,
            ordered,
            cancel_check=cancel_check,
            progress=lambda value: None,
            rng=rng,
            placement_rcl_size=parameters["placement_rcl_size"],
        )
        if best is None or solution_key(solution) > solution_key(best):
            best = solution
        progress(round((iteration + 1) * 100 / iterations))

    return best
