# zvity_textual.py
from __future__ import annotations

from datetime import datetime
from typing import Any, ClassVar

from sqlcipher3 import dbapi2 as sqlite3
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.css.query import NoMatches
from textual.widgets import Button, Checkbox, DataTable, Input, Label, Select, Static

from config import ALL_COLUMN_LABELS, START_YEAR
from database_logic_textual import (
    RankingValues,
    get_formatted_unique_awarded_distinctions,
    get_service_settings_data,
    get_units_and_ranks,
)
from report_export import export_report_csv, export_report_xlsx

PERSON_CATEGORY_ALL = 6
AWARD_HANDOVER_STATUS_REMAINING = 1
AWARD_HANDOVER_STATUS_ISSUED = 2
AWARD_HANDOVER_STATUS_ASSIGNED = 3
SUBMISSION_STATUS_ALL = 4


class ZvitTab(Vertical):
    """Порт вкладки звітів з wxPython в Textual."""

    def __init__(self, conn=None, cursor=None, db_path=None, key=None, **kwargs):
        super().__init__(**kwargs)
        self.conn = conn
        self.cursor = cursor
        self.db_path = db_path
        self.key = key

        self.start_date = Input(value=self._default_start(), id="zvit-start-date")
        self.end_date = Input(value=self._default_end(), id="zvit-end-date")

        self.worker = Select(
            [("Усі", ""), ("ВП", "0"), ("МПЗ", "1"), ("Інші", "2")],
            value="",
            id="zvit-worker",
        )
        self.person_category = Select(
            [
                ("Усі особи", PERSON_CATEGORY_ALL),
                ("Офіцери", 1),
                ("Сержанти", 2),
                ("Солдати", 3),
                ("Військові", 4),
                ("Цивільні", "civilian"),
            ],
            value=PERSON_CATEGORY_ALL,
            id="zvit-person-category",
        )
        self.unit = Select([("Усі", "")], value="", id="zvit-unit")
        self.award_rank = Select([("Усі", "")], value="", id="zvit-award-rank")
        self.award_name = Select([("Усі", "")], value="", id="zvit-award-name")

        self.consignment_note = Select(
            [("Усі накладні", "")], value="", id="zvit-consignment-note"
        )
        self.specific_submission_number = Select(
            [("Оберіть подання", "")],
            value="",
            id="zvit-specific-submission-number",
        )
        # Значення селектора сопоставляются с номером и датой регистрации.
        self._submission_options: dict[str, tuple[str, str]] = {}

        self.all_time = Checkbox("увесь час", value=False, id="zvit-all-time")
        self.posthumous = Checkbox("посмертно", value=False, id="zvit-posthumous")
        self.by_name = Checkbox(" назва", value=False, id="zvit-by-name")
        self.issue_protocols = Checkbox("відсутні протоколи видачі", value=False, id="zvit-issue-protocols")
        self.specific_submission = Checkbox("окреме подання", value=False, id="zvit-specific-submission")

        self.handover_status = Select(
            [
                ("призначені", AWARD_HANDOVER_STATUS_ASSIGNED),
                ("видані", AWARD_HANDOVER_STATUS_ISSUED),
                ("залишок в натурі", AWARD_HANDOVER_STATUS_REMAINING),
            ],
            value=AWARD_HANDOVER_STATUS_ASSIGNED,
            id="zvit-handover-status",
        )
        
        self.submission_status = Select(
            [
                ("Усі", SUBMISSION_STATUS_ALL),
                ("Погоджені", 1),
                ("Не погоджені", 2),
                ("У залишку", 3),
            ],
            value=SUBMISSION_STATUS_ALL,
            id="zvit-submission-status",
        )

    def set_database(self, conn, cursor):
        self.conn = conn
        self.cursor = cursor
        self._load_reference_data()
        self._apply_ui_state()
        #self.refresh_report()

    def compose(self) -> ComposeResult:
        with Vertical(id="zvit-root"):
            with Horizontal(id="zvit-top-row"):
                yield Label("Період виборки:", classes="zvit-label")
                yield self.start_date
                yield Label("—", classes="zvit-range-separator")
                yield self.end_date
                yield self.all_time

            with Horizontal(id="zvit-middle-row"):
                yield Label("виконавець:", classes="zvit-label")
                yield self.worker
                yield Label("категорія:", classes="zvit-label")
                yield self.person_category
                yield Label("підрозділ:", classes="zvit-label")
                yield self.unit
                yield self.posthumous

            with Horizontal(id="zvit-award-row"):
                yield Label("нагорода:", classes="zvit-label")
                yield self.award_rank
                yield self.by_name
                yield self.award_name

            with Horizontal(id="zvit-awards-issue-row"):
                yield Label("статус вручення:", classes="zvit-label")
                yield self.handover_status
                yield Label("накладна:", classes="zvit-label")
                yield self.consignment_note
                yield self.issue_protocols

            with Horizontal(id="zvit-extra-row"):
                yield Label("статус подання:", classes="zvit-label")
                yield self.submission_status
                yield self.specific_submission
                yield self.specific_submission_number
                yield Button("Сформувати", variant="primary", id="zvit-refresh")
                yield Button("CSV", id="zvit-export-csv")
                yield Button("XLSX", id="zvit-export-xlsx")

            yield DataTable(id="zvit-table", zebra_stripes=True)
            yield Static("Для створення звіту оберіть параметри та натисніть кнопку Оновити", id="zvit-footer")

    def on_mount(self) -> None:
        if self.cursor:
            self._load_reference_data()
            self._apply_ui_state()
            self.refresh_report()

    def _default_start(self) -> str:
        year = max(START_YEAR, datetime.now().year)
        return datetime(year, 1, 1).strftime("%Y-%m-%d")

    def _default_end(self) -> str:
        return datetime.now().strftime("%Y-%m-%d")

    def _load_reference_data(self):
        if not self.cursor:
            return

        self._load_report_columns_settings()

        # Категории берутся из RankingValues — для этого таблица libs не нужна.
        rank_options = [("Усі", "")]
        rank_options.extend(
            (rank_name, str(rank_number))
            for rank_number, rank_name in enumerate(RankingValues)
            if rank_name
        )
        self.award_rank.set_options(rank_options)

        self.unit.set_options([("Усі", "")])
        self._set_award_name_options([])

        if not self.cursor:
            return

        # Ошибка загрузки подразделений не должна мешать заполнению рангов.
        try:
            _, units = get_units_and_ranks(self.cursor)
            self.unit.set_options(
                [("Усі", "")] + [(unit, unit) for unit in units if unit]
            )
        except RuntimeError as exc:
            self._set_footer(f"Помилка завантаження підрозділів: {exc}")

        self.award_rank.value = ""
        self.unit.value = ""
        self._reload_consignment_options()
        self._reload_submission_options()

    def _set_award_name_options(self, names):
        """Обновляет список названий и сбрасывает выбранное название."""
        self.award_name.set_options(
            [("Усі", "")] + [(name, name) for name in names]
        )
        self.award_name.value = ""

    def _apply_ui_state(self):
        """Включает фильтры и загружает список наград при необходимости."""
        self.award_rank.disabled = False
        self.award_name.disabled = not self.by_name.value
        self.unit.disabled = self.person_category.value == "civilian"
        self.specific_submission_number.disabled = not self.specific_submission.value

        if self.by_name.value:
            self._reload_award_names_by_rank()
        else:
            self._set_award_name_options([])

    def _reload_award_names_by_rank(self):
        """Загружает награды, назначенные в текущем периоде и выбранного ранга."""
        if not self.cursor or not self.by_name.value:
            self._set_award_name_options([])
            return

        query = """
            SELECT DISTINCT a.denotation
            FROM meed AS m
            JOIN award AS a ON a.id = m.id_award
            WHERE a.denotation IS NOT NULL
              AND TRIM(a.denotation) != ''
        """
        params = []

        # Флажок «увесь час» отключает ограничение периода так же, как в отчёте.
        if not self.all_time.value:
            start = self.start_date.value.strip()
            end = self.end_date.value.strip()

            try:
                if start:
                    datetime.strptime(start, "%Y-%m-%d")
                if end:
                    datetime.strptime(end, "%Y-%m-%d")
            except ValueError:
                self._set_award_name_options([])
                return

            if start and end and start > end:
                self._set_award_name_options([])
                return

            if start:
                query += " AND m.date_decree >= ?"
                params.append(start)
            if end:
                query += " AND m.date_decree <= ?"
                params.append(end)

        rank_filter = self.award_rank.value
        if rank_filter not in (None, ""):
            query += " AND a.ranking = ?"
            params.append(int(rank_filter))

        query += " ORDER BY a.denotation COLLATE NOCASE"

        try:
            self.cursor.execute(query, params)
            names = [
                row[0]
                for row in self.cursor.fetchall()
                if row and row[0]
            ]
            self._set_award_name_options(names)
        except sqlite3.Error as exc:
            self._set_award_name_options([])
            self._set_footer(f"Помилка завантаження назв нагород: {exc}")

    def _date_bounds(self):
        """Возвращает корректный диапазон дат или (None, None) для режима «увесь час»."""
        if self.all_time.value:
            return None, None

        start = self.start_date.value.strip()
        end = self.end_date.value.strip()
        try:
            if start:
                datetime.strptime(start, "%Y-%m-%d")
            if end:
                datetime.strptime(end, "%Y-%m-%d")
        except ValueError:
            return None, None

        if start and end and start > end:
            return None, None
        return start or None, end or None

    def _reload_consignment_options(self):
        """Загружает накладные за выбранный период."""
        if not self.cursor:
            return

        start, end = self._date_bounds()
        if not self.all_time.value and start is None and end is None:
            return

        query = """
            SELECT DISTINCT consignment_note
            FROM meed
            WHERE consignment_note IS NOT NULL
              AND TRIM(consignment_note) != ''
        """
        params = []
        if start:
            query += " AND date_decree >= ?"
            params.append(start)
        if end:
            query += " AND date_decree <= ?"
            params.append(end)
        query += " ORDER BY consignment_note DESC"

        try:
            self.cursor.execute(query, params)
            notes = [
                str(row[0]).strip()
                for row in self.cursor.fetchall()
                if row and row[0]
            ]
            selected = self.consignment_note.value
            self.consignment_note.set_options(
                [("Усі накладні", "")] + [(note, note) for note in notes]
            )
            self.consignment_note.value = selected if selected in notes else ""
        except sqlite3.Error as exc:
            self._set_footer(f"Помилка завантаження накладних: {exc}")

    def _reload_submission_options(self):
        """Загружает отдельные подання в формате «номер від дата»."""
        if not self.cursor:
            return

        start, end = self._date_bounds()
        if not self.all_time.value and start is None and end is None:
            self._submission_options = {}
            self.specific_submission_number.set_options(
                [("Оберіть подання", "")]
            )
            return

        query = """
            SELECT DISTINCT registration, date_registration
            FROM presentation
            WHERE registration IS NOT NULL
              AND TRIM(registration) != ''
        """
        params = []
        if start:
            query += " AND date_registration >= ?"
            params.append(start)
        if end:
            query += " AND date_registration <= ?"
            params.append(end)
        query += " ORDER BY registration DESC, date_registration DESC"

        try:
            self.cursor.execute(query, params)
            options = []
            option_map = {}
            for index, (registration, date_registration) in enumerate(
                self.cursor.fetchall()
            ):
                registration = str(registration).strip()
                date_registration = str(date_registration or "").strip()
                value = str(index)
                label = f"{registration} від {date_registration}"
                options.append((label, value))
                option_map[value] = (registration, date_registration)

            selected = self.specific_submission_number.value
            self._submission_options = option_map
            self.specific_submission_number.set_options(
                [("Оберіть подання", "")] + options
            )
            self.specific_submission_number.value = (
                selected if selected in option_map else ""
            )
        except sqlite3.Error as exc:
            self._set_footer(f"Помилка завантаження подань: {exc}")

    def _collect_filters(self) -> dict[str, Any]:
        submission = self._submission_options.get(
            self.specific_submission_number.value
        )
        return {
            "all_time": self.all_time.value,
            "posthumous": self.posthumous.value,
            "civilian": self.person_category.value == "civilian",
            "by_name": self.by_name.value,
            "issue_protocols": self.issue_protocols.value,
            "specific_submission": self.specific_submission.value,
            "submission_number": submission[0] if submission else None,
            "submission_date": submission[1] if submission else None,
            "consignment_note": self.consignment_note.value,
            "worker": self.worker.value,
            "person_category": self.person_category.value,
            "unit": self.unit.value,
            "award_rank": self.award_rank.value,
            "award_name": self.award_name.value,
            "handover_status": self.handover_status.value,
            "submission_status": self.submission_status.value,
            "start_date": self.start_date.value,
            "end_date": self.end_date.value,
        }

    def refresh_report(self):
        if not self.cursor:
            self._set_footer("Немає виборки")
            return

        try:
            table = self.query_one("#zvit-table", DataTable)
            table.clear(columns=True)

            active_columns = self._get_active_report_columns()
            if not active_columns:
                self._set_footer("У налаштуваннях звіту не вибрано жодного стовпця.")
                return

            table.add_columns(*(ALL_COLUMN_LABELS[index] for index in active_columns))

            rows = self._fetch_rows()
            for row in rows:
                values = []
                for index in active_columns:
                    value = row[index] if index < len(row) else None

                    if index == 14:
                        # В базе m.dead обычно хранится как 1 или NULL.
                        value = "Так" if value not in (None, "", 0, "0") else ""
                    elif value is None:
                        value = ""

                    values.append(str(value))

                table.add_row(*values)

            self._set_footer(f"Знайдено записів: {len(rows)}")
        except NoMatches as exc:
            self._set_footer(f"Помилка: {exc}")

    def _fetch_rows(self):
        filters = self._collect_filters()

        status = filters["submission_status"]

        # У Select может не быть выбранного значения; трактуем его как «Усі».
        if status is Select.NULL or status in (None, ""):
            status = str(SUBMISSION_STATUS_ALL)

        status = str(status)
        has_submission_status_filter = status != str(SUBMISSION_STATUS_ALL)

        if has_submission_status_filter:
            report_fields = """
                SELECT
                    p.name,                                      -- 0 ПІБ
                    p.rank,                                      -- 1 Звання
                    p.unit,                                      -- 2 Підрозділ
                    pr.registration,                             -- 3 Подання №
                    pr.date_registration,                        -- 4 Дата подання
                    pr.text_presentation,                        -- 5 Текст подання
                    pr.report,                                   -- 6 Рух
                    m.decree,                                    -- 7 Рішення
                    m.date_decree,                               -- 8 Дата рішення
                    a.denotation,                                -- 9 Нагорода
                    m.date_handover,                             -- 10 Дата вручення
                    CASE
                        WHEN p2.name IS NOT NULL THEN p2.name
                        ELSE m.handover
                    END,                                         -- 11 Хто отримав
                    m.consignment_note,                          -- 12 Накладна
                    m.number_meed,                               -- 13 Номер нагороди
                    m.dead,                                      -- 14 Посмертно
                    p.inn,                                       -- 15 РНОКПП
                    p.date_birth                                 -- 16 Дата народження
            """

            # При выборе статуса начинаем с presentation:
            # иначе подання без связанной награды не попадут в результаты.
            if has_submission_status_filter:
                query = report_fields + """
                    FROM presentation pr
                    LEFT JOIN personality p ON p.id = pr.id_personality
                    LEFT JOIN meed m
                        ON CAST(pr.id_meed AS INTEGER) > 0
                       AND m.id = CAST(pr.id_meed AS INTEGER)
                    LEFT JOIN award a ON a.id = m.id_award
                    LEFT JOIN personality p2 ON p2.id = m.handover
                    WHERE 1=1
                """
            else:
                query = report_fields + """
                    FROM meed m
                    LEFT JOIN personality p ON p.id = m.id_personality
                    LEFT JOIN award a ON a.id = m.id_award
                    LEFT JOIN presentation pr ON pr.id_meed = m.id
                    LEFT JOIN personality p2 ON p2.id = m.handover
                    WHERE 1=1
                """

        params: list[Any] = []

        if not filters["all_time"]:
            start = (filters["start_date"] or "").strip()
            end = (filters["end_date"] or "").strip()

            # Для фильтра статуса период относится к дате регистрации подання.
            date_column = (
                "pr.date_registration"
                if has_submission_status_filter
                else "m.date_decree"
            )

            if start:
                query += f" AND {date_column} >= ?"
                params.append(start)
            if end:
                query += f" AND {date_column} <= ?"
                params.append(end)

        if filters["posthumous"]:
            query += " AND m.dead = 1"

        if filters["issue_protocols"]:
            query += " AND (m.handover IS NULL OR TRIM(m.handover) = '')"

        if filters["consignment_note"] not in (None, ""):
            query += " AND m.consignment_note = ?"
            params.append(filters["consignment_note"])

        if filters["civilian"]:
            query += " AND (p.rank IS NULL OR TRIM(p.rank) = '')"

        elif filters["person_category"] not in (None, "", PERSON_CATEGORY_ALL):
            category = int(filters["person_category"])
            query += " AND p.id IN (SELECT id FROM personality WHERE category = ?)"
            params.append(category)

        if not filters["civilian"] and filters["unit"] not in (None, ""):
            query += " AND p.unit = ?"
            params.append(filters["unit"])

        if filters["by_name"]:
            if filters["award_rank"] not in (None, ""):
                query += " AND a.ranking = ?"
                params.append(int(filters["award_rank"]))

            if filters["award_name"] not in (None, ""):
                query += " AND a.denotation = ?"
                params.append(filters["award_name"])

        worker = filters["worker"]
        if worker not in (None, ""):
            if worker == "0":
                query += " AND pr.worker = 0"
            elif worker == "1":
                query += " AND pr.worker = 1"
            elif worker == "2":
                query += " AND (pr.worker IS NULL OR pr.worker NOT IN (0, 1))"

        if has_submission_status_filter:
            status = int(status)

            if status == 1:  # Погоджені: подання связано с наградой
                query += " AND CAST(pr.id_meed AS INTEGER) > 0"

            elif status == 2:  # Не погоджені
                query += """
                    AND TRIM(CAST(pr.id_meed AS TEXT)) = '0'
                """

            elif status == 3:  # У залишку: связи с наградой ещё нет
                query += """
                    AND (
                        pr.id_meed IS NULL
                        OR TRIM(CAST(pr.id_meed AS TEXT)) = ''
                    )
                """

        if filters["specific_submission"]:
            if filters["submission_number"]:
                query += (
                    " AND pr.registration = ?"
                    " AND COALESCE(pr.date_registration, '') = ?"
                )
                params.extend([
                    filters["submission_number"],
                    filters["submission_date"] or "",
                ])
            else:
                query += (
                    " AND pr.registration IS NOT NULL"
                    " AND TRIM(pr.registration) != ''"
                )
            
        query += " ORDER BY m.date_decree DESC, p.name COLLATE NOCASE"

        try:
            self.cursor.execute(query, params)
            return self.cursor.fetchall()
        except sqlite3.Error as exc:
            self._set_footer(f"Помилка формування звіту: {exc}")
            return []
  
    def _set_footer(self, message: str):
        self.query_one("#zvit-footer", Static).update(message)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "zvit-refresh":
            self.refresh_report()
        elif event.button.id == "zvit-export-csv":
            self._export_report("csv")
        elif event.button.id == "zvit-export-xlsx":
            self._export_report("xlsx")

    def on_checkbox_changed(self, event) -> None:
        if event.checkbox.id in {
            "zvit-all-time",
            "zvit-posthumous",
            "zvit-by-name",
            "zvit-issue-protocols",
            "zvit-specific-submission",
        }:
            self._apply_ui_state()
            if event.checkbox.id == "zvit-specific-submission":
                if not self.specific_submission.value:
                    self.specific_submission_number.value = ""
            elif event.checkbox.id == "zvit-all-time":
                self._reload_consignment_options()
                self._reload_submission_options()

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id == "zvit-person-category":
            self._apply_ui_state()
        elif event.select.id == "zvit-award-rank" and self.by_name.value:
            self._reload_award_names_by_rank()
        elif event.select.id == "zvit-submission-status":
            self.refresh_report()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id in {"zvit-start-date", "zvit-end-date"}:
            if self.by_name.value:
                self._reload_award_names_by_rank()
            self._reload_consignment_options()
            self._reload_submission_options()

    def action_refresh_zvit(self):
        self.refresh_report()

    def action_open_report_settings(self) -> None:
        if not self.conn:
            self.notify("База даних не підключена.", severity="error")
            return

        from setuptab_textual import ReportSettingsModal
        self.app.push_screen(ReportSettingsModal(self.conn, self))

    def _load_report_columns_settings(self) -> None:
        """Загружает сохранённые настройки видимых колонок из service_.zvit_fields."""
        default_flags = [1] * 14 + [3]  # 14 основных + РНОКПП и дата рождения
        self.report_column_flags = default_flags

        if not self.cursor:
            return

        try:
            settings_row = get_service_settings_data(self.cursor)
            if not settings_row or len(settings_row) <= 5 or not settings_row[5]:
                return

            flags = [int(value) for value in str(settings_row[5]).split(",")]
            flags = (flags + [0] * 15)[:15]
            self.report_column_flags = flags

        except (ValueError, TypeError, sqlite3.Error) as exc:
            self._set_footer(f"Помилка налаштувань колонок звіту: {exc}")

    def _get_active_report_columns(self) -> list[int]:
        """Преобразует настройки чекбоксов в индексы полей результата SQL."""
        flags = getattr(self, "report_column_flags", [1] * 14 + [3])

        # Флаги 0–13 соответствуют первым четырнадцати полям ALL_COLUMN_LABELS.
        columns = [index for index in range(14) if flags[index] == 1]

        # Пятнадцатый флаг кодирует выбор РНОКПП и даты рождения:
        # 1 — РНОКПП, 2 — дата рождения, 3 — оба поля.
        last_flag = flags[14]
        if last_flag in (1, 3):
            columns.append(15)
        if last_flag in (2, 3):
            columns.append(16)

        return columns

    def refresh_tree(self) -> None:
        """Перечитывает настройки после их сохранения в окне настроек."""
        self._load_report_columns_settings()
        self.refresh_report()

    def _export_report(self, file_format: str) -> None:
        """Экспортирует текущее содержимое таблицы отчёта."""
        try:
            table = self.query_one("#zvit-table", DataTable)
            if not table.columns:
                self.notify("Сначала сформируйте отчёт.", severity="warning")
                return

            headers = [
                column.label.plain
                if hasattr(column.label, "plain")
                else str(column.label)
                for column in table.columns.values()
            ]

            rows = []
            for row_key in table.rows:
                cells = table.get_row(row_key)
                rows.append([
                    cell.plain if hasattr(cell, "plain") else str(cell)
                    for cell in cells
                ])

            if file_format == "csv":
                path = export_report_csv(headers, rows)
            elif file_format == "xlsx":
                path = export_report_xlsx(headers, rows)
            else:
                self.notify(f"Неизвестный формат экспорта: {file_format}", severity="error")
                return

            self.notify(f"Файл сохранён: {path}")

        except (OSError, RuntimeError, ValueError) as exc:
            self.notify(f"Ошибка экспорта: {exc}", severity="error", timeout=10)

    BINDINGS: ClassVar[list[tuple[str, str, str]]] = [
        ("f4", "open_report_settings", "Налаштування звітів"),
        ("f5", "refresh_zvit", "Оновити"),
    ]

