import wx
from config import DEF_FUT_LABEL

def get_focusable_fields(panel):
    """Динамічно збирає список фокусованих полів та чекбоксів з панелі (без індикаторів)"""
    fields = [
        getattr(panel, 'person_search_results_ctrl', None), # 1
        getattr(panel, 'full_name_ctrl', None),             # 2
        getattr(panel, 'inn', None),                        # 3
        getattr(panel, 'rank_ctrl', None),                  # 4
        getattr(panel, 'unit_ctrl', None),                  # 5
        #getattr(panel, 'pres_ctrl', None),                  # 6
        getattr(panel, 'submission_number_ctrl', None),     # 7
        getattr(panel, 'PresDATE', None),                   # 8
        getattr(panel, 'submission_executor_ctrl', None),   # 9
        getattr(panel, 'submission_movement_ctrl', None),   # 10
        getattr(panel, 'submission_posthumous_checkbox', None), # 11
        getattr(panel, 'pres_denied_checkbox', None),           # 12
        getattr(panel, 'pres_unlink_meed_checkbox', None),      # 13
        getattr(panel, 'text_pres', None),                  # 14
        getattr(panel, 'meed_ctrl', None),                  # 15
        getattr(panel, 'award_ctrl', None),                 # 16
        getattr(panel, 'award_basis_ctrl', None),           # 17
        getattr(panel, 'award_date_ctrl', None),            # 18
        getattr(panel, 'meed_dead_checkbox', None),         # 19
        getattr(panel, 'ConsingN', None),                   # 20
        getattr(panel, 'NumberMeed', None),                 # 21
        getattr(panel, 'HandoverDATE', None),               # 22
        getattr(panel, 'HandowerNAME', None),               # 23
        getattr(panel, 'protok_handing', None),             # 24
    ]
    return [f for f in fields if f is not None]

# Словник для збереження оригінальних текстів міток
_original_labels = {}

def setup_accelerators(panel, save_callback, find_callback, clear_callback):
    id_save = wx.NewIdRef()
    id_find = wx.NewIdRef()
    id_clear = wx.NewIdRef()

    panel.Bind(wx.EVT_MENU, save_callback, id=id_save)
    panel.Bind(wx.EVT_MENU, find_callback, id=id_find)
    panel.Bind(wx.EVT_MENU, clear_callback, id=id_clear)

    accel_entries = [
        wx.AcceleratorEntry(wx.ACCEL_CTRL, ord('S'), id_save),
        wx.AcceleratorEntry(wx.ACCEL_CTRL, ord('F'), id_find),
        wx.AcceleratorEntry(wx.ACCEL_CTRL, ord('N'), id_clear),
    ]
    panel.SetAcceleratorTable(wx.AcceleratorTable(accel_entries))

def _get_associated_label(panel, field):
    """Знаходить StaticText, що відповідає конкретному полю у макеті kartka.py"""
    if isinstance(field, wx.CheckBox):
        return field  # Чекбокси є власними мітками

    if field == getattr(panel, 'person_search_results_ctrl', None):
        parent = field.GetParent()
        if parent and parent.GetSizer():
            for child in parent.GetSizer().GetChildren():
                w = child.GetWindow()
                if isinstance(w, wx.StaticText) and w.GetLabel().startswith("ID:"):
                    return w

    if field == getattr(panel, 'pres_ctrl', None):
        parent = field.GetParent()
        if parent and parent.GetSizer():
            found_id = False
            for child in parent.GetSizer().GetChildren():
                w = child.GetWindow()
                if isinstance(w, wx.StaticText) and w.GetLabel().startswith("ID:"):
                    if found_id:
                        return w
                    found_id = True

    parent = field.GetParent()
    if not parent:
        return None

    sizer = parent.GetSizer()
    if sizer and hasattr(sizer, 'GetChildren'):
        children = sizer.GetChildren()
        for i, child in enumerate(children):
            if child.GetWindow() == field and i > 0:
                prev_child = children[i - 1].GetWindow()
                if isinstance(prev_child, wx.StaticText):
                    return prev_child

    if hasattr(parent, 'GetChildren'):
        siblings = parent.GetChildren()
        for i, sibling in enumerate(siblings):
            if sibling == field and i > 0:
                for j in range(i - 1, -1, -1):
                    if isinstance(siblings[j], wx.StaticText):
                        return siblings[j]

    return None

def show_field_numbers(panel, show=True):
    global _original_labels
    fields = get_focusable_fields(panel)
    
    for idx, field in enumerate(fields, start=1):
        if not field:
            continue
        
        label_obj = _get_associated_label(panel, field)
        if label_obj:
            if show:
                if label_obj not in _original_labels:
                    _original_labels[label_obj] = label_obj.GetLabel()
                orig_text = _original_labels[label_obj].rstrip()
                
                for i in range(1, 100):
                    orig_text = orig_text.replace(f" ({i})", "")
                
                label_obj.SetLabel(f"{orig_text} ({idx})")
            else:
                if label_obj in _original_labels:
                    label_obj.SetLabel(_original_labels[label_obj])
    panel.Layout()


