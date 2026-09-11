// Copyright (c) 2025 zolnoor. All rights reserved.

#pragma once

#include "CoreMinimal.h"
#include "EditorAction.h"

class AActor;

/**
 * FGetActorsInLevelAction
 * Returns all actors in the current level.
 */
class UEEDITORMCP_API FGetActorsInLevelAction : public FEditorAction
{
public:
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;

protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override { return true; }
	virtual FString GetActionName() const override { return TEXT("get_actors_in_level"); }
	virtual bool RequiresSave() const override { return false; }
};


/**
 * FFindActorsByNameAction
 * Finds actors matching a name pattern.
 */
class UEEDITORMCP_API FFindActorsByNameAction : public FEditorAction
{
public:
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;

protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual FString GetActionName() const override { return TEXT("find_actors_by_name"); }
	virtual bool RequiresSave() const override { return false; }
};


/**
 * FGetRuntimeWidgetsAction
 * Inspects live UserWidget instances in an editor or PIE world.
 */
class UEEDITORMCP_API FGetRuntimeWidgetsAction : public FEditorAction
{
public:
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;

protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual FString GetActionName() const override { return TEXT("get_runtime_widgets"); }
	virtual bool RequiresSave() const override { return false; }
};


/**
 * FSpawnActorAction
 * Spawns a basic actor type in the level.
 */
class UEEDITORMCP_API FSpawnActorAction : public FEditorAction
{
public:
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;

protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual FString GetActionName() const override { return TEXT("spawn_actor"); }

private:
	UClass* ResolveActorClass(const FString& TypeName) const;
};


/**
 * FDeleteActorAction
 * Deletes an actor from the level.
 */
class UEEDITORMCP_API FDeleteActorAction : public FEditorAction
{
public:
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;

protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual FString GetActionName() const override { return TEXT("delete_actor"); }
};


/**
 * FSetActorTransformAction
 * Sets the transform (location/rotation/scale) of an actor.
 */
class UEEDITORMCP_API FSetActorTransformAction : public FEditorAction
{
public:
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;

protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual FString GetActionName() const override { return TEXT("set_actor_transform"); }
};


/**
 * FGetActorPropertiesAction
 * Gets all properties of an actor.
 * Params: name (string), detailed (bool, default false), editable_only (bool, default false), category (string)
 * When detailed=true, enumerates ALL FProperty fields including Blueprint variables.
 */
class UEEDITORMCP_API FGetActorPropertiesAction : public FEditorAction
{
public:
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;

protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual FString GetActionName() const override { return TEXT("get_actor_properties"); }
	virtual bool RequiresSave() const override { return false; }

private:
	/** Serialize a single FProperty value to JSON representation */
	static TSharedPtr<FJsonValue> PropertyValueToJson(FProperty* Property, const void* ValuePtr);

	/** Get a human-readable type string for a property */
	static FString GetPropertyTypeString(FProperty* Property);
};


/**
 * FSetActorPropertyAction
 * Sets a property on an actor.
 */
class UEEDITORMCP_API FSetActorPropertyAction : public FEditorAction
{
public:
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;

protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual FString GetActionName() const override { return TEXT("set_actor_property"); }
};


/**
 * FFocusViewportAction
 * Focuses the viewport on an actor or location.
 */
class UEEDITORMCP_API FFocusViewportAction : public FEditorAction
{
public:
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;

protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual FString GetActionName() const override { return TEXT("focus_viewport"); }
	virtual bool RequiresSave() const override { return false; }
};


/**
 * FGetViewportTransformAction
 * Gets the current viewport camera location and rotation.
 */
class UEEDITORMCP_API FGetViewportTransformAction : public FEditorAction
{
public:
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;

protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override { return true; }
	virtual FString GetActionName() const override { return TEXT("get_viewport_transform"); }
	virtual bool RequiresSave() const override { return false; }
};


/**
 * FSetViewportTransformAction
 * Sets the viewport camera location and/or rotation.
 */
class UEEDITORMCP_API FSetViewportTransformAction : public FEditorAction
{
public:
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;

protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual FString GetActionName() const override { return TEXT("set_viewport_transform"); }
	virtual bool RequiresSave() const override { return false; }
};


/**
 * FSaveAllAction
 * Saves all dirty packages (blueprints, levels, assets).
 */
class UEEDITORMCP_API FSaveAllAction : public FEditorAction
{
public:
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;

protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override { return true; }
	virtual FString GetActionName() const override { return TEXT("save_all"); }
	virtual bool RequiresSave() const override { return false; }
};


/**
 * FListAssetsAction
 * Enumerate assets under a Content path with optional class/name filtering.
 * Params: path (e.g. "/Game/UI"), recursive (bool), class_filter (string),
 *         name_contains (string), max_results (int)
 */
class UEEDITORMCP_API FListAssetsAction : public FEditorAction
{
public:
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;

protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual FString GetActionName() const override { return TEXT("list_assets"); }
	virtual bool RequiresSave() const override { return false; }
};


/**
 * FRenameAssetsAction
 * Rename one or more assets and optionally fix redirectors automatically.
 *
 * Supported params:
 * 1) Single rename:
 *    old_asset_path, new_package_path, new_name
 * 2) Batch rename:
 *    items: [{old_asset_path, new_package_path, new_name}, ...]
 *
 * Optional params:
 *    auto_fixup_redirectors (bool, default true)
 *    allow_ui_prompts (bool, default false)
 *    fixup_mode (string: "delete" | "leave" | "prompt", default "delete")
 *    checkout_dialog_prompt (bool, default false; ignored when allow_ui_prompts=false)
 */
