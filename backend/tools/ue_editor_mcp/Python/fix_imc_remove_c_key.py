import unreal

IMC_PATH = "/Game/Input/IMC_Als_Default"

def remove_c_key_from_imc(imc_path):
    imc = unreal.load_asset(imc_path)
    if not imc:
        print(f"[ERROR] 无法加载 IMC: {imc_path}")
        return

    # UE5.7 使用 default_key_mappings 属性（旧 mappings 已废弃）
    mapping_data = imc.get_editor_property("default_key_mappings")
    mappings = mapping_data.get_editor_property("mappings")
    print(f"[INFO] IMC '{imc_path}' 共有 {len(mappings)} 条映射")

    # 先列出所有映射
    for i, m in enumerate(mappings):
        action = m.get_editor_property("action")
        key = m.get_editor_property("key")
        action_name = action.get_name() if action else "None"
        key_name = str(key.key_name) if key else "None"
        print(f"  [{i}] Action={action_name}, Key={key_name}")

    # 找出需要删除的（Key == C）
    to_remove = []
    for i, m in enumerate(mappings):
        key = m.get_editor_property("key")
        key_name = str(key.key_name) if key else ""
        if key_name == "C":
            action = m.get_editor_property("action")
            action_name = action.get_name() if action else "None"
            print(f"[FOUND] 索引 {i}: Action={action_name}, Key=C → 将删除")
            to_remove.append(m)

    if not to_remove:
        print("[INFO] 未找到 C 键绑定，无需修改")
        return

    # 删除 C 键绑定
    new_mappings = [m for m in mappings if m not in to_remove]

    # 构建新的 InputMappingContextMappingData 并写回
    new_mapping_data = unreal.InputMappingContextMappingData(mappings=new_mappings)
    with unreal.ScopedEditorTransaction("Remove C key from IMC"):
        imc.set_editor_property("default_key_mappings", new_mapping_data)

    # 标记脏并保存
    unreal.EditorAssetLibrary.save_asset(imc_path, only_if_is_dirty=False)
    print(f"[OK] 已删除 {len(to_remove)} 条 C 键绑定，IMC 已保存")

remove_c_key_from_imc(IMC_PATH)
