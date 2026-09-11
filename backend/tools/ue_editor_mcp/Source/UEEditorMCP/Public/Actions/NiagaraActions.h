// Copyright (c) 2025 zolnoor. All rights reserved.

#pragma once

#include "CoreMinimal.h"
#include "EditorAction.h"

// Forward declarations
class UNiagaraScript;
class UNiagaraSystem;
class UNiagaraEmitter;
struct FAssetData;

/**
 * FNiagaraAction
 *
 * Base class for Niagara-related MCP actions.
 *
 * Engine compatibility note (UE 5.7):
 *   The official 5.8 NiagaraToolsets System/Component "stack-editing" layer
 *   depends on the modules NiagaraExternalSystemEditorUtilities and
 *   ToolsetRegistry, neither of which exists in 5.7. The *system-composition*
 *   subset, however, is fully backed by stable 5.7 public API:
 *     - UNiagaraSystemFactoryNew (SystemToCopy / EmittersToAddToNewSystem)
 *     - FNiagaraEditorUtilities::AddEmitterToSystem (NIAGARAEDITOR_API)
 *   Those are used for create-from-template and add-emitter.
 *
 *   The from-zero stack-construction subset (add_renderer / add_module /
 *   set_module_input) is ALSO backed by stable 5.7 public API and is now
 *   exposed, deliberately routed through the asset-level (no-viewmodel) paths
 *   that the engine's own UNiagaraEmitterFactoryNew::InitializeEmitter uses:
 *     - UNiagaraEmitter::AddRenderer (NIAGARA_API, self-contained)
 *     - FNiagaraStackGraphUtilities::AddScriptModuleToStack (NIAGARAEDITOR_API)
 *     - rapid-iteration-parameter writes via
 *       FNiagaraStackGraphUtilities::CreateRapidIterationParameter +
 *       UNiagaraScript::RapidIterationParameters.SetParameterData
 *   These intentionally avoid the typed override-pin writes (the genuinely
 *   fragile 5.7 path), which remain unexposed.
 */
class UEEDITORMCP_API FNiagaraAction : public FEditorAction
{
protected:
	/** Load a UNiagaraScript by content path (e.g. "/Game/FX/Modules/MyModule"). */
	UNiagaraScript* LoadNiagaraScriptByPath(const FString& AssetPath, FString& OutError) const;

	/** Load a UNiagaraSystem by content path. */
	UNiagaraSystem* LoadNiagaraSystemByPath(const FString& AssetPath, FString& OutError) const;

	/** Load a UNiagaraEmitter asset by content path. */
	UNiagaraEmitter* LoadNiagaraEmitterByPath(const FString& AssetPath, FString& OutError) const;
};


/**
 * FNiagaraFindScriptsAction (read)
 *
 * Search for UNiagaraScript assets via the AssetRegistry.
 *
 * Parameters:
 *   - path (optional): content folder to search recursively (default: /Game)
 *   - name_filter (optional): case-insensitive substring match on asset name
 *   - visibility (optional): "Library" | "Unexposed" | "Hidden" | "Invalid"
 *   - usage (optional): ENiagaraScriptUsage name (e.g. "Module", "DynamicInput",
 *       "Function"). NOTE: 5.7 does not store the usage enum in registry tags,
 *       so filtering by usage forces a LoadObject() of each candidate.
 *   - include_deprecated (optional bool, default false)
 *   - max_results (optional int, default 100, hard cap 500)
 *
 * Returns:
 *   - count: number of matched scripts
 *   - scripts: array of digests (path, name, visibility, category, keywords,
 *       module_usage_bitmask, deprecated, suggested, [usage if resolved])
 */
class UEEDITORMCP_API FNiagaraFindScriptsAction : public FNiagaraAction
{
public:
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;

protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual FString GetActionName() const override { return TEXT("niagara_find_scripts"); }
	virtual bool RequiresSave() const override { return false; }
};


/**
 * FNiagaraGetScriptDigestAction (read)
 *
 * Decode a single UNiagaraScript's registry tags + resolved usage.
 *
 * Parameters:
 *   - asset_path (required): full content path of the UNiagaraScript
 *
 * Returns: a single digest object (same fields as find_scripts entries).
 */
