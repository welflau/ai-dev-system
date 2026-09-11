"""
PIE Screenshot Capturer - UE5 Python Script
Auto-capture screenshots during PIE runtime using tick callbacks, with multi-angle support

Usage:
    import pie_screenshot_capturer

    # Start capturer and auto-start PIE (default: screenshot every 1 second, multi-angle mode)
    capturer = pie_screenshot_capturer.start(auto_start_pie=True)

    # Single angle mode
    capturer = pie_screenshot_capturer.start(
        auto_start_pie=True,
        multi_angle=False
    )

    # Custom multi-angle parameters
    capturer = pie_screenshot_capturer.start(
        output_dir="C:/Screenshots",
        interval_seconds=2.0,
        resolution=(1920, 1080),
        auto_start_pie=True,
        multi_angle=True,
        camera_distance=400,
        target_height=90  # Target height offset
    )

    # Manually start/stop PIE
    pie_screenshot_capturer.start_pie()
    pie_screenshot_capturer.stop_pie()

    # Stop capturer
    pie_screenshot_capturer.stop()
"""

import unreal
import os
from datetime import datetime


class PIEScreenshotCapturer:
    """PIE screenshot capturer using tick callbacks, with multi-angle support"""

    # Camera angle definitions
    CAMERA_ANGLES = [
        {
            "name": "front",
            "description": "front view",
            "offset_func": lambda d, h: (0, d, h),
            "rotation": lambda: unreal.Rotator(roll=0, pitch=0, yaw=180)
        },
        {
            "name": "side",
            "description": "side view",
            "offset_func": lambda d, h: (d, 0, h),
            "rotation": lambda: unreal.Rotator(roll=0, pitch=0, yaw=-90)
        },
        {
            "name": "top",
            "description": "top view",
            "offset_func": lambda d, _h: (0, 0, d),
            "rotation": lambda: unreal.Rotator(roll=0, pitch=-90, yaw=0)
        },
        {
            "name": "perspective",
            "description": "45-degree perspective",
            "offset_func": lambda d, _h: (d * 0.707, d * 0.707, d * 0.707),
            "rotation": lambda: unreal.Rotator(roll=0, pitch=-35, yaw=-135)
        },
    ]

    def __init__(self, output_dir=None, interval_seconds=1.0, resolution=(1920, 1080),
                 multi_angle=True, camera_distance=300, target_height=90):
        """
        Initialize the capturer

        Args:
            output_dir: Screenshot output directory, defaults to project Screenshots directory
            interval_seconds: Screenshot interval in seconds
            resolution: Screenshot resolution (width, height)
            multi_angle: Enable multi-angle capture (4 angles)
            camera_distance: Camera distance from target
            target_height: Target height offset (from ground)
        """
        # Set output directory
        if output_dir is None:
            project_dir = unreal.Paths.project_dir()
            output_dir = os.path.join(project_dir, "Screenshots", "PIE_Captures")

        self.output_dir = output_dir
        self.interval_seconds = interval_seconds
        self.resolution = resolution
        self.multi_angle = multi_angle
        self.camera_distance = camera_distance
        self.target_height = target_height

        # State variables
        self._tick_handle = None
        self._accumulated_time = 0.0
        self._screenshot_count = 0
        self._is_running = False
        self._pending_task = None  # Current screenshot task
        self._was_in_pie = False
        self._camera_actor = None  # Camera for multi-angle capture

        # Multi-angle state machine
        self._current_angle_index = 0  # Current angle index being captured
        self._capture_in_progress = False  # Whether multi-angle capture is in progress
        self._capture_timestamp = ""  # Timestamp for current capture set
        self._capture_base_count = 0  # Base count for current capture set
        self._capture_target = None  # Current capture target location

        # Ensure output directory exists
        if not os.path.exists(self.output_dir):
            os.makedirs(self.output_dir)
            unreal.log(f"[PIE Capturer] Created output directory: {self.output_dir}")

    def start(self):
        """Start the capturer"""
        if self._is_running:
            unreal.log_warning("[PIE Capturer] Already running")
            return

        self._is_running = True
        self._accumulated_time = 0.0
        self._screenshot_count = 0
        self._was_in_pie = False
        self._pending_task = None
        self._current_angle_index = 0
        self._capture_in_progress = False

        # Create camera for multi-angle capture
        if self.multi_angle:
            self._create_camera()

        # Register tick callback
        self._tick_handle = unreal.register_slate_post_tick_callback(self._on_tick)

        mode_str = "Multi-angle (4 views)" if self.multi_angle else "Single view"
        unreal.log(f"[PIE Capturer] Started - Mode: {mode_str}")
        unreal.log(f"[PIE Capturer] Interval: {self.interval_seconds}s, Resolution: {self.resolution}")
        if self.multi_angle:
            unreal.log(f"[PIE Capturer] Camera distance: {self.camera_distance}, Target height: {self.target_height}")
        unreal.log(f"[PIE Capturer] Output: {self.output_dir}")

    def stop(self):
        """Stop the capturer"""
        if not self._is_running:
            unreal.log_warning("[PIE Capturer] Not running")
            return

        self._is_running = False

        # Unregister tick callback
        if self._tick_handle is not None:
            unreal.unregister_slate_post_tick_callback(self._tick_handle)
            self._tick_handle = None

        # Destroy camera
        if self._camera_actor is not None:
            self._camera_actor.destroy_actor()
            self._camera_actor = None

        unreal.log(f"[PIE Capturer] Stopped - Total screenshots: {self._screenshot_count}")

    def _create_camera(self):
        """Create camera actor for multi-angle capture"""
        actor_subsystem = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
        self._camera_actor = actor_subsystem.spawn_actor_from_class(
            unreal.CameraActor,
            unreal.Vector(0, 0, 0),
            transient=True
        )
        if self._camera_actor:
            self._camera_actor.set_actor_label("PIE_Screenshot_Camera")
            unreal.log("[PIE Capturer] Created screenshot camera")
        else:
            unreal.log_error("[PIE Capturer] Failed to create camera actor")

    def _get_target_location(self, pie_world):
        """Get target location for capture (player character position)"""
        # Try to get player character
        player_char = unreal.GameplayStatics.get_player_character(pie_world, 0)
        if player_char:
            loc = player_char.get_actor_location()
            # Add height offset to aim at character center
            return unreal.Vector(loc.x, loc.y, loc.z + self.target_height)

        # If no player character, try to get player pawn
        player_pawn = unreal.GameplayStatics.get_player_pawn(pie_world, 0)
        if player_pawn:
            loc = player_pawn.get_actor_location()
            return unreal.Vector(loc.x, loc.y, loc.z + self.target_height)

        # Default position
        return unreal.Vector(0, 0, self.target_height)

    def _calculate_camera_position(self, target, angle_config):
        """Calculate camera position for specified angle"""
        offset = angle_config["offset_func"](self.camera_distance, self.target_height)
        return unreal.Vector(
            target.x + offset[0],
            target.y + offset[1],
            target.z + offset[2] - self.target_height  # Subtract target_height since it's already added to target
        )

    def _on_tick(self, delta_time):
        """Tick callback function"""
        if not self._is_running:
            return

        # Check for pending screenshot task
        if self._pending_task is not None:
            if self._pending_task.is_task_done():
                self._pending_task = None
                # If multi-angle capture in progress, continue to next angle
                if self._capture_in_progress:
                    self._take_next_angle()
                    return
            else:
                # Task not complete, skip this tick
                return

        # Check PIE state
        pie_worlds = unreal.EditorLevelLibrary.get_pie_worlds(False)
        is_in_pie = len(pie_worlds) > 0

        # Detect PIE state changes
        if is_in_pie and not self._was_in_pie:
            unreal.log("[PIE Capturer] PIE started - beginning capture")
            self._accumulated_time = 0.0
            self._capture_in_progress = False
        elif not is_in_pie and self._was_in_pie:
            unreal.log("[PIE Capturer] PIE ended - pausing capture")
            self._capture_in_progress = False

        self._was_in_pie = is_in_pie

        # If not in PIE, don't capture
        if not is_in_pie:
            return

        # If multi-angle capture in progress, don't accumulate time
        if self._capture_in_progress:
            return

        # Accumulate time
        self._accumulated_time += delta_time

        # Check if screenshot interval reached
        if self._accumulated_time >= self.interval_seconds:
            self._accumulated_time = 0.0
            pie_world = pie_worlds[0]

            if self.multi_angle:
                self._start_multi_angle_capture(pie_world)
            else:
                self._take_single_screenshot()

    def _take_single_screenshot(self):
        """Take single-angle screenshot"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = os.path.join(
            self.output_dir,
            f"PIE_Screenshot_{timestamp}_{self._screenshot_count:04d}.png"
        )

        unreal.AutomationLibrary.finish_loading_before_screenshot()

        self._pending_task = unreal.AutomationLibrary.take_high_res_screenshot(
            res_x=self.resolution[0],
            res_y=self.resolution[1],
            filename=filename,
            camera=None,
            mask_enabled=False,
            capture_hdr=False,
            comparison_tolerance=unreal.ComparisonTolerance.LOW,
            comparison_notes="",
            delay=0.0,
            force_game_view=True
        )

        self._screenshot_count += 1
        unreal.log(f"[PIE Capturer] Screenshot #{self._screenshot_count}: {os.path.basename(filename)}")

    def _start_multi_angle_capture(self, pie_world):
        """Start multi-angle capture sequence"""
        if self._camera_actor is None:
            unreal.log_error("[PIE Capturer] Camera not available for multi-angle capture")
            self._take_single_screenshot()
            return

        # 初始化多角度拍摄状态
        self._capture_in_progress = True
        self._current_angle_index = 0
        self._capture_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self._capture_base_count = self._screenshot_count
        self._capture_target = self._get_target_location(pie_world)

        unreal.log(f"[PIE Capturer] Starting multi-angle capture at target: ({self._capture_target.x:.0f}, {self._capture_target.y:.0f}, {self._capture_target.z:.0f})")

        # Capture first angle
        self._take_current_angle()

    def _take_current_angle(self):
        """Capture current angle"""
        if self._current_angle_index >= len(self.CAMERA_ANGLES):
            # All angles captured
            self._capture_in_progress = False
            self._screenshot_count += 1
            unreal.log(f"[PIE Capturer] Completed set #{self._screenshot_count} (4 angles)")
            return

        angle_config = self.CAMERA_ANGLES[self._current_angle_index]

        # Calculate camera position and rotation
        cam_pos = self._calculate_camera_position(self._capture_target, angle_config)
        cam_rot = angle_config["rotation"]()

        # Move camera
        self._camera_actor.set_actor_location_and_rotation(
            cam_pos, cam_rot, sweep=False, teleport=True
        )

        # Generate filename
        filename = os.path.join(
            self.output_dir,
            f"PIE_Screenshot_{self._capture_timestamp}_{self._capture_base_count:04d}_{angle_config['name']}.png"
        )

        unreal.AutomationLibrary.finish_loading_before_screenshot()

        # Take screenshot
        self._pending_task = unreal.AutomationLibrary.take_high_res_screenshot(
            res_x=self.resolution[0],
            res_y=self.resolution[1],
            filename=filename,
            camera=self._camera_actor,
            mask_enabled=False,
            capture_hdr=False,
            comparison_tolerance=unreal.ComparisonTolerance.LOW,
            comparison_notes="",
            delay=0.0,
            force_game_view=True
        )

        unreal.log(f"[PIE Capturer] Screenshot {angle_config['name']}: {os.path.basename(filename)}")

    def _take_next_angle(self):
        """Capture next angle"""
        self._current_angle_index += 1
        self._take_current_angle()


# Global instance
_capturer_instance = None


def start(output_dir=None, interval_seconds=1.0, resolution=(1920, 1080),
          auto_start_pie=False, multi_angle=True, camera_distance=300, target_height=90):
    """
    Start PIE screenshot capturer

    Args:
        output_dir: Screenshot output directory
        interval_seconds: Screenshot interval in seconds
        resolution: Screenshot resolution (width, height)
        auto_start_pie: Whether to auto-start PIE
        multi_angle: Enable multi-angle capture (4 angles: front, side, top, 45-degree perspective)
        camera_distance: Camera distance from target
        target_height: Target height offset

    Returns:
        PIEScreenshotCapturer instance
    """
    global _capturer_instance

    if _capturer_instance is not None:
        _capturer_instance.stop()

    _capturer_instance = PIEScreenshotCapturer(
        output_dir=output_dir,
        interval_seconds=interval_seconds,
        resolution=resolution,
        multi_angle=multi_angle,
        camera_distance=camera_distance,
        target_height=target_height
    )
    _capturer_instance.start()

    # 自动启动PIE
    if auto_start_pie:
        start_pie()

    return _capturer_instance


def stop():
    """Stop PIE screenshot capturer"""
    global _capturer_instance

    if _capturer_instance is not None:
        _capturer_instance.stop()
        _capturer_instance = None


def get_capturer():
    """Get current capturer instance"""
    return _capturer_instance


def start_pie():
    """Start PIE"""
    subsystem = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
    if subsystem.is_in_play_in_editor():
        unreal.log_warning("[PIE Capturer] PIE is already running")
        return False

    subsystem.editor_request_begin_play()
    unreal.log("[PIE Capturer] PIE start requested")
    return True


def stop_pie():
    """Stop PIE"""
    subsystem = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
    if not subsystem.is_in_play_in_editor():
        unreal.log_warning("[PIE Capturer] PIE is not running")
        return False

    subsystem.editor_request_end_play()
    unreal.log("[PIE Capturer] PIE stop requested")
    return True


def is_pie_running():
    """Check if PIE is running"""
    subsystem = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
    return subsystem.is_in_play_in_editor()


# If running this script directly, start capturer and auto-start PIE (multi-angle mode)
if __name__ == "__main__":
    start(auto_start_pie=True, multi_angle=True)
