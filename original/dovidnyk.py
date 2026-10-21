# dovidnyk.py
import wx
from config import DEF_FUT_LABEL # Make sure config.py exists with DEF_FUT_LABEL
from database_logic import (
    connect_to_database, 
    get_treedata, 
    save_award_to_db, 
    create_award_in_db, 
    delete_award_from_db,
    RankingValues
    )
import wx.lib.scrolledpanel as scrolled 
from ui_utils import load_image_from_blob 

"""
__init__ → build_ui → (пользователь вибирает награду или категорию → on_select_award )
             → (если награда) → refresh_detail_view
             → (если "Редагувати") → on_edit_award → show_edit_form
                 → (нажать "Зберегти") → on_save → (Call DB Save/Create) → refresh_detail_view
                 → (нажать "Скасувати") → on_cancel → refresh_detail_view
                 → (нажать "Видалити") → on_delete → (Call DB Delete) → refresh_detail_view
             → (если "Створити") → on_create_award → show_edit_form
                 → (нажать "Зберегти") → on_save → (Call DB Save/Create) → refresh_detail_view
"""
def find_tree_item(tree_ctrl, category_name, award_name):
    """
    Ищет элемент TreeCtrl по названию категории и названию награды.
    Возвращает wx.TreeItemId или невалидный wx.TreeItemId().
    """
    root = tree_ctrl.GetRootItem()
    if not root.IsOk():
        return wx.TreeItemId()

    # Ищем категорию
    category_item = find_tree_category(tree_ctrl, category_name)
    if not category_item.IsOk():
        return wx.TreeItemId()

    # Ищем награду внутри категории
    child_item, cookie = tree_ctrl.GetFirstChild(category_item)
    while child_item.IsOk():
        if tree_ctrl.GetItemText(child_item) == award_name:
            return child_item
        child_item, cookie = tree_ctrl.GetNextChild(category_item, cookie)

    return wx.TreeItemId() # Элемент не найден

def find_tree_category(tree_ctrl, category_name):
     """
     Ищет элемент TreeCtrl, соответствующий категории (прямой потомок корня).
     Возвращает wx.TreeItemId или невалидный wx.TreeItemId().
     """
     root = tree_ctrl.GetRootItem()
     if not root.IsOk():
         return wx.TreeItemId()

     child_item, cookie = tree_ctrl.GetFirstChild(root)
     while child_item.IsOk():
         if tree_ctrl.GetItemText(child_item) == category_name:
             return child_item
         child_item, cookie = tree_ctrl.GetNextChild(root, cookie)

     return wx.TreeItemId() # Категория не найдена

