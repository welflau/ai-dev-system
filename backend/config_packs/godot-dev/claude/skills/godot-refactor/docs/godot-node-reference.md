# Godot 4.x Complete Node Reference

**Last Updated:** February 2026
**Source:** Official Godot 4.x Documentation + Web Research (2026)

This is a comprehensive reference for all major Godot 4.x node types, organized by category for intelligent node selection during refactoring operations.

---

## Table of Contents

1. [Core Base Nodes](#core-base-nodes)
2. [2D Visual Nodes](#2d-visual-nodes)
3. [2D Physics Nodes](#2d-physics-nodes)
4. [2D Lighting Nodes](#2d-lighting-nodes)
5. [2D Particle Nodes](#2d-particle-nodes)
6. [2D Navigation Nodes](#2d-navigation-nodes)
7. [3D Visual Nodes](#3d-visual-nodes)
8. [3D Physics Nodes](#3d-physics-nodes)
9. [3D Navigation Nodes](#3d-navigation-nodes)
10. [3D Lighting Nodes](#3d-lighting-nodes)
11. [Audio Nodes](#audio-nodes)
12. [UI/Control Nodes](#uicontrol-nodes)
13. [Container Nodes](#container-nodes)
14. [Utility & Timing Nodes](#utility--timing-nodes)
15. [Viewport & Camera Nodes](#viewport--camera-nodes)

---

## Core Base Nodes

### Node

**Type:** Base Class
**Extends:** Object
**Purpose:** The fundamental base class for all scene nodes. Provides scene tree management, signals, and lifecycle methods. Used for non-spatial, non-visual logic nodes.

**Key Properties:**
- `name` (String): Node identifier in scene
- `owner` (Node): Scene owner
- `process_mode` (enum): How node processes updates
- `unique_name_in_owner` (bool): Unique identifier

**Optimal Use Cases:**
- Data-only nodes (managers, controllers)
- Nodes that don't need position/visibility
- Non-visual logic containers
- Autoload (singleton) patterns

**Common Patterns:**
- Scene managers storing game state
- Event buses for inter-node communication
- Game controllers and input handlers

**tscn Template:**
```ini
[gd_scene format=3]

[node name="LogicNode" type="Node"]
```

**Related Nodes:**
- Node2D: When you need 2D spatial features
- Node3D: When you need 3D spatial features

---

### Node2D

**Type:** Core 2D
**Extends:** CanvasItem
**Purpose:** Base node for all 2D scenes. Provides position, rotation, scale, and Z-index for 2D spatial relationships.

**Key Properties:**
- `position` (Vector2): Node position in parent space
- `rotation` (float): Node rotation in radians
- `scale` (Vector2): Node scale (1.0 = 100%)
- `z_index` (int): Depth ordering
- `global_position` (Vector2): Position relative to scene root
- `global_rotation` (float): Rotation relative to scene root

**Optimal Use Cases:**
- Base for all 2D spatial objects
- Organizing 2D scene hierarchies
- Manual control of transform
- Grouping 2D nodes

**Common Patterns:**
- Parent node for game entities
- Camera reference node
- World container node

**tscn Template:**
```ini
[gd_scene format=3]

[node name="GameWorld" type="Node2D"]
position = Vector2(0, 0)
rotation = 0.0
scale = Vector2(1, 1)
```

**Related Nodes:**
- CanvasItem: When you need drawing capabilities
- Sprite2D: When you need visual representation
- Area2D: When you need physics detection

---

### Node3D

**Type:** Core 3D
**Extends:** Node
**Purpose:** Base node for all 3D scenes. Provides position, rotation, scale in 3D space (replaced Spatial in Godot 4).

**Key Properties:**
- `position` (Vector3): Node position
- `rotation` (Vector3): Node rotation in radians
- `scale` (Vector3): Node scale
- `global_position` (Vector3): Position relative to scene root
- `global_rotation` (Vector3): Rotation relative to scene root
- `transform` (Transform3D): Complete transform matrix

**Optimal Use Cases:**
- Base for all 3D spatial objects
- 3D scene organization
- 3D world containers
- 3D physics bodies

**Common Patterns:**
- Parent node for 3D game entities
- 3D environment setup
- 3D level organization

**tscn Template:**
```ini
[gd_scene format=3]

[node name="GameWorld3D" type="Node3D"]
position = Vector3(0, 0, 0)
rotation = Vector3(0, 0, 0)
scale = Vector3(1, 1, 1)
```

**Related Nodes:**
- MeshInstance3D: When you need 3D visual representation
- RigidBody3D: When you need 3D physics
- Camera3D: When you need 3D viewpoint

---

### CanvasItem

**Type:** Base Visual
**Extends:** Node
**Purpose:** Base class for all 2D visual nodes. Provides drawing capabilities, visibility, and canvas operations.

**Key Properties:**
- `visible` (bool): Node visibility
- `modulate` (Color): Color tint (affects children)
- `self_modulate` (Color): Color tint (self only)
- `z_index` (int): Drawing order
- `blend_mode` (enum): How to blend with background

**Optimal Use Cases:**
- Base for custom 2D drawing
- Controlling visibility of 2D groups
- Color effects on visual hierarchy
- Custom rendering operations

**Common Patterns:**
- Parent class for custom visual nodes
- Group color/visibility control

**tscn Template:**
```ini
[gd_scene format=3]

[node name="VisualNode" type="Node2D"]
visible = true
modulate = Color(1, 1, 1, 1)
```

**Related Nodes:**
- Node2D: For spatial + drawing
- Sprite2D: For static image display
- Control: For UI elements

---

## 2D Visual Nodes

### Sprite2D

**Type:** 2D Visual
**Extends:** Node2D
**Purpose:** Displays a single static 2D image/texture. Most common node for rendering 2D graphics.

**Key Properties:**
- `texture` (Texture2D): The image to display
- `centered` (bool): Center image on node position
- `offset` (Vector2): Manual offset from position
- `scale` (Vector2): Sprite scale
- `flip_h` / `flip_v` (bool): Horizontal/vertical flip
- `region_enabled` (bool): Enable texture region
- `region_rect` (Rect2): Which part of texture to show

**Optimal Use Cases:**
- Character/enemy sprites
- Static environmental objects
- Simple game entity visuals
- UI icons and images
- Tilemap building blocks

**Common Patterns:**
- Combine with CharacterBody2D for player
- Combine with Area2D for detection
- Combine with AnimatedSprite2D for animation

**tscn Template:**
```ini
[gd_scene load_steps=2 format=3]

[ext_resource type="Texture2D" path="res://assets/sprite.png" id="1"]

[node name="Sprite2D" type="Sprite2D"]
texture = ExtResource("1")
centered = true
```

**Related Nodes:**
- AnimatedSprite2D: When you need frame-by-frame animation
- TextureRect: When you need UI image display
- Polygon2D: When you need custom shape rendering

---

### AnimatedSprite2D

**Type:** 2D Visual
**Extends:** Node2D
**Purpose:** Displays animated sprites using frame sequences from a SpriteFrames resource.

**Key Properties:**
- `sprite_frames` (SpriteFrames): Animation data resource
- `animation` (String): Current animation name
- `frame` (int): Current frame number
- `playing` (bool): Is animation playing
- `speed_scale` (float): Animation speed multiplier

**Optimal Use Cases:**
- Character animations (walk, run, jump)
- Enemy animations
- Visual effects animations
- UI animated elements
- Dialogue character animations

**Common Patterns:**
- Play animations via script: `$AnimatedSprite2D.play("walk")`
- Combine with CharacterBody2D for animated player
- Connect animation_finished signal

**tscn Template:**
```ini
[gd_scene load_steps=2 format=3]

[ext_resource type="SpriteFrames" path="res://assets/frames.tres" id="1"]

[node name="AnimatedSprite2D" type="AnimatedSprite2D"]
sprite_frames = ExtResource("1")
animation = "idle"
playing = true
```

**Related Nodes:**
- Sprite2D: When you don't need animation
- AnimationPlayer: For complex skeletal animation
- SpriteFrames: Resource that holds animation data

---

### Line2D

**Type:** 2D Visual
**Extends:** Node2D
**Purpose:** Draws a continuous line between multiple 2D points. Useful for paths, drawing, and visual guides.

**Key Properties:**
- `points` (PackedVector2Array): Array of points forming the line
- `width` (float): Line thickness
- `width_curve` (Curve): Width variation along line
- `default_color` (Color): Line color
- `antialiased` (bool): Smooth line edges
- `joint_mode` (enum): How corners connect
- `begin_cap_mode` / `end_cap_mode` (enum): Line end styles

**Optimal Use Cases:**
- Path visualization
- Laser beam effects
- Drawing mechanics
- Debug visualization
- Health/energy bars (alternative to ProgressBar)

**Common Patterns:**
- Update points in real-time: `$Line2D.add_point(new_point)`
- Create procedural paths
- Animate line drawing

**tscn Template:**
```ini
[gd_scene format=3]

[node name="Line2D" type="Line2D"]
width = 2.0
default_color = Color(1, 1, 1, 1)
antialiased = true
points = PackedVector2Array(Vector2(0, 0), Vector2(100, 100))
```

**Related Nodes:**
- Polygon2D: When you need filled shapes
- ProgressBar: For health/energy visualization
- Sprite2D: For static visuals

---

### Polygon2D

**Type:** 2D Visual
**Extends:** Node2D
**Purpose:** Draws a filled polygon shape. Useful for platforms, terrain, and custom shapes.

**Key Properties:**
- `polygon` (PackedVector2Array): Vertices defining shape
- `color` (Color): Fill color
- `texture` (Texture2D): Optional texture fill
- `texture_offset` (Vector2): Texture position offset
- `internal_vertex_count` (int): For complex shapes

**Optimal Use Cases:**
- Platform shapes
- Terrain visualization
- Custom game entity shapes
- Procedural shape generation
- Environment visuals

**Common Patterns:**
- Use with physics for collision (add CollisionPolygon2D as child)
- Procedurally generate shapes
- Animate polygon vertices

**tscn Template:**
```ini
[gd_scene format=3]

[node name="Platform" type="Polygon2D"]
color = Color(0.5, 0.5, 0.5, 1)
polygon = PackedVector2Array(Vector2(0, 0), Vector2(100, 0), Vector2(100, 20), Vector2(0, 20))
```

**Related Nodes:**
- Line2D: When you need line only, not filled
- CollisionPolygon2D: For collision shapes
- Sprite2D: For image-based visuals

---

### MeshInstance2D

**Type:** 2D Visual
**Extends:** Node2D
**Purpose:** Displays 2D meshes with materials. Advanced rendering beyond simple sprites.

**Key Properties:**
- `mesh` (Mesh): The mesh geometry
- `texture` (Texture2D): Mesh texture
- `material` (Material): Shader material

**Optimal Use Cases:**
- Complex 2D rendering
- Custom mesh-based visuals
- Shader effects
- Batch rendering optimization

**Common Patterns:**
- Apply custom materials
- Use with shaders for effects

**tscn Template:**
```ini
[gd_scene format=3]

[node name="MeshInstance2D" type="MeshInstance2D"]
```

**Related Nodes:**
- Sprite2D: For simpler image display
- MultiMeshInstance2D: For multiple instances
- Material: For shader effects

---

### MultiMeshInstance2D

**Type:** 2D Visual
**Extends:** Node2D
**Purpose:** Renders multiple copies of the same mesh efficiently. Great for performance with many identical objects.

**Key Properties:**
- `multimesh` (MultiMesh): Contains mesh + instance data
- `texture` (Texture2D): Optional texture

**Optimal Use Cases:**
- Rendering many identical objects (trees, rocks, particles)
- Optimization for tile-based visuals
- Performance-critical situations

**Common Patterns:**
- Pre-create MultiMesh with transforms
- Use for visual optimization

**tscn Template:**
```ini
[gd_scene format=3]

[node name="MultiMeshInstance2D" type="MultiMeshInstance2D"]
```

**Related Nodes:**
- Sprite2D: For individual sprites
- MeshInstance2D: For single mesh
- TileMap: For tiled visuals

---

## 2D Physics Nodes

### RigidBody2D

**Type:** 2D Physics
**Extends:** PhysicsBody2D
**Purpose:** Physics body affected by forces and gravity. Used for objects that should behave like solid, movable objects.

**Key Properties:**
- `mass` (float): Object mass (affects physics)
- `gravity_scale` (float): How much gravity affects object
- `linear_velocity` (Vector2): Current velocity
- `angular_velocity` (float): Rotation speed
- `lock_rotation` (bool): Prevent rotation
- `constraints` (int): Frozen axes/rotation
- `friction` (float): Sliding friction
- `bounce` (float): Bounce/restitution

**Optimal Use Cases:**
- Balls, projectiles, bouncing objects
- Falling debris
- Physics-interactive objects
- Anything that should fall or be pushed by physics

**Common Patterns:**
- Apply force: `$RigidBody2D.apply_central_force(direction * force)`
- Add impulse: `add_central_impulse(force)`
- Check velocity in script

**tscn Template:**
```ini
[gd_scene load_steps=2 format=3]

[ext_resource type="Script" path="res://player.gd" id="1"]

[node name="RigidBody2D" type="RigidBody2D"]
mass = 1.0
gravity_scale = 1.0
script = ExtResource("1")

[node name="CollisionShape2D" parent="." instance=ExtResource("2")]
```

**Related Nodes:**
- CharacterBody2D: For player movement (better control)
- StaticBody2D: For immovable objects
- Area2D: For detection without physics
- CollisionShape2D: Required child for collision

---

### CharacterBody2D

**Type:** 2D Physics
**Extends:** PhysicsBody2D
**Purpose:** Specialized physics body for player/character movement. Provides built-in kinematic movement without being affected by gravity/physics forces by default.

**Key Properties:**
- `velocity` (Vector2): Character movement velocity
- `floor_snap_length` (float): Distance to snap to floor
- `floor_max_angle` (float): Maximum slope angle
- `velocity_mode` (enum): How velocity is applied

**Optimal Use Cases:**
- Player character controller
- NPCs with controlled movement
- Platform game characters
- Enemies with navigation
- Any entity that needs precise movement control

**Common Patterns:**
- Apply velocity in _physics_process: `velocity = calculate_velocity()` then `move_and_slide()`
- Check is_on_floor() for jump logic
- Implement acceleration/deceleration

**tscn Template:**
```ini
[gd_scene load_steps=3 format=3]

[ext_resource type="Script" path="res://player.gd" id="1"]
[ext_resource type="Texture2D" path="res://player.png" id="2"]

[node name="Player" type="CharacterBody2D"]
script = ExtResource("1")

[node name="Sprite2D" parent="." type="Sprite2D"]
texture = ExtResource("2")

[node name="CollisionShape2D" parent="." type="CollisionShape2D"]
```

**Related Nodes:**
- RigidBody2D: For physics-affected objects
- StaticBody2D: For immovable obstacles
- Area2D: For detection zones
- AnimatedSprite2D: Combine for animated characters

---

### StaticBody2D

**Type:** 2D Physics
**Extends:** PhysicsBody2D
**Purpose:** Immovable physics body. Objects collide with it, but it never moves. Used for walls, platforms, terrain.

**Key Properties:**
- (No unique physics properties - completely static)
- Can be moved in editor or by script, but physics don't move it

**Optimal Use Cases:**
- Walls and obstacles
- Platforms
- Level geometry
- Terrain
- Unmovable furniture
- Collision barriers

**Common Patterns:**
- Combine with Sprite2D for platform visuals
- Combine with CollisionPolygon2D for complex shapes
- Use for level layout

**tscn Template:**
```ini
[gd_scene load_steps=3 format=3]

[ext_resource type="Texture2D" path="res://platform.png" id="1"]

[node name="Platform" type="StaticBody2D"]

[node name="Sprite2D" parent="." type="Sprite2D"]
texture = ExtResource("1")

[node name="CollisionShape2D" parent="." type="CollisionShape2D"]
```

**Related Nodes:**
- RigidBody2D: For movable objects
- CharacterBody2D: For player movement
- Area2D: For detection instead of solid collision
- CollisionShape2D: Required for collision

---

### Area2D

**Type:** 2D Physics (Detection)
**Extends:** PhysicsBody2D
**Purpose:** Non-solid detection area. Detects overlaps with other bodies but doesn't collide or block movement. Used for triggers, damage zones, detection.

**Key Properties:**
- `monitoring` (bool): Can detect other bodies
- `monitorable` (bool): Can be detected by other bodies
- `collision_layer` (int): Which layers this area is on
- `collision_mask` (int): Which layers this area detects

**Optimal Use Cases:**
- Damage zones/hit areas
- Pickup/trigger zones
- Detection areas for AI
- Sensors (footsteps, pressure plates)
- Win conditions (goal areas)
- Interaction zones

**Common Patterns:**
- Connect signals: `body_entered.connect(_on_body_entered)`
- Check overlapping bodies: `get_overlapping_bodies()`
- Use for damage detection

**tscn Template:**
```ini
[gd_scene load_steps=2 format=3]

[ext_resource type="Script" path="res://damage_area.gd" id="1"]

[node name="DamageArea" type="Area2D"]
script = ExtResource("1")

[node name="CollisionShape2D" parent="." type="CollisionShape2D"]

[node name="Timer" parent="." type="Timer"]
```

**Related Nodes:**
- RigidBody2D: For solid physics objects
- CharacterBody2D: For player with physics
- StaticBody2D: For solid, static obstacles
- CollisionShape2D: Required for detection shape

---

### CollisionShape2D

**Type:** 2D Physics (Helper)
**Extends:** Node2D
**Purpose:** Defines collision shape for a physics body. Not visual by itself - must be child of physics body to work.

**Key Properties:**
- `shape` (Shape2D): The collision shape (CircleShape2D, RectangleShape2D, CapsuleShape2D, etc.)
- `disabled` (bool): Enable/disable collision

**Optimal Use Cases:**
- Required for all 2D physics bodies
- Define collision boundaries
- Create multiple shapes for complex bodies
- Hit boxes for damage

**Common Patterns:**
- Create as child of RigidBody2D, CharacterBody2D, StaticBody2D, Area2D
- Use shape templates from Godot
- Multiple children for complex shapes

**tscn Template:**
```ini
[gd_scene format=3]

[node name="Body" type="RigidBody2D"]

[node name="CollisionShape2D" parent="." type="CollisionShape2D"]
shape = CircleShape2D()
position = Vector2(0, 0)
```

**Related Nodes:**
- RigidBody2D: Parent for physics objects
- CharacterBody2D: Parent for characters
- StaticBody2D: Parent for static obstacles
- Area2D: Parent for detection zones
- CollisionPolygon2D: Alternative for custom shapes

---

### CollisionPolygon2D

**Type:** 2D Physics (Helper)
**Extends:** Node2D
**Purpose:** Defines collision using a polygon. Alternative to CollisionShape2D for complex, custom shapes.

**Key Properties:**
- `polygon` (PackedVector2Array): Vertices of collision shape
- `disabled` (bool): Enable/disable collision

**Optimal Use Cases:**
- Complex, irregular collision shapes
- Platform shapes with detail
- Custom terrain collision
- Non-rectangular obstacles

**Common Patterns:**
- Use with Polygon2D for visual + collision match
- Create in editor with visual tools
- Child of physics bodies

**tscn Template:**
```ini
[gd_scene format=3]

[node name="Platform" type="StaticBody2D"]

[node name="CollisionPolygon2D" parent="." type="CollisionPolygon2D"]
polygon = PackedVector2Array(Vector2(0, 0), Vector2(100, 0), Vector2(100, 20), Vector2(0, 20))
```

**Related Nodes:**
- CollisionShape2D: For simpler, predefined shapes
- Polygon2D: For visual representation

---

## 2D Lighting Nodes

### Light2D

**Type:** 2D Lighting (Base)
**Extends:** Node2D
**Purpose:** Base class for 2D lights. Provides lighting and shadow support for 2D scenes.

**Key Properties:**
- `enabled` (bool): Light on/off
- `energy` (float): Light brightness
- `color` (Color): Light color
- `blend_mode` (enum): How light blends with scene
- `shadow_enabled` (bool): Cast shadows
- `range_z_min` / `range_z_max` (float): Z-index range

**Optimal Use Cases:**
- 2D dynamic lighting
- Shadow effects
- Ambient lighting
- Atmospheric effects

**Related Nodes:**
- PointLight2D: For localized light sources
- DirectionalLight2D: For sun-like lighting
- LightOccluder2D: For shadow casting

---

### PointLight2D

**Type:** 2D Lighting
**Extends:** Light2D
**Purpose:** Localized 2D light source that emits from a single point. Creates a radiant light effect.

**Key Properties:**
- `energy` (float): Light brightness
- `color` (Color): Light color
- `texture` (Texture2D): Light projection texture
- `texture_scale` (float): Texture size
- `radius` (float): Light range
- `shadow_enabled` (bool): Cast shadows
- `blend_mode` (enum): Addition, Multiply, Mix

**Optimal Use Cases:**
- Lanterns, torches, lamps
- Explosions, muzzle flashes
- Room/dungeon lighting
- Dynamic shadow effects
- Candlelight

**Common Patterns:**
- Attach to moving objects for dynamic lighting
- Animate energy for flickering
- Combine with LightOccluder2D for shadows

**tscn Template:**
```ini
[gd_scene format=3]

[node name="Lantern" type="PointLight2D"]
energy = 1.0
color = Color(1, 0.8, 0, 1)
texture_scale = 1.0
radius = 100.0
shadow_enabled = true
```

**Related Nodes:**
- DirectionalLight2D: For sun-like global lighting
- LightOccluder2D: For shadow casting objects
- Light2D: Base class

---

### DirectionalLight2D

**Type:** 2D Lighting
**Extends:** Light2D
**Purpose:** Directional 2D light that emits in one direction (like sunlight). Affects everything equally regardless of distance.

**Key Properties:**
- `energy` (float): Light brightness
- `color` (Color): Light color
- `shadow_enabled` (bool): Cast shadows
- `blend_mode` (enum): Light blend mode

**Optimal Use Cases:**
- Sunlight
- Moonlight
- Global ambient lighting
- Global shadow direction

**Common Patterns:**
- Rotate for time-of-day effects
- Animate energy for day/night cycle
- Combine with PointLight2D for local lights

**tscn Template:**
```ini
[gd_scene format=3]

[node name="Sun" type="DirectionalLight2D"]
rotation = 0.0
energy = 1.0
color = Color(1, 1, 0.8, 1)
shadow_enabled = true
```

**Related Nodes:**
- PointLight2D: For localized lights
- LightOccluder2D: For shadow casting
- Light2D: Base class

---

### LightOccluder2D

**Type:** 2D Lighting (Helper)
**Extends:** Node2D
**Purpose:** Defines what blocks light and casts shadows. Works with Light2D nodes to create shadow effects.

**Key Properties:**
- `occluder` (OccluderPolygon2D): The shadow shape
- `sdf_collision` (bool): Use signed distance field

**Optimal Use Cases:**
- Shadow casting for obstacles
- Wall shadows
- Character shadows
- Dynamic shadow effects

**Common Patterns:**
- Child of objects that should cast shadows
- Pair with PointLight2D or DirectionalLight2D

**tscn Template:**
```ini
[gd_scene format=3]

[node name="Wall" type="StaticBody2D"]

[node name="LightOccluder2D" parent="." type="LightOccluder2D"]
```

**Related Nodes:**
- PointLight2D: Light that casts shadows
- DirectionalLight2D: Directional shadow light

---

## 2D Particle Nodes

### GPUParticles2D

**Type:** 2D Particles
**Extends:** Node2D
**Purpose:** GPU-accelerated 2D particle system. High-performance particle effects using graphics hardware.

**Key Properties:**
- `emitting` (bool): Emit particles
- `amount` (int): Number of particles
- `lifetime` (float): How long each particle lives
- `process_material` (Material): Particle behavior
- `texture` (Texture2D): Particle image

**Optimal Use Cases:**
- Explosions
- Dust/smoke effects
- Rain/snow
- Magical effects
- High-performance particle systems
- Fire, sparkles, weather

**Common Patterns:**
- Set emitting = true/false to control
- Use custom materials for effects
- Set one_shot for burst effects

**tscn Template:**
```ini
[gd_scene load_steps=2 format=3]

[ext_resource type="Material" path="res://particles.tres" id="1"]

[node name="GPUParticles2D" type="GPUParticles2D"]
emitting = true
amount = 50
lifetime = 2.0
process_material = ExtResource("1")
```

**Related Nodes:**
- CPUParticles2D: CPU-based alternative
- Particles2D: Legacy particle system

---

### CPUParticles2D

**Type:** 2D Particles
**Extends:** Node2D
**Purpose:** CPU-based 2D particle system. More compatible but less performant than GPU particles.

**Key Properties:**
- `emitting` (bool): Emit particles
- `amount` (int): Number of particles
- `lifetime` (float): Particle lifetime
- `emission_shape` (enum): Emission area shape
- `gravity` (Vector2): Particle gravity

**Optimal Use Cases:**
- Older device compatibility
- Customizable particle data access
- Particles that need script control
- Effects on less powerful hardware

**Common Patterns:**
- Access particles directly in script
- Customize individual particle properties
- Use for compatibility

**tscn Template:**
```ini
[gd_scene format=3]

[node name="CPUParticles2D" type="CPUParticles2D"]
emitting = true
amount = 30
lifetime = 1.5
gravity = Vector2(0, 98)
```

**Related Nodes:**
- GPUParticles2D: Faster GPU version
- Particles2D: Legacy

---

## 2D Navigation Nodes

### NavigationRegion2D

**Type:** 2D Navigation
**Extends:** Node2D
**Purpose:** Defines a navigable area for pathfinding. Contains a NavigationPolygon that represents where entities can walk.

**Key Properties:**
- `navigation_polygon` (NavigationPolygon): Walkable area definition
- `navigation_layers` (int): Layer bitmask for pathfinding

**Optimal Use Cases:**
- Define playable areas in level
- Create walking boundaries
- Pathfinding foundation
- Level layout navigation

**Common Patterns:**
- Create NavigationPolygon in editor with drawing tools
- Combine with NavigationAgent2D for AI movement
- Create multiple regions for complex levels

**tscn Template:**
```ini
[gd_scene load_steps=2 format=3]

[ext_resource type="NavigationPolygon" path="res://nav_poly.tres" id="1"]

[node name="NavRegion" type="NavigationRegion2D"]
navigation_polygon = ExtResource("1")
```

**Related Nodes:**
- NavigationAgent2D: For AI movement using the region
- NavigationLink2D: For connecting regions
- NavigationObstacle2D: For dynamic obstacles

---

### NavigationAgent2D

**Type:** 2D Navigation
**Extends:** Node2D
**Purpose:** Pathfinding and movement node for AI entities. Navigates using NavigationRegion2D data.

**Key Properties:**
- `target_position` (Vector2): Goal position to pathfind to
- `path_desired_distance` (float): Accuracy to destination
- `navigation_layers` (int): Which layers to use for pathfinding
- `max_speed` (float): Max movement speed

**Optimal Use Cases:**
- Enemy AI pathfinding
- NPC movement
- Autonomous entity navigation
- Game AI path planning

**Common Patterns:**
- Set target_position for entity to move to
- Check path_changed signal for updates
- Check target_reached signal for goal

**tscn Template:**
```ini
[gd_scene format=3]

[node name="Enemy" type="CharacterBody2D"]

[node name="NavAgent" parent="." type="NavigationAgent2D"]
target_position = Vector2(100, 100)

[node name="Sprite2D" parent="." type="Sprite2D"]
```

**Related Nodes:**
- NavigationRegion2D: Provides navigation mesh
- CharacterBody2D: Body to move
- NavigationLink2D: For path connections
- NavigationObstacle2D: For dynamic obstacles

---

### NavigationLink2D

**Type:** 2D Navigation
**Extends:** Node2D
**Purpose:** Connects two positions on navigation meshes for pathfinding. Allows bridging gaps or custom paths.

**Key Properties:**
- `start_position` (Vector2): Link start
- `end_position` (Vector2): Link end
- `navigation_layers` (int): Layer mask
- `bidirectional` (bool): Two-way or one-way link

**Optimal Use Cases:**
- Bridges between navigation regions
- Ladders or climbing zones
- Gaps that shouldn't be traversable
- Custom pathfinding routes
- One-way passages

**Common Patterns:**
- Connect separate navigation regions
- Create special movement paths

**tscn Template:**
```ini
[gd_scene format=3]

[node name="Bridge" type="NavigationLink2D"]
start_position = Vector2(0, 0)
end_position = Vector2(200, 0)
bidirectional = true
```

**Related Nodes:**
- NavigationRegion2D: Regions it connects
- NavigationAgent2D: Uses links for pathfinding
- NavigationObstacle2D: For obstacles

---

### NavigationObstacle2D

**Type:** 2D Navigation
**Extends:** Node2D
**Purpose:** Dynamic obstacle that affects pathfinding. Moving obstacles can be registered with pathfinding system.

**Key Properties:**
- `radius` (float): Obstacle size
- `navigation_layers` (int): Layer mask
- `avoidance_enabled` (bool): Crowd avoidance

**Optimal Use Cases:**
- Moving obstacles in pathfinding
- Dynamic collision avoidance
- Crowd simulation
- Entities blocking paths

**Common Patterns:**
- Attach to moving entities
- Enable avoidance for crowd behavior

**tscn Template:**
```ini
[gd_scene format=3]

[node name="MovingObstacle" type="Node2D"]

[node name="NavObstacle" parent="." type="NavigationObstacle2D"]
radius = 10.0
avoidance_enabled = true
```

**Related Nodes:**
- NavigationAgent2D: Uses obstacles for pathfinding
- NavigationRegion2D: Obstacle avoidance in region
- NavigationLink2D: For custom paths

---

## 3D Visual Nodes

### MeshInstance3D

**Type:** 3D Visual
**Extends:** Node3D
**Purpose:** Displays 3D geometry (meshes). The primary 3D visual node for rendering 3D models.

**Key Properties:**
- `mesh` (Mesh): The 3D geometry to display
- `material` (Material): Surface appearance/shader
- `instance_shader_parameters` (dict): Per-instance shader settings
- `cast_shadow` (enum): Shadow casting mode

**Optimal Use Cases:**
- Character models
- Environmental objects
- Props and scenery
- Weapons and items
- Anything 3D visual

**Common Patterns:**
- Import models from external tools
- Apply materials for appearance
- Combine with collision shapes
- Animate using AnimationPlayer

**tscn Template:**
```ini
[gd_scene load_steps=3 format=3]

[ext_resource type="Mesh" path="res://models/character.tres" id="1"]
[ext_resource type="Material" path="res://materials/character.tres" id="2"]

[node name="Character" type="Node3D"]

[node name="Mesh" parent="." type="MeshInstance3D"]
mesh = ExtResource("1")
material = ExtResource("2")
```

**Related Nodes:**
- Node3D: Parent spatial node
- CollisionShape3D: Collision for physics
- AnimationPlayer: For skeletal animation
- Material: For appearance

---

### Camera3D

**Type:** 3D View
**Extends:** Node3D
**Purpose:** Defines viewpoint and projection for rendering 3D scene. Only one can be active per viewport.

**Key Properties:**
- `current` (bool): Is this the active camera
- `fov` (float): Field of view angle
- `near` (float): Near clipping plane
- `far` (float): Far clipping plane
- `global_position` (Vector3): Camera position
- `global_rotation` (Vector3): Camera rotation

**Optimal Use Cases:**
- First-person camera
- Third-person camera
- Cinematic camera
- Fixed camera angles
- Orbital camera

**Common Patterns:**
- Make current to activate
- Follow player/target
- Implement smooth camera movement
- Lerp for smooth transitions

**tscn Template:**
```ini
[gd_scene load_steps=2 format=3]

[ext_resource type="Script" path="res://camera.gd" id="1"]

[node name="Camera3D" type="Camera3D"]
current = true
fov = 75.0
far = 1000.0
script = ExtResource("1")
```

**Related Nodes:**
- Node3D: Parent for positioning
- RemoteTransform3D: Link to another node
- Viewport: Receives camera output

---

## 3D Physics Nodes

### RigidBody3D

**Type:** 3D Physics
**Extends:** PhysicsBody3D
**Purpose:** 3D physics body affected by forces and gravity. For movable, physics-interactive objects.

**Key Properties:**
- `mass` (float): Object mass
- `gravity_scale` (float): Gravity multiplier
- `linear_velocity` (Vector3): Current velocity
- `angular_velocity` (Vector3): Rotation velocity
- `lock_rotation_x/y/z` (bool): Freeze rotation axes
- `physics_material_override` (PhysicsMaterial): Friction/bounce

**Optimal Use Cases:**
- Balls, projectiles
- Falling objects
- Physics-driven interactions
- Destructible objects
- Anything that falls or is pushed

**Common Patterns:**
- Apply force: `add_central_force()`
- Add impulse: `apply_central_impulse()`
- Check velocity for animations

**tscn Template:**
```ini
[gd_scene load_steps=2 format=3]

[ext_resource type="Script" path="res://ball.gd" id="1"]

[node name="Ball" type="RigidBody3D"]
mass = 1.0
script = ExtResource("1")

[node name="Mesh" parent="." type="MeshInstance3D"]

[node name="Collision" parent="." type="CollisionShape3D"]
```

**Related Nodes:**
- CharacterBody3D: For player/character control
- StaticBody3D: For immovable objects
- Area3D: For detection zones
- CollisionShape3D: Required for collision

---

### CharacterBody3D

**Type:** 3D Physics
**Extends:** PhysicsBody3D
**Purpose:** Specialized 3D physics body for character/player movement. Kinematic control without physics forces.

**Key Properties:**
- `velocity` (Vector3): Movement velocity
- `floor_snap_length` (float): Distance to maintain floor contact
- `floor_max_angle` (float): Maximum slope
- `velocity_mode` (enum): How velocity applies

**Optimal Use Cases:**
- Player character controller
- NPC movement
- Platform game characters
- Any entity needing precise movement
- 3D puzzle game characters

**Common Patterns:**
- Calculate velocity in _physics_process
- Call move_and_slide() to move
- Check is_on_floor() for jumping
- Handle input for direction

**tscn Template:**
```ini
[gd_scene load_steps=3 format=3]

[ext_resource type="Script" path="res://player.gd" id="1"]
[ext_resource type="Mesh" path="res://models/player.tres" id="2"]

[node name="Player" type="CharacterBody3D"]
script = ExtResource("1")

[node name="Mesh" parent="." type="MeshInstance3D"]
mesh = ExtResource("2")

[node name="Collision" parent="." type="CollisionShape3D"]
```

**Related Nodes:**
- RigidBody3D: For physics-driven movement
- StaticBody3D: For obstacles
- Area3D: For detection
- CollisionShape3D: Required collision

---

### StaticBody3D

**Type:** 3D Physics
**Extends:** PhysicsBody3D
**Purpose:** Immovable 3D physics body. Cannot move, but blocks other bodies.

**Key Properties:**
- (No unique properties - completely static)

**Optimal Use Cases:**
- Walls and obstacles
- Level geometry
- Terrain
- Platforms
- Non-moving architecture

**Common Patterns:**
- Combine with MeshInstance3D for visuals
- Combine with CollisionShape3D for collision
- Use for level building

**tscn Template:**
```ini
[gd_scene load_steps=2 format=3]

[ext_resource type="Mesh" path="res://models/wall.tres" id="1"]

[node name="Wall" type="StaticBody3D"]

[node name="Mesh" parent="." type="MeshInstance3D"]
mesh = ExtResource("1")

[node name="Collision" parent="." type="CollisionShape3D"]
```

**Related Nodes:**
- RigidBody3D: For movable objects
- CharacterBody3D: For player control
- Area3D: For detection
- CollisionShape3D: Required collision

---

### Area3D

**Type:** 3D Physics (Detection)
**Extends:** PhysicsBody3D
**Purpose:** Non-solid 3D detection volume. Detects overlaps without collision.

**Key Properties:**
- `monitoring` (bool): Can detect bodies
- `monitorable` (bool): Can be detected
- `collision_layer` (int): Layer assignment
- `collision_mask` (int): Detection mask

**Optimal Use Cases:**
- Damage zones
- Pickup areas
- Trigger zones
- AI detection
- Sensor areas

**Common Patterns:**
- Connect signals: body_entered, body_exited
- Check overlapping_bodies
- Use for range detection

**tscn Template:**
```ini
[gd_scene format=3]

[node name="DamageZone" type="Area3D"]

[node name="Collision" parent="." type="CollisionShape3D"]
```

**Related Nodes:**
- RigidBody3D: Solid physics bodies
- CharacterBody3D: Player bodies
- StaticBody3D: Static obstacles
- CollisionShape3D: Required collision

---

### CollisionShape3D

**Type:** 3D Physics (Helper)
**Extends:** Node3D
**Purpose:** Defines 3D collision shape for physics bodies. Required for all 3D physics.

**Key Properties:**
- `shape` (Shape3D): Collision shape type
- `disabled` (bool): Enable/disable collision

**Optimal Use Cases:**
- Required for all 3D physics bodies
- Collision boundaries
- Hit boxes
- Trigger shapes

**Common Patterns:**
- Child of physics bodies
- Use predefined shapes (BoxShape3D, SphereShape3D, CapsuleShape3D)
- Match visual mesh shape

**tscn Template:**
```ini
[gd_scene format=3]

[node name="Body" type="RigidBody3D"]

[node name="Collision" parent="." type="CollisionShape3D"]
shape = BoxShape3D()
scale = Vector3(1, 2, 1)
```

**Related Nodes:**
- RigidBody3D: Physics body parent
- CharacterBody3D: Character body parent
- StaticBody3D: Static body parent
- Area3D: Detection parent

---

## 3D Navigation Nodes

### NavigationRegion3D

**Type:** 3D Navigation
**Extends:** Node3D
**Purpose:** Defines navigable 3D space for pathfinding. Contains NavigationMesh.

**Key Properties:**
- `navigation_mesh` (NavigationMesh): Walkable area in 3D
- `navigation_layers` (int): Layer bitmask

**Optimal Use Cases:**
- 3D level pathfinding
- Large 3D environments
- 3D AI navigation

**Common Patterns:**
- Bake mesh from level geometry
- Combine with NavigationAgent3D

**tscn Template:**
```ini
[gd_scene load_steps=2 format=3]

[ext_resource type="NavigationMesh" path="res://nav_mesh.tres" id="1"]

[node name="NavRegion3D" type="NavigationRegion3D"]
navigation_mesh = ExtResource("1")
```

**Related Nodes:**
- NavigationAgent3D: For entity movement
- NavigationLink3D: For path connections

---

### NavigationAgent3D

**Type:** 3D Navigation
**Extends:** Node3D
**Purpose:** 3D pathfinding and movement for AI.

**Key Properties:**
- `target_position` (Vector3): Destination
- `path_desired_distance` (float): Goal accuracy
- `max_speed` (float): Movement speed

**Optimal Use Cases:**
- 3D enemy AI movement
- NPC pathfinding
- 3D autonomous movement

**Common Patterns:**
- Set target_position for movement
- Check target_reached signal

**tscn Template:**
```ini
[gd_scene format=3]

[node name="Enemy" type="CharacterBody3D"]

[node name="NavAgent" parent="." type="NavigationAgent3D"]
target_position = Vector3(0, 0, 10)
```

**Related Nodes:**
- NavigationRegion3D: Navigation mesh source
- CharacterBody3D: Body to move
- NavigationLink3D: Path connections

---

## 3D Lighting Nodes

### DirectionalLight3D

**Type:** 3D Lighting
**Extends:** Light3D
**Purpose:** Directional light like sunlight. Affects entire scene equally.

**Key Properties:**
- `energy` (float): Light brightness
- `color` (Color): Light color
- `shadow_enabled` (bool): Cast shadows
- `shadow_blur` (float): Shadow softness

**Optimal Use Cases:**
- Sun lighting
- Moon lighting
- Global ambient light
- Main light source

**Common Patterns:**
- Rotate for time-of-day
- Main scene light
- Animate for day/night

**tscn Template:**
```ini
[gd_scene format=3]

[node name="Sun" type="DirectionalLight3D"]
rotation = Vector3(-0.3, 0, 0)
energy = 1.0
shadow_enabled = true
```

**Related Nodes:**
- OmniLight3D: Localized light
- SpotLight3D: Cone light

---

### OmniLight3D

**Type:** 3D Lighting
**Extends:** Light3D
**Purpose:** Point light in 3D space. Emits light from a position in all directions.

**Key Properties:**
- `energy` (float): Brightness
- `color` (Color): Light color
- `omni_range` (float): Light distance
- `omni_attenuation` (float): Light falloff
- `shadow_enabled` (bool): Cast shadows

**Optimal Use Cases:**
- Lamps, lanterns, torches
- Indoor lighting
- Magical lights
- Explosions
- Dynamic light effects

**Common Patterns:**
- Attach to moving objects
- Animate for flickering
- Combine with shadows

**tscn Template:**
```ini
[gd_scene format=3]

[node name="Lantern" type="OmniLight3D"]
energy = 2.0
color = Color(1, 0.8, 0, 1)
omni_range = 10.0
shadow_enabled = true
```

**Related Nodes:**
- DirectionalLight3D: Sun-like light
- SpotLight3D: Cone light

---

### SpotLight3D

**Type:** 3D Lighting
**Extends:** Light3D
**Purpose:** Cone-shaped light. Emits light in a cone direction.

**Key Properties:**
- `energy` (float): Brightness
- `color` (Color): Light color
- `spot_range` (float): Light distance
- `spot_angle` (float): Cone angle
- `shadow_enabled` (bool): Cast shadows

**Optimal Use Cases:**
- Spotlights
- Flashlights
- Cone lights
- Theater lighting
- Directional point lights

**Common Patterns:**
- Adjust angle for focus
- Rotate for direction
- Dynamic spotlights

**tscn Template:**
```ini
[gd_scene format=3]

[node name="Spotlight" type="SpotLight3D"]
energy = 3.0
spot_range = 20.0
spot_angle = 45.0
shadow_enabled = true
```

**Related Nodes:**
- OmniLight3D: Omnidirectional point light
- DirectionalLight3D: Sun-like light

---

## Audio Nodes

### AudioStreamPlayer

**Type:** Audio
**Extends:** Node
**Purpose:** Plays audio without spatial positioning. Global audio playback.

**Key Properties:**
- `stream` (AudioStream): Audio file to play
- `volume_db` (float): Volume in decibels
- `playing` (bool): Is audio playing
- `bus` (String): Audio bus name
- `max_polyphony` (int): Max simultaneous playback

**Optimal Use Cases:**
- Background music
- UI sounds
- Global sound effects
- Game audio management
- Non-positional audio

**Common Patterns:**
- Play music: `$AudioStreamPlayer.play()`
- Stop audio: `$AudioStreamPlayer.stop()`
- Fade volume: Use Tween
- Connect finished signal

**tscn Template:**
```ini
[gd_scene load_steps=2 format=3]

[ext_resource type="AudioStream" path="res://audio/music.ogg" id="1"]

[node name="MusicPlayer" type="AudioStreamPlayer"]
stream = ExtResource("1")
volume_db = 0.0
bus = "Music"
```

**Related Nodes:**
- AudioStreamPlayer2D: 2D positional audio
- AudioStreamPlayer3D: 3D positional audio

---

### AudioStreamPlayer2D

**Type:** Audio
**Extends:** Node2D
**Purpose:** Plays audio with 2D spatial positioning. Volume and pan based on distance.

**Key Properties:**
- `stream` (AudioStream): Audio to play
- `volume_db` (float): Base volume
- `max_distance` (float): Maximum audible distance
- `bus` (String): Audio bus
- `attenuation` (float): Distance attenuation curve

**Optimal Use Cases:**
- 2D game ambient sounds
- 2D spatial effects
- Positional sound effects
- Character voice from position
- Environmental audio

**Common Patterns:**
- Attach to moving entities
- Volume based on distance
- Pan based on position

**tscn Template:**
```ini
[gd_scene load_steps=2 format=3]

[ext_resource type="AudioStream" path="res://audio/footstep.ogg" id="1"]

[node name="SoundEffect" type="AudioStreamPlayer2D"]
stream = ExtResource("1")
max_distance = 200.0
bus = "SFX"
```

**Related Nodes:**
- AudioStreamPlayer: Non-spatial audio
- AudioStreamPlayer3D: 3D spatial audio

---

### AudioStreamPlayer3D

**Type:** Audio
**Extends:** Node3D
**Purpose:** Plays audio with 3D spatial positioning. Full 3D surround audio.

**Key Properties:**
- `stream` (AudioStream): Audio to play
- `volume_db` (float): Base volume
- `max_distance` (float): Maximum audible distance
- `unit_size` (float): Reference distance
- `doppler_tracking` (enum): Doppler effect
- `bus` (String): Audio bus

**Optimal Use Cases:**
- 3D game sound effects
- 3D positional audio
- 3D ambient sounds
- Character voice from location
- Environmental 3D audio
- Immersive 3D soundscapes

**Common Patterns:**
- Attach to 3D entities
- Full 3D positioning
- Surround sound

**tscn Template:**
```ini
[gd_scene load_steps=2 format=3]

[ext_resource type="AudioStream" path="res://audio/explosion.ogg" id="1"]

[node name="Explosion" type="AudioStreamPlayer3D"]
stream = ExtResource("1")
max_distance = 100.0
unit_size = 1.0
bus = "SFX"
```

**Related Nodes:**
- AudioStreamPlayer: Non-spatial audio
- AudioStreamPlayer2D: 2D positional audio

---

## UI/Control Nodes

### Control

**Type:** UI Base
**Extends:** CanvasItem
**Purpose:** Base class for all UI elements. Provides positioning, sizing, anchors, and input handling.

**Key Properties:**
- `anchor_left` / `anchor_right` / `anchor_top` / `anchor_bottom` (float): Anchor positions
- `offset_left` / `offset_right` / `offset_top` / `offset_bottom` (float): Offset from anchors
- `size` (Vector2): Control size
- `pivot_offset` (Vector2): Rotation/scale center
- `mouse_filter` (enum): Input interaction mode
- `focus_mode` (enum): Keyboard focus handling

**Optimal Use Cases:**
- Base for custom UI elements
- Non-container UI layouts
- Custom input handling
- UI state management

**Common Patterns:**
- Inherit from Control for custom UI
- Implement _gui_input for input
- Use anchors for responsive layout

**tscn Template:**
```ini
[gd_scene format=3]

[node name="CustomUI" type="Control"]
anchor_left = 0.0
anchor_top = 0.0
anchor_right = 1.0
anchor_bottom = 1.0
```

**Related Nodes:**
- Container: For automatic layout
- Label: For text display
- Button: For buttons

---

### Label

**Type:** UI Text
**Extends:** Control
**Purpose:** Displays text. Simple text rendering for labels, scores, etc.

**Key Properties:**
- `text` (String): Text content
- `text_overrun_behavior` (enum): How to handle overflow
- `custom_minimum_size` (Vector2): Minimum size
- `label_settings` (LabelSettings): Text formatting (font, color, size)
- `horizontal_alignment` (enum): Text alignment

**Optimal Use Cases:**
- Score display
- HUD text
- Labels for UI elements
- Player names
- Simple text output

**Common Patterns:**
- Update text dynamically
- Use custom fonts
- Align text for UI

**tscn Template:**
```ini
[gd_scene format=3]

[node name="ScoreLabel" type="Label"]
text = "Score: 0"
custom_minimum_size = Vector2(100, 30)
```

**Related Nodes:**
- RichTextLabel: For formatted text
- LineEdit: For text input
- Button: For button text

---

### Button

**Type:** UI Input
**Extends:** Control
**Purpose:** Interactive button for user input. Responds to click/press actions.

**Key Properties:**
- `text` (String): Button label
- `pressed` (bool): Is button pressed
- `toggle_mode` (bool): Toggle on/off
- `button_pressed` (bool): Toggle state
- `action_mode` (enum): Click or release trigger
- `disabled` (bool): Disable button

**Optimal Use Cases:**
- UI buttons
- Menu items
- Interactive controls
- Action triggers
- Dialog choices

**Common Patterns:**
- Connect pressed signal
- Use toggle mode for on/off buttons
- Disable for invalid actions

**tscn Template:**
```ini
[gd_scene format=3]

[node name="StartButton" type="Button"]
text = "Start Game"
size_flags_horizontal = 3
size_flags_vertical = 3
```

**Related Nodes:**
- TextureButton: For image buttons
- OptionButton: For dropdown menu
- CheckBox: For toggle checkbox

---

### CheckBox / CheckButton

**Type:** UI Toggle
**Extends:** Button
**Purpose:** Toggleable checkbox or button for boolean options.

**Key Properties:**
- `button_pressed` (bool): Is checked
- `text` (String): Label text
- `toggle_mode` (bool): Always true for toggles

**Optimal Use Cases:**
- Settings checkboxes
- Boolean options
- Feature toggles
- Enable/disable options

**Common Patterns:**
- Connect toggled signal
- Check button_pressed for state

**tscn Template:**
```ini
[gd_scene format=3]

[node name="FullscreenCheckbox" type="CheckBox"]
text = "Fullscreen"
button_pressed = false
```

**Related Nodes:**
- Button: For non-toggle buttons
- OptionButton: For multiple options

---

### LineEdit

**Type:** UI Input
**Extends:** Control
**Purpose:** Single-line text input field. For player name, search, etc.

**Key Properties:**
- `text` (String): Current text content
- `placeholder_text` (String): Hint text
- `max_length` (int): Maximum characters
- `secret` (bool): Hide text (password)
- `editable` (bool): Allow editing

**Optimal Use Cases:**
- Player name input
- Search boxes
- Password fields
- Form inputs
- Chat input

**Common Patterns:**
- Connect text_changed signal
- Use placeholder for hints
- Validate input in script

**tscn Template:**
```ini
[gd_scene format=3]

[node name="NameInput" type="LineEdit"]
placeholder_text = "Enter your name"
max_length = 20
custom_minimum_size = Vector2(200, 30)
```

**Related Nodes:**
- TextEdit: For multi-line text
- RichTextLabel: For formatted text display
- Label: For read-only text

---

### TextEdit

**Type:** UI Input
**Extends:** Control
**Purpose:** Multi-line text editor. For longer text, code, chat, etc.

**Key Properties:**
- `text` (String): All text content
- `line_count` (int): Number of lines
- `editable` (bool): Allow editing
- `syntax_highlighter` (SyntaxHighlighter): Code syntax highlighting

**Optimal Use Cases:**
- Chat boxes
- Longer text input
- Script editing
- Code display
- Multi-line comments

**Common Patterns:**
- Connect text_changed signal
- Syntax highlighting for code
- Scroll for long text

**tscn Template:**
```ini
[gd_scene format=3]

[node name="ChatBox" type="TextEdit"]
editable = true
scroll_fit_content_height = true
custom_minimum_size = Vector2(400, 300)
```

**Related Nodes:**
- LineEdit: For single-line input
- RichTextLabel: For formatted text
- Label: For simple text display

---

### ProgressBar

**Type:** UI Display
**Extends:** Range (Control)
**Purpose:** Visual progress indicator (health, loading, etc.).

**Key Properties:**
- `value` (float): Current progress (0-100)
- `min_value` (float): Minimum value
- `max_value` (float): Maximum value
- `step` (float): Step size
- `show_percentage` (bool): Show % text

**Optimal Use Cases:**
- Health bars
- Loading bars
- Experience bars
- Resource indicators
- Progress displays

**Common Patterns:**
- Update value: `$ProgressBar.value = health`
- Animate with Tween
- Visual feedback for states

**tscn Template:**
```ini
[gd_scene format=3]

[node name="HealthBar" type="ProgressBar"]
min_value = 0.0
max_value = 100.0
value = 100.0
show_percentage = true
custom_minimum_size = Vector2(200, 20)
```

**Related Nodes:**
- Range: Base class for value controls
- HSlider: Interactive slider
- Label: For text display

---

### RichTextLabel

**Type:** UI Text
**Extends:** Control
**Purpose:** Displays formatted text with tags (bold, italics, colors, etc.). Like HTML for text.

**Key Properties:**
- `text` (String): Text with BBCode formatting
- `bbcode_enabled` (bool): Enable BBCode parsing
- `text_overrun_behavior` (enum): Text overflow behavior
- `custom_minimum_size` (Vector2): Minimum size
- `scroll_active` (bool): Enable scrolling

**Optimal Use Cases:**
- Formatted dialogue
- Story text
- Colored/styled text
- Documentation display
- Formatted logs

**Common Patterns:**
- Use BBCode tags: [b]bold[/b], [color=red]red[/color]
- Connect to signals for style changes
- Scroll for long content

**tscn Template:**
```ini
[gd_scene format=3]

[node name="DialogueText" type="RichTextLabel"]
bbcode_enabled = true
text = "[b]NPC:[/b] Hello, traveler!"
scroll_active = true
custom_minimum_size = Vector2(400, 300)
```

**Related Nodes:**
- Label: For simple text
- TextEdit: For editable text
- DialogueManager: For dialogue systems

---

## Container Nodes

### HBoxContainer

**Type:** UI Container
**Extends:** Container
**Purpose:** Arranges children horizontally (left to right). Automatically sizes and positions children.

**Key Properties:**
- `separation` (int): Space between children
- `alignment` (enum): How children align

**Optimal Use Cases:**
- Horizontal button rows
- Side-by-side layouts
- Toolbar layouts
- Menu options horizontally
- Horizontal UI grouping

**Common Patterns:**
- Nest containers for complex layouts
- Size flags for flexible layout
- Add/remove children dynamically

**tscn Template:**
```ini
[gd_scene format=3]

[node name="ButtonRow" type="HBoxContainer"]
separation = 10

[node name="Button1" parent="." type="Button"]
text = "Button 1"

[node name="Button2" parent="." type="Button"]
text = "Button 2"
```

**Related Nodes:**
- VBoxContainer: Vertical arrangement
- GridContainer: Grid arrangement
- Container: Base class

---

### VBoxContainer

**Type:** UI Container
**Extends:** Container
**Purpose:** Arranges children vertically (top to bottom). Automatically sizes and positions children.

**Key Properties:**
- `separation` (int): Space between children
- `alignment` (enum): How children align

**Optimal Use Cases:**
- Vertical menu lists
- Settings panels
- Stacked UI elements
- Form layouts
- Vertical UI grouping

**Common Patterns:**
- Most common container for menus
- Nest for complex layouts
- Size flags for flexible sizing

**tscn Template:**
```ini
[gd_scene format=3]

[node name="SettingsPanel" type="VBoxContainer"]
separation = 5

[node name="Label" parent="." type="Label"]
text = "Settings"

[node name="VolumeSlider" parent="." type="HSlider"]

[node name="Button" parent="." type="Button"]
text = "Save"
```

**Related Nodes:**
- HBoxContainer: Horizontal arrangement
- GridContainer: Grid arrangement
- Container: Base class

---

### GridContainer

**Type:** UI Container
**Extends:** Container
**Purpose:** Arranges children in a grid (rows × columns). Automatic alignment in cells.

**Key Properties:**
- `columns` (int): Number of columns
- `vertical_alignment` (enum): Vertical align in cells
- `horizontal_alignment` (enum): Horizontal align

**Optimal Use Cases:**
- Item grids (inventory)
- Game menus with 2+ columns
- Grid of buttons
- Settings with multiple columns
- Tile-based UI layouts

**Common Patterns:**
- Set columns for desired layout
- Consistent cell sizing
- Add items dynamically

**tscn Template:**
```ini
[gd_scene format=3]

[node name="ItemGrid" type="GridContainer"]
columns = 4

[node name="Item1" parent="." type="Button"]
text = "Item 1"

[node name="Item2" parent="." type="Button"]
text = "Item 2"
```

**Related Nodes:**
- HBoxContainer: Single row
- VBoxContainer: Single column
- Container: Base class

---

### TabContainer

**Type:** UI Container
**Extends:** Container
**Purpose:** Creates tabbed interface. Each child becomes a tab, named by child's name.

**Key Properties:**
- `current_tab` (int): Currently active tab
- `tab_changed` (signal): Emitted when tab changes
- Tabs use child node names as labels

**Optimal Use Cases:**
- Options menus with multiple sections
- Settings with tabs
- Multi-page dialogs
- Documentation viewers
- Tabbed panels

**Common Patterns:**
- Child names become tab labels
- Connect tab_changed signal
- Switch tabs programmatically

**tscn Template:**
```ini
[gd_scene format=3]

[node name="TabContainer" type="TabContainer"]

[node name="General" parent="." type="Control"]

[node name="Label" parent="General" type="Label"]
text = "General Settings"

[node name="Advanced" parent=".." type="Control"]

[node name="Label" parent="Advanced" type="Label"]
text = "Advanced Settings"
```

**Related Nodes:**
- HBoxContainer: No tabs
- VBoxContainer: No tabs
- Panel: Simple background container

---

### MarginContainer

**Type:** UI Container
**Extends:** Container
**Purpose:** Adds margin (padding) around children. Space between edge and content.

**Key Properties:**
- `margin_left/right/top/bottom` (int): Margin sizes

**Optimal Use Cases:**
- Add padding around content
- Inset children from edges
- Create spacing in layouts
- Consistent margins

**Common Patterns:**
- Wrap other containers
- Consistent UI spacing

**tscn Template:**
```ini
[gd_scene format=3]

[node name="PaddedContainer" type="MarginContainer"]
margin_left = 10
margin_right = 10
margin_top = 10
margin_bottom = 10

[node name="Content" parent="." type="VBoxContainer"]
```

**Related Nodes:**
- Container: Base class
- PanelContainer: Container with background
- CenterContainer: Centered children

---

### ScrollContainer

**Type:** UI Container
**Extends:** Container
**Purpose:** Provides scrollbars for content that exceeds visible area. Allows scrolling large content.

**Key Properties:**
- `scroll_horizontal_enabled` (bool): Enable horizontal scroll
- `scroll_vertical_enabled` (bool): Enable vertical scroll
- `h_scroll` (int): Horizontal scroll position
- `v_scroll` (int): Vertical scroll position

**Optimal Use Cases:**
- Long lists
- Large content areas
- Chat windows
- Documentation viewers
- Overflow content

**Common Patterns:**
- Single child (put container in it)
- Enable only needed scrollbars
- Set custom_minimum_size

**tscn Template:**
```ini
[gd_scene format=3]

[node name="ScrollView" type="ScrollContainer"]
custom_minimum_size = Vector2(400, 300)

[node name="VBoxContainer" parent="." type="VBoxContainer"]
size_flags_horizontal = 3

[node name="Item1" parent="VBoxContainer" type="Label"]
text = "Item 1"
```

**Related Nodes:**
- Container: Base container
- VBoxContainer: For content
- ItemList: Simpler list with scrolling

---

## Utility & Timing Nodes

### Timer

**Type:** Utility (Timing)
**Extends:** Node
**Purpose:** Executes code after a delay or repeatedly. Simple built-in timing mechanism.

**Key Properties:**
- `wait_time` (float): Seconds before timeout
- `one_shot` (bool): Single timeout vs repeated
- `autostart` (bool): Start automatically
- `paused` (bool): Pause timer
- `time_left` (float): Seconds remaining

**Signals:**
- `timeout`: Emitted when timer completes

**Optimal Use Cases:**
- Delays before actions
- Repeating actions
- Cooldowns
- Timers for effects
- Game logic timing

**Common Patterns:**
- Call start() to begin
- Call stop() to halt
- Connect timeout signal
- Access time_left for UI

**tscn Template:**
```ini
[gd_scene format=3]

[node name="AttackCooldown" type="Timer"]
wait_time = 0.5
one_shot = true
```

**Related Nodes:**
- Tween: For property animation over time
- Callable.call_deferred: Single delayed call

---

### Tween

**Type:** Utility (Animation)
**Extends:** RefCounted
**Purpose:** Animates properties over time. Tweens values smoothly with easing functions.

**Key Methods:**
- `tween_property(object, property, final_value, duration)`
- `tween_method(method, from, to, duration)`
- `tween_interval(delay)`
- `tween_callback(callable)`

**Optimal Use Cases:**
- Smooth camera movements
- UI animations
- Property interpolation
- Chained animations
- Eased transitions

**Common Patterns:**
- Chain multiple tweens
- Use easing for polish
- Animate multiple properties
- Call callbacks between steps

**Script Example:**
```gdscript
var tween = create_tween()
tween.tween_property($Label, "position", Vector2(100, 100), 1.0)
tween.tween_callback(_on_animation_complete)
```

**Related Nodes:**
- Timer: For discrete timing
- AnimationPlayer: For complex animations

---

### HTTPRequest

**Type:** Utility (Network)
**Extends:** Node
**Purpose:** Makes HTTP requests to web servers. Downloads data, APIs, web content.

**Key Properties:**
- `timeout` (float): Request timeout in seconds

**Key Methods:**
- `request(url, custom_headers, method, request_body)`

**Signals:**
- `request_completed(result, response_code, headers, body)`

**Optimal Use Cases:**
- API calls
- Cloud data loading
- Web content fetching
- Server communication
- Leaderboard retrieval
- Analytics sending

**Common Patterns:**
- Connect request_completed signal
- Parse JSON responses
- Handle errors gracefully

**Script Example:**
```gdscript
var http = HTTPRequest.new()
add_child(http)
http.request_completed.connect(_on_request_complete)
http.request("https://api.example.com/data")
```

**Related Nodes:**
- Node: Parent class
- JSON: For parsing responses

---

### ResourcePreloader

**Type:** Utility (Resource Loading)
**Extends:** Node
**Purpose:** Preloads and caches resources for instant access. Reduces loading times.

**Key Methods:**
- `get_resource(name: String) -> Resource`
- `get_resource_list() -> PackedStringArray`

**Optimal Use Cases:**
- Preload frequently used assets
- Cache textures/sounds
- Improve load times
- Avoid runtime loading delays
- Asset pooling

**Common Patterns:**
- Add resources in editor
- Access with get_resource()
- Pre-cache common assets

**tscn Template:**
```ini
[gd_scene format=3]

[node name="ResourcePreloader" type="ResourcePreloader"]
resources = {}
```

**Related Nodes:**
- Node: Parent class
- Resource: Base for preloadable assets

---

## Viewport & Camera Nodes

### Viewport

**Type:** View
**Extends:** Node
**Purpose:** Renders a 3D or 2D scene to a texture. Used for mirrors, split-screen, custom rendering.

**Key Properties:**
- `size` (Vector2i): Viewport render size
- `world_2d` (World2D): 2D world
- `world_3d` (World3D): 3D world
- `transparent_bg` (bool): Transparent background

**Optimal Use Cases:**
- Mirror effects
- Picture-in-picture
- Split-screen gameplay
- Custom rendering
- Minimap rendering

**Common Patterns:**
- Use SubViewport for UI
- Render to texture for effects

**tscn Template:**
```ini
[gd_scene format=3]

[node name="Viewport" type="Viewport"]
size = Vector2i(800, 600)
transparent_bg = false
```

**Related Nodes:**
- SubViewport: In-scene viewport
- Camera2D/Camera3D: Define viewpoint

---

### SubViewport

**Type:** View
**Extends:** Viewport
**Purpose:** Viewport that renders as a Control node. In-scene rendering texture.

**Key Properties:**
- `size` (Vector2i): Render size
- `render_target_clear_mode` (enum): When to clear
- `render_target_update_mode` (enum): Update frequency

**Optimal Use Cases:**
- Game windows in UI
- Embedded scene preview
- Minimap in Control
- Screen-space effects
- Picture-in-picture UI

**Common Patterns:**
- Place in UI hierarchy
- Use TextureRect to display
- Render child scenes

**tscn Template:**
```ini
[gd_scene format=3]

[node name="MiniMapViewport" type="SubViewport"]
size = Vector2i(200, 200)

[node name="Camera2D" parent="." type="Camera2D"]
```

**Related Nodes:**
- Viewport: Full-screen viewport
- TextureRect: Display viewport texture

---

### ColorRect

**Type:** UI Visual
**Extends:** Control
**Purpose:** Simple colored rectangle. Used for solid color UI backgrounds and effects.

**Key Properties:**
- `color` (Color): Rectangle color
- `size` (Vector2): Rectangle size

**Optimal Use Cases:**
- UI backgrounds
- Color overlays (pauses, transitions)
- Visual separators
- Solid color regions
- Fade/transition effects

**Common Patterns:**
- Full-screen overlays
- Animate color for effects
- Background layers

**tscn Template:**
```ini
[gd_scene format=3]

[node name="Background" type="ColorRect"]
anchor_right = 1.0
anchor_bottom = 1.0
color = Color(0.1, 0.1, 0.1, 1)
```

**Related Nodes:**
- Control: Base class
- PanelContainer: Container with background

---

### TextureRect

**Type:** UI Visual
**Extends:** Control
**Purpose:** Displays a texture/image in UI. For UI backgrounds, icons, previews.

**Key Properties:**
- `texture` (Texture2D): Image to display
- `expand_mode` (enum): How to scale texture
- `stretch_mode` (enum): Stretch behavior

**Optimal Use Cases:**
- UI icons
- Background images
- Backgrounds in menus
- Image previews
- Viewport display

**Common Patterns:**
- Set texture for image
- Use expand for scaling
- Parent for content

**tscn Template:**
```ini
[gd_scene load_steps=2 format=3]

[ext_resource type="Texture2D" path="res://icon.png" id="1"]

[node name="IconRect" type="TextureRect"]
texture = ExtResource("1")
expand_mode = 1
anchor_right = 1.0
anchor_bottom = 1.0
```

**Related Nodes:**
- Sprite2D: For 2D game sprites
- Control: Base class
- TextureButton: Button with texture

---

### CanvasLayer

**Type:** View Management
**Extends:** Node
**Purpose:** Renders all children to a specific layer on the 2D canvas. Controls drawing order.

**Key Properties:**
- `layer` (int): Canvas layer number (higher renders on top)
- `offset` (Vector2): Layer position offset
- `rotation` (float): Layer rotation
- `scale` (Vector2): Layer scale

**Optimal Use Cases:**
- Separate rendering layers
- UI on top of gameplay
- Parallax backgrounds
- HUD separation
- Light/shadow layers

**Common Patterns:**
- HUD as CanvasLayer on top
- Parallax backgrounds
- Separate visual layers

**tscn Template:**
```ini
[gd_scene format=3]

[node name="HUDLayer" type="CanvasLayer"]
layer = 10
offset = Vector2(0, 0)

[node name="ScoreLabel" parent="." type="Label"]
text = "Score: 0"
```

**Related Nodes:**
- Node2D: Parent for children
- WorldEnvironment: Global environment

---

### WorldEnvironment

**Type:** Environment (3D)
**Extends:** Node3D
**Purpose:** Sets global 3D environment properties (lighting, fog, ambient, effects).

**Key Properties:**
- `environment` (Environment): Global environment settings
- `camera_attributes` (CameraAttributes): Camera-specific settings

**Optimal Use Cases:**
- Global 3D lighting
- Ambient light
- Fog effects
- Background/sky
- Global post-processing

**Common Patterns:**
- Single per 3D scene
- Set ambient light
- Configure fog
- Add sky

**tscn Template:**
```ini
[gd_scene load_steps=2 format=3]

[ext_resource type="Environment" path="res://environment.tres" id="1"]

[node name="WorldEnvironment" type="WorldEnvironment"]
environment = ExtResource("1")
```

**Related Nodes:**
- Sky: For skybox
- DirectionalLight3D: Main light

---

## Additional Information

### Size Flags

Control nodes support size flags for responsive layout:

- `SIZE_FILL`: Expand to fill available space
- `SIZE_SHRINK_CENTER`: Shrink and center
- `SIZE_EXPAND_FILL`: Expand and fill
- `SIZE_IGNORE`: Don't consider in layout

Use `size_flags_horizontal` and `size_flags_vertical` on UI elements in containers.

### Anchors and Offsets

Control nodes use anchors (0-1) to position relative to parent:

- `anchor_left`: Left edge position (0 = left parent edge, 1 = right)
- `anchor_right`: Right edge position
- `offset_left/right`: Pixel offset from anchor
- `margin_left/right`: Old-style positioning (offset from edges)

### Collision Layers and Masks

Physics bodies use layers and masks for selective collision:

- `collision_layer`: Which layers this body is on (bit flags)
- `collision_mask`: Which layers this body detects (bit flags)

Bodies only collide when their layer is in the other body's mask.

---

## Quick Node Selection Reference

### "I need to display a static image"
→ **Sprite2D**

### "I need animated character"
→ **AnimatedSprite2D** + **CharacterBody2D**

### "I need text on screen"
→ **Label** (simple) or **RichTextLabel** (formatted)

### "I need a button"
→ **Button** or **TextureButton**

### "I need a click detection area"
→ **Area2D** with **CollisionShape2D**

### "I need physics-based movement"
→ **RigidBody2D** + **CollisionShape2D**

### "I need player character movement"
→ **CharacterBody2D** + **CollisionShape2D**

### "I need a solid obstacle"
→ **StaticBody2D** + **CollisionShape2D**

### "I need enemy AI navigation"
→ **NavigationAgent2D** + **CharacterBody2D**

### "I need to play music"
→ **AudioStreamPlayer** (non-spatial)

### "I need positioned sound"
→ **AudioStreamPlayer2D** (2D) or **AudioStreamPlayer3D** (3D)

### "I need a timer/delay"
→ **Timer**

### "I need smooth animation"
→ **Tween** (simple) or **AnimationPlayer** (complex)

### "I need a menu layout"
→ **VBoxContainer** or **GridContainer**

### "I need a horizontal layout"
→ **HBoxContainer**

### "I need multiple pages/tabs"
→ **TabContainer**

### "I need a loading/health bar"
→ **ProgressBar**

### "I need text input"
→ **LineEdit** (single-line) or **TextEdit** (multi-line)

### "I need scrollable content"
→ **ScrollContainer**

---

## Summary

This reference covers 80+ essential Godot 4.x nodes organized by category. Use the decision trees in `node-selection-guide.md` to intelligently select the optimal node for your refactoring operations.

**Key Principles:**
- Each node has a specific purpose - don't use unnecessarily
- Physics bodies (RigidBody2D, CharacterBody2D, etc.) require CollisionShape2D
- Container nodes automatically position children - use for responsive UI
- Keep node hierarchy clean and intentional
- Refer to this guide when analyzing code for node creation

For complete API details and examples, visit the [official Godot documentation](https://docs.godotengine.org/en/stable/index.html).