def bind_help_tooltips(panel):
    panel._jump_buffer = ""
    panel._jump_mode_active = False

    def process_key_down(event):
        keycode = event.GetKeyCode()
        uni_char = event.GetUnicodeKey()
        ctrl_down = event.ControlDown()

        # Універсальне переведення символу у верхній регістр (працює і для латиниці, і для кирилиці)
        char_upper = ''
        if uni_char != wx.WXK_NONE:
            try:
                char_upper = chr(uni_char).upper()
            except ValueError:
                pass

        # --------------------------------------------------
        # Обробка глобальних комбінацій Ctrl + S / F / N (робота з будь-якою розкладкою)
        # --------------------------------------------------
        if ctrl_down:
            if char_upper in ('S', 'Ы', 'І') or keycode in (ord('S'), ord('s')):
                if hasattr(panel, '_save_cb') and panel._save_cb:
                    panel._save_cb(event)
                    return
            elif char_upper in ('F', 'А') or keycode in (ord('F'), ord('f')):
                if hasattr(panel, '_find_cb') and panel._find_cb:
                    panel._find_cb(event)
                    return
            elif char_upper in ('N', 'Т') or keycode in (ord('N'), ord('n')):
                if hasattr(panel, '_clear_cb') and panel._clear_cb:
                    panel._clear_cb(event)
                    return

        # 1. Активація режиму Ctrl+G (або Ctrl+П в українській розкладці)
        if ctrl_down and (char_upper in ('G', 'П') or keycode in (ord('G'), ord('g'))):
            panel._jump_mode_active = True
            panel._jump_buffer = ""

            # Забираємо фокус із поточного поля
            panel.SetFocus()

            panel.update_footer_message(
                "РЕЖИМ ПЕРЕМІЩЕННЯ [Введіть номер + Enter, або J/K (О/Л), Esc для виходу]"
            )
            show_field_numbers(panel, show=True)
            return

        # Якщо режим переміщення активний
        if panel._jump_mode_active:

            # --------------------------------------------------
            # Esc — вихід із режиму
            # --------------------------------------------------
            if keycode == wx.WXK_ESCAPE:
                panel._jump_mode_active = False
                panel._jump_buffer = ""
                show_field_numbers(panel, show=False)
                panel.update_footer_message(DEF_FUT_LABEL)
                return

            # --------------------------------------------------
            # J / О — наступне поле (J в латиниці, О в українській)
            # --------------------------------------------------
            if char_upper in ('J', 'О') or keycode in (ord('J'), ord('j')):
                _navigate_fields(panel, direction=1)
                return

            # --------------------------------------------------
            # K / Л — попереднє поле (K в латиниці, Л в українській)
            # --------------------------------------------------
            if char_upper in ('K', 'Л') or keycode in (ord('K'), ord('k')):
                _navigate_fields(panel, direction=-1)
                return

            # --------------------------------------------------
            # Цифри — тільки накопичуємо номер поля
            # --------------------------------------------------
            is_digit = (
                (ord('0') <= keycode <= ord('9'))
                or
                (wx.WXK_NUMPAD0 <= keycode <= wx.WXK_NUMPAD9)
            )

            if is_digit:
                if wx.WXK_NUMPAD0 <= keycode <= wx.WXK_NUMPAD9:
                    digit = str(keycode - wx.WXK_NUMPAD0)
                else:
                    digit = chr(keycode)

                panel._jump_buffer += digit

                panel.update_footer_message(
                    f"РЕЖИМ ПЕРЕМІЩЕННЯ --- "
                    f"Поле №: {panel._jump_buffer} (Натисніть Enter)"
                )
                return

            # --------------------------------------------------
            # Enter — перейти до поля
            # --------------------------------------------------
            if keycode in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
                if panel._jump_buffer:
                    fields = get_focusable_fields(panel)

                    try:
                        field_index = int(panel._jump_buffer) - 1

                        if 0 <= field_index < len(fields):
                            target_field = fields[field_index]

                            if target_field:
                                target_field.SetFocus()
                                panel.update_footer_message(DEF_FUT_LABEL)
                            else:
                                panel.update_footer_message(
                                    "Помилка: такого номера поля не існує!"
                                )

                    except ValueError:
                        pass

                    panel._jump_mode_active = False
                    panel._jump_buffer = ""

                    show_field_numbers(panel, show=False)

                return

            # Будь-яка інша клавіша в режимі переміщення блокується
            return

        # Звичайний режим — клавіші працюють нормально
        event.Skip()

    panel.Bind(wx.EVT_KEY_DOWN, process_key_down)
    wx.CallAfter(lambda: _bind_children_recursively(panel, process_key_down, lambda e: e.Skip()))

def _navigate_fields(panel, direction=1):
    fields = get_focusable_fields(panel)
    valid_fields = [f for f in fields if f and f.IsShown()]
    if not valid_fields:
        return

    current_focus = wx.Window.FindFocus()
    
    current_idx = -1
    for idx, f in enumerate(valid_fields):
        if f == current_focus:
            current_idx = idx
            break
            
    if current_idx == -1:
        current_idx = 0 if direction > 0 else len(valid_fields) - 1
    else:
        current_idx = (current_idx + direction) % len(valid_fields)
        
    valid_fields[current_idx].SetFocus()

def _bind_children_recursively(parent, down_handler, up_handler):
    for child in parent.GetChildren():
        if child:
            child.Bind(wx.EVT_KEY_DOWN, down_handler)
            child.Bind(wx.EVT_KEY_UP, up_handler)
            if hasattr(child, 'GetChildren'):
                _bind_children_recursively(child, down_handler, up_handler)