class UEEDITORMCP_API FRenameAssetsAction : public FEditorAction
{
public:
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;

protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual FString GetActionName() const override { return TEXT("rename_assets"); }
};


/**
 * FPlanAssetRenamesAction
 * Dry-run planning for one or more asset moves/renames. Reports source validity,
 * destination conflicts, duplicate destinations, protected paths, and referencers.
 *
 * Supported params match rename_assets:
 *   old_asset_path, new_package_path, new_name
 *   items: [{old_asset_path, new_package_path, new_name}, ...]
 *
 * Optional params:
 *   include_referencers (bool, default true)
 *   max_referencers_per_item (int, default 20)
 *   allow_protected_paths (bool, default false)
 */
class UEEDITORMCP_API FPlanAssetRenamesAction : public FEditorAction
{
public:
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;

protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual FString GetActionName() const override { return TEXT("plan_asset_renames"); }
	virtual bool RequiresSave() const override { return false; }
};


/**
 * FDeleteAssetsAction
 * Delete one or more assets after optional dry-run and reference checks.
 *
 * Params:
 *   asset_path or asset_paths
 *
 * Optional params:
 *   dry_run (bool, default true)
 *   require_unreferenced (bool, default true)
 *   force (bool, default false)
 *   allow_map_assets (bool, default false)
 *   allow_protected_paths (bool, default false)
 *   max_referencers_per_asset (int, default 20)
 */
class UEEDITORMCP_API FDeleteAssetsAction : public FEditorAction
{
public:
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;

protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual FString GetActionName() const override { return TEXT("delete_assets"); }
	virtual bool RequiresSave() const override { return false; }
};


/**
 * FDeleteEmptyDirectoriesAction
 * Delete empty Content Browser directories only. The action scans both the
 * AssetRegistry and disk so purely empty physical directories are not missed.
 *
 * Params:
 *   path or paths
 *
 * Optional params:
 *   dry_run (bool, default true)
 *   recursive (bool, default true)
 *   allow_protected_paths (bool, default false)
 *   max_directories (int, default 1000)
 */
class UEEDITORMCP_API FDeleteEmptyDirectoriesAction : public FEditorAction
{
public:
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;

protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual FString GetActionName() const override { return TEXT("delete_empty_directories"); }
	virtual bool RequiresSave() const override { return false; }
};


/**
 * FProcessAssetMaintenanceManifestAction
 * Validate or apply an LLM-produced asset maintenance manifest. The manifest is
 * converted into deterministic rename/delete-empty-directory sub-commands, gets
 * a stable plan hash, and requires hash confirmation before any write.
 *
 * Params:
 *   manifest: {
 *     schema: "ue.asset_maintenance_plan.v1" | "ue.asset_rename_plan.v1",
 *     project: optional project name,
 *     defaults: optional execution defaults,
 *     items: [
 *       {
 *         id, op: "rename_or_move_asset",
 *         source: { object_path or package_path + asset_name, expected_class },
 *         target: { directory or new_package_path or package_path, asset_name/new_name, object_path }
 *       },
 *       { id, op: "delete_empty_directory", path }
 *     ],
 *     cleanup: { empty_directories: ["/Game/Old"] }
 *   }
 *
 * Optional params:
 *   mode (string: "plan" | "apply", default "plan")
 *   confirm_plan_hash (string, required for apply)
 *   include_referencers, max_referencers_per_item
 *   allow_protected_paths, allow_case_only_renames
 *   min_confidence
 */
class UEEDITORMCP_API FProcessAssetMaintenanceManifestAction : public FEditorAction
{
public:
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;

protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual FString GetActionName() const override { return TEXT("process_asset_maintenance_manifest"); }
	virtual bool RequiresSave() const override { return false; }
};


/**
 * FGetSelectedAssetThumbnailAction
 * Returns base64-encoded PNG thumbnails for selected Content Browser assets,
 * or explicit asset path/id lists if provided.
 * Params:
 *   asset_path (string, optional) - one full asset path
 *   asset_paths (string[], optional) - multiple full asset paths
 *   asset_ids (string[], optional) - alias of asset_paths
 *   ids (string[], optional) - alias of asset_paths
 *   size (int, optional, default 256, clamp 1..256)
 */
class UEEDITORMCP_API FGetSelectedAssetThumbnailAction : public FEditorAction
{
public:
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;

protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual FString GetActionName() const override { return TEXT("get_selected_asset_thumbnail"); }
	virtual bool RequiresSave() const override { return false; }
};


/**
 * FCaptureEditorScreenshotAction
 * Captures the current UE editor UI as a base64-encoded PNG.
 * Token-saving default: output is downscaled to max_width=512 with proportional height.
 * Only request higher resolution when needed by setting max_width/max_height, or use full_resolution=true for the captured source size.
 * Params:
 *   target (string, optional): "active_window" (default) or "active_viewport"
 *   max_width (int, optional, default 512, clamp 64..1920)
 *   max_height (int, optional, default 1920, clamp 64..1920)
 *   full_resolution (bool, optional, default false): ignore max_width/max_height and return captured source size
 *   include_base64 (bool, optional, default true)

 */
class UEEDITORMCP_API FCaptureEditorScreenshotAction : public FEditorAction
{
public:
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;

protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual FString GetActionName() const override { return TEXT("capture_editor_screenshot"); }
	virtual bool RequiresSave() const override { return false; }
};


