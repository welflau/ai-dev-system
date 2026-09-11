# Copyright P111 Project. All Rights Reserved.
# 一次性脚本：修复 4 个 WBP_Row_* 的布局缺陷
#   1) HorizontalBoxSlot.SizeRule = Fill 让 Slider/ComboBox 撑开宽度
#   2) DisplayName_Label / Value_Text 字号 = 16, MinDesiredWidth 锁宽
#   3) CheckBox CheckedImage/UncheckedImage 尺寸放大
#   4) Root_HBox CanvasPanelSlot anchors=Fill, size 撑满父 Row Widget
# 用法：在 UE Editor Python 控制台执行 py D:\UGit\P111\Plugins\UEEditorMCP\Python\p111_fix_settings_rows_layout.py

import unreal

ROW_WBPS = [
    ('/Game/P111/UI/Settings/Rows/WBP_Row_Slider',   'Slider'),
    ('/Game/P111/UI/Settings/Rows/WBP_Row_ComboBox', 'ComboBox'),
    ('/Game/P111/UI/Settings/Rows/WBP_Row_CheckBox', 'CheckBox'),
    ('/Game/P111/UI/Settings/Rows/WBP_Row_Text',     'Text'),
]

# Row 容器目标尺寸：ScrollBox 内宽 ~1152
ROW_WIDTH = 1100.0
ROW_HEIGHT = 56.0

# Label 子项
LABEL_FILL_SIZE = 0.0    # SizeRule=Auto（不参与 Fill 分配）
LABEL_MIN_WIDTH = 280.0  # 通过 MinDesiredWidth 锁定 Label 宽度
LABEL_FONT_SIZE = 16

# 中间值控件（Slider/Combo）的 Fill 比例
VALUE_MAIN_FILL = 1.0

# 右侧 Value_Text（Slider 行用）
VALUE_TEXT_MIN_WIDTH = 120.0
VALUE_TEXT_FONT_SIZE = 16

# CheckBox/Text 行的右侧值
RIGHT_VALUE_FIXED_WIDTH = 60.0


def _get_widget_tree(wbp_path):
    """加载 WBP 资产并返回 (asset, widget_tree, blueprint)。"""
    asset = unreal.EditorAssetLibrary.load_asset(wbp_path)
    if asset is None:
        unreal.log_error(f'[FixRows] 加载失败: {wbp_path}')
        return None, None, None
    # asset 实际上就是 WidgetBlueprint
    widget_tree = asset.widget_tree if hasattr(asset, 'widget_tree') else asset.get_editor_property('WidgetTree')
    return asset, widget_tree, asset


def _find_widget_by_name(widget_tree, name):
    """递归找名字为 name 的 widget。"""
    found = [None]

    def visit(w):
        if w is None or found[0] is not None:
            return
        if w.get_name() == name or w.get_fname().to_string() == name:
            found[0] = w
            return
        # children
        if hasattr(w, 'get_children_count'):
            try:
                cnt = w.get_children_count()
                for i in range(cnt):
                    visit(w.get_child_at(i))
            except Exception:
                pass

    root = widget_tree.root_widget
    visit(root)
    return found[0]


def _all_widgets(widget_tree):
    """返回所有 UWidget（含 Root）。"""
    out = []

    def visit(w):
        if w is None:
            return
        out.append(w)
        if hasattr(w, 'get_children_count'):
            try:
                cnt = w.get_children_count()
                for i in range(cnt):
                    visit(w.get_child_at(i))
            except Exception:
                pass

    visit(widget_tree.root_widget)
    return out


def _set_hbox_slot(widget, size_rule, fill_value, h_align='Fill', v_align='Center', padding=(12.0, 6.0, 12.0, 6.0)):
    """设 HorizontalBoxSlot 的 Size.SizeRule + Size.Value + Padding + Alignment。
    size_rule: 'Auto' | 'Fill'
    """
    slot = widget.slot
    if slot is None:
        unreal.log_warning(f'[FixRows] {widget.get_name()} 没有 slot')
        return False
    if not isinstance(slot, unreal.HorizontalBoxSlot):
        unreal.log_warning(f'[FixRows] {widget.get_name()} slot 不是 HorizontalBoxSlot ({type(slot).__name__})')
        return False
    # SlateChildSize
    size = unreal.SlateChildSize()
    size.size_rule = unreal.SlateSizeRule.AUTOMATIC if size_rule == 'Auto' else unreal.SlateSizeRule.FILL
    size.value = fill_value
    slot.set_size(size)
    # padding
    pad = unreal.Margin(padding[0], padding[1], padding[2], padding[3])
    slot.set_padding(pad)
    # alignment
    h_map = {'Fill': unreal.HorizontalAlignment.H_ALIGN_FILL, 'Left': unreal.HorizontalAlignment.H_ALIGN_LEFT,
             'Center': unreal.HorizontalAlignment.H_ALIGN_CENTER, 'Right': unreal.HorizontalAlignment.H_ALIGN_RIGHT}
    v_map = {'Fill': unreal.VerticalAlignment.V_ALIGN_FILL, 'Top': unreal.VerticalAlignment.V_ALIGN_TOP,
             'Center': unreal.VerticalAlignment.V_ALIGN_CENTER, 'Bottom': unreal.VerticalAlignment.V_ALIGN_BOTTOM}
    slot.set_horizontal_alignment(h_map.get(h_align, unreal.HorizontalAlignment.H_ALIGN_FILL))
    slot.set_vertical_alignment(v_map.get(v_align, unreal.VerticalAlignment.V_ALIGN_CENTER))
    return True


