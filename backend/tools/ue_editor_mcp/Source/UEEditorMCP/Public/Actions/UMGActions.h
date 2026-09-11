// Copyright (c) 2025 zolnoor. All rights reserved.

#pragma once

#include "CoreMinimal.h"
#include "Actions/EditorAction.h"

/**
 * Create a UMG Widget Blueprint
 */
class UEEDITORMCP_API FCreateUMGWidgetBlueprintAction : public FEditorAction
{
public:
	virtual FString GetActionName() const override { return TEXT("CreateUMGWidgetBlueprint"); }

protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;
};

/**
 * Add a Text Block to a Widget Blueprint
 */
class UEEDITORMCP_API FAddTextBlockToWidgetAction : public FEditorAction
{
public:
	virtual FString GetActionName() const override { return TEXT("AddTextBlockToWidget"); }

protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;
};

/**
 * Add a Button to a Widget Blueprint
 */
class UEEDITORMCP_API FAddButtonToWidgetAction : public FEditorAction
{
public:
	virtual FString GetActionName() const override { return TEXT("AddButtonToWidget"); }

protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;
};

/**
 * Add an Image to a Widget Blueprint
 */
class UEEDITORMCP_API FAddImageToWidgetAction : public FEditorAction
{
public:
	virtual FString GetActionName() const override { return TEXT("AddImageToWidget"); }

protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;
};

/**
 * Add a Border to a Widget Blueprint
 */
class UEEDITORMCP_API FAddBorderToWidgetAction : public FEditorAction
{
public:
	virtual FString GetActionName() const override { return TEXT("AddBorderToWidget"); }

protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;
};

/**
 * Add an Overlay to a Widget Blueprint
 */
class UEEDITORMCP_API FAddOverlayToWidgetAction : public FEditorAction
{
public:
	virtual FString GetActionName() const override { return TEXT("AddOverlayToWidget"); }

protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;
};

/**
 * Add a Horizontal Box to a Widget Blueprint
 */
class UEEDITORMCP_API FAddHorizontalBoxToWidgetAction : public FEditorAction
{
public:
	virtual FString GetActionName() const override { return TEXT("AddHorizontalBoxToWidget"); }

protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;
};

/**
 * Add a Vertical Box to a Widget Blueprint
 */
class UEEDITORMCP_API FAddVerticalBoxToWidgetAction : public FEditorAction
{
public:
	virtual FString GetActionName() const override { return TEXT("AddVerticalBoxToWidget"); }

protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;
};

/**
 * Add a Slider to a Widget Blueprint
 */
class UEEDITORMCP_API FAddSliderToWidgetAction : public FEditorAction
{
public:
	virtual FString GetActionName() const override { return TEXT("AddSliderToWidget"); }

protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;
};

/**
 * Add a Progress Bar to a Widget Blueprint
 */
class UEEDITORMCP_API FAddProgressBarToWidgetAction : public FEditorAction
{
public:
	virtual FString GetActionName() const override { return TEXT("AddProgressBarToWidget"); }

protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;
};

/**
 * Add a Size Box to a Widget Blueprint
 */
class UEEDITORMCP_API FAddSizeBoxToWidgetAction : public FEditorAction
{
public:
	virtual FString GetActionName() const override { return TEXT("AddSizeBoxToWidget"); }

protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;
};

/**
 * Add a Scale Box to a Widget Blueprint
 */
class UEEDITORMCP_API FAddScaleBoxToWidgetAction : public FEditorAction
{
public:
	virtual FString GetActionName() const override { return TEXT("AddScaleBoxToWidget"); }

protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;
};

/**
 * Add a Canvas Panel to a Widget Blueprint
 */
class UEEDITORMCP_API FAddCanvasPanelToWidgetAction : public FEditorAction
{
public:
	virtual FString GetActionName() const override { return TEXT("AddCanvasPanelToWidget"); }

protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;
};

/**
 * Add a ComboBox (String) to a Widget Blueprint
 */
