from .base import PackingSolution, expanded_instances, make_placement, orientations_for
from .common import can_place, weight_allows
from .registry import registry


@registry.register(
    key="shelf_layer",
    display_name="Shelf / Layer",
    description="A fast row-and-layer heuristic that builds upward from the floor.",
    parameters={
        "prefer_low_height": {
            "type": "boolean",
            "default": True,
            "description": "Prefer orientations with a shorter vertical dimension.",
        }
    },
)
def run_shelf(
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
    cursor_x = cursor_y = cursor_z = 0
    row_depth = layer_height = 0
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

        choices = orientations_for(instance, parameters["allow_rotation_global"])
        if parameters["prefer_low_height"]:
            choices.sort(
                key=lambda choice: (choice[1][2], choice[1][1], choice[1][0], choice[0])
            )
        selected = None
        for location in ("current", "new_row", "new_layer"):
            for orientation, size in choices:
                if location == "current":
                    point = (cursor_x, cursor_y, cursor_z)
                elif location == "new_row":
                    point = (0, cursor_y + row_depth, cursor_z)
                else:
                    point = (0, 0, cursor_z + layer_height)
                if (
                    point[0] + size[0] <= container["length_mm"]
                    and point[1] + size[1] <= container["width_mm"]
                    and point[2] + size[2] <= container["height_mm"]
                ):
                    candidate = make_placement(instance, point, orientation, size)
                    if can_place(
                        candidate,
                        placed,
                        container,
                        respect_stacking=parameters["respect_stacking"],
                        box_by_id=box_by_id,
                    ):
                        selected = (location, candidate)
                        break
            if selected:
                break

        if not selected:
            unplaced.append(instance)
        else:
            location, placement = selected
            size = placement["size_mm"]
            if location == "new_row":
                cursor_x = 0
                cursor_y += row_depth
                row_depth = 0
            elif location == "new_layer":
                cursor_x = cursor_y = 0
                cursor_z += layer_height
                row_depth = layer_height = 0
            placed.append(placement)
            cursor_x += size["length"]
            row_depth = max(row_depth, size["width"])
            layer_height = max(layer_height, size["height"])
            current_weight += float(instance["weight_kg"])
        progress(round(processed * 100 / total))

    return PackingSolution(placed, unplaced)