class UEEDITORMCP_API FNiagaraGetScriptDigestAction : public FNiagaraAction
{
public:
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;

protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual FString GetActionName() const override { return TEXT("niagara_get_script_digest"); }
	virtual bool RequiresSave() const override { return false; }
};


/**
 * FNiagaraGetSystemSummaryAction (read)
 *
 * Load a UNiagaraSystem and report exposed user parameters + per-emitter info.
 *
 * Parameters:
 *   - asset_path (required): full content path of the UNiagaraSystem
 *
 * Returns:
 *   - name, path
 *   - user_parameters: array of { name, type }
 *   - emitters: array of { name, enabled, mode }
 *   - emitter_count
 */
class UEEDITORMCP_API FNiagaraGetSystemSummaryAction : public FNiagaraAction
{
public:
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;

protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual FString GetActionName() const override { return TEXT("niagara_get_system_summary"); }
	virtual bool RequiresSave() const override { return false; }
};

/**
 * Add or update an exposed Niagara User parameter on a system.
 *
 * Parameters:
 *   - system_path (required): content path of the target UNiagaraSystem
 *   - parameter_name (required): "User.Foo" or "Foo"
 *   - value_type (required): "float" | "int" | "bool" | "vec2" | "vec3" |
 *       "position" | "vec4" | "color"
 *   - value (required): number, bool, or numeric array
 */
class UEEDITORMCP_API FNiagaraSetUserParameterAction : public FNiagaraAction
{
public:
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;

protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual FString GetActionName() const override { return TEXT("niagara_set_user_parameter"); }
};


/**
 * FNiagaraGetCompileDiagnosticsAction (read)
 *
 * Load a UNiagaraSystem and report the latest per-script compile status,
 * compile events (warnings/errors) from FNiagaraVMExecutableData, and editor
 * stack issues such as deprecated modules and unmet module dependencies.
 *
 * Parameters:
 *   - asset_path (required): full content path of the UNiagaraSystem
 *   - refresh_compile (optional bool, default false): request a fresh compile
 *   - wait (optional bool, default true): wait for outstanding compilation
 *   - min_severity (optional): "log" | "display" | "warning" | "error"
 *       (default: "warning")
 *
 * Returns:
 *   - name, path, compile_status, error_count, warning_count
 *   - scripts[]: per-script status + events[]
 *   - events[]: flattened compile diagnostic events with display_text
 *   - stack_issues[]: flattened editor stack warning/error entries
 */
class UEEDITORMCP_API FNiagaraGetCompileDiagnosticsAction : public FNiagaraAction
{
public:
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;

protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual FString GetActionName() const override { return TEXT("niagara_get_compile_diagnostics"); }
	virtual bool RequiresSave() const override { return false; }
};


/**
 * FNiagaraSpawnSystemActorAction (write)
 *
 * Spawn a temporary Niagara actor in the current editor world, bind a system,
 * optionally push vector user parameters, and activate it. This is intended for
 * viewport/screenshot validation of generated VFX assets.
 */
class UEEDITORMCP_API FNiagaraSpawnSystemActorAction : public FNiagaraAction
{
public:
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;

protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual FString GetActionName() const override { return TEXT("niagara_spawn_system_actor"); }
};


/**
 * FNiagaraGetComponentDebugSummaryAction (read)
 *
 * Inspect a NiagaraComponent on an actor in the current PIE/editor world.
 * Reports component state, bounds, system instance state, and per-emitter
 * particle counts for runtime VFX validation.
 */
class UEEDITORMCP_API FNiagaraGetComponentDebugSummaryAction : public FNiagaraAction
{
public:
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;

protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual FString GetActionName() const override { return TEXT("niagara_get_component_debug_summary"); }
	virtual bool RequiresSave() const override { return false; }
};

/** List all NiagaraComponents in the current PIE/editor world, including transient components without level actors. */
class UEEDITORMCP_API FNiagaraListWorldComponentsAction : public FNiagaraAction
{
public:
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;

protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual FString GetActionName() const override { return TEXT("niagara_list_world_components"); }
	virtual bool RequiresSave() const override { return false; }
};

