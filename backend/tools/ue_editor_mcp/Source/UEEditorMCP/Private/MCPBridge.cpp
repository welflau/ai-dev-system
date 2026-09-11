// Copyright (c) 2025 zolnoor. All rights reserved.

#include "MCPBridge.h"
#include "MCPServer.h"
#include "Actions/EditorAction.h"
#include "Actions/BlueprintActions.h"
#include "Actions/EditorActions.h"
#include "Actions/NodeActions.h"
#include "Actions/GraphActions.h"
#include "Actions/ProjectActions.h"
#include "Actions/UMGActions.h"
#include "Actions/MaterialActions.h"
#include "Actions/LayoutActions.h"
#include "Actions/EditorDiffActions.h"
#include "Actions/NiagaraActions.h"
#include "Actions/ToolsetBridgeActions.h"
#include "Engine/World.h"
#include "GameFramework/Actor.h"
#include "Kismet/GameplayStatics.h"
#include "Engine/Blueprint.h"
#include "AssetRegistry/AssetRegistryModule.h"
#include "Editor.h"
#include "Interfaces/IPluginManager.h"
#include "Misc/FileHelper.h"
#include "Misc/Paths.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"

namespace
{
constexpr TCHAR BridgeConfigFileName[] = TEXT("UEEditorMCP.config.json");

int32 LoadConfiguredBridgePort(int32 FallbackPort)
{
	const TSharedPtr<IPlugin> Plugin = IPluginManager::Get().FindPlugin(TEXT("UEEditorMCP"));
	if (!Plugin.IsValid())
	{
		UE_LOG(LogMCP, Warning, TEXT("UEEditorMCP: Plugin root unavailable; using fallback port %d"), FallbackPort);
		return FallbackPort;
	}

	const FString ConfigPath = FPaths::Combine(Plugin->GetBaseDir(), BridgeConfigFileName);
	FString ConfigText;
	if (!FFileHelper::LoadFileToString(ConfigText, *ConfigPath))
	{
		UE_LOG(LogMCP, Warning, TEXT("UEEditorMCP: Config not found at %s; using fallback port %d"), *ConfigPath, FallbackPort);
		return FallbackPort;
	}

	TSharedPtr<FJsonObject> ConfigObject;
	const TSharedRef<TJsonReader<>> Reader = TJsonReaderFactory<>::Create(ConfigText);
	if (!FJsonSerializer::Deserialize(Reader, ConfigObject) || !ConfigObject.IsValid())
	{
		UE_LOG(LogMCP, Warning, TEXT("UEEditorMCP: Invalid config JSON at %s; using fallback port %d"), *ConfigPath, FallbackPort);
		return FallbackPort;
	}

	double ConfiguredPort = 0.0;
	if (!ConfigObject->TryGetNumberField(TEXT("bridge_port"), ConfiguredPort) || ConfiguredPort < 1.0 || ConfiguredPort > 65535.0)
	{
		UE_LOG(LogMCP, Warning, TEXT("UEEditorMCP: Invalid bridge_port in %s; using fallback port %d"), *ConfigPath, FallbackPort);
		return FallbackPort;
	}

	return static_cast<int32>(ConfiguredPort);
}
}

UMCPBridge::UMCPBridge()
	: Server(nullptr)
{
}

void UMCPBridge::Initialize(FSubsystemCollectionBase& Collection)
{
	Super::Initialize(Collection);

	UE_LOG(LogMCP, Log, TEXT("UEEditorMCP: Bridge initializing"));

	// Register action handlers
	RegisterActions();

	// Start the TCP server using the plugin-root configuration.
	const int32 BridgePort = LoadConfiguredBridgePort(DefaultPort);
	Server = new FMCPServer(this, BridgePort);
	if (Server->Start())
	{
		UE_LOG(LogMCP, Log, TEXT("UEEditorMCP: Server started on configured port %d"), BridgePort);
	}
	else
	{
		UE_LOG(LogMCP, Error, TEXT("UEEditorMCP: Failed to start server"));
	}
}

void UMCPBridge::Deinitialize()
{
	UE_LOG(LogMCP, Log, TEXT("UEEditorMCP: Bridge deinitializing"));

	// Stop the server
	if (Server)
	{
		Server->Stop();
		delete Server;
		Server = nullptr;
	}

	// Clear action handlers
	ActionHandlers.Empty();

	Super::Deinitialize();
}

