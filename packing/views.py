import logging

from celery import current_app
from django.db import transaction
from django.db.models import Count
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.exceptions import APIException, PermissionDenied, ValidationError
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from .algorithms import registry
from .exports import create_csv_artifact, create_pdf_artifact, create_png_artifact
from .models import (
    Container,
    ContainerPreset,
    Layout,
    Notification,
    OutputArtifact,
    PackingJob,
    Project,
)
from .notifications import publish_notification
from .serializers import (
    BoxSerializer,
    ContainerPresetSerializer,
    ContainerSerializer,
    ExportSerializer,
    LayoutSerializer,
    LayoutSummarySerializer,
    LayoutWriteSerializer,
    NotificationSerializer,
    OutputArtifactSerializer,
    PackingJobCreateSerializer,
    PackingJobSerializer,
    ProjectSerializer,
)
from .tasks import run_packing_job

logger = logging.getLogger(__name__)


class ServiceUnavailable(APIException):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    default_detail = "The service is temporarily unavailable."
    default_code = "service_unavailable"


def owned_project(request, project_id):
    return get_object_or_404(Project, id=project_id, owner=request.user)


def require_verified(user):
    if not user.is_email_verified:
        raise PermissionDenied(
            "Verify your email before running packing jobs or creating exports.",
            code="email_not_verified",
        )


def make_snapshot(project):
    try:
        container = project.containers.get()
    except Container.DoesNotExist as exc:
        raise ValidationError(
            {"container": ["Configure a container before packing."]}
        ) from exc
    except Container.MultipleObjectsReturned as exc:
        raise ValidationError(
            {
                "container": [
                    "This project has multiple containers; v1 requires exactly one."
                ]
            }
        ) from exc
    boxes = list(project.boxes.all())
    if not boxes:
        raise ValidationError({"boxes": ["Add at least one box type before packing."]})
    return {
        "container": {
            "id": str(container.id),
            "name": container.name,
            "length_mm": container.length_mm,
            "width_mm": container.width_mm,
            "height_mm": container.height_mm,
            "max_weight_kg": None
            if container.max_weight_kg is None
            else float(container.max_weight_kg),
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
                "max_load_kg": None
                if box.max_load_kg is None
                else float(box.max_load_kg),
                "allow_rotation": box.allow_rotation,
            }
            for box in boxes
        ],
    }


class ProjectListCreateView(APIView):
    def get(self, request):
        queryset = (
            Project.objects.filter(owner=request.user)
            .annotate(box_count=Count("boxes"))
            .prefetch_related("containers")
        )
        paginator = self.pagination_class()
        page = paginator.paginate_queryset(queryset, request)
        return paginator.get_paginated_response(ProjectSerializer(page, many=True).data)

    def post(self, request):
        serializer = ProjectSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        project = serializer.save(owner=request.user)
        project.box_count = 0
        return Response(ProjectSerializer(project).data, status=status.HTTP_201_CREATED)

    @staticmethod
    def pagination_class():
        from rest_framework.pagination import PageNumberPagination

        return PageNumberPagination()


