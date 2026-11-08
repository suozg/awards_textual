# search_tab_textual.py
from __future__ import annotations

import platform
import subprocess
from io import BytesIO
from typing import ClassVar

from PIL import Image as PILImage
from PIL import ImageDraw, ImageFont, ImageOps
from sqlcipher3 import dbapi2 as sqlite3
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.css.query import NoMatches
from textual.widgets import Button, Input, TextArea
from textual_image.widget import Image as TerminalImage

from config import START_YEAR
from database_logic_textual import (
    AwardDataLoader,
    get_award_image_blobs_for_search,
    search_q,
)


class SearchTab(Vertical):
    """Пошук за ПІБ/РНОКПП та вивід результатів."""

    def __init__(self, conn=None, cursor=None, **kwargs):
        super().__init__(**kwargs)
        self.conn = conn
        self.cursor = cursor
        self.latest_search_results = []
        self.source_data_award_and_presentation = {}
        self.search_revision = 0
        self.skip_next_population = False

    def compose(self) -> ComposeResult:
        with Horizontal(id="search-toolbar"):
            yield Input(
                placeholder="Введіть ПІБ або РНОКПП (10 цифр) та натисніть Enter",
                id="person-search",
            )
            yield Button("Пошук", variant="primary", id="person-search-run")
            yield Button("Очистити", id="person-search-clear")

        with Vertical(id="search-body"):
            with VerticalScroll(id="search-results-scroll"):
                yield TextArea(id="search-results", read_only=True)

            yield Vertical(id="search-images")

    def on_mount(self) -> None:
        """Викликається при запуску / появі вкладки — виводимо графік за замовчуванням."""
        self.show_default_graph()

    def set_database(self, conn, cursor) -> None:
        self.conn, self.cursor = conn, cursor
        self.show_default_graph()

    def show_default_graph(self) -> None:
        """Генерує текстовий варіант графіку awards_graph_modal та виводить у TextArea."""
        try:
            if not self.cursor:
                self.query_one("#search-results", TextArea).text = "База даних не підключена для побудови графіка."
                return

            loader = AwardDataLoader(START_YEAR)
            loader.load_data(self.cursor)
            years, state, all_awards, presentations = loader.get_recent_graph_data()
            
            if not years:
                self.query_one("#search-results", TextArea).text = "Немає даних для побудови графіка."
                return

            max_value = max([1, *state, *all_awards, *presentations])
            width = 40

            lines = ["ДИНАМІКА НАГОРОДЖЕНЬ\n"]

            for year, state_n, all_n, pres_n in zip(
                years, state, all_awards, presentations
            ):
                lines.append(
                    f"  {year}  "
                    + "█" * round(all_n / max_value * width)
                    + f" {all_n} усі нагороди"
                )
                lines.append(
                    "        "
                    + "█" * round(state_n / max_value * width)
                    + f" {state_n} державні та відомчі"
                )
                lines.append(
                    "        "
                    + "█" * round(pres_n / max_value * width)
                    + f" {pres_n} подання\n"
                )

            lines.append("=" * 40)
            lines.append(loader.get_status_text())

            self.query_one("#search-results", TextArea).text = "\n".join(lines)

        except sqlite3.Error as exc:
            self.query_one("#search-results", TextArea).text = (
                f"Помилка завантаження графіка: {exc}"
            )

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "person-search":
            await self.run_search()

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "person-search-run":
            await self.run_search()
        elif event.button.id == "person-search-clear":
            await self.clear_search()


    def action_copy_results(self) -> None:
        """Копіювання результатів пошуку до системного буфера обміну."""
        try:
            textarea = self.query_one("#search-results", TextArea)
        except NoMatches:
            return

        text_to_copy = textarea.selected_text or textarea.text
        if not text_to_copy:
            self.app.notify("Немає тексту для копіювання", severity="warning")
            return

        system = platform.system()
        commands = {
            "Linux": ["xclip", "-selection", "clipboard"],
            "Windows": ["clip"],
            "Darwin": ["pbcopy"],
        }
        command = commands.get(system)
        if command is None:
            self.app.notify(f"Непідтримувана ОС: {system}", severity="error")
            return

        try:
            subprocess.run(command, input=text_to_copy, text=True, check=True, timeout=5)
            self.app.notify("Текст скопійовано")
        except (OSError, subprocess.SubprocessError) as exc:
            self.app.notify(f"Помилка копіювання: {exc}", severity="error")

    async def run_search(self) -> None:
        query = self.query_one("#person-search", Input).value.strip()
        
        if not query:
            await self.clear_search()
            return

        if not self.cursor:
            self.notify("База даних не підключена.", severity="error")
            return
        
        self.latest_search_results = []
        self.source_data_award_and_presentation = {}
        await self.query_one("#search-images", Vertical).remove_children()
        
        try:
            results, result_text, image_ids, counts, source = search_q(query, self.cursor)
            self.latest_search_results = results
            self.source_data_award_and_presentation = source
            self.search_revision += 1
            
            # Виводимо результати пошуку в TextArea
            self.query_one("#search-results", TextArea).text = result_text or "Нагород та подань не знайдено."

            # Завантаження та рендеринг зображень із другого файлу
            blobs_to_show = get_award_image_blobs_for_search(image_ids, counts, self.cursor)
            image_row = self.query_one("#search-images", Vertical)
            
            for index, blob in enumerate(blobs_to_show, start=1):
                try:
                    with PILImage.open(BytesIO(blob)) as source_image:
                        source_image.load()
                        source_image = source_image.convert("RGB")
                        
                        current_theme = getattr(self.app, "theme", "gruvbox-dark")
                        is_light = "light" in current_theme
                        
                        canvas_bg = (251, 241, 199) if is_light else (40, 40, 40)
                        text_fill = (60, 56, 54) if is_light else (200, 200, 200)
                        
                        canvas_width = 144
                        canvas_height = 128
                        text_offset_y = 14
                        available_height = canvas_height - text_offset_y
                        
                        fitted = ImageOps.contain(
                            source_image,
                            (canvas_width, available_height),
                            method=PILImage.Resampling.LANCZOS,
                        )
                        
                        canvas = PILImage.new("RGB", (canvas_width, canvas_height), canvas_bg)
                        x = (canvas_width - fitted.width) // 2
                        y = text_offset_y + (available_height - fitted.height) // 2
                        
                        fitted_rgba = fitted.convert("RGBA")
                        datas = fitted_rgba.getdata()
                        new_data = []
                        for item in datas:
                            if item[0] < 15 and item[1] < 15 and item[2] < 15:
                                new_data.append((*canvas_bg, 0))
                            else:
                                new_data.append(item)
                        fitted_rgba.putdata(new_data)
                        
                        canvas.paste(fitted_rgba.convert("RGB"), (x, y), fitted_rgba) 
                        
                        draw = ImageDraw.Draw(canvas)
                        try:
                            font = ImageFont.truetype("DejaVuSans.ttf", 9)
                        except OSError:
                            font = ImageFont.load_default()
                            
                        label_text = f"= {index} ="
                        bbox = draw.textbbox((0, 0), label_text, font=font)
                        text_width = bbox[2] - bbox[0]
                        text_x = (canvas_width - text_width) // 2
                        text_y = 2
                        
                        draw.text((text_x, text_y), label_text, fill=text_fill, font=font)
                        
                        image_widget = TerminalImage(classes="award-image")
                        image_widget.image = canvas
                        
                        await image_row.mount(
                            Vertical(
                                image_widget,
                                classes="search-award-image-card",
                            )
                        )
                except (OSError, ValueError, TypeError) as exc:
                    self.notify(
                        f"Помилка завантаження зображення: {exc}",
                        severity="warning",
                    )
        except sqlite3.Error as exc:
            self.notify(
                f"Помилка пошуку: {exc}",
                severity="error",
                timeout=10,
            )

    async def clear_search(self) -> None:
        self.query_one("#person-search", Input).value = ""
        await self.query_one("#search-images", Vertical).remove_children()
        
        self.latest_search_results = []
        self.source_data_award_and_presentation = {}
        self.search_revision += 1
        
        # Повертаємо графік при очищенні
        self.show_default_graph()
        self.query_one("#person-search", Input).focus()

    def action_show_award_graph(self) -> None:
        """Дія для відкриття модального вікна графіку нагороджень."""
        from award_graph_modal import AwardGraphScreen
        cursor = getattr(self, "cursor", None)
        if cursor:
            self.app.push_screen(AwardGraphScreen(cursor))
        else:
            self.notify("База даних не підключена.", severity="error")

    def get_search_revision(self) -> int:
        return self.search_revision

    def get_latest_search_results(self):
        return self.latest_search_results, self.source_data_award_and_presentation
   
    BINDINGS: ClassVar[list[tuple[str, str, str]]] = [
        ("f2", "show_award_graph", "Графік"),
        ("f3", "copy_results", "Копіювати"),
    ]


