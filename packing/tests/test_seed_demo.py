from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from packing.models import Project
from users.models import User


class SeedDemoCommandTests(TestCase):
    email = "presentation@example.test"
    password = "PresentationPass-123!"

    def run_command(self, **options):
        output = StringIO()
        call_command(
            "seed_demo",
            email=self.email,
            password=self.password,
            stdout=output,
            **options,
        )
        return output.getvalue()

    def test_creates_verified_user_projects_and_saved_layouts(self):
        output = self.run_command()

        user = User.objects.get(email=self.email)
        self.assertTrue(user.is_email_verified)
        self.assertTrue(user.check_password(self.password))
        self.assertEqual(user.projects.count(), 7)
        self.assertEqual(
            sum(project.layouts.count() for project in user.projects.all()), 11
        )
        self.assertIn("Demo presentation data is ready", output)

        weight_project = Project.objects.get(
            owner=user, name="04 — Container Weight Limit"
        )
        weight_layout = weight_project.layouts.get()
        self.assertEqual(weight_layout.metrics["packed_count"], 3)
        self.assertEqual(weight_layout.metrics["total_weight_kg"], 90.0)

        rotation_project = Project.objects.get(
            owner=user, name="03 — Rotation Required"
        )
        rotation_counts = sorted(
            layout.metrics["packed_count"] for layout in rotation_project.layouts.all()
        )
        self.assertEqual(rotation_counts, [0, 2])

        fragile_project = Project.objects.get(
            owner=user, name="05 — Fragile Load Bearing"
        )
        fragile_layout = fragile_project.layouts.get()
        self.assertEqual(fragile_layout.metrics["packed_count"], 12)
        self.assertEqual(fragile_layout.metrics["unplaced_count"], 8)

    def test_requires_reset_before_replacing_the_demo_account(self):
        self.run_command(no_layouts=True)
        first_user_id = User.objects.get(email=self.email).id

        with self.assertRaises(CommandError):
            self.run_command(no_layouts=True)

        self.run_command(reset=True, no_layouts=True)
        replacement = User.objects.get(email=self.email)
        self.assertNotEqual(replacement.id, first_user_id)
        self.assertEqual(replacement.projects.count(), 7)