/**
 * FGetSelectedAssetsAction
 * Returns a list of currently selected assets in the Content Browser.
 * No parameters required — returns paths, names, class info, and package paths
 * of all assets selected in Content Browser at the time of the call.
 * Action ID: editor.get_selected_assets
 */
class UEEDITORMCP_API FGetSelectedAssetsAction : public FEditorAction
{
public:
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;

protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override { return true; }
	virtual FString GetActionName() const override { return TEXT("get_selected_assets"); }
	virtual bool RequiresSave() const override { return false; }
};


/**
 * FGetBlueprintSummaryAction
 * Get a comprehensive summary of a Blueprint's internal implementation:
 * variables, functions, event graphs, components, parent class, compile status, etc.
 * Params: blueprint_name (string) or asset_path (string)
 */
class UEEDITORMCP_API FGetBlueprintSummaryAction : public FEditorAction
{
public:
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;

protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual FString GetActionName() const override { return TEXT("get_blueprint_summary"); }
	virtual bool RequiresSave() const override { return false; }
};


// =========================================================================
// P2 Actions
// =========================================================================

/**
 * FGetEditorLogsAction
 * Returns recent editor log entries from the MCPLogCapture ring buffer.
 * Params: count (int, default 100), category (string), min_verbosity (string)
 */
class UEEDITORMCP_API FGetEditorLogsAction : public FEditorAction
{
public:
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;

protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override { return true; }
	virtual FString GetActionName() const override { return TEXT("get_editor_logs"); }
	virtual bool RequiresSave() const override { return false; }
};


/**
 * FGetUnrealLogsAction
 * Returns live log lines from FMCPLogCapture using seq cursor + byte/line limits.
 * Params:
 *   cursor ("live:<seq>")
 *   tail_lines (int, default 200, clamp 20..2000)
 *   max_bytes (int, default 65536, clamp 8192..1048576)
 *   include_meta (bool, default true)
 *   require_recent (bool, default false)
 *   recent_window_seconds (double, default 2.0)
 *   filter_min_verbosity (string)
 *   filter_contains (string)
 *   filter_category (string) / filter_categories (string[])
 */
class UEEDITORMCP_API FGetUnrealLogsAction : public FEditorAction
{
public:
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;

protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override { return true; }
	virtual FString GetActionName() const override { return TEXT("get_unreal_logs"); }
	virtual bool RequiresSave() const override { return false; }
};


/**
 * FBatchExecuteAction
 * Executes multiple commands in sequence within a single TCP request.
 * Params: commands (array of {type, params, action_id}), stop_on_error (bool, default true),
 * result_verbosity (compact default | full). Params support batch refs such as {"$ref":"steps[0].path"}.
 */
class UEEDITORMCP_API FBatchExecuteAction : public FEditorAction
{
public:
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;

protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual FString GetActionName() const override { return TEXT("batch_execute"); }

private:
	/** Max commands per batch (C++ side limit) */
	static constexpr int32 MaxBatchSize = 50;
};


/**
 * FEditorIsReadyAction
 * Checks whether the editor has fully initialized and is ready for use.
 * Returns: ready (bool), details about startup state.
 * No params required.
 */
class UEEDITORMCP_API FEditorIsReadyAction : public FEditorAction
{
public:
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;

protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override { return true; }
	virtual FString GetActionName() const override { return TEXT("is_ready"); }
	virtual bool RequiresSave() const override { return false; }
};


/**
 * FRequestEditorShutdownAction
 * Requests the editor to shut down gracefully via FGenericPlatformMisc::RequestExit.
 * Params: force (bool, default false) - if true, force-exits without save prompts.
 */
class UEEDITORMCP_API FRequestEditorShutdownAction : public FEditorAction
{
public:
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;

protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override { return true; }
	virtual FString GetActionName() const override { return TEXT("request_shutdown"); }
	virtual bool RequiresSave() const override { return false; }
};


/**
 * FExecConsoleCommandAction
 *
 * Execute a UE console command inside the running editor (e.g. "Automation RunTests P111.LJC+",
 * "Stat Unit", "log LogLJC Verbose"). Command output is captured from the editor log ring buffer
 * (via FUEEditorMCPLogCapture) and returned alongside the synchronous Exec() boolean.
 *
 * SECURITY — strict allowlist + denylist:
 *  - Empty command rejected.
 *  - Length > 512 chars rejected.
 *  - Multi-command separators ';' '&&' '||' rejected (one command per call).
 *  - Allowed prefixes (case-insensitive, leading whitespace stripped):
 *      "Automation "  — automation framework (RunTests, List, etc.)
 *      "Stat "        — stat counters
 *      "log "         — log verbosity tweaks (`log LogLJC Verbose`)
 *      "viewmode "    — render viewmode switches
 *      "showflag."    — render showflag toggles
 *      "r."           — read-only render cvars (writes still go through Exec, accept)
 *      "p."           — physics cvars
 *      "t."           — timing cvars
 *      "ai."          — AI cvars
 *      "slomo "       — time dilation
 *      "ke "          — kismet event triggers (test-only)
 *  - Forbidden substrings (case-insensitive): "quit", "exit", "open ", "travel ", "restart",
 *    "obj gc", "crash", "fatal", "rhi.", "..\\", "..//", absolute file paths.
 *
 * Params:
 *   command (string, required) - the console command to execute
 *   capture_logs (bool, default true) - if true, return the editor log lines emitted during this Exec.
 *   capture_lines (int, default 200) - max log lines to return when capture_logs=true.
 *
 * Returns:
 *   exec_succeeded (bool) - GEngine->Exec() return value (false = command not recognized)
 *   command (string)      - the validated command actually executed
 *   captured_logs (array) - editor log entries during Exec (only if capture_logs=true)
 *
 * Action ID: editor.exec_console_command
 */