class UEEDITORMCP_API FAddComboBoxToWidgetAction : public FEditorAction
{
public:
	virtual FString GetActionName() const override { return TEXT("AddComboBoxToWidget"); }

protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;
};

/**
 * Add a CheckBox to a Widget Blueprint
 */
class UEEDITORMCP_API FAddCheckBoxToWidgetAction : public FEditorAction
{
public:
	virtual FString GetActionName() const override { return TEXT("AddCheckBoxToWidget"); }

protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;
};

/**
 * Add a SpinBox to a Widget Blueprint
 */
class UEEDITORMCP_API FAddSpinBoxToWidgetAction : public FEditorAction
{
public:
	virtual FString GetActionName() const override { return TEXT("AddSpinBoxToWidget"); }

protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;
};

/**
 * Add an EditableTextBox to a Widget Blueprint
 */
class UEEDITORMCP_API FAddEditableTextBoxToWidgetAction : public FEditorAction
{
public:
	virtual FString GetActionName() const override { return TEXT("AddEditableTextBoxToWidget"); }

protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;
};

/**
 * Bind a widget event to a function
 */
class UEEDITORMCP_API FBindWidgetEventAction : public FEditorAction
{
public:
	virtual FString GetActionName() const override { return TEXT("BindWidgetEvent"); }

protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;
};

/**
 * Add widget to viewport (returns class path for Blueprint use)
 */
class UEEDITORMCP_API FAddWidgetToViewportAction : public FEditorAction
{
public:
	virtual FString GetActionName() const override { return TEXT("AddWidgetToViewport"); }

protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;
};

/**
 * Set up text block binding to a variable
 */
class UEEDITORMCP_API FSetTextBlockBindingAction : public FEditorAction
{
public:
	virtual FString GetActionName() const override { return TEXT("SetTextBlockBinding"); }

protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;
};

/**
 * List components in a Widget Blueprint
 */
class UEEDITORMCP_API FListWidgetComponentsAction : public FEditorAction
{
public:
	virtual FString GetActionName() const override { return TEXT("ListWidgetComponents"); }

protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;
};

/**
 * Reparent widgets: move specified widgets into a target container
 */
class UEEDITORMCP_API FReparentWidgetsAction : public FEditorAction
{
public:
	virtual FString GetActionName() const override { return TEXT("ReparentWidgets"); }

protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;
};

/**
 * Set widget properties: position, size, padding, render transform (scale/rotation/shear), alignment, visibility
 */
class UEEDITORMCP_API FSetWidgetPropertiesAction : public FEditorAction
{
public:
	virtual FString GetActionName() const override { return TEXT("SetWidgetProperties"); }

protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;
};

/**
 * Get the full widget tree with hierarchy, slot info, and render transform for each widget
 */
class UEEDITORMCP_API FGetWidgetTreeAction : public FEditorAction
{
public:
	virtual FString GetActionName() const override { return TEXT("GetWidgetTree"); }

protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;
};

/**
 * Delete a widget component by name from a Widget Blueprint
 */
class UEEDITORMCP_API FDeleteWidgetFromBlueprintAction : public FEditorAction
{
public:
	virtual FString GetActionName() const override { return TEXT("DeleteWidgetFromBlueprint"); }

protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;
};

/**
 * Rename a widget component in a Widget Blueprint
 */
class UEEDITORMCP_API FRenameWidgetInBlueprintAction : public FEditorAction
{
public:
	virtual FString GetActionName() const override { return TEXT("RenameWidgetInBlueprint"); }

protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;
};

/**
 * Move an existing widget to become a child of a specified parent container
 */
class UEEDITORMCP_API FAddWidgetChildAction : public FEditorAction
{
public:
	virtual FString GetActionName() const override { return TEXT("AddWidgetChild"); }

protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;
};

/**
 * Delete a UMG Widget Blueprint asset from the project
 */
class UEEDITORMCP_API FDeleteUMGWidgetBlueprintAction : public FEditorAction
{
public:
	virtual FString GetActionName() const override { return TEXT("DeleteUMGWidgetBlueprint"); }

protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;
};

