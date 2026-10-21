# zvity.py
import wx
import wx.adv
import wx.lib.scrolledpanel as scrolled
import os
import io
import threading
from datetime import datetime, date

# --- Локальні імпорти ---
from config import START_YEAR, DEF_FUT_LABEL
from database_logic import (
    connect_to_database, get_service_settings_data,
    get_units_and_ranks,
    get_formatted_unique_awarded_distinctions,
    RankingValues 
)

from ui_utils import (
    load_image_from_blob, ReportGeneratorWx, ComboSearchHelper,  
    ComparisonReportFrame, parse_input_person_csv
)

# --- Константи ---
# Значення для радіокнопок категорії осіб (MeedvarR1_value)
PERSON_CATEGORY_OFFICER = 1
PERSON_CATEGORY_SERGEANT = 2
PERSON_CATEGORY_SOLDIER = 3
PERSON_CATEGORY_MILITARY = 4
PERSON_CATEGORY_ALL = 6 # Початкове значення "Усі особи"

# Значення для радіокнопок статусу вручення (handowerAward_value)
AWARD_HANDOVER_STATUS_ASSIGNED = 3
AWARD_HANDOVER_STATUS_ISSUED = 2
AWARD_HANDOVER_STATUS_REMAINING = 1 # Початкове значення "залишок в натурі"

# Значення для радіокнопок статусу подання (PresvarR2_value)
SUBMISSION_STATUS_APPROVED = 1
SUBMISSION_STATUS_REJECTED = 2
SUBMISSION_STATUS_PENDING = 3
SUBMISSION_STATUS_ALL = 4 # Початкове значення "Усі"

# Індекси стовпців для get_service_settings_data
class ServiceSettingsIndices:
    LOGO = 0
    EXCEL_BUTTON = 1
    VIEW_BUTTON = 2
    OR_BUTTON = 3
    ZVIT_DIR = 4
    ZVIT_FIELDS = 5
    IMG_HOMER = 10
    IMG_HOMER2 = 11

# --- Глобальні налаштування ---
MIN_DATE_DT = datetime(START_YEAR, 1, 1)
MIN_DATE_WX = wx.DateTime(MIN_DATE_DT.day, MIN_DATE_DT.month - 1, MIN_DATE_DT.year)

# Поточна дата
today_dt = datetime.now()
today_wx = wx.DateTime(today_dt.day, today_dt.month - 1, today_dt.year)

# Дата "рік тому" для початкового відображення
one_year_ago_dt = datetime(today_dt.year - 1, today_dt.month, today_dt.day)
one_year_ago_wx = wx.DateTime(one_year_ago_dt.day, one_year_ago_dt.month - 1, one_year_ago_dt.year)

# --- Функція, що виконується у окремому потоці для завантаження назв нагород ---
def load_award_names_worker(panel, db_path, key, rank_filter=None):
    """
    Функція, що виконується у окремому потоці для завантаження та форматування назв нагород.
    Приймає об'єкт панелі для зворотного виклику та опціональний фільтр рангу.
    """
    loaded_names = [] # Цей список буде містити відформатовані унікальні рядки
    error = None
    conn = None
    cursor = None
    try:
        # Важливо: встановлюємо з'єднання з БД У СЕРЕДИНІ ПОТОКУ,
        # а не використовуємо курсор з головного потоку
        conn, cursor = connect_to_database(key, db_path)
        if conn is None or cursor is None:
            error = "Не вдалося підключитися до бази даних у робочому потоці."
        else:
            loaded_names = get_formatted_unique_awarded_distinctions(cursor, rank_filter)

    except Exception as e:
        error = f"Помилка у робочому потоці при завантаженні та формуванні назв нагород (фільтр: '{rank_filter}'): {e}"
        print(error)
    finally:
        # Завжди намагаємося закрити з'єднання у потоці
        if cursor:
            try: cursor.close()
            except Exception: pass
        if conn:
            try: conn.close()
            except Exception: pass

    # wx.CallAfter гарантує, що self._on_award_names_loaded буде викликано
    # в безпечний час у головному потоці UI.
    wx.CallAfter(panel._on_award_names_loaded, loaded_names, error)

# --- Головний клас панелі звіту ---

