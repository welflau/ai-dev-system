# Copyright P111 Project. All Rights Reserved.
# 一次性诊断脚本:dump DT_P111Settings 当前实际持久化的所有行,
# 重点确认 WidgetClass(SoftClassPath) 字段真实值。

import unreal

DT_FULL_PATH = '/Game/P111/Data/DT_P111Settings'

def main():
    asset_lib = unreal.EditorAssetLibrary
    dt = asset_lib.load_asset(DT_FULL_PATH)
    if dt is None:
        unreal.log_error(f'[DUMP] Cannot load: {DT_FULL_PATH}')
        return

    json_str = unreal.DataTableFunctionLibrary.get_data_table_as_json(dt)
    unreal.log(f'[DUMP] DT JSON 字符数={len(json_str)},内容如下:')
    # 分块输出避免 UE log 单行截断
    chunk = 512
    for i in range(0, len(json_str), chunk):
        unreal.log(json_str[i:i+chunk])

    unreal.log(f'[DUMP] Row Names: {[str(n) for n in dt.get_row_names()]}')

main()
