from django.contrib import admin

from .models import (
    Box,
    Container,
    ContainerPreset,
    Layout,
    Notification,
    OutputArtifact,
    PackingJob,
    Project,
)

admin.site.register(
    [
        Project,
        Container,
        ContainerPreset,
        Box,
        PackingJob,
        Layout,
        OutputArtifact,
        Notification,
    ]
)
