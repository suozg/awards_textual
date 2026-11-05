from __future__ import annotations

import base64
from io import BytesIO
import os
import sqlite3

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Button, Checkbox, Input, Label, Select, Static

from config import ALL_COLUMN_LABELS
from database_logic_textual import get_units_and_ranks, get_service_settings_data, connect_to_database


class ServiceSettingsIndices:
    LOGO = 0
    EXCEL_BUTTON = 1
    VIEW_BUTTON = 2
    OR_BUTTON = 3
    ZVIT_DIR = 4
    ZVIT_FIELDS = 5
    SHOW_HELLOU = 6
    SERVICE_ID = 7
    SERVICE_PASS = 8
    COOKIES = 9
    IMG_HOMER = 10
    IMG_HOMER2 = 11
    LAST_TIME_CHANGES = 12


class SettingsTab(VerticalScroll):
    """Вкладка «Налаштування» для Textual."""

    def __init__(self, conn=None, cursor=None, database_path=None, KEY=None, fut_place=None, tab4_panel=None, info_panel=None, search_tab=None, kartka_panel=None, **kwargs):
        super().__init__(**kwargs)
        self.conn = conn
        self.cursor = cursor
        self.database_path = database_path
        self.KEY = KEY
        self.fut_place = fut_place
        self.tab4_panel = tab4_panel
        self.kartka_panel = kartka_panel
        self.search_tab = search_tab
        self.info_panel = info_panel
        self.last_footer_message = None

        self._loaded_units = []
        self._loaded_ranks = []
        self._selected_report_fields_flags = []
        
        # Завантаження початкових даних
        self._load_service_settings_data()
        self._parse_zvit_fields()
        self._load_global_libs_data()

    def compose(self) -> ComposeResult:
        with Vertical(id="settings-root"):
            
            # --- Верхній рядок: Зміна пароля та Логотип ---
            with Horizontal(id="settings-top-row"):
                
                # Блок зміни пароля
                with Vertical(id="settings-password-box"):
                    yield Label("Зміна пароля до бази даних", classes="settings-section-title")
                    yield Label("Ввести старий пароль", classes="settings-label")
                    yield Input(placeholder="Старий пароль", password=True, id="settings-old-pass")
                    yield Label("Ввести новий пароль", classes="settings-label")
                    yield Input(placeholder="Новий пароль", password=True, id="settings-new-pass")
                    yield Label("Повторити новий пароль", classes="settings-label")
                    yield Input(placeholder="Повторити новий пароль", password=True, id="settings-repeat-pass")
                    
                    with Horizontal(classes="settings-row"):
                        yield Checkbox("— завжди показувати блок посмертних нагород", id="show-dead-chk", value=self.show_hellou >= 2)
                        yield Checkbox("— графік при старті", id="show-hello-chk", value=self.show_hellou in (1, 3))
                    
                    with Horizontal(classes="settings-row"):
                        yield Button("Змінити пароль", variant="error", id="settings-change-password")

                # Блок логотипу
                with Vertical(id="settings-logo-box"):
                    yield Label("Логотип організації", classes="settings-section-title")
                    # Замість wx.StaticBitmap виводимо шлях або статус у Static
                    yield Static("Шлях до файлу логотипу:", classes="settings-label")
                    with Horizontal(classes="settings-row"):
                        yield Input(placeholder="Шлях до зображення (*.png)", id="settings-logo-path")
                        yield Button("Зберегти лого", variant="primary", id="settings-logo-save")

            # --- Блок налаштування звітів ---
            with Vertical(id="settings-report-box"):
                yield Label("Налаштування звітів", classes="settings-section-title")
                yield Label("Місце збереження файлів EXCEL", classes="settings-label")
                with Horizontal(classes="settings-row"):
                    yield Input(value=self.zvit_dir or "", placeholder="Шлях до папки звітів", id="settings-report-dir")
                
                yield Label("Наповнення таблиць", classes="settings-label")
                
                # Сітка чекбоксів колонок
                with Horizontal(id="settings-report-grid"):
                    self._report_column_checkboxes = []
                    for i in range(14):
                        label_text = ALL_COLUMN_LABELS[i] if i < len(ALL_COLUMN_LABELS) else f"Колонка {i}"
                        is_checked = i < len(self._selected_report_fields_flags) and self._selected_report_fields_flags[i] == 1
                        chk = Checkbox(label_text, id=f"rep-col-{i}", value=is_checked)
                        self._report_column_checkboxes.append(chk)
                        yield chk
                    
                    last_flag_val = self._selected_report_fields_flags[14] if len(self._selected_report_fields_flags) > 14 else 0
                    self.rno_checkbox = Checkbox("РНОКПП", id="rep-rno", value=last_flag_val in (1, 3))
                    self.dob_checkbox = Checkbox("Дата народження", id="rep-dob", value=last_flag_val in (2, 3))
                    yield self.rno_checkbox
                    yield self.dob_checkbox

                with Horizontal(classes="settings-row"):
                    yield Button("Встановити колони звіту", variant="primary", id="settings-save-report-cols")

            # --- Блок глобальних змінних (Звання / Підрозділи) ---
            with Vertical(id="settings-global-box"):
                yield Label("Назви підрозділів / звань", classes="settings-section-title")
                
                with Horizontal(classes="settings-row"):
                    yield Label("Звання:", classes="settings-label")
                    yield Select([(r, r) for r in self._loaded_ranks], id="settings-rank-select", prompt="Виберіть звання")
                    yield Input(placeholder="Нове звання", id="settings-rank-entry")
                    yield Checkbox("— видалити", id="settings-rank-delete")

                with Horizontal(classes="settings-row"):
                    yield Label("Підрозділ:", classes="settings-label")
                    yield Select([(u, u) for u in self._loaded_units], id="settings-unit-select", prompt="Виберіть підрозділ")
                    yield Input(placeholder="Новий підрозділ", id="settings-unit-entry")
                    yield Checkbox("— видалити", id="settings-unit-delete")

                with Horizontal(classes="settings-row"):
                    yield Button("Зберегти зміни", variant="primary", id="settings-save-global")
                    yield Button("Очистити", id="settings-clear-global")

            # Статусний рядок усередині вкладки за потреби
            yield Static("", id="settings-status")

    def on_mount(self) -> None:
        if self.show_hellou in (1, 3) and self.search_tab and hasattr(self.search_tab, "on_t_sizer_click"):
            self.search_tab.on_t_sizer_click(None)
        self._update_global_vars_ui_state()

    def _load_service_settings_data(self):
        cursor = None
        settings_row = None
        try:
            if self.conn:
                cursor = self.conn.cursor()
                settings_row = get_service_settings_data(cursor)
        except Exception as e:
            self.notify(f"Помилка завантаження налаштувань: {e}", severity="error")
        finally:
            if cursor:
                cursor.close()

        self.zvit_dir = ""
        self.zvit_fields = ""
        self.show_hellou = 0
        self.service_id = None
        self.service_pass = None
        self.cookies = None
        self.last_time_changes = None

        if settings_row:
            indices = ServiceSettingsIndices
            if indices.ZVIT_DIR < len(settings_row) and settings_row[indices.ZVIT_DIR] is not None:
                self.zvit_dir = str(settings_row[indices.ZVIT_DIR])
            if indices.ZVIT_FIELDS < len(settings_row) and settings_row[indices.ZVIT_FIELDS] is not None:
                self.zvit_fields = str(settings_row[indices.ZVIT_FIELDS])
            if indices.SHOW_HELLOU < len(settings_row) and settings_row[indices.SHOW_HELLOU] is not None:
                try:
                    self.show_hellou = int(settings_row[indices.SHOW_HELLOU])
                except (ValueError, TypeError):
                    self.show_hellou = 0
            if indices.SERVICE_ID < len(settings_row) and settings_row[indices.SERVICE_ID] is not None:
                self.service_id = settings_row[indices.SERVICE_ID]
            if indices.SERVICE_PASS < len(settings_row) and settings_row[indices.SERVICE_PASS] is not None:
                self.service_pass = settings_row[indices.SERVICE_PASS]
            if indices.COOKIES < len(settings_row) and settings_row[indices.COOKIES] is not None:
                self.cookies = settings_row[indices.COOKIES]
            if indices.LAST_TIME_CHANGES < len(settings_row) and settings_row[indices.LAST_TIME_CHANGES] is not None:
                self.last_time_changes = settings_row[indices.LAST_TIME_CHANGES]

    def _parse_zvit_fields(self):
        self._selected_report_fields_flags = []
        zvit_fields_str = self.zvit_fields
        if not zvit_fields_str:
            zvit_fields_str = "0," * 14 + "0"
        try:
            self._selected_report_fields_flags = [int(f) for f in zvit_fields_str.split(",")]
            while len(self._selected_report_fields_flags) < 15:
                self._selected_report_fields_flags.append(0)
            self._selected_report_fields_flags = self._selected_report_fields_flags[:15]
        except (ValueError, TypeError):
            self.notify("Некоректний формат налаштувань колонок звіту.", severity="error")
            self._selected_report_fields_flags = [0] * 15

    def _load_global_libs_data(self):
        self._loaded_units = ["", "Створити >"]
        self._loaded_ranks = ["", "Створити >"]
        cursor = None
        try:
            if self.conn:
                cursor = self.conn.cursor()
                loaded_ranks, loaded_units = get_units_and_ranks(cursor)
                if loaded_units:
                    self._loaded_units.extend([str(u).strip() for u in loaded_units if u and str(u).strip()])
                if loaded_ranks:
                    self._loaded_ranks.extend([str(r).strip() for r in loaded_ranks if r and str(r).strip()])
                
                self._loaded_units = list(dict.fromkeys(self._loaded_units))
                self._loaded_ranks = list(dict.fromkeys(self._loaded_ranks))

                units_sorted = sorted(self._loaded_units[2:]) if len(self._loaded_units) > 2 else []
                self._loaded_units = ["", "Створити >"] + units_sorted
                ranks_sorted = sorted(self._loaded_ranks[2:]) if len(self._loaded_ranks) > 2 else []
                self._loaded_ranks = ["", "Створити >"] + ranks_sorted
        except Exception as e:
            self.notify(f"Помилка завантаження довідників: {e}", severity="error")
        finally:
            if cursor:
                cursor.close()

    def _refresh_global_libs_ui(self):
        self._load_global_libs_data()
        try:
            self.query_one("#settings-unit-select", Select).set_options([(u, u) for u in self._loaded_units])
            self.query_one("#settings-rank-select", Select).set_options([(r, r) for r in self._loaded_ranks])
        except Exception:
            pass
        self.on_clear_global_vars()
        if self.kartka_panel and hasattr(self.kartka_panel, "refresh_data_after_change_setuptab"):
            self.kartka_panel.refresh_data_after_change_setuptab(self._loaded_ranks, self._loaded_units)

    def _update_global_vars_ui_state(self):
        try:
            sel_rank = self.query_one("#settings-rank-select", Select).value
            sel_unit = self.query_one("#settings-unit-select", Select).value
            
            rank_entry = self.query_one("#settings-rank-entry", Input)
            unit_entry = self.query_one("#settings-unit-entry", Input)
            
            if sel_rank and sel_rank != Select.NULL and sel_rank != "Створити >":
                rank_entry.value = str(sel_rank)
            elif sel_rank == "Створити >":
                rank_entry.value = ""

            if sel_unit and sel_unit != Select.NULL and sel_unit != "Створити >":
                unit_entry.value = str(sel_unit)
            elif sel_unit == "Створити >":
                unit_entry.value = ""
        except Exception:
            pass

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id in ("settings-rank-select", "settings-unit-select"):
            self._update_global_vars_ui_state()

    def on_checkbox_changed(self, event: Checkbox.Changed) -> None:
        if event.checkbox.id in ("show-hello-chk", "show-dead-chk"):
            self.on_toggle_show_hello(event)

    def on_toggle_show_hello(self, event):
        state_1 = self.query_one("#show-hello-chk", Checkbox).value
        state_2 = self.query_one("#show-dead-chk", Checkbox).value

        if not state_1 and self.search_tab and hasattr(self.search_tab, "clear_tab1"):
            self.search_tab.clear_tab1(None)
        elif state_1 and self.search_tab and hasattr(self.search_tab, "on_t_sizer_click"):
            self.search_tab.on_t_sizer_click(None)

        if state_1 and state_2:
            state_onoff = 3
        elif state_1:
            state_onoff = 1
        elif state_2:
            state_onoff = 2
        else:
            state_onoff = 0

        self.show_hellou = state_onoff
        self.update_show_hellou_in_db(self.show_hellou)
        self.notify("Налаштування відображення оновлено")

    def update_show_hellou_in_db(self, value):
        cursor = None
        try:
            if self.conn:
                cursor = self.conn.cursor()
                cursor.execute("UPDATE service_ SET show_hellou = ? WHERE id = 1", (value,))
                self.conn.commit()
        except Exception as e:
            if self.conn:
                self.conn.rollback()
            self.notify(f"Помилка збереження статистики: {e}", severity="error")
        finally:
            if cursor:
                cursor.close()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        btn_id = event.button.id
        if btn_id == "settings-change-password":
            self.on_change_password()
        elif btn_id == "settings-logo-save":
            self.on_save_logo()
        elif btn_id == "settings-save-report-cols":
            self.on_save_report_column_selection()
        elif btn_id == "settings-save-global":
            self.on_save_global_vars()
        elif btn_id == "settings-clear-global":
            self.on_clear_global_vars()

    def on_save_logo(self):
        path = self.query_one("#settings-logo-path", Input).value.strip()
        if not path or not os.path.exists(path):
            self.notify("Не вказано коректний шлях до файлу логотипу", severity="error")
            return
        cursor = None
        try:
            with open(path, "rb") as f:
                logo_data = f.read()
            if self.conn:
                cursor = self.conn.cursor()
                cursor.execute("UPDATE service_ SET logo = ? WHERE id = 1", (logo_data,))
                if cursor.rowcount == 0:
                    cursor.execute("INSERT INTO service_ (id, logo) VALUES (1, ?)", (logo_data,))
                self.conn.commit()
                self.notify("Логотип успішно збережено в базу!")
                
                if self.search_tab and hasattr(self.search_tab, "refresh_logo"):
                    self.search_tab.refresh_logo()
                if self.info_panel and hasattr(self.info_panel, "refresh_logo"):
                    self.info_panel.refresh_logo()
                if self.kartka_panel and hasattr(self.kartka_panel, "refresh_logo"):
                    self.kartka_panel.refresh_logo()
                if self.tab4_panel and hasattr(self.tab4_panel, "refresh_tree"):
                    self.tab4_panel.refresh_tree()
        except Exception as e:
            self.notify(f"Помилка збереження логотипу: {e}", severity="error")
        finally:
            if cursor:
                cursor.close()

    def on_change_password(self):
        old_pass = self.query_one("#settings-old-pass", Input).value
        new_pass1 = self.query_one("#settings-new-pass", Input).value
        new_pass2 = self.query_one("#settings-repeat-pass", Input).value

        if not new_pass1 or not new_pass2:
            self.notify("Порожні паролі неприйнятні.", severity="warning")
            return
        if new_pass1 != new_pass2:
            self.notify("Нові паролі не збігаються.", severity="warning")
            return
        if old_pass == new_pass1:
            self.notify("Новий пароль збігається зі старим.", severity="warning")
            return

        temp_db = None
        temp_cursor = None
        try:
            temp_db, temp_cursor = connect_to_database(old_pass, self.database_path)
            if temp_db is None or temp_cursor is None:
                self.notify("Введено невірний старий пароль.", severity="error")
                return

            temp_cursor.execute(f"PRAGMA rekey = '{new_pass2}';")
            temp_db.commit()
            self.notify("Пароль бази даних успішно змінено. Перезапустіть програму.", severity="information")

            self.query_one("#settings-old-pass", Input).value = ""
            self.query_one("#settings-new-pass", Input).value = ""
            self.query_one("#settings-repeat-pass", Input).value = ""
        except Exception as e:
            self.notify(f"Помилка при зміні паролю: {e}", severity="error")
            if temp_db:
                temp_db.rollback()
        finally:
            if temp_cursor:
                temp_cursor.close()
            if temp_db:
                temp_db.close()

    def on_save_report_column_selection(self):
        selected_flags_list = []
        for i in range(14):
            chk = self.query_one(f"#rep-col-{i}", Checkbox)
            selected_flags_list.append("1" if chk.value else "0")

        rno_val = self.query_one("#rep-rno", Checkbox).value
        dob_val = self.query_one("#rep-dob", Checkbox).value
        last_flag_value = 0
        if rno_val and not dob_val:
            last_flag_value = 1
        elif not rno_val and dob_val:
            last_flag_value = 2
        elif rno_val and dob_val:
            last_flag_value = 3

        selected_flags_list.append(str(last_flag_value))
        selected_fields_zvit_str = ",".join(selected_flags_list)

        cursor = None
        try:
            if self.conn:
                cursor = self.conn.cursor()
                cursor.execute("UPDATE service_ SET zvit_fields = ? WHERE id = 1", (selected_fields_zvit_str,))
                self.conn.commit()
                self.notify("Налаштування колонок звіту успішно збережено.")
                if self.tab4_panel and hasattr(self.tab4_panel, "refresh_tree"):
                    self.tab4_panel.refresh_tree()
        except Exception as e:
            if self.conn:
                self.conn.rollback()
            self.notify(f"Помилка збереження налаштувань звіту: {e}", severity="error")
        finally:
            if cursor:
                cursor.close()

    def on_save_global_vars(self):
        sel_rank = self.query_one("#settings-rank-select", Select).value
        new_rank = self.query_one("#settings-rank-entry", Input).value.strip()
        del_rank = self.query_one("#settings-rank-delete", Checkbox).value

        sel_unit = self.query_one("#settings-unit-select", Select).value
        new_unit = self.query_one("#settings-unit-entry", Input).value.strip()
        del_unit = self.query_one("#settings-unit-delete", Checkbox).value

        cursor = None
        try:
            if self.conn:
                cursor = self.conn.cursor()
                if del_rank and sel_rank and sel_rank != Select.NULL:
                    cursor.execute("DELETE FROM libs WHERE rank_src = ?", (sel_rank,))
                if del_unit and sel_unit and sel_unit != Select.NULL:
                    cursor.execute("DELETE FROM libs WHERE unit_src = ?", (sel_unit,))

                if new_rank and sel_rank == "Створити >":
                    cursor.execute("INSERT INTO libs (rank_src) VALUES (?)", (new_rank,))
                elif new_rank and sel_rank and sel_rank != Select.NULL and new_rank != sel_rank:
                    cursor.execute("UPDATE libs SET rank_src = ? WHERE rank_src = ?", (new_rank, sel_rank))
                    cursor.execute("UPDATE personality SET rank = ? WHERE rank = ?", (new_rank, sel_rank))

                if new_unit and sel_unit == "Створити >":
                    cursor.execute("INSERT INTO libs (unit_src) VALUES (?)", (new_unit,))
                elif new_unit and sel_unit and sel_unit != Select.NULL and new_unit != sel_unit:
                    cursor.execute("UPDATE libs SET unit_src = ? WHERE unit_src = ?", (new_unit, sel_unit))
                    cursor.execute("UPDATE personality SET unit = ? WHERE unit = ?", (new_unit, sel_unit))

                self.conn.commit()
                self.notify("Глобальні змінні успішно оновлено!")
                self._refresh_global_libs_ui()
                if self.tab4_panel and hasattr(self.tab4_panel, "refresh_tree"):
                    self.tab4_panel.refresh_tree()
        except Exception as e:
            if self.conn:
                self.conn.rollback()
            self.notify(f"Помилка збереження довідників: {e}", severity="error")
        finally:
            if cursor:
                cursor.close()

    def on_clear_global_vars(self):
        try:
            self.query_one("#settings-rank-select", Select).value = Select.NULL
            self.query_one("#settings-unit-select", Select).value = Select.NULL
            self.query_one("#settings-rank-entry", Input).value = ""
            self.query_one("#settings-unit-entry", Input).value = ""
            self.query_one("#settings-rank-delete", Checkbox).value = False
            self.query_one("#settings-unit-delete", Checkbox).value = False
        except Exception:
            pass
