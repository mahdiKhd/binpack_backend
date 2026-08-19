from django.test import TestCase
from rest_framework.exceptions import ValidationError

from packing.geometry import validate_and_measure
from packing.models import Box, Container, Project
from users.models import User


class GeometryValidationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("geometry@example.test", "ValidPass-123")
        self.project = Project.objects.create(owner=self.user, name="Geometry")
        Container.objects.create(
            project=self.project,
            length_mm=100,
            width_mm=100,
            height_mm=100,
            max_weight_kg=20,
        )
        self.box = Box.objects.create(
            project=self.project,
            label="Box",
            length_mm=50,
            width_mm=50,
            height_mm=50,
            weight_kg=5,
            count=2,
        )

    def placement(self, index, x=0, y=0, z=0):
        return {
            "box_id": str(self.box.id),
            "instance_index": index,
            "position_mm": {"x": x, "y": y, "z": z},
            "size_mm": {"length": 50, "width": 50, "height": 50},
            "orientation": "LWH",
        }

    def test_metrics_and_unplaced_are_authoritative(self):
        payload, metrics = validate_and_measure(
            self.project,
            {"placements": [self.placement(0)], "unplaced": []},
        )
        self.assertEqual(
            payload["unplaced"], [{"box_id": str(self.box.id), "count": 1}]
        )
        self.assertEqual(metrics["packed_count"], 1)
        self.assertEqual(metrics["volume_utilization_pct"], 12.5)

    def test_overlap_is_rejected(self):
        with self.assertRaises(ValidationError):
            validate_and_measure(
                self.project,
                {"placements": [self.placement(0), self.placement(1, x=25)]},
            )

    def test_floating_box_rejected_when_stacking_enabled(self):
        with self.assertRaises(ValidationError):
            validate_and_measure(
                self.project,
                {"placements": [self.placement(0, z=50)]},
                respect_stacking=True,
            )
