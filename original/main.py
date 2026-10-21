# main.py
import wx
import sys

from config import (
    MASTERKEY, DATABASE_FILE_PATH, DEF_FUT_LABEL, DEFAULT_FRAME_SIZE, TITLE_PROG
    )
from database_logic import connect_to_database, is_database_existing, create_database
from settings_manager import ServiceSettingsManager
import argparse # Импортируем argparse для обработки аргументов командной строки

# Импортируем классы всех панелей-вкладок
from search_tab import Tab1Panel
from kartka import KartkaPanel
from dovidnyk import DovidnykPanel
from zvity import Tab4Panel
from text_present_search import SearchPanel
from setuptab import SettingsPanel
from info import InfoPanel
from websearch import WebSearchPanel
from tablaw import LawsPanel
import locale
locale.setlocale(locale.LC_TIME, 'uk_UA.UTF-8') 
from sql_console import SqlConsolePanel

# --- Допоміжна функція для отримання кастомної панелі зі сторінки Notebook ---
def get_custom_panel_from_page(page_object):

    if not isinstance(page_object, wx.Window):
        return None

    # Випадок 1: Об'єкт сторінки сам є кастомною панеллю
    # Перевіряємо наявність одного з методів, які ми очікуємо у наших панелей
    if hasattr(page_object, "get_footer_message") or \
       hasattr(page_object, "get_latest_search_results") or \
       hasattr(page_object, "populate_person_search_combobox"):
        return page_object

    # Випадок 2: Кастомна панель є першим дочірнім елементом об'єкта сторінки (контейнера)
    if page_object.GetChildren():
        first_child = page_object.GetChildren()[0]
        if isinstance(first_child, wx.Window):
             # Перевіряємо, чи перший дочірній елемент є нашою кастомною панеллю за наявністю методів
             if hasattr(first_child, "get_footer_message") or \
                hasattr(first_child, "get_latest_search_results") or \
                hasattr(first_child, "populate_person_search_combobox"):
                 return first_child

    return None


