# csv_person_filter.py
from __future__ import annotations

import csv
from pathlib import Path
from typing import Iterable

def normalize_inn(value) -> str:
    """Нормализует РНОКПП: убирает пробелы, дефисы, .0 и лишние нули."""
    if value is None:
        return ""

    text = str(value).strip()
    if not text:
        return ""

    text = text.replace(" ", "").replace("-", "").replace(";", "")
    text = text.replace("\ufeff", "")

    # Если число хранится как 1234567890.0
    if text.endswith(".0"):
        text = text[:-2]

    # Убираем точку, если вдруг "123.0"
    if "." in text:
        text = text.replace(".", "")

    # Если в CSV это число с плавающей запятой, на всякий случай
    if text.isdigit():
        return text

    # Иногда встречаются строки вида "0123456789.0"
    digits = "".join(ch for ch in text if ch.isdigit())
    return digits


def _iter_csv_rows(path: str | Path) -> Iterable[dict[str, str]]:
    csv_path = Path(path)
    with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f, delimiter=";")
        if reader.fieldnames:
            for row in reader:
                yield {str(k).strip(): str(v).strip() if v is not None else "" for k, v in row.items()}
            return

        # Если CSV без заголовка, читаем как обычный список
        f.seek(0)
        file_rows = csv.reader(f, delimiter=";")
        for raw in file_rows:
            if not raw:
                continue
            row = {f"col_{idx}": str(cell).strip() for idx, cell in enumerate(raw)}
            yield row


def load_person_inns_from_csv(path: str | Path) -> list[str]:
    """
    Читает CSV и возвращает список нормализованных РНОКПП.
    Поддерживает столбцы: РНОКПП, INN, inn, tax_id, tax, person_inn.
    """
    values: set[str] = set()

    for row in _iter_csv_rows(path):
        for key in (
            "РНОКПП",
            "INN",
            "inn",
            "ИНН",
            "tax_id",
            "tax",
            "person_inn",
            "РНОКПП_norm",
        ):
            if key in row:
                inn = normalize_inn(row.get(key))
                if inn and len(inn) >= 10:
                    values.add(inn)
                break

        # Если заголовков нет или колонки не найдены — пробуем первый столбец
        if not values:
            for row in _iter_csv_rows(path):
                for cell in row.values():
                    inn = normalize_inn(cell)
                    if inn and len(inn) >= 10:
                        values.add(inn)
                if values:
                    break

    return sorted(values)


class CsvPersonFilter:
    def __init__(self):
        self.path: str | None = None
        self.inn_values: list[str] = []
        self.enabled: bool = False

    def load(self, path: str | Path) -> list[str]:
        self.path = str(path)
        self.inn_values = load_person_inns_from_csv(path)
        self.enabled = bool(self.inn_values)
        return self.inn_values

    def clear(self) -> None:
        self.path = None
        self.inn_values = []
        self.enabled = False
