// Copyright (c) 2025 zolnoor. All rights reserved.

#pragma once

#include "CoreMinimal.h"
#include "EditorAction.h"

class UEdGraph;
class UEdGraphNode;
class UEdGraphPin;

// ============================================================================
// Graph Operations (connect, find, delete, inspect)
// ============================================================================

/** Connect two nodes in a Blueprint graph */
class UEEDITORMCP_API FConnectBlueprintNodesAction : public FBlueprintNodeAction
{
public:
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;
protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual FString GetActionName() const override { return TEXT("connect_blueprint_nodes"); }
};


/** Find nodes in a Blueprint graph */
class UEEDITORMCP_API FFindBlueprintNodesAction : public FBlueprintNodeAction
{
public:
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;
protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual FString GetActionName() const override { return TEXT("find_blueprint_nodes"); }
	virtual bool RequiresSave() const override { return false; }
};


/** Delete a node from a Blueprint graph */
class UEEDITORMCP_API FDeleteBlueprintNodeAction : public FBlueprintNodeAction
{
public:
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;
protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual FString GetActionName() const override { return TEXT("delete_blueprint_node"); }
};


/** Get all pins on a node (for debugging connections) */
class UEEDITORMCP_API FGetNodePinsAction : public FBlueprintNodeAction
{
public:
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;
protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual FString GetActionName() const override { return TEXT("get_node_pins"); }
	virtual bool RequiresSave() const override { return false; }
};


// ============================================================================
// Event Nodes
// ============================================================================

/** Add an event node (ReceiveBeginPlay, ReceiveTick, etc.) */
class UEEDITORMCP_API FAddBlueprintEventNodeAction : public FBlueprintNodeAction
{
public:
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;
protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual FString GetActionName() const override { return TEXT("add_blueprint_event_node"); }
};


/** Add an input action event node (legacy input) */
class UEEDITORMCP_API FAddBlueprintInputActionNodeAction : public FBlueprintNodeAction
{
public:
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;
protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual FString GetActionName() const override { return TEXT("add_blueprint_input_action_node"); }
};


/** Add an Enhanced Input action event node */
class UEEDITORMCP_API FAddEnhancedInputActionNodeAction : public FBlueprintNodeAction
{
public:
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;
protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual FString GetActionName() const override { return TEXT("add_enhanced_input_action_node"); }
};


/** Add a custom event node */
class UEEDITORMCP_API FAddBlueprintCustomEventAction : public FBlueprintNodeAction
{
public:
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;
protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual FString GetActionName() const override { return TEXT("add_blueprint_custom_event"); }
};


/** Add a custom event whose signature automatically matches a delegate.
 *  Supports two delegate source modes:
 *  - Class property mode: delegate_class + delegate_name → finds the multicast delegate property
 *  - Node pin mode: source_node_id + source_pin_name → resolves from an existing node's delegate pin
 *  The resulting custom event will have its pins locked to the delegate signature. */
class UEEDITORMCP_API FAddCustomEventForDelegateAction : public FBlueprintNodeAction
{
public:
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;
protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual FString GetActionName() const override { return TEXT("add_custom_event_for_delegate"); }
private:
	UClass* ResolveClass(const FString& ClassName) const;
};


// ============================================================================
// Variable Nodes
// ============================================================================

/** Add a variable to a Blueprint */
class UEEDITORMCP_API FAddBlueprintVariableAction : public FBlueprintAction
{
public:
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;
protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual FString GetActionName() const override { return TEXT("add_blueprint_variable"); }
};


/** Add a variable get node */
class UEEDITORMCP_API FAddBlueprintVariableGetAction : public FBlueprintNodeAction
{
public:
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;
protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual FString GetActionName() const override { return TEXT("add_blueprint_variable_get"); }
};


/** Add a variable set node */
class UEEDITORMCP_API FAddBlueprintVariableSetAction : public FBlueprintNodeAction
{
public:
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;
protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual FString GetActionName() const override { return TEXT("add_blueprint_variable_set"); }
};


/** Set the default value of a pin */
class UEEDITORMCP_API FSetNodePinDefaultAction : public FBlueprintNodeAction
{
public:
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;
protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual FString GetActionName() const override { return TEXT("set_node_pin_default"); }
};