void UMCPBridge::RegisterActions()
{
	// =========================================================================
	// Blueprint Actions
	// =========================================================================
	ActionHandlers.Add(TEXT("create_blueprint"), MakeShared<FCreateBlueprintAction>());
	ActionHandlers.Add(TEXT("compile_blueprint"), MakeShared<FCompileBlueprintAction>());
	ActionHandlers.Add(TEXT("refresh_blueprint_nodes"), MakeShared<FRefreshBlueprintNodesAction>());
	ActionHandlers.Add(TEXT("repair_blueprint_component_references"), MakeShared<FRepairBlueprintComponentReferencesAction>());
	ActionHandlers.Add(TEXT("add_component_to_blueprint"), MakeShared<FAddComponentToBlueprintAction>());
	ActionHandlers.Add(TEXT("remove_component_from_blueprint"), MakeShared<FRemoveComponentFromBlueprintAction>());
	ActionHandlers.Add(TEXT("spawn_blueprint_actor"), MakeShared<FSpawnBlueprintActorAction>());
	ActionHandlers.Add(TEXT("set_component_property"), MakeShared<FSetComponentPropertyAction>());
	ActionHandlers.Add(TEXT("set_static_mesh_properties"), MakeShared<FSetStaticMeshPropertiesAction>());
	ActionHandlers.Add(TEXT("set_skeletal_mesh_properties"), MakeShared<FSetSkeletalMeshPropertiesAction>());
	ActionHandlers.Add(TEXT("set_physics_properties"), MakeShared<FSetPhysicsPropertiesAction>());
	ActionHandlers.Add(TEXT("set_blueprint_property"), MakeShared<FSetBlueprintPropertyAction>());
	ActionHandlers.Add(TEXT("create_colored_material"), MakeShared<FCreateColoredMaterialAction>());
	ActionHandlers.Add(TEXT("set_blueprint_parent_class"), MakeShared<FSetBlueprintParentClassAction>());
	ActionHandlers.Add(TEXT("add_blueprint_interface"), MakeShared<FAddBlueprintInterfaceAction>());
	ActionHandlers.Add(TEXT("remove_blueprint_interface"), MakeShared<FRemoveBlueprintInterfaceAction>());

	// =========================================================================
	// Editor Actions (actors, viewport, save)
	// =========================================================================
	ActionHandlers.Add(TEXT("get_actors_in_level"), MakeShared<FGetActorsInLevelAction>());
	ActionHandlers.Add(TEXT("find_actors_by_name"), MakeShared<FFindActorsByNameAction>());
	ActionHandlers.Add(TEXT("get_runtime_widgets"), MakeShared<FGetRuntimeWidgetsAction>());
	ActionHandlers.Add(TEXT("spawn_actor"), MakeShared<FSpawnActorAction>());
	ActionHandlers.Add(TEXT("delete_actor"), MakeShared<FDeleteActorAction>());
	ActionHandlers.Add(TEXT("set_actor_transform"), MakeShared<FSetActorTransformAction>());
	ActionHandlers.Add(TEXT("get_actor_properties"), MakeShared<FGetActorPropertiesAction>());
	ActionHandlers.Add(TEXT("set_actor_property"), MakeShared<FSetActorPropertyAction>());
	ActionHandlers.Add(TEXT("focus_viewport"), MakeShared<FFocusViewportAction>());
	ActionHandlers.Add(TEXT("get_viewport_transform"), MakeShared<FGetViewportTransformAction>());
	ActionHandlers.Add(TEXT("set_viewport_transform"), MakeShared<FSetViewportTransformAction>());
	ActionHandlers.Add(TEXT("save_all"), MakeShared<FSaveAllAction>());
	ActionHandlers.Add(TEXT("list_assets"), MakeShared<FListAssetsAction>());
	ActionHandlers.Add(TEXT("rename_assets"), MakeShared<FRenameAssetsAction>());
	ActionHandlers.Add(TEXT("plan_asset_renames"), MakeShared<FPlanAssetRenamesAction>());
	ActionHandlers.Add(TEXT("delete_assets"), MakeShared<FDeleteAssetsAction>());
	ActionHandlers.Add(TEXT("delete_empty_directories"), MakeShared<FDeleteEmptyDirectoriesAction>());
	ActionHandlers.Add(TEXT("process_asset_maintenance_manifest"), MakeShared<FProcessAssetMaintenanceManifestAction>());
	ActionHandlers.Add(TEXT("get_selected_asset_thumbnail"), MakeShared<FGetSelectedAssetThumbnailAction>());
	ActionHandlers.Add(TEXT("capture_editor_screenshot"), MakeShared<FCaptureEditorScreenshotAction>());
	ActionHandlers.Add(TEXT("get_selected_assets"), MakeShared<FGetSelectedAssetsAction>());
	ActionHandlers.Add(TEXT("get_blueprint_summary"), MakeShared<FGetBlueprintSummaryAction>());
	ActionHandlers.Add(TEXT("describe_blueprint_full"), MakeShared<FDescribeFullAction>());
	ActionHandlers.Add(TEXT("get_editor_logs"), MakeShared<FGetEditorLogsAction>());
	ActionHandlers.Add(TEXT("get_unreal_logs"), MakeShared<FGetUnrealLogsAction>());
	ActionHandlers.Add(TEXT("batch_execute"), MakeShared<FBatchExecuteAction>());
	ActionHandlers.Add(TEXT("is_ready"), MakeShared<FEditorIsReadyAction>());
	ActionHandlers.Add(TEXT("request_shutdown"), MakeShared<FRequestEditorShutdownAction>());
	ActionHandlers.Add(TEXT("exec_console_command"), MakeShared<FExecConsoleCommandAction>());
	ActionHandlers.Add(TEXT("live_coding_compile"), MakeShared<FLiveCodingCompileAction>());
	ActionHandlers.Add(TEXT("live_coding_status"), MakeShared<FLiveCodingStatusAction>());
	ActionHandlers.Add(TEXT("list_toolsets"), MakeShared<FListToolsetsAction>());
	ActionHandlers.Add(TEXT("describe_toolset"), MakeShared<FDescribeToolsetAction>());
	ActionHandlers.Add(TEXT("call_tool"), MakeShared<FCallToolAction>());
	ActionHandlers.Add(TEXT("tool_job_status"), MakeShared<FToolJobStatusAction>());

	// =========================================================================
	// Layout Actions - Auto-arrange Blueprint graph nodes
	// =========================================================================
	ActionHandlers.Add(TEXT("auto_layout_selected"), MakeShared<FAutoLayoutSelectedAction>());
	ActionHandlers.Add(TEXT("auto_layout_subtree"), MakeShared<FAutoLayoutSubtreeAction>());
	ActionHandlers.Add(TEXT("auto_layout_blueprint"), MakeShared<FAutoLayoutBlueprintAction>());
	ActionHandlers.Add(TEXT("layout_and_comment"), MakeShared<FLayoutAndCommentAction>());

	// =========================================================================
	// Node Actions - Graph Operations
	// =========================================================================
	ActionHandlers.Add(TEXT("connect_blueprint_nodes"), MakeShared<FConnectBlueprintNodesAction>());
	ActionHandlers.Add(TEXT("find_blueprint_nodes"), MakeShared<FFindBlueprintNodesAction>());
	ActionHandlers.Add(TEXT("delete_blueprint_node"), MakeShared<FDeleteBlueprintNodeAction>());
	ActionHandlers.Add(TEXT("get_node_pins"), MakeShared<FGetNodePinsAction>());
	ActionHandlers.Add(TEXT("describe_graph"), MakeShared<FDescribeGraphAction>());
	ActionHandlers.Add(TEXT("get_selected_nodes"), MakeShared<FGetSelectedNodesAction>());
	ActionHandlers.Add(TEXT("collapse_selection_to_function"), MakeShared<FCollapseSelectionToFunctionAction>());
	ActionHandlers.Add(TEXT("collapse_selection_to_macro"), MakeShared<FCollapseSelectionToMacroAction>());
	ActionHandlers.Add(TEXT("set_selected_nodes"), MakeShared<FSetSelectedNodesAction>());
	ActionHandlers.Add(TEXT("batch_select_and_act"), MakeShared<FBatchSelectAndActAction>());

	// =========================================================================
	// Node Actions - Event Nodes
	// =========================================================================
	ActionHandlers.Add(TEXT("add_blueprint_event_node"), MakeShared<FAddBlueprintEventNodeAction>());
	ActionHandlers.Add(TEXT("add_blueprint_input_action_node"), MakeShared<FAddBlueprintInputActionNodeAction>());
	ActionHandlers.Add(TEXT("add_enhanced_input_action_node"), MakeShared<FAddEnhancedInputActionNodeAction>());
	ActionHandlers.Add(TEXT("add_blueprint_custom_event"), MakeShared<FAddBlueprintCustomEventAction>());
	ActionHandlers.Add(TEXT("add_custom_event_for_delegate"), MakeShared<FAddCustomEventForDelegateAction>());

	// =========================================================================
	// Node Actions - Variable Nodes
	// =========================================================================
	ActionHandlers.Add(TEXT("add_blueprint_variable"), MakeShared<FAddBlueprintVariableAction>());
	ActionHandlers.Add(TEXT("add_blueprint_variable_get"), MakeShared<FAddBlueprintVariableGetAction>());
	ActionHandlers.Add(TEXT("add_blueprint_variable_set"), MakeShared<FAddBlueprintVariableSetAction>());
	ActionHandlers.Add(TEXT("set_node_pin_default"), MakeShared<FSetNodePinDefaultAction>());

	// =========================================================================
	// Node Actions - Function Nodes
	// =========================================================================
	ActionHandlers.Add(TEXT("add_blueprint_function_node"), MakeShared<FAddBlueprintFunctionNodeAction>());
	ActionHandlers.Add(TEXT("add_blueprint_self_reference"), MakeShared<FAddBlueprintSelfReferenceAction>());
	ActionHandlers.Add(TEXT("add_blueprint_get_self_component_reference"), MakeShared<FAddBlueprintGetSelfComponentReferenceAction>());
	ActionHandlers.Add(TEXT("add_blueprint_branch_node"), MakeShared<FAddBlueprintBranchNodeAction>());
	ActionHandlers.Add(TEXT("add_blueprint_cast_node"), MakeShared<FAddBlueprintCastNodeAction>());
	ActionHandlers.Add(TEXT("add_blueprint_get_subsystem_node"), MakeShared<FAddBlueprintGetSubsystemNodeAction>());

	// =========================================================================
	// Node Actions - Blueprint Function Graph
	// =========================================================================
	ActionHandlers.Add(TEXT("create_blueprint_function"), MakeShared<FCreateBlueprintFunctionAction>());
	ActionHandlers.Add(TEXT("add_blueprint_override_function"), MakeShared<FAddBlueprintOverrideFunctionAction>());

	// =========================================================================
	// Node Actions - Event Dispatchers

	// =========================================================================
	ActionHandlers.Add(TEXT("add_event_dispatcher"), MakeShared<FAddEventDispatcherAction>());
	ActionHandlers.Add(TEXT("call_event_dispatcher"), MakeShared<FCallEventDispatcherAction>());
	ActionHandlers.Add(TEXT("bind_event_dispatcher"), MakeShared<FBindEventDispatcherAction>());
	ActionHandlers.Add(TEXT("create_event_delegate"), MakeShared<FCreateEventDelegateAction>());
	ActionHandlers.Add(TEXT("bind_component_event"), MakeShared<FBindComponentEventAction>());
	ActionHandlers.Add(TEXT("bind_uobject_delegate"), MakeShared<FBindUObjectDelegateAction>());

	// =========================================================================
	// Node Actions - Spawn Actor Nodes
	// =========================================================================
	ActionHandlers.Add(TEXT("add_spawn_actor_from_class_node"), MakeShared<FAddSpawnActorFromClassNodeAction>());
	ActionHandlers.Add(TEXT("call_blueprint_function"), MakeShared<FCallBlueprintFunctionAction>());

	// =========================================================================
	// Node Actions - Async Action Nodes (Third-party plugin support)
	// =========================================================================
	ActionHandlers.Add(TEXT("add_async_action_node"), MakeShared<FAddAsyncActionNodeAction>());

	// =========================================================================
	// Self-Evolution: Dynamic Node Discovery & Creation
	// =========================================================================
	ActionHandlers.Add(TEXT("search_catalog"), MakeShared<FSearchCatalogAction>());
	ActionHandlers.Add(TEXT("add_generic_node"), MakeShared<FAddGenericNodeAction>());
	ActionHandlers.Add(TEXT("add_level_actor_reference_node"), MakeShared<FAddLevelActorReferenceNodeAction>());
	ActionHandlers.Add(TEXT("suggest_next"), MakeShared<FSuggestNextAction>());

	// =========================================================================
	// Node Actions - External Object Property Nodes
	// =========================================================================
	ActionHandlers.Add(TEXT("set_object_property"), MakeShared<FSetObjectPropertyAction>());

	// =========================================================================
	// Node Actions - Sequence Node
	// =========================================================================
	ActionHandlers.Add(TEXT("add_sequence_node"), MakeShared<FAddSequenceNodeAction>());

	// =========================================================================
	// Node Actions - Macro Instance Nodes
	// =========================================================================
	ActionHandlers.Add(TEXT("add_macro_instance_node"), MakeShared<FAddMacroInstanceNodeAction>());

	// =========================================================================
	// Node Actions - Struct Nodes
	// =========================================================================
	ActionHandlers.Add(TEXT("add_make_struct_node"), MakeShared<FAddMakeStructNodeAction>());
	ActionHandlers.Add(TEXT("add_break_struct_node"), MakeShared<FAddBreakStructNodeAction>());

	// =========================================================================
	// Node Actions - Switch Nodes
	// =========================================================================
	ActionHandlers.Add(TEXT("add_switch_on_string_node"), MakeShared<FAddSwitchOnStringNodeAction>());
	ActionHandlers.Add(TEXT("add_switch_on_int_node"), MakeShared<FAddSwitchOnIntNodeAction>());
	ActionHandlers.Add(TEXT("add_function_local_variable"), MakeShared<FAddFunctionLocalVariableAction>());
	ActionHandlers.Add(TEXT("set_blueprint_variable_default"), MakeShared<FSetBlueprintVariableDefaultAction>());
	ActionHandlers.Add(TEXT("add_blueprint_comment"), MakeShared<FAddBlueprintCommentAction>());
	ActionHandlers.Add(TEXT("auto_comment"), MakeShared<FAutoCommentAction>());

	// =========================================================================
	// Node Actions - P1: Variable & Function Management
	// =========================================================================
	ActionHandlers.Add(TEXT("delete_blueprint_variable"), MakeShared<FDeleteBlueprintVariableAction>());
	ActionHandlers.Add(TEXT("rename_blueprint_variable"), MakeShared<FRenameBlueprintVariableAction>());
	ActionHandlers.Add(TEXT("set_variable_metadata"), MakeShared<FSetVariableMetadataAction>());
	ActionHandlers.Add(TEXT("delete_blueprint_function"), MakeShared<FDeleteBlueprintFunctionAction>());
	ActionHandlers.Add(TEXT("rename_blueprint_function"), MakeShared<FRenameBlueprintFunctionAction>());
	ActionHandlers.Add(TEXT("rename_blueprint_macro"), MakeShared<FRenameBlueprintMacroAction>());

	// =========================================================================
	// Node Actions - P2: Graph Operation Enhancements
	// =========================================================================
	ActionHandlers.Add(TEXT("disconnect_blueprint_pin"), MakeShared<FDisconnectBlueprintPinAction>());
	ActionHandlers.Add(TEXT("move_node"), MakeShared<FMoveNodeAction>());
	ActionHandlers.Add(TEXT("add_reroute_node"), MakeShared<FAddRerouteNodeAction>());

	// =========================================================================
	// P3: Graph Patch System
	// =========================================================================
	ActionHandlers.Add(TEXT("describe_graph_enhanced"), MakeShared<FGraphDescribeEnhancedAction>());
	ActionHandlers.Add(TEXT("apply_graph_patch"), MakeShared<FApplyPatchAction>());
	ActionHandlers.Add(TEXT("validate_graph_patch"), MakeShared<FValidatePatchAction>());

	// =========================================================================
	// P4: Cross-Graph Node Transfer
	// =========================================================================
	ActionHandlers.Add(TEXT("export_nodes_to_text"), MakeShared<FExportNodesToTextAction>());
	ActionHandlers.Add(TEXT("import_nodes_from_text"), MakeShared<FImportNodesFromTextAction>());

	// =========================================================================
	// Project Actions (Input Mappings, Enhanced Input)
	// =========================================================================
	ActionHandlers.Add(TEXT("create_input_mapping"), MakeShared<FCreateInputMappingAction>());
	ActionHandlers.Add(TEXT("create_input_action"), MakeShared<FCreateInputActionAction>());
	ActionHandlers.Add(TEXT("create_input_mapping_context"), MakeShared<FCreateInputMappingContextAction>());
	ActionHandlers.Add(TEXT("add_key_mapping_to_context"), MakeShared<FAddKeyMappingToContextAction>());
	ActionHandlers.Add(TEXT("remove_key_mapping_from_context"), MakeShared<FRemoveKeyMappingFromContextAction>());

	// =========================================================================
	// UMG Actions (Widget Blueprints)
	// =========================================================================
	ActionHandlers.Add(TEXT("create_umg_widget_blueprint"), MakeShared<FCreateUMGWidgetBlueprintAction>());
	ActionHandlers.Add(TEXT("add_text_block_to_widget"), MakeShared<FAddTextBlockToWidgetAction>());
	ActionHandlers.Add(TEXT("add_button_to_widget"), MakeShared<FAddButtonToWidgetAction>());
	ActionHandlers.Add(TEXT("add_image_to_widget"), MakeShared<FAddImageToWidgetAction>());
	ActionHandlers.Add(TEXT("add_border_to_widget"), MakeShared<FAddBorderToWidgetAction>());
	ActionHandlers.Add(TEXT("add_overlay_to_widget"), MakeShared<FAddOverlayToWidgetAction>());
	ActionHandlers.Add(TEXT("add_horizontal_box_to_widget"), MakeShared<FAddHorizontalBoxToWidgetAction>());
	ActionHandlers.Add(TEXT("add_vertical_box_to_widget"), MakeShared<FAddVerticalBoxToWidgetAction>());
	ActionHandlers.Add(TEXT("add_slider_to_widget"), MakeShared<FAddSliderToWidgetAction>());
	ActionHandlers.Add(TEXT("add_progress_bar_to_widget"), MakeShared<FAddProgressBarToWidgetAction>());
	ActionHandlers.Add(TEXT("add_size_box_to_widget"), MakeShared<FAddSizeBoxToWidgetAction>());
	ActionHandlers.Add(TEXT("add_scale_box_to_widget"), MakeShared<FAddScaleBoxToWidgetAction>());
	ActionHandlers.Add(TEXT("add_canvas_panel_to_widget"), MakeShared<FAddCanvasPanelToWidgetAction>());
	ActionHandlers.Add(TEXT("add_combo_box_to_widget"), MakeShared<FAddComboBoxToWidgetAction>());
	ActionHandlers.Add(TEXT("add_check_box_to_widget"), MakeShared<FAddCheckBoxToWidgetAction>());
	ActionHandlers.Add(TEXT("add_spin_box_to_widget"), MakeShared<FAddSpinBoxToWidgetAction>());
	ActionHandlers.Add(TEXT("add_editable_text_box_to_widget"), MakeShared<FAddEditableTextBoxToWidgetAction>());
	ActionHandlers.Add(TEXT("bind_widget_event"), MakeShared<FBindWidgetEventAction>());
	ActionHandlers.Add(TEXT("add_widget_to_viewport"), MakeShared<FAddWidgetToViewportAction>());
	ActionHandlers.Add(TEXT("set_text_block_binding"), MakeShared<FSetTextBlockBindingAction>());
	ActionHandlers.Add(TEXT("list_widget_components"), MakeShared<FListWidgetComponentsAction>());
	ActionHandlers.Add(TEXT("reparent_widgets"), MakeShared<FReparentWidgetsAction>());
	ActionHandlers.Add(TEXT("set_widget_properties"), MakeShared<FSetWidgetPropertiesAction>());
	ActionHandlers.Add(TEXT("get_widget_tree"), MakeShared<FGetWidgetTreeAction>());
	ActionHandlers.Add(TEXT("delete_widget_from_blueprint"), MakeShared<FDeleteWidgetFromBlueprintAction>());
	ActionHandlers.Add(TEXT("rename_widget_in_blueprint"), MakeShared<FRenameWidgetInBlueprintAction>());
	ActionHandlers.Add(TEXT("add_widget_child"), MakeShared<FAddWidgetChildAction>());
	ActionHandlers.Add(TEXT("delete_umg_widget_blueprint"), MakeShared<FDeleteUMGWidgetBlueprintAction>());
	ActionHandlers.Add(TEXT("set_combo_box_options"), MakeShared<FSetComboBoxOptionsAction>());
	ActionHandlers.Add(TEXT("set_widget_text"), MakeShared<FSetWidgetTextAction>());
	ActionHandlers.Add(TEXT("set_slider_properties"), MakeShared<FSetSliderPropertiesAction>());
	ActionHandlers.Add(TEXT("add_generic_widget_to_widget"), MakeShared<FAddGenericWidgetAction>());

	// MVVM Actions
	ActionHandlers.Add(TEXT("mvvm_add_viewmodel"), MakeShared<FMVVMAddViewModelAction>());
	ActionHandlers.Add(TEXT("mvvm_add_binding"), MakeShared<FMVVMAddBindingAction>());
	ActionHandlers.Add(TEXT("mvvm_add_event"), MakeShared<FMVVMAddEventAction>());
	ActionHandlers.Add(TEXT("mvvm_remove_event"), MakeShared<FMVVMRemoveEventAction>());
	ActionHandlers.Add(TEXT("mvvm_get_bindings"), MakeShared<FMVVMGetBindingsAction>());
	ActionHandlers.Add(TEXT("mvvm_remove_binding"), MakeShared<FMVVMRemoveBindingAction>());
	ActionHandlers.Add(TEXT("mvvm_remove_viewmodel"), MakeShared<FMVVMRemoveViewModelAction>());

	// Widget Is Variable
	ActionHandlers.Add(TEXT("set_widget_is_variable"), MakeShared<FSetWidgetIsVariableAction>());

	// Widget Tree Repair
	ActionHandlers.Add(TEXT("purge_panel_orphans"), MakeShared<FPurgePanelOrphansAction>());

	// Widget instance reflected UPROPERTY writer (FLinearColor / FVector2D / FName / etc.)
	ActionHandlers.Add(TEXT("set_widget_reflected_property"), MakeShared<FSetWidgetReflectedPropertyAction>());
	ActionHandlers.Add(TEXT("remove_widget_delegate_bindings"), MakeShared<FRemoveWidgetDelegateBindingsAction>());

	// =========================================================================
	// Material Actions (Materials, Shaders, Post-Process)
	// =========================================================================

	ActionHandlers.Add(TEXT("create_material"), MakeShared<FCreateMaterialAction>());
	ActionHandlers.Add(TEXT("set_material_property"), MakeShared<FSetMaterialPropertyAction>());
	ActionHandlers.Add(TEXT("list_material_expression_classes"), MakeShared<FListMaterialExpressionClassesAction>());
	ActionHandlers.Add(TEXT("add_material_expression"), MakeShared<FAddMaterialExpressionAction>());
	ActionHandlers.Add(TEXT("connect_material_expressions"), MakeShared<FConnectMaterialExpressionsAction>());
	ActionHandlers.Add(TEXT("connect_to_material_output"), MakeShared<FConnectToMaterialOutputAction>());
	ActionHandlers.Add(TEXT("set_material_expression_property"), MakeShared<FSetMaterialExpressionPropertyAction>());
	ActionHandlers.Add(TEXT("compile_material"), MakeShared<FCompileMaterialAction>());
	ActionHandlers.Add(TEXT("create_material_instance"), MakeShared<FCreateMaterialInstanceAction>());
	ActionHandlers.Add(TEXT("create_post_process_volume"), MakeShared<FCreatePostProcessVolumeAction>());
	// Phase 4 Material Actions
	ActionHandlers.Add(TEXT("get_material_summary"), MakeShared<FGetMaterialSummaryAction>());
	ActionHandlers.Add(TEXT("remove_material_expression"), MakeShared<FRemoveMaterialExpressionAction>());
	ActionHandlers.Add(TEXT("auto_layout_material"), MakeShared<FAutoLayoutMaterialAction>());
	ActionHandlers.Add(TEXT("auto_comment_material"), MakeShared<FAutoCommentMaterialAction>());
	ActionHandlers.Add(TEXT("get_material_selected_nodes"), MakeShared<FGetMaterialSelectedNodesAction>());
	// Phase 5 Material Actions
	ActionHandlers.Add(TEXT("apply_material_to_component"), MakeShared<FApplyMaterialToComponentAction>());
	ActionHandlers.Add(TEXT("apply_material_to_actor"), MakeShared<FApplyMaterialToActorAction>());
	ActionHandlers.Add(TEXT("refresh_material_editor"), MakeShared<FRefreshMaterialEditorAction>());

	// =========================================================================
	// Diff Actions (Source Control)
	// =========================================================================
	ActionHandlers.Add(TEXT("diff_against_depot"), MakeShared<FDiffAgainstDepotAction>());
	ActionHandlers.Add(TEXT("get_asset_history"), MakeShared<FGetAssetHistoryAction>());

	// =========================================================================
	// P6: PIE Control Actions
	// =========================================================================
	ActionHandlers.Add(TEXT("start_pie"), MakeShared<FStartPIEAction>());
	ActionHandlers.Add(TEXT("stop_pie"), MakeShared<FStopPIEAction>());
	ActionHandlers.Add(TEXT("get_pie_state"), MakeShared<FGetPIEStateAction>());

	// =========================================================================
	// P6: Log Enhancement Actions
	// =========================================================================
	ActionHandlers.Add(TEXT("clear_logs"), MakeShared<FClearLogsAction>());
	ActionHandlers.Add(TEXT("assert_log"), MakeShared<FAssertLogAction>());

	// =========================================================================
	// P6: Outliner Management Actions
	// =========================================================================
	ActionHandlers.Add(TEXT("rename_actor_label"), MakeShared<FRenameActorLabelAction>());
	ActionHandlers.Add(TEXT("set_actor_folder"), MakeShared<FSetActorFolderAction>());
	ActionHandlers.Add(TEXT("select_actors"), MakeShared<FSelectActorsAction>());
	ActionHandlers.Add(TEXT("get_outliner_tree"), MakeShared<FGetOutlinerTreeAction>());

	// =========================================================================
	// P7: Asset Editor Actions
	// =========================================================================
	ActionHandlers.Add(TEXT("open_asset_editor"), MakeShared<FOpenAssetEditorAction>());

	// =========================================================================
	// P8: PIE Automation Test Actions（关卡切换 + 输入模拟）
	// =========================================================================
	ActionHandlers.Add(TEXT("open_level"),                MakeShared<FOpenLevelAction>());
	ActionHandlers.Add(TEXT("create_level"),              MakeShared<FCreateLevelAction>());
	ActionHandlers.Add(TEXT("duplicate_asset"),           MakeShared<FDuplicateAssetAction>());
	ActionHandlers.Add(TEXT("set_world_settings_class"),  MakeShared<FSetWorldSettingsClassAction>());
	ActionHandlers.Add(TEXT("simulate_input"),            MakeShared<FSimulateInputAction>());

	// =========================================================================
	// P9: Asset Property Editing — DataAsset 直写 / 直读
	// =========================================================================
	ActionHandlers.Add(TEXT("set_data_asset_property"), MakeShared<FSetDataAssetPropertyAction>());
	ActionHandlers.Add(TEXT("get_data_asset_property"), MakeShared<FGetDataAssetPropertyAction>());
	ActionHandlers.Add(TEXT("get_blueprint_cdo_gameplay_tags"), MakeShared<FGetBlueprintCDOGameplayTagsAction>());
	ActionHandlers.Add(TEXT("configure_gameplay_effect_target_tags"), MakeShared<FConfigureGameplayEffectTargetTagsAction>());
	ActionHandlers.Add(TEXT("configure_gameplay_effect_ignore_tags"), MakeShared<FConfigureGameplayEffectIgnoreTagsAction>());
	ActionHandlers.Add(TEXT("set_gameplay_effect_modifier_scalable_float"), MakeShared<FSetGameplayEffectModifierScalableFloatAction>());
	ActionHandlers.Add(TEXT("create_data_asset"),       MakeShared<FCreateDataAssetAction>());
	ActionHandlers.Add(TEXT("create_data_table"),       MakeShared<FCreateDataTableAction>());
	ActionHandlers.Add(TEXT("save_loaded_asset"),       MakeShared<FSaveLoadedAssetAction>());

	// =========================================================================
	// P10: DataTable Row CRUD — 增删改查行数据
	// =========================================================================
	ActionHandlers.Add(TEXT("data_table_get_rows"),          MakeShared<FDataTableGetRowsAction>());
	ActionHandlers.Add(TEXT("data_table_add_row"),           MakeShared<FDataTableAddRowAction>());
	ActionHandlers.Add(TEXT("data_table_set_row_property"),  MakeShared<FDataTableSetRowPropertyAction>());

	// =========================================================================
	// P11: Niagara — AssetRegistry discovery + read-only introspection +
	// system composition (create / create-from-template / add-emitter) +
	// from-zero stack construction (add-renderer / add-module / set-module-input).
	// (UE 5.7: typed override-pin writes remain unavailable; module inputs are
	//  written via the rapid-iteration parameter store — see NiagaraActions.h)
	// =========================================================================
	ActionHandlers.Add(TEXT("niagara_find_scripts"),             MakeShared<FNiagaraFindScriptsAction>());
	ActionHandlers.Add(TEXT("niagara_get_script_digest"),        MakeShared<FNiagaraGetScriptDigestAction>());
	ActionHandlers.Add(TEXT("niagara_get_system_summary"),       MakeShared<FNiagaraGetSystemSummaryAction>());
	ActionHandlers.Add(TEXT("niagara_set_user_parameter"),       MakeShared<FNiagaraSetUserParameterAction>());
	ActionHandlers.Add(TEXT("niagara_get_compile_diagnostics"),  MakeShared<FNiagaraGetCompileDiagnosticsAction>());
	ActionHandlers.Add(TEXT("niagara_spawn_system_actor"),       MakeShared<FNiagaraSpawnSystemActorAction>());
	ActionHandlers.Add(TEXT("niagara_get_component_debug_summary"), MakeShared<FNiagaraGetComponentDebugSummaryAction>());
	ActionHandlers.Add(TEXT("niagara_list_world_components"), MakeShared<FNiagaraListWorldComponentsAction>());
	ActionHandlers.Add(TEXT("niagara_advance_world_components"), MakeShared<FNiagaraAdvanceWorldComponentsAction>());
	ActionHandlers.Add(TEXT("niagara_preview_seek"),             MakeShared<FNiagaraPreviewSeekAction>());
	ActionHandlers.Add(TEXT("niagara_create_system"),            MakeShared<FNiagaraCreateSystemAction>());
	ActionHandlers.Add(TEXT("niagara_add_emitter"),        MakeShared<FNiagaraAddEmitterAction>());
	ActionHandlers.Add(TEXT("niagara_add_renderer"),       MakeShared<FNiagaraAddRendererAction>());
	ActionHandlers.Add(TEXT("niagara_remove_renderer"),    MakeShared<FNiagaraRemoveRendererAction>());
	ActionHandlers.Add(TEXT("niagara_get_renderer_summary"), MakeShared<FNiagaraGetRendererSummaryAction>());
	ActionHandlers.Add(TEXT("niagara_set_renderer_mesh"),  MakeShared<FNiagaraSetRendererMeshAction>());
	ActionHandlers.Add(TEXT("niagara_set_renderer_material"), MakeShared<FNiagaraSetRendererMaterialAction>());
	ActionHandlers.Add(TEXT("niagara_set_renderer_binding"), MakeShared<FNiagaraSetRendererBindingAction>());
	ActionHandlers.Add(TEXT("niagara_add_module"),         MakeShared<FNiagaraAddModuleAction>());
	ActionHandlers.Add(TEXT("niagara_remove_module"),      MakeShared<FNiagaraRemoveModuleAction>());
	ActionHandlers.Add(TEXT("niagara_set_module_input"),   MakeShared<FNiagaraSetModuleInputAction>());
	ActionHandlers.Add(TEXT("niagara_set_emitter_property"), MakeShared<FNiagaraSetEmitterPropertyAction>());
	ActionHandlers.Add(TEXT("niagara_set_module_static_int"), MakeShared<FNiagaraSetModuleStaticIntAction>());
	ActionHandlers.Add(TEXT("niagara_set_module_enabled"), MakeShared<FNiagaraSetModuleEnabledAction>());
	ActionHandlers.Add(TEXT("niagara_get_module_inputs"), MakeShared<FNiagaraGetModuleInputsAction>());
	ActionHandlers.Add(TEXT("niagara_set_module_input_binding"), MakeShared<FNiagaraSetModuleInputBindingAction>());
	ActionHandlers.Add(TEXT("niagara_set_module_float_curve"), MakeShared<FNiagaraSetModuleFloatCurveAction>());
	ActionHandlers.Add(TEXT("niagara_set_data_channel_reader"), MakeShared<FNiagaraSetDataChannelReaderAction>());
	ActionHandlers.Add(TEXT("niagara_add_data_channel_spawn_handler"), MakeShared<FNiagaraAddDataChannelSpawnHandlerAction>());
	ActionHandlers.Add(TEXT("niagara_create_data_channel"), MakeShared<FNiagaraCreateDataChannelAction>());
	ActionHandlers.Add(TEXT("niagara_write_data_channel_test"), MakeShared<FNiagaraWriteDataChannelTestAction>());


	UE_LOG(LogMCP, Log, TEXT("UEEditorMCP: Registered %d action handlers"), ActionHandlers.Num());
}

