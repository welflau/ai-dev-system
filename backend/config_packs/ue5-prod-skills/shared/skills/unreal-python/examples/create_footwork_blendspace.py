# -*- coding: utf-8 -*-
"""
Create a 2D BlendSpace for boxing footwork locomotion.
Run this script in UE5 Editor via Python remote execution.
"""

import unreal


# Configuration
BLENDSPACE_NAME = "BS_Footwork_2D"
BLENDSPACE_PATH = "/Game/Animations/BlendSpaces"
SKELETON_PATH = "/Game/imported/Characters/Mannequins/Meshes/SK_Mannequin"

# Animation samples: (asset_path, x, y)
# X axis: Strafe (-1 left, 1 right)
# Y axis: Forward (-1 backward, 1 forward)
ANIMATION_SAMPLES = [
    ("/Game/Animations/Boxing_Retargeted/Basic_Guard", 0, 0),              # Center (idle)
    ("/Game/Animations/Boxing_Retargeted/Footwork_Drills_Forward", 0, 1),  # Forward
    ("/Game/Animations/Boxing_Retargeted/Footwork_Drills_Backward", 0, -1),# Backward
    ("/Game/Animations/Boxing_Retargeted/Footwork_Drills_Left", -1, 0),    # Left
    ("/Game/Animations/Boxing_Retargeted/Footwork_Drills_Right", 1, 0),    # Right
]


def log(message):
    """Log message to UE5 output log"""
    unreal.log(str(message))


def create_footwork_blendspace():
    """Create the 2D BlendSpace for footwork locomotion"""

    full_path = "{}/{}".format(BLENDSPACE_PATH, BLENDSPACE_NAME)

    # Check if already exists
    if unreal.EditorAssetLibrary.does_asset_exist(full_path):
        log("BlendSpace already exists: {}".format(full_path))
        log("Delete it first if you want to recreate.")
        return None

    # Load skeleton
    log("Loading skeleton: {}".format(SKELETON_PATH))
    skeleton = unreal.load_asset(SKELETON_PATH)
    if not skeleton:
        log("ERROR: Failed to load skeleton: {}".format(SKELETON_PATH))
        return None
    log("  Skeleton loaded: {}".format(skeleton.get_name()))

    # Verify all animations exist and use the same skeleton
    log("")
    log("Verifying animations...")
    for anim_path, x, y in ANIMATION_SAMPLES:
        anim = unreal.load_asset(anim_path)
        if not anim:
            log("ERROR: Animation not found: {}".format(anim_path))
            return None
        anim_skeleton = anim.get_skeleton()
        if anim_skeleton != skeleton:
            log("WARNING: Animation {} uses different skeleton: {}".format(
                anim_path, anim_skeleton.get_name() if anim_skeleton else "None"))
        log("  OK: {} at ({}, {})".format(anim.get_name(), x, y))

    # Create BlendSpace factory
    log("")
    log("Creating BlendSpace...")
    factory = unreal.BlendSpaceFactoryNew()
    factory.target_skeleton = skeleton

    # Create asset
    asset_tools = unreal.AssetToolsHelpers.get_asset_tools()
    blend_space = asset_tools.create_asset(
        BLENDSPACE_NAME,
        BLENDSPACE_PATH,
        unreal.BlendSpace,
        factory
    )

    if not blend_space:
        log("ERROR: Failed to create BlendSpace")
        return None

    log("  BlendSpace created: {}".format(blend_space.get_path_name()))

    # Configure axis parameters
    log("")
    log("Configuring axis parameters...")

    # Create new BlendParameter objects (FixedArray cannot be modified in place)
    param_x = unreal.BlendParameter()
    param_x.set_editor_property("display_name", "Strafe")
    param_x.set_editor_property("min", -1.0)
    param_x.set_editor_property("max", 1.0)
    param_x.set_editor_property("grid_num", 2)
    log("  X axis (Strafe): -1 to 1")

    param_y = unreal.BlendParameter()
    param_y.set_editor_property("display_name", "Forward")
    param_y.set_editor_property("min", -1.0)
    param_y.set_editor_property("max", 1.0)
    param_y.set_editor_property("grid_num", 2)
    log("  Y axis (Forward): -1 to 1")

    # Set the new parameters
    blend_space.set_editor_property("blend_parameters", [param_x, param_y])

    # Disable animation speed scaling
    blend_space.set_editor_property("axis_to_scale_animation", unreal.BlendSpaceAxis.BSA_NONE)

    # Add samples
    log("")
    log("Adding animation samples...")
    samples = []
    for anim_path, x, y in ANIMATION_SAMPLES:
        anim = unreal.load_asset(anim_path)
        sample = unreal.BlendSample()
        sample.set_editor_property("animation", anim)
        sample.set_editor_property("sample_value", unreal.Vector(x, y, 0))
        samples.append(sample)
        log("  Added: {} at ({}, {})".format(anim.get_name(), x, y))

    blend_space.set_editor_property("sample_data", samples)

    # Save asset
    log("")
    log("Saving asset...")
    unreal.EditorAssetLibrary.save_asset(full_path)

    log("")
    log("=" * 60)
    log("BlendSpace created successfully!")
    log("Path: {}".format(full_path))
    log("Samples: {}".format(len(samples)))
    log("=" * 60)

    return blend_space


if __name__ == "__main__":
    create_footwork_blendspace()
