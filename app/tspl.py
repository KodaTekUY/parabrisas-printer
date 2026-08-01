import re

from .models import (
    BarcodeElement,
    BoxElement,
    LineElement,
    PrintDocument,
    QrElement,
    TextElement,
)


def mm_to_dots(value: float, dpi: int) -> int:
    return round(value * dpi / 25.4)


def sanitize_tspl_text(value: str) -> str:
    value = re.sub(r"[\x00-\x1f\x7f]+", " ", value)
    return value.replace('"', "'").replace("\\", "/").strip()


def compile_tspl(
    document: PrintDocument,
    *,
    dpi: int = 203,
    encoding: str = "utf-8",
    codepage: str = "UTF-8",
) -> bytes:
    commands = [
        f"SIZE {document.width_mm:g} mm,{document.height_mm:g} mm",
        f"GAP {document.gap_mm:g} mm,0 mm",
        f"SPEED {document.speed}",
        f"DENSITY {document.density}",
        "DIRECTION 1",
        f"CODEPAGE {sanitize_tspl_text(codepage)}",
        "CLS",
    ]

    for element in document.elements:
        x = mm_to_dots(element.x_mm, dpi)
        y = mm_to_dots(element.y_mm, dpi)
        if isinstance(element, TextElement):
            value = sanitize_tspl_text(element.text)
            commands.append(
                f'TEXT {x},{y},"{element.font}",{element.rotation},'
                f'{element.x_scale},{element.y_scale},"{value}"'
            )
        elif isinstance(element, LineElement):
            width = max(1, mm_to_dots(element.width_mm, dpi))
            height = max(1, mm_to_dots(element.height_mm, dpi))
            commands.append(f"BAR {x},{y},{width},{height}")
        elif isinstance(element, BoxElement):
            x_end = mm_to_dots(element.x_end_mm, dpi)
            y_end = mm_to_dots(element.y_end_mm, dpi)
            thickness = max(1, mm_to_dots(element.thickness_mm, dpi))
            commands.append(f"BOX {x},{y},{x_end},{y_end},{thickness}")
        elif isinstance(element, BarcodeElement):
            value = sanitize_tspl_text(element.value)
            height = max(1, mm_to_dots(element.height_mm, dpi))
            readable = 1 if element.readable else 0
            commands.append(
                f'BARCODE {x},{y},"{element.symbology}",{height},{readable},'
                f'{element.rotation},2,2,"{value}"'
            )
        elif isinstance(element, QrElement):
            value = sanitize_tspl_text(element.value)
            commands.append(
                f'QRCODE {x},{y},{element.ecc},{element.cell},A,{element.rotation},M2,S7,"{value}"'
            )

    commands.append(f"PRINT {document.copies},1")
    return ("\r\n".join(commands) + "\r\n").encode(encoding, errors="replace")
