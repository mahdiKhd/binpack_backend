from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from packing.algorithms import registry
from packing.geometry import validate_and_measure
from packing.models import Box, Container, Layout, PackingJob, Project
from users.models import User


DEMO_EMAIL = "demo@packlab.local"
DEMO_PASSWORD = "PackLabDemo2026!"


SCENARIOS = (
    {
        "name": "01 — Perfect Fit",
        "description": (
            "Eight identical cartons fill the container exactly. Use this first to "
            "explain bounds, coordinates, utilization, and deterministic placement."
        ),
        "container": {
            "name": "Exact-fit demo container",
            "length_mm": 1200,
            "width_mm": 800,
            "height_mm": 600,
            "max_weight_kg": 500,
        },
        "boxes": (
            {
                "label": "Exact-fit carton",
                "length_mm": 600,
                "width_mm": 400,
                "height_mm": 300,
                "weight_kg": 12,
                "count": 8,
                "color": "#5B6CFF",
                "is_stackable": True,
                "max_load_kg": 100,
                "allow_rotation": False,
            },
        ),
        "runs": (
            {
                "name": "Perfect 100% fill — FFD",
                "algorithm": "ffd_extreme_point",
                "parameters": {"respect_stacking": True},
            },
        ),
    },
    {
        "name": "02 — Mixed Cargo",
        "description": (
            "Three box types with different dimensions, weights, and colors. Includes "
            "all four algorithms so their results can be compared in layout history."
        ),
        "container": {
            "name": "Mixed-cargo bay",
            "length_mm": 3000,
            "width_mm": 1800,
            "height_mm": 1800,
            "max_weight_kg": 2000,
        },
        "boxes": (
            {
                "label": "Blue cartons",
                "length_mm": 600,
                "width_mm": 400,
                "height_mm": 300,
                "weight_kg": 10,
                "count": 18,
                "color": "#5B6CFF",
                "is_stackable": True,
                "max_load_kg": 80,
                "allow_rotation": True,
            },
            {
                "label": "Orange drums",
                "length_mm": 450,
                "width_mm": 450,
                "height_mm": 900,
                "weight_kg": 35,
                "count": 8,
                "color": "#F97316",
                "is_stackable": True,
                "max_load_kg": 150,
                "allow_rotation": False,
            },
            {
                "label": "Green equipment cases",
                "length_mm": 900,
                "width_mm": 600,
                "height_mm": 500,
                "weight_kg": 60,
                "count": 5,
                "color": "#10B981",
                "is_stackable": True,
                "max_load_kg": 250,
                "allow_rotation": True,
            },
        ),
        "runs": (
            {
                "name": "Mixed cargo — FFD",
                "algorithm": "ffd_extreme_point",
                "parameters": {"respect_stacking": False},
            },
            {
                "name": "Mixed cargo — Shelf / Layer",
                "algorithm": "shelf_layer",
                "parameters": {"respect_stacking": False},
            },
            {
                "name": "Mixed cargo — Best Fit Extreme Point",
                "algorithm": "best_fit_extreme_point",
                "parameters": {"respect_stacking": False},
            },
            {
                "name": "Mixed cargo — GRASP",
                "algorithm": "grasp_extreme_point",
                "parameters": {
                    "iterations": 6,
                    "seed": 2026,
                    "respect_stacking": False,
                },
            },
        ),
    },
    {
        "name": "03 — Rotation Required",
        "description": (
            "The panels do not fit in their original orientation. Compare the two saved "
            "layouts to demonstrate why orientation search matters."
        ),
        "container": {
            "name": "Narrow panel container",
            "length_mm": 1000,
            "width_mm": 600,
            "height_mm": 500,
            "max_weight_kg": 100,
        },
        "boxes": (
            {
                "label": "Wide display panel",
                "length_mm": 600,
                "width_mm": 700,
                "height_mm": 200,
                "weight_kg": 8,
                "count": 2,
                "color": "#8B5CF6",
                "is_stackable": True,
                "max_load_kg": 20,
                "allow_rotation": True,
            },
        ),
        "runs": (
            {
                "name": "Rotation disabled — no fit",
                "algorithm": "ffd_extreme_point",
                "parameters": {
                    "allow_rotation_global": False,
                    "respect_stacking": True,
                },
            },
            {
                "name": "Rotation enabled — panels fit",
                "algorithm": "ffd_extreme_point",
                "parameters": {
                    "allow_rotation_global": True,
                    "respect_stacking": True,
                },
            },
        ),
    },
    {
        "name": "04 — Container Weight Limit",
        "description": (
            "The volume can hold every battery, but the 100 kg container capacity permits "
            "only three 30 kg units."
        ),
        "container": {
            "name": "Weight-limited van",
            "length_mm": 3000,
            "width_mm": 2000,
            "height_mm": 2000,
            "max_weight_kg": 100,
        },
        "boxes": (
            {
                "label": "Dense battery module",
                "length_mm": 500,
                "width_mm": 500,
                "height_mm": 500,
                "weight_kg": 30,
                "count": 10,
                "color": "#EAB308",
                "is_stackable": True,
                "max_load_kg": 200,
                "allow_rotation": True,
            },
        ),
        "runs": (
            {
                "name": "Stopped by 100 kg capacity",
                "algorithm": "ffd_extreme_point",
                "parameters": {"respect_weight": True},
            },
        ),
    },
    {
        "name": "05 — Fragile Load Bearing",
        "description": (
            "Each television weighs 40 kg but may carry only 10 kg. With stacking checks "
            "enabled, televisions remain on the floor instead of forming a second layer."
        ),
        "container": {
            "name": "Fragile-goods container",
            "length_mm": 4000,
            "width_mm": 1200,
            "height_mm": 2100,
            "max_weight_kg": 2000,
        },
        "boxes": (
            {
                "label": "Television",
                "length_mm": 1000,
                "width_mm": 400,
                "height_mm": 1000,
                "weight_kg": 40,
                "count": 20,
                "color": "#EC4899",
                "is_stackable": True,
                "max_load_kg": 10,
                "allow_rotation": False,
            },
        ),
        "runs": (
            {
                "name": "Fragile TVs — load bearing enabled",
                "algorithm": "ffd_extreme_point",
                "parameters": {"respect_stacking": True},
            },
        ),
    },
    {
        "name": "06 — Non-stackable Cargo",
        "description": (
            "These crates fit in two geometric layers, but their non-stackable flag limits "
            "the valid result to the floor layer."
        ),
        "container": {
            "name": "Non-stackable cargo bay",
            "length_mm": 2400,
            "width_mm": 800,
            "height_mm": 1700,
            "max_weight_kg": 1000,
        },
        "boxes": (
            {
                "label": "Do-not-stack crate",
                "length_mm": 800,
                "width_mm": 400,
                "height_mm": 800,
                "weight_kg": 20,
                "count": 12,
                "color": "#EF4444",
                "is_stackable": False,
                "max_load_kg": 0,
                "allow_rotation": False,
            },
        ),
        "runs": (
            {
                "name": "Floor layer only",
                "algorithm": "shelf_layer",
                "parameters": {"respect_stacking": True},
            },
        ),
    },
    {
        "name": "07 — Oversized and Unplaced",
        "description": (
            "Small samples fit normally, while beams exceed every container axis in at "
            "least one dimension and are reported as unplaced."
        ),
        "container": {
            "name": "One-metre test cube",
            "length_mm": 1000,
            "width_mm": 1000,
            "height_mm": 1000,
            "max_weight_kg": 500,
        },
        "boxes": (
            {
                "label": "Small sample",
                "length_mm": 250,
                "width_mm": 250,
                "height_mm": 250,
                "weight_kg": 2,
                "count": 8,
                "color": "#06B6D4",
                "is_stackable": True,
                "max_load_kg": 30,
                "allow_rotation": True,
            },
            {
                "label": "Oversized beam",
                "length_mm": 1200,
                "width_mm": 200,
                "height_mm": 200,
                "weight_kg": 15,
                "count": 3,
                "color": "#F97316",
                "is_stackable": True,
                "max_load_kg": 100,
                "allow_rotation": True,
            },
        ),
        "runs": (
            {
                "name": "Oversized beams remain unplaced",
                "algorithm": "ffd_extreme_point",
                "parameters": {"respect_stacking": True},
            },
        ),
    },
)


