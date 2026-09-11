# create_punching_bag_blueprint.py
# Creates a reusable Punching Bag Blueprint with physics-enabled rope (Cable Component)
# The bag swings realistically when hit due to physics simulation

import unreal


def create_punching_bag_blueprint(blueprint_path="/Game/Blueprints/BP_PunchingBag"):
    """
    Create a Blueprint Actor containing:
    - A hanging hook point (Scene Component at top)
    - A Cable Component for the rope (physics-enabled)
    - A Static Mesh for the punching bag (with physics simulation)

    The Blueprint will be reusable and can be placed anywhere in levels.
    """

    unreal.log("=" * 60)
    unreal.log("[INFO] Creating Punching Bag Blueprint")
    unreal.log("=" * 60)

    # Get the asset tools
    asset_tools = unreal.AssetToolsHelpers.get_asset_tools()

    # Extract path and name
    package_path = "/".join(blueprint_path.split("/")[:-1])
    blueprint_name = blueprint_path.split("/")[-1]

    # Check if blueprint already exists
    if unreal.EditorAssetLibrary.does_asset_exist(blueprint_path):
        unreal.log_warning(
            f"[WARNING] Blueprint already exists: {blueprint_path}, deleting..."
        )
        unreal.EditorAssetLibrary.delete_asset(blueprint_path)

    # Create the Blueprint factory
    factory = unreal.BlueprintFactory()
    factory.set_editor_property("parent_class", unreal.Actor)

    # Create the Blueprint asset
    blueprint = asset_tools.create_asset(
        blueprint_name, package_path, unreal.Blueprint, factory
    )

    if not blueprint:
        unreal.log_error("[ERROR] Failed to create Blueprint asset")
        return False

    unreal.log(f"[OK] Blueprint asset created: {blueprint_path}")

    # Use SubobjectDataSubsystem to add components
    subsystem = unreal.get_engine_subsystem(unreal.SubobjectDataSubsystem)
    # Helper library for getting objects from SubobjectData
    helper = unreal.SubobjectDataBlueprintFunctionLibrary

    # Get handles for the blueprint
    root_data_handles = subsystem.k2_gather_subobject_data_for_blueprint(blueprint)

    if len(root_data_handles) == 0:
        unreal.log_error("[ERROR] Failed to get subobject data handles")
        return False

    unreal.log(f"[INFO] Got {len(root_data_handles)} subobject data handles")

    # Find the default scene root
    root_handle = root_data_handles[0]

    with unreal.ScopedEditorTransaction("Setup Punching Bag Blueprint") as transaction:
        try:
            # ============================================
            # PART 1: Add Static Mesh Component for Punching Bag
            # ============================================
            unreal.log("\n[PHASE 1] Adding punching bag mesh component...")

            # Create params for adding a new subobject
            add_params = unreal.AddNewSubobjectParams()
            add_params.parent_handle = root_handle
            add_params.new_class = unreal.StaticMeshComponent
            add_params.blueprint_context = blueprint

            # Add the static mesh component
            result_bag = subsystem.add_new_subobject(add_params)

            # result_bag is a tuple (handle, reason_string)
            bag_handle = result_bag[0] if isinstance(result_bag, tuple) else result_bag

            # Get the actual component data using SubobjectDataBlueprintFunctionLibrary
            bag_data = subsystem.k2_find_subobject_data_from_handle(bag_handle)
            if bag_data:
                # Use the helper library to get the object
                bag_component = helper.get_object_for_blueprint(bag_data, blueprint)
                if bag_component:
                    # Rename the component
                    subsystem.rename_subobject(bag_handle, "PunchingBagMesh")

                    # Set the mesh
                    cylinder_mesh = unreal.load_asset("/Engine/BasicShapes/Cylinder")
                    if cylinder_mesh:
                        bag_component.set_static_mesh(cylinder_mesh)

                    # Set transform - the bag hangs below
                    # Bigger bag for better visibility
                    bag_component.set_editor_property(
                        "relative_location", unreal.Vector(0, 0, -100)
                    )
                    bag_component.set_editor_property(
                        "relative_scale3d",
                        unreal.Vector(0.35, 0.35, 0.7),  # Punching bag shape
                    )

                    # Enable physics via body_instance
                    # Create a new BodyInstance with the physics settings we want
                    new_body_instance = unreal.BodyInstance(
                        simulate_physics=True,
                        enable_gravity=True,
                        linear_damping=0.3,
                        angular_damping=0.3,
                        mass_in_kg_override=30.0,  # 30kg bag
                    )
                    new_body_instance.set_editor_property("override_mass", True)
                    new_body_instance.set_editor_property(
                        "collision_enabled",
                        unreal.CollisionEnabled.QUERY_AND_PHYSICS,
                    )

                    # Assign the body instance to the component
                    bag_component.set_editor_property(
                        "body_instance", new_body_instance
                    )

                    unreal.log("  [OK] Punching bag mesh component added")
                else:
                    unreal.log_warning("  [WARNING] Could not get bag component object")
            else:
                unreal.log_warning("  [WARNING] Could not get bag component data")

            # ============================================
            # PART 2: Add Cable Component for Rope
            # ============================================
            unreal.log("\n[PHASE 2] Adding cable (rope) component...")

            add_params_cable = unreal.AddNewSubobjectParams()
            add_params_cable.parent_handle = root_handle
            add_params_cable.new_class = unreal.CableComponent
            add_params_cable.blueprint_context = blueprint

            result_cable = subsystem.add_new_subobject(add_params_cable)
            cable_handle = (
                result_cable[0] if isinstance(result_cable, tuple) else result_cable
            )

            cable_data = subsystem.k2_find_subobject_data_from_handle(cable_handle)
            if cable_data:
                cable_component = helper.get_object_for_blueprint(cable_data, blueprint)
                if cable_component:
                    subsystem.rename_subobject(cable_handle, "RopeCable")

                    # Set cable properties - rope connecting hook to bag
                    cable_component.set_editor_property(
                        "cable_length", 60.0
                    )  # Shorter rope
                    cable_component.set_editor_property(
                        "cable_width", 2.0
                    )  # Thinner rope
                    cable_component.set_editor_property("num_segments", 8)
                    cable_component.set_editor_property("num_sides", 6)
                    cable_component.set_editor_property("enable_stiffness", True)
                    cable_component.set_editor_property("solver_iterations", 8)
                    cable_component.set_editor_property("enable_collision", True)

                    # Set end location to connect to top of bag
                    cable_component.set_editor_property(
                        "end_location",
                        unreal.Vector(0, 0, -65),  # Connect to top of bag
                    )

                    unreal.log("  [OK] Cable (rope) component added")
                else:
                    unreal.log_warning(
                        "  [WARNING] Could not get cable component object"
                    )
            else:
                unreal.log_warning("  [WARNING] Could not get cable component data")

            # ============================================
            # PART 3: Add Physics Constraint Component
            # ============================================
            unreal.log("\n[PHASE 3] Adding physics constraint...")

            add_params_constraint = unreal.AddNewSubobjectParams()
            add_params_constraint.parent_handle = root_handle
            add_params_constraint.new_class = unreal.PhysicsConstraintComponent
            add_params_constraint.blueprint_context = blueprint

            result_constraint = subsystem.add_new_subobject(add_params_constraint)
            constraint_handle = (
                result_constraint[0]
                if isinstance(result_constraint, tuple)
                else result_constraint
            )

            constraint_data = subsystem.k2_find_subobject_data_from_handle(
                constraint_handle
            )
            if constraint_data:
                constraint_component = helper.get_object_for_blueprint(
                    constraint_data, blueprint
                )
                if constraint_component:
                    subsystem.rename_subobject(constraint_handle, "SwingConstraint")

                    # The constraint will connect the bag to the hook point
                    # allowing it to swing freely
                    # Create ConstrainComponentPropName properly
                    prop_name1 = unreal.ConstrainComponentPropName()
                    prop_name1.set_editor_property("component_name", "DefaultSceneRoot")
                    constraint_component.set_editor_property(
                        "component_name1", prop_name1
                    )

                    prop_name2 = unreal.ConstrainComponentPropName()
                    prop_name2.set_editor_property("component_name", "PunchingBagMesh")
                    constraint_component.set_editor_property(
                        "component_name2", prop_name2
                    )

                    unreal.log("  [OK] Physics constraint component added")
                else:
                    unreal.log_warning(
                        "  [WARNING] Could not get constraint component object"
                    )
            else:
                unreal.log_warning(
                    "  [WARNING] Could not get constraint component data"
                )

        except Exception as e:
            transaction.cancel()
            unreal.log_error(f"[ERROR] Failed to setup Blueprint: {e}")
            import traceback

            traceback.print_exc()
            return False

    # Compile the Blueprint
    unreal.BlueprintEditorLibrary.compile_blueprint(blueprint)
    unreal.log("\n[OK] Blueprint compiled")

    # Save the Blueprint
    unreal.EditorAssetLibrary.save_asset(blueprint_path)
    unreal.log(f"[OK] Blueprint saved: {blueprint_path}")

    # Summary
    unreal.log("\n" + "=" * 60)
    unreal.log("[COMPLETE] Punching Bag Blueprint Created Successfully!")
    unreal.log("=" * 60)
    unreal.log(f"Blueprint: {blueprint_path}")
    unreal.log("\nComponents:")
    unreal.log("  - DefaultSceneRoot - Attachment point (hook)")
    unreal.log("  - PunchingBagMesh - Physics-enabled punching bag")
    unreal.log("  - RopeCable - Visual rope with physics")
    unreal.log("  - SwingConstraint - Connects bag to hook for swinging")
    unreal.log("\nPhysics Features:")
    unreal.log("  - Gravity enabled on bag")
    unreal.log("  - 30kg mass for realistic swinging")
    unreal.log("  - Damping for smooth movement")
    unreal.log("  - Cable physics simulation")
    unreal.log("\nUsage: Place BP_PunchingBag in level, position at desired hook point")
    unreal.log("=" * 60)

    return True


if __name__ == "__main__":
    create_punching_bag_blueprint("/Game/Blueprints/BP_PunchingBag")
