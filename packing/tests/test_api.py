from unittest.mock import patch

from django.core import mail
from django.test import override_settings
from rest_framework import status
from rest_framework.test import APITestCase

from packing.algorithms import registry
from packing.models import Box, Container, Layout, PackingJob, Project
from packing.tasks import run_packing_job
from packing.views import make_snapshot
from users.models import EmailVerificationToken, User


@override_settings(
    CELERY_TASK_ALWAYS_EAGER=True,
    CELERY_TASK_EAGER_PROPAGATES=True,
    CHANNEL_LAYERS={"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}},
)
class ApiTests(APITestCase):
    def test_registration_hashes_verification_token(self):
        response = self.client.post(
            "/api/v1/auth/register",
            {"email": "new@example.test", "password": "StrongPass-123"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        token = EmailVerificationToken.objects.get()
        self.assertEqual(len(token.token_hash), 64)
        self.assertNotIn(token.token_hash, mail.outbox[0].body)
        self.assertIn("verify-email?token=", mail.outbox[0].body)

    def test_resources_are_owner_scoped(self):
        owner = User.objects.create_user("owner@example.test", "StrongPass-123")
        stranger = User.objects.create_user("stranger@example.test", "StrongPass-123")
        project = Project.objects.create(owner=owner, name="Private")
        self.client.force_authenticate(stranger)
        response = self.client.get(f"/api/v1/projects/{project.id}")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    @patch("packing.views.run_packing_job.delay")
    def test_unverified_user_cannot_submit_job(self, delay):
        user, project = self.make_project(verified=False)
        self.client.force_authenticate(user)
        response = self.client.post(
            f"/api/v1/projects/{project.id}/packing-jobs",
            {"algorithm": "ffd_extreme_point", "parameters": {}},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        delay.assert_not_called()

    @patch("packing.views.run_packing_job.delay")
    def test_job_submission_captures_snapshot_and_enqueues(self, delay):
        delay.return_value.id = "task-123"
        user, project = self.make_project(verified=True)
        self.client.force_authenticate(user)
        response = self.client.post(
            f"/api/v1/projects/{project.id}/packing-jobs",
            {"algorithm": "ffd_extreme_point", "parameters": {}},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        job = PackingJob.objects.get()
        self.assertEqual(job.input_snapshot["container"]["length_mm"], 100)
        self.assertEqual(job.celery_task_id, "task-123")
        delay.assert_called_once_with(str(job.id))

    def test_manual_layout_rejects_overlap_with_error_envelope(self):
        user, project = self.make_project(verified=True)
        box = project.boxes.get()
        placement = {
            "box_id": str(box.id),
            "position_mm": {"x": 0, "y": 0, "z": 0},
            "size_mm": {"length": 50, "width": 50, "height": 50},
            "orientation": "LWH",
        }
        self.client.force_authenticate(user)
        response = self.client.post(
            f"/api/v1/projects/{project.id}/layouts",
            {
                "placements": {
                    "placements": [
                        {**placement, "instance_index": 0},
                        {**placement, "instance_index": 1},
                    ]
                }
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["error"]["code"], "validation_error")

    def test_worker_lifecycle_creates_algorithm_layout(self):
        user, project = self.make_project(verified=True)
        job = PackingJob.objects.create(
            project=project,
            created_by=user,
            algorithm="ffd_extreme_point",
            parameters=registry.get("ffd_extreme_point").validate({}),
            input_snapshot=make_snapshot(project),
        )
        result = run_packing_job.apply(args=[str(job.id)])
        self.assertTrue(result.successful())
        job.refresh_from_db()
        self.assertEqual(job.status, PackingJob.Status.SUCCEEDED)
        self.assertEqual(job.progress, 100)
        self.assertEqual(job.layout.source, Layout.Source.ALGORITHM)
        self.assertEqual(job.layout.metrics["packed_count"], 2)

    def test_csv_export_is_created_for_verified_user(self):
        user, project = self.make_project(verified=True)
        box = project.boxes.get()
        layout = Layout.objects.create(
            project=project,
            source=Layout.Source.MANUAL,
            name="Export me",
            is_saved=True,
            placements={
                "placements": [
                    {
                        "box_id": str(box.id),
                        "instance_index": 0,
                        "position_mm": {"x": 0, "y": 0, "z": 0},
                        "size_mm": {"length": 50, "width": 50, "height": 50},
                        "orientation": "LWH",
                    }
                ],
                "unplaced": [{"box_id": str(box.id), "count": 1}],
            },
            metrics={"packed_count": 1, "unplaced_count": 1},
        )
        self.client.force_authenticate(user)
        response = self.client.post(
            f"/api/v1/layouts/{layout.id}/export",
            {"format": "csv"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(response.data["url"].endswith(".csv"))

    def make_project(self, verified):
        user = User.objects.create_user(
            f"user-{User.objects.count()}@example.test",
            "StrongPass-123",
            is_email_verified=verified,
        )
        project = Project.objects.create(owner=user, name="Project")
        Container.objects.create(
            project=project,
            length_mm=100,
            width_mm=100,
            height_mm=100,
            max_weight_kg=100,
        )
        Box.objects.create(
            project=project,
            label="Cube",
            length_mm=50,
            width_mm=50,
            height_mm=50,
            weight_kg=1,
            count=2,
        )
        return user, project