class ProjectDetailView(APIView):
    def get_object(self, request, project_id):
        return get_object_or_404(
            Project.objects.filter(owner=request.user)
            .annotate(box_count=Count("boxes"))
            .prefetch_related("containers"),
            id=project_id,
        )

    def get(self, request, project_id):
        return Response(ProjectSerializer(self.get_object(request, project_id)).data)

    def patch(self, request, project_id):
        project = self.get_object(request, project_id)
        serializer = ProjectSerializer(project, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    def delete(self, request, project_id):
        self.get_object(request, project_id).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class ContainerPresetListView(APIView):
    def get(self, request):
        return Response(
            ContainerPresetSerializer(ContainerPreset.objects.all(), many=True).data
        )


class ProjectContainerView(APIView):
    def get(self, request, project_id):
        project = owned_project(request, project_id)
        return Response(
            ContainerSerializer(get_object_or_404(project.containers.all())).data
        )

    @transaction.atomic
    def put(self, request, project_id):
        project = (
            Project.objects.select_for_update()
            .filter(id=project_id, owner=request.user)
            .first()
        )
        if not project:
            return Response(status=status.HTTP_404_NOT_FOUND)
        if project.containers.count() > 1:
            raise ValidationError(
                {
                    "container": [
                        "This project has multiple containers; v1 requires exactly one."
                    ]
                }
            )
        existing = project.containers.first()
        serializer = ContainerSerializer(existing, data=request.data)
        serializer.is_valid(raise_exception=True)
        container = serializer.save(project=project)
        return Response(
            ContainerSerializer(container).data,
            status=status.HTTP_200_OK if existing else status.HTTP_201_CREATED,
        )

    def patch(self, request, project_id):
        project = owned_project(request, project_id)
        container = get_object_or_404(project.containers.all())
        serializer = ContainerSerializer(container, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


class BoxListCreateView(APIView):
    def get(self, request, project_id):
        project = owned_project(request, project_id)
        return Response(BoxSerializer(project.boxes.all(), many=True).data)

    def post(self, request, project_id):
        project = owned_project(request, project_id)
        serializer = BoxSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        box = serializer.save(project=project)
        return Response(BoxSerializer(box).data, status=status.HTTP_201_CREATED)


class BoxDetailView(APIView):
    def get_object(self, request, project_id, box_id):
        project = owned_project(request, project_id)
        return get_object_or_404(project.boxes.all(), id=box_id)

    def get(self, request, project_id, box_id):
        return Response(
            BoxSerializer(self.get_object(request, project_id, box_id)).data
        )

    def patch(self, request, project_id, box_id):
        box = self.get_object(request, project_id, box_id)
        serializer = BoxSerializer(box, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    def delete(self, request, project_id, box_id):
        self.get_object(request, project_id, box_id).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class BoxBulkCreateView(APIView):
    @transaction.atomic
    def post(self, request, project_id):
        project = owned_project(request, project_id)
        data = (
            request.data.get("boxes")
            if isinstance(request.data, dict)
            else request.data
        )
        serializer = BoxSerializer(data=data, many=True)
        serializer.is_valid(raise_exception=True)
        boxes = serializer.save(project=project)
        return Response(
            BoxSerializer(boxes, many=True).data, status=status.HTTP_201_CREATED
        )


class AlgorithmListView(APIView):
    def get(self, request):
        return Response(registry.metadata())


class PackingJobListCreateView(APIView):
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "jobs"

    def get(self, request, project_id):
        project = owned_project(request, project_id)
        queryset = project.packing_jobs.select_related("layout").all()
        paginator = ProjectListCreateView.pagination_class()
        page = paginator.paginate_queryset(queryset, request)
        return paginator.get_paginated_response(
            PackingJobSerializer(page, many=True).data
        )

    def post(self, request, project_id):
        require_verified(request.user)
        project = owned_project(request, project_id)
        serializer = PackingJobCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        snapshot = make_snapshot(project)
        job = PackingJob.objects.create(
            project=project,
            created_by=request.user,
            algorithm=serializer.validated_data["algorithm"],
            parameters=serializer.validated_data["parameters"],
            input_snapshot=snapshot,
        )
        try:
            task = run_packing_job.delay(str(job.id))
        except Exception as exc:
            job.status = PackingJob.Status.FAILED
            job.error_message = (
                "The packing worker is unavailable. Please retry shortly."
            )
            job.finished_at = timezone.now()
            job.save(
                update_fields=["status", "error_message", "finished_at", "updated_at"]
            )
            raise ServiceUnavailable(job.error_message) from exc
        job.celery_task_id = task.id
        job.save(update_fields=["celery_task_id", "updated_at"])
        job.refresh_from_db()
        return Response(PackingJobSerializer(job).data, status=status.HTTP_202_ACCEPTED)


class PackingJobDetailView(APIView):
    def get_object(self, request, job_id):
        return get_object_or_404(
            PackingJob.objects.select_related("layout"),
            id=job_id,
            project__owner=request.user,
        )

    def get(self, request, job_id):
        return Response(PackingJobSerializer(self.get_object(request, job_id)).data)


class PackingJobCancelView(PackingJobDetailView):
    def post(self, request, job_id):
        job = self.get_object(request, job_id)
        if job.status not in (PackingJob.Status.QUEUED, PackingJob.Status.RUNNING):
            raise ValidationError(
                {"status": ["Only queued or running jobs can be cancelled."]},
                code="invalid_job_state",
            )
        if job.celery_task_id:
            try:
                current_app.control.revoke(job.celery_task_id, terminate=False)
            except Exception:
                logger.warning(
                    "Celery revoke failed for job %s; database cancellation remains active",
                    job.id,
                    exc_info=True,
                )
        job.status = PackingJob.Status.CANCELLED
        job.finished_at = timezone.now()
        job.save(update_fields=["status", "finished_at", "updated_at"])
        publish_notification(
            request.user,
            "packing_job.updated",
            {
                "job_id": str(job.id),
                "status": job.status,
                "progress": job.progress,
                "layout_id": None,
            },
        )
        return Response(PackingJobSerializer(job).data)


class LayoutListCreateView(APIView):
    def get(self, request, project_id):
        project = owned_project(request, project_id)
        queryset = project.layouts.all()
        source = request.query_params.get("source")
        is_saved = request.query_params.get("is_saved")
        if source:
            if source not in Layout.Source.values:
                raise ValidationError({"source": ["Unknown layout source."]})
            queryset = queryset.filter(source=source)
        if is_saved is not None:
            if is_saved.lower() not in {"true", "false"}:
                raise ValidationError({"is_saved": ["Use true or false."]})
            queryset = queryset.filter(is_saved=is_saved.lower() == "true")
        paginator = ProjectListCreateView.pagination_class()
        page = paginator.paginate_queryset(queryset, request)
        return paginator.get_paginated_response(
            LayoutSummarySerializer(page, many=True).data
        )

    def post(self, request, project_id):
        project = owned_project(request, project_id)
        serializer = LayoutWriteSerializer(
            data=request.data, context={"project": project}
        )
        serializer.is_valid(raise_exception=True)
        layout = serializer.save()
        return Response(LayoutSerializer(layout).data, status=status.HTTP_201_CREATED)


class LayoutDetailView(APIView):
    def get_object(self, request, layout_id):
        return get_object_or_404(Layout, id=layout_id, project__owner=request.user)

    def get(self, request, layout_id):
        return Response(LayoutSerializer(self.get_object(request, layout_id)).data)

    def patch(self, request, layout_id):
        layout = self.get_object(request, layout_id)
        serializer = LayoutWriteSerializer(
            layout,
            data=request.data,
            partial=True,
            context={"project": layout.project},
        )
        serializer.is_valid(raise_exception=True)
        layout = serializer.save()
        return Response(LayoutSerializer(layout).data)

    def delete(self, request, layout_id):
        self.get_object(request, layout_id).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class LayoutExportView(LayoutDetailView):
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    def post(self, request, layout_id):
        require_verified(request.user)
        layout = self.get_object(request, layout_id)
        serializer = ExportSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        export_format = serializer.validated_data["format"]
        if export_format == OutputArtifact.Format.CSV:
            artifact = create_csv_artifact(layout)
        elif export_format == OutputArtifact.Format.PDF:
            artifact = create_pdf_artifact(layout)
        else:
            artifact = create_png_artifact(layout, serializer.validated_data["image"])
        return Response(
            OutputArtifactSerializer(artifact, context={"request": request}).data,
            status=status.HTTP_201_CREATED,
        )


class LayoutArtifactListView(LayoutDetailView):
    def get(self, request, layout_id):
        layout = self.get_object(request, layout_id)
        return Response(
            OutputArtifactSerializer(
                layout.artifacts.all(), many=True, context={"request": request}
            ).data
        )


class NotificationListView(APIView):
    def get(self, request):
        queryset = request.user.notifications.all()
        paginator = ProjectListCreateView.pagination_class()
        page = paginator.paginate_queryset(queryset, request)
        return paginator.get_paginated_response(
            NotificationSerializer(page, many=True).data
        )


class NotificationReadView(APIView):
    def post(self, request, notification_id):
        notification = get_object_or_404(
            Notification, id=notification_id, user=request.user
        )
        if notification.read_at is None:
            notification.read_at = timezone.now()
            notification.save(update_fields=["read_at", "updated_at"])
        return Response(NotificationSerializer(notification).data)
