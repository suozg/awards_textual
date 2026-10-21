"""Модальне вікно графіку нагороджень."""
from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Label, Select, Static

from config import START_YEAR
from database_logic_textual import AwardDataLoader


class AwardGraphScreen(ModalScreen[None]):
    """Термінальний графік кількості нагород і подань за роками."""
    def __init__(self, cursor):
        super().__init__()
        self.cursor = cursor
        self.loader = AwardDataLoader(START_YEAR)
        self.loader.load_data(cursor)

    def compose(self) -> ComposeResult:
        years, _, _, _ = self.loader.get_graph_data()
        options = [(str(year), str(year)) for year in years] or [("Немає даних", "none")]
        
        with Vertical(id="graph-box"):
            yield Label("ДИНАМІКА НАГОРОЖЕНЬ")
            
            # Контейнер із прокручуванням
            with VerticalScroll(id="graph-scroll-container"):
                yield Static("", id="graph-chart")
                
            with Horizontal(id="graph-controls"):
                yield Label("Рік:")
                yield Select(options, value=str(years[-1]) if years else "none", id="graph-year", allow_blank=False)
                yield Button("Закрити", id="graph-close", variant="error")
                
            yield Static(self.loader.get_status_text(), id="graph-status")

    def on_mount(self) -> None:
        years, _, _, _ = self.loader.get_graph_data()
        default_year = years[-1] if years else None
        self._render_chart(default_year)

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id == "graph-year":
            try:
                selected_year = int(event.value)
                self._render_chart(selected_year)
            except (ValueError, TypeError):
                self._render_chart(None)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "graph-close":
            self.dismiss(None)

    def _render_chart(self, selected_year: int | None) -> None:
        years, state, all_awards, presentations = self.loader.get_graph_data()
        if not years:
            self.query_one("#graph-chart", Static).update("Немає даних для побудови графіка.")
            return

        max_value = max([1, *state, *all_awards, *presentations])
        width = max(8, min(48, self.size.width - 42))
        
        output = Text()
        output.append("Рік     Нагороди\n", style="bold underline")
        
        target_line_index = 0
        current_line = 1 # враховуємо заголовок

        for year, state_n, all_n, pres_n in zip(years, state, all_awards, presentations):
            is_selected = (year == selected_year)
            marker = "▶ " if is_selected else "  "
            
            if is_selected:
                target_line_index = current_line

            output.append(f"{marker}{year}  ", style="bold green" if is_selected else "")
            output.append("█" * round(all_n / max_value * width), style="red")
            output.append(f" {all_n} усі нагороди\n")
            output.append("        ")
            output.append("█" * round(state_n / max_value * width), style="blue")
            output.append(f" {state_n} державні та відомчі\n")
            output.append("        ")
            output.append("█" * round(pres_n / max_value * width), style="green")
            output.append(f" {pres_n} подання\n\n")
            current_line += 4

        chart_widget = self.query_one("#graph-chart", Static)
        chart_widget.update(output)

        # Автоматична прокрутка до обраного року
        if selected_year in years:
            idx = years.index(selected_year)
            scroll_container = self.query_one("#graph-scroll-container", VerticalScroll)
            # Приближний розрахунок рядка для скролу
            scroll_container.scroll_to(y=idx * 4, animate=False)

            pct = round(state[idx] / all_awards[idx] * 100) if all_awards[idx] else 0
            status = f"За {selected_year} рік: усі нагороди — {all_awards[idx]}, державні — {state[idx]} ({pct}%), подання — {presentations[idx]}"
        else:
            status = self.loader.get_status_text()

        self.query_one("#graph-status", Static).update(status)