/** Advance matching NiagaraComponents in the current editor/runtime world and return particle diagnostics. */
class UEEDITORMCP_API FNiagaraAdvanceWorldComponentsAction : public FNiagaraAction
{
public:
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;

protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual FString GetActionName() const override { return TEXT("niagara_advance_world_components"); }
	virtual bool RequiresSave() const override { return false; }
};

/**
 * Seek the Niagara editor preview component for a system asset.
 *
 * Parameters:
 *   - asset_path (required): full content path of the UNiagaraSystem.
 *   - time_seconds (optional): preview time to seek to. Defaults to 0.
 *   - frame (optional): frame index; used when time_seconds is omitted.
 *   - fps (optional): frame rate for frame -> seconds conversion. Defaults to 30.
 *   - open_editor (optional bool, default true): open the Niagara editor if needed.
 *   - focus_editor (optional bool, default true): focus the editor tab/window.
 *   - reset_system (optional bool, default true): reinitialize before seeking.
 *   - seek_delta (optional number, default 1/60): desired-age seek step.
 *   - vector_parameters / position_parameters (optional): map of User parameter
 *       name to [x,y,z] preview override values.
 *
 * Returns preview component age, bounds, and emitter particle counts from the
 * Niagara editor preview component.
 */
class UEEDITORMCP_API FNiagaraPreviewSeekAction : public FNiagaraAction
{
public:
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;

protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual FString GetActionName() const override { return TEXT("niagara_preview_seek"); }
	virtual bool RequiresSave() const override { return false; }
};


/**
 * FNiagaraCreateSystemAction (write)
 *
 * Create a new UNiagaraSystem asset using UNiagaraSystemFactoryNew.
 * FactoryCreateNew is invoked directly (no ConfigureProperties), so no modal
 * asset-browser window is shown.
 *
 * Three composition modes (mutually exclusive; checked in this order):
 *   1. template_system_path set -> duplicate that system (Factory.SystemToCopy).
 *   2. emitter_asset_paths set  -> new system seeded with those emitter assets
 *        (Factory.EmittersToAddToNewSystem). Each path must be a UNiagaraEmitter.
 *   3. neither                  -> empty system.
 * In all cases the factory ends with RequestCompile(false).
 *
 * Parameters:
 *   - name (required): asset name (e.g. "NS_Explosion")
 *   - path (optional): content path (default: /Game/FX)
 *   - template_system_path (optional): UNiagaraSystem to duplicate
 *   - emitter_asset_paths (optional): array of UNiagaraEmitter content paths
 *   - if_exists (optional): error (default), overwrite, skip, or reuse.
 *       overwrite closes editors for the existing asset, deletes it first, and
 *       aborts if the old package cannot be removed cleanly.
 *
 * Returns:
 *   - name, path, object_path, mode, emitter_count
 */
class UEEDITORMCP_API FNiagaraCreateSystemAction : public FNiagaraAction
{
public:
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;

protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual FString GetActionName() const override { return TEXT("niagara_create_system"); }
};


/**
 * FNiagaraAddEmitterAction (write)
 *
 * Add a template UNiagaraEmitter asset into an existing UNiagaraSystem via
 * FNiagaraEditorUtilities::AddEmitterToSystem (a self-contained NIAGARAEDITOR_API
 * helper that handles KillSystemInstances / Modify / AddEmitterHandle /
 * RebuildEmitterNodes / SynchronizeOverviewGraphWithSystem). The system is then
 * recompiled (RequestCompile(false)) and marked dirty.
 *
 * Parameters:
 *   - system_path (required): content path of the target UNiagaraSystem
 *   - emitter_path (required): content path of the UNiagaraEmitter to add
 *   - create_copy (optional bool, default true): copy the emitter into the
 *       system rather than referencing it as an inheritance parent
 *
 * Returns:
 *   - system_path, emitter_path, emitter_handle_id, emitter_count
 */
class UEEDITORMCP_API FNiagaraAddEmitterAction : public FNiagaraAction
{
public:
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;

protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual FString GetActionName() const override { return TEXT("niagara_add_emitter"); }
};