// ============================================================================
// Function Nodes
// ============================================================================

/** Add a function call node */
class UEEDITORMCP_API FAddBlueprintFunctionNodeAction : public FBlueprintNodeAction
{
public:
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;
protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual FString GetActionName() const override { return TEXT("add_blueprint_function_node"); }
};


/** Add a self reference node */
class UEEDITORMCP_API FAddBlueprintSelfReferenceAction : public FBlueprintNodeAction
{
public:
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;
protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual FString GetActionName() const override { return TEXT("add_blueprint_self_reference"); }
};


/** Add a component reference node */
class UEEDITORMCP_API FAddBlueprintGetSelfComponentReferenceAction : public FBlueprintNodeAction
{
public:
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;
protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual FString GetActionName() const override { return TEXT("add_blueprint_get_self_component_reference"); }
};


/** Add a branch (if/then/else) node */
class UEEDITORMCP_API FAddBlueprintBranchNodeAction : public FBlueprintNodeAction
{
public:
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;
protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual FString GetActionName() const override { return TEXT("add_blueprint_branch_node"); }
};


/** Add a cast node */
class UEEDITORMCP_API FAddBlueprintCastNodeAction : public FBlueprintNodeAction
{
public:
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;
protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual FString GetActionName() const override { return TEXT("add_blueprint_cast_node"); }
};


/** Add a subsystem getter node (e.g., EnhancedInputLocalPlayerSubsystem) */
class UEEDITORMCP_API FAddBlueprintGetSubsystemNodeAction : public FBlueprintNodeAction
{
public:
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;
protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual FString GetActionName() const override { return TEXT("add_blueprint_get_subsystem_node"); }
};


// ============================================================================
// Blueprint Function Graph
// ============================================================================

/** Create a new function in a Blueprint */
class UEEDITORMCP_API FCreateBlueprintFunctionAction : public FBlueprintAction
{
public:
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;
protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual FString GetActionName() const override { return TEXT("create_blueprint_function"); }
};

/** Add an override implementation graph for a function inherited from the parent class */
class UEEDITORMCP_API FAddBlueprintOverrideFunctionAction : public FBlueprintAction
{
public:
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;
protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual FString GetActionName() const override { return TEXT("add_blueprint_override_function"); }
};


// ============================================================================
// Event Dispatchers

// ============================================================================

/** Add an event dispatcher to a Blueprint */
class UEEDITORMCP_API FAddEventDispatcherAction : public FBlueprintAction
{
public:
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;
protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual FString GetActionName() const override { return TEXT("add_event_dispatcher"); }
};


/** Add a call node for an event dispatcher */
class UEEDITORMCP_API FCallEventDispatcherAction : public FBlueprintNodeAction
{
public:
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;
protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual FString GetActionName() const override { return TEXT("call_event_dispatcher"); }
};


/** Add a bind node for an event dispatcher */
class UEEDITORMCP_API FBindEventDispatcherAction : public FBlueprintNodeAction
{
public:
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;
protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual FString GetActionName() const override { return TEXT("bind_event_dispatcher"); }
};


/** Create a "Create Event" (K2Node_CreateDelegate) node that binds a function to a delegate pin.
 *  Works inside function graphs where CustomEvent is not available. */
class UEEDITORMCP_API FCreateEventDelegateAction : public FBlueprintNodeAction
{
public:
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;
protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual FString GetActionName() const override { return TEXT("create_event_delegate"); }
};


/** Bind a component delegate event (e.g., OnComponentBeginOverlap, OnTTSEnvelope).
 *  Creates a UK2Node_ComponentBoundEvent in the Blueprint event graph.
 *  The component must exist as a UPROPERTY on the Blueprint's GeneratedClass
 *  (i.e., added via SCS or declared in C++ parent). */
class UEEDITORMCP_API FBindComponentEventAction : public FBlueprintNodeAction
{
public:
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;
protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual FString GetActionName() const override { return TEXT("bind_component_event"); }
};


