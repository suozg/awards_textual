from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from textual.app import ComposeResult
from textual.containers import Container, Grid, Horizontal, Vertical
from textual.widgets import Button, Checkbox, Input, Label, Select, Static

from config import ALL_COLUMN_LABELS
from database_logic_textual import (
    connect_to_database,
    get_service_settings_data,
    get_units_and_ranks,
)


class SettingsTab(Vertical):
    """Textual port для вкладки настроек (setuptab.py)."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.conn = None
        self.cursor = None
        self.db_path = ""
        self.password = ""
        self.zvit_dir = ""
        self.zvit_fields = ""
        self.show_hellou = 0
        self.service_id = None
        self.service_pass = None
        self.cookies = None
        self.last_time_changes = None
        self.logo_bmp = None
        self.logo_path = None

        self._loaded_units = ["", "Створити >"]
        self._loaded_ranks = ["", "Створити >"]
        self._selected_report_fields_flags = [0] * 15

        # --- Пароль
        self.pass_old = Input(password=True, placeholder="старий пароль", id="settings-old-pass")
        self.pass_new = Input(password=True, placeholder="новий пароль", id="settings-new-pass")
        self.pass_repeat = Input(password=True, placeholder="повторити новий пароль", id="settings-repeat-pass")

        # --- Показ графіка / посмертних
        self.show_dead_checkbox = Checkbox("- завжди показувати блок посмертних нагород в КАРТКА", value=False, id="settings-show-dead")
        self.show_graph_checkbox = Checkbox("- графік при старті", value=False, id="settings-show-graph")

        # --- Логотип
        self.logo_path_input = Input(placeholder="шлях до логотипа (.png)", id="settings-logo-path")
        self.logo_select_btn = Button("Вибрати файл", id="settings-logo-select")
        self.logo_save_btn = Button("Зберегти логотип", variant="primary", id="settings-logo-save")

        # --- Глобальні налаштування
        self.rank_combo = Select([], allow_blank=True, id="settings-rank-select")
        self.rank_entry = Input(placeholder="звання", id="settings-rank-entry")
        self.rank_delete = Checkbox("видалити", value=False, id="settings-rank-delete")

        self.unit_combo = Select([], allow_blank=True, id="settings-unit-select")
        self.unit_entry = Input(placeholder="підрозділ", id="settings-unit-entry")
        self.unit_delete = Checkbox("видалити", value=False, id="settings-unit-delete")

        self.save_global_btn = Button("Зберегти", id="settings-save-global")
        self.clear_global_btn = Button("Очистити", id="settings-clear-global")

        # --- Налаштування звітів
        self.report_dir = Input(placeholder="шлях до папки для EXCEL", id="settings-report-dir")
        self.report_dir_save = Button("Зберегти каталог", id="settings-dir-save")

        self.report_checkboxes = []
        self.rno_checkbox = Checkbox("РНОКПП", value=False, id="settings-rno")
        self.dob_checkbox = Checkbox("Дата народження", value=False, id="settings-dob")
        self.save_report_cols_btn = Button("Встановити", id="settings-save-report-cols")

        self.status = Static("Готово", id="settings-status")

    def set_database(self, conn, cursor, db_path: str = "", password: str = ""):
        self.conn = conn
        self.cursor = cursor
        self.db_path = db_path
        self.password = password
        self.load_service_settings_data()
        self.load_global_libs_data()
        self.refresh_ui()

    def compose(self) -> ComposeResult:
        with Vertical(id="settings-root"):

            with Vertical(id="settings-password-box"):
                yield Label("Зміна пароля до бази даних", classes="settings-section-title")
                with Horizontal(classes="settings-row"):
                    yield self.pass_old
                    yield self.pass_new
                    yield self.pass_repeat
                    yield Button("Змінити пароль", variant="primary", id="settings-change-password")

            with Horizontal(id="settings-top-row"):
                with Vertical(id="settings-password-side"):
                    yield Label("Показ при старті", classes="settings-section-title")
                    yield self.show_dead_checkbox
                    yield self.show_graph_checkbox

                with Vertical(id="settings-logo-box"):
                    yield Label("Логотип організації", classes="settings-section-title")
                    with Horizontal(classes="settings-row"):
                        yield self.logo_path_input
                        yield self.logo_select_btn
                    with Horizontal(classes="settings-row"):
                        yield self.logo_save_btn

            with Vertical(id="settings-report-box"):
                yield Label("Налаштування звітів", classes="settings-section-title")
                with Horizontal(classes="settings-row"):
                    yield Label("Місце збереження EXCEL:", classes="settings-label")
                    yield self.report_dir
                    yield self.report_dir_save

                yield Label("Наповнення таблиць", classes="settings-label")
                with Grid(id="settings-report-grid"):
                    for cb in self.report_checkboxes:
                        yield cb
                    yield self.rno_checkbox
                    yield self.dob_checkbox
                with Horizontal(classes="settings-row"):
                    yield self.save_report_cols_btn

            with Vertical(id="settings-global-box"):
                yield Label("Назви підрозділів / звань", classes="settings-section-title")
                with Horizontal(classes="settings-row"):
                    yield Label("звання", classes="settings-label")
                    yield self.rank_combo
                    yield self.rank_entry
                    yield self.rank_delete

                with Horizontal(classes="settings-row"):
                    yield Label("підрозділ", classes="settings-label")
                    yield self.unit_combo
                    yield self.unit_entry
                    yield self.unit_delete

                with Horizontal(classes="settings-row"):
                    yield self.save_global_btn
                    yield self.clear_global_btn

            yield self.status

    def on_mount(self) -> None:
        self.refresh_ui()

    def refresh_ui(self):
        """Оновлює текст і стан елементів після завантаження БД."""
        self._sync_report_columns_ui()
        self._sync_global_vars_ui()
        self._update_show_hellou_state()
        self._update_status("Готово")

    def load_service_settings_data(self):
        """Завантажує service_ з БД у атрибути."""
        if not self.conn or not self.cursor:
            return

        try:
            row = get_service_settings_data(self.cursor)
            if not row:
                self.zvit_dir = ""
                self.zvit_fields = ""
                self.show_hellou = 0
                return

            self.zvit_dir = str(row[4]) if row[4] is not None else ""
            self.zvit_fields = str(row[5]) if row[5] is not None else ""
            self.show_hellou = int(row[6]) if row[6] is not None else 0
            self.service_id = row[7]
            self.service_pass = row[8]
            self.cookies = row[9]
            self.last_time_changes = row[12]
            self.report_dir.value = self.zvit_dir

            self._selected_report_fields_flags = []
            if self.zvit_fields:
                try:
                    flags = [int(v) for v in self.zvit_fields.split(",")]
                    self._selected_report_fields_flags = flags[:15]
                    while len(self._selected_report_fields_flags) < 15:
                        self._selected_report_fields_flags.append(0)
                except Exception:
                    self._selected_report_fields_flags = [0] * 15
            else:
                self._selected_report_fields_flags = [0] * 15

        except Exception as exc:
            self._update_status(f"Помилка завантаження service_: {exc}")
            self._selected_report_fields_flags = [0] * 15

        self._sync_report_columns_ui()

    def load_global_libs_data(self):
        """Загружает ranks/units из libs."""
        if not self.conn or not self.cursor:
            return

        try:
            self._loaded_units = ["", "Створити >"]
            self._loaded_ranks = ["", "Створити >"]

            ranks, units = get_units_and_ranks(self.cursor)
            if ranks:
                self._loaded_ranks.extend([str(r).strip() for r in ranks if str(r).strip()])
            if units:
                self._loaded_units.extend([str(u).strip() for u in units if str(u).strip()])

            self._loaded_ranks = list(dict.fromkeys(self._loaded_ranks))
            self._loaded_units = list(dict.fromkeys(self._loaded_units))

            self._loaded_ranks = ["", "Створити >"] + sorted(self._loaded_ranks[2:]) if len(self._loaded_ranks) > 2 else ["", "Створити >"]
            self._loaded_units = ["", "Створити >"] + sorted(self._loaded_units[2:]) if len(self._loaded_units) > 2 else ["", "Створити >"]

            self.rank_combo._options = [(item, item) for item in self._loaded_ranks]
            self.unit_combo._options = [(item, item) for item in self._loaded_units]
            self.rank_combo.value = None
            self.unit_combo.value = None
        except Exception as exc:
            self._update_status(f"Помилка завантаження libs: {exc}")

    def _sync_report_columns_ui(self):
        self.report_checkboxes = []

        standard_labels = ALL_COLUMN_LABELS[:14]
        for i, label in enumerate(standard_labels):
            cb = Checkbox(label, value=bool(self._selected_report_fields_flags[i]) if i < len(self._selected_report_fields_flags) else False, id=f"settings-col-{i}")
            self.report_checkboxes.append(cb)

        self.rno_checkbox.value = bool(self._selected_report_fields_flags[14]) in (1, 3) if len(self._selected_report_fields_flags) > 14 else False
        self.dob_checkbox.value = bool(self._selected_report_fields_flags[14]) in (2, 3) if len(self._selected_report_fields_flags) > 14 else False

        self.report_dir.value = self.zvit_dir
        self._update_show_hellou_state()

    def _update_show_hellou_state(self):
        state_1 = self.show_hellou in (1, 3)
        state_2 = self.show_hellou in (2, 3)
        self.show_graph_checkbox.value = state_1
        self.show_dead_checkbox.value = state_2

    def _sync_global_vars_ui(self):
        self.rank_combo._options = [(item, item) for item in self._loaded_ranks]
        self.unit_combo._options = [(item, item) for item in self._loaded_units]
        if not self.rank_combo.value:
            self.rank_combo.value = ""
        if not self.unit_combo.value:
            self.unit_combo.value = ""

        self.rank_entry.value = ""
        self.unit_entry.value = ""
        self.rank_delete.value = False
        self.unit_delete.value = False

    def _update_status(self, message: str):
        self.status.update(message)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "settings-change-password":
            self.change_password()
        elif event.button.id == "settings-logo-select":
            self.select_logo_file()
        elif event.button.id == "settings-logo-save":
            self.save_logo()
        elif event.button.id == "settings-dir-save":
            self.save_report_dir()
        elif event.button.id == "settings-save-report-cols":
            self.save_report_column_selection()
        elif event.button.id == "settings-save-global":
            self.save_global_vars()
        elif event.button.id == "settings-clear-global":
            self.clear_global_vars()

    def on_checkbox_changed(self, event):
        if event.checkbox.id == "settings-show-dead":
            self.update_show_hellou_in_db()
        elif event.checkbox.id == "settings-show-graph":
            self.update_show_hellou_in_db()
        elif event.checkbox.id == "settings-rank-delete":
            self._sync_global_vars_ui()
        elif event.checkbox.id == "settings-unit-delete":
            self._sync_global_vars_ui()

    def on_select_changed(self, event):
        if event.select.id in {"settings-rank-select", "settings-unit-select"}:
            self._sync_global_vars_ui()
            if event.select.id == "settings-rank-select":
                selected = self.rank_combo.value
                self.rank_entry.value = selected
            elif event.select.id == "settings-unit-select":
                selected = self.unit_combo.value
                self.unit_entry.value = selected

    def on_input_changed(self, event):
        if event.input.id in {"settings-report-dir", "settings-logo-path"}:
            pass

    def select_logo_file(self):
        from tkinter import Tk
        from tkinter.filedialog import askopenfilename

        try:
            Tk().withdraw()
            path = askopenfilename(filetypes=[("PNG files", "*.png")])
            if path:
                self.logo_path_input.value = path
                self.logo_path = path
        except Exception:
            self._update_status("Не вдалося вибрати файл логотипу")

    def save_logo(self):
        if not self.conn or not self.cursor:
            return
        path = self.logo_path_input.value.strip()
        if not path:
            self._update_status("Файл логотипу не вибраний")
            return
        try:
            with open(path, "rb") as f:
                blob = f.read()
            self.cursor.execute("UPDATE service_ SET logo = ? WHERE id = 1", (blob,))
            self.conn.commit()
            self._update_status("Логотип збережено до бази")
        except Exception as exc:
            self._update_status(f"Помилка збереження логотипу: {exc}")

    def change_password(self):
        old_pass = self.pass_old.value.strip()
        new_pass1 = self.pass_new.value.strip()
        new_pass2 = self.pass_repeat.value.strip()

        if not old_pass or not new_pass1 or not new_pass2:
            self._update_status("Порожні паролі неприйнятні")
            return
        if new_pass1 != new_pass2:
            self._update_status("Нові паролі не збігаються")
            return
        if old_pass == new_pass1:
            self._update_status("Новий пароль такий самий як і старий")
            return

        try:
            temp_db, temp_cursor = connect_to_database(old_pass, self.db_path)
            if temp_db is None or temp_cursor is None:
                self._update_status("Введено невірний старий пароль")
                return

            temp_cursor.execute(f"PRAGMA rekey = '{new_pass2}';")
            temp_db.commit()
            self._update_status("Пароль успішно змінено. Потрібен перезапуск.")
            self.pass_old.value = ""
            self.pass_new.value = ""
            self.pass_repeat.value = ""
        except Exception as exc:
            self._update_status(f"Помилка зміни паролю: {exc}")
        finally:
            if temp_db:
                temp_db.close()
            if temp_cursor:
                temp_cursor.close()

    def save_report_dir(self):
        if not self.conn or not self.cursor:
            return

        directory = self.report_dir.value.strip()
        if not directory or not Path(directory).is_dir():
            self._update_status("Обрано некоректний шлях")
            return

        try:
            self.cursor.execute("UPDATE service_ SET zvit_dir = ? WHERE id = 1", (directory,))
            self.conn.commit()
            self._update_status("Шлях звітів успішно збережений")
        except Exception as exc:
            self._update_status(f"Помилка збереження шляху: {exc}")

    def save_report_column_selection(self):
        selected_flags = []
        for i in range(14):
            if i < len(self.report_checkboxes):
                selected_flags.append("1" if self.report_checkboxes[i].value else "0")
            else:
                selected_flags.append("0")

        if self.rno_checkbox.value and not self.dob_checkbox.value:
            last_flag = 1
        elif not self.rno_checkbox.value and self.dob_checkbox.value:
            last_flag = 2
        elif self.rno_checkbox.value and self.dob_checkbox.value:
            last_flag = 3
        else:
            last_flag = 0
        selected_flags.append(str(last_flag))
        selected_fields = ",".join(selected_flags)

        try:
            self.cursor.execute("UPDATE service_ SET zvit_fields = ? WHERE id = 1", (selected_fields,))
            self.conn.commit()
            self._update_status("Налаштування колонок звіту збережено")
        except Exception as exc:
            self._update_status(f"Помилка збереження колонок: {exc}")

    def update_show_hellou_in_db(self):
        if not self.conn or not self.cursor:
            return

        state_1 = self.show_graph_checkbox.value
        state_2 = self.show_dead_checkbox.value

        if state_1 and state_2:
            new_value = 3
        elif state_1:
            new_value = 1
        elif state_2:
            new_value = 2
        else:
            new_value = 0

        try:
            self.cursor.execute("UPDATE service_ SET show_hellou = ? WHERE id = 1", (new_value,))
            self.conn.commit()
            self.show_hellou = new_value
            self._update_status("Параметри стартового вигляду оновлено")
        except Exception as exc:
            self._update_status(f"Помилка оновлення параметрів стартового вигляду: {exc}")

    def save_global_vars(self):
        selected_rank = self.rank_combo.value
        new_rank_value = self.rank_entry.value.strip()
        delete_rank = self.rank_delete.value

        selected_unit = self.unit_combo.value
        new_unit_value = self.unit_entry.value.strip()
        delete_unit = self.unit_delete.value

        if delete_rank and selected_rank:
            self.cursor.execute("DELETE FROM libs WHERE rank_src = ?", (selected_rank,))
            self.cursor.execute("UPDATE personality SET rank = ? WHERE rank = ?", (new_rank_value or selected_rank, selected_rank))
            self.conn.commit()
            self._update_status(f"Видалено звання {selected_rank}")
            self.load_global_libs_data()
            return

        if delete_unit and selected_unit:
            self.cursor.execute("DELETE FROM libs WHERE unit_src = ?", (selected_unit,))
            self.cursor.execute("UPDATE personality SET unit = ? WHERE unit = ?", (new_unit_value or selected_unit, selected_unit))
            self.conn.commit()
            self._update_status(f"Видалено підрозділ {selected_unit}")
            self.load_global_libs_data()
            return

        if len(new_rank_value) >= 2 and new_rank_value != selected_rank:
            if selected_rank and selected_rank != "Створити >":
                self.cursor.execute("UPDATE libs SET rank_src = ? WHERE rank_src = ?", (new_rank_value, selected_rank))
                self.cursor.execute("UPDATE personality SET rank = ? WHERE rank = ?", (new_rank_value, selected_rank))
            else:
                self.cursor.execute("SELECT COUNT(*) FROM libs WHERE rank_src = ?", (new_rank_value,))
                exists = self.cursor.fetchone()[0]
                if exists:
                    self._update_status(f"Звання '{new_rank_value}' вже існує")
                    return
                self.cursor.execute("INSERT INTO libs (rank_src) VALUES (?)", (new_rank_value,))
            self.conn.commit()
            self._update_status(f"Змінено/додано звання {new_rank_value}")
            self.load_global_libs_data()
            return

        if len(new_unit_value) >= 2 and new_unit_value != selected_unit:
            if selected_unit and selected_unit != "Створити >":
                self.cursor.execute("UPDATE libs SET unit_src = ? WHERE unit_src = ?", (new_unit_value, selected_unit))
                self.cursor.execute("UPDATE personality SET unit = ? WHERE unit = ?", (new_unit_value, selected_unit))
            else:
                self.cursor.execute("SELECT COUNT(*) FROM libs WHERE unit_src = ?", (new_unit_value,))
                exists = self.cursor.fetchone()[0]
                if exists:
                    self._update_status(f"Підрозділ '{new_unit_value}' вже існує")
                    return
                self.cursor.execute("INSERT INTO libs (unit_src) VALUES (?)", (new_unit_value,))
            self.conn.commit()
            self._update_status(f"Змінено/додано підрозділ {new_unit_value}")
            self.load_global_libs_data()
            return

        self._update_status("Немає змін для збереження")

    def clear_global_vars(self):
        self.rank_combo.value = ""
        self.unit_combo.value = ""
        self.rank_entry.value = ""
        self.unit_entry.value = ""
        self.rank_delete.value = False
        self.unit_delete.value = False

    def on_unmount(self):
        pass