TSharedRef<FEditorAction>* UMCPBridge::FindAction(const FString& CommandType)
{
	return ActionHandlers.Find(CommandType);
}

TSharedPtr<FJsonObject> UMCPBridge::ExecuteCommand(const FString& CommandType, const TSharedPtr<FJsonObject>& Params)
{
	// =========================================================================
	// Action Handlers (modular actions - check these first)
	// =========================================================================
	TSharedRef<FEditorAction>* ActionPtr = FindAction(CommandType);
	if (ActionPtr)
	{
		return (*ActionPtr)->Execute(Params, Context);
	}

	// =========================================================================
	// Unknown Command (all handlers should be registered as actions now)
	// =========================================================================
	return CreateErrorResponse(
		FString::Printf(TEXT("Unknown command type: %s"), *CommandType),
		TEXT("unknown_command")
	);
}

TSharedPtr<FJsonObject> UMCPBridge::ExecuteCommandSafe(const FString& CommandType, const TSharedPtr<FJsonObject>& Params)
{
	// Phase 2: Top-level C++ exception guard around command execution.
	// SEH is handled per-action inside FEditorAction::ExecuteWithCrashProtection.
	try
	{
		return ExecuteCommandInternal(CommandType, Params);
	}
	catch (const std::exception& Ex)
	{
		UE_LOG(LogMCP, Error, TEXT("C++ exception in command '%s': %hs"), *CommandType, Ex.what());
		return CreateErrorResponse(
			FString::Printf(TEXT("C++ exception: %hs"), Ex.what()),
			TEXT("cpp_exception")
		);
	}
	catch (...)
	{
		UE_LOG(LogMCP, Error, TEXT("Unknown C++ exception in command '%s'"), *CommandType);
		return CreateErrorResponse(TEXT("Unknown C++ exception"), TEXT("cpp_exception"));
	}
}