class UEEDITORMCP_API FExecConsoleCommandAction : public FEditorAction
{
public:
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;

protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual FString GetActionName() const override { return TEXT("exec_console_command"); }
	virtual bool RequiresSave() const override { return false; }

private:
	/** Strict allowlist + denylist. Returns true if the (trimmed) command passes safety checks. */
	static bool IsCommandAllowed(const FString& Command, FString& OutError);
};



/**
 * FDescribeFullAction
 * Returns a comprehensive single-call snapshot of an entire Blueprint:
 * summary (parent class, variables, components, interfaces, compile status) +
 * all graph topologies (EventGraph + function graphs + macro graphs) with
 * compact node/edge serialization.
 *
 * Replaces the need for: 1x blueprint.get_summary + Nx graph.describe calls.
 *
 * Params:
 *   blueprint_name (string) or asset_path (string)
 *   include_pin_details (bool, default false) - if true, serialize full FEdGraphPinType
 *   include_function_signatures (bool, default false) - if true, inline function signatures
 *
 * Command: describe_blueprint_full
 * Action ID: blueprint.describe_full
 */
class UEEDITORMCP_API FDescribeFullAction : public FEditorAction
{
public:
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;

protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual FString GetActionName() const override { return TEXT("describe_blueprint_full"); }
	virtual bool RequiresSave() const override { return false; }

private:
	/** Serialize a single graph's topology in compact or detailed mode */
	TSharedPtr<FJsonObject> SerializeGraph(UBlueprint* Blueprint, UEdGraph* Graph,
		bool bIncludePinDetails, bool bIncludeFunctionSignatures) const;

	/** Serialize a pin in compact mode (category + direction + connected + default only) */
	static TSharedPtr<FJsonObject> SerializePinCompact(const UEdGraphPin* Pin);
};


// =========================================================================
// P6: PIE Control Actions
// =========================================================================

/**
 * FStartPIEAction
 * Starts a Play In Editor session.
 * Params: mode (string: SelectedViewport|NewWindow|Simulate, default SelectedViewport)
 * Action ID: editor.start_pie
 */
class UEEDITORMCP_API FStartPIEAction : public FEditorAction
{
public:
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;

protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual FString GetActionName() const override { return TEXT("start_pie"); }
	virtual bool RequiresSave() const override { return false; }
};


/**
 * FStopPIEAction
 * Stops the current PIE session without closing the editor.
 * Action ID: editor.stop_pie
 */
class UEEDITORMCP_API FStopPIEAction : public FEditorAction
{
public:
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;

protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override { return true; }
	virtual FString GetActionName() const override { return TEXT("stop_pie"); }
	virtual bool RequiresSave() const override { return false; }
};


/**
 * FGetPIEStateAction
 * Queries the current PIE session state: Running/Stopped, world name, duration, paused.
 * Action ID: editor.get_pie_state
 */
class UEEDITORMCP_API FGetPIEStateAction : public FEditorAction
{
public:
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;

protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override { return true; }
	virtual FString GetActionName() const override { return TEXT("get_pie_state"); }
	virtual bool RequiresSave() const override { return false; }
};


// =========================================================================
// P6: Log Enhancement Actions
// =========================================================================

/**
 * FClearLogsAction
 * Clears the MCPLogCapture ring buffer. Optionally inserts a session tag marker before clearing.
 * Params: tag (string, optional)
 * Action ID: editor.clear_logs
 */
class UEEDITORMCP_API FClearLogsAction : public FEditorAction
{
public:
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;

protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override { return true; }
	virtual FString GetActionName() const override { return TEXT("clear_logs"); }
	virtual bool RequiresSave() const override { return false; }
};


/**
 * FAssertLogAction
 * Assertion-based log validation. Checks log entries for keyword occurrences
 * and returns pass/fail for each assertion.
 * Params: assertions (array of {keyword, expected_count, comparison, category}),
 *         since_cursor (string, optional "live:<seq>")
 * Action ID: editor.assert_log
 */
class UEEDITORMCP_API FAssertLogAction : public FEditorAction
{
public:
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;

protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual FString GetActionName() const override { return TEXT("assert_log"); }
	virtual bool RequiresSave() const override { return false; }
};


// =========================================================================
// P6: Outliner Management Actions
// =========================================================================

/**
 * FRenameActorLabelAction
 * Renames an actor's display label in the World Outliner.
 * Params: actor_name (string), new_label (string) — or items[] for batch.
 * Action ID: editor.rename_actor_label
 */
class UEEDITORMCP_API FRenameActorLabelAction : public FEditorAction
{
public:
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;

protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual FString GetActionName() const override { return TEXT("rename_actor_label"); }

private:
	/** Find actor by name or label in the editor world */
	AActor* FindActorByName(UWorld* World, const FString& ActorName) const;
};


/**
 * FSetActorFolderAction
 * Moves actors into Outliner folders (creates folders automatically).
 * Params: actor_name (string), folder_path (string) — or items[] for batch.
 * Action ID: editor.set_actor_folder
 */