def _set_canvas_slot_fill(widget):
    """把 root HBox 的 CanvasPanelSlot 设为 anchors=Fill, offset=0 让其撑满父容器。"""
    slot = widget.slot
    if slot is None or not isinstance(slot, unreal.CanvasPanelSlot):
        unreal.log_warning(f'[FixRows] {widget.get_name()} root slot 不是 CanvasPanelSlot')
        return False
    # anchors 全 1（Anchors(minimum, maximum) 各为 Vector2D）
    anchors = unreal.Anchors(unreal.Vector2D(0.0, 0.0), unreal.Vector2D(1.0, 1.0))
    slot.set_anchors(anchors)
    # offsets: Left=0 Top=0 Right=0 Bottom=0
    slot.set_offsets(unreal.Margin(0.0, 0.0, 0.0, 0.0))
    slot.set_alignment(unreal.Vector2D(0.0, 0.0))
    return True


def _set_textblock_font_and_min_width(text_widget, font_size, min_width):
    """设 TextBlock 字号 + MinDesiredWidth。"""
    if not isinstance(text_widget, unreal.TextBlock):
        return False
    # 字号
    font = text_widget.get_editor_property('Font')
    font.size = font_size
    text_widget.set_editor_property('Font', font)
    # MinDesiredWidth
    text_widget.set_editor_property('MinDesiredWidth', float(min_width))
    return True


def _ensure_slider_visual(slider_widget):
    """给 Slider 设个最小 desired width + 居中 + bar 厚度。"""
    if not isinstance(slider_widget, unreal.Slider):
        return False
    # Slider 没有公共 MinDesiredWidth，但可以设 BarThickness 让条变粗
    try:
        slider_widget.set_editor_property('IndentHandle', False)
    except Exception:
        pass
    return True


def _enlarge_checkbox(checkbox_widget):
    """放大 CheckBox 渲染 transform，把默认 16px 拉到 28px。"""
    if not isinstance(checkbox_widget, unreal.CheckBox):
        return False
    # render transform scale 1.75 → 16*1.75≈28
    transform = unreal.WidgetTransform(
        translation=unreal.Vector2D(0.0, 0.0),
        scale=unreal.Vector2D(1.75, 1.75),
        shear=unreal.Vector2D(0.0, 0.0),
        angle=0.0,
    )
    checkbox_widget.set_render_transform(transform)
    return True


def fix_one_wbp(wbp_path, kind):
    unreal.log(f'[FixRows] === 处理 {wbp_path} (kind={kind}) ===')
    asset, tree, bp = _get_widget_tree(wbp_path)
    if tree is None:
        return False

    # 1) Root_HBox 的 CanvasPanelSlot → anchors=Fill 撑满父
    root_hbox = _find_widget_by_name(tree, 'Root_HBox')
    if root_hbox is None:
        unreal.log_error(f'[FixRows] 找不到 Root_HBox')
        return False
    _set_canvas_slot_fill(root_hbox)

    # 2) DisplayName_Label：HBoxSlot SizeRule=Auto + 字号16 + MinDesiredWidth 锁宽
    label = _find_widget_by_name(tree, 'DisplayName_Label')
    if label is not None:
        _set_hbox_slot(label, 'Auto', 0.0, h_align='Left', v_align='Center', padding=(12.0, 6.0, 12.0, 6.0))
        _set_textblock_font_and_min_width(label, LABEL_FONT_SIZE, LABEL_MIN_WIDTH)

    # 3) 中间值控件 + 4) 右侧 Value_Text(仅 Slider) / 5) CheckBox 放大
    if kind == 'Slider':
        v_slider = _find_widget_by_name(tree, 'Value_Slider')
        if v_slider is not None:
            _set_hbox_slot(v_slider, 'Fill', VALUE_MAIN_FILL, h_align='Fill', v_align='Center',
                           padding=(12.0, 6.0, 12.0, 6.0))
            _ensure_slider_visual(v_slider)
        v_text = _find_widget_by_name(tree, 'Value_Text')
        if v_text is not None:
            _set_hbox_slot(v_text, 'Auto', 0.0, h_align='Right', v_align='Center',
                           padding=(12.0, 6.0, 12.0, 6.0))
            _set_textblock_font_and_min_width(v_text, VALUE_TEXT_FONT_SIZE, VALUE_TEXT_MIN_WIDTH)

    elif kind == 'ComboBox':
        v_combo = _find_widget_by_name(tree, 'Value_Combo')
        if v_combo is not None:
            _set_hbox_slot(v_combo, 'Fill', VALUE_MAIN_FILL, h_align='Fill', v_align='Center',
                           padding=(12.0, 6.0, 12.0, 6.0))

    elif kind == 'CheckBox':
        v_check = _find_widget_by_name(tree, 'Value_Check')
        if v_check is not None:
            _set_hbox_slot(v_check, 'Auto', 0.0, h_align='Right', v_align='Center',
                           padding=(12.0, 6.0, 12.0, 6.0))
            _enlarge_checkbox(v_check)

    elif kind == 'Text':
        v_text = _find_widget_by_name(tree, 'Value_Text')
        if v_text is not None:
            _set_hbox_slot(v_text, 'Auto', 0.0, h_align='Right', v_align='Center',
                           padding=(12.0, 6.0, 12.0, 6.0))
            _set_textblock_font_and_min_width(v_text, VALUE_TEXT_FONT_SIZE, VALUE_TEXT_MIN_WIDTH)

    # 6) 编译 + 保存
    unreal.BlueprintEditorLibrary.compile_blueprint(bp)
    unreal.EditorAssetLibrary.save_asset(wbp_path, only_if_is_dirty=False)
    unreal.log(f'[FixRows] OK {wbp_path}')
    return True


def main():
    success = 0
    for path, kind in ROW_WBPS:
        if fix_one_wbp(path, kind):
            success += 1
    unreal.log(f'[FixRows] DONE: {success}/{len(ROW_WBPS)} succeeded')


main()

