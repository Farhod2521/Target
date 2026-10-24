import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from io import BytesIO
from typing import Final
from xml.sax.saxutils import escape
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

Cell = str | int | None
_CONTROL: Final = re.compile("[\\x00-\\x08\\x0b\\x0c\\x0e-\\x1f]")
_CELL_LIMIT: Final = 32767
_SHEET_FORBIDDEN: Final = re.compile("[\\[\\]:*?/\\\\]")
_SHEET_LIMIT: Final = 31
_STAMP: Final = (1980, 1, 1, 0, 0, 0)
_HEADER_STYLE: Final = 1


@dataclass(frozen=True, slots=True)
class Column:
    header: str
    width: int = 18


def workbook(
    *, sheet: str, columns: Sequence[Column], rows: Iterable[Sequence[Cell]]
) -> bytes:
    heading = [column.header for column in columns]
    body = [_row(index=1, values=heading, style=_HEADER_STYLE)]
    body += [
        _row(index=number, values=_fit(values, len(columns)))
        for number, values in enumerate(rows, start=2)
    ]
    return _zip(
        {
            "[Content_Types].xml": _CONTENT_TYPES,
            "_rels/.rels": _ROOT_RELS,
            "xl/workbook.xml": _workbook_xml(sheet),
            "xl/_rels/workbook.xml.rels": _WORKBOOK_RELS,
            "xl/styles.xml": _STYLES,
            "xl/worksheets/sheet1.xml": _sheet_xml(columns=columns, body=body),
        }
    )


def _zip(parts: dict[str, str]) -> bytes:
    stream = BytesIO()
    with ZipFile(stream, "w", ZIP_DEFLATED) as archive:
        for name, content in parts.items():
            archive.writestr(_entry(name), content)
    return stream.getvalue()


def _entry(name: str) -> ZipInfo:
    info = ZipInfo(name, date_time=_STAMP)
    info.compress_type = ZIP_DEFLATED
    return info


def _fit(values: Sequence[Cell], width: int) -> list[Cell]:
    row = list(values[:width])
    return row + [None] * (width - len(row))


def _row(*, index: int, values: Sequence[Cell], style: int = 0) -> str:
    cells = [
        _cell(reference=f"{_letter(column)}{index}", value=value, style=style)
        for column, value in enumerate(values)
        if value is not None and value != ""
    ]
    return f'''<row r="{index}">{"".join(cells)}</row>'''


def _cell(*, reference: str, value: Cell, style: int) -> str:
    attrs = f' s="{style}"' if style else ""
    if isinstance(value, bool):
        return _inline(reference=reference, attrs=attrs, value=str(value))
    if isinstance(value, int):
        return f'<c r="{reference}"{attrs}><v>{value}</v></c>'
    return _inline(reference=reference, attrs=attrs, value=str(value))


def _inline(*, reference: str, attrs: str, value: str) -> str:
    return f'<c r="{reference}"{attrs} t="inlineStr"><is><t xml:space="preserve">{_text(value)}</t></is></c>'


def _text(value: str) -> str:
    return escape(_CONTROL.sub("", value)[:_CELL_LIMIT])


def _letter(index: int) -> str:
    name = ""
    while index >= 0:
        name = chr(ord("A") + index % 26) + name
        index = index // 26 - 1
    return name


def _sheet_name(name: str) -> str:
    cleaned = _SHEET_FORBIDDEN.sub(" ", name).strip()[:_SHEET_LIMIT]
    return escape(cleaned or "Sheet1")


def _sheet_xml(*, columns: Sequence[Column], body: Sequence[str]) -> str:
    last = _letter(max(len(columns) - 1, 0))
    widths = "".join(
        (
            f'<col min="{index}" max="{index}" width="{column.width}" customWidth="1"/>'
            for index, column in enumerate(columns, start=1)
        )
    )
    return f'''{_DECLARATION}<worksheet xmlns="{_MAIN_NS}"><dimension ref="A1:{last}{len(body)}"/><sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews><cols>{widths}</cols><sheetData>{"".join(body)}</sheetData><autoFilter ref="A1:{last}{len(body)}"/></worksheet>'''


def _workbook_xml(sheet: str) -> str:
    return f'{_DECLARATION}<workbook xmlns="{_MAIN_NS}" xmlns:r="{_REL_NS}"><sheets><sheet name="{_sheet_name(sheet)}" sheetId="1" r:id="rId1"/></sheets></workbook>'


_DECLARATION: Final = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
_MAIN_NS: Final = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_REL_NS: Final = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_PKG_REL_NS: Final = "http://schemas.openxmlformats.org/package/2006/relationships"
_SHEET_TYPE: Final = "application/vnd.openxmlformats-officedocument.spreadsheetml"
_RELS_TYPE: Final = "application/vnd.openxmlformats-package.relationships+xml"
_CONTENT_TYPES: Final = f'{_DECLARATION}<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="{_RELS_TYPE}"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="{_SHEET_TYPE}.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="{_SHEET_TYPE}.worksheet+xml"/><Override PartName="/xl/styles.xml" ContentType="{_SHEET_TYPE}.styles+xml"/></Types>'
_ROOT_RELS: Final = f'{_DECLARATION}<Relationships xmlns="{_PKG_REL_NS}"><Relationship Id="rId1" Type="{_REL_NS}/officeDocument" Target="xl/workbook.xml"/></Relationships>'
_WORKBOOK_RELS: Final = f'{_DECLARATION}<Relationships xmlns="{_PKG_REL_NS}"><Relationship Id="rId1" Type="{_REL_NS}/worksheet" Target="worksheets/sheet1.xml"/><Relationship Id="rId2" Type="{_REL_NS}/styles" Target="styles.xml"/></Relationships>'
_STYLES: Final = f'{_DECLARATION}<styleSheet xmlns="{_MAIN_NS}"><fonts count="2"><font><sz val="11"/><name val="Calibri"/></font><font><b/><sz val="11"/><name val="Calibri"/></font></fonts><fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill></fills><borders count="1"><border/></borders><cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs><cellXfs count="2"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/><xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/></cellXfs></styleSheet>'
__all__ = ["Cell", "Column", "workbook"]