class DovidnykPanel(scrolled.ScrolledPanel): # ScrolledPanel для поддержки прокрутки
    def __init__(self, parent, conn, cursor, fut_place=None, kartka_panel=None):
        super().__init__(parent, wx.ID_ANY) 

        self.edit_mode = None # None=view, 'create'=создание, 'edit'=редактирование
        self.current_award_key = None  # Текущая выбранная награда (категория, название)
        self.current_award_id = None # ID выбранной награды из базы данных
        self.last_message = "" # Используется функцией update_footer_message
        self.fut_place = fut_place # Место для обновления футера в родительском окне
        self.conn = conn
        self.cursor = cursor
        self._is_dragging = False # Добавляем новый флаг
        self.loaded_image_blob = None # Временное хранилище BLOB изображения для редактирования/создания
        self.selected_category_for_creation = None # Категория, выбранная для создания новой награды

        self.kartka_panel = kartka_panel # для обновления комбосписка наград

        # Данные из базы данных structured as {category: {award_name: {details}}}
        self.awards_data = {}

        # --- Создание элементов UI и загрузка данных ---
        self.build_ui()
        # привязка действия к собитю уничтожения вкладки
        self.Bind(wx.EVT_WINDOW_DESTROY, self.OnDestroy)

    def OnDestroy(self, event):
        event.Skip()

    def build_ui(self):
        # Создание основного интерфейса
        main_sizer = wx.BoxSizer(wx.HORIZONTAL)

        # Дерево наград
        self.tree = wx.TreeCtrl(self, wx.ID_ANY, style=wx.TR_HAS_BUTTONS | wx.TR_HIDE_ROOT | wx.TR_DEFAULT_STYLE | wx.TR_EDIT_LABELS)
        self.tree.SetMinSize((300, -1))
        self.tree.Bind(wx.EVT_TREE_BEGIN_DRAG, self.on_begin_drag) 
        self.tree.Bind(wx.EVT_TREE_END_DRAG, self.on_end_drag)
        self.root = self.tree.AddRoot("Нагороди")

        # Привязка события выбора элемента в дереве
        self.tree.Bind(wx.EVT_TREE_SEL_CHANGED, self.on_tree_selection_changed)

        main_sizer.Add(self.tree, 0, wx.EXPAND | wx.ALL, 5) # Дерево не расширяется по горизонтали

        self.detail_panel = scrolled.ScrolledPanel(self, wx.ID_ANY)
        self.detail_sizer = wx.BoxSizer(wx.VERTICAL) 
        self.detail_panel.SetSizer(self.detail_sizer)
        self.detail_panel.SetAutoLayout(True) 

        # --- Создаем панели для разных видов и добавляем их в detail_sizer ---
        self.setup_detail_views() 
        self.detail_panel.SetupScrolling()
        main_sizer.Add(self.detail_panel, 2, wx.EXPAND | wx.ALL, 10) 

        # Установка основного сайзера для DovidnykPanel
        self.SetSizer(main_sizer)
        self.update_footer_message(DEF_FUT_LABEL)
        self.show_view("no_selection")

    def refresh_tree(self):
        if self.cursor:
            try:
                # 1. Отримуємо дані з БД (тут лише категорії з нагородами)
                self.awards_data = get_treedata(self.cursor)
                
                # 2. Ініціалізуємо порожні категорії з RankingValues 
                # Це гарантує, що target_category in self.awards_data завжди буде True
                for category in RankingValues:
                    if category and category not in self.awards_data:
                        self.awards_data[category] = {}

                if not self.awards_data and self.conn:
                    wx.MessageBox("База даних порожня...", "Попередження", wx.OK | wx.ICON_INFORMATION)

                self.populate_tree()
            except Exception as e:
                wx.MessageBox(f"Не вдалося завантажити або обробити дані з бази даних: {e}", "Помилка даних БД", wx.OK | wx.ICON_ERROR)
                self.awards_data = {} # Устанавливаем пустые данные при ошибке

        else: # Если курсор из MainFrame оказался None
            wx.MessageBox("З'єднання з базою даних недоступне.", "Помилка БД", wx.OK | wx.ICON_ERROR)
            self.awards_data = {} # Пустые данные


    def populate_tree(self):
        """ метод для заполнения дерева """
        self.tree.DeleteChildren(self.root)  # Очищаем существующие элементы дерева

        # Строим категории из RankingValues, а не из awards_data
        for category in RankingValues:
            if not category:  # пропускаем пустую категорию ""
                continue

            awards = self.awards_data.get(category, {})

            cat_item = self.tree.AppendItem(self.root, category)

            # Сортируем награды внутри категории
            for award_name in sorted(awards.keys()):
                award_details = awards.get(award_name, {})
                award_id = award_details.get("award_id")

                item = self.tree.AppendItem(cat_item, award_name)

                # привязываем ID награды
                self.tree.SetItemData(item, award_id)

        # self.tree.ExpandAllChildren(self.root)  # при необходимости

        self.last_message = DEF_FUT_LABEL
        self.update_footer_message(self.last_message)
    
    def setup_detail_views(self):
        """ метод для создания всех панелей/виджетов для разных режимов """

        # 1. Панель для сообщения "Ничего не выбрано"
        self.no_selection_panel = wx.Panel(self.detail_panel, wx.ID_ANY)
        no_selection_sizer = wx.BoxSizer(wx.VERTICAL)

        self.edit_create_button = wx.Button(self.no_selection_panel, wx.ID_ANY, label="Створити новий запис про нову нагороду")
        self.edit_create_button.Bind(wx.EVT_BUTTON, self.on_create_award) # Привязываем к новому методу
        no_selection_sizer.Add(wx.StaticText(self.no_selection_panel, label="Виберіть категорію для створення нової нагороди."), 0, wx.ALIGN_LEFT | wx.TOP, 50)         
        no_selection_sizer.Add(wx.StaticText(self.no_selection_panel, label="Перетягуйте <Назву нагороди> в режимі редагування щоб змінити її категорію."), 0, wx.ALIGN_LEFT | wx.TOP, 5)
        self.no_selection_panel.SetSizer(no_selection_sizer)
        self.detail_sizer.Add(self.no_selection_panel, 1, wx.EXPAND | wx.ALL, 0) # Добавляем в основной сайзер деталей, занимает пропорциональное место

        # 2. Панель для режима просмотра награды
        self.award_view_panel = wx.Panel(self.detail_panel, wx.ID_ANY)
        view_sizer = wx.BoxSizer(wx.VERTICAL)
        # Создаем все виджеты для просмотра ОДИН РАЗ
        view_short_label = wx.StaticText(self.award_view_panel, label="Нормативний акт про заснування:")
        self.view_text_short = wx.TextCtrl(self.award_view_panel, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_NO_VSCROLL, size=(-1, 60))
        self.view_image = wx.StaticBitmap(self.award_view_panel, wx.ID_ANY, size=(100, 100)) # Используем тот же размер
        view_full_label = wx.StaticText(self.award_view_panel, label="Опис нагороди:")
        self.view_text_full = wx.TextCtrl(self.award_view_panel, style=wx.TE_MULTILINE | wx.TE_READONLY, size=(-1, 300))
        self.view_edit_button = wx.Button(self.award_view_panel, wx.ID_ANY, label="Редагувати")
        self.view_edit_button.Bind(wx.EVT_BUTTON, self.on_edit_award) # Привязываем кнопку редактирования

        # Настройка сайзера для панели просмотра
        view_sizer.Add(view_short_label, 0, wx.TOP | wx.LEFT, 5)
        view_desc_img_sizer = wx.BoxSizer(wx.HORIZONTAL) # Горизонтальный сайзер для краткого описания и изображения
        view_desc_img_sizer.Add(self.view_text_short, 1, wx.EXPAND | wx.ALL, 5) # Краткое описание расширяется по горизонтали
        view_desc_img_sizer.Add(self.view_image, 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 5) # Изображение по центру вертикали
        view_sizer.Add(view_desc_img_sizer, 0, wx.EXPAND | wx.ALL, 0) # Добавляем горизонтальный сайзер

        view_sizer.Add(view_full_label, 0, wx.TOP | wx.LEFT, 5)
        view_sizer.Add(self.view_text_full, 1, wx.EXPAND | wx.ALL, 5) # Полное описание расширяется по вертикали

        view_button_sizer = wx.BoxSizer(wx.HORIZONTAL) # Сайзер для кнопки
        view_button_sizer.AddStretchSpacer(1) # Отталкивает кнопку вправо
        view_button_sizer.Add(self.view_edit_button, 0, wx.ALL, 5)
        view_sizer.Add(view_button_sizer, 0, wx.EXPAND | wx.ALL, 0) # Сайзер кнопки расширяется по горизонтали

        self.award_view_panel.SetSizer(view_sizer)
        self.detail_sizer.Add(self.award_view_panel, 1, wx.EXPAND | wx.ALL, 0) # Добавляем в основной сайзер деталей

        # 3. Панель для режима редактирования/создания награды
        self.award_edit_panel = wx.Panel(self.detail_panel, wx.ID_ANY)
        edit_sizer = wx.BoxSizer(wx.VERTICAL)
        # Создаем все виджеты для редактирования ОДИН РАЗ
        edit_name_label = wx.StaticText(self.award_edit_panel, label="Назва нагороди:")
        self.edit_input_name_award = wx.TextCtrl(self.award_edit_panel, wx.ID_ANY)
        edit_short_label = wx.StaticText(self.award_edit_panel, label="Нормативний акт про заснування:")
        self.edit_input_short = wx.TextCtrl(self.award_edit_panel, wx.ID_ANY)
        edit_full_label = wx.StaticText(self.award_edit_panel, label="Опис нагороди:")
        self.edit_input_full = wx.TextCtrl(self.award_edit_panel, wx.ID_ANY, style=wx.TE_MULTILINE, size=(-1, 200))

        self.edit_load_img_button = wx.Button(self.award_edit_panel, wx.ID_ANY, label="Завантажити зображення нагороди")
        self.edit_image_preview = wx.StaticBitmap(self.award_edit_panel, wx.ID_ANY, size=(100, 100), name="edit_image_preview") # Сохраняем name для поиска по нему

        self.edit_delete_button = wx.Button(self.award_edit_panel, wx.ID_ANY, label="Видалити")
        self.edit_save_button = wx.Button(self.award_edit_panel, wx.ID_ANY, label="Зберегти")
        self.edit_cancel_button = wx.Button(self.award_edit_panel, wx.ID_ANY, label="Скасувати")

        # Привязываем кнопки к новым методам класса
        self.edit_load_img_button.Bind(wx.EVT_BUTTON, self.on_load_img_file) # Предполагается, что on_load_img_file существует
        self.edit_delete_button.Bind(wx.EVT_BUTTON, self.on_delete_award) # Привязываем к новому методу
        self.edit_save_button.Bind(wx.EVT_BUTTON, self.on_save_award) # Привязываем к новому методу
        self.edit_cancel_button.Bind(wx.EVT_BUTTON, self.on_cancel_edit) # Привязываем к новому методу

        # Настройка сайзера для панели редактирования
        edit_sizer.Add(edit_name_label, 0, wx.LEFT | wx.TOP, 5)
        edit_sizer.Add(self.edit_input_name_award, 0, wx.EXPAND | wx.ALL, 5)
        edit_sizer.Add(edit_short_label, 0, wx.LEFT | wx.TOP, 5)
        edit_sizer.Add(self.edit_input_short, 0, wx.EXPAND | wx.ALL, 5)
        edit_sizer.Add(edit_full_label, 0, wx.LEFT, 5)
        edit_sizer.Add(self.edit_input_full, 1, wx.EXPAND | wx.ALL, 5) # Полное описание расширяется по вертикали

        edit_img_sizer = wx.BoxSizer(wx.HORIZONTAL) # Горизонтальный сайзер для загрузки изображения
        edit_img_sizer.Add(self.edit_load_img_button, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 10)
        edit_img_sizer.Add(self.edit_image_preview, 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 5) # Выравнивание по вертикали
        edit_sizer.Add(edit_img_sizer, 0, wx.ALIGN_CENTER_HORIZONTAL | wx.ALL, 5) # Сайзер изображения по центру горизонтали

        edit_btn_sizer = wx.BoxSizer(wx.HORIZONTAL) # Сайзер для кнопок
        edit_btn_sizer.Add(self.edit_delete_button, 0, wx.ALL, 5)
        edit_btn_sizer.AddStretchSpacer(1) # Отталкивает кнопки вправо
        edit_btn_sizer.Add(self.edit_save_button, 0, wx.ALL, 5)
        edit_btn_sizer.Add(self.edit_cancel_button, 0, wx.ALL, 5)
        edit_sizer.Add(edit_btn_sizer, 0, wx.EXPAND | wx.ALL, 0) # Сайзер кнопок расширяется по горизонтали

        self.award_edit_panel.SetSizer(edit_sizer)
        self.detail_sizer.Add(self.award_edit_panel, 1, wx.EXPAND | wx.ALL, 0) # Добавляем в основной сайзер деталей

    
    def show_view(self, view_name):
        """ вспомогательный метод для управления видимостью панелей режимов """
        # Используем Freeze/Thaw для более плавного обновления
        self.detail_panel.Freeze()
        try:
            # Скрываем все панели режимов
            self.no_selection_panel.Hide()
            self.award_view_panel.Hide()
            self.award_edit_panel.Hide()

            # Показываем нужную панель
            if view_name == "no_selection":
                self.no_selection_panel.Show()
            elif view_name == "award_view":
                self.award_view_panel.Show()
            elif view_name == "edit_form":
                self.award_edit_panel.Show()
                # При показе формы редактирования нужно также обновить состояние включенности кнопки "Удалить"
                if self.edit_mode == 'create':
                     self.edit_delete_button.Disable()
                else: # edit mode
                     self.edit_delete_button.Enable() # Включаем, если редактируем существующую
            else:
                self.no_selection_panel.Show() # Показываем по умолчанию

            self.detail_sizer.Layout()
            # self.detail_panel.Layout() # Иногда этот вызов также нужен, попробуйте, если Layout() сайзера недостаточно
            self.detail_panel.SetupScrolling() # Обновляем прокрутку панели деталей

        finally:
            self.detail_panel.Thaw()


    def on_tree_selection_changed(self, event):
        """ метод изменения дерева """
        # Если выделение изменилось из-за перетаскивания, игнорируем этот вызов
        if hasattr(self, '_is_dragging') and self._is_dragging:
            return

        item = event.GetItem()
        self.item_text = self.tree.GetItemText(item)
        parent_item = self.tree.GetItemParent(item)

        # Сбрасываем временные данные и состояние редактирования при смене выбора
        self.loaded_image_blob = None
        self.edit_mode = None # Всегда выходим из режима редактирования при смене выбора в дереве

        if item == self.root:
            # Выбран скрытый корневой элемент (обычно не происходит, но обрабатываем)
            self.current_award_key = None
            self.current_award_id = None
            self.selected_category_for_creation = None # Сбрасываем категорию для создания
            self.update_footer_message(DEF_FUT_LABEL)
            self.show_view("no_selection") # Показываем сообщение "ничего не выбрано"
            return

        if parent_item == self.root:
            # Выбрана категория
            self.current_award_key = None # Категория не является конкретной наградой
            self.current_award_id = None
            self.selected_category_for_creation = self.item_text # Сохраняем категорию для будущего создания

            # Показываем форму редактирования/создания в режиме создания новой награды
            self.show_edit_form(None, None) # Передаем None, None для индикации режима создания
            self.edit_mode = 'create' # Устанавливаем режим создания

            return

        # Если выбран лист (награда)
        category = self.tree.GetItemText(parent_item)
        award_name = self.item_text

        # Получаем ID из данных элемента дерева
        item_data = self.tree.GetItemData(item)
        self.current_award_id = item_data 

        if self.current_award_id is None:
            wx.MessageBox(f"Не вдалося отримати ID для нагороди '{award_name}'.", "Помилка даних елемента дерева", wx.OK | wx.ICON_ERROR)
            self.last_message = "no_selection."
            self.show_view("no_selection") # Показываем сообщение "ничего не выбрано"
            return

        self.current_award_key = (category, award_name)
        self.selected_category_for_creation = None # Сбрасываем категорию для создания

        # Показываем панель просмотра награды и заполняем ее данными
        self.show_award_view(category, award_name)
        self.edit_mode = 'view' # Устанавливаем режим просмотра

    
    def show_award_view(self, category, award_name):
        """ метод для показа и заполнения панели просмотра награды """
        # Получаем данные награды из кэша
        data = self.awards_data.get(category, {}).get(award_name, {})

        if not data:
            # Если данные не найдены в кэше (например, удалены где-то), переходим в режим "ничего не выбрано"
            self.show_view("no_selection")
            # Также нужно сбросить текущий выбранный элемент в дереве, если он еще выбран
            item_to_deselect = find_tree_item(self.tree, category, award_name) # Используем find_tree_item
            if item_to_deselect and self.tree.IsSelected(item_to_deselect):
                self.tree.UnselectItem(item_to_deselect)
            self.current_award_key = None
            self.current_award_id = None
            wx.MessageBox(f"Дані для нагороди '{award_name}' в категорії '{category}' не знайдено.", "Помилка даних", wx.OK | wx.ICON_ERROR)
            return

        # Заполняем СУЩЕСТВУЮЩИЕ виджеты на панели просмотра
        self.view_text_short.SetValue(data.get("law", ""))
        self.view_text_full.SetValue(data.get("grounds", ""))

        # Загружаем и отображаем изображение
        image_data_blob = data.get("image")
        if image_data_blob:
            # Используем max_dim с соответствующим значением (например, 100)
            bitmap = load_image_from_blob(image_data_blob, max_dim=100)
            self.view_image.SetBitmap(bitmap)
        else:
            # Показываем пустой битмап, если изображения нет
            self.view_image.SetBitmap(wx.Bitmap(100, 100)) # Пустой квадрат нужного размера

        # Убеждаемся, что кнопка "Редактировать" включена в режиме просмотра
        self.view_edit_button.Enable()

        # Показываем панель просмотра, скрывая остальные
        self.last_message = award_name
        self.update_footer_message(self.last_message)
        self.show_view("award_view")


    def show_edit_form(self, category, award_name):
        """  метод для показа и заполнения панели редактирования/создания """
        # Режим 'create' или 'edit' определяется перед вызовом этого метода в on_tree_selection_changed или on_edit_award
        is_creating = (self.edit_mode == 'create')

        current_data = {"law": "", "grounds": "", "image": None, "award_id": None} # Значения по умолчанию для нового записи

        if not is_creating:
            # Если режим 'edit', получаем существующие данные
            if category is None or award_name is None:
                # Это не должно происходить, если логика в on_edit_award правильная
                self.edit_mode = None
                self.show_view("no_selection")
                return

            current_data = self.awards_data.get(category, {}).get(award_name, {})
            if not current_data:
                # Данные не найдены в кэше для редактирования
                wx.MessageBox(f"Дані для редагування нагороди '{award_name}' в категорії '{category}' не знайдено.", "Помилка даних", wx.OK | wx.ICON_ERROR)
                self.edit_mode = None
                self.show_view("no_selection") # Возвращаемся в режим "ничего не выбрано"
                return

            # Для режима редактирования, сохраняем ID и ключ
            self.current_award_id = current_data.get("award_id") # Получаем ID из данных
            self.current_award_key = (category, award_name) # Сохраняем ключ редактируемой награды

        else: # Режим 'create'
            # Убеждаемся, что current_award_id и key сброшены в None для создания
            self.current_award_id = None
            self.current_award_key = None
            # category для создания уже сохранен в self.selected_category_for_creation в on_tree_selection_changed

        # Сохраняем BLOB изображения временно для формы (для предпросмотра и сохранения)
        self.loaded_image_blob = current_data.get("image")

        # --- Заполняем СУЩЕСТВУЮЩИЕ виджеты на панели редактирования/создания ---
        # Используем award_name из параметров функции, если редактируем (он будет None при создании)
        self.edit_input_name_award.SetValue(award_name if not is_creating and award_name is not None else "")
        self.edit_input_short.SetValue(current_data.get("law", ""))
        self.edit_input_full.SetValue(current_data.get("grounds", ""))

        # Обновляем предпросмотр изображения
        if self.loaded_image_blob:
            preview_bitmap = load_image_from_blob(self.loaded_image_blob, max_dim=100) # <-- Изменено на 'max_dim'
            self.edit_image_preview.SetBitmap(preview_bitmap)
        else:
            self.edit_image_preview.SetBitmap(wx.Bitmap(100, 100)) # Пустой квадрат

        # Кнопка "Удалить" включена только в режиме редактирования существующей записи
        if is_creating:
            self.edit_delete_button.Disable()
        else:
            self.edit_delete_button.Enable()

        # Показываем панель редактирования/создания, скрывая остальные
        self.last_message = "Режим редагування увімкнений."
        self.update_footer_message(self.last_message)
        self.show_view("edit_form")


    def on_save_award(self, event):
        """ метод пoдготовки и передачи даних из форм для сохранения в БД """
        # Получаем данные из полей ввода
        name_award_val = self.edit_input_name_award.GetValue().strip()
        short_val = self.edit_input_short.GetValue().strip()
        full_val = self.edit_input_full.GetValue().strip()
        image_data_to_save = self.loaded_image_blob # Используем временное хранилище для изображения

        if not name_award_val:
            wx.MessageBox("Назва нагороди не може бути порожньою.", "Помилка введення", wx.OK | wx.ICON_ERROR)
            self.edit_input_name_award.SetFocus()
            return

        # Определяем режим: создание или редактирование
        is_creating = (self.edit_mode == 'create')

        if is_creating:
            target_category = self.selected_category_for_creation # Категория для создания

            if not target_category or target_category not in self.awards_data:
                wx.MessageBox("Не вибрано категорію для створення.", "Помилка", wx.OK | wx.ICON_ERROR)
                self.show_view("no_selection")
                return

            # Проверка на дублирование имени в выбранной категории
            if name_award_val in self.awards_data.get(target_category, {}):
                 wx.MessageBox(f"Нагорода з назвою '{name_award_val}' вже існує в категорії '{target_category}'.", "Помилка введення", wx.OK | wx.ICON_ERROR)
                 self.edit_input_name_award.SetFocus()
                 return

            # Вызываем функцию создания в БД
            # Получаем ranking на основе выбранной категории для создания
            ranking_for_creation = self.get_ranking_from_category_name(target_category)
            if ranking_for_creation is None:
                 wx.MessageBox(f"Не вдалося визначити ранжування для категорії '{target_category}'.", "Помилка даних", wx.OK | wx.ICON_ERROR)
                 return # Не можем создать запись без валидного ранжирования

            # Предполагается, что create_award_in_db принимает ranking
            new_id = create_award_in_db(self.conn, self.cursor, target_category, name_award_val, short_val, full_val, image_data_to_save, ranking_for_creation) # Убедитесь, что функция DB корректна

            if new_id is not None:
                # Обновляем кэш данных в памяти при успехе
                if target_category not in self.awards_data:
                     # Это не должно происходить, если populate_tree вызывается при старте, но для безопасности
                     self.awards_data[target_category] = {} # Словарь категорий должен быть уже создан

                self.awards_data[target_category][name_award_val] = {
                     "award_id": new_id,
                     "law": short_val,
                     "grounds": full_val,
                     "image": image_data_to_save,
                     "original_ranking_int": ranking_for_creation # Сохраняем ranking в кэше
                }

                # Обновляем дерево
                # Находим или добавляем категорию в дереве
                parent_item = find_tree_category(self.tree, target_category) # Ищем по дереву
                if not parent_item:
                     # Если категория не найдена (что странно, если она в self.awards_data), добавляем ее
                     parent_item = self.tree.AppendItem(self.root, target_category)
                     # После добавления новой категории, нужно бы пересортировать элементы в корне дерева
                     # self.tree.SortChildren(self.root) # Это может быть сложно, возможно, проще перестроить все дерево

                if parent_item:
                     new_item = self.tree.AppendItem(parent_item, name_award_val)
                     self.tree.SetItemData(new_item, new_id) # привязываем ID
                     # Сортируем элементы внутри категории после добавления нового
                     self.tree.SortChildren(parent_item)
                     self.tree.Expand(parent_item)
                     self.tree.SelectItem(new_item) # Выбираем новый элемент в дереве
                     # Обновляем текущий выбранный элемент после создания
                     self.current_award_key = (target_category, name_award_val)
                     self.current_award_id = new_id

                wx.MessageBox("Новий запис успішно створено.", "Створення успішне", wx.OK | wx.ICON_INFORMATION)
                self.edit_mode = 'view' # Переходим в режим просмотра
                self.show_award_view(target_category, name_award_val) # Показываем созданную награду
                self.last_message = "Запис створено."
                self.update_footer_message(self.last_message)

                # обновляем данние КАРТКА
                self._refresh_combo_award_ui()

            else:
                 wx.MessageBox("Виникла помилка при створенні запису в базі даних.", "Помилка БД", wx.OK | wx.ICON_ERROR)

        else: # Режим 'edit'
            original_category, original_award_name = self.current_award_key # Используем текущий выбранный ключ
            award_id_to_save = self.current_award_id # Используем текущий выбранный ID

            if not award_id_to_save:
                wx.MessageBox("Не вдалося зберегти: Відсутній ID нагороди.", "Помилка", wx.OK | wx.ICON_ERROR)
                self.show_view("no_selection")
                return

            # Проверка на изменение имени и конфликт в ТЕКУЩЕЙ категории
            if name_award_val != original_award_name:
                if name_award_val in self.awards_data.get(original_category, {}):
                    wx.MessageBox(f"Нагорода з назвою '{name_award_val}' вже існує в категорії '{original_category}'.", "Помилка введення", wx.OK | wx.ICON_ERROR)
                    self.edit_input_name_award.SetFocus()
                    return

            # Вызываем функцию сохранения в БД 
            ranking_for_save = self.get_ranking_from_category_name(original_category)

            if save_award_to_db(self.conn, self.cursor, award_id_to_save, name_award_val, short_val, full_val, image_data_to_save, ranking_for_save): 
                # Обновляем кэш данных в памяти при успехе
                # Если имя изменилось, нужно удалить старую запись и добавить новую с новым именем
                if name_award_val != original_award_name:
                    # Удаляем старую запись по старому имени
                    if original_category in self.awards_data and original_award_name in self.awards_data[original_category]:
                        award_details = self.awards_data[original_category].pop(original_award_name)
                    else:
                        # Если не нашли в кэше, возможно, нужно перезагрузить данные или обработать как ошибку
                        award_details = {} # Пустой словарь, чтобы избежать ошибки ниже

                    # Добавляем обновленные данные с новым именем
                    self.awards_data[original_category][name_award_val] = award_details

                # Обновляем кэш
                self.awards_data[original_category][name_award_val].update({
                    "law": short_val,
                    "grounds": full_val,
                    "image": image_data_to_save,
                    "original_category": ranking_for_save # Сохраняем обновленный ranking, если он определен
                    # award_id остается тем же
                })

                # Обновляем текст элемента дерева, если имя изменилось
                if name_award_val != original_award_name:
                    old_item = find_tree_item(self.tree, original_category, original_award_name) # Ищем старый элемент по старому имени
                    if old_item:
                        self.tree.SetItemText(old_item, name_award_val)

                # Обновляем текущий выбранный ключ, если имя изменилось
                self.current_award_key = (original_category, name_award_val)
                # current_award_id не меняется

                wx.MessageBox("Зміни успішно збережено.", "Збереження успішне", wx.OK | wx.ICON_INFORMATION)
                self.edit_mode = 'view' # Переходим в режим просмотра
                self.show_award_view(original_category, name_award_val) # Показываем обновленную награду
                self.last_message = "Зміни збережено."
                self.update_footer_message(self.last_message)

                # обновляем данние КАРТКА
                self._refresh_combo_award_ui()

            else:
                wx.MessageBox("Виникла помилка при збереженні запису в базі даних.", "Помилка БД", wx.OK | wx.ICON_ERROR)


    def get_ranking_from_category_name(self, category_name):
        """
        Преобразует название категории (строку) в соответствующее числовое значение ранжирования.
        Использует индексы списка RankingValues.
        Возвращает числовое ранжирование (int) или None, если название не найдено."""
        try:
            ranking_value = RankingValues.index(category_name)
            return ranking_value
        except ValueError:
            return None 


    def on_cancel_edit(self, event):
        # Сбрасываем временные данные изображения
        self.loaded_image_blob = None
        self.edit_mode = None # Выходим из режима редактирования/создания

        # Восстанавливаем дерево в исходное состояние
        self.refresh_tree()  
        # Решаем, что показать после отмены
        if self.current_award_key:
            # Если отменяли редактирование существующей награды, возвращаемся к её просмотру
            category, award_name = self.current_award_key
            self.show_award_view(category, award_name)
        else:
            # Если отменяли создание новой награды, возвращаемся в режим "ничего не выбрано"
            self.show_view("no_selection")

        self.last_message = "Редагування скасовано."
        self.update_footer_message(self.last_message)

    def on_delete_award(self, event):
        """ Метод удаления записи о награде из БД """
        if self.edit_mode != 'edit' or not self.current_award_id:
            wx.MessageBox("Неможливо видалити запис в даному режимі або без ID.", "Помилка видалення", wx.OK | wx.ICON_ERROR)
            return

        category, award_name = self.current_award_key # Используем текущий выбранный ключ для сообщения

        confirm_dlg = wx.MessageDialog(
            self,
            f"Ви впевнені, що хочете видалити нагороду '{award_name}' з категорії '{category}'?",
            "Підтвердження видалення",
            wx.YES_NO | wx.ICON_WARNING
        )
        if confirm_dlg.ShowModal() == wx.ID_YES:
            # Вызываем функцию удаления из БД
            if delete_award_from_db(self.conn, self.cursor, self.current_award_id): # Убедитесь, что функция DB корректна
                 # Обновляем кэш данных в памяти при успехе
                 if category in self.awards_data and award_name in self.awards_data[category]:
                      del self.awards_data[category][award_name]

                 # Удаляем элемент из дерева
                 item_to_delete = find_tree_item(self.tree, category, award_name) # Ищем по дереву
                 if item_to_delete:
                      self.tree.Delete(item_to_delete)

                 wx.MessageBox("Запис успішно видалено.", "Видалення успішне", wx.OK | wx.ICON_INFORMATION)
                 # После удаления сбрасываем состояние и переходим в режим "ничего не выбрано"
                 self.edit_mode = None # Выходим из режима
                 self.current_award_key = None # Сбрасываем выбранную награду
                 self.current_award_id = None
                 self.loaded_image_blob = None # Сбрасываем временные данные изображения

                 self.show_view("no_selection") # Переходим в режим "ничего не выбрано"
                 self.last_message = "Запис видалено."
                 self.update_footer_message(self.last_message) # Обновляем футер

                 # Возможно, нужно сбросить выбранный элемент в дереве, если он еще как-то выделен
                 # self.tree.UnselectAll() # show_view("no_selection") и сброс key/id могут быть достаточны

                 # обновляем данние КАРТКА
                 self._refresh_combo_award_ui()

            else:
                 wx.MessageBox("Виникла помилка при видаленні запису з бази даних.", "Помилка БД", wx.OK | wx.ICON_ERROR)

        confirm_dlg.Destroy() # Уничтожаем диалог

    def on_begin_drag(self, event):
        """ фуккция проверяет условия для начала перетягивания """
        item = event.GetItem()
        parent = self.tree.GetItemParent(item)

        # если не включен режим редактирования обриваем попитку и показиваем сообщение
        if self.edit_mode != 'edit':
            self.last_message = "Для зміни категорії увімкніть режим редагування."
            self.update_footer_message(self.last_message)
            return

        if parent == self.root:
            return

        self.drag_item = item
        self._is_dragging = True # Устанавливаем флаг, что началось перетаскивание

        event.Allow()


    def on_end_drag(self, event):
        # Получаем элемент, на который отпустили мышь (цель перетаскивания)
        target_item = event.GetItem()

        # Получаем элемент, который перетаскивали (источник перетаскивания)
        source_item = self.drag_item

        # Если нет ни источника, ни цели (что-то пошло не так) — выходим
        if not source_item or not target_item:
            return

        # Получаем текст целевого элемента
        target_text = self.tree.GetItemText(target_item)
        
        # Получаем текст перетаскиваемого элемента
        source_text = self.tree.GetItemText(source_item)

        # Получаем родителя перетаскиваемого элемента
        source_parent = self.tree.GetItemParent(source_item)

        # Получаем текст родителя перетаскиваемого элемента (категорию)
        source_category = self.tree.GetItemText(source_parent)

        # Перемещать можно только в категорию
        if self.tree.GetItemParent(target_item) != self.root:
            return

        dest_category = target_text

        if dest_category == source_category:
            # Перетаскивание в ту же категорию — ничего не делаем
            return

        # Обновляем awards_data
        award_data = self.awards_data[source_category].pop(source_text)

        if dest_category not in self.awards_data:
            self.awards_data[dest_category] = {}

        self.awards_data[dest_category][source_text] = award_data

        # если категории ещё нет в awards_data — создаём
        if dest_category not in self.awards_data:
            self.awards_data[dest_category] = {}

        self.awards_data[dest_category][source_text] = award_data

        # Вставляем новый элемент в нужную категорию
        dest_category_item = None
        child, cookie = self.tree.GetFirstChild(self.root)  # Ищем нужную категорию в дереве

        while child.IsOk():
            if self.tree.GetItemText(child) == dest_category:
                dest_category_item = child
                break
            child, cookie = self.tree.GetNextChild(self.root, cookie)

        if dest_category_item is None:
            return  # Категория не найдена — что-то пошло не так

        # Добавляем новую запись в нужную категорию
        new_item = self.tree.AppendItem(dest_category_item, source_text)

        # Привязываем award_id к новому элементу дерева
        new_award_id = award_data.get("award_id") # Получаем ID из данных, которые мы удалили из кэша старой категории
        if new_award_id is not None:
             self.tree.SetItemData(new_item, new_award_id)

        # Удаляем старую запись в дереве
        self.tree.Delete(source_item)

        # создаём новый пункт в дереве и выделяем его 
        self.tree.SelectItem(new_item)
        self._is_dragging = False  # Сбрасываем флаг после завершения перетаскивания
        self.current_award_key = (dest_category, source_text)
        # Возможно, здесь также стоит обновить self.current_award_id,
        # хотя по логике он должен быть правильным, т.к. не менялся
        self.current_award_id = new_award_id


    # def on_create_award(self, event):
    #     """ Обработчик кнопки "Створити" в режиме "ничего не выбрано" """
    #     if self.selected_category_for_creation:
    #         self.edit_mode = 'create' # Устанавливаем режим создания
    #         self.show_edit_form(None, None) # Передаем None, None для индикации режима создания
    #         self.last_message = f"Режим створення. Категорія: {self.selected_category_for_creation}"
    #         self.update_footer_message(self.last_message)
    #     else:
    #         wx.MessageBox("Виберіть категорію для створення нової нагороди.", "Помилка", wx.OK | wx.ICON_ERROR)

    def on_create_award(self, event):
        """ Обработчик кнопки 'Створити' в режиме 'ничего не выбрано' """
        if not self.selected_category_for_creation:
            # Берём первую категорию из RankingValues, которая есть в self.awards_data или вообще первую
            for cat in RankingValues[1:]:  # пропускаем пустую строку
                if cat in self.awards_data:
                    self.selected_category_for_creation = cat
                    break
            else:
                # Если в awards_data нет ни одной категории, берем первую из RankingValues
                self.selected_category_for_creation = RankingValues[1]

        if self.selected_category_for_creation:
            self.edit_mode = 'create'
            self.show_edit_form(None, None)
            self.last_message = f"Режим створення. Категорія: {self.selected_category_for_creation}"
            self.update_footer_message(self.last_message)
        else:
            wx.MessageBox("Не вдалося визначити категорію для створення нової нагороди.", "Помилка", wx.OK | wx.ICON_ERROR)


    def on_edit_award(self, event):        
        # Переход в режим редактирования существующей награды"
        self.edit_mode = 'edit'
        if not self.current_award_key:
            return
        self.show_edit_form(*self.current_award_key)


    def on_load_img_file(self, event):
        """Обробляє натискання кнопки 'Завантажити файл'."""
        # Убедимся, что фильтр файлов правильный для PNG
        wildcard = "PNG Image Files (*.png)|*.png|All files (*.*)|*.*" # Добавим опцию "Все файлы" для гибкости

        dlg = wx.FileDialog(
            self, message="Виберіть файл для завантаження",
            defaultDir="",
            defaultFile="",
            wildcard=wildcard,
            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST
        )

        if dlg.ShowModal() == wx.ID_OK:
            path = dlg.GetPath()
            try:
                with open(path, 'rb') as f:
                    content = f.read()
                self.loaded_image_blob = content # Загруженные данные здесь

                # Если у вас есть элемент для ПРЕДПРОСМОТРА изображения
                if self.loaded_image_blob:
                    # Используем load_image_from_blob для создания Bitmap из загруженных данных (self.loaded_image_blob)
                    # Выберите подходящее значение для максимального измерения (например, 100)
                    bitmap = load_image_from_blob(self.loaded_image_blob, max_dim=100) # <-- ИСПОЛЬЗУЕМ self.loaded_image_blob

                    # Устанавливаем созданный bitmap в элемент предпросмотра
                    self.edit_image_preview.SetBitmap(bitmap) # <-- ИСПОЛЬЗУЕМ bitmap
                else:
                    # Если загрузка не удалась или файл пустой
                    self.edit_image_preview.SetBitmap(wx.Bitmap(100, 100)) # Отобразить пустой квадрат

            except IOError:
                wx.MessageBox("Неможливо відкрити файл '%s'." % path, "Помилка", wx.OK | wx.ICON_ERROR)
            except Exception as e:
                wx.MessageBox(f"Помилка обробки зображення: {e}", "Помилка", wx.OK | wx.ICON_ERROR)
                self.loaded_image_blob = None # Сбросить данные при ошибке
                self.edit_image_preview.SetBitmap(wx.Bitmap(100, 100)) # Сбросить предпросмотр

        dlg.Destroy()

    def _refresh_combo_award_ui(self):
        # --- Метод для ПОВНОГО оновлення списків нагород в КАРТКА ---
        # Цей метод викликається ПІСЛЯ збереження змін про нагороди
        if self.kartka_panel: 
            self.kartka_panel._update_award_combobox()
        
    def update_footer_message(self, message):
        #  вивод текста в футер
        if self.fut_place:
            self.last_message = message
            self.fut_place.SetLabel(self.last_message)  # обновляем футер

    def get_footer_message(self):
        """ метод для определения значения self.last_message """
        return self.last_message


# --- Конец класса DovidnykPanel ---