class UEEDITORMCP_API FSetActorFolderAction : public FEditorAction
{
public:
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;

protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual FString GetActionName() const override { return TEXT("set_actor_folder"); }

private:
	AActor* FindActorByName(UWorld* World, const FString& ActorName) const;
};


/**
 * FSelectActorsAction
 * Selects/deselects actors in the editor World Outliner.
 * Params: actor_names (string[]), mode (set|add|remove|toggle, default set)
 * Action ID: editor.select_actors
 */
class UEEDITORMCP_API FSelectActorsAction : public FEditorAction
{
public:
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;

protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual FString GetActionName() const override { return TEXT("select_actors"); }
	virtual bool RequiresSave() const override { return false; }

private:
	AActor* FindActorByName(UWorld* World, const FString& ActorName) const;
};


/**
 * FGetOutlinerTreeAction
 * Returns the actor hierarchy organized by Outliner folders.
 * Params: class_filter (string, optional), folder_filter (string, optional)
 * Action ID: editor.get_outliner_tree
 */
class UEEDITORMCP_API FGetOutlinerTreeAction : public FEditorAction
{
public:
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;

protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override { return true; }
	virtual FString GetActionName() const override { return TEXT("get_outliner_tree"); }
	virtual bool RequiresSave() const override { return false; }
};


// =========================================================================
// P7: Asset Editor Actions
// =========================================================================

/**
 * FOpenAssetEditorAction
 * Opens the asset editor for a given asset and optionally brings it to focus.
 * Params:
 *   asset_path (string, required) - Full content path, e.g. "/Game/Characters/BP_Hero"
 *   focus (bool, default true) - Whether to focus the editor window after opening
 * Action ID: editor.open_asset_editor
 */
class UEEDITORMCP_API FOpenAssetEditorAction : public FEditorAction
{
public:
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;

protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual FString GetActionName() const override { return TEXT("open_asset_editor"); }
	virtual bool RequiresSave() const override { return false; }
};


// =========================================================================
// P8: PIE Automation Test Actions（关卡切换 + 多人 PIE + 输入模拟）
// =========================================================================

/**
 * FOpenLevelAction
 * 在编辑器中切换/加载指定关卡（不进入 PIE）。
 * Params: level_path (string, required) - 例如 "/Game/LJCTest/L_LJCTest"
 *         save_dirty (bool, default false) - 切换前是否保存当前未保存的资产
 * Action ID: editor.open_level
 */
class UEEDITORMCP_API FOpenLevelAction : public FEditorAction
{
public:
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;

protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual FString GetActionName() const override { return TEXT("open_level"); }
	virtual bool RequiresSave() const override { return false; }
};

/**
 * FCreateLevelAction
 * Creates and saves a blank level package, optionally opening it in the editor.
 * Params: level_path (string, required) - e.g. "/Game/P110_2/TPS/Maps/L_TPS_Test"
 *         if_exists (string, default "error") - "error" | "overwrite" | "skip" | "reuse"
 *         open_level (bool, default true) - keep the new/reused level open after creation
 *         save_dirty (bool, default false) - save dirty packages before replacing the current map
 * Action ID: editor.create_level
 */
class UEEDITORMCP_API FCreateLevelAction : public FEditorAction
{
public:
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;

protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual FString GetActionName() const override { return TEXT("create_level"); }
	virtual bool RequiresSave() const override { return false; }
};

/**
 * FDuplicateAssetAction
 * Duplicates one asset to a destination package path using EditorAssetSubsystem.
 * Params: source_asset_path (string, required) - object or package path
 *         destination_asset_path (string, required) - destination package/object path
 *         if_exists (string, default "error") - "error" | "overwrite" | "skip" | "reuse"
 *         save (bool, default true) - save the duplicated asset package
 * Action ID: editor.duplicate_asset
 */
class UEEDITORMCP_API FDuplicateAssetAction : public FEditorAction
{
public:
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;

protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual FString GetActionName() const override { return TEXT("duplicate_asset"); }
};

/**
 * FSetWorldSettingsClassAction
 * Sets a class-valued property on the current editor world's WorldSettings.
 * Params: property_name (string, required) - e.g. "DefaultGameMode" (displayed as GameMode Override)
 *         class_path (string, required) - class path/name, e.g. "/Game/.../BP_Mode.BP_Mode_C"
 * Action ID: editor.set_world_settings_class
 */
class UEEDITORMCP_API FSetWorldSettingsClassAction : public FEditorAction
{
public:
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;

protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual FString GetActionName() const override { return TEXT("set_world_settings_class"); }
};

/**
 * FSimulateInputAction
 * 在 PIE 中模拟按键 / 鼠标输入，定向派发到指定客户端实例。
 * Params:
 *   client_index (int, default 0)         - PIE 实例索引（0=Listen Server，1=Client，依此类推）
 *   key (string, required)                - 按键名（如 "W"、"Two"、"LeftMouseButton"、"SpaceBar"）
 *   event (string, default "Pressed")     - "Pressed" | "Released" | "Click"
 *   duration_ms (int, default 50)         - 当 event=Click 时按下→释放的间隔毫秒数
 *   focus_viewport (bool, default true)   - 派发前是否将焦点切到游戏视口
 * Action ID: editor.simulate_input
 */
class UEEDITORMCP_API FSimulateInputAction : public FEditorAction
{
public:
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;

protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual FString GetActionName() const override { return TEXT("simulate_input"); }
	virtual bool RequiresSave() const override { return false; }
};