/** Bind a BlueprintAssignable delegate on a UObject reference pin.
 *  Creates a UK2Node_AddDelegate and a signature-matched UK2Node_CustomEvent,
 *  then connects the source object pin and event delegate pin automatically. */
class UEEDITORMCP_API FBindUObjectDelegateAction : public FBlueprintNodeAction
{
public:
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;
protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual FString GetActionName() const override { return TEXT("bind_uobject_delegate"); }
};


// ============================================================================
// Spawn Actor Nodes
// ============================================================================

/** Add a SpawnActorFromClass node */
class UEEDITORMCP_API FAddSpawnActorFromClassNodeAction : public FBlueprintNodeAction
{
public:
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;
protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual FString GetActionName() const override { return TEXT("add_spawn_actor_from_class_node"); }
};


/** Call a Blueprint function */
class UEEDITORMCP_API FCallBlueprintFunctionAction : public FBlueprintNodeAction
{
public:
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;
protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual FString GetActionName() const override { return TEXT("call_blueprint_function"); }
};


// ============================================================================
// External Object Property Nodes
// ============================================================================

/** Set a property on an external object reference (e.g., bShowMouseCursor on PlayerController) */
class UEEDITORMCP_API FSetObjectPropertyAction : public FBlueprintNodeAction
{
public:
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;
protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual FString GetActionName() const override { return TEXT("set_object_property"); }
};


// ============================================================================
// Sequence Node
// ============================================================================

/** Add an Execution Sequence node (native K2 node, NOT a macro) */
class UEEDITORMCP_API FAddSequenceNodeAction : public FBlueprintNodeAction
{
public:
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;
protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual FString GetActionName() const override { return TEXT("add_sequence_node"); }
};


// ============================================================================
// Macro Instance Nodes
// ============================================================================

/** Add a macro instance node (ForEachLoop, ForLoop, WhileLoop, etc.) */
class UEEDITORMCP_API FAddMacroInstanceNodeAction : public FBlueprintNodeAction
{
public:
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;
protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual FString GetActionName() const override { return TEXT("add_macro_instance_node"); }
private:
	UEdGraph* FindMacroGraph(const FString& MacroName) const;
};


// ============================================================================
// Struct Nodes
// ============================================================================

/** Add a Make Struct node (e.g., Make IntPoint, Make Vector, Make LinearColor) */
class UEEDITORMCP_API FAddMakeStructNodeAction : public FBlueprintNodeAction
{
public:
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;
protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual FString GetActionName() const override { return TEXT("add_make_struct_node"); }
};


/** Add a Break Struct node (e.g., Break IntPoint, Break Vector) */
class UEEDITORMCP_API FAddBreakStructNodeAction : public FBlueprintNodeAction
{
public:
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;
protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual FString GetActionName() const override { return TEXT("add_break_struct_node"); }
};


// ============================================================================
// Switch Nodes
// ============================================================================

/** Add a Switch on String node */
class UEEDITORMCP_API FAddSwitchOnStringNodeAction : public FBlueprintNodeAction
{
public:
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;
protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual FString GetActionName() const override { return TEXT("add_switch_on_string_node"); }
};


/** Add a Switch on Int node */
class UEEDITORMCP_API FAddSwitchOnIntNodeAction : public FBlueprintNodeAction
{
public:
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;
protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual FString GetActionName() const override { return TEXT("add_switch_on_int_node"); }
};


// ============================================================================
// Local Variables
// ============================================================================

/** Add a local variable to a Blueprint function graph */
class UEEDITORMCP_API FAddFunctionLocalVariableAction : public FBlueprintAction
{
public:
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;
protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual FString GetActionName() const override { return TEXT("add_function_local_variable"); }
};


// ============================================================================
// Variable Default Values
// ============================================================================

/** Set the default value of a Blueprint member variable */
class UEEDITORMCP_API FSetBlueprintVariableDefaultAction : public FBlueprintAction
{
public:
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;
protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual FString GetActionName() const override { return TEXT("set_blueprint_variable_default"); }
};


// ============================================================================
// Comment Nodes
// ============================================================================

