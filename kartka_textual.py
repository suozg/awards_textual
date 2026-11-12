# kartka_textual.py
from __future__ import annotations

import base64
import re
from io import BytesIO

from sqlcipher3 import dbapi2 as sqlite3
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Checkbox, Input, Label, Select, Static, TextArea

try:
    from textual_image.widget import Image
    HAS_TEXTUAL_IMAGE = True
except ImportError:
    HAS_TEXTUAL_IMAGE = False

from database_logic_textual import get_treedata, get_units_and_ranks, is_valid_INN


class ConfirmDeletePresentationModal(ModalScreen[str]):
    """Модальне вікно для видалення подання зі зв'язаною нагородою."""

    def __init__(self, cursor, presentation_id):
        super().__init__()
        self.cursor = cursor
        self.presentation_id = presentation_id
        self.has_meed = False
        self.check_linked_meed()

    def check_linked_meed(self) -> None:
        try:
            self.cursor.execute(
                "SELECT id_meed FROM presentation WHERE id = ?",
                (self.presentation_id,),
            )
            row = self.cursor.fetchone()
            if row and row[0] is not None:
                # Перевіряємо, чи існує таке нагородження в таблиці meed
                self.cursor.execute("SELECT id FROM meed WHERE id = ?", (row[0],))
                if self.cursor.fetchone():
                    self.has_meed = True
        except sqlite3.Error:
            self.has_meed = False

    def compose(self) -> ComposeResult:
        msg = "Дійсно видалити запис про подання?"
        if self.has_meed:
            msg = "Знайдено запис про пов'язану нагороду, яка може існувати в натурі. Видалити разом запис про нагороду?"

        with Vertical(id="link-box"):
            yield Label("Видалення подання", id="link-title")
            yield Static(msg, id="link-label")
            with Horizontal():
                if self.has_meed:
                    yield Button("Видалити з нагородою", variant="error", id="del-both-btn")
                    yield Button("Тільки подання", variant="warning", id="del-pres-only-btn")
                else:
                    yield Button("Видалити", variant="error", id="del-pres-only-btn")
                yield Button("Скасувати", id="cancel-btn")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "del-both-btn":
            self.dismiss("both")
        elif event.button.id == "del-pres-only-btn":
            self.dismiss("pres_only")
        else:
            self.dismiss("cancel")


class ConfirmDeleteMeedModal(ModalScreen[str]):
    """Модальне вікно для видалення нагородження зі зв'язаним поданням."""

    def __init__(self, cursor, meed_id):
        super().__init__()
        self.cursor = cursor
        self.meed_id = meed_id
        self.linked_pres_id = None
        self.check_linked_presentation()

    def check_linked_presentation(self) -> None:
        try:
            self.cursor.execute(
                "SELECT id FROM presentation WHERE id_meed = ?",
                (self.meed_id,),
            )
            row = self.cursor.fetchone()
            if row:
                self.linked_pres_id = row[0]
        except sqlite3.Error:
            self.linked_pres_id = None

    def compose(self) -> ComposeResult:
        msg = "Дійсно видалити запис про нагородження?"
        if self.linked_pres_id:
            msg = f"Видалити пов'язане подання (ID: {self.linked_pres_id})? Якщо ні, подання перейде в категорію 'у залишку'."

        with Vertical(id="link-box"):
            yield Label("Видалення нагородження", id="link-title")
            yield Static(msg, id="link-label")
            with Horizontal():
                if self.linked_pres_id:
                    yield Button("Видалити з поданням", variant="error", id="del-both-btn")
                    yield Button("Тільки нагороду (подання у залишок)", variant="warning", id="del-meed-only-btn")
                else:
                    yield Button("Видалити", variant="error", id="del-meed-only-btn")
                yield Button("Скасувати", id="cancel-btn")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "del-both-btn":
            self.dismiss("both")
        elif event.button.id == "del-meed-only-btn":
            self.dismiss("meed_only")
        else:
            self.dismiss("cancel")


class ConfirmDeleteModal(ModalScreen[bool]):
    """Модальне вікно підтвердження видалення особи та пов'язаних записів."""

    def __init__(self, cursor, person_id):
        super().__init__()
        self.cursor = cursor
        self.person_id = person_id
        self.pres_count = 0
        self.meed_count = 0
        self.load_counts()

    def load_counts(self) -> None:
        try:
            self.cursor.execute(
                "SELECT COUNT(*) FROM presentation WHERE id_personality = ?",
                (self.person_id,),
            )
            res_p = self.cursor.fetchone()
            self.pres_count = res_p[0] if res_p else 0

            self.cursor.execute(
                "SELECT COUNT(*) FROM meed WHERE id_personality = ?",
                (self.person_id,),
            )
            res_m = self.cursor.fetchone()
            self.meed_count = res_m[0] if res_m else 0
        except sqlite3.Error:
            self.pres_count = 0
            self.meed_count = 0

    def compose(self) -> ComposeResult:
        parts = []
        if self.pres_count > 0:
            parts.append(f"подань: {self.pres_count}")
        if self.meed_count > 0:
            parts.append(f"нагороджень: {self.meed_count}")

        if parts:
            related_str = "Знайдено " + ", ".join(parts) + ". "
            msg = f"{related_str}Видалення запису про особу призведе до втрати цих записів. Продовжити?"
        else:
            msg = "Дійсно видалити запис про особу?"

        with Vertical(id="link-box"):
            yield Label("Підтвердження видалення", id="link-title")
            yield Static(msg, id="link-label")
            with Horizontal():
                yield Button("Видалити", variant="error", id="confirm-del-btn")
                yield Button("Скасувати", id="cancel-btn")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "confirm-del-btn":
            self.dismiss(True)
        else:
            self.dismiss(False)


