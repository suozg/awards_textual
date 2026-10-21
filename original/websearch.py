import wx
import wx.html
import webbrowser
import wx.grid
import re
from datetime import datetime, timedelta
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
import threading
from database_logic import (
    execute_query
)


def rodovyi_to_znachidnyy(prizvyshe):
    if prizvyshe.endswith(("ець")):
        return prizvyshe[:-3] + "ця"
    elif prizvyshe.endswith(("ень")):
        return prizvyshe[:-3] + "ня"
    elif prizvyshe.endswith(("іл")):
        return prizvyshe[:-2] + "ола"
    elif prizvyshe.endswith(("ок")):
        return prizvyshe[:-2] + "ка"         
    elif prizvyshe.endswith(("ий")):
        return prizvyshe[:-2] + "ого"
    elif prizvyshe.endswith(("ній")):
        return prizvyshe[:-2] + "ього"
    elif prizvyshe.endswith(("ня", "ля", "дя", "мя", "кя", "ця", "жя", "бя", "гя", "ря")):
        return prizvyshe[:-1] + "ю"
    elif prizvyshe.endswith(("ко", "до", "ло")):
        return prizvyshe[:-1] + "а"
    elif prizvyshe.endswith(("а")):
        return prizvyshe[:-1] + "у"
    elif prizvyshe.endswith(("нь", "ль", "ій", "ай", "дь", "сь", "зь", "ть", "ой")):
        return prizvyshe[:-1] + "я"
    elif prizvyshe.endswith(("их", "зе")):
        return prizvyshe
    else:
        return prizvyshe + "а"