/** Add a comment node to a Blueprint graph */
class UEEDITORMCP_API FAddBlueprintCommentAction : public FBlueprintNodeAction
{
public:
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;
protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual FString GetActionName() const override { return TEXT("add_blueprint_comment"); }
};

/**
 * Auto-create a comment box that precisely wraps a set of nodes.
 * Given node_ids, calculates the bounding box from actual node positions/sizes
 * and creates a properly sized comment with configurable padding.
 *
 * Params:
 *   blueprint_name  (required)  Blueprint name or asset path
 *   graph_name      (optional)  Graph name, defaults to "EventGraph"
 *   node_ids        (required)  Array of node GUID strings to wrap
 *   comment_text    (required)  Comment text
 *   color           (optional)  [R, G, B, A] in 0-1 range
 *   padding         (optional)  Extra padding in px around nodes (default: 40)
 *   title_height    (optional)  Space reserved for comment title text (default: 36)
 */
class UEEDITORMCP_API FAutoCommentAction : public FBlueprintNodeAction
{
public:
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;
protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual FString GetActionName() const override { return TEXT("auto_comment"); }
};


// ============================================================================
// P1 — Variable & Function Management
// ============================================================================

/** Delete a Blueprint member variable */
class UEEDITORMCP_API FDeleteBlueprintVariableAction : public FBlueprintAction
{
public:
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;
protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual FString GetActionName() const override { return TEXT("delete_blueprint_variable"); }
};


/** Rename a Blueprint member variable */
class UEEDITORMCP_API FRenameBlueprintVariableAction : public FBlueprintAction
{
public:
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;
protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual FString GetActionName() const override { return TEXT("rename_blueprint_variable"); }
};


/** Set metadata on a Blueprint member variable (Category, Tooltip, Replication, etc.)
 *  After setting flags, the Blueprint is automatically recompiled so that
 *  CPF_Edit / CPF_ExposeOnSpawn etc. take effect on the Generated Class.
 */
class UEEDITORMCP_API FSetVariableMetadataAction : public FBlueprintAction
{
public:
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;
protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual FString GetActionName() const override { return TEXT("set_variable_metadata"); }
};


/** Delete a Blueprint custom function graph */
class UEEDITORMCP_API FDeleteBlueprintFunctionAction : public FBlueprintAction
{
public:
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;
protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual FString GetActionName() const override { return TEXT("delete_blueprint_function"); }
};


/** Rename a custom function graph in a Blueprint */
class UEEDITORMCP_API FRenameBlueprintFunctionAction : public FBlueprintAction
{
public:
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;
protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual FString GetActionName() const override { return TEXT("rename_blueprint_function"); }
};


/** Rename a custom macro graph in a Blueprint */
class UEEDITORMCP_API FRenameBlueprintMacroAction : public FBlueprintAction
{
public:
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;
protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual FString GetActionName() const override { return TEXT("rename_blueprint_macro"); }
};


// ============================================================================
// P2 — Graph Operation Enhancements
// ============================================================================

/** Disconnect all connections on a specific pin */
class UEEDITORMCP_API FDisconnectBlueprintPinAction : public FBlueprintNodeAction
{
public:
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;
protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual FString GetActionName() const override { return TEXT("disconnect_blueprint_pin"); }
};


/** Move (reposition) a node in a Blueprint graph */
class UEEDITORMCP_API FMoveNodeAction : public FBlueprintNodeAction
{
public:
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;
protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual FString GetActionName() const override { return TEXT("move_node"); }
};


/** Add a Reroute node to a Blueprint graph */
class UEEDITORMCP_API FAddRerouteNodeAction : public FBlueprintNodeAction
{
public:
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;
protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual FString GetActionName() const override { return TEXT("add_reroute_node"); }
};


// ============================================================================
// Graph Selection Read (read-only, editor-state based)
// ============================================================================

/**
 * FGetSelectedNodesAction
 * Returns information about the currently selected nodes in the focused
 * Blueprint graph editor.  Accepts optional blueprint_name/graph_name;
 * falls back to the active editor when omitted.
 * Pure read-only – does not modify any asset.
 */
class UEEDITORMCP_API FGetSelectedNodesAction : public FBlueprintNodeAction
{
public:
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;

protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual FString GetActionName() const override { return TEXT("get_selected_nodes"); }
	virtual bool RequiresSave() const override { return false; }
};


