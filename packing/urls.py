from django.urls import path

from .views import (
    AlgorithmListView,
    BoxBulkCreateView,
    BoxDetailView,
    BoxListCreateView,
    ContainerPresetListView,
    LayoutArtifactListView,
    LayoutDetailView,
    LayoutExportView,
    LayoutListCreateView,
    NotificationListView,
    NotificationReadView,
    PackingJobCancelView,
    PackingJobDetailView,
    PackingJobListCreateView,
    ProjectContainerView,
    ProjectDetailView,
    ProjectListCreateView,
)

urlpatterns = [
    path("projects", ProjectListCreateView.as_view(), name="project-list"),
    path(
        "projects/<uuid:project_id>", ProjectDetailView.as_view(), name="project-detail"
    ),
    path(
        "container-presets",
        ContainerPresetListView.as_view(),
        name="container-preset-list",
    ),
    path(
        "projects/<uuid:project_id>/container",
        ProjectContainerView.as_view(),
        name="project-container",
    ),
    path(
        "projects/<uuid:project_id>/boxes", BoxListCreateView.as_view(), name="box-list"
    ),
    path(
        "projects/<uuid:project_id>/boxes/bulk",
        BoxBulkCreateView.as_view(),
        name="box-bulk",
    ),
    path(
        "projects/<uuid:project_id>/boxes/<uuid:box_id>",
        BoxDetailView.as_view(),
        name="box-detail",
    ),
    path("algorithms", AlgorithmListView.as_view(), name="algorithm-list"),
    path(
        "projects/<uuid:project_id>/packing-jobs",
        PackingJobListCreateView.as_view(),
        name="packing-job-list",
    ),
    path(
        "packing-jobs/<uuid:job_id>",
        PackingJobDetailView.as_view(),
        name="packing-job-detail",
    ),
    path(
        "packing-jobs/<uuid:job_id>/cancel",
        PackingJobCancelView.as_view(),
        name="packing-job-cancel",
    ),
    path(
        "projects/<uuid:project_id>/layouts",
        LayoutListCreateView.as_view(),
        name="layout-list",
    ),
    path("layouts/<uuid:layout_id>", LayoutDetailView.as_view(), name="layout-detail"),
    path(
        "layouts/<uuid:layout_id>/export",
        LayoutExportView.as_view(),
        name="layout-export",
    ),
    path(
        "layouts/<uuid:layout_id>/artifacts",
        LayoutArtifactListView.as_view(),
        name="layout-artifacts",
    ),
    path("notifications", NotificationListView.as_view(), name="notification-list"),
    path(
        "notifications/<uuid:notification_id>/read",
        NotificationReadView.as_view(),
        name="notification-read",
    ),
]
