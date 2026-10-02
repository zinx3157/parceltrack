"""Printable barcode labels (Code 128) and the print sheet.

  GET /api/labels/{parcel_id}.svg          single label as SVG
  GET /api/labels/{parcel_id}/svg?plain=1  barcode only, no shipment block
  GET /labels/{parcel_id}                  print-ready page (opens the print dialog)
  GET /labels/print?ids=1,2,3              print sheet for several parcels
  GET /api/parcels/{id}/barcode.svg        raw barcode SVG for embedding
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..models import Parcel, User
from ..security import current_user
from ..services import barcode
from ..services.receiving import parcel_receiving_state

router = APIRouter(tags=["labels"])


def _get_parcel(db: Session, parcel_id: int) -> Parcel:
    parcel = db.get(Parcel, parcel_id)
    if not parcel:
        raise HTTPException(404, "Parcel not found")
    return parcel


def _label_text(parcel: Parcel, state: dict | None = None) -> str:
    ref = f" / {parcel.client_reference}" if parcel.client_reference else ""
    return f"{parcel.tracking_number}{ref}"


def _svg_response(svg: str, filename: str) -> Response:
    return Response(svg, media_type="image/svg+xml",
                    headers={"Content-Disposition": f'inline; filename="{filename}"'})


@router.get("/api/parcels/{parcel_id}/barcode.svg")
def parcel_barcode(parcel_id: int, _: User = Depends(current_user), db: Session = Depends(get_db)):
    """Just the barcode for the parcel's tracking number (embed-friendly)."""
    parcel = _get_parcel(db, parcel_id)
    if not barcode.is_encodable(parcel.tracking_number):
        raise HTTPException(400, "This tracking number contains characters Code 128 cannot encode")
    svg = barcode.code128_svg(parcel.tracking_number, module_width=settings.label_module_mm)
    return _svg_response(svg, f"{parcel.tracking_number}.svg")


@router.get("/api/labels/{parcel_id}.svg")
def parcel_label(parcel_id: int, plain: bool = False, carton: int | None = None,
                 _: User = Depends(current_user), db: Session = Depends(get_db)):
    """A full label: barcode + shipment block, sized for a 100x60 mm label.

    Add ``?carton=2`` for a specific box of a multi-carton shipment.
    """
    parcel = _get_parcel(db, parcel_id)
    return _svg_response(_label_svg(db, parcel, plain=plain, carton_no=carton),
                         f"label-{parcel.tracking_number}.svg")


def _label_svg(db: Session, parcel: Parcel, *, plain: bool = False,
               carton_no: int | None = None) -> str:
    state = parcel_receiving_state(db, parcel)
    width, height = settings.label_width_mm, settings.label_height_mm
    barcode_width = width - 12
    barcode_height = 16.0
    shown = parcel.barcode or parcel.tracking_number
    if not barcode.is_encodable(shown):
        shown = parcel.tracking_number
    inner = barcode.code128_svg(shown, module_width=settings.label_module_mm,
                                height=barcode_height, show_text=True, text=shown,
                                font_size=3.4)
    # crop the SVG's own viewBox into the label coordinates
    inner_body = inner.split(">", 1)[1].rsplit("</svg>", 1)[0]
    inner_width = len(barcode.code128_bits(shown)) * settings.label_module_mm

    def line(y: float, size: float, text: str, weight: str = "normal") -> str:
        return (f'<text x="6" y="{y:.2f}" font-family="Helvetica, Arial, sans-serif" '
                f'font-size="{size:.2f}" font-weight="{weight}" fill="#000">{_xml(text)}</text>')

    cartons = state["cartons_expected"]
    if cartons > 1:
        shown_carton = carton_no if carton_no else min(
            state["cartons_received"] + (0 if state["complete"] else 1), cartons)
        shown_carton = max(1, min(int(shown_carton), cartons))
        carton_line = f"Carton {shown_carton} of {cartons}"
    else:
        carton_line = ""
    body = [
        f'<rect width="{width}" height="{height}" fill="#fff"/>',
        f'<rect x="0.4" y="0.4" width="{width - 0.8:.2f}" height="{height - 0.8:.2f}" '
        f'fill="none" stroke="#000" stroke-width="0.4"/>',
        line(6.5, 3.2, settings.company_name.upper(), "bold"),
        line(11.0, 3.1, f"{parcel.carrier.upper()}  |  {parcel.tracking_number}", "bold"),
        f'<g transform="translate(6,13.5) scale({(barcode_width / inner_width) if inner_width else 1:.4f})">{inner_body}</g>',
        line(36.5, 3.2, f"REF: {parcel.client_reference or '—'}"
                        f"   {parcel.client.name if parcel.client else '—'}", "bold"),
        line(41.0, 2.9, f"{(parcel.description or '')[:52]}"),
        line(45.5, 2.9, f"Dest: {parcel.destination[:28] or '—'}"
                        + (f"   {carton_line}" if carton_line else "")),
        line(50.0, 2.9, f"Store: {parcel.storage_location or '—'}"
                        f"   ETA: {parcel.eta.date().isoformat() if parcel.eta else '—'}"),
        line(54.5, 2.6, f"Printed {__import__('datetime').datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC"),
    ]
    if plain:
        body = [f'<rect width="{width}" height="22" fill="#fff"/>',
                f'<g transform="translate(6,3) scale({(barcode_width / inner_width) if inner_width else 1:.4f})">{inner_body}</g>']
        return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}mm" height="22mm" '
                f'viewBox="0 0 {width} 22">{"".join(body)}</svg>')
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}mm" height="{height}mm" '
            f'viewBox="0 0 {width} {height}">{"".join(body)}</svg>')