class LinkDialogModal(ModalScreen[int | None]):
    """Модальне вікно для прив'язки подання до нагороди."""

    def __init__(self, conn, cursor, query_ids):
        super().__init__()
        self.conn = conn
        self.cursor = cursor
        self.query_ids = query_ids  # [person_id, meed_id, presentation_id]
        self.person_id, self.meed_id, self.presentation_id = query_ids
        self.results_data = []

    def compose(self) -> ComposeResult:
        with Vertical(id="link-box"):
            yield Label("Прив'язка до запису", id="link-title")
            yield Static("", id="link-label")
            yield Select([], id="link-select", prompt="Виберіть запис для прив'язки")
            with Horizontal():
                yield Button("Пов'язати", variant="primary", id="link-btn")
                yield Button("Скасувати", id="cancel-btn")

    def on_mount(self) -> None:
        self.load_data()

    def load_data(self) -> None:
        try:
            if self.presentation_id is not None:
                label_str = "нагородження"
                sql = """
                    SELECT m.id, m.decree, m.date_decree
                    FROM meed AS m
                    WHERE m.id_personality = ?
                      AND NOT EXISTS (
                          SELECT 1 FROM presentation AS p WHERE p.id_meed = m.id
                      )
                    ORDER BY m.date_decree DESC, m.id DESC
                """
                self.cursor.execute(sql, (self.person_id,))
            elif self.meed_id is not None:
                label_str = "подання"
                sql = """
                    SELECT id, registration, date_registration
                    FROM presentation
                    WHERE id_meed IS NULL AND id_personality = ?
                    ORDER BY date_registration DESC, id DESC
                """
                self.cursor.execute(sql, (self.person_id,))
            else:
                self.dismiss(None)
                return

            rows = self.cursor.fetchall()
            options = []
            self.results_data = []
            for row in rows:
                display_str = f"{row[1] or 'б/н'} від {row[2] or '—'}"
                options.append((display_str, int(row[0])))
                self.results_data.append(int(row[0]))

            self.query_one("#link-label", Static).update(
                f"Знайдено записів ({label_str}): {len(rows)}"
            )
            self.query_one("#link-select", Select).set_options(options)

        except sqlite3.Error as exc:
            self.notify(
                f"Помилка завантаження даних для прив'язки: {exc}",
                severity="error",
            )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel-btn":
            self.dismiss(None)
            return
        if event.button.id != "link-btn":
            return

        selected_id = self.query_one("#link-select", Select).value
        if selected_id is None:
            self.notify("Виберіть запис для прив'язування.", severity="warning")
            return

        try:
            if self.presentation_id is not None:
                self.cursor.execute(
                    "UPDATE presentation SET id_meed = ? WHERE id = ?",
                    (int(selected_id), self.presentation_id),
                )
            elif self.meed_id is not None:
                self.cursor.execute(
                    "UPDATE presentation SET id_meed = ? WHERE id = ?",
                    (self.meed_id, int(selected_id)),
                )
            self.conn.commit()
            self.dismiss(int(selected_id))
        except sqlite3.Error as exc:
            self.conn.rollback()
            self.notify(f"Помилка прив'язки: {exc}", severity="error")

