from __future__ import annotations

from datetime import datetime
from typing import Any

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Checkbox, DataTable, Input, Label, Select, Static

from config import START_YEAR
from database_logic_textual import (
    get_formatted_unique_awarded_distinctions,
    get_units_and_ranks,
)


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
            ],
            value=PERSON_CATEGORY_ALL,
            id="zvit-person-category",
        )
        self.unit = Select([("Усі", "")], value="", id="zvit-unit")
        self.award_rank = Select([("Усі", "")], value="", id="zvit-award-rank")
        self.award_name = Select([("Усі", "")], value="", id="zvit-award-name")

        self.all_time = Checkbox("увесь час", value=False, id="zvit-all-time")
        self.posthumous = Checkbox("посмертно", value=False, id="zvit-posthumous")
        self.civilian = Checkbox("= цивільні", value=False, id="zvit-civilian")
        self.by_name = Checkbox("ранг / назва", value=False, id="zvit-by-name")
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
                yield self.posthumous

            with Horizontal(id="zvit-middle-row"):
                yield Label("виконавець:", classes="zvit-label")
                yield self.worker
                yield Label("категорія:", classes="zvit-label")
                yield self.person_category
                yield Label("підрозділ:", classes="zvit-label")
                yield self.unit
                yield self.civilian

            with Horizontal(id="zvit-award-row"):
                yield Label("нагорода:", classes="zvit-label")
                yield self.award_rank
                yield self.by_name
                yield self.award_name

            with Horizontal(id="zvit-extra-row"):
                yield Label("статус вручення:", classes="zvit-label")
                yield self.handover_status
                yield Label("статус подання:", classes="zvit-label")
                yield self.submission_status
                yield self.issue_protocols
                yield self.specific_submission
                yield Button("Сформувати", variant="primary", id="zvit-refresh")

            yield DataTable(id="zvit-table", zebra_stripes=True)
            yield Static("Для створення звіту оберіть параметри та натисніть кнопку Оновити", id="zvit-footer")

    def on_mount(self) -> None:
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
            self.unit.options = [("Усі", "")]
            self.award_rank.options = [("Усі", "")]
            self.award_name.options = [("Усі", "")]
            return

        try:
            ranks, units = get_units_and_ranks(self.cursor)
            self.award_rank.options = [("Усі", "")] + [(rank, rank) for rank in ranks]
            self.unit.options = [("Усі", "")] + [(unit, unit) for unit in units]

            names = get_formatted_unique_awarded_distinctions(self.cursor)
            self.award_name.options = [("Усі", "")] + [(name, name) for name in names]
        except Exception:
            self.award_rank.options = [("Усі", "")]
            self.unit.options = [("Усі", "")]
            self.award_name.options = [("Усі", "")]

        self.award_rank.value = ""
        self.unit.value = ""
        self.award_name.value = ""

    def _apply_ui_state(self):
        self.award_rank.disabled = self.by_name.value
        self.award_name.disabled = not self.by_name.value
        self.unit.disabled = self.civilian.value

        if self.by_name.value:
            self._reload_award_names_by_rank()

    def _reload_award_names_by_rank(self):
        if not self.cursor:
            return

        rank_filter = self.award_rank.value
        try:
            names = get_formatted_unique_awarded_distinctions(self.cursor, rank_filter=rank_filter or None)
            self.award_name.options = [("Усі", "")] + [(name, name) for name in names]
            self.award_name.value = ""
        except Exception:
            self.award_name.options = [("Усі", "")]
            self.award_name.value = ""

    def _collect_filters(self) -> dict[str, Any]:
        return {
            "all_time": self.all_time.value,
            "posthumous": self.posthumous.value,
            "civilian": self.civilian.value,
            "by_name": self.by_name.value,
            "issue_protocols": self.issue_protocols.value,
            "specific_submission": self.specific_submission.value,
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
            table = self.query_one(DataTable)
            table.clear(columns=True)
            table.add_columns(
                "ПІБ",
                "Звання",
                "Підрозділ",
                "Нагорода",
                "Дата нагородження",
                "Статус вручення",
                "Подання",
                "Дата подання",
            )

            rows = self._fetch_rows()
            for row in rows:
                table.add_row(*[str(value) if value is not None else "" for value in row])

            self._set_footer(f"Знайдено записів: {len(rows)}")
        except Exception as exc:
            self._set_footer(f"Помилка: {exc}")

    def _fetch_rows(self):
        filters = self._collect_filters()

        query = """
            SELECT
                p.name,
                p.rank,
                p.unit,
                a.denotation,
                m.date_decree,
                CASE
                    WHEN m.handover IS NULL OR TRIM(m.handover) = '' THEN 'залишок в натурі'
                    ELSE 'видано'
                END,
                pr.registration,
                pr.date_registration
            FROM meed m
            LEFT JOIN personality p ON p.id = m.id_personality
            LEFT JOIN award a ON a.id = m.id_award
            LEFT JOIN presentation pr ON pr.id_meed = m.id
            WHERE 1=1
        """
        params: list[Any] = []

        if not filters["all_time"]:
            start = (filters["start_date"] or "").strip()
            end = (filters["end_date"] or "").strip()
            if start:
                query += " AND m.date_decree >= ?"
                params.append(start)
            if end:
                query += " AND m.date_decree <= ?"
                params.append(end)

        if filters["posthumous"]:
            query += " AND m.dead = 1"

        if filters["issue_protocols"]:
            query += " AND (m.handover IS NULL OR TRIM(m.handover) = '')"

        if filters["person_category"] not in (None, "", PERSON_CATEGORY_ALL):
            category = int(filters["person_category"])
            query += " AND p.id IN (SELECT id FROM personality WHERE category = ?)"
            params.append(category)

        if filters["unit"] not in (None, ""):
            query += " AND p.unit = ?"
            params.append(filters["unit"])

        if filters["award_rank"] not in (None, ""):
            query += " AND a.ranking = ?"
            params.append(filters["award_rank"])

        if filters["award_name"] not in (None, ""):
            if filters["by_name"]:
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

        submission_status = filters["submission_status"]
        if submission_status not in (None, "", SUBMISSION_STATUS_ALL):
            status = int(submission_status)
            if status == 1:
                query += " AND pr.report = 1"
            elif status == 2:
                query += " AND pr.report = 0"
            elif status == 3:
                query += " AND (pr.report IS NULL OR pr.report = '')"

        if filters["specific_submission"]:
            query += " AND pr.registration IS NOT NULL AND TRIM(pr.registration) != ''"

        query += " ORDER BY m.date_decree DESC, p.name COLLATE NOCASE"

        try:
            self.cursor.execute(query, params)
            return self.cursor.fetchall()
        except Exception:
            return []

    def _set_footer(self, message: str):
        try:
            self.query_one("#zvit-footer", Static).update(message)
        except Exception:
            pass

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "zvit-refresh":
            self.refresh_report()

    def on_checkbox_changed(self, event) -> None:
        if event.checkbox.id in {
            "zvit-all-time",
            "zvit-posthumous",
            "zvit-civilian",
            "zvit-by-name",
            "zvit-issue-protocols",
            "zvit-specific-submission",
        }:
            self._apply_ui_state()

    def on_select_changed(self, event):
        if event.select.id == "zvit-award-rank" and self.by_name.value:
            self._reload_award_names_by_rank()

    def action_refresh_zvit(self):
        self.refresh_report()

    BINDINGS = [("f5", "refresh_zvit", "Оновити")]
