from app.models import PrintDocument
from app.tspl import compile_tspl, mm_to_dots, sanitize_tspl_text


def test_mm_to_dots_uses_203_dpi() -> None:
    assert mm_to_dots(108, 203) == 863


def test_compile_tspl_sanitizes_text_and_prints_document() -> None:
    document = PrintDocument.model_validate(
        {
            "version": 1,
            "widthMm": 108,
            "heightMm": 60,
            "gapMm": 0,
            "copies": 1,
            "speed": 4,
            "density": 8,
            "elements": [
                {
                    "type": "text",
                    "xMm": 4,
                    "yMm": 4,
                    "text": 'Cliente "A"\nCLS',
                    "font": "3",
                    "xScale": 1,
                    "yScale": 1,
                    "rotation": 0,
                },
                {
                    "type": "line",
                    "xMm": 4,
                    "yMm": 10,
                    "widthMm": 100,
                    "heightMm": 0.4,
                },
            ],
        }
    )

    output = compile_tspl(document).decode("utf-8")
    assert "SIZE 108 mm,60 mm" in output
    assert 'Cliente \'A\' CLS' in output
    assert output.count("\nCLS\r") == 1
    assert output.endswith("PRINT 1,1\r\n")


def test_sanitize_tspl_text_removes_command_breaks() -> None:
    assert sanitize_tspl_text('A\r\nPRINT 9,9"') == "A PRINT 9,9'"
