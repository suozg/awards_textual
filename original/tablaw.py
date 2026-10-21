import wx
import wx.adv
from datetime import datetime
import wx.dataview as dv
from wx.dataview import TreeListCtrl, NullDataViewItem
from database_logic import execute_query
from config import DEF_FUT_LABEL
import webbrowser


class LawsPanel(wx.Panel):
    def __init__(self, parent, conn, cursor, fut_place=None):
        super().__init__(parent, wx.ID_ANY)
        self.conn = conn
        self.cursor = cursor 
        self.fut_place = fut_place
        self.last_message = DEF_FUT_LABEL
        self.init_ui()

    def init_ui(self):
        main_sizer = wx.BoxSizer(wx.VERTICAL)

        # Верхній блок
        group_top_box = wx.StaticBox(self, label=" ПОСИЛАННЯ НА ДЕЯКІ НОРМАТИВНІ АКТИ ")
        group_top_sizer = wx.StaticBoxSizer(group_top_box, wx.VERTICAL)
        main_sizer.Add(group_top_sizer, proportion=1, flag=wx.EXPAND | wx.ALL, border=5)

        # Нижний блок (без StaticBox)
        group_bottom_sizer = wx.BoxSizer(wx.HORIZONTAL)
        main_sizer.Add(group_bottom_sizer, proportion=0, flag=wx.EXPAND | wx.ALL, border=5)

        # Кнопка для изменения записей
        self.edit_law_btn = wx.Button(self, label="Змінити")
        self.edit_law_btn.Bind(wx.EVT_BUTTON, self.edit_law)
        group_bottom_sizer.AddStretchSpacer()
        group_bottom_sizer.Add(self.edit_law_btn, flag=wx.RIGHT | wx.ALIGN_CENTER_VERTICAL, border=10)

        # Кнопка для добавления записи
        self.add_law_btn = wx.Button(self, label="Додати")
        self.add_law_btn.Bind(wx.EVT_BUTTON, self.add_new_law)
        group_bottom_sizer.Add(self.add_law_btn, flag=wx.RIGHT | wx.ALIGN_CENTER_VERTICAL, border=10)

        self.tree = TreeListCtrl(group_top_sizer.GetStaticBox())
        self.tree.AppendColumn("Номер", width=100)        
        self.tree.AppendColumn("Дата", width=100)
        self.tree.AppendColumn("Назва", width=200)
        group_top_sizer.Add(self.tree, proportion=1, flag=wx.EXPAND)

        self.SetSizer(main_sizer)

        self.tree.Bind(dv.EVT_TREELIST_ITEM_ACTIVATED, self.on_item_activated)

        if self.fut_place:
            self.fut_place.SetLabel(self.last_message)  # обновляем футер

    def get_footer_message(self):
        return self.last_message

    def add_new_law(self, event=None):
        dlg = LawEditDialog(self, self.conn, self.cursor, self.refresh_tree, law_id=None)
        dlg.ShowModal()
        dlg.Destroy()

    def edit_law(self, event=None):
        items = self.tree.GetSelections()
        if not items:
            wx.MessageBox("Будь ласка, оберіть запис для редагування.", "Увага", wx.OK | wx.ICON_WARNING)
            return

        selected_item = items[0]
        law_id = None

        if selected_item and self.tree.GetItemData(selected_item):
            data = self.tree.GetItemData(selected_item)
            if isinstance(data, dict) and "id" in data:
                law_id = data["id"]

        dlg = LawEditDialog(self, self.conn, self.cursor, self.refresh_tree, law_id=law_id)
        dlg.ShowModal()
        dlg.Destroy()

    def refresh_tree(self):
        self.tree.DeleteAllItems()

        rows = execute_query(self.cursor, "SELECT id_law, law_date, law_denotation, law_link, law_number FROM law ORDER BY law_date")

        for row in rows:
            # row = (id_law, law_date, law_denotation, law_link)
            item = self.tree.AppendItem(self.tree.GetRootItem(), "")
            self.tree.SetItemText(item, 0, row[4])  # law_number
            self.tree.SetItemText(item, 1, row[1])  # law_date
            self.tree.SetItemText(item, 2, row[2])  # law_denotation

            self.tree.SetItemData(item, {
                "id": row[0],
                "url": row[3]
            })


    def on_item_activated(self, event):
        item = event.GetItem()
        data = self.tree.GetItemData(item)

        if data and isinstance(data, dict):
            if wx.GetKeyState(wx.WXK_CONTROL):  # Ctrl натиснуто
                dlg = LawEditDialog(
                    self,
                    self.conn,
                    self.cursor,
                    self.refresh_tree,
                    law_id=data["id"]
                )
                dlg.ShowModal()
                dlg.Destroy()
            else:
                url = data.get("url", "")
                if url:
                    webbrowser.open(url)




