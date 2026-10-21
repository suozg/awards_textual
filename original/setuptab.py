import wx
import wx.grid
from wx import DirPickerCtrl
import wx.lib.scrolledpanel as scrolled

import os
import sqlite3
from wx import MessageBox, OK, ICON_INFORMATION, ICON_ERROR, ICON_WARNING
from config import ALL_COLUMN_LABELS, DEF_FUT_LABEL

import io

from database_logic import (
    get_units_and_ranks, # Завантажує доступні підрозділи та ранги. МАЄ ПРИЙМАТИ КУРСОР!
    get_service_settings_data, # Витягує рядок налаштувань сервісу. МАЄ ПРИЙМАТИ КУРСОР!
    connect_to_database # Ваша функція підключення
)

# Індекси стовпців для get_service_settings_data
class ServiceSettingsIndices:
    LOGO = 0
    EXCEL_BUTTON = 1
    VIEW_BUTTON = 2
    OR_BUTTON = 3
    ZVIT_DIR = 4
    ZVIT_FIELDS = 5 # Рядок типу '1,0,1,...'
    SHOW_HELLOU = 6 # 0 або 1
    SERVICE_ID = 7
    SERVICE_PASS = 8
    COOKIES = 9
    IMG_HOMER = 10
    IMG_HOMER2 = 11
    LAST_TIME_CHANGES = 12

# Розмір зображення, який ти хочеш у вікні
LOGO_WIDTH = 150
LOGO_HEIGHT = 150

