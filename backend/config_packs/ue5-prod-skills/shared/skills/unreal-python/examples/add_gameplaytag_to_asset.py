#!/usr/bin/env python3
"""
Set AbilityTags for Movement Ability blueprints

Use export_text/import_text method to modify GameplayTagContainer,
because gameplay_tags property is read-only.

Usage:
    Run via UE5 Python Remote Execution:
    unreal.execute_python_script("set_movement_ability_tags_final.py")
"""

import unreal


def add_ability_tag_to_asset(asset_path, tag_name):
    """
    Add AbilityTag to a single Ability asset

    Args:
        asset_path: UE5 asset path (e.g., "/Game/GAS/Abilities/Movement/GA_Step")
        tag_name: Name of tag to add (e.g., "Ability.Move.Step")

    Returns:
        bool: True on success, False on failure
    """
    try:
        # Load asset
        ability = unreal.load_asset(asset_path)
        if not ability:
            unreal.log_error(f"Failed to load asset: {asset_path}")
            return False

        # Get Blueprint Generated Class and CDO
        ability_class = ability.generated_class()
        if not ability_class:
            unreal.log_error(f"Failed to get generated class for: {asset_path}")
            return False

        cdo = unreal.get_default_object(ability_class)
        if not cdo:
            unreal.log_error(f"Failed to get CDO for: {asset_path}")
            return False

        # Get current ability_tags container
        current_container = cdo.get_editor_property("ability_tags")
        if current_container is None:
            unreal.log_error(f"Failed to get ability_tags for: {asset_path}")
            return False

        # Check if tag already exists
        current_tags = current_container.get_editor_property("gameplay_tags")
        for existing_tag in current_tags:
            existing_tag_name = str(existing_tag.get_editor_property("tag_name"))
            if existing_tag_name == tag_name:
                unreal.log(f"  Tag '{tag_name}' already exists, skipping")
                return True

        # Export container as text
        exported_text = current_container.export_text()

        # Modify text to add new tag
        # Format: (GameplayTags=((TagName="Tag1"),(TagName="Tag2")))
        # Or: (GameplayTags=((TagName="Tag1")))
        # Or: (GameplayTags=())
        if "(GameplayTags=(" in exported_text:
            # Find the last ))
            parts = exported_text.rsplit('))', 1)
            if len(parts) == 2:
                # Check if empty container
                if "(GameplayTags=())" in exported_text:
                    # Empty container, add first tag directly
                    new_text = f'(GameplayTags=((TagName="{tag_name}")))'
                else:
                    # Has tags, add new one
                    new_text = f'{parts[0]},(TagName="{tag_name}")){parts[1]}'
            else:
                unreal.log_error(f"Unexpected container text format: {exported_text}")
                return False
        else:
            unreal.log_error(f"Unexpected container text format: {exported_text}")
            return False

        # Create new container and import modified text
        new_container = unreal.GameplayTagContainer()
        new_container.import_text(new_text)

        # Set to CDO
        cdo.set_editor_property("ability_tags", new_container)

        # Save asset
        unreal.EditorAssetLibrary.save_loaded_asset(ability, False)

        # Verify
        verify_container = cdo.get_editor_property("ability_tags")
        verify_tags = verify_container.get_editor_property("gameplay_tags")
        tag_found = False
        for tag in verify_tags:
            if str(tag.get_editor_property("tag_name")) == tag_name:
                tag_found = True
                break

        if tag_found:
            unreal.log(f"  [OK] Successfully added tag '{tag_name}'")
            return True
        else:
            unreal.log_error(f"  [ERROR] Tag '{tag_name}' not found after save")
            return False

    except Exception as e:
        unreal.log_error(f"  [ERROR] Exception adding tag to {asset_path}: {str(e)}")
        import traceback
        unreal.log_error(traceback.format_exc())
        return False


def main():
    """Add AbilityTags to all Movement Abilities"""

    unreal.log("=" * 80)
    unreal.log("=== Setting Movement Ability AbilityTags ===")
    unreal.log("=" * 80)

    # Define Movement Abilities to configure
    movement_abilities = [
        {
            "path": "/Game/GAS/Abilities/Movement/GA_Step",
            "name": "GA_Step",
            "tag": "Ability.Move.Step"
        },
        {
            "path": "/Game/GAS/Abilities/Movement/GA_Retreat",
            "name": "GA_Retreat",
            "tag": "Ability.Move.Retreat"
        },
        {
            "path": "/Game/GAS/Abilities/Movement/GA_SideStepLeft",
            "name": "GA_SideStepLeft",
            "tag": "Ability.Move.SideStepLeft"
        },
        {
            "path": "/Game/GAS/Abilities/Movement/GA_SideStepRight",
            "name": "GA_SideStepRight",
            "tag": "Ability.Move.SideStepRight"
        }
    ]

    unreal.log(f"\nProcessing {len(movement_abilities)} Movement Abilities...")
    unreal.log("")

    success_count = 0
    failed_list = []

    # Use transaction to ensure undo capability
    with unreal.ScopedEditorTransaction("Set Movement Ability AbilityTags"):
        for ability_cfg in movement_abilities:
            unreal.log(f"Processing {ability_cfg['name']}...")

            if add_ability_tag_to_asset(ability_cfg["path"], ability_cfg["tag"]):
                success_count += 1
            else:
                failed_list.append(ability_cfg)

    # Summary
    unreal.log("")
    unreal.log("=" * 80)
    unreal.log("=== Summary ===")
    unreal.log("=" * 80)
    unreal.log(f"Success: {success_count}/{len(movement_abilities)}")

    if failed_list:
        unreal.log(f"Failed: {len(failed_list)}")
        for ability_cfg in failed_list:
            unreal.log(f"  - {ability_cfg['name']}: {ability_cfg['path']}")
    else:
        unreal.log("[OK] All Movement Abilities configured successfully!")

    unreal.log("")
    unreal.log("Next steps:")
    unreal.log("1. Verify tags with: check_movement_ability_tags.py")
    unreal.log("2. Test in PIE mode (press W/S/A/D keys)")
    unreal.log("3. Use 'showdebug abilitysystem' command to debug")
    unreal.log("=" * 80)

    return len(failed_list) == 0


if __name__ == "__main__":
    result = main()
    exit(0 if result else 1)
