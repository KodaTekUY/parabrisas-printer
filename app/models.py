from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class TextElement(StrictModel):
    type: Literal["text"]
    x_mm: float = Field(alias="xMm", ge=0, le=1778)
    y_mm: float = Field(alias="yMm", ge=0, le=1778)
    text: str = Field(min_length=1, max_length=500)
    font: Literal["1", "2", "3", "4", "5", "6", "7", "8"] = "3"
    x_scale: int = Field(default=1, alias="xScale", ge=1, le=10)
    y_scale: int = Field(default=1, alias="yScale", ge=1, le=10)
    rotation: Literal[0, 90, 180, 270] = 0


class LineElement(StrictModel):
    type: Literal["line"]
    x_mm: float = Field(alias="xMm", ge=0, le=1778)
    y_mm: float = Field(alias="yMm", ge=0, le=1778)
    width_mm: float = Field(alias="widthMm", gt=0, le=108)
    height_mm: float = Field(default=0.4, alias="heightMm", gt=0, le=10)


class BoxElement(StrictModel):
    type: Literal["box"]
    x_mm: float = Field(alias="xMm", ge=0, le=1778)
    y_mm: float = Field(alias="yMm", ge=0, le=1778)
    x_end_mm: float = Field(alias="xEndMm", ge=0, le=1778)
    y_end_mm: float = Field(alias="yEndMm", ge=0, le=1778)
    thickness_mm: float = Field(default=0.4, alias="thicknessMm", gt=0, le=10)


class BarcodeElement(StrictModel):
    type: Literal["barcode"]
    x_mm: float = Field(alias="xMm", ge=0, le=1778)
    y_mm: float = Field(alias="yMm", ge=0, le=1778)
    value: str = Field(min_length=1, max_length=200)
    symbology: Literal["128", "39", "EAN13"] = "128"
    height_mm: float = Field(alias="heightMm", gt=0, le=100)
    readable: bool = True
    rotation: Literal[0, 90, 180, 270] = 0


class QrElement(StrictModel):
    type: Literal["qr"]
    x_mm: float = Field(alias="xMm", ge=0, le=1778)
    y_mm: float = Field(alias="yMm", ge=0, le=1778)
    value: str = Field(min_length=1, max_length=1000)
    ecc: Literal["L", "M", "Q", "H"] = "M"
    cell: int = Field(default=4, ge=1, le=10)
    rotation: Literal[0, 90, 180, 270] = 0


PrintElement = Annotated[
    Union[TextElement, LineElement, BoxElement, BarcodeElement, QrElement],
    Field(discriminator="type"),
]


class PrintDocument(StrictModel):
    version: Literal[1]
    width_mm: float = Field(alias="widthMm", gt=0, le=108)
    height_mm: float = Field(alias="heightMm", ge=20, le=1778)
    gap_mm: float = Field(default=0, alias="gapMm", ge=0, le=10)
    copies: int = Field(default=1, ge=1, le=10)
    speed: int = Field(default=4, ge=2, le=6)
    density: int = Field(default=8, ge=0, le=15)
    elements: list[PrintElement] = Field(min_length=1, max_length=300)

    @model_validator(mode="after")
    def elements_fit_document(self) -> "PrintDocument":
        for element in self.elements:
            if element.x_mm > self.width_mm or element.y_mm > self.height_mm:
                raise ValueError("Un elemento queda fuera del documento")
        return self


class ClaimedPrintJob(StrictModel):
    id: str
    document_type: Literal["operativa", "cobro"] = Field(alias="documentType")
    attempts: int = Field(ge=1)
    payload: PrintDocument


class PrintResult(StrictModel):
    agent_id: str = Field(alias="agentId")
    status: Literal["sent", "failed"]
    error: str | None = Field(default=None, min_length=1, max_length=1000)
