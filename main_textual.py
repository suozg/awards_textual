"""Textual-порт AWARDS 53."""
from __future__ import annotations
import argparse
import csv
import sys
from pathlib import Path

from sqlcipher3 import dbapi2 as sqlite3
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen, Screen
from textual.theme import Theme
from textual.widgets import (
    Button, DataTable, Footer, Input, Label, Static,
    TabbedContent, TabPane, TextArea,
)

from config import DATABASE_FILE_PATH, MASTERKEY, TITLE_PROG, VERSION

from dovidnyk_textual import DovidnykTab
from search_tab_textual import SearchTab
from kartka_textual import KartkaTab
from text_panel_textual import TextPanel
from laws_textual import LawsTab, LawEditScreen
from checkers_textual import CheckersWidget
from zvity_textual import ZvitTab
from setuptab_textual import SettingsTab, ReportSettingsModal

def connect_database(path: str, password: str):
    """Відкриває SQLCipher-базу в режимі сумісності з наявною БД."""
    conn = sqlite3.connect(path, check_same_thread=False)
    cur = conn.cursor()
    cur.execute(f"PRAGMA key = '{password.replace(chr(39), chr(39)*2)}';")
    cur.execute("PRAGMA cipher_compatibility = 3;")
    cur.execute("PRAGMA kdf_iter = 64000;")
    cur.execute("PRAGMA journal_mode=WAL;")
    cur.execute("PRAGMA synchronous=NORMAL;")
    cur.execute("PRAGMA cache_size = -64000;")
    cur.execute("PRAGMA temp_store = MEMORY;")
    cur.execute("SELECT name FROM sqlite_master WHERE type='table';")
    if not cur.fetchall():
        cur.close()
        conn.close()
        raise RuntimeError("У базі немає таблиць або пароль неправильний.")
    conn.create_function("LOWER", 1, lambda value: str(value).lower())
    return conn, cur

class LoginScreen(ModalScreen[tuple[str, object, object] | None]):
    """Діалог входу до бази даних."""

    def __init__(self, db_path: str, db_exists: bool):
        super().__init__()
        self.db_path = db_path
        self.db_exists = db_exists
        self._creation_needed = not Path(db_path).is_file()

    def compose(self) -> ComposeResult:
        with Vertical(id="login-box"):
            yield Label("AWARDS 53" if self.db_exists else "AWARDS 53 - Створення бази даних", id="login-title")
            yield Static(f"База: {self.db_path}", id="db-path")
            yield Input(placeholder="Пароль бази даних", password=True, id="password")
            yield Static("", id="login-error")
            with Horizontal():
                yield Button("Увійти", variant="primary", id="login")
                yield Button("Вийти", id="cancel")

    def on_mount(self) -> None:
        self.query_one("#password", Input).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel":
            self.dismiss(None)
        elif event.button.id == "login":
            self._submit_password()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "password":
            self._submit_password()

    def _submit_password(self) -> None:
        password = self.query_one("#password", Input).value
        if not password:
            self.query_one("#login-error", Static).update("Введіть пароль бази даних.")
            return
        try:
            self.db_exists = Path(self.db_path).is_file()
            if self._creation_needed:
                Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
                from create_db0 import create_database
                if not create_database(self.db_path, password):
                    raise RuntimeError("Не вдалося створити базу даних.")
                self.db_exists = Path(self.db_path).is_file()
                self.notify("Нова база даних успішно створена!", severity="information", timeout=5)

            # Перевіряємо з'єднання одразу при введенні пароля
            conn, cur = connect_database(self.db_path, password)
            self._creation_needed = False
            self.dismiss((password, conn, cur))
        except Exception as exc:
            self.query_one("#login-error", Static).update(f"Помилка: {exc}")
            self.query_one("#password", Input).focus()


