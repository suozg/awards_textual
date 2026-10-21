import wx
import io

from config import TITLE_PROG, VERSION
from ui_utils import load_image_from_blob
from gameoflife import GameOfLifePanel # пасхалка по клику на лого

class InfoPanel(wx.Panel):
    def __init__(self, parent, settings_manager, conn, fut_place=None):
        super().__init__(parent)

        self.conn = conn
        self.fut_place = fut_place
        self.last_footer_message = None
        self.settings_manager = settings_manager
        self.current_footer_handler = self

        main_sizer = wx.BoxSizer(wx.VERTICAL)
        content_sizer = wx.BoxSizer(wx.VERTICAL)


        # Заголовок
        label = wx.StaticText(self, label=TITLE_PROG)
        content_sizer.Add(label, 0, wx.ALIGN_CENTER_HORIZONTAL | wx.ALL, 10)

        # Версія
        version_label = wx.StaticText(self, label=VERSION)
        content_sizer.Add(version_label, 0, wx.ALIGN_CENTER_HORIZONTAL | wx.TOP | wx.BOTTOM, 5)

        # Логотип
        # Додати зображення лого
        logo_bitmap = None
        # Проверяем, что настройки загружены
        if self.settings_manager and self.settings_manager.is_loaded:
            # Получаем СЫРОЙ BLOB логотипа из менеджера
            logo_blob = self.settings_manager.get_logo_blob()

            search_tab_logo_max_dim = 300 # <--- ЗАДАЙТЕ НУЖНЫЙ РАЗМЕР ЗДЕСЬ!

            # Если BLOB получен, вызываем load_image_from_blob для создания масштабированного Bitmap
            if logo_blob:
                # Вызываем load_image_from_blob, добавляя параметры grayscale и brightness_factor
                logo_bitmap = load_image_from_blob(
                    logo_blob,
                    max_dim=search_tab_logo_max_dim,
                    grayscale=False,          #  Сделать серым : True
                    brightness_factor=0.6    # Сделать немного темнее (60% от оригинальной яркости)
                )

        # Создаем контрол wx.StaticBitmap для отображения логотипа
        if logo_bitmap and logo_bitmap.IsOk():
            self.logo_display = wx.StaticBitmap(self, wx.ID_ANY, logo_bitmap)
        else:
            # Placeholder, если логотип не загружен или невалиден
            # Размер placeholder должен примерно соответствовать ожидаемому размеру
            self.logo_display = wx.StaticBitmap(self, size=(300, 300)) # Используем тот же размер, что и желаемый max_dim

        # Добавляем контрол логотипа 
        content_sizer.Add(self.logo_display, 0, wx.ALIGN_CENTER_HORIZONTAL | wx.BOTTOM, 15)

        # Опис 1
        description_label1 = wx.StaticText(self, label="Зручний облік подань, нагород і нагороджених.")
        content_sizer.Add(description_label1, 0, wx.ALIGN_CENTER_HORIZONTAL | wx.TOP | wx.BOTTOM, 8)

        # Опис 2
        description_label2 = wx.StaticText(self, label="2023-2026, Холодов О.В., GPL2.0, GitHub/suozg")
        content_sizer.Add(description_label2, 0, wx.ALIGN_CENTER_HORIZONTAL | wx.TOP | wx.BOTTOM, 8)

        # Центруємо весь блок
        main_sizer.AddStretchSpacer(1)
        main_sizer.Add(content_sizer, 0, wx.ALIGN_CENTER)
        main_sizer.AddStretchSpacer()

        self.SetSizer(main_sizer)

        self.logo_display.Bind(wx.EVT_LEFT_DOWN, self.on_logo_click)

        self.game_panel = None # Тут буде зберігатися об'єкт гри, коли вона запуститься


    def get_footer_message(self):
        # Перевіряємо, чи поточний обробник - це НЕ сам InfoPanel
        if self.current_footer_handler is not self and \
            self.current_footer_handler and \
            hasattr(self.current_footer_handler, 'get_footer_message'):

            try:
                # Делегуємо запит до іншого об'єкта (наприклад, GameOfLifePanel)
                return self.current_footer_handler.get_footer_message()
            except Exception as e:
                return f"Error in {type(self.current_footer_handler).__name__}: {e}"
        else:
            # Якщо обробник - це сам InfoPanel, або він не ініціалізований ,
            return self.last_footer_message


    def update_footer_message(self, message):
        """Оновлює внутрішнє останнє повідомлення InfoPanel."""
        self.last_footer_message = f"Info: {message}"


    def on_logo_click(self, event):
        # Видаляємо весь початковий вміст панелі
        for child in self.GetChildren():
            child.Destroy()
        self.current_footer_handler = self.game_panel # 

        # Передаємо fut_place грі, щоб вона могла оновлювати футер в реальному часі
        self.game_panel = GameOfLifePanel(self, fut_place=self.fut_place)
        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(self.game_panel, 1, wx.EXPAND)
        self.SetSizer(sizer)
        self.Layout()
        self.Fit() # Можливо, потрібно оновити розмір панелі

        # *** Важливо: після створення гри, вона стає поточним обробником футера для цієї вкладки ***
        self.current_footer_handler = self.game_panel

        # Оновлюємо футер після запуску гри (опціонально)
        if self.game_panel:
            # Можемо викликати її власний метод, щоб встановити початкове повідомлення гри
            self.game_panel.update_footer_message("(лівий клік: настройка поля, пробіл: start/stop)")


    def refresh_logo(self):
        """Перезагружает логотип из базы данных и обновляет отображение."""
        try:
            with self.conn: # Используем активное подключение к БД
                cursor = self.conn.cursor()
                # ПЕРЕзагружаем настройки (включая логотип)
                self.settings_manager.load_settings(cursor)

            logo_blob = self.settings_manager.get_logo_blob()

            if logo_blob:
                bmp = load_image_from_blob(
                    logo_blob,
                    max_dim=300, # Keep this consistent with __init__
                    grayscale=False,
                    brightness_factor=0.6
                )
                if bmp.IsOk():
                    self.logo_display.SetBitmap(bmp)
                    # *** ДОДАЙТЕ ЦЕЙ РЯДОК ***
                    self.Layout() # Наказати панелі перекомпонувати вміст за допомогою сайзера

        except Exception as e:
            print(f"Помилка оновленни логотипу: {e}")
            # Хороша практика також оновлювати повідомлення футера у разі помилки
            self.last_footer_message = f"Ошибка обновления логотипа: {e}"
        finally:
            # Переконайтеся, що повідомлення про успіх встановлюється тільки якщо не було помилки
            if not self.last_footer_message or "Ошибка" not in self.last_footer_message:
                 self.last_footer_message = "Оновлено логотип"
            self.update_footer_message(self.last_footer_message)
