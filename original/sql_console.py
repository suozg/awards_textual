import wx
import wx.grid
import csv

class SqlConsolePanel(wx.Panel):
    def __init__(self, parent, conn, cursor, fut_place=None):
        super().__init__(parent)

        self.conn = conn
        self.cursor = cursor
        self.fut_place = fut_place
        self.schema = self.load_db_schema()

        main_sizer = wx.BoxSizer(wx.VERTICAL)

        # --- Поле ввода SQL ---
        main_sizer.Add(
            wx.StaticText(
                self, label="SQL запит (Ctrl+Shift+Space — автоввід). НЕ ЗНАЄШ БРОДУ - НЕ ЛІЗЬ У ВОДУ!!!:"
            ), 0, wx.ALL, 5
        )

        self.sql_input = wx.TextCtrl(
            self,
            style=wx.TE_MULTILINE | wx.TE_DONTWRAP,
            size=(-1, 120)  # -1 — ширина по умолчанию, 180 — высота в пикселях
        )
        self.sql_input.Bind(wx.EVT_KEY_DOWN, self.on_key_down)
        main_sizer.Add(self.sql_input, 0, wx.EXPAND | wx.ALL, 5)

        # --- Кнопки на одном ряду ---
        btn_sizer = wx.BoxSizer(wx.HORIZONTAL)

        run_btn = wx.Button(self, label="Виконати")
        run_btn.Bind(wx.EVT_BUTTON, self.on_execute)
        btn_sizer.Add(run_btn, 0, wx.RIGHT, 5)

        explain_btn = wx.Button(self, label="EXPLAIN")
        explain_btn.Bind(wx.EVT_BUTTON, self.on_explain)
        btn_sizer.Add(explain_btn, 0, wx.RIGHT, 5)

        export_btn = wx.Button(self, label="CSV")
        export_btn.Bind(wx.EVT_BUTTON, self.on_export_csv)
        btn_sizer.Add(export_btn, 0)

        main_sizer.Add(btn_sizer, 0, wx.ALL, 5)

        # --- Grid для вывода ---
        self.grid = wx.grid.Grid(self)
        self.grid.CreateGrid(0, 0)
        self.grid.SetRowLabelSize(60)  # настройка левого столбца
        font = wx.Font(9, wx.FONTFAMILY_TELETYPE, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL)
        self.grid.SetFont(font)
        self.grid.EnableEditing(False)
        self.grid.EnableDragGridSize(False)
        self.grid.SetMargins(0, 0)
        self.grid.AutoSizeColumns()
        main_sizer.Add(self.grid, 1, wx.EXPAND | wx.ALL, 5)

        self.SetSizer(main_sizer)

    # --- Выполнение SQL ---
    def on_execute(self, event):
        sql = self.sql_input.GetValue().strip()
        if not sql:
            return

        try:
            self.cursor.execute(sql)
            if sql.lower().startswith("select"):
                rows = self.cursor.fetchall()
                cols = [d[0] for d in self.cursor.description]
                self.show_grid(rows, cols)
            else:
                self.conn.commit()
                wx.MessageBox("Запит виконано успішно.", "OK", wx.OK | wx.ICON_INFORMATION)
            if self.fut_place:
                self.fut_place.SetLabel("SQL: виконано")
        except Exception as e:
            wx.MessageBox(str(e), "Помилка", wx.OK | wx.ICON_ERROR)
            if self.fut_place:
                self.fut_place.SetLabel("SQL: помилка")

    # --- EXPLAIN ---
    def on_explain(self, event):
        sql = self.sql_input.GetValue().strip()
        if not sql.lower().startswith("select"):
            wx.MessageBox("EXPLAIN доступний лише для SELECT", "Помилка", wx.OK | wx.ICON_WARNING)
            return
        try:
            self.cursor.execute(f"EXPLAIN QUERY PLAN {sql}")
            rows = self.cursor.fetchall()
            cols = ["id", "parent", "notused", "detail"]
            self.show_grid(rows, cols)
            if self.fut_place:
                self.fut_place.SetLabel("SQL: EXPLAIN")
        except Exception as e:
            wx.MessageBox(str(e), "Помилка", wx.OK | wx.ICON_ERROR)

    # --- Экспорт CSV ---
    def on_export_csv(self, event):
        sql = self.sql_input.GetValue().strip()
        if not sql.lower().startswith("select"):
            wx.MessageBox("CSV доступний лише для SELECT", "Помилка", wx.OK | wx.ICON_WARNING)
            return

        dlg = wx.FileDialog(self, "Зберегти CSV", wildcard="CSV files (*.csv)|*.csv",
                            style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT)
        if dlg.ShowModal() != wx.ID_OK:
            return
        path = dlg.GetPath()
        try:
            self.cursor.execute(sql)
            rows = self.cursor.fetchall()
            headers = [d[0] for d in self.cursor.description]

            with open(path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f, delimiter=";")
                writer.writerow(headers)
                writer.writerows(rows)

            wx.MessageBox("CSV збережено", "OK", wx.OK | wx.ICON_INFORMATION)
        except Exception as e:
            wx.MessageBox(str(e), "Помилка", wx.OK | wx.ICON_ERROR)

    # --- Заполнение Grid ---
    def show_grid(self, rows, headers):
        self.grid.ClearGrid()
        if self.grid.GetNumberRows() > 0:
            self.grid.DeleteRows(0, self.grid.GetNumberRows())
        if self.grid.GetNumberCols() > 0:
            self.grid.DeleteCols(0, self.grid.GetNumberCols())

        self.grid.AppendCols(len(headers))
        for c, h in enumerate(headers):
            self.grid.SetColLabelValue(c, h)

        self.grid.AppendRows(len(rows))
        for r, row in enumerate(rows):
            for c, val in enumerate(row):
                self.grid.SetCellValue(r, c, str(val) if val is not None else "")

        self.grid.AutoSizeColumns()
        self.grid.AutoSizeRows()

    # --- Автодополнение (Ctrl+Shift+Space) ---
    def on_key_down(self, event):
        if event.ControlDown() and event.ShiftDown() and event.GetKeyCode() == wx.WXK_SPACE:
            self.show_autocomplete()
            return
        event.Skip()

    def show_autocomplete(self):
        menu = wx.Menu()
        for kw in self.schema["keywords"]:
            item = menu.Append(wx.ID_ANY, kw)
            self.Bind(wx.EVT_MENU, lambda e, t=kw: self.insert_text(t), item)

        for table, cols in self.schema["tables"].items():
            item = menu.Append(wx.ID_ANY, table)
            self.Bind(wx.EVT_MENU, lambda e, t=table: self.insert_text(t), item)
            sub = wx.Menu()
            for col in cols:
                ci = sub.Append(wx.ID_ANY, col)
                self.Bind(wx.EVT_MENU, lambda e, c=col: self.insert_text(c), ci)
            menu.AppendSubMenu(sub, f"{table}.*")

        self.PopupMenu(menu)
        menu.Destroy()

    def insert_text(self, text):
        pos = self.sql_input.GetInsertionPoint()
        self.sql_input.WriteText(text + " ")
        self.sql_input.SetInsertionPoint(pos + len(text) + 1)

    # --- Схема БД для автодополнения ---
    def load_db_schema(self):
        schema = {"tables": {}, "keywords": []}
        schema["keywords"] = [
            "SELECT", "INSERT", "UPDATE", "DELETE", "FROM", "WHERE",
            "JOIN", "LEFT", "RIGHT", "INNER", "OUTER", "ON",
            "GROUP BY", "ORDER BY", "HAVING", "LIMIT",
            "CREATE", "DROP", "ALTER",
            "EXPLAIN", "QUERY", "PLAN"
        ]
        self.cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
        for (table,) in self.cursor.fetchall():
            self.cursor.execute(f"PRAGMA table_info({table})")
            cols = [row[1] for row in self.cursor.fetchall()]
            schema["tables"][table] = cols
        return schema