class SplashScreen(Screen):
    """Екран заставки з текстом по центру на час ініціалізації."""

    def compose(self) -> ComposeResult:
        with Vertical(classes="splash-container"):
            yield Label("AWARDS 53", classes="splash-title")
            yield Static("(c) Холодов О.В. [git/suozg]", classes="splash-author")
            yield Static("Підготовка робочого середовища...", id="splash-status", classes="splash-status")

    def update_status(self, text: str) -> None:
        try:
            self.query_one("#splash-status", Static).update(text)
        except Exception:
            pass


class MainScreen(Screen):
    """Головний екран із вкладками (створюється лише після заставки)."""

    def compose(self) -> ComposeResult:
        with TabbedContent(initial="tab-search"):
            with TabPane("ПОШУК", id="tab-search"):
                yield SearchTab(id="search-tab")
            with TabPane("КАРТКА", id="tab-card"):
                yield KartkaTab(id="kartka-tab")
            with TabPane("ДОВІДНИК", id="tab-reference"):
                yield DovidnykTab(id="dovidnyk-tab")
            with TabPane("ЗВІТИ", id="tab-reports"):
                yield ZvitTab(id="zvity-panel")
            with TabPane("ТЕКСТ", id="tab-text"):
                yield TextPanel(id="text-panel")
            with TabPane("НАЛАШТУВАННЯ", id="tab-settings"):
                yield SettingsTab(id="settings-tab")
            with TabPane("ЗАКОНИ", id="tab-laws"):
                yield LawsTab(id="laws-tab") 
            with TabPane("SQL", id="tab-sql"):
                with Vertical():
                    yield Label("SQL-запит (Ctrl+Enter — виконати)")
                    yield TextArea(id="sql-input")
                    with Horizontal():
                        yield Button("Виконати", variant="primary", id="sql-run")
                        yield Button("EXPLAIN", id="sql-explain")
                        yield Button("CSV", id="sql-csv")
                    yield DataTable(id="sql-result", cursor_type="cell")
            with TabPane("ПРО", id="tab-about"):
                with Horizontal(classes="about-container"):
                    with Vertical(classes="about-info-pane"):
                        yield Label("AWARDS 53", classes="about-header")
                        yield Static(
                            f"Програма: [bold]{TITLE_PROG}[/bold]\n"
                            f"Версія: [bold]{VERSION}[/bold]\n"
                            "Архітектура: [italic]Textual Terminal UI[/italic]\n\n"
                            "Система призначена для ведення обліку нагород, "
                            "роботи з базами даних SQLCipher та нормативними актами.\n\n"
                            "(c) 2026. Холодов О.В. [git/suozg]",
                            classes="about-text"
                        )
                    with Vertical(classes="about-game-pane"):
                        yield CheckersWidget(id="checkers-game")
        yield Footer()


