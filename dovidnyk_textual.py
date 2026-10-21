"""Textual-довідник державних нагород. SQL-схема award не змінюється."""
from __future__ import annotations

import json
from io import BytesIO
from pathlib import Path

import textual_image.renderable  # Визначення графічних протоколів до запуску Textual
from textual_image.widget import Image as TerminalImage
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Select, Static, TextArea, Tree


# Індекси відповідають наявному полю award.ranking. Не змінюємо таблицю award.
RANKING_VALUES = [
    "", "Найвища", "Державні", "Від центральних ов", "Відомчі",
    "Від місцевих ов", "Від керівництва", "Інші",
]
CATEGORY_META_PATH = Path.home() / ".config" / "awards_textual" / "categories.json"


class ConfirmDeleteScreen(ModalScreen[bool]):

    def __init__(self, message: str):
        super().__init__()
        self.message = message

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm-box"):
            yield Static(self.message, id="confirm-message")
            with Horizontal:
                yield Button("Видалити", variant="error", id="confirm-yes")
                yield Button("Скасувати", id="confirm-no")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "confirm-yes")


class DovidnykTab(Vertical):
    """Дерево категорій і наград; редактори не змінюють структуру SQL-бази."""

    def __init__(self, conn=None, cursor=None, **kwargs):
        super().__init__(**kwargs)
        self.conn = conn
        self.cursor = cursor
        self.categories: dict[int, dict[str, str]] = {}
        self.awards_data: dict[int, dict] = {}
        self._tree_nodes_by_award_id: dict[int, object] = {}
        self._tree_nodes_by_category_id: dict[int, object] = {}
        self.current_category_id: int | None = None  # category_id here is award.ranking value
        self.current_award_id: int | None = None
        self.edit_mode: str | None = None
        self.editor_fullscreen = False
        self.loaded_image_blob: bytes | None = None
        self.category_meta: dict[str, dict[str, str]] = {}

    def compose(self) -> ComposeResult:
        with Horizontal(id="dovidnyk-layout"):
            yield Tree("Державні нагороди", id="award-tree")
            with VerticalScroll(id="award-details"):
                with Vertical(id="empty-panel"):
                    yield Static("Оберіть категорію або нагороду в дереві ліворуч.")
                    with Horizontal(classes="actions"):
                        yield Button("Додати категорію", id="add-category", variant="primary")
                        yield Button("Додати нагороду", id="add-award-empty")

                with Vertical(id="category-view"):
                    yield Label("Категорія", classes="field-label")
                    yield Static("", id="category-view-name")
                    yield Label("Опис категорії", classes="field-label")
                    yield TextArea(read_only=True, id="category-view-description")
                    with Horizontal(classes="actions"):
                        yield Button("Додати нагороду", id="add-award", variant="primary")
                        yield Button("Редагувати категорію", id="edit-category")

                with Vertical(id="award-view"):
                    with Horizontal(id="award-view-layout"):
                        with Vertical(id="award-view-text"):
                            yield Static("", id="award-view-name")
                            yield Label("Опис нагороди", classes="field-label")
                            yield TextArea(read_only=True, id="view-grounds")
                            yield Label("Нормативний акт про заснування", classes="field-label")
                            yield TextArea(read_only=True, id="view-law")
                            # Кнопка редагування зафіксована в самому низу текстового блоку
                            with Horizontal(classes="actions"):
                                yield Button("Редагувати нагороду", id="edit-award", variant="primary")
                        with Vertical(id="award-view-image-column"):
                            yield TerminalImage(id="view-image-preview")
                            yield Static("Зображення не завантажено.", id="view-image-status")

                with Vertical(id="category-editor"):
                    with Horizontal(classes="editor-toolbar"):
                        yield Static("Редактор категорії", classes="editor-title")
                        yield Button("На весь екран", id="toggle-editor-size-category")
                    yield Label("Назва категорії", classes="field-label")
                    yield Input(placeholder="Назва категорії", id="category-editor-name")
                    yield Label("Опис категорії", classes="field-label")
                    yield TextArea(id="category-editor-description")
                    with Horizontal(classes="actions"):
                        yield Button("Зберегти", id="save-category", variant="primary")
                        yield Button("Скасувати", id="cancel-editor-category")

                with Vertical(id="award-editor"):
                    with Horizontal(classes="editor-toolbar"):
                        yield Static("Редактор нагороди", classes="editor-title")
                        yield Button("На весь екран", id="toggle-editor-size-award")
                    yield Label("Категорія", classes="field-label")
                    yield Select([], id="award-editor-category", prompt="Оберіть категорію")
                    yield Label("Назва нагороди", classes="field-label")
                    yield Input(placeholder="Назва нагороди", id="award-editor-name")
                    yield Label("Нормативний акт про заснування", classes="field-label")
                    yield TextArea(id="award-editor-law")
                    yield Label("Опис нагороди", classes="field-label")
                    yield TextArea(id="award-editor-grounds")
                    yield Label("Зображення (шлях до файлу, необов'язково)", classes="field-label")
                    yield Input(placeholder="/шлях/до/зображення.png", id="award-editor-image-path")
                    yield Static("", id="image-status")
                    with Horizontal(classes="actions"):
                        yield Button("Видалити нагороду", id="delete-award", variant="error")
                        yield Button("Зберегти", id="save-award", variant="primary")
                        yield Button("Скасувати", id="cancel-editor-award")

    def on_mount(self) -> None:
        self._load_category_meta()
        self._show_panel("empty-panel")
        self._load_data()

    def set_database(self, conn, cursor) -> None:
        self.conn, self.cursor = conn, cursor
        self._load_category_meta()
        self._load_data()

    def _load_category_meta(self) -> None:
        try:
            if CATEGORY_META_PATH.exists():
                data = json.loads(CATEGORY_META_PATH.read_text(encoding="utf-8"))
                self.category_meta = data if isinstance(data, dict) else {}
            else:
                self.category_meta = {}
        except (OSError, json.JSONDecodeError):
            self.category_meta = {}

    def _save_category_meta(self) -> None:
        CATEGORY_META_PATH.parent.mkdir(parents=True, exist_ok=True)
        CATEGORY_META_PATH.write_text(
            json.dumps(self.category_meta, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def _load_data(self) -> None:
        if self.cursor is None:
            return
        try:
            # Читаємо тільки наявні поля. Ніяких CREATE TABLE або ALTER TABLE.
            self.cursor.execute("SELECT id, denotation, law, grounds, img, ranking FROM award ORDER BY ranking, denotation")
            rows = self.cursor.fetchall()
            used_ranks = set()
            awards: dict[int, dict] = {}
            for award_id, name, law, grounds, image, ranking in rows:
                try:
                    rank = int(ranking)
                except (ValueError, TypeError):
                    rank = 0
                used_ranks.add(rank)
                awards[award_id] = {
                    "id": award_id, "name": name or "", "law": law or "",
                    "grounds": grounds or "", "image": image, "ranking": rank,
                }
            metadata_ranks = set()
            for key in self.category_meta:
                try:
                    metadata_ranks.add(int(key))
                except (TypeError, ValueError):
                    pass
            ranks = (set(range(1, len(RANKING_VALUES))) | used_ranks | metadata_ranks)
            ranks.discard(0)
            self.categories = {}
            for rank in sorted(ranks):
                default_name = RANKING_VALUES[rank] if rank < len(RANKING_VALUES) else f"Категорія {rank}"
                meta = self.category_meta.get(str(rank), {})
                self.categories[rank] = {
                    "name": str(meta.get("name") or default_name),
                    "description": str(meta.get("description") or ""),
                }
            self.awards_data = awards
            self._populate_tree()
            self._refresh_award_category_options()
        except Exception as exc:
            self.notify(f"Не вдалося завантажити довідник: {exc}", severity="error", timeout=8)

    def _populate_tree(self) -> None:
        tree = self.query_one("#award-tree", Tree)
        tree.clear()
        tree.root.set_label("Державні нагороди")
        tree.root.data = {"type": "root"}
        self._tree_nodes_by_award_id.clear()
        self._tree_nodes_by_category_id.clear()
        for rank, category in self.categories.items():
            node = tree.root.add(category["name"], data={"type": "category", "ranking": rank})
            self._tree_nodes_by_category_id[rank] = node
            for award_id, award in sorted(self.awards_data.items(), key=lambda pair: pair[1]["name"].casefold()):
                if award["ranking"] == rank:
                    award_node = node.add(award["name"], data={"type": "award", "award_id": award_id, "ranking": rank})
                    self._tree_nodes_by_award_id[award_id] = award_node
        tree.root.expand()
        tree.show_root = False

    def _refresh_award_category_options(self) -> None:
        widget = self.query_one("#award-editor-category", Select)
        widget.set_options([(cat["name"], str(rank)) for rank, cat in self.categories.items()])

    def _show_panel(self, panel_id: str) -> None:
        for name in ("empty-panel", "category-view", "award-view", "category-editor", "award-editor"):
            self.query_one(f"#{name}").display = name == panel_id
        is_editor = panel_id in {"category-editor", "award-editor"}
        self.query_one("#award-tree").display = not (is_editor and self.editor_fullscreen)
        self.query_one("#award-details").styles.width = "1fr" if not (is_editor and self.editor_fullscreen) else "100%"

    def on_tree_node_highlighted(self, event: Tree.NodeHighlighted) -> None:
        # Відкриваємо інформацію одразу під час переміщення курсора, без Enter/кліку.
        self._display_tree_node(event.node)

    def on_tree_node_selected(self, event: Tree.NodeSelected) -> None:
        # Клік/Enter також працюють, як і раніше.
        self._display_tree_node(event.node)

    def _display_tree_node(self, node) -> None:
        data = node.data or {}
        if data.get("type") == "category":
            self.editor_fullscreen = False
            self.current_category_id = int(data["ranking"])
            self.current_award_id = None
            self._show_category(self.current_category_id)
        elif data.get("type") == "award":
            self.editor_fullscreen = False
            self.current_award_id = int(data["award_id"])
            self.current_category_id = int(data["ranking"])
            self._show_award(self.current_award_id)

    def _show_category(self, ranking: int) -> None:
        category = self.categories.get(ranking)
        if not category:
            self._show_panel("empty-panel")
            return
        self.query_one("#category-view-name", Static).update(category["name"])
        self.query_one("#category-view-description", TextArea).load_text(category["description"])
        self._show_panel("category-view")

    def _show_award(self, award_id: int) -> None:
        award = self.awards_data.get(award_id)
        if not award:
            self._show_panel("empty-panel")
            return
        self.query_one("#award-view-name", Static).update(award["name"])
        self.query_one("#view-law", TextArea).load_text(award["law"])
        self.query_one("#view-grounds", TextArea).load_text(award["grounds"])
        preview = self.query_one("#view-image-preview", TerminalImage)
        image_data = award["image"]
        if image_data:
            try:
                from PIL import Image as PILImage, ImageOps
                with PILImage.open(BytesIO(image_data)) as source:
                    source.load()
                    source = source.convert("RGB")
                    fitted = ImageOps.contain(source, (640, 220))
                    # Притискаємо зображення чітко до лівого краю (x = 0)
                    display_image = PILImage.new("RGB", (640, 220), (24, 24, 24))
                    x = 0 
                    y = (220 - fitted.height) // 2
                    display_image.paste(fitted, (x, y))
                preview.image = display_image
                status = "Зображення завантажено з бази даних."
            except Exception as exc:
                preview.image = None
                status = f"Не вдалося показати зображення: {exc}"
        else:
            preview.image = None
            status = "Зображення не завантажено."
        self.query_one("#view-image-status", Static).update(status)
        self._show_panel("award-view")

    def _open_category_editor(self, creating: bool) -> None:
        self.edit_mode = "category-create" if creating else "category-edit"
        if creating:
            # ranking — це вже наявне числове поле, нові категорії отримують наступний індекс.
            self.current_category_id = max(self.categories, default=0) + 1
            name, description = "", ""
        else:
            category = self.categories.get(self.current_category_id or -1, {})
            name, description = category.get("name", ""), category.get("description", "")
        self.query_one("#category-editor-name", Input).value = name
        self.query_one("#category-editor-description", TextArea).load_text(description)
        self.editor_fullscreen = False
        self._show_panel("category-editor")

    def _open_award_editor(self, creating: bool) -> None:
        self.edit_mode = "award-create" if creating else "award-edit"
        self._refresh_award_category_options()
        if creating:
            self.current_award_id = None
            self.loaded_image_blob = None
            self.query_one("#award-editor-name", Input).value = ""
            self.query_one("#award-editor-law", TextArea).load_text("")
            self.query_one("#award-editor-grounds", TextArea).load_text("")
            self.query_one("#award-editor-image-path", Input).value = ""
            default_rank = self.current_category_id if self.current_category_id in self.categories else next(iter(self.categories), None)
            self.query_one("#award-editor-category", Select).value = str(default_rank) if default_rank is not None else Select.BLANK
            self.query_one("#image-status", Static).update("Нове зображення не вибрано.")
        else:
            award = self.awards_data[self.current_award_id]
            self.loaded_image_blob = award["image"]
            self.query_one("#award-editor-name", Input).value = award["name"]
            self.query_one("#award-editor-law", TextArea).load_text(award["law"])
            self.query_one("#award-editor-grounds", TextArea).load_text(award["grounds"])
            self.query_one("#award-editor-image-path", Input).value = ""
            self.query_one("#award-editor-category", Select).value = str(award["ranking"])
            self.query_one("#image-status", Static).update(
                "У базі вже є зображення; залиште шлях порожнім, щоб його зберегти." if self.loaded_image_blob else "Нове зображення не вибрано."
            )
        self.query_one("#delete-award", Button).display = not creating
        self.editor_fullscreen = False
        self._show_panel("award-editor")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        action = event.button.id
        if action == "add-category":
            self._open_category_editor(True)
        elif action in {"add-award", "add-award-empty"}:
            if not self.categories:
                self.notify("Спочатку створіть категорію.", severity="warning")
                return
            self._open_award_editor(True)
        elif action == "edit-category":
            self._open_category_editor(False)
        elif action == "edit-award":
            if self.current_award_id is not None:
                self._open_award_editor(False)
        elif action == "save-category":
            self._save_category()
        elif action == "save-award":
            self._save_award()
        elif action in {"cancel-editor-category", "cancel-editor-award"}:
            self._cancel_editor()
        elif action in {"toggle-editor-size-category", "toggle-editor-size-award"}:
            self.editor_fullscreen = not self.editor_fullscreen
            self._show_panel("category-editor" if action.endswith("category") else "award-editor")
            event.button.label = "Поруч із деревом" if self.editor_fullscreen else "На весь екран"
        elif action == "delete-award":
            self._confirm_delete()

    def _save_category(self) -> None:
        name = self.query_one("#category-editor-name", Input).value.strip()
        description = self.query_one("#category-editor-description", TextArea).text.strip()
        if not name:
            self.notify("Назва категорії не може бути порожньою.", severity="error")
            return
        if self.edit_mode == "category-create":
            ranking = self.current_category_id
            if any(cat["name"].casefold() == name.casefold() for cat in self.categories.values()):
                self.notify("Категорія з такою назвою вже існує.", severity="error")
                return
        elif self.edit_mode == "category-edit":
            ranking = self.current_category_id
            if any(rank != ranking and cat["name"].casefold() == name.casefold() for rank, cat in self.categories.items()):
                self.notify("Категорія з такою назвою вже існує.", severity="error")
                return
        else:
            return
        self.category_meta[str(ranking)] = {"name": name, "description": description}
        try:
            self._save_category_meta()
            self._load_data()
            self.current_category_id = ranking
            self.current_award_id = None
            self.editor_fullscreen = False
            self._show_category(ranking)
            self._select_category_node(ranking)
            self.notify("Категорію збережено. SQL-база не змінювалася.")
        except OSError as exc:
            self.notify(f"Не вдалося зберегти опис категорії: {exc}", severity="error")

    def _save_award(self) -> None:
        if self.conn is None or self.cursor is None:
            self.notify("Немає підключення до бази даних.", severity="error")
            return
        name = self.query_one("#award-editor-name", Input).value.strip()
        law = self.query_one("#award-editor-law", TextArea).text.strip()
        grounds = self.query_one("#award-editor-grounds", TextArea).text.strip()
        category_value = self.query_one("#award-editor-category", Select).value
        image_path = self.query_one("#award-editor-image-path", Input).value.strip()
        if not name:
            self.notify("Назва нагороди не може бути порожньою.", severity="error")
            return
        try:
            ranking = int(category_value)
        except (ValueError, TypeError):
            self.notify("Оберіть категорію нагороди.", severity="error")
            return
        if image_path:
            try:
                self.loaded_image_blob = Path(image_path).read_bytes()
            except OSError as exc:
                self.notify(f"Не вдалося прочитати зображення: {exc}", severity="error")
                return
        duplicate = any(
            row["name"].casefold() == name.casefold() and row["ranking"] == ranking and row["id"] != self.current_award_id
            for row in self.awards_data.values()
        )
        if duplicate:
            self.notify("Нагорода з такою назвою вже є в цій категорії.", severity="error")
            return
        try:
            if self.edit_mode == "award-create":
                self.cursor.execute(
                    "INSERT INTO award (denotation, law, grounds, img, ranking) VALUES (?, ?, ?, ?, ?)",
                    (name.replace("\n", " "), law, grounds, self.loaded_image_blob, ranking),
                )
                self.conn.commit()
                award_id = self.cursor.lastrowid
                message = "Нагороду створено."
            elif self.edit_mode == "award-edit" and self.current_award_id is not None:
                award_id = self.current_award_id
                self.cursor.execute(
                    "UPDATE award SET denotation=?, law=?, grounds=?, img=?, ranking=? WHERE id=?",
                    (name.replace("\n", " "), law, grounds, self.loaded_image_blob, ranking, award_id),
                )
                self.conn.commit()
                message = "Зміни збережено."
            else:
                return
            self._load_data()
            self.current_award_id = award_id
            self.current_category_id = ranking
            self.editor_fullscreen = False
            self._show_award(award_id)
            self._select_award_node(award_id)
            self.notify(message)
        except Exception as exc:
            try:
                self.conn.rollback()
            except Exception:
                pass
            self.notify(f"Помилка збереження нагороди: {exc}", severity="error", timeout=8)

    def _cancel_editor(self) -> None:
        self._load_data()
        self.editor_fullscreen = False
        if self.current_award_id in self.awards_data:
            self._show_award(self.current_award_id)
            self._select_award_node(self.current_award_id)
        elif self.current_category_id in self.categories:
            self._show_category(self.current_category_id)
            self._select_category_node(self.current_category_id)
        else:
            self._show_panel("empty-panel")

    def _select_category_node(self, ranking: int) -> None:
        node = self._tree_nodes_by_category_id.get(ranking)
        if node:
            self.query_one("#award-tree", Tree).move_cursor(node)

    def _select_award_node(self, award_id: int) -> None:
        node = self._tree_nodes_by_award_id.get(award_id)
        if node:
            node.parent.expand()
            self.query_one("#award-tree", Tree).move_cursor(node)

    def _confirm_delete(self) -> None:
        if self.current_award_id is None:
            return
        award = self.awards_data.get(self.current_award_id)
        if not award:
            return
        self.app.push_screen(
            ConfirmDeleteScreen(f"Видалити нагороду «{award['name']}»?"),
            self._delete_confirmed,
        )

    def _delete_confirmed(self, confirmed: bool | None) -> None:
        if not confirmed or self.current_award_id is None:
            return
        try:
            self.cursor.execute("DELETE FROM award WHERE id=?", (self.current_award_id,))
            self.conn.commit()
            self.current_award_id = None
            self._load_data()
            self.editor_fullscreen = False
            self._show_panel("category-view" if self.current_category_id in self.categories else "empty-panel")
            if self.current_category_id in self.categories:
                self._show_category(self.current_category_id)
            self.notify("Нагороду видалено.")
        except Exception as exc:
            self.conn.rollback()
            self.notify(f"Помилка видалення: {exc}", severity="error")
