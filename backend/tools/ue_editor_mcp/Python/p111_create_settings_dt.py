# Copyright P111 Project. All Rights Reserved.
# 一次性脚本：填充 DT_P111Settings DataTable 6 行设置项数据(改用 CSV 路径,兼容 SoftClassPath)。
# 使用方法(在 UE Editor):
#   Cmd 模式 → py D:\UGit\P111\Plugins\UEEditorMCP\Python\p111_create_settings_dt.py

import unreal


# ============================================================================
# 配置
# ============================================================================

DT_PACKAGE_PATH = '/Game/P111/Data'
DT_NAME = 'DT_P111Settings'
DT_FULL_PATH = f'{DT_PACKAGE_PATH}/{DT_NAME}'
ROW_STRUCT_PATH = '/Script/P111.P111SettingItemRow'

# WBP_Row_* 路径(SoftClassPath 标准格式 = /Path/Asset.Asset_C)
WBP_ROW = {
    'Slider':   '/Game/P111/UI/Settings/Rows/WBP_Row_Slider.WBP_Row_Slider_C',
    'ComboBox': '/Game/P111/UI/Settings/Rows/WBP_Row_ComboBox.WBP_Row_ComboBox_C',
    'CheckBox': '/Game/P111/UI/Settings/Rows/WBP_Row_CheckBox.WBP_Row_CheckBox_C',
    'Text':     '/Game/P111/UI/Settings/Rows/WBP_Row_Text.WBP_Row_Text_C',
}

# 6 行数据
ROWS = [
    {'row_name':'UseVSync', 'ControlType':'CheckBox', 'FieldName':'UseVSync', 'ValueType':'Bool',
     'DisplayName':'垂直同步', 'Description':'开启垂直同步可消除画面撕裂，但可能增加输入延迟。',
     'Category':'Display', 'WidgetClass':WBP_ROW['CheckBox'],
     'MinValue':0.0, 'MaxValue':1.0, 'StepSize':1.0, 'ValueSuffix':'', 'OptionsProvider':''},
    {'row_name':'FrameRateLimit', 'ControlType':'ComboBox', 'FieldName':'FrameRateLimit', 'ValueType':'Int',
     'DisplayName':'帧率上限', 'Description':'限制游戏渲染帧率，30/60/无限制 三档可选。',
     'Category':'Display', 'WidgetClass':WBP_ROW['ComboBox'],
     'MinValue':0.0, 'MaxValue':2.0, 'StepSize':1.0, 'ValueSuffix':'', 'OptionsProvider':'FrameRate'},
    {'row_name':'ResolutionScalePercent', 'ControlType':'Slider', 'FieldName':'ResolutionScalePercent', 'ValueType':'Int',
     'DisplayName':'3D 渲染比例', 'Description':'降低渲染分辨率以提升性能，最低 75% 防止 TSR/TAA 上采样产生 RGB 边缘错位。',
     'Category':'Graphics', 'WidgetClass':WBP_ROW['Slider'],
     'MinValue':75.0, 'MaxValue':100.0, 'StepSize':5.0, 'ValueSuffix':'%', 'OptionsProvider':''},
    {'row_name':'FOV', 'ControlType':'Slider', 'FieldName':'FOV', 'ValueType':'Float',
     'DisplayName':'视野', 'Description':'调整玩家相机 FOV（视野范围），更大值显示更宽广的画面。',
     'Category':'Graphics', 'WidgetClass':WBP_ROW['Slider'],
     'MinValue':60.0, 'MaxValue':120.0, 'StepSize':1.0, 'ValueSuffix':'°', 'OptionsProvider':''},
    {'row_name':'VoiceVolume', 'ControlType':'Slider', 'FieldName':'VoiceVolume', 'ValueType':'Float',
     'DisplayName':'通话音量', 'Description':'调整队友语音通话的音量。',
     'Category':'Audio', 'WidgetClass':WBP_ROW['Slider'],
     'MinValue':0.0, 'MaxValue':1.0, 'StepSize':0.05, 'ValueSuffix':'', 'OptionsProvider':''},
    {'row_name':'MusicVolume', 'ControlType':'Slider', 'FieldName':'MusicVolume', 'ValueType':'Float',
     'DisplayName':'音乐音量', 'Description':'调整背景音乐音量。',
     'Category':'Audio', 'WidgetClass':WBP_ROW['Slider'],
     'MinValue':0.0, 'MaxValue':1.0, 'StepSize':0.05, 'ValueSuffix':'', 'OptionsProvider':''},
]


# ============================================================================
# 实现
# ============================================================================

def _csv_escape(s):
    """CSV 字段转义:含逗号/引号/换行的字段用双引号包裹,内部双引号双写。"""
    s = str(s)
    if any(c in s for c in [',', '"', '\n', '\r']):
        return '"' + s.replace('"', '""') + '"'
    return s


