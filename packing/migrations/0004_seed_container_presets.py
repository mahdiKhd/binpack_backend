from django.db import migrations


PRESETS = [
    {
        "key": "iso_20ft",
        "display_name": "20ft ISO Standard Container",
        "length_mm": 5898,
        "width_mm": 2352,
        "height_mm": 2393,
        "max_weight_kg": "28200.000",
        "category": "shipping",
    },
    {
        "key": "iso_40ft",
        "display_name": "40ft ISO Standard Container",
        "length_mm": 12032,
        "width_mm": 2352,
        "height_mm": 2393,
        "max_weight_kg": "26700.000",
        "category": "shipping",
    },
    {
        "key": "euro_pallet_box",
        "display_name": "Euro Pallet Box",
        "length_mm": 1200,
        "width_mm": 800,
        "height_mm": 1000,
        "max_weight_kg": "1000.000",
        "category": "pallet box",
    },
    {
        "key": "parcel_medium",
        "display_name": "Medium Parcel",
        "length_mm": 600,
        "width_mm": 400,
        "height_mm": 400,
        "max_weight_kg": "30.000",
        "category": "parcel",
    },
    {
        "key": "moving_box",
        "display_name": "Standard Moving Box",
        "length_mm": 580,
        "width_mm": 400,
        "height_mm": 350,
        "max_weight_kg": "25.000",
        "category": "moving box",
    },
]


def seed_presets(apps, schema_editor):
    ContainerPreset = apps.get_model("packing", "ContainerPreset")
    for preset in PRESETS:
        ContainerPreset.objects.update_or_create(key=preset["key"], defaults=preset)


def remove_presets(apps, schema_editor):
    ContainerPreset = apps.get_model("packing", "ContainerPreset")
    ContainerPreset.objects.filter(key__in=[item["key"] for item in PRESETS]).delete()


class Migration(migrations.Migration):
    dependencies = [("packing", "0003_alter_box_count_alter_box_height_mm_and_more")]

    operations = [migrations.RunPython(seed_presets, remove_presets)]