TSharedPtr<FJsonObject> UMCPBridge::ExecuteCommandInternal(const FString& CommandType, const TSharedPtr<FJsonObject>& Params)
{
	return ExecuteCommand(CommandType, Params);
}

TSharedPtr<FJsonObject> UMCPBridge::CreateSuccessResponse(const TSharedPtr<FJsonObject>& ResultData)
{
	TSharedPtr<FJsonObject> Response = MakeShared<FJsonObject>();
	Response->SetStringField(TEXT("status"), TEXT("success"));
	Response->SetBoolField(TEXT("success"), true);

	if (ResultData.IsValid())
	{
		Response->SetObjectField(TEXT("result"), ResultData);
	}
	else
	{
		Response->SetObjectField(TEXT("result"), MakeShared<FJsonObject>());
	}

	return Response;
}

TSharedPtr<FJsonObject> UMCPBridge::CreateErrorResponse(const FString& ErrorMessage, const FString& ErrorType)
{
	TSharedPtr<FJsonObject> Response = MakeShared<FJsonObject>();
	Response->SetStringField(TEXT("status"), TEXT("error"));
	Response->SetBoolField(TEXT("success"), false);
	Response->SetStringField(TEXT("error"), ErrorMessage);
	Response->SetStringField(TEXT("error_type"), ErrorType);

	return Response;
}
