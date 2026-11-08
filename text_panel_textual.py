"""Textual-версія вкладки повнотекстового пошуку подань."""
from __future__ import annotations

from sqlcipher3 import dbapi2 as sqlite3
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.css.query import NoMatches
from textual.widgets import Button, DataTable, Input, TextArea

from database_logic_textual import search_presentations


class TextPanel(Vertical):
    """Пошук текстів подань із переглядом вибраного документа."""

    HELP_TEXT = """Пошук подання за текстом

1. Пошук одного слова
   слово
   Знайде усі записи, що містять указане слово.

2. Пошук декількох слів (AND)
   слово1 слово2
   Знайде записи, що містять обидва слова.

3. Пошук з OR
   слово1 OR слово2
   Знайде записи, які містять хоча б одне зі слів.

4. Пошук фрази (у лапках)
   \"точна фраза\"
   Знайде точне співпадіння заданої фрази.

5. Виключення слів (NOT, -)
   слово1 -слово2
   Знайде записи, які містять слово1, але не слово2.

6. Пошук за близькістю слів (NEAR)
   слово1 NEAR/5 слово2
   Слова не далі ніж у 5 словах одне від одного.

7. Пошук за префіксом
   сло*
   Знайде слова, що починаються з «сло».

Введіть запит у поле вище та натисніть «Пошук» або Enter."""

    def __init__(self, conn=None, cursor=None, **kwargs):
        super().__init__(**kwargs)
        self.conn = conn
        self.cursor = cursor
        self.results = []
        self._row_by_id = {}

    def compose(self) -> ComposeResult:
        with Horizontal(id="text-search-row"):
            yield Input(placeholder="Пошуковий запит у текстах подань", id="text-search-query")
            yield Button("Пошук", variant="primary", id="text-search-run")
            yield Button("Очистити", id="text-search-clear")
        with Horizontal(id="text-results-row"):
            yield DataTable(id="text-presentation-list", cursor_type="row", zebra_stripes=True)
            yield TextArea(self.HELP_TEXT, read_only=True, id="text-presentation-body", soft_wrap=True)

    def on_mount(self) -> None:
        table = self.query_one("#text-presentation-list", DataTable)
        table.add_columns("№", "Дата", "Статус")


    def set_database(self, conn, cursor) -> None:
        self.conn, self.cursor = conn, cursor

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "text-search-query":
            self.search()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "text-search-run":
            self.search()
        elif event.button.id == "text-search-clear":
            self.clear_search()

    def search(self) -> None:
        query = self.query_one("#text-search-query", Input).value.strip()
        table = self.query_one("#text-presentation-list", DataTable)
        body = self.query_one("#text-presentation-body", TextArea)
        table.clear()
        body.load_text("")
        self.results = []
        self._row_by_id = {}

        if not self.cursor:
            self._notify("База даних не підключена.", "error")
            return

        try:
            status, results, message = search_presentations(self.cursor, query)

            if status == "EMPTY":
                body.load_text(self.HELP_TEXT)
                self._notify(message, "warning")
                return

            if status == "ERROR":
                self._notify(message, "error")
                return

            self.results = results or []

            presentation_ids = []
            for row in self.results:
                try:
                    presentation_ids.append(int(row[0]))
                except (TypeError, ValueError, IndexError):
                    continue

            if not presentation_ids:
                body.load_text("Не знайдено.\n\n────────────────────────")
                return

            placeholders = ",".join("?" for _ in presentation_ids)
            self.cursor.execute(
                f"""
                SELECT id, registration, date_registration, id_meed
                FROM presentation
                WHERE id IN ({placeholders})
                """,
                presentation_ids,
            )
            presentation_info = {
                row[0]: row[1:] for row in self.cursor.fetchall()
            }

            for row in self.results:
                try:
                    pres_id = int(row[0])
                except (TypeError, ValueError, IndexError):
                    continue

                self._row_by_id[pres_id] = row

                info = presentation_info.get(pres_id)
                if info:
                    registration, date, meed = info

                    if meed is None:
                        presentation_status = "НА РОЗГЛЯДІ"
                    elif str(meed) == "0":
                        presentation_status = "ВІДМОВЛЕНО"
                    else:
                        presentation_status = "ЗАДОВОЛЕНО"

                    table.add_row(
                        str(registration or pres_id),
                        str(date or ""),
                        presentation_status,
                        key=str(pres_id),
                    )

        except sqlite3.Error as exc:
            self._notify(f"Помилка пошуку: {exc}", "error")
            return

        if not self.results:
            body.load_text("Не знайдено.\n\n────────────────────────")

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.data_table.id != "text-presentation-list" or event.row_key is None:
            return
        try:
            pres_id = int(str(event.row_key.value))
            row = self._row_by_id.get(pres_id)
            if row is None:
                return
            self.query_one("#text-presentation-body", TextArea).load_text(str(row[1] or ""))
        except (ValueError, NoMatches) as exc:
            self._notify(f"Не вдалося відкрити подання: {exc}", "error")

    def clear_search(self) -> None:
        self.query_one("#text-search-query", Input).value = ""
        self.query_one("#text-presentation-list", DataTable).clear()
        self.query_one("#text-presentation-body", TextArea).load_text(self.HELP_TEXT)
        self.results = []
        self._row_by_id = {}
        self.query_one("#text-search-query", Input).focus()

    def _notify(self, message: str, severity: str = "information") -> None:
        self.app.notify(message, severity=severity)
