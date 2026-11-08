from __future__ import annotations

import webbrowser
from datetime import datetime

from sqlcipher3 import dbapi2 as sqlite3
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Checkbox, DataTable, Input, Label, Static


class LawEditScreen(ModalScreen[bool]):
    """Модальне вікно для створення, редагування або видалення нормативного акту."""

    def __init__(self, conn, cursor, law_id: int | None = None):
        super().__init__()
        self.conn = conn
        self.cursor = cursor
        self.law_id = law_id

    def compose(self) -> ComposeResult:
        with Vertical(id="law-edit-box"):
            title = "Редагування нормативного акту" if self.law_id else "Додавання нормативного акту"
            yield Label(title, id="law-edit-title")
            
            yield Label("Номер:")
            yield Input(id="law-number")
            
            yield Label("Дата (РРРР-ММ-ДД):")
            yield Input(id="law-date", placeholder="2026-01-01")
            
            yield Label("Назва:")
            yield Input(id="law-name")
            
            yield Label("Посилання (URL):")
            yield Input(id="law-link")
            
            if self.law_id:
                yield Checkbox("Видалити запис", id="law-delete-chk")

            yield Static("", id="law-edit-error")
            
            with Horizontal():
                yield Button("Зберегти", variant="primary", id="save")
                yield Button("Скасувати", id="cancel")

    def on_mount(self) -> None:
        if self.law_id:
            try:
                self.cursor.execute(
                    "SELECT law_denotation, law_link, law_number, law_date FROM law WHERE id_law = ?",
                    (self.law_id,)
                )
                row = self.cursor.fetchone()
                if row:
                    self.query_one("#law-name", Input).value = row[0] or ""
                    self.query_one("#law-link", Input).value = row[1] or ""
                    self.query_one("#law-number", Input).value = row[2] or ""
                    self.query_one("#law-date", Input).value = row[3] or ""

            except sqlite3.Error as exc:
                self.query_one("#law-edit-error", Static).update(
                    f"Помилка завантаження: {exc}"
                )
        self.query_one("#law-number", Input).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel":
            self.dismiss(False)
        elif event.button.id == "save":
            self._save_data()

    def _save_data(self) -> None:
        try:
            delete_chk = self.query_one("#law-delete-chk", Checkbox) if self.law_id else None
            is_deleted = delete_chk.value if delete_chk else False

            if is_deleted and self.law_id:
                self.cursor.execute("DELETE FROM law WHERE id_law = ?", (self.law_id,))
            else:
                number = self.query_one("#law-number", Input).value.strip()
                date_str = self.query_one("#law-date", Input).value.strip()
                name = self.query_one("#law-name", Input).value.strip()
                link = self.query_one("#law-link", Input).value.strip()

                if not number or not date_str or not name:
                    self.query_one("#law-edit-error", Static).update("Заповніть обов'язкові поля (Номер, Дата, Назва).")
                    return

                # Перевірка формату дати
                datetime.strptime(date_str, "%Y-%m-%d")

                if self.law_id:
                    query = """
                        UPDATE law
                        SET law_denotation = ?, law_link = ?, law_date = ?, law_number = ?
                        WHERE id_law = ?
                    """
                    self.cursor.execute(query, (name, link, date_str, number, self.law_id))
                else:
                    query = """
                        INSERT INTO law (law_denotation, law_link, law_date, law_number)
                        VALUES (?, ?, ?, ?)
                    """
                    self.cursor.execute(query, (name, link, date_str, number))

            self.conn.commit()
            self.dismiss(True)
        except ValueError:
            self.query_one("#law-edit-error", Static).update("Невірний формат дати. Використовуйте РРРР-ММ-ДД.")
        except sqlite3.Error as exc:
            self.conn.rollback()
            self.query_one("#law-edit-error", Static).update(
                f"Помилка збереження: {exc}"
            )


class LawsTab(Vertical):
    """Вкладка 'ЗАКОНИ' (Нормативні акти)."""

    def __init__(self, id: str | None = None):
        super().__init__(id=id)
        self.conn = None
        self.cursor = None

    def compose(self) -> ComposeResult:
        with Vertical(classes="laws-container"):
            yield Label("ПОСИЛАННЯ НА ДЕЯКІ НОРМАТИВНІ АКТИ", classes="section-title")
            yield DataTable(id="laws-table", cursor_type="row")
            with Horizontal(classes="laws-buttons"):
                yield Button("Додати", variant="primary", id="law-add")
                yield Button("Змінити", id="law-edit")

    def set_database(self, conn, cursor) -> None:
        self.conn = conn
        self.cursor = cursor
        self.refresh_table()

    def refresh_table(self) -> None:
        if not self.cursor:
            return
        table = self.query_one("#laws-table", DataTable)
        table.clear(columns=True)
        table.add_columns("Номер", "Дата", "Назва")

        try:
            self.cursor.execute("SELECT id_law, law_date, law_denotation, law_link, law_number FROM law ORDER BY law_date")
            rows = self.cursor.fetchall()
            for row in rows:
                table.add_row(row[4] or "", row[1] or "", row[2] or "", key=str(row[0]))
        except sqlite3.Error as exc:
            self.app.notify(
                f"Помилка завантаження законів: {exc}",
                severity="error",
            )

    def open_edit_dialog(self, law_id: int | None = None) -> None:
        def check_result(result: bool | None) -> None:
            if result:
                self.refresh_table()
        self.app.push_screen(LawEditScreen(self.conn, self.cursor, law_id), check_result)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "law-add":
            self.open_edit_dialog(None)
        elif event.button.id == "law-edit":
            table = self.query_one("#laws-table", DataTable)
            if table.cursor_row is not None and table.row_count > 0:
                row_key = list(table.rows.keys())[table.cursor_row]
                law_id = int(row_key.value)
                self.open_edit_dialog(law_id)
            else:
                self.app.notify("Оберіть рядок для редагування.", severity="warning")

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """Відкриває посилання в браузері при натисканні Enter на рядку."""
        law_id = int(event.row_key.value)
        try:
            self.cursor.execute(
                "SELECT law_link FROM law WHERE id_law = ?",
                (law_id,),
            )
            row = self.cursor.fetchone()
            if row and row[0]:
                webbrowser.open(row[0])
        except (sqlite3.Error, OSError, webbrowser.Error) as exc:
            self.app.notify(
                f"Не вдалося відкрити посилання: {exc}",
                severity="error",
            )
