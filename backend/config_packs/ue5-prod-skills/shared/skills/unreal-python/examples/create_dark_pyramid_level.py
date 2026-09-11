# create_dark_pyramid_level.py
# Creates a complete level with dark fog atmosphere and a giant pyramid
# This is the main entry script that combines both components

import unreal

def create_dark_pyramid_level(level_name="DarkPyramidLevel", maps_path="/Game/Maps"):
    """
    Create a new level with dark fog atmosphere and a giant pyramid.

    Args:
        level_name: Name for the new level
        maps_path: Package path for the level
    """

    level_path = f"{maps_path}/{level_name}"

    # Check if level already exists
    if unreal.EditorAssetLibrary.does_asset_exist(level_path):
        unreal.log_warning(f"[WARNING] Level already exists: {level_path}")
        return False

    unreal.log("=" * 60)
    unreal.log(f"[INFO] Creating Dark Pyramid Level: {level_name}")
    unreal.log("=" * 60)

    # Get editor subsystems
    level_subsystem = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
    actor_subsystem = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)

    # Create new level
    success = level_subsystem.new_level(level_path)
    if not success:
        unreal.log_error(f"[ERROR] Failed to create level: {level_path}")
        return False

    unreal.log("[OK] Empty level created")

    # Pyramid parameters
    pyramid_base = 8000.0   # 80 meters base
    pyramid_height = 6000.0  # 60 meters tall
    pyramid_location = unreal.Vector(0, 0, 0)

    with unreal.ScopedEditorTransaction("Create Dark Pyramid Level") as transaction:
        try:
            # ============================================
            # PART 1: Dark Atmosphere Setup
            # ============================================
            unreal.log("\n[PHASE 1] Setting up dark atmosphere...")

            # 1.1 Directional Light (Dim moonlight)
            directional_light = actor_subsystem.spawn_actor_from_class(
                unreal.DirectionalLight,
                unreal.Vector(0, 0, 0)
            )
            if directional_light:
                directional_light.set_actor_label("MoonLight")
                directional_light.set_actor_rotation(unreal.Rotator(-25, 30, 0), False)
                light_comp = directional_light.get_component_by_class(unreal.DirectionalLightComponent)
                if light_comp:
                    light_comp.set_intensity(0.3)
                    light_comp.set_light_color(unreal.LinearColor(0.5, 0.55, 0.7, 1.0))
                    light_comp.set_editor_property("atmosphere_sun_light", True)
                unreal.log("  [OK] Moonlight added")

            # 1.2 Sky Atmosphere (dark, foreboding sky)
            sky_atmosphere = actor_subsystem.spawn_actor_from_class(
                unreal.SkyAtmosphere,
                unreal.Vector(0, 0, 0)
            )
            if sky_atmosphere:
                sky_atmosphere.set_actor_label("DarkSky")
                sky_comp = sky_atmosphere.get_component_by_class(unreal.SkyAtmosphereComponent)
                if sky_comp:
                    sky_comp.set_editor_property("rayleigh_scattering_scale", 0.05)
                    sky_comp.set_editor_property("mie_scattering_scale", 0.02)
                unreal.log("  [OK] Dark sky atmosphere added")

            # 1.3 DENSE BLACK FOG - Core visual element
            height_fog = actor_subsystem.spawn_actor_from_class(
                unreal.ExponentialHeightFog,
                unreal.Vector(0, 0, -500)
            )
            if height_fog:
                height_fog.set_actor_label("DenseDarkFog")
                fog_comp = height_fog.get_component_by_class(unreal.ExponentialHeightFogComponent)
                if fog_comp:
                    # Very dense, dark fog
                    fog_comp.set_editor_property("fog_density", 0.15)
                    fog_comp.set_editor_property("fog_height_falloff", 0.2)
                    fog_comp.set_editor_property("fog_max_opacity", 0.99)
                    # Very dark, nearly black fog color
                    fog_comp.set_editor_property("fog_inscattering_luminance",
                        unreal.LinearColor(0.005, 0.005, 0.008, 1.0))
                    # Minimal directional inscattering
                    fog_comp.set_editor_property("directional_inscattering_exponent", 16.0)
                    fog_comp.set_editor_property("directional_inscattering_luminance",
                        unreal.LinearColor(0.01, 0.01, 0.02, 1.0))
                    # Disable volumetric fog to keep it darker
                    try:
                        fog_comp.set_editor_property("enable_volumetric_fog", False)
                    except:
                        pass
                unreal.log("  [OK] Dense dark fog added")

            # 1.4 Sky Light (very dim ambient)
            sky_light = actor_subsystem.spawn_actor_from_class(
                unreal.SkyLight,
                unreal.Vector(0, 0, 1000)
            )
            if sky_light:
                sky_light.set_actor_label("AmbientLight")
                sky_light_comp = sky_light.get_component_by_class(unreal.SkyLightComponent)
                if sky_light_comp:
                    sky_light_comp.set_editor_property("intensity", 0.2)
                    sky_light_comp.set_editor_property("real_time_capture", True)
                    # Use Color type instead of LinearColor for light_color
                    sky_light_comp.set_editor_property("light_color",
                        unreal.Color(20, 20, 30, 255))
                unreal.log("  [OK] Ambient light added")

            # 1.5 Ground plane (dark desert floor)
            ground = actor_subsystem.spawn_actor_from_class(
                unreal.StaticMeshActor,
                unreal.Vector(0, 0, -100)
            )
            if ground:
                ground.set_actor_label("DesertGround")
                ground.set_actor_scale3d(unreal.Vector(1000, 1000, 1))
                mesh_comp = ground.get_component_by_class(unreal.StaticMeshComponent)
                if mesh_comp:
                    cube = unreal.load_asset("/Engine/BasicShapes/Cube")
                    if cube:
                        mesh_comp.set_static_mesh(cube)
                unreal.log("  [OK] Ground plane added")

            # ============================================
            # PART 2: Giant Pyramid Construction
            # ============================================
            unreal.log("\n[PHASE 2] Constructing giant pyramid...")

            num_tiers = 25
            tier_height = pyramid_height / num_tiers
            pyramid_actors = []

            for i in range(num_tiers):
                tier_ratio = 1.0 - (i / num_tiers)
                tier_size = pyramid_base * tier_ratio
                tier_z = pyramid_location.z + (i * tier_height)

                tier = actor_subsystem.spawn_actor_from_class(
                    unreal.StaticMeshActor,
                    unreal.Vector(pyramid_location.x, pyramid_location.y, tier_z)
                )

                if tier:
                    tier.set_actor_label(f"Pyramid_Tier_{i:02d}")
                    scale_xy = tier_size / 100.0
                    scale_z = tier_height / 100.0
                    tier.set_actor_scale3d(unreal.Vector(scale_xy, scale_xy, scale_z))

                    mesh_comp = tier.get_component_by_class(unreal.StaticMeshComponent)
                    if mesh_comp:
                        cube = unreal.load_asset("/Engine/BasicShapes/Cube")
                        if cube:
                            mesh_comp.set_static_mesh(cube)

                    pyramid_actors.append(tier)

            unreal.log(f"  [OK] Pyramid built with {len(pyramid_actors)} tiers")

            # 2.2 Pyramid apex light (mystical glow - reduced intensity for dark atmosphere)
            apex_light = actor_subsystem.spawn_actor_from_class(
                unreal.PointLight,
                unreal.Vector(pyramid_location.x, pyramid_location.y, pyramid_height + 800)
            )
            if apex_light:
                apex_light.set_actor_label("PyramidApexLight")
                apex_comp = apex_light.get_component_by_class(unreal.PointLightComponent)
                if apex_comp:
                    apex_comp.set_intensity(20000.0)  # Reduced for darker atmosphere
                    # Golden/amber mystical glow
                    apex_comp.set_light_color(unreal.LinearColor(1.0, 0.7, 0.2, 1.0))
                    apex_comp.set_editor_property("attenuation_radius", 10000.0)
                unreal.log("  [OK] Pyramid apex light added")

            # 2.3 Base torches around pyramid
            torch_distance = pyramid_base * 0.7
            torch_positions = [
                unreal.Vector(torch_distance, 0, 200),
                unreal.Vector(-torch_distance, 0, 200),
                unreal.Vector(0, torch_distance, 200),
                unreal.Vector(0, -torch_distance, 200),
            ]

            for idx, pos in enumerate(torch_positions):
                torch = actor_subsystem.spawn_actor_from_class(
                    unreal.PointLight,
                    pos
                )
                if torch:
                    torch.set_actor_label(f"Torch_{idx+1}")
                    torch_comp = torch.get_component_by_class(unreal.PointLightComponent)
                    if torch_comp:
                        torch_comp.set_intensity(8000.0)  # Reduced for darker atmosphere
                        # Warm fire-like glow
                        torch_comp.set_light_color(unreal.LinearColor(1.0, 0.5, 0.1, 1.0))
                        torch_comp.set_editor_property("attenuation_radius", 2000.0)

            unreal.log("  [OK] 4 torches added around pyramid base")

            # ============================================
            # PART 3: Player Start
            # ============================================
            unreal.log("\n[PHASE 3] Adding player start...")

            # Position player to view the pyramid from distance
            player_start = actor_subsystem.spawn_actor_from_class(
                unreal.PlayerStart,
                unreal.Vector(-pyramid_base * 1.5, 0, 200)
            )
            if player_start:
                player_start.set_actor_label("PlayerStart")
                # Face towards pyramid
                player_start.set_actor_rotation(unreal.Rotator(0, 0, 0), False)
                unreal.log("  [OK] Player start added")

        except Exception as e:
            transaction.cancel()
            unreal.log_error(f"[ERROR] Failed to create level: {e}")
            import traceback
            traceback.print_exc()
            return False

    # Save the level
    unreal.EditorAssetLibrary.save_asset(level_path)
    unreal.log(f"\n[OK] Level saved: {level_path}")

    # Summary
    unreal.log("\n" + "=" * 60)
    unreal.log("[COMPLETE] Dark Pyramid Level Created Successfully!")
    unreal.log("=" * 60)
    unreal.log(f"Level: {level_path}")
    unreal.log("\nAtmosphere:")
    unreal.log("  - Dense black fog with purple tint")
    unreal.log("  - Dark sky atmosphere")
    unreal.log("  - Dim moonlight")
    unreal.log("\nPyramid:")
    unreal.log(f"  - 25-tier stepped pyramid")
    unreal.log(f"  - Base: {pyramid_base/100:.0f}m x Height: {pyramid_height/100:.0f}m")
    unreal.log("  - Golden apex light")
    unreal.log("  - 4 surrounding torches")
    unreal.log("\nPlayer starts facing the pyramid from distance")
    unreal.log("=" * 60)

    return True


if __name__ == "__main__":
    # Change level name here if needed
    create_dark_pyramid_level("DarkPyramidLevel", "/Game/Maps")
