from collections import Counter
from dataclasses import dataclass


ORIENTATION_ORDERS = {
    "LWH": (0, 1, 2),
    "LHW": (0, 2, 1),
    "WLH": (1, 0, 2),
    "WHL": (1, 2, 0),
    "HLW": (2, 0, 1),
    "HWL": (2, 1, 0),
}


def orientations_for(instance, global_rotation=True):
    dimensions = (instance["length_mm"], instance["width_mm"], instance["height_mm"])
    allowed = (
        ORIENTATION_ORDERS
        if global_rotation and instance.get("allow_rotation", True)
        else {"LWH": (0, 1, 2)}
    )
    seen = set()
    result = []
    for name, order in allowed.items():
        size = tuple(dimensions[index] for index in order)
        if size not in seen:
            result.append((name, size))
            seen.add(size)
    return result


def overlaps(a, b):
    ap, ass = a["position_mm"], a["size_mm"]
    bp, bss = b["position_mm"], b["size_mm"]
    return (
        ap["x"] < bp["x"] + bss["length"]
        and ap["x"] + ass["length"] > bp["x"]
        and ap["y"] < bp["y"] + bss["width"]
        and ap["y"] + ass["width"] > bp["y"]
        and ap["z"] < bp["z"] + bss["height"]
        and ap["z"] + ass["height"] > bp["z"]
    )


def within_bounds(placement, container):
    position, size = placement["position_mm"], placement["size_mm"]
    return (
        position["x"] >= 0
        and position["y"] >= 0
        and position["z"] >= 0
        and position["x"] + size["length"] <= container["length_mm"]
        and position["y"] + size["width"] <= container["width_mm"]
        and position["z"] + size["height"] <= container["height_mm"]
    )


def make_placement(instance, position, orientation, size):
    return {
        "box_id": instance["box_id"],
        "instance_index": instance["instance_index"],
        "position_mm": {"x": position[0], "y": position[1], "z": position[2]},
        "size_mm": {"length": size[0], "width": size[1], "height": size[2]},
        "orientation": orientation,
    }


def expanded_instances(snapshot):
    result = []
    for box in snapshot["boxes"]:
        for index in range(box["count"]):
            result.append({**box, "box_id": str(box["id"]), "instance_index": index})
    return result


def aggregate_unplaced(instances):
    counts = Counter(item["box_id"] for item in instances)
    return [
        {"box_id": box_id, "count": count} for box_id, count in sorted(counts.items())
    ]


@dataclass(frozen=True)
class PackingSolution:
    placements: list
    unplaced: list

    def as_payload(self):
        return {
            "placements": self.placements,
            "unplaced": aggregate_unplaced(self.unplaced),
        }