/**
 * Collapse current Blueprint graph selection to a new function.
 * Uses Unreal's native Blueprint editor flow (same behavior as context menu).
 */
class UEEDITORMCP_API FCollapseSelectionToFunctionAction : public FBlueprintNodeAction
{
public:
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;

protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual FString GetActionName() const override { return TEXT("collapse_selection_to_function"); }
};

/**
 * Collapse current Blueprint graph selection to a new macro.
 * Uses Unreal's native Blueprint editor CollapseSelectionToMacro flow
 * (same behavior as right-click context menu → "Collapse to Macro").
 *
 * Parameters:
 *   - blueprint_name (optional): target a specific open Blueprint editor
 *
 * Returns:
 *   - blueprint_name: name of the owning Blueprint
 *   - source_graph:   name of the graph where nodes were selected
 *   - macro_count_before / macro_count_after: macro graph counts
 *   - created_macros: array of new macro graph names
 *   - created_macro:  name of the (most recently) created macro
 */
class UEEDITORMCP_API FCollapseSelectionToMacroAction : public FBlueprintNodeAction
{
public:
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;

protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual FString GetActionName() const override { return TEXT("collapse_selection_to_macro"); }
};


// ============================================================================
// Graph Selection Write — Programmatic selection by node ID
// ============================================================================

/**
 * FSetSelectedNodesAction
 * Programmatically set the selection in the focused Blueprint graph editor
 * by providing an array of node GUIDs.  Clears the previous selection and
 * selects only the specified nodes.
 *
 * Parameters:
 *   - node_ids (required): array of GUID strings identifying nodes to select
 *   - blueprint_name (optional): target a specific open Blueprint editor
 *   - graph_name (optional): target a specific graph (defaults to focused graph)
 *   - append (optional, default false): if true, add to existing selection
 *                                       instead of replacing it
 *
 * Returns: selected_count, node_ids (actually selected), missing_ids (not found)
 */
class UEEDITORMCP_API FSetSelectedNodesAction : public FBlueprintNodeAction
{
public:
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;

protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual FString GetActionName() const override { return TEXT("set_selected_nodes"); }
	virtual bool RequiresSave() const override { return false; }
};


/**
 * FBatchSelectAndActAction
 * Batch grouped selection + action execution.
 * Accepts an array of "groups", each containing:
 *   - node_ids: GUID strings for the group
 *   - action: action command to execute on this selection (e.g. "collapse_selection_to_function", "auto_comment")
 *   - action_params: optional extra params to pass to the action
 *
 * For each group, the action:
 *   1. Clears current selection
 *   2. Selects the specified nodes
 *   3. Executes the specified action with the merged params
 *   4. Collects the result
 *
 * Parameters:
 *   - blueprint_name (optional): target Blueprint editor
 *   - graph_name (optional): target graph
 *   - groups (required): array of {node_ids, action, action_params?}
 *
 * Returns: results array with per-group outcomes
 */
class UEEDITORMCP_API FBatchSelectAndActAction : public FBlueprintNodeAction
{
public:
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;

protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual FString GetActionName() const override { return TEXT("batch_select_and_act"); }
};


// ============================================================================
// Async Action Nodes (Third-party plugin support: UForge, etc.)
// ============================================================================

/** Add an async action node (UK2Node_AsyncAction) by class name.
 *  Supports any UBlueprintAsyncActionBase subclass, including third-party
 *  plugins like UForge HTTP & JSON Utility.
 *
 *  Params:
 *    blueprint_name  (required)  Target Blueprint
 *    class_name      (required)  C++ class name of the async action (e.g. "HTTPProxyAsync")
 *    factory_function (optional) Factory function name (auto-detected if omitted)
 *    node_position   (optional)  [X, Y]
 *    graph_name      (optional)  Target graph (default: EventGraph)
 *    pin_defaults    (optional)  Object mapping pin_name -> default_value
 */