# --- Клас для вкладки "Настройки" ---
class SettingsPanel(scrolled.ScrolledPanel):
    def __init__(self, parent, conn, cursor, database_path, KEY, fut_place=None, tab4_panel=None, info_panel=None, search_tab=None, kartka_panel=None):

        super().__init__(parent) 

        self.parent = parent # нужно для передачи переменной блокировки пароля из главного окна

        self.tab4_panel = tab4_panel  # Зберігаємо посилання щоб перезавантажувати дані в tab4_panel
        self.kartka_panel = kartka_panel # посилання на KartkaPanel

        self.search_tab = search_tab
        self.info_panel = info_panel

        self.conn = conn
        self.cursor = cursor # Цей курсор можна використовувати для простих речей, але для записів/оновлень краще створювати локальні
        self.db_path = database_path
        self.KEY = KEY # Ключ для доступу до БД, використовується у зміні пароля
        self.fut_place = fut_place
        self.last_footer_message = None

        # --- 1. ЗАВАНТАЖЕННЯ ДАНИХ (без звернення до віджетів) ---

        # 1а. Завантажуємо налаштування сервісу
        self._load_service_settings_data() # Цей метод заповнить self.zvit_dir, self.zvit_fields, self.show_hellou тощо

        # 1б. Обробляємо завантажений рядок zvit_fields в список int
        self._selected_report_fields_flags = [] # Ініціалізація атрибуту
        zvit_fields_str = self.zvit_fields # Беремо завантажене значення з self.zvit_fields

        # Якщо рядок self.zvit_fields виявився None або порожнім після завантаження, використовуємо дефолт
        if not zvit_fields_str:
             # Не показуємо тут MessageBox, якщо помилку вже показав _load_service_settings_data
             default_flags_count = 14
             # Передбачаємо, що останній флаг завжди є, тому +1 до дефолтної кількості стандартних
             zvit_fields_str = '0,' * (default_flags_count) + '0'

        try:
            # Розділяємо рядок за комою та перетворюємо кожен елемент на ціле число
            self._selected_report_fields_flags = [int(flag) for flag in zvit_fields_str.split(',')]

            # Перевіряємо, чи список флагов має очікувану кількість елементів (15)
            expected_flag_count = 15 # 14 стандартних + 1 спеціальний флаг
            while len(self._selected_report_fields_flags) < expected_flag_count:
                 self._selected_report_fields_flags.append(0)
            self._selected_report_fields_flags = self._selected_report_fields_flags[:expected_flag_count]

        except (ValueError, TypeError):
             # Обробляємо помилки, якщо рядок з бази був у некоректному форматі
             MessageBox("Некоректний формат налаштувань колонок звіту. Використовуються налаштування за замовчуванням.", "Помилка конфігурації", ICON_ERROR)
             self._selected_report_fields_flags = [0] * 15 # Дефолтні значення у випадку помилки

        # 1в. Завантажуємо дані списків звань/підрозділів у атрибути даних
        # Ці атрибути потрібні ЛИШЕ для _refresh_global_libs_ui, вони не використовуються on_save_global_vars напряму
        self._loaded_units = ['', 'Створити >'] # Ініціалізація атрибуту
        self._loaded_ranks = ['', 'Створити >'] # Ініціалізація атрибуту
        # Викликаємо метод, який ЛИШЕ завантажує дані, не оновлюючи UI
        self._load_global_libs_data() 

        # --- 2. СТВОРЕННЯ ВІДЖЕТІВ та КОМПОНОВКА ---
        main_sizer = wx.BoxSizer(wx.VERTICAL)

        # Assuming main_sizer is already a wx.BoxSizer(wx.VERTICAL)

        # --- Create a horizontal sizer for the top row ---
        # Це сайзер, який буде містити блок зміни пароля та блок логотипу поруч
        top_horizontal_sizer = wx.BoxSizer(wx.HORIZONTAL)

        # --- Блок зміни пароля ---
        # Внутрішня структура блоку пароля залишається без змін
        password_box = wx.StaticBoxSizer(wx.StaticBox(self, label=" Зміна пароля до бази даних (після дії програма закриється автоматично) "), wx.VERTICAL)
        password_box_gbsizer = wx.GridBagSizer(5, 5)

        # ... (додавання текстових полів пароля - без змін) ...
        password_box_gbsizer.Add(wx.StaticText(password_box.GetStaticBox(), label="ввести старий пароль"), pos=(0, 0), flag=wx.ALIGN_CENTER_VERTICAL | wx.LEFT, border=3)
        self.pass1_ctrl = wx.TextCtrl(password_box.GetStaticBox(), style=wx.TE_PASSWORD | wx.TE_PROCESS_ENTER)
        password_box_gbsizer.Add(self.pass1_ctrl, pos=(0, 1), flag=wx.EXPAND | wx.RIGHT, border=3)

        password_box_gbsizer.Add(wx.StaticText(password_box.GetStaticBox(), label="ввести новий пароль"), pos=(1, 0), flag=wx.ALIGN_CENTER_VERTICAL | wx.LEFT, border=3)
        self.pass2_ctrl = wx.TextCtrl(password_box.GetStaticBox(), style=wx.TE_PASSWORD | wx.TE_PROCESS_ENTER)
        password_box_gbsizer.Add(self.pass2_ctrl, pos=(1, 1), flag=wx.EXPAND | wx.RIGHT, border=3)

        password_box_gbsizer.Add(wx.StaticText(password_box.GetStaticBox(), label="повторити новий пароль"), pos=(2, 0), flag=wx.ALIGN_CENTER_VERTICAL | wx.LEFT, border=3)
        self.pass3_ctrl = wx.TextCtrl(password_box.GetStaticBox(), style=wx.TE_PASSWORD | wx.TE_PROCESS_ENTER)
        self.pass3_ctrl.Bind(wx.EVT_TEXT_ENTER, self.on_change_password)
        password_box_gbsizer.Add(self.pass3_ctrl, pos=(2, 1), flag=wx.EXPAND | wx.RIGHT, border=3)

        self.change_pass_button = wx.Button(password_box.GetStaticBox(), label=" Змінити пароль ")
        self.change_pass_button.Bind(wx.EVT_BUTTON, self.on_change_password)
        password_box_gbsizer.Add(self.change_pass_button, pos=(0, 2), span=(3, 1), flag=wx.EXPAND | wx.ALL, border=5)

        password_box_gbsizer.AddGrowableCol(1)
        password_box.Add(password_box_gbsizer, 0, wx.EXPAND | wx.ALL, 5)

        # Горизонтальний сайзер для двох чекбоксів (Без змін)
        checkbox_row_sizer = wx.BoxSizer(wx.HORIZONTAL)

        # Чекбокс 1 — показувати блок вручення посмертних нагород
        self.show_dead_checkbox = wx.CheckBox(password_box.GetStaticBox(), label="- завжди показувати блок посмертних нагород в КАРТКА")
        self.show_dead_checkbox.Bind(wx.EVT_CHECKBOX, self.on_toggle_show_hello)
        self.show_dead_checkbox.SetValue(self.show_hellou >= 2)
        checkbox_row_sizer.Add(self.show_dead_checkbox, 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 5)

        # Чекбокс 2 — показувати графік і статистику при старті
        self.show_hello_checkbox = wx.CheckBox(password_box.GetStaticBox(), label="- графік при старті")
        self.show_hello_checkbox.Bind(wx.EVT_CHECKBOX, self.on_toggle_show_hello)
        self.show_hello_checkbox.SetValue(self.show_hellou == 1 or self.show_hellou == 3)
        checkbox_row_sizer.Add(self.show_hello_checkbox, 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 5)

        if self.show_hellou == 1 or self.show_hellou == 3: # запускаєм графік на ТАБ1
            self.search_tab.on_t_sizer_click(None)

        # Додаємо горизонтальний сайзер у password_box
        password_box.Add(checkbox_row_sizer, 0, wx.ALL | wx.EXPAND, 5)

        # --- Додаємо password_box до нового горизонтального сайзера ---
        # Використовуємо proportion 0, щоб він займав лише свій природний розмір
        # Вирівнюємо по верхньому краю, на випадок, якщо блок логотипу буде вищий
        top_horizontal_sizer.Add(password_box, 0, wx.EXPAND | wx.ALL, 5)

        top_horizontal_sizer.AddStretchSpacer(1)

        # --- Блок логотипу ---
        # Внутрішня структура блоку логотипу залишається без змін
        logo_box = wx.StaticBoxSizer(wx.StaticBox(self, label=" Логотип організації "), wx.VERTICAL)

        # Статичне зображення (пусте на початку)
        self.logo_bitmap = wx.StaticBitmap(logo_box.GetStaticBox(), bitmap=self.logo_bmp)
        self.logo_bitmap.SetMinSize((LOGO_WIDTH, LOGO_HEIGHT))  # фіксований розмір
        logo_box.Add(self.logo_bitmap, 0, wx.ALL | wx.ALIGN_CENTER, 5)

        # Горизонтальний контейнер для FilePicker та кнопки
        logo_controls_sizer = wx.BoxSizer(wx.HORIZONTAL)

        # Кнопка або FilePicker для вибору файлу
        self.logo_file_picker = wx.FilePickerCtrl(
            logo_box.GetStaticBox(),
            message="Оберіть зображення логотипу",
            wildcard="Зображення (*.png)|*.png"
        )

        self.logo_file_picker.Bind(wx.EVT_FILEPICKER_CHANGED, self.on_logo_selected)
        logo_controls_sizer.Add(self.logo_file_picker, 1, wx.EXPAND | wx.ALL, 5)

        # Кнопка "Зберегти"
        self.save_logo_button = wx.Button(logo_box.GetStaticBox(), label="Зберегти")
        self.save_logo_button.Bind(wx.EVT_BUTTON, self.on_save_logo)
        logo_controls_sizer.Add(self.save_logo_button, 0, wx.ALL, 5)

        # Додаємо горизонтальний контейнер у logo_box
        logo_box.Add(logo_controls_sizer, 0, wx.EXPAND)


        # --- Додаємо logo_box до нового горизонтального сайзера ---
        # Використовуємо proportion 0, вирівнюємо по верхньому краю
        top_horizontal_sizer.Add(logo_box, 0, wx.ALL | wx.ALIGN_TOP, 5) # Використовуйте ALIGN_TOP тут

        # --- Додаємо новий горизонтальний сайзер до головного сайзера ПЕРШИМ ---
        # Сам горизонтальний сайзер може розтягуватися по горизонталі, щоб заповнити ширину вікна
        main_sizer.Add(top_horizontal_sizer, 0, wx.EXPAND | wx.ALL, 5)


        # --- Блок настройки отчетов ---
        report_settings_box = wx.StaticBoxSizer(wx.StaticBox(self, label=" Налаштування звітів "), wx.VERTICAL)

        # Путь сохранения отчетов (Без змін)
        dir_picker_sizer = wx.BoxSizer(wx.HORIZONTAL)
        dir_picker_sizer.Add(wx.StaticText(report_settings_box.GetStaticBox(), label=" Місце збереження файлів EXEL "), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5) # OK
        # Встановлення початкового значення з self.zvit_dir...
        self.report_dir_picker = DirPickerCtrl(report_settings_box.GetStaticBox(), path=self.zvit_dir if self.zvit_dir else '', style=wx.DIRP_USE_TEXTCTRL | wx.DIRP_DIR_MUST_EXIST)
        self.report_dir_picker.Bind(wx.EVT_DIRPICKER_CHANGED, self.on_report_dir_changed)
        dir_picker_sizer.Add(self.report_dir_picker, 1, wx.EXPAND)

        report_settings_box.Add(dir_picker_sizer, 0, wx.EXPAND | wx.ALL, 5)
        report_settings_box.Add(wx.StaticText(report_settings_box.GetStaticBox(), label=" Наповнення таблиць "), 0, wx.ALL | wx.ALIGN_LEFT, 5) # OK

        # --- (додавання чекбоксів колонок) ---
        num_cols_per_row_report = 5
        report_cols_grid_sizer = wx.GridSizer(0, num_cols_per_row_report, 5, 5)
        self._report_column_checkboxes = []
        num_standard_cols_report = 14 # Кількість стандартних колонок

        for i in range(num_standard_cols_report):
            # Використовуємо ALL_COLUMN_LABELS для тексту чекбокса
            col_label_text = ALL_COLUMN_LABELS[i] if i < len(ALL_COLUMN_LABELS) else f"Колонка {i}"
            checkbox = wx.CheckBox(report_settings_box.GetStaticBox(), label=col_label_text)
            checkbox.SetToolTip(col_label_text) # Додаємо Tooltip

            # Встановлюємо початкове значення з self._selected_report_fields_flags
            if i < len(self._selected_report_fields_flags) and self._selected_report_fields_flags[i] == 1:
                    checkbox.SetValue(True)

            self._report_column_checkboxes.append(checkbox)
            report_cols_grid_sizer.Add(checkbox, 0, wx.ALIGN_LEFT | wx.ALL, 1)

        # Чекбокси РНОКПП та Дати народження
        self.rno_checkbox = wx.CheckBox(report_settings_box.GetStaticBox(), label=" РНОКПП")
        self.rno_checkbox.SetToolTip(ALL_COLUMN_LABELS[15] if 15 < len(ALL_COLUMN_LABELS) else "РНОКПП") # Tooltip
        self.dob_checkbox = wx.CheckBox(report_settings_box.GetStaticBox(), label=" Дата народження")
        self.dob_checkbox.SetToolTip(ALL_COLUMN_LABELS[16] if 16 < len(ALL_COLUMN_LABELS) else "Дата народження") # Tooltip

        # Встановлення початкового значення для РНОКПП та Дати народження
        last_flag_index = 14 # Це індекс останнього флага у списку _selected_report_fields_flags
        last_flag_value = self._selected_report_fields_flags[last_flag_index] if last_flag_index < len(self._selected_report_fields_flags) else 0

        if last_flag_value in (1, 3): # 1 = тільки РНОКПП, 3 = РНОКПП + ДН
            self.rno_checkbox.SetValue(True)
        if last_flag_value in (2, 3): # 2 = тільки ДН, 3 = РНОКПП + ДН
            self.dob_checkbox.SetValue(True)

        report_cols_grid_sizer.Add(self.rno_checkbox, 0, wx.ALIGN_LEFT | wx.ALL, 1)
        report_cols_grid_sizer.Add(self.dob_checkbox, 0, wx.ALIGN_LEFT | wx.ALL, 1)

        # Додаємо порожні комірки, щоб вирівняти чекбокси по сітці
        while report_cols_grid_sizer.GetItemCount() % num_cols_per_row_report != 0:
            report_cols_grid_sizer.AddStretchSpacer(1) # Додається до grid sizer

        # --- Створюємо горизонтальний сайзер для сітки чекбоксів та кнопки ---
        report_checkboxes_and_button_sizer = wx.BoxSizer(wx.HORIZONTAL)

        # Додаємо сітку чекбоксів до горизонтального сайзера
        # Використовуємо proportion 1, щоб сітка займала більшу частину простору, відсуваючи кнопку праворуч
        # Також використовуємо wx.EXPAND, щоб елементи в сітці (чекбокси) правильно розтягувалися/вирівнювалися
        report_checkboxes_and_button_sizer.Add(report_cols_grid_sizer, 1, wx.EXPAND | wx.ALL, 5) # Використовуйте EXPAND тут

        # Створюємо кнопку "Зберегти"
        save_report_cols_button = wx.Button(report_settings_box.GetStaticBox(), label="Встановити")
        save_report_cols_button.Bind(wx.EVT_BUTTON, self.on_save_report_column_selection)

        report_checkboxes_and_button_sizer.Add(save_report_cols_button, 0, wx.LEFT | wx.ALL | wx.EXPAND, 5) 
        # Використовуйте ALIGN_CENTER_VERTICAL

        # --- Додаємо новий горизонтальний сайзер до report_settings_box ---
        # Цей рядок замінює окреме додавання report_cols_grid_sizer та save_report_cols_button
        report_settings_box.Add(report_checkboxes_and_button_sizer, 0, wx.EXPAND | wx.ALL, 5) # Додайте цей складений сайзер
        
        main_sizer.Add(report_settings_box, 0, wx.EXPAND | wx.ALL, 5)


        # --- Блок редагування глобальних змінних ---
        # Додаємо цей блок після report_settings_box
        # Використовуємо self._loaded_ranks та self._loaded_units для початкового заповнення комбобоксів
        global_vars_box = wx.StaticBoxSizer(wx.StaticBox(self, label=" Назви підрозділів/звання (виберіть зі списку значення і введіть нові дані в полі праворуч, або позначте щоб видалити) "), wx.VERTICAL)
        global_vars_grid_sizer = wx.GridBagSizer(5, 5)

        # Секция "Звания"
        global_vars_grid_sizer.Add(wx.StaticText(global_vars_box.GetStaticBox(), label="звання"), pos=(0, 0), flag=wx.ALIGN_CENTER_VERTICAL|wx.LEFT, border=3)
        self.rank_combobox = wx.ComboBox(global_vars_box.GetStaticBox(), style=wx.CB_READONLY, choices=self._loaded_ranks)
        self.rank_combobox.Bind(wx.EVT_COMBOBOX, self.on_select_global_var)
        global_vars_grid_sizer.Add(self.rank_combobox, pos=(0, 1), flag=wx.EXPAND|wx.RIGHT, border=3)

        self.rank_entry = wx.TextCtrl(global_vars_box.GetStaticBox())
        global_vars_grid_sizer.Add(self.rank_entry, pos=(0, 2), flag=wx.EXPAND|wx.RIGHT, border=3)

        self.rank_delete_checkbox = wx.CheckBox(global_vars_box.GetStaticBox(), label="- видалити")
        self.rank_delete_checkbox.Bind(wx.EVT_CHECKBOX, self.on_global_var_delete_check)
        global_vars_grid_sizer.Add(self.rank_delete_checkbox, pos=(0, 3), flag=wx.ALIGN_CENTER_VERTICAL|wx.RIGHT, border=3)

        # Секция "Підрозділи"
        global_vars_grid_sizer.Add(wx.StaticText(global_vars_box.GetStaticBox(), label="підрозділ"), pos=(1, 0), flag=wx.ALIGN_CENTER_VERTICAL|wx.LEFT, border=3)

        self.unit_combobox = wx.ComboBox(global_vars_box.GetStaticBox(), style=wx.CB_READONLY, choices=self._loaded_units)
        self.unit_combobox.Bind(wx.EVT_COMBOBOX, self.on_select_global_var)
        global_vars_grid_sizer.Add(self.unit_combobox, pos=(1, 1), flag=wx.EXPAND | wx.ALIGN_CENTER_VERTICAL, border=5)

        self.unit_entry = wx.TextCtrl(global_vars_box.GetStaticBox())
        global_vars_grid_sizer.Add(self.unit_entry, pos=(1, 2), flag=wx.EXPAND | wx.RIGHT, border=3)

        self.unit_delete_checkbox = wx.CheckBox(global_vars_box.GetStaticBox(), label="- видалити")
        self.unit_delete_checkbox.Bind(wx.EVT_CHECKBOX, self.on_global_var_delete_check)
        global_vars_grid_sizer.Add(self.unit_delete_checkbox, pos=(1, 3), flag=wx.ALIGN_CENTER_VERTICAL | wx.RIGHT | wx.BOTTOM, border=10)

        self.save_global_vars_button = wx.Button(global_vars_box.GetStaticBox(), label="Зберегти")
        self.save_global_vars_button.Bind(wx.EVT_BUTTON, self.on_save_global_vars)
        global_vars_grid_sizer.Add(self.save_global_vars_button, pos=(0, 4), span=(2, 1), flag=wx.EXPAND | wx.LEFT | wx.BOTTOM, border=10)

        clear_global_vars_button = wx.Button(global_vars_box.GetStaticBox(), label="Очистити")
        clear_global_vars_button.Bind(wx.EVT_BUTTON, self.on_clear_global_vars)
        global_vars_grid_sizer.Add(clear_global_vars_button, pos=(0, 5), span=(2, 1), flag=wx.EXPAND | wx.LEFT | wx.BOTTOM, border=10)

        global_vars_grid_sizer.AddGrowableCol(1)
        global_vars_grid_sizer.AddGrowableCol(2)

        global_vars_box.Add(global_vars_grid_sizer, 1, wx.EXPAND | wx.ALL, 5)
        main_sizer.Add(global_vars_box, 1, wx.EXPAND | wx.ALL, 5)


        # Встановлюємо зицери
        self.SetSizer(main_sizer)

        self.SetupScrolling() # <--- Цей метод робить вікно прокручуваним

        # --- Встановлення початкового стану елементів керування "Глобальні змінні" ---
        # У початковому стані комбобокси мають порожнє значення, поля вводу активні та порожні,
        # чекбокси видалення неактивні, кнопка "Зберегти" неактивна.
        self._update_global_vars_ui_state()


    # --- Внутрішня функція для завантаження налаштувань сервісу (ДАНИХ) ---
    # Викликається ОДИН РАЗ на початку __init__
    def _load_service_settings_data(self): # Перейменовано для ясності
        """Завантажує налаштування сервісу з таблиці 'service_' в атрибути даних."""
        cursor = None # Використовуємо локальний курсор
        settings_row = None # Ініціалізуємо змінну

        try:
            cursor = self.conn.cursor() # Створюємо локальний курсор
            # Викликаємо зовнішню функцію, передаючи курсор
            # get_service_settings_data має повертати None, якщо немає даних
            settings_row = get_service_settings_data(cursor)

        except Exception as e: # Ловимо можливі помилки при завантаженні
            MessageBox(f"Помилка завантаження налаштувань сервісу: {e}\nВикористовуються значення за замовчуванням.", "Помилка", ICON_WARNING)
            # settings_row залишається None або старим значенням, що обробляється далі

        finally:
            if cursor:
                cursor.close() # Закриваємо локальний курсор

        # Ініціалізуємо атрибути значеннями за замовчуванням
        self.zvit_dir = ''
        self.zvit_fields = '' # Дефолтний порожній рядок
        self.show_hellou = 0
        self.service_id = None
        self.service_pass = None
        self.cookies = None
        self.last_time_changes = None
        # Ініціалізація атрибутів для BMP, якщо вони є (якщо є в ServiceSettingsIndices)
        self.logo_bmp = None
        # self.img_homer_bmp = None
        # self.img_homer2_bmp = None

        if settings_row: # Якщо дані завантажені успішно
            indices = ServiceSettingsIndices
            # Заповнюємо атрибути з завантаженого рядка, перевіряючи індекси та тип даних
            if indices.ZVIT_DIR < len(settings_row) and settings_row[indices.ZVIT_DIR] is not None:
                 self.zvit_dir = str(settings_row[indices.ZVIT_DIR])
            if indices.ZVIT_FIELDS < len(settings_row) and settings_row[indices.ZVIT_FIELDS] is not None:
                 self.zvit_fields = str(settings_row[indices.ZVIT_FIELDS])
            if indices.SHOW_HELLOU < len(settings_row) and settings_row[indices.SHOW_HELLOU] is not None:
                 try:
                    self.show_hellou = int(settings_row[indices.SHOW_HELLOU])
                 except (ValueError, TypeError):
                    self.show_hellou = 0 # Дефолт у випадку некоректного значення в БД
            if indices.SERVICE_ID < len(settings_row) and settings_row[indices.SERVICE_ID] is not None:
                 self.service_id = settings_row[indices.SERVICE_ID] # Залишаємо як є, може бути int або str
            if indices.SERVICE_PASS < len(settings_row) and settings_row[indices.SERVICE_PASS] is not None:
                 self.service_pass = settings_row[indices.SERVICE_PASS]
            if indices.COOKIES < len(settings_row) and settings_row[indices.COOKIES] is not None:
                 self.cookies = settings_row[indices.COOKIES] # Залишаємо як є (може бути BLOB або str)
            if indices.LAST_TIME_CHANGES < len(settings_row) and settings_row[indices.LAST_TIME_CHANGES] is not None:
                 self.last_time_changes = settings_row[indices.LAST_TIME_CHANGES] # Залишаємо як є

            # Завантаження — BLOB из базы
            logo_bytes = settings_row[indices.LOGO]
            if logo_bytes:
                stream = io.BytesIO(logo_bytes)
                image = wx.Image(stream, wx.BITMAP_TYPE_PNG)

                # Оригинальные размеры изображения
                img_w, img_h = image.GetSize()

                # Максимальные размеры
                max_w, max_h = LOGO_WIDTH, LOGO_HEIGHT

                # Вычисляем коэффициент масштабирования
                scale = min(max_w / img_w, max_h / img_h)

                # Новый размер с сохранением пропорций
                new_w = int(img_w * scale)
                new_h = int(img_h * scale)

                # Масштабируем
                image = image.Scale(new_w, new_h, wx.IMAGE_QUALITY_HIGH)
                self.logo_bmp = wx.Bitmap(image)
            else:
                self.logo_bmp = wx.Bitmap(LOGO_WIDTH, LOGO_HEIGHT)



    # --- Внутрішня функція для завантаження списків звань/підрозділів ---
    # Викликається ОДИН РАЗ на початку __init__ ТА ПІСЛЯ збереження змін
    def _load_global_libs_data(self):
        """Завантажує списки звань і підрозділів з БД в атрибути даних. Використовує self.conn."""

        # Очищаємо попередні дані
        self._loaded_units = ['', 'Створити >']
        self._loaded_ranks = ['', 'Створити >']

        cursor = None # Використовуємо локальний курсор
        try:
            cursor = self.conn.cursor() # Створюємо локальний курсор
            # Викликаємо зовнішню функцію, передаючи курсор
            # get_units_and_ranks має приймати курсор і не закривати його
            loaded_ranks_from_db, loaded_units_from_db = get_units_and_ranks(cursor)

            # Додаємо завантажені значення до атрибутів ДАНИХ, перетворюючи на str та видаляючи пробіли
            if loaded_units_from_db: # Перевіряємо, чи список не None/порожній
                 self._loaded_units.extend([str(u).strip() for u in loaded_units_from_db if u is not None and str(u).strip() != ''])
            if loaded_ranks_from_db:
                 self._loaded_ranks.extend([str(r).strip() for r in loaded_ranks_from_db if r is not None and str(r).strip() != ''])

            # Видаляємо дублікати (хоча get_units_and_ranks має це робити або DB має UNIQUE constraint)
            self._loaded_units = list(dict.fromkeys(self._loaded_units))
            self._loaded_ranks = list(dict.fromkeys(self._loaded_ranks))

            # Сортуємо атрибути ДАНИХ (пуста строка і строка 'Створити >' мають залишатись зверху)
            loaded_units_sorted = sorted(self._loaded_units[2:]) if len(self._loaded_units) > 2 else []
            self._loaded_units = ['', 'Створити >'] + loaded_units_sorted

            loaded_ranks_sorted = sorted(self._loaded_ranks[2:]) if len(self._loaded_ranks) > 2 else []
            self._loaded_ranks = ['', 'Створити >'] + loaded_ranks_sorted


        except Exception as e:
            MessageBox(f"Помилка завантаження списків звань/підрозділів: {e}", "Помилка", OK | ICON_ERROR)
            # Встановлюємо заглушки в атрибути ДАНИХ у випадку помилки
            self._loaded_units = ["", "(Помилка завантаження)"]
            self._loaded_ranks = ["", "(Помилка завантаження)"]

        finally:
            if cursor:
                cursor.close() # Закриваємо локальний курсор


    # --- Метод для ПОВНОГО оновлення списків звань/підрозділів у КОМБОБОКСАХ UI ---
    # Цей метод викликається ПІСЛЯ збереження змін (з on_save_global_vars)
    def _refresh_global_libs_ui(self):
        """Перезавантажує дані звань/підрозділів та оновлює комбобокси на UI."""

        # Перезавантажуємо дані в атрибути self._loaded_units та self._loaded_ranks
        self._load_global_libs_data()

        # Обновляем значения в КОМБОБОКСАХ на этой панели
        # ЦЕ БЕЗПЕЧНО, бо комбобокси гарантовано існують після створення віджетів в __init__
        self.unit_combobox.SetItems(self._loaded_units) 
        self.rank_combobox.SetItems(self._loaded_ranks) 

        # Сбрасываем выбор в комбобоксах на первый элемент (пустой)
        # on_clear_global_vars робить це і викликає _update_global_vars_ui_state
        self.on_clear_global_vars()

        # Якщо потрібно оновити комбобокси в інших частинах UI, зробіть це тут.
        # Наприклад, викликати метод батьківського фрейму, який оновлює інші панелі.

        if self.kartka_panel: 
            self.kartka_panel.refresh_data_after_change_setuptab(self._loaded_ranks, self._loaded_units)
        
        wx.CallAfter(self.update_footer_message, self.last_footer_message)


    # --- метод для керування станом елементів керування "Глобальні змінні" ---
    def _update_global_vars_ui_state(self):
        """
        Оновлює стан (Enable/Disable, Value) елементів керування
        для редагування глобальних змінних (звання, підрозділи)
        на основі поточного вибору в комбобоксах та стану чекбоксів.
        """
        selected_rank = self.rank_combobox.GetValue()
        delete_rank_checked = self.rank_delete_checkbox.GetValue()

        selected_unit = self.unit_combobox.GetValue()
        delete_unit_checked = self.unit_delete_checkbox.GetValue()

        # --- Логіка для елементів "Звання" ---
        # Поле вводу звання завжди НЕ активне, 
        self.rank_entry.Enable(False) # Поле активне для введення/редагування

        # Чекбокс "видалити" для звання активний лише якщо щось обрано у комбобоксі
        self.rank_delete_checkbox.Enable(selected_rank != '' and selected_rank != 'Створити >')
        self.rank_entry.Enable(selected_rank != '')

        # Якщо обрали значення 'Створити >' , знімаємо галочку "видалити", бо видаляти нічого
        if selected_rank == 'Створити >':
            self.rank_delete_checkbox.SetValue(False)

        # Встановлюємо значення поля вводу
        if selected_rank != '' and selected_rank != 'Створити >':
            # Якщо обрано існуюче звання, копіюємо його у поле вводу
            self.rank_entry.SetValue(selected_rank)

        # --- Логіка для елементів "Підрозділ" ---
        self.unit_entry.Enable(False) # Поле НЕ активне для введення/редагування

        self.unit_delete_checkbox.Enable(selected_unit != '' and selected_unit != 'Створити >')
        self.unit_entry.Enable(selected_unit != '')

        if selected_unit == 'Створити >':
            self.unit_delete_checkbox.SetValue(False)

        if selected_unit != '' and selected_unit != 'Створити >':
            self.unit_entry.SetValue(selected_unit)

        # --- Логіка для кнопки "Зберегти" ---
        rank_change_pending = (selected_rank != '' or delete_rank_checked) 
        unit_change_pending = (selected_unit != '' or delete_unit_checked) 

        self.save_global_vars_button.Enable(rank_change_pending or unit_change_pending)


    def on_logo_selected(self, event):
        """ метод загрузки логотипа """
        path = self.logo_file_picker.GetPath()
        if path:
            image = wx.Image(path, wx.BITMAP_TYPE_ANY)
            
            # Оригінальні розміри
            img_w, img_h = image.GetSize()
            
            # Максимальні розміри
            max_w, max_h = LOGO_WIDTH, LOGO_HEIGHT
            
            # Масштаб із збереженням пропорцій
            scale = min(max_w / img_w, max_h / img_h)
            new_w = int(img_w * scale)
            new_h = int(img_h * scale)
            
            image = image.Scale(new_w, new_h, wx.IMAGE_QUALITY_HIGH)
            self.logo_bitmap.SetBitmap(wx.Bitmap(image))
            self.Layout()  # оновити розмітку



    def on_save_logo(self, event):
        path = self.logo_file_picker.GetPath()
        if not path:
            wx.MessageBox("Не вибрано файл логотипу", "Помилка", wx.OK | wx.ICON_ERROR)
            return

        cursor = None
        try:
            with open(path, 'rb') as f:
                logo_data = f.read()

            cursor = self.conn.cursor() # Используем постоянное соединение

            # Припускаємо, що запис уже є, і потрібно лише оновити
            cursor.execute("UPDATE service_ SET logo = ? WHERE id = 1", (logo_data,))

            # Якщо запису ще немає, замість UPDATE треба INSERT
            if cursor.rowcount == 0:
                cursor.execute("INSERT INTO service_ (id, logo) VALUES (1, ?)", (logo_data,))
            self.conn.commit()

            wx.MessageBox("Логотип збережено до бази!", "Успіх", wx.OK | wx.ICON_INFORMATION)

        except Exception as e:
            wx.MessageBox(f"Помилка збереження: {e}", "Помилка", wx.OK | wx.ICON_ERROR)

        finally:
            if cursor:
                cursor.close() # Закриваємо локальний курсор

            self.last_footer_message = "Змінено логотип"
            wx.CallAfter(self.update_footer_message, self.last_footer_message)

            # Вызываем обновление логотипа в search_tab и info
            if self.search_tab:
                wx.CallAfter(self.search_tab.refresh_logo)  # Обновляем логотип на вкладке поиска
            if self.info_panel:
                wx.CallAfter(self.info_panel.refresh_logo)  # Обновляем логотип на вкладке информации
            if self.kartka_panel:
                wx.CallAfter(self.kartka_panel.refresh_logo) #оновлення для KartkaPanel

            # оновлюємо налаштування для вкладки ЗВІТ
            if self.tab4_panel:
                wx.CallAfter(self.tab4_panel.refresh_tree)


    def on_change_password(self, event):
        self.parent.must_change_password = True
        self.change_pass_button.SetLabel(" ЧЕКАЙТЕ! ")
        self.update_footer_message(f"Зміна паролю ...")
        wx.GetApp().Yield()  # Перемалювати GUI
        wx.CallLater(100, self._do_change_password)  # Відкладаємо виконання основної операції на 100 мс


    def _do_change_password(self):
        """Обработчик кнопки "Змінити пароль". Использует отдельное соединение через connect_to_database."""

        old_pass = self.pass1_ctrl.GetValue()
        new_pass1 = self.pass2_ctrl.GetValue()
        new_pass2 = self.pass3_ctrl.GetValue()

        if not new_pass1 or not new_pass2:
            MessageBox("Порожні паролі неприйнятні.", "Увага!", OK | ICON_INFORMATION)
            return
        if new_pass1 != new_pass2:
            MessageBox("Нові паролі не збігаються.", "Увага!", OK | ICON_INFORMATION)
            return
        if old_pass == new_pass1:
            MessageBox("Новий пароль такий же як і старий.", "Увага!", OK | ICON_INFORMATION)
            return           

        temp_db = None
        temp_cursor = None
        try:
            # Используем вашу функцию для создания временного соединения
            # connect_to_database должна обработать PRAGMA key и вернуть None,None при ошибке
            temp_db, temp_cursor = connect_to_database(old_pass, self.db_path)

            if temp_db is None or temp_cursor is None:
                MessageBox("Введено невірний старий пароль.", "Увага!", OK | ICON_WARNING)
                return

            # Выполняем rekey операцию на временном соединении
            temp_cursor.execute(f"PRAGMA rekey = '{new_pass2}';")
            temp_db.commit()

            # --- УСПЕХ ---
            self.last_footer_message = " Буде автовихід "
            wx.CallAfter(self.change_pass_button.SetLabel, self.last_footer_message)  # Новый текст на кнопке
            wx.CallAfter(self.update_footer_message, self.last_footer_message)

            MessageBox("Пароль бази даних успішно змінено. \nПотрібен перезапуск програми.", "Успіх!", OK | ICON_INFORMATION)

            # --- ДЕЙСТВИЯ ПОСЛЕ СМЕНЫ ПАРОЛЯ ---
            # 1. Очистить поля ввода пароля
            self.pass1_ctrl.SetValue("")
            self.pass2_ctrl.SetValue("")
            self.pass3_ctrl.SetValue("")

        except Exception as e: # Ловим исключения
            MessageBox(f"Помилка при зміні паролю: {e}", "Помилка", OK | ICON_ERROR)
            if temp_db: # Якщо з'єднання було встановлено, але rekey не пройшов, потрібно спробувати відкотити транзакцію
                 temp_db.rollback()

        finally:
            # Всегда закрываем ВРЕМЕННОЕ соединение и курсор
            if temp_cursor:
                temp_cursor.close()
            if temp_db:
                temp_db.close()

            wx.CallAfter(wx.Exit)


    def on_toggle_show_hello(self, event):
        """Обработчик чекбокса показа блока посмертних нагород """
        state_1 = self.show_hello_checkbox.GetValue()
        state_2 = self.show_dead_checkbox.GetValue()

        if not state_1: # переключаем график с помощью чекбокса
            self.search_tab.clear_tab1(None)
        else:
            self.search_tab.on_t_sizer_click(None)

        self.last_footer_message = "Увімкнено"

        if state_1 and state_2:
            state_onoff = 3      
            self.last_footer_message += " графік при старті та блок посмертні нагородження в КАРТКА" 
        elif state_1:
            state_onoff = 1
            self.last_footer_message += " графік при старті" 
        elif state_2:
            state_onoff = 2
            self.last_footer_message += " блок посмертні нагородження в КАРТКА"
        else:
            state_onoff = 0
            self.last_footer_message = "Скасовано показ графіка та блоку посмертних нагороджень"

        self.show_hellou = state_onoff

        self.update_show_hellou_in_db(self.show_hellou)

        wx.CallAfter(self.update_footer_message, self.last_footer_message)


    def update_show_hellou_in_db(self, value):
        cursor = None
        try:
            cursor = self.conn.cursor()
            cursor.execute("UPDATE service_ SET show_hellou = ? WHERE id = 1", (value,))
            self.conn.commit()
        except Exception as e:
            self.conn.rollback()
            MessageBox(f"Невідома помилка при збереженні налаштування статистики: {e}", "Помилка", wx.OK | wx.ICON_ERROR)
        finally:
            if cursor:
                cursor.close()


    def on_report_dir_changed(self, event):
        """Обработчик выбора папки для сохранения отчетов. Использует self.conn."""
        directory = self.report_dir_picker.GetPath()
        # Додаткова перевірка: чи шлях дійсно змінився і чи він коректний (існує)
        if not directory or not os.path.isdir(directory):
            MessageBox("Обрано некоректний шлях.", "Увага", OK | ICON_WARNING)
            # Можливо, варто повернути попереднє значення, якщо воно було коректним
            self.report_dir_picker.SetPath(self.zvit_dir if self.zvit_dir else '') # Відновлюємо попередній шлях
            return

        self.zvit_dir = directory

        cursor = None
        try:
            cursor = self.conn.cursor() # Используем постоянное соединение
            cursor.execute("UPDATE service_ SET zvit_dir = ? WHERE id = 1", (self.zvit_dir,)) # Додано WHERE id = 1
            self.conn.commit()

        except Exception as e:
            self.conn.rollback() # Відкат у випадку помилки
            MessageBox(f"Невідома помилка при збереженні шляху звітів: {e}", "Помилка", OK | ICON_ERROR)
        finally:
            if cursor:
                cursor.close()
            self.last_footer_message=f"Змінено шлях збереження {self.zvit_dir}"

            wx.CallAfter(self.update_footer_message, self.last_footer_message)

            # оновлюємо налаштування для вкладки ЗВІТ
            if self.tab4_panel:
                wx.CallAfter(self.tab4_panel.refresh_tree)


    def on_save_report_column_selection(self, event):
        """Обработчик кнопки "Зберегти вибір" для колонок отчета. Использует self.conn."""
        selected_flags_list = []
        num_standard_cols_report = 14
        for i in range(num_standard_cols_report):
            if i < len(self._report_column_checkboxes):
                checkbox = self._report_column_checkboxes[i]
                selected_flags_list.append("1" if checkbox.GetValue() else "0")
            else:
                selected_flags_list.append("0") # Додаємо 0 для відсутніх чекбоксів (якщо ALL_COLUMN_LABELS коротший)

        # Обробка останнього флага для РНОКПП та Дати народження
        last_flag_value = 0
        if self.rno_checkbox.GetValue() and not self.dob_checkbox.GetValue():
             last_flag_value = 1 # Тільки РНОКПП
        elif not self.rno_checkbox.GetValue() and self.dob_checkbox.GetValue():
             last_flag_value = 2 # Тільки Дата народження
        elif self.rno_checkbox.GetValue() and self.dob_checkbox.GetValue():
             last_flag_value = 3 # Обидва
        # Якщо жоден не обрано, last_flag_value = 0 (початкове значення)

        selected_flags_list.append(str(last_flag_value)) # Додаємо останній флаг до списку

        selected_fields_zvit_str = ",".join(selected_flags_list)

        try:
            # Оновлюємо внутрішній атрибут _selected_report_fields_flags після збереження
            # Це потрібно, якщо логіка UI або інші частини коду залежать від актуального стану цього атрибуту
            self._selected_report_fields_flags = [int(flag) for flag in selected_flags_list]
            expected_flag_count = 15 # Очікуємо 15 флагов
            # Заповнюємо нулями, якщо список виявився коротшим (хоча selected_flags_list тепер має 15 елементів)
            while len(self._selected_report_fields_flags) < expected_flag_count: self._selected_report_fields_flags.append(0)
            # Обрізаємо, якщо список виявився довшим (не повинно статися з поточною логікою)
            self._selected_report_fields_flags = self._selected_report_fields_flags[:expected_flag_count]

        except ValueError:
            # Ця помилка менш ймовірна після формування рядка з чекбоксів, але залишаємо
            MessageBox("Помилка формату обраних колонок. Налаштування можуть бути некоректними.", "Помилка", OK | ICON_WARNING)
            # У випадку помилки форматування, можна скинути внутрішній атрибут до дефолту або попереднього значення

        cursor = None
        try:
            cursor = self.conn.cursor() # Используем постоянное соединение
            cursor.execute("UPDATE service_ SET zvit_fields = ? WHERE id = 1", (selected_fields_zvit_str,)) 
            self.conn.commit()
            MessageBox("Налаштування колонок звіту успішно збережено.", "Успіх!", OK | ICON_INFORMATION)

        except Exception as e:
            self.conn.rollback() # Відкат у випадку помилки
            MessageBox(f"Невідома помилка при збереженні налаштувань колонок звіту: {e}", "Помилка", OK | ICON_ERROR)
        finally:
            if cursor:
                cursor.close()
            self.last_footer_message = f"Зміна налаштування колонок звіту"
            wx.CallAfter(self.update_footer_message, self.last_footer_message)

            # оновлюємо налаштування для вкладки ЗВІТ
            if self.tab4_panel:
                wx.CallAfter(self.tab4_panel.refresh_tree)


    # --- Методы для редактирования глобальных переменных (звания, подразделения) ---

    def on_select_global_var(self, event):
        """ вставка вибраного елементу зі списку комбобокса в відповідне текстове поле """
        try:
            selected_combobox = event.GetEventObject()
            selected_value = selected_combobox.GetValue()

            if selected_combobox == self.rank_combobox:
                entry_ctrl = self.rank_entry
            elif selected_combobox == self.unit_combobox:
                entry_ctrl = self.unit_entry
            else:
                return  # Невідомий комбобокс

            entry_ctrl.SetValue(selected_value)
            self._update_global_vars_ui_state()

        finally:
            self._internal_global_var_change = False


    def on_global_var_delete_check(self, event):
        """
        Обработчик события изменения состояния чекбокса "видалити".
        """
        self._update_global_vars_ui_state()
        event.Skip()


    def on_save_global_vars(self, event):
        """Сохраняет изменения (обновление/вставка/удаление) в таблице libs. Использует self.conn."""

        # Отримуємо поточні значення з віджетів
        selected_rank = self.rank_combobox.GetValue()
        new_rank_value = self.rank_entry.GetValue().strip()
        delete_rank = self.rank_delete_checkbox.GetValue() 

        selected_unit = self.unit_combobox.GetValue()
        new_unit_value = self.unit_entry.GetValue().strip()
        delete_unit = self.unit_delete_checkbox.GetValue()

        # Визначаємо, які дії потрібно виконати
        delete_rank_action = delete_rank and selected_rank != '' 
        delete_unit_action = delete_unit and selected_unit != '' 

        update_unit_action = None
        insert_unit_action = None
        update_rank_action = None
        insert_rank_action = None        

        if len(new_rank_value) >= 2 and new_rank_value != selected_rank :
            update_rank_action = selected_rank != '' and selected_rank != 'Створити >'
            insert_rank_action = selected_rank == 'Створити >'

        if len(new_unit_value) >= 2 and new_unit_value != selected_unit :
            update_unit_action = selected_unit != '' and selected_unit != 'Створити >'
            insert_unit_action = selected_unit == 'Створити >'

        # Перевірка, чи є хоч якісь зміни, які потребують збереження/видалення
        has_changes_to_save = delete_rank_action or delete_unit_action or \
                              update_rank_action or update_unit_action or \
                              insert_rank_action or insert_unit_action


        if not has_changes_to_save:
             MessageBox("Немає змін для збереження.", "Увага!", OK | ICON_INFORMATION)
             # Після такої перевірки варто оновити стан UI, якщо раптом кнопка була активна без реальних змін
             self._update_global_vars_ui_state()
             return

        cursor = None
        try:
            cursor = self.conn.cursor()

            # --- Обработка удаления ---
            if delete_rank_action or delete_unit_action:
                # Запитуємо підтвердження лише якщо є хоч одне видалення
                if MessageBox("Видалення значень може зламати базу! Продовжити?", "Увага! Небезпечна дія!!!", OK | wx.CANCEL | ICON_WARNING) != wx.OK:
                    # Якщо користувач відмовився, скидаємо стан UI і виходимо
                    self.on_clear_global_vars()
                    return # Вихід без commit/rollback, бо дії не виконувались

                if delete_rank_action:
                    cursor.execute("DELETE FROM libs WHERE rank_src = ?", (selected_rank,))
                    self.last_footer_message = f"Видалено {selected_rank}"
                   
                if delete_unit_action:
                    cursor.execute("DELETE FROM libs WHERE unit_src = ?", (selected_unit,))
                    self.last_footer_message = f"Видалено {selected_unit}"

            # --- Обработка обновления или вставки ---
            # Виконуємо оновлення/вставку, якщо відповідна дія запланована
            if update_rank_action:
                # Оновлення існуючого звання
                cursor.execute("UPDATE libs SET rank_src = ? WHERE rank_src = ?", (new_rank_value, selected_rank))
                cursor.execute("UPDATE personality SET rank = ? WHERE rank = ?", (new_rank_value, selected_rank))

                self.last_footer_message = f"Змінено {selected_rank} -> {new_rank_value}"

            if insert_rank_action:
                 # Вставка нового звання
                 # Перевірка на дублікат перед вставкою
                 cursor.execute("SELECT COUNT(*) FROM libs WHERE rank_src = ?", (new_rank_value,))
                 exists = cursor.fetchone()[0] > 0
                 if exists:
                    MessageBox(f"Звання '{new_rank_value}' вже існує.", "Увага!", OK | ICON_WARNING)
                    self.conn.rollback() # Відкат всіх змін у цій транзакції
                    self._refresh_global_libs_ui() # Оновлюємо UI
                    return # Вихід після помилки дубліката
                 else:
                    cursor.execute("INSERT INTO libs (rank_src) VALUES (?)", (new_rank_value,))
                    self.last_footer_message = f"Створено {new_rank_value}"

            if update_unit_action:
                # Оновлення існуючого підрозділу
                cursor.execute("UPDATE libs SET unit_src = ? WHERE unit_src = ?", (new_unit_value, selected_unit))
                cursor.execute("UPDATE personality SET unit = ? WHERE unit = ?", (new_unit_value, selected_unit))

                self.last_footer_message = f"Змінено {selected_unit} -> {new_unit_value}"

            if insert_unit_action:
                 # Вставка нового підрозділу
                 # Перевірка на дублікат перед вставкою
                 cursor.execute("SELECT COUNT(*) FROM libs WHERE unit_src = ?", (new_unit_value,))
                 exists = cursor.fetchone()[0] > 0
                 if exists:
                    MessageBox(f"Підрозділ '{new_unit_value}' вже існує.", "Увага!", OK | ICON_WARNING)
                    self.conn.rollback() # Відкат
                    self._refresh_global_libs_ui() # Оновлюємо UI
                    return # Вихід
                 else:
                    cursor.execute("INSERT INTO libs (unit_src) VALUES (?)", (new_unit_value,))
                    self.last_footer_message = f"Створено {new_unit_value}"


            # Якщо дій видалення та оновлення/вставки не було (хоча has_changes_to_save перевіряє це раніше)
            # або якщо всі дії пройшли успішно до цього моменту - комітимо.
            # Якщо була помилка дубліката, ми вже зробили rollback і вийшли.
            self.conn.commit()
            MessageBox("Зміни збережено.", "Успіх!", OK | ICON_INFORMATION)

            # --- ОНОВЛЕННЯ UI ПІСЛЯ УСПІШНОГО ЗБЕРЕЖЕННЯ ---
            self._refresh_global_libs_ui() 

        except Exception as e:
            self.conn.rollback() # Відкат у випадку будь-якої іншої помилки бази даних
            MessageBox(f"Помилка бази даних при збереженні: {e}", "Помилка", OK | ICON_ERROR)

        finally:
            if cursor:
                cursor.close()

             # оновлюємо налаштування для вкладки ЗВІТ
            if self.tab4_panel:
                wx.CallAfter(self.tab4_panel.refresh_tree)


    def on_clear_global_vars(self, event=None):
        """Очищає поля та скидає вибір у комбобоксах глобальних змінних."""
        # Скидаємо вибір у комбобоксах на перший елемент (порожній)
        self.rank_combobox.SetSelection(0)
        self.unit_combobox.SetSelection(0)

        # Очищаємо поля вводу
        self.rank_entry.SetValue("")
        self.unit_entry.SetValue("")

        # Скидаємо чекбокси видалення
        self.rank_delete_checkbox.SetValue(False)
        self.unit_delete_checkbox.SetValue(False)

        # Оновлюємо стан елементів керування
        self._update_global_vars_ui_state()
        

    def update_footer_message(self, message):
        #  вивод текста в футер
        if self.fut_place:
            self.last_message = f"Остання дія: {message}"
            self.fut_place.SetLabel(self.last_message)  # обновляем футер


    def get_footer_message(self):
        """Повертає останнє повідомлення, що було встановлено у футері."""
        return self.last_footer_message


    # ---  МЕТОД ДЛЯ ПЕРЕДАЧИ в КАРТКА ---
    def get_show_hellou(self):
        return self.show_hellou
