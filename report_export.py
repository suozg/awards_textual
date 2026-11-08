"""Экспорт таблицы отчёта в CSV и XLSX."""

from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Sequence


def _make_export_path(extension: str, output_dir: str | Path | None = None) -> Path:
    directory = Path(output_dir) if output_dir else Path.cwd()
    directory.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return directory / f"zvit_{timestamp}.{extension}"


def export_report_csv(
    headers: Sequence[str],
    rows: Iterable[Sequence[Any]],
    output_dir: str | Path | None = None,
) -> Path:
    """Сохраняет строки отчёта в CSV с BOM для корректного открытия в Excel."""
    path = _make_export_path("csv", output_dir)

    with path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.writer(file, delimiter=";")
        writer.writerow(headers)
        writer.writerows(rows)

    return path


def export_report_xlsx(
    headers: Sequence[str],
    rows: Iterable[Sequence[Any]],
    output_dir: str | Path | None = None,
) -> Path:
    """Сохраняет строки отчёта в XLSX."""
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Alignment, Font, PatternFill
    except ImportError as exc:
        raise RuntimeError(
            "Для экспорта XLSX установите зависимость: pip install openpyxl"
        ) from exc

    path = _make_export_path("xlsx", output_dir)
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Звіт"

    sheet.append(list(headers))
    for row in rows:
        sheet.append(list(row))

    header_fill = PatternFill(
        fill_type="solid",
        fgColor="D9EAD3",
    )
    for cell in sheet[1]:
        cell.font = Font(bold=True)
        cell.fill = header_fill
        cell.alignment = Alignment(vertical="center", wrap_text=True)

    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = sheet.dimensions

    for column_cells in sheet.columns:
        column_letter = column_cells[0].column_letter
        max_length = max(
            (len(str(cell.value)) if cell.value is not None else 0)
            for cell in column_cells
        )
        sheet.column_dimensions[column_letter].width = min(max(max_length + 2, 12), 60)

    workbook.save(path)
    return path