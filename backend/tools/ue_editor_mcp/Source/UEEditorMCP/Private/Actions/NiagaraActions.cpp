// Copyright (c) 2025 zolnoor. All rights reserved.

#include "Actions/NiagaraActions.h"

#include "NiagaraScript.h"
#include "NiagaraSystem.h"
#include "NiagaraEmitter.h"
#include "NiagaraEmitterBase.h"
#include "NiagaraEmitterHandle.h"
#include "NiagaraActor.h"
#include "NiagaraComponent.h"
#include "NiagaraSystemInstance.h"
#include "NiagaraSystemSimulation.h"
#include "NiagaraSystemInstanceController.h"
#include "NiagaraEmitterInstance.h"
#include "NiagaraDataSet.h"
#include "NiagaraTypes.h"
#include "NiagaraCommon.h"
#include "NiagaraDataChannel.h"
#include "NiagaraDataChannelAccessContext.h"
#include "NiagaraDataChannelAccessor.h"
#include "NiagaraDataChannelAsset.h"
#include "NiagaraDataChannelData.h"
#include "NiagaraDataChannelFunctionLibrary.h"
#include "NiagaraDataChannel_Map.h"
#include "NiagaraDataChannelVariable.h"
#include "NiagaraDataChannel_GameplayBurst.h"
#include "NiagaraDataChannel_Global.h"
#include "NiagaraDataInterfaceCurve.h"
#include "NiagaraDataInterfaceDataChannelRead.h"
#include "NiagaraDataInterfaceUtilities.h"
#include "NiagaraWorldManager.h"
#include "NiagaraDataChannelHandler.h"
#include "NiagaraUserRedirectionParameterStore.h"
#include "NiagaraSystemFactoryNew.h"
#include "NiagaraEditorUtilities.h"
#include "NiagaraSystemEditorData.h"
#include "NiagaraEditorModule.h"
#include "NiagaraDataInterface.h"
#include "NiagaraConstants.h"
#include "ViewModels/NiagaraScratchPadViewModel.h"
#include "ViewModels/NiagaraScratchPadScriptViewModel.h"
#include "NiagaraNodeOp.h"
#include "NiagaraOverviewNode.h"
#include "ViewModels/NiagaraSystemViewModel.h"

// From-zero stack construction (add_renderer / add_module / set_module_input)
#include "NiagaraScriptSource.h"
#include "NiagaraGraph.h"
#include "NiagaraNode.h"
#include "NiagaraNodeOutput.h"
#include "NiagaraNodeFunctionCall.h"
#include "NiagaraNodeAssignment.h"
#include "NiagaraNodeCustomHlsl.h"
#include "NiagaraNodeInput.h"
#include "NiagaraParameterMapHistory.h"
#include "EdGraphSchema_Niagara.h"
#include "NiagaraRendererProperties.h"
#include "NiagaraSpriteRendererProperties.h"
#include "NiagaraMeshRendererProperties.h"
#include "NiagaraMeshRendererMeshProperties.h"
#include "NiagaraRibbonRendererProperties.h"
#include "NiagaraLightRendererProperties.h"
#include "EdGraph/EdGraph.h"
#include "EdGraph/EdGraphNode.h"
#include "ViewModels/Stack/NiagaraStackGraphUtilities.h"
#include "ViewModels/Stack/NiagaraParameterHandle.h"
#include "Materials/MaterialInterface.h"
#include "Engine/StaticMesh.h"

#include "AssetRegistry/AssetRegistryModule.h"
#include "AssetRegistry/ARFilter.h"
#include "AssetRegistry/AssetData.h"
#include "AssetRegistry/IAssetRegistry.h"
#include "AssetToolsModule.h"
#include "Editor.h"
#include "EditorAssetLibrary.h"
#include "Subsystems/AssetEditorSubsystem.h"
#include "Engine/World.h"
#include "EngineUtils.h"
#include "GameFramework/Actor.h"
#include "Framework/Application/SlateApplication.h"

#include "UObject/UObjectGlobals.h"
#include "UObject/UObjectIterator.h"
#include "UObject/Package.h"
#include "UObject/UnrealType.h"
#include "HAL/PlatformProcess.h"
#include "HAL/PlatformTime.h"
#include "Misc/PackageName.h"
#include "Modules/ModuleManager.h"
#include "Dom/JsonObject.h"
#include "Dom/JsonValue.h"

class UNiagaraNodeParameterMapGet;
class UNiagaraNodeParameterMapSet;

namespace UE::Niagara::Wizard::Utilities
{
	NIAGARAEDITOR_API UEdGraphPin* AddReadParameterPin(const FNiagaraTypeDefinition& Type, const FName& Name, UNiagaraNodeParameterMapGet* MapGetNode);
	NIAGARAEDITOR_API UEdGraphPin* AddWriteParameterPin(const FNiagaraTypeDefinition& Type, const FName& Name, UNiagaraNodeParameterMapSet* MapSetNode);
	NIAGARAEDITOR_API UNiagaraNodeFunctionCall* CreateDataInterfaceFunctionNode(const TSubclassOf<UNiagaraDataInterface>& DataInterfaceClass, const FName& FunctionName, UNiagaraGraph* Graph);
	NIAGARAEDITOR_API UNiagaraNodeFunctionCall* CreateFunctionCallNode(UNiagaraScript* FunctionScript, UNiagaraGraph* Graph);
	NIAGARAEDITOR_API UNiagaraNodeOp* CreateOpNode(const FName& OpName, UNiagaraGraph* Graph);
	NIAGARAEDITOR_API void SetDefaultBinding(UNiagaraGraph* Graph, const FName& VarName, const FName& DefaultBinding);
}
// =========================================================================
// Local helpers (engine-internal Niagara reflection / tags)
// =========================================================================
namespace
{
	/** AssetRegistry tag names emitted by UNiagaraScript::GetAssetRegistryTags (UE 5.7). */
	const FName TAG_LibraryVisibility(TEXT("LibraryVisibility"));
	const FName TAG_Category(TEXT("Category"));
	const FName TAG_Description(TEXT("Description"));
	const FName TAG_Keywords(TEXT("Keywords"));
	const FName TAG_ModuleUsageBitmask(TEXT("ModuleUsageBitmask"));
	const FName TAG_Deprecated(TEXT("bDeprecated"));
	const FName TAG_Suggested(TEXT("bSuggested"));

	FString GetTagString(const FAssetData& AssetData, const FName& Tag)
	{
		FString Value;
		AssetData.GetTagValue(Tag, Value);
		return Value;
	}

	bool GetTagBool(const FAssetData& AssetData, const FName& Tag)
	{
		FString Value;
		if (AssetData.GetTagValue(Tag, Value))
		{
			return Value == TEXT("1") || Value.ToBool();
		}
		return false;
	}

	/** Convert ENiagaraScriptUsage to its short reflected name (e.g. "Module"). */
	FString UsageToString(ENiagaraScriptUsage Usage)
	{
		if (const UEnum* Enum = StaticEnum<ENiagaraScriptUsage>())
		{
			return Enum->GetNameStringByValue(static_cast<int64>(Usage));
		}
		return FString();
	}

	/**
	 * Parse a usage string (short or fully-qualified) into ENiagaraScriptUsage.
	 * Returns false if the string does not match any enum entry.
	 */
	bool ParseUsage(const FString& In, ENiagaraScriptUsage& Out)
	{
		const UEnum* Enum = StaticEnum<ENiagaraScriptUsage>();
		if (!Enum)
		{
			return false;
		}
		int64 Value = Enum->GetValueByNameString(In);
		if (Value == INDEX_NONE)
		{
			// Try with the enum-qualified prefix as a fallback.
			Value = Enum->GetValueByNameString(FString::Printf(TEXT("ENiagaraScriptUsage::%s"), *In));
		}
		if (Value == INDEX_NONE)
		{
			return false;
		}
		Out = static_cast<ENiagaraScriptUsage>(Value);
		return true;
	}

	/** Build a JSON digest from a UNiagaraScript's AssetRegistry tags (no asset load). */
	TSharedPtr<FJsonObject> MakeScriptDigest(const FAssetData& AssetData)
	{
		TSharedPtr<FJsonObject> Obj = MakeShared<FJsonObject>();
		Obj->SetStringField(TEXT("name"), AssetData.AssetName.ToString());
		Obj->SetStringField(TEXT("path"), AssetData.GetObjectPathString());

		const FString Visibility = GetTagString(AssetData, TAG_LibraryVisibility);
		Obj->SetStringField(TEXT("visibility"), Visibility.IsEmpty() ? TEXT("Invalid") : Visibility);
		Obj->SetStringField(TEXT("category"), GetTagString(AssetData, TAG_Category));
		Obj->SetStringField(TEXT("description"), GetTagString(AssetData, TAG_Description));
		Obj->SetStringField(TEXT("keywords"), GetTagString(AssetData, TAG_Keywords));

		const FString Bitmask = GetTagString(AssetData, TAG_ModuleUsageBitmask);
		Obj->SetNumberField(TEXT("module_usage_bitmask"), Bitmask.IsEmpty() ? 0 : FCString::Atoi(*Bitmask));
		Obj->SetBoolField(TEXT("deprecated"), GetTagBool(AssetData, TAG_Deprecated));
		Obj->SetBoolField(TEXT("suggested"), GetTagBool(AssetData, TAG_Suggested));
		return Obj;
	}

	/** Resolve a content path string to a normalized object path for LoadObject. */
	FString NormalizeAssetObjectPath(const FString& InPath)
	{
		FString Path = InPath;
		Path.TrimStartAndEndInline();
		// Accept either "/Game/Foo/Bar" (package path) or "/Game/Foo/Bar.Bar" (object path).
		if (!Path.Contains(TEXT(".")))
		{
			FString AssetName;
			if (Path.Split(TEXT("/"), nullptr, &AssetName, ESearchCase::IgnoreCase, ESearchDir::FromEnd))
			{
				Path = FString::Printf(TEXT("%s.%s"), *Path, *AssetName);
			}
		}
		return Path;
	}

	/**
	 * Resolve an emitter handle inside a system by name. If EmitterName is empty
	 * the system must contain exactly one emitter handle. Returns the matching
	 * handle pointer (owned by the system) or nullptr with OutError populated.
	 */
	const FNiagaraEmitterHandle* ResolveEmitterHandle(UNiagaraSystem& System, const FString& EmitterName, FString& OutError)
	{
		const TArray<FNiagaraEmitterHandle>& Handles = System.GetEmitterHandles();
		if (Handles.Num() == 0)
		{
			OutError = TEXT("System has no emitters; add an emitter first.");
			return nullptr;
		}
		if (EmitterName.IsEmpty())
		{
			if (Handles.Num() != 1)
			{
				OutError = FString::Printf(TEXT("System has %d emitters; specify emitter_name."), Handles.Num());
				return nullptr;
			}
			return &Handles[0];
		}
		for (const FNiagaraEmitterHandle& Handle : Handles)
		{
			if (Handle.GetName().ToString().Equals(EmitterName, ESearchCase::IgnoreCase))
			{
				return &Handle;
			}
		}
		OutError = FString::Printf(TEXT("No emitter named '%s' in system."), *EmitterName);
		return nullptr;
	}

	FString GetJsonString(const TSharedPtr<FJsonObject>& Params, const FString& FieldName, const FString& DefaultValue = TEXT(""))
	{
		FString Value;
		return Params.IsValid() && Params->TryGetStringField(FieldName, Value) ? Value : DefaultValue;
	}

	double GetJsonNumber(const TSharedPtr<FJsonObject>& Params, const FString& FieldName, double DefaultValue = 0.0)
	{
		double Value = 0.0;
		return Params.IsValid() && Params->TryGetNumberField(FieldName, Value) ? Value : DefaultValue;
	}

	FString NiagaraTypeToString(const FNiagaraTypeDefinition& Type);

	FString GetRendererTypeString(const UNiagaraRendererProperties* Renderer)
	{
		if (Cast<UNiagaraSpriteRendererProperties>(Renderer))
		{
			return TEXT("sprite");
		}
		if (Cast<UNiagaraMeshRendererProperties>(Renderer))
		{
			return TEXT("mesh");
		}
		if (Cast<UNiagaraRibbonRendererProperties>(Renderer))
		{
			return TEXT("ribbon");
		}
		if (Cast<UNiagaraLightRendererProperties>(Renderer))
		{
			return TEXT("light");
		}
		return Renderer ? Renderer->GetClass()->GetName() : TEXT("null");
	}
	FString NiagaraMeshFacingModeToString(ENiagaraMeshFacingMode Mode)
	{
		if (const UEnum* Enum = StaticEnum<ENiagaraMeshFacingMode>())
		{
			return Enum->GetNameStringByValue(static_cast<int64>(Mode));
		}
		return FString::FromInt(static_cast<int32>(Mode));
	}

	bool TryReadNiagaraMeshFacingModeParam(const TSharedPtr<FJsonObject>& Params, const FString& FieldName, ENiagaraMeshFacingMode& OutMode, FString& OutError)
	{
		FString FacingModeString;
		if (!Params->TryGetStringField(FieldName, FacingModeString))
		{
			return false;
		}

		FString Normalized = FacingModeString.ToLower();
		Normalized.ReplaceInline(TEXT("_"), TEXT(""));
		Normalized.ReplaceInline(TEXT("-"), TEXT(""));
		Normalized.ReplaceInline(TEXT(" "), TEXT(""));

		if (Normalized == TEXT("default"))
		{
			OutMode = ENiagaraMeshFacingMode::Default;
			return true;
		}
		if (Normalized == TEXT("velocity"))
		{
			OutMode = ENiagaraMeshFacingMode::Velocity;
			return true;
		}
		if (Normalized == TEXT("cameraposition") || Normalized == TEXT("camera"))
		{
			OutMode = ENiagaraMeshFacingMode::CameraPosition;
			return true;
		}
		if (Normalized == TEXT("cameraplane"))
		{
			OutMode = ENiagaraMeshFacingMode::CameraPlane;
			return true;
		}

		OutError = FString::Printf(TEXT("Invalid facing_mode '%s'. Use default|velocity|camera_position|camera_plane."), *FacingModeString);
		return false;
	}
	FString RendererSourceModeToString(ENiagaraRendererSourceDataMode SourceMode)
	{
		if (const UEnum* Enum = StaticEnum<ENiagaraRendererSourceDataMode>())
		{
			return Enum->GetNameStringByValue(static_cast<int64>(SourceMode));
		}
		return FString::FromInt(static_cast<int32>(SourceMode));
	}

	FString BindingSourceToString(ENiagaraBindingSource BindingSource)
	{
		if (const UEnum* Enum = StaticEnum<ENiagaraBindingSource>())
		{
			return Enum->GetNameStringByValue(static_cast<int64>(BindingSource));
		}
		return FString::FromInt(static_cast<int32>(BindingSource));
	}

	TSharedPtr<FJsonObject> MakeAttributeBindingJson(const FString& BindingName, const FNiagaraVariableAttributeBinding& Binding)
	{
		TSharedPtr<FJsonObject> Obj = MakeShared<FJsonObject>();
		const FNiagaraVariableBase& ParamMapVariable = Binding.GetParamMapBindableVariable();
		const FNiagaraVariableBase DataSetVariable = Binding.GetDataSetBindableVariable();
		Obj->SetStringField(TEXT("binding_name"), BindingName);
		Obj->SetBoolField(TEXT("valid"), Binding.IsValid());
		Obj->SetBoolField(TEXT("exists_on_source"), Binding.DoesBindingExistOnSource());
		Obj->SetBoolField(TEXT("particle_binding"), Binding.IsParticleBinding());
		Obj->SetStringField(TEXT("source_mode"), BindingSourceToString(Binding.GetBindingSourceMode()));
		Obj->SetStringField(TEXT("display_name"), Binding.GetName().ToString());
		Obj->SetStringField(TEXT("param_map_variable"), ParamMapVariable.GetName().ToString());
		Obj->SetStringField(TEXT("dataset_variable"), DataSetVariable.GetName().ToString());
		Obj->SetStringField(TEXT("type"), NiagaraTypeToString(ParamMapVariable.GetType()));
		return Obj;
	}

	TSharedPtr<FJsonObject> MakeMeshRendererSummaryJson(UNiagaraMeshRendererProperties& MeshRenderer)
	{
		TSharedPtr<FJsonObject> Obj = MakeShared<FJsonObject>();
		Obj->SetStringField(TEXT("source_mode"), RendererSourceModeToString(MeshRenderer.SourceMode));
		Obj->SetBoolField(TEXT("override_materials"), MeshRenderer.bOverrideMaterials != 0);
		Obj->SetBoolField(TEXT("cast_shadows"), MeshRenderer.bCastShadows != 0);
		Obj->SetStringField(TEXT("mesh_bounds_scale"), MeshRenderer.MeshBoundsScale.ToString());
		Obj->SetStringField(TEXT("facing_mode"), NiagaraMeshFacingModeToString(MeshRenderer.FacingMode));
		Obj->SetNumberField(TEXT("renderer_visibility"), MeshRenderer.RendererVisibility);
		Obj->SetBoolField(TEXT("locked_axis_enable"), MeshRenderer.bLockedAxisEnable != 0);
		Obj->SetStringField(TEXT("locked_axis"), MeshRenderer.LockedAxis.ToString());

		TArray<TSharedPtr<FJsonValue>> MeshArray;
		for (int32 MeshIndex = 0; MeshIndex < MeshRenderer.Meshes.Num(); ++MeshIndex)
		{
			const FNiagaraMeshRendererMeshProperties& MeshProps = MeshRenderer.Meshes[MeshIndex];
			TSharedPtr<FJsonObject> MeshObj = MakeShared<FJsonObject>();
			MeshObj->SetNumberField(TEXT("mesh_slot"), MeshIndex);
			MeshObj->SetBoolField(TEXT("has_mesh"), MeshProps.Mesh != nullptr);
			MeshObj->SetStringField(TEXT("mesh_path"), MeshProps.Mesh ? MeshProps.Mesh->GetPathName() : FString());
			MeshObj->SetStringField(TEXT("scale"), MeshProps.Scale.ToString());
			MeshObj->SetStringField(TEXT("rotation"), MeshProps.Rotation.ToString());
			MeshObj->SetStringField(TEXT("pivot_offset"), MeshProps.PivotOffset.ToString());
			MeshArray.Add(MakeShared<FJsonValueObject>(MeshObj));
		}
		Obj->SetNumberField(TEXT("mesh_count"), MeshArray.Num());
		Obj->SetArrayField(TEXT("meshes"), MeshArray);

		TArray<TSharedPtr<FJsonValue>> MaterialArray;
		for (int32 MaterialIndex = 0; MaterialIndex < MeshRenderer.OverrideMaterials.Num(); ++MaterialIndex)
		{
			const FNiagaraMeshMaterialOverride& MaterialOverride = MeshRenderer.OverrideMaterials[MaterialIndex];
			TSharedPtr<FJsonObject> MaterialObj = MakeShared<FJsonObject>();
			MaterialObj->SetNumberField(TEXT("material_slot"), MaterialIndex);
			MaterialObj->SetBoolField(TEXT("has_explicit_material"), MaterialOverride.ExplicitMat != nullptr);
			MaterialObj->SetStringField(TEXT("explicit_material_path"), MaterialOverride.ExplicitMat ? MaterialOverride.ExplicitMat->GetPathName() : FString());
			MaterialArray.Add(MakeShared<FJsonValueObject>(MaterialObj));
		}
		Obj->SetNumberField(TEXT("override_material_count"), MaterialArray.Num());
		Obj->SetArrayField(TEXT("override_materials_array"), MaterialArray);

		TArray<TSharedPtr<FJsonValue>> BindingArray;
		BindingArray.Add(MakeShared<FJsonValueObject>(MakeAttributeBindingJson(TEXT("position"), MeshRenderer.PositionBinding)));
		BindingArray.Add(MakeShared<FJsonValueObject>(MakeAttributeBindingJson(TEXT("color"), MeshRenderer.ColorBinding)));
		BindingArray.Add(MakeShared<FJsonValueObject>(MakeAttributeBindingJson(TEXT("velocity"), MeshRenderer.VelocityBinding)));
		BindingArray.Add(MakeShared<FJsonValueObject>(MakeAttributeBindingJson(TEXT("mesh_orientation"), MeshRenderer.MeshOrientationBinding)));
		BindingArray.Add(MakeShared<FJsonValueObject>(MakeAttributeBindingJson(TEXT("scale"), MeshRenderer.ScaleBinding)));
		BindingArray.Add(MakeShared<FJsonValueObject>(MakeAttributeBindingJson(TEXT("normalized_age"), MeshRenderer.NormalizedAgeBinding)));
		BindingArray.Add(MakeShared<FJsonValueObject>(MakeAttributeBindingJson(TEXT("renderer_visibility_tag"), MeshRenderer.RendererVisibilityTagBinding)));
		BindingArray.Add(MakeShared<FJsonValueObject>(MakeAttributeBindingJson(TEXT("mesh_index"), MeshRenderer.MeshIndexBinding)));
		Obj->SetArrayField(TEXT("bindings"), BindingArray);
		return Obj;
	}

	TSharedPtr<FJsonObject> MakeRendererSummaryJson(UNiagaraRendererProperties& Renderer, int32 RendererIndex)
	{
		TSharedPtr<FJsonObject> Obj = MakeShared<FJsonObject>();
		Obj->SetNumberField(TEXT("renderer_index"), RendererIndex);
		Obj->SetStringField(TEXT("renderer_type"), GetRendererTypeString(&Renderer));
		Obj->SetStringField(TEXT("renderer_class"), Renderer.GetClass()->GetName());
		Obj->SetBoolField(TEXT("enabled"), Renderer.GetIsEnabled());
		Obj->SetBoolField(TEXT("debug_draw_enabled"), Renderer.IsDebugDrawEnabled());

		if (UNiagaraMeshRendererProperties* MeshRenderer = Cast<UNiagaraMeshRendererProperties>(&Renderer))
		{
			Obj->SetObjectField(TEXT("mesh_renderer"), MakeMeshRendererSummaryJson(*MeshRenderer));
		}
		else if (UNiagaraSpriteRendererProperties* SpriteRenderer = Cast<UNiagaraSpriteRendererProperties>(&Renderer))
		{
			Obj->SetStringField(TEXT("material_path"), SpriteRenderer->Material ? SpriteRenderer->Material->GetPathName() : FString());
		}
		else if (UNiagaraRibbonRendererProperties* RibbonRenderer = Cast<UNiagaraRibbonRendererProperties>(&Renderer))
		{
			Obj->SetStringField(TEXT("material_path"), RibbonRenderer->Material ? RibbonRenderer->Material->GetPathName() : FString());
		}
		return Obj;
	}

	bool DoesRendererMatchType(const UNiagaraRendererProperties* Renderer, const FString& RendererType)
	{
		return RendererType.IsEmpty() || GetRendererTypeString(Renderer).Equals(RendererType, ESearchCase::IgnoreCase);
	}

	int32 ResolveRendererIndex(const TArray<UNiagaraRendererProperties*>& Renderers, const TSharedPtr<FJsonObject>& Params, FString& OutError)
	{
		const int32 ExplicitIndex = static_cast<int32>(GetJsonNumber(Params, TEXT("renderer_index"), -1.0));
		if (ExplicitIndex >= 0)
		{
			if (!Renderers.IsValidIndex(ExplicitIndex) || !Renderers[ExplicitIndex])
			{
				OutError = FString::Printf(TEXT("renderer_index %d is out of range (renderer_count=%d)."), ExplicitIndex, Renderers.Num());
				return INDEX_NONE;
			}
			return ExplicitIndex;
		}

		const FString RendererType = GetJsonString(Params, TEXT("renderer_type"), TEXT(""));
		int32 MatchIndex = INDEX_NONE;
		int32 MatchCount = 0;
		for (int32 Index = 0; Index < Renderers.Num(); ++Index)
		{
			if (DoesRendererMatchType(Renderers[Index], RendererType))
			{
				MatchIndex = Index;
				++MatchCount;
			}
		}

		if (MatchCount == 1)
		{
			return MatchIndex;
		}
		if (MatchCount == 0)
		{
			OutError = RendererType.IsEmpty()
				? TEXT("Emitter has no renderers.")
				: FString::Printf(TEXT("No renderer of type '%s' found."), *RendererType);
			return INDEX_NONE;
		}

		OutError = RendererType.IsEmpty()
			? FString::Printf(TEXT("Emitter has %d renderers; specify renderer_index."), MatchCount)
			: FString::Printf(TEXT("Emitter has %d renderers of type '%s'; specify renderer_index."), MatchCount, *RendererType);
		return INDEX_NONE;
	}

	UNiagaraRendererProperties* ResolveRenderer(UNiagaraSystem& System, const TSharedPtr<FJsonObject>& Params,
		FString& OutEmitterName, FVersionedNiagaraEmitter& OutVersionedEmitter, FVersionedNiagaraEmitterData*& OutEmitterData, int32& OutRendererIndex, FString& OutError)
	{
		const FString EmitterName = GetJsonString(Params, TEXT("emitter_name"), TEXT(""));
		const FNiagaraEmitterHandle* Handle = ResolveEmitterHandle(System, EmitterName, OutError);
		if (!Handle)
		{
			return nullptr;
		}

		OutEmitterName = Handle->GetName().ToString();
		OutVersionedEmitter = Handle->GetInstance();
		OutEmitterData = Handle->GetEmitterData();
		if (!OutVersionedEmitter.Emitter || !OutEmitterData)
		{
			OutError = TEXT("Emitter handle has no valid instance data.");
			return nullptr;
		}

		const TArray<UNiagaraRendererProperties*>& Renderers = OutEmitterData->GetRenderers();
		OutRendererIndex = ResolveRendererIndex(Renderers, Params, OutError);
		if (OutRendererIndex == INDEX_NONE)
		{
			return nullptr;
		}
		return Renderers[OutRendererIndex];
	}

	bool ReadVectorParam(const TSharedPtr<FJsonObject>& Params, const FString& FieldName, FVector& OutValue, FString& OutError)
	{
		const TArray<TSharedPtr<FJsonValue>>* Values = nullptr;
		if (!Params->TryGetArrayField(FieldName, Values) || !Values)
		{
			return false;
		}
		if (Values->Num() < 3)
		{
			OutError = FString::Printf(TEXT("%s needs 3 numbers."), *FieldName);
			return false;
		}
		OutValue = FVector((*Values)[0]->AsNumber(), (*Values)[1]->AsNumber(), (*Values)[2]->AsNumber());
		return true;
	}

	bool ReadRotatorParam(const TSharedPtr<FJsonObject>& Params, const FString& FieldName, FRotator& OutValue, FString& OutError)
	{
		FVector VectorValue;
		if (!ReadVectorParam(Params, FieldName, VectorValue, OutError))
		{
			return false;
		}
		OutValue = FRotator(VectorValue.X, VectorValue.Y, VectorValue.Z);
		return true;
	}

	void RepairNiagaraEditorOverview(UNiagaraSystem& System)
	{
		UNiagaraSystemEditorData* SystemEditorData = Cast<UNiagaraSystemEditorData>(System.GetEditorData());
		if (!SystemEditorData)
		{
			return;
		}

		// MCP 经常在资产编辑器外修改 Niagara；旧 OverviewNode 可能保留空 OwningSystem，导致编辑器显示 INVALID。
		if (UEdGraph* OverviewGraph = SystemEditorData->GetSystemOverviewGraph())
		{
			TArray<UNiagaraOverviewNode*> OverviewNodes;
			OverviewGraph->GetNodesOfClass<UNiagaraOverviewNode>(OverviewNodes);
			for (UNiagaraOverviewNode* OverviewNode : OverviewNodes)
			{
				if (!OverviewNode)
				{
					continue;
				}

				OverviewNode->Modify();
				const FGuid EmitterHandleGuid = OverviewNode->GetEmitterHandleGuid();
				if (EmitterHandleGuid.IsValid())
				{
					OverviewNode->Initialize(&System, EmitterHandleGuid);
				}
				else
				{
					OverviewNode->Initialize(&System);
				}
			}
		}

		SystemEditorData->SynchronizeOverviewGraphWithSystem(System);
	}

	void MarkNiagaraSystemEdited(UNiagaraSystem& System, FMCPEditorContext& Context)
	{
		System.Modify();
		RepairNiagaraEditorOverview(System);
		System.RequestCompile(false);
		System.MarkPackageDirty();
		if (UPackage* Package = System.GetOutermost())
		{
			Context.MarkPackageDirty(Package);
		}
	}

	void MarkNiagaraRendererEdited(UNiagaraSystem& System, UNiagaraRendererProperties& Renderer, FMCPEditorContext& Context)
	{
		Renderer.Modify();
		Renderer.PostEditChange();
		MarkNiagaraSystemEdited(System, Context);
	}

	FString NodeEnabledStateToString(ENodeEnabledState State)
	{
		switch (State)
		{
		case ENodeEnabledState::Enabled:
			return TEXT("enabled");
		case ENodeEnabledState::Disabled:
			return TEXT("disabled");
		case ENodeEnabledState::DevelopmentOnly:
			return TEXT("development_only");
		default:
			return TEXT("unknown");
		}
	}

	FString JsonValueToImportText(const TSharedPtr<FJsonValue>& Value)
	{
		if (!Value.IsValid())
		{
			return FString();
		}
		switch (Value->Type)
		{
		case EJson::String:
			return Value->AsString();
		case EJson::Boolean:
			return Value->AsBool() ? TEXT("true") : TEXT("false");
		case EJson::Number:
			return FString::SanitizeFloat(Value->AsNumber());
		default:
			return FString();
		}
	}

	FString ExportStructPropertyAsText(void* Container, UObject* Owner, FProperty* Property)
	{
		if (!Container || !Property)
		{
			return FString();
		}
		FString Out;
		void* PropertyAddr = Property->ContainerPtrToValuePtr<void>(Container);
		Property->ExportText_Direct(Out, PropertyAddr, PropertyAddr, Owner, PPF_None);
		return Out;
	}

	UEdGraphPin* GetParameterMapInputPin(UEdGraphNode* Node);

	FString NiagaraTypeToString(const FNiagaraTypeDefinition& Type)
	{
		return Type.GetName();
	}

	bool ParseNiagaraValueType(const FString& ValueType, FNiagaraTypeDefinition& OutType)
	{
		const FString Type = ValueType.ToLower();
		if (Type == TEXT("float")) { OutType = FNiagaraTypeDefinition::GetFloatDef(); return true; }
		if (Type == TEXT("int")) { OutType = FNiagaraTypeDefinition::GetIntDef(); return true; }
		if (Type == TEXT("bool")) { OutType = FNiagaraTypeDefinition::GetBoolDef(); return true; }
		if (Type == TEXT("vec2") || Type == TEXT("vector2d")) { OutType = FNiagaraTypeDefinition::GetVec2Def(); return true; }
		if (Type == TEXT("vec3") || Type == TEXT("vector") || Type == TEXT("position"))
		{
			OutType = Type == TEXT("position") ? FNiagaraTypeDefinition::GetPositionDef() : FNiagaraTypeDefinition::GetVec3Def();
			return true;
		}
		if (Type == TEXT("vec4") || Type == TEXT("vector4")) { OutType = FNiagaraTypeDefinition::GetVec4Def(); return true; }
		if (Type == TEXT("quat") || Type == TEXT("quaternion")) { OutType = FNiagaraTypeDefinition::GetQuatDef(); return true; }
		if (Type == TEXT("color")) { OutType = FNiagaraTypeDefinition::GetColorDef(); return true; }
		return false;
	}

	FString MakeNiagaraUserParameterName(const FString& InName)
	{
		FString Name = InName;
		Name.TrimStartAndEndInline();
		if (!Name.StartsWith(TEXT("User."), ESearchCase::CaseSensitive))
		{
			Name = FString::Printf(TEXT("User.%s"), *Name);
		}
		return Name;
	}

	bool TryReadNumericArray(
		const TSharedPtr<FJsonObject>& Params,
		const FString& FieldName,
		int32 MinCount,
		TArray<double>& OutValues,
		FString& OutError)
	{
		const TArray<TSharedPtr<FJsonValue>>* Array = nullptr;
		if (!Params.IsValid() || !Params->TryGetArrayField(FieldName, Array) || !Array)
		{
			OutError = FString::Printf(TEXT("'%s' must be a numeric array."), *FieldName);
			return false;
		}
		if (Array->Num() < MinCount)
		{
			OutError = FString::Printf(TEXT("'%s' needs at least %d numeric values."), *FieldName, MinCount);
			return false;
		}

		OutValues.Reset(Array->Num());
		for (const TSharedPtr<FJsonValue>& JsonValue : *Array)
		{
			if (!JsonValue.IsValid() || JsonValue->Type != EJson::Number)
			{
				OutError = FString::Printf(TEXT("'%s' must contain only numbers."), *FieldName);
				return false;
			}
			OutValues.Add(JsonValue->AsNumber());
		}
		return true;
	}

	bool TryBuildNiagaraValueVariable(
		const TSharedPtr<FJsonObject>& Params,
		const FString& ParameterName,
		const FString& ValueType,
		FNiagaraVariable& OutValueVariable,
		FVector& OutPositionValue,
		bool& bOutIsPosition,
		FString& OutError)
	{
		FNiagaraTypeDefinition TypeDefinition;
		if (!ParseNiagaraValueType(ValueType, TypeDefinition))
		{
			OutError = FString::Printf(TEXT("Invalid value_type '%s'. Use float|int|bool|vec2|vec3|position|vec4|quat|color."), *ValueType);
			return false;
		}

		OutValueVariable = FNiagaraVariable(TypeDefinition, FName(*MakeNiagaraUserParameterName(ParameterName)));
		bOutIsPosition = TypeDefinition == FNiagaraTypeDefinition::GetPositionDef();

		const TSharedPtr<FJsonValue> JsonValue = Params.IsValid() ? Params->TryGetField(TEXT("value")) : nullptr;
		if (!JsonValue.IsValid())
		{
			OutError = TEXT("Missing required 'value'.");
			return false;
		}

		if (TypeDefinition == FNiagaraTypeDefinition::GetFloatDef())
		{
			if (JsonValue->Type != EJson::Number)
			{
				OutError = TEXT("'value' must be a number for float.");
				return false;
			}
			OutValueVariable.SetValue<float>(static_cast<float>(JsonValue->AsNumber()));
			return true;
		}
		if (TypeDefinition == FNiagaraTypeDefinition::GetIntDef())
		{
			if (JsonValue->Type != EJson::Number)
			{
				OutError = TEXT("'value' must be a number for int.");
				return false;
			}
			OutValueVariable.SetValue<int32>(static_cast<int32>(JsonValue->AsNumber()));
			return true;
		}
		if (TypeDefinition == FNiagaraTypeDefinition::GetBoolDef())
		{
			if (JsonValue->Type != EJson::Boolean)
			{
				OutError = TEXT("'value' must be a bool for bool.");
				return false;
			}
			FNiagaraBool BoolValue;
			BoolValue.SetValue(JsonValue->AsBool());
			OutValueVariable.SetValue<FNiagaraBool>(BoolValue);
			return true;
		}

		TArray<double> Values;
		if (TypeDefinition == FNiagaraTypeDefinition::GetVec2Def())
		{
			if (!TryReadNumericArray(Params, TEXT("value"), 2, Values, OutError)) { return false; }
			OutValueVariable.SetValue<FVector2f>(FVector2f(static_cast<float>(Values[0]), static_cast<float>(Values[1])));
			return true;
		}
		if (TypeDefinition == FNiagaraTypeDefinition::GetVec3Def())
		{
			if (!TryReadNumericArray(Params, TEXT("value"), 3, Values, OutError)) { return false; }
			OutValueVariable.SetValue<FVector3f>(FVector3f(static_cast<float>(Values[0]), static_cast<float>(Values[1]), static_cast<float>(Values[2])));
			return true;
		}
		if (TypeDefinition == FNiagaraTypeDefinition::GetPositionDef())
		{
			if (!TryReadNumericArray(Params, TEXT("value"), 3, Values, OutError)) { return false; }
			OutPositionValue = FVector(Values[0], Values[1], Values[2]);
			return true;
		}
		if (TypeDefinition == FNiagaraTypeDefinition::GetVec4Def())
		{
			if (!TryReadNumericArray(Params, TEXT("value"), 4, Values, OutError)) { return false; }
			OutValueVariable.SetValue<FVector4f>(FVector4f(static_cast<float>(Values[0]), static_cast<float>(Values[1]), static_cast<float>(Values[2]), static_cast<float>(Values[3])));
			return true;
		}
		if (TypeDefinition == FNiagaraTypeDefinition::GetColorDef())
		{
			if (!TryReadNumericArray(Params, TEXT("value"), 4, Values, OutError)) { return false; }
			OutValueVariable.SetValue<FLinearColor>(FLinearColor(static_cast<float>(Values[0]), static_cast<float>(Values[1]), static_cast<float>(Values[2]), static_cast<float>(Values[3])));
			return true;
		}

		OutError = FString::Printf(TEXT("Unsupported value_type '%s'."), *ValueType);
		return false;
	}

	FString GetInputNameForModule(const FNiagaraVariable& InputVariable, const FString& ModuleName)
	{
		const FString FullName = InputVariable.GetName().ToString();
		const FString ModuleNodePrefix = ModuleName + TEXT(".");
		if (FullName.StartsWith(ModuleNodePrefix, ESearchCase::IgnoreCase))
		{
			return FullName.Mid(ModuleNodePrefix.Len());
		}
		const FString ModuleNamespacePrefix = TEXT("Module.");
		if (FullName.StartsWith(ModuleNamespacePrefix, ESearchCase::IgnoreCase))
		{
			return FullName.Mid(ModuleNamespacePrefix.Len());
		}
		return FullName;
	}

	bool DoesInputNameMatch(const FNiagaraVariable& InputVariable, const FString& ModuleName, const FString& Query)
	{
		if (Query.IsEmpty())
		{
			return true;
		}
		const FString FullName = InputVariable.GetName().ToString();
		const FString ShortName = GetInputNameForModule(InputVariable, ModuleName);
		return FullName.Equals(Query, ESearchCase::IgnoreCase) || ShortName.Equals(Query, ESearchCase::IgnoreCase) || FullName.EndsWith(TEXT(".") + Query, ESearchCase::IgnoreCase);
	}

	FString NormalizeNiagaraInputNameForMatch(const FString& Name)
	{
		FString Result;
		Result.Reserve(Name.Len());
		for (const TCHAR Character : Name)
		{
			if (FChar::IsAlnum(Character))
			{
				Result.AppendChar(FChar::ToLower(Character));
			}
		}
		return Result;
	}

	bool DoesStaticInputNameMatch(const FString& ActualName, const FString& Query)
	{
		return ActualName.Equals(Query, ESearchCase::IgnoreCase)
			|| NormalizeNiagaraInputNameForMatch(ActualName).Equals(NormalizeNiagaraInputNameForMatch(Query), ESearchCase::CaseSensitive);
	}

	bool TryResolveKnownStaticEnumAlias(const FString& ValueString, int32& OutValue)
	{
		const FString NormalizedValue = NormalizeNiagaraInputNameForMatch(ValueString);
		if (NormalizedValue == TEXT("depthbuffer") || NormalizedValue == TEXT("scenedepth") || NormalizedValue == TEXT("zdepth"))
		{
			OutValue = 0;
			return true;
		}
		if (NormalizedValue == TEXT("distancefield") || NormalizedValue == TEXT("distancefields") || NormalizedValue == TEXT("meshdistancefield") || NormalizedValue == TEXT("meshdistancefields"))
		{
			OutValue = 1;
			return true;
		}
		return false;
	}

	FString GetEnumValueNamesForError(const UEnum& Enum)
	{
		TArray<FString> Names;
		for (int32 Index = 0; Index < Enum.NumEnums(); ++Index)
		{
			if (Enum.HasMetaData(TEXT("Hidden"), Index))
			{
				continue;
			}
			Names.Add(FString::Printf(TEXT("%s=%lld"), *Enum.GetNameStringByIndex(Index), Enum.GetValueByIndex(Index)));
		}
		return FString::Join(Names, TEXT(", "));
	}

	bool TryParseEnumValueString(const UEnum& Enum, const FString& ValueString, int32& OutValue)
	{
		const int64 DirectValue = Enum.GetValueByNameString(ValueString);
		if (DirectValue != INDEX_NONE)
		{
			OutValue = static_cast<int32>(DirectValue);
			return true;
		}

		const FString NormalizedValue = NormalizeNiagaraInputNameForMatch(ValueString);
		for (int32 Index = 0; Index < Enum.NumEnums(); ++Index)
		{
			if (Enum.HasMetaData(TEXT("Hidden"), Index))
			{
				continue;
			}

			const FString Name = Enum.GetNameStringByIndex(Index);
			const FString DisplayName = Enum.GetDisplayNameTextByIndex(Index).ToString();
			if (NormalizeNiagaraInputNameForMatch(Name) == NormalizedValue || NormalizeNiagaraInputNameForMatch(DisplayName) == NormalizedValue)
			{
				OutValue = static_cast<int32>(Enum.GetValueByIndex(Index));
				return true;
			}
		}

		return TryResolveKnownStaticEnumAlias(ValueString, OutValue) && Enum.IsValidEnumValue(OutValue);
	}

	bool TryReadStaticIndexValue(const TSharedPtr<FJsonObject>& Params, const FNiagaraTypeDefinition& SwitchType, int32& OutValue, FString& OutError)
	{
		const TSharedPtr<FJsonValue> Value = Params.IsValid() ? Params->TryGetField(TEXT("value")) : nullptr;
		if (!Value.IsValid())
		{
			OutError = TEXT("Missing required 'value'.");
			return false;
		}

		const UEnum* Enum = SwitchType.GetEnum();
		switch (Value->Type)
		{
		case EJson::Number:
			OutValue = static_cast<int32>(Value->AsNumber());
			break;
		case EJson::String:
		{
			const FString ValueString = Value->AsString().TrimStartAndEnd();
			if (ValueString.IsNumeric())
			{
				OutValue = FCString::Atoi(*ValueString);
				break;
			}

			if (Enum)
			{
				if (TryParseEnumValueString(*Enum, ValueString, OutValue))
				{
					break;
				}
				OutError = FString::Printf(TEXT("Unsupported enum value '%s' for %s. Available values: %s"), *ValueString, *Enum->GetName(), *GetEnumValueNamesForError(*Enum));
				return false;
			}

			if (TryResolveKnownStaticEnumAlias(ValueString, OutValue))
			{
				break;
			}

			OutError = FString::Printf(TEXT("Unsupported static int alias '%s'; use a number or depth_buffer|distance_field."), *ValueString);
			return false;
		}
		default:
			OutError = TEXT("value must be an integer number or string/enum alias.");
			return false;
		}

		if (Enum && !Enum->IsValidEnumValue(OutValue))
		{
			OutError = FString::Printf(TEXT("Value %d is not valid for enum %s. Available values: %s"), OutValue, *Enum->GetName(), *GetEnumValueNamesForError(*Enum));
			return false;
		}
		return true;
	}

	bool MakeNiagaraStaticPinDefaultValue(const FNiagaraTypeDefinition& SwitchType, int32 Value, FString& OutDefaultValue)
	{
		FNiagaraVariable ValueVariable(SwitchType, NAME_None);
		FNiagaraInt32 NiagaraValue;
		NiagaraValue.Value = Value;
		ValueVariable.SetValue<FNiagaraInt32>(NiagaraValue);

		const UEdGraphSchema_Niagara* NiagaraSchema = GetDefault<UEdGraphSchema_Niagara>();
		return NiagaraSchema && NiagaraSchema->TryGetPinDefaultValueFromNiagaraVariable(ValueVariable, OutDefaultValue);
	}

	UEdGraphPin* FindStaticSwitchPinByName(UNiagaraNodeFunctionCall& ModuleNode, FCompileConstantResolver& Resolver, const FString& ParameterName, TSet<UEdGraphPin*>& OutHiddenPins, FString& OutAvailableNames)
	{
		TArray<UEdGraphPin*> StaticSwitchPins;
		FNiagaraStackGraphUtilities::GetStackFunctionStaticSwitchPins(ModuleNode, StaticSwitchPins, OutHiddenPins, Resolver);

		TArray<FString> Names;
		for (UEdGraphPin* StaticSwitchPin : StaticSwitchPins)
		{
			if (!StaticSwitchPin)
			{
				continue;
			}

			const FString PinName = StaticSwitchPin->PinName.ToString();
			Names.Add(PinName);
			if (DoesStaticInputNameMatch(PinName, ParameterName))
			{
				return StaticSwitchPin;
			}
		}

		OutAvailableNames = FString::Join(Names, TEXT(", "));
		return nullptr;
	}

	FNiagaraParameterHandle MakeAliasedInputHandle(UNiagaraNodeFunctionCall& ModuleNode, const FString& InputName)
	{
		const FNiagaraParameterHandle ModuleInputHandle = FNiagaraParameterHandle::CreateModuleParameterHandle(FName(*InputName));
		return FNiagaraParameterHandle::CreateAliasedModuleParameterHandle(ModuleInputHandle, &ModuleNode);
	}

	UEdGraphNode* GetStackFunctionOverrideNodeLocal(UNiagaraNodeFunctionCall& FunctionCallNode)
	{
		UEdGraphPin* ParameterMapInput = GetParameterMapInputPin(&FunctionCallNode);
		if (ParameterMapInput && ParameterMapInput->LinkedTo.Num() == 1)
		{
			UEdGraphNode* LinkedNode = ParameterMapInput->LinkedTo[0]->GetOwningNode();
			if (LinkedNode && LinkedNode->GetClass()->GetName().Contains(TEXT("NiagaraNodeParameterMapSet")))
			{
				return LinkedNode;
			}
		}
		return nullptr;
	}

	UEdGraphPin* GetStackFunctionInputOverridePinLocal(UNiagaraNodeFunctionCall& ModuleNode, const FString& InputName)
	{
		const FNiagaraParameterHandle AliasedInputHandle = MakeAliasedInputHandle(ModuleNode, InputName);
		UEdGraphNode* OverrideNode = GetStackFunctionOverrideNodeLocal(ModuleNode);
		if (!OverrideNode)
		{
			return nullptr;
		}

		TArray<UEdGraphPin*> InputPins;
		for (UEdGraphPin* Pin : OverrideNode->Pins)
		{
			if (Pin && Pin->Direction == EGPD_Input)
			{
				InputPins.Add(Pin);
			}
		}
		if (UEdGraphPin** OverridePinPtr = InputPins.FindByPredicate([&AliasedInputHandle](const UEdGraphPin* Pin)
		{
			return Pin && Pin->PinName == AliasedInputHandle.GetParameterHandleString();
		}))
		{
			return *OverridePinPtr;
		}
		return nullptr;
	}

	FNiagaraVariable MakeRapidIterationParameter(const FString& UniqueEmitterName, ENiagaraScriptUsage ScriptUsage, const FName& AliasedInputName, const FNiagaraTypeDefinition& InputType);

	TArray<TSharedPtr<FJsonValue>> MakeNumberArrayJson(std::initializer_list<double> Values)
	{
		TArray<TSharedPtr<FJsonValue>> Result;
		for (double Value : Values)
		{
			Result.Add(MakeShared<FJsonValueNumber>(Value));
		}
		return Result;
	}

	bool NiagaraVariableValueToJson(const FNiagaraVariable& Variable, TSharedPtr<FJsonValue>& OutValue, FString& OutText)
	{
		const FNiagaraTypeDefinition& Type = Variable.GetType();
		if (!Variable.IsDataAllocated())
		{
			return false;
		}

		if (Type == FNiagaraTypeDefinition::GetFloatDef())
		{
			const float Value = Variable.GetValue<float>();
			OutValue = MakeShared<FJsonValueNumber>(Value);
			OutText = FString::SanitizeFloat(Value);
			return true;
		}
		if (Type == FNiagaraTypeDefinition::GetIntDef())
		{
			const int32 Value = Variable.GetValue<int32>();
			OutValue = MakeShared<FJsonValueNumber>(Value);
			OutText = FString::FromInt(Value);
			return true;
		}
		if (Type == FNiagaraTypeDefinition::GetBoolDef())
		{
			const bool bValue = Variable.GetValue<bool>();
			OutValue = MakeShared<FJsonValueBoolean>(bValue);
			OutText = bValue ? TEXT("true") : TEXT("false");
			return true;
		}
		if (Type == FNiagaraTypeDefinition::GetVec2Def())
		{
			const FVector2f Value = Variable.GetValue<FVector2f>();
			OutValue = MakeShared<FJsonValueArray>(MakeNumberArrayJson({ Value.X, Value.Y }));
			OutText = FString::Printf(TEXT("%g,%g"), Value.X, Value.Y);
			return true;
		}
		if (Type == FNiagaraTypeDefinition::GetVec3Def())
		{
			const FVector3f Value = Variable.GetValue<FVector3f>();
			OutValue = MakeShared<FJsonValueArray>(MakeNumberArrayJson({ Value.X, Value.Y, Value.Z }));
			OutText = FString::Printf(TEXT("%g,%g,%g"), Value.X, Value.Y, Value.Z);
			return true;
		}
		if (Type == FNiagaraTypeDefinition::GetPositionDef())
		{
			const FNiagaraPosition Value = Variable.GetValue<FNiagaraPosition>();
			OutValue = MakeShared<FJsonValueArray>(MakeNumberArrayJson({ Value.X, Value.Y, Value.Z }));
			OutText = FString::Printf(TEXT("%g,%g,%g"), Value.X, Value.Y, Value.Z);
			return true;
		}
		if (Type == FNiagaraTypeDefinition::GetVec4Def())
		{
			const FVector4f Value = Variable.GetValue<FVector4f>();
			OutValue = MakeShared<FJsonValueArray>(MakeNumberArrayJson({ Value.X, Value.Y, Value.Z, Value.W }));
			OutText = FString::Printf(TEXT("%g,%g,%g,%g"), Value.X, Value.Y, Value.Z, Value.W);
			return true;
		}
		if (Type == FNiagaraTypeDefinition::GetColorDef())
		{
			const FLinearColor Value = Variable.GetValue<FLinearColor>();
			OutValue = MakeShared<FJsonValueArray>(MakeNumberArrayJson({ Value.R, Value.G, Value.B, Value.A }));
			OutText = Value.ToString();
			return true;
		}

		return false;
	}

	void AppendRapidIterationValueJson(
		TSharedPtr<FJsonObject> Obj,
		const UNiagaraScript* OwnerScript,
		const FString& UniqueEmitterName,
		ENiagaraScriptUsage Usage,
		const FName& AliasedInputName,
		const FNiagaraTypeDefinition& InputType)
	{
		if (!Obj.IsValid() || !OwnerScript)
		{
			return;
		}

		FNiagaraVariable RapidIterationParameter = MakeRapidIterationParameter(UniqueEmitterName, Usage, AliasedInputName, InputType);
		Obj->SetStringField(TEXT("rapid_iteration_parameter"), RapidIterationParameter.GetName().ToString());

		const uint8* ValueData = OwnerScript->RapidIterationParameters.GetParameterData(RapidIterationParameter);
		Obj->SetBoolField(TEXT("rapid_iteration_has_value"), ValueData != nullptr);
		if (!ValueData)
		{
			return;
		}

		FNiagaraVariable ValueVariable(InputType, RapidIterationParameter.GetName());
		ValueVariable.SetData(ValueData);

		TSharedPtr<FJsonValue> JsonValue;
		FString ValueText;
		if (NiagaraVariableValueToJson(ValueVariable, JsonValue, ValueText) && JsonValue.IsValid())
		{
			Obj->SetField(TEXT("rapid_iteration_value"), JsonValue);
			Obj->SetStringField(TEXT("rapid_iteration_value_text"), ValueText);
		}
		else
		{
			Obj->SetStringField(TEXT("rapid_iteration_value_text"), InputType.ToString(ValueVariable.GetData()));
		}
	}

    FString GetCustomHlslTextFromNode(const UNiagaraNodeCustomHlsl& CustomHlslNode)
    {
        FStrProperty* CustomHlslProperty = FindFProperty<FStrProperty>(CustomHlslNode.GetClass(), TEXT("CustomHlsl"));
        return CustomHlslProperty ? CustomHlslProperty->GetPropertyValue_InContainer(&CustomHlslNode) : FString();
    }

    bool SetCustomHlslTextOnNode(UNiagaraNodeCustomHlsl& CustomHlslNode, const FString& CustomHlsl, FString& OutError)
    {
        FStrProperty* CustomHlslProperty = FindFProperty<FStrProperty>(CustomHlslNode.GetClass(), TEXT("CustomHlsl"));
        if (!CustomHlslProperty)
        {
            OutError = TEXT("UNiagaraNodeCustomHlsl.CustomHlsl property was not found.");
            return false;
        }

        CustomHlslNode.Modify();
        CustomHlslProperty->SetPropertyValue_InContainer(&CustomHlslNode, CustomHlsl);
        CustomHlslNode.MarkNodeRequiresSynchronization(TEXT("Custom HLSL Changed"), true);
        return true;
    }

	UNiagaraDataInterface* GetDataInterfaceFromInputNode(UNiagaraNodeInput* InputNode);
	TSharedPtr<FJsonObject> MakeDataInterfaceDebugJson(UNiagaraDataInterface* DataInterface);

	FString PinDirectionToString(const EEdGraphPinDirection Direction)
	{
		switch (Direction)
		{
		case EGPD_Input:
			return TEXT("input");
		case EGPD_Output:
			return TEXT("output");
		default:
			return TEXT("unknown");
		}
	}

	TSharedPtr<FJsonObject> MakeInternalFunctionCallDebugJson(UNiagaraNodeFunctionCall* FunctionNode)
	{
		TSharedPtr<FJsonObject> Obj = MakeShared<FJsonObject>();
		if (!FunctionNode)
		{
			Obj->SetBoolField(TEXT("valid"), false);
			return Obj;
		}

		Obj->SetBoolField(TEXT("valid"), true);
		Obj->SetStringField(TEXT("function_name"), FunctionNode->GetFunctionName());
		Obj->SetStringField(TEXT("node_title"), FunctionNode->GetNodeTitle(ENodeTitleType::FullTitle).ToString());
		Obj->SetStringField(TEXT("node_guid"), FunctionNode->NodeGuid.ToString(EGuidFormats::DigitsWithHyphens));
		Obj->SetStringField(TEXT("function_script"), FunctionNode->FunctionScript ? FunctionNode->FunctionScript->GetPathName() : FString());

		TArray<TSharedPtr<FJsonValue>> SpecifierArray;
		for (const TPair<FName, FName>& Pair : FunctionNode->FunctionSpecifiers)
		{
			TSharedPtr<FJsonObject> SpecifierObj = MakeShared<FJsonObject>();
			SpecifierObj->SetStringField(TEXT("name"), Pair.Key.ToString());
			SpecifierObj->SetStringField(TEXT("value"), Pair.Value.ToString());
			SpecifierArray.Add(MakeShared<FJsonValueObject>(SpecifierObj));
		}
		Obj->SetArrayField(TEXT("function_specifiers"), SpecifierArray);

		TArray<TSharedPtr<FJsonValue>> PinArray;
		for (UEdGraphPin* Pin : FunctionNode->Pins)
		{
			if (!Pin)
			{
				continue;
			}

			TSharedPtr<FJsonObject> PinObj = MakeShared<FJsonObject>();
			PinObj->SetStringField(TEXT("name"), Pin->PinName.ToString());
			PinObj->SetStringField(TEXT("direction"), PinDirectionToString(Pin->Direction));
			PinObj->SetStringField(TEXT("type_category"), Pin->PinType.PinCategory.ToString());
			PinObj->SetStringField(TEXT("type_subcategory_object"), Pin->PinType.PinSubCategoryObject.IsValid() ? Pin->PinType.PinSubCategoryObject->GetPathName() : FString());
			PinObj->SetNumberField(TEXT("linked_pin_count"), Pin->LinkedTo.Num());

			TArray<TSharedPtr<FJsonValue>> LinkedArray;
			for (UEdGraphPin* LinkedPin : Pin->LinkedTo)
			{
				TSharedPtr<FJsonObject> LinkedObj = MakeShared<FJsonObject>();
				LinkedObj->SetStringField(TEXT("pin_name"), LinkedPin ? LinkedPin->PinName.ToString() : FString());
				LinkedObj->SetStringField(TEXT("direction"), LinkedPin ? PinDirectionToString(LinkedPin->Direction) : FString());
				LinkedObj->SetStringField(TEXT("node_class"), (LinkedPin && LinkedPin->GetOwningNode()) ? LinkedPin->GetOwningNode()->GetClass()->GetName() : FString());
				LinkedObj->SetStringField(TEXT("node_title"), (LinkedPin && LinkedPin->GetOwningNode()) ? LinkedPin->GetOwningNode()->GetNodeTitle(ENodeTitleType::FullTitle).ToString() : FString());
				LinkedArray.Add(MakeShared<FJsonValueObject>(LinkedObj));
			}
			PinObj->SetArrayField(TEXT("linked_pins"), LinkedArray);
			PinArray.Add(MakeShared<FJsonValueObject>(PinObj));
		}
		Obj->SetArrayField(TEXT("pins"), PinArray);
		return Obj;
	}

	TSharedPtr<FJsonObject> MakeScratchModuleInternalGraphDebugJson(UNiagaraNodeFunctionCall* ModuleNode)
	{
		TSharedPtr<FJsonObject> Obj = MakeShared<FJsonObject>();
		UNiagaraScript* FunctionScript = ModuleNode ? ModuleNode->FunctionScript : nullptr;
		Obj->SetBoolField(TEXT("has_function_script"), FunctionScript != nullptr);
		Obj->SetStringField(TEXT("function_script"), FunctionScript ? FunctionScript->GetPathName() : FString());

		UNiagaraScriptSource* ScriptSource = FunctionScript ? Cast<UNiagaraScriptSource>(FunctionScript->GetLatestSource()) : nullptr;
		UNiagaraGraph* InnerGraph = ScriptSource ? ScriptSource->NodeGraph : nullptr;
		Obj->SetBoolField(TEXT("has_graph"), InnerGraph != nullptr);
		if (!InnerGraph)
		{
			return Obj;
		}

		TArray<UNiagaraNodeFunctionCall*> FunctionNodes;
		InnerGraph->GetNodesOfClass<UNiagaraNodeFunctionCall>(FunctionNodes);
		TArray<TSharedPtr<FJsonValue>> FunctionArray;
		for (UNiagaraNodeFunctionCall* FunctionNode : FunctionNodes)
		{
			FunctionArray.Add(MakeShared<FJsonValueObject>(MakeInternalFunctionCallDebugJson(FunctionNode)));
		}
		Obj->SetNumberField(TEXT("function_call_count"), FunctionArray.Num());
		Obj->SetArrayField(TEXT("function_calls"), FunctionArray);

		TArray<TSharedPtr<FJsonValue>> ParameterMapSetArray;
		for (UEdGraphNode* Node : InnerGraph->Nodes)
		{
			if (!Node || !Node->GetClass()->GetName().Contains(TEXT("NiagaraNodeParameterMapSet")))
			{
				continue;
			}

			TSharedPtr<FJsonObject> NodeObj = MakeShared<FJsonObject>();
			NodeObj->SetStringField(TEXT("node_title"), Node->GetNodeTitle(ENodeTitleType::FullTitle).ToString());
			NodeObj->SetStringField(TEXT("node_guid"), Node->NodeGuid.ToString(EGuidFormats::DigitsWithHyphens));

			TArray<TSharedPtr<FJsonValue>> PinArray;
			for (UEdGraphPin* Pin : Node->Pins)
			{
				if (!Pin)
				{
					continue;
				}

				TSharedPtr<FJsonObject> PinObj = MakeShared<FJsonObject>();
				PinObj->SetStringField(TEXT("name"), Pin->PinName.ToString());
				PinObj->SetStringField(TEXT("direction"), PinDirectionToString(Pin->Direction));
				PinObj->SetStringField(TEXT("type_category"), Pin->PinType.PinCategory.ToString());
				PinObj->SetStringField(TEXT("type_subcategory_object"), Pin->PinType.PinSubCategoryObject.IsValid() ? Pin->PinType.PinSubCategoryObject->GetPathName() : FString());
				PinObj->SetBoolField(TEXT("orphaned"), Pin->bOrphanedPin);
				PinObj->SetNumberField(TEXT("linked_pin_count"), Pin->LinkedTo.Num());

				TArray<TSharedPtr<FJsonValue>> LinkedArray;
				for (UEdGraphPin* LinkedPin : Pin->LinkedTo)
				{
					TSharedPtr<FJsonObject> LinkedObj = MakeShared<FJsonObject>();
					LinkedObj->SetStringField(TEXT("pin_name"), LinkedPin ? LinkedPin->PinName.ToString() : FString());
					LinkedObj->SetStringField(TEXT("direction"), LinkedPin ? PinDirectionToString(LinkedPin->Direction) : FString());
					LinkedObj->SetStringField(TEXT("type_category"), LinkedPin ? LinkedPin->PinType.PinCategory.ToString() : FString());
					LinkedObj->SetStringField(TEXT("type_subcategory_object"), (LinkedPin && LinkedPin->PinType.PinSubCategoryObject.IsValid()) ? LinkedPin->PinType.PinSubCategoryObject->GetPathName() : FString());
					LinkedObj->SetStringField(TEXT("node_class"), (LinkedPin && LinkedPin->GetOwningNode()) ? LinkedPin->GetOwningNode()->GetClass()->GetName() : FString());
					LinkedObj->SetStringField(TEXT("node_title"), (LinkedPin && LinkedPin->GetOwningNode()) ? LinkedPin->GetOwningNode()->GetNodeTitle(ENodeTitleType::FullTitle).ToString() : FString());
					LinkedArray.Add(MakeShared<FJsonValueObject>(LinkedObj));
				}
				PinObj->SetArrayField(TEXT("linked_pins"), LinkedArray);
				PinArray.Add(MakeShared<FJsonValueObject>(PinObj));
			}
			NodeObj->SetArrayField(TEXT("pins"), PinArray);
			ParameterMapSetArray.Add(MakeShared<FJsonValueObject>(NodeObj));
		}
		Obj->SetNumberField(TEXT("parameter_map_set_count"), ParameterMapSetArray.Num());
		Obj->SetArrayField(TEXT("parameter_map_set_nodes"), ParameterMapSetArray);
		return Obj;
	}

	TSharedPtr<FJsonObject> MakeModuleInputBindingJson(
		UNiagaraNodeFunctionCall& ModuleNode,
		const FNiagaraVariable& InputVariable,
		bool bHidden,
		const UNiagaraScript* OwnerScript = nullptr,
		const FString& UniqueEmitterName = FString(),
		ENiagaraScriptUsage Usage = ENiagaraScriptUsage::Module)
	{
		const FString ModuleName = ModuleNode.GetFunctionName();
		const FString InputName = GetInputNameForModule(InputVariable, ModuleName);
		TSharedPtr<FJsonObject> Obj = MakeShared<FJsonObject>();
		Obj->SetStringField(TEXT("input_name"), InputName);
		Obj->SetStringField(TEXT("full_name"), InputVariable.GetName().ToString());
		Obj->SetStringField(TEXT("type"), NiagaraTypeToString(InputVariable.GetType()));
		Obj->SetBoolField(TEXT("hidden"), bHidden);

		const FNiagaraParameterHandle ModuleInputHandle = FNiagaraParameterHandle::CreateModuleParameterHandle(FName(*InputName));
		const FNiagaraParameterHandle AliasedInputHandle = FNiagaraParameterHandle::CreateAliasedModuleParameterHandle(ModuleInputHandle, &ModuleNode);
		AppendRapidIterationValueJson(Obj, OwnerScript, UniqueEmitterName, Usage, AliasedInputHandle.GetParameterHandleString(), InputVariable.GetType());

		UEdGraphPin* OverridePin = GetStackFunctionInputOverridePinLocal(ModuleNode, InputName);
		Obj->SetBoolField(TEXT("has_override_pin"), OverridePin != nullptr);
		if (!OverridePin)
		{
			Obj->SetStringField(TEXT("value_mode"), TEXT("default_or_rapid_iteration"));
			return Obj;
		}

		Obj->SetStringField(TEXT("override_pin_name"), OverridePin->PinName.ToString());
		Obj->SetStringField(TEXT("override_pin_id"), OverridePin->PinId.ToString(EGuidFormats::DigitsWithHyphens));
		Obj->SetNumberField(TEXT("linked_pin_count"), OverridePin->LinkedTo.Num());
		if (OverridePin->LinkedTo.Num() == 0)
		{
			Obj->SetStringField(TEXT("value_mode"), TEXT("override_unlinked"));
			return Obj;
		}

		UEdGraphPin* LinkedPin = OverridePin->LinkedTo[0];
		UEdGraphNode* LinkedNode = LinkedPin ? LinkedPin->GetOwningNode() : nullptr;
		Obj->SetStringField(TEXT("linked_pin_name"), LinkedPin ? LinkedPin->PinName.ToString() : FString());
		Obj->SetStringField(TEXT("linked_node_class"), LinkedNode ? LinkedNode->GetClass()->GetName() : FString());
		Obj->SetStringField(TEXT("linked_node_title"), LinkedNode ? LinkedNode->GetNodeTitle(ENodeTitleType::ListView).ToString() : FString());
		if (UNiagaraNodeInput* InputNode = LinkedNode ? Cast<UNiagaraNodeInput>(LinkedNode) : nullptr)
		{
			Obj->SetStringField(TEXT("linked_input_name"), InputNode->Input.GetName().ToString());
			Obj->SetStringField(TEXT("linked_input_type"), NiagaraTypeToString(InputNode->Input.GetType()));
			if (UNiagaraDataInterface* DataInterface = GetDataInterfaceFromInputNode(InputNode))
			{
				Obj->SetObjectField(TEXT("linked_data_interface"), MakeDataInterfaceDebugJson(DataInterface));
			}
		}

		if (LinkedPin && LinkedNode && LinkedNode->GetClass()->GetName().Contains(TEXT("NiagaraNodeParameterMapGet")))
		{
			Obj->SetStringField(TEXT("value_mode"), TEXT("linked_parameter"));
			Obj->SetStringField(TEXT("linked_parameter"), LinkedPin->PinName.ToString());
		}
        else if (UNiagaraNodeCustomHlsl* CustomHlslNode = LinkedNode ? Cast<UNiagaraNodeCustomHlsl>(LinkedNode) : nullptr)
        {
            Obj->SetStringField(TEXT("value_mode"), TEXT("custom_hlsl"));
            Obj->SetStringField(TEXT("custom_hlsl"), GetCustomHlslTextFromNode(*CustomHlslNode));
        }
		else if (UNiagaraNodeFunctionCall* DynamicInputNode = LinkedNode ? Cast<UNiagaraNodeFunctionCall>(LinkedNode) : nullptr)
		{
			Obj->SetStringField(TEXT("value_mode"), TEXT("dynamic_input"));
			Obj->SetStringField(TEXT("dynamic_input_name"), DynamicInputNode->GetFunctionName());
			Obj->SetStringField(TEXT("dynamic_input_script"), DynamicInputNode->FunctionScript ? DynamicInputNode->FunctionScript->GetPathName() : FString());
		}
		else
		{
			Obj->SetStringField(TEXT("value_mode"), TEXT("other_override"));
		}
		return Obj;
	}

	struct FNiagaraFloatCurveKeySpec
	{
		float Time = 0.0f;
		float Value = 0.0f;
	};

	bool TryReadFloatCurveKeys(const TSharedPtr<FJsonObject>& Params, TArray<FNiagaraFloatCurveKeySpec>& OutKeys, FString& OutError)
	{
		const TArray<TSharedPtr<FJsonValue>>* KeyValues = nullptr;
		if (!Params->TryGetArrayField(TEXT("keys"), KeyValues) || !KeyValues)
		{
			OutError = TEXT("Required parameter 'keys' is missing. Use [{\"time\":0,\"value\":1}, ...].");
			return false;
		}
		if (KeyValues->Num() < 2)
		{
			OutError = TEXT("Parameter 'keys' must contain at least two points.");
			return false;
		}

		for (const TSharedPtr<FJsonValue>& KeyValue : *KeyValues)
		{
			if (!KeyValue.IsValid() || KeyValue->Type != EJson::Object)
			{
				OutError = TEXT("Each curve key must be an object with numeric 'time' and 'value'.");
				return false;
			}

			const TSharedPtr<FJsonObject> KeyObject = KeyValue->AsObject();
			double Time = 0.0;
			double Value = 0.0;
			if (!KeyObject.IsValid()
				|| !KeyObject->TryGetNumberField(TEXT("time"), Time)
				|| !KeyObject->TryGetNumberField(TEXT("value"), Value))
			{
				OutError = TEXT("Each curve key must provide numeric 'time' and 'value'.");
				return false;
			}

			FNiagaraFloatCurveKeySpec KeySpec;
			KeySpec.Time = static_cast<float>(Time);
			KeySpec.Value = static_cast<float>(Value);
			OutKeys.Add(KeySpec);
		}

		OutKeys.Sort([](const FNiagaraFloatCurveKeySpec& A, const FNiagaraFloatCurveKeySpec& B)
		{
			return A.Time < B.Time;
		});
		return true;
	}

	bool DoesFunctionCallUseScript(UNiagaraNodeFunctionCall& FunctionCallNode, const FString& ScriptNameOrPath)
	{
		if (ScriptNameOrPath.IsEmpty() || !FunctionCallNode.FunctionScript)
		{
			return false;
		}

		const FString ScriptPath = FunctionCallNode.FunctionScript->GetPathName();
		const FString ScriptName = FunctionCallNode.FunctionScript->GetName();
		return ScriptPath.Contains(ScriptNameOrPath) || ScriptName.Equals(ScriptNameOrPath, ESearchCase::IgnoreCase);
	}

	UNiagaraNodeFunctionCall* FindLinkedDynamicInputNodeRecursive(UEdGraphPin* SourcePin, const FString& ScriptNameOrPath, TSet<UEdGraphNode*>& VisitedNodes, int32 Depth = 0)
	{
		if (!SourcePin || Depth > 16)
		{
			return nullptr;
		}

		for (UEdGraphPin* LinkedPin : SourcePin->LinkedTo)
		{
			UEdGraphNode* LinkedNode = LinkedPin ? LinkedPin->GetOwningNode() : nullptr;
			if (!LinkedNode || VisitedNodes.Contains(LinkedNode))
			{
				continue;
			}
			VisitedNodes.Add(LinkedNode);

			UNiagaraNodeFunctionCall* FunctionCallNode = Cast<UNiagaraNodeFunctionCall>(LinkedNode);
			if (!FunctionCallNode)
			{
				continue;
			}

			if (DoesFunctionCallUseScript(*FunctionCallNode, ScriptNameOrPath))
			{
				return FunctionCallNode;
			}

			// 动态输入可套多层类型转换节点；遍历函数节点全部链接 pin，才能稳定找到内层 FloatFromCurve。
			for (UEdGraphPin* InputPin : FunctionCallNode->Pins)
			{
				if (!InputPin
					|| InputPin == LinkedPin
					|| InputPin->PinName == FName(TEXT("InputMap"))
					|| InputPin->PinName == FName(TEXT("OutputMap"))
					|| InputPin->LinkedTo.Num() == 0)
				{
					continue;
				}
				if (UNiagaraNodeFunctionCall* NestedNode = FindLinkedDynamicInputNodeRecursive(InputPin, ScriptNameOrPath, VisitedNodes, Depth + 1))
				{
					return NestedNode;
				}
			}
		}

		return nullptr;
	}

	UNiagaraDataInterfaceCurve* GetFloatCurveDataInterfaceFromInputNode(UNiagaraNodeInput* InputNode)
	{
		if (!InputNode)
		{
			return nullptr;
		}

		FObjectProperty* DataInterfaceProperty = FindFProperty<FObjectProperty>(UNiagaraNodeInput::StaticClass(), TEXT("DataInterface"));
		if (!DataInterfaceProperty)
		{
			return nullptr;
		}

		UObject* DataInterfaceObject = DataInterfaceProperty->GetObjectPropertyValue_InContainer(InputNode);
		return Cast<UNiagaraDataInterfaceCurve>(DataInterfaceObject);
	}

	UNiagaraDataInterface* GetDataInterfaceFromInputNode(UNiagaraNodeInput* InputNode)
	{
		if (!InputNode)
		{
			return nullptr;
		}

		FObjectProperty* DataInterfaceProperty = FindFProperty<FObjectProperty>(UNiagaraNodeInput::StaticClass(), TEXT("DataInterface"));
		if (!DataInterfaceProperty)
		{
			return nullptr;
		}

		UObject* DataInterfaceObject = DataInterfaceProperty->GetObjectPropertyValue_InContainer(InputNode);
		return Cast<UNiagaraDataInterface>(DataInterfaceObject);
	}

	void AppendBoolPropertyIfPresent(TSharedPtr<FJsonObject>& Obj, UObject* Object, const TCHAR* PropertyName)
	{
		if (!Object)
		{
			return;
		}

		if (const FBoolProperty* BoolProperty = FindFProperty<FBoolProperty>(Object->GetClass(), PropertyName))
		{
			Obj->SetBoolField(PropertyName, BoolProperty->GetPropertyValue_InContainer(Object));
		}
	}

	TSharedPtr<FJsonObject> MakeDataInterfaceDebugJson(UNiagaraDataInterface* DataInterface)
	{
		TSharedPtr<FJsonObject> Obj = MakeShared<FJsonObject>();
		if (!DataInterface)
		{
			Obj->SetBoolField(TEXT("valid"), false);
			return Obj;
		}

		Obj->SetBoolField(TEXT("valid"), true);
		Obj->SetStringField(TEXT("class"), DataInterface->GetClass() ? DataInterface->GetClass()->GetName() : FString());
		Obj->SetStringField(TEXT("path"), DataInterface->GetPathName());

		if (const FObjectProperty* ChannelProperty = FindFProperty<FObjectProperty>(DataInterface->GetClass(), TEXT("Channel")))
		{
			UObject* ChannelObject = ChannelProperty->GetObjectPropertyValue_InContainer(DataInterface);
			Obj->SetStringField(TEXT("Channel"), ChannelObject ? ChannelObject->GetPathName() : FString());
		}

		AppendBoolPropertyIfPresent(Obj, DataInterface, TEXT("bReadCurrentFrame"));
		AppendBoolPropertyIfPresent(Obj, DataInterface, TEXT("bUpdateSourceDataEveryTick"));
		AppendBoolPropertyIfPresent(Obj, DataInterface, TEXT("bAutoLinkToSpawningNDC"));
		AppendBoolPropertyIfPresent(Obj, DataInterface, TEXT("bOverrideSpawnGroupToDataChannelIndex"));
		AppendBoolPropertyIfPresent(Obj, DataInterface, TEXT("bOnlySpawnOnceOnSubticks"));
		return Obj;
	}

	UNiagaraDataInterfaceCurve* FindLinkedFloatCurveDataInterfaceRecursive(UEdGraphPin* SourcePin, TSet<UEdGraphNode*>& VisitedNodes, int32 Depth = 0)
	{
		if (!SourcePin || Depth > 16)
		{
			return nullptr;
		}

		for (UEdGraphPin* LinkedPin : SourcePin->LinkedTo)
		{
			UEdGraphNode* LinkedNode = LinkedPin ? LinkedPin->GetOwningNode() : nullptr;
			if (!LinkedNode)
			{
				continue;
			}

			if (UNiagaraNodeInput* InputNode = Cast<UNiagaraNodeInput>(LinkedNode))
			{
				if (UNiagaraDataInterfaceCurve* CurveDataInterface = GetFloatCurveDataInterfaceFromInputNode(InputNode))
				{
					return CurveDataInterface;
				}
			}

			if (VisitedNodes.Contains(LinkedNode))
			{
				continue;
			}
			VisitedNodes.Add(LinkedNode);

			for (UEdGraphPin* CandidatePin : LinkedNode->Pins)
			{
				if (!CandidatePin
					|| CandidatePin == LinkedPin
					|| CandidatePin->PinName == FName(TEXT("InputMap"))
					|| CandidatePin->PinName == FName(TEXT("OutputMap"))
					|| CandidatePin->LinkedTo.Num() == 0)
				{
					continue;
				}

				if (UNiagaraDataInterfaceCurve* CurveDataInterface = FindLinkedFloatCurveDataInterfaceRecursive(CandidatePin, VisitedNodes, Depth + 1))
				{
					return CurveDataInterface;
				}
			}
		}

		return nullptr;
	}

	TSharedPtr<FJsonObject> MakeCurveInputNodeJson(UNiagaraNodeInput& InputNode, UNiagaraDataInterfaceCurve& CurveDataInterface)
	{
		TSharedPtr<FJsonObject> NodeJson = MakeShared<FJsonObject>();
		NodeJson->SetStringField(TEXT("node_class"), InputNode.GetClass()->GetName());
		NodeJson->SetStringField(TEXT("node_title"), InputNode.GetNodeTitle(ENodeTitleType::FullTitle).ToString());
		NodeJson->SetStringField(TEXT("input_name"), InputNode.Input.GetName().ToString());
		NodeJson->SetStringField(TEXT("input_type"), InputNode.Input.GetType().GetNameText().ToString());
		NodeJson->SetStringField(TEXT("data_interface_name"), CurveDataInterface.GetName());
		NodeJson->SetStringField(TEXT("data_interface_path"), CurveDataInterface.GetPathName());

		TArray<TSharedPtr<FJsonValue>> KeysJson;
		for (auto It = CurveDataInterface.Curve.GetKeyHandleIterator(); It; ++It)
		{
			const FKeyHandle KeyHandle = *It;
			const FRichCurveKey& Key = CurveDataInterface.Curve.GetKey(KeyHandle);
			TSharedPtr<FJsonObject> KeyJson = MakeShared<FJsonObject>();
			KeyJson->SetNumberField(TEXT("time"), Key.Time);
			KeyJson->SetNumberField(TEXT("value"), Key.Value);
			KeysJson.Add(MakeShared<FJsonValueObject>(KeyJson));
		}
		NodeJson->SetArrayField(TEXT("keys"), KeysJson);
		return NodeJson;
	}

	void AppendGraphFloatCurveInputs(UNiagaraGraph& Graph, TArray<TSharedPtr<FJsonValue>>& OutCurveInputs)
	{
		for (UEdGraphNode* Node : Graph.Nodes)
		{
			UNiagaraNodeInput* InputNode = Cast<UNiagaraNodeInput>(Node);
			if (!InputNode)
			{
				continue;
			}

			UNiagaraDataInterfaceCurve* CurveDataInterface = GetFloatCurveDataInterfaceFromInputNode(InputNode);
			if (!CurveDataInterface)
			{
				continue;
			}

			OutCurveInputs.Add(MakeShared<FJsonValueObject>(MakeCurveInputNodeJson(*InputNode, *CurveDataInterface)));
		}
	}

	UNiagaraDataInterfaceCurve* FindGraphFloatCurveDataInterfaceByName(UNiagaraGraph& Graph, const TArray<FString>& Needles, FString& OutMatchedInputName, int32& OutMatchCount)
	{
		OutMatchedInputName.Reset();
		OutMatchCount = 0;
		UNiagaraDataInterfaceCurve* MatchedCurve = nullptr;

		for (UEdGraphNode* Node : Graph.Nodes)
		{
			UNiagaraNodeInput* InputNode = Cast<UNiagaraNodeInput>(Node);
			if (!InputNode)
			{
				continue;
			}

			UNiagaraDataInterfaceCurve* CurveDataInterface = GetFloatCurveDataInterfaceFromInputNode(InputNode);
			if (!CurveDataInterface)
			{
				continue;
			}

			const FString CandidateInputName = InputNode->Input.GetName().ToString();
			const FString CandidateDataInterfaceName = CurveDataInterface->GetName();
			for (const FString& Needle : Needles)
			{
				if (Needle.IsEmpty())
				{
					continue;
				}

				const FString SanitizedNeedle = Needle.Replace(TEXT(" "), TEXT("_")).Replace(TEXT("."), TEXT("_"));
				const bool bMatchesInputName = CandidateInputName.Contains(Needle, ESearchCase::IgnoreCase);
				const bool bMatchesDataInterfaceName = CandidateDataInterfaceName.Contains(SanitizedNeedle, ESearchCase::IgnoreCase);
				if (bMatchesInputName || bMatchesDataInterfaceName)
				{
					OutMatchCount++;
					if (!MatchedCurve)
					{
						MatchedCurve = CurveDataInterface;
						OutMatchedInputName = CandidateInputName;
					}
					break;
				}
			}
		}

		return OutMatchCount == 1 ? MatchedCurve : nullptr;
	}

	void AppendLinkedPinTraceRecursive(UEdGraphPin* SourcePin, TArray<TSharedPtr<FJsonValue>>& OutTrace, TSet<UEdGraphNode*>& VisitedNodes, int32 Depth = 0)
	{
		if (!SourcePin || Depth > 6 || OutTrace.Num() >= 80)
		{
			return;
		}

		for (UEdGraphPin* LinkedPin : SourcePin->LinkedTo)
		{
			UEdGraphNode* LinkedNode = LinkedPin ? LinkedPin->GetOwningNode() : nullptr;
			if (!LinkedNode)
			{
				continue;
			}

			TSharedPtr<FJsonObject> TraceJson = MakeShared<FJsonObject>();
			TraceJson->SetNumberField(TEXT("depth"), Depth);
			TraceJson->SetStringField(TEXT("source_pin"), SourcePin->PinName.ToString());
			TraceJson->SetStringField(TEXT("linked_pin"), LinkedPin->PinName.ToString());
			TraceJson->SetStringField(TEXT("node_class"), LinkedNode->GetClass()->GetName());
			TraceJson->SetStringField(TEXT("node_title"), LinkedNode->GetNodeTitle(ENodeTitleType::FullTitle).ToString());
			if (UNiagaraNodeFunctionCall* FunctionCallNode = Cast<UNiagaraNodeFunctionCall>(LinkedNode))
			{
				TraceJson->SetStringField(TEXT("function_name"), FunctionCallNode->GetFunctionName());
				TraceJson->SetStringField(TEXT("function_script"), FunctionCallNode->FunctionScript ? FunctionCallNode->FunctionScript->GetPathName() : FString());
			}
			if (UNiagaraNodeInput* InputNode = Cast<UNiagaraNodeInput>(LinkedNode))
			{
				TraceJson->SetStringField(TEXT("input_name"), InputNode->Input.GetName().ToString());
				if (UNiagaraDataInterfaceCurve* CurveDataInterface = GetFloatCurveDataInterfaceFromInputNode(InputNode))
				{
					TraceJson->SetStringField(TEXT("data_interface_class"), CurveDataInterface->GetClass()->GetName());
					TraceJson->SetStringField(TEXT("data_interface_path"), CurveDataInterface->GetPathName());
				}
			}
			OutTrace.Add(MakeShared<FJsonValueObject>(TraceJson));

			if (VisitedNodes.Contains(LinkedNode))
			{
				continue;
			}
			VisitedNodes.Add(LinkedNode);

			for (UEdGraphPin* CandidatePin : LinkedNode->Pins)
			{
				if (!CandidatePin
					|| CandidatePin == LinkedPin
					|| CandidatePin->LinkedTo.Num() == 0
					|| CandidatePin->PinName == FName(TEXT("InputMap"))
					|| CandidatePin->PinName == FName(TEXT("OutputMap")))
				{
					continue;
				}
				AppendLinkedPinTraceRecursive(CandidatePin, OutTrace, VisitedNodes, Depth + 1);
			}
		}
	}

	UNiagaraDataInterfaceCurve* GetOrCreateLinkedFloatCurveDataInterface(UEdGraphPin& CurveOverridePin, const FString& InputNodeName, bool bReplaceExisting)
	{
		if (CurveOverridePin.LinkedTo.Num() > 0)
		{
			if (!bReplaceExisting)
			{
				return nullptr;
			}

			CurveOverridePin.Modify();
			CurveOverridePin.BreakAllPinLinks();
		}

		UNiagaraDataInterface* DataObject = nullptr;
		FNiagaraStackGraphUtilities::SetDataInterfaceValueForFunctionInput(
			CurveOverridePin,
			UNiagaraDataInterfaceCurve::StaticClass(),
			InputNodeName,
			DataObject);
		return Cast<UNiagaraDataInterfaceCurve>(DataObject);
	}

	/** Map a stage string to its ENiagaraScriptUsage. Returns false on unknown stage. */
	bool ParseStage(const FString& Stage, ENiagaraScriptUsage& OutUsage)
	{
		if (Stage.Equals(TEXT("system_spawn"), ESearchCase::IgnoreCase)) { OutUsage = ENiagaraScriptUsage::SystemSpawnScript; return true; }
		if (Stage.Equals(TEXT("system_update"), ESearchCase::IgnoreCase)) { OutUsage = ENiagaraScriptUsage::SystemUpdateScript; return true; }
		if (Stage.Equals(TEXT("particle_spawn"), ESearchCase::IgnoreCase)) { OutUsage = ENiagaraScriptUsage::ParticleSpawnScript; return true; }
		if (Stage.Equals(TEXT("particle_update"), ESearchCase::IgnoreCase)) { OutUsage = ENiagaraScriptUsage::ParticleUpdateScript; return true; }
		if (Stage.Equals(TEXT("emitter_spawn"), ESearchCase::IgnoreCase)) { OutUsage = ENiagaraScriptUsage::EmitterSpawnScript; return true; }
		if (Stage.Equals(TEXT("emitter_update"), ESearchCase::IgnoreCase)) { OutUsage = ENiagaraScriptUsage::EmitterUpdateScript; return true; }
		return false;
	}

	bool IsSystemStage(ENiagaraScriptUsage Usage)
	{
		return Usage == ENiagaraScriptUsage::SystemSpawnScript || Usage == ENiagaraScriptUsage::SystemUpdateScript;
	}

	UNiagaraScript* GetSystemStageScript(UNiagaraSystem& System, ENiagaraScriptUsage Usage)
	{
		switch (Usage)
		{
		case ENiagaraScriptUsage::SystemSpawnScript: return System.GetSystemSpawnScript();
		case ENiagaraScriptUsage::SystemUpdateScript: return System.GetSystemUpdateScript();
		default: return nullptr;
		}
	}

	/** Get the per-stage UNiagaraScript that owns the rapid-iteration parameters for a stage. */
	UNiagaraScript* GetStageScript(FVersionedNiagaraEmitterData& EmitterData, ENiagaraScriptUsage Usage)
	{
		switch (Usage)
		{
		case ENiagaraScriptUsage::ParticleSpawnScript: return EmitterData.SpawnScriptProps.Script;
		case ENiagaraScriptUsage::ParticleUpdateScript: return EmitterData.UpdateScriptProps.Script;
		case ENiagaraScriptUsage::EmitterSpawnScript: return EmitterData.EmitterSpawnScriptProps.Script;
		case ENiagaraScriptUsage::EmitterUpdateScript: return EmitterData.EmitterUpdateScriptProps.Script;
		default: return nullptr;
		}
	}

	/** Resolve the emitter graph (UNiagaraGraph) from emitter data. */
	UNiagaraGraph* GetEmitterGraph(FVersionedNiagaraEmitterData& EmitterData)
	{
		if (UNiagaraScriptSource* Source = Cast<UNiagaraScriptSource>(EmitterData.GraphSource))
		{
			return Source->NodeGraph;
		}
		return nullptr;
	}

	// The NiagaraEditor module does NOT export UNiagaraGraph::FindOutputNode or
	// FNiagaraStackGraphUtilities::GetOrderedModuleNodes, so we walk the graph's
	// public node array directly (Cast on the public UEdGraph::Nodes is fully
	// link-safe and avoids depending on un-exported helpers).

	/** Find the stage output node for a usage by scanning the graph's nodes. */
	UNiagaraNodeOutput* FindOutputNodeForUsage(UNiagaraGraph* Graph, ENiagaraScriptUsage Usage)
	{
		if (!Graph)
		{
			return nullptr;
		}
		for (UEdGraphNode* Node : Graph->Nodes)
		{
			if (UNiagaraNodeOutput* OutputNode = Cast<UNiagaraNodeOutput>(Node))
			{
				if (OutputNode->GetUsage() == Usage)
				{
					return OutputNode;
				}
			}
		}
		return nullptr;
	}

	/** Find a module function-call node by its display name (graph-wide). */
	UNiagaraNodeFunctionCall* FindModuleNodeByName(UNiagaraGraph* Graph, const FString& ModuleName)
	{
		if (!Graph)
		{
			return nullptr;
		}
		for (UEdGraphNode* Node : Graph->Nodes)
		{
			if (UNiagaraNodeFunctionCall* FunctionNode = Cast<UNiagaraNodeFunctionCall>(Node))
			{
				if (FunctionNode->GetFunctionName().Equals(ModuleName, ESearchCase::IgnoreCase))
				{
					return FunctionNode;
				}
			}
		}
		return nullptr;
	}

	/** Count module (function-call) nodes in the graph (diagnostic only). */
	int32 CountModuleNodes(UNiagaraGraph* Graph)
	{
		int32 Count = 0;
		if (Graph)
		{
			for (UEdGraphNode* Node : Graph->Nodes)
			{
				if (Cast<UNiagaraNodeFunctionCall>(Node))
				{
					++Count;
				}
			}
		}
		return Count;
	}

	/**
	 * Replicates FNiagaraStackGraphUtilities::CreateRapidIterationParameter (which
	 * NiagaraEditor does not export) on top of the exported runtime helper
	 * FNiagaraUtilities::ConvertVariableToRapidIterationConstantName.
	 */
	FNiagaraVariable MakeRapidIterationParameter(const FString& UniqueEmitterName, ENiagaraScriptUsage ScriptUsage, const FName& AliasedInputName, const FNiagaraTypeDefinition& InputType)
	{
		FNiagaraVariable InputVariable(InputType, AliasedInputName);
		if (ScriptUsage == ENiagaraScriptUsage::SystemSpawnScript || ScriptUsage == ENiagaraScriptUsage::SystemUpdateScript)
		{
			return FNiagaraUtilities::ConvertVariableToRapidIterationConstantName(InputVariable, nullptr, ScriptUsage);
		}
		return FNiagaraUtilities::ConvertVariableToRapidIterationConstantName(InputVariable, *UniqueEmitterName, ScriptUsage);
	}

	FString CompileStatusToString(ENiagaraScriptCompileStatus Status)
	{
		if (const UEnum* Enum = StaticEnum<ENiagaraScriptCompileStatus>())
		{
			return Enum->GetNameStringByValue(static_cast<int64>(Status));
		}
		return TEXT("Unknown");
	}

	FString CompileSeverityToString(FNiagaraCompileEventSeverity Severity)
	{
		switch (Severity)
		{
		case FNiagaraCompileEventSeverity::Log: return TEXT("Log");
		case FNiagaraCompileEventSeverity::Display: return TEXT("Display");
		case FNiagaraCompileEventSeverity::Warning: return TEXT("Warning");
		case FNiagaraCompileEventSeverity::Error: return TEXT("Error");
		default: return TEXT("Unknown");
		}
	}

	FString CompileEventSourceToString(FNiagaraCompileEventSource Source)
	{
		switch (Source)
		{
		case FNiagaraCompileEventSource::Unset: return TEXT("Unset");
		case FNiagaraCompileEventSource::ScriptDependency: return TEXT("ScriptDependency");
		default: return TEXT("Unknown");
		}
	}

	bool ParseCompileMinSeverity(const FString& MinSeverity, FNiagaraCompileEventSeverity& OutSeverity)
	{
		if (MinSeverity.Equals(TEXT("log"), ESearchCase::IgnoreCase)) { OutSeverity = FNiagaraCompileEventSeverity::Log; return true; }
		if (MinSeverity.Equals(TEXT("display"), ESearchCase::IgnoreCase)) { OutSeverity = FNiagaraCompileEventSeverity::Display; return true; }
		if (MinSeverity.Equals(TEXT("warning"), ESearchCase::IgnoreCase)) { OutSeverity = FNiagaraCompileEventSeverity::Warning; return true; }
		if (MinSeverity.Equals(TEXT("error"), ESearchCase::IgnoreCase)) { OutSeverity = FNiagaraCompileEventSeverity::Error; return true; }
		return false;
	}

	FString UsageToDisplayString(ENiagaraScriptUsage Usage)
	{
		switch (Usage)
		{
		case ENiagaraScriptUsage::SystemSpawnScript: return TEXT("System Spawn");
		case ENiagaraScriptUsage::SystemUpdateScript: return TEXT("System Update");
		case ENiagaraScriptUsage::EmitterSpawnScript: return TEXT("Emitter Spawn");
		case ENiagaraScriptUsage::EmitterUpdateScript: return TEXT("Emitter Update");
		case ENiagaraScriptUsage::ParticleSpawnScript:
		case ENiagaraScriptUsage::ParticleSpawnScriptInterpolated: return TEXT("Particle Spawn");
		case ENiagaraScriptUsage::ParticleUpdateScript: return TEXT("Particle Update");
		case ENiagaraScriptUsage::ParticleEventScript: return TEXT("Particle Event");
		case ENiagaraScriptUsage::ParticleSimulationStageScript: return TEXT("Particle Simulation Stage");
		case ENiagaraScriptUsage::ParticleGPUComputeScript: return TEXT("Particle GPU Compute");
		default: return UsageToString(Usage);
		}
	}

	UNiagaraGraph* GetScriptGraph(UNiagaraScript* Script)
	{
		if (!Script)
		{
			return nullptr;
		}
		if (UNiagaraScriptSource* Source = Cast<UNiagaraScriptSource>(Script->GetLatestSource()))
		{
			return Source->NodeGraph;
		}
		return nullptr;
	}

	FString GetNodeNameForGuid(UNiagaraGraph* Graph, const FGuid& NodeGuid)
	{
		if (!Graph || !NodeGuid.IsValid())
		{
			return FString();
		}
		for (UEdGraphNode* Node : Graph->Nodes)
		{
			if (Node && Node->NodeGuid == NodeGuid)
			{
				if (UNiagaraNodeFunctionCall* FunctionNode = Cast<UNiagaraNodeFunctionCall>(Node))
				{
					return FunctionNode->GetFunctionName();
				}
				return Node->GetNodeTitle(ENodeTitleType::ListView).ToString();
			}
		}
		return FString();
	}

	FString FindCompileEventNodeName(UNiagaraGraph* Graph, const FNiagaraCompileEvent& Event)
	{
		FString NodeName = GetNodeNameForGuid(Graph, Event.NodeGuid);
		if (!NodeName.IsEmpty())
		{
			return NodeName;
		}
		for (int32 Index = Event.StackGuids.Num() - 1; Index >= 0; --Index)
		{
			NodeName = GetNodeNameForGuid(Graph, Event.StackGuids[Index]);
			if (!NodeName.IsEmpty())
			{
				return NodeName;
			}
		}
		return FString();
	}

	TSharedPtr<FJsonObject> MakeCompileEventJson(
		const FNiagaraCompileEvent& Event,
		UNiagaraScript* Script,
		UNiagaraGraph* Graph,
		const FString& Scope,
		const FString& EmitterName)
	{
		TSharedPtr<FJsonObject> EventObj = MakeShared<FJsonObject>();
		const FString Severity = CompileSeverityToString(Event.Severity);
		const FString UsageName = Script ? UsageToString(Script->GetUsage()) : TEXT("Unknown");
		const FString ScriptDisplayName = Script ? UsageToDisplayString(Script->GetUsage()) : TEXT("Unknown");
		const FString NodeName = FindCompileEventNodeName(Graph, Event);
		const FString Message = Event.Message.IsEmpty() ? Event.ShortDescription : Event.Message;

		FString Prefix = ScriptDisplayName;
		if (!NodeName.IsEmpty())
		{
			Prefix += FString::Printf(TEXT(" - %s"), *NodeName);
		}

		EventObj->SetStringField(TEXT("severity"), Severity);
		EventObj->SetStringField(TEXT("source"), CompileEventSourceToString(Event.Source));
		EventObj->SetStringField(TEXT("message"), Event.Message);
		EventObj->SetStringField(TEXT("short_description"), Event.ShortDescription);
		EventObj->SetStringField(TEXT("display_text"), FString::Printf(TEXT("%s - %s - %s"), *Prefix, *Severity, *Message));
		EventObj->SetStringField(TEXT("scope"), Scope);
		EventObj->SetStringField(TEXT("emitter_name"), EmitterName);
		EventObj->SetStringField(TEXT("script_usage"), UsageName);
		EventObj->SetStringField(TEXT("script_display_name"), ScriptDisplayName);
		EventObj->SetStringField(TEXT("script_name"), Script ? Script->GetName() : FString());
		EventObj->SetStringField(TEXT("node_name"), NodeName);
		EventObj->SetStringField(TEXT("node_guid"), Event.NodeGuid.ToString(EGuidFormats::DigitsWithHyphens));
		EventObj->SetStringField(TEXT("pin_guid"), Event.PinGuid.ToString(EGuidFormats::DigitsWithHyphens));

		TArray<TSharedPtr<FJsonValue>> StackGuidArray;
		for (const FGuid& StackGuid : Event.StackGuids)
		{
			StackGuidArray.Add(MakeShared<FJsonValueString>(StackGuid.ToString(EGuidFormats::DigitsWithHyphens)));
		}
		EventObj->SetArrayField(TEXT("stack_guids"), StackGuidArray);
		return EventObj;
	}

	TSharedPtr<FJsonObject> MakeScriptDiagnosticsJson(
		UNiagaraScript* Script,
		UNiagaraGraph* Graph,
		const FString& Scope,
		const FString& EmitterName,
		FNiagaraCompileEventSeverity MinSeverity,
		TArray<TSharedPtr<FJsonValue>>& OutFlatEvents,
		int32& OutErrorCount,
		int32& OutWarningCount)
	{
		TSharedPtr<FJsonObject> ScriptObj = MakeShared<FJsonObject>();
		ScriptObj->SetStringField(TEXT("scope"), Scope);
		ScriptObj->SetStringField(TEXT("emitter_name"), EmitterName);
		ScriptObj->SetStringField(TEXT("script_name"), Script ? Script->GetName() : FString());
		ScriptObj->SetStringField(TEXT("script_usage"), Script ? UsageToString(Script->GetUsage()) : TEXT("Unknown"));
		ScriptObj->SetStringField(TEXT("script_display_name"), Script ? UsageToDisplayString(Script->GetUsage()) : TEXT("Unknown"));
		ScriptObj->SetBoolField(TEXT("valid"), Script != nullptr);

		TArray<TSharedPtr<FJsonValue>> Events;
		int32 ScriptErrors = 0;
		int32 ScriptWarnings = 0;
		if (Script)
		{
			ScriptObj->SetBoolField(TEXT("is_compilable"), Script->IsCompilable());
			ScriptObj->SetBoolField(TEXT("source_synchronized"), Script->AreScriptAndSourceSynchronized());
			ScriptObj->SetStringField(TEXT("compile_status"), CompileStatusToString(Script->GetLastCompileStatus()));
			ScriptObj->SetStringField(TEXT("error_message"), Script->GetVMExecutableData().ErrorMsg);

			for (const FNiagaraCompileEvent& Event : Script->GetVMExecutableData().LastCompileEvents)
			{
				if (static_cast<uint8>(Event.Severity) < static_cast<uint8>(MinSeverity))
				{
					continue;
				}
				if (Event.Severity == FNiagaraCompileEventSeverity::Error)
				{
					++ScriptErrors;
					++OutErrorCount;
				}
				else if (Event.Severity == FNiagaraCompileEventSeverity::Warning)
				{
					++ScriptWarnings;
					++OutWarningCount;
				}

				TSharedPtr<FJsonObject> EventObj = MakeCompileEventJson(Event, Script, Graph, Scope, EmitterName);
				Events.Add(MakeShared<FJsonValueObject>(EventObj));
				OutFlatEvents.Add(MakeShared<FJsonValueObject>(EventObj));
			}
		}
		else
		{
			ScriptObj->SetStringField(TEXT("compile_status"), TEXT("Missing"));
		}

		ScriptObj->SetNumberField(TEXT("error_count"), ScriptErrors);
		ScriptObj->SetNumberField(TEXT("warning_count"), ScriptWarnings);
		ScriptObj->SetNumberField(TEXT("event_count"), Events.Num());
		ScriptObj->SetArrayField(TEXT("events"), Events);
		return ScriptObj;
	}

	struct FMCPNiagaraStackModuleData
	{
		UNiagaraNodeFunctionCall* Node = nullptr;
		ENiagaraScriptUsage Usage = ENiagaraScriptUsage::Module;
		FGuid UsageId;
		int32 Index = INDEX_NONE;
	};

	UEdGraphPin* FindParameterMapPin(TConstArrayView<UEdGraphPin*> Pins)
	{
		for (UEdGraphPin* Pin : Pins)
		{
			if (!Pin)
			{
				continue;
			}
			if (const UEdGraphSchema_Niagara* NiagaraSchema = Cast<UEdGraphSchema_Niagara>(Pin->GetSchema()))
			{
				if (NiagaraSchema->PinToTypeDefinition(Pin) == FNiagaraTypeDefinition::GetParameterMapDef())
				{
					return Pin;
				}
			}
		}
		return nullptr;
	}

	UEdGraphPin* GetParameterMapInputPin(UEdGraphNode* Node)
	{
		TArray<UEdGraphPin*> InputPins;
		if (Node)
		{
			for (UEdGraphPin* Pin : Node->Pins)
			{
				if (Pin && Pin->Direction == EGPD_Input)
				{
					InputPins.Add(Pin);
				}
			}
		}
		return FindParameterMapPin(InputPins);
	}

	UEdGraphPin* GetParameterMapOutputPin(UEdGraphNode* Node)
	{
		TArray<UEdGraphPin*> OutputPins;
		if (Node)
		{
			for (UEdGraphPin* Pin : Node->Pins)
			{
				if (Pin && Pin->Direction == EGPD_Output)
				{
					OutputPins.Add(Pin);
				}
			}
		}
		return FindParameterMapPin(OutputPins);
	}

   bool IsNiagaraDynamicAddPin(const UEdGraphPin* Pin)
    {
        return Pin
            && Pin->PinType.PinCategory == UEdGraphSchema_Niagara::PinCategoryMisc
            && Pin->PinType.PinSubCategory == FName(TEXT("DynamicAddPin"));
    }

    UEdGraphPin* FindNonAddOutputPinByType(UEdGraphNode* Node, const FNiagaraTypeDefinition& ExpectedType)
    {
        if (!Node)
        {
            return nullptr;
        }

        const UEdGraphSchema_Niagara* NiagaraSchema = GetDefault<UEdGraphSchema_Niagara>();
        for (UEdGraphPin* Pin : Node->Pins)
        {
            if (Pin && Pin->Direction == EGPD_Output && !IsNiagaraDynamicAddPin(Pin) && NiagaraSchema->PinToTypeDefinition(Pin) == ExpectedType)
            {
                return Pin;
            }
        }
        return nullptr;
    }

    void RemoveLinkedOverrideValueNodeLocal(UEdGraphPin& OverridePin)
    {
        if (OverridePin.LinkedTo.Num() != 1 || !OverridePin.LinkedTo[0])
        {
            OverridePin.Modify();
            OverridePin.BreakAllPinLinks();
            return;
        }

        UEdGraphPin* LinkedPin = OverridePin.LinkedTo[0];
        UEdGraphNode* LinkedNode = LinkedPin->GetOwningNode();
        UEdGraph* Graph = LinkedNode ? LinkedNode->GetGraph() : nullptr;
        OverridePin.Modify();
        OverridePin.BreakAllPinLinks();

        if (!Graph || !LinkedNode)
        {
            return;
        }

        const FString LinkedClassName = LinkedNode->GetClass()->GetName();
        const bool bCanRemoveStackValueNode = LinkedClassName.Contains(TEXT("NiagaraNodeFunctionCall"))
            || LinkedClassName.Contains(TEXT("NiagaraNodeCustomHlsl"))
            || LinkedClassName.Contains(TEXT("NiagaraNodeParameterMapGet"))
            || LinkedClassName.Contains(TEXT("NiagaraNodeInput"));
        if (bCanRemoveStackValueNode)
        {
            // 只移除当前输入 override 链路上的旧值节点，不删除 Niagara 系统或关卡资产。
            for (UEdGraphPin* Pin : LinkedNode->Pins)
            {
                if (Pin)
                {
                    Pin->BreakAllPinLinks();
                }
            }
            Graph->RemoveNode(LinkedNode);
        }
    }

    UNiagaraNodeCustomHlsl* CreateCustomHlslDynamicInputForOverride(UEdGraphPin& OverridePin, const FString& CustomHlsl, FString& OutError)
    {
        UEdGraphNode* OverrideNode = OverridePin.GetOwningNode();
        UEdGraph* Graph = OverrideNode ? OverrideNode->GetGraph() : nullptr;
        const UEdGraphSchema_Niagara* NiagaraSchema = Cast<UEdGraphSchema_Niagara>(OverridePin.GetSchema());
        if (!OverrideNode || !Graph || !NiagaraSchema)
        {
            OutError = TEXT("Override pin does not belong to an editable Niagara graph.");
            return nullptr;
        }

        FNiagaraTypeDefinition OutputType = NiagaraSchema->PinToTypeDefinition(&OverridePin);
        if (!OutputType.IsValid())
        {
            OutError = TEXT("Override pin has an invalid Niagara type.");
            return nullptr;
        }

        Graph->Modify();
        FGraphNodeCreator<UNiagaraNodeCustomHlsl> CustomNodeCreator(*Graph);
        UNiagaraNodeCustomHlsl* CustomHlslNode = CustomNodeCreator.CreateNode();
        CustomHlslNode->Modify();
        CustomHlslNode->ScriptUsage = ENiagaraScriptUsage::DynamicInput;
        CustomHlslNode->Signature.Name = TEXT("Custom Hlsl");
        CustomHlslNode->Signature.Inputs.Empty();
        CustomHlslNode->Signature.Outputs.Empty();
        CustomHlslNode->Signature.Inputs.Add(FNiagaraVariable(FNiagaraTypeDefinition::GetParameterMapDef(), TEXT("Map")));
        CustomHlslNode->Signature.Outputs.Add(FNiagaraVariable(OutputType, TEXT("CustomHLSLOutput")));
        CustomNodeCreator.Finalize();

        if (!SetCustomHlslTextOnNode(*CustomHlslNode, CustomHlsl, OutError))
        {
            Graph->RemoveNode(CustomHlslNode);
            return nullptr;
        }

        UEdGraphPin* CustomInputPin = GetParameterMapInputPin(CustomHlslNode);
        UEdGraphPin* CustomOutputPin = FindNonAddOutputPinByType(CustomHlslNode, OutputType);
        UEdGraphPin* OverrideNodeInputPin = GetParameterMapInputPin(OverrideNode);
        UEdGraphPin* PreviousStackOutputPin = (OverrideNodeInputPin && OverrideNodeInputPin->LinkedTo.Num() > 0) ? OverrideNodeInputPin->LinkedTo[0] : nullptr;
        if (!CustomInputPin || !CustomOutputPin || !PreviousStackOutputPin)
        {
            OutError = TEXT("Failed to find pins needed to connect the Custom HLSL dynamic input.");
            Graph->RemoveNode(CustomHlslNode);
            return nullptr;
        }

        CustomInputPin->MakeLinkTo(PreviousStackOutputPin);
        CustomOutputPin->MakeLinkTo(&OverridePin);
        return CustomHlslNode;
    }

	void GetOrderedModuleNodesForOutput(UNiagaraNodeOutput* OutputNode, TArray<UNiagaraNodeFunctionCall*>& OutModuleNodes)
	{
		UEdGraphNode* PreviousNode = OutputNode;
		while (PreviousNode)
		{
			UEdGraphPin* PreviousInputPin = GetParameterMapInputPin(PreviousNode);
			if (!PreviousInputPin || PreviousInputPin->LinkedTo.Num() != 1)
			{
				break;
			}

			UEdGraphNode* CurrentNode = PreviousInputPin->LinkedTo[0] ? PreviousInputPin->LinkedTo[0]->GetOwningNode() : nullptr;
			if (UNiagaraNodeFunctionCall* ModuleNode = Cast<UNiagaraNodeFunctionCall>(CurrentNode))
			{
				OutModuleNodes.Insert(ModuleNode, 0);
			}
			PreviousNode = CurrentNode;
		}
	}

	void CollectStackModuleData(UNiagaraGraph* Graph, TArray<FMCPNiagaraStackModuleData>& OutModuleData)
	{
		if (!Graph)
		{
			return;
		}

		for (UEdGraphNode* Node : Graph->Nodes)
		{
			UNiagaraNodeOutput* OutputNode = Cast<UNiagaraNodeOutput>(Node);
			if (!OutputNode)
			{
				continue;
			}

			TArray<UNiagaraNodeFunctionCall*> ModuleNodes;
			GetOrderedModuleNodesForOutput(OutputNode, ModuleNodes);
			for (int32 Index = 0; Index < ModuleNodes.Num(); ++Index)
			{
				FMCPNiagaraStackModuleData ModuleData;
				ModuleData.Node = ModuleNodes[Index];
				ModuleData.Usage = OutputNode->GetUsage();
				ModuleData.UsageId = OutputNode->GetUsageId();
				ModuleData.Index = Index;
				OutModuleData.Add(ModuleData);
			}
		}
	}

	bool FindUniqueModuleDataByName(UNiagaraGraph* Graph, const FString& ModuleName, const FString& Stage, FMCPNiagaraStackModuleData& OutModuleData, FString& OutError)
	{
		ENiagaraScriptUsage RequiredUsage = ENiagaraScriptUsage::Module;
		const bool bFilterByStage = !Stage.IsEmpty();
		if (bFilterByStage && !ParseStage(Stage, RequiredUsage))
		{
			OutError = FString::Printf(TEXT("Invalid stage '%s'. Use system_spawn|system_update|particle_spawn|particle_update|emitter_spawn|emitter_update."), *Stage);
			return false;
		}

		TArray<FMCPNiagaraStackModuleData> ModuleDataList;
		CollectStackModuleData(Graph, ModuleDataList);

		int32 MatchCount = 0;
		for (const FMCPNiagaraStackModuleData& ModuleData : ModuleDataList)
		{
			if (!ModuleData.Node)
			{
				continue;
			}
			if (bFilterByStage && ModuleData.Usage != RequiredUsage)
			{
				continue;
			}
			if (ModuleData.Node->GetFunctionName().Equals(ModuleName, ESearchCase::IgnoreCase))
			{
				OutModuleData = ModuleData;
				++MatchCount;
			}
		}

		if (MatchCount == 1)
		{
			return true;
		}
		if (MatchCount == 0)
		{
			OutError = bFilterByStage
				? FString::Printf(TEXT("No module named '%s' in stage '%s'."), *ModuleName, *Stage)
				: FString::Printf(TEXT("No module named '%s'."), *ModuleName);
			return false;
		}

		OutError = FString::Printf(TEXT("Found %d modules named '%s'; specify stage to disambiguate."), MatchCount, *ModuleName);
		return false;
	}

	UNiagaraNodeOutput* FindOutputNodeForModuleData(UNiagaraGraph* Graph, const FMCPNiagaraStackModuleData& ModuleData)
	{
		if (!Graph)
		{
			return nullptr;
		}
		for (UEdGraphNode* Node : Graph->Nodes)
		{
			UNiagaraNodeOutput* OutputNode = Cast<UNiagaraNodeOutput>(Node);
			if (OutputNode && OutputNode->GetUsage() == ModuleData.Usage && OutputNode->GetUsageId() == ModuleData.UsageId)
			{
				return OutputNode;
			}
		}
		return nullptr;
	}

	bool IsRemovableModuleOwnedNode(UEdGraphNode* Node, UNiagaraNodeFunctionCall& RootModule, const TSet<UNiagaraNodeFunctionCall*>& StackModuleSet)
	{
		if (!Node)
		{
			return false;
		}
		if (Node == &RootModule)
		{
			return true;
		}
		if (UNiagaraNodeFunctionCall* FunctionCallNode = Cast<UNiagaraNodeFunctionCall>(Node))
		{
			return !StackModuleSet.Contains(FunctionCallNode);
		}
		return Cast<UNiagaraNodeInput>(Node) || Cast<UNiagaraNodeOp>(Node) || Cast<UNiagaraNodeCustomHlsl>(Node);
	}

	void CollectModuleOwnedInputNodesForRemoval(
		UEdGraphNode* Node,
		UNiagaraNodeFunctionCall& RootModule,
		const TSet<UNiagaraNodeFunctionCall*>& StackModuleSet,
		TSet<UEdGraphNode*>& VisitedNodes,
		TArray<UNiagaraNode*>& OutNodesToRemove)
	{
		if (!Node || VisitedNodes.Contains(Node) || !IsRemovableModuleOwnedNode(Node, RootModule, StackModuleSet))
		{
			return;
		}

		VisitedNodes.Add(Node);
		if (UNiagaraNode* NiagaraNode = Cast<UNiagaraNode>(Node))
		{
			OutNodesToRemove.AddUnique(NiagaraNode);
		}

		for (UEdGraphPin* Pin : Node->Pins)
		{
			if (!Pin || Pin->Direction != EGPD_Input)
			{
				continue;
			}
			for (UEdGraphPin* LinkedPin : Pin->LinkedTo)
			{
				CollectModuleOwnedInputNodesForRemoval(
					LinkedPin ? LinkedPin->GetOwningNode() : nullptr,
					RootModule,
					StackModuleSet,
					VisitedNodes,
					OutNodesToRemove);
			}
		}
	}

	bool RemoveStackModuleNodeFromGraph(
		UNiagaraGraph& Graph,
		UNiagaraNodeOutput& OutputNode,
		UNiagaraNodeFunctionCall& ModuleNode,
		int32& OutRemovedNodeCount,
		int32& OutRemovedInputNodeCount,
		FString& OutError)
	{
		TArray<UNiagaraNodeFunctionCall*> OrderedModules;
		GetOrderedModuleNodesForOutput(&OutputNode, OrderedModules);
		const int32 ModuleIndex = OrderedModules.IndexOfByKey(&ModuleNode);
		if (ModuleIndex == INDEX_NONE)
		{
			OutError = TEXT("Module is not connected to the requested stack output.");
			return false;
		}

		UEdGraphPin* ModuleInputPin = GetParameterMapInputPin(&ModuleNode);
		UEdGraphPin* ModuleOutputPin = GetParameterMapOutputPin(&ModuleNode);
		UEdGraphPin* PreviousStackOutputPin = (ModuleInputPin && ModuleInputPin->LinkedTo.Num() == 1) ? ModuleInputPin->LinkedTo[0] : nullptr;
		UEdGraphNode* NextStackNode = OrderedModules.IsValidIndex(ModuleIndex + 1)
			? static_cast<UEdGraphNode*>(OrderedModules[ModuleIndex + 1])
			: static_cast<UEdGraphNode*>(&OutputNode);
		UEdGraphPin* NextStackInputPin = GetParameterMapInputPin(NextStackNode);
		if (!ModuleInputPin || !ModuleOutputPin || !PreviousStackOutputPin || !NextStackInputPin)
		{
			OutError = TEXT("Failed to resolve parameter-map pins needed to remove the module.");
			return false;
		}

		TSet<UNiagaraNodeFunctionCall*> StackModuleSet;
		for (UNiagaraNodeFunctionCall* OrderedModule : OrderedModules)
		{
			if (OrderedModule)
			{
				StackModuleSet.Add(OrderedModule);
			}
		}

		Graph.Modify();
		ModuleNode.Modify();
		ModuleInputPin->Modify();
		ModuleOutputPin->Modify();
		PreviousStackOutputPin->Modify();
		NextStackInputPin->Modify();

		ModuleInputPin->BreakAllPinLinks();
		ModuleOutputPin->BreakAllPinLinks();
		NextStackInputPin->BreakAllPinLinks();

		const UEdGraphSchema_Niagara* NiagaraSchema = GetDefault<UEdGraphSchema_Niagara>();
		if (!NiagaraSchema || !NiagaraSchema->TryCreateConnection(PreviousStackOutputPin, NextStackInputPin))
		{
			PreviousStackOutputPin->MakeLinkTo(NextStackInputPin);
		}

		TSet<UEdGraphNode*> VisitedNodes;
		TArray<UNiagaraNode*> NodesToRemove;
		CollectModuleOwnedInputNodesForRemoval(&ModuleNode, ModuleNode, StackModuleSet, VisitedNodes, NodesToRemove);

		for (UNiagaraNode* NodeToRemove : NodesToRemove)
		{
			if (!NodeToRemove || NodeToRemove == &OutputNode)
			{
				continue;
			}
			NodeToRemove->Modify();
			Graph.RemoveNode(NodeToRemove);
			++OutRemovedNodeCount;
			if (Cast<UNiagaraNodeInput>(NodeToRemove))
			{
				++OutRemovedInputNodeCount;
			}
		}

		return OutRemovedNodeCount > 0;
	}

	ENiagaraModuleDependencyUsage ConvertScriptUsageToDependencyUsage(ENiagaraScriptUsage ScriptUsage)
	{
		if (ScriptUsage == ENiagaraScriptUsage::ParticleEventScript)
		{
			return ENiagaraModuleDependencyUsage::Event;
		}
		if (ScriptUsage == ENiagaraScriptUsage::ParticleSimulationStageScript)
		{
			return ENiagaraModuleDependencyUsage::SimulationStage;
		}
		if (ScriptUsage == ENiagaraScriptUsage::EmitterSpawnScript || ScriptUsage == ENiagaraScriptUsage::SystemSpawnScript ||
			ScriptUsage == ENiagaraScriptUsage::ParticleSpawnScriptInterpolated || ScriptUsage == ENiagaraScriptUsage::ParticleSpawnScript)
		{
			return ENiagaraModuleDependencyUsage::Spawn;
		}
		if (ScriptUsage == ENiagaraScriptUsage::EmitterUpdateScript || ScriptUsage == ENiagaraScriptUsage::SystemUpdateScript ||
			ScriptUsage == ENiagaraScriptUsage::ParticleUpdateScript)
		{
			return ENiagaraModuleDependencyUsage::Update;
		}
		return ENiagaraModuleDependencyUsage::None;
	}

	bool IsDependencyUsageAllowed(ENiagaraScriptUsage Usage, int32 AllowedUsageBitmask)
	{
		const ENiagaraModuleDependencyUsage DependencyUsage = ConvertScriptUsageToDependencyUsage(Usage);
		return (AllowedUsageBitmask & (1 << static_cast<int32>(DependencyUsage))) != 0;
	}

	bool DoesModuleProvideDependency(const FMCPNiagaraStackModuleData& ProviderData, const FNiagaraModuleDependency& RequiredDependency, const FMCPNiagaraStackModuleData& SourceData)
	{
		UNiagaraNodeFunctionCall* ProviderNode = ProviderData.Node;
		if (!ProviderNode || !ProviderNode->FunctionScript)
		{
			return false;
		}
		FVersionedNiagaraScriptData* ProviderScriptData = ProviderNode->FunctionScript->GetScriptData(ProviderNode->SelectedScriptVersion);
		if (!ProviderScriptData || !ProviderScriptData->ProvidedDependencies.Contains(RequiredDependency.Id))
		{
			return false;
		}
		if (RequiredDependency.ScriptConstraint == ENiagaraModuleDependencyScriptConstraint::AllScripts)
		{
			return true;
		}
		return UNiagaraScript::IsEquivalentUsage(ProviderData.Usage, SourceData.Usage) && ProviderData.UsageId == SourceData.UsageId;
	}

	bool IsCorrectDependencyVersion(const FMCPNiagaraStackModuleData& ProviderData, const FNiagaraModuleDependency& RequiredDependency)
	{
		UNiagaraNodeFunctionCall* ProviderNode = ProviderData.Node;
		if (!ProviderNode || !ProviderNode->FunctionScript)
		{
			return false;
		}
		FVersionedNiagaraScriptData* ProviderScriptData = ProviderNode->FunctionScript->GetScriptData(ProviderNode->SelectedScriptVersion);
		return ProviderScriptData && RequiredDependency.IsVersionAllowed(ProviderScriptData->Version);
	}

	FString StackSeverityToString(const FString& Severity)
	{
		return Severity;
	}

	TSharedPtr<FJsonObject> MakeStackIssueJson(
		const FString& Severity,
		const FString& ShortDescription,
		const FString& LongDescription,
		const FString& EmitterName,
		const FMCPNiagaraStackModuleData& ModuleData,
		const FString& IssueId)
	{
		const FString Stage = UsageToDisplayString(ModuleData.Usage);
		const FString ModuleName = ModuleData.Node ? ModuleData.Node->GetFunctionName() : FString();
		TSharedPtr<FJsonObject> IssueObj = MakeShared<FJsonObject>();
		IssueObj->SetStringField(TEXT("severity"), StackSeverityToString(Severity));
		IssueObj->SetStringField(TEXT("short_description"), ShortDescription);
		IssueObj->SetStringField(TEXT("long_description"), LongDescription);
		IssueObj->SetStringField(TEXT("display_text"), FString::Printf(TEXT("%s - %s - %s - %s"), *Stage, *ModuleName, *Severity, *ShortDescription));
		IssueObj->SetStringField(TEXT("emitter_name"), EmitterName);
		IssueObj->SetStringField(TEXT("stage"), Stage);
		IssueObj->SetStringField(TEXT("script_usage"), UsageToString(ModuleData.Usage));
		IssueObj->SetStringField(TEXT("module_name"), ModuleName);
		IssueObj->SetStringField(TEXT("node_guid"), ModuleData.Node ? ModuleData.Node->NodeGuid.ToString(EGuidFormats::DigitsWithHyphens) : FString());
		IssueObj->SetStringField(TEXT("issue_id"), IssueId);
		return IssueObj;
	}

	void AppendStackIssuesForEmitter(
		const FString& EmitterName,
		UNiagaraGraph* Graph,
		TConstArrayView<FMCPNiagaraStackModuleData> SystemModuleData,
		TArray<TSharedPtr<FJsonValue>>& OutIssues,
		int32& OutErrorCount,
		int32& OutWarningCount)
	{
		TArray<FMCPNiagaraStackModuleData> ModuleDataList;
		CollectStackModuleData(Graph, ModuleDataList);
		TArray<FMCPNiagaraStackModuleData> ProviderDataList = ModuleDataList;
		ProviderDataList.Append(SystemModuleData.GetData(), SystemModuleData.Num());
		for (const FMCPNiagaraStackModuleData& ModuleData : ModuleDataList)
		{
			UNiagaraNodeFunctionCall* ModuleNode = ModuleData.Node;
			if (!ModuleNode)
			{
				continue;
			}

			FVersionedNiagaraScriptData* ScriptData = ModuleNode->GetScriptData();
			if (!ScriptData)
			{
				++OutErrorCount;
				OutIssues.Add(MakeShared<FJsonValueObject>(MakeStackIssueJson(
					TEXT("Error"), TEXT("Invalid module script."), TEXT("The script this module is supposed to execute is missing or invalid."),
					EmitterName, ModuleData, TEXT("invalid_module_script"))));
				continue;
			}

			if (ScriptData->bDeprecated)
			{
				FString LongDescription = FString::Printf(TEXT("The script asset for the assigned module %s has been deprecated."), *ModuleNode->GetFunctionName());
				if (!ScriptData->DeprecationMessage.IsEmptyOrWhitespace())
				{
					LongDescription += FString::Printf(TEXT(" Reason: %s"), *ScriptData->DeprecationMessage.ToString());
				}
				if (ScriptData->DeprecationRecommendation)
				{
					LongDescription += FString::Printf(TEXT(" Suggested replacement: %s"), *ScriptData->DeprecationRecommendation->GetPathName());
				}
				++OutWarningCount;
				OutIssues.Add(MakeShared<FJsonValueObject>(MakeStackIssueJson(
					TEXT("Warning"), TEXT("Deprecated module"), LongDescription, EmitterName, ModuleData, TEXT("deprecated_module"))));
			}

			for (const FNiagaraModuleDependency& RequiredDependency : ScriptData->RequiredDependencies)
			{
				if (!IsDependencyUsageAllowed(ModuleData.Usage, RequiredDependency.OnlyEvaluateInScriptUsage))
				{
					continue;
				}

				bool bDependencyMet = false;
				for (const FMCPNiagaraStackModuleData& ProviderData : ProviderDataList)
				{
					if (!DoesModuleProvideDependency(ProviderData, RequiredDependency, ModuleData))
					{
						continue;
					}

					const bool bCorrectOrder =
						RequiredDependency.ScriptConstraint == ENiagaraModuleDependencyScriptConstraint::AllScripts ||
						(RequiredDependency.Type == ENiagaraModuleDependencyType::PreDependency && ProviderData.Index < ModuleData.Index) ||
						(RequiredDependency.Type == ENiagaraModuleDependencyType::PostDependency && ProviderData.Index > ModuleData.Index);
					const bool bEnabled = ProviderData.Node && ProviderData.Node->GetDesiredEnabledState() == ENodeEnabledState::Enabled;
					if (bCorrectOrder && bEnabled && IsCorrectDependencyVersion(ProviderData, RequiredDependency))
					{
						bDependencyMet = true;
						break;
					}
				}

				if (!bDependencyMet)
				{
					const FString DependencyTypeString = RequiredDependency.Type == ENiagaraModuleDependencyType::PreDependency ? TEXT("pre-dependency") : TEXT("post-dependency");
					const FString LongDescription = FString::Printf(TEXT("The following %s is not met: %s; %s"),
						*DependencyTypeString, *RequiredDependency.Id.ToString(), *RequiredDependency.Description.ToString());
					++OutErrorCount;
					OutIssues.Add(MakeShared<FJsonValueObject>(MakeStackIssueJson(
						TEXT("Error"), TEXT("The module has unmet dependencies."), LongDescription, EmitterName, ModuleData,
						FString::Printf(TEXT("dependency-%s"), *RequiredDependency.Id.ToString()))));
				}
			}
		}
	}

	AActor* FindEditorActorByName(UWorld* World, const FString& ActorName)
	{
		if (!World || ActorName.IsEmpty())
		{
			return nullptr;
		}

		for (TActorIterator<AActor> It(World); It; ++It)
		{
			AActor* Actor = *It;
			if (!Actor)
			{
				continue;
			}
			if (Actor->GetName().Equals(ActorName, ESearchCase::IgnoreCase) ||
				Actor->GetActorLabel().Equals(ActorName, ESearchCase::IgnoreCase))
			{
				return Actor;
			}
		}

		return nullptr;
	}

	bool TryReadVector3Array(const TArray<TSharedPtr<FJsonValue>>& Array, FVector& OutVector)
	{
		if (Array.Num() < 3)
		{
			return false;
		}
		OutVector = FVector(Array[0]->AsNumber(), Array[1]->AsNumber(), Array[2]->AsNumber());
		return true;
	}

	FVector GetJsonVector3OrDefault(const TSharedPtr<FJsonObject>& Params, const FString& FieldName, const FVector& DefaultValue)
	{
		const TArray<TSharedPtr<FJsonValue>>* Array = nullptr;
		FVector Value = DefaultValue;
		if (Params.IsValid() && Params->TryGetArrayField(FieldName, Array) && Array)
		{
			TryReadVector3Array(*Array, Value);
		}
		return Value;
	}

	TArray<TSharedPtr<FJsonValue>> VectorToJsonArray(const FVector& Value)
	{
		return MakeNumberArrayJson({ Value.X, Value.Y, Value.Z });
	}

	FString WorldTypeToString(EWorldType::Type WorldType)
	{
		switch (WorldType)
		{
		case EWorldType::Editor:
			return TEXT("Editor");
		case EWorldType::PIE:
			return TEXT("PIE");
		case EWorldType::Game:
			return TEXT("Game");
		case EWorldType::GamePreview:
			return TEXT("GamePreview");
		case EWorldType::EditorPreview:
			return TEXT("EditorPreview");
		case EWorldType::Inactive:
			return TEXT("Inactive");
		default:
			return TEXT("Unknown");
		}
	}

	FString ExecutionStateToString(ENiagaraExecutionState State)
	{
		if (const UEnum* Enum = StaticEnum<ENiagaraExecutionState>())
		{
			return Enum->GetNameStringByValue(static_cast<int64>(State));
		}
		return FString::Printf(TEXT("%d"), static_cast<int32>(State));
	}

	TSharedPtr<FJsonObject> MakeBoxJson(const FBox& Box)
	{
		TSharedPtr<FJsonObject> Obj = MakeShared<FJsonObject>();
		Obj->SetBoolField(TEXT("valid"), Box.IsValid != 0);
		if (Box.IsValid)
		{
			Obj->SetArrayField(TEXT("min"), VectorToJsonArray(Box.Min));
			Obj->SetArrayField(TEXT("max"), VectorToJsonArray(Box.Max));
			Obj->SetArrayField(TEXT("center"), VectorToJsonArray(Box.GetCenter()));
			Obj->SetArrayField(TEXT("extent"), VectorToJsonArray(Box.GetExtent()));
		}
		return Obj;
	}

	TSharedPtr<FJsonObject> MakeBoundsJson(const FBoxSphereBounds& Bounds)
	{
		TSharedPtr<FJsonObject> Obj = MakeShared<FJsonObject>();
		Obj->SetArrayField(TEXT("origin"), VectorToJsonArray(Bounds.Origin));
		Obj->SetArrayField(TEXT("box_extent"), VectorToJsonArray(Bounds.BoxExtent));
		Obj->SetNumberField(TEXT("sphere_radius"), Bounds.SphereRadius);
		Obj->SetObjectField(TEXT("box"), MakeBoxJson(Bounds.GetBox()));
		return Obj;
	}

	TArray<TSharedPtr<FJsonValue>> MakeNiagaraVariableNameArrayJson(const TArray<FNiagaraVariableBase>& Variables)
	{
		TArray<TSharedPtr<FJsonValue>> Result;
		Result.Reserve(Variables.Num());
		for (const FNiagaraVariableBase& Variable : Variables)
		{
			Result.Add(MakeShared<FJsonValueString>(Variable.GetName().ToString()));
		}
		return Result;
	}

	int32 GetNiagaraDataBufferInstanceCount(const FNiagaraDataBuffer* Buffer)
	{
		return Buffer ? static_cast<int32>(Buffer->GetNumInstances()) : -1;
	}

	void AppendDataChannelDataCounts(TSharedPtr<FJsonObject> Obj, const TCHAR* Prefix, const FNiagaraDataChannelDataPtr& Data)
	{
		const FString PrefixString(Prefix);
		Obj->SetBoolField(PrefixString + TEXT("has_data"), Data.IsValid());
		if (!Data.IsValid())
		{
			Obj->SetNumberField(PrefixString + TEXT("game_instances"), -1);
			Obj->SetNumberField(PrefixString + TEXT("game_previous_instances"), -1);
			Obj->SetNumberField(PrefixString + TEXT("current_cpu_instances"), -1);
			Obj->SetNumberField(PrefixString + TEXT("previous_cpu_instances"), -1);
			return;
		}

		FNiagaraDataChannelGameData* GameData = Data->GetGameData();
		Obj->SetNumberField(PrefixString + TEXT("game_instances"), GameData ? GameData->Num() : -1);
		Obj->SetNumberField(PrefixString + TEXT("game_previous_instances"), GameData ? GameData->PrevNum() : -1);
		Obj->SetNumberField(PrefixString + TEXT("current_cpu_instances"), GetNiagaraDataBufferInstanceCount(Data->GetCPUData(false).GetReference()));
		Obj->SetNumberField(PrefixString + TEXT("previous_cpu_instances"), GetNiagaraDataBufferInstanceCount(Data->GetCPUData(true).GetReference()));
	}

	UNiagaraDataChannelHandler* FindDataChannelHandlerInWorld(UWorld* World, const UNiagaraDataChannel* Channel)
	{
		if (!World || !Channel)
		{
			return nullptr;
		}

		for (TObjectIterator<UNiagaraDataChannelHandler> It; It; ++It)
		{
			UNiagaraDataChannelHandler* Handler = *It;
			if (Handler && Handler->GetWorld() == World && Handler->GetDataChannel() == Channel)
			{
				return Handler;
			}
		}
		return nullptr;
	}
	TSharedPtr<FJsonObject> MakeDataChannelReadDIJson(
		FNiagaraSystemInstance& SystemInstance,
		const FNiagaraVariableBase& Variable,
		UNiagaraDataInterfaceDataChannelRead& ReaderDI)
	{
		TSharedPtr<FJsonObject> Obj = MakeShared<FJsonObject>();
		Obj->SetStringField(TEXT("variable_name"), Variable.GetName().ToString());
		Obj->SetStringField(TEXT("object_name"), ReaderDI.GetName());
		Obj->SetStringField(TEXT("object_path"), ReaderDI.GetPathName());
		Obj->SetStringField(TEXT("channel"), ReaderDI.Channel ? ReaderDI.Channel->GetPathName() : FString());
		Obj->SetBoolField(TEXT("auto_link_to_spawning_ndc"), ReaderDI.bAutoLinkToSpawningNDC);
		Obj->SetBoolField(TEXT("read_current_frame"), ReaderDI.bReadCurrentFrame);
		Obj->SetBoolField(TEXT("update_source_data_every_tick"), ReaderDI.bUpdateSourceDataEveryTick);
		Obj->SetBoolField(TEXT("override_spawn_group_to_ndc_index"), ReaderDI.bOverrideSpawnGroupToDataChannelIndex);
		Obj->SetBoolField(TEXT("only_spawn_once_on_subticks"), ReaderDI.bOnlySpawnOnceOnSubticks);

		FNDIDataChannelCompiledData& CompiledData = ReaderDI.GetCompiledData();
		Obj->SetBoolField(TEXT("compiled_used_by_cpu"), CompiledData.UsedByCPU());
		Obj->SetBoolField(TEXT("compiled_used_by_gpu"), CompiledData.UsedByGPU());
		Obj->SetBoolField(TEXT("compiled_spawns_particles"), CompiledData.SpawnsParticles());
		Obj->SetBoolField(TEXT("compiled_needs_spawn_data_table"), CompiledData.NeedSpawnDataTable());
		Obj->SetBoolField(TEXT("compiled_calls_write"), CompiledData.CallsWriteFunction());
		Obj->SetNumberField(TEXT("compiled_function_count"), CompiledData.GetFunctionInfo().Num());

		TArray<TSharedPtr<FJsonValue>> FunctionsJson;
		for (const FNDIDataChannelFunctionInfo& FunctionInfo : CompiledData.GetFunctionInfo())
		{
			TSharedPtr<FJsonObject> FunctionJson = MakeShared<FJsonObject>();
			FunctionJson->SetStringField(TEXT("name"), FunctionInfo.FunctionName.ToString());
			FunctionJson->SetArrayField(TEXT("inputs"), MakeNiagaraVariableNameArrayJson(FunctionInfo.Inputs));
			FunctionJson->SetArrayField(TEXT("outputs"), MakeNiagaraVariableNameArrayJson(FunctionInfo.Outputs));
			FunctionsJson.Add(MakeShared<FJsonValueObject>(FunctionJson));
		}
		Obj->SetArrayField(TEXT("compiled_functions"), FunctionsJson);

		FNDIDataChannelReadInstanceData* InstanceData = SystemInstance.FindTypedDataInterfaceInstanceData<FNDIDataChannelReadInstanceData>(&ReaderDI);
		Obj->SetBoolField(TEXT("has_instance_data"), InstanceData != nullptr);
		if (!InstanceData)
		{
			return Obj;
		}

		Obj->SetBoolField(TEXT("has_channel_handler"), InstanceData->DataChannel.IsValid());
		Obj->SetStringField(TEXT("channel_handler"), InstanceData->DataChannel.IsValid() ? InstanceData->DataChannel->GetPathName() : FString());
		Obj->SetBoolField(TEXT("has_data_channel_data"), InstanceData->DataChannelData.IsValid());
		Obj->SetBoolField(TEXT("update_function_binding_rt_data"), InstanceData->bUpdateFunctionBindingRTData);
		Obj->SetNumberField(TEXT("function_binding_count"), InstanceData->FuncToDataSetBindingInfo.Num());
		Obj->SetNumberField(TEXT("consume_index"), static_cast<int32>(InstanceData->ConsumeIndex.load()));
		Obj->SetNumberField(TEXT("ndc_element_count_at_spawn"), InstanceData->NDCElementCountAtSpawn);

		FNiagaraDataBuffer* CurrentBuffer = nullptr;
		FNiagaraDataBuffer* PreviousBuffer = nullptr;
		if (InstanceData->DataChannelData.IsValid())
		{
			CurrentBuffer = InstanceData->DataChannelData->GetCPUData(false);
			PreviousBuffer = InstanceData->DataChannelData->GetCPUData(true);
		}
		Obj->SetNumberField(TEXT("current_cpu_instances"), GetNiagaraDataBufferInstanceCount(CurrentBuffer));
		Obj->SetNumberField(TEXT("previous_cpu_instances"), GetNiagaraDataBufferInstanceCount(PreviousBuffer));
		AppendDataChannelDataCounts(Obj, TEXT("reader_"), InstanceData->DataChannelData);

		TArray<TSharedPtr<FJsonValue>> EmitterDataJson;
		for (const TPair<FNiagaraEmitterInstance*, FNDIDataChannelRead_EmitterInstanceData>& EmitterPair : InstanceData->EmitterInstanceData)
		{
			const FNiagaraEmitterInstance* EmitterInstance = EmitterPair.Key;
			const FNDIDataChannelRead_EmitterInstanceData& EmitterData = EmitterPair.Value;

			TSharedPtr<FJsonObject> EmitterJson = MakeShared<FJsonObject>();
			EmitterJson->SetStringField(TEXT("name"), EmitterInstance ? EmitterInstance->GetEmitterHandle().GetName().ToString() : FString());
			EmitterJson->SetNumberField(TEXT("emitter_id"), EmitterInstance ? EmitterInstance->GetEmitterID().ID : INDEX_NONE);
			EmitterJson->SetNumberField(TEXT("spawn_count_entry_count"), EmitterData.NDCSpawnCounts.Num());

			uint64 TotalSpawnCount = 0;
			TArray<TSharedPtr<FJsonValue>> SpawnCountsJson;
			for (const FNDIDataChannelRead_EmitterSpawnInfo& SpawnInfo : EmitterData.NDCSpawnCounts)
			{
				const uint32 Count = SpawnInfo.Get();
				TotalSpawnCount += Count;
				SpawnCountsJson.Add(MakeShared<FJsonValueNumber>(static_cast<double>(Count)));
			}
			EmitterJson->SetNumberField(TEXT("spawn_count_total"), static_cast<double>(TotalSpawnCount));
			EmitterJson->SetArrayField(TEXT("spawn_counts"), SpawnCountsJson);
			EmitterJson->SetNumberField(TEXT("spawn_data_count"), EmitterData.NDCSpawnData.NDCSpawnData.Num());

			TArray<TSharedPtr<FJsonValue>> SpawnDataBucketsJson;
			for (int32 BucketIndex = 0; BucketIndex < UE_ARRAY_COUNT(EmitterData.NDCSpawnData.NDCSpawnDataBuckets); ++BucketIndex)
			{
				SpawnDataBucketsJson.Add(MakeShared<FJsonValueNumber>(EmitterData.NDCSpawnData.NDCSpawnDataBuckets[BucketIndex]));
			}
			EmitterJson->SetArrayField(TEXT("spawn_data_buckets"), SpawnDataBucketsJson);
			EmitterDataJson.Add(MakeShared<FJsonValueObject>(EmitterJson));
		}
		Obj->SetNumberField(TEXT("emitter_instance_data_count"), InstanceData->EmitterInstanceData.Num());
		Obj->SetArrayField(TEXT("emitter_instance_data"), EmitterDataJson);
		return Obj;
	}

	TSharedPtr<FJsonObject> MakeNiagaraComponentDebugJson(UNiagaraComponent* Component)
	{
		TSharedPtr<FJsonObject> Result = MakeShared<FJsonObject>();
		if (!Component)
		{
			return Result;
		}

		UWorld* ComponentWorld = Component->GetWorld();
		AActor* OwnerActor = Component->GetOwner();
		Result->SetStringField(TEXT("component_name"), Component->GetName());
		Result->SetStringField(TEXT("component_path"), Component->GetPathName());
		Result->SetStringField(TEXT("component_class"), Component->GetClass() ? Component->GetClass()->GetName() : FString());
		Result->SetStringField(TEXT("owner_name"), OwnerActor ? OwnerActor->GetName() : FString());
		Result->SetStringField(TEXT("owner_label"), OwnerActor ? OwnerActor->GetActorLabel() : FString());
		Result->SetStringField(TEXT("owner_class"), OwnerActor && OwnerActor->GetClass() ? OwnerActor->GetClass()->GetName() : FString());
		Result->SetStringField(TEXT("world_name"), ComponentWorld ? ComponentWorld->GetName() : FString());
		Result->SetStringField(TEXT("world_type"), ComponentWorld ? WorldTypeToString(ComponentWorld->WorldType) : FString());
		Result->SetArrayField(TEXT("component_location"), VectorToJsonArray(Component->GetComponentLocation()));
		Result->SetBoolField(TEXT("component_active"), Component->IsActive());
		Result->SetBoolField(TEXT("component_registered"), Component->IsRegistered());
		Result->SetBoolField(TEXT("component_world_ready_to_run"), Component->IsWorldReadyToRun());
		Result->SetBoolField(TEXT("component_complete"), Component->IsComplete());
		Result->SetStringField(TEXT("component_requested_execution_state"), ExecutionStateToString(Component->GetRequestedExecutionState()));
		Result->SetObjectField(TEXT("component_world_bounds"), MakeBoundsJson(Component->Bounds));
		Result->SetStringField(TEXT("asset_path"), Component->GetAsset() ? Component->GetAsset()->GetPathName() : FString());

		TArray<TSharedPtr<FJsonValue>> ComponentTags;
		for (const FName& Tag : Component->ComponentTags)
		{
			ComponentTags.Add(MakeShared<FJsonValueString>(Tag.ToString()));
		}
		Result->SetArrayField(TEXT("component_tags"), ComponentTags);

		FNiagaraSystemInstanceControllerPtr Controller = Component->GetSystemInstanceController();
		Result->SetBoolField(TEXT("has_system_instance_controller"), Controller.IsValid());
		TArray<TSharedPtr<FJsonValue>> EmittersJson;
		int32 TotalParticles = 0;
		if (Controller.IsValid() && Controller->IsValid())
		{
			Result->SetStringField(TEXT("system_requested_execution_state"), ExecutionStateToString(Controller->GetRequestedExecutionState()));
			Result->SetStringField(TEXT("system_actual_execution_state"), ExecutionStateToString(Controller->GetActualExecutionState()));
			Result->SetBoolField(TEXT("system_complete"), Controller->IsComplete());
			Result->SetBoolField(TEXT("system_paused"), Controller->IsPaused());
			Result->SetObjectField(TEXT("system_local_bounds"), MakeBoxJson(Controller->GetLocalBounds()));

			FNiagaraSystemInstance* SystemInstance = Controller->GetSystemInstance_Unsafe();
			if (SystemInstance)
			{
				Result->SetNumberField(TEXT("system_age"), SystemInstance->GetAge());
				Result->SetNumberField(TEXT("system_tick_count"), SystemInstance->GetTickCount());
				if (TSharedPtr<FNiagaraSystemSimulation, ESPMode::ThreadSafe> SystemSimulation = SystemInstance->GetSystemSimulation())
				{
					const FNiagaraTickInfo& TickInfo = SystemSimulation->GetTickInfo();
					Result->SetNumberField(TEXT("system_tick_info_tick_number"), TickInfo.TickNumber);
					Result->SetNumberField(TEXT("system_tick_info_tick_count"), TickInfo.TickCount);
					Result->SetNumberField(TEXT("system_tick_info_time_step_fraction"), TickInfo.TimeStepFraction);
					Result->SetNumberField(TEXT("system_tick_info_engine_tick"), TickInfo.EngineTick);
				}

				TArray<TSharedPtr<FJsonValue>> DataChannelReadersJson;
				TSet<const UNiagaraDataInterface*> VisitedReaderDIs;
				FNiagaraDataInterfaceUtilities::ForEachDataInterface(SystemInstance, [&](const FNiagaraVariableBase Variable, UNiagaraDataInterface* DataInterface) -> bool
				{
					UNiagaraDataInterfaceDataChannelRead* ReaderDI = Cast<UNiagaraDataInterfaceDataChannelRead>(DataInterface);
					if (ReaderDI && !VisitedReaderDIs.Contains(ReaderDI))
					{
						VisitedReaderDIs.Add(ReaderDI);
						DataChannelReadersJson.Add(MakeShared<FJsonValueObject>(MakeDataChannelReadDIJson(*SystemInstance, Variable, *ReaderDI)));
					}
					return true;
				});
				Result->SetNumberField(TEXT("data_channel_reader_count"), DataChannelReadersJson.Num());
				Result->SetArrayField(TEXT("data_channel_readers"), DataChannelReadersJson);

				for (const FNiagaraEmitterInstanceRef& EmitterRef : SystemInstance->GetEmitters())
				{
					const FNiagaraEmitterInstance& Emitter = EmitterRef.Get();
					const int32 NumParticles = Emitter.GetNumParticles();
					TotalParticles += NumParticles;

					TSharedPtr<FJsonObject> EmitterJson = MakeShared<FJsonObject>();
					EmitterJson->SetStringField(TEXT("name"), Emitter.GetEmitterHandle().GetName().ToString());
					EmitterJson->SetNumberField(TEXT("emitter_id"), Emitter.GetEmitterID().ID);
					EmitterJson->SetBoolField(TEXT("handle_enabled"), Emitter.GetEmitterHandle().GetIsEnabled());
					EmitterJson->SetStringField(TEXT("execution_state"), ExecutionStateToString(Emitter.GetExecutionState()));
					EmitterJson->SetBoolField(TEXT("active"), Emitter.IsActive());
					EmitterJson->SetBoolField(TEXT("complete"), Emitter.IsComplete());
					EmitterJson->SetStringField(TEXT("sim_target"), Emitter.GetSimTarget() == ENiagaraSimTarget::CPUSim ? TEXT("CPUSim") : TEXT("GPUComputeSim"));
					EmitterJson->SetNumberField(TEXT("num_particles"), NumParticles);
					EmitterJson->SetNumberField(TEXT("total_spawned_particles"), Emitter.GetTotalSpawnedParticles());
					EmitterJson->SetObjectField(TEXT("bounds"), MakeBoxJson(Emitter.GetBounds()));

					const FNiagaraDataSet& ParticleData = Emitter.GetParticleData();
					const FNiagaraDataBuffer* CurrentData = ParticleData.GetCurrentData();
					EmitterJson->SetNumberField(TEXT("current_data_instances"), CurrentData ? CurrentData->GetNumInstances() : -1);
					EmittersJson.Add(MakeShared<FJsonValueObject>(EmitterJson));
				}
			}
		}
		Result->SetNumberField(TEXT("total_particles"), TotalParticles);
		Result->SetArrayField(TEXT("emitters"), EmittersJson);
		return Result;
	}

	UWorld* ResolveRuntimeOrEditorWorld()
	{
		if (!GEditor)
		{
			return nullptr;
		}
		return GEditor->PlayWorld ? GEditor->PlayWorld.Get() : GEditor->GetEditorWorldContext().World();
	}
}

// =========================================================================
// FNiagaraAction
// =========================================================================

UNiagaraScript* FNiagaraAction::LoadNiagaraScriptByPath(const FString& AssetPath, FString& OutError) const
{
	const FString ObjectPath = NormalizeAssetObjectPath(AssetPath);
	UNiagaraScript* Script = LoadObject<UNiagaraScript>(nullptr, *ObjectPath);
	if (!Script)
	{
		OutError = FString::Printf(TEXT("Failed to load UNiagaraScript at '%s'"), *AssetPath);
	}
	return Script;
}

UNiagaraSystem* FNiagaraAction::LoadNiagaraSystemByPath(const FString& AssetPath, FString& OutError) const
{
	const FString ObjectPath = NormalizeAssetObjectPath(AssetPath);
	UNiagaraSystem* System = LoadObject<UNiagaraSystem>(nullptr, *ObjectPath);
	if (!System)
	{
		OutError = FString::Printf(TEXT("Failed to load UNiagaraSystem at '%s'"), *AssetPath);
	}
	return System;
}

UNiagaraEmitter* FNiagaraAction::LoadNiagaraEmitterByPath(const FString& AssetPath, FString& OutError) const
{
	const FString ObjectPath = NormalizeAssetObjectPath(AssetPath);
	UNiagaraEmitter* Emitter = LoadObject<UNiagaraEmitter>(nullptr, *ObjectPath);
	if (!Emitter)
	{
		OutError = FString::Printf(TEXT("Failed to load UNiagaraEmitter at '%s'"), *AssetPath);
	}
	return Emitter;
}

// =========================================================================
// FNiagaraFindScriptsAction
// =========================================================================

bool FNiagaraFindScriptsAction::Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError)
{
	// All parameters are optional; validate usage string up-front if provided.
	const FString UsageStr = GetOptionalString(Params, TEXT("usage"), TEXT(""));
	if (!UsageStr.IsEmpty())
	{
		ENiagaraScriptUsage Dummy;
		if (!ParseUsage(UsageStr, Dummy))
		{
			OutError = FString::Printf(TEXT("Invalid usage '%s'. Use names like Module, DynamicInput, Function, ParticleUpdateScript, etc."), *UsageStr);
			return false;
		}
	}
	return true;
}

TSharedPtr<FJsonObject> FNiagaraFindScriptsAction::ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context)
{
	const FString SearchPath = GetOptionalString(Params, TEXT("path"), TEXT("/Game"));
	const FString NameFilter = GetOptionalString(Params, TEXT("name_filter"), TEXT(""));
	const FString VisibilityFilter = GetOptionalString(Params, TEXT("visibility"), TEXT(""));
	const FString UsageStr = GetOptionalString(Params, TEXT("usage"), TEXT(""));
	const bool bIncludeDeprecated = GetOptionalBool(Params, TEXT("include_deprecated"), false);

	int32 MaxResults = static_cast<int32>(GetOptionalNumber(Params, TEXT("max_results"), 100.0));
	MaxResults = FMath::Clamp(MaxResults, 1, 500);

	ENiagaraScriptUsage RequiredUsage = ENiagaraScriptUsage::Module;
	const bool bFilterByUsage = !UsageStr.IsEmpty() && ParseUsage(UsageStr, RequiredUsage);

	FAssetRegistryModule& AssetRegistryModule = FModuleManager::LoadModuleChecked<FAssetRegistryModule>(TEXT("AssetRegistry"));
	IAssetRegistry& AssetRegistry = AssetRegistryModule.Get();

	FARFilter Filter;
	Filter.ClassPaths.Add(UNiagaraScript::StaticClass()->GetClassPathName());
	Filter.bRecursiveClasses = true;
	Filter.PackagePaths.Add(FName(*SearchPath));
	Filter.bRecursivePaths = true;

	TArray<FAssetData> AssetList;
	AssetRegistry.GetAssets(Filter, AssetList);

	TArray<TSharedPtr<FJsonValue>> ResultArray;
	int32 Scanned = 0;

	for (const FAssetData& AssetData : AssetList)
	{
		if (ResultArray.Num() >= MaxResults)
		{
			break;
		}
		++Scanned;

		// Name substring filter (case-insensitive)
		if (!NameFilter.IsEmpty() && !AssetData.AssetName.ToString().Contains(NameFilter, ESearchCase::IgnoreCase))
		{
			continue;
		}

		// Deprecated filter
		if (!bIncludeDeprecated && GetTagBool(AssetData, TAG_Deprecated))
		{
			continue;
		}

		// Visibility filter (tag value is the short enum name, e.g. "Library")
		if (!VisibilityFilter.IsEmpty())
		{
			const FString Visibility = GetTagString(AssetData, TAG_LibraryVisibility);
			if (!Visibility.Equals(VisibilityFilter, ESearchCase::IgnoreCase))
			{
				continue;
			}
		}

		TSharedPtr<FJsonObject> Digest = MakeScriptDigest(AssetData);

		// Usage filter / resolution requires loading the asset (5.7 has no usage registry tag).
		if (bFilterByUsage)
		{
			FString LoadError;
			UNiagaraScript* Script = LoadNiagaraScriptByPath(AssetData.GetObjectPathString(), LoadError);
			if (!Script || Script->GetUsage() != RequiredUsage)
			{
				continue;
			}
			Digest->SetStringField(TEXT("usage"), UsageToString(Script->GetUsage()));
		}

		ResultArray.Add(MakeShared<FJsonValueObject>(Digest));
	}

	TSharedPtr<FJsonObject> Result = MakeShared<FJsonObject>();
	Result->SetNumberField(TEXT("count"), ResultArray.Num());
	Result->SetNumberField(TEXT("scanned"), Scanned);
	Result->SetBoolField(TEXT("truncated"), ResultArray.Num() >= MaxResults);
	Result->SetArrayField(TEXT("scripts"), ResultArray);
	if (bFilterByUsage)
	{
		Result->SetStringField(TEXT("usage_filter"), UsageToString(RequiredUsage));
	}
	return CreateSuccessResponse(Result);
}

// =========================================================================
// FNiagaraGetScriptDigestAction
// =========================================================================

bool FNiagaraGetScriptDigestAction::Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError)
{
	FString AssetPath;
	return GetRequiredString(Params, TEXT("asset_path"), AssetPath, OutError);
}

TSharedPtr<FJsonObject> FNiagaraGetScriptDigestAction::ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context)
{
	FString Error;
	FString AssetPath;
	GetRequiredString(Params, TEXT("asset_path"), AssetPath, Error);

	// Resolve registry tags first (cheap), then load to get usage.
	FAssetRegistryModule& AssetRegistryModule = FModuleManager::LoadModuleChecked<FAssetRegistryModule>(TEXT("AssetRegistry"));
	IAssetRegistry& AssetRegistry = AssetRegistryModule.Get();

	const FString ObjectPath = NormalizeAssetObjectPath(AssetPath);
	const FAssetData AssetData = AssetRegistry.GetAssetByObjectPath(FSoftObjectPath(ObjectPath));
	if (!AssetData.IsValid())
	{
		return CreateErrorResponse(
			FString::Printf(TEXT("No Niagara script found at '%s'"), *AssetPath),
			TEXT("asset_not_found"));
	}

	TSharedPtr<FJsonObject> Digest = MakeScriptDigest(AssetData);

	FString LoadError;
	if (UNiagaraScript* Script = LoadNiagaraScriptByPath(AssetPath, LoadError))
	{
		Digest->SetStringField(TEXT("usage"), UsageToString(Script->GetUsage()));
	}
	else
	{
		// Tag data is still valid even if the asset could not be loaded; report usage as unknown.
		Digest->SetStringField(TEXT("usage"), TEXT("Unknown"));
		Digest->SetStringField(TEXT("usage_load_warning"), LoadError);
	}

	return CreateSuccessResponse(Digest);
}

// =========================================================================
// FNiagaraGetSystemSummaryAction
// =========================================================================

bool FNiagaraGetSystemSummaryAction::Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError)
{
	FString AssetPath;
	return GetRequiredString(Params, TEXT("asset_path"), AssetPath, OutError);
}

TSharedPtr<FJsonObject> FNiagaraGetSystemSummaryAction::ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context)
{
	FString Error;
	FString AssetPath;
	GetRequiredString(Params, TEXT("asset_path"), AssetPath, Error);

	FString LoadError;
	UNiagaraSystem* System = LoadNiagaraSystemByPath(AssetPath, LoadError);
	if (!System)
	{
		return CreateErrorResponse(LoadError, TEXT("asset_not_found"));
	}

	TSharedPtr<FJsonObject> Result = MakeShared<FJsonObject>();
	Result->SetStringField(TEXT("name"), System->GetName());
	Result->SetStringField(TEXT("path"), System->GetPathName());

	// Exposed (User.) parameters
	TArray<TSharedPtr<FJsonValue>> UserParamArray;
	{
		TArray<FNiagaraVariable> UserParams;
		const FNiagaraUserRedirectionParameterStore& UserParameterStore = System->GetExposedParameters();
		UserParameterStore.GetUserParameters(UserParams);
		for (const FNiagaraVariable& Var : UserParams)
		{
			TSharedPtr<FJsonObject> VarObj = MakeShared<FJsonObject>();
			VarObj->SetStringField(TEXT("name"), Var.GetName().ToString());
			VarObj->SetStringField(TEXT("qualified_name"), MakeNiagaraUserParameterName(Var.GetName().ToString()));
			VarObj->SetStringField(TEXT("type"), Var.GetType().GetName());

			if (Var.GetType() == FNiagaraTypeDefinition::GetPositionDef())
			{
				if (const FVector* PositionValue = UserParameterStore.GetPositionParameterValue(Var.GetName()))
				{
					VarObj->SetArrayField(TEXT("default_value"), VectorToJsonArray(*PositionValue));
					VarObj->SetStringField(TEXT("default_value_text"), PositionValue->ToString());
				}
			}
			else if (const uint8* ParameterData = UserParameterStore.GetParameterData(Var))
			{
				FNiagaraVariable ValueVariable(Var.GetType(), Var.GetName());
				ValueVariable.SetData(ParameterData);

				TSharedPtr<FJsonValue> JsonValue;
				FString ValueText;
				if (NiagaraVariableValueToJson(ValueVariable, JsonValue, ValueText) && JsonValue.IsValid())
				{
					VarObj->SetField(TEXT("default_value"), JsonValue);
					VarObj->SetStringField(TEXT("default_value_text"), ValueText);
				}
				else
				{
					VarObj->SetStringField(TEXT("default_value_text"), Var.GetType().ToString(ValueVariable.GetData()));
				}
			}
			UserParamArray.Add(MakeShared<FJsonValueObject>(VarObj));
		}
	}
	Result->SetArrayField(TEXT("user_parameters"), UserParamArray);

	// Per-emitter summary
	TArray<TSharedPtr<FJsonValue>> EmitterArray;
	const UEnum* EmitterModeEnum = StaticEnum<ENiagaraEmitterMode>();
	for (const FNiagaraEmitterHandle& Handle : System->GetEmitterHandles())
	{
		TSharedPtr<FJsonObject> EmitterObj = MakeShared<FJsonObject>();
		EmitterObj->SetStringField(TEXT("name"), Handle.GetName().ToString());
		EmitterObj->SetBoolField(TEXT("enabled"), Handle.GetIsEnabled());
		if (EmitterModeEnum)
		{
			EmitterObj->SetStringField(TEXT("mode"), EmitterModeEnum->GetNameStringByValue(static_cast<int64>(Handle.GetEmitterMode())));
		}
		EmitterArray.Add(MakeShared<FJsonValueObject>(EmitterObj));
	}
	Result->SetArrayField(TEXT("emitters"), EmitterArray);
	Result->SetNumberField(TEXT("emitter_count"), EmitterArray.Num());

	return CreateSuccessResponse(Result);
}

// =========================================================================
// FNiagaraSetUserParameterAction
// =========================================================================

bool FNiagaraSetUserParameterAction::Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError)
{
	FString SystemPath;
	if (!GetRequiredString(Params, TEXT("system_path"), SystemPath, OutError))
	{
		return false;
	}
	FString ParameterName;
	if (!GetRequiredString(Params, TEXT("parameter_name"), ParameterName, OutError))
	{
		return false;
	}
	FString ValueType;
	if (!GetRequiredString(Params, TEXT("value_type"), ValueType, OutError))
	{
		return false;
	}
	if (!Params.IsValid() || !Params->HasField(TEXT("value")))
	{
		OutError = TEXT("Missing required 'value'.");
		return false;
	}
	FNiagaraTypeDefinition DummyType;
	if (!ParseNiagaraValueType(ValueType, DummyType))
	{
		OutError = FString::Printf(TEXT("Invalid value_type '%s'. Use float|int|bool|vec2|vec3|position|vec4|quat|color."), *ValueType);
		return false;
	}
	return true;
}

TSharedPtr<FJsonObject> FNiagaraSetUserParameterAction::ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context)
{
	FString Error;
	FString SystemPath;
	FString ParameterName;
	FString ValueType;
	GetRequiredString(Params, TEXT("system_path"), SystemPath, Error);
	GetRequiredString(Params, TEXT("parameter_name"), ParameterName, Error);
	GetRequiredString(Params, TEXT("value_type"), ValueType, Error);

	FNiagaraVariable ValueVariable;
	FVector PositionValue = FVector::ZeroVector;
	bool bIsPosition = false;
	if (!TryBuildNiagaraValueVariable(Params, ParameterName, ValueType, ValueVariable, PositionValue, bIsPosition, Error))
	{
		return CreateErrorResponse(Error, TEXT("invalid_value"));
	}

	FString LoadError;
	UNiagaraSystem* System = LoadNiagaraSystemByPath(SystemPath, LoadError);
	if (!System)
	{
		return CreateErrorResponse(LoadError, TEXT("system_not_found"));
	}

	FNiagaraUserRedirectionParameterStore& UserParameterStore = System->GetExposedParameters();
	FNiagaraVariable ExistingParameter(ValueVariable.GetType(), ValueVariable.GetName());
	FNiagaraUserRedirectionParameterStore::MakeUserVariable(ExistingParameter);
	const FString QualifiedParameterName = ExistingParameter.GetName().ToString();
	bool bExisted = false;
	bool bRemovedTypeMismatch = false;

	System->Modify();

	TArray<FNiagaraVariable> CurrentParameters;
	UserParameterStore.GetUserParameters(CurrentParameters);
	for (const FNiagaraVariable& CurrentParameter : CurrentParameters)
	{
		const FString CurrentQualifiedName = MakeNiagaraUserParameterName(CurrentParameter.GetName().ToString());
		if (!CurrentQualifiedName.Equals(QualifiedParameterName, ESearchCase::CaseSensitive))
		{
			continue;
		}

		bExisted = true;
		if (CurrentParameter.GetType() != ExistingParameter.GetType())
		{
			UserParameterStore.RemoveParameter(CurrentParameter);
			bRemovedTypeMismatch = true;
		}
		break;
	}

	UserParameterStore.AddParameter(ExistingParameter, true, false);

	bool bSetValue = false;
	if (bIsPosition)
	{
		bSetValue = UserParameterStore.SetPositionParameterValue(PositionValue, ExistingParameter.GetName(), false);
	}
	else
	{
		bSetValue = UserParameterStore.SetParameterData(ValueVariable.GetData(), ExistingParameter, false);
	}

	if (!bSetValue)
	{
		return CreateErrorResponse(
			FString::Printf(TEXT("Failed to set Niagara user parameter '%s'."), *QualifiedParameterName),
			TEXT("set_parameter_failed"));
	}

	MarkNiagaraSystemEdited(*System, Context);

	TSharedPtr<FJsonObject> Result = MakeShared<FJsonObject>();
	Result->SetStringField(TEXT("system_path"), System->GetPathName());
	Result->SetStringField(TEXT("parameter_name"), ParameterName);
	Result->SetStringField(TEXT("qualified_name"), ExistingParameter.GetName().ToString());
	Result->SetStringField(TEXT("value_type"), NiagaraTypeToString(ExistingParameter.GetType()));
	Result->SetBoolField(TEXT("existed_before"), bExisted);
	Result->SetBoolField(TEXT("created"), !bExisted);
	Result->SetBoolField(TEXT("removed_type_mismatch"), bRemovedTypeMismatch);

	if (bIsPosition)
	{
		Result->SetArrayField(TEXT("value"), VectorToJsonArray(PositionValue));
		Result->SetStringField(TEXT("value_text"), PositionValue.ToString());
	}
	else
	{
		TSharedPtr<FJsonValue> JsonValue;
		FString ValueText;
		if (NiagaraVariableValueToJson(ValueVariable, JsonValue, ValueText) && JsonValue.IsValid())
		{
			Result->SetField(TEXT("value"), JsonValue);
			Result->SetStringField(TEXT("value_text"), ValueText);
		}
	}

	return CreateSuccessResponse(Result);
}

// =========================================================================
// FNiagaraGetCompileDiagnosticsAction
// =========================================================================

bool FNiagaraGetCompileDiagnosticsAction::Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError)
{
	FString AssetPath;
	if (!GetRequiredString(Params, TEXT("asset_path"), AssetPath, OutError))
	{
		return false;
	}

	const FString MinSeverity = GetOptionalString(Params, TEXT("min_severity"), TEXT("warning"));
	FNiagaraCompileEventSeverity ParsedSeverity;
	if (!ParseCompileMinSeverity(MinSeverity, ParsedSeverity))
	{
		OutError = FString::Printf(TEXT("Invalid min_severity '%s'. Use log, display, warning, or error."), *MinSeverity);
		return false;
	}
	return true;
}

TSharedPtr<FJsonObject> FNiagaraGetCompileDiagnosticsAction::ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context)
{
	FString Error;
	FString AssetPath;
	GetRequiredString(Params, TEXT("asset_path"), AssetPath, Error);

	FString LoadError;
	UNiagaraSystem* System = LoadNiagaraSystemByPath(AssetPath, LoadError);
	if (!System)
	{
		return CreateErrorResponse(LoadError, TEXT("asset_not_found"));
	}

	const bool bRefreshCompile = GetOptionalBool(Params, TEXT("refresh_compile"), false);
	const bool bWait = GetOptionalBool(Params, TEXT("wait"), true);
	const FString MinSeverityString = GetOptionalString(Params, TEXT("min_severity"), TEXT("warning"));
	FNiagaraCompileEventSeverity MinSeverity = FNiagaraCompileEventSeverity::Warning;
	ParseCompileMinSeverity(MinSeverityString, MinSeverity);

	bool bRequestedCompile = false;
	if (bRefreshCompile)
	{
		bRequestedCompile = System->RequestCompile(true);
	}

	if (bWait && (bRequestedCompile || System->HasOutstandingCompilationRequests(true)))
	{
		System->WaitForCompilationComplete(true, false);
	}
	else
	{
		System->PollForCompilationComplete(true);
	}

	TArray<TSharedPtr<FJsonValue>> ScriptArray;
	TArray<TSharedPtr<FJsonValue>> FlatEvents;
	TArray<TSharedPtr<FJsonValue>> StackIssues;
	int32 ErrorCount = 0;
	int32 WarningCount = 0;
	int32 StackIssueErrorCount = 0;
	int32 StackIssueWarningCount = 0;

	TArray<FMCPNiagaraStackModuleData> SystemModuleData;
	UNiagaraScript* SystemSpawnScript = System->GetSystemSpawnScript();
	UNiagaraGraph* SystemSpawnGraph = GetScriptGraph(SystemSpawnScript);
	CollectStackModuleData(SystemSpawnGraph, SystemModuleData);
	ScriptArray.Add(MakeShared<FJsonValueObject>(MakeScriptDiagnosticsJson(
		SystemSpawnScript, SystemSpawnGraph, TEXT("system"), FString(), MinSeverity, FlatEvents, ErrorCount, WarningCount)));

	UNiagaraScript* SystemUpdateScript = System->GetSystemUpdateScript();
	UNiagaraGraph* SystemUpdateGraph = GetScriptGraph(SystemUpdateScript);
	CollectStackModuleData(SystemUpdateGraph, SystemModuleData);
	ScriptArray.Add(MakeShared<FJsonValueObject>(MakeScriptDiagnosticsJson(
		SystemUpdateScript, SystemUpdateGraph, TEXT("system"), FString(), MinSeverity, FlatEvents, ErrorCount, WarningCount)));

	for (const FNiagaraEmitterHandle& Handle : System->GetEmitterHandles())
	{
		FVersionedNiagaraEmitterData* EmitterData = Handle.GetEmitterData();
		if (!EmitterData)
		{
			continue;
		}

		TArray<UNiagaraScript*> EmitterScripts;
		EmitterData->GetScripts(EmitterScripts, false);
		UNiagaraGraph* EmitterGraph = GetEmitterGraph(*EmitterData);
		const FString EmitterName = Handle.GetName().ToString();
		AppendStackIssuesForEmitter(EmitterName, EmitterGraph, SystemModuleData, StackIssues, StackIssueErrorCount, StackIssueWarningCount);
		for (UNiagaraScript* Script : EmitterScripts)
		{
			ScriptArray.Add(MakeShared<FJsonValueObject>(MakeScriptDiagnosticsJson(
				Script, EmitterGraph, TEXT("emitter"), EmitterName, MinSeverity, FlatEvents, ErrorCount, WarningCount)));
		}
	}

	const int32 TotalErrorCount = ErrorCount + StackIssueErrorCount;
	const int32 TotalWarningCount = WarningCount + StackIssueWarningCount;
	FString AggregateStatus = TEXT("UpToDate");
	if (TotalErrorCount > 0)
	{
		AggregateStatus = TEXT("Error");
	}
	else if (TotalWarningCount > 0)
	{
		AggregateStatus = TEXT("UpToDateWithWarnings");
	}

	TSharedPtr<FJsonObject> Result = MakeShared<FJsonObject>();
	Result->SetStringField(TEXT("name"), System->GetName());
	Result->SetStringField(TEXT("path"), System->GetPathName());
	Result->SetStringField(TEXT("compile_status"), AggregateStatus);
	Result->SetStringField(TEXT("min_severity"), CompileSeverityToString(MinSeverity));
	Result->SetBoolField(TEXT("refresh_compile"), bRefreshCompile);
	Result->SetBoolField(TEXT("requested_compile"), bRequestedCompile);
	Result->SetBoolField(TEXT("wait"), bWait);
	Result->SetBoolField(TEXT("has_outstanding_compilation_requests"), System->HasOutstandingCompilationRequests(true));
	Result->SetNumberField(TEXT("error_count"), TotalErrorCount);
	Result->SetNumberField(TEXT("warning_count"), TotalWarningCount);
	Result->SetNumberField(TEXT("compile_event_error_count"), ErrorCount);
	Result->SetNumberField(TEXT("compile_event_warning_count"), WarningCount);
	Result->SetNumberField(TEXT("event_count"), FlatEvents.Num());
	Result->SetNumberField(TEXT("stack_issue_error_count"), StackIssueErrorCount);
	Result->SetNumberField(TEXT("stack_issue_warning_count"), StackIssueWarningCount);
	Result->SetNumberField(TEXT("stack_issue_count"), StackIssues.Num());
	Result->SetArrayField(TEXT("events"), FlatEvents);
	Result->SetArrayField(TEXT("stack_issues"), StackIssues);
	Result->SetArrayField(TEXT("scripts"), ScriptArray);
	return CreateSuccessResponse(Result);
}

// =========================================================================
// FNiagaraSpawnSystemActorAction
// =========================================================================

bool FNiagaraSpawnSystemActorAction::Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError)
{
	FString SystemPath;
	return GetRequiredString(Params, TEXT("system_path"), SystemPath, OutError);
}

TSharedPtr<FJsonObject> FNiagaraSpawnSystemActorAction::ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context)
{
	FString SystemPath, Error;
	GetRequiredString(Params, TEXT("system_path"), SystemPath, Error);

	UNiagaraSystem* System = LoadNiagaraSystemByPath(SystemPath, Error);
	if (!System)
	{
		return CreateErrorResponse(Error, TEXT("system_not_found"));
	}

	UWorld* World = ResolveRuntimeOrEditorWorld();
	if (!World)
	{
		return CreateErrorResponse(TEXT("No editor world available."), TEXT("no_world"));
	}

	FString ActorName = GetJsonString(Params, TEXT("actor_name"));
	if (ActorName.IsEmpty())
	{
		ActorName = FString::Printf(TEXT("MCP_%s_%s"), *System->GetName(), *FGuid::NewGuid().ToString(EGuidFormats::Short));
	}

	const bool bDestroyExisting = !Params->HasField(TEXT("destroy_existing")) || Params->GetBoolField(TEXT("destroy_existing"));
	if (bDestroyExisting)
	{
		if (AActor* ExistingActor = FindEditorActorByName(World, ActorName))
		{
			World->EditorDestroyActor(ExistingActor, true);
		}
	}
	else if (FindEditorActorByName(World, ActorName))
	{
		return CreateErrorResponse(FString::Printf(TEXT("Actor already exists: %s"), *ActorName), TEXT("actor_exists"));
	}

	const FVector Location = GetJsonVector3OrDefault(Params, TEXT("location"), FVector::ZeroVector);
	const FVector RotationVector = GetJsonVector3OrDefault(Params, TEXT("rotation"), FVector::ZeroVector);
	const FRotator Rotation = FRotator::MakeFromEuler(RotationVector);
	const FVector Scale = GetJsonVector3OrDefault(Params, TEXT("scale"), FVector(1.0, 1.0, 1.0));
	const bool bAutoActivate = !Params->HasField(TEXT("auto_activate")) || Params->GetBoolField(TEXT("auto_activate"));
	double DesiredAgeValue = 0.0;
	const bool bUseDesiredAge = Params->TryGetNumberField(TEXT("desired_age"), DesiredAgeValue);
	const double SeekDelta = FMath::Max(0.001, GetOptionalNumber(Params, TEXT("seek_delta"), 1.0 / 60.0));

	FActorSpawnParameters SpawnParams;
	SpawnParams.Name = FName(*ActorName);
	SpawnParams.NameMode = FActorSpawnParameters::ESpawnActorNameMode::Requested;

	ANiagaraActor* Actor = World->SpawnActor<ANiagaraActor>(ANiagaraActor::StaticClass(), Location, Rotation, SpawnParams);
	if (!Actor)
	{
		return CreateErrorResponse(TEXT("Failed to spawn NiagaraActor."), TEXT("spawn_failed"));
	}

	Actor->SetActorLabel(*ActorName);
	Actor->SetActorScale3D(Scale);

	UNiagaraComponent* Component = Actor->GetNiagaraComponent();
	if (!Component)
	{
		World->EditorDestroyActor(Actor, true);
		return CreateErrorResponse(TEXT("Spawned NiagaraActor has no NiagaraComponent."), TEXT("missing_component"));
	}

	Component->SetAutoActivate(false);
	Component->SetAsset(System, true);
	if (bUseDesiredAge)
	{
		Component->SetAgeUpdateMode(ENiagaraAgeUpdateMode::DesiredAge);
		Component->SetSeekDelta(static_cast<float>(SeekDelta));
		Component->SetLockDesiredAgeDeltaTimeToSeekDelta(true);
		Component->SetCanRenderWhileSeeking(true);
	}

	TArray<TSharedPtr<FJsonValue>> AppliedParameters;
	const TSharedPtr<FJsonObject>* VectorParametersObject = nullptr;
	if (Params->TryGetObjectField(TEXT("vector_parameters"), VectorParametersObject) && VectorParametersObject && VectorParametersObject->IsValid())
	{
		for (const auto& Pair : (*VectorParametersObject)->Values)
		{
			if (!Pair.Value.IsValid() || Pair.Value->Type != EJson::Array)
			{
				continue;
			}

			FVector Value;
			if (!TryReadVector3Array(Pair.Value->AsArray(), Value))
			{
				continue;
			}

			FString ParameterName(Pair.Key.ToView());
			if (!ParameterName.Contains(TEXT(".")))
			{
				ParameterName = FString::Printf(TEXT("User.%s"), *ParameterName);
			}

			Component->SetVariableVec3(FName(*ParameterName), Value);

			TSharedPtr<FJsonObject> ParameterJson = MakeShared<FJsonObject>();
			ParameterJson->SetStringField(TEXT("name"), ParameterName);
			ParameterJson->SetArrayField(TEXT("value"), VectorToJsonArray(Value));
			AppliedParameters.Add(MakeShared<FJsonValueObject>(ParameterJson));
		}
	}

	if (bAutoActivate)
	{
		Component->Activate(true);
		if (bUseDesiredAge)
		{
			Component->SeekToDesiredAge(static_cast<float>(FMath::Max(0.0, DesiredAgeValue)));
		}
	}

	Context.LastCreatedActorName = ActorName;
	if (World->WorldType == EWorldType::Editor)
	{
		Context.MarkPackageDirty(World->GetOutermost());
	}

	TSharedPtr<FJsonObject> Result = MakeShared<FJsonObject>();
	Result->SetStringField(TEXT("system_path"), System->GetPathName());
	Result->SetStringField(TEXT("actor_name"), ActorName);
	Result->SetStringField(TEXT("world_name"), World->GetName());
	Result->SetStringField(TEXT("world_type"), WorldTypeToString(World->WorldType));
	Result->SetStringField(TEXT("component_name"), Component->GetName());
	Result->SetBoolField(TEXT("auto_activate"), bAutoActivate);
	Result->SetBoolField(TEXT("component_active"), Component->IsActive());
	Result->SetBoolField(TEXT("used_desired_age"), bUseDesiredAge);
	if (bUseDesiredAge)
	{
		Result->SetNumberField(TEXT("desired_age"), DesiredAgeValue);
		Result->SetNumberField(TEXT("seek_delta"), SeekDelta);
	}
	Result->SetArrayField(TEXT("location"), VectorToJsonArray(Location));
	Result->SetArrayField(TEXT("rotation"), VectorToJsonArray(RotationVector));
	Result->SetArrayField(TEXT("scale"), VectorToJsonArray(Scale));
	Result->SetArrayField(TEXT("applied_vector_parameters"), AppliedParameters);
	return CreateSuccessResponse(Result);
}

// =========================================================================
// FNiagaraGetComponentDebugSummaryAction
// =========================================================================

bool FNiagaraGetComponentDebugSummaryAction::Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError)
{
	FString ActorName;
	return GetRequiredString(Params, TEXT("actor_name"), ActorName, OutError);
}

TSharedPtr<FJsonObject> FNiagaraGetComponentDebugSummaryAction::ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context)
{
	FString ActorName, Error;
	GetRequiredString(Params, TEXT("actor_name"), ActorName, Error);

	UWorld* World = ResolveRuntimeOrEditorWorld();
	if (!World)
	{
		return CreateErrorResponse(TEXT("No editor world available."), TEXT("no_world"));
	}

	AActor* Actor = FindEditorActorByName(World, ActorName);
	if (!Actor)
	{
		return CreateErrorResponse(FString::Printf(TEXT("Actor not found: %s"), *ActorName), TEXT("actor_not_found"));
	}

	UNiagaraComponent* Component = nullptr;
	if (ANiagaraActor* NiagaraActor = Cast<ANiagaraActor>(Actor))
	{
		Component = NiagaraActor->GetNiagaraComponent();
	}
	if (!Component)
	{
		Component = Actor->FindComponentByClass<UNiagaraComponent>();
	}
	if (!Component)
	{
		return CreateErrorResponse(FString::Printf(TEXT("Actor '%s' has no NiagaraComponent."), *ActorName), TEXT("component_not_found"));
	}

	TSharedPtr<FJsonObject> Result = MakeNiagaraComponentDebugJson(Component);
	Result->SetStringField(TEXT("actor_name"), Actor->GetName());
	Result->SetStringField(TEXT("actor_label"), Actor->GetActorLabel());
	Result->SetStringField(TEXT("world_name"), World->GetName());
	Result->SetStringField(TEXT("world_type"), WorldTypeToString(World->WorldType));

	return CreateSuccessResponse(Result);
}

// =========================================================================
// FNiagaraListWorldComponentsAction
// =========================================================================

bool FNiagaraListWorldComponentsAction::Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError)
{
	return true;
}

TSharedPtr<FJsonObject> FNiagaraListWorldComponentsAction::ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context)
{
	UWorld* World = ResolveRuntimeOrEditorWorld();
	if (!World)
	{
		return CreateErrorResponse(TEXT("No editor world available."), TEXT("no_world"));
	}

	const FString AssetPathFilter = GetOptionalString(Params, TEXT("asset_path"), TEXT(""));
	const FString NameContains = GetOptionalString(Params, TEXT("name_contains"), TEXT(""));
	const bool bIncludeInactive = !Params->HasField(TEXT("include_inactive")) || Params->GetBoolField(TEXT("include_inactive"));
	const bool bIncludeComplete = !Params->HasField(TEXT("include_complete")) || Params->GetBoolField(TEXT("include_complete"));

	TArray<TSharedPtr<FJsonValue>> ComponentsJson;
	for (TObjectIterator<UNiagaraComponent> It; It; ++It)
	{
		UNiagaraComponent* Component = *It;
		if (!IsValid(Component) || Component->GetWorld() != World)
		{
			continue;
		}
		if (!bIncludeInactive && !Component->IsActive())
		{
			continue;
		}
		if (!bIncludeComplete && Component->IsComplete())
		{
			continue;
		}
		if (!NameContains.IsEmpty() && !Component->GetName().Contains(NameContains, ESearchCase::IgnoreCase))
		{
			continue;
		}
		if (!AssetPathFilter.IsEmpty())
		{
			UNiagaraSystem* Asset = Component->GetAsset();
			const FString AssetPath = Asset ? Asset->GetPathName() : FString();
			if (!AssetPath.Contains(AssetPathFilter, ESearchCase::IgnoreCase))
			{
				continue;
			}
		}

		ComponentsJson.Add(MakeShared<FJsonValueObject>(MakeNiagaraComponentDebugJson(Component)));
	}

	TSharedPtr<FJsonObject> Result = MakeShared<FJsonObject>();
	Result->SetStringField(TEXT("world_name"), World->GetName());
	Result->SetStringField(TEXT("world_type"), WorldTypeToString(World->WorldType));
	Result->SetStringField(TEXT("asset_path_filter"), AssetPathFilter);
	Result->SetStringField(TEXT("name_contains"), NameContains);
	Result->SetBoolField(TEXT("include_inactive"), bIncludeInactive);
	Result->SetBoolField(TEXT("include_complete"), bIncludeComplete);
	Result->SetNumberField(TEXT("component_count"), ComponentsJson.Num());
	Result->SetArrayField(TEXT("components"), ComponentsJson);
	return CreateSuccessResponse(Result);
}

// =========================================================================
// FNiagaraAdvanceWorldComponentsAction
// =========================================================================

bool FNiagaraAdvanceWorldComponentsAction::Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError)
{
	const int32 TickCount = static_cast<int32>(GetOptionalNumber(Params, TEXT("tick_count"), 1.0));
	if (TickCount < 1)
	{
		OutError = TEXT("tick_count must be >= 1.");
		return false;
	}
	const double TickDeltaSeconds = GetOptionalNumber(Params, TEXT("tick_delta_seconds"), 1.0 / 60.0);
	if (TickDeltaSeconds <= 0.0)
	{
		OutError = TEXT("tick_delta_seconds must be > 0.");
		return false;
	}
	return true;
}

TSharedPtr<FJsonObject> FNiagaraAdvanceWorldComponentsAction::ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context)
{
	UWorld* World = ResolveRuntimeOrEditorWorld();
	if (!World)
	{
		return CreateErrorResponse(TEXT("No editor world available."), TEXT("no_world"));
	}

	const FString AssetPathFilter = GetOptionalString(Params, TEXT("asset_path"), TEXT(""));
	const FString NameContains = GetOptionalString(Params, TEXT("name_contains"), TEXT(""));
	const bool bIncludeInactive = !Params->HasField(TEXT("include_inactive")) || Params->GetBoolField(TEXT("include_inactive"));
	const bool bIncludeComplete = !Params->HasField(TEXT("include_complete")) || Params->GetBoolField(TEXT("include_complete"));
	const bool bActivate = GetOptionalBool(Params, TEXT("activate"), true);
	const bool bTickWorld = GetOptionalBool(Params, TEXT("tick_world"), false);
	if (bTickWorld)
	{
		return CreateErrorResponse(TEXT("tick_world is disabled because synchronous UWorld::Tick from MCP can break the editor bridge. Component advance only ticks NiagaraComponents and does not flush Niagara Data Channel publish requests; use normal editor frames or Data Channel diagnostics for NDC validation."), TEXT("world_tick_unsupported"));
	}
	const int32 TickCount = FMath::Max(1, static_cast<int32>(GetOptionalNumber(Params, TEXT("tick_count"), 1.0)));
	const float TickDeltaSeconds = FMath::Max(KINDA_SMALL_NUMBER, static_cast<float>(GetOptionalNumber(Params, TEXT("tick_delta_seconds"), 1.0 / 60.0)));

	TArray<UNiagaraComponent*> Components;
	for (TObjectIterator<UNiagaraComponent> It; It; ++It)
	{
		UNiagaraComponent* Component = *It;
		if (!IsValid(Component) || Component->GetWorld() != World)
		{
			continue;
		}
		if (!bIncludeInactive && !Component->IsActive())
		{
			continue;
		}
		if (!bIncludeComplete && Component->IsComplete())
		{
			continue;
		}
		if (!NameContains.IsEmpty() && !Component->GetName().Contains(NameContains, ESearchCase::IgnoreCase))
		{
			continue;
		}
		if (!AssetPathFilter.IsEmpty())
		{
			UNiagaraSystem* Asset = Component->GetAsset();
			const FString AssetPath = Asset ? Asset->GetPathName() : FString();
			if (!AssetPath.Contains(AssetPathFilter, ESearchCase::IgnoreCase))
			{
				continue;
			}
		}
		Components.Add(Component);
	}

	for (UNiagaraComponent* Component : Components)
	{
		if (bActivate && !Component->IsActive())
		{
			Component->Activate(true);
		}
		Component->SetPaused(false);
	}

	for (int32 TickIndex = 0; TickIndex < TickCount; ++TickIndex)
	{

		for (UNiagaraComponent* Component : Components)
		{
			if (!IsValid(Component))
			{
				continue;
			}

			if (!bTickWorld)
			{
				Component->AdvanceSimulation(1, TickDeltaSeconds);
			}
		}
	}

	TArray<TSharedPtr<FJsonValue>> ComponentsJson;
	int32 AdvancedCount = 0;
	for (UNiagaraComponent* Component : Components)
	{
		if (!IsValid(Component))
		{
			continue;
		}
		++AdvancedCount;
		ComponentsJson.Add(MakeShared<FJsonValueObject>(MakeNiagaraComponentDebugJson(Component)));
	}

	TSharedPtr<FJsonObject> Result = MakeShared<FJsonObject>();
	Result->SetStringField(TEXT("world_name"), World->GetName());
	Result->SetStringField(TEXT("world_type"), WorldTypeToString(World->WorldType));
	Result->SetStringField(TEXT("asset_path_filter"), AssetPathFilter);
	Result->SetStringField(TEXT("name_contains"), NameContains);
	Result->SetBoolField(TEXT("include_inactive"), bIncludeInactive);
	Result->SetBoolField(TEXT("include_complete"), bIncludeComplete);
	Result->SetBoolField(TEXT("activate"), bActivate);
	Result->SetBoolField(TEXT("tick_world"), bTickWorld);
	Result->SetNumberField(TEXT("tick_count"), TickCount);
	Result->SetNumberField(TEXT("tick_delta_seconds"), TickDeltaSeconds);
	Result->SetNumberField(TEXT("advanced_component_count"), AdvancedCount);
	Result->SetArrayField(TEXT("components"), ComponentsJson);
	return CreateSuccessResponse(Result);
}

// =========================================================================
// FNiagaraPreviewSeekAction
// =========================================================================

bool FNiagaraPreviewSeekAction::Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError)
{
	FString AssetPath;
	if (!GetRequiredString(Params, TEXT("asset_path"), AssetPath, OutError))
	{
		return false;
	}

	double TimeSeconds = 0.0;
	if (Params->TryGetNumberField(TEXT("time_seconds"), TimeSeconds) && TimeSeconds < 0.0)
	{
		OutError = TEXT("time_seconds must be >= 0.");
		return false;
	}

	double Frame = 0.0;
	if (Params->TryGetNumberField(TEXT("frame"), Frame) && Frame < 0.0)
	{
		OutError = TEXT("frame must be >= 0.");
		return false;
	}

	double Fps = 30.0;
	if (Params->TryGetNumberField(TEXT("fps"), Fps) && Fps <= 0.0)
	{
		OutError = TEXT("fps must be > 0.");
		return false;
	}

	return true;
}

TSharedPtr<FJsonObject> FNiagaraPreviewSeekAction::ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context)
{
	FString AssetPath, Error;
	GetRequiredString(Params, TEXT("asset_path"), AssetPath, Error);

	UNiagaraSystem* System = LoadNiagaraSystemByPath(AssetPath, Error);
	if (!System)
	{
		return CreateErrorResponse(Error, TEXT("system_not_found"));
	}

	if (!GEditor)
	{
		return CreateErrorResponse(TEXT("GEditor is not available."), TEXT("no_editor"));
	}

	double TimeSeconds = 0.0;
	if (!Params->TryGetNumberField(TEXT("time_seconds"), TimeSeconds))
	{
		double Frame = 0.0;
		if (Params->TryGetNumberField(TEXT("frame"), Frame))
		{
			const double Fps = FMath::Max(0.001, GetOptionalNumber(Params, TEXT("fps"), 30.0));
			TimeSeconds = Frame / Fps;
		}
	}
	TimeSeconds = FMath::Max(0.0, TimeSeconds);

	const bool bOpenEditor = !Params->HasField(TEXT("open_editor")) || Params->GetBoolField(TEXT("open_editor"));
	const bool bFocusEditor = !Params->HasField(TEXT("focus_editor")) || Params->GetBoolField(TEXT("focus_editor"));
	bool bEditorAlreadyOpen = false;
	bool bOpenEditorRequested = false;
	bool bOpenEditorSucceeded = false;

	UAssetEditorSubsystem* AssetEditorSubsystem = GEditor->GetEditorSubsystem<UAssetEditorSubsystem>();
	if (AssetEditorSubsystem)
	{
		bEditorAlreadyOpen = AssetEditorSubsystem->FindEditorForAsset(System, bFocusEditor) != nullptr;
		if (bOpenEditor && !bEditorAlreadyOpen)
		{
			bOpenEditorRequested = true;
			bOpenEditorSucceeded = AssetEditorSubsystem->OpenEditorForAsset(System);
		}
		else
		{
			bOpenEditorSucceeded = bEditorAlreadyOpen;
		}
	}

	FNiagaraEditorModule& NiagaraEditorModule = FModuleManager::LoadModuleChecked<FNiagaraEditorModule>(TEXT("NiagaraEditor"));
	TSharedPtr<FNiagaraSystemViewModel> SystemViewModel = NiagaraEditorModule.GetExistingViewModelForSystem(System);
	for (int32 Attempt = 0; !SystemViewModel.IsValid() && bOpenEditor && Attempt < 8; ++Attempt)
	{
		if (FSlateApplication::IsInitialized())
		{
			FSlateApplication::Get().PumpMessages();
			FSlateApplication::Get().Tick();
		}
		SystemViewModel = NiagaraEditorModule.GetExistingViewModelForSystem(System);
	}

	if (!SystemViewModel.IsValid())
	{
		return CreateErrorResponse(
			TEXT("Niagara editor preview ViewModel was not found. Open the Niagara asset editor or call with open_editor=true."),
			TEXT("preview_view_model_not_found"));
	}

	UNiagaraComponent* Component = SystemViewModel->GetPreviewComponent();
	if (!Component)
	{
		return CreateErrorResponse(TEXT("Niagara editor ViewModel has no preview component."), TEXT("preview_component_not_found"));
	}

	const double PreviewReadyTimeout = FMath::Max(0.0, GetOptionalNumber(Params, TEXT("preview_ready_timeout"), bOpenEditorRequested ? 2.0 : 0.0));
	const double PreviewReadyStart = FPlatformTime::Seconds();
	while (PreviewReadyTimeout > 0.0 && FPlatformTime::Seconds() - PreviewReadyStart < PreviewReadyTimeout)
	{
		if (System->HasOutstandingCompilationRequests(true))
		{
			System->PollForCompilationComplete();
		}

		if (System->IsReadyToRun()
			&& Component->IsRegistered()
			&& Component->GetWorld()
			&& Component->GetWorld()->WorldType == EWorldType::EditorPreview
			&& Component->IsWorldReadyToRun())
		{
			break;
		}
		if (FSlateApplication::IsInitialized())
		{
			FSlateApplication::Get().PumpMessages();
			FSlateApplication::Get().Tick();
		}
		FPlatformProcess::Sleep(0.02f);
	}

	TArray<TSharedPtr<FJsonValue>> AppliedParameters;
	auto ApplyVectorOverrides = [&](const FString& FieldName, const bool bPosition)
	{
		const TSharedPtr<FJsonObject>* ParametersObject = nullptr;
		if (!Params->TryGetObjectField(FieldName, ParametersObject) || !ParametersObject || !ParametersObject->IsValid())
		{
			return;
		}

		for (const auto& Pair : (*ParametersObject)->Values)
		{
			if (!Pair.Value.IsValid() || Pair.Value->Type != EJson::Array)
			{
				continue;
			}

			FVector Value;
			if (!TryReadVector3Array(Pair.Value->AsArray(), Value))
			{
				continue;
			}

			FString ParameterName(Pair.Key.ToView());
			if (!ParameterName.Contains(TEXT(".")))
			{
				ParameterName = FString::Printf(TEXT("User.%s"), *ParameterName);
			}

			if (bPosition)
			{
				Component->SetVariablePosition(FName(*ParameterName), Value);
			}
			else
			{
				Component->SetVariableVec3(FName(*ParameterName), Value);
			}

			TSharedPtr<FJsonObject> ParameterJson = MakeShared<FJsonObject>();
			ParameterJson->SetStringField(TEXT("name"), ParameterName);
			ParameterJson->SetStringField(TEXT("type"), bPosition ? TEXT("position") : TEXT("vec3"));
			ParameterJson->SetArrayField(TEXT("value"), VectorToJsonArray(Value));
			AppliedParameters.Add(MakeShared<FJsonValueObject>(ParameterJson));
		}
	};
	ApplyVectorOverrides(TEXT("vector_parameters"), false);
	ApplyVectorOverrides(TEXT("position_parameters"), true);

	const bool bResetSystem = !Params->HasField(TEXT("reset_system")) || Params->GetBoolField(TEXT("reset_system"));
	const double SeekDelta = FMath::Max(0.001, GetOptionalNumber(Params, TEXT("seek_delta"), 1.0 / 60.0));

	if (System->HasOutstandingCompilationRequests(true))
	{
		System->WaitForCompilationComplete(true, false);
	}
	System->PollForCompilationComplete();

	Component->SetAsset(System, false);
	Component->SetForceSolo(true);
	Component->SetAgeUpdateMode(ENiagaraAgeUpdateMode::DesiredAge);
	Component->SetSeekDelta(static_cast<float>(SeekDelta));
	Component->SetLockDesiredAgeDeltaTimeToSeekDelta(false);
	Component->SetCanRenderWhileSeeking(true);
	if (bResetSystem)
	{
		Component->DeactivateImmediate();
		Component->SetDesiredAge(0.0f);
		Component->ReinitializeSystem();
	}
	bool bDrovePreviewTick = false;
	int32 PreviewTickAttempts = 0;
	const int32 MaxPreviewTickAttempts = 16;
	for (; PreviewTickAttempts < MaxPreviewTickAttempts; ++PreviewTickAttempts)
	{
		if (!Component->IsActive() || !Component->GetSystemInstanceController().IsValid())
		{
			Component->Activate(true);
		}

		Component->SeekToDesiredAge(static_cast<float>(TimeSeconds));
		UWorld* PreviewWorld = Component->GetWorld();
		if (PreviewWorld)
		{
			const float TimeSecondsFloat = static_cast<float>(TimeSeconds);
			const float SeekDeltaFloat = static_cast<float>(SeekDelta);
			PreviewWorld->TimeSeconds = TimeSecondsFloat;
			PreviewWorld->UnpausedTimeSeconds = TimeSecondsFloat;
			PreviewWorld->RealTimeSeconds = TimeSecondsFloat;
			PreviewWorld->DeltaRealTimeSeconds = SeekDeltaFloat;
			PreviewWorld->DeltaTimeSeconds = SeekDeltaFloat;
		}
		Component->TickComponent(static_cast<float>(SeekDelta), ELevelTick::LEVELTICK_All, nullptr);
		bDrovePreviewTick = true;

		FNiagaraSystemInstanceControllerPtr TickController = Component->GetSystemInstanceController();
		FNiagaraSystemInstance* TickSystemInstance = TickController.IsValid() ? TickController->GetSystemInstance_Unsafe() : nullptr;
		if (TickSystemInstance && (TimeSeconds <= 0.0 || TickSystemInstance->GetTickCount() > 0 || TickSystemInstance->GetAge() > 0.0f))
		{
			break;
		}

		if (FSlateApplication::IsInitialized())
		{
			FSlateApplication::Get().PumpMessages();
			FSlateApplication::Get().Tick();
		}
		FPlatformProcess::Sleep(0.02f);
	}
	Component->MarkRenderStateDirty();
	const int32 PreviewTickAttemptsRun = bDrovePreviewTick
		? FMath::Min(PreviewTickAttempts + 1, MaxPreviewTickAttempts)
		: 0;

	TSharedPtr<FJsonObject> Result = MakeShared<FJsonObject>();
	Result->SetStringField(TEXT("system_path"), System->GetPathName());
	Result->SetStringField(TEXT("asset_name"), System->GetName());
	Result->SetNumberField(TEXT("requested_time_seconds"), TimeSeconds);
	Result->SetBoolField(TEXT("reset_system"), bResetSystem);
	Result->SetNumberField(TEXT("seek_delta"), SeekDelta);
	Result->SetNumberField(TEXT("preview_ready_timeout"), PreviewReadyTimeout);
	Result->SetBoolField(TEXT("drove_preview_tick"), bDrovePreviewTick);
	Result->SetNumberField(TEXT("preview_tick_attempts"), PreviewTickAttemptsRun);
	Result->SetBoolField(TEXT("system_ready_to_run"), System->IsReadyToRun());
	Result->SetBoolField(TEXT("system_outstanding_compilation"), System->HasOutstandingCompilationRequests(true));
	Result->SetBoolField(TEXT("open_editor"), bOpenEditor);
	Result->SetBoolField(TEXT("focus_editor"), bFocusEditor);
	Result->SetBoolField(TEXT("editor_already_open"), bEditorAlreadyOpen);
	Result->SetBoolField(TEXT("open_editor_requested"), bOpenEditorRequested);
	Result->SetBoolField(TEXT("open_editor_succeeded"), bOpenEditorSucceeded);
	Result->SetBoolField(TEXT("sequencer_timeline_control_available"), false);
	Result->SetStringField(TEXT("sequencer_timeline_control_reason"),
		TEXT("UE 5.7 exposes FNiagaraSystemViewModel::GetSequencer in the header but does not export the symbol; preview is sought through the exported Niagara editor PreviewComponent instead."));
	Result->SetStringField(TEXT("component_name"), Component->GetName());
	Result->SetBoolField(TEXT("component_active"), Component->IsActive());
	Result->SetBoolField(TEXT("component_registered"), Component->IsRegistered());
	Result->SetBoolField(TEXT("component_world_ready_to_run"), Component->IsWorldReadyToRun());
	Result->SetBoolField(TEXT("component_complete"), Component->IsComplete());
	Result->SetNumberField(TEXT("component_desired_age"), Component->GetDesiredAge());
	Result->SetBoolField(TEXT("component_paused"), Component->IsPaused());
	Result->SetObjectField(TEXT("component_world_bounds"), MakeBoundsJson(Component->Bounds));
	Result->SetStringField(TEXT("preview_world_name"), Component->GetWorld() ? Component->GetWorld()->GetName() : FString());
	Result->SetStringField(TEXT("preview_world_type"), Component->GetWorld() ? WorldTypeToString(Component->GetWorld()->WorldType) : FString());
	Result->SetArrayField(TEXT("applied_parameters"), AppliedParameters);

	FNiagaraSystemInstanceControllerPtr Controller = Component->GetSystemInstanceController();
	Result->SetBoolField(TEXT("has_system_instance_controller"), Controller.IsValid());
	if (Controller.IsValid() && Controller->IsValid())
	{
		Result->SetStringField(TEXT("system_requested_execution_state"), ExecutionStateToString(Controller->GetRequestedExecutionState()));
		Result->SetStringField(TEXT("system_actual_execution_state"), ExecutionStateToString(Controller->GetActualExecutionState()));
		Result->SetBoolField(TEXT("system_complete"), Controller->IsComplete());
		Result->SetBoolField(TEXT("system_paused"), Controller->IsPaused());
		Result->SetObjectField(TEXT("system_local_bounds"), MakeBoxJson(Controller->GetLocalBounds()));

		TArray<TSharedPtr<FJsonValue>> EmittersJson;
		int32 TotalParticles = 0;
		FNiagaraSystemInstance* SystemInstance = Controller->GetSystemInstance_Unsafe();
		if (SystemInstance)
		{
			Result->SetNumberField(TEXT("system_age"), SystemInstance->GetAge());
			Result->SetNumberField(TEXT("system_tick_count"), SystemInstance->GetTickCount());
			if (TSharedPtr<FNiagaraSystemSimulation, ESPMode::ThreadSafe> SystemSimulation = SystemInstance->GetSystemSimulation())
			{
				const FNiagaraTickInfo& TickInfo = SystemSimulation->GetTickInfo();
				Result->SetNumberField(TEXT("system_tick_info_tick_number"), TickInfo.TickNumber);
				Result->SetNumberField(TEXT("system_tick_info_tick_count"), TickInfo.TickCount);
				Result->SetNumberField(TEXT("system_tick_info_time_step_fraction"), TickInfo.TimeStepFraction);
				Result->SetNumberField(TEXT("system_tick_info_engine_tick"), TickInfo.EngineTick);
			}

			for (const FNiagaraEmitterInstanceRef& EmitterRef : SystemInstance->GetEmitters())
			{
				const FNiagaraEmitterInstance& Emitter = EmitterRef.Get();
				const int32 NumParticles = Emitter.GetNumParticles();
				TotalParticles += NumParticles;

				TSharedPtr<FJsonObject> EmitterJson = MakeShared<FJsonObject>();
				EmitterJson->SetStringField(TEXT("name"), Emitter.GetEmitterHandle().GetName().ToString());
					EmitterJson->SetNumberField(TEXT("emitter_id"), Emitter.GetEmitterID().ID);
				EmitterJson->SetBoolField(TEXT("handle_enabled"), Emitter.GetEmitterHandle().GetIsEnabled());
				EmitterJson->SetStringField(TEXT("execution_state"), ExecutionStateToString(Emitter.GetExecutionState()));
				EmitterJson->SetBoolField(TEXT("active"), Emitter.IsActive());
				EmitterJson->SetBoolField(TEXT("complete"), Emitter.IsComplete());
				EmitterJson->SetStringField(TEXT("sim_target"), Emitter.GetSimTarget() == ENiagaraSimTarget::CPUSim ? TEXT("CPUSim") : TEXT("GPUComputeSim"));
				EmitterJson->SetNumberField(TEXT("num_particles"), NumParticles);
				EmitterJson->SetNumberField(TEXT("total_spawned_particles"), Emitter.GetTotalSpawnedParticles());
				EmitterJson->SetObjectField(TEXT("bounds"), MakeBoxJson(Emitter.GetBounds()));

				const FNiagaraDataSet& ParticleData = Emitter.GetParticleData();
				const FNiagaraDataBuffer* CurrentData = ParticleData.GetCurrentData();
				EmitterJson->SetNumberField(TEXT("current_data_instances"), CurrentData ? CurrentData->GetNumInstances() : -1);
				EmittersJson.Add(MakeShared<FJsonValueObject>(EmitterJson));
			}
		}
		Result->SetNumberField(TEXT("total_particles"), TotalParticles);
		Result->SetArrayField(TEXT("emitters"), EmittersJson);
	}

	return CreateSuccessResponse(Result);
}

// =========================================================================
// FNiagaraCreateSystemAction
// =========================================================================

bool FNiagaraCreateSystemAction::Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError)
{
	FString Name;
	if (!GetRequiredString(Params, TEXT("name"), Name, OutError))
	{
		return false;
	}
	if (!FName(*Name).IsValidXName(INVALID_OBJECTNAME_CHARACTERS))
	{
		OutError = FString::Printf(TEXT("Invalid asset name '%s'."), *Name);
		return false;
	}
	return true;
}

TSharedPtr<FJsonObject> FNiagaraCreateSystemAction::ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context)
{
	FString Error;
	FString Name;
	GetRequiredString(Params, TEXT("name"), Name, Error);
	const FString Path = GetOptionalString(Params, TEXT("path"), TEXT("/Game/FX"));
	const FString IfExists = GetOptionalString(Params, TEXT("if_exists"), TEXT("error"));

	const FString PackagePath = Path / Name;

	// Handle an existing asset explicitly; never silently overwrite.
	{
		FAssetRegistryModule& AssetRegistryModule = FModuleManager::LoadModuleChecked<FAssetRegistryModule>(TEXT("AssetRegistry"));
		const FString ObjectPath = FString::Printf(TEXT("%s.%s"), *PackagePath, *Name);
		const FAssetData Existing = AssetRegistryModule.Get().GetAssetByObjectPath(FSoftObjectPath(ObjectPath));
		const bool bAssetExists = Existing.IsValid() || UEditorAssetLibrary::DoesAssetExist(PackagePath) || FindPackage(nullptr, *PackagePath) != nullptr;
		if (bAssetExists)
		{
			if (IfExists.Equals(TEXT("overwrite"), ESearchCase::IgnoreCase))
			{
				const FString ExistingObjectPath = FString::Printf(TEXT("%s.%s"), *PackagePath, *Name);
				UObject* ExistingAsset = Existing.GetAsset();
				if (!ExistingAsset)
				{
					ExistingAsset = LoadObject<UObject>(nullptr, *ExistingObjectPath);
				}
				if (!ExistingAsset)
				{
					if (UPackage* ExistingPackage = FindPackage(nullptr, *PackagePath))
					{
						ExistingAsset = FindObject<UObject>(ExistingPackage, *Name);
					}
				}

				if (ExistingAsset && GEditor)
				{
					if (UAssetEditorSubsystem* AssetEditorSubsystem = GEditor->GetEditorSubsystem<UAssetEditorSubsystem>())
					{
						AssetEditorSubsystem->CloseAllEditorsForAsset(ExistingAsset);
					}
				}

				if (UEditorAssetLibrary::DoesAssetExist(PackagePath))
				{
					if (!UEditorAssetLibrary::DeleteAsset(PackagePath))
					{
						return CreateErrorResponse(
							FString::Printf(TEXT("Failed to delete existing Niagara system '%s' before overwrite. Close asset editors/save dialogs and retry, or use if_exists='reuse' / a new asset name."), *PackagePath),
							TEXT("delete_existing_failed"));
					}
					CollectGarbage(RF_NoFlags);
				}
				else if (FindPackage(nullptr, *PackagePath) != nullptr)
				{
					return CreateErrorResponse(
						FString::Printf(TEXT("Existing package '%s' is loaded but no loadable asset exists at that path; refusing overwrite to avoid creating an unsavable package."), *PackagePath),
						TEXT("loaded_package_without_asset"));
				}

				if (UEditorAssetLibrary::DoesAssetExist(PackagePath) || FindPackage(nullptr, *PackagePath) != nullptr)
				{
					return CreateErrorResponse(
						FString::Printf(TEXT("Existing Niagara system package '%s' is still loaded after delete; refusing overwrite to avoid editor/object mismatch."), *PackagePath),
						TEXT("existing_package_still_loaded"));
				}
			}
			else if (IfExists.Equals(TEXT("skip"), ESearchCase::IgnoreCase) || IfExists.Equals(TEXT("reuse"), ESearchCase::IgnoreCase))
			{
				FString LoadError;
				UNiagaraSystem* ExistingSystem = LoadNiagaraSystemByPath(PackagePath, LoadError);
				if (!ExistingSystem)
				{
					return CreateErrorResponse(
						FString::Printf(TEXT("An asset already exists at '%s' but it is not a Niagara system"), *PackagePath),
						TEXT("asset_exists_type_mismatch"));
				}
				TSharedPtr<FJsonObject> Result = MakeShared<FJsonObject>();
				Result->SetStringField(TEXT("name"), Name);
				Result->SetStringField(TEXT("path"), PackagePath);
				Result->SetStringField(TEXT("object_path"), ExistingSystem->GetPathName());
				Result->SetStringField(TEXT("mode"), TEXT("existing"));
				Result->SetNumberField(TEXT("emitter_count"), ExistingSystem->GetEmitterHandles().Num());
				Result->SetBoolField(TEXT("existing"), true);
				Result->SetBoolField(TEXT("skipped"), true);
				Result->SetStringField(TEXT("if_exists"), IfExists);
				return CreateSuccessResponse(Result);
			}
			else if (!IfExists.Equals(TEXT("error"), ESearchCase::IgnoreCase))
			{
				return CreateErrorResponse(
					FString::Printf(TEXT("Invalid if_exists '%s'. Valid: error, overwrite, skip, reuse"), *IfExists),
					TEXT("invalid_if_exists"));
			}
			else
			{
				return CreateErrorResponse(
					FString::Printf(TEXT("An asset already exists at '%s'. Set if_exists to overwrite, skip, or reuse."), *PackagePath),
					TEXT("asset_exists"));
			}
		}
		else if (!IfExists.Equals(TEXT("error"), ESearchCase::IgnoreCase) && !IfExists.Equals(TEXT("overwrite"), ESearchCase::IgnoreCase) && !IfExists.Equals(TEXT("skip"), ESearchCase::IgnoreCase) && !IfExists.Equals(TEXT("reuse"), ESearchCase::IgnoreCase))
		{
			return CreateErrorResponse(
				FString::Printf(TEXT("Invalid if_exists '%s'. Valid: error, overwrite, skip, reuse"), *IfExists),
				TEXT("invalid_if_exists"));
		}
	}

	UPackage* Package = CreatePackage(*PackagePath);
	if (!Package)
	{
		return CreateErrorResponse(TEXT("Failed to create package for Niagara system"), TEXT("package_creation_failed"));
	}
	Package->FullyLoad();

	// AssetTools invokes the Niagara factory's private FactoryCreateNew override in UE 5.8.
	UNiagaraSystemFactoryNew* Factory = NewObject<UNiagaraSystemFactoryNew>();

	// Composition mode resolution (mutually exclusive; template wins over emitters).
	FString Mode = TEXT("empty");
	const FString TemplateSystemPath = GetOptionalString(Params, TEXT("template_system_path"), TEXT(""));
	if (!TemplateSystemPath.IsEmpty())
	{
		FString LoadError;
		UNiagaraSystem* TemplateSystem = LoadNiagaraSystemByPath(TemplateSystemPath, LoadError);
		if (!TemplateSystem)
		{
			return CreateErrorResponse(LoadError, TEXT("template_not_found"));
		}
		Factory->SystemToCopy = TemplateSystem;
		Mode = TEXT("template_copy");
	}
	else if (const TArray<TSharedPtr<FJsonValue>>* EmitterPaths = GetOptionalArray(Params, TEXT("emitter_asset_paths")))
	{
		for (const TSharedPtr<FJsonValue>& Entry : *EmitterPaths)
		{
			FString EmitterPath;
			if (!Entry.IsValid() || !Entry->TryGetString(EmitterPath) || EmitterPath.IsEmpty())
			{
				return CreateErrorResponse(
					TEXT("emitter_asset_paths must be an array of non-empty content path strings"),
					TEXT("invalid_param"));
			}
			FString LoadError;
			UNiagaraEmitter* EmitterAsset = LoadNiagaraEmitterByPath(EmitterPath, LoadError);
			if (!EmitterAsset)
			{
				return CreateErrorResponse(LoadError, TEXT("emitter_not_found"));
			}
			Factory->EmittersToAddToNewSystem.Add(FVersionedNiagaraEmitter(EmitterAsset, EmitterAsset->GetExposedVersion().VersionGuid));
		}
		if (Factory->EmittersToAddToNewSystem.Num() > 0)
		{
			Mode = TEXT("from_emitters");
		}
	}

	FAssetToolsModule& AssetToolsModule = FModuleManager::LoadModuleChecked<FAssetToolsModule>(TEXT("AssetTools"));
	UNiagaraSystem* NewSystem = Cast<UNiagaraSystem>(
		AssetToolsModule.Get().CreateAsset(Name, FPackageName::GetLongPackagePath(PackagePath), UNiagaraSystem::StaticClass(), Factory));

	if (!NewSystem)
	{
		return CreateErrorResponse(TEXT("Failed to create Niagara system"), TEXT("system_creation_failed"));
	}

	FAssetRegistryModule::AssetCreated(NewSystem);
	MarkNiagaraSystemEdited(*NewSystem, Context);

	TSharedPtr<FJsonObject> Result = MakeShared<FJsonObject>();
	Result->SetStringField(TEXT("name"), Name);
	Result->SetStringField(TEXT("path"), PackagePath);
	Result->SetStringField(TEXT("object_path"), NewSystem->GetPathName());
	Result->SetStringField(TEXT("mode"), Mode);
	Result->SetNumberField(TEXT("emitter_count"), NewSystem->GetEmitterHandles().Num());
	Result->SetBoolField(TEXT("existing"), false);
	Result->SetBoolField(TEXT("skipped"), false);
	Result->SetStringField(TEXT("if_exists"), IfExists);
	return CreateSuccessResponse(Result);
}

// =========================================================================
// FNiagaraAddEmitterAction
// =========================================================================

bool FNiagaraAddEmitterAction::Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError)
{
	FString SystemPath;
	if (!GetRequiredString(Params, TEXT("system_path"), SystemPath, OutError))
	{
		return false;
	}
	FString EmitterPath;
	return GetRequiredString(Params, TEXT("emitter_path"), EmitterPath, OutError);
}

TSharedPtr<FJsonObject> FNiagaraAddEmitterAction::ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context)
{
	FString Error;
	FString SystemPath;
	FString EmitterPath;
	GetRequiredString(Params, TEXT("system_path"), SystemPath, Error);
	GetRequiredString(Params, TEXT("emitter_path"), EmitterPath, Error);
	const bool bCreateCopy = GetOptionalBool(Params, TEXT("create_copy"), true);

	FString LoadError;
	UNiagaraSystem* System = LoadNiagaraSystemByPath(SystemPath, LoadError);
	if (!System)
	{
		return CreateErrorResponse(LoadError, TEXT("system_not_found"));
	}

	UNiagaraEmitter* Emitter = LoadNiagaraEmitterByPath(EmitterPath, LoadError);
	if (!Emitter)
	{
		return CreateErrorResponse(LoadError, TEXT("emitter_not_found"));
	}

	// AddEmitterToSystem is self-contained: it kills running instances, calls
	// Modify(), adds the emitter handle, rebuilds emitter nodes and synchronizes
	// the overview graph. Returns the new emitter handle id.
	const FGuid HandleId = FNiagaraEditorUtilities::AddEmitterToSystem(
		*System, *Emitter, Emitter->GetExposedVersion().VersionGuid, bCreateCopy);

	if (!HandleId.IsValid())
	{
		return CreateErrorResponse(
			FString::Printf(TEXT("AddEmitterToSystem returned an invalid handle for '%s'"), *EmitterPath),
			TEXT("add_emitter_failed"));
	}

	// Recompile so the system reflects the new emitter, then persist.
	MarkNiagaraSystemEdited(*System, Context);

	TSharedPtr<FJsonObject> Result = MakeShared<FJsonObject>();
	Result->SetStringField(TEXT("system_path"), System->GetPathName());
	Result->SetStringField(TEXT("emitter_path"), Emitter->GetPathName());
	Result->SetStringField(TEXT("emitter_handle_id"), HandleId.ToString());
	Result->SetNumberField(TEXT("emitter_count"), System->GetEmitterHandles().Num());
	return CreateSuccessResponse(Result);
}

// =========================================================================
// FNiagaraAddRendererAction
// =========================================================================

bool FNiagaraAddRendererAction::Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError)
{
	FString SystemPath;
	if (!GetRequiredString(Params, TEXT("system_path"), SystemPath, OutError))
	{
		return false;
	}
	FString RendererType;
	if (!GetRequiredString(Params, TEXT("renderer_type"), RendererType, OutError))
	{
		return false;
	}
	if (!(RendererType.Equals(TEXT("sprite"), ESearchCase::IgnoreCase) ||
		  RendererType.Equals(TEXT("mesh"), ESearchCase::IgnoreCase) ||
		  RendererType.Equals(TEXT("ribbon"), ESearchCase::IgnoreCase) ||
		  RendererType.Equals(TEXT("light"), ESearchCase::IgnoreCase)))
	{
		OutError = FString::Printf(TEXT("Invalid renderer_type '%s'. Use sprite|mesh|ribbon|light."), *RendererType);
		return false;
	}
	return true;
}

TSharedPtr<FJsonObject> FNiagaraAddRendererAction::ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context)
{
	FString Error;
	FString SystemPath;
	FString RendererType;
	GetRequiredString(Params, TEXT("system_path"), SystemPath, Error);
	GetRequiredString(Params, TEXT("renderer_type"), RendererType, Error);
	const FString EmitterName = GetOptionalString(Params, TEXT("emitter_name"), TEXT(""));
	const FString MaterialPath = GetOptionalString(Params, TEXT("material_path"), TEXT(""));
	const FString MeshPath = GetOptionalString(Params, TEXT("mesh_path"), TEXT(""));

	FString LoadError;
	UNiagaraSystem* System = LoadNiagaraSystemByPath(SystemPath, LoadError);
	if (!System)
	{
		return CreateErrorResponse(LoadError, TEXT("system_not_found"));
	}

	FString ResolveError;
	const FNiagaraEmitterHandle* Handle = ResolveEmitterHandle(*System, EmitterName, ResolveError);
	if (!Handle)
	{
		return CreateErrorResponse(ResolveError, TEXT("emitter_not_found"));
	}

	FVersionedNiagaraEmitter VersionedEmitter = Handle->GetInstance();
	UNiagaraEmitter* Emitter = VersionedEmitter.Emitter;
	FVersionedNiagaraEmitterData* EmitterData = Handle->GetEmitterData();
	if (!Emitter || !EmitterData)
	{
		return CreateErrorResponse(TEXT("Emitter handle has no valid instance data."), TEXT("invalid_emitter"));
	}

	// Construct the renderer property object owned by the emitter.
	UNiagaraRendererProperties* Renderer = nullptr;
	if (RendererType.Equals(TEXT("sprite"), ESearchCase::IgnoreCase))
	{
		UNiagaraSpriteRendererProperties* Sprite = NewObject<UNiagaraSpriteRendererProperties>(Emitter, NAME_None, RF_Transactional);
		if (!MaterialPath.IsEmpty())
		{
			if (UMaterialInterface* Material = LoadObject<UMaterialInterface>(nullptr, *NormalizeAssetObjectPath(MaterialPath)))
			{
				Sprite->Material = Material;
			}
			else
			{
				return CreateErrorResponse(FString::Printf(TEXT("Failed to load material '%s'"), *MaterialPath), TEXT("material_not_found"));
			}
		}
		Renderer = Sprite;
	}
	else if (RendererType.Equals(TEXT("mesh"), ESearchCase::IgnoreCase))
	{
		UNiagaraMeshRendererProperties* MeshRenderer = NewObject<UNiagaraMeshRendererProperties>(Emitter, NAME_None, RF_Transactional);
		if (!MeshPath.IsEmpty())
		{
			if (UStaticMesh* Mesh = LoadObject<UStaticMesh>(nullptr, *NormalizeAssetObjectPath(MeshPath)))
			{
				FNiagaraMeshRendererMeshProperties MeshProps;
				MeshProps.Mesh = Mesh;
				FVector Scale;
				FString VectorError;
				if (ReadVectorParam(Params, TEXT("scale"), Scale, VectorError))
				{
					MeshProps.Scale = Scale;
				}
				FRotator Rotation;
				if (ReadRotatorParam(Params, TEXT("rotation"), Rotation, VectorError))
				{
					MeshProps.Rotation = Rotation;
				}
				FVector PivotOffset;
				if (ReadVectorParam(Params, TEXT("pivot_offset"), PivotOffset, VectorError))
				{
					MeshProps.PivotOffset = PivotOffset;
				}
				MeshRenderer->Meshes.Add(MeshProps);
			}
			else
			{
				return CreateErrorResponse(FString::Printf(TEXT("Failed to load static mesh '%s'"), *MeshPath), TEXT("mesh_not_found"));
			}
		}
		if (!MaterialPath.IsEmpty())
		{
			if (UMaterialInterface* Material = LoadObject<UMaterialInterface>(nullptr, *NormalizeAssetObjectPath(MaterialPath)))
			{
				MeshRenderer->bOverrideMaterials = true;
				MeshRenderer->OverrideMaterials.SetNum(1);
				MeshRenderer->OverrideMaterials[0].ExplicitMat = Material;
			}
			else
			{
				return CreateErrorResponse(FString::Printf(TEXT("Failed to load material '%s'"), *MaterialPath), TEXT("material_not_found"));
			}
		}
		Renderer = MeshRenderer;
	}
	else if (RendererType.Equals(TEXT("ribbon"), ESearchCase::IgnoreCase))
	{
		UNiagaraRibbonRendererProperties* Ribbon = NewObject<UNiagaraRibbonRendererProperties>(Emitter, NAME_None, RF_Transactional);
		if (!MaterialPath.IsEmpty())
		{
			if (UMaterialInterface* Material = LoadObject<UMaterialInterface>(nullptr, *NormalizeAssetObjectPath(MaterialPath)))
			{
				Ribbon->Material = Material;
			}
			else
			{
				return CreateErrorResponse(FString::Printf(TEXT("Failed to load material '%s'"), *MaterialPath), TEXT("material_not_found"));
			}
		}
		Renderer = Ribbon;
	}
	else // light
	{
		Renderer = NewObject<UNiagaraLightRendererProperties>(Emitter, NAME_None, RF_Transactional);
	}

	if (!Renderer)
	{
		return CreateErrorResponse(TEXT("Failed to construct renderer properties."), TEXT("renderer_creation_failed"));
	}

	// Self-contained: AddRenderer Modify()s, wires version, rebuilds bindings,
	// updates the change id and broadcasts the change delegate.
	Emitter->AddRenderer(Renderer, EmitterData->Version.VersionGuid);
	MarkNiagaraSystemEdited(*System, Context);

	TSharedPtr<FJsonObject> Result = MakeShared<FJsonObject>();
	Result->SetStringField(TEXT("system_path"), System->GetPathName());
	Result->SetStringField(TEXT("emitter_name"), Handle->GetName().ToString());
	Result->SetStringField(TEXT("renderer_type"), RendererType.ToLower());
	Result->SetStringField(TEXT("renderer_class"), Renderer->GetClass()->GetName());
	Result->SetNumberField(TEXT("renderer_count"), EmitterData->GetRenderers().Num());
	return CreateSuccessResponse(Result);
}

// =========================================================================
// FNiagaraRemoveRendererAction
// =========================================================================

bool FNiagaraRemoveRendererAction::Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError)
{
	FString SystemPath;
	return GetRequiredString(Params, TEXT("system_path"), SystemPath, OutError);
}

TSharedPtr<FJsonObject> FNiagaraRemoveRendererAction::ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context)
{
	FString Error;
	FString SystemPath;
	GetRequiredString(Params, TEXT("system_path"), SystemPath, Error);

	UNiagaraSystem* System = LoadNiagaraSystemByPath(SystemPath, Error);
	if (!System)
	{
		return CreateErrorResponse(Error, TEXT("system_not_found"));
	}

	FString EmitterName;
	FVersionedNiagaraEmitter VersionedEmitter;
	FVersionedNiagaraEmitterData* EmitterData = nullptr;
	int32 RendererIndex = INDEX_NONE;
	UNiagaraRendererProperties* Renderer = ResolveRenderer(*System, Params, EmitterName, VersionedEmitter, EmitterData, RendererIndex, Error);
	if (!Renderer || !VersionedEmitter.Emitter || !EmitterData)
	{
		return CreateErrorResponse(Error, TEXT("renderer_not_found"));
	}

	const FString RendererType = GetRendererTypeString(Renderer);
	VersionedEmitter.Emitter->RemoveRenderer(Renderer, EmitterData->Version.VersionGuid);
	MarkNiagaraSystemEdited(*System, Context);

	TSharedPtr<FJsonObject> Result = MakeShared<FJsonObject>();
	Result->SetStringField(TEXT("system_path"), System->GetPathName());
	Result->SetStringField(TEXT("emitter_name"), EmitterName);
	Result->SetNumberField(TEXT("renderer_index"), RendererIndex);
	Result->SetStringField(TEXT("renderer_type"), RendererType);
	Result->SetNumberField(TEXT("renderer_count"), EmitterData->GetRenderers().Num());
	return CreateSuccessResponse(Result);
}

// =========================================================================
// FNiagaraGetRendererSummaryAction
// =========================================================================

bool FNiagaraGetRendererSummaryAction::Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError)
{
	FString SystemPath;
	if (!GetRequiredString(Params, TEXT("system_path"), SystemPath, OutError))
	{
		return false;
	}
	return true;
}

TSharedPtr<FJsonObject> FNiagaraGetRendererSummaryAction::ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context)
{
	FString Error;
	FString SystemPath;
	GetRequiredString(Params, TEXT("system_path"), SystemPath, Error);
	const FString EmitterName = GetOptionalString(Params, TEXT("emitter_name"), TEXT(""));
	const FString RendererTypeFilter = GetOptionalString(Params, TEXT("renderer_type"), TEXT(""));
	const int32 RendererIndexFilter = static_cast<int32>(GetJsonNumber(Params, TEXT("renderer_index"), -1.0));

	UNiagaraSystem* System = LoadNiagaraSystemByPath(SystemPath, Error);
	if (!System)
	{
		return CreateErrorResponse(Error, TEXT("system_not_found"));
	}

	FString ResolveError;
	const FNiagaraEmitterHandle* Handle = ResolveEmitterHandle(*System, EmitterName, ResolveError);
	if (!Handle)
	{
		return CreateErrorResponse(ResolveError, TEXT("emitter_not_found"));
	}

	FVersionedNiagaraEmitterData* EmitterData = Handle->GetEmitterData();
	if (!EmitterData)
	{
		return CreateErrorResponse(TEXT("Emitter handle has no valid instance data."), TEXT("invalid_emitter"));
	}

	const TArray<UNiagaraRendererProperties*>& Renderers = EmitterData->GetRenderers();
	TArray<TSharedPtr<FJsonValue>> RendererArray;
	for (int32 RendererIndex = 0; RendererIndex < Renderers.Num(); ++RendererIndex)
	{
		UNiagaraRendererProperties* Renderer = Renderers[RendererIndex];
		if (!Renderer)
		{
			continue;
		}
		if (RendererIndexFilter >= 0 && RendererIndex != RendererIndexFilter)
		{
			continue;
		}
		if (!DoesRendererMatchType(Renderer, RendererTypeFilter))
		{
			continue;
		}

		RendererArray.Add(MakeShared<FJsonValueObject>(MakeRendererSummaryJson(*Renderer, RendererIndex)));
	}

	TSharedPtr<FJsonObject> Result = MakeShared<FJsonObject>();
	Result->SetStringField(TEXT("system_path"), System->GetPathName());
	Result->SetStringField(TEXT("emitter_name"), Handle->GetName().ToString());
	Result->SetNumberField(TEXT("renderer_count"), Renderers.Num());
	Result->SetNumberField(TEXT("matched_renderer_count"), RendererArray.Num());
	Result->SetArrayField(TEXT("renderers"), RendererArray);
	return CreateSuccessResponse(Result);
}

// =========================================================================
// FNiagaraSetRendererMeshAction
// =========================================================================

bool FNiagaraSetRendererMeshAction::Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError)
{
	FString SystemPath;
	if (!GetRequiredString(Params, TEXT("system_path"), SystemPath, OutError))
	{
		return false;
	}
	FString MeshPath;
	return GetRequiredString(Params, TEXT("mesh_path"), MeshPath, OutError);
}

TSharedPtr<FJsonObject> FNiagaraSetRendererMeshAction::ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context)
{
	FString Error;
	FString SystemPath;
	FString MeshPath;
	GetRequiredString(Params, TEXT("system_path"), SystemPath, Error);
	GetRequiredString(Params, TEXT("mesh_path"), MeshPath, Error);

	UNiagaraSystem* System = LoadNiagaraSystemByPath(SystemPath, Error);
	if (!System)
	{
		return CreateErrorResponse(Error, TEXT("system_not_found"));
	}

	FString EmitterName;
	FVersionedNiagaraEmitter VersionedEmitter;
	FVersionedNiagaraEmitterData* EmitterData = nullptr;
	int32 RendererIndex = INDEX_NONE;
	UNiagaraRendererProperties* Renderer = ResolveRenderer(*System, Params, EmitterName, VersionedEmitter, EmitterData, RendererIndex, Error);
	if (!Renderer)
	{
		return CreateErrorResponse(Error, TEXT("renderer_not_found"));
	}

	UNiagaraMeshRendererProperties* MeshRenderer = Cast<UNiagaraMeshRendererProperties>(Renderer);
	if (!MeshRenderer)
	{
		return CreateErrorResponse(TEXT("Target renderer is not a mesh renderer."), TEXT("invalid_renderer_type"));
	}

	UStaticMesh* Mesh = LoadObject<UStaticMesh>(nullptr, *NormalizeAssetObjectPath(MeshPath));
	if (!Mesh)
	{
		return CreateErrorResponse(FString::Printf(TEXT("Failed to load static mesh '%s'"), *MeshPath), TEXT("mesh_not_found"));
	}

	const int32 MeshSlot = static_cast<int32>(GetOptionalNumber(Params, TEXT("mesh_slot"), 0.0));
	if (MeshSlot < 0)
	{
		return CreateErrorResponse(TEXT("mesh_slot must be >= 0."), TEXT("invalid_mesh_slot"));
	}

	MeshRenderer->Modify();
	MeshRenderer->Meshes.SetNum(FMath::Max(MeshRenderer->Meshes.Num(), MeshSlot + 1));
	FNiagaraMeshRendererMeshProperties& MeshProps = MeshRenderer->Meshes[MeshSlot];
	MeshProps.Mesh = Mesh;

	FVector VectorValue;
	if (ReadVectorParam(Params, TEXT("scale"), VectorValue, Error))
	{
		MeshProps.Scale = VectorValue;
	}
	else if (!Error.IsEmpty())
	{
		return CreateErrorResponse(Error, TEXT("invalid_scale"));
	}

	FRotator RotationValue;
	if (ReadRotatorParam(Params, TEXT("rotation"), RotationValue, Error))
	{
		MeshProps.Rotation = RotationValue;
	}
	else if (!Error.IsEmpty())
	{
		return CreateErrorResponse(Error, TEXT("invalid_rotation"));
	}

	if (ReadVectorParam(Params, TEXT("pivot_offset"), VectorValue, Error))
	{
		MeshProps.PivotOffset = VectorValue;
	}
	else if (!Error.IsEmpty())
	{
		return CreateErrorResponse(Error, TEXT("invalid_pivot_offset"));
	}

	ENiagaraMeshFacingMode FacingMode = MeshRenderer->FacingMode;
	if (TryReadNiagaraMeshFacingModeParam(Params, TEXT("facing_mode"), FacingMode, Error))
	{
		MeshRenderer->FacingMode = FacingMode;
	}
	else if (!Error.IsEmpty())
	{
		return CreateErrorResponse(Error, TEXT("invalid_facing_mode"));
	}

	double RendererVisibilityValue = 0.0;
	if (Params->TryGetNumberField(TEXT("renderer_visibility"), RendererVisibilityValue))
	{
		if (RendererVisibilityValue < 0.0)
		{
			return CreateErrorResponse(TEXT("renderer_visibility must be >= 0."), TEXT("invalid_renderer_visibility"));
		}
		MeshRenderer->RendererVisibility = static_cast<uint32>(FMath::RoundToInt(RendererVisibilityValue));
	}

	bool bLockedAxisEnable = false;
	if (Params->TryGetBoolField(TEXT("locked_axis_enable"), bLockedAxisEnable))
	{
		MeshRenderer->bLockedAxisEnable = bLockedAxisEnable;
	}

	if (ReadVectorParam(Params, TEXT("locked_axis"), VectorValue, Error))
	{
		MeshRenderer->LockedAxis = VectorValue;
	}
	else if (!Error.IsEmpty())
	{
		return CreateErrorResponse(Error, TEXT("invalid_locked_axis"));
	}
	MarkNiagaraRendererEdited(*System, *MeshRenderer, Context);

	TSharedPtr<FJsonObject> Result = MakeShared<FJsonObject>();
	Result->SetStringField(TEXT("system_path"), System->GetPathName());
	Result->SetStringField(TEXT("emitter_name"), EmitterName);
	Result->SetNumberField(TEXT("renderer_index"), RendererIndex);
	Result->SetNumberField(TEXT("mesh_slot"), MeshSlot);
	Result->SetStringField(TEXT("mesh_path"), Mesh->GetPathName());
	Result->SetStringField(TEXT("scale"), MeshProps.Scale.ToString());
	Result->SetStringField(TEXT("facing_mode"), NiagaraMeshFacingModeToString(MeshRenderer->FacingMode));
	Result->SetNumberField(TEXT("renderer_visibility"), static_cast<double>(MeshRenderer->RendererVisibility));
	Result->SetBoolField(TEXT("locked_axis_enable"), MeshRenderer->bLockedAxisEnable != 0);
	return CreateSuccessResponse(Result);
}

// =========================================================================
// FNiagaraSetRendererMaterialAction
// =========================================================================

bool FNiagaraSetRendererMaterialAction::Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError)
{
	FString SystemPath;
	if (!GetRequiredString(Params, TEXT("system_path"), SystemPath, OutError))
	{
		return false;
	}
	FString MaterialPath;
	return GetRequiredString(Params, TEXT("material_path"), MaterialPath, OutError);
}

TSharedPtr<FJsonObject> FNiagaraSetRendererMaterialAction::ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context)
{
	FString Error;
	FString SystemPath;
	FString MaterialPath;
	GetRequiredString(Params, TEXT("system_path"), SystemPath, Error);
	GetRequiredString(Params, TEXT("material_path"), MaterialPath, Error);

	UNiagaraSystem* System = LoadNiagaraSystemByPath(SystemPath, Error);
	if (!System)
	{
		return CreateErrorResponse(Error, TEXT("system_not_found"));
	}

	UMaterialInterface* Material = LoadObject<UMaterialInterface>(nullptr, *NormalizeAssetObjectPath(MaterialPath));
	if (!Material)
	{
		return CreateErrorResponse(FString::Printf(TEXT("Failed to load material '%s'"), *MaterialPath), TEXT("material_not_found"));
	}

	FString EmitterName;
	FVersionedNiagaraEmitter VersionedEmitter;
	FVersionedNiagaraEmitterData* EmitterData = nullptr;
	int32 RendererIndex = INDEX_NONE;
	UNiagaraRendererProperties* Renderer = ResolveRenderer(*System, Params, EmitterName, VersionedEmitter, EmitterData, RendererIndex, Error);
	if (!Renderer)
	{
		return CreateErrorResponse(Error, TEXT("renderer_not_found"));
	}

	const int32 MaterialSlot = static_cast<int32>(GetOptionalNumber(Params, TEXT("material_slot"), 0.0));
	if (MaterialSlot < 0)
	{
		return CreateErrorResponse(TEXT("material_slot must be >= 0."), TEXT("invalid_material_slot"));
	}

	FString RendererType = GetRendererTypeString(Renderer);
	if (UNiagaraSpriteRendererProperties* Sprite = Cast<UNiagaraSpriteRendererProperties>(Renderer))
	{
		Sprite->Modify();
		Sprite->Material = Material;
		MarkNiagaraRendererEdited(*System, *Sprite, Context);
	}
	else if (UNiagaraRibbonRendererProperties* Ribbon = Cast<UNiagaraRibbonRendererProperties>(Renderer))
	{
		Ribbon->Modify();
		Ribbon->Material = Material;
		MarkNiagaraRendererEdited(*System, *Ribbon, Context);
	}
	else if (UNiagaraMeshRendererProperties* Mesh = Cast<UNiagaraMeshRendererProperties>(Renderer))
	{
		Mesh->Modify();
		Mesh->bOverrideMaterials = GetOptionalBool(Params, TEXT("enable_override"), true);
		Mesh->OverrideMaterials.SetNum(FMath::Max(Mesh->OverrideMaterials.Num(), MaterialSlot + 1));
		Mesh->OverrideMaterials[MaterialSlot].ExplicitMat = Material;
		MarkNiagaraRendererEdited(*System, *Mesh, Context);
	}
	else
	{
		return CreateErrorResponse(FString::Printf(TEXT("Renderer type '%s' does not support material assignment."), *RendererType), TEXT("unsupported_renderer_type"));
	}

	TSharedPtr<FJsonObject> Result = MakeShared<FJsonObject>();
	Result->SetStringField(TEXT("system_path"), System->GetPathName());
	Result->SetStringField(TEXT("emitter_name"), EmitterName);
	Result->SetNumberField(TEXT("renderer_index"), RendererIndex);
	Result->SetStringField(TEXT("renderer_type"), RendererType);
	Result->SetNumberField(TEXT("material_slot"), MaterialSlot);
	Result->SetStringField(TEXT("material_path"), Material->GetPathName());
	return CreateSuccessResponse(Result);
}

// =========================================================================
// FNiagaraSetRendererBindingAction
// =========================================================================

bool FNiagaraSetRendererBindingAction::Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError)
{
	FString SystemPath;
	if (!GetRequiredString(Params, TEXT("system_path"), SystemPath, OutError))
	{
		return false;
	}
	FString BindingName;
	if (!GetRequiredString(Params, TEXT("binding_name"), BindingName, OutError))
	{
		return false;
	}
	FString VariableName;
	return GetRequiredString(Params, TEXT("variable_name"), VariableName, OutError);
}

TSharedPtr<FJsonObject> FNiagaraSetRendererBindingAction::ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context)
{
	FString Error;
	FString SystemPath;
	FString BindingName;
	FString VariableName;
	GetRequiredString(Params, TEXT("system_path"), SystemPath, Error);
	GetRequiredString(Params, TEXT("binding_name"), BindingName, Error);
	GetRequiredString(Params, TEXT("variable_name"), VariableName, Error);

	UNiagaraSystem* System = LoadNiagaraSystemByPath(SystemPath, Error);
	if (!System)
	{
		return CreateErrorResponse(Error, TEXT("system_not_found"));
	}

	FString EmitterName;
	FVersionedNiagaraEmitter VersionedEmitter;
	FVersionedNiagaraEmitterData* EmitterData = nullptr;
	int32 RendererIndex = INDEX_NONE;
	UNiagaraRendererProperties* Renderer = ResolveRenderer(*System, Params, EmitterName, VersionedEmitter, EmitterData, RendererIndex, Error);
	if (!Renderer || !VersionedEmitter.Emitter || !EmitterData)
	{
		return CreateErrorResponse(Error, TEXT("renderer_not_found"));
	}

	static const TMap<FString, FName> BindingAliases = {
		{TEXT("position"), TEXT("PositionBinding")},
		{TEXT("color"), TEXT("ColorBinding")},
		{TEXT("velocity"), TEXT("VelocityBinding")},
		{TEXT("scale"), TEXT("ScaleBinding")},
		{TEXT("mesh_orientation"), TEXT("MeshOrientationBinding")},
		{TEXT("renderer_enabled"), TEXT("RendererEnabledBinding")},
		{TEXT("renderer_visibility_tag"), TEXT("RendererVisibilityTagBinding")},
		{TEXT("mesh_index"), TEXT("MeshIndexBinding")},
		{TEXT("normalized_age"), TEXT("NormalizedAgeBinding")},
		{TEXT("camera_offset"), TEXT("CameraOffsetBinding")}
	};

	FName PropertyName(*BindingName);
	if (const FName* AliasProperty = BindingAliases.Find(BindingName.ToLower()))
	{
		PropertyName = *AliasProperty;
	}

	FStructProperty* BindingProperty = CastField<FStructProperty>(Renderer->GetClass()->FindPropertyByName(PropertyName));
	if (!BindingProperty || BindingProperty->Struct != FNiagaraVariableAttributeBinding::StaticStruct())
	{
		return CreateErrorResponse(
			FString::Printf(TEXT("Binding property '%s' was not found or is not FNiagaraVariableAttributeBinding on renderer class '%s'."), *PropertyName.ToString(), *Renderer->GetClass()->GetName()),
			TEXT("binding_not_found"));
	}

	FNiagaraVariableAttributeBinding* Binding = BindingProperty->ContainerPtrToValuePtr<FNiagaraVariableAttributeBinding>(Renderer);
	Renderer->Modify();
	const FVersionedNiagaraEmitterBase VersionedBase(VersionedEmitter.Emitter, EmitterData->Version.VersionGuid);
	Binding->SetValue(FName(*VariableName), VersionedBase, Renderer->GetCurrentSourceMode());
	EmitterData->RebuildRendererBindings(*VersionedEmitter.Emitter);
	MarkNiagaraRendererEdited(*System, *Renderer, Context);

	TSharedPtr<FJsonObject> Result = MakeShared<FJsonObject>();
	Result->SetStringField(TEXT("system_path"), System->GetPathName());
	Result->SetStringField(TEXT("emitter_name"), EmitterName);
	Result->SetNumberField(TEXT("renderer_index"), RendererIndex);
	Result->SetStringField(TEXT("renderer_type"), GetRendererTypeString(Renderer));
	Result->SetStringField(TEXT("binding_name"), PropertyName.ToString());
	Result->SetStringField(TEXT("variable_name"), VariableName);
	Result->SetStringField(TEXT("resolved_dataset_variable"), Binding->GetDataSetBindableVariable().GetName().ToString());
	return CreateSuccessResponse(Result);
}

// =========================================================================
// FNiagaraAddModuleAction
// =========================================================================

bool FNiagaraAddModuleAction::Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError)
{
	FString SystemPath;
	if (!GetRequiredString(Params, TEXT("system_path"), SystemPath, OutError))
	{
		return false;
	}
	FString Stage;
	if (!GetRequiredString(Params, TEXT("stage"), Stage, OutError))
	{
		return false;
	}
	ENiagaraScriptUsage DummyUsage;
	if (!ParseStage(Stage, DummyUsage))
	{
		OutError = FString::Printf(TEXT("Invalid stage '%s'. Use system_spawn|system_update|particle_spawn|particle_update|emitter_spawn|emitter_update."), *Stage);
		return false;
	}
	FString ModuleScriptPath;
	return GetRequiredString(Params, TEXT("module_script_path"), ModuleScriptPath, OutError);
}

TSharedPtr<FJsonObject> FNiagaraAddModuleAction::ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context)
{
	FString Error;
	FString SystemPath;
	FString Stage;
	FString ModuleScriptPath;
	GetRequiredString(Params, TEXT("system_path"), SystemPath, Error);
	GetRequiredString(Params, TEXT("stage"), Stage, Error);
	GetRequiredString(Params, TEXT("module_script_path"), ModuleScriptPath, Error);
	const FString EmitterName = GetOptionalString(Params, TEXT("emitter_name"), TEXT(""));
	const int32 TargetIndex = static_cast<int32>(GetOptionalNumber(Params, TEXT("target_index"), -1.0));

	ENiagaraScriptUsage Usage = ENiagaraScriptUsage::ParticleSpawnScript;
	ParseStage(Stage, Usage);

	FString LoadError;
	UNiagaraSystem* System = LoadNiagaraSystemByPath(SystemPath, LoadError);
	if (!System)
	{
		return CreateErrorResponse(LoadError, TEXT("system_not_found"));
	}

	UNiagaraScript* ModuleScript = LoadNiagaraScriptByPath(ModuleScriptPath, LoadError);
	if (!ModuleScript)
	{
		return CreateErrorResponse(LoadError, TEXT("module_not_found"));
	}
	if (ModuleScript->GetUsage() != ENiagaraScriptUsage::Module)
	{
		return CreateErrorResponse(
			FString::Printf(TEXT("Script '%s' is not a Module (usage=%s)."), *ModuleScriptPath, *UsageToString(ModuleScript->GetUsage())),
			TEXT("invalid_module"));
	}

	FString ResultEmitterName;
	UNiagaraGraph* Graph = nullptr;
	UNiagaraScript* OwnerScript = nullptr;

	if (IsSystemStage(Usage))
	{
		OwnerScript = GetSystemStageScript(*System, Usage);
		Graph = GetScriptGraph(OwnerScript);
	}
	else
	{
		FString ResolveError;
		const FNiagaraEmitterHandle* Handle = ResolveEmitterHandle(*System, EmitterName, ResolveError);
		if (!Handle)
		{
			return CreateErrorResponse(ResolveError, TEXT("emitter_not_found"));
		}
		ResultEmitterName = Handle->GetName().ToString();
		FVersionedNiagaraEmitterData* EmitterData = Handle->GetEmitterData();
		if (!EmitterData)
		{
			return CreateErrorResponse(TEXT("Emitter handle has no valid instance data."), TEXT("invalid_emitter"));
		}

		OwnerScript = GetStageScript(*EmitterData, Usage);
		Graph = GetEmitterGraph(*EmitterData);
	}

	if (!OwnerScript)
	{
		return CreateErrorResponse(FString::Printf(TEXT("No owner script for stage '%s'."), *Stage), TEXT("no_stage_script"));
	}
	if (!Graph)
	{
		return CreateErrorResponse(FString::Printf(TEXT("No editable graph source for stage '%s'."), *Stage), TEXT("no_graph"));
	}
	UNiagaraNodeOutput* OutputNode = FindOutputNodeForUsage(Graph, Usage);
	if (!OutputNode)
	{
		return CreateErrorResponse(
			FString::Printf(TEXT("No output node for stage '%s'."), *Stage),
			TEXT("no_output_node"));
	}

	UNiagaraNodeFunctionCall* ModuleNode = FNiagaraStackGraphUtilities::AddScriptModuleToStack(
		ModuleScript, *OutputNode, TargetIndex);
	if (!ModuleNode)
	{
		return CreateErrorResponse(
			FString::Printf(TEXT("AddScriptModuleToStack failed for '%s'."), *ModuleScriptPath),
			TEXT("add_module_failed"));
	}

	MarkNiagaraSystemEdited(*System, Context);

	// Count modules currently in this stage for diagnostics.
	const int32 ModuleCount = CountModuleNodes(Graph);

	TSharedPtr<FJsonObject> Result = MakeShared<FJsonObject>();
	Result->SetStringField(TEXT("system_path"), System->GetPathName());
	Result->SetStringField(TEXT("emitter_name"), ResultEmitterName);
	Result->SetStringField(TEXT("stage"), Stage.ToLower());
	Result->SetStringField(TEXT("module_node_name"), ModuleNode->GetFunctionName());
	Result->SetNumberField(TEXT("module_count"), ModuleCount);
	return CreateSuccessResponse(Result);
}

// =========================================================================
// FNiagaraRemoveModuleAction
// =========================================================================

bool FNiagaraRemoveModuleAction::Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError)
{
	FString SystemPath;
	if (!GetRequiredString(Params, TEXT("system_path"), SystemPath, OutError))
	{
		return false;
	}
	FString ModuleName;
	if (!GetRequiredString(Params, TEXT("module_name"), ModuleName, OutError))
	{
		return false;
	}
	const FString Stage = GetOptionalString(Params, TEXT("stage"), TEXT(""));
	if (!Stage.IsEmpty())
	{
		ENiagaraScriptUsage DummyUsage;
		if (!ParseStage(Stage, DummyUsage))
		{
			OutError = FString::Printf(TEXT("Invalid stage '%s'. Use system_spawn|system_update|particle_spawn|particle_update|emitter_spawn|emitter_update."), *Stage);
			return false;
		}
	}
	return true;
}

TSharedPtr<FJsonObject> FNiagaraRemoveModuleAction::ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context)
{
	FString Error;
	FString SystemPath;
	FString ModuleName;
	GetRequiredString(Params, TEXT("system_path"), SystemPath, Error);
	GetRequiredString(Params, TEXT("module_name"), ModuleName, Error);
	const FString EmitterName = GetOptionalString(Params, TEXT("emitter_name"), TEXT(""));
	const FString Stage = GetOptionalString(Params, TEXT("stage"), TEXT(""));

	UNiagaraSystem* System = LoadNiagaraSystemByPath(SystemPath, Error);
	if (!System)
	{
		return CreateErrorResponse(Error, TEXT("system_not_found"));
	}

	FString ResultEmitterName;
	UNiagaraGraph* Graph = nullptr;
	UNiagaraScript* OwnerScript = nullptr;
	FVersionedNiagaraEmitterData* EmitterData = nullptr;
	if (!Stage.IsEmpty())
	{
		ENiagaraScriptUsage Usage = ENiagaraScriptUsage::Module;
		ParseStage(Stage, Usage);
		if (IsSystemStage(Usage))
		{
			OwnerScript = GetSystemStageScript(*System, Usage);
			Graph = GetScriptGraph(OwnerScript);
		}
		else
		{
			FString ResolveError;
			const FNiagaraEmitterHandle* Handle = ResolveEmitterHandle(*System, EmitterName, ResolveError);
			if (!Handle)
			{
				return CreateErrorResponse(ResolveError, TEXT("emitter_not_found"));
			}
			ResultEmitterName = Handle->GetName().ToString();
			EmitterData = Handle->GetEmitterData();
			if (!EmitterData)
			{
				return CreateErrorResponse(TEXT("Emitter handle has no valid instance data."), TEXT("invalid_emitter"));
			}
			OwnerScript = GetStageScript(*EmitterData, Usage);
			Graph = GetEmitterGraph(*EmitterData);
		}
	}
	else
	{
		FString ResolveError;
		const FNiagaraEmitterHandle* Handle = ResolveEmitterHandle(*System, EmitterName, ResolveError);
		if (!Handle)
		{
			return CreateErrorResponse(ResolveError, TEXT("emitter_not_found"));
		}
		ResultEmitterName = Handle->GetName().ToString();
		EmitterData = Handle->GetEmitterData();
		if (!EmitterData)
		{
			return CreateErrorResponse(TEXT("Emitter handle has no valid instance data."), TEXT("invalid_emitter"));
		}
		Graph = GetEmitterGraph(*EmitterData);
	}

	if (!Graph)
	{
		return CreateErrorResponse(TEXT("No editable Niagara graph for requested scope."), TEXT("no_graph"));
	}

	FMCPNiagaraStackModuleData ModuleData;
	FString FindError;
	if (!FindUniqueModuleDataByName(Graph, ModuleName, Stage, ModuleData, FindError) || !ModuleData.Node)
	{
		return CreateErrorResponse(FindError, TEXT("module_not_found"));
	}

	if (!OwnerScript)
	{
		OwnerScript = IsSystemStage(ModuleData.Usage)
			? GetSystemStageScript(*System, ModuleData.Usage)
			: (EmitterData ? GetStageScript(*EmitterData, ModuleData.Usage) : nullptr);
	}
	if (!OwnerScript)
	{
		return CreateErrorResponse(TEXT("No owner script for target module stage."), TEXT("no_stage_script"));
	}

	UNiagaraNodeOutput* OutputNode = FindOutputNodeForModuleData(Graph, ModuleData);
	if (!OutputNode)
	{
		return CreateErrorResponse(TEXT("No output node found for target module stage."), TEXT("no_output_node"));
	}

	const FString RemovedModuleName = ModuleData.Node->GetFunctionName();
	const FString RemovedNodeGuid = ModuleData.Node->NodeGuid.ToString(EGuidFormats::DigitsWithHyphens);
	const int32 RemovedModuleIndex = ModuleData.Index;
	const FString RemovedStage = UsageToDisplayString(ModuleData.Usage);

	System->Modify();
	OwnerScript->Modify();
	int32 RemovedNodeCount = 0;
	int32 RemovedInputNodeCount = 0;
	if (!RemoveStackModuleNodeFromGraph(*Graph, *OutputNode, *ModuleData.Node, RemovedNodeCount, RemovedInputNodeCount, Error))
	{
		return CreateErrorResponse(Error.IsEmpty() ? TEXT("Failed to remove module from stack.") : Error, TEXT("remove_module_failed"));
	}

	Graph->NotifyGraphChanged();
	MarkNiagaraSystemEdited(*System, Context);

	TArray<FMCPNiagaraStackModuleData> RemainingModules;
	CollectStackModuleData(Graph, RemainingModules);
	int32 RemainingInStage = 0;
	for (const FMCPNiagaraStackModuleData& RemainingModule : RemainingModules)
	{
		if (RemainingModule.Usage == ModuleData.Usage)
		{
			++RemainingInStage;
		}
	}

	TSharedPtr<FJsonObject> Result = MakeShared<FJsonObject>();
	Result->SetStringField(TEXT("system_path"), System->GetPathName());
	Result->SetStringField(TEXT("emitter_name"), ResultEmitterName);
	Result->SetStringField(TEXT("stage"), RemovedStage);
	Result->SetStringField(TEXT("module_name"), RemovedModuleName);
	Result->SetStringField(TEXT("removed_node_guid"), RemovedNodeGuid);
	Result->SetNumberField(TEXT("module_index"), RemovedModuleIndex);
	Result->SetNumberField(TEXT("removed_node_count"), RemovedNodeCount);
	Result->SetNumberField(TEXT("removed_input_node_count"), RemovedInputNodeCount);
	Result->SetNumberField(TEXT("remaining_modules_in_stage"), RemainingInStage);
	return CreateSuccessResponse(Result);
}

// =========================================================================
// FNiagaraSetModuleInputAction
// =========================================================================

bool FNiagaraSetModuleInputAction::Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError)
{
	FString SystemPath;
	if (!GetRequiredString(Params, TEXT("system_path"), SystemPath, OutError))
	{
		return false;
	}
	FString Stage;
	if (!GetRequiredString(Params, TEXT("stage"), Stage, OutError))
	{
		return false;
	}
	ENiagaraScriptUsage DummyUsage;
	if (!ParseStage(Stage, DummyUsage))
	{
		OutError = FString::Printf(TEXT("Invalid stage '%s'. Use system_spawn|system_update|particle_spawn|particle_update|emitter_spawn|emitter_update."), *Stage);
		return false;
	}
	FString ModuleName;
	if (!GetRequiredString(Params, TEXT("module_name"), ModuleName, OutError))
	{
		return false;
	}
	FString InputName;
	if (!GetRequiredString(Params, TEXT("input_name"), InputName, OutError))
	{
		return false;
	}
	FString ValueType;
	if (!GetRequiredString(Params, TEXT("value_type"), ValueType, OutError))
	{
		return false;
	}
	if (!Params->HasField(TEXT("value")))
	{
		OutError = TEXT("Missing required 'value'.");
		return false;
	}
	return true;
}

TSharedPtr<FJsonObject> FNiagaraSetModuleInputAction::ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context)
{
	FString Error;
	FString SystemPath;
	FString Stage;
	FString ModuleName;
	FString InputName;
	FString ValueType;
	GetRequiredString(Params, TEXT("system_path"), SystemPath, Error);
	GetRequiredString(Params, TEXT("stage"), Stage, Error);
	GetRequiredString(Params, TEXT("module_name"), ModuleName, Error);
	GetRequiredString(Params, TEXT("input_name"), InputName, Error);
	GetRequiredString(Params, TEXT("value_type"), ValueType, Error);
	const FString EmitterName = GetOptionalString(Params, TEXT("emitter_name"), TEXT(""));

	ENiagaraScriptUsage Usage = ENiagaraScriptUsage::ParticleSpawnScript;
	ParseStage(Stage, Usage);

	// Resolve the Niagara type definition + read the typed value from JSON.
	FNiagaraTypeDefinition InputType;
	FNiagaraVariable ValueVar;
	{
		const FString Type = ValueType.ToLower();
		if (Type == TEXT("float"))
		{
			InputType = FNiagaraTypeDefinition::GetFloatDef();
			ValueVar = FNiagaraVariable(InputType, NAME_None);
			ValueVar.SetValue<float>(static_cast<float>(GetOptionalNumber(Params, TEXT("value"), 0.0)));
		}
		else if (Type == TEXT("int"))
		{
			InputType = FNiagaraTypeDefinition::GetIntDef();
			ValueVar = FNiagaraVariable(InputType, NAME_None);
			ValueVar.SetValue<int32>(static_cast<int32>(GetOptionalNumber(Params, TEXT("value"), 0.0)));
		}
		else if (Type == TEXT("bool"))
		{
			InputType = FNiagaraTypeDefinition::GetBoolDef();
			ValueVar = FNiagaraVariable(InputType, NAME_None);
			FNiagaraBool BoolValue;
			BoolValue.SetValue(GetOptionalBool(Params, TEXT("value"), false));
			ValueVar.SetValue<FNiagaraBool>(BoolValue);
		}
		else if (Type == TEXT("ndc_spawn_mode") || Type == TEXT("data_channel_spawn_mode") || Type == TEXT("spawn_mode"))
		{
			UEnum* SpawnModeEnum = FindObject<UEnum>(nullptr, TEXT("/Script/Niagara.ENDIDataChannelSpawnMode"));
			if (!SpawnModeEnum)
			{
				return CreateErrorResponse(TEXT("ENDIDataChannelSpawnMode enum not found."), TEXT("enum_not_found"));
			}
			InputType = FNiagaraTypeDefinition(SpawnModeEnum);
			ValueVar = FNiagaraVariable(InputType, NAME_None);
			FNiagaraInt32 NiagaraValue;
			NiagaraValue.Value = static_cast<int32>(GetOptionalNumber(Params, TEXT("value"), 0.0));
			ValueVar.SetValue<FNiagaraInt32>(NiagaraValue);
		}
		else if (Type == TEXT("vec2") || Type == TEXT("vec3") || Type == TEXT("vec4") || Type == TEXT("color"))
		{
			const TArray<TSharedPtr<FJsonValue>>* Arr = nullptr;
			if (!Params->TryGetArrayField(TEXT("value"), Arr) || !Arr)
			{
				return CreateErrorResponse(
					FString::Printf(TEXT("value for type '%s' must be a numeric array."), *Type),
					TEXT("invalid_value"));
			}
			auto ReadN = [&Arr](int32 Index) -> double
			{
				return Arr->IsValidIndex(Index) ? (*Arr)[Index]->AsNumber() : 0.0;
			};
			if (Type == TEXT("vec2"))
			{
				if (Arr->Num() < 2) { return CreateErrorResponse(TEXT("vec2 needs 2 numbers."), TEXT("invalid_value")); }
				InputType = FNiagaraTypeDefinition::GetVec2Def();
				ValueVar = FNiagaraVariable(InputType, NAME_None);
				ValueVar.SetValue<FVector2f>(FVector2f(static_cast<float>(ReadN(0)), static_cast<float>(ReadN(1))));
			}
			else if (Type == TEXT("vec3"))
			{
				if (Arr->Num() < 3) { return CreateErrorResponse(TEXT("vec3 needs 3 numbers."), TEXT("invalid_value")); }
				InputType = FNiagaraTypeDefinition::GetVec3Def();
				ValueVar = FNiagaraVariable(InputType, NAME_None);
				ValueVar.SetValue<FVector3f>(FVector3f(static_cast<float>(ReadN(0)), static_cast<float>(ReadN(1)), static_cast<float>(ReadN(2))));
			}
			else if (Type == TEXT("vec4"))
			{
				if (Arr->Num() < 4) { return CreateErrorResponse(TEXT("vec4 needs 4 numbers."), TEXT("invalid_value")); }
				InputType = FNiagaraTypeDefinition::GetVec4Def();
				ValueVar = FNiagaraVariable(InputType, NAME_None);
				ValueVar.SetValue<FVector4f>(FVector4f(static_cast<float>(ReadN(0)), static_cast<float>(ReadN(1)), static_cast<float>(ReadN(2)), static_cast<float>(ReadN(3))));
			}
			else // color
			{
				if (Arr->Num() < 4) { return CreateErrorResponse(TEXT("color needs 4 numbers (RGBA)."), TEXT("invalid_value")); }
				InputType = FNiagaraTypeDefinition::GetColorDef();
				ValueVar = FNiagaraVariable(InputType, NAME_None);
				ValueVar.SetValue<FLinearColor>(FLinearColor(static_cast<float>(ReadN(0)), static_cast<float>(ReadN(1)), static_cast<float>(ReadN(2)), static_cast<float>(ReadN(3))));
			}
		}
		else
		{
			return CreateErrorResponse(
				FString::Printf(TEXT("Invalid value_type '%s'. Use float|int|bool|vec2|vec3|vec4|color|ndc_spawn_mode."), *ValueType),
				TEXT("invalid_value_type"));
		}
	}

	FString LoadError;
	UNiagaraSystem* System = LoadNiagaraSystemByPath(SystemPath, LoadError);
	if (!System)
	{
		return CreateErrorResponse(LoadError, TEXT("system_not_found"));
	}

	FString ResultEmitterName;
	FString UniqueEmitterName;
	UNiagaraScript* TargetScript = nullptr;
	UNiagaraGraph* Graph = nullptr;

	if (IsSystemStage(Usage))
	{
		TargetScript = GetSystemStageScript(*System, Usage);
		Graph = GetScriptGraph(TargetScript);
	}
	else
	{
		FString ResolveError;
		const FNiagaraEmitterHandle* Handle = ResolveEmitterHandle(*System, EmitterName, ResolveError);
		if (!Handle)
		{
			return CreateErrorResponse(ResolveError, TEXT("emitter_not_found"));
		}
		ResultEmitterName = Handle->GetName().ToString();
		FVersionedNiagaraEmitter VersionedEmitter = Handle->GetInstance();
		UNiagaraEmitter* Emitter = VersionedEmitter.Emitter;
		FVersionedNiagaraEmitterData* EmitterData = Handle->GetEmitterData();
		if (!Emitter || !EmitterData)
		{
			return CreateErrorResponse(TEXT("Emitter handle has no valid instance data."), TEXT("invalid_emitter"));
		}

		UniqueEmitterName = Emitter->GetUniqueEmitterName();
		TargetScript = GetStageScript(*EmitterData, Usage);
		Graph = GetEmitterGraph(*EmitterData);
	}

	if (!TargetScript)
	{
		return CreateErrorResponse(
			FString::Printf(TEXT("No script for stage '%s'."), *Stage),
			TEXT("no_stage_script"));
	}
	if (!Graph)
	{
		return CreateErrorResponse(FString::Printf(TEXT("No editable graph source for stage '%s'."), *Stage), TEXT("no_graph"));
	}
	UNiagaraNodeOutput* OutputNode = FindOutputNodeForUsage(Graph, Usage);
	if (!OutputNode)
	{
		return CreateErrorResponse(
			FString::Printf(TEXT("No output node for stage '%s'."), *Stage),
			TEXT("no_output_node"));
	}

	// Locate the target module function-call node by its display name.
	UNiagaraNodeFunctionCall* TargetModule = FindModuleNodeByName(Graph, ModuleName);
	if (!TargetModule)
	{
		return CreateErrorResponse(
			FString::Printf(TEXT("No module named '%s' in stage '%s'."), *ModuleName, *Stage),
			TEXT("module_not_found"));
	}

	// Build the aliased rapid-iteration parameter and write its value on the
	// owning stage script (the stable 5.7 SetRapidIterationParameter path).
	FNiagaraParameterHandle ModuleInputHandle = FNiagaraParameterHandle::CreateModuleParameterHandle(FName(*InputName));
	FNiagaraParameterHandle AliasedInputHandle = FNiagaraParameterHandle::CreateAliasedModuleParameterHandle(ModuleInputHandle, TargetModule);
	FNiagaraVariable RapidIterationParameter = MakeRapidIterationParameter(
		UniqueEmitterName, TargetScript->GetUsage(), AliasedInputHandle.GetParameterHandleString(), InputType);

	// Copy the typed value bytes onto the rapid iteration parameter.
	RapidIterationParameter.SetData(ValueVar.GetData());

	TargetScript->Modify();
	TargetScript->RapidIterationParameters.SetParameterData(
		RapidIterationParameter.GetData(), RapidIterationParameter, /*bAddParameterIfMissing*/ true);

	MarkNiagaraSystemEdited(*System, Context);

	TSharedPtr<FJsonObject> Result = MakeShared<FJsonObject>();
	Result->SetStringField(TEXT("system_path"), System->GetPathName());
	Result->SetStringField(TEXT("emitter_name"), ResultEmitterName);
	Result->SetStringField(TEXT("stage"), Stage.ToLower());
	Result->SetStringField(TEXT("module_name"), TargetModule->GetFunctionName());
	Result->SetStringField(TEXT("input_name"), InputName);
	Result->SetStringField(TEXT("value_type"), ValueType.ToLower());
	Result->SetStringField(TEXT("rapid_iteration_parameter"), RapidIterationParameter.GetName().ToString());
	return CreateSuccessResponse(Result);
}

// =========================================================================
// FNiagaraSetEmitterPropertyAction
// =========================================================================

bool FNiagaraSetEmitterPropertyAction::Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError)
{
	FString SystemPath;
	if (!GetRequiredString(Params, TEXT("system_path"), SystemPath, OutError))
	{
		return false;
	}
	FString PropertyName;
	if (!GetRequiredString(Params, TEXT("property_name"), PropertyName, OutError))
	{
		return false;
	}
	if (!Params->HasField(TEXT("property_value")))
	{
		OutError = TEXT("Missing required 'property_value'.");
		return false;
	}
	return true;
}

TSharedPtr<FJsonObject> FNiagaraSetEmitterPropertyAction::ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context)
{
	FString Error;
	FString SystemPath;
	FString PropertyName;
	GetRequiredString(Params, TEXT("system_path"), SystemPath, Error);
	GetRequiredString(Params, TEXT("property_name"), PropertyName, Error);
	const FString EmitterName = GetOptionalString(Params, TEXT("emitter_name"), TEXT(""));
	const FString PropertyValue = JsonValueToImportText(Params->TryGetField(TEXT("property_value")));
	if (PropertyValue.IsEmpty())
	{
		return CreateErrorResponse(TEXT("property_value must be a string, number, or bool import-text value."), TEXT("invalid_value"));
	}

	UNiagaraSystem* System = LoadNiagaraSystemByPath(SystemPath, Error);
	if (!System)
	{
		return CreateErrorResponse(Error, TEXT("system_not_found"));
	}

	FString ResolveError;
	const FNiagaraEmitterHandle* Handle = ResolveEmitterHandle(*System, EmitterName, ResolveError);
	if (!Handle)
	{
		return CreateErrorResponse(ResolveError, TEXT("emitter_not_found"));
	}

	FVersionedNiagaraEmitter VersionedEmitter = Handle->GetInstance();
	UNiagaraEmitter* Emitter = VersionedEmitter.Emitter;
	FVersionedNiagaraEmitterData* EmitterData = Handle->GetEmitterData();
	if (!Emitter || !EmitterData)
	{
		return CreateErrorResponse(TEXT("Emitter handle has no valid instance data."), TEXT("invalid_emitter"));
	}

	UScriptStruct* EmitterDataStruct = FVersionedNiagaraEmitterData::StaticStruct();
	FProperty* Property = EmitterDataStruct ? EmitterDataStruct->FindPropertyByName(FName(*PropertyName)) : nullptr;
	if (!Property)
	{
		return CreateErrorResponse(
			FString::Printf(TEXT("Property '%s' not found on FVersionedNiagaraEmitterData."), *PropertyName),
			TEXT("property_not_found"));
	}

	const FString ValueBefore = ExportStructPropertyAsText(EmitterData, Emitter, Property);
	void* PropertyAddr = Property->ContainerPtrToValuePtr<void>(EmitterData);

	System->Modify();
	Emitter->Modify();
	const TCHAR* ImportResult = Property->ImportText_Direct(*PropertyValue, PropertyAddr, Emitter, PPF_None);
	if (!ImportResult)
	{
		return CreateErrorResponse(
			FString::Printf(TEXT("ImportText failed for emitter property '%s' with value '%s'."), *PropertyName, *PropertyValue),
			TEXT("import_text_failed"));
	}
	FPropertyChangedEvent ChangeEvent(Property, EPropertyChangeType::ValueSet);
	Emitter->PostEditChangeVersionedProperty(ChangeEvent, VersionedEmitter.Version);

	MarkNiagaraSystemEdited(*System, Context);

	TSharedPtr<FJsonObject> Result = MakeShared<FJsonObject>();
	Result->SetStringField(TEXT("system_path"), System->GetPathName());
	Result->SetStringField(TEXT("emitter_name"), Handle->GetName().ToString());
	Result->SetStringField(TEXT("property_name"), Property->GetName());
	Result->SetStringField(TEXT("value_before"), ValueBefore);
	Result->SetStringField(TEXT("value_after"), ExportStructPropertyAsText(EmitterData, Emitter, Property));
	return CreateSuccessResponse(Result);
}

// =========================================================================
// FNiagaraSetModuleStaticIntAction
// =========================================================================

bool FNiagaraSetModuleStaticIntAction::Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError)
{
	FString SystemPath;
	if (!GetRequiredString(Params, TEXT("system_path"), SystemPath, OutError))
	{
		return false;
	}
	FString ModuleName;
	if (!GetRequiredString(Params, TEXT("module_name"), ModuleName, OutError))
	{
		return false;
	}
	FString ParameterName;
	if (!GetRequiredString(Params, TEXT("parameter_name"), ParameterName, OutError))
	{
		return false;
	}
	if (!Params->HasField(TEXT("value")))
	{
		OutError = TEXT("Missing required 'value'.");
		return false;
	}
	const FString Stage = GetOptionalString(Params, TEXT("stage"), TEXT(""));
	if (!Stage.IsEmpty())
	{
		ENiagaraScriptUsage DummyUsage;
		if (!ParseStage(Stage, DummyUsage))
		{
			OutError = FString::Printf(TEXT("Invalid stage '%s'. Use system_spawn|system_update|particle_spawn|particle_update|emitter_spawn|emitter_update."), *Stage);
			return false;
		}
	}
	return true;
}

TSharedPtr<FJsonObject> FNiagaraSetModuleStaticIntAction::ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context)
{
	FString Error;
	FString SystemPath;
	FString ModuleName;
	FString ParameterName;
	GetRequiredString(Params, TEXT("system_path"), SystemPath, Error);
	GetRequiredString(Params, TEXT("module_name"), ModuleName, Error);
	GetRequiredString(Params, TEXT("parameter_name"), ParameterName, Error);
	const FString EmitterName = GetOptionalString(Params, TEXT("emitter_name"), TEXT(""));
	const FString Stage = GetOptionalString(Params, TEXT("stage"), TEXT(""));

	int32 NewValue = 0;

	UNiagaraSystem* System = LoadNiagaraSystemByPath(SystemPath, Error);
	if (!System)
	{
		return CreateErrorResponse(Error, TEXT("system_not_found"));
	}

	FString ResultEmitterName;
	UNiagaraGraph* Graph = nullptr;
	FVersionedNiagaraEmitter VersionedEmitter;
	bool bHasEmitterContext = false;
	if (!EmitterName.IsEmpty())
	{
		FString ResolveError;
		const FNiagaraEmitterHandle* Handle = ResolveEmitterHandle(*System, EmitterName, ResolveError);
		if (!Handle)
		{
			return CreateErrorResponse(ResolveError, TEXT("emitter_not_found"));
		}
		FVersionedNiagaraEmitterData* EmitterData = Handle->GetEmitterData();
		if (!EmitterData)
		{
			return CreateErrorResponse(TEXT("Emitter handle has no valid instance data."), TEXT("invalid_emitter"));
		}
		VersionedEmitter = Handle->GetInstance();
		bHasEmitterContext = true;
		Graph = GetEmitterGraph(*EmitterData);
		ResultEmitterName = Handle->GetName().ToString();
	}
	else if (!Stage.IsEmpty())
	{
		ENiagaraScriptUsage Usage = ENiagaraScriptUsage::Module;
		ParseStage(Stage, Usage);
		if (IsSystemStage(Usage))
		{
			Graph = GetScriptGraph(GetSystemStageScript(*System, Usage));
		}
		else
		{
			FString ResolveError;
			const FNiagaraEmitterHandle* Handle = ResolveEmitterHandle(*System, EmitterName, ResolveError);
			if (!Handle)
			{
				return CreateErrorResponse(ResolveError, TEXT("emitter_not_found"));
			}
			FVersionedNiagaraEmitterData* EmitterData = Handle->GetEmitterData();
			if (!EmitterData)
			{
				return CreateErrorResponse(TEXT("Emitter handle has no valid instance data."), TEXT("invalid_emitter"));
			}
			VersionedEmitter = Handle->GetInstance();
			bHasEmitterContext = true;
			Graph = GetEmitterGraph(*EmitterData);
			ResultEmitterName = Handle->GetName().ToString();
		}
	}
	else
	{
		FString ResolveError;
		const FNiagaraEmitterHandle* Handle = ResolveEmitterHandle(*System, EmitterName, ResolveError);
		if (!Handle)
		{
			return CreateErrorResponse(ResolveError, TEXT("emitter_not_found"));
		}
		FVersionedNiagaraEmitterData* EmitterData = Handle->GetEmitterData();
		if (!EmitterData)
		{
			return CreateErrorResponse(TEXT("Emitter handle has no valid instance data."), TEXT("invalid_emitter"));
		}
		VersionedEmitter = Handle->GetInstance();
		bHasEmitterContext = true;
		Graph = GetEmitterGraph(*EmitterData);
		ResultEmitterName = Handle->GetName().ToString();
	}

	if (!Graph)
	{
		return CreateErrorResponse(TEXT("No editable Niagara graph for requested scope."), TEXT("no_graph"));
	}

	FMCPNiagaraStackModuleData ModuleData;
	FString FindError;
	if (!FindUniqueModuleDataByName(Graph, ModuleName, Stage, ModuleData, FindError) || !ModuleData.Node)
	{
		return CreateErrorResponse(FindError, TEXT("module_not_found"));
	}

	FCompileConstantResolver Resolver = bHasEmitterContext
		? FCompileConstantResolver(VersionedEmitter, ModuleData.Usage)
		: FCompileConstantResolver(System, ModuleData.Usage);
	TSet<UEdGraphPin*> HiddenStaticPins;
	FString AvailableStaticNames;
	UEdGraphPin* StaticSwitchPin = FindStaticSwitchPinByName(*ModuleData.Node, Resolver, ParameterName, HiddenStaticPins, AvailableStaticNames);
	if (!StaticSwitchPin)
	{
		return CreateErrorResponse(
			FString::Printf(TEXT("No static int/enum input named '%s' on module '%s'. Available static inputs: %s"), *ParameterName, *ModuleData.Node->GetFunctionName(), AvailableStaticNames.IsEmpty() ? TEXT("<none>") : *AvailableStaticNames),
			TEXT("static_input_not_found"));
	}

	const UEdGraphSchema_Niagara* NiagaraSchema = GetDefault<UEdGraphSchema_Niagara>();
	const FNiagaraTypeDefinition SwitchType = NiagaraSchema ? NiagaraSchema->PinToTypeDefinition(StaticSwitchPin) : FNiagaraTypeDefinition();
	if (SwitchType != FNiagaraTypeDefinition::GetIntDef() && !SwitchType.IsEnum())
	{
		return CreateErrorResponse(
			FString::Printf(TEXT("Static input '%s' is type '%s', not int or enum."), *StaticSwitchPin->PinName.ToString(), *NiagaraTypeToString(SwitchType)),
			TEXT("invalid_static_input_type"));
	}

	if (!TryReadStaticIndexValue(Params, SwitchType, NewValue, Error))
	{
		return CreateErrorResponse(Error, TEXT("invalid_value"));
	}

	FString NewDefaultValue;
	if (!MakeNiagaraStaticPinDefaultValue(SwitchType, NewValue, NewDefaultValue))
	{
		return CreateErrorResponse(TEXT("Failed to convert int/enum value to Niagara pin default text."), TEXT("pin_default_conversion_failed"));
	}

	const FString ValueBefore = StaticSwitchPin->DefaultValue;
	System->Modify();
	Graph->Modify();
	ModuleData.Node->Modify();
	StaticSwitchPin->Modify();
	StaticSwitchPin->DefaultValue = NewDefaultValue;
	if (UNiagaraNode* OwningNode = Cast<UNiagaraNode>(StaticSwitchPin->GetOwningNode()))
	{
		OwningNode->MarkNodeRequiresSynchronization(TEXT("Static Switch Value Changed"), true);
	}
	Graph->NotifyGraphChanged();
	MarkNiagaraSystemEdited(*System, Context);

	TSharedPtr<FJsonObject> Result = MakeShared<FJsonObject>();
	Result->SetStringField(TEXT("system_path"), System->GetPathName());
	Result->SetStringField(TEXT("emitter_name"), ResultEmitterName);
	Result->SetStringField(TEXT("stage"), UsageToDisplayString(ModuleData.Usage));
	Result->SetStringField(TEXT("module_name"), ModuleData.Node->GetFunctionName());
	Result->SetNumberField(TEXT("module_index"), ModuleData.Index);
	Result->SetStringField(TEXT("parameter_name"), StaticSwitchPin->PinName.ToString());
	Result->SetStringField(TEXT("requested_parameter_name"), ParameterName);
	Result->SetStringField(TEXT("value_before"), ValueBefore);
	Result->SetStringField(TEXT("value_after"), StaticSwitchPin->DefaultValue);
	Result->SetStringField(TEXT("value_type"), SwitchType.IsEnum() ? TEXT("enum") : TEXT("int"));
	Result->SetStringField(TEXT("type_name"), NiagaraTypeToString(SwitchType));
	Result->SetNumberField(TEXT("int_value"), NewValue);
	Result->SetBoolField(TEXT("hidden"), HiddenStaticPins.Contains(StaticSwitchPin));
	return CreateSuccessResponse(Result);
}

// =========================================================================
// FNiagaraSetModuleEnabledAction
// =========================================================================

bool FNiagaraSetModuleEnabledAction::Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError)
{
	FString SystemPath;
	if (!GetRequiredString(Params, TEXT("system_path"), SystemPath, OutError))
	{
		return false;
	}
	FString ModuleName;
	if (!GetRequiredString(Params, TEXT("module_name"), ModuleName, OutError))
	{
		return false;
	}
	if (!Params->HasField(TEXT("enabled")))
	{
		OutError = TEXT("Missing required 'enabled'.");
		return false;
	}
	const FString Stage = GetOptionalString(Params, TEXT("stage"), TEXT(""));
	if (!Stage.IsEmpty())
	{
		ENiagaraScriptUsage DummyUsage;
		if (!ParseStage(Stage, DummyUsage))
		{
			OutError = FString::Printf(TEXT("Invalid stage '%s'. Use system_spawn|system_update|particle_spawn|particle_update|emitter_spawn|emitter_update."), *Stage);
			return false;
		}
	}
	return true;
}

TSharedPtr<FJsonObject> FNiagaraSetModuleEnabledAction::ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context)
{
	FString Error;
	FString SystemPath;
	FString ModuleName;
	GetRequiredString(Params, TEXT("system_path"), SystemPath, Error);
	ModuleName = GetOptionalString(Params, TEXT("module_name"), TEXT(""));
	const FString EmitterName = GetOptionalString(Params, TEXT("emitter_name"), TEXT(""));
	const FString Stage = GetOptionalString(Params, TEXT("stage"), TEXT(""));
	const bool bEnabled = GetOptionalBool(Params, TEXT("enabled"), true);

	UNiagaraSystem* System = LoadNiagaraSystemByPath(SystemPath, Error);
	if (!System)
	{
		return CreateErrorResponse(Error, TEXT("system_not_found"));
	}

	FString ResultEmitterName;
	UNiagaraGraph* Graph = nullptr;
	if (!EmitterName.IsEmpty())
	{
		FString ResolveError;
		const FNiagaraEmitterHandle* Handle = ResolveEmitterHandle(*System, EmitterName, ResolveError);
		if (!Handle)
		{
			return CreateErrorResponse(ResolveError, TEXT("emitter_not_found"));
		}
		FVersionedNiagaraEmitterData* EmitterData = Handle->GetEmitterData();
		if (!EmitterData)
		{
			return CreateErrorResponse(TEXT("Emitter handle has no valid instance data."), TEXT("invalid_emitter"));
		}
		Graph = GetEmitterGraph(*EmitterData);
		ResultEmitterName = Handle->GetName().ToString();
	}
	else if (!Stage.IsEmpty())
	{
		ENiagaraScriptUsage Usage = ENiagaraScriptUsage::Module;
		ParseStage(Stage, Usage);
		if (IsSystemStage(Usage))
		{
			Graph = GetScriptGraph(GetSystemStageScript(*System, Usage));
		}
		else
		{
			FString ResolveError;
			const FNiagaraEmitterHandle* Handle = ResolveEmitterHandle(*System, EmitterName, ResolveError);
			if (!Handle)
			{
				return CreateErrorResponse(ResolveError, TEXT("emitter_not_found"));
			}
			FVersionedNiagaraEmitterData* EmitterData = Handle->GetEmitterData();
			if (!EmitterData)
			{
				return CreateErrorResponse(TEXT("Emitter handle has no valid instance data."), TEXT("invalid_emitter"));
			}
			Graph = GetEmitterGraph(*EmitterData);
			ResultEmitterName = Handle->GetName().ToString();
		}
	}
	else
	{
		FString ResolveError;
		const FNiagaraEmitterHandle* Handle = ResolveEmitterHandle(*System, EmitterName, ResolveError);
		if (!Handle)
		{
			return CreateErrorResponse(ResolveError, TEXT("emitter_not_found"));
		}
		FVersionedNiagaraEmitterData* EmitterData = Handle->GetEmitterData();
		if (!EmitterData)
		{
			return CreateErrorResponse(TEXT("Emitter handle has no valid instance data."), TEXT("invalid_emitter"));
		}
		Graph = GetEmitterGraph(*EmitterData);
		ResultEmitterName = Handle->GetName().ToString();
	}

	if (!Graph)
	{
		return CreateErrorResponse(TEXT("No editable Niagara graph for requested scope."), TEXT("no_graph"));
	}

	FMCPNiagaraStackModuleData ModuleData;
	FString FindError;
	if (!FindUniqueModuleDataByName(Graph, ModuleName, Stage, ModuleData, FindError) || !ModuleData.Node)
	{
		return CreateErrorResponse(FindError, TEXT("module_not_found"));
	}

	const ENodeEnabledState PreviousState = ModuleData.Node->GetDesiredEnabledState();
	const ENodeEnabledState NewState = bEnabled ? ENodeEnabledState::Enabled : ENodeEnabledState::Disabled;
	System->Modify();
	Graph->Modify();
	ModuleData.Node->Modify();
	ModuleData.Node->SetEnabledState(NewState);
	Graph->NotifyGraphChanged();
	MarkNiagaraSystemEdited(*System, Context);

	TSharedPtr<FJsonObject> Result = MakeShared<FJsonObject>();
	Result->SetStringField(TEXT("system_path"), System->GetPathName());
	Result->SetStringField(TEXT("emitter_name"), ResultEmitterName);
	Result->SetStringField(TEXT("stage"), UsageToDisplayString(ModuleData.Usage));
	Result->SetStringField(TEXT("module_name"), ModuleData.Node->GetFunctionName());
	Result->SetNumberField(TEXT("module_index"), ModuleData.Index);
	Result->SetStringField(TEXT("previous_state"), NodeEnabledStateToString(PreviousState));
	Result->SetStringField(TEXT("new_state"), NodeEnabledStateToString(NewState));
	Result->SetBoolField(TEXT("enabled"), bEnabled);
	return CreateSuccessResponse(Result);
}

// =========================================================================
// FNiagaraGetModuleInputsAction
// =========================================================================

bool FNiagaraGetModuleInputsAction::Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError)
{
	FString SystemPath;
	if (!GetRequiredString(Params, TEXT("system_path"), SystemPath, OutError))
	{
		return false;
	}
	const FString Stage = GetOptionalString(Params, TEXT("stage"), TEXT(""));
	if (!Stage.IsEmpty())
	{
		ENiagaraScriptUsage DummyUsage;
		if (!ParseStage(Stage, DummyUsage))
		{
			OutError = FString::Printf(TEXT("Invalid stage '%s'. Use system_spawn|system_update|particle_spawn|particle_update|emitter_spawn|emitter_update."), *Stage);
			return false;
		}
	}
	return true;
}

TSharedPtr<FJsonObject> FNiagaraGetModuleInputsAction::ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context)
{
	FString Error;
	FString SystemPath;
	FString ModuleName;
	GetRequiredString(Params, TEXT("system_path"), SystemPath, Error);
	ModuleName = GetOptionalString(Params, TEXT("module_name"), TEXT(""));
	const FString EmitterName = GetOptionalString(Params, TEXT("emitter_name"), TEXT(""));
	const FString Stage = GetOptionalString(Params, TEXT("stage"), TEXT(""));
	const FString InputNameFilter = GetOptionalString(Params, TEXT("input_name"), TEXT(""));
	const bool bIncludeHidden = GetOptionalBool(Params, TEXT("include_hidden"), true);
	const bool bIncludeInternalGraph = GetOptionalBool(Params, TEXT("include_internal_graph"), false);

	UNiagaraSystem* System = LoadNiagaraSystemByPath(SystemPath, Error);
	if (!System)
	{
		return CreateErrorResponse(Error, TEXT("system_not_found"));
	}

	FString ResultEmitterName;
	UNiagaraGraph* Graph = nullptr;
	FVersionedNiagaraEmitter VersionedEmitter;
	bool bHasEmitterContext = false;
	if (!EmitterName.IsEmpty())
	{
		FString ResolveError;
		const FNiagaraEmitterHandle* Handle = ResolveEmitterHandle(*System, EmitterName, ResolveError);
		if (!Handle)
		{
			return CreateErrorResponse(ResolveError, TEXT("emitter_not_found"));
		}
		FVersionedNiagaraEmitterData* EmitterData = Handle->GetEmitterData();
		if (!EmitterData)
		{
			return CreateErrorResponse(TEXT("Emitter handle has no valid instance data."), TEXT("invalid_emitter"));
		}
		VersionedEmitter = Handle->GetInstance();
		bHasEmitterContext = true;
		Graph = GetEmitterGraph(*EmitterData);
		ResultEmitterName = Handle->GetName().ToString();
	}
	else if (!Stage.IsEmpty())
	{
		ENiagaraScriptUsage Usage = ENiagaraScriptUsage::Module;
		ParseStage(Stage, Usage);
		if (IsSystemStage(Usage))
		{
			Graph = GetScriptGraph(GetSystemStageScript(*System, Usage));
		}
		else
		{
			FString ResolveError;
			const FNiagaraEmitterHandle* Handle = ResolveEmitterHandle(*System, EmitterName, ResolveError);
			if (!Handle)
			{
				return CreateErrorResponse(ResolveError, TEXT("emitter_not_found"));
			}
			FVersionedNiagaraEmitterData* EmitterData = Handle->GetEmitterData();
			if (!EmitterData)
			{
				return CreateErrorResponse(TEXT("Emitter handle has no valid instance data."), TEXT("invalid_emitter"));
			}
			VersionedEmitter = Handle->GetInstance();
			bHasEmitterContext = true;
			Graph = GetEmitterGraph(*EmitterData);
			ResultEmitterName = Handle->GetName().ToString();
		}
	}
	else
	{
		FString ResolveError;
		const FNiagaraEmitterHandle* Handle = ResolveEmitterHandle(*System, EmitterName, ResolveError);
		if (!Handle)
		{
			return CreateErrorResponse(ResolveError, TEXT("emitter_not_found"));
		}
		FVersionedNiagaraEmitterData* EmitterData = Handle->GetEmitterData();
		if (!EmitterData)
		{
			return CreateErrorResponse(TEXT("Emitter handle has no valid instance data."), TEXT("invalid_emitter"));
		}
		VersionedEmitter = Handle->GetInstance();
		bHasEmitterContext = true;
		Graph = GetEmitterGraph(*EmitterData);
		ResultEmitterName = Handle->GetName().ToString();
	}

	if (!Graph)
	{
		return CreateErrorResponse(TEXT("No editable Niagara graph for requested scope."), TEXT("no_graph"));
	}

	if (ModuleName.IsEmpty())
	{
		ENiagaraScriptUsage RequiredUsage = ENiagaraScriptUsage::Module;
		const bool bFilterByStage = !Stage.IsEmpty() && ParseStage(Stage, RequiredUsage);
		TArray<FMCPNiagaraStackModuleData> ModuleDataList;
		CollectStackModuleData(Graph, ModuleDataList);

		TArray<TSharedPtr<FJsonValue>> ModuleArray;
		for (const FMCPNiagaraStackModuleData& Candidate : ModuleDataList)
		{
			if (!Candidate.Node || (bFilterByStage && Candidate.Usage != RequiredUsage))
			{
				continue;
			}
			TSharedPtr<FJsonObject> ModuleObj = MakeShared<FJsonObject>();
			ModuleObj->SetStringField(TEXT("module_name"), Candidate.Node->GetFunctionName());
			ModuleObj->SetStringField(TEXT("stage"), UsageToDisplayString(Candidate.Usage));
			ModuleObj->SetStringField(TEXT("script_usage"), UsageToString(Candidate.Usage));
			ModuleObj->SetNumberField(TEXT("module_index"), Candidate.Index);
			ModuleObj->SetStringField(TEXT("node_guid"), Candidate.Node->NodeGuid.ToString(EGuidFormats::DigitsWithHyphens));
			ModuleObj->SetStringField(TEXT("script_path"), Candidate.Node->FunctionScript ? Candidate.Node->FunctionScript->GetPathName() : FString());
			ModuleArray.Add(MakeShared<FJsonValueObject>(ModuleObj));
		}

		TSharedPtr<FJsonObject> Result = MakeShared<FJsonObject>();
		Result->SetStringField(TEXT("system_path"), System->GetPathName());
		Result->SetStringField(TEXT("emitter_name"), ResultEmitterName);
		Result->SetStringField(TEXT("stage_filter"), Stage);
		Result->SetNumberField(TEXT("module_count"), ModuleArray.Num());
		Result->SetArrayField(TEXT("modules"), ModuleArray);
		return CreateSuccessResponse(Result);
	}

	FMCPNiagaraStackModuleData ModuleData;
	FString FindError;
	if (!FindUniqueModuleDataByName(Graph, ModuleName, Stage, ModuleData, FindError) || !ModuleData.Node)
	{
		return CreateErrorResponse(FindError, TEXT("module_not_found"));
	}

	FCompileConstantResolver Resolver = bHasEmitterContext
		? FCompileConstantResolver(VersionedEmitter, ModuleData.Usage)
		: FCompileConstantResolver(System, ModuleData.Usage);
	TArray<FNiagaraVariable> InputVariables;
	TSet<FNiagaraVariable> HiddenVariables;
	FNiagaraStackGraphUtilities::GetStackFunctionInputs(
		*ModuleData.Node,
		InputVariables,
		HiddenVariables,
		Resolver,
		FNiagaraStackGraphUtilities::ENiagaraGetStackFunctionInputPinsOptions::ModuleInputsOnly,
		false);

	UNiagaraScript* OwnerScript = nullptr;
	FString UniqueEmitterName;
	if (IsSystemStage(ModuleData.Usage))
	{
		OwnerScript = GetSystemStageScript(*System, ModuleData.Usage);
	}
	else if (bHasEmitterContext)
	{
		if (UNiagaraEmitter* Emitter = VersionedEmitter.Emitter)
		{
			UniqueEmitterName = Emitter->GetUniqueEmitterName();
		}
		if (FVersionedNiagaraEmitterData* EmitterData = VersionedEmitter.GetEmitterData())
		{
			OwnerScript = GetStageScript(*EmitterData, ModuleData.Usage);
		}
	}

	TArray<TSharedPtr<FJsonValue>> InputArray;
	for (const FNiagaraVariable& InputVariable : InputVariables)
	{
		const bool bHidden = HiddenVariables.Contains(InputVariable);
		if (bHidden && !bIncludeHidden)
		{
			continue;
		}
		if (!DoesInputNameMatch(InputVariable, ModuleData.Node->GetFunctionName(), InputNameFilter))
		{
			continue;
		}
		InputArray.Add(MakeShared<FJsonValueObject>(MakeModuleInputBindingJson(
			*ModuleData.Node, InputVariable, bHidden, OwnerScript, UniqueEmitterName, ModuleData.Usage)));
	}

	TSharedPtr<FJsonObject> Result = MakeShared<FJsonObject>();
	Result->SetStringField(TEXT("system_path"), System->GetPathName());
	Result->SetStringField(TEXT("emitter_name"), ResultEmitterName);
	Result->SetStringField(TEXT("stage"), UsageToDisplayString(ModuleData.Usage));
	Result->SetStringField(TEXT("module_name"), ModuleData.Node->GetFunctionName());
	Result->SetNumberField(TEXT("module_index"), ModuleData.Index);
	Result->SetStringField(TEXT("input_filter"), InputNameFilter);
	Result->SetNumberField(TEXT("input_count"), InputArray.Num());
	Result->SetArrayField(TEXT("inputs"), InputArray);
	if (bIncludeInternalGraph)
	{
		Result->SetObjectField(TEXT("internal_graph"), MakeScratchModuleInternalGraphDebugJson(ModuleData.Node));
	}
	return CreateSuccessResponse(Result);
}

// =========================================================================
// FNiagaraSetModuleInputBindingAction
// =========================================================================

bool FNiagaraSetModuleInputBindingAction::Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError)
{
	FString SystemPath;
	if (!GetRequiredString(Params, TEXT("system_path"), SystemPath, OutError))
	{
		return false;
	}
	FString ModuleName;
	if (!GetRequiredString(Params, TEXT("module_name"), ModuleName, OutError))
	{
		return false;
	}
	FString InputName;
	if (!GetRequiredString(Params, TEXT("input_name"), InputName, OutError))
	{
		return false;
	}
	FString BindingMode;
	if (!GetRequiredString(Params, TEXT("binding_mode"), BindingMode, OutError))
	{
		return false;
	}
	if (!(BindingMode.Equals(TEXT("linked_parameter"), ESearchCase::IgnoreCase) || BindingMode.Equals(TEXT("dynamic_input"), ESearchCase::IgnoreCase) || BindingMode.Equals(TEXT("custom_hlsl"), ESearchCase::IgnoreCase) || BindingMode.Equals(TEXT("assignment_custom_hlsl"), ESearchCase::IgnoreCase) || BindingMode.Equals(TEXT("assignment_dynamic_input"), ESearchCase::IgnoreCase)))
	{
		OutError = FString::Printf(TEXT("Invalid binding_mode '%s'. Use linked_parameter, dynamic_input, custom_hlsl, assignment_custom_hlsl, or assignment_dynamic_input."), *BindingMode);
		return false;
	}
	if (BindingMode.Equals(TEXT("linked_parameter"), ESearchCase::IgnoreCase))
	{
		FString LinkedParameter;
		if (!GetRequiredString(Params, TEXT("linked_parameter"), LinkedParameter, OutError))
		{
			return false;
		}
	}
	else if (BindingMode.Equals(TEXT("dynamic_input"), ESearchCase::IgnoreCase) || BindingMode.Equals(TEXT("assignment_dynamic_input"), ESearchCase::IgnoreCase))
	{
		FString DynamicInputScriptPath;
		if (!GetRequiredString(Params, TEXT("dynamic_input_script_path"), DynamicInputScriptPath, OutError))
		{
			return false;
		}
	}
	else
	{
		FString CustomHlsl;
		if (!GetRequiredString(Params, TEXT("custom_hlsl"), CustomHlsl, OutError))
		{
			return false;
		}
		if (CustomHlsl.TrimStartAndEnd().IsEmpty())
		{
			OutError = TEXT("custom_hlsl must not be empty.");
			return false;
		}
	}
	const FString Stage = GetOptionalString(Params, TEXT("stage"), TEXT(""));
	if (!Stage.IsEmpty())
	{
		ENiagaraScriptUsage DummyUsage;
		if (!ParseStage(Stage, DummyUsage))
		{
			OutError = FString::Printf(TEXT("Invalid stage '%s'. Use system_spawn|system_update|particle_spawn|particle_update|emitter_spawn|emitter_update."), *Stage);
			return false;
		}
	}
	return true;
}

TSharedPtr<FJsonObject> FNiagaraSetModuleInputBindingAction::ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context)
{
	FString Error;
	FString SystemPath;
	FString ModuleName;
	FString InputName;
	FString BindingMode;
	GetRequiredString(Params, TEXT("system_path"), SystemPath, Error);
	GetRequiredString(Params, TEXT("module_name"), ModuleName, Error);
	GetRequiredString(Params, TEXT("input_name"), InputName, Error);
	GetRequiredString(Params, TEXT("binding_mode"), BindingMode, Error);
	const FString EmitterName = GetOptionalString(Params, TEXT("emitter_name"), TEXT(""));
	const FString Stage = GetOptionalString(Params, TEXT("stage"), TEXT(""));
	const bool bReplaceExisting = GetOptionalBool(Params, TEXT("replace_existing"), false);

	UNiagaraSystem* System = LoadNiagaraSystemByPath(SystemPath, Error);
	if (!System)
	{
		return CreateErrorResponse(Error, TEXT("system_not_found"));
	}

	FString ResultEmitterName;
	UNiagaraGraph* Graph = nullptr;
	FVersionedNiagaraEmitter VersionedEmitter;
	bool bHasEmitterContext = false;
	if (!EmitterName.IsEmpty())
	{
		FString ResolveError;
		const FNiagaraEmitterHandle* Handle = ResolveEmitterHandle(*System, EmitterName, ResolveError);
		if (!Handle)
		{
			return CreateErrorResponse(ResolveError, TEXT("emitter_not_found"));
		}
		FVersionedNiagaraEmitterData* EmitterData = Handle->GetEmitterData();
		if (!EmitterData)
		{
			return CreateErrorResponse(TEXT("Emitter handle has no valid instance data."), TEXT("invalid_emitter"));
		}
		VersionedEmitter = Handle->GetInstance();
		bHasEmitterContext = true;
		Graph = GetEmitterGraph(*EmitterData);
		ResultEmitterName = Handle->GetName().ToString();
	}
	else if (!Stage.IsEmpty())
	{
		ENiagaraScriptUsage Usage = ENiagaraScriptUsage::Module;
		ParseStage(Stage, Usage);
		if (IsSystemStage(Usage))
		{
			Graph = GetScriptGraph(GetSystemStageScript(*System, Usage));
		}
		else
		{
			FString ResolveError;
			const FNiagaraEmitterHandle* Handle = ResolveEmitterHandle(*System, EmitterName, ResolveError);
			if (!Handle)
			{
				return CreateErrorResponse(ResolveError, TEXT("emitter_not_found"));
			}
			FVersionedNiagaraEmitterData* EmitterData = Handle->GetEmitterData();
			if (!EmitterData)
			{
				return CreateErrorResponse(TEXT("Emitter handle has no valid instance data."), TEXT("invalid_emitter"));
			}
			VersionedEmitter = Handle->GetInstance();
			bHasEmitterContext = true;
			Graph = GetEmitterGraph(*EmitterData);
			ResultEmitterName = Handle->GetName().ToString();
		}
	}
	else
	{
		FString ResolveError;
		const FNiagaraEmitterHandle* Handle = ResolveEmitterHandle(*System, EmitterName, ResolveError);
		if (!Handle)
		{
			return CreateErrorResponse(ResolveError, TEXT("emitter_not_found"));
		}
		FVersionedNiagaraEmitterData* EmitterData = Handle->GetEmitterData();
		if (!EmitterData)
		{
			return CreateErrorResponse(TEXT("Emitter handle has no valid instance data."), TEXT("invalid_emitter"));
		}
		VersionedEmitter = Handle->GetInstance();
		bHasEmitterContext = true;
		Graph = GetEmitterGraph(*EmitterData);
		ResultEmitterName = Handle->GetName().ToString();
	}

	if (!Graph)
	{
		return CreateErrorResponse(TEXT("No editable Niagara graph for requested scope."), TEXT("no_graph"));
	}

	if (BindingMode.Equals(TEXT("assignment_custom_hlsl"), ESearchCase::IgnoreCase) || BindingMode.Equals(TEXT("assignment_dynamic_input"), ESearchCase::IgnoreCase))
	{
		const FString AssignmentStage = Stage.IsEmpty() ? TEXT("particle_spawn") : Stage;
		ENiagaraScriptUsage AssignmentUsage = ENiagaraScriptUsage::ParticleSpawnScript;
		if (!ParseStage(AssignmentStage, AssignmentUsage))
		{
			return CreateErrorResponse(
				FString::Printf(TEXT("Invalid stage '%s'. Use particle_spawn or particle_update for particle attributes."), *AssignmentStage),
				TEXT("invalid_stage"));
		}
		if (IsSystemStage(AssignmentUsage))
		{
			return CreateErrorResponse(TEXT("assignment_custom_hlsl writes particle attributes and requires an emitter particle stage."), TEXT("invalid_stage"));
		}
		UNiagaraNodeOutput* OutputNode = FindOutputNodeForUsage(Graph, AssignmentUsage);
		if (!OutputNode)
		{
			return CreateErrorResponse(
				FString::Printf(TEXT("No output node for stage '%s'."), *AssignmentStage),
				TEXT("no_output_node"));
		}

		FNiagaraTypeDefinition TargetType = FNiagaraTypeDefinition::GetIntDef();
		const FString TargetValueType = GetOptionalString(Params, TEXT("target_value_type"), TEXT("int"));
		if (!TargetValueType.IsEmpty() && !ParseNiagaraValueType(TargetValueType, TargetType))
		{
			return CreateErrorResponse(
				FString::Printf(TEXT("Invalid target_value_type '%s'. Use float|int|bool|vec2|vec3|position|vec4|quat|color."), *TargetValueType),
				TEXT("invalid_value_type"));
		}

		const FString TargetParameterName = GetOptionalString(Params, TEXT("target_parameter"), InputName);
		FNiagaraVariable TargetVariable(TargetType, FName(*TargetParameterName));
		FCompileConstantResolver Resolver = bHasEmitterContext
			? FCompileConstantResolver(VersionedEmitter, AssignmentUsage)
			: FCompileConstantResolver(System, AssignmentUsage);

		UNiagaraNodeFunctionCall* AssignmentNode = nullptr;
		bool bCreatedAssignment = false;
		int32 AssignmentIndex = INDEX_NONE;
		TArray<FNiagaraVariable> InputVariables;
		TSet<FNiagaraVariable> HiddenVariables;

		TArray<FMCPNiagaraStackModuleData> ModuleDataList;
		CollectStackModuleData(Graph, ModuleDataList);
		int32 RequestedAssignmentIndex = static_cast<int32>(GetOptionalNumber(Params, TEXT("target_index"), -1.0));
		const FString InsertBeforeModule = GetOptionalString(Params, TEXT("insert_before_module"), TEXT(""));
		if (!InsertBeforeModule.IsEmpty())
		{
			bool bFoundInsertBeforeModule = false;
			for (const FMCPNiagaraStackModuleData& CandidateModule : ModuleDataList)
			{
				if (CandidateModule.Node
					&& CandidateModule.Usage == AssignmentUsage
					&& CandidateModule.Node->GetFunctionName().Equals(InsertBeforeModule, ESearchCase::IgnoreCase))
				{
					RequestedAssignmentIndex = CandidateModule.Index;
					bFoundInsertBeforeModule = true;
					break;
				}
			}
			if (!bFoundInsertBeforeModule)
			{
				return CreateErrorResponse(
					FString::Printf(TEXT("No module named '%s' in stage '%s' for insert_before_module."), *InsertBeforeModule, *AssignmentStage),
					TEXT("insert_before_module_not_found"));
			}
		}
		for (const FMCPNiagaraStackModuleData& CandidateModule : ModuleDataList)
		{
			if (!CandidateModule.Node || CandidateModule.Usage != AssignmentUsage)
			{
				continue;
			}

			TArray<FNiagaraVariable> CandidateInputs;
			TSet<FNiagaraVariable> CandidateHiddenInputs;
			FNiagaraStackGraphUtilities::GetStackFunctionInputs(
				*CandidateModule.Node,
				CandidateInputs,
				CandidateHiddenInputs,
				Resolver,
				FNiagaraStackGraphUtilities::ENiagaraGetStackFunctionInputPinsOptions::AllInputs,
				false);
			if (CandidateInputs.ContainsByPredicate([CandidateModule, &TargetParameterName](const FNiagaraVariable& CandidateInput)
			{
				return CandidateInput.GetName().ToString().Equals(TargetParameterName, ESearchCase::IgnoreCase)
					|| DoesInputNameMatch(CandidateInput, CandidateModule.Node->GetFunctionName(), TargetParameterName);
			}))
			{
				AssignmentNode = CandidateModule.Node;
				AssignmentIndex = CandidateModule.Index;
				InputVariables = MoveTemp(CandidateInputs);
				HiddenVariables = MoveTemp(CandidateHiddenInputs);
				break;
			}
		}

		if (!AssignmentNode)
		{
			TArray<FNiagaraVariable> ParameterVariables;
			ParameterVariables.Add(TargetVariable);
			TArray<FString> DefaultValues;
			DefaultValues.Add(TEXT("0"));
			AssignmentNode = FNiagaraStackGraphUtilities::AddParameterModuleToStack(ParameterVariables, *OutputNode, RequestedAssignmentIndex, DefaultValues);
			if (!AssignmentNode)
			{
				return CreateErrorResponse(
					Error.IsEmpty()
						? FString::Printf(TEXT("Failed to add Set Variables assignment module for '%s'."), *TargetVariable.GetName().ToString())
						: Error,
					TEXT("assignment_module_failed"));
			}

			bCreatedAssignment = true;

			FNiagaraStackGraphUtilities::GetStackFunctionInputs(
				*AssignmentNode,
				InputVariables,
				HiddenVariables,
				Resolver,
				FNiagaraStackGraphUtilities::ENiagaraGetStackFunctionInputPinsOptions::AllInputs,
				false);

			TArray<FMCPNiagaraStackModuleData> RefreshedModuleDataList;
			CollectStackModuleData(Graph, RefreshedModuleDataList);
			for (const FMCPNiagaraStackModuleData& CandidateModule : RefreshedModuleDataList)
			{
				if (CandidateModule.Node == AssignmentNode)
				{
					AssignmentIndex = CandidateModule.Index;
					break;
				}
			}
		}
		FNiagaraVariable* MatchingInput = InputVariables.FindByPredicate([AssignmentNode, &TargetParameterName](const FNiagaraVariable& Candidate)
		{
			return Candidate.GetName().ToString().Equals(TargetParameterName, ESearchCase::IgnoreCase)
				|| DoesInputNameMatch(Candidate, AssignmentNode->GetFunctionName(), TargetParameterName);
		});
		if (!MatchingInput)
		{
			TArray<FString> AvailableInputs;
			for (const FNiagaraVariable& Candidate : InputVariables)
			{
				AvailableInputs.Add(Candidate.GetName().ToString());
			}
			return CreateErrorResponse(
				FString::Printf(TEXT("No assignment input named '%s'. Available inputs: %s"), *TargetParameterName, *FString::Join(AvailableInputs, TEXT(", "))),
				TEXT("input_not_found"));
		}

		const FString ResolvedInputName = GetInputNameForModule(*MatchingInput, AssignmentNode->GetFunctionName());
		const FNiagaraParameterHandle AliasedInputHandle = MakeAliasedInputHandle(*AssignmentNode, ResolvedInputName);
		UEdGraphPin& OverridePin = FNiagaraStackGraphUtilities::GetOrCreateStackFunctionInputOverridePin(
			*AssignmentNode,
			AliasedInputHandle,
			MatchingInput->GetType(),
			FGuid(),
			FGuid());

		if (OverridePin.LinkedTo.Num() > 0)
		{
			if (!bReplaceExisting)
			{
				return CreateErrorResponse(
					FString::Printf(TEXT("Assignment input '%s' already has an override binding; pass replace_existing=true to relink."), *ResolvedInputName),
					TEXT("input_already_bound"));
			}
			OverridePin.Modify();
			RemoveLinkedOverrideValueNodeLocal(OverridePin);
		}

		System->Modify();
		Graph->Modify();
		AssignmentNode->Modify();

		FString CustomHlsl;
		FString DynamicInputScriptPath;
		FString DynamicInputNodeName;
		FString DynamicInputNodeGuid;
		FString CustomHlslNodeGuid;
		if (BindingMode.Equals(TEXT("assignment_dynamic_input"), ESearchCase::IgnoreCase))
		{
			GetRequiredString(Params, TEXT("dynamic_input_script_path"), DynamicInputScriptPath, Error);
			UNiagaraScript* DynamicInputScript = LoadNiagaraScriptByPath(DynamicInputScriptPath, Error);
			if (!DynamicInputScript)
			{
				return CreateErrorResponse(Error, TEXT("dynamic_input_not_found"));
			}
			if (DynamicInputScript->GetUsage() != ENiagaraScriptUsage::DynamicInput)
			{
				return CreateErrorResponse(
					FString::Printf(TEXT("Script '%s' is not a DynamicInput (usage=%s)."), *DynamicInputScriptPath, *UsageToString(DynamicInputScript->GetUsage())),
					TEXT("invalid_dynamic_input"));
			}

			UNiagaraNodeFunctionCall* DynamicInputNode = nullptr;
			const FString SuggestedName = GetOptionalString(Params, TEXT("suggested_name"), TEXT(""));
			FNiagaraStackGraphUtilities::SetDynamicInputForFunctionInput(OverridePin, DynamicInputScript, DynamicInputNode, FGuid(), SuggestedName);
			DynamicInputNodeName = DynamicInputNode ? DynamicInputNode->GetFunctionName() : FString();
			DynamicInputNodeGuid = DynamicInputNode ? DynamicInputNode->NodeGuid.ToString(EGuidFormats::DigitsWithHyphens) : FString();
		}
		else
		{
			GetRequiredString(Params, TEXT("custom_hlsl"), CustomHlsl, Error);
			UNiagaraNodeCustomHlsl* CustomHlslNode = CreateCustomHlslDynamicInputForOverride(OverridePin, CustomHlsl, Error);
			if (!CustomHlslNode)
			{
				return CreateErrorResponse(Error.IsEmpty() ? TEXT("Failed to create Custom HLSL dynamic input node.") : Error, TEXT("custom_hlsl_node_failed"));
			}
			CustomHlslNodeGuid = CustomHlslNode->NodeGuid.ToString(EGuidFormats::DigitsWithHyphens);
		}

		Graph->NotifyGraphChanged();
		MarkNiagaraSystemEdited(*System, Context);

		TSharedPtr<FJsonObject> Result = MakeShared<FJsonObject>();
		Result->SetStringField(TEXT("system_path"), System->GetPathName());
		Result->SetStringField(TEXT("emitter_name"), ResultEmitterName);
		Result->SetStringField(TEXT("stage"), UsageToDisplayString(AssignmentUsage));
		Result->SetStringField(TEXT("module_name"), AssignmentNode->GetFunctionName());
		Result->SetStringField(TEXT("input_name"), ResolvedInputName);
		Result->SetStringField(TEXT("target_parameter"), TargetParameterName);
		Result->SetStringField(TEXT("target_type"), NiagaraTypeToString(TargetType));
		Result->SetStringField(TEXT("binding_mode"), BindingMode.ToLower());
		Result->SetBoolField(TEXT("created_assignment_module"), bCreatedAssignment);
		Result->SetNumberField(TEXT("module_index"), AssignmentIndex);
		Result->SetNumberField(TEXT("requested_module_index"), RequestedAssignmentIndex);
		Result->SetStringField(TEXT("insert_before_module"), InsertBeforeModule);
		Result->SetStringField(TEXT("custom_hlsl"), CustomHlsl);
		Result->SetStringField(TEXT("custom_hlsl_node_guid"), CustomHlslNodeGuid);
		Result->SetStringField(TEXT("dynamic_input_script"), DynamicInputScriptPath);
		Result->SetStringField(TEXT("dynamic_input_node"), DynamicInputNodeName);
		Result->SetStringField(TEXT("dynamic_input_node_guid"), DynamicInputNodeGuid);
		Result->SetObjectField(TEXT("binding_after"), MakeModuleInputBindingJson(*AssignmentNode, *MatchingInput, HiddenVariables.Contains(*MatchingInput)));
		return CreateSuccessResponse(Result);
	}
	if (ModuleName.IsEmpty())
	{
		ENiagaraScriptUsage RequiredUsage = ENiagaraScriptUsage::Module;
		const bool bFilterByStage = !Stage.IsEmpty() && ParseStage(Stage, RequiredUsage);
		TArray<FMCPNiagaraStackModuleData> ModuleDataList;
		CollectStackModuleData(Graph, ModuleDataList);

		TArray<TSharedPtr<FJsonValue>> ModuleArray;
		for (const FMCPNiagaraStackModuleData& Candidate : ModuleDataList)
		{
			if (!Candidate.Node || (bFilterByStage && Candidate.Usage != RequiredUsage))
			{
				continue;
			}
			TSharedPtr<FJsonObject> ModuleObj = MakeShared<FJsonObject>();
			ModuleObj->SetStringField(TEXT("module_name"), Candidate.Node->GetFunctionName());
			ModuleObj->SetStringField(TEXT("stage"), UsageToDisplayString(Candidate.Usage));
			ModuleObj->SetStringField(TEXT("script_usage"), UsageToString(Candidate.Usage));
			ModuleObj->SetNumberField(TEXT("module_index"), Candidate.Index);
			ModuleObj->SetStringField(TEXT("node_guid"), Candidate.Node->NodeGuid.ToString(EGuidFormats::DigitsWithHyphens));
			ModuleObj->SetStringField(TEXT("script_path"), Candidate.Node->FunctionScript ? Candidate.Node->FunctionScript->GetPathName() : FString());
			ModuleArray.Add(MakeShared<FJsonValueObject>(ModuleObj));
		}

		TSharedPtr<FJsonObject> Result = MakeShared<FJsonObject>();
		Result->SetStringField(TEXT("system_path"), System->GetPathName());
		Result->SetStringField(TEXT("emitter_name"), ResultEmitterName);
		Result->SetStringField(TEXT("stage_filter"), Stage);
		Result->SetNumberField(TEXT("module_count"), ModuleArray.Num());
		Result->SetArrayField(TEXT("modules"), ModuleArray);
		return CreateSuccessResponse(Result);
	}

	FMCPNiagaraStackModuleData ModuleData;
	FString FindError;
	if (!FindUniqueModuleDataByName(Graph, ModuleName, Stage, ModuleData, FindError) || !ModuleData.Node)
	{
		return CreateErrorResponse(FindError, TEXT("module_not_found"));
	}

	FCompileConstantResolver Resolver = bHasEmitterContext
		? FCompileConstantResolver(VersionedEmitter, ModuleData.Usage)
		: FCompileConstantResolver(System, ModuleData.Usage);
	TArray<FNiagaraVariable> InputVariables;
	TSet<FNiagaraVariable> HiddenVariables;
	FNiagaraStackGraphUtilities::GetStackFunctionInputs(
		*ModuleData.Node,
		InputVariables,
		HiddenVariables,
		Resolver,
		FNiagaraStackGraphUtilities::ENiagaraGetStackFunctionInputPinsOptions::ModuleInputsOnly,
		false);

	FNiagaraVariable* MatchingInput = InputVariables.FindByPredicate([&ModuleData, &InputName](const FNiagaraVariable& Candidate)
	{
		return DoesInputNameMatch(Candidate, ModuleData.Node->GetFunctionName(), InputName);
	});
	if (!MatchingInput)
	{
		return CreateErrorResponse(
			FString::Printf(TEXT("No input named '%s' on module '%s'."), *InputName, *ModuleData.Node->GetFunctionName()),
			TEXT("input_not_found"));
	}

	const FString ResolvedInputName = GetInputNameForModule(*MatchingInput, ModuleData.Node->GetFunctionName());
	const FNiagaraParameterHandle AliasedInputHandle = MakeAliasedInputHandle(*ModuleData.Node, ResolvedInputName);
	UEdGraphPin& OverridePin = FNiagaraStackGraphUtilities::GetOrCreateStackFunctionInputOverridePin(
		*ModuleData.Node,
		AliasedInputHandle,
		MatchingInput->GetType(),
		FGuid(),
		FGuid());

	if (OverridePin.LinkedTo.Num() > 0)
	{
		if (!bReplaceExisting)
		{
			return CreateErrorResponse(
				FString::Printf(TEXT("Input '%s' already has an override binding; pass replace_existing=true to relink."), *ResolvedInputName),
				TEXT("input_already_bound"));
		}
		OverridePin.Modify();
		RemoveLinkedOverrideValueNodeLocal(OverridePin);
	}

	System->Modify();
	Graph->Modify();
	ModuleData.Node->Modify();

	TSharedPtr<FJsonObject> Result = MakeShared<FJsonObject>();
	Result->SetStringField(TEXT("system_path"), System->GetPathName());
	Result->SetStringField(TEXT("emitter_name"), ResultEmitterName);
	Result->SetStringField(TEXT("stage"), UsageToDisplayString(ModuleData.Usage));
	Result->SetStringField(TEXT("module_name"), ModuleData.Node->GetFunctionName());
	Result->SetStringField(TEXT("input_name"), ResolvedInputName);
	Result->SetStringField(TEXT("binding_mode"), BindingMode.ToLower());

	if (BindingMode.Equals(TEXT("linked_parameter"), ESearchCase::IgnoreCase))
	{
		FString LinkedParameterName;
		GetRequiredString(Params, TEXT("linked_parameter"), LinkedParameterName, Error);

		FNiagaraTypeDefinition LinkedType = MatchingInput->GetType();
		const FString LinkedValueType = GetOptionalString(Params, TEXT("linked_value_type"), TEXT(""));
		if (!LinkedValueType.IsEmpty() && !ParseNiagaraValueType(LinkedValueType, LinkedType))
		{
			return CreateErrorResponse(
				FString::Printf(TEXT("Invalid linked_value_type '%s'. Use float|int|bool|vec2|vec3|position|vec4|quat|color."), *LinkedValueType),
				TEXT("invalid_value_type"));
		}

		const FNiagaraVariableBase LinkedParameter(LinkedType, FName(*LinkedParameterName));
		const TSet<FNiagaraVariableBase> KnownParameters;
		FNiagaraStackGraphUtilities::SetLinkedParameterValueForFunctionInput(OverridePin, LinkedParameter, KnownParameters);
		Result->SetStringField(TEXT("linked_parameter"), LinkedParameterName);
		Result->SetStringField(TEXT("linked_type"), NiagaraTypeToString(LinkedType));
	}
	else if (BindingMode.Equals(TEXT("dynamic_input"), ESearchCase::IgnoreCase))
	{
		FString DynamicInputScriptPath;
		GetRequiredString(Params, TEXT("dynamic_input_script_path"), DynamicInputScriptPath, Error);
		UNiagaraScript* DynamicInputScript = LoadNiagaraScriptByPath(DynamicInputScriptPath, Error);
		if (!DynamicInputScript)
		{
			return CreateErrorResponse(Error, TEXT("dynamic_input_not_found"));
		}
		if (DynamicInputScript->GetUsage() != ENiagaraScriptUsage::DynamicInput)
		{
			return CreateErrorResponse(
				FString::Printf(TEXT("Script '%s' is not a DynamicInput (usage=%s)."), *DynamicInputScriptPath, *UsageToString(DynamicInputScript->GetUsage())),
				TEXT("invalid_dynamic_input"));
		}

		UNiagaraNodeFunctionCall* DynamicInputNode = nullptr;
		const FString SuggestedName = GetOptionalString(Params, TEXT("suggested_name"), TEXT(""));
		FNiagaraStackGraphUtilities::SetDynamicInputForFunctionInput(OverridePin, DynamicInputScript, DynamicInputNode, FGuid(), SuggestedName);
		Result->SetStringField(TEXT("dynamic_input_script"), DynamicInputScript->GetPathName());
		Result->SetStringField(TEXT("dynamic_input_node"), DynamicInputNode ? DynamicInputNode->GetFunctionName() : FString());
		Result->SetStringField(TEXT("dynamic_input_node_guid"), DynamicInputNode ? DynamicInputNode->NodeGuid.ToString(EGuidFormats::DigitsWithHyphens) : FString());
	}

	else
	{
		FString CustomHlsl;
		GetRequiredString(Params, TEXT("custom_hlsl"), CustomHlsl, Error);
		UNiagaraNodeCustomHlsl* CustomHlslNode = CreateCustomHlslDynamicInputForOverride(OverridePin, CustomHlsl, Error);
		if (!CustomHlslNode)
		{
			return CreateErrorResponse(Error.IsEmpty() ? TEXT("Failed to create Custom HLSL dynamic input node.") : Error, TEXT("custom_hlsl_node_failed"));
		}
		Result->SetStringField(TEXT("custom_hlsl"), CustomHlsl);
		Result->SetStringField(TEXT("custom_hlsl_node_guid"), CustomHlslNode->NodeGuid.ToString(EGuidFormats::DigitsWithHyphens));
	}

	Graph->NotifyGraphChanged();
	MarkNiagaraSystemEdited(*System, Context);
	Result->SetObjectField(TEXT("binding_after"), MakeModuleInputBindingJson(*ModuleData.Node, *MatchingInput, HiddenVariables.Contains(*MatchingInput)));
	return CreateSuccessResponse(Result);
}


// =========================================================================
// FNiagaraSetModuleFloatCurveAction
// =========================================================================

bool FNiagaraSetModuleFloatCurveAction::Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError)
{
	FString SystemPath;
	if (!GetRequiredString(Params, TEXT("system_path"), SystemPath, OutError))
	{
		return false;
	}
	FString ModuleName;
	if (!GetRequiredString(Params, TEXT("module_name"), ModuleName, OutError))
	{
		return false;
	}
	FString InputName;
	if (!GetRequiredString(Params, TEXT("input_name"), InputName, OutError))
	{
		return false;
	}

	TArray<FNiagaraFloatCurveKeySpec> CurveKeys;
	if (!TryReadFloatCurveKeys(Params, CurveKeys, OutError))
	{
		return false;
	}

	const FString Stage = GetOptionalString(Params, TEXT("stage"), TEXT(""));
	if (!Stage.IsEmpty())
	{
		ENiagaraScriptUsage DummyUsage;
		if (!ParseStage(Stage, DummyUsage))
		{
			OutError = FString::Printf(TEXT("Invalid stage '%s'. Use system_spawn|system_update|particle_spawn|particle_update|emitter_spawn|emitter_update."), *Stage);
			return false;
		}
	}
	return true;
}

TSharedPtr<FJsonObject> FNiagaraSetModuleFloatCurveAction::ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context)
{
	FString Error;
	FString SystemPath;
	FString ModuleName;
	FString InputName;
	GetRequiredString(Params, TEXT("system_path"), SystemPath, Error);
	GetRequiredString(Params, TEXT("module_name"), ModuleName, Error);
	GetRequiredString(Params, TEXT("input_name"), InputName, Error);
	const FString EmitterName = GetOptionalString(Params, TEXT("emitter_name"), TEXT(""));
	const FString Stage = GetOptionalString(Params, TEXT("stage"), TEXT(""));
	const FString FloatCurveScript = GetOptionalString(Params, TEXT("float_curve_script"), TEXT("FloatFromCurve"));
	const FString CurveInputName = GetOptionalString(Params, TEXT("curve_input_name"), TEXT("Curve"));
	const bool bReplaceExisting = GetOptionalBool(Params, TEXT("replace_existing"), true);

	TArray<FNiagaraFloatCurveKeySpec> CurveKeys;
	if (!TryReadFloatCurveKeys(Params, CurveKeys, Error))
	{
		return CreateErrorResponse(Error, TEXT("invalid_curve_keys"));
	}

	UNiagaraSystem* System = LoadNiagaraSystemByPath(SystemPath, Error);
	if (!System)
	{
		return CreateErrorResponse(Error, TEXT("system_not_found"));
	}

	FString ResultEmitterName;
	UNiagaraGraph* Graph = nullptr;
	FVersionedNiagaraEmitter VersionedEmitter;
	bool bHasEmitterContext = false;
	if (!EmitterName.IsEmpty())
	{
		FString ResolveError;
		const FNiagaraEmitterHandle* Handle = ResolveEmitterHandle(*System, EmitterName, ResolveError);
		if (!Handle)
		{
			return CreateErrorResponse(ResolveError, TEXT("emitter_not_found"));
		}
		FVersionedNiagaraEmitterData* EmitterData = Handle->GetEmitterData();
		if (!EmitterData)
		{
			return CreateErrorResponse(TEXT("Emitter handle has no valid instance data."), TEXT("invalid_emitter"));
		}
		VersionedEmitter = Handle->GetInstance();
		bHasEmitterContext = true;
		Graph = GetEmitterGraph(*EmitterData);
		ResultEmitterName = Handle->GetName().ToString();
	}
	else if (!Stage.IsEmpty())
	{
		ENiagaraScriptUsage Usage = ENiagaraScriptUsage::Module;
		ParseStage(Stage, Usage);
		if (IsSystemStage(Usage))
		{
			Graph = GetScriptGraph(GetSystemStageScript(*System, Usage));
		}
	}

	if (!Graph)
	{
		return CreateErrorResponse(TEXT("No editable Niagara graph for requested scope. Pass emitter_name for emitter modules."), TEXT("no_graph"));
	}

	FMCPNiagaraStackModuleData ModuleData;
	FString FindError;
	if (!FindUniqueModuleDataByName(Graph, ModuleName, Stage, ModuleData, FindError) || !ModuleData.Node)
	{
		return CreateErrorResponse(FindError, TEXT("module_not_found"));
	}

	FCompileConstantResolver Resolver = bHasEmitterContext
		? FCompileConstantResolver(VersionedEmitter, ModuleData.Usage)
		: FCompileConstantResolver(System, ModuleData.Usage);
	TArray<FNiagaraVariable> InputVariables;
	TSet<FNiagaraVariable> HiddenVariables;
	FNiagaraStackGraphUtilities::GetStackFunctionInputs(
		*ModuleData.Node,
		InputVariables,
		HiddenVariables,
		Resolver,
		FNiagaraStackGraphUtilities::ENiagaraGetStackFunctionInputPinsOptions::ModuleInputsOnly,
		false);

	FNiagaraVariable* MatchingInput = InputVariables.FindByPredicate([&ModuleData, &InputName](const FNiagaraVariable& Candidate)
	{
		return DoesInputNameMatch(Candidate, ModuleData.Node->GetFunctionName(), InputName);
	});
	if (!MatchingInput)
	{
		return CreateErrorResponse(
			FString::Printf(TEXT("No input named '%s' on module '%s'."), *InputName, *ModuleData.Node->GetFunctionName()),
			TEXT("input_not_found"));
	}

	const FString ResolvedInputName = GetInputNameForModule(*MatchingInput, ModuleData.Node->GetFunctionName());
	UEdGraphPin* InputOverridePin = GetStackFunctionInputOverridePinLocal(*ModuleData.Node, ResolvedInputName);
	if (!InputOverridePin || InputOverridePin->LinkedTo.Num() == 0)
	{
		return CreateErrorResponse(
			FString::Printf(TEXT("Input '%s' is not linked to a dynamic input chain."), *ResolvedInputName),
			TEXT("input_not_dynamic"));
	}

	TSet<UEdGraphNode*> VisitedNodes;
	UNiagaraNodeFunctionCall* FloatCurveNode = FindLinkedDynamicInputNodeRecursive(InputOverridePin, FloatCurveScript, VisitedNodes);
	UNiagaraDataInterfaceCurve* CurveDataInterface = nullptr;
	FString ResolvedCurveInputName;
	FString CurveResolutionMode = TEXT("dynamic_input");
	int32 GraphCurveMatchCount = 0;

	System->Modify();
	Graph->Modify();
	ModuleData.Node->Modify();

	if (FloatCurveNode)
	{
		TArray<FNiagaraVariable> CurveInputVariables;
		TSet<FNiagaraVariable> CurveHiddenVariables;
		FNiagaraStackGraphUtilities::GetStackFunctionInputs(
			*FloatCurveNode,
			CurveInputVariables,
			CurveHiddenVariables,
			Resolver,
			FNiagaraStackGraphUtilities::ENiagaraGetStackFunctionInputPinsOptions::ModuleInputsOnly,
			false);

		FNiagaraVariable* MatchingCurveInput = CurveInputVariables.FindByPredicate([FloatCurveNode, &CurveInputName](const FNiagaraVariable& Candidate)
		{
			return DoesInputNameMatch(Candidate, FloatCurveNode->GetFunctionName(), CurveInputName);
		});
		if (!MatchingCurveInput)
		{
			const FString ExplicitGraphCurveInputName = GetOptionalString(Params, TEXT("graph_curve_input_name"), TEXT(""));
			TArray<FString> CurveNeedles;
			if (!ExplicitGraphCurveInputName.IsEmpty())
			{
				CurveNeedles.Add(ExplicitGraphCurveInputName);
			}
			else
			{
				CurveNeedles.Add(ResolvedInputName);
				CurveNeedles.Add(InputName);
			}

			CurveDataInterface = FindGraphFloatCurveDataInterfaceByName(*Graph, CurveNeedles, ResolvedCurveInputName, GraphCurveMatchCount);
			if (CurveDataInterface)
			{
				CurveResolutionMode = TEXT("graph_curve_input_name");
			}
			else
			{
				return CreateErrorResponse(
					FString::Printf(TEXT("Float curve dynamic input '%s' has no input named '%s' and no unique graph curve matched '%s'."), *FloatCurveNode->GetFunctionName(), *CurveInputName, *ResolvedInputName),
					TEXT("curve_input_not_found"));
			}
		}
		else
		{
			ResolvedCurveInputName = GetInputNameForModule(*MatchingCurveInput, FloatCurveNode->GetFunctionName());
			const FNiagaraParameterHandle AliasedCurveInputHandle = MakeAliasedInputHandle(*FloatCurveNode, ResolvedCurveInputName);

			FloatCurveNode->Modify();
			UEdGraphPin& CurveOverridePin = FNiagaraStackGraphUtilities::GetOrCreateStackFunctionInputOverridePin(
				*FloatCurveNode,
				AliasedCurveInputHandle,
				MatchingCurveInput->GetType(),
				FGuid(),
				FGuid());
			CurveDataInterface = GetOrCreateLinkedFloatCurveDataInterface(
				CurveOverridePin,
				AliasedCurveInputHandle.GetParameterHandleString().ToString(),
				bReplaceExisting);
		}
	}
	else
	{
		TSet<UEdGraphNode*> CurveVisitedNodes;
		CurveDataInterface = FindLinkedFloatCurveDataInterfaceRecursive(InputOverridePin, CurveVisitedNodes);
		CurveResolutionMode = TEXT("linked_data_interface");
		if (!CurveDataInterface)
		{
			const FString ExplicitGraphCurveInputName = GetOptionalString(Params, TEXT("graph_curve_input_name"), TEXT(""));
			TArray<FString> CurveNeedles;
			if (!ExplicitGraphCurveInputName.IsEmpty())
			{
				CurveNeedles.Add(ExplicitGraphCurveInputName);
			}
			else
			{
				CurveNeedles.Add(ResolvedInputName);
				CurveNeedles.Add(InputName);
			}

			CurveDataInterface = FindGraphFloatCurveDataInterfaceByName(*Graph, CurveNeedles, ResolvedCurveInputName, GraphCurveMatchCount);
			if (CurveDataInterface)
			{
				CurveResolutionMode = TEXT("graph_curve_input_name");
			}
		}
	}

	if (!CurveDataInterface)
	{
		if (Params->HasTypedField<EJson::Boolean>(TEXT("debug_trace")) && Params->GetBoolField(TEXT("debug_trace")))
		{
			TArray<TSharedPtr<FJsonValue>> LinkedTrace;
			TSet<UEdGraphNode*> TraceVisitedNodes;
			AppendLinkedPinTraceRecursive(InputOverridePin, LinkedTrace, TraceVisitedNodes);

			TArray<TSharedPtr<FJsonValue>> GraphCurveInputs;
			AppendGraphFloatCurveInputs(*Graph, GraphCurveInputs);

			TSharedPtr<FJsonObject> DebugResult = MakeShared<FJsonObject>();
			DebugResult->SetBoolField(TEXT("success"), false);
			DebugResult->SetStringField(TEXT("error"), FString::Printf(TEXT("Could not find or create a FloatFromCurve data interface under '%s.%s'."), *ModuleData.Node->GetFunctionName(), *ResolvedInputName));
			DebugResult->SetStringField(TEXT("error_type"), TEXT("curve_data_interface_not_found"));
			DebugResult->SetStringField(TEXT("module_name"), ModuleData.Node->GetFunctionName());
			DebugResult->SetStringField(TEXT("input_name"), ResolvedInputName);
			DebugResult->SetBoolField(TEXT("found_float_curve_node"), FloatCurveNode != nullptr);
			DebugResult->SetArrayField(TEXT("linked_trace"), LinkedTrace);
			DebugResult->SetArrayField(TEXT("graph_float_curve_inputs"), GraphCurveInputs);
			return DebugResult;
		}
		return CreateErrorResponse(
			FString::Printf(TEXT("Could not find or create a FloatFromCurve data interface under '%s.%s'."), *ModuleData.Node->GetFunctionName(), *ResolvedInputName),
			TEXT("curve_data_interface_not_found"));
	}

	const FString InterpModeString = GetOptionalString(Params, TEXT("interpolation"), TEXT("linear"));
	ERichCurveInterpMode InterpMode = RCIM_Linear;
	if (InterpModeString.Equals(TEXT("constant"), ESearchCase::IgnoreCase))
	{
		InterpMode = RCIM_Constant;
	}
	else if (InterpModeString.Equals(TEXT("cubic"), ESearchCase::IgnoreCase))
	{
		InterpMode = RCIM_Cubic;
	}

	CurveDataInterface->Modify();
	CurveDataInterface->Curve.Reset();
	TArray<TSharedPtr<FJsonValue>> KeyArray;
	for (const FNiagaraFloatCurveKeySpec& KeySpec : CurveKeys)
	{
		FKeyHandle KeyHandle = CurveDataInterface->Curve.AddKey(KeySpec.Time, KeySpec.Value);
		CurveDataInterface->Curve.SetKeyInterpMode(KeyHandle, InterpMode);

		TSharedPtr<FJsonObject> KeyObject = MakeShared<FJsonObject>();
		KeyObject->SetNumberField(TEXT("time"), KeySpec.Time);
		KeyObject->SetNumberField(TEXT("value"), KeySpec.Value);
		KeyArray.Add(MakeShared<FJsonValueObject>(KeyObject));
	}
	if (InterpMode == RCIM_Cubic)
	{
		CurveDataInterface->Curve.AutoSetTangents();
	}
	CurveDataInterface->UpdateTimeRanges();

	Graph->NotifyGraphChanged();
	MarkNiagaraSystemEdited(*System, Context);

	TSharedPtr<FJsonObject> Result = MakeShared<FJsonObject>();
	Result->SetStringField(TEXT("system_path"), System->GetPathName());
	Result->SetStringField(TEXT("emitter_name"), ResultEmitterName);
	Result->SetStringField(TEXT("stage"), UsageToDisplayString(ModuleData.Usage));
	Result->SetStringField(TEXT("module_name"), ModuleData.Node->GetFunctionName());
	Result->SetStringField(TEXT("input_name"), ResolvedInputName);
	Result->SetStringField(TEXT("curve_resolution_mode"), CurveResolutionMode);
	Result->SetStringField(TEXT("float_curve_node"), FloatCurveNode ? FloatCurveNode->GetFunctionName() : FString());
	Result->SetStringField(TEXT("float_curve_script"), FloatCurveNode && FloatCurveNode->FunctionScript ? FloatCurveNode->FunctionScript->GetPathName() : FString());
	Result->SetStringField(TEXT("curve_input_name"), ResolvedCurveInputName);
	Result->SetNumberField(TEXT("graph_curve_match_count"), GraphCurveMatchCount);
	Result->SetStringField(TEXT("interpolation"), InterpModeString.ToLower());
	Result->SetArrayField(TEXT("keys"), KeyArray);
	Result->SetObjectField(TEXT("binding_after"), MakeModuleInputBindingJson(*ModuleData.Node, *MatchingInput, HiddenVariables.Contains(*MatchingInput)));
	return CreateSuccessResponse(Result);
}
// =========================================================================
// Generic Niagara Data Channel helpers/actions
// =========================================================================
namespace
{
	FString NormalizePackagePathFromAssetPath(const FString& InPath)
	{
		const FString ObjectPath = NormalizeAssetObjectPath(InPath);
		FString PackagePath = ObjectPath;
		int32 DotIndex = INDEX_NONE;
		if (PackagePath.FindChar(TEXT('.'), DotIndex))
		{
			PackagePath.LeftInline(DotIndex);
		}
		return PackagePath;
	}

	TSharedPtr<FJsonObject> MakeDataChannelVariableJson(const FNiagaraDataChannelVariable& Variable)
	{
		TSharedPtr<FJsonObject> Obj = MakeShared<FJsonObject>();
		Obj->SetStringField(TEXT("name"), Variable.GetName().ToString());
		Obj->SetStringField(TEXT("type"), NiagaraTypeToString(Variable.GetType()));
		return Obj;
	}

	void AddDataChannelVariable(TArray<FNiagaraDataChannelVariable>& Variables, const FName Name, const FNiagaraTypeDefinition& Type)
	{
		FNiagaraDataChannelVariable Variable;
		Variable.SetName(Name);
		Variable.SetType(FNiagaraDataChannelVariable::ToDataChannelType(Type));
#if WITH_EDITORONLY_DATA
		Variable.Version = FGuid::NewGuid();
#endif
		Variables.Add(Variable);
	}

	bool SetObjectPropertyValue(UObject* Object, const UClass* PropertyOwnerClass, const TCHAR* PropertyName, UObject* Value, FString& OutError)
	{
		if (!Object || !PropertyOwnerClass)
		{
			OutError = TEXT("Invalid object or property owner class.");
			return false;
		}

		FObjectProperty* Property = FindFProperty<FObjectProperty>(PropertyOwnerClass, FName(PropertyName));
		if (!Property)
		{
			OutError = FString::Printf(TEXT("Object property '%s' not found on %s."), PropertyName, *PropertyOwnerClass->GetName());
			return false;
		}

		Property->SetObjectPropertyValue_InContainer(Object, Value);
		return true;
	}

	bool SetVectorPropertyValue(UObject* Object, const UClass* PropertyOwnerClass, const TCHAR* PropertyName, const FVector& Value, FString& OutError)
	{
		if (!Object || !PropertyOwnerClass)
		{
			OutError = TEXT("Invalid object or property owner class.");
			return false;
		}

		FStructProperty* Property = FindFProperty<FStructProperty>(PropertyOwnerClass, FName(PropertyName));
		if (!Property || Property->Struct != TBaseStructure<FVector>::Get())
		{
			OutError = FString::Printf(TEXT("FVector property '%s' not found on %s."), PropertyName, *PropertyOwnerClass->GetName());
			return false;
		}

		*Property->ContainerPtrToValuePtr<FVector>(Object) = Value;
		return true;
	}

	FProperty* GetDataChannelVariablesProperty(FString& OutError)
	{
		FProperty* VariablesProperty = FindFProperty<FProperty>(UNiagaraDataChannel::StaticClass(), TEXT("ChannelVariables"));
		if (!VariablesProperty)
		{
			OutError = TEXT("UNiagaraDataChannel.ChannelVariables property was not found.");
		}
		return VariablesProperty;
	}

	bool BeginDataChannelSchemaEdit(UNiagaraDataChannel* Channel, FString& OutError)
	{
		if (!Channel)
		{
			OutError = TEXT("Data channel is null.");
			return false;
		}

		FProperty* VariablesProperty = GetDataChannelVariablesProperty(OutError);
		if (!VariablesProperty)
		{
			return false;
		}

		Channel->PreEditChange(VariablesProperty);
		return true;
	}

	bool FinishDataChannelSchemaEdit(UNiagaraDataChannel* Channel, FString& OutError)
	{
		if (!Channel)
		{
			OutError = TEXT("Data channel is null.");
			return false;
		}

		FProperty* VariablesProperty = GetDataChannelVariablesProperty(OutError);
		if (!VariablesProperty)
		{
			return false;
		}

		FPropertyChangedEvent ChangedEvent(VariablesProperty, EPropertyChangeType::ValueSet);
		Channel->PostEditChangeProperty(ChangedEvent);
		if (!Channel->IsValid())
		{
			OutError = FString::Printf(TEXT("Niagara Data Channel layout refresh failed for %d variables."), Channel->GetVariables().Num());
			return false;
		}
		return true;
	}
	bool ConfigureDataChannelVariablesFromJson(UNiagaraDataChannel* Channel, const TArray<TSharedPtr<FJsonValue>>& VariableValues, FString& OutError)
	{
		if (!Channel)
		{
			OutError = TEXT("Data channel is null.");
			return false;
		}

		FArrayProperty* VariablesProperty = FindFProperty<FArrayProperty>(UNiagaraDataChannel::StaticClass(), TEXT("ChannelVariables"));
		if (!VariablesProperty)
		{
			OutError = TEXT("UNiagaraDataChannel.ChannelVariables property was not found.");
			return false;
		}

		TArray<FNiagaraDataChannelVariable>* Variables = VariablesProperty->ContainerPtrToValuePtr<TArray<FNiagaraDataChannelVariable>>(Channel);
		if (!Variables)
		{
			OutError = TEXT("Failed to access ChannelVariables array.");
			return false;
		}

		Variables->Reset();
		for (const TSharedPtr<FJsonValue>& VariableValue : VariableValues)
		{
			const TSharedPtr<FJsonObject>* VariableObject = nullptr;
			if (!VariableValue.IsValid() || !VariableValue->TryGetObject(VariableObject) || !VariableObject || !VariableObject->IsValid())
			{
				OutError = TEXT("Each variables[] entry must be an object with name and type.");
				return false;
			}

			FString Name;
			FString TypeString;
			if (!(*VariableObject)->TryGetStringField(TEXT("name"), Name) || Name.TrimStartAndEnd().IsEmpty())
			{
				OutError = TEXT("Each variables[] entry must include a non-empty name.");
				return false;
			}
			if (!(*VariableObject)->TryGetStringField(TEXT("type"), TypeString) || TypeString.TrimStartAndEnd().IsEmpty())
			{
				OutError = FString::Printf(TEXT("Variable '%s' must include a type."), *Name);
				return false;
			}

			FNiagaraTypeDefinition TypeDefinition;
			if (!ParseNiagaraValueType(TypeString, TypeDefinition))
			{
				OutError = FString::Printf(TEXT("Invalid variable type '%s' for '%s'. Use float|int|bool|vec2|vec3|position|vec4|quat|color."), *TypeString, *Name);
				return false;
			}

			AddDataChannelVariable(*Variables, FName(*Name), TypeDefinition);
		}

		return Variables->Num() > 0;
	}

	UClass* ResolveDataChannelClass(const FString& ChannelClass, FString& OutNormalizedClass, FString& OutError)
	{
		const FString ClassKey = ChannelClass.TrimStartAndEnd().ToLower();
		if (ClassKey.IsEmpty() || ClassKey == TEXT("gameplay_burst") || ClassKey == TEXT("gameplayburst"))
		{
			OutNormalizedClass = TEXT("gameplay_burst");
			return UNiagaraDataChannel_GameplayBurst::StaticClass();
		}
		if (ClassKey == TEXT("global"))
		{
			OutNormalizedClass = TEXT("global");
			return UNiagaraDataChannel_Global::StaticClass();
		}

		UClass* LoadedClass = LoadObject<UClass>(nullptr, *ChannelClass);
		if (LoadedClass && LoadedClass->IsChildOf(UNiagaraDataChannel::StaticClass()))
		{
			OutNormalizedClass = LoadedClass->GetPathName();
			return LoadedClass;
		}

		OutError = FString::Printf(TEXT("Unsupported channel_class '%s'. Use gameplay_burst, global, or a UNiagaraDataChannel class path."), *ChannelClass);
		return nullptr;
	}

	void ApplyDataChannelSystemOverride(FNDCAccessContext& AccessContext, UObject* SystemToSpawn)
	{
		if (!SystemToSpawn)
		{
			return;
		}

		AccessContext.bOverrideSystemToSpawn = true;
		AccessContext.SystemToSpawn = SystemToSpawn;
	}

	void ConfigureDataChannelWriteContext(FNDCAccessContextInst& AccessContext, const FVector& Location, const float CellSize, const float BoundsPadding, UObject* SystemToSpawn = nullptr)
	{
		if (FNDCAccessContext_GameplayBurst* GameplayContext = AccessContext.Get<FNDCAccessContext_GameplayBurst>())
		{
			GameplayContext->Location = Location;
			GameplayContext->bOverrideLocation = true;
			GameplayContext->bOverrideCellSize = true;
			GameplayContext->CellSizeOverride = FVector(FMath::Max(1.0f, CellSize));
			GameplayContext->bOverrideBoundsPadding = true;
			GameplayContext->SystemBoundsPadding = FVector(FMath::Max(0.0f, BoundsPadding));
			ApplyDataChannelSystemOverride(*GameplayContext, SystemToSpawn);
			return;
		}

		if (FNDCAccessContext* BasicContext = AccessContext.Get<FNDCAccessContext>())
		{
			BasicContext->Location = Location;
			BasicContext->bOverrideLocation = true;
			ApplyDataChannelSystemOverride(*BasicContext, SystemToSpawn);
			return;
		}

		if (FNDCAccessContextLegacy* LegacyContext = AccessContext.Get<FNDCAccessContextLegacy>())
		{
			LegacyContext->Location = Location;
			LegacyContext->bOverrideLocation = true;
		}
	}

	void AppendAccessContextDiagnostics(TSharedPtr<FJsonObject>& Result, FNDCAccessContextInst& AccessContext)
	{
		Result->SetBoolField(TEXT("access_context_valid"), AccessContext.IsValid());
		Result->SetStringField(TEXT("access_context_struct"), AccessContext.GetScriptStruct() ? AccessContext.GetScriptStruct()->GetPathName() : FString());

		TArray<TSharedPtr<FJsonValue>> SpawnedSystems;
		int32 SpawnedSystemCount = 0;
		if (FNDCAccessContext* BasicContext = AccessContext.Get<FNDCAccessContext>())
		{
			Result->SetBoolField(TEXT("context_override_system_to_spawn"), BasicContext->bOverrideSystemToSpawn != 0);
			Result->SetStringField(TEXT("context_system_to_spawn"), BasicContext->SystemToSpawn ? BasicContext->SystemToSpawn->GetPathName() : FString());

			for (const FNDCSpawnedSystemRef& SpawnedSystem : BasicContext->SpawnedSystems)
			{
				UNiagaraComponent* Component = SpawnedSystem.Get();
				if (!Component)
				{
					continue;
				}

				++SpawnedSystemCount;
				SpawnedSystems.Add(MakeShared<FJsonValueObject>(MakeNiagaraComponentDebugJson(Component)));
			}
		}
		else
		{
			Result->SetBoolField(TEXT("context_override_system_to_spawn"), false);
			Result->SetStringField(TEXT("context_system_to_spawn"), FString());
		}

		Result->SetNumberField(TEXT("spawned_system_count"), SpawnedSystemCount);
		Result->SetArrayField(TEXT("spawned_systems"), SpawnedSystems);
	}

	void CollectAccessContextSpawnedComponents(FNDCAccessContextInst& AccessContext, TArray<UNiagaraComponent*>& OutComponents)
	{
		if (FNDCAccessContext* BasicContext = AccessContext.Get<FNDCAccessContext>())
		{
			for (const FNDCSpawnedSystemRef& SpawnedSystem : BasicContext->SpawnedSystems)
			{
				if (UNiagaraComponent* Component = SpawnedSystem.Get())
				{
					if (IsValid(Component))
					{
						OutComponents.AddUnique(Component);
					}
				}
			}
		}
	}

	void CollectSystemsFromSpawnObject(UObject* SystemToSpawn, TArray<UNiagaraSystem*>& OutSystems)
	{
		if (UNiagaraSystem* NiagaraSystem = Cast<UNiagaraSystem>(SystemToSpawn))
		{
			OutSystems.AddUnique(NiagaraSystem);
			return;
		}

		if (UNiagaraSystemCollection* SystemCollection = Cast<UNiagaraSystemCollection>(SystemToSpawn))
		{
			for (UNiagaraSystem* NiagaraSystem : SystemCollection->GetSystems())
			{
				if (NiagaraSystem)
				{
					OutSystems.AddUnique(NiagaraSystem);
				}
			}
		}
	}

	void CollectMatchingNiagaraComponents(UWorld* World, UObject* SystemToSpawn, TArray<UNiagaraComponent*>& OutComponents)
	{
		TArray<UNiagaraSystem*> Systems;
		CollectSystemsFromSpawnObject(SystemToSpawn, Systems);
		if (!World || Systems.Num() == 0)
		{
			return;
		}

		for (TObjectIterator<UNiagaraComponent> It; It; ++It)
		{
			UNiagaraComponent* Component = *It;
			if (IsValid(Component) && Component->GetWorld() == World && Systems.Contains(Component->GetAsset()))
			{
				OutComponents.AddUnique(Component);
			}
		}
	}

	void AppendNiagaraComponentArrayDiagnostics(TSharedPtr<FJsonObject>& Result, const TCHAR* Prefix, const TArray<UNiagaraComponent*>& Components)
	{
		const FString PrefixString(Prefix);
		TArray<TSharedPtr<FJsonValue>> ComponentsJson;
		int32 ValidCount = 0;
		for (UNiagaraComponent* Component : Components)
		{
			if (!IsValid(Component))
			{
				continue;
			}

			++ValidCount;
			ComponentsJson.Add(MakeShared<FJsonValueObject>(MakeNiagaraComponentDebugJson(Component)));
		}
		Result->SetNumberField(PrefixString + TEXT("count"), ValidCount);
		Result->SetArrayField(PrefixString + TEXT("components"), ComponentsJson);
	}

	void AdvanceNiagaraComponentsForDiagnostics(
		const TArray<UNiagaraComponent*>& Components,
		const int32 TickCount,
		const float TickDeltaSeconds,
		const bool bActivate,
		const bool bReset,
		TArray<UNiagaraComponent*>& OutAdvancedComponents)
	{
		for (UNiagaraComponent* Component : Components)
		{
			if (!IsValid(Component))
			{
				continue;
			}

			if (bActivate)
			{
				if (bReset)
				{
					Component->Activate(true);
				}
				else if (!Component->IsActive())
				{
					Component->Activate(false);
				}
			}
			Component->SetPaused(false);
			OutAdvancedComponents.AddUnique(Component);
		}

		for (int32 TickIndex = 0; TickIndex < TickCount; ++TickIndex)
		{
			for (UNiagaraComponent* Component : OutAdvancedComponents)
			{
				if (IsValid(Component))
				{
					Component->AdvanceSimulation(1, TickDeltaSeconds);
				}
			}
		}
	}

	bool TryReadJsonVector(const TSharedPtr<FJsonValue>& Value, int32 Components, TArray<double>& OutValues, FString& OutError)
	{
		if (!Value.IsValid() || Value->Type != EJson::Array)
		{
			OutError = FString::Printf(TEXT("Expected an array with %d numeric values."), Components);
			return false;
		}

		const TArray<TSharedPtr<FJsonValue>>& Array = Value->AsArray();
		if (Array.Num() < Components)
		{
			OutError = FString::Printf(TEXT("Expected at least %d numeric values."), Components);
			return false;
		}

		OutValues.Reset(Components);
		for (int32 Index = 0; Index < Components; ++Index)
		{
			if (!Array[Index].IsValid() || Array[Index]->Type != EJson::Number)
			{
				OutError = TEXT("Vector arrays must contain only numbers.");
				return false;
			}
			OutValues.Add(Array[Index]->AsNumber());
		}
		return true;
	}

	bool TryReadJsonVector3Value(const TSharedPtr<FJsonValue>& Value, FVector& OutVector)
	{
		TArray<double> Values;
		FString Error;
		if (!TryReadJsonVector(Value, 3, Values, Error))
		{
			return false;
		}
		OutVector = FVector(Values[0], Values[1], Values[2]);
		return true;
	}

	bool WriteDataChannelValue(UNiagaraDataChannelWriter& Writer, const FNiagaraDataChannelVariable& Variable, int32 RowIndex, const TSharedPtr<FJsonValue>& Value, FString& OutError)
	{
		const FName Name = Variable.GetName();
		const FNiagaraTypeDefinition Type = Variable.GetType();
		if (Type == FNiagaraTypeDefinition::GetFloatDef() || Type == FNiagaraTypeHelper::GetDoubleDef())
		{
			if (!Value.IsValid() || Value->Type != EJson::Number)
			{
				OutError = FString::Printf(TEXT("Variable '%s' expects a number."), *Name.ToString());
				return false;
			}
			Writer.WriteFloat(Name, RowIndex, Value->AsNumber());
			return true;
		}
		if (Type == FNiagaraTypeDefinition::GetIntDef())
		{
			if (!Value.IsValid() || Value->Type != EJson::Number)
			{
				OutError = FString::Printf(TEXT("Variable '%s' expects an integer number."), *Name.ToString());
				return false;
			}
			Writer.WriteInt(Name, RowIndex, static_cast<int32>(Value->AsNumber()));
			return true;
		}
		if (Type == FNiagaraTypeDefinition::GetBoolDef())
		{
			if (!Value.IsValid() || (Value->Type != EJson::Boolean && Value->Type != EJson::Number))
			{
				OutError = FString::Printf(TEXT("Variable '%s' expects a bool."), *Name.ToString());
				return false;
			}
			Writer.WriteBool(Name, RowIndex, Value->Type == EJson::Boolean ? Value->AsBool() : Value->AsNumber() != 0.0);
			return true;
		}

		TArray<double> Values;
		if (Type == FNiagaraTypeDefinition::GetVec2Def() || Type == FNiagaraTypeHelper::GetVector2DDef())
		{
			if (!TryReadJsonVector(Value, 2, Values, OutError)) { OutError = FString::Printf(TEXT("Variable '%s': %s"), *Name.ToString(), *OutError); return false; }
			Writer.WriteVector2D(Name, RowIndex, FVector2D(Values[0], Values[1]));
			return true;
		}
		if (Type == FNiagaraTypeDefinition::GetVec3Def() || Type == FNiagaraTypeHelper::GetVectorDef())
		{
			if (!TryReadJsonVector(Value, 3, Values, OutError)) { OutError = FString::Printf(TEXT("Variable '%s': %s"), *Name.ToString(), *OutError); return false; }
			Writer.WriteVector(Name, RowIndex, FVector(Values[0], Values[1], Values[2]));
			return true;
		}
		if (Type == FNiagaraTypeDefinition::GetPositionDef())
		{
			if (!TryReadJsonVector(Value, 3, Values, OutError)) { OutError = FString::Printf(TEXT("Variable '%s': %s"), *Name.ToString(), *OutError); return false; }
			Writer.WritePosition(Name, RowIndex, FVector(Values[0], Values[1], Values[2]));
			return true;
		}
		if (Type == FNiagaraTypeDefinition::GetVec4Def() || Type == FNiagaraTypeHelper::GetVector4Def())
		{
			if (!TryReadJsonVector(Value, 4, Values, OutError)) { OutError = FString::Printf(TEXT("Variable '%s': %s"), *Name.ToString(), *OutError); return false; }
			Writer.WriteVector4(Name, RowIndex, FVector4(Values[0], Values[1], Values[2], Values[3]));
			return true;
		}
		if (Type == FNiagaraTypeDefinition::GetQuatDef() || Type == FNiagaraTypeHelper::GetQuatDef())
		{
			if (!TryReadJsonVector(Value, 4, Values, OutError)) { OutError = FString::Printf(TEXT("Variable '%s': %s"), *Name.ToString(), *OutError); return false; }
			const FQuat QuatValue(Values[0], Values[1], Values[2], Values[3]);
			Writer.WriteQuat(Name, RowIndex, QuatValue.IsNormalized() ? QuatValue : QuatValue.GetNormalized());
			return true;
		}
		if (Type == FNiagaraTypeDefinition::GetColorDef())
		{
			if (!TryReadJsonVector(Value, 4, Values, OutError)) { OutError = FString::Printf(TEXT("Variable '%s': %s"), *Name.ToString(), *OutError); return false; }
			Writer.WriteLinearColor(Name, RowIndex, FLinearColor(Values[0], Values[1], Values[2], Values[3]));
			return true;
		}

		OutError = FString::Printf(TEXT("Variable '%s' has unsupported type '%s'."), *Name.ToString(), *NiagaraTypeToString(Type));
		return false;
	}
}

namespace
{
	UClass* ResolveDataChannelReadClass(FString& OutError)
	{
		UClass* ReaderClass = FindObject<UClass>(nullptr, TEXT("/Script/Niagara.NiagaraDataInterfaceDataChannelRead"));
		if (!ReaderClass)
		{
			ReaderClass = LoadObject<UClass>(nullptr, TEXT("/Script/Niagara.NiagaraDataInterfaceDataChannelRead"));
		}
		if (!ReaderClass || !ReaderClass->IsChildOf(UNiagaraDataInterface::StaticClass()))
		{
			OutError = TEXT("Failed to resolve /Script/Niagara.NiagaraDataInterfaceDataChannelRead.");
			return nullptr;
		}
		return ReaderClass;
	}

	UEnum* ResolveDataChannelSpawnModeEnum(FString& OutError)
	{
		UEnum* SpawnModeEnum = FindObject<UEnum>(nullptr, TEXT("/Script/Niagara.ENDIDataChannelSpawnMode"));
		if (!SpawnModeEnum)
		{
			SpawnModeEnum = LoadObject<UEnum>(nullptr, TEXT("/Script/Niagara.ENDIDataChannelSpawnMode"));
		}
		if (!SpawnModeEnum)
		{
			OutError = TEXT("Failed to resolve /Script/Niagara.ENDIDataChannelSpawnMode.");
		}
		return SpawnModeEnum;
	}

	bool SetBoolPropertyValue(UObject* Object, const UClass* PropertyOwnerClass, const TCHAR* PropertyName, const bool bValue, FString& OutError)
	{
		if (!Object || !PropertyOwnerClass)
		{
			OutError = TEXT("Invalid object or property owner class.");
			return false;
		}

		FBoolProperty* Property = FindFProperty<FBoolProperty>(PropertyOwnerClass, FName(PropertyName));
		if (!Property)
		{
			OutError = FString::Printf(TEXT("Bool property '%s' not found on %s."), PropertyName, *PropertyOwnerClass->GetName());
			return false;
		}

		Property->SetPropertyValue_InContainer(Object, bValue);
		return true;
	}

	void TrySetOptionalBoolPropertyValue(UObject* Object, const UClass* PropertyOwnerClass, const TCHAR* PropertyName, const bool bValue)
	{
		FString IgnoredError;
		SetBoolPropertyValue(Object, PropertyOwnerClass, PropertyName, bValue, IgnoredError);
	}

	FNiagaraTypeDefinition ToDataChannelScriptType(const FNiagaraTypeDefinition& Type)
	{
		if (Type.IsEnum())
		{
			return Type;
		}
		if (UScriptStruct* ScriptStruct = Type.GetScriptStruct())
		{
			if (UScriptStruct* SWCStruct = FNiagaraTypeHelper::GetSWCStruct(ScriptStruct))
			{
				return FNiagaraTypeDefinition(SWCStruct);
			}
		}
		return Type;
	}

	bool ConfigureDataChannelReaderDataInterface(
		UNiagaraDataInterface* DataInterface,
		UClass* ReaderClass,
		UNiagaraDataChannelAsset* ChannelAsset,
		const bool bReadCurrentFrame,
		const bool bUpdateSourceEveryTick,
		const bool bOnlySpawnOnceOnSubticks,
		FString& OutError)
	{
		if (!DataInterface || !ReaderClass || !ChannelAsset)
		{
			OutError = TEXT("Invalid Data Channel reader DI, class, or asset.");
			return false;
		}

		DataInterface->Modify();
		if (!SetObjectPropertyValue(DataInterface, ReaderClass, TEXT("Channel"), ChannelAsset, OutError))
		{
			return false;
		}
		if (!SetBoolPropertyValue(DataInterface, ReaderClass, TEXT("bReadCurrentFrame"), bReadCurrentFrame, OutError))
		{
			return false;
		}
		if (!SetBoolPropertyValue(DataInterface, ReaderClass, TEXT("bUpdateSourceDataEveryTick"), bUpdateSourceEveryTick, OutError))
		{
			return false;
		}

		TrySetOptionalBoolPropertyValue(DataInterface, ReaderClass, TEXT("bAutoLinkToSpawningNDC"), true);
		TrySetOptionalBoolPropertyValue(DataInterface, ReaderClass, TEXT("bOverrideSpawnGroupToDataChannelIndex"), false);
		TrySetOptionalBoolPropertyValue(DataInterface, ReaderClass, TEXT("bOnlySpawnOnceOnSubticks"), bOnlySpawnOnceOnSubticks);
		DataInterface->PostEditChange();
		return true;
	}

	bool SetDataChannelReaderOverrideOnModule(
		UNiagaraNodeFunctionCall& ModuleNode,
		UClass* ReaderClass,
		UNiagaraDataChannelAsset* ChannelAsset,
		const bool bReadCurrentFrame,
		const bool bUpdateSourceEveryTick,
		const bool bOnlySpawnOnceOnSubticks,
		FString& OutError)
	{
		const FNiagaraTypeDefinition ReaderType(ReaderClass);
		const FNiagaraParameterHandle AliasedInputHandle = MakeAliasedInputHandle(ModuleNode, TEXT("Data Channel"));
		UEdGraphPin& OverridePin = FNiagaraStackGraphUtilities::GetOrCreateStackFunctionInputOverridePin(
			ModuleNode,
			AliasedInputHandle,
			ReaderType,
			FGuid(),
			FGuid());

		if (OverridePin.LinkedTo.Num() > 0)
		{
			OverridePin.Modify();
			RemoveLinkedOverrideValueNodeLocal(OverridePin);
		}

		UNiagaraDataInterface* DataObject = nullptr;
		FNiagaraStackGraphUtilities::SetDataInterfaceValueForFunctionInput(
			OverridePin,
			ReaderClass,
			TEXT("Data Channel"),
			DataObject);

		if (!DataObject)
		{
			OutError = TEXT("Failed to create Data Channel reader data interface override.");
			return false;
		}

		return ConfigureDataChannelReaderDataInterface(
			DataObject,
			ReaderClass,
			ChannelAsset,
			bReadCurrentFrame,
			bUpdateSourceEveryTick,
			bOnlySpawnOnceOnSubticks,
			OutError);
	}

	bool RemoveDataChannelReaderOverrideOnModule(UNiagaraNodeFunctionCall& ModuleNode, int32& OutRemovedOverrideCount)
	{
		UEdGraphPin* OverridePin = GetStackFunctionInputOverridePinLocal(ModuleNode, TEXT("Data Channel"));
		if (!OverridePin)
		{
			return true;
		}

		UEdGraphNode* OverrideNode = OverridePin->GetOwningNode();
		if (!OverrideNode)
		{
			return true;
		}

		OverrideNode->Modify();
		OverridePin->Modify();
		RemoveLinkedOverrideValueNodeLocal(*OverridePin);
		OverrideNode->RemovePin(OverridePin);
		if (UNiagaraNode* NiagaraOverrideNode = Cast<UNiagaraNode>(OverrideNode))
		{
			NiagaraOverrideNode->MarkNodeRequiresSynchronization(TEXT("LJC NDC shared reader override removed"), true);
		}
		++OutRemovedOverrideCount;
		return true;
	}

		template<typename NodeType>
	NodeType* FindSingleNiagaraNodeChecked(UNiagaraGraph* Graph)
	{
		check(Graph);
		TArray<NodeType*> NiagaraNodes;
		Graph->GetNodesOfClass(NiagaraNodes);
		check(NiagaraNodes.Num() == 1);
		return NiagaraNodes[0];
	}

	template<typename NodeType>
	NodeType* FindSingleNiagaraNodeByClassNameChecked(UNiagaraGraph* Graph, const TCHAR* RequiredClassName)
	{
		check(Graph);
		TArray<UEdGraphNode*> MatchedNodes;
		for (UEdGraphNode* Node : Graph->Nodes)
		{
			if (Node && Node->GetClass() && Node->GetClass()->GetName().Contains(RequiredClassName))
			{
				MatchedNodes.Add(Node);
			}
		}
		check(MatchedNodes.Num() == 1);
		return reinterpret_cast<NodeType*>(MatchedNodes[0]);
	}

	UNiagaraGraph* GetScratchPadGraph(const TSharedPtr<FNiagaraScratchPadScriptViewModel>& ScratchPadScriptViewModel)
	{
		if (!ScratchPadScriptViewModel.IsValid())
		{
			return nullptr;
		}

		FVersionedNiagaraScriptData* ScriptData = ScratchPadScriptViewModel->GetEditScript().GetScriptData();
		UNiagaraScriptSource* ScriptSource = ScriptData ? Cast<UNiagaraScriptSource>(ScriptData->GetSource()) : nullptr;
		return ScriptSource ? ScriptSource->NodeGraph : nullptr;
	}

	bool SetNiagaraScriptVariableDefaultValueData(UNiagaraGraph* Graph, const FName& VarName, FNiagaraVariable& Var)
	{
		UNiagaraScriptVariable* ScriptVariable = Graph ? Graph->GetScriptVariable(VarName) : nullptr;
		if (!ScriptVariable)
		{
			return false;
		}

		ScriptVariable->Modify();
		ScriptVariable->DefaultMode = ENiagaraDefaultMode::Value;
		ScriptVariable->SetDefaultValueData(Var.GetData());
		ScriptVariable->UpdateChangeId();
		return true;
	}

	bool SetNiagaraScriptVariableDefaultValue(UNiagaraGraph* Graph, const FName& VarName, const FNiagaraTypeDefinition& TypeDef, const float Value)
	{
		FNiagaraVariable Var(TypeDef, VarName);
		Var.SetValue<float>(Value);
		return SetNiagaraScriptVariableDefaultValueData(Graph, VarName, Var);
	}

	bool SetNiagaraScriptVariableDefaultValue(UNiagaraGraph* Graph, const FName& VarName, const FNiagaraTypeDefinition& TypeDef, const int32 Value)
	{
		FNiagaraVariable Var(TypeDef, VarName);
		if (TypeDef.IsEnum())
		{
			FNiagaraInt32 NiagaraValue;
			NiagaraValue.Value = Value;
			Var.SetValue<FNiagaraInt32>(NiagaraValue);
		}
		else
		{
			Var.SetValue<int32>(Value);
		}
		return SetNiagaraScriptVariableDefaultValueData(Graph, VarName, Var);
	}

	bool SetNiagaraScriptVariableDefaultValue(UNiagaraGraph* Graph, const FName& VarName, const FNiagaraTypeDefinition& TypeDef, const bool bValue)
	{
		FNiagaraVariable Var(TypeDef, VarName);
		FNiagaraBool NiagaraValue;
		NiagaraValue.SetValue(bValue);
		Var.SetValue<FNiagaraBool>(NiagaraValue);
		return SetNiagaraScriptVariableDefaultValueData(Graph, VarName, Var);
	}

	bool SetNiagaraScriptVariableDefaultValueForModuleInput(UNiagaraGraph* Graph, const FString& InputName, const FNiagaraTypeDefinition& TypeDef, const bool bValue)
	{
		return SetNiagaraScriptVariableDefaultValue(Graph, FName(*(TEXT("Module.") + InputName)), TypeDef, bValue)
			|| SetNiagaraScriptVariableDefaultValue(Graph, FName(*InputName), TypeDef, bValue);
	}

	bool SetNiagaraScriptVariableDefaultValueForModuleInput(UNiagaraGraph* Graph, const FString& InputName, const FNiagaraTypeDefinition& TypeDef, const int32 Value)
	{
		return SetNiagaraScriptVariableDefaultValue(Graph, FName(*(TEXT("Module.") + InputName)), TypeDef, Value)
			|| SetNiagaraScriptVariableDefaultValue(Graph, FName(*InputName), TypeDef, Value);
	}

	bool SetNiagaraScriptVariableDefaultValueForModuleInput(UNiagaraGraph* Graph, const FString& InputName, const FNiagaraTypeDefinition& TypeDef, const float Value)
	{
		return SetNiagaraScriptVariableDefaultValue(Graph, FName(*(TEXT("Module.") + InputName)), TypeDef, Value)
			|| SetNiagaraScriptVariableDefaultValue(Graph, FName(*InputName), TypeDef, Value);
	}

	bool SetNDCSpawnDirectVariableSpecifier(UNiagaraNodeFunctionCall& SpawnFunction, const FNiagaraDataChannelVariable& CountVariable, FString& OutError)
	{
		if (CountVariable.GetType() != FNiagaraTypeDefinition::GetIntDef())
		{
			OutError = FString::Printf(TEXT("Spawn count variable '%s' must be an int variable."), *CountVariable.GetName().ToString());
			return false;
		}

		FString TypeString;
		FNiagaraTypeDefinition IntType = FNiagaraTypeDefinition::GetIntDef();
		FNiagaraTypeDefinition::StaticStruct()->ExportText(TypeString, &IntType, nullptr, nullptr, PPF_None, nullptr);

		SpawnFunction.Modify();
		SpawnFunction.FunctionSpecifiers.FindOrAdd(FName(TEXT("VarName"))) = CountVariable.GetName();
		SpawnFunction.FunctionSpecifiers.FindOrAdd(FName(TEXT("VarType"))) = FName(*TypeString);
		SpawnFunction.MarkNodeRequiresSynchronization(TEXT("LJC NDC SpawnDirect specifier changed"), true);
		return true;
	}

	bool ConfigureNDCSpawnDirectScriptDefaults(
		UNiagaraScript* FunctionScript,
		const FString& ModuleName,
		UEnum* SpawnModeEnum,
		const FNiagaraDataChannelVariable& CountVariable,
		const int32 MinCount,
		const int32 MaxCount,
		int32& OutUpdatedDefaultCount,
		FString& OutError)
	{
		UNiagaraScriptSource* ScriptSource = FunctionScript ? Cast<UNiagaraScriptSource>(FunctionScript->GetLatestSource()) : nullptr;
		UNiagaraGraph* InnerGraph = ScriptSource ? ScriptSource->NodeGraph : nullptr;
		if (!InnerGraph || !SpawnModeEnum)
		{
			OutError = FString::Printf(TEXT("SpawnDirect scratch module '%s' has no editable inner graph."), *ModuleName);
			return false;
		}

		FunctionScript->Modify();
		InnerGraph->Modify();
		OutUpdatedDefaultCount = 0;

		UNiagaraNodeFunctionCall* SpawnFunction = nullptr;
		TArray<UNiagaraNodeFunctionCall*> FunctionNodes;
		InnerGraph->GetNodesOfClass<UNiagaraNodeFunctionCall>(FunctionNodes);
		for (UNiagaraNodeFunctionCall* FunctionNode : FunctionNodes)
		{
			if (FunctionNode && FunctionNode->GetFunctionName().Equals(TEXT("SpawnDirect"), ESearchCase::IgnoreCase))
			{
				SpawnFunction = FunctionNode;
				break;
			}
		}
		if (!SpawnFunction)
		{
			OutError = FString::Printf(TEXT("SpawnDirect scratch module '%s' does not contain a SpawnDirect node."), *ModuleName);
			return false;
		}
		if (!SetNDCSpawnDirectVariableSpecifier(*SpawnFunction, CountVariable, OutError))
		{
			return false;
		}

		if (UEdGraphPin* EnableInput = SpawnFunction->FindPin(FName(TEXT("Enable")), EGPD_Input))
		{
			if (EnableInput->LinkedTo.Num() > 0)
			{
				EnableInput->Modify();
				EnableInput->BreakAllPinLinks(true);
				++OutUpdatedDefaultCount;
			}
		}

		OutUpdatedDefaultCount += SetNiagaraScriptVariableDefaultValueForModuleInput(InnerGraph, TEXT("Spawn Mode"), FNiagaraTypeDefinition(SpawnModeEnum), 0) ? 1 : 0;
		OutUpdatedDefaultCount += SetNiagaraScriptVariableDefaultValueForModuleInput(InnerGraph, TEXT("Random Scale Min"), FNiagaraTypeDefinition::GetFloatDef(), 1.0f) ? 1 : 0;
		OutUpdatedDefaultCount += SetNiagaraScriptVariableDefaultValueForModuleInput(InnerGraph, TEXT("Random Scale Max"), FNiagaraTypeDefinition::GetFloatDef(), 1.0f) ? 1 : 0;
		OutUpdatedDefaultCount += SetNiagaraScriptVariableDefaultValueForModuleInput(InnerGraph, TEXT("Min Count"), FNiagaraTypeDefinition::GetIntDef(), MinCount) ? 1 : 0;
		OutUpdatedDefaultCount += SetNiagaraScriptVariableDefaultValueForModuleInput(InnerGraph, TEXT("Max Count"), FNiagaraTypeDefinition::GetIntDef(), MaxCount) ? 1 : 0;

		InnerGraph->NotifyGraphChanged();
		FunctionScript->MarkPackageDirty();
		return true;
	}

	bool ConfigureNDCSpawnDirectModuleDefaults(
		UNiagaraNodeFunctionCall& ModuleNode,
		UEnum* SpawnModeEnum,
		const FNiagaraDataChannelVariable& CountVariable,
		const int32 MinCount,
		const int32 MaxCount,
		int32& OutUpdatedDefaultCount,
		FString& OutError)
	{
		return ConfigureNDCSpawnDirectScriptDefaults(
			ModuleNode.FunctionScript,
			ModuleNode.GetFunctionName(),
			SpawnModeEnum,
			CountVariable,
			MinCount,
			MaxCount,
			OutUpdatedDefaultCount,
			OutError);
	}


	UNiagaraGraph* GetScratchScriptInnerGraph(UNiagaraScript* FunctionScript, const FString& ModuleName, FString& OutError)
	{
		UNiagaraScriptSource* ScriptSource = FunctionScript ? Cast<UNiagaraScriptSource>(FunctionScript->GetLatestSource()) : nullptr;
		UNiagaraGraph* InnerGraph = ScriptSource ? ScriptSource->NodeGraph : nullptr;
		if (!InnerGraph)
		{
			OutError = FString::Printf(TEXT("Scratch module '%s' has no editable inner graph."), *ModuleName);
		}
		return InnerGraph;
	}

	UNiagaraGraph* GetScratchModuleInnerGraph(UNiagaraNodeFunctionCall& ModuleNode, FString& OutError)
	{
		return GetScratchScriptInnerGraph(ModuleNode.FunctionScript, ModuleNode.GetFunctionName(), OutError);
	}

	UNiagaraNodeFunctionCall* FindInnerDataInterfaceFunction(UNiagaraGraph& Graph, const FString& FunctionName)
	{
		TArray<UNiagaraNodeFunctionCall*> FunctionNodes;
		Graph.GetNodesOfClass<UNiagaraNodeFunctionCall>(FunctionNodes);
		for (UNiagaraNodeFunctionCall* FunctionNode : FunctionNodes)
		{
			if (FunctionNode && FunctionNode->GetFunctionName().Equals(FunctionName, ESearchCase::IgnoreCase))
			{
				return FunctionNode;
			}
		}
		return nullptr;
	}

	UNiagaraNodeFunctionCall* FindUniqueNDCSpawnDirectModuleInEmitterUpdateStack(UNiagaraGraph* Graph, int32& OutMatchCount)
	{
		OutMatchCount = 0;
		UNiagaraNodeFunctionCall* UniqueMatch = nullptr;
		TArray<FMCPNiagaraStackModuleData> ModuleDataList;
		CollectStackModuleData(Graph, ModuleDataList);
		for (const FMCPNiagaraStackModuleData& ModuleData : ModuleDataList)
		{
			if (!ModuleData.Node || ModuleData.Usage != ENiagaraScriptUsage::EmitterUpdateScript)
			{
				continue;
			}

			FString IgnoredError;
			UNiagaraGraph* InnerGraph = GetScratchModuleInnerGraph(*ModuleData.Node, IgnoredError);
			if (InnerGraph && FindInnerDataInterfaceFunction(*InnerGraph, TEXT("SpawnDirect")))
			{
				UniqueMatch = ModuleData.Node;
				++OutMatchCount;
			}
		}
		return OutMatchCount == 1 ? UniqueMatch : nullptr;
	}

	bool ConfigureNDCParticleReadScriptGraph(
		UNiagaraScript* FunctionScript,
		const FString& ModuleName,
		UClass* ReaderClass,
		UNiagaraDataChannel* Channel,
		const FString& TargetNamespace,
		int32& OutUpdatedPinCount,
		int32& OutRemovedPinCount,
		FString& OutError)
	{
		using namespace UE::Niagara::Wizard;

		OutUpdatedPinCount = 0;
		OutRemovedPinCount = 0;
		UNiagaraGraph* InnerGraph = GetScratchScriptInnerGraph(FunctionScript, ModuleName, OutError);
		if (!InnerGraph || !ReaderClass || !Channel)
		{
			if (OutError.IsEmpty())
			{
				OutError = TEXT("Invalid particle read module graph, Data Channel reader class, or channel.");
			}
			return false;
		}

		FunctionScript->Modify();
		InnerGraph->Modify();
		UNiagaraNodeFunctionCall* ReadFunction = FindInnerDataInterfaceFunction(*InnerGraph, TEXT("Read"));
		UNiagaraNodeParameterMapSet* MapSetTypedNode = FindSingleNiagaraNodeByClassNameChecked<UNiagaraNodeParameterMapSet>(InnerGraph, TEXT("NiagaraNodeParameterMapSet"));
		UEdGraphNode* MapSetNode = reinterpret_cast<UEdGraphNode*>(MapSetTypedNode);
		if (!ReadFunction || !MapSetTypedNode || !MapSetNode)
		{
			OutError = FString::Printf(TEXT("Particle read module '%s' is missing its Data Channel Read node or ParameterMapSet."), *ModuleName);
			return false;
		}

		ReadFunction->Modify();
		MapSetNode->Modify();

		const FString CleanNamespace = TargetNamespace.IsEmpty() ? TEXT("Particles") : TargetNamespace;
		TArray<FNiagaraVariable> DesiredReadOutputs;

		for (const FNiagaraDataChannelVariable& Variable : Channel->GetVariables())
		{
			const FNiagaraTypeDefinition ScriptType = ToDataChannelScriptType(Variable.GetType());
			const FName DesiredName = Variable.GetName();
			DesiredReadOutputs.Emplace(ScriptType, DesiredName);

		}

		const UEdGraphSchema_Niagara* GraphSchema = GetDefault<UEdGraphSchema_Niagara>();
		TArray<UEdGraphPin*> DataChannelInputLinks;
		TArray<UEdGraphPin*> IndexInputLinks;
		TArray<UEdGraphPin*> SuccessOutputLinks;
		if (UEdGraphPin* DataChannelInputPin = ReadFunction->FindPin(FName(TEXT("DataChannel interface")), EGPD_Input))
		{
			DataChannelInputLinks = DataChannelInputPin->LinkedTo;
		}
		if (UEdGraphPin* IndexInputPin = ReadFunction->FindPin(FName(TEXT("Index")), EGPD_Input))
		{
			IndexInputLinks = IndexInputPin->LinkedTo;
		}
		if (UEdGraphPin* SuccessOutputPin = ReadFunction->FindPin(FName(TEXT("Success")), EGPD_Output))
		{
			SuccessOutputLinks = SuccessOutputPin->LinkedTo;
		}

		TArray<UEdGraphPin*> MapSetPinsToRemove;
		for (UEdGraphPin* Pin : MapSetNode->Pins)
		{
			if (!Pin || Pin->Direction != EGPD_Input)
			{
				continue;
			}
			for (UEdGraphPin* LinkedPin : Pin->LinkedTo)
			{
				if (LinkedPin && LinkedPin->GetOwningNode() == ReadFunction && LinkedPin->PinName != FName(TEXT("Success")))
				{
					MapSetPinsToRemove.AddUnique(Pin);
					break;
				}
			}
		}
		for (UEdGraphPin* PinToRemove : MapSetPinsToRemove)
		{
			PinToRemove->Modify();
			PinToRemove->BreakAllPinLinks();
			MapSetNode->RemovePin(PinToRemove);
			++OutRemovedPinCount;
		}

		const int32 ReadNodePosX = ReadFunction->NodePosX;
		const int32 ReadNodePosY = ReadFunction->NodePosY;
		ReadFunction->BreakAllNodeLinks();
		InnerGraph->RemoveNode(ReadFunction);
		++OutRemovedPinCount;

		ReadFunction = Utilities::CreateDataInterfaceFunctionNode(ReaderClass, FName(TEXT("Read")), InnerGraph);
		if (!ReadFunction)
		{
			OutError = FString::Printf(TEXT("Failed to recreate Data Channel Read node for particle read module '%s'."), *ModuleName);
			return false;
		}
		ReadFunction->NodePosX = ReadNodePosX;
		ReadFunction->NodePosY = ReadNodePosY;
		ReadFunction->Modify();
		++OutUpdatedPinCount;

		if (UEdGraphPin* DataChannelInputPin = ReadFunction->FindPin(FName(TEXT("DataChannel interface")), EGPD_Input))
		{
			for (UEdGraphPin* LinkedPin : DataChannelInputLinks)
			{
				if (LinkedPin)
				{
					GraphSchema->TryCreateConnection(DataChannelInputPin, LinkedPin);
				}
			}
		}
		if (UEdGraphPin* IndexInputPin = ReadFunction->FindPin(FName(TEXT("Index")), EGPD_Input))
		{
			for (UEdGraphPin* LinkedPin : IndexInputLinks)
			{
				if (LinkedPin)
				{
					GraphSchema->TryCreateConnection(IndexInputPin, LinkedPin);
				}
			}
		}
		if (UEdGraphPin* SuccessOutputPin = ReadFunction->FindPin(FName(TEXT("Success")), EGPD_Output))
		{
			for (UEdGraphPin* LinkedPin : SuccessOutputLinks)
			{
				if (LinkedPin)
				{
					GraphSchema->TryCreateConnection(SuccessOutputPin, LinkedPin);
				}
			}
		}

		for (const FNiagaraVariable& DesiredOutput : DesiredReadOutputs)
		{
			const FName DesiredName = DesiredOutput.GetName();
			ReadFunction->Signature.AddOutput(DesiredOutput);
			const FEdGraphPinType ReadPinType = UEdGraphSchema_Niagara::TypeDefinitionToPinType(DesiredOutput.GetType());
			UEdGraphPin* ReadParamPin = ReadFunction->CreatePin(EGPD_Output, ReadPinType, DesiredName);
			if (!ReadParamPin)
			{
				OutError = FString::Printf(TEXT("Failed to create Data Channel Read output pin '%s'."), *DesiredName.ToString());
				return false;
			}
			ReadParamPin->bDefaultValueIsIgnored = true;
			++OutUpdatedPinCount;

			const FName TargetAttributeName(CleanNamespace + TEXT(".") + DesiredName.ToString());
			while (UEdGraphPin* ExistingSetPin = MapSetNode->FindPin(TargetAttributeName, EGPD_Input))
			{
				ExistingSetPin->Modify();
				ExistingSetPin->BreakAllPinLinks();
				MapSetNode->RemovePin(ExistingSetPin);
				++OutRemovedPinCount;
			}
			UEdGraphPin* SetVarPin = Utilities::AddWriteParameterPin(DesiredOutput.GetType(), TargetAttributeName, MapSetTypedNode);
			if (!SetVarPin)
			{
				OutError = FString::Printf(TEXT("Failed to create ParameterMapSet pin for '%s'."), *TargetAttributeName.ToString());
				return false;
			}
			if (!GraphSchema->TryCreateConnection(ReadParamPin, SetVarPin))
			{
				OutError = FString::Printf(
					TEXT("Failed to connect Data Channel Read output '%s' to ParameterMapSet pin '%s'."),
					*DesiredName.ToString(),
					*TargetAttributeName.ToString());
				return false;
			}
			++OutUpdatedPinCount;
		}
		ReadFunction->MarkNodeRequiresSynchronization(TEXT("LJC NDC Read outputs synchronized"), true);
		if (UNiagaraNode* NiagaraMapSetNode = Cast<UNiagaraNode>(MapSetNode))
		{
			NiagaraMapSetNode->MarkNodeRequiresSynchronization(TEXT("LJC NDC particle attributes synchronized"), true);
		}

		InnerGraph->NotifyGraphChanged();
		FunctionScript->MarkPackageDirty();
		return true;
	}

	bool ConfigureNDCParticleReadModuleGraph(
		UNiagaraNodeFunctionCall& ModuleNode,
		UClass* ReaderClass,
		UNiagaraDataChannel* Channel,
		const FString& TargetNamespace,
		int32& OutUpdatedPinCount,
		int32& OutRemovedPinCount,
		FString& OutError)
	{
		return ConfigureNDCParticleReadScriptGraph(
			ModuleNode.FunctionScript,
			ModuleNode.GetFunctionName(),
			ReaderClass,
			Channel,
			TargetNamespace,
			OutUpdatedPinCount,
			OutRemovedPinCount,
			OutError);
	}

	TSharedPtr<FNiagaraSystemViewModel> OpenNiagaraSystemViewModelForEdit(UNiagaraSystem* System, const bool bOpenEditor, const bool bFocusEditor, FString& OutError)
	{
		if (!System)
		{
			OutError = TEXT("System is null.");
			return nullptr;
		}

		if (UAssetEditorSubsystem* AssetEditorSubsystem = GEditor ? GEditor->GetEditorSubsystem<UAssetEditorSubsystem>() : nullptr)
		{
			const bool bEditorAlreadyOpen = AssetEditorSubsystem->FindEditorForAsset(System, bFocusEditor) != nullptr;
			if (bOpenEditor && !bEditorAlreadyOpen)
			{
				AssetEditorSubsystem->OpenEditorForAsset(System);
			}
		}

		FNiagaraEditorModule& NiagaraEditorModule = FModuleManager::LoadModuleChecked<FNiagaraEditorModule>(TEXT("NiagaraEditor"));
		TSharedPtr<FNiagaraSystemViewModel> SystemViewModel = NiagaraEditorModule.GetExistingViewModelForSystem(System);
		for (int32 Attempt = 0; !SystemViewModel.IsValid() && bOpenEditor && Attempt < 8; ++Attempt)
		{
			if (FSlateApplication::IsInitialized())
			{
				FSlateApplication::Get().PumpMessages();
				FSlateApplication::Get().Tick();
			}
			SystemViewModel = NiagaraEditorModule.GetExistingViewModelForSystem(System);
		}

		if (!SystemViewModel.IsValid())
		{
			OutError = TEXT("Niagara system ViewModel was not found. Open the asset editor or call with open_editor=true.");
		}
		return SystemViewModel;
	}

	typedef TFunction<bool(TSharedPtr<FNiagaraScratchPadScriptViewModel>, FString&)> FGenerateNDCModuleGraph;

	UNiagaraNodeFunctionCall* CreateScratchNDCModule(
		TSharedPtr<FNiagaraSystemViewModel> SystemViewModel,
		UNiagaraNodeOutput* OutputNode,
		const int32 TargetIndex,
		FGenerateNDCModuleGraph GenerateGraph,
		FString& OutError)
	{
		if (!SystemViewModel.IsValid() || !OutputNode)
		{
			OutError = TEXT("Invalid Niagara system ViewModel or output node.");
			return nullptr;
		}

		UNiagaraScratchPadViewModel* ScratchPadViewModel = SystemViewModel->GetScriptScratchPadViewModel();
		if (!ScratchPadViewModel)
		{
			OutError = TEXT("Niagara scratch pad ViewModel is unavailable.");
			return nullptr;
		}

		TSharedPtr<FNiagaraScratchPadScriptViewModel> ScratchPadScriptViewModel = ScratchPadViewModel->CreateNewScript(
			ENiagaraScriptUsage::Module,
			OutputNode->GetUsage(),
			FNiagaraTypeDefinition());
		if (!ScratchPadScriptViewModel.IsValid())
		{
			OutError = TEXT("Failed to create Niagara scratch pad module.");
			return nullptr;
		}

		if (!GenerateGraph(ScratchPadScriptViewModel, OutError))
		{
			return nullptr;
		}

		UNiagaraNodeFunctionCall* NewModule = FNiagaraStackGraphUtilities::AddScriptModuleToStack(
			ScratchPadScriptViewModel->GetOriginalScript(),
			*OutputNode,
			TargetIndex);
		if (!NewModule)
		{
			OutError = TEXT("Failed to add scratch pad module to Niagara stack.");
			return nullptr;
		}
		return NewModule;
	}

	bool GenerateNDCEmitterSpawnModule(TSharedPtr<FNiagaraScratchPadScriptViewModel> ScratchPadScriptViewModel, UClass* ReaderClass, FString& OutError)
	{
		using namespace UE::Niagara::Wizard;
		ScratchPadScriptViewModel->SetScriptName(FText::FromString(TEXT("Init data channel")));
		UNiagaraGraph* Graph = GetScratchPadGraph(ScratchPadScriptViewModel);
		if (!Graph || !ReaderClass)
		{
			OutError = TEXT("Invalid scratch graph or Data Channel reader class.");
			return false;
		}

		const UEdGraphSchema_Niagara* GraphSchema = GetDefault<UEdGraphSchema_Niagara>();
		UNiagaraNodeParameterMapGet* MapGetNode = FindSingleNiagaraNodeByClassNameChecked<UNiagaraNodeParameterMapGet>(Graph, TEXT("NiagaraNodeParameterMapGet"));
		UNiagaraNodeParameterMapSet* MapSetNode = FindSingleNiagaraNodeByClassNameChecked<UNiagaraNodeParameterMapSet>(Graph, TEXT("NiagaraNodeParameterMapSet"));
		const FNiagaraTypeDefinition ReaderType(ReaderClass);
		UEdGraphPin* DIInputPin = Utilities::AddReadParameterPin(ReaderType, FName(TEXT("Data Channel")), MapGetNode);
		UEdGraphPin* DIVarPin = Utilities::AddWriteParameterPin(ReaderType, FName(TEXT("Emitter.SpawnDataChannel")), MapSetNode);
		GraphSchema->TryCreateConnection(DIInputPin, DIVarPin);
		ScratchPadScriptViewModel->ApplyChanges();
		return true;
	}

	bool GenerateNDCEmitterUpdateSpawnDirectModule(
		TSharedPtr<FNiagaraScratchPadScriptViewModel> ScratchPadScriptViewModel,
		UClass* ReaderClass,
		UEnum* SpawnModeEnum,
		UNiagaraDataChannel* Channel,
		const FString& ModuleName,
		const FName SpawnCountVariable,
		const int32 MinCount,
		const int32 MaxCount,
		FString& OutError)
	{
		using namespace UE::Niagara::Wizard;
		ScratchPadScriptViewModel->SetScriptName(FText::FromString(ModuleName.IsEmpty() ? TEXT("Spawn From Data Channel") : ModuleName));
		UNiagaraGraph* Graph = GetScratchPadGraph(ScratchPadScriptViewModel);
		if (!Graph || !ReaderClass || !SpawnModeEnum || !Channel)
		{
			OutError = TEXT("Invalid scratch graph, Data Channel reader class, enum, or channel.");
			return false;
		}

		const UEdGraphSchema_Niagara* GraphSchema = GetDefault<UEdGraphSchema_Niagara>();
		UNiagaraNodeParameterMapGet* MapGetNode = FindSingleNiagaraNodeByClassNameChecked<UNiagaraNodeParameterMapGet>(Graph, TEXT("NiagaraNodeParameterMapGet"));
		UNiagaraNodeParameterMapSet* MapSetNode = FindSingleNiagaraNodeByClassNameChecked<UNiagaraNodeParameterMapSet>(Graph, TEXT("NiagaraNodeParameterMapSet"));
		Graph->RemoveNode(reinterpret_cast<UEdGraphNode*>(MapSetNode));
		UNiagaraNodeInput* InputNode = FindSingleNiagaraNodeChecked<UNiagaraNodeInput>(Graph);
		UNiagaraNodeOutput* OutputNode = FindSingleNiagaraNodeChecked<UNiagaraNodeOutput>(Graph);

		UNiagaraNodeFunctionCall* SpawnFunction = Utilities::CreateDataInterfaceFunctionNode(ReaderClass, FName(TEXT("SpawnDirect")), Graph);
		if (!SpawnFunction)
		{
			OutError = TEXT("Failed to create Data Channel SpawnDirect function node.");
			return false;
		}

		const FNiagaraTypeDefinition ReaderType(ReaderClass);
		UEdGraphPin* DIPin = Utilities::AddReadParameterPin(ReaderType, FName(TEXT("Data Channel")), MapGetNode);
		SpawnFunction->AutowireNewNode(DIPin);
		GraphSchema->TryCreateConnection(InputNode->GetOutputPin(0), SpawnFunction->GetInputPin(0));
		GraphSchema->TryCreateConnection(SpawnFunction->GetOutputPin(0), OutputNode->GetInputPin(0));
		Utilities::SetDefaultBinding(Graph, DIPin->PinName, FName(TEXT("Emitter.SpawnDataChannel")));

		if (UEdGraphPin* EnableInput = SpawnFunction->FindPin(FName(TEXT("Enable")), EGPD_Input))
		{
			// SpawnDirect 的 Enable 有签名默认 true；不要接 MapGet，避免默认 pin 未同步时被编译成 false。
			EnableInput->BreakAllPinLinks(true);
		}
		if (UEdGraphPin* EmitterIDInput = SpawnFunction->FindPin(FName(TEXT("Emitter ID")), EGPD_Input))
		{
			UEdGraphPin* EmitterIDPin = Utilities::AddReadParameterPin(FNiagaraTypeDefinition(FNiagaraEmitterID::StaticStruct()), FName(TEXT("Emitter ID")), MapGetNode);
			GraphSchema->TryCreateConnection(EmitterIDPin, EmitterIDInput);
			Utilities::SetDefaultBinding(Graph, EmitterIDPin->PinName, SYS_PARAM_ENGINE_EMITTER_ID.GetName());
		}
		if (UEdGraphPin* ModeInput = SpawnFunction->FindPin(FName(TEXT("Mode")), EGPD_Input))
		{
			UEdGraphPin* SpawnModePin = Utilities::AddReadParameterPin(FNiagaraTypeDefinition(SpawnModeEnum), FName(TEXT("Spawn Mode")), MapGetNode);
			SetNiagaraScriptVariableDefaultValue(Graph, SpawnModePin->PinName, FNiagaraTypeDefinition(SpawnModeEnum), 0);
			GraphSchema->TryCreateConnection(SpawnModePin, ModeInput);
		}
		if (UEdGraphPin* ScaleMinInput = SpawnFunction->FindPin(FName(TEXT("RandomScaleMin")), EGPD_Input))
		{
			UEdGraphPin* ScaleMinPin = Utilities::AddReadParameterPin(FNiagaraTypeDefinition::GetFloatDef(), FName(TEXT("Random Scale Min")), MapGetNode);
			SetNiagaraScriptVariableDefaultValue(Graph, ScaleMinPin->PinName, FNiagaraTypeDefinition::GetFloatDef(), 1.0f);
			GraphSchema->TryCreateConnection(ScaleMinPin, ScaleMinInput);
		}
		if (UEdGraphPin* ScaleMaxInput = SpawnFunction->FindPin(FName(TEXT("RandomScaleMax")), EGPD_Input))
		{
			UEdGraphPin* ScaleMaxPin = Utilities::AddReadParameterPin(FNiagaraTypeDefinition::GetFloatDef(), FName(TEXT("Random Scale Max")), MapGetNode);
			SetNiagaraScriptVariableDefaultValue(Graph, ScaleMaxPin->PinName, FNiagaraTypeDefinition::GetFloatDef(), 1.0f);
			GraphSchema->TryCreateConnection(ScaleMaxPin, ScaleMaxInput);
		}
		if (UEdGraphPin* MinInput = SpawnFunction->FindPin(FName(TEXT("ClampMin")), EGPD_Input))
		{
			UEdGraphPin* MinPin = Utilities::AddReadParameterPin(FNiagaraTypeDefinition::GetIntDef(), FName(TEXT("Min Count")), MapGetNode);
			SetNiagaraScriptVariableDefaultValue(Graph, MinPin->PinName, FNiagaraTypeDefinition::GetIntDef(), MinCount);
			GraphSchema->TryCreateConnection(MinPin, MinInput);
		}
		if (UEdGraphPin* MaxInput = SpawnFunction->FindPin(FName(TEXT("ClampMax")), EGPD_Input))
		{
			UEdGraphPin* MaxPin = Utilities::AddReadParameterPin(FNiagaraTypeDefinition::GetIntDef(), FName(TEXT("Max Count")), MapGetNode);
			SetNiagaraScriptVariableDefaultValue(Graph, MaxPin->PinName, FNiagaraTypeDefinition::GetIntDef(), MaxCount);
			GraphSchema->TryCreateConnection(MaxPin, MaxInput);
		}

		const FNiagaraDataChannelVariable* CountVariable = Channel->GetVariables().FindByPredicate([SpawnCountVariable](const FNiagaraDataChannelVariable& Variable)
		{
			return Variable.GetName() == SpawnCountVariable;
		});
		if (!CountVariable || CountVariable->GetType() != FNiagaraTypeDefinition::GetIntDef())
		{
			OutError = FString::Printf(TEXT("Spawn count variable '%s' must exist on the data channel and be int."), *SpawnCountVariable.ToString());
			return false;
		}

		if (!SetNDCSpawnDirectVariableSpecifier(*SpawnFunction, *CountVariable, OutError))
		{
			return false;
		}
		SpawnFunction->RefreshFromExternalChanges();
		ScratchPadScriptViewModel->ApplyChanges();
		return true;
	}

	bool GenerateNDCParticleSpawnReadModule(
		TSharedPtr<FNiagaraScratchPadScriptViewModel> ScratchPadScriptViewModel,
		UClass* ReaderClass,
		UNiagaraDataChannel* Channel,
		const FString& TargetNamespace,
		const FString& SpawnIndexAttribute,
		const FString& SpawnCountAttribute,
		FString& OutError)
	{
		using namespace UE::Niagara::Wizard;
		ScratchPadScriptViewModel->SetScriptName(FText::FromString(TEXT("Init Particle From NDC")));
		UNiagaraGraph* Graph = GetScratchPadGraph(ScratchPadScriptViewModel);
		if (!Graph || !ReaderClass || !Channel)
		{
			OutError = TEXT("Invalid scratch graph, Data Channel reader class, or channel.");
			return false;
		}

		const FString CleanNamespace = TargetNamespace.IsEmpty() ? TEXT("Particles") : TargetNamespace;
		const UEdGraphSchema_Niagara* GraphSchema = GetDefault<UEdGraphSchema_Niagara>();
		UNiagaraNodeParameterMapGet* MapGetNode = FindSingleNiagaraNodeByClassNameChecked<UNiagaraNodeParameterMapGet>(Graph, TEXT("NiagaraNodeParameterMapGet"));
		UNiagaraNodeParameterMapSet* MapSetNode = FindSingleNiagaraNodeByClassNameChecked<UNiagaraNodeParameterMapSet>(Graph, TEXT("NiagaraNodeParameterMapSet"));

		UNiagaraNodeFunctionCall* SpawnDataFunction = Utilities::CreateDataInterfaceFunctionNode(ReaderClass, FName(TEXT("GetNDCSpawnData")), Graph);
		UNiagaraNodeFunctionCall* ReadFunction = Utilities::CreateDataInterfaceFunctionNode(ReaderClass, FName(TEXT("Read")), Graph);
		if (!SpawnDataFunction || !ReadFunction)
		{
			OutError = TEXT("Failed to create Data Channel GetNDCSpawnData or Read function node.");
			return false;
		}

		const FNiagaraTypeDefinition ReaderType(ReaderClass);
		UEdGraphPin* DIPin = Utilities::AddReadParameterPin(ReaderType, FName(TEXT("Data Channel")), MapGetNode);
		SpawnDataFunction->AutowireNewNode(DIPin);
		ReadFunction->AutowireNewNode(DIPin);
		Utilities::SetDefaultBinding(Graph, DIPin->PinName, FName(TEXT("Emitter.SpawnDataChannel")));

		if (UEdGraphPin* EmitterIDInput = SpawnDataFunction->FindPin(FName(TEXT("Emitter ID")), EGPD_Input))
		{
			UEdGraphPin* EmitterIDPin = Utilities::AddReadParameterPin(FNiagaraTypeDefinition(FNiagaraEmitterID::StaticStruct()), FName(TEXT("Emitter ID")), MapGetNode);
			GraphSchema->TryCreateConnection(EmitterIDPin, EmitterIDInput);
			Utilities::SetDefaultBinding(Graph, EmitterIDPin->PinName, SYS_PARAM_ENGINE_EMITTER_ID.GetName());
		}

		UNiagaraNodeOp* ExecIndexNode = Utilities::CreateOpNode(FName(TEXT("Util::ExecIndex")), Graph);
		if (ExecIndexNode && ExecIndexNode->Pins.Num() > 0)
		{
			if (UEdGraphPin* ExecIndexInput = SpawnDataFunction->FindPin(FName(TEXT("Spawned Particle Exec Index")), EGPD_Input))
			{
				GraphSchema->TryCreateConnection(ExecIndexNode->Pins[0], ExecIndexInput);
			}
		}

		GraphSchema->TryCreateConnection(SpawnDataFunction->GetOutputPin(0), ReadFunction->GetInputPin(1));

		UEdGraphPin* SuccessVarPin = Utilities::AddWriteParameterPin(FNiagaraTypeDefinition::GetBoolDef(), FName(CleanNamespace + TEXT(".ReadSuccess")), MapSetNode);
		if (UEdGraphPin* SuccessOutPin = ReadFunction->GetOutputPin(0))
		{
			GraphSchema->TryCreateConnection(SuccessOutPin, SuccessVarPin);
		}

		if (!SpawnIndexAttribute.IsEmpty())
		{
			UEdGraphPin* SpawnIndexOutPin = SpawnDataFunction->FindPin(FName(TEXT("NDC Spawn Index")), EGPD_Output);
			UEdGraphPin* SpawnIndexSetPin = Utilities::AddWriteParameterPin(FNiagaraTypeDefinition::GetIntDef(), FName(*SpawnIndexAttribute), MapSetNode);
			if (SpawnIndexOutPin && SpawnIndexSetPin)
			{
				GraphSchema->TryCreateConnection(SpawnIndexOutPin, SpawnIndexSetPin);
			}
		}
		if (!SpawnCountAttribute.IsEmpty())
		{
			UEdGraphPin* SpawnCountOutPin = SpawnDataFunction->FindPin(FName(TEXT("NDC Spawn Count")), EGPD_Output);
			UEdGraphPin* SpawnCountSetPin = Utilities::AddWriteParameterPin(FNiagaraTypeDefinition::GetIntDef(), FName(*SpawnCountAttribute), MapSetNode);
			if (SpawnCountOutPin && SpawnCountSetPin)
			{
				GraphSchema->TryCreateConnection(SpawnCountOutPin, SpawnCountSetPin);
			}
		}

		for (const FNiagaraDataChannelVariable& Variable : Channel->GetVariables())
		{
			const FNiagaraTypeDefinition ScriptType = ToDataChannelScriptType(Variable.GetType());
			FNiagaraVariable SWCVariable(ScriptType, Variable.GetName());
			ReadFunction->Modify();
			ReadFunction->Signature.AddOutput(SWCVariable);
			const FEdGraphPinType ReadPinType = UEdGraphSchema_Niagara::TypeDefinitionToPinType(ScriptType);
			UEdGraphPin* ReadParamPin = ReadFunction->CreatePin(EGPD_Output, ReadPinType, SWCVariable.GetName());
			if (ReadParamPin)
			{
				ReadParamPin->bDefaultValueIsIgnored = true;
			}
			UEdGraphPin* SetVarPin = Utilities::AddWriteParameterPin(ScriptType, FName(CleanNamespace + TEXT(".") + Variable.GetName().ToString()), MapSetNode);
			if (ReadParamPin && SetVarPin)
			{
				GraphSchema->TryCreateConnection(ReadParamPin, SetVarPin);
			}
		}
		ScratchPadScriptViewModel->ApplyChanges();
		return true;
	}
}

bool FNiagaraSetDataChannelReaderAction::Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError)
{
	FString SystemPath;
	if (!GetRequiredString(Params, TEXT("system_path"), SystemPath, OutError))
	{
		return false;
	}
	FString ModuleName;
	if (!GetRequiredString(Params, TEXT("module_name"), ModuleName, OutError))
	{
		return false;
	}
	FString DataChannelPath;
	if (!GetRequiredString(Params, TEXT("data_channel_asset_path"), DataChannelPath, OutError))
	{
		return false;
	}

	const FString Stage = GetOptionalString(Params, TEXT("stage"), TEXT(""));
	if (!Stage.IsEmpty())
	{
		ENiagaraScriptUsage Usage;
		if (!ParseStage(Stage, Usage))
		{
			OutError = FString::Printf(TEXT("Invalid stage '%s'."), *Stage);
			return false;
		}
	}
	return true;
}

TSharedPtr<FJsonObject> FNiagaraSetDataChannelReaderAction::ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context)
{
	FString Error;
	FString SystemPath;
	GetRequiredString(Params, TEXT("system_path"), SystemPath, Error);
	UNiagaraSystem* System = LoadNiagaraSystemByPath(SystemPath, Error);
	if (!System)
	{
		return CreateErrorResponse(Error, TEXT("system_not_found"));
	}

	const FString DataChannelPath = GetJsonString(Params, TEXT("data_channel_asset_path"), TEXT(""));
	UNiagaraDataChannelAsset* DataChannelAsset = LoadObject<UNiagaraDataChannelAsset>(nullptr, *NormalizeAssetObjectPath(DataChannelPath));
	if (!DataChannelAsset || !DataChannelAsset->Get())
	{
		return CreateErrorResponse(FString::Printf(TEXT("Niagara Data Channel asset missing or invalid: %s"), *DataChannelPath), TEXT("data_channel_not_found"));
	}

	UClass* ReaderClass = ResolveDataChannelReadClass(Error);
	if (!ReaderClass)
	{
		return CreateErrorResponse(Error, TEXT("reader_class_not_found"));
	}

	const FString EmitterName = GetOptionalString(Params, TEXT("emitter_name"), TEXT(""));
	const FNiagaraEmitterHandle* Handle = ResolveEmitterHandle(*System, EmitterName, Error);
	if (!Handle)
	{
		return CreateErrorResponse(Error, TEXT("emitter_not_found"));
	}
	FVersionedNiagaraEmitterData* EmitterData = Handle->GetEmitterData();
	UNiagaraGraph* Graph = EmitterData ? GetEmitterGraph(*EmitterData) : nullptr;
	if (!EmitterData || !Graph)
	{
		return CreateErrorResponse(TEXT("Emitter has no editable Niagara graph."), TEXT("no_emitter_graph"));
	}

	const FString Stage = GetOptionalString(Params, TEXT("stage"), TEXT(""));
	const FString ModuleName = GetJsonString(Params, TEXT("module_name"), TEXT(""));
	FMCPNiagaraStackModuleData ModuleData;
	FString FindError;
	if (!FindUniqueModuleDataByName(Graph, ModuleName, Stage, ModuleData, FindError) || !ModuleData.Node)
	{
		return CreateErrorResponse(FindError, TEXT("module_not_found"));
	}

	const bool bReadCurrentFrame = GetOptionalBool(Params, TEXT("read_current_frame"), false);
	const bool bUpdateSourceEveryTick = GetOptionalBool(Params, TEXT("update_source_every_tick"), true);
	const bool bOnlySpawnOnceOnSubticks = GetOptionalBool(Params, TEXT("only_spawn_once_on_subticks"), false);

	System->Modify();
	Graph->Modify();
	ModuleData.Node->Modify();
	if (!SetDataChannelReaderOverrideOnModule(*ModuleData.Node, ReaderClass, DataChannelAsset, bReadCurrentFrame, bUpdateSourceEveryTick, bOnlySpawnOnceOnSubticks, Error))
	{
		return CreateErrorResponse(Error, TEXT("configure_reader_failed"));
	}

	Graph->NotifyGraphChanged();
	MarkNiagaraSystemEdited(*System, Context);

	TSharedPtr<FJsonObject> Result = MakeShared<FJsonObject>();
	Result->SetStringField(TEXT("system_path"), System->GetPathName());
	Result->SetStringField(TEXT("emitter_name"), Handle->GetName().ToString());
	Result->SetStringField(TEXT("stage"), Stage);
	Result->SetStringField(TEXT("module_name"), ModuleData.Node->GetFunctionName());
	Result->SetStringField(TEXT("data_channel_asset_path"), DataChannelAsset->GetPathName());
	Result->SetBoolField(TEXT("read_current_frame"), bReadCurrentFrame);
	Result->SetBoolField(TEXT("update_source_every_tick"), bUpdateSourceEveryTick);
	Result->SetBoolField(TEXT("only_spawn_once_on_subticks"), bOnlySpawnOnceOnSubticks);
	return CreateSuccessResponse(Result);
}
bool FNiagaraAddDataChannelSpawnHandlerAction::Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError)
{
	FString SystemPath;
	if (!GetRequiredString(Params, TEXT("system_path"), SystemPath, OutError))
	{
		return false;
	}
	FString DataChannelPath;
	if (!GetRequiredString(Params, TEXT("data_channel_asset_path"), DataChannelPath, OutError))
	{
		return false;
	}

	const FString IfExists = GetOptionalString(Params, TEXT("if_exists"), TEXT("skip"));
	if (!IfExists.Equals(TEXT("skip"), ESearchCase::IgnoreCase)
		&& !IfExists.Equals(TEXT("error"), ESearchCase::IgnoreCase)
		&& !IfExists.Equals(TEXT("append"), ESearchCase::IgnoreCase)
		&& !IfExists.Equals(TEXT("update"), ESearchCase::IgnoreCase))
	{
		OutError = TEXT("if_exists must be one of: skip, error, append, update.");
		return false;
	}

	const int32 MinCount = static_cast<int32>(GetOptionalNumber(Params, TEXT("min_count"), 0.0));
	const int32 MaxCount = static_cast<int32>(GetOptionalNumber(Params, TEXT("max_count"), 3.0));
	if (MinCount < 0 || MaxCount < MinCount)
	{
		OutError = TEXT("min_count must be >= 0 and max_count must be >= min_count.");
		return false;
	}
	return true;
}

TSharedPtr<FJsonObject> FNiagaraAddDataChannelSpawnHandlerAction::ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context)
{
	FString Error;
	FString SystemPath;
	FString DataChannelPath;
	GetRequiredString(Params, TEXT("system_path"), SystemPath, Error);
	GetRequiredString(Params, TEXT("data_channel_asset_path"), DataChannelPath, Error);

	UNiagaraSystem* System = LoadNiagaraSystemByPath(SystemPath, Error);
	if (!System)
	{
		return CreateErrorResponse(Error, TEXT("system_not_found"));
	}

	UNiagaraDataChannelAsset* DataChannelAsset = LoadObject<UNiagaraDataChannelAsset>(nullptr, *NormalizeAssetObjectPath(DataChannelPath));
	UNiagaraDataChannel* DataChannel = DataChannelAsset ? DataChannelAsset->Get() : nullptr;
	if (!DataChannelAsset || !DataChannel)
	{
		return CreateErrorResponse(FString::Printf(TEXT("Niagara Data Channel asset missing or invalid: %s"), *DataChannelPath), TEXT("data_channel_not_found"));
	}

	const FString EmitterName = GetOptionalString(Params, TEXT("emitter_name"), TEXT(""));
	const FNiagaraEmitterHandle* Handle = ResolveEmitterHandle(*System, EmitterName, Error);
	if (!Handle)
	{
		return CreateErrorResponse(Error, TEXT("emitter_not_found"));
	}
	FVersionedNiagaraEmitterData* EmitterData = Handle->GetEmitterData();
	UNiagaraGraph* Graph = EmitterData ? GetEmitterGraph(*EmitterData) : nullptr;
	if (!EmitterData || !Graph)
	{
		return CreateErrorResponse(TEXT("Emitter has no editable Niagara graph."), TEXT("no_emitter_graph"));
	}

	UNiagaraNodeOutput* EmitterSpawnOutput = FindOutputNodeForUsage(Graph, ENiagaraScriptUsage::EmitterSpawnScript);
	UNiagaraNodeOutput* EmitterUpdateOutput = FindOutputNodeForUsage(Graph, ENiagaraScriptUsage::EmitterUpdateScript);
	UNiagaraNodeOutput* ParticleSpawnOutput = FindOutputNodeForUsage(Graph, ENiagaraScriptUsage::ParticleSpawnScript);
	if (!EmitterSpawnOutput || !EmitterUpdateOutput || !ParticleSpawnOutput)
	{
		return CreateErrorResponse(TEXT("Emitter must have emitter_spawn, emitter_update, and particle_spawn output nodes."), TEXT("missing_output_node"));
	}

	UClass* ReaderClass = ResolveDataChannelReadClass(Error);
	if (!ReaderClass)
	{
		return CreateErrorResponse(Error, TEXT("reader_class_not_found"));
	}
	UEnum* SpawnModeEnum = ResolveDataChannelSpawnModeEnum(Error);
	if (!SpawnModeEnum)
	{
		return CreateErrorResponse(Error, TEXT("spawn_mode_enum_not_found"));
	}

	const FString SpawnCountVariableString = GetOptionalString(Params, TEXT("spawn_count_variable"), TEXT("DigitCount"));
	const FName SpawnCountVariable(*SpawnCountVariableString);
	const FNiagaraDataChannelVariable* CountVariable = DataChannel->GetVariables().FindByPredicate([SpawnCountVariable](const FNiagaraDataChannelVariable& Variable)
	{
		return Variable.GetName() == SpawnCountVariable;
	});
	if (!CountVariable || CountVariable->GetType() != FNiagaraTypeDefinition::GetIntDef())
	{
		return CreateErrorResponse(FString::Printf(TEXT("spawn_count_variable '%s' must be an int variable on the data channel."), *SpawnCountVariableString), TEXT("invalid_spawn_count_variable"));
	}

	const FString ModuleName = GetOptionalString(Params, TEXT("module_name"), TEXT("Spawn From Data Channel"));
	const FString TargetNamespace = GetOptionalString(Params, TEXT("target_namespace"), TEXT("Particles"));
	const FString SpawnIndexAttribute = GetOptionalString(Params, TEXT("spawn_index_attribute"), TEXT("Particles.NDCSpawnIndex"));
	const FString SpawnCountAttribute = GetOptionalString(Params, TEXT("spawn_count_attribute"), TEXT("Particles.NDCSpawnCount"));
	const FString IfExists = GetOptionalString(Params, TEXT("if_exists"), TEXT("skip"));
	// GameplayBurst 会在发布数据的当前帧拉起系统；默认同帧读取，避免新组件错过刚发布的数据。
	const bool bReadCurrentFrame = GetOptionalBool(Params, TEXT("read_current_frame"), true);
	const bool bUpdateSourceEveryTick = GetOptionalBool(Params, TEXT("update_source_every_tick"), true);
	const bool bOnlySpawnOnceOnSubticks = GetOptionalBool(Params, TEXT("only_spawn_once_on_subticks"), false);
	const bool bOpenEditor = GetOptionalBool(Params, TEXT("open_editor"), true);
	const bool bFocusEditor = GetOptionalBool(Params, TEXT("focus_editor"), false);
	const int32 MinCount = FMath::Max(0, static_cast<int32>(GetOptionalNumber(Params, TEXT("min_count"), 0.0)));
	const int32 MaxCount = FMath::Max(MinCount, static_cast<int32>(GetOptionalNumber(Params, TEXT("max_count"), 3.0)));

	UNiagaraNodeFunctionCall* ExistingInitModule = FindModuleNodeByName(Graph, TEXT("Init_data_channel"));
	if (!ExistingInitModule)
	{
		ExistingInitModule = FindModuleNodeByName(Graph, TEXT("Init data channel"));
	}
	UNiagaraNodeFunctionCall* ExistingSpawnModule = FindModuleNodeByName(Graph, ModuleName);
	int32 SpawnDirectModuleMatchCount = ExistingSpawnModule ? 1 : 0;
	bool bSpawnModuleAutoDetected = false;
	if (!ExistingSpawnModule)
	{
		ExistingSpawnModule = FindUniqueNDCSpawnDirectModuleInEmitterUpdateStack(Graph, SpawnDirectModuleMatchCount);
		bSpawnModuleAutoDetected = ExistingSpawnModule != nullptr;
	}
	UNiagaraNodeFunctionCall* ExistingParticleModule = FindModuleNodeByName(Graph, TEXT("Init_Particle_From_NDC"));
	if (!ExistingParticleModule)
	{
		ExistingParticleModule = FindModuleNodeByName(Graph, TEXT("Init Particle From NDC"));
	}
	const bool bHasExistingModules = ExistingInitModule != nullptr
		|| ExistingSpawnModule != nullptr
		|| ExistingParticleModule != nullptr;
	if (bHasExistingModules && !IfExists.Equals(TEXT("append"), ESearchCase::IgnoreCase))
	{
		if (IfExists.Equals(TEXT("error"), ESearchCase::IgnoreCase))
		{
			return CreateErrorResponse(TEXT("One or more NDC spawn handler modules already exist on this emitter."), TEXT("modules_already_exist"));
		}
		if (IfExists.Equals(TEXT("update"), ESearchCase::IgnoreCase))
		{
			if (!ExistingSpawnModule && SpawnDirectModuleMatchCount > 1)
			{
				return CreateErrorResponse(
					TEXT("Multiple emitter update scratch modules contain SpawnDirect; pass module_name to choose the intended NDC spawn module."),
					TEXT("ambiguous_spawn_direct_module"));
			}

			TSharedPtr<FNiagaraSystemViewModel> UpdateSystemViewModel = OpenNiagaraSystemViewModelForEdit(System, true, bFocusEditor, Error);
			if (!UpdateSystemViewModel.IsValid())
			{
				return CreateErrorResponse(Error, TEXT("view_model_not_found_for_update"));
			}
			UNiagaraScratchPadViewModel* ScratchPadViewModel = UpdateSystemViewModel->GetScriptScratchPadViewModel();
			if (!ScratchPadViewModel)
			{
				return CreateErrorResponse(TEXT("Niagara scratch pad ViewModel is unavailable for existing module update."), TEXT("scratch_pad_view_model_not_found"));
			}

			auto GetScratchPadEditScriptForModule = [&](UNiagaraNodeFunctionCall* ModuleNode, TSharedPtr<FNiagaraScratchPadScriptViewModel>& OutScratchPadScriptViewModel) -> UNiagaraScript*
			{
				OutScratchPadScriptViewModel.Reset();
				if (!ModuleNode)
				{
					return nullptr;
				}
				OutScratchPadScriptViewModel = ScratchPadViewModel->GetViewModelForScript(ModuleNode->FunctionScript);
				if (!OutScratchPadScriptViewModel.IsValid())
				{
					Error = FString::Printf(TEXT("Scratch pad ViewModel was not found for module '%s'."), *ModuleNode->GetFunctionName());
					return nullptr;
				}
				return OutScratchPadScriptViewModel->GetEditScript().Script;
			};

			TSharedPtr<FNiagaraScratchPadScriptViewModel> SpawnScratchPadScriptViewModel;
			UNiagaraScript* SpawnEditScript = GetScratchPadEditScriptForModule(ExistingSpawnModule, SpawnScratchPadScriptViewModel);
			if (ExistingSpawnModule && !SpawnEditScript)
			{
				return CreateErrorResponse(Error, TEXT("spawn_scratch_pad_script_not_found"));
			}
			TSharedPtr<FNiagaraScratchPadScriptViewModel> ParticleScratchPadScriptViewModel;
			UNiagaraScript* ParticleEditScript = GetScratchPadEditScriptForModule(ExistingParticleModule, ParticleScratchPadScriptViewModel);
			if (ExistingParticleModule && !ParticleEditScript)
			{
				return CreateErrorResponse(Error, TEXT("particle_scratch_pad_script_not_found"));
			}

			System->Modify();
			Graph->Modify();

			TArray<TSharedPtr<FJsonValue>> UpdatedModules;
			int32 RemovedSharedReaderOverrideCount = 0;
			auto UpdateReaderOnExistingModule = [&](UNiagaraNodeFunctionCall* ModuleNode, const bool bOwnsSharedReaderOverride) -> bool
			{
				if (!ModuleNode)
				{
					return true;
				}
				ModuleNode->Modify();
				if (bOwnsSharedReaderOverride)
				{
					if (!SetDataChannelReaderOverrideOnModule(*ModuleNode, ReaderClass, DataChannelAsset, bReadCurrentFrame, bUpdateSourceEveryTick, bOnlySpawnOnceOnSubticks, Error))
					{
						Error = FString::Printf(TEXT("%s: %s"), *ModuleNode->GetFunctionName(), *Error);
						return false;
					}
				}
				else
				{
					RemoveDataChannelReaderOverrideOnModule(*ModuleNode, RemovedSharedReaderOverrideCount);
				}
				UpdatedModules.Add(MakeShared<FJsonValueString>(ModuleNode->GetFunctionName()));
				return true;
			};

			if (!UpdateReaderOnExistingModule(ExistingInitModule, true))
			{
				return CreateErrorResponse(Error, TEXT("configure_init_reader_failed"));
			}
			if (!UpdateReaderOnExistingModule(ExistingSpawnModule, false))
			{
				return CreateErrorResponse(Error, TEXT("configure_spawn_reader_failed"));
			}
			if (!UpdateReaderOnExistingModule(ExistingParticleModule, false))
			{
				return CreateErrorResponse(Error, TEXT("configure_particle_reader_failed"));
			}

			int32 UpdatedParticleReadPinCount = 0;
			int32 RemovedParticleReadPinCount = 0;
			if (ExistingParticleModule && !ConfigureNDCParticleReadScriptGraph(ParticleEditScript, ExistingParticleModule->GetFunctionName(), ReaderClass, DataChannel, TargetNamespace, UpdatedParticleReadPinCount, RemovedParticleReadPinCount, Error))
			{
				return CreateErrorResponse(Error, TEXT("configure_particle_read_graph_failed"));
			}

			int32 UpdatedSpawnDefaultCount = 0;
			if (ExistingSpawnModule && !ConfigureNDCSpawnDirectScriptDefaults(SpawnEditScript, ExistingSpawnModule->GetFunctionName(), SpawnModeEnum, *CountVariable, MinCount, MaxCount, UpdatedSpawnDefaultCount, Error))
			{
				return CreateErrorResponse(Error, TEXT("configure_spawn_defaults_failed"));
			}

			int32 AppliedScratchPadChangeCount = 0;
			if (SpawnScratchPadScriptViewModel.IsValid())
			{
				SpawnScratchPadScriptViewModel->ApplyChanges();
				++AppliedScratchPadChangeCount;
			}
			if (ParticleScratchPadScriptViewModel.IsValid() && ParticleScratchPadScriptViewModel != SpawnScratchPadScriptViewModel)
			{
				ParticleScratchPadScriptViewModel->ApplyChanges();
				++AppliedScratchPadChangeCount;
			}

			Graph->NotifyGraphChanged();
			MarkNiagaraSystemEdited(*System, Context);

			TSharedPtr<FJsonObject> Result = MakeShared<FJsonObject>();
			Result->SetStringField(TEXT("system_path"), System->GetPathName());
			Result->SetStringField(TEXT("emitter_name"), Handle->GetName().ToString());
			Result->SetStringField(TEXT("data_channel_asset_path"), DataChannelAsset->GetPathName());
			Result->SetBoolField(TEXT("skipped"), false);
			Result->SetBoolField(TEXT("updated_existing"), true);
			Result->SetArrayField(TEXT("updated_modules"), UpdatedModules);
			Result->SetNumberField(TEXT("removed_shared_reader_override_count"), RemovedSharedReaderOverrideCount);
			Result->SetBoolField(TEXT("read_current_frame"), bReadCurrentFrame);
			Result->SetBoolField(TEXT("update_source_every_tick"), bUpdateSourceEveryTick);
			Result->SetBoolField(TEXT("only_spawn_once_on_subticks"), bOnlySpawnOnceOnSubticks);
			Result->SetBoolField(TEXT("had_init_module"), ExistingInitModule != nullptr);
			Result->SetBoolField(TEXT("had_spawn_module"), ExistingSpawnModule != nullptr);
			Result->SetStringField(TEXT("spawn_module_name"), ExistingSpawnModule ? ExistingSpawnModule->GetFunctionName() : FString());
			Result->SetBoolField(TEXT("spawn_module_auto_detected"), bSpawnModuleAutoDetected);
			Result->SetNumberField(TEXT("spawn_direct_module_match_count"), SpawnDirectModuleMatchCount);
			Result->SetBoolField(TEXT("had_particle_module"), ExistingParticleModule != nullptr);
			Result->SetNumberField(TEXT("updated_spawn_default_count"), UpdatedSpawnDefaultCount);
			Result->SetNumberField(TEXT("updated_particle_read_pin_count"), UpdatedParticleReadPinCount);
			Result->SetNumberField(TEXT("removed_particle_read_pin_count"), RemovedParticleReadPinCount);
			Result->SetNumberField(TEXT("applied_scratch_pad_change_count"), AppliedScratchPadChangeCount);
			return CreateSuccessResponse(Result);
		}

		TSharedPtr<FJsonObject> Result = MakeShared<FJsonObject>();
		Result->SetStringField(TEXT("system_path"), System->GetPathName());
		Result->SetStringField(TEXT("emitter_name"), Handle->GetName().ToString());
		Result->SetStringField(TEXT("data_channel_asset_path"), DataChannelAsset->GetPathName());
		Result->SetBoolField(TEXT("skipped"), true);
		Result->SetBoolField(TEXT("updated_existing"), false);
		Result->SetStringField(TEXT("reason"), TEXT("modules_already_exist"));
		Result->SetBoolField(TEXT("had_init_module"), ExistingInitModule != nullptr);
		Result->SetBoolField(TEXT("had_spawn_module"), ExistingSpawnModule != nullptr);
		Result->SetStringField(TEXT("spawn_module_name"), ExistingSpawnModule ? ExistingSpawnModule->GetFunctionName() : FString());
		Result->SetBoolField(TEXT("spawn_module_auto_detected"), bSpawnModuleAutoDetected);
		Result->SetNumberField(TEXT("spawn_direct_module_match_count"), SpawnDirectModuleMatchCount);
		Result->SetBoolField(TEXT("had_particle_module"), ExistingParticleModule != nullptr);
		return CreateSuccessResponse(Result);
	}

	TSharedPtr<FNiagaraSystemViewModel> SystemViewModel = OpenNiagaraSystemViewModelForEdit(System, bOpenEditor, bFocusEditor, Error);
	if (!SystemViewModel.IsValid())
	{
		return CreateErrorResponse(Error, TEXT("view_model_not_found"));
	}

	System->Modify();
	Graph->Modify();

	TArray<TSharedPtr<FJsonValue>> CreatedModules;
	UNiagaraNodeFunctionCall* InitModule = CreateScratchNDCModule(
		SystemViewModel,
		EmitterSpawnOutput,
		INDEX_NONE,
		[ReaderClass](TSharedPtr<FNiagaraScratchPadScriptViewModel> ScratchPadScriptViewModel, FString& InOutError)
		{
			return GenerateNDCEmitterSpawnModule(ScratchPadScriptViewModel, ReaderClass, InOutError);
		},
		Error);
	if (!InitModule)
	{
		return CreateErrorResponse(Error, TEXT("create_init_module_failed"));
	}
	if (!SetDataChannelReaderOverrideOnModule(*InitModule, ReaderClass, DataChannelAsset, bReadCurrentFrame, bUpdateSourceEveryTick, bOnlySpawnOnceOnSubticks, Error))
	{
		return CreateErrorResponse(Error, TEXT("configure_reader_failed"));
	}
	CreatedModules.Add(MakeShared<FJsonValueString>(InitModule->GetFunctionName()));

	UNiagaraNodeFunctionCall* SpawnModule = CreateScratchNDCModule(
		SystemViewModel,
		EmitterUpdateOutput,
		INDEX_NONE,
		[ReaderClass, SpawnModeEnum, DataChannel, ModuleName, SpawnCountVariable, MinCount, MaxCount](TSharedPtr<FNiagaraScratchPadScriptViewModel> ScratchPadScriptViewModel, FString& InOutError)
		{
			return GenerateNDCEmitterUpdateSpawnDirectModule(ScratchPadScriptViewModel, ReaderClass, SpawnModeEnum, DataChannel, ModuleName, SpawnCountVariable, MinCount, MaxCount, InOutError);
		},
		Error);
	if (!SpawnModule)
	{
		return CreateErrorResponse(Error, TEXT("create_spawn_module_failed"));
	}
	CreatedModules.Add(MakeShared<FJsonValueString>(SpawnModule->GetFunctionName()));

	UNiagaraNodeFunctionCall* ParticleModule = CreateScratchNDCModule(
		SystemViewModel,
		ParticleSpawnOutput,
		1,
		[ReaderClass, DataChannel, TargetNamespace, SpawnIndexAttribute, SpawnCountAttribute](TSharedPtr<FNiagaraScratchPadScriptViewModel> ScratchPadScriptViewModel, FString& InOutError)
		{
			return GenerateNDCParticleSpawnReadModule(ScratchPadScriptViewModel, ReaderClass, DataChannel, TargetNamespace, SpawnIndexAttribute, SpawnCountAttribute, InOutError);
		},
		Error);
	if (!ParticleModule)
	{
		return CreateErrorResponse(Error, TEXT("create_particle_read_module_failed"));
	}
	CreatedModules.Add(MakeShared<FJsonValueString>(ParticleModule->GetFunctionName()));

	Graph->NotifyGraphChanged();
	MarkNiagaraSystemEdited(*System, Context);

	TSharedPtr<FJsonObject> Result = MakeShared<FJsonObject>();
	Result->SetStringField(TEXT("system_path"), System->GetPathName());
	Result->SetStringField(TEXT("emitter_name"), Handle->GetName().ToString());
	Result->SetStringField(TEXT("data_channel_asset_path"), DataChannelAsset->GetPathName());
	Result->SetStringField(TEXT("spawn_count_variable"), SpawnCountVariable.ToString());
	Result->SetStringField(TEXT("target_namespace"), TargetNamespace);
	Result->SetStringField(TEXT("spawn_index_attribute"), SpawnIndexAttribute);
	Result->SetStringField(TEXT("spawn_count_attribute"), SpawnCountAttribute);
	Result->SetBoolField(TEXT("read_current_frame"), bReadCurrentFrame);
	Result->SetBoolField(TEXT("update_source_every_tick"), bUpdateSourceEveryTick);
	Result->SetBoolField(TEXT("only_spawn_once_on_subticks"), bOnlySpawnOnceOnSubticks);
	Result->SetNumberField(TEXT("min_count"), MinCount);
	Result->SetNumberField(TEXT("max_count"), MaxCount);
	Result->SetArrayField(TEXT("created_modules"), CreatedModules);
	return CreateSuccessResponse(Result);
}
bool FNiagaraCreateDataChannelAction::Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError)
{
	FString AssetPath;
	if (!GetRequiredString(Params, TEXT("asset_path"), AssetPath, OutError))
	{
		return false;
	}
	const FString PackagePath = NormalizePackagePathFromAssetPath(AssetPath);
	if (!FPackageName::IsValidLongPackageName(PackagePath))
	{
		OutError = FString::Printf(TEXT("Invalid asset_path '%s'. Expected a long package path such as /Game/FX/NDC/MyDataChannel."), *AssetPath);
		return false;
	}

	const TArray<TSharedPtr<FJsonValue>>* Variables = GetOptionalArray(Params, TEXT("variables"));
	if (!Variables || Variables->Num() == 0)
	{
		OutError = TEXT("variables must be a non-empty array of {name,type} objects.");
		return false;
	}

	FString NormalizedClass;
	FString ClassError;
	ResolveDataChannelClass(GetOptionalString(Params, TEXT("channel_class"), TEXT("gameplay_burst")), NormalizedClass, ClassError);
	if (!ClassError.IsEmpty())
	{
		OutError = ClassError;
		return false;
	}

	const FString IfExists = GetOptionalString(Params, TEXT("if_exists"), TEXT("update"));
	if (!IfExists.Equals(TEXT("update"), ESearchCase::IgnoreCase) && !IfExists.Equals(TEXT("reuse"), ESearchCase::IgnoreCase) && !IfExists.Equals(TEXT("error"), ESearchCase::IgnoreCase))
	{
		OutError = TEXT("if_exists must be one of: update, reuse, error.");
		return false;
	}
	return true;
}

TSharedPtr<FJsonObject> FNiagaraCreateDataChannelAction::ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context)
{
	FString AssetPath;
	FString Error;
	GetRequiredString(Params, TEXT("asset_path"), AssetPath, Error);
	const FString ObjectPath = NormalizeAssetObjectPath(AssetPath);
	const FString PackagePath = NormalizePackagePathFromAssetPath(AssetPath);
	const FString AssetName = FPackageName::GetLongPackageAssetName(PackagePath);
	const FString IfExists = GetOptionalString(Params, TEXT("if_exists"), TEXT("update"));
	const float CellSize = FMath::Max(1.0f, static_cast<float>(GetOptionalNumber(Params, TEXT("cell_size"), 2500.0)));
	const float BoundsPadding = FMath::Max(0.0f, static_cast<float>(GetOptionalNumber(Params, TEXT("bounds_padding"), 500.0)));
	const bool bKeepPreviousFrameData = GetOptionalBool(Params, TEXT("keep_previous_frame_data"), true);
	const TArray<TSharedPtr<FJsonValue>>* VariableValues = GetOptionalArray(Params, TEXT("variables"));

	FString NormalizedClass;
	UClass* ChannelClass = ResolveDataChannelClass(GetOptionalString(Params, TEXT("channel_class"), TEXT("gameplay_burst")), NormalizedClass, Error);
	if (!ChannelClass)
	{
		return CreateErrorResponse(Error, TEXT("invalid_channel_class"));
	}

	UNiagaraDataChannelAsset* Asset = LoadObject<UNiagaraDataChannelAsset>(nullptr, *ObjectPath);
	bool bCreated = false;
	if (!Asset)
	{
		if (IfExists.Equals(TEXT("reuse"), ESearchCase::IgnoreCase))
		{
			return CreateErrorResponse(FString::Printf(TEXT("Niagara Data Channel asset does not exist: %s"), *PackagePath), TEXT("asset_not_found"));
		}

		UPackage* Package = CreatePackage(*PackagePath);
		if (!Package)
		{
			return CreateErrorResponse(FString::Printf(TEXT("Failed to create package: %s"), *PackagePath), TEXT("package_creation_failed"));
		}
		Package->FullyLoad();

		Asset = NewObject<UNiagaraDataChannelAsset>(Package, *AssetName, RF_Public | RF_Standalone | RF_Transactional);
		if (!Asset)
		{
			return CreateErrorResponse(TEXT("Failed to create UNiagaraDataChannelAsset."), TEXT("asset_creation_failed"));
		}
		FAssetRegistryModule::AssetCreated(Asset);
		bCreated = true;
	}
	else if (IfExists.Equals(TEXT("error"), ESearchCase::IgnoreCase))
	{
		return CreateErrorResponse(FString::Printf(TEXT("Asset already exists: %s"), *PackagePath), TEXT("asset_exists"));
	}

	Asset->Modify();
	UNiagaraDataChannel* Channel = Asset->Get();
	if (!Channel || Channel->GetClass() != ChannelClass)
	{
		UNiagaraDataChannel* NewChannel = NewObject<UNiagaraDataChannel>(Asset, ChannelClass, NAME_None, RF_Transactional);
		if (!SetObjectPropertyValue(Asset, UNiagaraDataChannelAsset::StaticClass(), TEXT("DataChannel"), NewChannel, Error))
		{
			return CreateErrorResponse(Error, TEXT("set_data_channel_failed"));
		}
		Channel = NewChannel;
	}

	Channel->Modify();
	if (!BeginDataChannelSchemaEdit(Channel, Error))
	{
		return CreateErrorResponse(Error, TEXT("begin_schema_edit_failed"));
	}
	if (!ConfigureDataChannelVariablesFromJson(Channel, *VariableValues, Error))
	{
		return CreateErrorResponse(Error, TEXT("configure_variables_failed"));
	}
	if (!SetBoolPropertyValue(Channel, UNiagaraDataChannel::StaticClass(), TEXT("bKeepPreviousFrameData"), bKeepPreviousFrameData, Error))
	{
		return CreateErrorResponse(Error, TEXT("set_keep_previous_frame_data_failed"));
	}

	if (Channel->IsA<UNiagaraDataChannel_GameplayBurst>())
	{
		if (!SetVectorPropertyValue(Channel, UNiagaraDataChannel_GameplayBurst::StaticClass(), TEXT("CellSize"), FVector(CellSize), Error))
		{
			return CreateErrorResponse(Error, TEXT("set_cell_size_failed"));
		}
		if (!SetVectorPropertyValue(Channel, UNiagaraDataChannel_GameplayBurst::StaticClass(), TEXT("SystemBoundsPadding"), FVector(BoundsPadding), Error))
		{
			return CreateErrorResponse(Error, TEXT("set_bounds_padding_failed"));
		}
	}

	const FString DefaultSystemPath = GetOptionalString(Params, TEXT("default_system_to_spawn"), TEXT(""));
	bool bDefaultSystemMissing = false;
	if (!DefaultSystemPath.IsEmpty() && Channel->IsA<UNiagaraDataChannel_MapBase>())
	{
		UObject* DefaultSystem = LoadObject<UObject>(nullptr, *NormalizeAssetObjectPath(DefaultSystemPath));
		bDefaultSystemMissing = (DefaultSystem == nullptr);
		if (DefaultSystem)
		{
			if (!SetObjectPropertyValue(Channel, UNiagaraDataChannel_MapBase::StaticClass(), TEXT("DefaultSystemToSpawn"), DefaultSystem, Error))
			{
				return CreateErrorResponse(Error, TEXT("set_default_system_failed"));
			}
		}
	}

	if (!FinishDataChannelSchemaEdit(Channel, Error))
	{
		return CreateErrorResponse(Error, TEXT("refresh_layout_failed"));
	}

	Asset->MarkPackageDirty();
	if (UPackage* Package = Asset->GetOutermost())
	{
		Context.MarkPackageDirty(Package);
	}

	TArray<TSharedPtr<FJsonValue>> VariableArray;
	for (const FNiagaraDataChannelVariable& Variable : Channel->GetVariables())
	{
		VariableArray.Add(MakeShared<FJsonValueObject>(MakeDataChannelVariableJson(Variable)));
	}

	TSharedPtr<FJsonObject> Result = MakeShared<FJsonObject>();
	Result->SetStringField(TEXT("asset_path"), PackagePath);
	Result->SetStringField(TEXT("object_path"), Asset->GetPathName());
	Result->SetStringField(TEXT("channel_class"), Channel->GetClass()->GetName());
	Result->SetStringField(TEXT("channel_class_param"), NormalizedClass);
	Result->SetBoolField(TEXT("created"), bCreated);
	Result->SetNumberField(TEXT("cell_size"), CellSize);
	Result->SetNumberField(TEXT("bounds_padding"), BoundsPadding);
	Result->SetBoolField(TEXT("keep_previous_frame_data"), bKeepPreviousFrameData);
	Result->SetStringField(TEXT("default_system_to_spawn"), DefaultSystemPath);
	Result->SetBoolField(TEXT("default_system_missing"), bDefaultSystemMissing);
	Result->SetArrayField(TEXT("variables"), VariableArray);
	return CreateSuccessResponse(Result);
}

bool FNiagaraWriteDataChannelTestAction::Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError)
{
	FString AssetPath;
	if (!GetRequiredString(Params, TEXT("asset_path"), AssetPath, OutError))
	{
		return false;
	}
	const FString PackagePath = NormalizePackagePathFromAssetPath(AssetPath);
	if (!FPackageName::IsValidLongPackageName(PackagePath))
	{
		OutError = FString::Printf(TEXT("Invalid asset_path '%s'."), *AssetPath);
		return false;
	}
	return true;
}

TSharedPtr<FJsonObject> FNiagaraWriteDataChannelTestAction::ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context)
{
	FString AssetPath;
	FString Error;
	GetRequiredString(Params, TEXT("asset_path"), AssetPath, Error);
	UNiagaraDataChannelAsset* Asset = LoadObject<UNiagaraDataChannelAsset>(nullptr, *NormalizeAssetObjectPath(AssetPath));
	UNiagaraDataChannel* Channel = Asset ? Asset->Get() : nullptr;
	if (!Asset || !Channel)
	{
		return CreateErrorResponse(FString::Printf(TEXT("Niagara Data Channel asset missing or invalid: %s"), *AssetPath), TEXT("asset_not_found"));
	}

	UWorld* World = ResolveRuntimeOrEditorWorld();
	if (!World)
	{
		return CreateErrorResponse(TEXT("No editor/runtime world available."), TEXT("no_world"));
	}

	TArray<TSharedPtr<FJsonObject>> Rows;
	const TArray<TSharedPtr<FJsonValue>>* EntryValues = nullptr;
	if (Params->TryGetArrayField(TEXT("entries"), EntryValues) && EntryValues)
	{
		for (const TSharedPtr<FJsonValue>& EntryValue : *EntryValues)
		{
			const TSharedPtr<FJsonObject>* EntryObject = nullptr;
			if (EntryValue.IsValid() && EntryValue->TryGetObject(EntryObject) && EntryObject && EntryObject->IsValid())
			{
				Rows.Add(*EntryObject);
			}
		}
	}
	else
	{
		const TSharedPtr<FJsonObject>* ValuesObject = nullptr;
		if (Params->TryGetObjectField(TEXT("values"), ValuesObject) && ValuesObject && ValuesObject->IsValid())
		{
			Rows.Add(*ValuesObject);
		}
	}

	if (Rows.Num() == 0)
	{
		return CreateErrorResponse(TEXT("Pass entries:[{...}] or values:{...} with data channel variable values."), TEXT("missing_entries"));
	}

	FVector ContextLocation = GetJsonVector3OrDefault(Params, TEXT("context_location"), FVector::ZeroVector);
	if (ContextLocation.IsNearlyZero())
	{
		TSharedPtr<FJsonValue> PositionValue = Rows[0]->TryGetField(TEXT("Position"));
		if (PositionValue.IsValid())
		{
			TryReadJsonVector3Value(PositionValue, ContextLocation);
		}
	}

	const float CellSize = FMath::Max(1.0f, static_cast<float>(GetOptionalNumber(Params, TEXT("cell_size"), 2500.0)));
	const float BoundsPadding = FMath::Max(0.0f, static_cast<float>(GetOptionalNumber(Params, TEXT("bounds_padding"), 500.0)));
	const bool bFindDataBeforeWrite = GetOptionalBool(Params, TEXT("find_data_before_write"), false);
	const bool bFindDataAfterWrite = !Params->HasField(TEXT("find_data_after_write")) || Params->GetBoolField(TEXT("find_data_after_write"));
	const bool bFlushPublishRequests = GetOptionalBool(Params, TEXT("flush_publish_requests"), false);
	const bool bAdvanceSpawnedComponents = GetOptionalBool(Params, TEXT("advance_spawned_components"), false);
	const bool bAdvanceMatchingComponents = GetOptionalBool(Params, TEXT("advance_matching_components"), false);
	const bool bActivateAdvancedComponents = !Params->HasField(TEXT("activate_advanced_components")) || Params->GetBoolField(TEXT("activate_advanced_components"));
	const bool bResetAdvancedComponents = !Params->HasField(TEXT("reset_advanced_components")) || Params->GetBoolField(TEXT("reset_advanced_components"));
	const int32 AdvanceTickCount = FMath::Max(1, static_cast<int32>(GetOptionalNumber(Params, TEXT("tick_count"), 1.0)));
	const float AdvanceTickDeltaSeconds = FMath::Max(KINDA_SMALL_NUMBER, static_cast<float>(GetOptionalNumber(Params, TEXT("tick_delta_seconds"), 1.0 / 60.0)));
	UNiagaraDataChannel_MapBase* MapChannel = Cast<UNiagaraDataChannel_MapBase>(Channel);
	UObject* DefaultSystemToSpawn = MapChannel ? MapChannel->GetDefaultSystemToSpawn() : nullptr;

	UObject* ContextSystemToSpawn = nullptr;
	const FString SystemToSpawnPath = GetOptionalString(Params, TEXT("system_to_spawn"), TEXT(""));
	if (!SystemToSpawnPath.IsEmpty())
	{
		ContextSystemToSpawn = LoadObject<UObject>(nullptr, *NormalizeAssetObjectPath(SystemToSpawnPath));
		if (!ContextSystemToSpawn)
		{
			return CreateErrorResponse(FString::Printf(TEXT("system_to_spawn asset not found: %s"), *SystemToSpawnPath), TEXT("system_to_spawn_not_found"));
		}
	}
	else if (GetOptionalBool(Params, TEXT("override_default_system_to_spawn"), false))
	{
		ContextSystemToSpawn = DefaultSystemToSpawn;
		if (!ContextSystemToSpawn)
		{
			return CreateErrorResponse(TEXT("override_default_system_to_spawn was requested, but the data channel has no DefaultSystemToSpawn."), TEXT("default_system_to_spawn_missing"));
		}
	}

	FNDCAccessContextInst& AccessContext = Channel->GetTransientAccessContext();
	ConfigureDataChannelWriteContext(AccessContext, ContextLocation, CellSize, BoundsPadding, ContextSystemToSpawn);

	UNiagaraDataChannelHandler* DebugHandler = FindDataChannelHandlerInWorld(World, Channel);
	FNiagaraDataChannelDataPtr DebugDataBeforeWrite;
	TArray<UNiagaraComponent*> SpawnedComponentsAfterPrewarm;
	if (bFindDataBeforeWrite && DebugHandler)
	{
		DebugDataBeforeWrite = DebugHandler->FindData(AccessContext, ENiagaraResourceAccess::ReadOnly);
		CollectAccessContextSpawnedComponents(AccessContext, SpawnedComponentsAfterPrewarm);
	}

	UNiagaraDataChannelWriter* Writer = UNiagaraDataChannelLibrary::WriteToNiagaraDataChannel_WithContext(
		World,
		Asset,
		AccessContext,
		Rows.Num(),
		/*bVisibleToBlueprint*/ true,
		/*bVisibleToNiagaraCPU*/ true,
		/*bVisibleToNiagaraGPU*/ false,
		TEXT("MCP.NiagaraDataChannelTest"));
	if (!Writer)
	{
		return CreateErrorResponse(TEXT("Failed to create Niagara Data Channel writer."), TEXT("writer_failed"));
	}

	int32 ValuesWritten = 0;
	for (int32 RowIndex = 0; RowIndex < Rows.Num(); ++RowIndex)
	{
		const TSharedPtr<FJsonObject>& Row = Rows[RowIndex];
		for (const FNiagaraDataChannelVariable& Variable : Channel->GetVariables())
		{
			const FString VariableName = Variable.GetName().ToString();
			TSharedPtr<FJsonValue> Value = Row->TryGetField(VariableName);
			if (!Value.IsValid())
			{
				continue;
			}
			if (!WriteDataChannelValue(*Writer, Variable, RowIndex, Value, Error))
			{
				return CreateErrorResponse(Error, TEXT("invalid_value"));
			}
			++ValuesWritten;
		}
	}

	TArray<UNiagaraComponent*> SpawnedComponentsAfterWrite;
	CollectAccessContextSpawnedComponents(AccessContext, SpawnedComponentsAfterWrite);

	FNiagaraDataChannelDataPtr DebugDataAfterWrite;
	if (!DebugHandler)
	{
		DebugHandler = FindDataChannelHandlerInWorld(World, Channel);
	}
	const bool bNeedAfterWriteData = bFindDataAfterWrite || bFlushPublishRequests;
	if (bNeedAfterWriteData && DebugHandler)
	{
		DebugDataAfterWrite = DebugHandler->FindData(AccessContext, ENiagaraResourceAccess::ReadOnly);
	}
	TSharedPtr<FJsonObject> AfterWriteCountsSnapshot = MakeShared<FJsonObject>();
	AppendDataChannelDataCounts(AfterWriteCountsSnapshot, TEXT(""), DebugDataAfterWrite);

	int32 FlushedPublishRequests = -1;
	if (bFlushPublishRequests && DebugHandler && DebugDataAfterWrite.IsValid())
	{
		FlushedPublishRequests = DebugDataAfterWrite->ConsumePublishRequests(DebugHandler, TG_LastDemotable);
	}
	FNiagaraDataChannelDataPtr DebugDataAfterFlush = DebugDataAfterWrite;
	TSharedPtr<FJsonObject> AfterFlushCountsSnapshot = MakeShared<FJsonObject>();
	AppendDataChannelDataCounts(AfterFlushCountsSnapshot, TEXT(""), DebugDataAfterFlush);

	UObject* SystemForMatching = ContextSystemToSpawn ? ContextSystemToSpawn : DefaultSystemToSpawn;
	TArray<UNiagaraComponent*> MatchingComponentsAfterWrite;
	CollectMatchingNiagaraComponents(World, SystemForMatching, MatchingComponentsAfterWrite);

	TArray<UNiagaraComponent*> ComponentsToAdvance;
	if (bAdvanceSpawnedComponents)
	{
		ComponentsToAdvance.Append(SpawnedComponentsAfterPrewarm);
		ComponentsToAdvance.Append(SpawnedComponentsAfterWrite);
	}
	if (bAdvanceMatchingComponents)
	{
		ComponentsToAdvance.Append(MatchingComponentsAfterWrite);
	}
	for (int32 Index = ComponentsToAdvance.Num() - 1; Index >= 0; --Index)
	{
		if (!IsValid(ComponentsToAdvance[Index]) || ComponentsToAdvance.Find(ComponentsToAdvance[Index]) != Index)
		{
			ComponentsToAdvance.RemoveAt(Index);
		}
	}

	TArray<UNiagaraComponent*> AdvancedComponents;
	if (ComponentsToAdvance.Num() > 0)
	{
		AdvanceNiagaraComponentsForDiagnostics(
			ComponentsToAdvance,
			AdvanceTickCount,
			AdvanceTickDeltaSeconds,
			bActivateAdvancedComponents,
			bResetAdvancedComponents,
			AdvancedComponents);
	}

	TSharedPtr<FJsonObject> Result = MakeShared<FJsonObject>();
	Result->SetStringField(TEXT("asset_path"), Asset->GetPathName());
	Result->SetStringField(TEXT("channel_class"), Channel->GetClass() ? Channel->GetClass()->GetName() : FString());
	Result->SetStringField(TEXT("default_system_to_spawn"), DefaultSystemToSpawn ? DefaultSystemToSpawn->GetPathName() : FString());
	Result->SetStringField(TEXT("requested_system_to_spawn"), SystemToSpawnPath);
	Result->SetBoolField(TEXT("override_default_system_to_spawn"), ContextSystemToSpawn == DefaultSystemToSpawn && ContextSystemToSpawn != nullptr);
	Result->SetNumberField(TEXT("rows_written"), Rows.Num());
	Result->SetNumberField(TEXT("values_written"), ValuesWritten);
	Result->SetArrayField(TEXT("context_location"), VectorToJsonArray(ContextLocation));
	Result->SetBoolField(TEXT("find_data_before_write"), bFindDataBeforeWrite);
	Result->SetBoolField(TEXT("find_data_after_write"), bFindDataAfterWrite);
	Result->SetBoolField(TEXT("flush_publish_requests"), bFlushPublishRequests);
	Result->SetNumberField(TEXT("flushed_publish_requests"), FlushedPublishRequests);
	Result->SetBoolField(TEXT("advance_spawned_components"), bAdvanceSpawnedComponents);
	Result->SetBoolField(TEXT("advance_matching_components"), bAdvanceMatchingComponents);
	Result->SetBoolField(TEXT("activate_advanced_components"), bActivateAdvancedComponents);
	Result->SetBoolField(TEXT("reset_advanced_components"), bResetAdvancedComponents);
	Result->SetNumberField(TEXT("tick_count"), AdvanceTickCount);
	Result->SetNumberField(TEXT("tick_delta_seconds"), AdvanceTickDeltaSeconds);
	Result->SetBoolField(TEXT("has_debug_handler"), DebugHandler != nullptr);
	Result->SetStringField(TEXT("debug_handler"), DebugHandler ? DebugHandler->GetPathName() : FString());
	AppendDataChannelDataCounts(Result, TEXT("before_write_"), DebugDataBeforeWrite);
	AppendDataChannelDataCounts(Result, TEXT("after_write_"), DebugDataAfterWrite);
	AppendDataChannelDataCounts(Result, TEXT("after_flush_"), DebugDataAfterFlush);
	Result->SetObjectField(TEXT("after_write_counts_snapshot"), AfterWriteCountsSnapshot);
	Result->SetObjectField(TEXT("after_flush_counts_snapshot"), AfterFlushCountsSnapshot);
	AppendNiagaraComponentArrayDiagnostics(Result, TEXT("spawned_after_prewarm_"), SpawnedComponentsAfterPrewarm);
	AppendNiagaraComponentArrayDiagnostics(Result, TEXT("spawned_after_write_"), SpawnedComponentsAfterWrite);
	AppendNiagaraComponentArrayDiagnostics(Result, TEXT("matching_after_write_"), MatchingComponentsAfterWrite);
	AppendNiagaraComponentArrayDiagnostics(Result, TEXT("advance_target_"), ComponentsToAdvance);
	AppendNiagaraComponentArrayDiagnostics(Result, TEXT("advanced_"), AdvancedComponents);
	AppendAccessContextDiagnostics(Result, AccessContext);
	return CreateSuccessResponse(Result);
}
