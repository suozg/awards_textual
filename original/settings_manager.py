# settings_manager.py

import wx # Нужен, т.к. создаем wx.Bitmap
from database_logic import get_service_settings_data # Импортируем функцию БД
from ui_utils import load_image_from_blob # Импортируем функцию UI-утилиты

class ServiceSettingsManager:
    """
    Управляет загрузкой и хранением настроек сервиса и связанных изображений.
    """
    def __init__(self):
        self._raw_settings_row = None

        # Инициализируем атрибуты для хранения настроек и битмапов
        self.logo_blob = None
        self.exel_blob = None
        self.view_blob = None
        self.or_blob = None
        self.homer_blob = None
        self.homer2_blob = None

        self.zvit_dir = None
        self.zvit_fields = None
        self.show_hellou = None
        self.service_id = None
        self.service_pass = None
        self.cookies = None
        self.last_time_changes = None
        self.is_loaded = False # Флаг успешной загрузки


    def load_settings(self, cursor):

        self.is_loaded = False # Сбрасываем флаг перед попыткой загрузки
        self._raw_settings_row = None # Сбрасываем сырые данные

        # Сбрасываем предыдущие данные
        self.logo_blob = None
        self.exel_blob = None
        self.view_blob = None
        self.or_blob = None
        self.homer_blob = None
        self.homer2_blob = None

        self.zvit_dir = None
        self.zvit_fields = None
        self.show_hellou = None
        self.service_id = None
        self.service_pass = None
        self.cookies = None
        self.last_time_changes = None

        try:
            # Получаем сырые данные из базы данных
            settings_row = get_service_settings_data(cursor)

            if not settings_row:
                return False # Загрузка не удалась

            self._raw_settings_row = settings_row # Сохраняем сырую строку

            # Сохраняем отдельные атрибуты для сырых BLOBов и текстовых настроек
            if len(self._raw_settings_row) > 12: # Проверка по максимальному используемому индексу (12)
                 self.logo_blob = self._raw_settings_row[0]
                 self.exel_blob = self._raw_settings_row[1]
                 self.view_blob = self._raw_settings_row[2]
                 self.or_blob = self._raw_settings_row[3]
                 self.zvit_dir = self._raw_settings_row[4]
                 self.zvit_fields = self._raw_settings_row[5]
                 self.show_hellou = self._raw_settings_row[6]
                 self.service_id = self._raw_settings_row[7]
                 self.service_pass = self._raw_settings_row[8]
                 self.cookies = self._raw_settings_row[9]
                 self.homer_blob = self._raw_settings_row[10]
                 self.homer2_blob = self._raw_settings_row[11]
                 self.last_time_changes = self._raw_settings_row[12]

            self.is_loaded = True
            return True

        except Exception as e:
            # Атрибуты останутся None/предыдущими значениями
            self.is_loaded = False 
            return False


    def get_logo_blob(self):
        """Возвращает сырой BLOB логотипа или None."""
        return self.logo_blob


    def get_exel_blob(self):
        """Возвращает сырой BLOB логотипа или None."""
        return self.exel_blob


    def get_view_blob(self):
        """Возвращает сырой BLOB логотипа или None."""
        return self.view_blob


    def get_or_blob(self):
        """Возвращает сырой BLOB логотипа или None."""
        return self.or_blob


    def get_homer_blob(self):
        """Возвращает сырой BLOB логотипа или None."""
        return self.homer_blob


    def get_homer2_blob(self):
        """Возвращает сырой BLOB логотипа или None."""
        return self.homer2_blob


    def get_scaled_bitmap_from_blob(self, blob_getter_method, max_dim, grayscale=False, brightness_factor=1.0):
        """
        Получает масштабированный wx.Bitmap из сырого BLOB, с опциональной обработкой серости/яркости.
        """
        blob_data = blob_getter_method()

        # Вызываем load_image_from_blob, передавая все параметры
        return load_image_from_blob(
            blob_data,
            max_dim=max_dim,
            grayscale=grayscale,
            brightness_factor=brightness_factor
        )