class LawEditDialog(wx.Dialog):
    def __init__(self, parent, conn, cursor, refresh_callback, law_id=None):
        super().__init__(parent, title="Форма змін списку нормативних актів", size=(600, 400))
        self.conn = conn
        self.cursor = cursor
        self.refresh_callback = refresh_callback
        self.law_id = law_id  # зберігаємо ID
        self.init_ui()
        if self.law_id:
            self.load_law_data()


    def init_ui(self):
        panel = wx.Panel(self)
        sizer = wx.BoxSizer(wx.VERTICAL)

        form_box = wx.StaticBox(panel, label=" РЕДАГУВАННЯ СПИСКУ НОРМАТИВНИХ АКТІВ ")
        form_sizer = wx.StaticBoxSizer(form_box, wx.VERTICAL)

        grid = wx.FlexGridSizer(4, 2, 10, 10)
        grid.AddGrowableCol(1)

        self.link_entry = wx.TextCtrl(panel)
        self.name_entry = wx.TextCtrl(panel)
        self.number_entry = wx.TextCtrl(panel)
        self.date_entry = wx.adv.DatePickerCtrl(panel, style=wx.adv.DP_DROPDOWN | wx.adv.DP_SHOWCENTURY)

        grid.Add(wx.StaticText(panel, label="Посилання:"), 0, wx.ALIGN_CENTER_VERTICAL)
        grid.Add(self.link_entry, 1, wx.EXPAND)

        grid.Add(wx.StaticText(panel, label="Назва:"), 0, wx.ALIGN_CENTER_VERTICAL)
        grid.Add(self.name_entry, 1, wx.EXPAND)

        grid.Add(wx.StaticText(panel, label="Номер:"), 0, wx.ALIGN_CENTER_VERTICAL)
        grid.Add(self.number_entry, 1, wx.EXPAND)

        grid.Add(wx.StaticText(panel, label="Дата:"), 0, wx.ALIGN_CENTER_VERTICAL)
        grid.Add(self.date_entry, 1, wx.EXPAND)

        form_sizer.Add(grid, flag=wx.ALL | wx.EXPAND, border=10)

        # Чекбокс
        self.del_checkbox = wx.CheckBox(panel, label="- видалити")
        form_sizer.Add(self.del_checkbox, flag=wx.LEFT | wx.TOP, border=10)

        # Кнопка збереження
        btn = wx.Button(panel, label="Зберегти")
        btn.Bind(wx.EVT_BUTTON, self.on_save)
        form_sizer.Add(btn, flag=wx.LEFT | wx.TOP, border=10)

        sizer.Add(form_sizer, proportion=1, flag=wx.EXPAND | wx.ALL, border=10)
        panel.SetSizer(sizer)

    def load_law_data(self):
        query = "SELECT law_denotation, law_link, law_number, law_date FROM law WHERE id_law = ?"
        self.cursor.execute(query, (self.law_id,))
        row = self.cursor.fetchone()
        if row:
            self.name_entry.SetValue(row[0] or "")
            self.link_entry.SetValue(row[1] or "")
            self.number_entry.SetValue(row[2] or "")
            try:
                date = datetime.strptime(row[3], "%Y-%m-%d")
                self.date_entry.SetValue(wx.DateTime.FromDMY(date.day, date.month - 1, date.year))
            except Exception:
                pass

    def on_save(self, event):
        name = self.name_entry.GetValue()
        link = self.link_entry.GetValue()
        number = self.number_entry.GetValue()
        date = self.date_entry.GetValue()

        if self.del_checkbox.IsChecked():
            if self.law_id:
                query = "DELETE FROM law WHERE id_law=?"
                self.cursor.execute(query, (self.law_id,))
        else:
            if self.law_id:
                query = """
                UPDATE law
                SET law_denotation=?, law_link=?, law_date=?, law_number=?
                WHERE id_law=?
                """
                self.cursor.execute(query, (name, link, date.FormatISODate(), number, self.law_id))
            else:
                query = """
                INSERT INTO law (law_denotation, law_link, law_date, law_number)
                VALUES (?, ?, ?, ?)
                """
                self.cursor.execute(query, (name, link, date.FormatISODate(), number))

        self.conn.commit()
        self.refresh_callback()
        self.Close()