def make_snapshot(project):
    container = project.containers.get()
    boxes = list(project.boxes.all())
    return {
        "container": {
            "id": str(container.id),
            "name": container.name,
            "length_mm": container.length_mm,
            "width_mm": container.width_mm,
            "height_mm": container.height_mm,
            "max_weight_kg": (
                None
                if container.max_weight_kg is None
                else float(container.max_weight_kg)
            ),
        },
        "boxes": [
            {
                "id": str(box.id),
                "label": box.label,
                "length_mm": box.length_mm,
                "width_mm": box.width_mm,
                "height_mm": box.height_mm,
                "weight_kg": float(box.weight_kg),
                "count": box.count,
                "color": box.color,
                "is_stackable": box.is_stackable,
                "max_load_kg": (
                    None if box.max_load_kg is None else float(box.max_load_kg)
                ),
                "allow_rotation": box.allow_rotation,
            }
            for box in boxes
        ],
    }


class Command(BaseCommand):
    help = "Create a verified demo user with presentation-ready packing scenarios."

    def add_arguments(self, parser):
        parser.add_argument(
            "--email",
            default=DEMO_EMAIL,
            help=f"Presenter account email (default: {DEMO_EMAIL}).",
        )
        parser.add_argument(
            "--password",
            default=DEMO_PASSWORD,
            help="Presenter account password. Use a demo-only password.",
        )
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Delete and recreate only the selected demo account and its data.",
        )
        parser.add_argument(
            "--no-layouts",
            action="store_true",
            help="Create scenario inputs without precomputing saved layouts.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        email = User.objects.normalize_email(options["email"]).lower()
        password = options["password"]
        existing = User.objects.filter(email=email).first()

        if existing and not options["reset"]:
            raise CommandError(
                f"{email} already exists. Add --reset to recreate only this demo account."
            )
        if existing:
            existing.delete()

        user = User.objects.create_user(
            email=email,
            password=password,
            first_name="Demo",
            last_name="Presenter",
            is_email_verified=True,
        )

        layout_count = 0
        for scenario in SCENARIOS:
            project = Project.objects.create(
                owner=user,
                name=scenario["name"],
                description=scenario["description"],
            )
            Container.objects.create(project=project, **scenario["container"])
            Box.objects.bulk_create(
                [Box(project=project, **box) for box in scenario["boxes"]]
            )

            if not options["no_layouts"]:
                for run in scenario["runs"]:
                    self.create_layout(user, project, run)
                    layout_count += 1

            self.stdout.write(
                self.style.SUCCESS(
                    f"Created {project.name} ({len(scenario['boxes'])} box type(s), "
                    f"{0 if options['no_layouts'] else len(scenario['runs'])} layout(s))"
                )
            )

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Demo presentation data is ready."))
        self.stdout.write(f"Email:    {email}")
        self.stdout.write(f"Password: {password}")
        self.stdout.write("Verified: yes")
        self.stdout.write(
            f"Created:  {len(SCENARIOS)} projects and {layout_count} saved layouts"
        )
        self.stdout.write(
            self.style.WARNING("Use this account only for local/demo environments.")
        )

    def create_layout(self, user, project, run):
        snapshot = make_snapshot(project)
        definition = registry.get(run["algorithm"])
        parameters = definition.validate(run.get("parameters", {}))
        solution = definition.runner(snapshot, parameters)
        payload, metrics = validate_and_measure(
            project,
            solution.as_payload(),
            respect_stacking=parameters["respect_stacking"],
        )
        now = timezone.now()
        job = PackingJob.objects.create(
            project=project,
            created_by=user,
            algorithm=run["algorithm"],
            parameters=parameters,
            input_snapshot=snapshot,
            status=PackingJob.Status.SUCCEEDED,
            progress=100,
            started_at=now,
            finished_at=now,
        )
        return Layout.objects.create(
            project=project,
            source=Layout.Source.ALGORITHM,
            job=job,
            name=run["name"],
            is_saved=True,
            placements=payload,
            metrics=metrics,
        )
