from collections import Counter
from decimal import Decimal

from rest_framework import serializers

from .algorithms.base import ORIENTATION_ORDERS, overlaps
from .algorithms.common import candidate_is_supported


def expected_size(box, orientation):
    dimensions = (box.length_mm, box.width_mm, box.height_mm)
    return tuple(dimensions[index] for index in ORIENTATION_ORDERS[orientation])


def validate_and_measure(project, payload, *, respect_stacking=False):
    try:
        container = project.containers.get()
    except project.containers.model.DoesNotExist as exc:
        raise serializers.ValidationError(
            {"container": ["Configure a container first."]}
        ) from exc
    except project.containers.model.MultipleObjectsReturned as exc:
        raise serializers.ValidationError(
            {
                "container": [
                    "This project has multiple containers; select one explicitly."
                ]
            }
        ) from exc

    if not isinstance(payload, dict) or not isinstance(payload.get("placements"), list):
        raise serializers.ValidationError(
            {"placements": ["Expected an object containing a placements list."]}
        )

    boxes = {str(box.id): box for box in project.boxes.all()}
    box_dicts = {
        key: {
            "weight_kg": float(box.weight_kg),
            "is_stackable": box.is_stackable,
            "max_load_kg": None if box.max_load_kg is None else float(box.max_load_kg),
        }
        for key, box in boxes.items()
    }
    placements = payload["placements"]
    normalized = []
    seen_instances = set()
    counts = Counter()
    errors = []

    for index, raw in enumerate(placements):
        path = f"placements[{index}]"
        if not isinstance(raw, dict):
            errors.append({"path": path, "message": "Placement must be an object."})
            continue
        box_id = str(raw.get("box_id", ""))
        box = boxes.get(box_id)
        if box is None:
            errors.append(
                {
                    "path": f"{path}.box_id",
                    "message": "Box does not belong to this project.",
                }
            )
            continue
        instance_index = raw.get("instance_index")
        if type(instance_index) is not int or not 0 <= instance_index < box.count:
            errors.append(
                {
                    "path": f"{path}.instance_index",
                    "message": f"Must be an integer from 0 to {box.count - 1}.",
                }
            )
            continue
        instance_key = (box_id, instance_index)
        if instance_key in seen_instances:
            errors.append(
                {"path": path, "message": "This box instance is placed more than once."}
            )
            continue
        seen_instances.add(instance_key)
        counts[box_id] += 1

        orientation = raw.get("orientation")
        if orientation not in ORIENTATION_ORDERS:
            errors.append(
                {"path": f"{path}.orientation", "message": "Unknown orientation."}
            )
            continue
        if not box.allow_rotation and orientation != "LWH":
            errors.append(
                {
                    "path": f"{path}.orientation",
                    "message": "Rotation is disabled for this box type.",
                }
            )
            continue
        position, size = raw.get("position_mm"), raw.get("size_mm")
        if not isinstance(position, dict) or set(position) != {"x", "y", "z"}:
            errors.append(
                {
                    "path": f"{path}.position_mm",
                    "message": "Expected numeric x, y, and z.",
                }
            )
            continue
        if not isinstance(size, dict) or set(size) != {"length", "width", "height"}:
            errors.append(
                {
                    "path": f"{path}.size_mm",
                    "message": "Expected length, width, and height.",
                }
            )
            continue
        coords = [position.get(axis) for axis in ("x", "y", "z")]
        dimensions = [size.get(axis) for axis in ("length", "width", "height")]
        if any(type(value) not in (int, float) or value < 0 for value in coords):
            errors.append(
                {
                    "path": f"{path}.position_mm",
                    "message": "Coordinates must be non-negative numbers.",
                }
            )
            continue
        if tuple(dimensions) != expected_size(box, orientation):
            errors.append(
                {
                    "path": f"{path}.size_mm",
                    "message": "Size does not match the box dimensions and orientation.",
                }
            )
            continue

        candidate = {
            "box_id": box_id,
            "instance_index": instance_index,
            "position_mm": {axis: position[axis] for axis in ("x", "y", "z")},
            "size_mm": {axis: size[axis] for axis in ("length", "width", "height")},
            "orientation": orientation,
        }
        p, s = candidate["position_mm"], candidate["size_mm"]
        if (
            p["x"] + s["length"] > container.length_mm
            or p["y"] + s["width"] > container.width_mm
            or p["z"] + s["height"] > container.height_mm
        ):
            errors.append(
                {"path": path, "message": "Placement extends outside the container."}
            )
            continue
        for other_index, other in enumerate(normalized):
            if overlaps(candidate, other):
                errors.append(
                    {"path": path, "message": f"Overlaps placements[{other_index}]."}
                )
                break
        else:
            normalized.append(candidate)

    if respect_stacking and not errors:
        for index, candidate in enumerate(normalized):
            other_placements = [item for item in normalized if item is not candidate]
            if not candidate_is_supported(candidate, other_placements, box_dicts):
                errors.append(
                    {
                        "path": f"placements[{index}]",
                        "message": "Placement is not fully supported or exceeds a support load.",
                    }
                )

    if errors:
        raise serializers.ValidationError({"placements": errors})

    total_weight = sum(
        Decimal(str(boxes[box_id].weight_kg)) * count
        for box_id, count in counts.items()
    )
    if (
        container.max_weight_kg not in (None, 0)
        and total_weight > container.max_weight_kg
    ):
        raise serializers.ValidationError(
            {"placements": ["Total packed weight exceeds container capacity."]}
        )

    unplaced = [
        {"box_id": box_id, "count": box.count - counts[box_id]}
        for box_id, box in sorted(boxes.items())
        if box.count - counts[box_id] > 0
    ]
    authoritative = {"placements": normalized, "unplaced": unplaced}
    return authoritative, compute_metrics(container, boxes, authoritative)


def compute_metrics(container, boxes, payload):
    placements = payload["placements"]
    packed_volume = sum(
        item["size_mm"]["length"] * item["size_mm"]["width"] * item["size_mm"]["height"]
        for item in placements
    )
    container_volume = container.length_mm * container.width_mm * container.height_mm
    total_weight = sum(
        Decimal(str(boxes[item["box_id"]].weight_kg)) for item in placements
    )
    unplaced_count = sum(item["count"] for item in payload.get("unplaced", []))
    capacity = container.max_weight_kg
    return {
        "volume_utilization_pct": round(packed_volume * 100 / container_volume, 2),
        "packed_count": len(placements),
        "unplaced_count": unplaced_count,
        "total_weight_kg": float(total_weight),
        "weight_utilization_pct": None
        if capacity in (None, 0)
        else round(float(total_weight * 100 / capacity), 2),
        "container_volume_mm3": container_volume,
    }