// =========================================================================
// Asset Property Editing — DataAsset / UObject 资产字段直写
// =========================================================================

/**
 * FSetDataAssetPropertyAction
 *
 * 直接修改一个已加载（或可加载）的 UObject 资产（DataAsset、PrimaryDataAsset、
 * 普通 UDataAsset 派生类，乃至任意 UObject 资产）的 UPROPERTY，包括 USTRUCT
 * 字段、数组、Map、Set 等复杂类型。底层走 ImportText，所以任何在 UE 文本格式下
 * 可表达的值都能写入。
 *
 * Params:
 *   asset_path     (string, required) — 资产路径，例如 "/Game/P111/Data/DA_LevelSelect_Default"
 *                                       支持带或不带尾随 ".AssetName"。
 *   property_name  (string, required) — 顶层 UPROPERTY 名（例如 "Entries"）
 *   property_value (string|number|bool|object, required) — 字段值
 *                                       字符串值会走 FProperty::ImportText_Direct 路径，
 *                                       适合写复杂结构（"((LevelId=\"lobby\",...))"）。
 *   save           (bool, optional, default true) — 写入后立即 SavePackage 落盘
 *
 * 返回:
 *   {
 *     success: true,
 *     asset_path: "...",
 *     property_name: "Entries",
 *     value_after: "...UE 文本格式回读..." ,
 *     saved: true
 *   }
 *
 * 设计目的：
 *   早先 set_object_property 是"在 BP 里创建 K2Node_VariableSet 节点"的接口，
 *   名字与"修改资产 UPROPERTY"易混淆，且无法用于 DataAsset。本 Action 专攻
 *   后者，避免名字撞车。
 *
 * Action ID: editor.set_data_asset_property
 */
class UEEDITORMCP_API FSetDataAssetPropertyAction : public FEditorAction
{
public:
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;

protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual FString GetActionName() const override { return TEXT("set_data_asset_property"); }
	virtual bool RequiresSave() const override { return false; } // 内部按 save 参数自行处理
};


/**
 * FGetDataAssetPropertyAction
 *
 * 读取一个 UObject 资产上单个 UPROPERTY 的当前值（以 UE 文本格式回写为字符串）。
 * 主要用于 set_data_asset_property 的端到端验证；普通 BP_API 也可用。
 *
 * Params:
 *   asset_path    (string, required)
 *   property_name (string, required)
 *
 * 返回:
 *   { success: true, asset_path, property_name, value: "...UE 文本格式..." }
 *
 * Action ID: editor.get_data_asset_property
 */
class UEEDITORMCP_API FGetDataAssetPropertyAction : public FEditorAction
{
public:
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;

protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual FString GetActionName() const override { return TEXT("get_data_asset_property"); }
	virtual bool RequiresSave() const override { return false; }
};

/**
 * FGetBlueprintCDOGameplayTagsAction
 *
 * 读取 Blueprint GeneratedClass CDO 上所有 GameplayTag 相关属性，并输出字段路径到 Tag 的精确映射。
 * 递归覆盖 FGameplayTag、FGameplayTagContainer、数组、Set、Map 与普通 USTRUCT 嵌套字段。
 *
 * Params:
 *   asset_path     (string, required) — Blueprint 资产路径
 *   include_empty  (bool, optional, default false) — 是否输出空的 Tag 属性
 *
 * Action ID: editor.get_blueprint_cdo_gameplay_tags
 */
class UEEDITORMCP_API FGetBlueprintCDOGameplayTagsAction : public FEditorAction
{
public:
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;

protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual FString GetActionName() const override { return TEXT("get_blueprint_cdo_gameplay_tags"); }
	virtual bool RequiresSave() const override { return false; }
};

/**
 * FConfigureGameplayEffectTargetTagsAction
 *
 * 给 GameplayEffect Blueprint 添加/更新 TargetTagsGameplayEffectComponent，
 * 用于 UE 5.7 冷却 GE 必须通过组件赋予 Granted Tags 的资产修复。
 *
 * Params:
 *   asset_path (string, required) — GameplayEffect Blueprint 资产路径
 *   tag_name   (string, required) — 要赋予目标 Actor 的 GameplayTag
 *   save       (bool, optional, default true) — 是否立即保存资产
 *
 * Action ID: editor.configure_gameplay_effect_target_tags
 */
class UEEDITORMCP_API FConfigureGameplayEffectTargetTagsAction : public FEditorAction
{
public:
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;

protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual FString GetActionName() const override { return TEXT("configure_gameplay_effect_target_tags"); }
	virtual bool RequiresSave() const override { return false; }
};

/**
 * FConfigureGameplayEffectIgnoreTagsAction
 *
 * 给 GameplayEffect Blueprint 添加/更新 TargetTagRequirementsGameplayEffectComponent 的
 * ApplicationTagRequirements.IgnoreTags（"Must Not Have Tags"）。
 * 用于 BUFF 系统的免疫逻辑：目标身上带有 IgnoreTags 中的任意 Tag 时，
 * 该 GameplayEffect 无法应用到该目标身上（不写 C++ if 分支，纯数据驱动）。
 *
 * Params:
 *   asset_path (string, required) — GameplayEffect Blueprint 资产路径
 *   tag_name   (string, required) — 要加入 ApplicationTagRequirements.IgnoreTags 的 GameplayTag
 *   save       (bool, optional, default true) — 是否立即保存资产
 *
 * Action ID: editor.configure_gameplay_effect_ignore_tags
 */
