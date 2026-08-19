import uuid

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator, RegexValidator
from django.db import models


class UUIDTimestampModel(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class Project(UUIDTimestampModel):
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="projects"
    )
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self):
        return self.name


class ContainerPreset(models.Model):
    key = models.SlugField(primary_key=True, max_length=80)
    display_name = models.CharField(max_length=160)
    length_mm = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    width_mm = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    height_mm = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    max_weight_kg = models.DecimalField(
        max_digits=12, decimal_places=3, validators=[MinValueValidator(0)]
    )
    category = models.CharField(max_length=80, blank=True)

    class Meta:
        ordering = ["category", "display_name"]

    def __str__(self):
        return self.display_name


class Container(UUIDTimestampModel):
    project = models.ForeignKey(
        Project, on_delete=models.CASCADE, related_name="containers"
    )
    name = models.CharField(max_length=160, blank=True)
    length_mm = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    width_mm = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    height_mm = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    max_weight_kg = models.DecimalField(
        max_digits=12,
        decimal_places=3,
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
    )
    based_on_preset = models.CharField(max_length=80, null=True, blank=True)

    class Meta:
        ordering = ["created_at"]


class Box(UUIDTimestampModel):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="boxes")
    label = models.CharField(max_length=160)
    length_mm = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    width_mm = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    height_mm = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    weight_kg = models.DecimalField(
        max_digits=12, decimal_places=3, default=0, validators=[MinValueValidator(0)]
    )
    count = models.PositiveIntegerField(default=1, validators=[MinValueValidator(1)])
    color = models.CharField(
        max_length=7,
        default="#3B82F6",
        validators=[
            RegexValidator(
                r"^#[0-9A-Fa-f]{6}$", "Use a six-digit hex color, such as #3B82F6."
            )
        ],
    )
    is_stackable = models.BooleanField(default=True)
    max_load_kg = models.DecimalField(
        max_digits=12,
        decimal_places=3,
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
    )
    allow_rotation = models.BooleanField(default=True)

    class Meta:
        ordering = ["created_at", "id"]


class PackingJob(UUIDTimestampModel):
    class Status(models.TextChoices):
        QUEUED = "queued", "Queued"
        RUNNING = "running", "Running"
        SUCCEEDED = "succeeded", "Succeeded"
        FAILED = "failed", "Failed"
        CANCELLED = "cancelled", "Cancelled"

    project = models.ForeignKey(
        Project, on_delete=models.CASCADE, related_name="packing_jobs"
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="packing_jobs"
    )
    algorithm = models.CharField(max_length=80)
    parameters = models.JSONField(default=dict)
    input_snapshot = models.JSONField(default=dict)
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.QUEUED, db_index=True
    )
    progress = models.PositiveSmallIntegerField(
        default=0, validators=[MaxValueValidator(100)]
    )
    error_message = models.TextField(blank=True)
    celery_task_id = models.CharField(max_length=255, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]


class Layout(UUIDTimestampModel):
    class Source(models.TextChoices):
        ALGORITHM = "algorithm", "Algorithm"
        MANUAL = "manual", "Manual"

    project = models.ForeignKey(
        Project, on_delete=models.CASCADE, related_name="layouts"
    )
    source = models.CharField(max_length=16, choices=Source.choices)
    job = models.OneToOneField(
        PackingJob,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="layout",
    )
    name = models.CharField(max_length=200, blank=True)
    is_saved = models.BooleanField(default=False)
    placements = models.JSONField(default=dict)
    metrics = models.JSONField(default=dict)

    class Meta:
        ordering = ["-created_at"]


def artifact_upload_path(instance, filename):
    return f"exports/{instance.layout.project_id}/{instance.layout_id}/{filename}"


class OutputArtifact(UUIDTimestampModel):
    class Format(models.TextChoices):
        PNG = "png", "PNG"
        PDF = "pdf", "PDF"
        CSV = "csv", "CSV"

    layout = models.ForeignKey(
        Layout, on_delete=models.CASCADE, related_name="artifacts"
    )
    format = models.CharField(max_length=8, choices=Format.choices)
    file = models.FileField(upload_to=artifact_upload_path)

    class Meta:
        ordering = ["-created_at"]


class Notification(UUIDTimestampModel):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications"
    )
    event = models.CharField(max_length=80)
    payload = models.JSONField(default=dict)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["user", "read_at", "-created_at"])]