def _xml(text) -> str:
    return (str(text or "").replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def _print_sheet(db: Session, parcels: list[Parcel], title: str) -> str:
    labels = []
    for parcel in parcels:
        # one label per carton so a box never arrives without its own label
        cartons = max(1, parcel_receiving_state(db, parcel)["cartons_expected"])
        for carton_no in range(1, cartons + 1):
            svg = _label_svg(db, parcel, carton_no=carton_no if cartons > 1 else None)
            labels.append(f'<div class="label">{svg}</div>')
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>{_xml(title)}</title>
<style>
  @page {{ size: {settings.label_width_mm}mm {settings.label_height_mm}mm; margin: 0; }}
  body {{ margin: 0; font-family: Helvetica, Arial, sans-serif; background: #eef1f6; }}
  .bar {{ position: sticky; top: 0; background: #0f172a; color: #fff; padding: 10px 14px;
          display: flex; align-items: center; gap: 12px; }}
  .bar button {{ font: inherit; padding: 7px 14px; border: 0; border-radius: 8px;
                 background: #2563eb; color: #fff; cursor: pointer; font-weight: 600; }}
  .bar span {{ opacity: .8; font-size: 13px; }}
  .sheet {{ display: flex; flex-wrap: wrap; gap: 6mm; padding: 8mm; justify-content: flex-start; }}
  .label {{ background: #fff; box-shadow: 0 2px 10px rgba(15,23,42,.18);
            width: {settings.label_width_mm}mm; height: {settings.label_height_mm}mm; }}
  .label svg {{ display: block; }}
  @media print {{
    body {{ background: #fff; }}
    .bar {{ display: none; }}
    .sheet {{ gap: 0; padding: 0; }}
    .label {{ box-shadow: none; page-break-after: always; }}
    .label:last-child {{ page-break-after: auto; }}
  }}
</style></head>
<body>
  <div class="bar">
    <button onclick="window.print()">Print {len(parcels)} label(s)</button>
    <span>Label size {settings.label_width_mm:g} × {settings.label_height_mm:g} mm — set your printer
      to 100% scale and disable “fit to page”. Barcode: Code 128.</span>
  </div>
  <div class="sheet">{''.join(labels)}</div>
  <script>window.addEventListener("load", function () {{ setTimeout(function () {{ window.print(); }}, 400); }});</script>
</body></html>"""


@router.get("/labels/print", response_class=HTMLResponse)
def print_sheet(ids: str = Query(..., description="comma separated parcel ids"),
                _: User = Depends(current_user), db: Session = Depends(get_db)):
    try:
        parcel_ids = [int(x) for x in ids.replace(" ", "").split(",") if x]
    except ValueError:
        raise HTTPException(400, "ids must be a comma-separated list of numbers")
    if not parcel_ids:
        raise HTTPException(400, "No parcels selected")
    if len(parcel_ids) > 200:
        raise HTTPException(400, "Print at most 200 labels at a time")
    parcels = db.query(Parcel).filter(Parcel.id.in_(parcel_ids)).all()
    if not parcels:
        raise HTTPException(404, "No matching parcels")
    order = {pid: i for i, pid in enumerate(parcel_ids)}
    parcels.sort(key=lambda p: order.get(p.id, 999))
    return HTMLResponse(_print_sheet(db, parcels, f"Labels — {len(parcels)} parcel(s)"))


@router.get("/labels/{parcel_id}", response_class=HTMLResponse)
def print_single(parcel_id: int, _: User = Depends(current_user), db: Session = Depends(get_db)):
    parcel = _get_parcel(db, parcel_id)
    return HTMLResponse(_print_sheet(db, [parcel], f"Label {parcel.tracking_number}"))
