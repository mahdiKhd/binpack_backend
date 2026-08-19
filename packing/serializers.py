from rest_framework import serializers

from users.serializers import StrictFieldsMixin

from .algorithms import registry
from .geometry import validate_and_measure
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


class ProjectSerializer(StrictFieldsMixin, serializers.ModelSerializer):
    box_count = serializers.IntegerField(read_only=True)
    container = serializers.SerializerMethodField()

    class Meta:
        model = Project
        fields = (
            "id",
            "name",
            "description",
            "box_count",
            "container",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "box_count", "container", "created_at", "updated_at")

    def get_container(self, obj):
        container = next(iter(obj.containers.all()), None)
        return ContainerSerializer(container).data if container else None


class ContainerPresetSerializer(serializers.ModelSerializer):
    class Meta:
        model = ContainerPreset
        fields = (
            "key",
            "display_name",
            "length_mm",
            "width_mm",
            "height_mm",
            "max_weight_kg",
            "category",
        )


class ContainerSerializer(StrictFieldsMixin, serializers.ModelSerializer):
    class Meta:
        model = Container
        fields = (
            "id",
            "name",
            "length_mm",
            "width_mm",
            "height_mm",
            "max_weight_kg",
            "based_on_preset",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "created_at", "updated_at")
        extra_kwargs = {
            "max_weight_kg": {"allow_null": True, "required": False},
            "based_on_preset": {"allow_null": True, "required": False},
        }

    def validate_based_on_preset(self, value):
        if value and not ContainerPreset.objects.filter(key=value).exists():
            raise serializers.ValidationError("Unknown container preset key.")
        return value


class BoxSerializer(StrictFieldsMixin, serializers.ModelSerializer):
    class Meta:
        model = Box
        fields = (
            "id",
            "label",
            "length_mm",
            "width_mm",
            "height_mm",
            "weight_kg",
            "count",
            "color",
            "is_stackable",
            "max_load_kg",
            "allow_rotation",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "created_at", "updated_at")
        extra_kwargs = {"max_load_kg": {"allow_null": True, "required": False}}


class PackingJobCreateSerializer(StrictFieldsMixin, serializers.Serializer):
    algorithm = serializers.CharField(max_length=80)
    parameters = serializers.JSONField(required=False, default=dict)

    def validate(self, attrs):
        definition = registry.get(attrs["algorithm"])
        attrs["parameters"] = definition.validate(attrs.get("parameters"))
        return attrs


class LayoutSummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = Layout
        fields = (
            "id",
            "project",
            "source",
            "job",
            "name",
            "is_saved",
            "metrics",
            "created_at",
            "updated_at",
        )


class PackingJobSerializer(serializers.ModelSerializer):
    layout_id = serializers.SerializerMethodField()

    class Meta:
        model = PackingJob
        fields = (
            "id",
            "project",
            "algorithm",
            "parameters",
            "status",
            "progress",
            "error_message",
            "layout_id",
            "created_at",
            "started_at",
            "finished_at",
        )

    def get_layout_id(self, obj):
        try:
            return obj.layout.id
        except Layout.DoesNotExist:
            return None


class LayoutSerializer(serializers.ModelSerializer):
    class Meta:
        model = Layout
        fields = (
            "id",
            "project",
            "source",
            "job",
            "name",
            "is_saved",
            "placements",
            "metrics",
            "created_at",
            "updated_at",
        )


class LayoutWriteSerializer(StrictFieldsMixin, serializers.Serializer):
    name = serializers.CharField(max_length=200, required=False, allow_blank=True)
    is_saved = serializers.BooleanField(required=False)
    placements = serializers.JSONField(required=False)
    respect_stacking = serializers.BooleanField(
        required=False, default=False, write_only=True
    )

    def validate(self, attrs):
        if not self.instance and "placements" not in attrs:
            raise serializers.ValidationError(
                {"placements": ["This field is required."]}
            )
        if attrs.get("is_saved") and not attrs.get(
            "name", getattr(self.instance, "name", "")
        ):
            raise serializers.ValidationError(
                {"name": ["A saved layout must have a name."]}
            )
        if "placements" in attrs:
            payload, metrics = validate_and_measure(
                self.context["project"],
                attrs["placements"],
                respect_stacking=attrs.pop("respect_stacking", False),
            )
            attrs["placements"] = payload
            attrs["metrics"] = metrics
        else:
            attrs.pop("respect_stacking", None)
        return attrs

    def create(self, validated_data):
        return Layout.objects.create(
            project=self.context["project"],
            source=Layout.Source.MANUAL,
            **validated_data,
        )

    def update(self, instance, validated_data):
        for field, value in validated_data.items():
            setattr(instance, field, value)
        instance.save(update_fields=[*validated_data.keys(), "updated_at"])
        return instance


class OutputArtifactSerializer(serializers.ModelSerializer):
    url = serializers.SerializerMethodField()

    class Meta:
        model = OutputArtifact
        fields = ("id", "layout", "format", "url", "created_at")

    def get_url(self, obj):
        request = self.context.get("request")
        return request.build_absolute_uri(obj.file.url) if request else obj.file.url


class ExportSerializer(StrictFieldsMixin, serializers.Serializer):
    format = serializers.ChoiceField(choices=OutputArtifact.Format.choices)
    image = serializers.ImageField(required=False, write_only=True)

    def validate(self, attrs):
        if attrs["format"] == OutputArtifact.Format.PNG and not attrs.get("image"):
            raise serializers.ValidationError(
                {"image": ["Upload the frontend canvas image for PNG export."]}
            )
        if attrs["format"] != OutputArtifact.Format.PNG and attrs.get("image"):
            raise serializers.ValidationError(
                {"image": ["An image is accepted only for PNG export."]}
            )
        return attrs


class NotificationSerializer(serializers.ModelSerializer):
    is_read = serializers.SerializerMethodField()

    class Meta:
        model = Notification
        fields = ("id", "event", "payload", "is_read", "created_at")

    def get_is_read(self, obj):
        return obj.read_at is not None
