// Copyright (c) 2025 zolnoor. All rights reserved.

using System.IO;
using UnrealBuildTool;

public class UEEditorMCP : ModuleRules
{
	public UEEditorMCP(ReadOnlyTargetRules Target) : base(Target)
	{
		PCHUsage = ModuleRules.PCHUsageMode.UseExplicitOrSharedPCHs;

		PublicDependencyModuleNames.AddRange(new string[]
		{
			"Core",
			"CoreUObject",
			"Engine",
			"Projects",
			"Slate",
			"SlateCore",
			"InputCore",
		});

		PrivateDependencyModuleNames.AddRange(new string[]
		{
			"UnrealEd",
			"EditorSubsystem",
			"BlueprintGraph",
			"Kismet",
			"KismetCompiler",
			"GraphEditor",
			"Json",
			"JsonUtilities",
			"Networking",
			"Sockets",
			"UMG",
			"UMGEditor",
			"EnhancedInput",
			"InputBlueprintNodes",
			"GameplayAbilities",
			"GameplayTags",
			"EditorScriptingUtilities",
			"AssetTools",
			"SubobjectDataInterface", // UE-native Blueprint component hierarchy editing
			"SourceControl",      // For Diff Against Depot (ISourceControlModule, ISourceControlProvider, etc.)
			"MaterialEditor",     // For UMaterialEditingLibrary and material expression manipulation
			"RenderCore",         // For material shader compilation
			"RHI",                // For GMaxRHIShaderPlatform (compile diagnostics)
			"ModelViewViewModel",           // MVVM runtime types (EMVVMBindingMode, EMVVMExecutionMode)
			"ModelViewViewModelBlueprint",  // MVVM editor-time binding API (UMVVMBlueprintView, etc.)
			"FieldNotification",            // INotifyFieldValueChanged interface
			"Niagara",            // Niagara runtime: UNiagaraScript/UNiagaraSystem, FNiagaraVariable, emitter handles
			"NiagaraCore",        // ENiagaraScriptUsage and core Niagara types
			"NiagaraEditor",      // UNiagaraSystemFactoryNew (editor-only asset creation)
			"ToolsetRegistry",    // Official UE ToolsetRegistry bridge (list_toolsets / describe_toolset / call_tool)
		});

		PrivateIncludePaths.AddRange(new string[]
		{
			Path.Combine(EngineDirectory, "Plugins/FX/Niagara/Source/Niagara/Classes"),
			Path.Combine(EngineDirectory, "Plugins/FX/Niagara/Source/Niagara/Internal/DataInterface"),
			Path.Combine(EngineDirectory, "Plugins/Runtime/GameplayAbilities/Source/GameplayAbilities/Public"),
		});

		// LiveCoding (only available on Windows: Engine/Source/Developer/Windows/LiveCoding)
		// Used by FLiveCodingCompileAction / FLiveCodingStatusAction.
		if (Target.Platform == UnrealTargetPlatform.Win64)
		{
			PrivateDependencyModuleNames.Add("LiveCoding");
			PrivateDefinitions.Add("UEEDITORMCP_HAS_LIVECODING=1");
		}
		else
		{
			PrivateDefinitions.Add("UEEDITORMCP_HAS_LIVECODING=0");
		}

		// Ensure proper RTTI/exceptions for crash handling
		bUseRTTI = true;
		bEnableExceptions = true;
	}
}