class AwardsTextualApp(App):
    CSS_PATH = "styles.tcss" 
    TITLE = TITLE_PROG
    SUB_TITLE = f"Textual port · {VERSION}"
    BINDINGS = [
        ("ctrl+q", "quit", "Вихід"),
        ("f6", "toggle_theme", "Перемкнути тему"),
        ("f4", "open_report_settings", "Налаштування звітів"),
    ]

    def __init__(self, db_path: str):
        super().__init__()
        self.db_path = db_path
        self.password = None
        self.conn = None
        self.cursor = None
        self.presentations = []
        self._card_search_revision = -1
        self._initialized_tabs = set()
        self._theme_names = ("gruvbox-dark", "gruvbox-light")
        self.register_theme(Theme(
            name="gruvbox-dark", primary="#d79921", secondary="#83a598",
            warning="#fabd2f", error="#fb4934", success="#b8bb26",
            accent="#fe8019", foreground="#ebdbb2", background="#282828",
            surface="#3c3836", panel="#504945", boost="#665c54", dark=True,
            variables={"text-muted": "#a89984"},
        ))
        self.register_theme(Theme(
            name="gruvbox-light", primary="#b57614", secondary="#689d6a",
            warning="#d79921", error="#cc241d", success="#98971a",
            accent="#d65d0e", foreground="#3c3836", background="#fbf1c7",
            surface="#f2e5bc", panel="#ebdbb2", boost="#d5c4a1", dark=False,
            variables={"text-muted": "#7c6f64"},
        ))
        self.theme = "gruvbox-dark"

    def on_mount(self) -> None:
        db_exists = Path(self.db_path).is_file()
        
        if MASTERKEY:
            self.password = MASTERKEY
            # Якщо є MASTERKEY, одразу показуємо заставку і запускаємо ініціалізацію
            self.push_screen(SplashScreen())
            self.run_worker(self._initialize_backend_task, thread=True)
        else:
            def handle_login(result):
                if not result:
                    self.exit()
                    return
                self.password, self.conn, self.cursor = result
                # ПЕРШИЙ КРОК ЗАСТАВКИ: після успішного логіну показуємо SplashScreen
                self.push_screen(SplashScreen())
                # ДРУГИЙ КРОК: запускаємо фонову ініціалізацію
                self.run_worker(self._initialize_backend_task, thread=True)

            # Показуємо вікно логіну поверх порожнього дефолтного екрана
            self.push_screen(LoginScreen(self.db_path, db_exists), handle_login)

    def action_open_report_settings(self) -> None:
        if not self.conn:
            self.notify("База даних не підключена.", severity="error")
            return

        try:
            report_tab = self.screen.query_one("#zvity-panel", ZvitTab)
            self.push_screen(ReportSettingsModal(self.conn, report_tab))
        except Exception as exc:
            self.notify(f"Не вдалося відкрити налаштування звітів: {exc}", severity="error")

    def _initialize_backend_task(self) -> None:
        try:
            self.call_from_thread(
                self._update_splash_status,
                "Підключення до бази даних SQLCipher...",
            )

            # Якщо з'єднання ще не відкрите (наприклад, при заданому MASTERKEY),
            # відкриваємо його у фоновому потоці.
            if self.conn is None:
                self.conn, self.cursor = connect_database(
                    self.db_path, self.password
                )

            self.call_from_thread(
                self._update_splash_status,
                "Підготовка вкладки пошуку...",
            )
            self.call_from_thread(self._transition_to_main_screen)

        except Exception as exc:
            self.call_from_thread(self._handle_init_error, str(exc))

    def _update_splash_status(self, message: str) -> None:
        if isinstance(self.screen, SplashScreen):
            self.screen.update_status(message)

    def _transition_to_main_screen(self) -> None:
        self.switch_screen(MainScreen())

        # Спочатку Textual має завершити compose/mount MainScreen.
        self.call_after_refresh(self._initialize_search_tab)

    def _initialize_search_tab(self) -> None:
        try:
            main_screen = self.screen
            if not isinstance(main_screen, MainScreen):
                raise RuntimeError("Основний екран ще не активний.")

            search_tab = main_screen.query_one("#search-tab", SearchTab)
            search_tab.set_database(self.conn, self.cursor)
            self._initialized_tabs.add("tab-search")

        except Exception as exc:
            self.notify(
                f"Помилка ініціалізації пошуку: {exc}",
                severity="error",
                timeout=10,
            )

    def on_tabbed_content_tab_activated(
        self, event: TabbedContent.TabActivated
    ) -> None:
        tab_id = event.pane.id

        if tab_id in self._initialized_tabs:
            if tab_id == "tab-card":
                self._sync_card_with_search()
            return

        self.call_after_refresh(self._initialize_tab, tab_id)

    def _initialize_tab(self, tab_id: str) -> None:
        tab_setup = {
            "tab-card": ("#kartka-tab", KartkaTab),
            "tab-reference": ("#dovidnyk-tab", DovidnykTab),
            "tab-reports": ("#zvity-panel", ZvitTab),
            "tab-text": ("#text-panel", TextPanel),
            "tab-settings": ("#settings-tab", SettingsTab),
            "tab-laws": ("#laws-tab", LawsTab),
        }

        if tab_id in self._initialized_tabs:
            return

        if tab_id not in tab_setup:
            return

        selector, widget_type = tab_setup[tab_id]

        try:
            main_screen = self.screen

            if not isinstance(main_screen, MainScreen):
                return

            widget = main_screen.query_one(selector, widget_type)
            widget.set_database(self.conn, self.cursor)

            if tab_id == "tab-reference":
                widget._load_data()

            self._initialized_tabs.add(tab_id)

            if tab_id == "tab-card":
                self._sync_card_with_search()

        except Exception as exc:
            self.notify(
                f"Не вдалося ініціалізувати вкладку: {exc}",
                severity="error",
                timeout=10,
            )

    def _sync_card_with_search(self) -> None:
        try:
            main_screen = self.screen

            if not isinstance(main_screen, MainScreen):
                return

            search_tab = main_screen.query_one("#search-tab", SearchTab)
            revision = search_tab.get_search_revision()

            if revision == self._card_search_revision:
                return

            results, source = search_tab.get_latest_search_results()

            if results is None:
                return

            self._card_search_revision = revision

            main_screen.query_one(
                "#kartka-tab", KartkaTab
            ).populate_and_load_search_results(results, source)

        except Exception as exc:
            self.notify(
                f"Помилка синхронізації картки: {exc}",
                severity="error",
                timeout=10,
            )

    def action_toggle_theme(self) -> None:
        self.theme = "gruvbox-light" if self.theme == "gruvbox-dark" else "gruvbox-dark"
        theme_label = "світла Gruvbox" if self.theme == "gruvbox-light" else "темна Gruvbox"
        try:
            self.query_one("#status", Static).update(f"Тема: {theme_label} (F12 — перемкнути)")
        except Exception:
            pass

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "search-button":
            self.search_presentations()
        elif event.button.id == "sql-run":
            self.execute_sql()
        elif event.button.id == "sql-explain":
            self.execute_sql(explain=True)
        elif event.button.id == "sql-csv":
            self.export_csv()

    def execute_sql(self, explain: bool = False) -> None:
        try:
            sql = self.query_one("#sql-input", TextArea).text.strip()
            if not sql:
                return
            if explain:
                sql = "EXPLAIN QUERY PLAN " + sql
            self.cursor.execute(sql)
            table = self.query_one("#sql-result", DataTable)
            table.clear(columns=True)
            if self.cursor.description:
                columns = [str(col[0]) for col in self.cursor.description]
                table.add_columns(*columns)
                for row in self.cursor.fetchall():
                    table.add_row(*(str(value) if value is not None else "NULL" for value in row))
            else:
                self.conn.commit()
                self.notify(f"Запит виконано. Змінено рядків: {self.cursor.rowcount}")
            self.query_one("#status", Static).update("SQL: виконано")
        except Exception as exc:
            self.notify(f"SQL: {exc}", severity="error", timeout=10)

    def export_csv(self) -> None:
        try:
            table = self.query_one("#sql-result", DataTable)
            if not table.columns:
                self.notify("Немає результатів для експорту.", severity="warning")
                return
            from datetime import datetime
            path = Path.cwd() / f"awards_sql_{datetime.now():%Y%m%d_%H%M%S}.csv"
            with path.open("w", newline="", encoding="utf-8-sig") as stream:
                writer = csv.writer(stream)
                writer.writerow([column.label.plain for column in table.columns.values()])
                for row_key in table.rows:
                    writer.writerow([str(cell) for cell in table.get_row(row_key)])
            self.notify(f"CSV збережено: {path}")
        except Exception as exc:
            self.notify(f"Помилка експорту CSV: {exc}", severity="error")

    def on_unmount(self) -> None:
        if self.cursor:
            try:
                self.cursor.close()
            except Exception:
                pass
        if self.conn:
            try:
                self.conn.close()
            except Exception:
                pass


def main() -> None:
    parser = argparse.ArgumentParser(description="AWARDS 53")
    parser.add_argument("-c", default=DATABASE_FILE_PATH, help="Шлях до файлу бази даних")
    args = parser.parse_args()
    
    app = AwardsTextualApp(args.c)
    app.run()


if __name__ == "__main__":
    main()