/**
 * FNiagaraAddRendererAction (write)
 *
 * Add a renderer to an emitter inside a UNiagaraSystem via the self-contained
 * UNiagaraEmitter::AddRenderer (NIAGARA_API). This is the same call the engine's
 * UNiagaraEmitterFactoryNew uses to seed a default sprite renderer.
 *
 * Parameters:
 *   - system_path (required): content path of the target UNiagaraSystem
 *   - emitter_name (optional): name of the emitter handle; if omitted the system
 *       must contain exactly one emitter (which is then used)
 *   - renderer_type (required): "sprite" | "mesh" | "ribbon" | "light"
 *   - material_path (optional): UMaterialInterface to assign (sprite/ribbon)
 *   - mesh_path (optional): UStaticMesh to assign (mesh renderer)
 *
 * Returns:
 *   - system_path, emitter_name, renderer_type, renderer_class, renderer_count
 */
class UEEDITORMCP_API FNiagaraAddRendererAction : public FNiagaraAction
{
public:
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;

protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual FString GetActionName() const override { return TEXT("niagara_add_renderer"); }
};


/** Remove a renderer from an emitter by renderer_index or unique renderer_type. */
class UEEDITORMCP_API FNiagaraRemoveRendererAction : public FNiagaraAction
{
public:
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;

protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual FString GetActionName() const override { return TEXT("niagara_remove_renderer"); }
};


/** Read renderer classes, meshes, materials, and core attribute bindings. */
class UEEDITORMCP_API FNiagaraGetRendererSummaryAction : public FNiagaraAction
{
public:
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;

protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual FString GetActionName() const override { return TEXT("niagara_get_renderer_summary"); }
	virtual bool RequiresSave() const override { return false; }
};


/** Set a mesh renderer's static mesh slot and optional per-mesh transform. */
class UEEDITORMCP_API FNiagaraSetRendererMeshAction : public FNiagaraAction
{
public:
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;

protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual FString GetActionName() const override { return TEXT("niagara_set_renderer_mesh"); }
};


/** Set material on sprite/ribbon renderers or mesh override materials. */
class UEEDITORMCP_API FNiagaraSetRendererMaterialAction : public FNiagaraAction
{
public:
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;

protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual FString GetActionName() const override { return TEXT("niagara_set_renderer_material"); }
};


/** Set an FNiagaraVariableAttributeBinding property on a renderer. */
class UEEDITORMCP_API FNiagaraSetRendererBindingAction : public FNiagaraAction
{
public:
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;

protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual FString GetActionName() const override { return TEXT("niagara_set_renderer_binding"); }
};


/**
 * FNiagaraAddModuleAction (write)
 *
 * Add a module (UNiagaraScript with Module usage) into one stage of an emitter's
 * script stack via FNiagaraStackGraphUtilities::AddScriptModuleToStack
 * (NIAGARAEDITOR_API), the asset-level path used by InitializeEmitter. Module
 * inputs keep their script defaults (use set_module_input to override them).
 *
 * Parameters:
 *   - system_path (required): content path of the target UNiagaraSystem
 *   - emitter_name (optional): emitter handle name (default: the single emitter;
 *       ignored for system_spawn/system_update)
 *   - stage (required): "system_spawn" | "system_update" |
 *       "particle_spawn" | "particle_update" | "emitter_spawn" | "emitter_update"
 *   - module_script_path (required): content path of the module UNiagaraScript
 *   - target_index (optional int, default -1 = append)
 *
 * Returns:
 *   - system_path, emitter_name, stage, module_node_name, module_count
 */
class UEEDITORMCP_API FNiagaraAddModuleAction : public FNiagaraAction
{
public:
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;

protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual FString GetActionName() const override { return TEXT("niagara_add_module"); }
};

/** Remove a Niagara module function-call node from one script stack. */
class UEEDITORMCP_API FNiagaraRemoveModuleAction : public FNiagaraAction
{
public:
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;

protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual FString GetActionName() const override { return TEXT("niagara_remove_module"); }
};


