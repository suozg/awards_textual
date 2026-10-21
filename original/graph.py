# graph.py

import wx
import wx.lib.plot as plot
from database_logic import AwardDataLoader  

class AwardGraphPanel(wx.Panel):
    def __init__(self, parent, cursor, start_year, element_controls): 
        super().__init__(parent, wx.ID_ANY) 
        self.cursor = cursor 
        self.START_YEAR = start_year 
        self.element_controls = element_controls
        self.data_loader = AwardDataLoader(self.START_YEAR) 
        try:
            self.data_loader.load_data(self.cursor) 
        except RuntimeError as e:
            wx.MessageBox(str(e), "Помилка завантаження даних графіка", wx.OK | wx.ICON_ERROR)

        self.init_ui()

    def init_ui(self):
        sizer = wx.BoxSizer(wx.VERTICAL)

        # Створення canvas для графіка
        self.plot_canvas = plot.PlotCanvas(self, wx.ID_ANY) 
        sizer.Add(self.plot_canvas, 1, wx.EXPAND | wx.ALL, 10)

        # Отримуємо дані для графіка
        x_data, y_state, y_all, y_present = self.data_loader.get_graph_data() 
        
        if not x_data or not y_all:
            empty_plot_label = wx.StaticText(self.plot_canvas, wx.ID_ANY, "Немає даних для побудови графіка.")
            sizer.Replace(self.plot_canvas, empty_plot_label)
            self.plot_canvas.Hide()
            sizer.Add(empty_plot_label, 1, wx.ALIGN_CENTER | wx.ALL, 10)
            self.plot_canvas = None 
        else:
            # Налаштування меж осей
            self.plot_canvas.xSpec = (min(x_data), max(x_data))
                        
            all_y_values = []
            if y_state: all_y_values.extend(y_state)
            if y_all: all_y_values.extend(y_all)
            if y_present: all_y_values.extend(y_present)

            ymin = min(all_y_values)
            ymax_real = max(all_y_values)
            padding = max(1, int(ymax_real * 0.05))
            
            self.plot_canvas.ySpec = (ymin, ymax_real + padding)

            # Виклик малювання
            self.draw_graph_with_highlight()

        # Легенда
        legend_panel = wx.Panel(self, wx.ID_ANY)
        legend_sizer = wx.BoxSizer(wx.HORIZONTAL)
        total_all = sum(y_all) if y_all else 0 
        total_state = sum(y_state) if y_state else 0 
        total_present = sum(y_present) if y_present else 0 

        legend_sizer.Add(wx.StaticText(legend_panel, wx.ID_ANY, label=f"🟥 Усі нагороди ({total_all})"), 0, wx.RIGHT, 10)
        legend_sizer.Add(wx.StaticText(legend_panel, wx.ID_ANY, label=f"🟦 Від держави ({total_state})"), 0, wx.RIGHT, 10)
        legend_sizer.Add(wx.StaticText(legend_panel, wx.ID_ANY, label=f"🟩 Подання ({total_present})"), 0)
        legend_panel.SetSizer(legend_sizer)
        sizer.Add(legend_panel, 0, wx.ALIGN_CENTER_HORIZONTAL | wx.BOTTOM, 10)

        # Слайдер
        self.slider_panel = wx.Panel(self, wx.ID_ANY)
        slider_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.slider_label = wx.StaticText(self.slider_panel, wx.ID_ANY, label="")
        slider_max_value = len(x_data) - 1 if x_data else 0
        self.slider = wx.Slider(self.slider_panel, wx.ID_ANY, value=slider_max_value, minValue=0, maxValue=slider_max_value)
        slider_sizer.Add(self.slider_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        slider_sizer.Add(self.slider, 1, wx.EXPAND)
        self.slider_panel.SetSizer(slider_sizer)
        sizer.Add(self.slider_panel, 0, wx.EXPAND | wx.ALL, 10)

        if x_data:
            self.slider.Bind(wx.EVT_SLIDER, self.on_slider_scroll)
            self.slider.SetFocus()
            self.on_slider_scroll(None)
        else:
            self.slider.Disable()
            self.slider_label.SetLabel("Нет данных за годы для слайдера")

        self.SetSizer(sizer)
        self.Layout()
        self.SetMinSize((600, 400))

    def draw_graph_with_highlight(self, highlight_index=None):
        """Малює чисті лінії та вертикальну лінію-індикатор для слайдера без використання маркерів."""
        x_data, y_state, y_all, y_present = self.data_loader.get_graph_data()
        if not x_data:
            return

        # Тільки основні лінії
        line1 = plot.PolyLine(list(zip(x_data, y_state)), colour='#2E86C1', width=2, legend='Від держави')
        line2 = plot.PolyLine(list(zip(x_data, y_all)), colour='#E74C3C', width=2, legend='Усі нагороди')
        line3 = plot.PolyLine(list(zip(x_data, y_present)), colour='#27AE60', width=2, legend='Подання')

        graphics_list = [line1, line2, line3]

        # Додаємо лише вертикальну лінію-орієнтир для обраного року
        if highlight_index is not None and 0 <= highlight_index < len(x_data):
            hx = x_data[highlight_index]
            ymin, ymax = self.plot_canvas.ySpec
            v_line = plot.PolyLine([(hx, ymin), (hx, ymax)], colour='#E67E22', width=2, style=wx.PENSTYLE_DOT)
            graphics_list.append(v_line)

        self.plot_canvas.Draw(
            plot.PlotGraphics(
                graphics_list, 
                "Динаміка нагороджень", 
                "Рік", 
                "Кількість"
            )
        )

    def on_slider_scroll(self, event):
        x_data, y_state, y_all, y_present = self.data_loader.get_graph_data() 

        val = self.slider.GetValue()
        if not x_data or val < 0 or val >= len(x_data):
             text = "** Нет данных для слайдера **"
             self.slider_label.SetLabel(text)
             self.slider_panel.Layout()
             return

        selected_year = x_data[val]
        if selected_year in x_data:
             index = x_data.index(selected_year)
             y_val_state = y_state[index]
             y_val_all = y_all[index]
             percentage = round(y_val_state / y_val_all * 100) if y_val_all else 0
             text = f' ** за {selected_year} рік: {y_val_all} ({y_val_state}, або {percentage}%)'
             
             if self.plot_canvas:
                 self.draw_graph_with_highlight(highlight_index=index)
        else:
             text = f' ** за {selected_year} рік: 0'

        self.slider_label.SetLabel(text)
        self.slider_panel.Layout()

    def get_status_text(self):
        return self.data_loader.get_status_text()
