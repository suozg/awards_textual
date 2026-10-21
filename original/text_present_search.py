# text_panel.py
import wx
from database_logic import search_presentations, get_presentation_info

class SearchPanel(wx.Panel):
    def __init__(self, parent, conn, cursor, fut_place=None):
        super().__init__(parent, wx.ID_ANY)
        self.conn = conn
        self.cursor = cursor 
        self.fut_place = fut_place
        self.last_message = ""
        self.results = []

        main_sizer = wx.BoxSizer(wx.VERTICAL)

        group_box = wx.StaticBox(self, label=" Пошук подання по тексту ")
        group_sizer = wx.StaticBoxSizer(group_box, wx.VERTICAL)

        # Поисковий рядок
        search_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.search_ctrl = wx.TextCtrl(self, size=(400, -1), style=wx.TE_PROCESS_ENTER)
        self.search_ctrl.Bind(wx.EVT_TEXT_ENTER, self.on_search)
        search_btn = wx.Button(self, label="Пошук")
        search_btn.Bind(wx.EVT_BUTTON, self.on_search)
        search_sizer.Add(self.search_ctrl, 1, wx.RIGHT, 5)
        search_sizer.Add(search_btn)
        group_sizer.Add(search_sizer, 0, wx.EXPAND | wx.ALL, 5)

        # Результати
        results_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.listbox = wx.ListBox(self, style=wx.LB_SINGLE)
        self.listbox.Bind(wx.EVT_LISTBOX, self.on_select)
        results_sizer.Add(self.listbox, 0, wx.EXPAND | wx.RIGHT, 5)

        self.text_ctrl = wx.TextCtrl(self, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.VSCROLL)
        results_sizer.Add(self.text_ctrl, 1, wx.EXPAND)

        group_sizer.Add(results_sizer, 1, wx.EXPAND | wx.ALL, 5)

        main_sizer.Add(group_sizer, 1, wx.EXPAND | wx.ALL, 2)
        self.SetSizer(main_sizer)

        wx.CallAfter(self.show_help)

    def get_footer_message(self):
        return self.last_message

    def on_search(self, event=None):
        query = self.search_ctrl.GetValue().strip()
        status, results, message = search_presentations(self.cursor, query) 
        self.listbox.Clear()
        self.text_ctrl.SetValue("")

        if status == "EMPTY":
            wx.MessageBox(message, "Помилка", wx.ICON_WARNING)
            return
        elif status == "ERROR":
            wx.MessageBox(message, "Помилка", wx.ICON_ERROR)
            return
        elif not results:
            self.show_help("Не знайдено.\n\n------------")
        else:
            self.results = results
            for row in results:
                self.listbox.Append(str(row[0]))
        if self.fut_place:
            self.last_message = message  
            self.fut_place.SetLabel(self.last_message)  # обновляем футер

    def on_select(self, event):
        selection = self.listbox.GetSelection()
        if selection == wx.NOT_FOUND:
            return

        pres_id = int(self.listbox.GetString(selection))
        for row in self.results:
            if row[0] == pres_id:
                self.text_ctrl.SetValue(row[1])
                extra_info = get_presentation_info(self.cursor, pres_id) # Змінено виклик
                if extra_info:
                    reg, date, meed = extra_info
                    status = " *(відмовлено)" if meed == "0" else ""
                    if self.fut_place:
                        self.last_message = f"[{pres_id}] Подання № {reg} від {date}{status}"
                        self.fut_place.SetLabel(self.last_message)
                break

    def show_help(self, addon=""):
        help_text = f"""{addon}
1. Пошук одного слова
\tслово
Знайде усі записи, що містять указане слово.

2. Пошук декілька слів (AND)
\tслово1 слово2
Знайде записи, що містять обидва слова.

3. Пошук з OR
\tслово1 OR слово2
Знайде записи, які містять хоча б одне зі слів.

4. Пошук фрази (використовуємо лапки)
\tʼточная фразаʼ
Знайде точне співпадіння заданої фрази.

5. Виключення слів (NOT, -)
\tслово1 -слово2
Знайде записи, які містять слово1, але не слово2.

6. Пошук за близкістю слів (NEAR)
\tслово1 NEAR/5 слово2
Слова не далі ніж в 5 словах одне від одного.

7. Пошук за префіксом
\tсло*
Знайде слова, що починаються з 'сло'.
"""
        self.text_ctrl.SetValue(help_text)