class MainFrame(wx.Frame):
    def __init__(self, parent, id=wx.ID_ANY, title="", pos=wx.DefaultPosition, size=wx.DefaultSize, style=wx.DEFAULT_FRAME_STYLE, name=wx.FrameNameStr):
        super(MainFrame, self).__init__(parent, id, title=title, pos=pos, size=size, style=style, name=name)

        self.KEY = None
        self.database_path = DATABASE_FILE_PATH
        self.must_change_password = False
        self.fut_place = None
        self.conn = None
        self.cursor = None
        self.last_active_tab_index = -1
        self.refreshed_tabs = set()

        # аргумент командной строки -с /путь/к/базе
        parser_file_db = argparse.ArgumentParser(description='Process some database file.')
        parser_file_db.add_argument('-c', type=str, default=self.database_path, help='Path to the database file')
        args_db = parser_file_db.parse_args()
        self.database_path = args_db.c

        # --- Визначаємо, чи існує БД, ОДИН РАЗ перед запитом пароля ---
        self.db_exists_at_start = is_database_existing(self.database_path)

        if MASTERKEY:
            self.KEY = MASTERKEY
        else:
            # Передаємо інформацію про існування БД у діалог пароля
            self.KEY = self._ask_password_dialog(self.db_exists_at_start)

        if self.KEY is None:
            self.Destroy()
            return

        self.SetSize(DEFAULT_FRAME_SIZE)
        self.CenterOnScreen()

        try:
            # Тепер підключаємося до БД лише один раз, коли пароль вже отримано
            self.conn, self.cursor = connect_to_database(self.KEY, self.database_path)

            if not self.cursor:
                wx.MessageBox("Не вдалося підключитися до бази даних при старті додатку. Перевірте пароль та файл БД.", "Критична помилка БД", wx.OK | wx.ICON_ERROR)
                self.Destroy()
                return

        except Exception as e:
            wx.MessageBox(f"MAIN: Виникла неочікувана помилка при підключенні до БД: {e}", "Критична помилка БД", wx.OK | wx.ICON_ERROR)
            self.Destroy()
            return


        # --- Создание и загрузка менеджера настроек ---
        self.settings_manager = ServiceSettingsManager()
        loading_success = self.settings_manager.load_settings(self.cursor)

        if not loading_success:
             wx.MessageBox("Не вдалося завантажити налаштування сервісу з бази даних. Додаток може працювати некоректно.", "Помилка завантаження налаштувань", wx.OK | wx.ICON_WARNING)

        # --- Инициализация интерфейса (создание вкладок, панелей и т.д.) ---
        self.init_ui()

        # --- Привязываем событие закрытия ГЛАВНОГО окна для закрытия соединения БД ---
        self.Bind(wx.EVT_CLOSE, self.OnClose)

        # Важно: Show() вызывается только после успешной инициализации
        self.Show(True)


    def _ask_password_dialog(self, db_exists_at_start):
        """Внутрішній метод для запиту пароля у користувача з перевіркою."""
        while True:
            # Використовуємо db_exists_at_start, щоб не викликати is_database_existing щоразу
            if not db_exists_at_start:
                dlg_message = "База даних не знайдена. Введіть пароль для створення:"
                dlg_caption = "Створення бази даних"
            else:
                dlg_message = "Введіть пароль для доступу:"
                dlg_caption = "Вхід"

            dlg = wx.TextEntryDialog(self, dlg_message, caption=dlg_caption, value="", style=wx.TextEntryDialogStyle | wx.TE_PASSWORD)

            if dlg.ShowModal() == wx.ID_OK:
                password = dlg.GetValue()
                dlg.Destroy()

                if not db_exists_at_start:
                    try:
                        # Спроба створити БД, якщо її не було
                        if create_database(self.database_path, password):
                            # Після створення, перевіряємо, чи можемо ми підключитися
                            # (Цей блок є ключовим для уникнення повторного діалогу, якщо створення успішне)
                            temp_conn, temp_cursor = connect_to_database(password, self.database_path)
                            if temp_conn and temp_cursor:
                                temp_cursor.close()
                                temp_conn.close()
                                return password # Успішно створено та підключено
                            else:
                                wx.MessageDialog(self, "Базу даних створено, але не вдалося підключитися з цим паролем.", "Помилка підключення після створення", wx.ICON_ERROR).ShowModal()
                        else:
                            wx.MessageDialog(self, "Не вдалося створити базу даних. Перевірте права доступу або місце розташування.", "Помилка створення БД", wx.ICON_ERROR).ShowModal()
                    except Exception as e:
                        wx.MessageDialog(self, f"Неочікувана помилка при створенні БД: {e}", "Помилка створення БД", wx.OK | wx.ICON_ERROR).ShowModal()
                else:
                    # Якщо БД існує, просто намагаємося підключитися
                    temp_conn, temp_cursor = connect_to_database(password, self.database_path)
                    if temp_conn and temp_cursor:
                        temp_cursor.close()
                        temp_conn.close()
                        return password # Пароль вірний, повертаємо його
                    else:
                        wx.MessageDialog(self, "Невірний пароль.", "Помилка", wx.ICON_ERROR).ShowModal()
            else:
                dlg.Destroy()
                return None # Користувач відмінив
                
    def on_key_navigation(self, event):
        """Обробник глобальних гарячих клавіш для перемикання вкладок"""
        ctrl_down = event.ControlDown()
        shift_down = event.ShiftDown()
        keycode = event.GetKeyCode()
        
        page_count = self.notebook.GetPageCount()
        current_sel = self.notebook.GetSelection()

        if ctrl_down:
            # Ctrl + Tab (наступна вкладка) або Ctrl + Shift + Tab (попередня вкладка)
            if keycode == wx.WXK_TAB:
                if shift_down:
                    new_sel = (current_sel - 1) % page_count
                else:
                    new_sel = (current_sel + 1) % page_count
                self.notebook.SetSelection(new_sel)
                return

            # Перехід за допомогою цифрових клавіш від Ctrl + 1 до Ctrl + 9
            if ord('1') <= keycode <= ord('9'):
                target_idx = keycode - ord('1')
                if target_idx < page_count:
                    self.notebook.SetSelection(target_idx)
                    return

        event.Skip()   

   
    def init_ui(self):
        """Инициализация интерфейса."""
        vbox = wx.BoxSizer(wx.VERTICAL)
        notebook = wx.Notebook(self, wx.ID_ANY)

        self.fut_place = wx.StaticText(self, wx.ID_ANY, label=DEF_FUT_LABEL)
        vbox.Add(notebook, 1, wx.EXPAND | wx.ALL, 5)
        vbox.Add(self.fut_place, 0, wx.ALIGN_LEFT | wx.LEFT | wx.BOTTOM, 10)

        self.tab1_panel_instance = None

        # --- Создаем вкладки и панели ----
        try:
            tab1_panel = Tab1Panel(notebook, self.conn, self.cursor, self.settings_manager, fut_place=self.fut_place)
            notebook.AddPage(tab1_panel, "ПОШУК")
            self.search_panel_instance = tab1_panel
        except Exception as e:
            error_panel = wx.Panel(notebook, wx.ID_ANY); error_panel_sizer = wx.BoxSizer(wx.VERTICAL)
            error_panel_sizer.Add(wx.StaticText(error_panel, wx.ID_ANY, f"Не вдалося завантажити вкладку 'ПОШУК': {e}"), 1, wx.EXPAND | wx.ALL, 10)
            error_panel.SetSizer(error_panel_sizer)
            notebook.AddPage(error_panel, "ПОШУК (Помилка)")
            self.search_panel_instance = None

        tab2_container_panel = wx.Panel(notebook, wx.ID_ANY)
        tab2_sizer = wx.BoxSizer(wx.VERTICAL)
        try:
            panel2 = KartkaPanel(
                tab2_container_panel,
                self.conn,
                self.cursor,
                self.settings_manager,
                fut_place=self.fut_place,
                search_panel=self.search_panel_instance
            )
            tab2_sizer.Add(panel2, 1, wx.EXPAND)
            tab2_container_panel.SetSizer(tab2_sizer)
            notebook.AddPage(tab2_container_panel, "КАРТКА")
        except Exception as e:
            error_panel = wx.Panel(notebook, wx.ID_ANY); error_panel_sizer = wx.BoxSizer(wx.VERTICAL)
            error_panel_sizer.Add(wx.StaticText(error_panel, wx.ID_ANY, f"Не вдалося завантажити вкладку 'КАРТКА': {e}"), 1, wx.EXPAND | wx.ALL, 10)
            error_panel.SetSizer(error_panel_sizer)
            notebook.AddPage(error_panel, "КАРТКА (Помилка)")

        tab3_container_panel = wx.Panel(notebook, wx.ID_ANY)
        tab3_sizer = wx.BoxSizer(wx.VERTICAL)
        try:
            panel3 = DovidnykPanel(tab3_container_panel, self.conn, self.cursor, fut_place=self.fut_place, kartka_panel=panel2)
            tab3_sizer.Add(panel3, 1, wx.EXPAND | wx.ALL, 5)
            tab3_container_panel.SetSizer(tab3_sizer)
            notebook.AddPage(tab3_container_panel, "ДОВІДНИК")
        except Exception as e:
            error_panel = wx.Panel(notebook, wx.ID_ANY); error_panel_sizer = wx.BoxSizer(wx.VERTICAL)
            error_panel_sizer.Add(wx.StaticText(error_panel, wx.ID_ANY, f"Не вдалося завантажити вкладку 'ДОВІДНИК': {e}"), 1, wx.EXPAND | wx.ALL, 10)
            error_panel.SetSizer(error_panel_sizer)
            notebook.AddPage(error_panel, "ДОВІДНИК (Помилка)")

        tab4_container_panel = wx.Panel(notebook, wx.ID_ANY)
        tab4_sizer = wx.BoxSizer(wx.VERTICAL)
        try:
            panel4 = Tab4Panel(
                tab4_container_panel,
                self.conn, self.cursor,
                self.database_path,
                self.KEY,
                fut_place=self.fut_place
            )
            tab4_sizer.Add(panel4, 1, wx.EXPAND | wx.ALL, 5)
            tab4_container_panel.SetSizer(tab4_sizer)
            notebook.AddPage(tab4_container_panel, "ЗВІТИ")
        except Exception as e:
            error_panel = wx.Panel(notebook, wx.ID_ANY); error_panel_sizer = wx.BoxSizer(wx.VERTICAL)
            error_panel_sizer.Add(wx.StaticText(error_panel, wx.ID_ANY, f"Не вдалося завантажити вкладку 'ЗВІТИ': {e}"), 1, wx.EXPAND | wx.ALL, 10)
            error_panel.SetSizer(error_panel_sizer)
            notebook.AddPage(error_panel, "ЗВІТИ (Помилка)")

        tab5_container_panel = wx.Panel(notebook, wx.ID_ANY)
        tab5_sizer = wx.BoxSizer(wx.VERTICAL)
        try:
            panel5 = SearchPanel(tab5_container_panel, self.conn, self.cursor, fut_place=self.fut_place)
            tab5_sizer.Add(panel5, 1, wx.EXPAND | wx.ALL, 5)
            tab5_container_panel.SetSizer(tab5_sizer)
            notebook.AddPage(tab5_container_panel, "ТЕКСТ")
        except Exception as e:
            error_panel = wx.Panel(notebook, wx.ID_ANY); error_panel_sizer = wx.BoxSizer(wx.VERTICAL)
            error_panel_sizer.Add(wx.StaticText(error_panel, wx.ID_ANY, f"Не вдалося завантажити вкладку 'ТЕКСТ': {e}"), 1, wx.EXPAND | wx.ALL, 10)
            error_panel.SetSizer(error_panel_sizer)
            notebook.AddPage(error_panel, "ТЕКСТ (Помилка)")

        tab6_container_panel = wx.Panel(notebook, wx.ID_ANY)
        tab6_sizer = wx.BoxSizer(wx.VERTICAL)
        try:
            panel6 = WebSearchPanel(
                tab6_container_panel,
                self.conn,
                self.cursor,
                fut_place=self.fut_place
            )
            tab6_sizer.Add(panel6, 1, wx.EXPAND | wx.ALL, 5)
            tab6_container_panel.SetSizer(tab6_sizer)
            notebook.AddPage(tab6_container_panel, "ВЕБ-ПОШУК")
        except Exception as e:
            error_panel = wx.Panel(notebook, wx.ID_ANY); error_panel_sizer = wx.BoxSizer(wx.VERTICAL)
            error_panel_sizer.Add(wx.StaticText(error_panel, wx.ID_ANY, f"Не вдалося завантажити вкладку 'ВЕБ-ПОШУК': {e}"), 1, wx.EXPAND | wx.ALL, 10)
            error_panel.SetSizer(error_panel_sizer)
            notebook.AddPage(error_panel, "ВЕБ-ПОШУК (Помилка)")

        tab10_panel = InfoPanel(notebook, self.settings_manager, self.conn, fut_place=self.fut_place)

        tab9_container_panel = wx.Panel(notebook, wx.ID_ANY)
        tab9_sizer = wx.BoxSizer(wx.VERTICAL)
        try:
            panel9 = SettingsPanel(
                tab9_container_panel,
                self.conn, self.cursor,
                self.database_path,
                self.KEY, fut_place=self.fut_place,
                tab4_panel=panel4,
                info_panel=tab10_panel,
                search_tab=tab1_panel,
                kartka_panel=panel2
            )
            tab9_sizer.Add(panel9, 1, wx.EXPAND | wx.ALL, 5)
            tab9_container_panel.SetSizer(tab9_sizer)
            notebook.AddPage(tab9_container_panel, "НАСТРОЙКИ")
        except Exception as e:
            error_panel = wx.Panel(notebook, wx.ID_ANY); error_panel_sizer = wx.BoxSizer(wx.VERTICAL)
            error_panel_sizer.Add(wx.StaticText(error_panel, wx.ID_ANY, f"Не вдалося завантажити вкладку 'НАСТРОЙКИ': {e}"), 1, wx.EXPAND | wx.ALL, 10)
            error_panel.SetSizer(error_panel_sizer)
            notebook.AddPage(error_panel, "НАСТРОЙКИ (Помилка)")


        tab7_container_panel = wx.Panel(notebook, wx.ID_ANY)
        tab7_sizer = wx.BoxSizer(wx.VERTICAL)
        try:
            panel7 = LawsPanel(
                tab7_container_panel,
                self.conn,
                self.cursor,
                fut_place=self.fut_place
            )
            tab7_sizer.Add(panel7, 1, wx.EXPAND | wx.ALL, 5)
            tab7_container_panel.SetSizer(tab7_sizer)
            notebook.AddPage(tab7_container_panel, "ЗАКОНИ")
        except Exception as e:
            error_panel = wx.Panel(notebook, wx.ID_ANY)
            error_panel_sizer = wx.BoxSizer(wx.VERTICAL)
            error_panel_sizer.Add(wx.StaticText(error_panel, wx.ID_ANY,
                f"Не вдалося завантажити вкладку 'ЗАКОНИ': {e}"),
                1, wx.EXPAND | wx.ALL, 10)
            print(f"Не вдалося завантажити вкладку 'ЗАКОНИ': {e}")
            error_panel.SetSizer(error_panel_sizer)
            notebook.AddPage(error_panel, "ЗАКОНИ (Помилка)")

        # --- SQL вкладка ---
        tab_sql_panel = wx.Panel(notebook, wx.ID_ANY)
        tab_sql_sizer = wx.BoxSizer(wx.VERTICAL)

        try:
            sql_panel = SqlConsolePanel(
                tab_sql_panel,
                self.conn,
                self.cursor,
                fut_place=self.fut_place
            )
            tab_sql_sizer.Add(sql_panel, 1, wx.EXPAND | wx.ALL, 5)
            tab_sql_panel.SetSizer(tab_sql_sizer)
            notebook.AddPage(tab_sql_panel, "SQL")
        except Exception as e:
            error_panel = wx.Panel(notebook)
            s = wx.BoxSizer(wx.VERTICAL)
            s.Add(wx.StaticText(error_panel, label=f"SQL вкладка не завантажена: {e}"), 1, wx.ALL, 10)
            error_panel.SetSizer(s)
            notebook.AddPage(error_panel, "SQL (Помилка)")
            print(f"SQL вкладка не завантажена: {e}")
        # --- вкладка ПРО програму -------------
        try:
            notebook.AddPage(tab10_panel, "ПРО")
        except Exception as e:
            error_panel = wx.Panel(notebook, wx.ID_ANY); error_panel_sizer = wx.BoxSizer(wx.VERTICAL)
            error_panel_sizer.Add(wx.StaticText(error_panel, wx.ID_ANY, f"Не вдалося завантажити вкладку 'ПРО': {e}"), 1, wx.EXPAND | wx.ALL, 10)
            error_panel.SetSizer(error_panel_sizer)
            notebook.AddPage(error_panel, "ПРО (Помилка)")

        notebook.Bind(wx.EVT_NOTEBOOK_PAGE_CHANGED, self.on_tab_changed)
        self.notebook = notebook
        # --- Додаємо обробку швидких клавіш для перемикання вкладок ---
        self.Bind(wx.EVT_CHAR_HOOK, self.on_key_navigation)
        
        self.SetSizer(vbox)
        self.Layout()

        self.fut_place.SetLabel(DEF_FUT_LABEL)
        # Встановлюємо фокус на поле пошуку при старті програми ---
        if hasattr(self, 'search_panel_instance') and self.search_panel_instance:
            self.search_panel_instance.set_focus_to_search()


    def OnClose(self, event):
        """Обрабатывает событие закрытия главного фрейма. Закрывает соединение с базой данных."""
        if self.must_change_password:
            wx.MessageBox("Дочекайтесь зміни пароля перед закриттям!", "Увага", wx.OK | wx.ICON_WARNING)
            event.Veto()
        else:
            event.Skip()

        if self.cursor:
            try:
                self.cursor.close()
            except Exception as e:
                wx.MessageBox(f"Error closing cursor: {e}", "Увага", wx.OK | wx.ICON_WARNING)
            self.cursor = None

        if self.conn:
            try:
                self.conn.close()
            except Exception as e:
                wx.MessageBox(f"Error closing conn: {e}", "Увага", wx.OK | wx.ICON_WARNING)
            self.conn = None

        event.Skip()


    def on_tab_changed(self, event):
        """ Функция обновляет футер и вызывает refresh_tree только один раз для каждой вкладки """
        new_tab_index = self.notebook.GetSelection()
        selected_index = event.GetSelection()
        currentPage_object = self.notebook.GetPage(selected_index)
        current_custom_panel = get_custom_panel_from_page(currentPage_object)

        # Обновление футера
        msg = DEF_FUT_LABEL
        if current_custom_panel and hasattr(current_custom_panel, "get_footer_message"):
            try:
                msg = current_custom_panel.get_footer_message()
            except Exception as e:
                msg = f"Помилка футера в {type(current_custom_panel).__name__}: {e}"

        self.fut_place.SetLabel(str(msg) if msg else DEF_FUT_LABEL)

        # refresh_tree вызывается только один раз для каждой вкладки
        if selected_index not in self.refreshed_tabs:
            if hasattr(currentPage_object, "refresh_tree"):
                currentPage_object.refresh_tree()
                self.refreshed_tabs.add(selected_index)
            elif current_custom_panel and hasattr(current_custom_panel, "refresh_tree"):
                current_custom_panel.refresh_tree()
                self.refreshed_tabs.add(selected_index)
        
        # Переводимо фокус на поле пошуку, якщо активна вкладка ПОШУК ---
        if isinstance(current_custom_panel, Tab1Panel):
            current_custom_panel.set_focus_to_search()
        
        # Дополнительная логика для KartkaPanel
        try:
            if isinstance(current_custom_panel, KartkaPanel):
                search_panel_instance = None
                setuptab_panel_instance = None

                for i in range(self.notebook.GetPageCount()):
                    page_i_object = self.notebook.GetPage(i)
                    custom_panel_i = get_custom_panel_from_page(page_i_object)

                    if isinstance(custom_panel_i, Tab1Panel):
                        search_panel_instance = custom_panel_i
                    elif isinstance(custom_panel_i, SettingsPanel):
                        setuptab_panel_instance = custom_panel_i

                if search_panel_instance:
                    latest_search_results, source_data = search_panel_instance.get_latest_search_results()
                    current_custom_panel.populate_and_load_search_results(latest_search_results, source_data)

                if setuptab_panel_instance:
                    show_hellou = setuptab_panel_instance.get_show_hellou()
                    current_custom_panel.populate_and_load_hellou(show_hellou)

        except Exception as e:
            wx.MessageBox(f"Помилка завантаження даних: {e}.", "Помилка", wx.OK | wx.ICON_WARNING)

        event.Skip()


# Точка входа в приложение
def main():
    app = wx.App(False)

    # Создаем главное окно
    frame = MainFrame(
        None,                # parent (для wx.Frame)
        wx.ID_ANY,
        title=TITLE_PROG,
        size=DEFAULT_FRAME_SIZE # Передаем размер в конструктор MainFrame
    )

    # Если MainFrame уничтожен (например, пользователь отменил ввод пароля)
    if not frame: # frame будет None, если self.Destroy() был вызван в __init__
        return

    # Запускаем основной цикл обработки событий wxWidgets
    app.MainLoop()

# Убеждаемся, что main() вызывается только при запуске скрипта напрямую
if __name__ == '__main__':
    main()