class Tab4Panel(scrolled.ScrolledPanel):
    def __init__ (self, parent, conn, cursor, db_path, key, fut_place=None):
        super().__init__(parent)
        self.SetDoubleBuffered(True)  
        
        # Залежності та дані
        self.conn = conn
        self.cursor = cursor
        self.db_path = db_path # Для worker-а
        self.key = key         # Для worker-а
        self.fut_place = fut_place 

        # Списки даних (заповнюються)
        self._loaded_units = []
        self._loaded_ranks = []
        self._loaded_award_names = []

        # Зображення (завантажуються з БД)
        self._logo_bmp = None
        self._excel_bmp = None # Змінено ім'я з _exel_bmp
        self._view_bmp = None
        self._or_bmp = None

        # Налаштування сервісу (завантажуються з БД)
        self.zvit_dir = None
        self.zvit_fields = None

        # Початковий стан UI (значення за замовчуванням)
        self.person_category_filter = PERSON_CATEGORY_ALL
        self.is_civilian_filter = False # state_b_value
        self.is_posthumous_filter = False # deadOn_value
        self.is_award_by_name_filter = False # typeAward_value
        self.is_all_time_filter = False # allTime_value
        self.is_issue_protocols_filter = False #  змінна стану для фільтра "протоколи видачі"
        self.award_handover_status = AWARD_HANDOVER_STATUS_ASSIGNED
        self.submission_status_filter = SUBMISSION_STATUS_ALL
        self.is_specific_submission_filter = False # SelNumberPresent_value
        self.mode_toggle_state = 0 # 0 - Нагородження, 1 - Подання (idMeedOrPres)
        self.last_footer_message = "Для створення звіту оберіть параметри та категорію"
        if self.mode_toggle_state == 0:
            self.last_footer_message += " [Нагородження]" # значение по умолчанию
        else:
            self.last_footer_message += " [Подання]" # значение по умолчанию

        self.selected_award_id = None
        
        self._submission_loaded = False  # флаг щоб не тригерився список      
        
        # Прив'язка обробника закриття вікна
        self.Bind(wx.EVT_WINDOW_DESTROY, self.on_destroy)

    def refresh_tree(self, event=None):
        self.Freeze()
        # --- Завантаження початкових даних ---
        try:
            # Перевіряємо курсор перед використанням
            if self.cursor:
                self._loaded_ranks, self._loaded_units = get_units_and_ranks(self.cursor)
                self._load_service_settings() # Завантажує зображення та інші налаштування
            else:
                 # Можна показати помилку користувачу або встановити значення за замовчуванням
                 self._loaded_units = ["(Помилка завантаження)"]
                 self._loaded_ranks = ["(Помилка завантаження)"]
                 # Ініціалізувати інші залежні від БД значення як порожні/вимкнені
            
        except Exception as e:
            pass

        finally:
            self.build_ui() 
            self.update_initial_widget_state()
            self._update_mode_ui() # Цей метод має оновлювати вигляд залежно від self.mode_toggle_state
            self.update_unit_civilian_visibility() # Цей метод оновлює видимість залежно від вибору категорії особи
            self.Layout()
            self.Thaw()

    def on_destroy(self, event):
        """Обробник події закриття вікна."""
        event.Skip() # Передати подію далі


    def _load_service_settings(self):
        """Завантажує налаштування сервісу та зображення кнопок з БД."""
        # Скидання атрибутів перед завантаженням
        self._logo_bmp = None
        self._excel_bmp = None
        self._view_bmp = None
        self._or_bmp = None
        self.zvit_dir = None
        self.zvit_fields = None

        if not self.cursor:
            return

        try:
            settings_row = get_service_settings_data(self.cursor)

            if not settings_row:
                return

            # Використовуємо константи для індексів
            indices = ServiceSettingsIndices

            # Розміри для зображень
            logo_max_dim = 100
            button_max_dim = 60
            homer_max_dim = 50

            self._logo_bmp = load_image_from_blob(settings_row[indices.LOGO], max_dim=60)
            self._excel_bmp = load_image_from_blob(settings_row[indices.EXCEL_BUTTON], max_dim=button_max_dim)
            self._view_bmp = load_image_from_blob(settings_row[indices.VIEW_BUTTON], max_dim=button_max_dim)
            self._or_bmp = load_image_from_blob(settings_row[indices.OR_BUTTON], max_dim=button_max_dim)

            self.zvit_dir = settings_row[indices.ZVIT_DIR]
            self.zvit_fields = settings_row[indices.ZVIT_FIELDS]

        except Exception as e:
            pass
            # Атрибути залишаться None або зі значеннями за замовчуванням

    def _start_award_names_loading_thread(self, rank_filter=None):
        """Запускає фоновий потік для завантаження назв нагород."""
        self.update_footer_message("Підготовка списку нагород ...")

        # Перевірка наявності необхідних UI елементів
        if not hasattr(self, 'award_name_combo') or not hasattr(self, 'award_by_name_checkbox'):
            return

        # Завантажувати тільки якщо опція "ранг / назва" увімкнена
        if not self.award_by_name_checkbox.GetValue():
            self.award_name_combo.Clear()
            self.award_name_combo.Enable(False)
            self._loaded_award_names = []
            return

        # Перевірка параметрів для потоку
        if self.db_path is None or self.key is None:
            wx.MessageBox("Не вдалося завантажити список нагород: відсутні дані для підключення до БД.",
                          "Помилка", wx.OK | wx.ICON_ERROR)
            self.award_name_combo.Clear()
            self.award_name_combo.Enable(False)
            return

        # Оновлення UI перед запуском потоку
        self.award_name_combo.Clear()
        self.award_name_combo.Enable(False)

        # Створення та запуск потоку
        worker = threading.Thread(
            target=load_award_names_worker,
            args=(self, self.db_path, self.key, rank_filter),
            daemon=True # Дозволяє програмі завершитись, навіть якщо потік ще працює
        )
        worker.start()

    def _on_award_names_loaded(self, loaded_names, error):
        """
        Метод зворотного виклику (через wx.CallAfter) для оновлення UI
        після завантаження назв нагород у фоновому потоці.
        """
        if not hasattr(self, 'award_name_combo') or not hasattr(self, 'award_by_name_checkbox'):
             return # Або обробити помилку інакше

        if error:
            wx.MessageBox(f"Помилка завантаження списку нагород:\n{error}", "Помилка", wx.OK | wx.ICON_ERROR)
            self._loaded_award_names = []
            self.award_name_combo.Clear()
            self.award_name_combo.Enable(False)
        else:
            self._loaded_award_names = loaded_names
            self.award_name_combo.Clear()
            if self._loaded_award_names:
                self.award_name_combo.SetItems(self._loaded_award_names)
                self.award_search_helper.set_items(self._loaded_award_names)

            # Вмикаємо комбобокс, тільки якщо чекбокс все ще активний
            is_by_name_checked = self.award_by_name_checkbox.GetValue()
            self.award_name_combo.Enable(is_by_name_checked)
            self.update_footer_message(DEF_FUT_LABEL)



    # --- Методи побудови інтерфейсу ---

    def build_ui(self):
        """Збирає основний макет інтерфейсу користувача."""
        self.DestroyChildren()
        main_sizer = wx.BoxSizer(wx.VERTICAL)

        # Верхня панель: Фільтри
        info_panel = self.create_info_group()
        main_sizer.Add(info_panel, 0, wx.EXPAND | wx.ALL, 10) # Стандартизуємо відступи

        # Нижня панель: Налаштування та Дії
        bottom_panel_sizer = wx.BoxSizer(wx.HORIZONTAL)

        # Ліва частина нижньої панелі
        panel_left = wx.Panel(self)
        left_sizer = wx.BoxSizer(wx.VERTICAL)
        panel_left.SetSizer(left_sizer)

        # Група "Нагородження"
        self.award_sizer = self.create_award_group(panel_left)
        left_sizer.Add(self.award_sizer, 1, wx.EXPAND | wx.ALL, 3)

        # Група "Подання"
        self.submission_sizer = self.create_submission_group(panel_left)
        left_sizer.Add(self.submission_sizer, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 3)

        bottom_panel_sizer.Add(panel_left, 1, wx.EXPAND | wx.ALL, 3)

        # Права частина нижньої панелі: Кнопки дій
        action_panel_right = self.create_action_buttons()
        bottom_panel_sizer.Add(action_panel_right, 0, wx.EXPAND | wx.ALL, 3) # Пропорція 0, не розтягувати

        main_sizer.Add(bottom_panel_sizer, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 3)

        self.SetSizer(main_sizer)
        self.SetupScrolling() # Важливо для scrolled.ScrolledPanel

  
    def create_info_group(self):
        """Створює верхню панель з фільтрами дати, категорії осіб, підрозділу."""
        panel_top = wx.Panel(self)
        top_sizer = wx.BoxSizer(wx.VERTICAL)
        panel_top.SetSizer(top_sizer)

        grid_sizer_top = wx.FlexGridSizer(rows=2, cols=7, vgap=5, hgap=5)
        grid_sizer_top.AddGrowableCol(5, 1)

        # --- Рядок 1: Період, чекбокси та виконавець ---
        lbl_period = wx.StaticText(panel_top, label="Період виборки:")
        grid_sizer_top.Add(lbl_period, 0, wx.ALIGN_CENTER_VERTICAL | wx.ALIGN_RIGHT | wx.ALL, 3)

        self.start_date_picker = wx.adv.DatePickerCtrl(panel_top, style=wx.adv.DP_DROPDOWN | wx.adv.DP_SHOWCENTURY)
        self.start_date_picker.SetRange(MIN_DATE_WX, today_wx)
        self.start_date_picker.SetValue(one_year_ago_wx)
        self.start_date_picker.Bind(wx.adv.EVT_DATE_CHANGED, self.on_date_period_changed)        
        grid_sizer_top.Add(self.start_date_picker, 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 3)

        self.end_date_picker = wx.adv.DatePickerCtrl(panel_top, style=wx.adv.DP_DROPDOWN | wx.adv.DP_SHOWCENTURY)
        max_date = wx.DateTime(today_dt.day, today_dt.month - 1, today_dt.year + 1)
        self.end_date_picker.SetRange(MIN_DATE_WX, max_date)
        self.end_date_picker.SetValue(today_wx)
        self.end_date_picker.Bind(wx.adv.EVT_DATE_CHANGED, self.on_date_period_changed)
        grid_sizer_top.Add(self.end_date_picker, 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 3)

        self.all_time_checkbox = wx.CheckBox(panel_top, label="увесь час")
        self.all_time_checkbox.Bind(wx.EVT_CHECKBOX, self.on_all_time_toggle)
        grid_sizer_top.Add(self.all_time_checkbox, 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 3)

        self.posthumous_checkbox = wx.CheckBox(panel_top, label="посмертно")
        self.posthumous_checkbox.Bind(wx.EVT_CHECKBOX, self.on_posthumous_toggle)
        grid_sizer_top.Add(self.posthumous_checkbox, 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 3)

        worker_sizer = wx.BoxSizer(wx.HORIZONTAL)
        worker_label = wx.StaticText(panel_top, label="виконавець:")
        worker_sizer.Add(worker_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 3)
        self.worker_combo = wx.ComboBox(panel_top, choices=['Усі', 'ВП', 'МПЗ', 'Інші'], style=wx.CB_READONLY)
        self.worker_combo.SetSelection(0)
        worker_sizer.Add(self.worker_combo, 1, wx.EXPAND | wx.LEFT, 3)
        grid_sizer_top.Add(worker_sizer, 1, wx.EXPAND | wx.ALIGN_CENTER_VERTICAL | wx.ALL, 3)

        grid_sizer_top.AddStretchSpacer()

        # --- Рядок 2: Радіокнопки категорій осіб та вибір підрозділу ---
        self.person_officer_radio = wx.RadioButton(panel_top, label="Офіцери", style=wx.RB_GROUP)
        self.person_officer_radio.Bind(wx.EVT_RADIOBUTTON, lambda event: self.on_person_category_change(event, PERSON_CATEGORY_OFFICER))
        grid_sizer_top.Add(self.person_officer_radio, 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 3)

        self.person_sergeant_radio = wx.RadioButton(panel_top, label="Сержанти")
        self.person_sergeant_radio.Bind(wx.EVT_RADIOBUTTON, lambda event: self.on_person_category_change(event, PERSON_CATEGORY_SERGEANT))
        grid_sizer_top.Add(self.person_sergeant_radio, 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 3)

        self.person_soldier_radio = wx.RadioButton(panel_top, label="Солдати")
        self.person_soldier_radio.Bind(wx.EVT_RADIOBUTTON, lambda event: self.on_person_category_change(event, PERSON_CATEGORY_SOLDIER))
        grid_sizer_top.Add(self.person_soldier_radio, 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 3)

        self.person_military_radio = wx.RadioButton(panel_top, label="Військові")
        self.person_military_radio.Bind(wx.EVT_RADIOBUTTON, lambda event: self.on_person_category_change(event, PERSON_CATEGORY_MILITARY))
        grid_sizer_top.Add(self.person_military_radio, 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 3)

        self.person_all_radio = wx.RadioButton(panel_top, label="Усі особи")
        self.person_all_radio.Bind(wx.EVT_RADIOBUTTON, lambda event: self.on_person_category_change(event, PERSON_CATEGORY_ALL))
        grid_sizer_top.Add(self.person_all_radio, 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 3)

        self.unit_civilian_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.unit_label = wx.StaticText(panel_top, label="підрозділ:")
        self.unit_civilian_sizer.Add(self.unit_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 3)

        self.unit_combo = wx.ComboBox(panel_top, choices=self._loaded_units, style=wx.CB_READONLY)
        if self._loaded_units: self.unit_combo.SetSelection(0)
        self.unit_civilian_sizer.Add(self.unit_combo, 1, wx.EXPAND | wx.LEFT, 3)

        self.civilian_checkbox = wx.CheckBox(panel_top, label="= цивільні")
        self.civilian_checkbox.Bind(wx.EVT_CHECKBOX, self.on_civilian_toggle)
        self.unit_civilian_sizer.Add(self.civilian_checkbox, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 3)
        grid_sizer_top.Add(self.unit_civilian_sizer, 1, wx.EXPAND | wx.ALIGN_CENTER_VERTICAL | wx.ALL, 3)

        grid_sizer_top.AddStretchSpacer()

        # Додаємо сітку фільтрів у першу чергу
        top_sizer.Add(grid_sizer_top, 0, wx.EXPAND | wx.ALL, 3)

        # --- Рядок 3: Блок завантаження CSV-файлу (компактний) ---
        file_box_sizer = wx.BoxSizer(wx.HORIZONTAL)

        # Єдина кнопка вибору файлу
        self.btn_browse_csv = wx.Button(panel_top, label="Список (CSV):", size=(110, -1))
        self.btn_browse_csv.Bind(wx.EVT_BUTTON, self.on_select_input_csv)

        # Динамічне текстове поле для шляху до файлу
        self.file_path_text = wx.TextCtrl(panel_top, style=wx.TE_READONLY)
        self.file_path_text.SetHint("Виберіть CSV файл зі списком людей...")
        self.file_path_text.SetMinSize((80, -1))

        # Напис з кількістю завантажених осіб
        self.lbl_csv_info = wx.StaticText(panel_top, label="Файл не вибрано")
        self.lbl_csv_info.SetMinSize((200, -1))

        # Кнопка очищення CSV / фільтрів
        self.btn_clear_csv = wx.Button(panel_top, label="✕", size=(40, -1))
        self.btn_clear_csv.Bind(wx.EVT_BUTTON, self.on_clear_fields)

        file_box_sizer.Add(self.btn_browse_csv, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        file_box_sizer.Add(self.file_path_text, 1, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 10)
        file_box_sizer.Add(self.lbl_csv_info, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 10)
        file_box_sizer.Add(self.btn_clear_csv, 0, wx.ALIGN_CENTER_VERTICAL)

        # Додаємо блок нижче радіокнопок
        top_sizer.Add(file_box_sizer, 0, wx.EXPAND | wx.ALL, 5)

        return panel_top  

    def on_clear_fields(self, event=None):
        """Очищає завантажений CSV файл та скидає значення поля шлях до файлу."""
        # Очищення завантаженого датафрейму
        self.loaded_input_df = None
        
        # Скидання текстових полів UI
        if hasattr(self, 'file_path_text'):
            self.file_path_text.SetValue("")
        if hasattr(self, 'lbl_csv_info'):
            self.lbl_csv_info.SetLabel("Файл не вибрано")

        # Додатково: якщо потрібно скинути інші комбобокси чи фільтри, їх можна очистити тут:
        # self.unit_combo.SetSelection(0)
        # self.all_time_checkbox.SetValue(False)

        self.update_footer_message("Дані CSV списку очищено.")

    def create_award_group(self, parent_panel):
        """Створює групу налаштувань для секції 'Нагородження'."""
        self.award_static_box = wx.StaticBox(parent_panel, label=" Нагородження ")
        award_sizer = wx.StaticBoxSizer(self.award_static_box, wx.VERTICAL)

        # --- Рядок 1: Статус вручення та накладна ---
        handover_sizer = wx.BoxSizer(wx.HORIZONTAL)

        # Радіокнопки статусу
        self.handover_assigned_radio = wx.RadioButton(parent_panel, label="призначені", style=wx.RB_GROUP)
        self.handover_assigned_radio.Bind(wx.EVT_RADIOBUTTON, lambda e: self.on_handover_status_change(e, AWARD_HANDOVER_STATUS_ASSIGNED))
        handover_sizer.Add(self.handover_assigned_radio, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 3)

        self.handover_issued_radio = wx.RadioButton(parent_panel, label="видані")
        self.handover_issued_radio.Bind(wx.EVT_RADIOBUTTON, lambda e: self.on_handover_status_change(e, AWARD_HANDOVER_STATUS_ISSUED))
        handover_sizer.Add(self.handover_issued_radio, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 3)

        self.handover_remaining_radio = wx.RadioButton(parent_panel, label="залишок в натурі")
        # self.handover_remaining_radio.SetValue(True) # Встановлюється в update_initial_widget_state
        self.handover_remaining_radio.Bind(wx.EVT_RADIOBUTTON, lambda e: self.on_handover_status_change(e, AWARD_HANDOVER_STATUS_REMAINING))
        handover_sizer.Add(self.handover_remaining_radio, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 10)

        # Вибір накладної
        self.consignment_label = wx.StaticText(parent_panel, label="накладна:")
        handover_sizer.Add(self.consignment_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 3)
        self.consignment_combo = wx.ComboBox(parent_panel, choices=[], style=wx.CB_DROPDOWN, size=(120,-1)) 
        handover_sizer.Add(self.consignment_combo, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 3)
        self.consignment_count_label = wx.StaticText(parent_panel, label="") # Початковий лічильник
        self.consignment_count_label.SetMinSize((50, -1)) # Встановлюємо мінімальну ширину 50 пікселів (-1 означає автоматичну висоту)
        handover_sizer.Add(self.consignment_count_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 3)
        award_sizer.Add(handover_sizer, 0, wx.EXPAND | wx.ALL, 5)
        self.consignment_search_helper = ComboSearchHelper(self.consignment_combo)

        # --- Рядок 2: Тип нагороди (ранг / назва) ---
        award_type_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.award_label = wx.StaticText(parent_panel, label=" Нагорода:")
        award_type_sizer.Add(self.award_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 3)

        # Вибір рангу нагороди
        self.ranking_award_combo = wx.ComboBox(parent_panel, choices=RankingValues, style=wx.CB_READONLY)
        if RankingValues: self.ranking_award_combo.SetSelection(0) # Вибрати перший ранг
        self.ranking_award_combo.Bind(wx.EVT_COMBOBOX, self.on_award_rank_selected)
        award_type_sizer.Add(self.ranking_award_combo, 1, wx.EXPAND | wx.RIGHT, 3) # Пропорція 1

        # Чекбокс "ранг / назва"
        self.award_by_name_checkbox = wx.CheckBox(parent_panel, label="ранг / назва")
        self.award_by_name_checkbox.Bind(wx.EVT_CHECKBOX, self.on_award_by_name_toggle)
        award_type_sizer.Add(self.award_by_name_checkbox, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT | wx.RIGHT, 10)

        # Вибір назви нагороди (заповнюється асинхронно)
        self.award_name_combo = wx.ComboBox(parent_panel, choices=[], style=wx.CB_DROPDOWN, size=(250, -1))
        self.award_name_combo.Enable(False) # Вимкнено за замовчуванням
        self.award_name_combo.Bind(wx.EVT_COMBOBOX, self.on_award_name_selected) # Обробник міняє зображення нагороди поруч
        award_type_sizer.Add(self.award_name_combo, 2, wx.EXPAND | wx.LEFT, 3) # Пропорція 2
        award_sizer.Add(award_type_sizer, 0, wx.EXPAND | wx.ALL, 5)
        self.award_search_helper = ComboSearchHelper(self.award_name_combo)


        # ---- рядок 3 -------
        # Додаємо чекбокс "Протоколи видачі" тепер у новий рядок
        self.issue_protocols_checkbox = wx.CheckBox(parent_panel, wx.ID_ANY, label="Відсутні протоколи видачі нагород")
        self.issue_protocols_checkbox.Bind(wx.EVT_CHECKBOX, self.on_issue_protocols_toggle)
        # Додаємо його безпосередньо до основного вертикального сайзера award_sizer
        award_sizer.Add(self.issue_protocols_checkbox, 0, wx.ALL | wx.ALIGN_LEFT, 5)

        return award_sizer


    def create_submission_group(self, parent_panel):
        """Створює групу налаштувань для секції 'Подання'."""
        self.submission_static_box = wx.StaticBox(parent_panel, label=" Подання ")
        self.submission_static_box.SetForegroundColour(wx.Colour("gray")) # ДОДАЙТЕ ЦЕЙ РЯДОК
        submission_sizer = wx.StaticBoxSizer(self.submission_static_box, wx.VERTICAL)

        # --- Рядок 1: Статус подання ---
        present_status_sizer = wx.BoxSizer(wx.HORIZONTAL)

        self.submission_approved_radio = wx.RadioButton(parent_panel, label="Погоджені", style=wx.RB_GROUP)
        self.submission_approved_radio.Bind(wx.EVT_RADIOBUTTON, lambda e: self.on_submission_status_change(e, SUBMISSION_STATUS_APPROVED))
        present_status_sizer.Add(self.submission_approved_radio, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 3)

        self.submission_rejected_radio = wx.RadioButton(parent_panel, label="Не погоджені")
        self.submission_rejected_radio.Bind(wx.EVT_RADIOBUTTON, lambda e: self.on_submission_status_change(e, SUBMISSION_STATUS_REJECTED))
        present_status_sizer.Add(self.submission_rejected_radio, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 3)

        self.submission_pending_radio = wx.RadioButton(parent_panel, label="У залишку")
        self.submission_pending_radio.Bind(wx.EVT_RADIOBUTTON, lambda e: self.on_submission_status_change(e, SUBMISSION_STATUS_PENDING))
        present_status_sizer.Add(self.submission_pending_radio, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 3)

        self.submission_all_radio = wx.RadioButton(parent_panel, label="Усі")
        self.submission_all_radio.Bind(wx.EVT_RADIOBUTTON, lambda e: self.on_submission_status_change(e, SUBMISSION_STATUS_ALL))
        present_status_sizer.Add(self.submission_all_radio, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 3)

        submission_sizer.Add(present_status_sizer, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 5)

        # --- Рядок 2: Вибір конкретного подання ---
        present_sel_sizer = wx.BoxSizer(wx.HORIZONTAL)

        self.specific_submission_checkbox = wx.CheckBox(parent_panel, label="Окреме подання:")
        self.specific_submission_checkbox.Bind(wx.EVT_CHECKBOX, self.on_specific_submission_toggle)
        present_sel_sizer.Add(self.specific_submission_checkbox, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 10)

        # ComboBox для номерів подань
        self.specific_submission_combo = wx.ComboBox(parent_panel, choices=[], style=wx.CB_DROPDOWN, size=(250, -1))
        self.specific_submission_combo.Enable(False) # Вимкнено за замовчуванням
        self.specific_submission_combo.Bind(wx.EVT_COMBOBOX_DROPDOWN, self.on_submission_combo_open) # Завантаження при відкритті
        present_sel_sizer.Add(self.specific_submission_combo, 1, wx.EXPAND | wx.RIGHT, 3) # Пропорція 1

        self.submission_count_label = wx.StaticText(parent_panel, label="") # Початковий лічильник
        self.submission_count_label.SetMinSize((50, -1)) # Встановлюємо мінімальну ширину 50 пікселів (-1 означає автоматичну висоту)
        present_sel_sizer.Add(self.submission_count_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 3)

        submission_sizer.Add(present_sel_sizer, 0, wx.EXPAND | wx.ALL, 5)

        self.specific_submission_search_helper = ComboSearchHelper(self.specific_submission_combo)
        
        return submission_sizer


    def on_select_input_csv(self, event):
        """Обробник вибору CSV-файлу зі списком людей."""
        with wx.FileDialog(self, "Оберіть CSV файл зі списком", wildcard="CSV files (*.csv)|*.csv",
                           style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST) as dlg:
            if dlg.ShowModal() == wx.ID_OK:
                filepath = dlg.GetPath()
                self.file_path_text.SetValue(filepath)
                
                # Парсинг файлу
                try:
                    self.loaded_input_df = parse_input_person_csv(filepath)
                    count = len(self.loaded_input_df)
                    has_inn = sum(1 for item in self.loaded_input_df if item.get("РНОКПП_norm"))                   

                    self.lbl_csv_info.SetLabel(f"(ПІБ:{count}/РНОКПП:{has_inn})")
                except Exception as e:
                    wx.MessageBox(f"Помилка при зчитуванні CSV файлу:\n{e}", "Помилка", wx.OK | wx.ICON_ERROR)
                    self.lbl_csv_info.SetLabel("Помилка файлу")

    def on_run_comparison_report(self, event):
        # Перевіряємо, чи існує атрибут і чи не порожній список
        if not hasattr(self, 'loaded_input_df') or not self.loaded_input_df:
            wx.MessageBox(
                "Будь ласка, спочатку виберіть коректний CSV файл зі списком людей!", 
                "Увага", 
                wx.OK | wx.ICON_WARNING
            )
            return
        # Збираємо обрані в інтерфейсі фільтри
        filters = {
            'mode': 'awarding' if self.mode_toggle_state == 0 else 'submission',
            'start_date': self.start_date_picker.GetValue().Format("%Y-%m-%d"),
            'end_date': self.end_date_picker.GetValue().Format("%Y-%m-%d"),
            'all_time': self.all_time_checkbox.GetValue(),
            'posthumous': self.posthumous_checkbox.GetValue(),
            'worker': self.worker_combo.GetValue(),
            'person_category': self.person_category_filter,
            'unit': self.unit_combo.GetValue() if self.unit_combo.IsEnabled() else "",
            'handover_status': self.award_handover_status,
            'submission_status': self.submission_status_filter,
            'award_rank': self.ranking_award_combo.GetValue(),
            'award_id': self.selected_award_id
        }

        # Відкриваємо вікно порівняльного звіту
        report_frame = ComparisonReportFrame(
            parent=self,
            db_path=self.db_path,
            key=self.key,
            filters=filters,
            zvit_fields=self.zvit_fields,
            zvit_dir=self.zvit_dir,
            input_data=self.loaded_input_df,  
            exel_bmp=self._excel_bmp
        )
        report_frame.Show()

    def create_action_buttons(self):
        """Створює праву панель з кнопками дій (Перегляд, Excel, тощо)."""
        panel_right = wx.Panel(self)
        action_sizer = wx.BoxSizer(wx.VERTICAL)
        panel_right.SetSizer(action_sizer)

        # Додати зображення нагороди зверху (якщо є)
        image_sizer = wx.BoxSizer(wx.VERTICAL)
        # Початковий показ лого - зображення нагород буде оновлюватися пізніше
        if hasattr(self, '_logo_bmp') and self._logo_bmp and self._logo_bmp.IsOk():
            self.award_image = wx.StaticBitmap(panel_right, wx.ID_ANY, self._logo_bmp)
        else:
            # При отсутствии логотипа создаем пустой StaticBitmap
            self.award_image = wx.StaticBitmap(panel_right, wx.ID_ANY) # Уберите size=(100, 100) здесь
            # Возможно, инициализируйте его пустым битмапом или индикатором
            empty_bitmap = wx.Bitmap(60, 60) # Или любой размер, который не вызовет проблем
            # Можно нарисовать что-то на empty_bitmap, как вы делаете в catch блоке или _reset_award_image
            self.award_image.SetBitmap(empty_bitmap)

        # *** Установите минимальный размер для StaticBitmap ***
        # max_dim, используемый в load_image_from_blob в _update_award_image, равен 60.
        # Убедимся, что StaticBitmap имеет как минимум этот размер.
        self.award_image.SetMinSize((60, 60)) # Важная строка!

        image_sizer.Add(self.award_image, 0, wx.ALIGN_CENTER | wx.ALL, 3)
        action_sizer.Add(image_sizer, 0, wx.ALIGN_CENTER | wx.TOP, 10)

        action_sizer.AddStretchSpacer(1)

        # Секція кнопок
        buttons_sizer = wx.BoxSizer(wx.VERTICAL)

        # Кнопка Перемикання Режиму (Нагородження / Подання)
        self.mode_toggle_button = wx.ToggleButton(panel_right, label="Режим", size=(80, 80))
        if self._or_bmp:
            self.mode_toggle_button.SetBitmap(self._or_bmp, wx.LEFT)   
            self.mode_toggle_button.SetLabel("")    
        self.mode_toggle_button.Bind(wx.EVT_TOGGLEBUTTON, self.on_mode_toggle)
        buttons_sizer.Add(self.mode_toggle_button, 0, wx.ALIGN_CENTER_HORIZONTAL | wx.BOTTOM, 5)

        # Кнопка Перегляду (з іконкою, якщо є)
        # Змінюємо ширину на size_w (100), щоб отримати 100x100
        self.view_button = wx.Button(panel_right, label=" Перегляд", size=(80, 80))
        if self._view_bmp:
            self.view_button.SetBitmap(self._view_bmp, wx.LEFT)
            self.view_button.SetLabel("")
        self.view_button.Bind(wx.EVT_BUTTON, self.on_view_report)
        buttons_sizer.Add(self.view_button, 0, wx.ALIGN_CENTER_HORIZONTAL | wx.BOTTOM, 5)

        action_sizer.Add(buttons_sizer, 0, wx.EXPAND)

        return panel_right


    # --- Методи оновлення стану UI ---

    def update_footer_message(self, message):
        #  вивод текста в футер
        if self.fut_place:
            self.last_footer_message = message
            self.fut_place.SetLabel(self.last_footer_message)  # обновляем футер

    def get_footer_message(self):
        """ метод для определения значения self.last_footer_message """
        return self.last_footer_message

    def update_initial_widget_state(self):
        """Встановлює початковий стан віджетів на основі значень за замовчуванням."""
        # Дати - встановлюються при створенні DatePickerCtrl
        self.all_time_checkbox.SetValue(self.is_all_time_filter)
        self.posthumous_checkbox.SetValue(self.is_posthumous_filter)
        self.on_all_time_toggle(None) # Застосувати початковий стан (вкл/викл date pickers)

        # Категорія осіб
        radio_map = {
            PERSON_CATEGORY_OFFICER: self.person_officer_radio,
            PERSON_CATEGORY_SERGEANT: self.person_sergeant_radio,
            PERSON_CATEGORY_SOLDIER: self.person_soldier_radio,
            PERSON_CATEGORY_MILITARY: self.person_military_radio,
            PERSON_CATEGORY_ALL: self.person_all_radio,
        }
        radio_map.get(self.person_category_filter, self.person_all_radio).SetValue(True)
        self.update_unit_civilian_visibility() # Оновити видимість unit/civilian

        # Статус вручення нагороди
        handover_map = {
            AWARD_HANDOVER_STATUS_ASSIGNED: self.handover_assigned_radio,
            AWARD_HANDOVER_STATUS_ISSUED: self.handover_issued_radio,
            AWARD_HANDOVER_STATUS_REMAINING: self.handover_remaining_radio,
        }
        handover_map.get(self.award_handover_status, self.handover_remaining_radio).SetValue(True)
        self.update_consignment_combobox_state() # Оновити стан комбобокса накладної

        # Тип нагороди (ранг/назва)
        self.award_by_name_checkbox.SetValue(self.is_award_by_name_filter)
        self.on_award_by_name_toggle(None) # Застосувати стан (вкл/викл award_name_combo)

        # Статус подання
        submission_map = {
            SUBMISSION_STATUS_APPROVED: self.submission_approved_radio,
            SUBMISSION_STATUS_REJECTED: self.submission_rejected_radio,
            SUBMISSION_STATUS_PENDING: self.submission_pending_radio,
            SUBMISSION_STATUS_ALL: self.submission_all_radio,
        }
        submission_map.get(self.submission_status_filter, self.submission_all_radio).SetValue(True)

        # Окреме подання
        self.specific_submission_checkbox.SetValue(self.is_specific_submission_filter)
        self.on_specific_submission_toggle(None) # Застосувати стан (вкл/викл specific_submission_combo)

        # Режим (Нагородження / Подання)
        self.mode_toggle_button.SetValue(self.mode_toggle_state == 1) # True якщо Подання
        self._update_mode_ui()

    def _update_mode_ui(self, initial_setup=False): # Можливо, додайте параметр для початкової установки
        """Оновлює UI залежно від вибраного режиму (Нагородження / Подання)."""
        is_submission_mode = (self.mode_toggle_state == 1)

        # ввімкнення/вимкнення груп віджетів за допомогою обходу Sizer'ів
        self._enable_widgets_in_sizer_recursive(self.award_sizer, not is_submission_mode)
        self._enable_widgets_in_sizer_recursive(self.submission_sizer, is_submission_mode)

        # Змінюємо колір тексту StaticBox
        self.award_static_box.SetForegroundColour(wx.NullColour if not is_submission_mode else wx.Colour("gray"))
        self.submission_static_box.SetForegroundColour(wx.NullColour if is_submission_mode else wx.Colour("gray"))

        # Оновлення кольору тексту для StaticText віджетів 
        # Колір для віджетів всередині групи "Нагородження" (якщо блок вимкнений - сірий, інакше - стандартний)
        award_text_color = wx.NullColour if not is_submission_mode else wx.Colour("gray")

        # Перевіряємо існування атрибутів перед використанням 
        if hasattr(self, 'award_label') and self.award_label:
            self.award_label.SetForegroundColour(award_text_color)
        if hasattr(self, 'consignment_label') and self.consignment_label:
             self.consignment_label.SetForegroundColour(award_text_color)
        if hasattr(self, 'consignment_count_label') and self.consignment_count_label:
             self.consignment_count_label.SetForegroundColour(award_text_color)
        if hasattr(self, 'issue_protocols_checkbox') and self.issue_protocols_checkbox:
            self.issue_protocols_checkbox.SetForegroundColour(award_text_color)
            self.issue_protocols_checkbox.Enable(False)
            self.issue_protocols_checkbox.SetValue(False)
            self.is_issue_protocols_filter = False
        # Додайте сюди інші StaticText, які є в групі "Нагородження", якщо вони є

        # Колір для віджетів всередині групи "Подання" (якщо блок вимкнений - сірий, інакше - стандартний)
        submission_text_color = wx.NullColour if is_submission_mode else wx.Colour("gray")

        # Перевіряємо існування атрибутів перед використанням
        # submission_count_label знаходиться в групі "Подання"
        if hasattr(self, 'submission_count_label') and self.submission_count_label:
             self.submission_count_label.SetForegroundColour(submission_text_color)
        # Додайте сюди інші StaticText, які є в групі "Подання", якщо вони є

        # Оновлюємо текст кнопки перемикання (якщо не використовується зображення)
        if not self._or_bmp:
            self.mode_toggle_button.SetLabel(f"Режим: {'Подання' if is_submission_mode else 'Нагородження'}")
        # else: якщо є зображення, текст кнопки очищається

        # --- Зберігаємо ДОДАТКОВЕ оновлення стану залежних віджетів ---
        # Цей пост-процесінг потрібен, щоб переконатися, що комбобокси,
        # стан яких залежить від чекбоксів/радіокнопок всередині групи,
        # мають правильний кінцевий стан Enable ПІСЛЯ того, як вся група була ввімкнена
        # через обхід Sizer'ів.

        is_submission_mode = self.mode_toggle_state == 1

        if not is_submission_mode: # Якщо активний режим "Нагородження"
            # Оновлюємо стан award_name_combo на основі award_by_name_checkbox
            # Enable тільки якщо блок Нагородження активний І чекбокс вибрано
            self.award_name_combo.Enable(self.award_by_name_checkbox.GetValue())
            # Оновлюємо стан consignment_combo на основі радіокнопки "видані"
            # Enable тільки якщо блок Нагородження активний І вибрано "видані"
            is_issued_selected = self.handover_issued_radio.GetValue() # Перевіряємо стан радіокнопки
            self.consignment_combo.Enable(is_issued_selected)
            message = "Нагородження"

        else: # Якщо активний режим "Подання"
            self.consignment_combo.Disable() # виключаємо комбобокс "накладні"
            # Оновлюємо стан specific_submission_combo на основі specific_submission_checkbox
            # Enable тільки якщо блок Подання активний І чекбокс вибрано
            self.specific_submission_combo.Enable(self.specific_submission_checkbox.GetValue())
            message = "Подання"
            # виключаємо чекбокс "протоколи"
            if hasattr(self, 'issue_protocols_checkbox') and self.issue_protocols_checkbox:
                self.issue_protocols_checkbox.Enable(False)
                self.issue_protocols_checkbox.SetValue(False)
                self.is_issue_protocols_filter = False

        self.update_footer_message(message)

        self.Refresh() # Перемалювати елементи, щоб зміни застосувалися
        self.Layout() # Часто корисно після зміни стану віджетів або структури розміщення


    def _enable_widgets_in_sizer_recursive(self, sizer_item_or_sizer_or_window, enable):
        """
        Рекурсивно вмикає/вимикає віджети, обходячи структуру Sizer'ів та Window'ів.
        Призначена для обробки віджетів, розташованих за допомогою Sizer'ів.
        Пропускає StaticText та StaticBox для прямого виклику Enable (їх колір змінюється окремо).
        """
        if isinstance(sizer_item_or_sizer_or_window, wx.SizerItem):
            # Якщо це елемент Sizer'а, отримуємо вікно або вкладений Sizer
            window = sizer_item_or_sizer_or_window.GetWindow()
            sizer = sizer_item_or_sizer_or_window.GetSizer()

            if window:
                # Якщо елемент керує вікном, вмикаємо/вимикаємо його
                # Пропускаємо StaticText, оскільки його Enable не змінює вигляд, тільки колір (який ми вже встановили)
                if not isinstance(window, wx.StaticText):
                     window.Enable(enable)

            if sizer:
                # Якщо елемент керує вкладеним Sizer'ом, рекурсивно викликаємо для цього Sizer'а
                self._enable_widgets_in_sizer_recursive(sizer, enable)

        elif isinstance(sizer_item_or_sizer_or_window, wx.Sizer):
            # Якщо це сам Sizer, обходимо його елементи
            for child_item in sizer_item_or_sizer_or_window.GetChildren():
                self._enable_widgets_in_sizer_recursive(child_item, enable)

        elif isinstance(sizer_item_or_sizer_or_window, wx.Window):
            # Якщо це вікно (наприклад, батьківська панель, або StaticBox),
            # вмикаємо/вимикаємо його (якщо не StaticText/StaticBox)
            if not isinstance(sizer_item_or_sizer_or_window, (wx.StaticText, wx.StaticBox)):
                 sizer_item_or_sizer_or_window.Enable(enable)


    def update_unit_civilian_visibility(self):
        #  Показуємо комбо/мітку підрозділів, якщо вибрано БУДЬ-ЯКУ категорію, КРІМ "Усі особи".
        show_unit_group = self.person_category_filter != PERSON_CATEGORY_ALL

        # ЛОГІКА ДЛЯ ЧЕКБОКСА ЦИВІЛЬНИХ: Показуємо його ТІЛЬКИ якщо вибрано "Усі особи".
        show_civilian_checkbox = self.person_category_filter == PERSON_CATEGORY_ALL

        # Встановлення видимості елементів
        self.unit_label.Show(show_unit_group)
        self.unit_combo.Show(show_unit_group)
        self.civilian_checkbox.Show(show_civilian_checkbox)

        # Якщо чекбокс цивільних ховається, скидаємо його значення та внутрішній фільтр.
        # Цей блок виконується, якщо show_civilian_checkbox == False (тобто, якщо вибрано не "Усі особи")
        if not show_civilian_checkbox:
            # Перевіряємо, чи фільтр був активний, перш ніж його скидати,
            # щоб уникнути зайвих дій, якщо він і так був вимкнений.
            if self.is_civilian_filter: # Перевіряємо ВНУТРІШНІЙ СТАН ФІЛЬТРА
                self.civilian_checkbox.SetValue(False) # Візуально знімаємо галочку (навіть якщо приховано)
                self.is_civilian_filter = False # Скидаємо внутрішній фільтр

        # Вмикаємо/вимикаємо комбобокс підрозділу.
        self.unit_combo.Enable(show_unit_group and not self.is_civilian_filter)

        # Оновлення макету батьківського сайзера
        self.unit_civilian_sizer.Layout() # Оновлюємо горизонтальний сайзер, що містить ці елементи
        self.Layout() # Важливо оновити макет самої панелі


    def update_consignment_combobox_state(self):
        """Вмикає/вимикає комбобокс накладних залежно від статусу вручення."""
        enable_combo = self.award_handover_status in (AWARD_HANDOVER_STATUS_REMAINING, AWARD_HANDOVER_STATUS_ISSUED)
        self.consignment_label.Enable(enable_combo)
        self.consignment_combo.Enable(enable_combo)
        self.consignment_count_label.Enable(enable_combo)
        self.on_consignment_combo_open()
        if not enable_combo:
            self.consignment_combo.Clear()
            self.consignment_combo.SetValue("") # Очистити вибір
            self.consignment_count_label.SetLabel("")


    # --- Обробники подій віджетів ---

    def on_all_time_toggle(self, event):
        """Обробник зміни стану чекбокса 'увесь час'."""
        self._submission_loaded = False
        self.is_all_time_filter = self.all_time_checkbox.GetValue()
        # Вимкнути вибір дати, якщо вибрано "увесь час"
        self.start_date_picker.Enable(not self.is_all_time_filter)
        self.end_date_picker.Enable(not self.is_all_time_filter)

        # Если выбрано "увесь час", используем MIN_DATE_WX и today_wx
        self.start_date = MIN_DATE_WX
        self.end_date = today_wx

        # Застосувати логіку з on_date_period_changed
        self.on_date_period_changed(None)

        # зміна футера
        if self.is_all_time_filter:
            self.update_footer_message(f"Увага. Період вибірки: {self.start_date} - {self.end_date}")
        else:
            self.update_footer_message(DEF_FUT_LABEL)

        if event:
            event.Skip()        

    def on_date_period_changed(self, event):
        """Обробник події зміни дати у DatePickerCtrl."""        
        # Якщо режим "Нагородження" активний, переключити на "призначені"
        if self.mode_toggle_state == 0:
            if self.award_handover_status in (AWARD_HANDOVER_STATUS_REMAINING, AWARD_HANDOVER_STATUS_ISSUED):
                self.on_consignment_combo_open() # оновлюємо стан комбобоксу

        self._submission_loaded = False
        # Тут можна додати додаткову логіку для оновлення звіту чи запиту
        if self.mode_toggle_state == 1:
            self.on_submission_combo_open(None) 
        if event:
            event.Skip()

    def on_posthumous_toggle(self, event):
        """Обробник зміни стану чекбокса 'посмертно'."""
        self._submission_loaded = False
        self.is_posthumous_filter = self.posthumous_checkbox.GetValue()

    def on_person_category_change(self, event, category_value):
        """Обробник вибору категорії особи."""
        if event.GetEventObject().GetValue(): # Переконуємось, що це вибрана кнопка
            self._submission_loaded = False
            self.person_category_filter = category_value
            self.update_unit_civilian_visibility()

    def on_civilian_toggle(self, event):
        """Обробник зміни стану чекбокса '= цивільні'."""
        self.is_civilian_filter = self.civilian_checkbox.GetValue()
        # Вимкнути вибір підрозділу, якщо вибрано цивільних
        self.unit_combo.Enable(not self.is_civilian_filter)
        if self.is_civilian_filter:
            self._submission_loaded = False
            self.unit_combo.SetValue("") # Очистити вибір підрозділу

    def on_handover_status_change(self, event, status_value):
        """Обробник вибору статусу вручення нагороди."""
        if event.GetEventObject().GetValue():
            self.award_handover_status = status_value
            self.update_consignment_combobox_state()

            enable_issue_protocols_checkbox = (status_value == AWARD_HANDOVER_STATUS_ISSUED)

            if hasattr(self, 'issue_protocols_checkbox') and self.issue_protocols_checkbox:
                self.issue_protocols_checkbox.Enable(enable_issue_protocols_checkbox)
                # Якщо чекбокс вимикається, скидаємо його значення, щоб уникнути непередбачених фільтрів
                if not enable_issue_protocols_checkbox:
                    self.issue_protocols_checkbox.SetValue(False)
                    self.is_issue_protocols_filter = False # Оновлюємо внутрішній стан фільтра


    def on_consignment_combo_open(self):
        """Обробник відкриття списку комбобокса накладних. Завантажує дані з БД з урахуванням поточних фільтрів."""
        if not all(hasattr(self, name) for name in ['consignment_combo', 'consignment_count_label']) or not self.cursor:
            return
        # Очищаємо перед завантаженням
        self.consignment_combo.Clear()
        self.consignment_count_label.SetLabel("") 

        try:
            filters = self._get_current_filters()
            query = "SELECT DISTINCT consignment_note FROM meed WHERE consignment_note IS NOT NULL AND consignment_note != ''"
            params = {}

            if filters["mode"] == "awarding":
                if not filters["all_time"]:
                    query += " AND date_decree BETWEEN :start_date AND :end_date"
                    params["start_date"] = filters["start_date"]
                    params["end_date"] = filters["end_date"]
                
                query += " ORDER BY consignment_note DESC"

                self.cursor.execute(query, params)
                cons_notes_raw = self.cursor.fetchall()

                unique_consignment = [""]
                for row in cons_notes_raw:
                    cons_note = str(row[0]).strip()
                    if cons_note not in unique_consignment:
                        unique_consignment.append(cons_note)

                self.consignment_combo.SetItems(unique_consignment)
                self.consignment_count_label.SetLabel(str(len(unique_consignment) - 1))
                
                if hasattr(self, 'consignment_search_helper'):
                    self.consignment_search_helper.set_items(unique_consignment)        

        except Exception as e:
            self.consignment_count_label.SetLabel("ERROR")
        finally:
            pass

    def on_award_rank_selected(self, event):
        """Обробник вибору рангу нагороди."""
        selected_rank = self.ranking_award_combo.GetValue()
        # Якщо вибрано опцію "ранг / назва", перезавантажити список назв з урахуванням рангу
        if self.is_award_by_name_filter:
            self._start_award_names_loading_thread(rank_filter=selected_rank)

    def on_award_by_name_toggle(self, event):
        """Обробник зміни стану чекбокса 'ранг / назва'."""
        if not all(hasattr(self, name) for name in ['award_by_name_checkbox', 'ranking_award_combo', 'award_name_combo', 'award_image']):
            return

        self.is_award_by_name_filter = self.award_by_name_checkbox.GetValue()
        use_name_filter = self.is_award_by_name_filter

        # Якщо використовуємо фільтр за назвою, вимикаємо вибір рангу і вмикаємо вибір назви
        # Якщо НЕ використовуємо фільтр за назвою, вмикаємо вибір рангу і вимикаємо вибір назви
        self.ranking_award_combo.Enable(not use_name_filter)
        self.award_name_combo.Enable(use_name_filter)

        if use_name_filter:
            # Запустити завантаження назв, використовуючи поточний ранг як фільтр
            current_rank_filter = self.ranking_award_combo.GetStringSelection()
            self._start_award_names_loading_thread(rank_filter=current_rank_filter)
        else:
            # Якщо вимкнули фільтр за назвою, очистити комбобокс назв та зображення
            self.award_name_combo.Clear()
            self.award_name_combo.SetValue("")
            self.award_name_combo.Enable(False)
            self._loaded_award_names = [] # Очистити кеш
            self._reset_award_image() # Викликаємо функцію для очищення зображення

    def on_award_name_selected(self, event):
        """ при виборе названия награди визивает функцию обновления изображения """
        selected_award_name = self.award_name_combo.GetValue()
        self._update_award_image(selected_award_name)

    def on_issue_protocols_toggle(self, event):
        """Обробник зміни стану чекбокса 'протоколи видачі'."""
        self.is_issue_protocols_filter = self.issue_protocols_checkbox.GetValue()

    def on_submission_status_change(self, event, status_value):
        """Обробник вибору статусу подання."""
        if event.GetEventObject().GetValue():
            self._submission_loaded = False
            self.submission_status_filter = status_value

    def on_specific_submission_toggle(self, event):
        """Обробник зміни стану чекбокса 'Окреме подання за №'."""
        if not all(hasattr(self, name) for name in ['specific_submission_checkbox', 'specific_submission_combo', 'submission_count_label']):
             return

        self._submission_loaded = False
        
        self.is_specific_submission_filter = self.specific_submission_checkbox.GetValue()
        enable_combobox = self.is_specific_submission_filter
        self.specific_submission_combo.Enable(enable_combobox)

        if not enable_combobox:
            self.specific_submission_combo.Clear()
            self.specific_submission_combo.SetValue("")
            self.submission_count_label.SetLabel("")
        else:
            # Якщо увімкнули, можливо, варто одразу завантажити список
            self.on_submission_combo_open(None) # Імітуємо відкриття

    def on_submission_combo_open(self, event):
        """Обробник відкриття списку комбобокса номерів подань. Завантажує дані з БД з урахуванням поточних фільтрів."""
        if not all(hasattr(self, name) for name in ['specific_submission_combo', 'submission_count_label']) or not self.cursor:
            return

        if self._submission_loaded:
            if event: # Перевіряємо, чи існує event перед Skip
                event.Skip()
            return

        self._submission_loaded = True

        # Очищаємо перед завантаженням
        self.specific_submission_combo.Clear()
        self.submission_count_label.SetLabel("")

        try:
            filters = self._get_current_filters()
            query = "SELECT DISTINCT registration, date_registration FROM presentation WHERE registration IS NOT NULL AND registration != ''"
            params = {}

            if filters["mode"] == "submission":
                if not filters["all_time"]:
                    query += " AND date_registration BETWEEN :start_date AND :end_date"
                    params["start_date"] = filters["start_date"]
                    params["end_date"] = filters["end_date"]

            query += " ORDER BY registration DESC"

            self.cursor.execute(query, params)
            submission_numbers_raw = self.cursor.fetchall()

            unique_submissions = [""]
            for row in submission_numbers_raw:
                submission_number = str(row[0]).strip()
                date_registration = row[1]

                display_string = f"{submission_number} від {date_registration}"

                if display_string not in unique_submissions:
                    unique_submissions.append(display_string)

            self.specific_submission_combo.SetItems(unique_submissions)
            self.submission_count_label.SetLabel(str(len(unique_submissions) - 1))
       
            # Оновлюємо хелпер для подань
            if hasattr(self, 'specific_submission_search_helper'):
                self.specific_submission_search_helper.set_items(unique_submissions)

        except Exception as e:
            self.submission_count_label.SetLabel("ERROR")
        finally:
            pass 

    def on_mode_toggle(self, event):
        """Обробник для кнопки перемикання режиму 'Нагородження / Подання'."""
        if not hasattr(self, 'mode_toggle_button'):
             return

        # Отримуємо новий стан кнопки (True якщо натиснута -> режим Подання)
        is_submission_mode = self.mode_toggle_button.GetValue()
        self.mode_toggle_state = 1 if is_submission_mode else 0

        # Викликаємо метод, який оновить UI (текст кнопки, активність груп)
        self._update_mode_ui()

        # Оновлюємо стан залежних елементів (наприклад, комбобокса накладних)
        self.update_consignment_combobox_state()


    # --- Допоміжні методи ---
    def _get_current_filters(self):
        """Збирає поточні налаштування фільтрів з UI елементів."""
        filters = {
            "mode": "submission" if self.mode_toggle_state == 1 else "awarding",
            "all_time": self.is_all_time_filter,
            "start_date": self.start_date_picker.GetValue().FormatISODate() if not self.is_all_time_filter else None,
            "end_date": self.end_date_picker.GetValue().FormatISODate() if not self.is_all_time_filter else None,
            "posthumous": self.is_posthumous_filter,
            "worker": self.worker_combo.GetValue(),
            "person_category": self.person_category_filter,
            "unit": self.unit_combo.GetValue() if not self.is_civilian_filter else None,
            "civilian": self.is_civilian_filter,
            # Фільтри для режиму Нагородження
            "handover_status": self.award_handover_status if self.mode_toggle_state == 0 else None,
            "consignment_note": self.consignment_combo.GetValue() if self.mode_toggle_state == 0 and self.consignment_combo.IsEnabled() else None,
            "award_rank": self.ranking_award_combo.GetValue() if self.mode_toggle_state == 0 else None,
            "award_by_name": self.is_award_by_name_filter if self.mode_toggle_state == 0 else False,
            "award_name": self.award_name_combo.GetValue() if self.mode_toggle_state == 0 and self.is_award_by_name_filter else None,
            "award_id": self.selected_award_id if self.mode_toggle_state == 0 else None,
            "issue_protocols": self.is_issue_protocols_filter if self.mode_toggle_state == 0 else False,
            # Фільтри для режиму Подання
            "submission_status": self.submission_status_filter if self.mode_toggle_state == 1 else None,
            "specific_submission": self.is_specific_submission_filter if self.mode_toggle_state == 1 else False,
            "submission_number": self.specific_submission_combo.GetValue() if self.mode_toggle_state == 1 and self.is_specific_submission_filter else None,
        }

        if self.is_all_time_filter:
            # Если активирован фильтр "увесь час", передаем значения с 2014-01-01 по текущую дату
            filters["start_date"] = MIN_DATE_DT.strftime('%Y-%m-%d')
            filters["end_date"] = today_dt.strftime('%Y-%m-%d')
        
        return filters

    def _update_award_image(self, award_name):
        """Завантажує та відображає зображення для вибраної нагороди."""
        if not hasattr(self, 'award_image'):
            return

        new_bitmap = None # Переменная для хранения изображения
        self.selected_award_id = None # Переменная для хранения полученного ID

        if award_name:
            try:
                self.cursor.execute("SELECT img, id FROM award WHERE denotation = ?", (award_name,))
                result = self.cursor.fetchone()

                if result and result[0]:
                    image_blob = result[0]
                    award_id = result[1]   # ID награды - второй столбец
                    self.selected_award_id = award_id # Сохраняем полученный ID

                    if image_blob:
                        new_bitmap = load_image_from_blob(image_blob, max_dim=60)

            except Exception as e:
                print(f"Помилка бази даних при отриманні зображення: {e}")

        # Якщо зображення не знайдено або сталася помилка, повернути до початкового стану
        if not new_bitmap or not new_bitmap.IsOk():
            self._reset_award_image()
            return # Важливо вийти з функції, щоб не перезаписувати логотип

        # Оновити StaticBitmap, якщо зображення нагороди було успішно завантажено
        self.award_image.SetBitmap(new_bitmap)
        self.award_image.GetContainingSizer().Layout() # Важливо для оновлення розміру

    def _reset_award_image(self):
        """Повертає зображення нагороди до початкового стану (логотипу)."""
        if hasattr(self, 'award_image'):
            if hasattr(self, '_logo_bmp') and self._logo_bmp and self._logo_bmp.IsOk():
                self.award_image.SetBitmap(self._logo_bmp)
            else:
                # Якщо логотипу немає, встановлюємо порожній або стандартний бітмап
                empty_bitmap = wx.Bitmap(100, 100)
                dc = wx.MemoryDC(empty_bitmap)
                dc.SetBackground(wx.Brush(self.GetBackgroundColour()))
                dc.Clear()
                dc.DrawText("Лого відсутнє", 5, 5)
                dc.SelectObject(wx.NullBitmap)
                self.award_image.SetBitmap(empty_bitmap)
            self.award_image.GetContainingSizer().Layout()


    def on_view_report(self, event=None):
        """Головний обробник кнопки 'Перегляд' із виведенням статусу у футер."""
        # 1. Захист від повторного натискання
        if not self.view_button.IsEnabled():
            return

        # Зберігаємо початкові дані кнопки
        original_label = self.view_button.GetLabel()

        try:
            # 2. Змінюємо стан кнопки та виводимо повідомлення у футер
            self.view_button.Enable(False)
            if hasattr(self.view_button, 'SetBitmap'):
                self.view_button.SetBitmap(wx.NullBitmap)
            self.view_button.SetLabel("Чекайте...")

            # Ваш стандартний трюк з оновленням футера
            self.update_footer_message("Формування звіту, зачекайте будь ласка...")

            # Оновлюємо UI, щоб зміни у футері та на кнопці з'явилися негайно
            wx.Yield()

            # 3. Збирання фільтрів та формування звіту
            filters = self._get_current_filters()
            input_df = getattr(self, 'loaded_input_df', None)

            # Якщо CSV файл завантажено — відкриваємо порівняльний звіт
            if input_df is not None and len(input_df) > 0: 
                report_frame = ComparisonReportFrame(
                    parent=self,
                    db_path=self.db_path,
                    key=self.key,
                    filters=filters,
                    zvit_fields=self.zvit_fields,
                    zvit_dir=self.zvit_dir,
                    input_data=input_df,
                    exel_bmp=self._excel_bmp
                )
                report_frame.Show()
            
            # Якщо CSV немає — звичайний звіт
            else:
                report_window = ReportGeneratorWx(
                    parent=self,
                    db_path=self.db_path,
                    key=self.key,
                    zvit_fields=self.zvit_fields,
                    zvit_dir=self.zvit_dir,
                    filters=filters,
                    exel_bmp=self._excel_bmp
                )
                report_window.Show()

        except Exception as e:
            self.update_footer_message(f"Помилка при формуванні звіту: {e}")
            wx.MessageBox(f"Помилка при формуванні звіту:\n{e}", "Помилка", wx.OK | wx.ICON_ERROR)

        finally:
            # 4. Повертаємо кнопці початковий вигляд та відновлюємо дефолтне повідомлення у футері
            self.view_button.SetLabel(original_label)
            if self._view_bmp and hasattr(self.view_button, 'SetBitmap'):
                self.view_button.SetBitmap(self._view_bmp, wx.LEFT)
            self.view_button.Enable(True)

            # Повертаємо стандартне повідомлення статусу
            self.update_footer_message(DEF_FUT_LABEL)

# Кінець класу Tab4Panel