/**
 * FNiagaraSetModuleInputAction (write)
 *
 * Override a single module input by writing the script's rapid iteration
 * parameter store (the stable 5.7 path, avoiding fragile typed override-pin
 * writes). Mirrors the engine's SetRapidIterationParameter helper.
 *
 * Parameters:
 *   - system_path (required): content path of the target UNiagaraSystem
 *   - emitter_name (optional): emitter handle name (default: the single emitter;
 *       ignored for system_spawn/system_update)
 *   - stage (required): "system_spawn" | "system_update" |
 *       "particle_spawn" | "particle_update" | "emitter_spawn" | "emitter_update"
 *   - module_name (required): the module's function-call node name in the stack
 *       (matches the node's display name, e.g. "SpawnRate")
 *   - input_name (required): the module input parameter name (e.g. "SpawnRate")
 *   - value_type (required): "float" | "int" | "bool" | "vec2" | "vec3" |
 *       "vec4" | "color"
 *   - value (required): number (float/int), bool, or array of numbers (vec/color)
 *
 * Returns:
 *   - system_path, emitter_name, stage, module_name, input_name, value_type
 */
class UEEDITORMCP_API FNiagaraSetModuleInputAction : public FNiagaraAction
{
public:
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;

protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual FString GetActionName() const override { return TEXT("niagara_set_module_input"); }
};


/** Set a reflected FVersionedNiagaraEmitterData property on an emitter inside a system. */
class UEEDITORMCP_API FNiagaraSetEmitterPropertyAction : public FNiagaraAction
{
public:
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;

protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual FString GetActionName() const override { return TEXT("niagara_set_emitter_property"); }
};


/** Set an int or enum static-switch input on a Niagara module, e.g. Collision's GPU Collision Type. */
class UEEDITORMCP_API FNiagaraSetModuleStaticIntAction : public FNiagaraAction
{
public:
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;

protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual FString GetActionName() const override { return TEXT("niagara_set_module_static_int"); }
};


/** Enable or disable a Niagara module function-call node, e.g. the Collision module behind summary checkboxes. */
class UEEDITORMCP_API FNiagaraSetModuleEnabledAction : public FNiagaraAction
{
public:
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;

protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual FString GetActionName() const override { return TEXT("niagara_set_module_enabled"); }
};


/** Read module input override pins, linked parameters, and dynamic-input bindings. */
class UEEDITORMCP_API FNiagaraGetModuleInputsAction : public FNiagaraAction
{
public:
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;

protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual FString GetActionName() const override { return TEXT("niagara_get_module_inputs"); }
	virtual bool RequiresSave() const override { return false; }
};


/** Set a module input to a linked parameter or dynamic-input script through stack override pins. */
class UEEDITORMCP_API FNiagaraSetModuleInputBindingAction : public FNiagaraAction
{
public:
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;

protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual FString GetActionName() const override { return TEXT("niagara_set_module_input_binding"); }
};

/** Edit the float curve used by a module input dynamic-input chain, e.g. FloatFromCurve nested under VectorFromFloat. */
class UEEDITORMCP_API FNiagaraSetModuleFloatCurveAction : public FNiagaraAction
{
public:
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;

protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual FString GetActionName() const override { return TEXT("niagara_set_module_float_curve"); }
};
/** Set the Data Channel reader options on a specific Niagara stack module input. */
class UEEDITORMCP_API FNiagaraSetDataChannelReaderAction : public FNiagaraAction
{
public:
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;

protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual FString GetActionName() const override { return TEXT("niagara_set_data_channel_reader"); }
};
/** Add scratch-pad modules that make an emitter spawn particles from a Niagara Data Channel. */
class UEEDITORMCP_API FNiagaraAddDataChannelSpawnHandlerAction : public FNiagaraAction
{
public:
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;

protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual FString GetActionName() const override { return TEXT("niagara_add_data_channel_spawn_handler"); }
};
/** Create or update a Niagara Data Channel asset with a caller-provided schema. */
class UEEDITORMCP_API FNiagaraCreateDataChannelAction : public FNiagaraAction
{
public:
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;

protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual FString GetActionName() const override { return TEXT("niagara_create_data_channel"); }
};

/** Write test rows to a Niagara Data Channel using a caller-provided value map. */
class UEEDITORMCP_API FNiagaraWriteDataChannelTestAction : public FNiagaraAction
{
public:
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;

protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual FString GetActionName() const override { return TEXT("niagara_write_data_channel_test"); }
	virtual bool RequiresSave() const override { return false; }
};
