# kartka.py
import wx
import wx.adv
import wx.richtext as rt
import re
import wx.lib.scrolledpanel as scrolled # <-- Додайте цей імпорт
import io
from PIL import Image, ImageEnhance # Need to import PIL
from datetime import datetime
from config import DEF_FUT_LABEL
from database_logic import (
    get_units_and_ranks, # загрузка списков підрозділів и званий
    get_treedata, # загрузка списка ВСЕХ известних наград из ДОВІДНИК
    search_q,
    is_valid_INN,
    execute_query
)

from ui_utils import load_image_from_blob, ComboSearchHelper
from keymap_kartka import setup_accelerators, bind_help_tooltips

AWARD_IMAGE_SIZE = 80 # размер картинки
CURRENT_DATA = wx.DateTime.Now()

class KartkaPanel(scrolled.ScrolledPanel):
    def __init__(self, parent, conn, cursor, settings_manager, fut_place=None, search_panel=None):
        super(KartkaPanel, self).__init__(parent, wx.ID_ANY)

        self.conn = conn
        self.cursor = cursor
        self.fut_place = fut_place  # Получаем переданное место футера
        self.settings_manager = settings_manager # Зберігаємо settings_manager
        self.search_panel = search_panel # ЗБЕРІГАЄМО ПОСИЛАННЯ НА TAB1PANEL
        self.meed_row_items = []  # Список для элементов, которые будут скрываться/показываться в группе награды
        self.group3_row_items = [] # Список для элементов, которые будут скрываться/показываться в группе подання (при отмове)
        self.last_message = "Вкладка для редагування даних щодо осіб, нагород і подань"

        # Додаємо атрибути для елементів, які не були збережені раніше
        # Ініціалізуємо їх як None, вони будуть створені в build_ui
        self.full_name_ctrl = None
        self.inn = None
        self.rank_ctrl = None     # звание
        self.unit_ctrl = None     # підрозділ
        self.birtday = None       # StaticText, але посилання потрібне для оновлення
        self.submission_number_ctrl = None # 
        self.submission_movement_ctrl = None # 
        self.submission_posthumous_checkbox = None #  (чекбокс "посмертно" в поданні)
        self.pres_denied_checkbox = None
        self.pres_unlink_meed_checkbox = None
        self.PresDATE = None
        self.text_pres = None
        self.award_basis_ctrl = None # Текстове поле "Рішення"
        self.award_date_ctrl = None # Дата нагородження
        self.awards_data = None 

        self.meed_dead_checkbox = None # Чекбокс "Посмертно" в нагороді
        self.ConsingN = None         # Накладна
        self.NumberMeed = None      # Номер нагороди
        self.handower_btn = None
        self.HandowerNAME = None    # Вручено (ім'я)
        self.HandoverDATE = None    # Вручено (дата)
        self.birth_date = None      # Для збереження обчисленої дати народження з ІНН
        self.retry_meed_btn = None  # кнопка повторення останньої дії (блок нагородження)
        self.award_image_display = None
        self.protok_handing = None

        self._is_programmatic_award_change = False 
        
        # --- Завантаження початкових даних ЗВАННЯ / ПІДРОЗДІЛ / ВІДОМІ НАГОРОДИ ---
        self._loaded_award_names = [] # назви нагород для комбобокса
        self._loaded_units = []
        self._loaded_ranks = []
        self._is_updating_fields = False # прапорець завантаження нагроджени/подань

        self.selected_award_id = None # змінна для id нагороди (award_id)

        self.search_query_text = None # змінна для оновлення даних після збереження

        self.delete_ctrl = None # комбосписок видалення
        self.delete_mode_on = None # змінна режиму видалення

        try:
            if self.cursor:
                # 1. Завантажуємо дані рангів та підрозділів
                self._loaded_ranks, self._loaded_units = get_units_and_ranks(self.cursor)
                self._loaded_ranks = [rank for rank in self._loaded_ranks if rank != ""]  
                self._loaded_ranks.insert(0, "")  
                self._loaded_units = [unit for unit in self._loaded_units if unit != ""] 
                self._loaded_units.insert(0, "") 
            else:
                # Обробка випадку, коли курсор не був створений
                self._loaded_units = ["(Помилка завантаження)"]
                self._loaded_ranks = ["(Помилка завантаження)"]
                wx.MessageBox("Курсор бази даних не був ініціалізований.", "Помилка", wx.OK | wx.ICON_ERROR)

        except Exception as e:
            # Загальна обробка помилок завантаження даних
            self._loaded_units = ["(Помилка завантаження)"]
            self._loaded_ranks = ["(Помилка завантаження)"]
            wx.MessageBox(f"Загальна помилка при завантаженні початкових даних: {e}", "Помилка", wx.OK | wx.ICON_ERROR)
        # --- Кінець завантаження початкових даних ---

        self._load_award_data() # завантажуємо дані про нагороди

        # --- Завантаження стандартного зображення (логотипу) для панелі нагород ---
        self.default_award_bitmap = None 
        default_logo_bitmap = None
        logo_blob = None

        # Перевіряємо, що settings_manager існує і налаштування завантажені
        if self.settings_manager and hasattr(self.settings_manager, 'is_loaded') and self.settings_manager.is_loaded:
            if hasattr(self.settings_manager, 'get_logo_blob'):
                 logo_blob = self.settings_manager.get_logo_blob()

        # Використовуємо load_image_from_blob для створення Bitmap з логотипу
        try:
            if 'load_image_from_blob' in globals():
                default_logo_bitmap = load_image_from_blob(
                    logo_blob,
                    max_dim=AWARD_IMAGE_SIZE
                    # Можна додати grayscale=True або brightness_factor=... якщо лого має бути фоновим
                )
            else:
                default_logo_bitmap = None 

        except Exception as e:
            default_logo_bitmap = None 

        # Перевіряємо, чи отримали валідний Bitmap логотипу. Якщо ні, створюємо простий порожній fallback.
        if default_logo_bitmap and default_logo_bitmap.IsOk():
            self.default_award_bitmap = default_logo_bitmap
        else:
            # Fallback: простий порожній Bitmap з фоном вікна
            fallback_bitmap = wx.Bitmap(AWARD_IMAGE_SIZE, AWARD_IMAGE_SIZE)
            dc = wx.MemoryDC(fallback_bitmap)
            dc.SetBackground(wx.Brush(wx.SystemSettings.GetColour(wx.SYS_COLOUR_3DFACE)))
            dc.Clear()
            del dc # Звільнити DeviceContext
            self.default_award_bitmap = fallback_bitmap

        # --- Кінець завантаження стандартного зображення ---


        # --- Атрибути для обробки результатів пошуку ---
        # Комбобокс для вибору особи зі знайдених
        self.person_search_results_ctrl = None # Комбобокс
        self.person_result_count_text = None # длина списка комбобокса

        # Зберігати список ID осіб з результатів пошуку
        self.latest_search_person_ids_list = [] # Атрибут для СПИСКУ ID
        self.source_data_award_and_presentation = [] # Атрибут для СИРИХ даних пошуку
        self.show_hellou = None

        # Словник для відображення рядка комбобокса до ID особи
        self._search_result_id_map = {} 

        # Зберігати ID особи, дані якої зараз завантажені на панелі
        self.current_person_id = None # <-- Зберігаємо поточний ID osoba

        # Елемент для відображення інформації про ЗАВАНТАЖЕНУ ОСОБУ
        self.current_loaded_person_display = None

        self.meed_list = None
        self.presentations_list = None

        self.current_presentation_id = None # <-- Зберігаємо поточний ID presentation
        self.current_meed_id = None # <-- Зберігаємо поточний ID meed

        self.meed_presentation_is_linked = False

        # --- Кінець блоку атрибутів обробки результатів пошуку ---

        self.build_ui()
        # --- Підключаємо гарячі клавіші та хелп з keymap_kartka.py ---
        setup_accelerators(self, self.on_save, self.on_hotkey_find, self.clear_person_data)
        bind_help_tooltips(self)
        
        self.SetupScrolling() # Викликати після build_ui
        self.Bind(wx.EVT_WINDOW_DESTROY, self.OnDestroy)


    # --- Метод для закриття з'єднання з БД (залишаємо, як є) ---
    def OnDestroy(self, event):
        event.Skip()

    def on_hotkey_find(self, event):
        """Швидкий перехід на поле вибору особи за Ctrl+F"""
        if self.person_search_results_ctrl:
            self.person_search_results_ctrl.SetFocus()

    # -------------- методи построения елементов интерфейса ---------------

    def build_ui(self):
        main_sizer = wx.BoxSizer(wx.VERTICAL)

        # Секции интерфейса - верхние части остаются на отдельных вертикальных линиях
        main_sizer.Add(self.create_info_group(), 0, wx.ALL | wx.EXPAND, 10)
        main_sizer.Add(self.create_submission_group(), 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 10)

        # Создаем горизонтальный sizer для нижней секции (Award Group + Buttons)
        bottom_sizer = wx.BoxSizer(wx.HORIZONTAL)

        # Добавляем секцию награды в горизонтальный sizer
        bottom_sizer.Add(self.create_award_group(), 1, wx.EXPAND | wx.RIGHT, 10) 

        # Добавляем кнопки в тот же горизонтальный sizer
        buttons = self.create_buttons()
        bottom_sizer.Add(buttons, 0, wx.ALIGN_CENTER_VERTICAL)

        # Добавляем горизонтальный sizer нижней секции в основной вертикальный sizer
        main_sizer.Add(bottom_sizer, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 10)

        self.SetSizer(main_sizer)

    # ОСОБА
    def create_info_group(self):
        box = wx.StaticBox(self, label="Інформація про особу")
        sizer = wx.StaticBoxSizer(box, wx.VERTICAL)

        # --- КОМБОБОКС ДЛЯ РЕЗУЛЬТАТІВ ПОШУКУ ---

        # --- сайзер ДЛЯ ComboBox + текстового поля ---
        combo_and_count_sizer = wx.BoxSizer(wx.HORIZONTAL)
        combo_and_count_sizer.Add(wx.StaticText(self, label="ID:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, border=3) 
        # ComboBox для результатів пошуку
        self.person_search_results_ctrl = wx.ComboBox(self, choices=["Завантаження..."], style=wx.CB_READONLY)
        self.person_search_results_ctrl.Bind(wx.EVT_COMBOBOX, self.on_person_selected)

        combo_and_count_sizer.Add(self.person_search_results_ctrl, proportion=1, flag=wx.EXPAND | wx.ALL, border=3)

        # Текстовий елемент для кількості записів
        self.person_result_count_text = wx.StaticText(self, label="-")
        self.person_result_count_text.SetMinSize((30, -1))  

        combo_and_count_sizer.Add(self.person_result_count_text, flag=wx.ALIGN_CENTER_VERTICAL | wx.LEFT, border=10)

        # Додаємо горизонтальний сайзер до основного
        sizer.Add(combo_and_count_sizer, flag=wx.EXPAND | wx.ALL, border=0)


        # ПІБ
        pib_sizer = wx.BoxSizer(wx.HORIZONTAL)
        pib_sizer.Add(wx.StaticText(self, label="ПІБ: "), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT)
        self.full_name_ctrl = wx.TextCtrl(self) 
        pib_sizer.Add(self.full_name_ctrl, 2, wx.EXPAND)

        pib_sizer.Add(wx.StaticText(self, label="РНОКПП:"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.inn = wx.TextCtrl(self) 
        self.inn.SetMaxLength(10)
        pib_sizer.Add(self.inn, 1, wx.EXPAND)
        self.inn.Bind(wx.EVT_KILL_FOCUS, self.on_inn_focus_lost)
        sizer.Add(pib_sizer, 0, wx.EXPAND | wx.ALL, 3)

        grid = wx.FlexGridSizer(0, 5, vgap=5, hgap=2)  # 0 означає автоматичне визначення кількості рядків
        grid.Add(wx.StaticText(self, label="Звання:"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.rank_ctrl = wx.ComboBox(self, choices=self._loaded_ranks, style=wx.CB_READONLY) 
        grid.Add(self.rank_ctrl, 1, wx.EXPAND)
        grid.AddGrowableCol(1, 3)

        grid.Add(wx.StaticText(self, label="Підрозділ:"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.unit_ctrl = wx.ComboBox(self, choices=self._loaded_units, style=wx.CB_READONLY) 
        grid.Add(self.unit_ctrl, 1, wx.EXPAND)
        grid.AddGrowableCol(3, 3)
    
        self.birtday = wx.StaticText(self, label="Дата народження: ---- -- --") 
        grid.Add(self.birtday, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT)
        grid.AddGrowableCol(4, 1)
        sizer.Add(grid, 0, wx.ALL | wx.EXPAND, 3)

        return sizer


    # ПОДАННЯ
    def create_submission_group(self):
        box = wx.StaticBox(self, label=" Параметри подання ")
        sizer = wx.StaticBoxSizer(box, wx.VERTICAL)

        # Вибір подання
        pres_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.pres_ctrl = wx.ComboBox(self, choices=[""], style=wx.CB_READONLY) # Комбобокс вибора подання
        self.pres_ctrl.Bind(wx.EVT_COMBOBOX, self.fill_submission_fields)        
        pres_sizer.Add(wx.StaticText(self, label="ID:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, border=3) 
        # Текстовий елемент для кількості записів
        self.pres_count_text = wx.StaticText(self, label="-")
        self.pres_count_text.SetMinSize((30, -1))  

        pres_sizer.Add(self.pres_ctrl, 2, wx.EXPAND)
        pres_sizer.Add(self.pres_count_text, flag=wx.ALIGN_CENTER_VERTICAL | wx.LEFT, border=10)
        sizer.Add(pres_sizer, 0, wx.EXPAND | wx.ALL, 3)

        # FlexGridSizer для верхніх полів (Номер, Дата, Виконавець, Рух)
        # Тепер має 8 колонок: Label, Control, Label, Control, Label, Control, Label, Control
        grid = wx.FlexGridSizer(rows=1, cols=9, vgap=5, hgap=2)

        # Номер подання
        grid.Add(wx.StaticText(self, label=" Номер:"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.submission_number_ctrl = wx.TextCtrl(self) 
        grid.Add(self.submission_number_ctrl, 0, wx.EXPAND) # proportion 0 тут, розтягування в FlexGridSizer

        # Дата реєстрації подання
        grid.Add(wx.StaticText(self, label="Дата (м/д/р):"), 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 5) # Додано відступ
        self.PresDATE = wx.adv.DatePickerCtrl(self, style=wx.adv.DP_DROPDOWN | wx.adv.DP_SHOWCENTURY) 
        grid.Add(self.PresDATE, 0) # proportion 0

        # Виконавець подання
        grid.Add(wx.StaticText(self, label="Вик.:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 5) # Додано відступ
        # Припустимо, вибір виконавців завантажується з БД
        executor_choices = ["", "ВП", "МПЗ", "Інші"] # Приклад
        self.submission_executor_ctrl = wx.Choice(self, choices=executor_choices) 
        grid.Add(self.submission_executor_ctrl, 0, wx.EXPAND | wx.ALIGN_CENTER_VERTICAL) # proportion 0, розтягування в FlexGridSizer

        # Рух (звідки/куди) - ПЕРЕМІЩЕНО СЮДИ
        grid.Add(wx.StaticText(self, label="Рух:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 5) # Додано відступ
        self.submission_movement_ctrl = wx.TextCtrl(self) 
        grid.Add(self.submission_movement_ctrl, 0, wx.EXPAND) # proportion 0, розтягування в FlexGridSizer

        # кнопка повторения последнего ввода
        self.movement_btn = wx.Button(self, label="⟳", size=(50, -1))
        self.movement_btn.Bind(wx.EVT_BUTTON, self.on_retry_executor_button_clicked) # Прив'язуємо обробник, якщо потрібно
        grid.Add(self.movement_btn, 0, wx.LEFT | wx.RIGHT | wx.ALIGN_CENTER_VERTICAL, 5)

        # Налаштування розтягування колонок
        grid.AddGrowableCol(1, 1) # Номер подання
        grid.AddGrowableCol(3, 0) # Дата - не розтягуємо
        grid.AddGrowableCol(5, 0) # Виконавець
        grid.AddGrowableCol(7, 1) # Рух (звідки/куди)

        sizer.Add(grid, 0, wx.EXPAND | wx.ALL, 3) 

        # Текст подання (RichTextCtrl) та Чекбокси - ТЕПЕР НА ОДНІЙ СТРОЦІ
        text_and_checkbox_sizer = wx.BoxSizer(wx.HORIZONTAL)

        # Текст подання
        text_and_checkbox_sizer.Add(wx.StaticText(self, label="Текст:"), 0, wx.ALIGN_TOP | wx.ALL, 3) 
        self.text_pres = rt.RichTextCtrl(self, size=(-1, 100), style=wx.TE_MULTILINE | wx.TE_RICH2) 
        text_and_checkbox_sizer.Add(self.text_pres, 1, wx.ALL | wx.EXPAND, 3) 

        # Чекбокси 
        checkbox_v_sizer = wx.BoxSizer(wx.VERTICAL) 

        self.submission_posthumous_checkbox = wx.CheckBox(self, label="- посмертно") 
        checkbox_v_sizer.Add(self.submission_posthumous_checkbox, 0, wx.ALL, 3)
        self.submission_posthumous_checkbox.Bind(wx.EVT_CHECKBOX, self.ctrl_submission_posthumous_checkbox)

        self.pres_denied_checkbox = wx.CheckBox(self, label="- відмовлено") 
        checkbox_v_sizer.Add(self.pres_denied_checkbox, 0, wx.ALL, 3)
        self.pres_denied_checkbox.Bind(wx.EVT_CHECKBOX, self.ctrl_pres_denied_checkbox)

        self.pres_unlink_meed_checkbox = wx.CheckBox(self, label="- відв'язати") 
        checkbox_v_sizer.Add(self.pres_unlink_meed_checkbox, 0, wx.ALL, 3)
        self.pres_unlink_meed_checkbox.Bind(wx.EVT_CHECKBOX, self.ctrl_pres_unlink_meed_checkbox)
        self.pres_unlink_meed_checkbox.Hide()

        text_and_checkbox_sizer.Add(checkbox_v_sizer, 0, wx.EXPAND | wx.LEFT, 10) 

        sizer.Add(text_and_checkbox_sizer, 1, wx.EXPAND | wx.ALL, 3) 

        return sizer


    # НАГОРОДЖЕННЯ
    def create_award_group(self):
        box = wx.StaticBox(self, label=" Деталі нагородження ")
        sizer = wx.StaticBoxSizer(box, wx.VERTICAL)

        # Вибір НАГОРОДЖЕННЯ
        meed_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.meed_sizer_label_id = wx.StaticText(self, label="ID:")
        meed_sizer.Add(self.meed_sizer_label_id, 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, border=3) # Додано StaticText        
        self.meed_ctrl = wx.ComboBox(self, choices=[""], style=wx.CB_READONLY) # Комбобокс вибора нагородження
        self.meed_ctrl.Bind(wx.EVT_COMBOBOX, self.fill_meed_fields)      
        
        self.meed_count_text = wx.StaticText(self, label="-") # Текст  кількості записів
        self.meed_count_text.SetMinSize((30, -1))  
        meed_sizer.Add(self.meed_ctrl, 2, wx.EXPAND)
        meed_sizer.Add(self.meed_count_text, flag=wx.ALIGN_CENTER_VERTICAL | wx.LEFT, border=10)

        sizer.Add(meed_sizer, 0, wx.EXPAND | wx.ALL, 3)

        # --- Селектор нагороди та кнопка дії (без зображення на кнопці) ---
        # Основне зображення буде відображатися окремо
        award_selector_sizer = wx.BoxSizer(wx.HORIZONTAL)

        self.award_label_info = wx.StaticText(self, label="Нагорода:")
        award_selector_sizer.Add(self.award_label_info, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 3)

        # Створюємо комбобокс, використовуючи попередньо завантажені назви нагород
        award_selector_sizer.Add(self.award_ctrl, 1, wx.LEFT | wx.RIGHT | wx.ALIGN_CENTER_VERTICAL, 3)
        self.award_ctrl.Bind(wx.EVT_COMBOBOX, self.on_award_selected)

        # Кнопка, що, виконує повтор вибору,
        self.retry_meed_btn = wx.Button(self, label="⟳") 
        self.retry_meed_btn.Bind(wx.EVT_BUTTON, self.on_retry_meed_button_clicked) # Прив'язуємо обробник, якщо потрібно
        self.retry_meed_btn.SetMinSize(wx.Size(50, -1)) 

        # Додаємо кнопку в award_selector_sizer
        award_selector_sizer.Add(self.retry_meed_btn, 0, wx.LEFT | wx.RIGHT | wx.ALIGN_CENTER_VERTICAL, 3)

        # Додаємо сайзер вибору нагороди до основного сайзера секції
        sizer.Add(award_selector_sizer, 0, wx.EXPAND | wx.ALL, 3)

        # --- Нижня частина з нагородами: поля введення та зображення ---
        bottom_sizer = wx.BoxSizer(wx.HORIZONTAL)
        left_grid = wx.FlexGridSizer(rows=4, cols=5, vgap=5, hgap=2)
        left_grid.AddGrowableCol(1) # Дозволяємо деяким стовпцям розтягуватися
        left_grid.AddGrowableCol(3)

        # Ряд 1
        self.decree_label = wx.StaticText(self, label="Рішення:")
        left_grid.Add(self.decree_label, 0, wx.ALIGN_CENTER_VERTICAL)
        self.award_basis_ctrl = wx.TextCtrl(self)
        left_grid.Add(self.award_basis_ctrl, 1, wx.EXPAND) # Використовуємо вагу 1, щоб дозволити розтягування

        self.date_decree_label = wx.StaticText(self, label="Дата (м/д/р):")
        left_grid.Add(self.date_decree_label, 0, wx.ALIGN_CENTER_VERTICAL)
        self.award_date_ctrl = wx.adv.DatePickerCtrl(self, style=wx.adv.DP_DROPDOWN | wx.adv.DP_SHOWCENTURY)
        left_grid.Add(self.award_date_ctrl, 1, wx.EXPAND) # Використовуємо вагу 1

        self.meed_dead_checkbox = wx.CheckBox(self, label="- посмертно")
        left_grid.Add(self.meed_dead_checkbox, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 5) # Додано відступ ліворуч

        # Ряд 2
        self.ConsingN_label = wx.StaticText(self, label="Накладна:")
        left_grid.Add(self.ConsingN_label, 0, wx.ALIGN_CENTER_VERTICAL)
        self.ConsingN = wx.TextCtrl(self)
        left_grid.Add(self.ConsingN, 1, wx.EXPAND)

        self.NumberMeed_label = wx.StaticText(self, label="Номер нагороди:")
        left_grid.Add(self.NumberMeed_label, 0, wx.ALIGN_CENTER_VERTICAL)
        self.NumberMeed = wx.TextCtrl(self)
        left_grid.Add(self.NumberMeed, 1, wx.EXPAND)

        # Спейсер для останнього стовпця Ряду 2
        self.spacer_ctrl0 = wx.Panel(self, size=(0, 0))
        left_grid.Add(self.spacer_ctrl0, 0, wx.EXPAND) # Додаємо з expand для коректного розташування


        # Ряд 3
        self.HandowerNAME_label = wx.StaticText(self, label="Вручено:")
        left_grid.Add(self.HandowerNAME_label, 0, wx.ALIGN_CENTER_VERTICAL)

        self.HandoverDATE = wx.adv.DatePickerCtrl(self, style=wx.adv.DP_DROPDOWN | wx.adv.DP_SHOWCENTURY)
        left_grid.Add(self.HandoverDATE, 1, wx.EXPAND)

        self.HandowerNAME = wx.TextCtrl(self)
        left_grid.Add(self.HandowerNAME, 1, wx.EXPAND)
        self.HandowerNAME.Bind(wx.EVT_TEXT, self.on_handower_name_changed)

        self.handower_btn = wx.Button(self, label="")
        left_grid.Add(self.handower_btn, 0, wx.ALIGN_CENTER_VERTICAL | wx.EXPAND) 

        # Чекбокс для протоколу видачі
        self.protok_handing = wx.CheckBox(self, label="- є протокол") 
        left_grid.Add(self.protok_handing, 0, wx.ALL, 5)

        # Ряд 4 - Пусті комірки для завершення структури сітки
        for _ in range(5): # 5 стовпців в останньому ряду
             left_grid.Add(wx.Panel(self, size=(0,0)), 0, wx.EXPAND)


        # --- Створюємо StaticBitmap для відображення зображення нагороди ---
        self.award_image_display = wx.StaticBitmap(self, size=(AWARD_IMAGE_SIZE, AWARD_IMAGE_SIZE))
        # Встановлюємо початковий bitmap (наприклад, стандартний або пустий)
        if self.default_award_bitmap and self.default_award_bitmap.IsOk():
             self.award_image_display.SetBitmap(self.default_award_bitmap)
        else:
             # Створюємо просту заглушку, якщо стандартний bitmap недоступний
             empty_fallback = wx.Bitmap(AWARD_IMAGE_SIZE, AWARD_IMAGE_SIZE)
             dc = wx.MemoryDC(empty_fallback)
             dc.SetBackground(wx.Brush(wx.LIGHT_GREY)); dc.Clear(); del dc
             self.award_image_display.SetBitmap(empty_fallback)


        # --- Додавання всього в bottom_sizer ---
        # Спочатку додаємо сітку контролів
        bottom_sizer.Add(left_grid, 1, wx.EXPAND | wx.RIGHT, 10) # Сітка займає основний простір

        # Додаємо відображення зображення праворуч від сітки
        bottom_sizer.Add(self.award_image_display, 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 5) 

        # Додаємо нижній сайзер (що містить сітку та зображення) до основного сайзера
        sizer.Add(bottom_sizer, 1, wx.ALL | wx.EXPAND, 3) 

        self.meed_row_items = [
            # Ряд 2
            self.ConsingN_label, self.ConsingN,
            self.NumberMeed_label, self.NumberMeed,
            self.spacer_ctrl0, 

            # Ряд 3
            self.HandowerNAME_label, self.HandoverDATE,
            self.HandowerNAME, self.handower_btn,
            self.protok_handing # чекбокс протоколу видачі нагороди
        ]

        self.group3_row_items = [
            self.meed_sizer_label_id,
            self.meed_ctrl,
            self.meed_count_text,
            self.award_ctrl, 
            self.award_label_info,
            self.retry_meed_btn,
            self.award_image_display,     

            # Контроли з Ряду 1 сітки:
            self.decree_label, # Мітка для Рішення
            self.award_basis_ctrl,
            self.date_decree_label,
            self.award_date_ctrl,
            self.meed_dead_checkbox,

            # Всі елементи з meed_row_items (Рядки 2 та 3 сітки)
            *self.meed_row_items
        ]

        self.meed_dead_checkbox.Bind(wx.EVT_CHECKBOX, self.ctrl_meed_dead_checkbox)

        return sizer

    # ФУТЕР
    def update_footer_message(self, message):
        if self.fut_place:
            self.last_message = message
            self.fut_place.SetLabel(self.last_message)

    def get_footer_message(self):
        return self.last_message

    # -------------- конец методов построения елементов интерфейса ---------------





    # -------------- методи ОЧИСТКИ елементов интерфейса ---------------

    def clear_person_data(self, event=None):
        self.person_search_results_ctrl.SetSelection(0) # Вибираємо нульовий елемент комбосписка візуально
        """Очищає всі поля на панелі KartkaPanel."""        
        if self.full_name_ctrl: self.full_name_ctrl.SetValue('')

        if self.inn: self.inn.SetValue('')
        if self.rank_ctrl: self.rank_ctrl.SetSelection(0)
        if self.unit_ctrl: self.unit_ctrl.SetSelection(0)
        if self.birtday: self.birtday.SetLabel("Дата народження: ---- -- --") 
        self.clear_submission_data() # Очищаємо подання
        if self.pres_count_text: self.pres_count_text.SetLabel('0')
        if self.submission_number_ctrl: self.submission_number_ctrl.SetValue('')
        if self.pres_ctrl: 
            self.pres_ctrl.SetSelection(wx.NOT_FOUND)
            self.pres_ctrl.Clear() 

        self.clear_meed_data() # Очищаємо нагороди
        if self.meed_count_text: self.meed_count_text.SetLabel('0')
        self.current_person_id = None # -- ID особи
        # Перевірка перед використанням search_result_person_display
        if self.current_loaded_person_display: self.current_loaded_person_display.SetLabel("Результат пошуку: Немає завантаженої особи")
        if self.delete_ctrl: self.delete_ctrl.SetSelection(0)
        self.search_query_text = None
        self.delete_mode_on = False
        self.update_footer_message(DEF_FUT_LABEL)


    def clear_submission_data(self):
        self.current_presentation_id = None        
        # Очищає поля, пов'язані з поданням.
        if self.PresDATE: self.PresDATE.SetValue(CURRENT_DATA)
        if self.submission_number_ctrl: self.submission_number_ctrl.SetValue('')
        if self.submission_executor_ctrl: self.submission_executor_ctrl.SetSelection(wx.NOT_FOUND)
        if self.submission_movement_ctrl: 
            self.submission_movement_ctrl.SetEditable(True)
            self.submission_movement_ctrl.SetValue('')
        if self.submission_posthumous_checkbox: self.submission_posthumous_checkbox.SetValue(False)
        if self.pres_denied_checkbox: 
            self.pres_denied_checkbox.SetValue(False)
            self.pres_denied_checkbox.Show()
        if self.text_pres: self.text_pres.SetValue('')
        if self.pres_unlink_meed_checkbox: 
            self.pres_unlink_meed_checkbox.SetValue(False)
            self.pres_unlink_meed_checkbox.Hide()

        # Manually trigger the handler for denied checkbox to ensure fields are hidden
        if hasattr(self, 'ctrl_pres_denied_checkbox') and callable(self.ctrl_pres_denied_checkbox):
             self.ctrl_pres_denied_checkbox(None)


    def clear_meed_data(self):
        self.current_meed_id = None
        # Очищає поля, пов'язані з нагородженням 
        if self.meed_ctrl:
            self.meed_ctrl.SetSelection(0)
            #self.meed_ctrl.Clear() 

        if self.award_ctrl and hasattr(self, 'award_search_helper') and self.award_search_helper:
            self._is_programmatic_award_change = True 
            try:
                self.award_search_helper.reset_search()
            finally:
                self._is_programmatic_award_change = False
        elif self.award_ctrl: 
            self.award_ctrl.SetValue("")
            self.award_ctrl.SetSelection(0)

        if self.award_basis_ctrl: self.award_basis_ctrl.SetValue('')
        if self.award_date_ctrl: self.award_date_ctrl.SetValue(CURRENT_DATA)
        if self.meed_dead_checkbox: self.meed_dead_checkbox.SetValue(False)
        if self.ConsingN: self.ConsingN.SetValue('')
        if self.NumberMeed: self.NumberMeed.SetValue('')
        if self.HandowerNAME: self.HandowerNAME.SetValue('')
        if self.handower_btn: 
            self.handower_btn.SetLabel("особисто")
            wx.CallAfter(lambda: self.handower_btn.Bind(wx.EVT_BUTTON, self.on_handower_btn_self))
        
        if self.protok_handing: self.protok_handing.SetValue(False)

        if self.HandoverDATE: self.HandoverDATE.SetValue(CURRENT_DATA)

        # Manually trigger the handler for meed posthumous checkbox
        if hasattr(self, 'ctrl_meed_dead_checkbox') and callable(self.ctrl_meed_dead_checkbox):
            self.ctrl_meed_dead_checkbox(None)

        # Clear the award image if you have a control for it (e.g., wx.StaticBitmap)
        self.on_award_selected(None)

    # -------------- конец методов ОЧИСТКИ елементов интерфейса ---------------



    # -------------- Методи ЗАПОЛНЕНИЯ ДАННИМИ елементов интерфейса ---------------
    def populate_and_load_hellou(self, show_hellou):
        self.show_hellou = int(show_hellou) # переменная для отключения /  включения режима показа посмертних награждений


    def populate_and_load_search_results(self, person_ids_list, source_data_award_and_presentation):
        # -------------- ПОЛУЧАЕМ результати ПОИСКА  ---------------
        self.latest_search_person_ids_list = person_ids_list # сохраняем данние по найденим особам из personality
        self.source_data_award_and_presentation = source_data_award_and_presentation # сохраняем данние по найденим особам из meed и presentation
        self.current_person_id = None # Скидаємо поточний ID особи
        self.clear_person_data() # Очищаємо всі поля, ВКЛЮЧАЮЧИ комбобокс результатів
        self.person_search_results_ctrl.Clear()  # Чистимо комбобокс

        if self.latest_search_person_ids_list: # Якщо список ID не порожній
            # 1. Підготовка даних для ComboBox з безпечною обробкою відсутнього ІПН
            person_names = []
            for item in self.latest_search_person_ids_list:
                # Перевірка, щоб уникнути IndexError, якщо структура не відповідає очікуванням
                if len(item) > 5:
                    full_name = item[3]
                    inn = item[5] # Може бути None
                    inn_part = ""
                    # Перевіряємо, чи ІПН не None і не порожній рядок після видалення пробілів
                    if inn is not None and str(inn).strip() != "":
                        inn_part = f" ({int(inn)})" # Просто додаємо як рядок                    
                    person_names.append(f"{full_name}{inn_part}")
                else:
                    # Обробка випадку, коли елемент списку має неочікувану структуру
                    person_names.append("Невідомо що") # Додаємо хоч щось

            # 2. Наповнюємо ComboBox
            self.person_search_results_ctrl.AppendItems(person_names)
            self.person_search_results_ctrl.Insert("", 0)

            # 3. Оновлюємо позначку кількості записів справа від комбобокса та у футері
            len_person_names_str = str(len(person_names)) # кількість знайдених записів
            message = f"Знайдено {len_person_names_str} осіб."
            self.person_result_count_text.SetLabel(len_person_names_str)
            self.update_footer_message(message) 

            # --- Вибираємо перший елемент та завантажуємо його дані ---
            if person_names:
                self.person_search_results_ctrl.SetSelection(1) # Вибираємо перший елемент візуально
                self.on_person_selected(None) # Передаємо None як об'єкт події, обробник отримує індекс з контролу
            else:
                self.person_search_results_ctrl.AppendItems(["Не знайдено"]) # Додаємо повідомлення "Не знайдено"
                self.person_search_results_ctrl.SetSelection(0) # Вибираємо "Не знайдено"
                self.person_result_count_text.SetLabel("0")
                self.update_footer_message("Пошук не знайшов осіб або дані недійсні.")

        else: # Якщо person_ids_list порожній
            self.person_search_results_ctrl.AppendItems(["Не знайдено"])
            self.person_search_results_ctrl.SetSelection(0) # Вибираємо "Не знайдено"
            self.person_result_count_text.SetLabel("0")
            self.update_footer_message("Заповніть поля, натисніть 'Зберегти'. Кнопки '⟳' повторюють останній ввід.")

        # --- Оновлюємо компонування ---
        self.Layout()
        self.SetupScrolling()


    def on_person_selected(self, event):
        # --- Метод: Обробник вибору особи ---
        # --- Метод заполняет поля согласно вибору из комбосписка self.person_search_results_ctrl ---
        index = self.person_search_results_ctrl.GetSelection()-1
        if index == wx.NOT_FOUND or index >= len(self.latest_search_person_ids_list):
            self.clear_person_data() #очистка 
            return

        person = self.latest_search_person_ids_list[index]
        self.current_person_id = int(person[0]) # id ВИБРАНОЙ особи
        self.search_query_text = str(person[3]) # ПІБ персони

        # 1 -------- Заполнение данних на ОСОБУ

        self.full_name_ctrl.SetValue(self.search_query_text) # ПІБ 
        self.update_footer_message(f"Дані на: {self.search_query_text} [{self.current_person_id}]")
        inn_value = person[5] # РНОКПП
        inn_value_str = ''
        if inn_value: 
            if inn_value is not None:
                try:
                    inn_value_str = str(int(inn_value))
                except (ValueError, TypeError):
                    # Якщо перетворення на int не вдалося, використовуємо строкове представлення або залишаємо порожнім
                    inn_value_str = str(inn_value) if str(inn_value).strip() != '' else ''
        
        self.inn.SetValue(inn_value_str) 
        # Викликаємо метод перевірки ІНН
        self.on_inn_focus_lost(None)

        rank = person[2] # Звання
        rank_to_find = str(rank) if rank is not None else ""
        rank_index = self.rank_ctrl.FindString(rank_to_find)
        if rank_index != wx.NOT_FOUND:
            self.rank_ctrl.SetSelection(rank_index)
        else:
            self.rank_ctrl.SetSelection(0)

        unit = person[1] # Підрозділ
        unit_to_find = str(unit) if unit is not None else ""
        unit_index = self.unit_ctrl.FindString(unit_to_find)
        if unit_index != wx.NOT_FOUND:
            self.unit_ctrl.SetSelection(unit_index)
        else:
            self.unit_ctrl.SetSelection(0)


        # --- Отримуємо пов'язані дані нагород та подань для ВИБРАНОЇ особи ---

        person_related_data_dict = None # Ініціалізуємо словник з даними по особі

        if isinstance(self.source_data_award_and_presentation, dict):
            person_related_data_dict = self.source_data_award_and_presentation.get(self.current_person_id) 

        if person_related_data_dict:
            # Отримуємо списки нагород та подань з цього словника.
            self.presentations_list = person_related_data_dict.get('presentations', [])
            self.meed_list = person_related_data_dict.get('meed', [])

            # ---- формуємо комбосписок СПИСОК ПОДАНЬ НА ОСОБУ ------------            
            self.pres_ctrl.Clear()  # Clear existing items in the ComboBox
            presentation_display_strings = []

            if self.presentations_list:
                for p_row in self.presentations_list:
                    if len(p_row) > 1:
                        reg_num = p_row[0]
                        reg_date = p_row[1]  
                        display_string = f"№{reg_num if reg_num is not None else 'б/н'} від {reg_date}"
                        presentation_display_strings.append(display_string)
                    else:
                        presentation_display_strings.append("Невідоме подання")

                # Добавляем пустую строку в начало
                presentation_display_strings.insert(0, "")
                self.pres_ctrl.AppendItems(presentation_display_strings)
                self.pres_ctrl.SetSelection(0)

                # кількість знайдених записів
                len_presentations_list_str = str(len(self.presentations_list)) 
                self.pres_count_text.SetLabel(len_presentations_list_str)

            else:
                self.pres_ctrl.AppendItems(["Немає подань"])
                self.pres_ctrl.SetSelection(0)
                self.pres_count_text.SetLabel('0')
                self.clear_submission_data()


            # ---- формуємо комбосписок СПИСОК НАГОРОДЖЕНЬ НА ОСОБУ -------------   
            self.meed_ctrl.Clear()  # Clear 
            meed_display_strings = [] 

            if self.meed_list:
                # Ітеруємося по словниках у списку self.meed_list
                for award_dict in self.meed_list: 

                    # Отримуємо оригінальний кортеж даних з ключа 'raw_data'
                    if 'raw_data' in award_dict and isinstance(award_dict['raw_data'], (list, tuple)) and len(award_dict['raw_data']) > 3:
                        raw_data_tuple = award_dict['raw_data']

                        reg_num = raw_data_tuple[3]
                        reg_date = raw_data_tuple[2]

                        # Формуємо рядок для відображення
                        # Враховуємо, що reg_num чи reg_date можуть бути None
                        reg_num_str = reg_num if reg_num is not None else 'б/н'
                        reg_date_str = reg_date if reg_date is not None else 'дата відсутня' # Можливо, потрібне форматування дати

                        display_string = f"№{reg_num_str} від {reg_date_str}"
                        meed_display_strings.append(display_string)
                   
                    else:
                        # Обробка випадку, якщо структура даних неочікувана
                        meed_display_strings.append("Некоректні дані нагородження")

                # Добавляем пустую строку в начало
                meed_display_strings.insert(0, "")
                self.meed_ctrl.AppendItems(meed_display_strings)
                self.meed_ctrl.SetSelection(0)

                # Кількість записів 
                len_meed_list_str = str(len(self.meed_list))
                self.meed_count_text.SetLabel(len_meed_list_str)
           
            else:
                self.meed_ctrl.AppendItems(["Немає нагороджень"])
                self.meed_ctrl.SetSelection(0)
                self.meed_count_text.SetLabel('0')
 

    def search_index_from_list(self, s_list=None, s_position_in_list=None, s_query=None):
        # метод поиска индекса элемента по значению
        _list = s_list if s_list is not None else []  # Захист від None 
        _position_in_list = s_position_in_list
        _query = s_query

        # Ітеруємо по елементах ВХІДНОГО СПИСКУ
        for index, item in enumerate(_list):
            if isinstance(item, dict):
                sequence_to_search = item.get('raw_data') 
                if isinstance(sequence_to_search, (list, tuple)) and len(sequence_to_search) > _position_in_list:
                    try:
                        if int(sequence_to_search[_position_in_list]) == int(_query):
                            return index
                    except (ValueError, TypeError):
                        pass # Продовжуємо до наступного елемента, якщо перетворення не вдалося

            elif isinstance(item, (list, tuple)):
                if len(item) > _position_in_list:
                    try:
                        if int(item[_position_in_list]) == int(_query):
                            return index + 1
                    except (ValueError, TypeError):
                        pass # Продовжуємо

        return -1 # Якщо нічого не знайдено після перевірки всіх елементів списку


    def fill_submission_fields(self, event=None, _list_index=None): 
        """---- метод подгружает данние ПОДАННЯ по вибраному елементу в self.pres_ctrl ---- """

        # Перевірка прапорця: якщо вже відбувається оновлення, виходимо
        if self._is_updating_fields:
            return

        # Встановлюємо прапорець для цього циклу оновлення
        self._is_updating_fields = True

        try:
            self.clear_submission_data()
            # Визначаємо 0-базовий індекс списку presentations_list
            if _list_index is not None: # Якщо викликано внутрішньо з переданим 0-базовим індексом
                list_index = int(_list_index) - 1
                combobox_index_to_set = list_index + 1
                if combobox_index_to_set >= 0 and combobox_index_to_set < self.pres_ctrl.GetCount():
                    self.pres_ctrl.SetSelection(combobox_index_to_set)

            else: # Якщо викликано подією зміни вибору в комбоспіску                
                combobox_index = self.pres_ctrl.GetSelection()
                self.meed_presentation_is_linked = False
                list_index = combobox_index - 1

            # Перевірка валідності 0-базового індексу списку
            if list_index < 0 or list_index > len(self.presentations_list): 
                # Поля вже очищені на початку
                return # Виходимо, якщо індекс недійсний

            # заповнюємо тільки вибране подання зі списку
            (
                registration,
                date_registration,
                name,
                rank,
                inn,
                unit,
                pres_id,
                id_meed,  
                worker,
                report,
                text_presentation,
                _
            ) = self.presentations_list[list_index]

            self.current_presentation_id = pres_id # id 

            # Заповнюємо поля подання
            self.submission_number_ctrl.SetValue(str(registration))
            
            # Обробка дати
            try:
                y, m, d = map(int, date_registration.split('-'))
                self.PresDATE.SetValue(wx.DateTime.FromDMY(d, m - 1, y))
            except Exception as e:
                self.update_footer_message(f"Помилка при встановленні дати подання: {e}")
            
            worker_map = {0: "ВП", 1: "МПЗ"}
            worker_val = worker_map.get(int(worker), "Інші")

            self.submission_executor_ctrl.SetStringSelection(worker_val)
            
            if report == "посмертно":
                self.submission_posthumous_checkbox.SetValue(True)
                self.ctrl_submission_posthumous_checkbox(None)
            else:
                self.submission_posthumous_checkbox.SetValue(False)
                self.submission_movement_ctrl.SetValue(str(report or ""))

            self.text_pres.SetValue(text_presentation or "")

            self.clear_meed_data() # Очищаємо поля нагородження

            # Якщо id_meed == 0 -> відмовлено    
            if id_meed is not None and id_meed != '':
                id_meed_numeric = int(id_meed)
                if id_meed_numeric == 0:
                    self.pres_denied_checkbox.SetValue(True)                    
                    self.ctrl_pres_denied_checkbox(None)
                    self.pres_unlink_meed_checkbox.SetValue(False)
                    self.pres_unlink_meed_checkbox.Hide()
                elif id_meed_numeric > 0:
                    self.pres_denied_checkbox.SetValue(False)
                    self.pres_denied_checkbox.Hide()
                    self.pres_unlink_meed_checkbox.Show()
                    # Вичисляємо 0-базовий індекс списку нагородження для автозагрузки
                    meed_list_index = self.search_index_from_list(self.meed_list, 13, id_meed)
                    if meed_list_index != -1: # Якщо знайдено пов'язане нагородження (0-базовий індекс)
                        self.fill_meed_fields(_list_index=meed_list_index)

            else:
                self.pres_denied_checkbox.SetValue(False) 
                self.pres_denied_checkbox.Show() 
                self.pres_unlink_meed_checkbox.SetValue(False)
                self.pres_unlink_meed_checkbox.Hide() 

        finally:
            # скидаємо прапоперць
            self._is_updating_fields = False



    def fill_meed_fields(self, event=None, _list_index=None): 
        """---- метод подгружает данние НАГОРОДЖЕННЯ по вибраному елементу в self.meed_ctrl ---- """
        self.meed_presentation_is_linked = False

        # Визначаємо 0-базовий індекс списку meed_list
        if _list_index is not None: # Якщо викликано внутрішньо з переданим 0-базовим індексом
            list_index = int(_list_index)
            combobox_index_to_set = list_index + 1
            if combobox_index_to_set >= 0 and combobox_index_to_set <= self.meed_ctrl.GetCount():
                self.meed_ctrl.SetSelection(combobox_index_to_set)

        else: # Якщо викликано подією зміни вибору в комбоспіску
            combobox_index = self.meed_ctrl.GetSelection()
            list_index = combobox_index - 1

        # Перевірка валідності 0-базового індексу списку
        if list_index < 0 or list_index >= len(self.meed_list):
            self.clear_meed_data() # Очищаємо поля, якщо індекс недійсний
            return # Виходимо, якщо індекс недійсний

        try: 
            item = self.meed_list[list_index]
            raw = item["raw_data"]  # Це кортеж значень
            handover_info = item.get("handover_info", "")
            (
                id_personality,
                award_id,
                award_date,
                decree,
                number_meed,
                handover_date,
                handover_person,
                consignment_note,
                name,
                rank,
                inn,
                unit,
                award_name,
                meed_id,
                dead,
                hto_name,
            ) = raw
            self.current_meed_id = meed_id # id meed
            
            # Заповнення полів
            if self.award_ctrl: self.award_ctrl.SetStringSelection(award_name)

            if self.award_basis_ctrl: self.award_basis_ctrl.SetValue(decree or "")

            # Обробка дати нагородження
            if award_date:
                try:
                    y, m, d = map(int, award_date.split('-'))
                    self.award_date_ctrl.SetValue(wx.DateTime.FromDMY(d, m - 1, y))
                except Exception as e:
                    self.update_footer_message(f"Помилка дати нагородження: {e}")

            # Manually trigger the handler for meed posthumous checkbox           
            if dead is not None: # Перевіряємо, чи взагалі є значення
                try:
                    if int(dead) == 1:
                        self.meed_dead_checkbox.SetValue(True)
                        self.ctrl_meed_dead_checkbox(None) 
                    else:
                        self.meed_dead_checkbox.SetValue(False)
                except (ValueError, TypeError):
                    self.meed_dead_checkbox.SetValue(False)
            else:
                self.meed_dead_checkbox.SetValue(False)

            if self.NumberMeed: self.NumberMeed.SetValue(number_meed or "")
            if self.ConsingN: self.ConsingN.SetValue(consignment_note or "")

            # Обробка дати вручення 
            if handover_date:
                try:
                    y, m, d = map(int, handover_date.split('-'))
                    self.HandoverDATE.SetValue(wx.DateTime.FromDMY(d, m - 1, y))
                except Exception as e:
                    self.update_footer_message(f"Помилка дати вручення: {e}")

            # Обробка получателя нагороди
            if hasattr(self, 'HandowerNAME'):
                try:
                    if "$" in handover_person:
                        handover_ = handover_person.split("$")[0]
                        self.HandowerNAME.SetValue(handover_)
                        # проверка на наявність протоколу видачі
                        self.protok_handing.SetValue(True)
                    else:
                        self.HandowerNAME.SetValue(handover_person)
                except Exception as e:
                    self.HandowerNAME.SetValue("")

            # Вичисляємо 0-базовий індекс списку подань
            # Припускаємо, що search_index_from_list повертає 0-базовий індекс або -1
            pres_list_index = self.search_index_from_list(self.presentations_list, 7, meed_id) 

            if pres_list_index != -1: # Якщо знайдено пов'язане подання (0-базовий індекс)
                self.fill_submission_fields(_list_index=pres_list_index)
                self.meed_presentation_is_linked = True
            else:
                self.clear_submission_data() # Очищаємо поля подання, якщо не знайдено пов'язаного
                self.pres_ctrl.SetSelection(0)

            wx.CallAfter(self.on_award_selected, None) # изображение награди
        finally:
            pass 


    """----- ВСПОМОГАТЕЛЬНИЕ МЕТОДИ  ------"""
    
    def on_retry_executor_button_clicked(self, event):
        """
        Отримує дані останнього запису з таблиці 'presentation' і заповнює
        відповідні поля на формі, використовуючи вже існуючий self.cursor,
        включаючи поля дат.
        """

        try:
            self.cursor.execute("SELECT registration, date_registration, worker, report FROM presentation ORDER BY rowid DESC LIMIT 1")
            clip_pres = self.cursor.fetchone()
            
            if clip_pres:
                submission_registration = clip_pres[0]
                submission_date = clip_pres[1]
                submission_executor = clip_pres[2]
                submission_movement = clip_pres[3]

                if self.submission_number_ctrl:
                    self.submission_number_ctrl.SetValue(str(submission_registration or "").strip())

                if self.submission_executor_ctrl:
                    worker_map = {0: "ВП", 1: "МПЗ"}
                    worker_val = worker_map.get(int(submission_executor), "інші")
                    self.submission_executor_ctrl.SetStringSelection(worker_val)

                if self.submission_movement_ctrl:
                    self.submission_movement_ctrl.SetValue(str(submission_movement or "").strip())

                if  self.PresDATE and submission_date:
                    try:
                        year, month, day = map(int, submission_date.split('-'))
                        wx_date = wx.DateTime(day, month - 1, year)
                        self.PresDATE.SetValue(wx_date)
                    except ValueError:
                        wx.MessageBox(f"Некоректний формат дати подання: {submission_date}", "Помилка дати", wx.ICON_WARNING)
                elif self.PresDATE:
                    self.PresDATE.SetValue(wx.DateTime.Today())

            else:
                wx.MessageBox("Немає даних про нагородження для заповнення з бази даних.", "Інформація", wx.OK | wx.ICON_INFORMATION)

        except Exception as e:
            wx.MessageBox(f"Помилка при заповненні полів Подання: {e}", "Помилка", wx.OK | wx.ICON_ERROR)
        finally:
            pass


    def on_retry_meed_button_clicked(self, event):
        """
        Отримує дані останнього запису з таблиці 'meed' і заповнює
        відповідні поля на формі, використовуючи вже існуючий self.cursor,
        включаючи поля дат.
        """

        try:
            self.cursor.execute("SELECT decree, consignment_note, id_award, date_decree, date_handover FROM meed ORDER BY rowid DESC LIMIT 1")
            clip_meed = self.cursor.fetchone()

            if clip_meed:
                decree_value = clip_meed[0]
                consignment_note_value = clip_meed[1]
                id_award_value = clip_meed[2]
                award_date_str = clip_meed[3]
                handover_date_str = clip_meed[4]

                if self.award_basis_ctrl:
                    self.award_basis_ctrl.SetValue(str(decree_value or "").strip())

                if self.ConsingN:
                    self.ConsingN.SetValue(str(consignment_note_value or "").strip())

                # перетворюємо ID на назву за допомогою self._award_id_to_name
                if self.award_ctrl and hasattr(self, '_award_id_to_name'):

                    award_name_from_id = self._award_id_to_name.get(id_award_value)
                    if award_name_from_id:
                        try:
                            self.award_ctrl.SetStringSelection(award_name_from_id)
                            self.on_award_selected(None)
                        except wx.wxAssertionError as e:
                            wx.MessageBox(f"Назви '{award_name_from_id}' немає у списку нагород ComboBox. Перевірте _loaded_award_names.",
                                          "Помилка вибору нагороди", wx.OK | wx.ICON_WARNING)
                    else:
                        wx.MessageBox(f"Не знайдено назви нагороди для ID: {id_award_value} у внутрішній мапі.",
                                      "Помилка", wx.OK | wx.ICON_ERROR)
                else:
                    wx.MessageBox("ComboBox для нагороди або мапа _award_id_to_name не ініціалізовані належним чином.",
                                  "Помилка ініціалізації", wx.OK | wx.ICON_ERROR)


                if self.award_date_ctrl and award_date_str:
                    try:
                        year, month, day = map(int, award_date_str.split('-'))
                        wx_date = wx.DateTime(day, month - 1, year)
                        self.award_date_ctrl.SetValue(wx_date)
                    except ValueError:
                        wx.MessageBox(f"Некоректний формат дати нагородження: {award_date_str}", "Помилка дати", wx.ICON_WARNING)
                elif self.award_date_ctrl:
                    self.award_date_ctrl.SetValue(wx.DateTime.Today())


                if self.HandoverDATE and handover_date_str:
                    try:
                        year, month, day = map(int, handover_date_str.split('-'))
                        wx_date = wx.DateTime(day, month - 1, year)
                        self.HandoverDATE.SetValue(wx_date)
                    except ValueError:
                        wx.MessageBox(f"Некоректний формат дати вручення: {handover_date_str}", "Помилка дати", wx.ICON_WARNING)
                elif self.HandoverDATE:
                    self.HandoverDATE.SetValue(wx.DateTime.Today())

            else:
                wx.MessageBox("Немає даних про нагородження для заповнення з бази даних.", "Інформація", wx.OK | wx.ICON_INFORMATION)

        except Exception as e:
            wx.MessageBox(f"Помилка при заповненні полів Нагородження: {e}", "Помилка", wx.OK | wx.ICON_ERROR)
        finally:
            pass


    def on_handower_name_changed(self, event):
        """ управление кнопкой handower_btn """
        value = self.HandowerNAME.GetValue().strip()
        if len(value) > 3:
            self.handower_btn.SetLabel("уточнити")
            self.handower_btn.Bind(wx.EVT_BUTTON, self.on_handower_btn_select) 
        else:
            self.handower_btn.SetLabel("особисто")
            self.handower_btn.Bind(wx.EVT_BUTTON, self.on_handower_btn_self) 
        self.Layout()


    def on_handower_btn_select(self, event):
        name = self.HandowerNAME.GetValue().strip()
        search_window = SearchFrame(self.conn, self.cursor, initial_query=name, target_field=self.HandowerNAME)
        search_window.Centre()
        search_window.Show()


    def on_handower_btn_self(self, event):
            """ Метод вставляє ID поточної особи у поле "Вручено (ім'я)". """
            if self.current_person_id is not None:
                person_id_str = str(self.current_person_id)
                self.HandowerNAME.SetValue(person_id_str)


    def on_award_selected(self, event):
        """  ВСТАНОВЛЮЄМО КАРТИНКУ НАГОРОДИ  """
        # Активуємо прапорець, щоб хелпер ігнорував зміну тексту, 
        # яка зараз відбудеться через вибір елемента
        self._is_programmatic_award_change = True
        
        try:
            selected_index = self.award_ctrl.GetSelection()
            selected_award_name = self.award_ctrl.GetString(selected_index)
            self.selected_award_id = None # Скидаємо

            image_blob = None # Змінна для зберігання BLOB зображення
            found_award_details = None # Для перевірки, чи знайшли нагороду в awards_data

            # Шукаємо BLOB зображення, якщо вибрано валідну назву нагороди
            if selected_award_name and selected_award_name not in [""]:

                if self.awards_data:
                    # Проходимо по всіх категоріях рангів у awards_data
                    for ranking_desc, award_dict in self.awards_data.items():
                        # Перевіряємо, чи внутрішній словник award_dict не порожній і чи містить нашу назву як ключ
                        if award_dict and selected_award_name in award_dict:
                            found_award_details = award_dict[selected_award_name]
                            self.selected_award_id = award_dict[selected_award_name]["award_id"]
                            # Отримуємо BLOB зображення за ключем "image"
                            image_blob = found_award_details.get("image") # .get безпечніше, поверне None якщо "image" немає
                            break # Зупиняємо перебір категорій, оскільки нагороду знайдено
        
            bitmap_to_set = None # Bitmap, який буде встановлено 

            if image_blob:
                # Якщо BLOB зображення нагороди знайдено, завантажуємо його
                try:
                    if 'load_image_from_blob' in globals() and callable(load_image_from_blob):
                         bitmap_to_set = load_image_from_blob(image_blob, max_dim=AWARD_IMAGE_SIZE)
                         if not (bitmap_to_set and bitmap_to_set.IsOk()):
                             bitmap_to_set = None # Якщо Bitmap невалідний, переходимо до стандартного
                    else:
                         bitmap_to_set = None # Якщо функція недоступна, переходимо до стандартного

                except Exception as e:
                    bitmap_to_set = None # У випадку винятку, переходимо до стандартного

            # Якщо bitmap_to_set все ще None 
            if bitmap_to_set is None:
                 if self.default_award_bitmap and self.default_award_bitmap.IsOk():
                      bitmap_to_set = self.default_award_bitmap
                 else:
                      # Абсолютний fallback: порожній Bitmap
                      empty_fallback = wx.Bitmap(AWARD_IMAGE_SIZE, AWARD_IMAGE_SIZE)
                      dc = wx.MemoryDC(empty_fallback)
                      dc.SetBackground(wx.Brush(wx.RED)); dc.Clear(); del dc
                      bitmap_to_set = empty_fallback

            if self.award_image_display: # Перевіряємо, чи контрол існує
                self.award_image_display.SetBitmap(bitmap_to_set)

            self.Layout() 

        finally:
            # скидаємо прапорець через CallAfter, 
            # щоб він залишався True, поки подія тексту повністю не обробиться
            wx.CallAfter(self._reset_programmatic_flag)
    
        if event:
            event.Skip()

    def _reset_programmatic_flag(self):
        self._is_programmatic_award_change = False

    # Функции обработки чекбоксов 
    def ctrl_meed_dead_checkbox(self, event):
        is_checked = self.meed_dead_checkbox.IsChecked()
        if (self.show_hellou is not None and self.show_hellou < 2):
            for item in self.meed_row_items:
                item.Show(not is_checked)
        self.Layout()


    def ctrl_pres_denied_checkbox(self, event):
        is_checked = self.pres_denied_checkbox.IsChecked()
        # Тут ви приховуєте елементи з self.group3_row_items
        for item in self.group3_row_items:
             # Додаємо перевірку item, бо в списках можуть бути None, якщо елемент не створено
             if item:
                item.Show(not is_checked)

        if is_checked:
            if hasattr(self, 'decree_label') and self.decree_label: # Додаємо перевірку
                 self.decree_label.SetLabel("У задоволенні подання відмовлено")
        else:
            if hasattr(self, 'decree_label') and self.decree_label: # Додаємо перевірку
                 self.decree_label.SetLabel("Рішення:")

        self.Layout()


    def ctrl_submission_posthumous_checkbox(self, event):
        is_checked = self.submission_posthumous_checkbox.IsChecked()
        if is_checked:
            self.submission_movement_ctrl.SetValue(str(""))
            self.submission_movement_ctrl.SetEditable(False)
        else:
            self.submission_movement_ctrl.SetEditable(True)


    def ctrl_pres_unlink_meed_checkbox(self, event):
        is_checked = self.pres_unlink_meed_checkbox.IsChecked()
        if is_checked:
            self.update_footer_message("Подання буде відв'язано від нагороди після збереження")
        self.Layout()


    def refresh_data_after_change_setuptab(self, new_data_rank_ctrl = None,  new_data_unit_ctrl = None):
        """ обновляем комбосписки после изменения в панели НАСТРОЙКИ """
        # 1. Очищаем текущие элементы
        self.rank_ctrl.Clear()
        self.unit_ctrl.Clear()

        # 2. Добавляем новые элементы
        if new_data_unit_ctrl:
            self.unit_ctrl.AppendItems(new_data_unit_ctrl[2:])
        if new_data_rank_ctrl: 
            self.rank_ctrl.AppendItems(new_data_rank_ctrl[2:])


    def _load_award_data(self):
        try:
            if self.cursor:
                # Завантажуємо дані нагород
                try:
                    self.awards_data = get_treedata(self.cursor)

                except Exception as e:
                    self.awards_data = {}
                    wx.MessageBox(f"Помилка завантаження даних нагород: {e}\nСписок нагород може бути неповним або порожнім.", "Помилка БД", wx.OK | wx.ICON_WARNING)

                # 3. Витягуємо назви нагород для комбобокса
                temp_award_names = []
                self._award_id_to_name = {} # Ініціалізуємо словник для перетворення ID в назву

                if self.awards_data:
                    for ranking_desc, award_dict in self.awards_data.items():
                        if award_dict:
                            for award_name, details in award_dict.items():
                                temp_award_names.append(award_name)
                                self._award_id_to_name[details["award_id"]] = award_name

                unique_award_names = list(set(temp_award_names))
                unique_award_names.sort()
                self._loaded_award_names = [""] + unique_award_names

                # Перевіряємо, чи award_ctrl вже існує
                if not hasattr(self, 'award_ctrl') or not self.award_ctrl:
                    # Якщо не існує, створюємо його (це відбудеться лише при першому виклику)
                    self.award_ctrl = wx.ComboBox(self, choices=self._loaded_award_names, style=wx.CB_DROPDOWN)
                    self.award_ctrl.Bind(wx.EVT_COMBOBOX, self.on_award_selected) # Прив'язуємо обробник подій
                    # Також створюємо ComboSearchHelper лише один раз
                    self.award_search_helper = ComboSearchHelper(self.award_ctrl, kartka_panel_instance=self)
                    #self.award_search_helper = ComboSearchHelper(self.award_ctrl)
                else:
                    # Якщо вже існує, просто оновлюємо його елементи
                    self.award_ctrl.Clear()
                    self.award_ctrl.AppendItems(self._loaded_award_names)
                    self.award_ctrl.SetSelection(-1) # Скинути вибір

                # Оновлюємо дані в ComboSearchHelper, незалежно від того, чи він щойно створений чи ні
                if hasattr(self, 'award_search_helper') and self.award_search_helper:
                    self.award_search_helper.set_items(self._loaded_award_names)

            else:
                # Обробка випадку, коли курсор не був створений
                self._loaded_award_names = ["(Помилка завантаження)"]
                wx.MessageBox("Курсор бази даних не був ініціалізований.", "Помилка", wx.OK | wx.ICON_ERROR)

        except Exception as e:
            # Загальна обробка помилок завантаження даних
            self._loaded_award_names = ["(Помилка завантаження)"]
            wx.MessageBox(f"Загальна помилка при завантаженні даних про нагороди: {e}", "Помилка", wx.OK | wx.ICON_ERROR)

    def _update_award_combobox(self):
        self._load_award_data() # Це призведе до перезавантаження даних та оновлення комбобокса
        # Після оновлення даних та комбобокса, можливо, потрібно оновити компонування
        if hasattr(self, 'Layout'):
            self.Layout()
        if hasattr(self, 'SetupScrolling'):
            self.SetupScrolling()

    def create_buttons(self):
        # 1. Змінюємо орієнтацію sizer'а на ВЕРТИКАЛЬНУ
        button_v_sizer = wx.BoxSizer(wx.VERTICAL)

        square_dim = 85 #  розмір 

        s_choise_delete_ctrl = ["⌦    видалити", "Особу", "Подання", "Нагородження"]        
        self.delete_ctrl = wx.ComboBox(self, choices=s_choise_delete_ctrl, style=wx.CB_READONLY) 
        self.delete_ctrl.SetSelection(0)
        self.delete_ctrl.SetMinSize((square_dim, -1))
        self.delete_ctrl.Bind(wx.EVT_COMBOBOX, self.select_delete_mode)

        save_btn = wx.Button(self, label="ЗБЕРЕГТИ")
        save_btn.Bind(wx.EVT_BUTTON, self.on_save) 
        clear_btn = wx.Button(self, label="ОЧИСТИТИ")
        clear_btn.Bind(wx.EVT_BUTTON, self.clear_person_data) 

        # Встановлюємо мінімальний розмір для кожної кнопки, щоб вони були квадратними
        save_btn.SetMinSize((square_dim, square_dim))
        clear_btn.SetMinSize((square_dim, square_dim))

        button_v_sizer.Add(self.delete_ctrl, 0, wx.ALL, 5)
        button_v_sizer.Add(save_btn, 0, wx.ALL | wx.EXPAND, 5)
        button_v_sizer.Add(clear_btn, 0, wx.ALL | wx.EXPAND, 5)

        return button_v_sizer

    def on_inn_focus_lost(self, event):
        # --- Метод для обробки ІНН ---
        value = self.inn.GetValue()
        
        # Викликаємо is_valid_INN і зберігаємо результат (дату народження або повідомлення про помилку)
        birth_date_or_error = is_valid_INN(value)
        
        if hasattr(self, 'birtday') and self.birtday:
            # Перевіряємо, чи повернулося дійсне значення дати (не "")
            if birth_date_or_error != "":
                self.birtday.SetLabel(f"Дата народження: {birth_date_or_error}")
            else:
                self.birtday.SetLabel("Невірний РНОКПП")
                
        # Перевіряємо, чи event не є None, перш ніж викликати event.Skip()
        if event:
            event.Skip()

    # --- Допоміжні функції для видалення ---
    def select_delete_mode(self, event):
        """ виводит сообщение о режиме удаления в футер"""
        delete_mode = self.delete_ctrl.GetStringSelection().lower()
        self.update_footer_message(f"Видалити запис про {delete_mode}")


    def delete_personality(self):
        """
        Видаляє запис про особу та всі пов'язані подання і нагородження.
        Повертає True, якщо видалення пройшло успішно, інакше - False.
        """
        try:
            # Отримуємо ID всіх подань та нагород, пов'язаних з особою
            self.cursor.execute("SELECT id FROM presentation WHERE id_personality = ?", (self.current_person_id,))
            find_pres_ids = self.cursor.fetchall()

            self.cursor.execute("SELECT id FROM meed WHERE id_personality = ?", (self.current_person_id,))
            find_meed_ids = self.cursor.fetchall()

            # Формуємо повідомлення для користувача
            text_d_pres = f" подань ({len(find_pres_ids)});" if find_pres_ids else ""
            text_d_meed = f" нагороджень ({len(find_meed_ids)});" if find_meed_ids else ""
            
            if not find_pres_ids and not find_meed_ids:
                confirm_message = "Дійсно видалити запис про особу?"
            else:
                confirm_message = f"Знайдено{text_d_pres}{text_d_meed} - видалення запису про особу призведе до втрати цих записів. Продовжити?"

            # Запитуємо підтвердження видалення
            if wx.MessageBox(confirm_message, "Увага!", wx.OK | wx.CANCEL | wx.ICON_WARNING) == wx.CANCEL:
                return False # Користувач відмовився

            # Видаляємо всі подання, пов'язані з особою
            if find_pres_ids:
                placeholders = ','.join('?' for _ in find_pres_ids)
                self.cursor.execute(f"DELETE FROM presentation WHERE id IN ({placeholders})", tuple(row[0] for row in find_pres_ids))

            # Видаляємо всі нагороди, пов'язані з особою
            if find_meed_ids:
                placeholders = ','.join('?' for _ in find_meed_ids)
                self.cursor.execute(f"DELETE FROM meed WHERE id IN ({placeholders})", tuple(row[0] for row in find_meed_ids))

            # Видаляємо саму особу
            self.cursor.execute("DELETE FROM personality WHERE id = ?", (self.current_person_id,))
            return True

        except Exception as e:
            wx.MessageBox(f"Невідома помилка при видаленні особи: {e}", "Помилка", wx.OK | wx.ICON_ERROR)
            return False


    def delete_presentation(self):
        """
        Видаляє запис про подання. Якщо пов'язана нагорода існує, питає про її видалення.
        Повертає True, якщо видалення пройшло успішно, інакше - False.
        """
        try:
            # Шукаємо ID пов'язаної нагороди
            self.cursor.execute("SELECT id_meed FROM presentation WHERE id = ?", (self.current_presentation_id,))
            find_meed_id_result = self.cursor.fetchone()
            linked_meed_id = find_meed_id_result[0] if find_meed_id_result else None

            if linked_meed_id:
                # Шукаємо інформацію про нагороду (для перевірки "в натурі")
                self.cursor.execute("SELECT consignment_note, number_meed FROM meed WHERE id = ?", (linked_meed_id,))
                meed_info = self.cursor.fetchone()

                if meed_info and (meed_info[0] or meed_info[1]): # Якщо є consignment_note або number_meed
                    if wx.MessageBox("Знайдено запис про пов'язану нагороду, яка, можливо, існує в натурі. Видалити разом запис про нагороду?", "Увага!", wx.OK | wx.CANCEL | wx.ICON_WARNING) == wx.OK:
                        # Видаляємо пов'язану нагороду
                        self.cursor.execute("DELETE FROM meed WHERE id = ?", (linked_meed_id,))
                    # Якщо користувач обрав "Ні", нагорода залишиться, а подання все одно буде видалено.
                
            # Видаляємо подання
            self.cursor.execute("DELETE FROM presentation WHERE id = ?", (self.current_presentation_id,))
            return True

        except Exception as e:
            wx.MessageBox(f"Невідома помилка при видаленні подання: {e}", "Помилка", wx.OK | wx.ICON_ERROR)
            return False


    def delete_meed(self):
        """
        Видаляє запис про нагороду. Перевіряє наявність пов'язаного подання.
        Повертає True, якщо видалення пройшло успішно, інакше - False.
        """
        try:
            # Шукаємо пов'язане подання
            self.cursor.execute("SELECT id FROM presentation WHERE id_meed = ?", (self.current_meed_id,))
            find_pres_id_result = self.cursor.fetchone()
            linked_pres_id = find_pres_id_result[0] if find_pres_id_result else None

            # Шукаємо нагороду "в натурі" (за наявністю consignment_note або number_meed)
            self.cursor.execute("SELECT consignment_note, number_meed FROM meed WHERE id = ?", (self.current_meed_id,))
            meed_info = self.cursor.fetchone()

            if meed_info and (meed_info[0] or meed_info[1]): # Якщо є consignment_note або number_meed
                if wx.MessageBox("Нагорода, можливо, існує в натурі. Все одно видалити?", "Увага!", wx.OK | wx.CANCEL | wx.ICON_WARNING) == wx.CANCEL:
                    # Якщо користувач відмовився видаляти нагороду
                    if linked_pres_id:
                        wx.MessageBox("Для того, щоб відв'язати нагороду від подання без видалення, виберіть пункт 'нове нагородження' і натисніть 'Зберегти'", "Довідка.", wx.OK | wx.ICON_INFORMATION)
                    return False

            # Видаляємо нагороду
            self.cursor.execute("DELETE FROM meed WHERE id = ?", (self.current_meed_id,))
            
            # Якщо пов'язане подання існує, пропонуємо його видалити або відв'язати
            if linked_pres_id:
                confirm_msg = f"Видалити пов'язане подання {linked_pres_id}? Якщо ні, подання перейде в категорію 'у залишку'."
                if wx.MessageBox(confirm_msg, "Увага!", wx.OK | wx.CANCEL | wx.ICON_QUESTION) == wx.OK:
                    self.cursor.execute("DELETE FROM presentation WHERE id = ?", (linked_pres_id,))
                else:
                    # Відв'язуємо подання (id_meed = NULL)
                    self.cursor.execute("UPDATE presentation SET id_meed = NULL WHERE id = ?", (linked_pres_id,))
            
            return True

        except Exception as e:
            wx.MessageBox(f"Невідома помилка при видаленні нагороди: {e}", "Помилка", wx.OK | wx.ICON_ERROR)
            return False

    # -------------------------------------------------

    def refresh_logo(self):
        """
        Перезавантажує логотип з бази даних через settings_manager
        і оновлює відображення self.award_image_display.
        """
        try:
            # Перезавантажуємо налаштування, щоб отримати найновіший BLOB логотипу
            with self.conn: # Використовуємо існуюче підключення до БД
                cursor_for_refresh = self.conn.cursor()
                self.settings_manager.load_settings(cursor_for_refresh) # Перезавантажуємо всі налаштування
                cursor_for_refresh.close() # Закриваємо тимчасовий курсор

            logo_blob = self.settings_manager.get_logo_blob()

            new_bitmap = None
            if logo_blob:
                new_bitmap = load_image_from_blob(
                    logo_blob,
                    max_dim=AWARD_IMAGE_SIZE
                )
            if new_bitmap and new_bitmap.IsOk():
                self.default_award_bitmap = new_bitmap # Оновлюємо стандартний bitmap
                self.award_image_display.SetBitmap(new_bitmap)
            else:
                # Якщо логотип відсутній або помилковий, повертаємось до заглушки
                fallback_bitmap = wx.Bitmap(AWARD_IMAGE_SIZE, AWARD_IMAGE_SIZE)
                dc = wx.MemoryDC(fallback_bitmap)
                dc.SetBackground(wx.Brush(wx.SystemSettings.GetColour(wx.SYS_COLOUR_3DFACE)))
                dc.Clear()
                del dc
                self.default_award_bitmap = fallback_bitmap
                self.award_image_display.SetBitmap(fallback_bitmap)

            self.award_image_display.Refresh() # Примусове оновлення відображення
            self.Layout() # Перекомпонування, якщо розмір змістився

        except Exception as e:
            self.update_footer_message(f"Помилка оновлення логотипу в KartkaPanel: {e}")


    # -------------- методи ПОЛУЧЕНИЯ данних из елементов интерфейса --------------------

    def collect_ui_values(self):
        """ Збирає дані з усіх полів введення та вибору на панелі. Повертає словник """
        data = {
            'person': {},
            'submission': {},
            'award': {}
        }

        # --- Збір даних Особи ---

        # ID поточної особи
        data['person']['person_id'] = self.current_person_id

        # убираем пробели и меняем переводи строк на пробели 
        full_name = re.sub(r'\s+', ' ', self.full_name_ctrl.GetValue()).strip()

        # 1. Проверка на непустой ввод
        if not full_name:
            wx.MessageBox("Поле 'ПІБ' є обов'язковим для заповнення.", "Помилка введення", wx.OK | wx.ICON_ERROR)
            if hasattr(self, 'full_name_ctrl') and self.full_name_ctrl:
                self.full_name_ctrl.SetFocus()
            return

        # 2. Проверка на отсутствие цифр
        if any(char.isdigit() for char in full_name):
            wx.MessageBox("Поле 'ПІБ' не повинно містити цифр.", "Помилка введення", wx.OK | wx.ICON_ERROR)
            if hasattr(self, 'full_name_ctrl') and self.full_name_ctrl:
                self.full_name_ctrl.SetFocus()
            return

        # Для имени обычно достаточно букв, пробелов и дефисов, а также апострофов
        cyrillic_pattern = re.compile(r"^[А-Яа-яЄєІіЇїҐґ'\s-]+$")
        if not cyrillic_pattern.match(full_name):
            wx.MessageBox("Поле 'ПІБ' повинно містити лише кириличні літери, пробіли, дефіси та апострофи.", "Помилка введення", wx.OK | wx.ICON_ERROR)
            if hasattr(self, 'full_name_ctrl') and self.full_name_ctrl:
                self.full_name_ctrl.SetFocus()
            return
        
        data['person']['full_name'] = full_name

        if self.inn and int(self.delete_mode_on) != 1:
            inn = self.inn.GetValue().strip()            
            if not inn:
                wx.MessageBox("Поле 'РНОКПП' є обов'язковим для заповнення.", "Помилка введення", wx.OK | wx.ICON_ERROR)
                self.inn.SetFocus()
                return # Прекратить выполнение функции сохранения
            else:
                data['person']['inn'] = inn
            
        if self.birtday:
            data['person']['birth_date'] = self.birtday.GetLabel() 

        if self.rank_ctrl:
            # Зберігаємо обране звання як текст
            data['person']['rank'] = self.rank_ctrl.GetStringSelection()

        if self.unit_ctrl:
            # Зберігаємо обраний підрозділ як текст
            data['person']['unit'] = self.unit_ctrl.GetStringSelection()

        # --- Збір даних Подання ---

        if self.submission_number_ctrl:
            data['submission']['submission_number'] = self.submission_number_ctrl.GetValue()

        # Отримуємо значення дати, перевіряючи його валідність
        if self.PresDATE and self.PresDATE.GetValue().IsValid():
            # Зберігаємо дату як wx.DateTime об'єкт. Конвертація в формат БД
            # має відбуватися у функції збереження.
            data['submission']['submission_date'] = self.PresDATE.GetValue()
        else:
             data['submission']['submission_date'] = None # Або інше значення для недійсної дати

        if self.submission_executor_ctrl:
            worker = self.submission_executor_ctrl.GetStringSelection()
            if not worker and data['submission']['submission_number']:
                wx.MessageBox("Поле 'Виконавець' є обов'язковим для заповнення.", "Помилка введення", wx.OK | wx.ICON_ERROR)
                self.submission_executor_ctrl.SetFocus()
                return # Прекратить выполнение функции сохранения
            else:
                data['submission']['submission_executor'] = worker
        
        if self.submission_movement_ctrl:
            data['submission']['submission_movement'] = self.submission_movement_ctrl.GetValue()

        if self.text_pres:
            data['submission']['submission_text'] = self.text_pres.GetValue()

        if self.submission_posthumous_checkbox:
            data['submission']['submission_posthumous'] = self.submission_posthumous_checkbox.GetValue()
       
        if self.pres_denied_checkbox:
            data['submission']['submission_denied'] = self.pres_denied_checkbox.GetValue()
        
        if self.pres_unlink_meed_checkbox:
            data['submission']['submission_unlink_meed'] = self.pres_unlink_meed_checkbox.GetValue()


        # --- Збір даних Нагородження ---

        if self.award_ctrl:
            data['award']['award_name'] = self.award_ctrl.GetStringSelection() # Назва нагороди (рядок)

        if self.award_basis_ctrl:
            data['award']['award_basis'] = self.award_basis_ctrl.GetValue() # Рішення (підстава)

        if self.award_date_ctrl and self.award_date_ctrl.GetValue().IsValid():
            data['award']['award_date'] = self.award_date_ctrl.GetValue() # Дата нагородження (wx.DateTime)
        else:
            data['award']['award_date'] = None

        if self.meed_dead_checkbox:
            data['award']['meed_dead'] = self.meed_dead_checkbox.GetValue() # Чекбокс "Посмертно" для нагороди

        if self.ConsingN:
            data['award']['consignment_number'] = self.ConsingN.GetValue() # Накладна

        if self.NumberMeed:
            data['award']['award_number'] = self.NumberMeed.GetValue() # Номер нагороди

        if self.HandoverDATE and self.HandoverDATE.GetValue().IsValid():
            data['award']['handover_date'] = self.HandoverDATE.GetValue() # Вручено (дата) (wx.DateTime)
        else:
            data['award']['handover_date'] = None

        if self.HandowerNAME:
            data['award']['handover_name'] = self.HandowerNAME.GetValue() # Вручено (ім'я)

        if self.protok_handing:
            data['award']['protok_handing'] = self.protok_handing.GetValue() # Чекбокс протоколу видачі

        return data


    def on_save(self, event):
        """Обробник кнопки "Зберегти"."""
        self.delete_mode_on = self.delete_ctrl.GetSelection() # ВАЖНО расположение визовов функций именно так
        collected_data = self.collect_ui_values()
        
        if collected_data is None: 
            # странная ошибка. виход
            return

        # Прапор для відстеження, чи була операція видалення успішною
        deletion_successful = False
        update_ui_after_deletion = False # Прапор для оновлення UI після видалення


        """ --------------- режим видалення -------------------- """
        if self.delete_mode_on: 
            #  
            if int(self.delete_mode_on) == 1: # Видалити особу
                if self.current_person_id:
                    deletion_successful = self.delete_personality()
                    if deletion_successful:
                        # При видаленні особи, скидаємо всі ID
                        self.current_person_id = None
                        self.current_presentation_id = None
                        self.current_meed_id = None
                        update_ui_after_deletion = 1 # Повне оновлення UI
                else:
                    wx.MessageBox("Не вибрано жодної особи для видалення.", "Інформація", wx.OK | wx.ICON_INFORMATION)

            elif int(self.delete_mode_on) == 2: # Видалити подання
                if self.current_presentation_id:
                    deletion_successful = self.delete_presentation()
                    if deletion_successful:
                        self.current_presentation_id = None
                else:
                    wx.MessageBox("Не вибрано жодного подання для видалення.", "Інформація", wx.OK | wx.ICON_INFORMATION)

            elif int(self.delete_mode_on) == 3: # Видалити нагороду
                if self.current_meed_id:
                    deletion_successful = self.delete_meed()
                    if deletion_successful:
                        self.current_meed_id = None
                else:
                    wx.MessageBox("Не вибрано жодної нагороди для видалення.", "Інформація", wx.OK | wx.ICON_INFORMATION)
            
            if deletion_successful:
                try:
                    self.conn.commit()
                except Exception as e:
                    self.conn.rollback()
                    wx.MessageBox(f"Загальна помилка збереження: {e}", "Помилка", wx.OK | wx.ICON_ERROR)
                    return

                # оновлення UI
                self.delete_ctrl.SetSelection(0) 
                self.trigger_search_in_tab1_and_load_results()
                if update_ui_after_deletion == 1:
                    self.person_search_results_ctrl.Clear() 
                    self.person_result_count_text.SetLabel("0")
                    self.clear_person_data()

                self.update_footer_message("Видалення успішно виконано!")

            else:
                self.update_footer_message("Видалення скасовано або виникла помилка.")


            """ ---------------- режим изменения / создания записей ------------------------ """
        elif collected_data.get('person') and collected_data['person'].get("full_name"):
            # 
            person_data = collected_data['person']
            full_name = person_data.get("full_name")
            unit = person_data.get("unit")
            rank = person_data.get("rank")

            id_personality = self.current_person_id

            date_birth_wx = person_data.get("birth_date")
            date_birth = None
            if "Дата народження:" in date_birth_wx:
                date_birth = date_birth_wx.split(": ")[1]
                if date_birth == "" or not date_birth:
                    date_birth = None
            else:
                date_birth = None

            # --- Обробка та валідація ІНН ---
            inn_from_ui = person_data.get("inn")
            inn = None # Значення, яке буде збережено в базу даних

            # 1. Перетворюємо в рядок і очищаємо від пробілів
            inn_str_raw = str(inn_from_ui).strip() if inn_from_ui is not None else ""

            if inn_str_raw: # Якщо після очищення рядок ІНН не порожній
                # Спершу перевіряємо валідність використовуючи метод is_valid_INN.
                # is_valid_INN очікує, що рядок містить лише цифри.
                # Якщо is_valid_INN повертає False, це може бути через нецифрові символи
                # або неправильну контрольну суму (якщо введені лише цифри).

                # Витягуємо лише цифри з введеного ІНН
                inn_digits_only = re.sub(r'\D', '', inn_str_raw)

                # is_valid_INN повертає дату або порожній рядок
                # Якщо повертається порожній рядок, значить ІНН недійсний.
                validation_result = is_valid_INN(inn_digits_only) 

                if validation_result != "": 
                    # ІНН валідний (і за довжиною, і за контрольною сумою), зберігаємо як число
                    inn = int(inn_digits_only)
                else:
                    # ІНН не пройшов валідацію.
                    # Повідомляємо користувача та пропонуємо вибір.
                    msg_body = (
                        f"РНОКПП '{inn_str_raw}' некоректний. Він має бути 10-значним числом.\n\n"
                        f"Знайдено цифри: '{inn_digits_only}'.\n"
                        f"Бажаєте зберегти РНОКПП як '{inn_digits_only}' (тільки цифри), незважаючи на недійсність?"
                    )
                    dialog = wx.MessageDialog(
                        self,
                        msg_body,
                        "Некоректний РНОКПП",
                        wx.YES_NO | wx.ICON_WARNING | wx.CENTRE
                    )
                    response = dialog.ShowModal()
                    dialog.Destroy()

                    if response == wx.ID_YES:
                        # Користувач обрав "Так" (зберегти лише цифри, навіть якщо не валідний за контрольною сумою)
                        if inn_digits_only:
                            # Перевіряємо, чи є взагалі цифри для збереження
                            inn = int(inn_digits_only)
                    else:
                        # Користувач обрав "Ні" (не зберігати взагалі)
                        self.update_footer_message("Збереження скасовано через некоректний РНОКПП.")
                        return # Зупиняємо процес збереження

            else:
                # ІНН порожній, дозволяємо зберегти його як NULL
                inn = None # Використовуємо 'inn' замість 'inn_to_save'

            try:
                if self.current_person_id:
                    query = """
                        UPDATE personality
                        SET unit = ?, rank = ?, name = ?, date_birth = ?, inn = ?
                        WHERE id = ?
                    """
                    self.cursor.execute(query, (unit, rank, full_name, date_birth, inn, self.current_person_id))
                else:
                    query = """
                        INSERT INTO personality (unit, rank, name, date_birth, inn)
                        VALUES (?, ?, ?, ?, ?)
                    """
                    self.cursor.execute(query, (unit, rank, full_name, date_birth, inn))
                    self.current_person_id = self.cursor.lastrowid

            except Exception as e:
                self.conn.rollback()
                wx.MessageBox(f"Помилка при збереженні особи: {e}", "Помилка", wx.OK | wx.ICON_ERROR)
                return

            # --- Логика для таблицы 'presentation' (подання) ---
            id_meed_in_collected_data = None

            if collected_data.get('submission') and collected_data['submission'].get('submission_number'):
                presentation_data = collected_data['submission']

                text_presentation = presentation_data.get('submission_text')
                registration = presentation_data.get('submission_number')

                date_registration_wx = presentation_data.get('submission_date')
                date_registration = None
                if date_registration_wx and date_registration_wx.IsValid():
                    date_registration = date_registration_wx.FormatISODate()

                report = presentation_data.get('submission_movement')
                if presentation_data.get('submission_posthumous'):
                    report = "посмертно"

                worker_wx = presentation_data.get('submission_executor')
                worker = None
                worker_mapping = {"ВП": 0, "МПЗ": 1, "Інші": 2}
                worker = worker_mapping.get(worker_wx)
                # Логіка для зв'язування подання та нагороди
                if presentation_data.get('submission_denied'):
                    id_meed_in_collected_data = 0 # Відмовлено
                elif presentation_data.get('submission_unlink_meed'):
                    id_meed_in_collected_data = None # Відв'язати
                else:
                    id_meed_in_collected_data = self.current_meed_id # Зберігаємо існуючий зв'язок або None

                try:
                    if self.current_presentation_id:
                        query = """
                            UPDATE presentation
                            SET text_presentation = ?, registration = ?, date_registration = ?,
                                id_personality = ?, id_meed = ?, report = ?, worker = ?
                            WHERE id = ?
                        """
                        self.cursor.execute(query, (text_presentation, registration, date_registration,
                                                    self.current_person_id, id_meed_in_collected_data, report, worker,
                                                    self.current_presentation_id))
                    else:
                        query = """
                            INSERT INTO presentation (text_presentation, registration, date_registration,
                                                    id_personality, id_meed, report, worker)
                            VALUES (?, ?, ?, ?, ?, ?, ?)
                        """
                        self.cursor.execute(query, (text_presentation, registration, date_registration,
                                                    self.current_person_id, id_meed_in_collected_data, report, worker))
                        self.current_presentation_id = self.cursor.lastrowid
                        
                except Exception as e:
                    self.conn.rollback()
                    wx.MessageBox(f"Помилка при збереженні подання: {e}", "Помилка", wx.OK | wx.ICON_ERROR)
                    return

            # --- Логика для таблицы 'meed' (нагородження) ---
            if collected_data.get('award') and collected_data['award'].get('award_basis') and id_meed_in_collected_data != 0:
                meed_data = collected_data['award']

                date_decree_wx = meed_data.get('award_date')
                date_decree = None
                if date_decree_wx and date_decree_wx.IsValid():
                    date_decree = date_decree_wx.FormatISODate()

                id_award = self.selected_award_id
                decree = meed_data.get('award_basis')
                number_meed = meed_data.get('award_number')

                date_handover = None
                handover = meed_data.get('handover_name')
                if handover:
                    date_handover_wx = meed_data.get('handover_date')
                    if date_handover_wx and date_handover_wx.IsValid():
                        date_handover = date_handover_wx.FormatISODate()   

                consignment_note = meed_data.get('consignment_number')
                if number_meed in (None, "") and consignment_note not in (None, ""):
                    number_meed = "бн"

                dead = None
                if meed_data.get('meed_dead'):
                    dead = 1

                if meed_data.get('protok_handing'):
                    handover += "$"

                try:
                    if self.current_meed_id:
                        query = """
                            UPDATE meed
                            SET id_personality = ?, id_award = ?, date_decree = ?, decree = ?,
                                number_meed = ?, date_handover = ?, handover = ?,
                                consignment_note = ?, dead = ?
                            WHERE id = ?
                        """
                        self.cursor.execute(query, (self.current_person_id, id_award, date_decree, decree, number_meed,
                                                    date_handover, handover, consignment_note, dead,
                                                    self.current_meed_id))
                    else:
                        query = """
                            INSERT INTO meed (id_personality, id_award, date_decree, decree, number_meed,
                                            date_handover, handover, consignment_note, dead)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """
                        self.cursor.execute(query, (self.current_person_id, id_award, date_decree, decree, number_meed,
                                                    date_handover, handover, consignment_note, dead))

                        self.current_meed_id = self.cursor.lastrowid

                except Exception as e:
                    self.conn.rollback()
                    wx.MessageBox(f"Помилка при збереженні нагороди: {e}", "Помилка", wx.OK | wx.ICON_ERROR)
                    return

            # --- Завершення збереження ---
            try:
                self.conn.commit()
            except Exception as e:
                self.conn.rollback()
                wx.MessageBox(f"Загальна помилка збереження: {e}", "Помилка", wx.OK | wx.ICON_ERROR)
                return

            # --- Логіка прив'язування подання та нагороди (після успішного збереження) ---
            # 1 Якщо ми не в режимі видалення 
            # 2.Якщо не вибраний/і чекбокс/и відв'язування/відмови 
            # 3.Якщо є номер подання/нагородження
            link_dialog_was_shown = False
            if not self.delete_mode_on and \
                not self.pres_unlink_meed_checkbox.IsShown() and \
                not collected_data['submission']['submission_denied']:
                temp_link_dialog = LinkDialog(None, self.conn, self.cursor, initial_query=[self.current_person_id, self.current_meed_id, self.current_presentation_id])
                raw_results, label_str = temp_link_dialog._get_linkable_records(
                    self.current_person_id, self.current_presentation_id, self.current_meed_id
                )
                temp_link_dialog.Destroy() # Важливо знищити тимчасовий об'єкт

                if raw_results: # Тільки якщо є дані для прив'язки
                    initial_query = [self.current_person_id, self.current_meed_id, self.current_presentation_id]
                    link_frame = LinkDialog(
                        parent_panel=self,
                        conn=self.conn,
                        cursor=self.cursor,
                        initial_query=initial_query,
                        target_field=None
                    )
                    link_frame.Centre()
                    link_frame.Show()
                    link_dialog_was_shown = True

            if not link_dialog_was_shown:
                self.trigger_search_in_tab1_and_load_results()

            self.update_footer_message("Операція збереження завершена.")


    def trigger_search_in_tab1_and_load_results(self):
        search_id = self.current_person_id
        # виконати пошук у Tab1Panel для оновлення Картка
        fake_event = wx.CommandEvent() # Просто пустий CommandEvent
        self.search_panel.on_search_button(fake_event, search_id) # Запускаємо on_search_button в Tab1Panel

        latest_search_results, source_data_award_and_presentation = self.search_panel.get_latest_search_results()
        if latest_search_results:
            self.populate_and_load_search_results(latest_search_results, source_data_award_and_presentation)

# Кінець класу KartkaPanel


# класс пошуку і  вибору отримувача нагороди за прізвищем

class SearchFrame(wx.Frame):
    def __init__(self, conn, cursor, initial_query="", target_field=None):
        super(SearchFrame, self).__init__(None, title="Пошук отримувача", size=(600, 200)) 

        self.conn = conn
        self.cursor = cursor

        self.query = initial_query
        self.target_field = target_field  
        self.results_data = [] 

        panel = wx.Panel(self)
        vbox = wx.BoxSizer(wx.VERTICAL)

        self.combo = wx.ComboBox(panel, style=wx.CB_READONLY) 
        vbox.Add(self.combo, flag=wx.EXPAND | wx.ALL, border=10)

        self.label = wx.StaticText(panel, label="")
        vbox.Add(self.label, 0, flag=wx.EXPAND | wx.ALL, border=10)

        panel.SetSizer(vbox)

        self.combo.Bind(wx.EVT_COMBOBOX, self.on_select)

        if self.query:
            self.on_search(self.query) # Викликаємо метод пошуку


    def on_search(self, query_passed_as_event): 
        if not self.cursor:
            wx.MessageBox("Не вдалось підключитись до бази", "Помилка", wx.ICON_ERROR)
            return

        raw_results, stringTab1, imgList, counts_gid01, source_data = search_q(query_passed_as_event, self.cursor)
        label_str = ""
        if raw_results:
            # Оскільки ComboBox буде сортувати відображувані значення,
            # нам потрібно зберегти self.results_data у тому ж відсортованому порядку.

            # 1. Створюємо список пар: (рядок_для_відображення, оригінальний_рядок_даних)
            items_to_sort = []
            for row in raw_results:
                display_string = f"{row[3]} ({row[2]}, {row[1]})"
                items_to_sort.append((display_string, row))
            
            # 2. Сортуємо цей список за рядком для відображення (так само, як це зробить ComboBox)
            items_to_sort.sort(key=lambda x: x[0])
            
            # 3. Формуємо фінальний список для відображення та оновлюємо self.results_data
            final_display_values = [item[0] for item in items_to_sort]
            self.results_data = [item[1] for item in items_to_sort] 
            label_str = str(len(self.results_data))
            self.label.SetLabel(f"Знайдено: {label_str}")
            final_display_values.insert(0, "")
            self.results_data.insert(0, None)
            self.combo.Set(final_display_values)
            if final_display_values: # Додаткова перевірка, чи список не порожній після сортування
                self.combo.SetSelection(0) # Вибираємо перший елемент за замовчуванням
            self.combo.Show()
            self.Layout()
        else:
            self.results_data = [] # Очищаємо, якщо результатів немає
            self.combo.Clear()     # Очищаємо сам комбобокс
            self.combo.Hide()
            label_str = "Нічого не знайдено"
            self.label.SetLabel(label_str)
            self.Layout()


    def on_select(self, event):
        selected_string = self.combo.GetStringSelection()
        selected_index = self.combo.GetSelection()

        if selected_index != wx.NOT_FOUND and self.results_data:
            # Отримуємо повні дані вибраного елемента
            selected_data_row = self.results_data[selected_index]

            # Перевіряємо, чи selected_data_row не порожній і має хоча б один елемент
            if selected_data_row and len(selected_data_row) > 0:
                value_to_set = str(selected_data_row[0]) 
            else:
                value_to_set = "" 

            if self.target_field:
                self.target_field.SetValue(value_to_set)

            # Якщо вікно має закриватися після вибору:
            self.Close() 

if __name__ == "__main__":
    app = wx.App()
    frame = SearchFrame(conn, cursor)  # передаём conn и cursor
    frame.Centre()
    frame.Show()
    app.MainLoop()

# кінець классу пошуку і  вибору отримувача нагороди за прізвищем


# -------------- класс прив'язки подання до нагороди при збереженні даних 

class LinkDialog(wx.Frame):
    def __init__(self, parent_panel, conn, cursor, initial_query=None, target_field=None):
        super(LinkDialog, self).__init__(None, title="Прив'язка до запису", size=(600, 250),
                                         style=wx.DEFAULT_FRAME_STYLE & ~wx.CLOSE_BOX) 
        self.conn = conn
        self.cursor = cursor
        self.parent_panel = parent_panel
        # Переконайтеся, що initial_query - це список, і він має 3 елементи
        self.query_ids = initial_query if isinstance(initial_query, list) and len(initial_query) == 3 else [None, None, None]
        self.person_id = self.query_ids[0]
        self.meed_id = self.query_ids[1]
        self.presentation_id = self.query_ids[2]

        self.target_field = target_field
        self.results_data = [] # Зберігатиме оригінальні дані рядків бази даних
        self.selected_id = None

        panel = wx.Panel(self)
        vbox = wx.BoxSizer(wx.VERTICAL)

        self.combo = wx.ComboBox(panel, style=wx.CB_READONLY)
        vbox.Add(self.combo, 0, flag=wx.EXPAND | wx.ALL, border=10)

        self.label = wx.StaticText(panel, label="")
        vbox.Add(self.label, 0, flag=wx.EXPAND | wx.ALL, border=10)
        self.label_str = None

        button_sizer = wx.BoxSizer(wx.HORIZONTAL)
        link_button = wx.Button(panel, label="Пов'язати")
        cancel_button = wx.Button(panel, label="Скасувати")

        button_sizer.Add(link_button, 0, wx.RIGHT, 5)
        button_sizer.Add(cancel_button, 0, wx.LEFT, 5)

        vbox.Add(button_sizer, 0, wx.ALIGN_CENTER | wx.BOTTOM, 10)

        panel.SetSizer(vbox)
        self.Layout()
        self.CentreOnScreen()

        self.combo.Bind(wx.EVT_COMBOBOX, self.on_select)
        link_button.Bind(wx.EVT_BUTTON, self.on_link_button_click)
        cancel_button.Bind(wx.EVT_BUTTON, self.on_cancel_button_click)

        # Логіка початкового завантаження даних
        self.load_initial_data()

    def _get_linkable_records(self, person_id, presentation_id, meed_id):
        """
        Виконує запит до бази даних для пошуку записів, які можна прив'язати.
        Повертає список результатів.
        """
        sql_query = ""
        sql_params = None
        label_str = ""

        if presentation_id is not None:
            label_str = "(нагородження)"
            # Шукаємо нагородження на цю особу, які ще не прив'язані до подання
            sql_query = """
                SELECT m.id, m.decree, m.date_decree
                FROM meed AS m
                WHERE m.id_personality = ?
                AND NOT EXISTS (
                    SELECT 1
                    FROM presentation AS p
                    WHERE p.id_meed = m.id
                )
            """
            sql_params = (person_id,)

        elif meed_id is not None:
            label_str = "(подання)"
            # Шукаємо подання на цю особу, які ще не прив'язані до нагородження
            sql_query = """
                SELECT id, registration, date_registration
                FROM presentation
                WHERE id_meed IS NULL
                AND id_personality = ?
            """
            sql_params = (person_id,)
        else:
            return [], "" # Повертаємо порожній список і пустий label_str, якщо немає критеріїв

        if not self.cursor:
            wx.MessageBox("Не вдалося підключитися до бази даних (курсор відсутній).", "Помилка", wx.ICON_ERROR)
            return [], ""

        try:
            raw_results = execute_query(self.cursor, sql_query, sql_params)
            return raw_results, label_str
        except Exception as e:
            wx.LogError(f"Помилка бази даних під час пошуку прив'язуваних записів: {e}")
            return [], "" # У випадку помилки повертаємо порожній список


    def load_initial_data(self):
        raw_results, self.label_str = self._get_linkable_records(
            self.person_id,
            self.presentation_id,
            self.meed_id
        )

        final_display_values = []
        if raw_results:
            items_to_sort = []
            for row in raw_results:
                display_string = f"{row[1]} від {row[2]}"
                items_to_sort.append((display_string, row[0]))

            items_to_sort.sort(key=lambda x: x[0])

            final_display_values = [item[0] for item in items_to_sort]
            self.results_data = [item[1] for item in items_to_sort]

            final_display_values.insert(0, "")
            self.results_data.insert(0, None)

            self.combo.Set(final_display_values)
            self.label.SetLabel(f"Знайдено {len(self.results_data) - 1} записів {self.label_str}")
            self.combo.SetSelection(0)
            self.combo.Show()
            self.Layout()
        else:
            self.label.SetLabel("Немає записів для прив'язки." if self.label_str else "Недостатньо даних для пошуку.")
            self.combo.Hide()
            self.Layout()
            # Додаємо тут закриття вікна, якщо немає даних для відображення
            # або залишаємо його відкритим з повідомленням "Немає записів"
            # self.on_cancel_button_click(None) 


    def on_search(self, sql_query, sql_params):
        if not self.cursor:
            wx.MessageBox("Не вдалося підключитися до бази даних (курсор відсутній).", "Помилка", wx.ICON_ERROR)
            return

        try:
            # Викликаємо вашу універсальну функцію execute_query
            raw_results = execute_query(self.cursor, sql_query, sql_params)
        except Exception as e:
            wx.LogError(f"Помилка бази даних: {e}")
            raw_results = []

        final_display_values = []

        if raw_results:
            items_to_sort = []
            for row in raw_results:
                # Формуємо рядок для відображення БЕЗ ID
                display_string = f"{row[1]} від {row[2]}"
                items_to_sort.append((display_string, row[0])) # Зберігаємо display_string та id 

            items_to_sort.sort(key=lambda x: x[0])

            final_display_values = [item[0] for item in items_to_sort]
            self.results_data = [item[1] for item in items_to_sort] # self.results_data ЗБЕРІГАЄ ОРИГІНАЛЬНІ РЯДКИ З ID

            final_display_values.insert(0, "") # Додаємо порожній елемент на початок для ComboBox
            self.results_data.insert(0, None) # Відповідний None для порожнього елемента

            self.combo.Set(final_display_values) # ComboBox бачить лише рядки без ID
            self.label.SetLabel(f"Знайдено {len(self.results_data) - 1} записів {self.label_str}")
            self.combo.SetSelection(0)
            self.combo.Show()
            self.Layout()
        else:
            self.on_cancel_button_click(None)


    def on_select(self, event):
        selected_index = self.combo.GetSelection()
        
        # Перевіряємо, чи вибрано дійсний елемент (індекс > 0, оскільки 0 - це порожній елемент "")
        if selected_index > 0 and selected_index < len(self.results_data):
            self.selected_id = self.results_data[selected_index] 

        elif selected_index == 0:
            if self.target_field:
                self.target_field.SetValue("")

    def on_link_button_click(self, event):
        if self.selected_id:
            if self.presentation_id:
                # self.selected_id содержит id таблици meed
                # значит записиваем self.selected_id в id_meed 
                # таблици presentation WHERE id=self.presentation_id

                query = """
                    UPDATE presentation
                        SET id_meed = ?
                        WHERE id = ?
                    """
                self.cursor.execute(query, (self.selected_id, self.presentation_id))

            elif self.meed_id:
                # self.selected_id содержит id таблици presentation
                # значит записиваем self.meed_id в id_meed 
                # таблици presentation WHERE id=self.selected_id

                query = """
                    UPDATE presentation
                        SET id_meed = ?
                        WHERE id = ?
                    """
                self.cursor.execute(query, (self.meed_id, self.selected_id))
            else:
                pass

            self.conn.commit()
            if self.parent_panel and hasattr(self.parent_panel, 'trigger_search_in_tab1_and_load_results'):
                self.parent_panel.trigger_search_in_tab1_and_load_results()
            
            self.Close()
        else:
            wx.MessageBox("Виберіть запис для прив'язування.", "Увага", wx.OK | wx.ICON_INFORMATION)

    def on_cancel_button_click(self, event):
        if self.parent_panel and hasattr(self.parent_panel, 'trigger_search_in_tab1_and_load_results'):
            self.parent_panel.trigger_search_in_tab1_and_load_results()
        self.Close()