/**
 * Set/clear/add options on an existing ComboBoxString widget
 * Params: widget_name, target (ComboBox name), options (string array), selected_option, mode ("replace"|"add"|"remove")
 */
class UEEDITORMCP_API FSetComboBoxOptionsAction : public FEditorAction
{
public:
	virtual FString GetActionName() const override { return TEXT("SetComboBoxOptions"); }

protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;
};

/**
 * Set text on a TextBlock or Button's text in a Widget Blueprint
 * Params: widget_name, target (widget name), text, font_size, color
 */
class UEEDITORMCP_API FSetWidgetTextAction : public FEditorAction
{
public:
	virtual FString GetActionName() const override { return TEXT("SetWidgetText"); }

protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;
};

/**
 * Set Slider properties (value, min, max, step, etc.) on an existing Slider widget
 * Params: widget_name, target (Slider name), value, min_value, max_value, step_size, locked
 */
class UEEDITORMCP_API FSetSliderPropertiesAction : public FEditorAction
{
public:
	virtual FString GetActionName() const override { return TEXT("SetSliderProperties"); }

protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;
};

/**
 * Add a generic widget to a Widget Blueprint.
 * Handles: ScrollBox, WidgetSwitcher, BackgroundBlur, UniformGridPanel,
 * Spacer, RichTextBlock, WrapBox, CircularThrobber.
 * Uses component_class parameter to determine the widget type.
 */
class UEEDITORMCP_API FAddGenericWidgetAction : public FEditorAction
{
public:
	virtual FString GetActionName() const override { return TEXT("AddGenericWidgetToWidget"); }

protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;

private:
	UClass* ResolveWidgetClass(const FString& ClassName) const;
};

// =============================================================================
// MVVM Actions — ModelViewViewModel integration for Widget Blueprints
// =============================================================================

/**
 * Associate a ViewModel class with a Widget Blueprint via MVVM Extension.
 * Creates the MVVM BlueprintView if it doesn't exist, then adds the ViewModel context.
 * Params: widget_name, viewmodel_class, viewmodel_name, creation_type
 */
class UEEDITORMCP_API FMVVMAddViewModelAction : public FEditorAction
{
public:
	virtual FString GetActionName() const override { return TEXT("MVVMAddViewModel"); }

protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;
};

/**
 * Add a property binding between a ViewModel property and a Widget property.
 * Params: widget_name, viewmodel_name, source_property, destination_widget,
 *         destination_property, binding_mode, execution_mode
 */
class UEEDITORMCP_API FMVVMAddBindingAction : public FEditorAction
{
public:
	virtual FString GetActionName() const override { return TEXT("MVVMAddBinding"); }

protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;
};

/**
 * Add an MVVM event binding from a widget multicast event to a ViewModel function.
 * Params: widget_name, viewmodel_name, event_widget, event_property, destination_function
 */
class UEEDITORMCP_API FMVVMAddEventAction : public FEditorAction
{
public:
	virtual FString GetActionName() const override { return TEXT("MVVMAddEvent"); }

protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;
};

/**
 * Remove all MVVM event bindings whose event path matches (event_widget, event_property).
 * Optional 'event_property' acts as a filter; when omitted, removes every event binding on the widget.
 * Params: widget_name, event_widget, event_property (optional)
 */
class UEEDITORMCP_API FMVVMRemoveEventAction : public FEditorAction
{
public:
	virtual FString GetActionName() const override { return TEXT("MVVMRemoveEvent"); }

protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;
};

/**
 * Read all MVVM ViewModels and Bindings configured on a Widget Blueprint.
 * Params: widget_name
 */
class UEEDITORMCP_API FMVVMGetBindingsAction : public FEditorAction
{
public:
	virtual FString GetActionName() const override { return TEXT("MVVMGetBindings"); }

protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;
};

/**
 * Remove a MVVM binding from a Widget Blueprint by binding_id.
 * Params: widget_name, binding_id
 */
