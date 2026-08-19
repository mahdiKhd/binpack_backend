from django.apps import AppConfig


class PackingConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "packing"

    def ready(self):
        from . import algorithms  # noqa: F401