class WebSearchPanel(wx.ScrolledWindow):
    def __init__(self, parent, conn, cursor, fut_place=None):
        wx.ScrolledWindow.__init__(self, parent, -1) # Инициализация ScrolledWindow
        self.conn = conn
        self.cursor = cursor
        self.fut_place = fut_place

        self.stop_function_var = 0  # Флаг для остановки поиска

        self.init_ui()
        self.last_message = "Пошук указів про нагородження"
        self.SetScrollbars(1, 1, 0, 0) # Установка скроллбаров (единицы прокрутки, а не пиксели)
        self.SetTargetWindow(self)

    def init_ui(self):
        self.main_sizer = wx.BoxSizer(wx.VERTICAL) # Зробимо main_sizer доступним через self.

        top_section_sizer = wx.BoxSizer(wx.HORIZONTAL)

        left_input_section_sizer = wx.BoxSizer(wx.VERTICAL)

        single_name_sizer = wx.FlexGridSizer(1, 2, 5, 5)
        single_name_sizer.AddGrowableCol(1, 1)

        self.label_last_name = wx.StaticText(self, label="ПРІЗВИЩЕ (у знахідному відмінку)")
        self.entry_last_name = wx.TextCtrl(self, size=(100, -1), style=wx.TE_PROCESS_ENTER)

        single_name_sizer.Add(self.label_last_name, 0, wx.ALIGN_LEFT | wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 5)
        single_name_sizer.Add(self.entry_last_name, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 5)

        left_input_section_sizer.Add(single_name_sizer, 0, wx.EXPAND | wx.ALL, 5)

        listbox_group_sizer = wx.BoxSizer(wx.VERTICAL)

        listbox_label_sizer = wx.BoxSizer(wx.HORIZONTAL)
        
        listbox_label = wx.StaticText(self, label="Прізвища для пошуку зі списку")
        
        self.count_lbox1_label = wx.StaticText(self, label="0")
        
        listbox_label_sizer.Add(listbox_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        listbox_label_sizer.Add(self.count_lbox1_label, 0, wx.ALIGN_CENTER_VERTICAL)

        listbox_group_sizer.Add(listbox_label_sizer, 0, wx.ALIGN_LEFT | wx.LEFT | wx.TOP | wx.BOTTOM, 5)

        self.lbox1 = wx.ListBox(self, size=(250, 250), style=wx.LB_EXTENDED)
        self.lbox2 = wx.ListBox(self, size=(250, 250), style=wx.LB_EXTENDED)

        listbox_buttons_sizer = wx.BoxSizer(wx.VERTICAL)
        self.button1 = wx.Button(self, label=">>>", size=(50, -1))
        self.button2 = wx.Button(self, label="<<<", size=(50, -1))
        listbox_buttons_sizer.Add(self.button1, 0, wx.ALL, 5)
        listbox_buttons_sizer.Add(self.button2, 0, wx.ALL, 5)

        self.button1.Bind(wx.EVT_BUTTON, self.on_lbox1_to_lbox2)
        self.button2.Bind(wx.EVT_BUTTON, self.on_lbox2_to_lbox1)

        listbox_horizontal_sizer = wx.BoxSizer(wx.HORIZONTAL)
        listbox_horizontal_sizer.Add(self.lbox1, 1, wx.EXPAND | wx.RIGHT, 5)
        listbox_horizontal_sizer.Add(listbox_buttons_sizer, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        listbox_horizontal_sizer.Add(self.lbox2, 1, wx.EXPAND)

        listbox_group_sizer.Add(listbox_horizontal_sizer, 1, wx.EXPAND | wx.ALL, 5)

        left_input_section_sizer.Add(listbox_group_sizer, 1, wx.EXPAND | wx.ALL, 5)


        right_controls_sizer = wx.BoxSizer(wx.VERTICAL)

        self.spin_label = wx.StaticText(self, label="рік виборки:")

        self.button_up = wx.Button(self, label="↑", size=(100, -1))
        self.button_down = wx.Button(self, label="↓", size=(100, -1))

        self.current_year = datetime.now().year
        self.current_decade = (self.current_year // 10) * 10
        self.year_spinbox = wx.SpinCtrl(self, min=self.current_decade, max=self.current_decade + 9, initial=self.current_year)
        self.year_spinbox.Bind(wx.EVT_SPINCTRL, self.on_year_spin)

        self.button_up.Bind(wx.EVT_BUTTON, self.increase_decade)
        self.button_down.Bind(wx.EVT_BUTTON, self.decrease_decade)

        self.checkbox_posthumous = wx.CheckBox(self, label="посмертні")
        self.checkbox_posthumous.SetValue(True)
        self.checkbox_posthumous.Bind(wx.EVT_CHECKBOX, self.on_checkbox_toggle)

        right_controls_sizer.Add(self.spin_label, 0, wx.ALIGN_CENTRE_HORIZONTAL | wx.TOP | wx.BOTTOM, 10)
        right_controls_sizer.Add(self.button_up, 0, wx.ALIGN_CENTRE_HORIZONTAL | wx.BOTTOM, 5)
        right_controls_sizer.Add(self.year_spinbox, 0, wx.ALIGN_CENTRE_HORIZONTAL | wx.BOTTOM, 10)
        right_controls_sizer.Add(self.button_down, 0, wx.ALIGN_CENTRE_HORIZONTAL | wx.BOTTOM, 5)
        right_controls_sizer.Add(self.checkbox_posthumous, 0, wx.ALIGN_CENTRE_HORIZONTAL | wx.TOP | wx.BOTTOM, 10)

        self.button_search_decree = wx.Button(self, label="ПОШУК", size=(100, 50))
        self.button_stop = wx.Button(self, label="СКИНУТИ", size=(100, 50))

        self.button_search_decree.Bind(wx.EVT_BUTTON, self.on_start_search)
        self.button_stop.Bind(wx.EVT_BUTTON, self.on_stop_search)

        right_controls_sizer.Add(self.button_search_decree, 0, wx.ALIGN_CENTRE_HORIZONTAL | wx.TOP | wx.BOTTOM, 20)
        right_controls_sizer.Add(self.button_stop, 0, wx.ALIGN_CENTRE_HORIZONTAL | wx.BOTTOM, 20)

        top_section_sizer.Add(left_input_section_sizer, 3, wx.EXPAND | wx.ALL, 10)
        top_section_sizer.Add(right_controls_sizer, 1, wx.EXPAND | wx.ALL, 10)

        # Створюємо сайзер для HtmlWindow
        self.html_results_container = wx.BoxSizer(wx.VERTICAL) # контейнер для HtmlWindow
        self.result_websearch_text = wx.html.HtmlWindow(self)
        self.result_websearch_text.SetMinSize(wx.Size(100, 100)) # Зберігаємо мінімальний розмір
        self.result_websearch_text.Bind(wx.html.EVT_HTML_LINK_CLICKED, self.on_link_click)
        self.html_results_container.Add(self.result_websearch_text, 1, wx.EXPAND | wx.ALL, 10)

        # Створюємо сайзер для прогрес-бару внизу
        self.progress_bar_container = wx.BoxSizer(wx.VERTICAL) # контейнер для Gauge
        self.progress_gauge = wx.Gauge(self, range=100, style=wx.GA_HORIZONTAL | wx.GA_SMOOTH)
        self.progress_bar_container.Add(self.progress_gauge, 0, wx.EXPAND | wx.ALL, 10)

        # Додаємо секції до основного сайзера
        # Зберігаємо SizerItem для top_section_sizer та html_results_container
        # Щоб можна було змінювати їхні пропорції.
        self.top_section_sizer_item = self.main_sizer.Add(top_section_sizer, 1, wx.EXPAND) # top_section_sizer займе пропорцію 1
        self.html_results_container_item = self.main_sizer.Add(self.html_results_container, 0, wx.EXPAND) # HtmlWindow спочатку прихований, тому пропорція 0
        self.progress_bar_container_item = self.main_sizer.Add(self.progress_bar_container, 0, wx.EXPAND) # Прогрес-бар завжди внизу, пропорція 0

        self.SetSizer(self.main_sizer)

        # Початкове приховування елементів
        self.button_stop.Hide()
        
        self.html_results_container.ShowItems(False) # Приховуємо контейнер HtmlWindow
        # Пропорція вже 0 на цьому етапі, тому не потрібно встановлювати знову
        
        self.progress_bar_container.ShowItems(False) # Приховуємо контейнер прогрес-бара

        self.update_years()
        self.Layout() # Оновлюємо макет після ініціалізації


    def on_link_click(self, event):
        href = event.GetLinkInfo().GetHref()
        webbrowser.open(href)


    def on_checkbox_toggle(self, event):
        """
        Обробляє зміну стану чекбоксу "Шукати тільки посмертні"
        та оновлює список прізвищ у lbox1.
        """
        self.refresh_tree() # Просто перезавантажуємо список


    def update_lbox1_count(self):
        """
        Оновлює мітку, що відображає кількість елементів у self.lbox1.
        """
        count = self.lbox1.GetCount()
        self.count_lbox1_label.SetLabel(f"({count})")


    def refresh_tree(self):
        self.lbox1.Clear()
        # self.checkbox_posthumous.GetValue() повертає True, якщо відзначено, і False, якщо ні
        is_posthumous_only = self.checkbox_posthumous.GetValue()

        query_pr = """
            SELECT p.id AS id_personality, p.name
            FROM presentation pr
            JOIN personality p ON pr.id_personality = p.id
            WHERE pr.id_meed IS NULL AND pr.worker = 0 
        """
        
        # Додаємо умову WHERE залежно від стану чекбокса
        if is_posthumous_only:
            query_pr += """ AND pr.report = "посмертно" """
        
        query_pr += """
            ORDER BY
            CASE
                WHEN p.name GLOB '[А-Д]*' THEN 1
                WHEN p.name GLOB 'Є*' THEN 2
                WHEN p.name GLOB '[Е-З]*' THEN 3
                WHEN p.name GLOB 'І*' THEN 4
                WHEN p.name GLOB '[И-Я]*' THEN 5
                ELSE 6
            END, p.name
        """
        
        try:
            list_pres = execute_query(self.cursor, query_pr)

            unique_list_pres = []
            for list_pres_i in list_pres:
                name_parts = list_pres_i[1].strip().split(" ")
                if name_parts:
                    znachidnyy_prizvyshe = rodovyi_to_znachidnyy(name_parts[0].lower()).upper()
                    if znachidnyy_prizvyshe not in unique_list_pres:
                        unique_list_pres.append(znachidnyy_prizvyshe)

            for r, prizvyshe in enumerate(unique_list_pres):
                self.lbox1.Append(prizvyshe)

            # --- Оновлюємо лічильник після завантаження ---
            self.update_lbox1_count()  

        except Exception as e:
            wx.MessageBox(f"Помилка бази даних: {str(e)}", "Увага", wx.OK | wx.ICON_ERROR)
        finally:
            pass


    def on_lbox1_to_lbox2(self, event):
        selected_indices = self.lbox1.GetSelections()
        items_to_move = []
        for index in selected_indices:
            items_to_move.append(self.lbox1.GetString(index))

        for index in sorted(selected_indices, reverse=True):
            self.lbox1.Delete(index)

        for item in items_to_move:
            self.lbox2.Append(item)
        self.lbox2.Refresh()


    def on_lbox2_to_lbox1(self, event):
        selected_indices = self.lbox2.GetSelections()
        items_to_move = []
        for index in selected_indices:
            items_to_move.append(self.lbox2.GetString(index))

        for index in sorted(selected_indices, reverse=True):
            self.lbox2.Delete(index)

        for item in items_to_move:
            self.lbox1.Append(item)
        self.lbox1.Refresh()


    def update_years(self):
        current_year = datetime.now().year
        try:
            sel_spinbox_val = int(self.year_spinbox.GetValue())
        except ValueError:
            sel_spinbox_val = self.current_year

        year_offset = sel_spinbox_val % 10 if sel_spinbox_val else self.current_year % 10

        years = [year for year in range(self.current_decade, self.current_decade + 10) if year <= current_year]

        if years:
            min_year = years[0]
            max_year = years[-1]
            selected_year = years[min(year_offset, len(years) - 1)]
        else:
            min_year = current_year
            max_year = current_year
            selected_year = current_year

        self.year_spinbox.SetRange(min_year, max_year)
        self.year_spinbox.SetValue(selected_year)


    def on_year_spin(self, event):
        pass


    def increase_decade(self, event):
        if self.current_decade + 10 <= datetime.now().year:
            self.current_decade += 10
            self.update_years()

    def decrease_decade(self, event):
        self.current_decade -= 10
        self.update_years()


    def create_progress_bar_wx(self):
        self.progress_gauge.SetValue(0)
        self.progress_gauge.Show()
        self.result_websearch_text.SetPage("")  # Очищаем содержимое
        self.result_websearch_text.Hide() # Скрываем, чтобы показывался только прогресс-бар
        self.Layout()

    def destroy_progress_bar_wx(self):
        self.progress_gauge.SetValue(0)
        self.progress_gauge.Hide()
        self.Layout()


    def on_start_search(self, event):
        self.stop_function_var = 0

        find_names_web = []
        mess_in_result_websearch_text = ""

        single_name = self.entry_last_name.GetValue().strip().upper()
        list_names = [self.lbox2.GetString(i) for i in range(self.lbox2.GetCount())]

        if single_name and not list_names:
            if len(single_name) >= 3:
                find_names_web.append(single_name)
                mess_in_result_websearch_text = single_name
            else:
                wx.MessageBox("Введіть прізвище (мінімум 3 символи) або оберіть зі списку.", "Помилка", wx.OK | wx.ICON_ERROR)
                return
        elif not single_name and list_names:
            find_names_web.extend(list_names)
            mess_in_result_websearch_text = f"{len(find_names_web)} прізвищ" if len(find_names_web) > 1 else find_names_web[0]
        elif single_name and list_names:
            dlg = wx.MessageDialog(self,
                                   "Ви ввели прізвище та перемістили елементи до списку.\n"
                                   "Шукати за прізвищем з поля вводу чи за списком?",
                                   "Вибір джерела пошуку",
                                   wx.YES_NO | wx.CANCEL | wx.ICON_QUESTION)
            dlg.SetYesNoLabels("За полем вводу", "За списком")
            result = dlg.ShowModal()
            dlg.Destroy()

            if result == wx.ID_YES:
                if len(single_name) >= 3:
                    find_names_web.append(single_name)
                    mess_in_result_websearch_text = single_name
                else:
                    wx.MessageBox("Введіть прізвище (мінімум 3 символи) або оберіть зі списку.", "Помилка", wx.OK | wx.ICON_ERROR)
                    return
            elif result == wx.ID_NO:
                find_names_web.extend(list_names)
                mess_in_result_websearch_text = f"{len(find_names_web)} прізвищ" if len(find_names_web) > 1 else find_names_web[0]
            else:
                return
        else:
            wx.MessageBox("Введіть прізвище або оберіть зі списку для пошуку.", "Помилка", wx.OK | wx.ICON_ERROR)
            return

        self.button_search_decree.Hide()
        self.button_stop.Show()

        self.Layout()

        threading.Thread(target=self.run_web_search, args=(find_names_web, mess_in_result_websearch_text)).start()

    
    def run_web_search(self, find_names_web, mess_in_result_websearch_text):
        sel_spinbox = self.year_spinbox.GetValue()
        error_message = ""
        count_search = 0
        all_names_found_no_results = []
        search_successful = True
        html_result = f"<p><b>Здійснюється пошук {mess_in_result_websearch_text} за {sel_spinbox} рік</b></p>"

        # Показываем прогресс-бар и скрываем окно результатов
        wx.CallAfter(self.create_progress_bar_wx) 

        url = "https://zakon.rada.gov.ua/laws/main"
        headers = {
            "User-Agent": "Mozilla/5.0"
        }
        filter_phrase = "Про відзначення державними нагородами України"
        max_results = 100

        for i, find_name in enumerate(find_names_web, start=1):
            if self.stop_function_var == 1:
                error_message = "Пошук зупинено користувачем."
                search_successful = False
                break

            params = {
                "find": "2", "dat": "00000000", "user": "a",
                "text": find_name, "textl": "2", "bool": "and",
                "org": "4", "typ": "3", "yer": "0000", "mon": "00", "day": "00",
                "dat_from": f"{sel_spinbox}-01-01",
                "dat_to": f"{int(sel_spinbox) + 1}-01-01",
                "datl": "3", "numl": "2", "num": "", "minjustl": "2", "minjust": ""
            }

            found_results_for_current_name = False
            try:
                response = requests.get(url, params=params, headers=headers, timeout=10)
                response.raise_for_status()

                count_search += 1
                processed_results = 0
                soup = BeautifulSoup(response.text, "html.parser")
                doc_links = soup.find_all("div", class_="doc")

                html_result += f'<p><b>{count_search}) "{find_name}":</b>'

                if not doc_links:
                    html_result += " (не знайдено)</p>"
                    all_names_found_no_results.append(find_name)
                    continue

                found_results_for_current_name = True
                html_result += "</p><ul>"

                for doc in doc_links:
                    if processed_results >= max_results:
                        html_result += f'<li><i>Досягнуто обмеження на {max_results} результатів.</i></li>'
                        break

                    title = doc.find("a").text.strip()
                    if filter_phrase in title:
                        link = doc.find("a")["href"]
                        date = doc.find("span").text.strip()
                        number = doc.find("strong").text.strip()
                        full_link = urljoin("https://zakon.rada.gov.ua", link)

                        html_result += f'<li>№ <b>{number}</b> від {date} — <a href="{full_link}">{full_link}</a></li>'
                        processed_results += 1

                if found_results_for_current_name and processed_results == 0:
                    html_result += "<li><i>не знайдено</i></li>"

                html_result += "</ul>"

            except requests.exceptions.RequestException as e:
                error_message = f"Помилка доступу до сайту для '{find_name}': {e}"
                search_successful = False
                self.stop_function_var = 1
                break
            except Exception as e:
                error_message = f"Неочікувана помилка при обробці '{find_name}': {e}"
                search_successful = False
                self.stop_function_var = 1
                break

            progress_value = (i / len(find_names_web)) * 100
            wx.CallAfter(self.progress_gauge.SetValue, int(progress_value))

        # --- Завершення ---
        wx.CallAfter(self.destroy_progress_bar_wx)
        wx.CallAfter(self.button_search_decree.Show)
        wx.CallAfter(self.button_stop.Hide)

        if error_message:
            html_result = f'<p style="color:red;"><b>Помилка:</b><br>{error_message}</p>'
            self.update_footer_message("Помилка")

        elif not search_successful:
            html_result = "<p><b>Пошук зупинено користувачем.</b></p>"
            self.update_footer_message("Стоп")

        else:
            html_result = "<p><b>Результат пошуку указів про нагородження:</b></p>" + html_result

            if len(all_names_found_no_results) == len(find_names_web) and len(find_names_web) > 0:
                no_results_message = ("За всіма прізвищами нічого не знайдено." if len(find_names_web) > 1
                                      else f"За прізвищем '{find_names_web[0]}' нічого не знайдено.")
                html_result += f'<p style="color:blue;">{no_results_message}</p>'

            elif all_names_found_no_results:
                not_found_str = ", ".join(all_names_found_no_results)
                html_result += f'<p style="color:blue;">Не знайдено за прізвищами: {not_found_str}</p>'
        
        html_result = f"""
        <html>
          <body bgcolor="#FFFFE0" text="#000000" link="#0000EE">
            <font face="Times New Roman" size="3">
              {html_result}
            </font>
          </body>
        </html>
        """
        # Показываем result_websearch_text после установки содержимого
        wx.CallAfter(self.result_websearch_text.SetPage, html_result)
        wx.CallAfter(self.result_websearch_text.Show) # Показываем окно результатов
        wx.CallAfter(self.Layout) # Обновляем макет

        self.update_footer_message("Готово")


    def create_progress_bar_wx(self):
        # Приховуємо контейнер HtmlWindow
        self.html_results_container.ShowItems(False) 
        # Встановлюємо пропорцію контейнера HtmlWindow на 0
        self.html_results_container_item.SetProportion(0)
        
        # Показуємо контейнер прогрес-бара
        self.progress_gauge.SetValue(0)
        self.progress_bar_container.ShowItems(True) 
        
        # Змінюємо пропорцію top_section_sizer_item, щоб він розтягнувся
        self.top_section_sizer_item.SetProportion(1) # Займе доступний простір

        self.Layout() # Оновлюємо макет

    def destroy_progress_bar_wx(self):
        # Приховуємо контейнер прогрес-бара
        self.progress_gauge.SetValue(0)
        self.progress_bar_container.ShowItems(False)

        # Показуємо контейнер HtmlWindow
        self.html_results_container.ShowItems(True)
        # Встановлюємо пропорцію контейнера HtmlWindow на 1
        self.html_results_container_item.SetProportion(1)
        
        # Повертаємо пропорцію top_section_sizer_item на 0, щоб він зайняв мінімальний розмір
        self.top_section_sizer_item.SetProportion(0)

        self.Layout() # Оновлюємо макет

    def on_stop_search(self, event):
        self.stop_function_var = 1

        self.result_websearch_text.SetPage("") # Очищаємо вміст HtmlWindow
        
        # Повертаємо до стану, коли видно HtmlWindow, а прогрес-бару немає
        self.destroy_progress_bar_wx() 

        self.button_stop.Hide()
        self.button_search_decree.Show()

        self.Layout() # Оновлюємо макет


    # ФУТЕР
    def update_footer_message(self, message):
        if self.fut_place:
            self.last_message = message
            self.fut_place.SetLabel(self.last_message)

    def get_footer_message(self):
        return self.last_message