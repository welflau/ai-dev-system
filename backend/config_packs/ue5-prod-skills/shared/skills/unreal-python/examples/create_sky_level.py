# create_sky_level.py
# Creates an empty level with blue sky and clouds using UE5's sky atmosphere system

import unreal

def create_sky_level(level_name="BlueSkyLevel", maps_path="/Game/Maps"):
    """
    Create a new level with blue sky and white clouds.

    Args:
        level_name: Name for the new level
        maps_path: Package path for the level
    """

    # Full package path
    level_path = f"{maps_path}/{level_name}"

    # Check if level already exists
    if unreal.EditorAssetLibrary.does_asset_exist(level_path):
        unreal.log_warning(f"[WARNING] Level already exists: {level_path}")
        return False

    unreal.log(f"[INFO] Creating new level: {level_path}")

    # Get editor subsystems
    level_subsystem = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
    actor_subsystem = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)

    # Create new level
    success = level_subsystem.new_level(level_path)
    if not success:
        unreal.log_error(f"[ERROR] Failed to create level: {level_path}")
        return False

    unreal.log("[OK] Level created successfully")

    # Use transaction for undo support
    with unreal.ScopedEditorTransaction("Add Sky Atmosphere Components") as transaction:
        try:
            # 1. Add Directional Light (Sun)
            directional_light = actor_subsystem.spawn_actor_from_class(
                unreal.DirectionalLight,
                unreal.Vector(0, 0, 0)
            )
            if directional_light:
                directional_light.set_actor_label("Sun_DirectionalLight")
                # Set rotation for sun angle (morning/afternoon feel)
                directional_light.set_actor_rotation(
                    unreal.Rotator(-45, -30, 0),
                    False
                )
                # Configure light component
                light_component = directional_light.get_component_by_class(unreal.DirectionalLightComponent)
                if light_component:
                    light_component.set_intensity(10.0)
                    light_component.set_light_color(unreal.LinearColor(1.0, 0.98, 0.95, 1.0))
                    # Enable atmosphere sun light
                    light_component.set_editor_property("atmosphere_sun_light", True)
                    light_component.set_editor_property("atmosphere_sun_light_index", 0)
                unreal.log("[OK] Directional Light (Sun) added")

            # 2. Add Sky Atmosphere
            sky_atmosphere = actor_subsystem.spawn_actor_from_class(
                unreal.SkyAtmosphere,
                unreal.Vector(0, 0, 0)
            )
            if sky_atmosphere:
                sky_atmosphere.set_actor_label("SkyAtmosphere")
                unreal.log("[OK] Sky Atmosphere added")

            # 3. Add Volumetric Clouds
            volumetric_cloud = actor_subsystem.spawn_actor_from_class(
                unreal.VolumetricCloud,
                unreal.Vector(0, 0, 0)
            )
            if volumetric_cloud:
                volumetric_cloud.set_actor_label("VolumetricClouds")
                unreal.log("[OK] Volumetric Clouds added")

            # 4. Add Sky Light for ambient lighting
            sky_light = actor_subsystem.spawn_actor_from_class(
                unreal.SkyLight,
                unreal.Vector(0, 0, 500)
            )
            if sky_light:
                sky_light.set_actor_label("SkyLight")
                sky_light_component = sky_light.get_component_by_class(unreal.SkyLightComponent)
                if sky_light_component:
                    # Use real-time capture for sky atmosphere
                    sky_light_component.set_editor_property("real_time_capture", True)
                    sky_light_component.set_editor_property("source_type", unreal.SkyLightSourceType.SLS_CAPTURED_SCENE)
                unreal.log("[OK] Sky Light added")

            # 5. Add Exponential Height Fog for atmosphere
            height_fog = actor_subsystem.spawn_actor_from_class(
                unreal.ExponentialHeightFog,
                unreal.Vector(0, 0, 0)
            )
            if height_fog:
                height_fog.set_actor_label("AtmosphericFog")
                fog_component = height_fog.get_component_by_class(unreal.ExponentialHeightFogComponent)
                if fog_component:
                    fog_component.set_editor_property("fog_density", 0.005)
                    # Enable volumetric fog if available
                    try:
                        fog_component.set_editor_property("b_enable_volumetric_fog", True)
                    except:
                        pass  # Property may not exist in this UE version
                unreal.log("[OK] Exponential Height Fog added")

            # 6. Add a ground plane
            floor_actor = actor_subsystem.spawn_actor_from_class(
                unreal.StaticMeshActor,
                unreal.Vector(0, 0, -100)
            )
            if floor_actor:
                floor_actor.set_actor_label("Ground_Floor")
                floor_actor.set_actor_scale3d(unreal.Vector(100, 100, 1))

                # Set a basic cube mesh as floor
                mesh_component = floor_actor.get_component_by_class(unreal.StaticMeshComponent)
                if mesh_component:
                    cube_mesh = unreal.load_asset("/Engine/BasicShapes/Cube")
                    if cube_mesh:
                        mesh_component.set_static_mesh(cube_mesh)
                        unreal.log("[OK] Ground floor added")

        except Exception as e:
            transaction.cancel()
            unreal.log_error(f"[ERROR] Failed to add components: {e}")
            return False

    # Save the level
    unreal.EditorAssetLibrary.save_asset(level_path)
    unreal.log(f"[OK] Level saved: {level_path}")

    unreal.log("=" * 50)
    unreal.log(f"[COMPLETE] Blue sky level created: {level_name}")
    unreal.log("Components added:")
    unreal.log("  - Directional Light (Sun)")
    unreal.log("  - Sky Atmosphere")
    unreal.log("  - Volumetric Clouds")
    unreal.log("  - Sky Light")
    unreal.log("  - Exponential Height Fog")
    unreal.log("  - Ground Floor")
    unreal.log("=" * 50)

    return True


if __name__ == "__main__":
    # Create the level with default name
    create_sky_level("BlueSkyLevel", "/Game/Maps")