class UEEDITORMCP_API FAddAsyncActionNodeAction : public FBlueprintNodeAction
{
public:
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;
protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual FString GetActionName() const override { return TEXT("add_async_action_node"); }
private:
	UClass* FindAsyncActionClass(const FString& ClassName) const;
	UFunction* FindFactoryFunction(UClass* AsyncClass, const FString& FunctionName) const;
};


// ============================================================================
// Self-Evolution: Dynamic Node Discovery & Creation
// ============================================================================

/** Search the Blueprint action catalog for available nodes.
 *  Queries FBlueprintActionDatabase to discover all registered Blueprint actions.
 *
 *  Params:
 *    keyword       (required)  Search term (min 2 chars, matches name/category/keywords)
 *    category      (optional)  Additional category filter
 *    max_results   (optional)  Max results to return (default: 50, max: 200)
 *
 *  Returns: array of {spawner_id, name, category, node_class, keywords, tooltip}
 *  Use spawner_id with node.add_generic to create the node.
 */
class UEEDITORMCP_API FSearchCatalogAction : public FBlueprintNodeAction
{
public:
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;
protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual FString GetActionName() const override { return TEXT("search_catalog"); }
	virtual bool RequiresSave() const override { return false; }
};


/** Create any Blueprint node using a spawner_id from search_catalog or suggest_next.
 *  This is the "universal node creator" — replaces 30+ hardcoded node.add_* actions.
 *
 *  Params:
 *    blueprint_name  (required)  Target Blueprint
 *    spawner_id      (required)  ID from search_catalog or suggest_next
 *    node_position   (optional)  [X, Y]
 *    graph_name      (optional)  Target graph (default: EventGraph)
 *    pin_defaults    (optional)  Object mapping pin_name -> default_value
 *
 *  Returns: node_id, node_class, node_title, pins[]
 */
class UEEDITORMCP_API FAddGenericNodeAction : public FBlueprintNodeAction
{
public:
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;
protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual FString GetActionName() const override { return TEXT("add_generic_node"); }
};


/** Create a direct reference node for an Actor placed in the current level.
 *  This mirrors dragging an Actor from the World Outliner into the Level Blueprint.
 *
 *  Params:
 *    actor_name      (required)  Exact object name or actor label in the editor world
 *    node_position   (optional)  [X, Y]
 *    graph_name      (optional)  Target Level Blueprint graph (default: EventGraph)
 *
 *  Returns: node_id, node_class, node_title, actor_name, actor_path, value_pin
 */
class UEEDITORMCP_API FAddLevelActorReferenceNodeAction : public FBlueprintNodeAction
{
public:
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;
protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual FString GetActionName() const override { return TEXT("add_level_actor_reference_node"); }
};


/** Given a node pin, suggest compatible nodes that can connect to it.
 *  Uses UE's native context-sensitive menu system (FBlueprintActionMenuUtils).
 *
 *  Params:
 *    blueprint_name  (required)  Target Blueprint
 *    node_id         (required)  GUID of the source node
 *    pin_name        (required)  Name of the pin to find connections for
 *    max_results     (optional)  Max results (default: 30, max: 100)
 *    graph_name      (optional)  Target graph (default: EventGraph)
 *
 *  Returns: compatible_actions[], source_pin info, pin_type
 */
class UEEDITORMCP_API FSuggestNextAction : public FBlueprintNodeAction
{
public:
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;
protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual FString GetActionName() const override { return TEXT("suggest_next"); }
	virtual bool RequiresSave() const override { return false; }
};


// ============================================================================
// Graph Topology (P2)
// ============================================================================

/**
 * FDescribeGraphAction
 * Dumps the full topology of a Blueprint graph: every node (GUID, class, title,
 * position), every pin (name, direction, type, connections, default value), and
 * a de-duplicated edge list.  Complements get_blueprint_summary (macro view)
 * with a precise, AI-parseable graph map.
 */
class UEEDITORMCP_API FDescribeGraphAction : public FBlueprintNodeAction
{
public:
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;

protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual FString GetActionName() const override { return TEXT("describe_graph"); }
	virtual bool RequiresSave() const override { return false; }

private:
	/** Serialize a single pin to JSON (shared helper) */
	static TSharedPtr<FJsonObject> SerializePinToJson(const UEdGraphPin* Pin, bool bIncludeHidden);
};