class UEEDITORMCP_API FConfigureGameplayEffectIgnoreTagsAction : public FEditorAction
{
public:
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;

protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual FString GetActionName() const override { return TEXT("configure_gameplay_effect_ignore_tags"); }
	virtual bool RequiresSave() const override { return false; }
};
/**
 * FSetGameplayEffectModifierScalableFloatAction
 *
 * 只修改 GameplayEffect Blueprint CDO 上 Modifiers 中 ScalableFloat 类型幅度的 raw Value，
 * 保留 Attribute、ModifierOp、曲线、Tag 条件等其它配置不变。用于把 BUFF GE 调整为
 * “GE Level 原样通过”的模板配置。
 *
 * Params:
 *   asset_path  (string, optional) — 单个 GameplayEffect Blueprint 资产路径
 *   asset_paths (array, optional)  — 多个 GameplayEffect Blueprint 资产路径
 *   new_value   (number, optional, default 1.0) — 写入 ScalableFloat.Value 的值
 *   save        (bool, optional, default true) — 是否立即保存资产
 *   dry_run     (bool, optional, default false) — 只读取并返回将要修改的项，不写入资产
 *
 * Action ID: editor.set_gameplay_effect_modifier_scalable_float
 */
class UEEDITORMCP_API FSetGameplayEffectModifierScalableFloatAction : public FEditorAction
{
public:
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;

protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual FString GetActionName() const override { return TEXT("set_gameplay_effect_modifier_scalable_float"); }
	virtual bool RequiresSave() const override { return false; }
};
/**
 * FSaveLoadedAssetAction
 *
 * 强制保存一个已加载资产。等价于在 UE 编辑器内容浏览器右键 Save。
 * 内部走 UEditorAssetSubsystem::SaveLoadedAsset(Asset, bOnlyIfDirty=false)
 * 与 GUI Save 完全相同的路径，能正确触发 PreSave / Serialize / WidgetBlueprint
 * extension 链。这是修复"compile_blueprint 内置 save 没把 MVVM extension
 * 真正写进 .uasset"的关键工具。
 *
 * Params:
 *   asset_path     (string, required) — 资产路径（带或不带尾随对象名都行）
 *   only_if_dirty  (bool, optional, default false) — 是否只保存脏包
 *
 * 返回:
 *   { success: true, asset_path, asset_class, saved: true }
 *
 * Action ID: editor.save_loaded_asset
 */
class UEEDITORMCP_API FSaveLoadedAssetAction : public FEditorAction
{
public:
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;

protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual FString GetActionName() const override { return TEXT("save_loaded_asset"); }
	virtual bool RequiresSave() const override { return false; }
};


/**
 * FCreateDataAssetAction
 *
 * 创建一个 UDataAsset 派生类实例。支持任意 C++ 或蓝图 DataAsset 类。
 *
 * Params:
 *   asset_name    (string, required) — 资产名（不含路径），例如 "DA_LJCEventProfile_Default"
 *   package_path  (string, required) — 包路径，例如 "/Game/P111/Data/LJC"
 *   asset_class   (string, required) — DataAsset 类路径，支持以下格式：
 *                                      - 短名: "LJCGameplayEventProfile"
 *                                      - Script 路径: "/Script/P111.LJCGameplayEventProfile"
 *                                      - 蓝图路径: "/Game/.../BP_MyDA.BP_MyDA_C"
 *   save          (bool, optional, default true) — 创建后立即保存
 *
 * 返回:
 *   { success: true, asset_path, asset_class, saved: true }
 *
 * Action ID: editor.create_data_asset
 */
class UEEDITORMCP_API FCreateDataAssetAction : public FEditorAction
{
public:
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;

protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual FString GetActionName() const override { return TEXT("create_data_asset"); }
	virtual bool RequiresSave() const override { return false; }
};


/**
 * FCreateDataTableAction
 *
 * 创建 DataTable 资产并设置 RowStruct。用于自动化配置表迁移。
 *
 * Params:
 *   asset_name   (string, required) - 资产名，不含路径
 *   package_path (string, required) - 包路径，例如 "/Game/P111/Data/DataTables"
 *   row_struct   (string, required) - UScriptStruct 路径，例如 "/Script/P111.P111BuffEntry"
 *   save         (bool, optional, default true)
 *
 * Action ID: editor.create_data_table
 */
class UEEDITORMCP_API FCreateDataTableAction : public FEditorAction
{
public:
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;

protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual FString GetActionName() const override { return TEXT("create_data_table"); }
	virtual bool RequiresSave() const override { return false; }
};

// =========================================================================
// P10: DataTable Row CRUD Actions
// =========================================================================

/**
 * FDataTableGetRowsAction
 *
 * 读取 DataTable 全部行，返回 JSON 数组。适合批量读取/盘点。
 *
 * Params:
 *   asset_path (string, required) — DataTable 资产路径
 *
 * 返回:
 *   { success: true, asset_path, row_struct, row_count, rows: [...] }
 *   rows 中每条为一个 JSON object（row_name + 各字段值）。
 *
 * Action ID: editor.data_table_get_rows
 */
class UEEDITORMCP_API FDataTableGetRowsAction : public FEditorAction
{
public:
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;

protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual FString GetActionName() const override { return TEXT("data_table_get_rows"); }
	virtual bool RequiresSave() const override { return false; }
};