def _build_csv(rows):
    """按 RowStruct UPROPERTY 顺序构造 CSV 字符串。
    UE 5.7 CSV DataTable importer 对 SoftClassPath 字段调 FSoftClassPath::ImportText,
    接受 /Game/.../Asset.Asset_C 标准格式,这是比 JSON 路径更稳定的写入路径。"""
    # 第一列必须是 'Name' (row name 约定),其余按 P111SettingItemRow USTRUCT 字段顺序。
    headers = ['---', 'ControlType', 'FieldName', 'ValueType', 'DisplayName', 'Description',
               'Category', 'WidgetClass', 'MinValue', 'MaxValue', 'StepSize', 'ValueSuffix',
               'OptionsProvider']
    lines = [','.join(headers)]
    for r in rows:
        line = [
            _csv_escape(r['row_name']),
            _csv_escape(r['ControlType']),
            _csv_escape(r['FieldName']),
            _csv_escape(r['ValueType']),
            _csv_escape(r['DisplayName']),
            _csv_escape(r['Description']),
            _csv_escape(r['Category']),
            _csv_escape(r.get('WidgetClass', '')),
            _csv_escape(float(r.get('MinValue', 0.0))),
            _csv_escape(float(r.get('MaxValue', 100.0))),
            _csv_escape(float(r.get('StepSize', 1.0))),
            _csv_escape(r.get('ValueSuffix', '')),
            _csv_escape(r.get('OptionsProvider', '')),
        ]
        lines.append(','.join(line))
    return '\n'.join(lines) + '\n'


def main():
    asset_lib = unreal.EditorAssetLibrary

    # 1) 校验 DT 资产已被用户手动创建
    if not asset_lib.does_asset_exist(DT_FULL_PATH):
        raise RuntimeError(
            f'[P111][DT] DT 资产不存在: {DT_FULL_PATH}\n'
            f'        请先在 UE Editor Content Browser 进入 {DT_PACKAGE_PATH}/ 目录,\n'
            f'        右键 → Miscellaneous → Data Table → 选 Row Structure 为 P111SettingItemRow → 命名 {DT_NAME}')

    # 2) 加载 DT 资产
    existing_dt = asset_lib.load_asset(DT_FULL_PATH)
    if existing_dt is None:
        raise RuntimeError(f'Cannot load DataTable: {DT_FULL_PATH}')

    # 3) 校验 RowStruct 类型一致
    row_struct = unreal.load_object(None, ROW_STRUCT_PATH)
    if row_struct is None:
        raise RuntimeError(f'Cannot load row struct: {ROW_STRUCT_PATH}')
    bound_struct = existing_dt.get_editor_property('row_struct')
    if bound_struct is None or bound_struct.get_path_name() != row_struct.get_path_name():
        bound_name = bound_struct.get_path_name() if bound_struct else 'None'
        raise RuntimeError(
            f'[P111][DT] DT 资产 RowStruct 不匹配!\n        实际: {bound_name}\n        预期: {row_struct.get_path_name()}')

    unreal.log(f'[P111][DT] Loaded: {DT_FULL_PATH} (RowStruct = {row_struct.get_name()})')
    before_rows = list(existing_dt.get_row_names())
    unreal.log(f'[P111][DT] 写入前行数 = {len(before_rows)}, 行名 = {[str(n) for n in before_rows]}')

    # 4) 构造 CSV 字符串
    csv_str = _build_csv(ROWS)
    unreal.log(f'[P111][DT] CSV payload {len(csv_str)} chars, {len(ROWS)} rows')

    # 5) FillDataTableFromCSVString 内部会:① 清空所有旧行(含幽灵 NewRow)② 解析 CSV ③ 按列名匹配 UPROPERTY 填充。
    # CSV importer 对 SoftClassPath 字段调 FSoftClassPath::ImportText, 比 JSON 路径(直接 LoadObject)更稳。
    with unreal.ScopedEditorTransaction('Fill DT_P111Settings from CSV'):
        problems = unreal.DataTableFunctionLibrary.fill_data_table_from_csv_string(existing_dt, csv_str)

    if problems:
        unreal.log_warning(f'[P111][DT] FillDataTableFromCSVString reported issues: {problems}')
    else:
        unreal.log(f'[P111][DT] FillDataTableFromCSVString OK')

    # 6) 校验行数
    final_row_names = list(existing_dt.get_row_names())
    unreal.log(f'[P111][DT] 写入后行数 = {len(final_row_names)}, 行名 = {[str(n) for n in final_row_names]}')

    if len(final_row_names) != len(ROWS):
        raise RuntimeError(
            f'[P111][DT] 写入后行数不符! 预期 {len(ROWS)} 实际 {len(final_row_names)}\n'
            f'        FillDataTableFromCSVString problems: {problems}')

    # 7) 保存
    asset_lib.save_loaded_asset(existing_dt)
    unreal.log(f'[P111][DT] Saved: {DT_FULL_PATH}, total rows = {len(final_row_names)}')


main()
