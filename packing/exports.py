import csv
import io
from pathlib import Path

from django.core.files.base import ContentFile
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from .models import OutputArtifact


def create_csv_artifact(layout):
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        [
            "box_id",
            "instance_index",
            "x_mm",
            "y_mm",
            "z_mm",
            "length_mm",
            "width_mm",
            "height_mm",
            "orientation",
        ]
    )
    for placement in layout.placements.get("placements", []):
        p, s = placement["position_mm"], placement["size_mm"]
        writer.writerow(
            [
                placement["box_id"],
                placement["instance_index"],
                p["x"],
                p["y"],
                p["z"],
                s["length"],
                s["width"],
                s["height"],
                placement["orientation"],
            ]
        )
    artifact = OutputArtifact(layout=layout, format=OutputArtifact.Format.CSV)
    artifact.file.save(
        f"layout-{layout.id}.csv",
        ContentFile(buffer.getvalue().encode("utf-8")),
        save=True,
    )
    return artifact


def create_pdf_artifact(layout):
    raw = io.BytesIO()
    pdf = canvas.Canvas(raw, pagesize=A4)
    width, height = A4
    y = height - 50
    pdf.setTitle(layout.name or f"Packing layout {layout.id}")
    pdf.setFont("Helvetica-Bold", 16)
    pdf.drawString(50, y, layout.name or "3D Bin Packing Layout")
    y -= 28
    pdf.setFont("Helvetica", 10)
    for key, value in layout.metrics.items():
        pdf.drawString(50, y, f"{key.replace('_', ' ').title()}: {value}")
        y -= 15
    y -= 10
    pdf.setFont("Helvetica-Bold", 9)
    pdf.drawString(50, y, "Box / instance")
    pdf.drawString(180, y, "Position (mm)")
    pdf.drawString(310, y, "Size (mm)")
    pdf.drawString(445, y, "Orientation")
    y -= 14
    pdf.setFont("Helvetica", 8)
    for item in layout.placements.get("placements", []):
        if y < 45:
            pdf.showPage()
            y = height - 50
            pdf.setFont("Helvetica", 8)
        p, s = item["position_mm"], item["size_mm"]
        pdf.drawString(50, y, f"{item['box_id'][:8]} / {item['instance_index']}")
        pdf.drawString(180, y, f"{p['x']}, {p['y']}, {p['z']}")
        pdf.drawString(310, y, f"{s['length']} x {s['width']} x {s['height']}")
        pdf.drawString(445, y, item["orientation"])
        y -= 13
    pdf.save()
    artifact = OutputArtifact(layout=layout, format=OutputArtifact.Format.PDF)
    artifact.file.save(
        f"layout-{layout.id}.pdf", ContentFile(raw.getvalue()), save=True
    )
    return artifact


def create_png_artifact(layout, image):
    extension = Path(image.name).suffix.lower()
    if extension not in {".png"}:
        extension = ".png"
    artifact = OutputArtifact(layout=layout, format=OutputArtifact.Format.PNG)
    artifact.file.save(f"layout-{layout.id}{extension}", image, save=True)
    return artifact
