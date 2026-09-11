"""UMG Widgets action definitions."""

from __future__ import annotations

from .. import ActionDef


_WIDGET_ACTIONS = [
    ActionDef(
        id="widget.create",
        command="create_umg_widget_blueprint",
        tags=("widget", "umg", "ui", "create", "blueprint"),
        description="Create a new UMG Widget Blueprint",
        input_schema={
            "type": "object",
            "properties": {
                "widget_name": {"type": "string", "description": "Name of the widget blueprint"},
                "parent_class": {"type": "string", "description": "Parent class (default: UserWidget)"},
                "path": {"type": "string", "description": "Content path (default: /Game/UI)"}
            },
            "required": ["widget_name"]
        },
        examples=({"widget_name": "WBP_HUD"},),
    ),
    ActionDef(
        id="widget.delete",
        command="delete_umg_widget_blueprint",
        tags=("widget", "umg", "delete", "remove"),
        description="Delete a UMG Widget Blueprint asset",
        input_schema={
            "type": "object",
            "properties": {
                "widget_name": {"type": "string", "description": "Name of the Widget Blueprint to delete"}
            },
            "required": ["widget_name"]
        },
        capabilities=("write", "destructive"),
        risk="destructive",
    ),
    ActionDef(
        id="widget.add_component",
        command="add_widget_component",
        tags=("widget", "umg", "component", "add", "textblock", "button", "image"),
        description="Add a widget component (TextBlock, Button, Image, Border, Overlay, HorizontalBox, VerticalBox, Slider, ProgressBar, etc.)",
        input_schema={
            "type": "object",
            "properties": {
                "widget_name": {"type": "string", "description": "Name of the Widget Blueprint"},
                "component_type": {"type": "string", "enum": ["TextBlock", "Button", "Image", "Border", "Overlay", "HorizontalBox", "VerticalBox", "Slider", "ProgressBar", "SizeBox", "ScaleBox", "CanvasPanel", "ComboBox", "CheckBox", "SpinBox", "EditableTextBox", "ScrollBox", "WidgetSwitcher", "BackgroundBlur", "UniformGridPanel", "Spacer", "RichTextBlock", "WrapBox", "CircularThrobber", "CommonButtonBase", "UserWidget"]},
                "component_name": {"type": "string", "description": "Name for the component"},
                "widget_class_path": {"type": "string", "description": "For component_type=UserWidget: /Game/...Widget.Widget_C or /Script/... class path"},
                "component_class": {"type": "string", "description": "For component_type=UserWidget: WidgetBlueprint name, /Game/...Widget.Widget_C, or /Script/... class path"},
                "text": {"type": "string", "description": "Text content (TextBlock, Button)"},
                "position": {"type": "array", "items": {"type": "number"}, "description": "[X, Y]"},
                "size": {"type": "array", "items": {"type": "number"}, "description": "[Width, Height]"},
                "font_size": {"type": "integer", "description": "Font size"},
                "color": {"type": "array", "items": {"type": "number"}, "description": "[R, G, B, A]"},
                "parent": {"type": "string", "description": "Optional parent container name. If provided, widget is added as child of this container instead of root canvas."}
            },
            "required": ["widget_name", "component_type", "component_name"]
        },
    ),
    ActionDef(
        id="widget.bind_event",
        command="bind_widget_event",
        tags=("widget", "umg", "event", "bind", "onclick"),
        description="Bind an event on a widget component (e.g., button OnClicked)",
        input_schema={
            "type": "object",
            "properties": {
                "widget_name": {"type": "string", "description": "Name of the Widget Blueprint"},
                "widget_component_name": {"type": "string", "description": "Component name (e.g., RestartButton)"},
                "event_name": {"type": "string", "description": "Event (OnClicked, OnPressed, OnReleased, etc.)"}
            },
            "required": ["widget_name", "widget_component_name", "event_name"]
        },
    ),
    ActionDef(
        id="widget.add_to_viewport",
        command="add_widget_to_viewport",
        tags=("widget", "umg", "viewport", "display", "show"),
        description="Add a Widget Blueprint instance to the viewport",
        input_schema={
            "type": "object",
            "properties": {
                "widget_name": {"type": "string", "description": "Name of the Widget Blueprint"},
                "z_order": {"type": "integer", "description": "Z-order (higher = on top)"}
            },
            "required": ["widget_name"]
        },
    ),
    ActionDef(
        id="widget.set_text_binding",
        command="set_text_block_binding",
        tags=("widget", "umg", "text", "binding", "data"),
        description="Set up a property binding for a Text Block widget",
        input_schema={
            "type": "object",
            "properties": {
                "widget_name": {"type": "string", "description": "Name of the Widget Blueprint"},
                "text_block_name": {"type": "string", "description": "Name of the Text Block"},
                "binding_property": {"type": "string", "description": "Property to bind to"},
                "binding_type": {"type": "string", "description": "Binding type (Text, Visibility, etc.)"}
            },
            "required": ["widget_name", "text_block_name", "binding_property"]
        },
    ),
    ActionDef(
        id="widget.list_components",
        command="list_widget_components",
        tags=("widget", "umg", "list", "components", "read"),
        description="List all components in a UMG Widget Blueprint",
        input_schema={
            "type": "object",
            "properties": {
                "widget_name": {"type": "string", "description": "Name of the Widget Blueprint"}
            },
            "required": ["widget_name"]
        },
        capabilities=("read",),
    ),
    ActionDef(
        id="widget.get_tree",
        command="get_widget_tree",
        tags=("widget", "umg", "tree", "hierarchy", "read"),
        description="Get the full widget tree with hierarchy, classes, slot info, and render transforms",
        input_schema={
            "type": "object",
            "properties": {
                "widget_name": {"type": "string", "description": "Name of the Widget Blueprint"}
            },
            "required": ["widget_name"]
        },
        capabilities=("read",),
    ),
    ActionDef(
        id="widget.set_properties",
        command="set_widget_properties",
        tags=("widget", "umg", "properties", "slot", "transform"),
        description="Set properties on a widget: slot, render transform, visibility, and type-specific properties",
        input_schema={
            "type": "object",
            "properties": {
                "widget_name": {"type": "string", "description": "Name of the Widget Blueprint"},
                "target": {"type": "string", "description": "Name of the widget to modify"},
                "position": {"type": "array", "items": {"type": "number"}, "description": "[X, Y] (CanvasPanel slot)"},
                "size": {"type": "array", "items": {"type": "number"}, "description": "[W, H] (CanvasPanel slot)"},
                "visibility": {"type": "string", "description": "Visible, Hidden, Collapsed, HitTestInvisible, SelfHitTestInvisible"},
                "is_enabled": {"type": "boolean", "description": "Whether widget is enabled"},
                "h_align": {"type": "string", "description": "Horizontal alignment: Fill, Left, Center, Right"},
                "v_align": {"type": "string", "description": "Vertical alignment: Fill, Top, Center, Bottom"},
                "padding": {"type": "array", "items": {"type": "number"}, "description": "[Left, Top, Right, Bottom]"},
                "anchors": {"type": "array", "items": {"type": "number"}, "description": "[MinX, MinY, MaxX, MaxY] CanvasPanel anchors (0-1). Presets: [0,0,0,0]=TopLeft, [0.5,0.5,0.5,0.5]=Center, [0,0,1,1]=Stretch"},
                "alignment": {"type": "array", "items": {"type": "number"}, "description": "[X, Y] alignment pivot (0-1). E.g. [0.5, 0.5] for center"},
                "auto_size": {"type": "boolean", "description": "Enable auto-size for CanvasPanel slot (overrides explicit size)"},
                "z_order": {"type": "integer", "description": "Z-order in CanvasPanel (higher = on top)"},
                "size_rule": {"type": "string", "enum": ["Auto", "Fill"], "description": "Size rule for VerticalBox/HorizontalBox slots"}
            },
            "required": ["widget_name", "target"]
        },
    ),
    ActionDef(
        id="widget.set_text",
        command="set_widget_text",
        tags=("widget", "umg", "text", "set", "textblock"),
        description="Set text/style on a TextBlock or update a Button's child TextBlock",
        input_schema={
            "type": "object",
            "properties": {
                "widget_name": {"type": "string", "description": "Name of the Widget Blueprint"},
                "target": {"type": "string", "description": "TextBlock or Button name"},
                "text": {"type": "string", "description": "Text to set"},
                "font_size": {"type": "integer", "description": "Font size"},
                "color": {"type": "array", "items": {"type": "number"}, "description": "[R, G, B, A]"},
                "justification": {"type": "string", "enum": ["Left", "Center", "Right"]}
            },
            "required": ["widget_name", "target"]
        },
    ),
    ActionDef(
        id="widget.set_combo_options",
        command="set_combo_box_options",
        tags=("widget", "umg", "combobox", "options", "dropdown"),
        description="Set/clear/add/remove options on a ComboBoxString widget",
        input_schema={
            "type": "object",
            "properties": {
                "widget_name": {"type": "string", "description": "Name of the Widget Blueprint"},
                "target": {"type": "string", "description": "ComboBoxString widget name"},
                "mode": {"type": "string", "enum": ["replace", "add", "remove", "clear"]},
                "options": {"type": "array", "items": {"type": "string"}, "description": "Options to apply"},
                "selected_option": {"type": "string", "description": "Option to select"}
            },
            "required": ["widget_name", "target"]
        },
    ),
    ActionDef(
        id="widget.set_slider",
        command="set_slider_properties",
        tags=("widget", "umg", "slider", "range", "value"),
        description="Set value/range/step on a Slider widget",
        input_schema={
            "type": "object",
            "properties": {
                "widget_name": {"type": "string", "description": "Name of the Widget Blueprint"},
                "target": {"type": "string", "description": "Slider widget name"},
                "value": {"type": "number", "description": "Slider value"},
                "min_value": {"type": "number"}, "max_value": {"type": "number"},
                "step_size": {"type": "number"}, "locked": {"type": "boolean"}
            },
            "required": ["widget_name", "target"]
        },
    ),
    ActionDef(
        id="widget.reparent",
        command="reparent_widgets",
        tags=("widget", "umg", "reparent", "hierarchy", "container"),
        description="Move widgets into a target container (VerticalBox, HorizontalBox, etc.)",
        input_schema={
            "type": "object",
            "properties": {
                "widget_name": {"type": "string", "description": "Name of the Widget Blueprint"},
                "target_container_name": {"type": "string", "description": "Target container name"},
                "container_type": {"type": "string", "description": "Container type (VerticalBox, HorizontalBox, etc.)"},
                "children": {"type": "array", "items": {"type": "string"}, "description": "Widget names to move"},
                "filter_class": {"type": "string", "description": "Move only widgets of this class"}
            },
            "required": ["widget_name", "target_container_name"]
        },
    ),
    ActionDef(
        id="widget.add_child",
        command="add_widget_child",
        tags=("widget", "umg", "child", "parent", "hierarchy"),
        description="Move an existing widget to become a child of a specified parent container",
        input_schema={
            "type": "object",
            "properties": {
                "widget_name": {"type": "string", "description": "Name of the Widget Blueprint"},
                "child": {"type": "string", "description": "Widget to move"},
                "parent": {"type": "string", "description": "Target parent container"}
            },
            "required": ["widget_name", "child", "parent"]
        },
    ),
    ActionDef(
        id="widget.delete_component",
        command="delete_widget_from_blueprint",
        tags=("widget", "umg", "delete", "component", "remove"),
        description="Delete a widget component from a UMG Widget Blueprint",
        input_schema={
            "type": "object",
            "properties": {
                "widget_name": {"type": "string", "description": "Name of the Widget Blueprint"},
                "target": {"type": "string", "description": "Widget component to delete"}
            },
            "required": ["widget_name", "target"]
        },
        capabilities=("write", "destructive"),
        risk="moderate",
    ),
    ActionDef(
        id="widget.rename_component",
        command="rename_widget_in_blueprint",
        tags=("widget", "umg", "rename", "component"),
        description="Rename a widget component in a UMG Widget Blueprint",
        input_schema={
            "type": "object",
            "properties": {
                "widget_name": {"type": "string", "description": "Name of the Widget Blueprint"},
                "target": {"type": "string", "description": "Current component name"},
                "new_name": {"type": "string", "description": "New name"}
            },
            "required": ["widget_name", "target", "new_name"]
        },
    ),
    ActionDef(
        id="widget.remove_delegate_bindings",
        command="remove_widget_delegate_bindings",
        tags=("widget", "umg", "delegate", "binding", "remove", "delete", "cleanup"),
        description="Remove stale DelegateEditorBinding entries from a Widget Blueprint, e.g. bindings for a deleted button.",
        input_schema={
            "type": "object",
            "properties": {
                "widget_name": {"type": "string", "description": "Name or asset path of the Widget Blueprint"},
                "target": {"type": "string", "description": "Optional widget object name, e.g. LevelMapButton"},
                "property_name": {"type": "string", "description": "Optional delegate/property name, e.g. OnClicked"},
                "function_name": {"type": "string", "description": "Optional generated/bound function name"},
                "graph_name": {"type": "string", "description": "Optional hidden graph name to remove, e.g. K2Node_Event_1"},
                "remove_invalid": {"type": "boolean", "description": "Remove bindings whose target widget no longer exists"},

                "dry_run": {"type": "boolean", "description": "Report matching bindings without modifying the asset"}
            },
            "required": ["widget_name"]
        },
        capabilities=("write", "destructive"),
        risk="moderate",
        examples=(
            {"widget_name": "WBP_LevelSelect", "target": "LevelMapButton"},
            {"widget_name": "WBP_LevelSelect", "remove_invalid": True, "dry_run": True},
        ),
    ),
    # --- MVVM Actions ---
    ActionDef(
        id="widget.mvvm_add_viewmodel",

        command="mvvm_add_viewmodel",
        tags=("widget", "umg", "mvvm", "viewmodel", "binding", "view"),
        description="Associate a ViewModel class with a Widget Blueprint (MVVM). Creates the MVVM extension and adds the ViewModel context.",
        input_schema={
            "type": "object",
            "properties": {
                "widget_name": {"type": "string", "description": "Name of the Widget Blueprint"},
                "viewmodel_class": {"type": "string", "description": "ViewModel class name (must implement INotifyFieldValueChanged / derive from UMVVMViewModelBase)"},
                "viewmodel_name": {"type": "string", "description": "Display name for this ViewModel in the Widget (defaults to class name)"},
                "creation_type": {
                    "type": "string",
                    "enum": ["CreateInstance", "Manual", "GlobalViewModelCollection", "PropertyPath", "Resolver"],
                    "description": "How the ViewModel is created at runtime (default: CreateInstance)"
                },
                "create_setter": {"type": "boolean", "description": "Generate a public setter function (default: false)"},
                "create_getter": {"type": "boolean", "description": "Generate a public getter function (default: true)"}
            },
            "required": ["widget_name", "viewmodel_class"]
        },
        examples=(
            {"widget_name": "WBP_HUD", "viewmodel_class": "StatusViewModel", "viewmodel_name": "StatusVM", "creation_type": "CreateInstance"},
        ),
    ),
    ActionDef(
        id="widget.mvvm_add_binding",
        command="mvvm_add_binding",
        tags=("widget", "umg", "mvvm", "binding", "property", "viewmodel", "data"),
        description="Add a MVVM property binding between a ViewModel property and a Widget property",
        input_schema={
            "type": "object",
            "properties": {
                "widget_name": {"type": "string", "description": "Name of the Widget Blueprint"},
                "viewmodel_name": {"type": "string", "description": "Name of the ViewModel (as registered via mvvm_add_viewmodel)"},
                "source_property": {"type": "string", "description": "Property name on the ViewModel (source)"},
                "destination_widget": {"type": "string", "description": "Name of the target widget in the Widget Tree"},
                "destination_property": {"type": "string", "description": "Property name on the target widget (e.g. Text, Percent, Visibility)"},
                "binding_mode": {
                    "type": "string",
                    "enum": ["OneTimeToDestination", "OneWayToDestination", "TwoWay", "OneTimeToSource", "OneWayToSource"],
                    "description": "Binding direction (default: OneWayToDestination)"
                },
                "execution_mode": {
                    "type": "string",
                    "enum": ["Immediate", "Delayed", "Tick", "Auto"],
                    "description": "When to execute the binding (optional, uses engine default if omitted)"
                }
            },
            "required": ["widget_name", "viewmodel_name", "source_property", "destination_widget", "destination_property"]
        },
        examples=(
            {
                "widget_name": "WBP_HUD",
                "viewmodel_name": "StatusVM",
                "source_property": "HealthPercent",
                "destination_widget": "HealthBar",
                "destination_property": "Percent",
                "binding_mode": "OneWayToDestination"
            },
        ),
    ),
    ActionDef(
        id="widget.mvvm_get_bindings",
        command="mvvm_get_bindings",
        tags=("widget", "umg", "mvvm", "binding", "viewmodel", "read", "introspect"),
        description="Read all MVVM ViewModels and Bindings configured on a Widget Blueprint",
        input_schema={
            "type": "object",
            "properties": {
                "widget_name": {"type": "string", "description": "Name of the Widget Blueprint"}
            },
            "required": ["widget_name"]
        },
        examples=(
            {"widget_name": "WBP_HUD"},
        ),
        capabilities=("read",),
    ),
    ActionDef(
        id="widget.mvvm_remove_binding",
        command="mvvm_remove_binding",
        tags=("widget", "umg", "mvvm", "binding", "remove", "delete"),
        description="Remove a MVVM binding from a Widget Blueprint by binding_id",
        input_schema={
            "type": "object",
            "properties": {
                "widget_name": {"type": "string", "description": "Name of the Widget Blueprint"},
                "binding_id": {"type": "string", "description": "Binding ID to remove (from mvvm_get_bindings)"}
            },
            "required": ["widget_name", "binding_id"]
        },
        examples=(
            {"widget_name": "WBP_HUD", "binding_id": "102D0F354A7C97A46E6E22B42A0C9394"},
        ),
    ),
    ActionDef(
        id="widget.mvvm_remove_viewmodel",
        command="mvvm_remove_viewmodel",
        tags=("widget", "umg", "mvvm", "viewmodel", "remove", "delete"),
        description="Remove a MVVM ViewModel from a Widget Blueprint by viewmodel_name",
        input_schema={
            "type": "object",
            "properties": {
                "widget_name": {"type": "string", "description": "Name of the Widget Blueprint"},
                "viewmodel_name": {"type": "string", "description": "ViewModel name to remove"}
            },
            "required": ["widget_name", "viewmodel_name"]
        },
        examples=(
            {"widget_name": "WBP_HUD", "viewmodel_name": "StatusVM"},
        ),
    ),
    # =========================================================================
    # P9: Asset Property Editing — DataAsset 直读/直写
    # =========================================================================
    ActionDef(
        id="editor.get_data_asset_property",
        command="get_data_asset_property",
        tags=("editor", "asset", "dataasset", "property", "read", "get"),
        description=(
            "Read a single UPROPERTY value from any UObject asset (DataAsset, Blueprint CDO, etc.). "
            "Returns the property value as a UE text-format string."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "asset_path": {
                    "type": "string",
                    "description": "Full content path of the asset, e.g. '/Game/P111/Combat/Data/DA_HammerSwing'",
                },
                "property_name": {
                    "type": "string",
                    "description": "UPROPERTY name in C++ (lowercase with underscores, e.g. 'cue_timeline', 'hit_event_tag')",
                },
            },
            "required": ["asset_path", "property_name"],
        },
        capabilities=("read",),
        risk="safe",
        examples=(
            {"asset_path": "/Game/P111/Combat/Data/DA_HammerSwing", "property_name": "cue_timeline"},
            {"asset_path": "/Game/P111/Combat/Data/DA_HammerSwing", "property_name": "hit_event_tag"},
        ),
    ),
    ActionDef(
        id="editor.set_data_asset_property",
        command="set_data_asset_property",
        tags=("editor", "asset", "dataasset", "property", "set", "write"),
        description=(
            "Set a single UPROPERTY value on any UObject asset. Supports scalars, structs, arrays, maps. "
            "Uses UE import-text format. FText values use INVTEXT(\"...\") wrapping."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "asset_path": {
                    "type": "string",
                    "description": "Full content path of the asset",
                },
                "property_name": {
                    "type": "string",
                    "description": "UPROPERTY name in C++",
                },
                "property_value": {
                    "type": "string",
                    "description": "Value in UE text-format, e.g. 'true', '1.5', '((TimeOffset=0.8,CueTag=...))'",
                },
                "save": {
                    "type": "boolean",
                    "description": "Whether to save the asset after setting (default: true)",
                },
            },
            "required": ["asset_path", "property_name", "property_value"],
        },
        capabilities=("write",),
        risk="moderate",
        examples=(
            {"asset_path": "/Game/P111/Combat/Data/DA_HammerSwing", "property_name": "play_rate", "property_value": "1.5"},
        ),
    ),
]