/**
 * FDataTableAddRowAction
 *
 * 向 DataTable 新增一行。RowName 必须唯一，与已有行冲突时报错。
 * 通过 BulkImportText（UE 文本字面量）构造整行 struct，再写入 RowMap。
 *
 * Params:
 *   asset_path    (string, required) — DataTable 资产路径
 *   row_name      (string, required) — 行名（唯一标识）
 *   property_values (object, required) — { "FieldName": value, ... }
 *     标量值传 string/number/bool；
 *     FRuntimeFloatCurve 等复杂 USTRUCT 传 UE 文本字面量字符串。
 *   save          (bool, optional, default true) — 写入后立即落盘
 *
 * 返回:
 *   { success: true, asset_path, row_name, row_count_after, saved }
 *
 * Action ID: editor.data_table_add_row
 */
class UEEDITORMCP_API FDataTableAddRowAction : public FEditorAction
{
public:
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;

protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual FString GetActionName() const override { return TEXT("data_table_add_row"); }
	virtual bool RequiresSave() const override { return false; }
};


/**
 * FDataTableSetRowPropertyAction
 *
 * 修改 DataTable 中指定行的某个字段（单个 UPROPERTY），不走整表重新导入。
 *
 * Params:
 *   asset_path     (string, required) — DataTable 资产路径
 *   row_name       (string, required) — 目标行名
 *   property_name  (string, required) — 字段名
 *   property_value (string|number|bool, required) — 新值
 *   save           (bool, optional, default true) — 写入后立即落盘
 *
 * 返回:
 *   { success: true, asset_path, row_name, property_name, value_after, saved }
 *
 * Action ID: editor.data_table_set_row_property
 */
class UEEDITORMCP_API FDataTableSetRowPropertyAction : public FEditorAction
{
public:
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;

protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual FString GetActionName() const override { return TEXT("data_table_set_row_property"); }
	virtual bool RequiresSave() const override { return false; }
};


// =========================================================================
// LiveCoding Actions
// =========================================================================

/**
 * FLiveCodingCompileAction
 *
 * 触发 Unreal Editor 的 Live Coding 增量编译（等价于编辑器右下角 Live Coding 图标
 * 的 "Quick Compile / Compile Changes" 按钮）。该 action 必须在编辑器进程内执行，
 * 因为 ILiveCodingModule 只在 Editor / Live Coding 模块内可用。
 *
 * 使用场景：
 *   - Agent 修改 C++ 后无需关闭编辑器，调用本 action 触发热重载，省去全量重启。
 *   - 配合 launcher_start_editor 实现"全量构建 vs 热重载"两条路径。
 *
 * 行为契约（**fire-and-forget**，2026-06-05 修复 GameThread 自死锁）：
 *   - 本 action 仅负责"发起一次 Quick Compile"，**永远不阻塞**。
 *   - MCPServer 把每个 action 都派发到 GameThread 同步执行；ILiveCodingModule
 *     的状态机本身又依赖 GameThread Tick 推进，因此在 GameThread 上自旋
 *     `while (IsCompiling()) Sleep` 会自死锁，表现为编辑器 UI 整体卡死直到
 *     timeout (120s) 甚至 MCPServer 兜底超时 (240s)。
 *   - 调用方应轮询 `editor.live_coding_status` 直到 `compile_in_progress=false`。
 *
 * Params:
 *   wait_for_completion (bool, **DEPRECATED 已忽略**) — 历史兼容字段；如果传入 true
 *                                                       响应中会带 deprecation_warning。
 *   timeout_seconds     (int,  **DEPRECATED 已忽略**) — 同上，已不再生效。
 *
 * 返回:
 *   {
 *     success: true,
 *     enabled: bool,             // Live Coding 当前是否启用
 *     compile_started: bool,     // 本次是否成功发起编译
 *     compile_in_progress: bool, // 是否仍在进行（**调用瞬间**的快照，不代表已完成）
 *     waited: false,             // 永远 false：本 action 不再 wait
 *     timed_out: false,          // 永远 false
 *     fire_and_forget: true,     // 标记位，方便客户端识别新行为
 *     deprecation_warning?: str  // 仅当传入 wait_for_completion=true 时出现
 *   }
 *
 * 推荐用法（轮询）：
 *   1) ue_actions_run editor.live_coding_compile {}            // 发起
 *   2) loop: ue_actions_run editor.live_coding_status {}       // 直到 compile_in_progress=false
 *
 * Action ID: editor.live_coding_compile
 */
class UEEDITORMCP_API FLiveCodingCompileAction : public FEditorAction
{
public:
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;

protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override { return true; }
	virtual FString GetActionName() const override { return TEXT("live_coding_compile"); }
	virtual bool RequiresSave() const override { return false; }
};


/**
 * FLiveCodingStatusAction
 *
 * 查询 Live Coding 当前状态。无副作用，可高频轮询用于等待编译完成。
 *
 * 返回:
 *   {
 *     success: true,
 *     module_loaded: bool,        // LiveCoding 模块是否加载（UE 5.x 编辑器默认加载）
 *     enabled: bool,              // 是否处于 enabled 状态
 *     compile_in_progress: bool,  // 是否正在编译
 *     can_enable_for_session: bool
 *   }
 *
 * Action ID: editor.live_coding_status
 */
class UEEDITORMCP_API FLiveCodingStatusAction : public FEditorAction
{
public:
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;

protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override { return true; }
	virtual FString GetActionName() const override { return TEXT("live_coding_status"); }
	virtual bool RequiresSave() const override { return false; }
};