class KartkaTab(VerticalScroll):
    """Вкладка «Картка» для редагування даних особи, подань і нагороджень."""

    def __init__(self, conn=None, cursor=None, settings_manager=None, **kwargs):
        super().__init__(**kwargs)
        self.conn = conn
        self.cursor = cursor
        self.settings_manager = settings_manager
        self.current_person_id = None
        self.current_presentation_id = None
        self.current_meed_id = None
        self.latest_search_person_ids_list = []
        self.source_data_award_and_presentation = {}
        self._loaded_ranks = []
        self._loaded_units = []
        self._loaded_award_names = []
        self._award_id_to_name = {}
        self.awards_data = {}
        self.presentations_list = []
        self.meed_list = []

        # --- Завантаження дефолтного зображення (заглушки) ---
        self.default_award_image_bytes = None
        if (
            self.settings_manager
            and hasattr(self.settings_manager, "is_loaded")
            and self.settings_manager.is_loaded
            and hasattr(self.settings_manager, "get_logo_blob")
        ):
            self.default_award_image_bytes = self.settings_manager.get_logo_blob()       

    def compose(self) -> ComposeResult:
        with Vertical(classes="box"):
            yield Label("Інформація про особу", classes="legend")
            with Horizontal(classes="row"):
                yield Select([], id="person-select", prompt="Виберіть особу")
                yield Static("-", id="person-count")
            with Horizontal(classes="row"):
                yield Input(placeholder="Прізвище Ім'я По батькові", id="full-name")
                yield Input(placeholder="РНОКПП (ІНН)", id="inn", max_length=10)
            with Horizontal(classes="row"):
                yield Select([], id="rank-select", prompt="Звання")
                yield Select([], id="unit-select", prompt="Підрозділ")
                yield Static("Дата народження: ---- -- --", id="birth-date-label")

        with Horizontal(id="card-screen-switch", classes="row"):
            yield Button("Подання", id="show-pres", variant="primary")
            yield Button("Нагородження", id="show-meed")

        with Vertical(id="pres-panel", classes="box screen-panel"):
            yield Label("Параметри подання", classes="legend")
            with Horizontal(classes="row"):
                yield Select([], id="pres-select", prompt="Виберіть подання")
                yield Static("-", id="pres-count")
            with Horizontal(classes="row"):
                yield Input(placeholder="Номер подання", id="pres-number")
                yield Input(placeholder="Дата (РРРР-ММ-ДД)", id="pres-date")
                yield Select([("ВП", "0"), ("МПЗ", "1"), ("Інші", "2")], id="pres-worker", prompt="Виконавець")
                yield Input(placeholder="Рух", id="pres-movement")
            
            # Текст подання на всю ширину та ряд чекбоксів під ним
            with Vertical(classes="row"):
                yield Label("Текст подання:")
                yield TextArea(id="pres-text")
                with Horizontal(id="pres-checkboxes-row"):
                    yield Checkbox("Посмертно", id="pres-posthumous")
                    yield Checkbox("Відмовлено", id="pres-denied")
                    yield Checkbox("Відв'язати нагороду", id="pres-unlink", classes="hidden")
                    yield Button("Перейти до пов'язаного нагородження", id="goto-meed-btn", variant="default")

        with Vertical(id="meed-panel", classes="box screen-panel"):
            yield Label("Деталі нагородження", classes="legend")
            
            # Головний контейнер: ліворуч поля, праворуч — картинка
            with Horizontal(id="meed-content-row"):
                with Vertical(id="meed-fields-col"):
                    # Ряд із селектором, лічильником та кнопкою переходу до подання
                    with Horizontal(classes="row"):
                        yield Select([], id="meed-select", prompt="Виберіть нагородження")
                        yield Static("-", id="meed-count")
                        yield Button("🔗 Перейти до подання", id="goto-pres-btn", variant="default")

                    with Horizontal(classes="row"):
                        yield Select([], id="award-select", prompt="Оберіть нагороду")
                    with Horizontal(classes="row"):
                        yield Input(placeholder="Рішення", id="award-basis")
                        yield Input(placeholder="Дата рішення (РРРР-ММ-ДД)", id="award-date")
                        yield Checkbox("Посмертно", id="meed-dead")
                    with Horizontal(classes="row"):
                        yield Input(placeholder="Накладна", id="consing-n")
                        yield Input(placeholder="Номер нагороди", id="number-meed")
                    with Horizontal(classes="row"):
                        yield Input(placeholder="Вручено дата (РРРР-ММ-ДД)", id="handover-date")
                        yield Input(placeholder="Вручено (особа/ID)", id="handover-name")
                        yield Checkbox("Є протокол", id="protok-handing")

                with Vertical(id="meed-image-col"):
                    if HAS_TEXTUAL_IMAGE:
                        yield Image(id="award-image")
                    else:
                        yield Static("Зображення відсутнє", id="award-image")

             
        with Horizontal(classes="row", id="card-actions-row"):
            yield Select(
                [("⌦  Видалити", "0"), ("Особу", "1"), ("Подання", "2"), ("Нагородження", "3")],
                id="delete-select",
                value="0",
            )
            yield Button("ЗБЕРЕГТИ", variant="primary", id="save-btn")
            yield Button("ОЧИСТИТИ", id="clear-btn")


    def on_mount(self) -> None:
        self.show_card_screen("pres")
        if self.cursor:
            self.load_initial_data()

    def delete_person_with_related_records(self, person_id: int) -> None:
        try:
            self.cursor.execute(
                "DELETE FROM presentation WHERE id_personality = ?",
                (person_id,),
            )
            self.cursor.execute(
                "DELETE FROM meed WHERE id_personality = ?",
                (person_id,),
            )
            self.cursor.execute(
                "DELETE FROM personality WHERE id = ?",
                (person_id,),
            )
            self.conn.commit()
        except sqlite3.Error:
            self.conn.rollback()
            raise

    def delete_presentation_with_logic(self, presentation_id: int, delete_meed: bool) -> None:
        try:
            if delete_meed:
                self.cursor.execute(
                    "SELECT id_meed FROM presentation WHERE id = ?",
                    (presentation_id,),
                )
                row = self.cursor.fetchone()
                if row and row[0] is not None:
                    self.cursor.execute("DELETE FROM meed WHERE id = ?", (row[0],))
            
            self.cursor.execute("DELETE FROM presentation WHERE id = ?", (presentation_id,))
            self.conn.commit()
        except sqlite3.Error:
            self.conn.rollback()
            raise

    def delete_meed_with_logic(self, meed_id: int, delete_pres: bool, linked_pres_id: int | None) -> None:
        try:
            self.cursor.execute("DELETE FROM meed WHERE id = ?", (meed_id,))
            
            if linked_pres_id:
                if delete_pres:
                    self.cursor.execute("DELETE FROM presentation WHERE id = ?", (linked_pres_id,))
                else:
                    self.cursor.execute("UPDATE presentation SET id_meed = NULL WHERE id = ?", (linked_pres_id,))
            
            self.conn.commit()
        except sqlite3.Error:
            self.conn.rollback()
            raise

    def show_card_screen(self, screen: str) -> None:
        """Показати лише екран подання або нагородження без очищення полів."""
        show_pres = screen != "meed"
        pres_panel = self.query_one("#pres-panel", Vertical)
        meed_panel = self.query_one("#meed-panel", Vertical)
        pres_panel.styles.display = "block" if show_pres else "none"
        meed_panel.styles.display = "none" if show_pres else "block"

        pres_button = self.query_one("#show-pres", Button)
        meed_button = self.query_one("#show-meed", Button)
        pres_button.variant = "primary" if show_pres else "default"
        meed_button.variant = "primary" if not show_pres else "default"

    def set_database(self, conn, cursor) -> None:
        self.conn = conn
        self.cursor = cursor
        self.load_initial_data()

    def load_initial_data(self) -> None:
        try:
            self._loaded_ranks, self._loaded_units = get_units_and_ranks(self.cursor)
            self._loaded_ranks = [r for r in self._loaded_ranks if r]
            self._loaded_units = [u for u in self._loaded_units if u]
            self.query_one("#rank-select", Select).set_options([(r, r) for r in self._loaded_ranks])
            self.query_one("#unit-select", Select).set_options([(u, u) for u in self._loaded_units])

            self.awards_data = get_treedata(self.cursor) or {}
            award_names = []
            self._award_id_to_name = {}
            for award_dict in self.awards_data.values():
                if not award_dict:
                    continue
                for award_name, details in award_dict.items():
                    award_names.append(award_name)
                    self._award_id_to_name[details["award_id"]] = award_name
            self._loaded_award_names = sorted(set(award_names))
            self.query_one("#award-select", Select).set_options(
                [(name, name) for name in self._loaded_award_names]
            )
        except (sqlite3.Error, RuntimeError, KeyError, TypeError, AttributeError) as exc:
            self.notify(
                f"Помилка завантаження довідників: {exc}",
                severity="error",
            )

    def populate_and_load_search_results(self, person_ids_list, source_data_award_and_presentation) -> None:
        self.latest_search_person_ids_list = person_ids_list or []
        self.source_data_award_and_presentation = source_data_award_and_presentation or {}
        self.clear_person_data()
        options = []
        for item in self.latest_search_person_ids_list:
            if len(item) > 5:
                person_id, full_name, inn = item[0], item[3], item[5]
                try:
                    inn_part = f" ({int(inn)})" if inn and str(inn).strip() else ""
                except (TypeError, ValueError):
                    inn_part = f" ({inn})" if inn else ""
                options.append((f"ID {person_id} — {full_name}{inn_part}", int(person_id)))

        person_select = self.query_one("#person-select", Select)
        person_select.set_options(options)
        self.query_one("#person-count", Static).update(str(len(options)))

        person_select.clear()
        if len(options) == 1:
            person_select.value = options[0][1]
            self.on_person_selected(options[0][1])

    def on_select_changed(self, event: Select.Changed) -> None:
        """Обробка зміни вибору."""
        if event.value is Select.NULL:
            if event.select.id == "award-select":
                image_widget = self.query_one("#award-image")
                if HAS_TEXTUAL_IMAGE and isinstance(image_widget, Image):
                    image_widget.image = None
                elif isinstance(image_widget, Static):
                    image_widget.update("Зображення нагороди відсутнє")
            return

        if event.select.id == "person-select":
            self.on_person_selected(event.value)
        elif event.select.id == "pres-select":
            self.fill_submission_fields(int(event.value))
            self.show_card_screen("pres")
        elif event.select.id == "meed-select":
            self.fill_meed_fields(int(event.value))
            self.show_card_screen("meed")
        elif event.select.id == "award-select":
            award_name = event.value
            image_data = None
            for award_dict in self.awards_data.values():
                details = award_dict.get(award_name)
                if details:
                    image_data = details.get("image")
                    break

            image_widget = self.query_one("#award-image")
            
            # Определяем, какую картинку показывать: награды или дефолтную (заглушку)
            target_image_data = image_data if image_data else self.default_award_image_bytes

            if target_image_data:
                if HAS_TEXTUAL_IMAGE and isinstance(image_widget, Image):
                    try:
                        if isinstance(target_image_data, str):
                            binary_data = base64.b64decode(target_image_data)
                        else:
                            binary_data = target_image_data
                        image_widget.image = BytesIO(binary_data)
                    except (ValueError, TypeError, OSError):
                        image_widget.image = None
                elif isinstance(image_widget, Static):
                    image_widget.update("Зображення є в базі.")
            else:
                if HAS_TEXTUAL_IMAGE and isinstance(image_widget, Image):
                    image_widget.image = None
                elif isinstance(image_widget, Static):
                    image_widget.update("Зображення нагороди відсутнє")


    def fill_meed_fields(self, list_index: int) -> None:
        if list_index < 0 or list_index >= len(self.meed_list):
            return
        item = self.meed_list[list_index]
        raw = item["raw_data"]
        self.current_meed_id = raw[13]
        
        award_select = self.query_one("#award-select", Select)
        if raw[12] is not None:
            award_select.value = raw[12]
        else:
            award_select.clear()
            
        self.query_one("#award-basis", Input).value = str(raw[3] or "")
        self.query_one("#award-date", Input).value = str(raw[2] or "")
        self.query_one("#meed-dead", Checkbox).value = bool(raw[14])
        self.query_one("#consing-n", Input).value = str(raw[7] or "")
        self.query_one("#number-meed", Input).value = str(raw[4] or "")
        self.query_one("#handover-date", Input).value = str(raw[5] or "")
        handover = str(raw[6] or "")
        self.query_one("#protok-handing", Checkbox).value = handover.endswith("$")
        self.query_one("#handover-name", Input).value = handover.removesuffix("$")
        # Зв'язок із поданням
        linked_pres_index = next((i for i, p in enumerate(self.presentations_list) if p[7] == self.current_meed_id), None)
        goto_pres_btn = self.query_one("#goto-pres-btn", Button)
        
        if linked_pres_index is not None:
            p = self.presentations_list[linked_pres_index]
            goto_pres_btn.label = f"🔗 Подання №{p[0] or 'б/н'}"
            goto_pres_btn.styles.display = "block"
        else:
            goto_pres_btn.styles.display = "none"

        image_widget = self.query_one("#award-image")
        award_name = award_select.value
        image_data = None
        for award_dict in self.awards_data.values():
            details = award_dict.get(award_name)
            if details:
                image_data = details.get("image")
                break
        
        if image_data:
            if HAS_TEXTUAL_IMAGE and isinstance(image_widget, Image):
                try:
                    if isinstance(image_data, str):
                        binary_data = base64.b64decode(image_data)
                    else:
                        binary_data = image_data
                    image_widget.image = BytesIO(binary_data)
                except (ValueError, TypeError, OSError):
                    image_widget.image = None
            elif isinstance(image_widget, Static):
                image_widget.update("Зображення є в базі.")
        else:
            if HAS_TEXTUAL_IMAGE and isinstance(image_widget, Image):
                image_widget.image = None
            elif isinstance(image_widget, Static):
                image_widget.update("Зображення нагороди відсутнє")


    def on_person_selected(self, person_id) -> None:
        if person_id is None:
            return
        person = next((p for p in self.latest_search_person_ids_list if int(p[0]) == int(person_id)), None)
        if not person:
            return

        self.current_person_id = int(person[0])
        self.current_presentation_id = None
        self.current_meed_id = None
        self.query_one("#full-name", Input).value = str(person[3] or "")
        try:
            inn_val = str(int(person[5])) if person[5] else ""
        except (TypeError, ValueError):
            inn_val = str(person[5] or "")
        self.query_one("#inn", Input).value = inn_val
        self.on_inn_focus_lost()
        rank_select = self.query_one("#rank-select", Select)
        unit_select = self.query_one("#unit-select", Select)
        if person[2]:
            rank_select.value = person[2]
        else:
            rank_select.clear()
        if person[1]:
            unit_select.value = person[1]
        else:
            unit_select.clear()

        person_data = self.source_data_award_and_presentation.get(self.current_person_id, {})
        self.presentations_list = person_data.get("presentations", [])
        self.meed_list = person_data.get("meed", [])

        pres_options = [(f"№{p[0] or 'б/н'} від {p[1] or '—'}", i) for i, p in enumerate(self.presentations_list)]
        meed_options = []
        for i, item in enumerate(self.meed_list):
            raw = item["raw_data"]
            meed_options.append((f"№{raw[4] or 'б/н'} від {raw[2] or '—'}", i))
            
        self.query_one("#pres-select", Select).set_options(pres_options)
        self.query_one("#pres-count", Static).update(str(len(pres_options)))
        self.query_one("#meed-select", Select).set_options(meed_options)
        self.query_one("#meed-count", Static).update(str(len(meed_options)))

        self.query_one("#show-pres", Button).label = f"Подання ({len(pres_options)})"
        self.query_one("#show-meed", Button).label = f"Нагородження ({len(meed_options)})"

        self.clear_submission_data()
        self.clear_meed_data()
        if pres_options:
            self.query_one("#pres-select", Select).value = pres_options[0][1]
            self.fill_submission_fields(pres_options[0][1])
        if meed_options:
            self.query_one("#meed-select", Select).value = meed_options[0][1]
            self.fill_meed_fields(meed_options[0][1])

        self.show_card_screen("meed" if meed_options else "pres")

    def fill_submission_fields(self, list_index: int) -> None:
        if list_index < 0 or list_index >= len(self.presentations_list):
            return
        p = self.presentations_list[list_index]
        self.current_presentation_id = p[6]
        self.query_one("#pres-number", Input).value = str(p[0] or "")
        self.query_one("#pres-date", Input).value = str(p[1] or "")
        worker_select = self.query_one("#pres-worker", Select)
        if p[8] is not None:
            worker_select.value = str(p[8])
        else:
            worker_select.clear()
        posthumous = p[9] == "посмертно"
        self.query_one("#pres-posthumous", Checkbox).value = posthumous
        self.query_one("#pres-movement", Input).value = "" if posthumous else str(p[9] or "")
        self.query_one("#pres-movement", Input).disabled = posthumous
        self.query_one("#pres-text", TextArea).text = str(p[10] or "")
        
        id_meed = p[7]
        self.current_meed_id = id_meed if id_meed not in (None, 0, "0", "") else None
        
        self.query_one("#pres-denied", Checkbox).value = str(id_meed) == "0"
        linked = self.current_meed_id is not None
        unlink = self.query_one("#pres-unlink", Checkbox)
        unlink.value = False
        
        goto_meed_btn = self.query_one("#goto-meed-btn", Button)
        if linked:
            unlink.remove_class("hidden")
            goto_meed_btn.styles.display = "block"
            goto_meed_btn.label = f"🔗 Перейти до пов'язаного нагородження (ID: {self.current_meed_id})"
        else:
            unlink.add_class("hidden")
            goto_meed_btn.styles.display = "none"

    def on_inn_focus_lost(self) -> None:
        inn_val = self.query_one("#inn", Input).value
        result = is_valid_INN(inn_val)
        label = self.query_one("#birth-date-label", Static)
        if result:
            label.update(f"Дата народження: {result}")
        else:
            label.update("Невірний РНОКПП" if inn_val else "Дата народження: ---- -- --")

    def clear_person_data(self) -> None:
        """Очищує поля введення, але зберігає список знайдених осіб для повторного вибору."""
        self.current_person_id = None
        self.current_presentation_id = None
        self.current_meed_id = None
        
        self.query_one("#full-name", Input).value = ""
        self.query_one("#inn", Input).value = ""
        self.query_one("#rank-select", Select).clear()
        self.query_one("#unit-select", Select).clear()
        self.query_one("#birth-date-label", Static).update("Дата народження: ---- -- --")
        
        self.query_one("#show-pres", Button).label = "Подання (0)"
        self.query_one("#show-meed", Button).label = "Нагородження (0)"
        
        self.query_one("#pres-select", Select).clear()
        self.query_one("#pres-count", Static).update("-")
        self.query_one("#meed-select", Select).clear()
        self.query_one("#meed-count", Static).update("-")
        
        self.clear_submission_data()
        self.clear_meed_data()

    def clear_submission_data(self) -> None:
        self.query_one("#pres-number", Input).value = ""
        self.query_one("#pres-date", Input).value = ""
        self.query_one("#pres-worker", Select).clear()
        self.query_one("#pres-movement", Input).value = ""
        self.query_one("#pres-movement", Input).disabled = False
        self.query_one("#pres-text", TextArea).text = ""
        self.query_one("#pres-posthumous", Checkbox).value = False
        self.query_one("#pres-denied", Checkbox).value = False
        unlink = self.query_one("#pres-unlink", Checkbox)
        unlink.value = False
        unlink.add_class("hidden")
        self.query_one("#goto-meed-btn", Button).styles.display = "none"

    def clear_meed_data(self) -> None:
        self.query_one("#award-select", Select).clear()
        self.query_one("#award-basis", Input).value = ""
        self.query_one("#award-date", Input).value = ""
        self.query_one("#meed-dead", Checkbox).value = False
        self.query_one("#consing-n", Input).value = ""
        self.query_one("#number-meed", Input).value = ""
        self.query_one("#handover-date", Input).value = ""
        self.query_one("#handover-name", Input).value = ""
        self.query_one("#protok-handing", Checkbox).value = False
        self.query_one("#goto-pres-btn", Button).styles.display = "none"
        
        image_widget = self.query_one("#award-image")
        if HAS_TEXTUAL_IMAGE and isinstance(image_widget, Image):
            if self.default_award_image_bytes:
                try:
                    if isinstance(self.default_award_image_bytes, str):
                        binary_data = base64.b64decode(self.default_award_image_bytes)
                    else:
                        binary_data = self.default_award_image_bytes
                    image_widget.image = BytesIO(binary_data)
                except (ValueError, TypeError, OSError):
                    image_widget.image = None
            else:
                image_widget.image = None
        elif isinstance(image_widget, Static):
            image_widget.update("Зображення нагороди відсутнє")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "show-pres":
            self.show_card_screen("pres")
        elif event.button.id == "show-meed":
            self.show_card_screen("meed")
        elif event.button.id == "clear-btn":
            self.clear_person_data()
            self.show_card_screen("pres")
        elif event.button.id == "save-btn":
            self.on_save()
        # Кіллер-фіча: швидкий перехід між поданням та нагородженням
        elif event.button.id == "goto-meed-btn":
            if self.current_meed_id:
                matched_meed_index = next((i for i, item in enumerate(self.meed_list) if item["raw_data"][13] == self.current_meed_id), None)
                if matched_meed_index is not None:
                    self.query_one("#meed-select", Select).value = matched_meed_index
                    self.fill_meed_fields(matched_meed_index)
                    self.show_card_screen("meed")
                else:
                    self.notify("Нагородження не знайдено в списку.", severity="warning")
        elif event.button.id == "goto-pres-btn" and self.current_meed_id:
            matched_pres_index = next((i for i, p in enumerate(self.presentations_list) if p[7] == self.current_meed_id), None)
            if matched_pres_index is not None:
                self.query_one("#pres-select", Select).value = matched_pres_index
                self.fill_submission_fields(matched_pres_index)
                self.show_card_screen("pres")

    def on_checkbox_changed(self, event: Checkbox.Changed) -> None:
        if event.checkbox.id == "pres-posthumous":
            movement = self.query_one("#pres-movement", Input)
            movement.value = "" if event.value else movement.value
            movement.disabled = event.value

    def on_save(self) -> None:
        if not self.conn or not self.cursor:
            self.notify("База даних не підключена.", severity="error")
            return
        delete_value = self.query_one("#delete-select", Select).value
        delete_mode = int(delete_value) if delete_value is not None else 0

        if delete_mode > 0:
            if delete_mode == 1 and self.current_person_id:
                modal = ConfirmDeleteModal(self.cursor, self.current_person_id)
                
                def check_delete_modal(confirmed: bool) -> None:
                    if confirmed:
                        try:
                            self.delete_person_with_related_records(self.current_person_id)
                            self.notify("Видалення успішно виконано!", severity="information")
                            self.clear_person_data()
                        except sqlite3.Error as exc:
                            self.notify(f"Помилка видалення: {exc}", severity="error")

                self.app.push_screen(modal, check_delete_modal)
                return

            elif delete_mode == 2 and self.current_presentation_id:
                modal = ConfirmDeletePresentationModal(self.cursor, self.current_presentation_id)

                def check_pres_modal(action: str) -> None:
                    if action in ("both", "pres_only"):
                        try:
                            self.delete_presentation_with_logic(
                                self.current_presentation_id, 
                                delete_meed=(action == "both")
                            )
                            self.current_presentation_id = None
                            self.notify("Видалення подання успішно виконано!", severity="information")
                            self.clear_person_data()
                        except sqlite3.Error as exc:
                            self.notify(f"Помилка видалення: {exc}", severity="error")

                self.app.push_screen(modal, check_pres_modal)
                return

            elif delete_mode == 3 and self.current_meed_id:
                modal = ConfirmDeleteMeedModal(self.cursor, self.current_meed_id)

                def check_meed_modal(action: str) -> None:
                    if action in ("both", "meed_only"):
                        try:
                            linked_pres_id = modal.linked_pres_id
                            self.delete_meed_with_logic(
                                self.current_meed_id, 
                                delete_pres=(action == "both"),
                                linked_pres_id=linked_pres_id
                            )
                            self.current_meed_id = None
                            self.notify("Видалення нагородження успішно виконано!", severity="information")
                            self.clear_person_data()
                        except sqlite3.Error as exc:
                            self.notify(f"Помилка видалення: {exc}", severity="error")

                self.app.push_screen(modal, check_meed_modal)
                return

            else:
                self.notify("Спочатку виберіть запис для видалення.", severity="warning")
                return

        full_name = re.sub(r"\s+", " ", self.query_one("#full-name", Input).value).strip()
        if not full_name:
            self.notify("Поле 'ПІБ' є обов'язковим для заповнення.", severity="error")
            return
        inn_digits = re.sub(r"\D", "", self.query_one("#inn", Input).value.strip())
        inn = int(inn_digits) if inn_digits else None
        rank = self.query_one("#rank-select", Select).value
        unit = self.query_one("#unit-select", Select).value
        rank = rank if rank is not None else None
        unit = unit if unit is not None else None
        
        # Безпечне отримання дати народження (виправлено помилку з renderable)
        birth_widget = self.query_one("#birth-date-label", Static)
        birth_text = ""
        if hasattr(birth_widget, "text"):
            birth_text = birth_widget.text
        elif hasattr(birth_widget, "renderable"):
            birth_text = str(birth_widget.renderable)

        birth_date = birth_text.split(": ", 1)[1] if "Дата народження:" in birth_text else None
        if birth_date in ("---- -- --", "Невірний РНОКПП"):
            birth_date = None

        try:
            if self.current_person_id:
                self.cursor.execute(
                    "UPDATE personality SET unit = ?, rank = ?, name = ?, date_birth = ?, inn = ? WHERE id = ?",
                    (unit, rank, full_name, birth_date, inn, self.current_person_id),
                )
            else:
                self.cursor.execute(
                    "INSERT INTO personality (unit, rank, name, date_birth, inn) VALUES (?, ?, ?, ?, ?)",
                    (unit, rank, full_name, birth_date, inn),
                )
                self.current_person_id = self.cursor.lastrowid

            pres_num = self.query_one("#pres-number", Input).value.strip()
            if pres_num:
                pres_date = self.query_one("#pres-date", Input).value.strip() or None
                worker = self.query_one("#pres-worker", Select).value
                worker_val = int(worker) if worker is not None else 2
                report = self.query_one("#pres-movement", Input).value.strip()
                if self.query_one("#pres-posthumous", Checkbox).value:
                    report = "посмертно"
                text_pres = self.query_one("#pres-text", TextArea).text
                id_meed_val = self.current_meed_id
                if self.query_one("#pres-denied", Checkbox).value:
                    id_meed_val = 0
                elif self.query_one("#pres-unlink", Checkbox).value:
                    id_meed_val = None
                if self.current_presentation_id:
                    self.cursor.execute(
                        """UPDATE presentation SET text_presentation = ?, registration = ?, date_registration = ?,
                            id_personality = ?, id_meed = ?, report = ?, worker = ? WHERE id = ?""",
                        (text_pres, pres_num, pres_date, self.current_person_id, id_meed_val, report, worker_val, self.current_presentation_id),
                    )
                else:
                    self.cursor.execute(
                        """INSERT INTO presentation (text_presentation, registration, date_registration,
                            id_personality, id_meed, report, worker) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                        (text_pres, pres_num, pres_date, self.current_person_id, id_meed_val, report, worker_val),
                    )
                    self.current_presentation_id = self.cursor.lastrowid

            award_basis = self.query_one("#award-basis", Input).value.strip()
            if award_basis:
                award_name = self.query_one("#award-select", Select).value
                award_id = next((aid for aid, name in self._award_id_to_name.items() if name == award_name), None)
                award_date = self.query_one("#award-date", Input).value.strip() or None
                number_meed = self.query_one("#number-meed", Input).value.strip()
                consing = self.query_one("#consing-n", Input).value.strip()
                if not number_meed and consing:
                    number_meed = "бн"
                dead_val = 1 if self.query_one("#meed-dead", Checkbox).value else None
                handover_date = self.query_one("#handover-date", Input).value.strip() or None
                handover_name = self.query_one("#handover-name", Input).value.strip()
                if self.query_one("#protok-handing", Checkbox).value:
                    handover_name += "$"
                if self.current_meed_id:
                    self.cursor.execute(
                        """UPDATE meed SET id_personality = ?, id_award = ?, date_decree = ?, decree = ?,
                            number_meed = ?, date_handover = ?, handover = ?, consignment_note = ?, dead = ? WHERE id = ?""",
                        (self.current_person_id, award_id, award_date, award_basis, number_meed, handover_date, handover_name, consing, dead_val, self.current_meed_id),
                    )
                else:
                    self.cursor.execute(
                        """INSERT INTO meed (id_personality, id_award, date_decree, decree, number_meed,
                            date_handover, handover, consignment_note, dead) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (self.current_person_id, award_id, award_date, award_basis, number_meed, handover_date, handover_name, consing, dead_val),
                    )
                    self.current_meed_id = self.cursor.lastrowid

            self.conn.commit()
            if not self.query_one("#pres-unlink", Checkbox).value and not self.query_one("#pres-denied", Checkbox).value:
                modal = LinkDialogModal(
                    self.conn,
                    self.cursor,
                    [self.current_person_id, self.current_meed_id, self.current_presentation_id],
                )
                def check_modal(result):
                    if result:
                        self.notify("Записи успішно пов'язано!", severity="information")
                self.app.push_screen(modal, check_modal)
            self.notify("Операція збереження завершена.", severity="information")
        except sqlite3.Error as exc:
            self.conn.rollback()
            self.notify(f"Помилка збереження: {exc}", severity="error")

           
    def delete_person_with_related_records(self, person_id: int) -> None:
        try:
            self.cursor.execute(
                "DELETE FROM presentation WHERE id_personality = ?",
                (person_id,),
            )
            self.cursor.execute(
                "DELETE FROM meed WHERE id_personality = ?",
                (person_id,),
            )
            self.cursor.execute(
                "DELETE FROM personality WHERE id = ?",
                (person_id,),
            )
            self.conn.commit()
        except sqlite3.Error:
            self.conn.rollback()
            raise
