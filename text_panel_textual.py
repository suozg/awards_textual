"""Textual-версія вкладки повнотекстового пошуку подань."""
from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, DataTable, Input, Static, TextArea

from config import DEF_FUT_LABEL
from database_logic_textual import search_presentations, get_presentation_info


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
        self.last_message = DEF_FUT_LABEL
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
        table.add_columns("ID подання")

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
        except Exception as exc:
            self._notify(f"Помилка пошуку: {exc}", "error")
            return

        if status == "EMPTY":
            body.load_text(self.HELP_TEXT)
            self._notify(message, "warning")
            return
        if status == "ERROR":
            self._notify(message, "error")
            return

        self.results = results or []
        for row in self.results:
            try:
                pres_id = int(row[0])
            except (TypeError, ValueError, IndexError):
                continue
            self._row_by_id[pres_id] = row
            table.add_row(str(pres_id), key=str(pres_id))

        if not self.results:
            body.load_text("Не знайдено.\n\n────────────────────────")
            self._set_status("Текстів за запитом не знайдено.")
        else:
            self._set_status(message)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.data_table.id != "text-presentation-list" or event.row_key is None:
            return
        try:
            pres_id = int(str(event.row_key.value))
            row = self._row_by_id.get(pres_id)
            if row is None:
                return
            self.query_one("#text-presentation-body", TextArea).load_text(str(row[1] or ""))
            extra_info = get_presentation_info(self.cursor, pres_id)
            if extra_info:
                reg, date, meed = extra_info
                refused = " (відмовлено)" if str(meed) == "0" else ""
                self._set_status(f"[{pres_id}] Подання № {reg or ''} від {date or ''}{refused}")
            else:
                self._set_status(f"Подання ID {pres_id}")
        except Exception as exc:
            self._notify(f"Не вдалося відкрити подання: {exc}", "error")

    def clear_search(self) -> None:
        self.query_one("#text-search-query", Input).value = ""
        self.query_one("#text-presentation-list", DataTable).clear()
        self.query_one("#text-presentation-body", TextArea).load_text(self.HELP_TEXT)
        self.results = []
        self._row_by_id = {}
        self._set_status(DEF_FUT_LABEL)
        self.query_one("#text-search-query", Input).focus()

    def get_footer_message(self) -> str:
        return self.last_message

    def _set_status(self, message: str) -> None:
        self.last_message = message
        try:
            self.app.query_one("#status", Static).update(message)
        except Exception:
            pass

    def _notify(self, message: str, severity: str = "information") -> None:
        self._set_status(message)
        self.app.notify(message, severity=severity)
