from django.test import SimpleTestCase

from packing.algorithms import registry
from packing.algorithms.base import overlaps


def snapshot(count=8, max_weight=100):
    return {
        "container": {
            "id": "container",
            "length_mm": 10,
            "width_mm": 10,
            "height_mm": 10,
            "max_weight_kg": max_weight,
        },
        "boxes": [
            {
                "id": "box-a",
                "label": "Cube",
                "length_mm": 5,
                "width_mm": 5,
                "height_mm": 5,
                "weight_kg": 2,
                "count": count,
                "allow_rotation": True,
                "is_stackable": True,
                "max_load_kg": 100,
            }
        ],
    }


class AlgorithmTests(SimpleTestCase):
    def assert_valid_solution(self, solution):
        placements = solution.placements
        self.assertEqual(len(placements), 8)
        for placement in placements:
            p, s = placement["position_mm"], placement["size_mm"]
            self.assertGreaterEqual(min(p.values()), 0)
            self.assertLessEqual(p["x"] + s["length"], 10)
            self.assertLessEqual(p["y"] + s["width"], 10)
            self.assertLessEqual(p["z"] + s["height"], 10)
        for index, first in enumerate(placements):
            for second in placements[index + 1 :]:
                self.assertFalse(overlaps(first, second))

    def test_all_algorithms_pack_regular_cubes(self):
        for key in (
            "best_fit_extreme_point",
            "ffd_extreme_point",
            "grasp_extreme_point",
            "shelf_layer",
        ):
            definition = registry.get(key)
            parameters = definition.validate({})
            self.assert_valid_solution(definition.runner(snapshot(), parameters))

    def test_weight_limit_is_respected(self):
        definition = registry.get("ffd_extreme_point")
        solution = definition.runner(snapshot(max_weight=5), definition.validate({}))
        self.assertEqual(len(solution.placements), 2)
        self.assertEqual(len(solution.unplaced), 6)

    def test_algorithm_parameters_are_strict(self):
        definition = registry.get("shelf_layer")
        with self.assertRaisesMessage(Exception, "Unknown algorithm parameter"):
            definition.validate({"surprise": True})

    def test_grasp_is_reproducible_with_the_same_seed(self):
        definition = registry.get("grasp_extreme_point")
        parameters = definition.validate({"iterations": 3, "seed": 2026})
        first = definition.runner(snapshot(), parameters)
        second = definition.runner(snapshot(), parameters)
        self.assertEqual(first.as_payload(), second.as_payload())

    def test_advanced_algorithms_honor_the_weight_limit(self):
        for key in ("best_fit_extreme_point", "grasp_extreme_point"):
            definition = registry.get(key)
            supplied = {"iterations": 2} if key == "grasp_extreme_point" else {}
            solution = definition.runner(
                snapshot(max_weight=5), definition.validate(supplied)
            )
            self.assertEqual(len(solution.placements), 2)
            self.assertEqual(len(solution.unplaced), 6)

    def test_advanced_algorithms_can_be_cancelled(self):
        for key in ("best_fit_extreme_point", "grasp_extreme_point"):
            definition = registry.get(key)
            with self.assertRaises(InterruptedError):
                definition.runner(
                    snapshot(),
                    definition.validate({}),
                    cancel_check=lambda: True,
                )

    def test_advanced_algorithms_honor_support_loads(self):
        fragile = snapshot()
        fragile["boxes"][0]["max_load_kg"] = 1
        for key in ("best_fit_extreme_point", "grasp_extreme_point"):
            definition = registry.get(key)
            supplied = {
                "respect_stacking": True,
                **({"iterations": 2} if key == "grasp_extreme_point" else {}),
            }
            solution = definition.runner(fragile, definition.validate(supplied))
            self.assertEqual(len(solution.placements), 4)
            self.assertTrue(
                all(item["position_mm"]["z"] == 0 for item in solution.placements)
            )

    def test_registry_exposes_the_advanced_algorithms(self):
        metadata = {item["key"]: item for item in registry.metadata()}
        self.assertIn("best_fit_extreme_point", metadata)
        self.assertIn("grasp_extreme_point", metadata)
        self.assertIn("iterations", metadata["grasp_extreme_point"]["parameters"])
        self.assertEqual(
            metadata["grasp_extreme_point"]["parameters"]["seed"]["default"], 42
        )