class UEEDITORMCP_API FMVVMRemoveBindingAction : public FEditorAction
{
public:
	virtual FString GetActionName() const override { return TEXT("MVVMRemoveBinding"); }

protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;
};

/**
 * Remove a MVVM ViewModel from a Widget Blueprint by viewmodel_name.
 * Params: widget_name, viewmodel_name
 */
class UEEDITORMCP_API FMVVMRemoveViewModelAction : public FEditorAction
{
public:
	virtual FString GetActionName() const override { return TEXT("MVVMRemoveViewModel"); }

protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;
};


/**
 * Set bIsVariable on a widget component in a Widget Blueprint.
 * Params: widget_name, target (widget component name), is_variable (bool)
 */
class UEEDITORMCP_API FSetWidgetIsVariableAction : public FEditorAction
{
public:
	virtual FString GetActionName() const override { return TEXT("set_widget_is_variable"); }

protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;
};

/**
 * Purge stale entries from PanelWidget.Slots arrays (root canvas + all nested panels).
 *
 * Removes:
 *  - Slots whose Content is null
 *  - Slots whose Content->Slot points to a different slot (i.e. the widget actually lives
 *    in another panel; this slot is a stale duplicate left behind by buggy reparent paths)
 *  - Slots whose Content->Slot is null (widget orphaned but still pointer-referenced)
 *
 * This is the safe way to clean up "ghost" entries that show up duplicated in the Designer
 * hierarchy but cannot be removed via the normal Delete path because RemoveChild requires
 * widget->Slot->Parent == this panel.
 *
 * Params: widget_name [, dry_run (bool)]
 * Returns: { removed: [{panel, child_name, reason}], total_removed: N, dry_run: bool }
 */
class UEEDITORMCP_API FPurgePanelOrphansAction : public FEditorAction
{
public:
	virtual FString GetActionName() const override { return TEXT("purge_panel_orphans"); }

protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;
};

/**
 * Generic reflected-property writer for any widget instance inside a Widget Blueprint.
 *
 * Use this to set arbitrary UPROPERTY values (FLinearColor, FVector2D, FName, FString,
 * bool/int/float, FText) on a widget instance — including properties inherited from
 * a native parent class such as UP111CommonButton::SelectedBackgroundColor.
 *
 * Params:
 *   widget_name     : Widget Blueprint name (or asset path)
 *   target          : Widget instance name in the WidgetTree
 *   property_name   : UPROPERTY name on the widget instance class hierarchy
 *   property_value  : UE import-text value, e.g.
 *                     "(R=1.0,G=1.0,B=1.0,A=0.15)"   for FLinearColor
 *                     "(X=10.0,Y=20.0)"              for FVector2D
 *                     "true" / "false"               for bool
 *                     "1.5"                          for float/double
 *                     "Hello"                        for FString / FName
 *                     "INVTEXT(\"Hello\")"           for FText
 */
class UEEDITORMCP_API FSetWidgetReflectedPropertyAction : public FEditorAction
{
public:
	virtual FString GetActionName() const override { return TEXT("set_widget_reflected_property"); }

protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;
};

/**
 * Remove stale DelegateEditorBinding entries from a Widget Blueprint.
 *
 * Params:
 *   widget_name     : Widget Blueprint name or asset path
 *   target          : Optional widget object name, e.g. LevelMapButton
 *   property_name   : Optional delegate/property name, e.g. OnClicked
 *   function_name   : Optional generated/bound function name
 *   graph_name      : Optional hidden graph name to remove, e.g. K2Node_Event_1
 *   remove_invalid  : Optional bool; remove bindings whose target widget no longer exists

 *   dry_run         : Optional bool; report matches without modifying the asset
 */
class UEEDITORMCP_API FRemoveWidgetDelegateBindingsAction : public FEditorAction
{
public:
	virtual FString GetActionName() const override { return TEXT("remove_widget_delegate_bindings"); }

protected:
	virtual bool Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError) override;
	virtual TSharedPtr<FJsonObject> ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context) override;
};

