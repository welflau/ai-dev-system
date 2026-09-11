// Copyright (c) 2025 zolnoor. All rights reserved.

#include "Actions/EditorActions.h"
#include "MCPCommonUtils.h"
#include "Editor.h"
#include "EditorViewportClient.h"
#include "LevelEditorViewport.h"
#include "Engine/World.h"
#include "GameFramework/Actor.h"
#include "GameFramework/WorldSettings.h"
#include "Engine/StaticMeshActor.h"
#include "Engine/StaticMesh.h"
#include "Engine/DirectionalLight.h"
#include "Engine/PointLight.h"
#include "Engine/SpotLight.h"
#include "Components/StaticMeshComponent.h"
#include "Camera/CameraActor.h"
#include "Kismet/GameplayStatics.h"
#include "FileHelpers.h"
#include "UObject/SavePackage.h"
#include "AssetRegistry/AssetRegistryModule.h"
#include "UObject/Package.h"
#include "Engine/Blueprint.h"
#include "Engine/BlueprintGeneratedClass.h"
#include "Engine/SimpleConstructionScript.h"
#include "Engine/SCS_Node.h"
#include "EdGraphSchema_K2.h"
#include "K2Node_Event.h"
#include "K2Node_FunctionEntry.h"
#include "K2Node_CustomEvent.h"
#include "K2Node_CallFunction.h"
#include "K2Node_VariableGet.h"
#include "K2Node_VariableSet.h"
#include "AssetSelection.h"
#include "ObjectTools.h"
#include "Subsystems/AssetEditorSubsystem.h"
#include "Subsystems/EditorAssetSubsystem.h"
#include "AssetToolsModule.h"
#include "IAssetTools.h"
#include "EditorAssetLibrary.h"
#include "ImageUtils.h"
#include "UnrealClient.h"
#include "Misc/Base64.h"
#include "Misc/PackageName.h"
#include "MCPLogCapture.h"
#include "MCPBridge.h"
#include "UObject/ObjectRedirector.h"
#include "UObject/UnrealType.h"
#include "Async/Async.h"
#include "Containers/Ticker.h"
#include "HAL/PlatformMisc.h"
#include "HAL/PlatformProcess.h"
#include "Misc/DateTime.h"
#include "PlayInEditorDataTypes.h"
#include "Settings/LevelEditorPlaySettings.h"
#include "EngineUtils.h"
#include "Selection.h"
#include "Framework/Application/SlateApplication.h"
#include "Widgets/SWindow.h"
#include "GameFramework/PlayerController.h"
#include "InputCoreTypes.h"
#include "InputKeyEventArgs.h"
#include "Engine/Engine.h"
#include "Engine/EngineBaseTypes.h"
#include "Engine/DataTable.h"
#include "Blueprint/UserWidget.h"
#include "Components/Widget.h"
#include "GameplayEffect.h"
#include "GameplayEffectComponents/TargetTagsGameplayEffectComponent.h"
#include "GameplayEffectComponents/TargetTagRequirementsGameplayEffectComponent.h"
#include "GameplayTagContainer.h"
#include "HAL/FileManager.h"
#include "Misc/Paths.h"
#include "Misc/SecureHash.h"
#include "UObject/UObjectIterator.h"

#include <initializer_list>

namespace UEEditorMCP_DataAssetUtils
{
	static bool TryBuildLJCPackedChunkSummary(UObject* Asset, TSharedPtr<FJsonObject>& OutSummary, FString& OutError);
}

namespace UEEditorMCPBatch
{
	static TSharedPtr<FJsonValue> CloneJsonValue(const TSharedPtr<FJsonValue>& Value);

	static TSharedPtr<FJsonObject> CloneJsonObject(const TSharedPtr<FJsonObject>& Object)
	{
		TSharedPtr<FJsonObject> Clone = MakeShared<FJsonObject>();
		if (!Object.IsValid())
		{
			return Clone;
		}

		for (const auto& Field : Object->Values)
		{
			Clone->SetField(Field.Key.ToView(), CloneJsonValue(Field.Value));
		}
		return Clone;
	}

	static TSharedPtr<FJsonValue> CloneJsonValue(const TSharedPtr<FJsonValue>& Value)
	{
		if (!Value.IsValid())
		{
			return MakeShared<FJsonValueNull>();
		}

		switch (Value->Type)
		{
		case EJson::String:
			return MakeShared<FJsonValueString>(Value->AsString());
		case EJson::Number:
			return MakeShared<FJsonValueNumber>(Value->AsNumber());
		case EJson::Boolean:
			return MakeShared<FJsonValueBoolean>(Value->AsBool());
		case EJson::Array:
		{
			TArray<TSharedPtr<FJsonValue>> ClonedArray;
			for (const TSharedPtr<FJsonValue>& Entry : Value->AsArray())
			{
				ClonedArray.Add(CloneJsonValue(Entry));
			}
			return MakeShared<FJsonValueArray>(ClonedArray);
		}
		case EJson::Object:
			return MakeShared<FJsonValueObject>(CloneJsonObject(Value->AsObject()));
		case EJson::Null:
		default:
			return MakeShared<FJsonValueNull>();
		}
	}

	static bool ParseStepReference(const FString& RefPath, int32& OutIndex, FString& OutRemainder)
	{
		FString Ref = RefPath;
		Ref.TrimStartAndEndInline();
		if (Ref.StartsWith(TEXT("$.")))
		{
			Ref.RightChopInline(2, EAllowShrinking::No);
		}

		auto ParseBracketIndex = [&OutIndex, &OutRemainder](const FString& Input, const FString& Prefix) -> bool
		{
			if (!Input.StartsWith(Prefix))
			{
				return false;
			}
			const int32 Start = Prefix.Len();
			int32 End = INDEX_NONE;
			if (!Input.FindChar(TEXT(']'), End) || End <= Start)
			{
				return false;
			}
			const FString IndexText = Input.Mid(Start, End - Start);
			if (!IndexText.IsNumeric())
			{
				return false;
			}
			OutIndex = FCString::Atoi(*IndexText);
			OutRemainder = Input.Mid(End + 1);
			if (OutRemainder.StartsWith(TEXT(".")))
			{
				OutRemainder.RightChopInline(1, EAllowShrinking::No);
			}
			return true;
		};

		if (ParseBracketIndex(Ref, TEXT("steps[")) || ParseBracketIndex(Ref, TEXT("results[")))
		{
			return true;
		}

		int32 DotIndex = INDEX_NONE;
		const FString IndexText = Ref.FindChar(TEXT('.'), DotIndex) ? Ref.Left(DotIndex) : Ref;
		if (!IndexText.IsNumeric())
		{
			return false;
		}
		OutIndex = FCString::Atoi(*IndexText);
		OutRemainder = DotIndex == INDEX_NONE ? TEXT("") : Ref.Mid(DotIndex + 1);
		return true;
	}

	static bool ResolvePathSegments(TSharedPtr<FJsonValue> CurrentValue, const FString& Remainder, TSharedPtr<FJsonValue>& OutValue, FString& OutError)
	{
		FString Remaining = Remainder;
		while (!Remaining.IsEmpty())
		{
			FString Segment;
			const int32 DotIndex = Remaining.Find(TEXT("."));
			if (DotIndex == INDEX_NONE)
			{
				Segment = Remaining;
				Remaining.Empty();
			}
			else
			{
				Segment = Remaining.Left(DotIndex);
				Remaining = Remaining.Mid(DotIndex + 1);
			}

			while (!Segment.IsEmpty())
			{
				FString FieldName = Segment;
				FString ArraySuffix;
				const int32 BracketIndex = Segment.Find(TEXT("["));
				if (BracketIndex != INDEX_NONE)
				{
					FieldName = Segment.Left(BracketIndex);
					ArraySuffix = Segment.Mid(BracketIndex);
				}

				if (!FieldName.IsEmpty())
				{
					if (!CurrentValue.IsValid() || CurrentValue->Type != EJson::Object)
					{
						OutError = FString::Printf(TEXT("Cannot read field '%s' from non-object batch ref segment '%s'"), *FieldName, *Segment);
						return false;
					}
					const TSharedPtr<FJsonObject> CurrentObject = CurrentValue->AsObject();
					TSharedPtr<FJsonValue> FoundValue = CurrentObject->TryGetField(FieldName);
					if (!FoundValue.IsValid())
					{
						OutError = FString::Printf(TEXT("Batch ref field '%s' not found"), *FieldName);
						return false;
					}
					CurrentValue = FoundValue;
				}

				if (ArraySuffix.IsEmpty())
				{
					break;
				}

				if (!ArraySuffix.StartsWith(TEXT("[")))
				{
					OutError = FString::Printf(TEXT("Invalid batch ref array suffix '%s'"), *ArraySuffix);
					return false;
				}
				int32 CloseIndex = INDEX_NONE;
				if (!ArraySuffix.FindChar(TEXT(']'), CloseIndex) || CloseIndex <= 1)
				{
					OutError = FString::Printf(TEXT("Invalid batch ref array suffix '%s'"), *ArraySuffix);
					return false;
				}
				const FString ArrayIndexText = ArraySuffix.Mid(1, CloseIndex - 1);
				if (!ArrayIndexText.IsNumeric() || !CurrentValue.IsValid() || CurrentValue->Type != EJson::Array)
				{
					OutError = FString::Printf(TEXT("Cannot index batch ref segment '%s'"), *Segment);
					return false;
				}
				const int32 ArrayIndex = FCString::Atoi(*ArrayIndexText);
				const TArray<TSharedPtr<FJsonValue>>& Array = CurrentValue->AsArray();
				if (!Array.IsValidIndex(ArrayIndex))
				{
					OutError = FString::Printf(TEXT("Batch ref array index %d out of range"), ArrayIndex);
					return false;
				}
				CurrentValue = Array[ArrayIndex];
				ArraySuffix = ArraySuffix.Mid(CloseIndex + 1);
				Segment = ArraySuffix;
			}
		}

		OutValue = CloneJsonValue(CurrentValue);
		return true;
	}

	static bool ResolveStepReference(const FString& RefPath, const TArray<TSharedPtr<FJsonObject>>& StepResults, TSharedPtr<FJsonValue>& OutValue, FString& OutError)
	{
		int32 StepIndex = INDEX_NONE;
		FString Remainder;
		if (!ParseStepReference(RefPath, StepIndex, Remainder))
		{
			OutError = FString::Printf(TEXT("Invalid batch ref '%s'. Use steps[0].field, results[0].field, or 0.field"), *RefPath);
			return false;
		}
		if (!StepResults.IsValidIndex(StepIndex) || !StepResults[StepIndex].IsValid())
		{
			OutError = FString::Printf(TEXT("Batch ref step index %d is not available yet"), StepIndex);
			return false;
		}

		TSharedPtr<FJsonValue> CurrentValue = MakeShared<FJsonValueObject>(StepResults[StepIndex]);
		if (Remainder.IsEmpty())
		{
			OutValue = CloneJsonValue(CurrentValue);
			return true;
		}
		return ResolvePathSegments(CurrentValue, Remainder, OutValue, OutError);
	}

	static TSharedPtr<FJsonValue> ResolveJsonRefs(const TSharedPtr<FJsonValue>& Value, const TArray<TSharedPtr<FJsonObject>>& StepResults, FString& OutError);

	static TSharedPtr<FJsonObject> ResolveJsonRefsInObject(const TSharedPtr<FJsonObject>& Object, const TArray<TSharedPtr<FJsonObject>>& StepResults, FString& OutError)
	{
		TSharedPtr<FJsonObject> Resolved = MakeShared<FJsonObject>();
		if (!Object.IsValid())
		{
			return Resolved;
		}

		for (const auto& Field : Object->Values)
		{
			TSharedPtr<FJsonValue> ResolvedValue = ResolveJsonRefs(Field.Value, StepResults, OutError);
			if (!ResolvedValue.IsValid())
			{
				return nullptr;
			}
			Resolved->SetField(Field.Key.ToView(), ResolvedValue);
		}
		return Resolved;
	}

	static TSharedPtr<FJsonValue> ResolveJsonRefs(const TSharedPtr<FJsonValue>& Value, const TArray<TSharedPtr<FJsonObject>>& StepResults, FString& OutError)
	{
		if (!Value.IsValid())
		{
			return MakeShared<FJsonValueNull>();
		}

		if (Value->Type == EJson::Object)
		{
			const TSharedPtr<FJsonObject> Object = Value->AsObject();
			FString RefPath;
			if (Object.IsValid() && Object->Values.Num() == 1 && Object->TryGetStringField(TEXT("$ref"), RefPath))
			{
				TSharedPtr<FJsonValue> ResolvedValue;
				if (!ResolveStepReference(RefPath, StepResults, ResolvedValue, OutError))
				{
					return nullptr;
				}
				return ResolvedValue;
			}
			TSharedPtr<FJsonObject> ResolvedObject = ResolveJsonRefsInObject(Object, StepResults, OutError);
			if (!ResolvedObject.IsValid())
			{
				return nullptr;
			}
			return MakeShared<FJsonValueObject>(ResolvedObject);
		}

		if (Value->Type == EJson::Array)
		{
			TArray<TSharedPtr<FJsonValue>> ResolvedArray;
			for (const TSharedPtr<FJsonValue>& Entry : Value->AsArray())
			{
				TSharedPtr<FJsonValue> ResolvedEntry = ResolveJsonRefs(Entry, StepResults, OutError);
				if (!ResolvedEntry.IsValid())
				{
					return nullptr;
				}
				ResolvedArray.Add(ResolvedEntry);
			}
			return MakeShared<FJsonValueArray>(ResolvedArray);
		}

		if (Value->Type == EJson::String)
		{
			const FString Text = Value->AsString();
			if (Text.StartsWith(TEXT("$ref:")))
			{
				TSharedPtr<FJsonValue> ResolvedValue;
				if (!ResolveStepReference(Text.Mid(5), StepResults, ResolvedValue, OutError))
				{
					return nullptr;
				}
				return ResolvedValue;
			}
			if (Text.StartsWith(TEXT("${")) && Text.EndsWith(TEXT("}")))
			{
				TSharedPtr<FJsonValue> ResolvedValue;
				if (!ResolveStepReference(Text.Mid(2, Text.Len() - 3), StepResults, ResolvedValue, OutError))
				{
					return nullptr;
				}
				return ResolvedValue;
			}
		}

		return CloneJsonValue(Value);
	}

	static bool IsFullVerbosity(const FString& Verbosity)
	{
		return Verbosity.Equals(TEXT("full"), ESearchCase::IgnoreCase) || Verbosity.Equals(TEXT("verbose"), ESearchCase::IgnoreCase);
	}

	static void CopyFieldIfPresent(const TSharedPtr<FJsonObject>& Source, const TSharedPtr<FJsonObject>& Target, const TCHAR* FieldName)
	{
		if (Source.IsValid())
		{
			TSharedPtr<FJsonValue> FoundValue = Source->TryGetField(FieldName);
			if (FoundValue.IsValid())
			{
				Target->SetField(FieldName, CloneJsonValue(FoundValue));
			}
		}
	}

	static TSharedPtr<FJsonObject> MakeCompactResult(const TSharedPtr<FJsonObject>& Source)
	{
		TSharedPtr<FJsonObject> Compact = MakeShared<FJsonObject>();
		static const TCHAR* FieldsToKeep[] = {
			TEXT("index"), TEXT("type"), TEXT("action_id"), TEXT("success"), TEXT("error_type"), TEXT("error"),
			TEXT("name"), TEXT("path"), TEXT("object_path"), TEXT("asset_path"), TEXT("blueprint_name"),
			TEXT("material_name"), TEXT("widget_name"), TEXT("component_name"), TEXT("node_id"),
			TEXT("entry_node_id"), TEXT("result_node_id"), TEXT("emitter_handle_id"), TEXT("mode"),
			TEXT("status"), TEXT("compiled"), TEXT("error_count"), TEXT("warning_count"), TEXT("existing"),
			TEXT("skipped"), TEXT("if_exists")
		};
		for (const TCHAR* FieldName : FieldsToKeep)
		{
			CopyFieldIfPresent(Source, Compact, FieldName);
		}
		return Compact;
	}
}

namespace UEEditorMCPAssetMaintenance
{
	struct FRenameRequestItem
	{
		FString OldAssetPath;
		FString NewPackagePath;
		FString NewName;
	};

	struct FManifestRenameItem : FRenameRequestItem
	{
		FString Id;
		FString SourceObjectPath;
		FString SourcePackagePath;
		FString TargetObjectPath;
		FString TargetPackagePath;
		FString ExpectedClass;
		FString RuleId;
		FString Reason;
		double Confidence = -1.0;
		TArray<FString> ManifestWarnings;
		TArray<FString> ManifestBlockers;
	};

	struct FAssetMaintenanceManifestPlan
	{
		FString Schema;
		FString Project;
		TArray<FManifestRenameItem> RenameItems;
		TArray<FString> EmptyDirectories;
		TArray<FString> ManifestWarnings;
		TArray<FString> ManifestBlockers;
		bool bAutoFixupRedirectors = true;
		bool bDeleteEmptyDirectories = false;
		FString FixupMode = TEXT("delete");
		bool bAllowUIPrompts = false;
	};

	static FString CleanLongPath(FString Path)
	{
		Path.TrimStartAndEndInline();
		Path.ReplaceInline(TEXT("\\"), TEXT("/"));
		while (Path.Len() > 1 && Path.EndsWith(TEXT("/")))
		{
			Path.LeftChopInline(1, EAllowShrinking::No);
		}
		return Path;
	}

	static FString PackagePathFromAnyAssetPath(const FString& InAssetPath)
	{
		const FString CleanPath = CleanLongPath(InAssetPath);
		return CleanPath.Contains(TEXT("."))
			? FPackageName::ObjectPathToPackageName(CleanPath)
			: CleanPath;
	}

	static FString ObjectPathFromAnyAssetPath(const FString& InAssetPath)
	{
		const FString PackagePath = PackagePathFromAnyAssetPath(InAssetPath);
		if (PackagePath.IsEmpty())
		{
			return TEXT("");
		}
		return PackagePath + TEXT(".") + FPackageName::GetShortName(PackagePath);
	}

	static FString ObjectPathFromPackageAndName(const FString& ParentPackagePath, const FString& AssetName)
	{
		const FString ParentPath = CleanLongPath(ParentPackagePath);
		const FString PackagePath = ParentPath / AssetName;
		return PackagePath + TEXT(".") + AssetName;
	}

	static FString PackagePathFromPackageAndName(const FString& ParentPackagePath, const FString& AssetName)
	{
		return CleanLongPath(ParentPackagePath) / AssetName;
	}

	static FString ObjectPathFromPackageAndAssetName(const FString& PackagePath, const FString& AssetName)
	{
		const FString CleanPackagePath = CleanLongPath(PackagePath);
		const FString ObjectName = AssetName.IsEmpty() ? FPackageName::GetShortName(CleanPackagePath) : AssetName;
		return CleanPackagePath + TEXT(".") + ObjectName;
	}

	static FString ObjectPathFromObjectOrPackage(const FString& RawPath)
	{
		const FString CleanPath = CleanLongPath(RawPath);
		if (CleanPath.Contains(TEXT(".")))
		{
			return CleanPath;
		}
		return ObjectPathFromPackageAndAssetName(CleanPath, FPackageName::GetShortName(CleanPath));
	}

	static FString NormalizeFixupMode(const FString& RawFixupMode)
	{
		const FString Lower = RawFixupMode.ToLower();
		if (Lower == TEXT("leave") || Lower == TEXT("prompt"))
		{
			return Lower;
		}
		return TEXT("delete");
	}

	static bool TryGetObject(const TSharedPtr<FJsonObject>& Object, const TCHAR* FieldName, TSharedPtr<FJsonObject>& OutObject)
	{
		OutObject.Reset();
		if (!Object.IsValid())
		{
			return false;
		}

		const TSharedPtr<FJsonObject>* FoundObject = nullptr;
		if (Object->TryGetObjectField(FieldName, FoundObject) && FoundObject && FoundObject->IsValid())
		{
			OutObject = *FoundObject;
			return true;
		}
		return false;
	}

	static FString GetOptionalStringField(const TSharedPtr<FJsonObject>& Object, const TCHAR* FieldName, const FString& Default = TEXT(""))
	{
		FString Value;
		return Object.IsValid() && Object->TryGetStringField(FieldName, Value) ? Value : Default;
	}

	static bool TryGetAnyStringField(const TSharedPtr<FJsonObject>& Object, std::initializer_list<const TCHAR*> FieldNames, FString& OutValue)
	{
		if (!Object.IsValid())
		{
			return false;
		}

		for (const TCHAR* FieldName : FieldNames)
		{
			if (Object->TryGetStringField(FieldName, OutValue) && !OutValue.IsEmpty())
			{
				return true;
			}
		}
		return false;
	}

	static bool TryReadStringArrayFromValue(const TSharedPtr<FJsonValue>& Value, TArray<FString>& OutValues, FString& OutError)
	{
		OutValues.Reset();
		if (!Value.IsValid())
		{
			OutError = TEXT("Array value is invalid");
			return false;
		}

		if (Value->Type != EJson::Array)
		{
			OutError = TEXT("Expected an array");
			return false;
		}

		const TArray<TSharedPtr<FJsonValue>>& Values = Value->AsArray();
		for (int32 Index = 0; Index < Values.Num(); ++Index)
		{
			FString Parsed;
			if (Values[Index].IsValid() && Values[Index]->TryGetString(Parsed) && !Parsed.IsEmpty())
			{
				OutValues.Add(CleanLongPath(Parsed));
				continue;
			}

			if (Values[Index].IsValid() && Values[Index]->Type == EJson::Object)
			{
				const TSharedPtr<FJsonObject> DirObject = Values[Index]->AsObject();
				if (TryGetAnyStringField(DirObject, { TEXT("path"), TEXT("directory") }, Parsed) && !Parsed.IsEmpty())
				{
					OutValues.Add(CleanLongPath(Parsed));
					continue;
				}
			}

			OutError = FString::Printf(TEXT("Directory array item %d must be a string or object with path"), Index);
			return false;
		}
		return true;
	}

	static void AppendStringReasons(TArray<TSharedPtr<FJsonValue>>& JsonReasons, const TArray<FString>& Reasons)
	{
		for (const FString& Reason : Reasons)
		{
			JsonReasons.Add(MakeShared<FJsonValueString>(Reason));
		}
	}

	static TArray<TSharedPtr<FJsonValue>> StringsToJsonArray(const TArray<FString>& Values)
	{
		TArray<TSharedPtr<FJsonValue>> JsonValues;
		for (const FString& Value : Values)
		{
			JsonValues.Add(MakeShared<FJsonValueString>(Value));
		}
		return JsonValues;
	}

	static bool ClassMatchesExpected(const FString& ActualClass, const FString& ExpectedClass)
	{
		if (ExpectedClass.IsEmpty())
		{
			return true;
		}
		if (ActualClass.Equals(ExpectedClass, ESearchCase::IgnoreCase))
		{
			return true;
		}
		if (ExpectedClass.Equals(TEXT("Blueprint"), ESearchCase::IgnoreCase) && ActualClass.EndsWith(TEXT("Blueprint")))
		{
			return true;
		}
		return false;
	}

	static bool TryResolveManifestSource(const TSharedPtr<FJsonObject>& ItemObject, FManifestRenameItem& OutItem, FString& OutError)
	{
		TSharedPtr<FJsonObject> SourceObject;
		TryGetObject(ItemObject, TEXT("source"), SourceObject);

		FString SourceObjectPath;
		if (TryGetAnyStringField(ItemObject, { TEXT("old_asset_path"), TEXT("source_object_path") }, SourceObjectPath) ||
			TryGetAnyStringField(SourceObject, { TEXT("object_path"), TEXT("asset_path") }, SourceObjectPath))
		{
			OutItem.SourceObjectPath = ObjectPathFromObjectOrPackage(SourceObjectPath);
			OutItem.SourcePackagePath = PackagePathFromAnyAssetPath(OutItem.SourceObjectPath);
			OutItem.OldAssetPath = OutItem.SourceObjectPath;
		}
		else
		{
			FString SourcePackagePath;
			FString SourceAssetName;
			TryGetAnyStringField(SourceObject, { TEXT("package_path"), TEXT("package") }, SourcePackagePath);
			TryGetAnyStringField(SourceObject, { TEXT("asset_name"), TEXT("name") }, SourceAssetName);

			if (SourcePackagePath.IsEmpty())
			{
				OutError = TEXT("source.object_path or source.package_path is required");
				return false;
			}

			OutItem.SourcePackagePath = PackagePathFromAnyAssetPath(SourcePackagePath);
			OutItem.SourceObjectPath = ObjectPathFromPackageAndAssetName(OutItem.SourcePackagePath, SourceAssetName);
			OutItem.OldAssetPath = OutItem.SourceObjectPath;
		}

		if (SourceObject.IsValid())
		{
			TryGetAnyStringField(SourceObject, { TEXT("expected_class"), TEXT("class") }, OutItem.ExpectedClass);
		}
		return true;
	}

	static bool TryResolveManifestTarget(const TSharedPtr<FJsonObject>& ItemObject, FManifestRenameItem& OutItem, FString& OutError)
	{
		TSharedPtr<FJsonObject> TargetObject;
		TryGetObject(ItemObject, TEXT("target"), TargetObject);

		FString TargetObjectPath;
		FString TargetPackagePath;
		FString TargetDirectory;
		FString TargetName;

		TryGetAnyStringField(ItemObject, { TEXT("new_name"), TEXT("target_name") }, TargetName);
		TryGetAnyStringField(TargetObject, { TEXT("asset_name"), TEXT("new_name"), TEXT("name") }, TargetName);

		TryGetAnyStringField(TargetObject, { TEXT("object_path"), TEXT("asset_path") }, TargetObjectPath);
		TryGetAnyStringField(TargetObject, { TEXT("directory"), TEXT("new_package_path"), TEXT("parent_path") }, TargetDirectory);
		TryGetAnyStringField(TargetObject, { TEXT("package_path"), TEXT("package") }, TargetPackagePath);
		TryGetAnyStringField(ItemObject, { TEXT("new_package_path"), TEXT("target_directory") }, TargetDirectory);

		if (!TargetObjectPath.IsEmpty())
		{
			const FString TargetPackageFromObject = PackagePathFromAnyAssetPath(TargetObjectPath);
			if (TargetName.IsEmpty())
			{
				TargetName = FPackageName::ObjectPathToObjectName(TargetObjectPath);
			}
			if (TargetDirectory.IsEmpty())
			{
				TargetDirectory = FPackageName::GetLongPackagePath(TargetPackageFromObject);
			}
			OutItem.TargetObjectPath = ObjectPathFromObjectOrPackage(TargetObjectPath);
		}

		if (!TargetPackagePath.IsEmpty())
		{
			const FString CleanTargetPackagePath = PackagePathFromAnyAssetPath(TargetPackagePath);
			if (TargetName.IsEmpty())
			{
				TargetName = FPackageName::GetShortName(CleanTargetPackagePath);
				TargetDirectory = FPackageName::GetLongPackagePath(CleanTargetPackagePath);
			}
			else if (TargetDirectory.IsEmpty())
			{
				TargetDirectory = FPackageName::GetShortName(CleanTargetPackagePath).Equals(TargetName, ESearchCase::CaseSensitive)
					? FPackageName::GetLongPackagePath(CleanTargetPackagePath)
					: CleanTargetPackagePath;
			}
		}

		if (TargetDirectory.IsEmpty())
		{
			OutError = TEXT("target.directory, target.new_package_path, target.package_path, or target.object_path is required");
			return false;
		}
		if (TargetName.IsEmpty())
		{
			OutError = TEXT("target.asset_name or target.new_name is required");
			return false;
		}

		OutItem.NewPackagePath = CleanLongPath(TargetDirectory);
		OutItem.NewName = TargetName;
		OutItem.TargetPackagePath = PackagePathFromPackageAndName(OutItem.NewPackagePath, OutItem.NewName);
		if (OutItem.TargetObjectPath.IsEmpty())
		{
			OutItem.TargetObjectPath = ObjectPathFromPackageAndName(OutItem.NewPackagePath, OutItem.NewName);
		}

		const FString DerivedObjectPath = ObjectPathFromPackageAndName(OutItem.NewPackagePath, OutItem.NewName);
		if (!OutItem.TargetObjectPath.Equals(DerivedObjectPath, ESearchCase::CaseSensitive))
		{
			OutItem.ManifestBlockers.Add(FString::Printf(
				TEXT("target_object_path_mismatch: expected %s from directory/name"),
				*DerivedObjectPath
			));
		}
		return true;
	}

	static bool TryAppendManifestEmptyDirectory(const TSharedPtr<FJsonObject>& ItemObject, TArray<FString>& OutDirectories, FString& OutError)
	{
		FString DirectoryPath;
		if (!TryGetAnyStringField(ItemObject, { TEXT("path"), TEXT("directory") }, DirectoryPath))
		{
			TSharedPtr<FJsonObject> SourceObject;
			if (TryGetObject(ItemObject, TEXT("source"), SourceObject))
			{
				TryGetAnyStringField(SourceObject, { TEXT("path"), TEXT("directory") }, DirectoryPath);
			}
		}

		if (DirectoryPath.IsEmpty())
		{
			OutError = TEXT("delete_empty_directory item requires path or directory");
			return false;
		}

		OutDirectories.Add(CleanLongPath(DirectoryPath));
		return true;
	}

	static bool TryParseAssetMaintenanceManifest(const TSharedPtr<FJsonObject>& ManifestObject, FAssetMaintenanceManifestPlan& OutPlan, FString& OutError)
	{
		if (!ManifestObject.IsValid())
		{
			OutError = TEXT("'manifest' must be an object");
			return false;
		}

		OutPlan = FAssetMaintenanceManifestPlan();
		OutPlan.Schema = GetOptionalStringField(ManifestObject, TEXT("schema"), TEXT("ue.asset_maintenance_plan.v1"));
		OutPlan.Project = GetOptionalStringField(ManifestObject, TEXT("project"));
		if (OutPlan.Schema != TEXT("ue.asset_maintenance_plan.v1") && OutPlan.Schema != TEXT("ue.asset_rename_plan.v1"))
		{
			OutPlan.ManifestBlockers.Add(FString::Printf(TEXT("unsupported_schema: %s"), *OutPlan.Schema));
		}

		TSharedPtr<FJsonObject> DefaultsObject;
		if (TryGetObject(ManifestObject, TEXT("defaults"), DefaultsObject))
		{
			bool bBoolValue = false;
			FString StringValue;
			if (DefaultsObject->TryGetBoolField(TEXT("auto_fixup_redirectors"), bBoolValue))
			{
				OutPlan.bAutoFixupRedirectors = bBoolValue;
			}
			if (DefaultsObject->TryGetBoolField(TEXT("delete_empty_dirs"), bBoolValue) ||
				DefaultsObject->TryGetBoolField(TEXT("delete_empty_directories"), bBoolValue))
			{
				OutPlan.bDeleteEmptyDirectories = bBoolValue;
			}
			if (DefaultsObject->TryGetBoolField(TEXT("allow_ui_prompts"), bBoolValue))
			{
				OutPlan.bAllowUIPrompts = bBoolValue;
			}
			if (DefaultsObject->TryGetStringField(TEXT("fixup_mode"), StringValue))
			{
				OutPlan.FixupMode = NormalizeFixupMode(StringValue);
			}
		}

		const TArray<TSharedPtr<FJsonValue>>* ItemsArray = nullptr;
		if (ManifestObject->TryGetArrayField(TEXT("items"), ItemsArray) && ItemsArray)
		{
			for (int32 Index = 0; Index < ItemsArray->Num(); ++Index)
			{
				const TSharedPtr<FJsonValue>& ItemValue = (*ItemsArray)[Index];
				if (!ItemValue.IsValid() || ItemValue->Type != EJson::Object)
				{
					OutError = FString::Printf(TEXT("manifest.items[%d] must be an object"), Index);
					return false;
				}

				const TSharedPtr<FJsonObject> ItemObject = ItemValue->AsObject();
				const FString Op = GetOptionalStringField(ItemObject, TEXT("op"), TEXT("rename_or_move_asset")).ToLower();
				if (Op == TEXT("rename") || Op == TEXT("move") || Op == TEXT("rename_asset") || Op == TEXT("rename_or_move_asset"))
				{
					FManifestRenameItem RenameItem;
					RenameItem.Id = GetOptionalStringField(ItemObject, TEXT("id"), FString::Printf(TEXT("item_%04d"), Index));
					RenameItem.RuleId = GetOptionalStringField(ItemObject, TEXT("rule_id"));
					RenameItem.Reason = GetOptionalStringField(ItemObject, TEXT("reason"));
					ItemObject->TryGetNumberField(TEXT("confidence"), RenameItem.Confidence);

					FString ParseError;
					if (!TryResolveManifestSource(ItemObject, RenameItem, ParseError))
					{
						RenameItem.ManifestBlockers.Add(ParseError);
						const FString PlaceholderName = FString::Printf(TEXT("InvalidSource_%d"), Index);
						RenameItem.SourcePackagePath = FString(TEXT("/Game/__MCPInvalidManifest/")) + PlaceholderName;
						RenameItem.SourceObjectPath = ObjectPathFromPackageAndAssetName(RenameItem.SourcePackagePath, PlaceholderName);
						RenameItem.OldAssetPath = RenameItem.SourceObjectPath;
					}
					if (!TryResolveManifestTarget(ItemObject, RenameItem, ParseError))
					{
						RenameItem.ManifestBlockers.Add(ParseError);
						RenameItem.NewPackagePath = TEXT("/Game/__MCPInvalidManifest");
						RenameItem.NewName = FString::Printf(TEXT("InvalidTarget_%d"), Index);
						RenameItem.TargetPackagePath = PackagePathFromPackageAndName(RenameItem.NewPackagePath, RenameItem.NewName);
						RenameItem.TargetObjectPath = ObjectPathFromPackageAndName(RenameItem.NewPackagePath, RenameItem.NewName);
					}

					OutPlan.RenameItems.Add(RenameItem);
				}
				else if (Op == TEXT("delete_empty_directory") || Op == TEXT("delete_empty_dir"))
				{
					FString ParseError;
					if (!TryAppendManifestEmptyDirectory(ItemObject, OutPlan.EmptyDirectories, ParseError))
					{
						OutPlan.ManifestBlockers.Add(FString::Printf(TEXT("items[%d].%s"), Index, *ParseError));
					}
				}
				else if (Op == TEXT("delete_asset") || Op == TEXT("delete_assets"))
				{
					OutPlan.ManifestBlockers.Add(FString::Printf(
						TEXT("items[%d].delete_asset_unsupported_use_editor_delete_assets"),
						Index
					));
				}
				else
				{
					OutPlan.ManifestBlockers.Add(FString::Printf(TEXT("items[%d].unsupported_op: %s"), Index, *Op));
				}
			}
		}

		TSharedPtr<FJsonObject> CleanupObject;
		if (TryGetObject(ManifestObject, TEXT("cleanup"), CleanupObject))
		{
			const TSharedPtr<FJsonValue> EmptyDirectoriesValue = CleanupObject->TryGetField(TEXT("empty_directories"));
			if (EmptyDirectoriesValue.IsValid())
			{
				TArray<FString> ParsedDirectories;
				FString ParseError;
				if (!TryReadStringArrayFromValue(EmptyDirectoriesValue, ParsedDirectories, ParseError))
				{
					OutError = FString::Printf(TEXT("cleanup.empty_directories: %s"), *ParseError);
					return false;
				}
				OutPlan.EmptyDirectories.Append(ParsedDirectories);
			}
		}

		const TSharedPtr<FJsonValue> EmptyDirectoriesValue = ManifestObject->TryGetField(TEXT("empty_directories"));
		if (EmptyDirectoriesValue.IsValid())
		{
			TArray<FString> ParsedDirectories;
			FString ParseError;
			if (!TryReadStringArrayFromValue(EmptyDirectoriesValue, ParsedDirectories, ParseError))
			{
				OutError = FString::Printf(TEXT("empty_directories: %s"), *ParseError);
				return false;
			}
			OutPlan.EmptyDirectories.Append(ParsedDirectories);
		}

		OutPlan.EmptyDirectories.Sort();
		for (int32 Index = OutPlan.EmptyDirectories.Num() - 1; Index > 0; --Index)
		{
			if (OutPlan.EmptyDirectories[Index] == OutPlan.EmptyDirectories[Index - 1])
			{
				OutPlan.EmptyDirectories.RemoveAt(Index);
			}
		}

		if (OutPlan.RenameItems.Num() == 0 && OutPlan.EmptyDirectories.Num() == 0 && OutPlan.ManifestBlockers.Num() == 0)
		{
			OutPlan.ManifestBlockers.Add(TEXT("manifest_contains_no_supported_operations"));
		}

		return true;
	}

	static FString BuildAssetMaintenancePlanHash(const FAssetMaintenanceManifestPlan& Plan)
	{
		FString Canonical;
		Canonical += FString::Printf(TEXT("schema=%s\n"), *Plan.Schema);
		Canonical += FString::Printf(TEXT("auto_fixup_redirectors=%s\n"), Plan.bAutoFixupRedirectors ? TEXT("true") : TEXT("false"));
		Canonical += FString::Printf(TEXT("delete_empty_directories=%s\n"), Plan.bDeleteEmptyDirectories ? TEXT("true") : TEXT("false"));
		Canonical += FString::Printf(TEXT("fixup_mode=%s\n"), *Plan.FixupMode);

		for (int32 Index = 0; Index < Plan.RenameItems.Num(); ++Index)
		{
			const FManifestRenameItem& Item = Plan.RenameItems[Index];
			Canonical += FString::Printf(
				TEXT("rename[%d]=%s|%s|%s|%s\n"),
				Index,
				*Item.OldAssetPath,
				*Item.NewPackagePath,
				*Item.NewName,
				*Item.ExpectedClass
			);
		}

		for (int32 Index = 0; Index < Plan.EmptyDirectories.Num(); ++Index)
		{
			Canonical += FString::Printf(TEXT("empty_dir[%d]=%s\n"), Index, *Plan.EmptyDirectories[Index]);
		}

		return FMD5::HashAnsiString(*Canonical);
	}

	static TArray<TSharedPtr<FJsonValue>> BuildRenameItemsJson(const TArray<FManifestRenameItem>& RenameItems)
	{
		TArray<TSharedPtr<FJsonValue>> ItemsArray;
		for (const FManifestRenameItem& Item : RenameItems)
		{
			TSharedPtr<FJsonObject> ItemObject = MakeShared<FJsonObject>();
			ItemObject->SetStringField(TEXT("old_asset_path"), Item.OldAssetPath);
			ItemObject->SetStringField(TEXT("new_package_path"), Item.NewPackagePath);
			ItemObject->SetStringField(TEXT("new_name"), Item.NewName);
			ItemsArray.Add(MakeShared<FJsonValueObject>(ItemObject));
		}
		return ItemsArray;
	}

	static bool TryReadStringArray(const TSharedPtr<FJsonObject>& Params, const TCHAR* SingleField, const TCHAR* ArrayField, TArray<FString>& OutValues, FString& OutError)
	{
		OutValues.Reset();

		FString SingleValue;
		if (Params->TryGetStringField(SingleField, SingleValue) && !SingleValue.IsEmpty())
		{
			OutValues.Add(SingleValue);
		}

		if (Params->HasField(ArrayField))
		{
			const TArray<TSharedPtr<FJsonValue>>* Values = nullptr;
			if (!Params->TryGetArrayField(ArrayField, Values) || !Values)
			{
				OutError = FString::Printf(TEXT("'%s' must be an array of non-empty strings"), ArrayField);
				return false;
			}
			for (int32 Index = 0; Index < Values->Num(); ++Index)
			{
				FString Parsed;
				if (!(*Values)[Index].IsValid() || !(*Values)[Index]->TryGetString(Parsed) || Parsed.IsEmpty())
				{
					OutError = FString::Printf(TEXT("%s[%d] must be a non-empty string"), ArrayField, Index);
					return false;
				}
				OutValues.Add(Parsed);
			}
		}

		if (OutValues.Num() == 0)
		{
			OutError = FString::Printf(TEXT("Provide either '%s' or '%s'"), SingleField, ArrayField);
			return false;
		}
		return true;
	}

	static bool ValidateRenameParams(const TSharedPtr<FJsonObject>& Params, FString& OutError)
	{
		const bool bHasBatch = Params->HasField(TEXT("items"));
		const bool bHasSingle = Params->HasField(TEXT("old_asset_path"));
		if (!bHasBatch && !bHasSingle)
		{
			OutError = TEXT("Provide either 'items' or single fields 'old_asset_path', 'new_package_path', 'new_name'");
			return false;
		}

		if (bHasBatch)
		{
			const TArray<TSharedPtr<FJsonValue>>* Items = nullptr;
			if (!Params->TryGetArrayField(TEXT("items"), Items) || !Items || Items->Num() == 0)
			{
				OutError = TEXT("'items' must be a non-empty array");
				return false;
			}
			for (int32 Index = 0; Index < Items->Num(); ++Index)
			{
				if (!(*Items)[Index].IsValid() || (*Items)[Index]->Type != EJson::Object)
				{
					OutError = FString::Printf(TEXT("items[%d] must be an object"), Index);
					return false;
				}
				const TSharedPtr<FJsonObject> Item = (*Items)[Index]->AsObject();
				FString OldAssetPath;
				FString NewPackagePath;
				FString NewName;
				if (!Item->TryGetStringField(TEXT("old_asset_path"), OldAssetPath) || OldAssetPath.IsEmpty() ||
					!Item->TryGetStringField(TEXT("new_package_path"), NewPackagePath) || NewPackagePath.IsEmpty() ||
					!Item->TryGetStringField(TEXT("new_name"), NewName) || NewName.IsEmpty())
				{
					OutError = FString::Printf(TEXT("items[%d] requires old_asset_path, new_package_path, and new_name"), Index);
					return false;
				}
			}
			return true;
		}

		FString OldAssetPath;
		FString NewPackagePath;
		FString NewName;
		if (!Params->TryGetStringField(TEXT("old_asset_path"), OldAssetPath) || OldAssetPath.IsEmpty() ||
			!Params->TryGetStringField(TEXT("new_package_path"), NewPackagePath) || NewPackagePath.IsEmpty() ||
			!Params->TryGetStringField(TEXT("new_name"), NewName) || NewName.IsEmpty())
		{
			OutError = TEXT("Single rename mode requires old_asset_path, new_package_path, and new_name");
			return false;
		}
		return true;
	}

	static TArray<FRenameRequestItem> ParseRenameItems(const TSharedPtr<FJsonObject>& Params)
	{
		TArray<FRenameRequestItem> Items;
		if (Params->HasField(TEXT("items")))
		{
			const TArray<TSharedPtr<FJsonValue>>* JsonItems = nullptr;
			Params->TryGetArrayField(TEXT("items"), JsonItems);
			if (JsonItems)
			{
				for (const TSharedPtr<FJsonValue>& JsonItem : *JsonItems)
				{
					if (!JsonItem.IsValid() || JsonItem->Type != EJson::Object)
					{
						continue;
					}
					const TSharedPtr<FJsonObject> Obj = JsonItem->AsObject();
					FRenameRequestItem Item;
					if (Obj->TryGetStringField(TEXT("old_asset_path"), Item.OldAssetPath) &&
						Obj->TryGetStringField(TEXT("new_package_path"), Item.NewPackagePath) &&
						Obj->TryGetStringField(TEXT("new_name"), Item.NewName))
					{
						Items.Add(Item);
					}
				}
			}
		}
		else
		{
			FRenameRequestItem Item;
			Params->TryGetStringField(TEXT("old_asset_path"), Item.OldAssetPath);
			Params->TryGetStringField(TEXT("new_package_path"), Item.NewPackagePath);
			Params->TryGetStringField(TEXT("new_name"), Item.NewName);
			Items.Add(Item);
		}
		return Items;
	}

	static void AddReason(TArray<TSharedPtr<FJsonValue>>& Reasons, const FString& Reason)
	{
		Reasons.Add(MakeShared<FJsonValueString>(Reason));
	}

	static bool GetProtectedAssetReason(const FString& PackagePath, bool bAllowProtectedPaths, FString& OutReason)
	{
		if (bAllowProtectedPaths)
		{
			return false;
		}

		const FString CleanPath = CleanLongPath(PackagePath);
		if (!CleanPath.StartsWith(TEXT("/Game/")))
		{
			OutReason = TEXT("non_game_path");
			return true;
		}
		if (CleanPath.StartsWith(TEXT("/Game/__ExternalActors/")) || CleanPath.StartsWith(TEXT("/Game/__ExternalObjects/")))
		{
			OutReason = TEXT("world_partition_external_path");
			return true;
		}
		return false;
	}

	static bool GetProtectedDirectoryReason(const FString& DirectoryPath, bool bAllowProtectedPaths, FString& OutReason)
	{
		if (bAllowProtectedPaths)
		{
			return false;
		}

		const FString CleanPath = CleanLongPath(DirectoryPath);
		if (CleanPath == TEXT("/Game"))
		{
			OutReason = TEXT("game_root_protected");
			return true;
		}
		if (!CleanPath.StartsWith(TEXT("/Game/")))
		{
			OutReason = TEXT("non_game_path");
			return true;
		}
		if (CleanPath == TEXT("/Game/__ExternalActors") || CleanPath == TEXT("/Game/__ExternalObjects") ||
			CleanPath.StartsWith(TEXT("/Game/__ExternalActors/")) || CleanPath.StartsWith(TEXT("/Game/__ExternalObjects/")))
		{
			OutReason = TEXT("world_partition_external_path");
			return true;
		}
		return false;
	}

	static FAssetData GetAssetData(IAssetRegistry& AssetRegistry, const FString& AssetPath)
	{
		const FString ObjectPath = ObjectPathFromAnyAssetPath(AssetPath);
		if (ObjectPath.IsEmpty())
		{
			return FAssetData();
		}
		return AssetRegistry.GetAssetByObjectPath(FSoftObjectPath(ObjectPath));
	}

	static bool IsMapAsset(const FAssetData& AssetData)
	{
		return AssetData.IsValid() && AssetData.AssetClassPath.GetAssetName().ToString() == TEXT("World");
	}

	static TArray<FName> GetExternalReferencers(IAssetRegistry& AssetRegistry, const FString& PackagePath, const TSet<FName>& InternalPackages, int32& OutTotalReferencers)
	{
		TArray<FName> Referencers;
		AssetRegistry.GetReferencers(FName(*PackagePath), Referencers);
		OutTotalReferencers = Referencers.Num();

		TArray<FName> ExternalReferencers;
		for (const FName& Referencer : Referencers)
		{
			if (Referencer.ToString() == PackagePath || InternalPackages.Contains(Referencer))
			{
				continue;
			}
			ExternalReferencers.Add(Referencer);
		}
		ExternalReferencers.Sort([](const FName& A, const FName& B)
		{
			return A.ToString() < B.ToString();
		});
		return ExternalReferencers;
	}

	static TArray<TSharedPtr<FJsonValue>> NamesToJsonArray(const TArray<FName>& Names, int32 MaxItems)
	{
		TArray<TSharedPtr<FJsonValue>> Values;
		const int32 ClampedMax = FMath::Max(0, MaxItems);
		const int32 Count = FMath::Min(Names.Num(), ClampedMax);
		for (int32 Index = 0; Index < Count; ++Index)
		{
			Values.Add(MakeShared<FJsonValueString>(Names[Index].ToString()));
		}
		return Values;
	}

	static bool TryGamePathToDiskDirectory(const FString& DirectoryPath, FString& OutDiskDirectory, FString& OutError)
	{
		const FString CleanPath = CleanLongPath(DirectoryPath);
		if (!CleanPath.StartsWith(TEXT("/Game")))
		{
			OutError = FString::Printf(TEXT("Only /Game content directories are supported by default: %s"), *CleanPath);
			return false;
		}

		const FString PackagePathWithSlash = CleanPath.EndsWith(TEXT("/")) ? CleanPath : CleanPath + TEXT("/");
		if (!FPackageName::TryConvertLongPackageNameToFilename(PackagePathWithSlash, OutDiskDirectory))
		{
			OutError = FString::Printf(TEXT("Failed to convert content path to disk path: %s"), *CleanPath);
			return false;
		}

		OutDiskDirectory = FPaths::ConvertRelativePathToFull(OutDiskDirectory);
		FPaths::NormalizeDirectoryName(OutDiskDirectory);

		FString ProjectContentDir = FPaths::ConvertRelativePathToFull(FPaths::ProjectContentDir());
		FPaths::NormalizeDirectoryName(ProjectContentDir);
		if (!OutDiskDirectory.StartsWith(ProjectContentDir))
		{
			OutError = FString::Printf(TEXT("Resolved path escapes project Content directory: %s"), *OutDiskDirectory);
			return false;
		}
		return true;
	}

	static FString DiskDirectoryToGamePath(const FString& DiskDirectory)
	{
		FString ProjectContentDir = FPaths::ConvertRelativePathToFull(FPaths::ProjectContentDir());
		FPaths::NormalizeDirectoryName(ProjectContentDir);

		FString Relative = FPaths::ConvertRelativePathToFull(DiskDirectory);
		FPaths::NormalizeDirectoryName(Relative);
		if (!FPaths::MakePathRelativeTo(Relative, *ProjectContentDir))
		{
			return TEXT("");
		}
		Relative.ReplaceInline(TEXT("\\"), TEXT("/"));
		while (Relative.StartsWith(TEXT("./")))
		{
			Relative.RightChopInline(2, EAllowShrinking::No);
		}
		while (Relative.EndsWith(TEXT("/")))
		{
			Relative.LeftChopInline(1, EAllowShrinking::No);
		}
		return Relative.IsEmpty() || Relative == TEXT(".")
			? FString(TEXT("/Game"))
			: FString(TEXT("/Game/")) + Relative;
	}

	static bool DirectoryHasFilesRecursive(const FString& DiskDirectory)
	{
		if (!IFileManager::Get().DirectoryExists(*DiskDirectory))
		{
			return false;
		}

		bool bHasFiles = false;
		IFileManager::Get().IterateDirectoryRecursively(*DiskDirectory, [&bHasFiles](const TCHAR* FilenameOrDirectory, bool bIsDirectory) -> bool
		{
			if (!bIsDirectory)
			{
				bHasFiles = true;
				return false;
			}
			return true;
		});
		return bHasFiles;
	}
}

#if PLATFORM_WINDOWS
#include "Windows/AllowWindowsPlatformTypes.h"
#include "Windows/PreWindowsApi.h"
#include <windows.h>
#include "Windows/PostWindowsApi.h"
#include "Windows/HideWindowsPlatformTypes.h"
#endif


// Helper to find actor by name
static AActor* FindActorByName(UWorld* World, const FString& ActorName)
{
	if (!World) return nullptr;

	TArray<AActor*> AllActors;
	UGameplayStatics::GetAllActorsOfClass(World, AActor::StaticClass(), AllActors);

	for (AActor* Actor : AllActors)
	{
		if (Actor && Actor->GetName() == ActorName)
		{
			return Actor;
		}
	}
	return nullptr;
}


// ============================================================================
// FGetActorsInLevelAction
// ============================================================================

TSharedPtr<FJsonObject> FGetActorsInLevelAction::ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context)
{
	UWorld* World = GEditor ? GEditor->GetEditorWorldContext().World() : nullptr;
	if (!World)
	{
		return CreateErrorResponse(TEXT("No editor world available"), TEXT("no_world"));
	}

	const bool bSelectedOnly = Params.IsValid() && Params->HasField(TEXT("selected_only")) ? Params->GetBoolField(TEXT("selected_only")) : false;
	const bool bIncludeComponentDetails = Params.IsValid() && Params->HasField(TEXT("include_component_details")) ? Params->GetBoolField(TEXT("include_component_details")) : false;
	const bool bIncludeLJCPackedChunkSummary = Params.IsValid() && Params->HasField(TEXT("include_ljc_packed_chunk_summary")) ? Params->GetBoolField(TEXT("include_ljc_packed_chunk_summary")) : false;

	auto VectorToJson = [](const FVector& Vector) -> TArray<TSharedPtr<FJsonValue>>
	{
		TArray<TSharedPtr<FJsonValue>> Array;
		Array.Add(MakeShared<FJsonValueNumber>(Vector.X));
		Array.Add(MakeShared<FJsonValueNumber>(Vector.Y));
		Array.Add(MakeShared<FJsonValueNumber>(Vector.Z));
		return Array;
	};

	auto RotatorToJson = [](const FRotator& Rotator) -> TArray<TSharedPtr<FJsonValue>>
	{
		TArray<TSharedPtr<FJsonValue>> Array;
		Array.Add(MakeShared<FJsonValueNumber>(Rotator.Pitch));
		Array.Add(MakeShared<FJsonValueNumber>(Rotator.Yaw));
		Array.Add(MakeShared<FJsonValueNumber>(Rotator.Roll));
		return Array;
	};

	auto BoundsToJson = [&VectorToJson](const FBox& Bounds) -> TSharedPtr<FJsonObject>
	{
		TSharedPtr<FJsonObject> Object = MakeShared<FJsonObject>();
		Object->SetBoolField(TEXT("is_valid"), Bounds.IsValid != 0);
		if (Bounds.IsValid)
		{
			Object->SetArrayField(TEXT("min"), VectorToJson(Bounds.Min));
			Object->SetArrayField(TEXT("max"), VectorToJson(Bounds.Max));
			Object->SetArrayField(TEXT("center"), VectorToJson(Bounds.GetCenter()));
			Object->SetArrayField(TEXT("extent"), VectorToJson(Bounds.GetExtent()));
			Object->SetArrayField(TEXT("size"), VectorToJson(Bounds.GetSize()));
		}
		return Object;
	};

	auto SphereBoundsToJson = [&VectorToJson](const FBoxSphereBounds& Bounds) -> TSharedPtr<FJsonObject>
	{
		TSharedPtr<FJsonObject> Object = MakeShared<FJsonObject>();
		Object->SetArrayField(TEXT("origin"), VectorToJson(Bounds.Origin));
		Object->SetArrayField(TEXT("box_extent"), VectorToJson(Bounds.BoxExtent));
		Object->SetArrayField(TEXT("size"), VectorToJson(Bounds.BoxExtent * 2.0));
		Object->SetNumberField(TEXT("sphere_radius"), Bounds.SphereRadius);
		return Object;
	};

	const FString CurrentMapName = (World->GetOutermost() != nullptr)
		? FPackageName::GetShortName(World->GetOutermost()->GetName())
		: World->GetMapName();
	auto BuildLJCPackedChunkInfo = [&CurrentMapName](const AActor* SourceActor, const UStaticMesh* StaticMesh) -> TSharedPtr<FJsonObject>
	{
		TSharedPtr<FJsonObject> Info = MakeShared<FJsonObject>();
		if (!SourceActor || !StaticMesh)
		{
			Info->SetBoolField(TEXT("found"), false);
			Info->SetStringField(TEXT("reason"), TEXT("missing_actor_or_static_mesh"));
			return Info;
		}

		const FString AssetName = FString::Printf(TEXT("PCA_LJC_Auto_%s_%s"), *StaticMesh->GetName(), *SourceActor->GetName());
		const FString ObjectPath = FString::Printf(
			TEXT("/Game/P111/Environment/Generated/%s/Packed/%s.%s"),
			*CurrentMapName,
			*AssetName,
			*AssetName);
		Info->SetStringField(TEXT("object_path"), ObjectPath);

		UObject* PackedAsset = StaticLoadObject(UObject::StaticClass(), nullptr, *ObjectPath);
		Info->SetBoolField(TEXT("found"), PackedAsset != nullptr);
		if (!PackedAsset)
		{
			return Info;
		}

		TSharedPtr<FJsonObject> Summary;
		FString SummaryError;
		if (UEEditorMCP_DataAssetUtils::TryBuildLJCPackedChunkSummary(PackedAsset, Summary, SummaryError))
		{
			Info->SetObjectField(TEXT("summary"), Summary);
		}
		else
		{
			Info->SetStringField(TEXT("summary_error"), SummaryError);
		}
		return Info;
	};

	TArray<AActor*> AllActors;
	UGameplayStatics::GetAllActorsOfClass(World, AActor::StaticClass(), AllActors);

	TArray<TSharedPtr<FJsonValue>> ActorArray;
	int32 SelectedCount = 0;
	for (AActor* Actor : AllActors)
	{
		if (Actor)
		{
			const bool bIsSelected = Actor->IsSelected();
			if (bIsSelected)
			{
				SelectedCount++;
			}
			if (bSelectedOnly && !bIsSelected)
			{
				continue;
			}

			TSharedPtr<FJsonObject> ActorObject = FMCPCommonUtils::ActorToJsonObject(Actor);
			if (!ActorObject.IsValid())
			{
				ActorObject = MakeShared<FJsonObject>();
			}

			ActorObject->SetBoolField(TEXT("is_selected"), bIsSelected);
			ActorObject->SetStringField(TEXT("label"), Actor->GetActorLabel());
			ActorObject->SetStringField(TEXT("path"), Actor->GetPathName());

			if (bIncludeComponentDetails || bIsSelected)
			{
				const FTransform ActorTransform = Actor->GetActorTransform();
				ActorObject->SetArrayField(TEXT("actor_scale"), VectorToJson(ActorTransform.GetScale3D()));
				ActorObject->SetArrayField(TEXT("actor_rotation"), RotatorToJson(ActorTransform.Rotator()));
				ActorObject->SetObjectField(TEXT("components_bounds"), BoundsToJson(Actor->GetComponentsBoundingBox(true, true)));

				TArray<UActorComponent*> Components;
				Actor->GetComponents(Components);
				ActorObject->SetNumberField(TEXT("component_count"), Components.Num());

				TArray<UStaticMeshComponent*> StaticMeshComponents;
				Actor->GetComponents<UStaticMeshComponent>(StaticMeshComponents);
				ActorObject->SetNumberField(TEXT("static_mesh_component_count"), StaticMeshComponents.Num());

				TArray<TSharedPtr<FJsonValue>> ComponentArray;
				for (UStaticMeshComponent* StaticMeshComponent : StaticMeshComponents)
				{
					if (!StaticMeshComponent)
					{
						continue;
					}

					TSharedPtr<FJsonObject> ComponentObject = MakeShared<FJsonObject>();
					ComponentObject->SetStringField(TEXT("name"), StaticMeshComponent->GetName());
					ComponentObject->SetStringField(TEXT("path"), StaticMeshComponent->GetPathName());
					ComponentObject->SetStringField(TEXT("collision_profile"), StaticMeshComponent->GetCollisionProfileName().ToString());
					ComponentObject->SetNumberField(TEXT("collision_enabled"), static_cast<int32>(StaticMeshComponent->GetCollisionEnabled()));
					ComponentObject->SetNumberField(TEXT("object_type"), static_cast<int32>(StaticMeshComponent->GetCollisionObjectType()));
					ComponentObject->SetBoolField(TEXT("is_registered"), StaticMeshComponent->IsRegistered());
					ComponentObject->SetBoolField(TEXT("is_visible"), StaticMeshComponent->IsVisible());
					ComponentObject->SetBoolField(TEXT("is_simulating_physics"), StaticMeshComponent->IsSimulatingPhysics());
					ComponentObject->SetArrayField(TEXT("component_location"), VectorToJson(StaticMeshComponent->GetComponentLocation()));
					ComponentObject->SetArrayField(TEXT("component_rotation"), RotatorToJson(StaticMeshComponent->GetComponentRotation()));
					ComponentObject->SetArrayField(TEXT("component_scale"), VectorToJson(StaticMeshComponent->GetComponentTransform().GetScale3D()));
					ComponentObject->SetObjectField(TEXT("bounds"), SphereBoundsToJson(StaticMeshComponent->Bounds));

					UStaticMesh* StaticMesh = StaticMeshComponent->GetStaticMesh();
					ComponentObject->SetBoolField(TEXT("has_static_mesh"), StaticMesh != nullptr);
					if (StaticMesh)
					{
						ComponentObject->SetStringField(TEXT("static_mesh_name"), StaticMesh->GetName());
						ComponentObject->SetStringField(TEXT("static_mesh_path"), StaticMesh->GetPathName());
						if (bIncludeLJCPackedChunkSummary)
						{
							ComponentObject->SetObjectField(TEXT("ljc_packed_chunk_asset"), BuildLJCPackedChunkInfo(Actor, StaticMesh));
						}
					}

					ComponentArray.Add(MakeShared<FJsonValueObject>(ComponentObject));
				}

				ActorObject->SetArrayField(TEXT("static_mesh_components"), ComponentArray);
			}

			ActorArray.Add(MakeShared<FJsonValueObject>(ActorObject));
		}
	}

	TSharedPtr<FJsonObject> Result = MakeShared<FJsonObject>();
	Result->SetBoolField(TEXT("selected_only"), bSelectedOnly);
	Result->SetNumberField(TEXT("selected_count"), SelectedCount);
	Result->SetArrayField(TEXT("actors"), ActorArray);
	return CreateSuccessResponse(Result);
}


// ============================================================================
// FFindActorsByNameAction
// ============================================================================

bool FFindActorsByNameAction::Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError)
{
	FString Pattern;
	return GetRequiredString(Params, TEXT("pattern"), Pattern, OutError);
}

TSharedPtr<FJsonObject> FFindActorsByNameAction::ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context)
{
	FString Pattern, Error;
	GetRequiredString(Params, TEXT("pattern"), Pattern, Error);

	const FString RequestedWorldScope =
		GetOptionalString(Params, TEXT("world_scope"), TEXT("editor"));
	FString ResolvedWorldScope = RequestedWorldScope.ToLower();
	if (ResolvedWorldScope == TEXT("auto"))
	{
		ResolvedWorldScope =
			GEditor && GEditor->PlayWorld ? TEXT("pie") : TEXT("editor");
	}
	if (ResolvedWorldScope != TEXT("editor")
		&& ResolvedWorldScope != TEXT("pie"))
	{
		return CreateErrorResponse(
			FString::Printf(
				TEXT("Invalid world_scope '%s'; expected editor, pie, or auto."),
				*RequestedWorldScope),
			TEXT("invalid_world_scope"));
	}

	UWorld* World = nullptr;
	if (GEditor)
	{
		World = ResolvedWorldScope == TEXT("pie")
			? GEditor->PlayWorld.Get()
			: GEditor->GetEditorWorldContext().World();
	}
	if (!World)
	{
		return CreateErrorResponse(
			FString::Printf(
				TEXT("No %s world available"),
				*ResolvedWorldScope),
			TEXT("no_world"));
	}

	TArray<AActor*> AllActors;
	UGameplayStatics::GetAllActorsOfClass(World, AActor::StaticClass(), AllActors);

	TArray<TSharedPtr<FJsonValue>> MatchingActors;
	for (AActor* Actor : AllActors)
	{
		if (Actor
			&& (Actor->GetName().Contains(Pattern)
				|| Actor->GetActorLabel().Contains(Pattern)))
		{
			MatchingActors.Add(FMCPCommonUtils::ActorToJsonValue(Actor));
		}
	}

	TSharedPtr<FJsonObject> Result = MakeShared<FJsonObject>();
	Result->SetStringField(TEXT("world_scope"), ResolvedWorldScope);
	Result->SetStringField(TEXT("world_name"), World->GetName());
	Result->SetArrayField(TEXT("actors"), MatchingActors);
	return CreateSuccessResponse(Result);
}


// ============================================================================
// FGetRuntimeWidgetsAction
// ============================================================================

bool FGetRuntimeWidgetsAction::Validate(
	const TSharedPtr<FJsonObject>& Params,
	FMCPEditorContext& Context,
	FString& OutError)
{
	const FString WorldScope =
		GetOptionalString(Params, TEXT("world_scope"), TEXT("auto")).ToLower();
	if (WorldScope != TEXT("editor")
		&& WorldScope != TEXT("pie")
		&& WorldScope != TEXT("auto"))
	{
		OutError = FString::Printf(
			TEXT("Invalid world_scope '%s'; expected editor, pie, or auto."),
			*WorldScope);
		return false;
	}
	return true;
}

TSharedPtr<FJsonObject> FGetRuntimeWidgetsAction::ExecuteInternal(
	const TSharedPtr<FJsonObject>& Params,
	FMCPEditorContext& Context)
{
	FString ResolvedWorldScope =
		GetOptionalString(Params, TEXT("world_scope"), TEXT("auto")).ToLower();
	if (ResolvedWorldScope == TEXT("auto"))
	{
		ResolvedWorldScope =
			GEditor && GEditor->PlayWorld ? TEXT("pie") : TEXT("editor");
	}

	UWorld* World = nullptr;
	if (GEditor)
	{
		World = ResolvedWorldScope == TEXT("pie")
			? GEditor->PlayWorld.Get()
			: GEditor->GetEditorWorldContext().World();
	}
	if (!World)
	{
		return CreateErrorResponse(
			FString::Printf(TEXT("No %s world available"), *ResolvedWorldScope),
			TEXT("no_world"));
	}

	const FString ClassPattern =
		GetOptionalString(Params, TEXT("class_pattern"), TEXT(""));
	const bool bOnlyVisible =
		GetOptionalBool(Params, TEXT("only_visible"), false);

	auto ResolveTargetActor = [](UUserWidget* Widget) -> AActor*
	{
		if (!Widget)
		{
			return nullptr;
		}

		UFunction* Getter = Widget->FindFunction(TEXT("GetTargetActor"));
		FProperty* ReturnProperty = Getter ? Getter->GetReturnProperty() : nullptr;
		FObjectPropertyBase* ObjectReturn =
			CastField<FObjectPropertyBase>(ReturnProperty);
		if (!Getter || Getter->NumParms != 1 || !ObjectReturn)
		{
			return nullptr;
		}

		TArray<uint8> ParameterBuffer;
		ParameterBuffer.SetNumZeroed(Getter->ParmsSize);
		Widget->ProcessEvent(Getter, ParameterBuffer.GetData());
		return Cast<AActor>(
			ObjectReturn->GetObjectPropertyValue_InContainer(
				ParameterBuffer.GetData()));
	};

	TArray<TSharedPtr<FJsonValue>> Widgets;
	for (TObjectIterator<UUserWidget> It; It; ++It)
	{
		UUserWidget* Widget = *It;
		if (!IsValid(Widget)
			|| Widget->IsTemplate()
			|| Widget->GetWorld() != World)
		{
			continue;
		}

		const FString ClassName = Widget->GetClass()->GetName();
		const FString ClassPath = Widget->GetClass()->GetPathName();
		if (!ClassPattern.IsEmpty()
			&& !ClassName.Contains(ClassPattern, ESearchCase::IgnoreCase)
			&& !ClassPath.Contains(ClassPattern, ESearchCase::IgnoreCase))
		{
			continue;
		}

		const ESlateVisibility Visibility = Widget->GetVisibility();
		const bool bVisible =
			Visibility != ESlateVisibility::Collapsed
			&& Visibility != ESlateVisibility::Hidden
			&& Widget->GetRenderOpacity() > 0.0f;
		if (bOnlyVisible && !bVisible)
		{
			continue;
		}

		TSharedPtr<FJsonObject> WidgetJson = MakeShared<FJsonObject>();
		WidgetJson->SetStringField(TEXT("name"), Widget->GetName());
		WidgetJson->SetStringField(TEXT("class"), ClassName);
		WidgetJson->SetStringField(TEXT("class_path"), ClassPath);
		WidgetJson->SetStringField(
			TEXT("visibility"),
			UEnum::GetValueAsString(Visibility));
		WidgetJson->SetBoolField(TEXT("is_visible"), bVisible);
		WidgetJson->SetBoolField(TEXT("is_in_viewport"), Widget->IsInViewport());
		WidgetJson->SetNumberField(
			TEXT("render_opacity"),
			Widget->GetRenderOpacity());
		WidgetJson->SetStringField(
			TEXT("owning_player"),
			GetNameSafe(Widget->GetOwningPlayer()));

		if (AActor* TargetActor = ResolveTargetActor(Widget))
		{
			WidgetJson->SetStringField(
				TEXT("target_actor_name"),
				TargetActor->GetName());
			WidgetJson->SetStringField(
				TEXT("target_actor_class"),
				TargetActor->GetClass()->GetName());
			WidgetJson->SetStringField(
				TEXT("target_actor_path"),
				TargetActor->GetPathName());
		}

		Widgets.Add(MakeShared<FJsonValueObject>(WidgetJson));
	}

	TSharedPtr<FJsonObject> Result = MakeShared<FJsonObject>();
	Result->SetStringField(TEXT("world_scope"), ResolvedWorldScope);
	Result->SetStringField(TEXT("world_name"), World->GetName());
	Result->SetNumberField(TEXT("count"), Widgets.Num());
	Result->SetArrayField(TEXT("widgets"), Widgets);
	return CreateSuccessResponse(Result);
}


// ============================================================================
// FSpawnActorAction
// ============================================================================

bool FSpawnActorAction::Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError)
{
	FString Name, Type;
	if (!GetRequiredString(Params, TEXT("name"), Name, OutError)) return false;
	if (!GetRequiredString(Params, TEXT("type"), Type, OutError)) return false;
	return true;
}

TSharedPtr<FJsonObject> FSpawnActorAction::ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context)
{
	FString ActorName, ActorType, Error;
	GetRequiredString(Params, TEXT("name"), ActorName, Error);
	GetRequiredString(Params, TEXT("type"), ActorType, Error);

	UWorld* World = GEditor ? GEditor->GetEditorWorldContext().World() : nullptr;
	if (!World)
	{
		return CreateErrorResponse(TEXT("No editor world available"), TEXT("no_world"));
	}

	// Resolve actor class
	UClass* ActorClass = ResolveActorClass(ActorType);
	if (!ActorClass)
	{
		return CreateErrorResponse(
			FString::Printf(TEXT("Unknown actor type: %s"), *ActorType),
			TEXT("invalid_type")
		);
	}

	// Delete existing actor with same name
	AActor* Existing = FindActorByName(World, ActorName);
	if (Existing)
	{
		World->DestroyActor(Existing);
	}

	// Parse transform
	FVector Location = FMCPCommonUtils::GetVectorFromJson(Params, TEXT("location"));
	FRotator Rotation = FMCPCommonUtils::GetRotatorFromJson(Params, TEXT("rotation"));
	FVector Scale = Params->HasField(TEXT("scale")) ?
		FMCPCommonUtils::GetVectorFromJson(Params, TEXT("scale")) : FVector(1, 1, 1);

	// Spawn
	FActorSpawnParameters SpawnParams;
	SpawnParams.Name = FName(*ActorName);
	SpawnParams.NameMode = FActorSpawnParameters::ESpawnActorNameMode::Requested;

	AActor* NewActor = World->SpawnActor<AActor>(ActorClass, Location, Rotation, SpawnParams);
	if (!NewActor)
	{
		return CreateErrorResponse(TEXT("Failed to spawn actor"), TEXT("spawn_failed"));
	}

	NewActor->SetActorScale3D(Scale);
	NewActor->SetActorLabel(*ActorName);
	Context.LastCreatedActorName = ActorName;

	// Mark level dirty so auto-save works
	Context.MarkPackageDirty(World->GetOutermost());

	UE_LOG(LogMCP, Log, TEXT("UEEditorMCP: Spawned actor '%s' of type '%s'"), *ActorName, *ActorType);

	return CreateSuccessResponse(FMCPCommonUtils::ActorToJsonObject(NewActor));
}

UClass* FSpawnActorAction::ResolveActorClass(const FString& TypeName) const
{
	if (TypeName == TEXT("StaticMeshActor")) return AStaticMeshActor::StaticClass();
	if (TypeName == TEXT("PointLight")) return APointLight::StaticClass();
	if (TypeName == TEXT("SpotLight")) return ASpotLight::StaticClass();
	if (TypeName == TEXT("DirectionalLight")) return ADirectionalLight::StaticClass();
	if (TypeName == TEXT("CameraActor")) return ACameraActor::StaticClass();
	if (TypeName == TEXT("Actor")) return AActor::StaticClass();

	// Generic fallback: support /Script/Foo.Bar paths and bare native class names
	// (e.g. "PlayerStart", "TargetPoint"). Useful for level setup automation.
	if (TypeName.StartsWith(TEXT("/Script/")))
	{
		if (UClass* Loaded = LoadClass<AActor>(nullptr, *TypeName))
		{
			return Loaded;
		}
	}
	if (UClass* Found = FindFirstObject<UClass>(*TypeName, EFindFirstObjectOptions::ExactClass))
	{
		if (Found->IsChildOf(AActor::StaticClass()))
		{
			return Found;
		}
	}

	return nullptr;
}


// ============================================================================
// FDeleteActorAction
// ============================================================================

bool FDeleteActorAction::Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError)
{
	FString Name;
	return GetRequiredString(Params, TEXT("name"), Name, OutError);
}

TSharedPtr<FJsonObject> FDeleteActorAction::ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context)
{
	FString ActorName, Error;
	GetRequiredString(Params, TEXT("name"), ActorName, Error);

	UWorld* World = GEditor ? GEditor->GetEditorWorldContext().World() : nullptr;
	if (!World)
	{
		return CreateErrorResponse(TEXT("No editor world available"), TEXT("no_world"));
	}

	AActor* Actor = FindActorByName(World, ActorName);
	if (!Actor)
	{
		return CreateErrorResponse(
			FString::Printf(TEXT("Actor not found: %s"), *ActorName),
			TEXT("not_found")
		);
	}

	// Store info before deletion
	TSharedPtr<FJsonObject> ActorInfo = FMCPCommonUtils::ActorToJsonObject(Actor);

	// Use editor-proper destruction which handles World Partition external actors
	bool bDestroyed = World->EditorDestroyActor(Actor, true);
	if (!bDestroyed)
	{
		// Fallback to regular destroy
		Actor->Destroy();
	}

	// Mark world dirty
	Context.MarkPackageDirty(World->GetOutermost());

	UE_LOG(LogMCP, Log, TEXT("UEEditorMCP: Deleted actor '%s'"), *ActorName);

	TSharedPtr<FJsonObject> Result = MakeShared<FJsonObject>();
	Result->SetObjectField(TEXT("deleted_actor"), ActorInfo);
	return CreateSuccessResponse(Result);
}


// ============================================================================
// FSetActorTransformAction
// ============================================================================

bool FSetActorTransformAction::Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError)
{
	FString Name;
	return GetRequiredString(Params, TEXT("name"), Name, OutError);
}

TSharedPtr<FJsonObject> FSetActorTransformAction::ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context)
{
	FString ActorName, Error;
	GetRequiredString(Params, TEXT("name"), ActorName, Error);

	UWorld* World = GEditor ? GEditor->GetEditorWorldContext().World() : nullptr;
	if (!World)
	{
		return CreateErrorResponse(TEXT("No editor world available"), TEXT("no_world"));
	}

	AActor* Actor = FindActorByName(World, ActorName);
	if (!Actor)
	{
		return CreateErrorResponse(
			FString::Printf(TEXT("Actor not found: %s"), *ActorName),
			TEXT("not_found")
		);
	}

	// Update transform
	FTransform Transform = Actor->GetTransform();

	if (Params->HasField(TEXT("location")))
	{
		Transform.SetLocation(FMCPCommonUtils::GetVectorFromJson(Params, TEXT("location")));
	}
	if (Params->HasField(TEXT("rotation")))
	{
		Transform.SetRotation(FQuat(FMCPCommonUtils::GetRotatorFromJson(Params, TEXT("rotation"))));
	}
	if (Params->HasField(TEXT("scale")))
	{
		Transform.SetScale3D(FMCPCommonUtils::GetVectorFromJson(Params, TEXT("scale")));
	}

	Actor->SetActorTransform(Transform);

	// Mark level dirty so auto-save works
	Context.MarkPackageDirty(World->GetOutermost());

	UE_LOG(LogMCP, Log, TEXT("UEEditorMCP: Set transform on actor '%s'"), *ActorName);

	return CreateSuccessResponse(FMCPCommonUtils::ActorToJsonObject(Actor));
}


// ============================================================================
// FGetActorPropertiesAction
// ============================================================================

bool FGetActorPropertiesAction::Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError)
{
	FString Name;
	return GetRequiredString(Params, TEXT("name"), Name, OutError);
}

// --- Property value serialization helper ---
TSharedPtr<FJsonValue> FGetActorPropertiesAction::PropertyValueToJson(FProperty* Property, const void* ValuePtr)
{
	if (!Property || !ValuePtr)
	{
		return MakeShared<FJsonValueNull>();
	}

	if (FBoolProperty* BoolProp = CastField<FBoolProperty>(Property))
	{
		return MakeShared<FJsonValueBoolean>(BoolProp->GetPropertyValue(ValuePtr));
	}
	else if (FIntProperty* IntProp = CastField<FIntProperty>(Property))
	{
		return MakeShared<FJsonValueNumber>(IntProp->GetPropertyValue(ValuePtr));
	}
	else if (FInt64Property* Int64Prop = CastField<FInt64Property>(Property))
	{
		return MakeShared<FJsonValueNumber>(static_cast<double>(Int64Prop->GetPropertyValue(ValuePtr)));
	}
	else if (FFloatProperty* FloatProp = CastField<FFloatProperty>(Property))
	{
		return MakeShared<FJsonValueNumber>(FloatProp->GetPropertyValue(ValuePtr));
	}
	else if (FDoubleProperty* DoubleProp = CastField<FDoubleProperty>(Property))
	{
		return MakeShared<FJsonValueNumber>(DoubleProp->GetPropertyValue(ValuePtr));
	}
	else if (FByteProperty* ByteProp = CastField<FByteProperty>(Property))
	{
		uint8 Val = ByteProp->GetPropertyValue(ValuePtr);
		UEnum* EnumDef = ByteProp->Enum;
		if (EnumDef)
		{
			FString EnumName = EnumDef->GetNameStringByValue(Val);
			return MakeShared<FJsonValueString>(EnumName);
		}
		return MakeShared<FJsonValueNumber>(Val);
	}
	else if (FEnumProperty* EnumProp = CastField<FEnumProperty>(Property))
	{
		UEnum* EnumDef = EnumProp->GetEnum();
		FNumericProperty* UnderlyingProp = EnumProp->GetUnderlyingProperty();
		if (EnumDef && UnderlyingProp)
		{
			int64 Val = UnderlyingProp->GetSignedIntPropertyValue(ValuePtr);
			FString EnumName = EnumDef->GetNameStringByValue(Val);
			return MakeShared<FJsonValueString>(EnumName);
		}
		return MakeShared<FJsonValueNull>();
	}
	else if (FStrProperty* StrProp = CastField<FStrProperty>(Property))
	{
		return MakeShared<FJsonValueString>(StrProp->GetPropertyValue(ValuePtr));
	}
	else if (FNameProperty* NameProp = CastField<FNameProperty>(Property))
	{
		return MakeShared<FJsonValueString>(NameProp->GetPropertyValue(ValuePtr).ToString());
	}
	else if (FTextProperty* TextProp = CastField<FTextProperty>(Property))
	{
		return MakeShared<FJsonValueString>(TextProp->GetPropertyValue(ValuePtr).ToString());
	}
	else if (FStructProperty* StructProp = CastField<FStructProperty>(Property))
	{
		if (StructProp->Struct == TBaseStructure<FVector>::Get())
		{
			const FVector& Vec = *(const FVector*)ValuePtr;
			TArray<TSharedPtr<FJsonValue>> Arr;
			Arr.Add(MakeShared<FJsonValueNumber>(Vec.X));
			Arr.Add(MakeShared<FJsonValueNumber>(Vec.Y));
			Arr.Add(MakeShared<FJsonValueNumber>(Vec.Z));
			return MakeShared<FJsonValueArray>(Arr);
		}
		else if (StructProp->Struct == TBaseStructure<FRotator>::Get())
		{
			const FRotator& Rot = *(const FRotator*)ValuePtr;
			TArray<TSharedPtr<FJsonValue>> Arr;
			Arr.Add(MakeShared<FJsonValueNumber>(Rot.Pitch));
			Arr.Add(MakeShared<FJsonValueNumber>(Rot.Yaw));
			Arr.Add(MakeShared<FJsonValueNumber>(Rot.Roll));
			return MakeShared<FJsonValueArray>(Arr);
		}
		else if (StructProp->Struct == TBaseStructure<FLinearColor>::Get())
		{
			const FLinearColor& Color = *(const FLinearColor*)ValuePtr;
			TSharedPtr<FJsonObject> Obj = MakeShared<FJsonObject>();
			Obj->SetNumberField(TEXT("r"), Color.R);
			Obj->SetNumberField(TEXT("g"), Color.G);
			Obj->SetNumberField(TEXT("b"), Color.B);
			Obj->SetNumberField(TEXT("a"), Color.A);
			return MakeShared<FJsonValueObject>(Obj);
		}
		else if (StructProp->Struct == TBaseStructure<FColor>::Get())
		{
			const FColor& Color = *(const FColor*)ValuePtr;
			TSharedPtr<FJsonObject> Obj = MakeShared<FJsonObject>();
			Obj->SetNumberField(TEXT("r"), Color.R);
			Obj->SetNumberField(TEXT("g"), Color.G);
			Obj->SetNumberField(TEXT("b"), Color.B);
			Obj->SetNumberField(TEXT("a"), Color.A);
			return MakeShared<FJsonValueObject>(Obj);
		}
		else if (StructProp->Struct == TBaseStructure<FTransform>::Get())
		{
			const FTransform& Transform = *(const FTransform*)ValuePtr;
			TSharedPtr<FJsonObject> Obj = MakeShared<FJsonObject>();
			FVector Loc = Transform.GetLocation();
			FRotator Rot = Transform.Rotator();
			FVector Scale = Transform.GetScale3D();

			TArray<TSharedPtr<FJsonValue>> LocArr, RotArr, ScaleArr;
			LocArr.Add(MakeShared<FJsonValueNumber>(Loc.X));
			LocArr.Add(MakeShared<FJsonValueNumber>(Loc.Y));
			LocArr.Add(MakeShared<FJsonValueNumber>(Loc.Z));
			RotArr.Add(MakeShared<FJsonValueNumber>(Rot.Pitch));
			RotArr.Add(MakeShared<FJsonValueNumber>(Rot.Yaw));
			RotArr.Add(MakeShared<FJsonValueNumber>(Rot.Roll));
			ScaleArr.Add(MakeShared<FJsonValueNumber>(Scale.X));
			ScaleArr.Add(MakeShared<FJsonValueNumber>(Scale.Y));
			ScaleArr.Add(MakeShared<FJsonValueNumber>(Scale.Z));

			Obj->SetArrayField(TEXT("location"), LocArr);
			Obj->SetArrayField(TEXT("rotation"), RotArr);
			Obj->SetArrayField(TEXT("scale"), ScaleArr);
			return MakeShared<FJsonValueObject>(Obj);
		}
		else
		{
			// Generic struct: use ExportText
			FString ExportedValue;
			StructProp->ExportTextItem_Direct(ExportedValue, ValuePtr, nullptr, nullptr, PPF_None);
			return MakeShared<FJsonValueString>(ExportedValue);
		}
	}
	else if (FObjectProperty* ObjProp = CastField<FObjectProperty>(Property))
	{
		UObject* ObjValue = ObjProp->GetObjectPropertyValue(ValuePtr);
		if (ObjValue)
		{
			return MakeShared<FJsonValueString>(ObjValue->GetPathName());
		}
		return MakeShared<FJsonValueString>(TEXT("None"));
	}
	else if (FClassProperty* ClassProp = CastField<FClassProperty>(Property))
	{
		UClass* ClassValue = Cast<UClass>(ClassProp->GetObjectPropertyValue(ValuePtr));
		if (ClassValue)
		{
			return MakeShared<FJsonValueString>(ClassValue->GetPathName());
		}
		return MakeShared<FJsonValueString>(TEXT("None"));
	}
	else if (FArrayProperty* ArrayProp = CastField<FArrayProperty>(Property))
	{
		FScriptArrayHelper ArrayHelper(ArrayProp, ValuePtr);
		TArray<TSharedPtr<FJsonValue>> Arr;
		int32 Count = FMath::Min(ArrayHelper.Num(), 100); // Cap at 100 elements
		for (int32 i = 0; i < Count; ++i)
		{
			Arr.Add(PropertyValueToJson(ArrayProp->Inner, ArrayHelper.GetRawPtr(i)));
		}
		return MakeShared<FJsonValueArray>(Arr);
	}

	// Fallback: use ExportText
	FString ExportedValue;
	Property->ExportTextItem_Direct(ExportedValue, ValuePtr, nullptr, nullptr, PPF_None);
	return MakeShared<FJsonValueString>(ExportedValue);
}

// --- Property type string helper ---
FString FGetActorPropertiesAction::GetPropertyTypeString(FProperty* Property)
{
	if (!Property) return TEXT("Unknown");

	if (CastField<FBoolProperty>(Property)) return TEXT("Boolean");
	if (CastField<FIntProperty>(Property)) return TEXT("Int32");
	if (CastField<FInt64Property>(Property)) return TEXT("Int64");
	if (CastField<FFloatProperty>(Property)) return TEXT("Float");
	if (CastField<FDoubleProperty>(Property)) return TEXT("Double");
	if (CastField<FStrProperty>(Property)) return TEXT("String");
	if (CastField<FNameProperty>(Property)) return TEXT("Name");
	if (CastField<FTextProperty>(Property)) return TEXT("Text");

	if (FByteProperty* ByteProp = CastField<FByteProperty>(Property))
	{
		if (ByteProp->Enum) return FString::Printf(TEXT("Enum(%s)"), *ByteProp->Enum->GetName());
		return TEXT("Byte");
	}
	if (FEnumProperty* EnumProp = CastField<FEnumProperty>(Property))
	{
		if (EnumProp->GetEnum()) return FString::Printf(TEXT("Enum(%s)"), *EnumProp->GetEnum()->GetName());
		return TEXT("Enum");
	}
	if (FStructProperty* StructProp = CastField<FStructProperty>(Property))
	{
		return FString::Printf(TEXT("Struct(%s)"), *StructProp->Struct->GetName());
	}
	if (FObjectProperty* ObjProp = CastField<FObjectProperty>(Property))
	{
		return FString::Printf(TEXT("Object(%s)"), *ObjProp->PropertyClass->GetName());
	}
	if (FClassProperty* ClassProp = CastField<FClassProperty>(Property))
	{
		return FString::Printf(TEXT("Class(%s)"), *ClassProp->MetaClass->GetName());
	}
	if (FArrayProperty* ArrayProp = CastField<FArrayProperty>(Property))
	{
		return FString::Printf(TEXT("Array(%s)"), *GetPropertyTypeString(ArrayProp->Inner));
	}
	if (FSetProperty* SetProp = CastField<FSetProperty>(Property))
	{
		return FString::Printf(TEXT("Set(%s)"), *GetPropertyTypeString(SetProp->ElementProp));
	}
	if (FMapProperty* MapProp = CastField<FMapProperty>(Property))
	{
		return FString::Printf(TEXT("Map(%s, %s)"),
			*GetPropertyTypeString(MapProp->KeyProp),
			*GetPropertyTypeString(MapProp->ValueProp));
	}
	if (CastField<FSoftObjectProperty>(Property)) return TEXT("SoftObjectReference");
	if (CastField<FSoftClassProperty>(Property)) return TEXT("SoftClassReference");
	if (CastField<FWeakObjectProperty>(Property)) return TEXT("WeakObjectReference");
	if (CastField<FInterfaceProperty>(Property)) return TEXT("Interface");
	if (CastField<FDelegateProperty>(Property)) return TEXT("Delegate");
	if (CastField<FMulticastDelegateProperty>(Property)) return TEXT("MulticastDelegate");

	return Property->GetCPPType();
}

TSharedPtr<FJsonObject> FGetActorPropertiesAction::ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context)
{
	FString ActorName, Error;
	GetRequiredString(Params, TEXT("name"), ActorName, Error);

	const bool bDetailed = GetOptionalBool(Params, TEXT("detailed"), false);
	const bool bEditableOnly = GetOptionalBool(Params, TEXT("editable_only"), false);
	const FString CategoryFilter = GetOptionalString(Params, TEXT("category"));

	UWorld* World = GEditor ? GEditor->GetEditorWorldContext().World() : nullptr;
	if (!World)
	{
		return CreateErrorResponse(TEXT("No editor world available"), TEXT("no_world"));
	}

	AActor* Actor = FindActorByName(World, ActorName);
	if (!Actor)
	{
		return CreateErrorResponse(
			FString::Printf(TEXT("Actor not found: %s"), *ActorName),
			TEXT("not_found")
		);
	}

	// Always include basic info (backward compatible)
	TSharedPtr<FJsonObject> Result = FMCPCommonUtils::ActorToJsonObject(Actor);

	if (bDetailed)
	{
		// Determine if this is a Blueprint-generated actor
		UBlueprintGeneratedClass* BPGC = Cast<UBlueprintGeneratedClass>(Actor->GetClass());
		if (BPGC)
		{
			Result->SetBoolField(TEXT("is_blueprint_actor"), true);
			if (BPGC->ClassGeneratedBy)
			{
				Result->SetStringField(TEXT("blueprint_name"), BPGC->ClassGeneratedBy->GetName());
				Result->SetStringField(TEXT("blueprint_path"), BPGC->ClassGeneratedBy->GetPathName());
			}
		}
		else
		{
			Result->SetBoolField(TEXT("is_blueprint_actor"), false);
		}

		// Enumerate ALL FProperty fields on the actor's class
		TArray<TSharedPtr<FJsonValue>> PropertiesArray;
		UClass* ActorClass = Actor->GetClass();

		// Determine where native AActor properties end (to flag blueprint variables)
		UClass* NativeStopClass = AActor::StaticClass();

		for (TFieldIterator<FProperty> PropIt(ActorClass); PropIt; ++PropIt)
		{
			FProperty* Property = *PropIt;
			if (!Property) continue;

			// Filter: editable_only
			const bool bIsEditable = Property->HasAnyPropertyFlags(CPF_Edit);
			if (bEditableOnly && !bIsEditable) continue;

			// Filter: category
			FString PropCategory = Property->GetMetaData(TEXT("Category"));
			if (!CategoryFilter.IsEmpty() && !PropCategory.Contains(CategoryFilter)) continue;

			// Skip deprecated and transient unless explicitly asked
			if (Property->HasAnyPropertyFlags(CPF_Deprecated)) continue;

			// Determine if this is a Blueprint variable (defined in Generated class, not in native)
			bool bIsBlueprintVar = false;
			UClass* OwnerClass = Property->GetOwnerClass();
			if (OwnerClass && BPGC)
			{
				bIsBlueprintVar = OwnerClass->IsChildOf(BPGC) || OwnerClass == BPGC;
				// Also check if owner is any BP generated class in the hierarchy
				if (!bIsBlueprintVar)
				{
					bIsBlueprintVar = (Cast<UBlueprintGeneratedClass>(OwnerClass) != nullptr);
				}
			}

			TSharedPtr<FJsonObject> PropObj = MakeShared<FJsonObject>();
			PropObj->SetStringField(TEXT("name"), Property->GetName());
			PropObj->SetStringField(TEXT("type"), GetPropertyTypeString(Property));
			PropObj->SetBoolField(TEXT("is_editable"), bIsEditable);
			PropObj->SetBoolField(TEXT("is_blueprint_variable"), bIsBlueprintVar);

			if (!PropCategory.IsEmpty())
			{
				PropObj->SetStringField(TEXT("category"), PropCategory);
			}

			// Property flags of interest
			PropObj->SetBoolField(TEXT("is_visible_in_defaults"), Property->HasAnyPropertyFlags(CPF_Edit | CPF_EditConst));
			PropObj->SetBoolField(TEXT("is_read_only"), Property->HasAnyPropertyFlags(CPF_EditConst));
			PropObj->SetBoolField(TEXT("is_blueprint_visible"), Property->HasAnyPropertyFlags(CPF_BlueprintVisible));
			PropObj->SetBoolField(TEXT("is_expose_on_spawn"), Property->HasAnyPropertyFlags(CPF_ExposeOnSpawn));
			PropObj->SetBoolField(TEXT("is_replicated"), Property->HasAnyPropertyFlags(CPF_Net));

			if (OwnerClass)
			{
				PropObj->SetStringField(TEXT("owner_class"), OwnerClass->GetName());
			}

			// Serialize the value
			const void* ValuePtr = Property->ContainerPtrToValuePtr<void>(Actor);
			PropObj->SetField(TEXT("value"), PropertyValueToJson(Property, ValuePtr));

			PropertiesArray.Add(MakeShared<FJsonValueObject>(PropObj));
		}

		Result->SetArrayField(TEXT("properties"), PropertiesArray);
		Result->SetNumberField(TEXT("property_count"), PropertiesArray.Num());
	}

	return CreateSuccessResponse(Result);
}


// ============================================================================
// FSetActorPropertyAction
// ============================================================================

bool FSetActorPropertyAction::Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError)
{
	FString Name, PropertyName;
	if (!GetRequiredString(Params, TEXT("name"), Name, OutError)) return false;
	if (!GetRequiredString(Params, TEXT("property_name"), PropertyName, OutError)) return false;
	if (!Params->HasField(TEXT("property_value")))
	{
		OutError = TEXT("Missing 'property_value' parameter");
		return false;
	}
	return true;
}

TSharedPtr<FJsonObject> FSetActorPropertyAction::ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context)
{
	FString ActorName, PropertyName, Error;
	GetRequiredString(Params, TEXT("name"), ActorName, Error);
	GetRequiredString(Params, TEXT("property_name"), PropertyName, Error);

	UWorld* World = GEditor ? GEditor->GetEditorWorldContext().World() : nullptr;
	if (!World)
	{
		return CreateErrorResponse(TEXT("No editor world available"), TEXT("no_world"));
	}

	AActor* Actor = FindActorByName(World, ActorName);
	if (!Actor)
	{
		return CreateErrorResponse(
			FString::Printf(TEXT("Actor not found: %s"), *ActorName),
			TEXT("not_found")
		);
	}

	// Look up the property - this works for BOTH native C++ and Blueprint-generated properties
	// because Blueprint variables are compiled into the UBlueprintGeneratedClass as FProperty
	FProperty* Property = Actor->GetClass()->FindPropertyByName(*PropertyName);
	if (!Property)
	{
		// Also try case-insensitive search
		for (TFieldIterator<FProperty> PropIt(Actor->GetClass()); PropIt; ++PropIt)
		{
			if (PropIt->GetName().Equals(PropertyName, ESearchCase::IgnoreCase))
			{
				Property = *PropIt;
				break;
			}
		}
	}

	if (!Property)
	{
		return CreateErrorResponse(
			FString::Printf(TEXT("Property '%s' not found on actor '%s' (class: %s)"), *PropertyName, *ActorName, *Actor->GetClass()->GetName()),
			TEXT("property_not_found")
		);
	}

	TSharedPtr<FJsonValue> JsonValue = Params->Values.FindRef(TEXT("property_value"));

	FString ErrorMessage;
	if (!FMCPCommonUtils::SetObjectProperty(Actor, Property->GetName(), JsonValue, ErrorMessage))
	{
		return CreateErrorResponse(ErrorMessage, TEXT("property_set_failed"));
	}

	// Mark level dirty so auto-save works
	Context.MarkPackageDirty(World->GetOutermost());

	UE_LOG(LogMCP, Log, TEXT("UEEditorMCP: Set property '%s' on actor '%s'"), *PropertyName, *ActorName);

	TSharedPtr<FJsonObject> Result = MakeShared<FJsonObject>();
	Result->SetStringField(TEXT("actor"), ActorName);
	Result->SetStringField(TEXT("property"), Property->GetName());
	Result->SetStringField(TEXT("property_type"), Property->GetCPPType());
	Result->SetBoolField(TEXT("success"), true);
	return CreateSuccessResponse(Result);
}


// ============================================================================
// FFocusViewportAction
// ============================================================================

bool FFocusViewportAction::Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError)
{
	bool HasTarget = Params->HasField(TEXT("target"));
	bool HasLocation = Params->HasField(TEXT("location"));

	if (!HasTarget && !HasLocation)
	{
		OutError = TEXT("Either 'target' or 'location' must be provided");
		return false;
	}
	return true;
}

TSharedPtr<FJsonObject> FFocusViewportAction::ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context)
{
	FLevelEditorViewportClient* ViewportClient = nullptr;
	if (GEditor && GEditor->GetActiveViewport())
	{
		ViewportClient = (FLevelEditorViewportClient*)GEditor->GetActiveViewport()->GetClient();
	}

	if (!ViewportClient)
	{
		return CreateErrorResponse(TEXT("Failed to get active viewport"), TEXT("no_viewport"));
	}

	float Distance = GetOptionalNumber(Params, TEXT("distance"), 1000.0f);
	FVector TargetLocation(0, 0, 0);

	if (Params->HasField(TEXT("target")))
	{
		FString TargetActorName = Params->GetStringField(TEXT("target"));
		UWorld* World = GEditor ? GEditor->GetEditorWorldContext().World() : nullptr;
		AActor* TargetActor = FindActorByName(World, TargetActorName);

		if (!TargetActor)
		{
			return CreateErrorResponse(
				FString::Printf(TEXT("Actor not found: %s"), *TargetActorName),
				TEXT("not_found")
			);
		}
		TargetLocation = TargetActor->GetActorLocation();
	}
	else
	{
		TargetLocation = FMCPCommonUtils::GetVectorFromJson(Params, TEXT("location"));
	}

	ViewportClient->SetViewLocation(TargetLocation - FVector(Distance, 0, 0));

	if (Params->HasField(TEXT("orientation")))
	{
		ViewportClient->SetViewRotation(FMCPCommonUtils::GetRotatorFromJson(Params, TEXT("orientation")));
	}

	ViewportClient->Invalidate();

	TSharedPtr<FJsonObject> Result = MakeShared<FJsonObject>();
	Result->SetBoolField(TEXT("success"), true);
	return CreateSuccessResponse(Result);
}


// ============================================================================
// FGetViewportTransformAction
// ============================================================================

TSharedPtr<FJsonObject> FGetViewportTransformAction::ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context)
{
	FLevelEditorViewportClient* ViewportClient = nullptr;
	if (GEditor && GEditor->GetActiveViewport())
	{
		ViewportClient = (FLevelEditorViewportClient*)GEditor->GetActiveViewport()->GetClient();
	}

	if (!ViewportClient)
	{
		return CreateErrorResponse(TEXT("Failed to get active viewport"), TEXT("no_viewport"));
	}

	FVector Location = ViewportClient->GetViewLocation();
	FRotator Rotation = ViewportClient->GetViewRotation();

	TSharedPtr<FJsonObject> Result = MakeShared<FJsonObject>();

	TArray<TSharedPtr<FJsonValue>> LocationArray;
	LocationArray.Add(MakeShared<FJsonValueNumber>(Location.X));
	LocationArray.Add(MakeShared<FJsonValueNumber>(Location.Y));
	LocationArray.Add(MakeShared<FJsonValueNumber>(Location.Z));
	Result->SetArrayField(TEXT("location"), LocationArray);

	TArray<TSharedPtr<FJsonValue>> RotationArray;
	RotationArray.Add(MakeShared<FJsonValueNumber>(Rotation.Pitch));
	RotationArray.Add(MakeShared<FJsonValueNumber>(Rotation.Yaw));
	RotationArray.Add(MakeShared<FJsonValueNumber>(Rotation.Roll));
	Result->SetArrayField(TEXT("rotation"), RotationArray);

	return CreateSuccessResponse(Result);
}


// ============================================================================
// FSetViewportTransformAction
// ============================================================================

bool FSetViewportTransformAction::Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError)
{
	if (!Params->HasField(TEXT("location")) && !Params->HasField(TEXT("rotation")))
	{
		OutError = TEXT("At least 'location' or 'rotation' must be provided");
		return false;
	}
	return true;
}

TSharedPtr<FJsonObject> FSetViewportTransformAction::ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context)
{
	FLevelEditorViewportClient* ViewportClient = nullptr;
	if (GEditor && GEditor->GetActiveViewport())
	{
		ViewportClient = (FLevelEditorViewportClient*)GEditor->GetActiveViewport()->GetClient();
	}

	if (!ViewportClient)
	{
		return CreateErrorResponse(TEXT("Failed to get active viewport"), TEXT("no_viewport"));
	}

	if (Params->HasField(TEXT("location")))
	{
		ViewportClient->SetViewLocation(FMCPCommonUtils::GetVectorFromJson(Params, TEXT("location")));
	}
	if (Params->HasField(TEXT("rotation")))
	{
		ViewportClient->SetViewRotation(FMCPCommonUtils::GetRotatorFromJson(Params, TEXT("rotation")));
	}

	ViewportClient->Invalidate();

	// Return new state
	FVector Location = ViewportClient->GetViewLocation();
	FRotator Rotation = ViewportClient->GetViewRotation();

	TSharedPtr<FJsonObject> Result = MakeShared<FJsonObject>();

	TArray<TSharedPtr<FJsonValue>> LocationArray;
	LocationArray.Add(MakeShared<FJsonValueNumber>(Location.X));
	LocationArray.Add(MakeShared<FJsonValueNumber>(Location.Y));
	LocationArray.Add(MakeShared<FJsonValueNumber>(Location.Z));
	Result->SetArrayField(TEXT("location"), LocationArray);

	TArray<TSharedPtr<FJsonValue>> RotationArray;
	RotationArray.Add(MakeShared<FJsonValueNumber>(Rotation.Pitch));
	RotationArray.Add(MakeShared<FJsonValueNumber>(Rotation.Yaw));
	RotationArray.Add(MakeShared<FJsonValueNumber>(Rotation.Roll));
	Result->SetArrayField(TEXT("rotation"), RotationArray);

	return CreateSuccessResponse(Result);
}


// ============================================================================
// FSaveAllAction
// ============================================================================

TSharedPtr<FJsonObject> FSaveAllAction::ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context)
{
	bool bOnlyMaps = GetOptionalBool(Params, TEXT("only_maps"), false);

	int32 SavedCount = 0;
	TArray<FString> SavedPackages;

	if (bOnlyMaps)
	{
		UWorld* World = GEditor ? GEditor->GetEditorWorldContext().World() : nullptr;
		if (World)
		{
			UPackage* WorldPackage = World->GetOutermost();
			if (WorldPackage && WorldPackage->IsDirty())
			{
				FString PackageFilename;
				if (FPackageName::TryConvertLongPackageNameToFilename(
					WorldPackage->GetName(), PackageFilename, FPackageName::GetMapPackageExtension()))
				{
					FSavePackageArgs SaveArgs;
					SaveArgs.TopLevelFlags = RF_Standalone;
					if (UPackage::SavePackage(WorldPackage, World, *PackageFilename, SaveArgs))
					{
						SavedCount++;
						SavedPackages.Add(WorldPackage->GetName());
					}
				}
			}
		}
	}
	else
	{
		TArray<UPackage*> DirtyPackages;
		FEditorFileUtils::GetDirtyPackages(DirtyPackages);

		for (UPackage* Package : DirtyPackages)
		{
			if (!Package) continue;

			FString PackageFilename;
			FString PackageName = Package->GetName();
			bool bIsMap = Package->ContainsMap();
			FString Extension = bIsMap ?
				FPackageName::GetMapPackageExtension() :
				FPackageName::GetAssetPackageExtension();

			if (FPackageName::TryConvertLongPackageNameToFilename(PackageName, PackageFilename, Extension))
			{
				FSavePackageArgs SaveArgs;
				SaveArgs.TopLevelFlags = RF_Standalone;

				UObject* AssetToSave = bIsMap ? Package->FindAssetInPackage() : nullptr;

				if (UPackage::SavePackage(Package, AssetToSave, *PackageFilename, SaveArgs))
				{
					SavedCount++;
					SavedPackages.Add(PackageName);
					UE_LOG(LogMCP, Log, TEXT("UEEditorMCP SaveAll: Saved %s"), *PackageName);
				}
			}
		}
	}

	TSharedPtr<FJsonObject> Result = MakeShared<FJsonObject>();
	Result->SetNumberField(TEXT("saved_count"), SavedCount);

	TArray<TSharedPtr<FJsonValue>> PackagesArray;
	for (const FString& PkgName : SavedPackages)
	{
		PackagesArray.Add(MakeShared<FJsonValueString>(PkgName));
	}
	Result->SetArrayField(TEXT("saved_packages"), PackagesArray);

	return CreateSuccessResponse(Result);
}


// ========================================================================
// FListAssetsAction
// ========================================================================

bool FListAssetsAction::Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError)
{
	if (!Params->HasField(TEXT("path")))
	{
		OutError = TEXT("Missing required 'path' parameter (e.g. /Game/UI)");
		return false;
	}
	return true;
}

TSharedPtr<FJsonObject> FListAssetsAction::ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context)
{
	FString Path = Params->GetStringField(TEXT("path"));
	bool bRecursive = true;
	if (Params->HasField(TEXT("recursive")))
	{
		bRecursive = Params->GetBoolField(TEXT("recursive"));
	}
	FString ClassFilter;
	if (Params->HasField(TEXT("class_filter")))
	{
		ClassFilter = Params->GetStringField(TEXT("class_filter"));
	}
	FString NameContains;
	if (Params->HasField(TEXT("name_contains")))
	{
		NameContains = Params->GetStringField(TEXT("name_contains"));
	}
	int32 MaxResults = 500;
	if (Params->HasField(TEXT("max_results")))
	{
		MaxResults = static_cast<int32>(Params->GetNumberField(TEXT("max_results")));
	}

	FAssetRegistryModule& AssetRegistryModule = FModuleManager::LoadModuleChecked<FAssetRegistryModule>("AssetRegistry");
	IAssetRegistry& AssetRegistry = AssetRegistryModule.Get();

	FARFilter Filter;
	Filter.PackagePaths.Add(FName(*Path));
	Filter.bRecursivePaths = bRecursive;

	// Apply class filter if specified
	if (!ClassFilter.IsEmpty())
	{
		// Support common short names
		if (ClassFilter == TEXT("Blueprint") || ClassFilter == TEXT("UBlueprint"))
		{
			Filter.ClassPaths.Add(UBlueprint::StaticClass()->GetClassPathName());
			Filter.bRecursiveClasses = true;
		}
		else
		{
			// Try to find the class by name
			UClass* FilterClass = FindFirstObject<UClass>(*ClassFilter, EFindFirstObjectOptions::ExactClass, ELogVerbosity::Warning, TEXT("FListAssetsAction"));
			if (!FilterClass)
			{
				// Try with U prefix
				FilterClass = FindFirstObject<UClass>(*(FString(TEXT("U")) + ClassFilter), EFindFirstObjectOptions::ExactClass, ELogVerbosity::Warning, TEXT("FListAssetsAction"));
			}
			if (FilterClass)
			{
				Filter.ClassPaths.Add(FilterClass->GetClassPathName());
				Filter.bRecursiveClasses = true;
			}
		}
	}

	TArray<FAssetData> AssetList;
	AssetRegistry.GetAssets(Filter, AssetList);

	TArray<TSharedPtr<FJsonValue>> AssetsArray;
	int32 Count = 0;

	for (const FAssetData& AssetData : AssetList)
	{
		if (Count >= MaxResults) break;

		FString AssetName = AssetData.AssetName.ToString();

		// Name filter
		if (!NameContains.IsEmpty() && !AssetName.Contains(NameContains))
		{
			continue;
		}

		TSharedPtr<FJsonObject> AssetObj = MakeShared<FJsonObject>();
		AssetObj->SetStringField(TEXT("asset_name"), AssetName);
		AssetObj->SetStringField(TEXT("asset_path"), AssetData.GetObjectPathString());
		AssetObj->SetStringField(TEXT("package_path"), AssetData.PackagePath.ToString());
		AssetObj->SetStringField(TEXT("asset_class"), AssetData.AssetClassPath.GetAssetName().ToString());

		AssetsArray.Add(MakeShared<FJsonValueObject>(AssetObj));
		Count++;
	}

	TSharedPtr<FJsonObject> Result = MakeShared<FJsonObject>();
	Result->SetNumberField(TEXT("count"), Count);
	Result->SetNumberField(TEXT("total_unfiltered"), AssetList.Num());
	Result->SetStringField(TEXT("path"), Path);
	Result->SetArrayField(TEXT("assets"), AssetsArray);

	return CreateSuccessResponse(Result);
}


// ========================================================================
// FRenameAssetsAction
// ========================================================================

bool FRenameAssetsAction::Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError)
{
	const bool bHasBatch = Params->HasField(TEXT("items"));
	const bool bHasSingle = Params->HasField(TEXT("old_asset_path"));

	if (!bHasBatch && !bHasSingle)
	{
		OutError = TEXT("Provide either 'items' for batch rename or single fields 'old_asset_path', 'new_package_path', 'new_name'");
		return false;
	}

	if (bHasBatch)
	{
		const TArray<TSharedPtr<FJsonValue>>* ItemsArray = nullptr;
		if (!Params->TryGetArrayField(TEXT("items"), ItemsArray) || !ItemsArray || ItemsArray->Num() == 0)
		{
			OutError = TEXT("'items' must be a non-empty array");
			return false;
		}

		for (int32 Index = 0; Index < ItemsArray->Num(); ++Index)
		{
			const TSharedPtr<FJsonValue>& ItemValue = (*ItemsArray)[Index];
			if (!ItemValue.IsValid() || ItemValue->Type != EJson::Object)
			{
				OutError = FString::Printf(TEXT("items[%d] must be an object"), Index);
				return false;
			}

			const TSharedPtr<FJsonObject> ItemObject = ItemValue->AsObject();
			if (!ItemObject.IsValid())
			{
				OutError = FString::Printf(TEXT("items[%d] must be an object"), Index);
				return false;
			}

			FString OldAssetPath;
			FString NewPackagePath;
			FString NewName;
			if (!ItemObject->TryGetStringField(TEXT("old_asset_path"), OldAssetPath) || OldAssetPath.IsEmpty())
			{
				OutError = FString::Printf(TEXT("items[%d].old_asset_path is required"), Index);
				return false;
			}
			if (!ItemObject->TryGetStringField(TEXT("new_package_path"), NewPackagePath) || NewPackagePath.IsEmpty())
			{
				OutError = FString::Printf(TEXT("items[%d].new_package_path is required"), Index);
				return false;
			}
			if (!ItemObject->TryGetStringField(TEXT("new_name"), NewName) || NewName.IsEmpty())
			{
				OutError = FString::Printf(TEXT("items[%d].new_name is required"), Index);
				return false;
			}
		}

		return true;
	}

	FString OldAssetPath;
	FString NewPackagePath;
	FString NewName;
	if (!GetRequiredString(Params, TEXT("old_asset_path"), OldAssetPath, OutError))
	{
		return false;
	}
	if (!GetRequiredString(Params, TEXT("new_package_path"), NewPackagePath, OutError))
	{
		return false;
	}
	if (!GetRequiredString(Params, TEXT("new_name"), NewName, OutError))
	{
		return false;
	}

	return true;
}

TSharedPtr<FJsonObject> FRenameAssetsAction::ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context)
{
	struct FRenameRequestItem
	{
		FString OldAssetPath;
		FString NewPackagePath;
		FString NewName;
	};

	TArray<FRenameRequestItem> RequestItems;

	if (Params->HasField(TEXT("items")))
	{
		const TArray<TSharedPtr<FJsonValue>>* ItemsArray = nullptr;
		Params->TryGetArrayField(TEXT("items"), ItemsArray);
		if (ItemsArray)
		{
			for (const TSharedPtr<FJsonValue>& ItemValue : *ItemsArray)
			{
				if (!ItemValue.IsValid() || ItemValue->Type != EJson::Object)
				{
					continue;
				}

				const TSharedPtr<FJsonObject> ItemObject = ItemValue->AsObject();
				if (!ItemObject.IsValid())
				{
					continue;
				}

				FRenameRequestItem RequestItem;
				if (!ItemObject->TryGetStringField(TEXT("old_asset_path"), RequestItem.OldAssetPath))
				{
					continue;
				}
				if (!ItemObject->TryGetStringField(TEXT("new_package_path"), RequestItem.NewPackagePath))
				{
					continue;
				}
				if (!ItemObject->TryGetStringField(TEXT("new_name"), RequestItem.NewName))
				{
					continue;
				}

				RequestItems.Add(RequestItem);
			}
		}
	}
	else
	{
		FRenameRequestItem RequestItem;
		FString Error;
		GetRequiredString(Params, TEXT("old_asset_path"), RequestItem.OldAssetPath, Error);
		GetRequiredString(Params, TEXT("new_package_path"), RequestItem.NewPackagePath, Error);
		GetRequiredString(Params, TEXT("new_name"), RequestItem.NewName, Error);
		RequestItems.Add(RequestItem);
	}

	if (RequestItems.Num() == 0)
	{
		return CreateErrorResponse(TEXT("No valid rename items were provided"), TEXT("invalid_params"));
	}

	const bool bAutoFixupRedirectors = GetOptionalBool(Params, TEXT("auto_fixup_redirectors"), true);
	const bool bAllowUIPrompts = GetOptionalBool(Params, TEXT("allow_ui_prompts"), false);
	const bool bRequestedCheckoutDialogPrompt = GetOptionalBool(Params, TEXT("checkout_dialog_prompt"), false);
	const FString FixupModeRaw = GetOptionalString(Params, TEXT("fixup_mode"), TEXT("delete")).ToLower();

	ERedirectFixupMode FixupMode = ERedirectFixupMode::DeleteFixedUpRedirectors;
	if (FixupModeRaw == TEXT("leave"))
	{
		FixupMode = ERedirectFixupMode::LeaveFixedUpRedirectors;
	}
	else if (FixupModeRaw == TEXT("prompt"))
	{
		FixupMode = ERedirectFixupMode::PromptForDeletingRedirectors;
	}

	if (!bAllowUIPrompts && FixupMode == ERedirectFixupMode::PromptForDeletingRedirectors)
	{
		UE_LOG(LogMCP, Warning, TEXT("rename_assets: fixup_mode='prompt' requested, but allow_ui_prompts=false; forcing fixup_mode='delete' for non-interactive execution"));
		FixupMode = ERedirectFixupMode::DeleteFixedUpRedirectors;
	}

	const bool bEffectiveCheckoutDialogPrompt = bAllowUIPrompts && bRequestedCheckoutDialogPrompt;

	FAssetToolsModule& AssetToolsModule = FModuleManager::LoadModuleChecked<FAssetToolsModule>(TEXT("AssetTools"));
	IAssetTools& AssetTools = AssetToolsModule.Get();

	TArray<FAssetRenameData> RenameDataList;
	RenameDataList.Reserve(RequestItems.Num());

	TArray<FString> OldObjectPaths;
	OldObjectPaths.Reserve(RequestItems.Num());

	for (const FRenameRequestItem& RequestItem : RequestItems)
	{
		if (!FPackageName::IsValidLongPackageName(RequestItem.NewPackagePath))
		{
			return CreateErrorResponse(
				FString::Printf(TEXT("Invalid new_package_path: %s"), *RequestItem.NewPackagePath),
				TEXT("invalid_package_path")
			);
		}

		UObject* Asset = LoadObject<UObject>(nullptr, *RequestItem.OldAssetPath);
		if (!Asset)
		{
			return CreateErrorResponse(
				FString::Printf(TEXT("Asset not found: %s"), *RequestItem.OldAssetPath),
				TEXT("asset_not_found")
			);
		}

		OldObjectPaths.Add(Asset->GetPathName());
		RenameDataList.Emplace(Asset, RequestItem.NewPackagePath, RequestItem.NewName);
	}

	const bool bRenameSucceeded = AssetTools.RenameAssets(RenameDataList);
	if (!bRenameSucceeded)
	{
		return CreateErrorResponse(TEXT("RenameAssets failed. Check destination path/name conflicts and source-control state."), TEXT("rename_failed"));
	}

	int32 FoundRedirectorCount = 0;
	int32 FixedRedirectorCount = 0;
	int32 SilentlyDeletedRedirectorCount = 0;
	int32 KeptRedirectorCount = 0;
	TArray<UObjectRedirector*> RedirectorsToFix;
	TArray<TSharedPtr<FJsonValue>> KeptRedirectorsArray;

	if (bAutoFixupRedirectors)
	{
		for (const FString& OldObjectPath : OldObjectPaths)
		{
			UObject* LoadedObject = LoadObject<UObject>(nullptr, *OldObjectPath);
			UObjectRedirector* Redirector = Cast<UObjectRedirector>(LoadedObject);
			if (Redirector)
			{
				RedirectorsToFix.Add(Redirector);
				FoundRedirectorCount++;
			}
		}

		if (RedirectorsToFix.Num() > 0)
		{
			if (bAllowUIPrompts)
			{
				AssetTools.FixupReferencers(RedirectorsToFix, bEffectiveCheckoutDialogPrompt, FixupMode);
				FixedRedirectorCount = RedirectorsToFix.Num();
			}
			else
			{
				FAssetRegistryModule& AssetRegistryModule = FModuleManager::LoadModuleChecked<FAssetRegistryModule>(TEXT("AssetRegistry"));
				IAssetRegistry& AssetRegistry = AssetRegistryModule.Get();

				for (const FString& OldObjectPath : OldObjectPaths)
				{
					const FString OldPackagePath = FPackageName::ObjectPathToPackageName(OldObjectPath);
					if (OldPackagePath.IsEmpty())
					{
						continue;
					}

					TArray<FName> Referencers;
					AssetRegistry.GetReferencers(FName(*OldPackagePath), Referencers);

					int32 ExternalReferencerCount = 0;
					for (const FName& Referencer : Referencers)
					{
						if (Referencer.ToString() != OldPackagePath)
						{
							ExternalReferencerCount++;
						}
					}

					if (ExternalReferencerCount == 0)
					{
						if (UEditorAssetLibrary::DoesAssetExist(OldPackagePath) && UEditorAssetLibrary::DeleteAsset(OldPackagePath))
						{
							SilentlyDeletedRedirectorCount++;
						}
						else
						{
							KeptRedirectorCount++;
							TSharedPtr<FJsonObject> KeptObj = MakeShared<FJsonObject>();
							KeptObj->SetStringField(TEXT("redirector_package"), OldPackagePath);
							KeptObj->SetStringField(TEXT("reason"), TEXT("delete_failed"));
							KeptRedirectorsArray.Add(MakeShared<FJsonValueObject>(KeptObj));
						}
					}
					else
					{
						KeptRedirectorCount++;
						TSharedPtr<FJsonObject> KeptObj = MakeShared<FJsonObject>();
						KeptObj->SetStringField(TEXT("redirector_package"), OldPackagePath);
						KeptObj->SetStringField(TEXT("reason"), TEXT("still_referenced"));
						KeptObj->SetNumberField(TEXT("referencer_count"), ExternalReferencerCount);
						KeptRedirectorsArray.Add(MakeShared<FJsonValueObject>(KeptObj));
					}
				}
			}
		}
	}

	TArray<TSharedPtr<FJsonValue>> RenamedItemsArray;
	for (const FAssetRenameData& RenameData : RenameDataList)
	{
		TSharedPtr<FJsonObject> ItemObject = MakeShared<FJsonObject>();
		ItemObject->SetStringField(TEXT("old_asset_path"), RenameData.OldObjectPath.ToString());
		ItemObject->SetStringField(TEXT("new_asset_path"), RenameData.NewObjectPath.ToString());
		ItemObject->SetStringField(TEXT("new_package_path"), RenameData.NewPackagePath);
		ItemObject->SetStringField(TEXT("new_name"), RenameData.NewName);
		RenamedItemsArray.Add(MakeShared<FJsonValueObject>(ItemObject));
	}

	TSharedPtr<FJsonObject> Result = MakeShared<FJsonObject>();
	Result->SetNumberField(TEXT("renamed_count"), RenameDataList.Num());
	Result->SetBoolField(TEXT("auto_fixup_redirectors"), bAutoFixupRedirectors);
	Result->SetBoolField(TEXT("allow_ui_prompts"), bAllowUIPrompts);
	Result->SetBoolField(TEXT("checkout_dialog_prompt_effective"), bEffectiveCheckoutDialogPrompt);
	Result->SetStringField(
		TEXT("fixup_mode_effective"),
		FixupMode == ERedirectFixupMode::LeaveFixedUpRedirectors
			? TEXT("leave")
			: (FixupMode == ERedirectFixupMode::PromptForDeletingRedirectors ? TEXT("prompt") : TEXT("delete"))
	);
	Result->SetNumberField(TEXT("redirectors_found"), FoundRedirectorCount);
	Result->SetNumberField(TEXT("redirectors_fixup_attempted"), FixedRedirectorCount);
	Result->SetNumberField(TEXT("redirectors_deleted_silently"), SilentlyDeletedRedirectorCount);
	Result->SetNumberField(TEXT("redirectors_kept"), KeptRedirectorCount);
	Result->SetArrayField(TEXT("kept_redirectors"), KeptRedirectorsArray);
	Result->SetArrayField(TEXT("renamed_items"), RenamedItemsArray);

	return CreateSuccessResponse(Result);
}


// ========================================================================
// FPlanAssetRenamesAction
// ========================================================================

bool FPlanAssetRenamesAction::Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError)
{
	return UEEditorMCPAssetMaintenance::ValidateRenameParams(Params, OutError);
}

TSharedPtr<FJsonObject> FPlanAssetRenamesAction::ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context)
{
	using namespace UEEditorMCPAssetMaintenance;

	const TArray<FRenameRequestItem> RequestItems = ParseRenameItems(Params);
	const bool bIncludeReferencers = GetOptionalBool(Params, TEXT("include_referencers"), true);
	const bool bAllowProtectedPaths = GetOptionalBool(Params, TEXT("allow_protected_paths"), false);
	const int32 MaxReferencersPerItem = FMath::Clamp(static_cast<int32>(GetOptionalNumber(Params, TEXT("max_referencers_per_item"), 20.0)), 0, 500);

	FAssetRegistryModule& AssetRegistryModule = FModuleManager::LoadModuleChecked<FAssetRegistryModule>(TEXT("AssetRegistry"));
	IAssetRegistry& AssetRegistry = AssetRegistryModule.Get();

	TMap<FString, int32> DestinationCounts;
	TSet<FName> SourcePackages;
	for (const FRenameRequestItem& Item : RequestItems)
	{
		const FString DestinationObjectPath = ObjectPathFromPackageAndName(Item.NewPackagePath, Item.NewName);
		DestinationCounts.FindOrAdd(DestinationObjectPath)++;
		const FString OldPackagePath = PackagePathFromAnyAssetPath(Item.OldAssetPath);
		if (!OldPackagePath.IsEmpty())
		{
			SourcePackages.Add(FName(*OldPackagePath));
		}
	}

	TArray<TSharedPtr<FJsonValue>> ItemsArray;
	int32 ValidCount = 0;
	int32 WarningCount = 0;
	int32 BlockerCount = 0;

	for (int32 Index = 0; Index < RequestItems.Num(); ++Index)
	{
		const FRenameRequestItem& Item = RequestItems[Index];
		const FString OldPackagePath = PackagePathFromAnyAssetPath(Item.OldAssetPath);
		const FString OldObjectPath = ObjectPathFromAnyAssetPath(Item.OldAssetPath);
		const FString NewParentPath = CleanLongPath(Item.NewPackagePath);
		const FString NewPackagePath = PackagePathFromPackageAndName(NewParentPath, Item.NewName);
		const FString NewObjectPath = ObjectPathFromPackageAndName(NewParentPath, Item.NewName);

		TArray<TSharedPtr<FJsonValue>> Warnings;
		TArray<TSharedPtr<FJsonValue>> Blockers;

		FAssetData SourceData = AssetRegistry.GetAssetByObjectPath(FSoftObjectPath(OldObjectPath));
		const bool bSourceExists = SourceData.IsValid();
		if (!bSourceExists)
		{
			AddReason(Blockers, TEXT("source_asset_not_found"));
		}

		FString ProtectedReason;
		if (GetProtectedAssetReason(OldPackagePath, bAllowProtectedPaths, ProtectedReason))
		{
			AddReason(Blockers, FString::Printf(TEXT("source_%s"), *ProtectedReason));
		}
		if (GetProtectedAssetReason(NewPackagePath, bAllowProtectedPaths, ProtectedReason))
		{
			AddReason(Blockers, FString::Printf(TEXT("destination_%s"), *ProtectedReason));
		}

		FText NameReason;
		if (!FName(*Item.NewName).IsValidObjectName(NameReason))
		{
			AddReason(Blockers, FString::Printf(TEXT("invalid_new_name: %s"), *NameReason.ToString()));
		}

		FText PackageReason;
		if (!FPackageName::IsValidLongPackageName(NewPackagePath, false, &PackageReason))
		{
			AddReason(Blockers, FString::Printf(TEXT("invalid_destination_package: %s"), *PackageReason.ToString()));
		}

		FAssetData DestinationData = AssetRegistry.GetAssetByObjectPath(FSoftObjectPath(NewObjectPath));
		const bool bDestinationExists = DestinationData.IsValid();
		const bool bSameObjectPath = OldObjectPath == NewObjectPath;
		if (bDestinationExists && !bSameObjectPath)
		{
			AddReason(Blockers, TEXT("destination_asset_exists"));
		}
		if (DestinationCounts.FindRef(NewObjectPath) > 1)
		{
			AddReason(Blockers, TEXT("duplicate_destination_in_plan"));
		}
		if (bSameObjectPath)
		{
			AddReason(Warnings, TEXT("source_and_destination_are_identical"));
		}

		int32 TotalReferencerCount = 0;
		TArray<FName> ExternalReferencers;
		if (bIncludeReferencers && !OldPackagePath.IsEmpty())
		{
			ExternalReferencers = GetExternalReferencers(AssetRegistry, OldPackagePath, SourcePackages, TotalReferencerCount);
			if (ExternalReferencers.Num() > 0)
			{
				AddReason(Warnings, TEXT("source_has_external_referencers"));
			}
		}

		const bool bHasBlockers = Blockers.Num() > 0;
		const bool bHasWarnings = Warnings.Num() > 0;
		if (bHasBlockers)
		{
			BlockerCount++;
		}
		else
		{
			ValidCount++;
		}
		if (bHasWarnings)
		{
			WarningCount++;
		}

		TSharedPtr<FJsonObject> ItemObj = MakeShared<FJsonObject>();
		ItemObj->SetNumberField(TEXT("index"), Index);
		ItemObj->SetStringField(TEXT("old_asset_path"), Item.OldAssetPath);
		ItemObj->SetStringField(TEXT("old_object_path"), OldObjectPath);
		ItemObj->SetStringField(TEXT("old_package_path"), OldPackagePath);
		ItemObj->SetStringField(TEXT("new_package_path"), NewParentPath);
		ItemObj->SetStringField(TEXT("new_name"), Item.NewName);
		ItemObj->SetStringField(TEXT("new_object_path"), NewObjectPath);
		ItemObj->SetStringField(TEXT("new_asset_package"), NewPackagePath);
		ItemObj->SetBoolField(TEXT("source_exists"), bSourceExists);
		ItemObj->SetBoolField(TEXT("destination_exists"), bDestinationExists);
		ItemObj->SetBoolField(TEXT("same_object_path"), bSameObjectPath);
		ItemObj->SetBoolField(TEXT("can_rename"), !bHasBlockers);
		ItemObj->SetStringField(TEXT("asset_class"), bSourceExists ? SourceData.AssetClassPath.GetAssetName().ToString() : TEXT(""));
		ItemObj->SetNumberField(TEXT("referencer_count"), ExternalReferencers.Num());
		ItemObj->SetNumberField(TEXT("total_referencer_count"), TotalReferencerCount);
		ItemObj->SetArrayField(TEXT("referencers"), NamesToJsonArray(ExternalReferencers, MaxReferencersPerItem));
		ItemObj->SetNumberField(TEXT("referencers_truncated"), FMath::Max(0, ExternalReferencers.Num() - MaxReferencersPerItem));
		ItemObj->SetArrayField(TEXT("warnings"), Warnings);
		ItemObj->SetArrayField(TEXT("blockers"), Blockers);
		ItemsArray.Add(MakeShared<FJsonValueObject>(ItemObj));
	}

	TSharedPtr<FJsonObject> Result = MakeShared<FJsonObject>();
	Result->SetBoolField(TEXT("dry_run"), true);
	Result->SetNumberField(TEXT("requested_count"), RequestItems.Num());
	Result->SetNumberField(TEXT("valid_count"), ValidCount);
	Result->SetNumberField(TEXT("warning_count"), WarningCount);
	Result->SetNumberField(TEXT("blocker_count"), BlockerCount);
	Result->SetBoolField(TEXT("has_blockers"), BlockerCount > 0);
	Result->SetArrayField(TEXT("items"), ItemsArray);
	return CreateSuccessResponse(Result);
}


// ========================================================================
// FDeleteAssetsAction
// ========================================================================

bool FDeleteAssetsAction::Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError)
{
	TArray<FString> AssetPaths;
	return UEEditorMCPAssetMaintenance::TryReadStringArray(Params, TEXT("asset_path"), TEXT("asset_paths"), AssetPaths, OutError);
}

TSharedPtr<FJsonObject> FDeleteAssetsAction::ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context)
{
	using namespace UEEditorMCPAssetMaintenance;

	TArray<FString> AssetPaths;
	FString ParseError;
	if (!TryReadStringArray(Params, TEXT("asset_path"), TEXT("asset_paths"), AssetPaths, ParseError))
	{
		return CreateErrorResponse(ParseError, TEXT("invalid_params"));
	}

	const bool bDryRun = GetOptionalBool(Params, TEXT("dry_run"), true);
	const bool bRequireUnreferenced = GetOptionalBool(Params, TEXT("require_unreferenced"), true);
	const bool bForce = GetOptionalBool(Params, TEXT("force"), false);
	const bool bAllowMapAssets = GetOptionalBool(Params, TEXT("allow_map_assets"), false);
	const bool bAllowProtectedPaths = GetOptionalBool(Params, TEXT("allow_protected_paths"), false);
	const double MaxReferencersAlias = GetOptionalNumber(Params, TEXT("max_referencers_per_item"), 20.0);
	const int32 MaxReferencersPerAsset = FMath::Clamp(static_cast<int32>(GetOptionalNumber(Params, TEXT("max_referencers_per_asset"), MaxReferencersAlias)), 0, 500);

	FAssetRegistryModule& AssetRegistryModule = FModuleManager::LoadModuleChecked<FAssetRegistryModule>(TEXT("AssetRegistry"));
	IAssetRegistry& AssetRegistry = AssetRegistryModule.Get();

	TSet<FName> DeletePackages;
	for (const FString& AssetPath : AssetPaths)
	{
		const FString PackagePath = PackagePathFromAnyAssetPath(AssetPath);
		if (!PackagePath.IsEmpty())
		{
			DeletePackages.Add(FName(*PackagePath));
		}
	}

	TArray<TSharedPtr<FJsonValue>> ItemsArray;
	TArray<FAssetData> AssetsToDelete;
	int32 BlockerCount = 0;
	int32 WarningCount = 0;

	for (int32 Index = 0; Index < AssetPaths.Num(); ++Index)
	{
		const FString PackagePath = PackagePathFromAnyAssetPath(AssetPaths[Index]);
		const FString ObjectPath = ObjectPathFromAnyAssetPath(AssetPaths[Index]);
		FAssetData AssetData = AssetRegistry.GetAssetByObjectPath(FSoftObjectPath(ObjectPath));

		TArray<TSharedPtr<FJsonValue>> Warnings;
		TArray<TSharedPtr<FJsonValue>> Blockers;

		if (!AssetData.IsValid())
		{
			AddReason(Blockers, TEXT("asset_not_found"));
		}

		FString ProtectedReason;
		if (GetProtectedAssetReason(PackagePath, bAllowProtectedPaths, ProtectedReason))
		{
			AddReason(Blockers, ProtectedReason);
		}

		if (IsMapAsset(AssetData) && !bAllowMapAssets)
		{
			AddReason(Blockers, TEXT("map_asset_requires_allow_map_assets"));
		}

		int32 TotalReferencerCount = 0;
		TArray<FName> ExternalReferencers;
		if (!PackagePath.IsEmpty())
		{
			ExternalReferencers = GetExternalReferencers(AssetRegistry, PackagePath, DeletePackages, TotalReferencerCount);
			if (ExternalReferencers.Num() > 0)
			{
				AddReason(Warnings, TEXT("asset_has_external_referencers"));
				if (bRequireUnreferenced && !bForce)
				{
					AddReason(Blockers, TEXT("external_referencers_present"));
				}
			}
		}

		if (Blockers.Num() == 0 && AssetData.IsValid())
		{
			AssetsToDelete.Add(AssetData);
		}
		else
		{
			BlockerCount++;
		}
		if (Warnings.Num() > 0)
		{
			WarningCount++;
		}

		TSharedPtr<FJsonObject> ItemObj = MakeShared<FJsonObject>();
		ItemObj->SetNumberField(TEXT("index"), Index);
		ItemObj->SetStringField(TEXT("asset_path"), AssetPaths[Index]);
		ItemObj->SetStringField(TEXT("object_path"), ObjectPath);
		ItemObj->SetStringField(TEXT("package_path"), PackagePath);
		ItemObj->SetBoolField(TEXT("exists"), AssetData.IsValid());
		ItemObj->SetStringField(TEXT("asset_class"), AssetData.IsValid() ? AssetData.AssetClassPath.GetAssetName().ToString() : TEXT(""));
		ItemObj->SetBoolField(TEXT("is_map_asset"), IsMapAsset(AssetData));
		ItemObj->SetBoolField(TEXT("can_delete"), Blockers.Num() == 0 && AssetData.IsValid());
		ItemObj->SetNumberField(TEXT("referencer_count"), ExternalReferencers.Num());
		ItemObj->SetNumberField(TEXT("total_referencer_count"), TotalReferencerCount);
		ItemObj->SetArrayField(TEXT("referencers"), NamesToJsonArray(ExternalReferencers, MaxReferencersPerAsset));
		ItemObj->SetNumberField(TEXT("referencers_truncated"), FMath::Max(0, ExternalReferencers.Num() - MaxReferencersPerAsset));
		ItemObj->SetArrayField(TEXT("warnings"), Warnings);
		ItemObj->SetArrayField(TEXT("blockers"), Blockers);
		ItemsArray.Add(MakeShared<FJsonValueObject>(ItemObj));
	}

	int32 DeletedCount = 0;
	bool bExecuted = false;
	if (!bDryRun && BlockerCount == 0 && AssetsToDelete.Num() > 0)
	{
		bExecuted = true;
		DeletedCount = ObjectTools::DeleteAssets(AssetsToDelete, false);
	}

	TSharedPtr<FJsonObject> Result = MakeShared<FJsonObject>();
	Result->SetBoolField(TEXT("dry_run"), bDryRun);
	Result->SetBoolField(TEXT("executed"), bExecuted);
	Result->SetBoolField(TEXT("require_unreferenced"), bRequireUnreferenced);
	Result->SetBoolField(TEXT("force"), bForce);
	Result->SetNumberField(TEXT("requested_count"), AssetPaths.Num());
	Result->SetNumberField(TEXT("deletable_count"), AssetsToDelete.Num());
	Result->SetNumberField(TEXT("deleted_count"), DeletedCount);
	Result->SetNumberField(TEXT("warning_count"), WarningCount);
	Result->SetNumberField(TEXT("blocker_count"), BlockerCount);
	Result->SetBoolField(TEXT("has_blockers"), BlockerCount > 0);
	Result->SetArrayField(TEXT("items"), ItemsArray);
	return CreateSuccessResponse(Result);
}


// ========================================================================
// FDeleteEmptyDirectoriesAction
// ========================================================================

bool FDeleteEmptyDirectoriesAction::Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError)
{
	TArray<FString> Paths;
	if (!UEEditorMCPAssetMaintenance::TryReadStringArray(Params, TEXT("path"), TEXT("paths"), Paths, OutError))
	{
		return false;
	}

	const int32 MaxDirectories = static_cast<int32>(GetOptionalNumber(Params, TEXT("max_directories"), 1000.0));
	if (MaxDirectories <= 0)
	{
		OutError = TEXT("'max_directories' must be greater than 0");
		return false;
	}
	return true;
}

TSharedPtr<FJsonObject> FDeleteEmptyDirectoriesAction::ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context)
{
	using namespace UEEditorMCPAssetMaintenance;

	TArray<FString> RootPaths;
	FString ParseError;
	if (!TryReadStringArray(Params, TEXT("path"), TEXT("paths"), RootPaths, ParseError))
	{
		return CreateErrorResponse(ParseError, TEXT("invalid_params"));
	}

	const bool bDryRun = GetOptionalBool(Params, TEXT("dry_run"), true);
	const bool bRecursive = GetOptionalBool(Params, TEXT("recursive"), true);
	const bool bAllowProtectedPaths = GetOptionalBool(Params, TEXT("allow_protected_paths"), false);
	const int32 MaxDirectories = FMath::Max(1, static_cast<int32>(GetOptionalNumber(Params, TEXT("max_directories"), 1000.0)));

	FAssetRegistryModule& AssetRegistryModule = FModuleManager::LoadModuleChecked<FAssetRegistryModule>(TEXT("AssetRegistry"));
	IAssetRegistry& AssetRegistry = AssetRegistryModule.Get();
	UEditorAssetSubsystem* AssetSubsystem = GEditor ? GEditor->GetEditorSubsystem<UEditorAssetSubsystem>() : nullptr;
	if (!AssetSubsystem)
	{
		return CreateErrorResponse(TEXT("EditorAssetSubsystem unavailable"), TEXT("subsystem_error"));
	}

	TSet<FString> CandidateSet;
	for (const FString& RawRootPath : RootPaths)
	{
		const FString RootPath = CleanLongPath(RawRootPath);
		CandidateSet.Add(RootPath);
		if (bRecursive)
		{
			TArray<FString> SubPaths;
			AssetRegistry.GetSubPaths(RootPath, SubPaths, true);
			for (const FString& SubPath : SubPaths)
			{
				CandidateSet.Add(CleanLongPath(SubPath));
			}

			FString DiskRoot;
			FString DiskError;
			if (TryGamePathToDiskDirectory(RootPath, DiskRoot, DiskError) && IFileManager::Get().DirectoryExists(*DiskRoot))
			{
				IFileManager::Get().IterateDirectoryRecursively(*DiskRoot, [&CandidateSet](const TCHAR* FilenameOrDirectory, bool bIsDirectory) -> bool
				{
					if (bIsDirectory)
					{
						const FString PackagePath = DiskDirectoryToGamePath(FilenameOrDirectory);
						if (!PackagePath.IsEmpty())
						{
							CandidateSet.Add(CleanLongPath(PackagePath));
						}
					}
					return true;
				});
			}
		}
	}

	TArray<FString> Candidates = CandidateSet.Array();
	Candidates.Sort([](const FString& A, const FString& B)
	{
		if (A.Len() == B.Len())
		{
			return A < B;
		}
		return A.Len() > B.Len();
	});

	if (Candidates.Num() > MaxDirectories)
	{
		TSharedPtr<FJsonObject> Result = MakeShared<FJsonObject>();
		Result->SetNumberField(TEXT("candidate_count"), Candidates.Num());
		Result->SetNumberField(TEXT("max_directories"), MaxDirectories);
		Result->SetStringField(TEXT("error"), TEXT("Candidate directory count exceeds max_directories; narrow the path or raise the limit."));
		return CreateSuccessResponse(Result);
	}

	TArray<TSharedPtr<FJsonValue>> DirectoryArray;
	int32 DeletableCount = 0;
	int32 DeletedCount = 0;
	int32 BlockerCount = 0;
	int32 FailureCount = 0;

	for (int32 Index = 0; Index < Candidates.Num(); ++Index)
	{
		const FString DirectoryPath = Candidates[Index];
		TArray<TSharedPtr<FJsonValue>> Blockers;

		FString ProtectedReason;
		if (GetProtectedDirectoryReason(DirectoryPath, bAllowProtectedPaths, ProtectedReason))
		{
			AddReason(Blockers, ProtectedReason);
		}

		FString DiskDirectory;
		FString DiskError;
		const bool bResolvedDiskPath = TryGamePathToDiskDirectory(DirectoryPath, DiskDirectory, DiskError);
		if (!bResolvedDiskPath)
		{
			AddReason(Blockers, DiskError);
		}

		const bool bDiskExists = bResolvedDiskPath && IFileManager::Get().DirectoryExists(*DiskDirectory);
		const bool bRegistryExists = AssetSubsystem->DoesDirectoryExist(DirectoryPath);

		TArray<FAssetData> RecursiveAssets;
		AssetRegistry.GetAssetsByPath(FName(*DirectoryPath), RecursiveAssets, true);
		const bool bHasAssets = RecursiveAssets.Num() > 0;
		const bool bHasFiles = bResolvedDiskPath && DirectoryHasFilesRecursive(DiskDirectory);
		if (!bDiskExists && !bRegistryExists)
		{
			AddReason(Blockers, TEXT("directory_not_found"));
		}
		if (bHasAssets)
		{
			AddReason(Blockers, TEXT("directory_contains_assets"));
		}
		if (bHasFiles)
		{
			AddReason(Blockers, TEXT("directory_contains_files"));
		}

		const bool bCanDelete = Blockers.Num() == 0;
		bool bDeleted = false;
		if (bCanDelete)
		{
			DeletableCount++;
			if (!bDryRun)
			{
				bDeleted = AssetSubsystem->DeleteDirectory(DirectoryPath);
				if (!bDeleted && bDiskExists)
				{
					bDeleted = IFileManager::Get().DeleteDirectory(*DiskDirectory, false, false);
					if (bDeleted)
					{
						AssetRegistry.RemovePath(DirectoryPath);
					}
				}
				if (bDeleted)
				{
					DeletedCount++;
				}
				else
				{
					FailureCount++;
					AddReason(Blockers, TEXT("delete_failed"));
				}
			}
		}
		else
		{
			BlockerCount++;
		}

		TSharedPtr<FJsonObject> DirObj = MakeShared<FJsonObject>();
		DirObj->SetNumberField(TEXT("index"), Index);
		DirObj->SetStringField(TEXT("path"), DirectoryPath);
		DirObj->SetStringField(TEXT("disk_path"), bResolvedDiskPath ? DiskDirectory : TEXT(""));
		DirObj->SetBoolField(TEXT("disk_exists"), bDiskExists);
		DirObj->SetBoolField(TEXT("registry_exists"), bRegistryExists);
		DirObj->SetNumberField(TEXT("recursive_asset_count"), RecursiveAssets.Num());
		DirObj->SetBoolField(TEXT("has_files_on_disk"), bHasFiles);
		DirObj->SetBoolField(TEXT("can_delete"), bCanDelete);
		DirObj->SetBoolField(TEXT("deleted"), bDeleted);
		DirObj->SetArrayField(TEXT("blockers"), Blockers);
		DirectoryArray.Add(MakeShared<FJsonValueObject>(DirObj));
	}

	TSharedPtr<FJsonObject> Result = MakeShared<FJsonObject>();
	Result->SetBoolField(TEXT("dry_run"), bDryRun);
	Result->SetBoolField(TEXT("recursive"), bRecursive);
	Result->SetBoolField(TEXT("executed"), !bDryRun);
	Result->SetNumberField(TEXT("candidate_count"), Candidates.Num());
	Result->SetNumberField(TEXT("deletable_count"), DeletableCount);
	Result->SetNumberField(TEXT("deleted_count"), DeletedCount);
	Result->SetNumberField(TEXT("blocker_count"), BlockerCount);
	Result->SetNumberField(TEXT("failure_count"), FailureCount);
	Result->SetBoolField(TEXT("has_blockers"), BlockerCount > 0);
	Result->SetArrayField(TEXT("directories"), DirectoryArray);
	return CreateSuccessResponse(Result);
}


// ========================================================================
// FProcessAssetMaintenanceManifestAction
// ========================================================================

bool FProcessAssetMaintenanceManifestAction::Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError)
{
	const TSharedPtr<FJsonObject>* ManifestObject = nullptr;
	if (!Params->TryGetObjectField(TEXT("manifest"), ManifestObject) || !ManifestObject || !ManifestObject->IsValid())
	{
		OutError = TEXT("Missing required object parameter 'manifest'");
		return false;
	}

	const FString Mode = GetOptionalString(Params, TEXT("mode"), TEXT("plan")).ToLower();
	if (Mode != TEXT("plan") && Mode != TEXT("apply") && Mode != TEXT("dry_run"))
	{
		OutError = TEXT("'mode' must be 'plan' or 'apply'");
		return false;
	}

	return true;
}

TSharedPtr<FJsonObject> FProcessAssetMaintenanceManifestAction::ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context)
{
	using namespace UEEditorMCPAssetMaintenance;

	const TSharedPtr<FJsonObject>* ManifestObjectPtr = nullptr;
	Params->TryGetObjectField(TEXT("manifest"), ManifestObjectPtr);

	FAssetMaintenanceManifestPlan ManifestPlan;
	FString ParseError;
	if (!TryParseAssetMaintenanceManifest(ManifestObjectPtr ? *ManifestObjectPtr : nullptr, ManifestPlan, ParseError))
	{
		return CreateErrorResponse(ParseError, TEXT("invalid_manifest"));
	}

	const bool bIncludeReferencers = GetOptionalBool(Params, TEXT("include_referencers"), true);
	const bool bAllowProtectedPaths = GetOptionalBool(Params, TEXT("allow_protected_paths"), false);
	const bool bAllowCaseOnlyRenames = GetOptionalBool(Params, TEXT("allow_case_only_renames"), false);
	const int32 MaxReferencersPerItem = FMath::Clamp(static_cast<int32>(GetOptionalNumber(Params, TEXT("max_referencers_per_item"), 20.0)), 0, 500);
	const double MinConfidence = GetOptionalNumber(Params, TEXT("min_confidence"), 0.0);
	FString Mode = GetOptionalString(Params, TEXT("mode"), TEXT("plan")).ToLower();
	if (Mode == TEXT("dry_run"))
	{
		Mode = TEXT("plan");
	}

	FString OverrideFixupMode;
	if (Params->TryGetStringField(TEXT("fixup_mode"), OverrideFixupMode))
	{
		ManifestPlan.FixupMode = NormalizeFixupMode(OverrideFixupMode);
	}
	bool bBoolOverride = false;
	if (Params->TryGetBoolField(TEXT("auto_fixup_redirectors"), bBoolOverride))
	{
		ManifestPlan.bAutoFixupRedirectors = bBoolOverride;
	}
	if (Params->TryGetBoolField(TEXT("allow_ui_prompts"), bBoolOverride))
	{
		ManifestPlan.bAllowUIPrompts = bBoolOverride;
	}
	if (Params->TryGetBoolField(TEXT("delete_empty_directories"), bBoolOverride) ||
		Params->TryGetBoolField(TEXT("apply_empty_directory_cleanup"), bBoolOverride))
	{
		ManifestPlan.bDeleteEmptyDirectories = bBoolOverride;
	}

	if (!ManifestPlan.Project.IsEmpty() && !ManifestPlan.Project.Equals(FApp::GetProjectName(), ESearchCase::IgnoreCase))
	{
		ManifestPlan.ManifestWarnings.Add(FString::Printf(
			TEXT("manifest_project_mismatch: manifest=%s current=%s"),
			*ManifestPlan.Project,
			FApp::GetProjectName()
		));
	}

	TMap<FString, int32> SourcePackageToIndex;
	for (int32 Index = 0; Index < ManifestPlan.RenameItems.Num(); ++Index)
	{
		const FString SourcePackagePath = PackagePathFromAnyAssetPath(ManifestPlan.RenameItems[Index].OldAssetPath);
		if (!SourcePackagePath.IsEmpty())
		{
			SourcePackageToIndex.Add(SourcePackagePath, Index);
		}
	}

	FAssetRegistryModule& AssetRegistryModule = FModuleManager::LoadModuleChecked<FAssetRegistryModule>(TEXT("AssetRegistry"));
	IAssetRegistry& AssetRegistry = AssetRegistryModule.Get();

	TArray<TArray<FString>> ExtraItemWarnings;
	TArray<TArray<FString>> ExtraItemBlockers;
	ExtraItemWarnings.SetNum(ManifestPlan.RenameItems.Num());
	ExtraItemBlockers.SetNum(ManifestPlan.RenameItems.Num());

	for (int32 Index = 0; Index < ManifestPlan.RenameItems.Num(); ++Index)
	{
		const FManifestRenameItem& Item = ManifestPlan.RenameItems[Index];
		ExtraItemWarnings[Index].Append(Item.ManifestWarnings);
		ExtraItemBlockers[Index].Append(Item.ManifestBlockers);

		const FString OldObjectPath = ObjectPathFromAnyAssetPath(Item.OldAssetPath);
		const FString NewObjectPath = ObjectPathFromPackageAndName(Item.NewPackagePath, Item.NewName);
		const FString OldPackagePath = PackagePathFromAnyAssetPath(Item.OldAssetPath);
		const FString NewAssetPackagePath = PackagePathFromPackageAndName(Item.NewPackagePath, Item.NewName);

		if (OldObjectPath.Equals(NewObjectPath, ESearchCase::IgnoreCase) && !OldObjectPath.Equals(NewObjectPath, ESearchCase::CaseSensitive))
		{
			if (bAllowCaseOnlyRenames)
			{
				ExtraItemWarnings[Index].Add(TEXT("case_only_rename_may_require_two_step_or_source_control_checkout"));
			}
			else
			{
				ExtraItemBlockers[Index].Add(TEXT("case_only_rename_requires_allow_case_only_renames_or_two_step_temp_name"));
			}
		}

		const int32* ExistingSourceIndex = SourcePackageToIndex.Find(NewAssetPackagePath);
		if (ExistingSourceIndex && *ExistingSourceIndex != Index && !OldPackagePath.Equals(NewAssetPackagePath, ESearchCase::CaseSensitive))
		{
			ExtraItemBlockers[Index].Add(TEXT("destination_is_source_in_same_manifest_requires_temp_name"));
		}

		if (!Item.ExpectedClass.IsEmpty())
		{
			FAssetData SourceData = AssetRegistry.GetAssetByObjectPath(FSoftObjectPath(OldObjectPath));
			if (SourceData.IsValid())
			{
				const FString ActualClass = SourceData.AssetClassPath.GetAssetName().ToString();
				if (!ClassMatchesExpected(ActualClass, Item.ExpectedClass))
				{
					ExtraItemBlockers[Index].Add(FString::Printf(
						TEXT("expected_class_mismatch: expected=%s actual=%s"),
						*Item.ExpectedClass,
						*ActualClass
					));
				}
			}
		}

		if (MinConfidence > 0.0 && Item.Confidence >= 0.0 && Item.Confidence < MinConfidence)
		{
			ExtraItemBlockers[Index].Add(FString::Printf(
				TEXT("confidence_below_minimum: %.3f < %.3f"),
				Item.Confidence,
				MinConfidence
			));
		}
	}

	TArray<TSharedPtr<FJsonValue>> PlanItemsArray;
	int32 ValidCount = 0;
	int32 WarningCount = 0;
	int32 BlockerCount = 0;

	if (ManifestPlan.RenameItems.Num() > 0)
	{
		TSharedPtr<FJsonObject> RenamePlanParams = MakeShared<FJsonObject>();
		RenamePlanParams->SetArrayField(TEXT("items"), BuildRenameItemsJson(ManifestPlan.RenameItems));
		RenamePlanParams->SetBoolField(TEXT("include_referencers"), bIncludeReferencers);
		RenamePlanParams->SetBoolField(TEXT("allow_protected_paths"), bAllowProtectedPaths);
		RenamePlanParams->SetNumberField(TEXT("max_referencers_per_item"), MaxReferencersPerItem);

		FPlanAssetRenamesAction RenamePlanner;
		TSharedPtr<FJsonObject> RenamePlanResult = RenamePlanner.Execute(RenamePlanParams, Context);
		bool bRenamePlanSuccess = false;
		if (!RenamePlanResult.IsValid() || !RenamePlanResult->TryGetBoolField(TEXT("success"), bRenamePlanSuccess) || !bRenamePlanSuccess)
		{
			const FString RenamePlanError = RenamePlanResult.IsValid() ? RenamePlanResult->GetStringField(TEXT("error")) : TEXT("null plan result");
			return CreateErrorResponse(FString::Printf(TEXT("Internal rename plan failed: %s"), *RenamePlanError), TEXT("internal_plan_failed"));
		}

		const TArray<TSharedPtr<FJsonValue>>* RenamePlanItems = nullptr;
		RenamePlanResult->TryGetArrayField(TEXT("items"), RenamePlanItems);
		if (!RenamePlanItems || RenamePlanItems->Num() != ManifestPlan.RenameItems.Num())
		{
			return CreateErrorResponse(TEXT("Internal rename plan item count mismatch"), TEXT("internal_plan_failed"));
		}

		for (int32 Index = 0; Index < RenamePlanItems->Num(); ++Index)
		{
			TSharedPtr<FJsonObject> ItemObject = UEEditorMCPBatch::CloneJsonObject((*RenamePlanItems)[Index]->AsObject());
			const FManifestRenameItem& ManifestItem = ManifestPlan.RenameItems[Index];

			TArray<TSharedPtr<FJsonValue>> Warnings;
			TArray<TSharedPtr<FJsonValue>> Blockers;
			const TArray<TSharedPtr<FJsonValue>>* ExistingWarnings = nullptr;
			const TArray<TSharedPtr<FJsonValue>>* ExistingBlockers = nullptr;
			if (ItemObject->TryGetArrayField(TEXT("warnings"), ExistingWarnings) && ExistingWarnings)
			{
				Warnings = *ExistingWarnings;
			}
			if (ItemObject->TryGetArrayField(TEXT("blockers"), ExistingBlockers) && ExistingBlockers)
			{
				Blockers = *ExistingBlockers;
			}

			AppendStringReasons(Warnings, ExtraItemWarnings[Index]);
			AppendStringReasons(Blockers, ExtraItemBlockers[Index]);

			const bool bCanRename = Blockers.Num() == 0;
			if (bCanRename)
			{
				ValidCount++;
			}
			else
			{
				BlockerCount++;
			}
			if (Warnings.Num() > 0)
			{
				WarningCount++;
			}

			ItemObject->SetStringField(TEXT("manifest_id"), ManifestItem.Id);
			ItemObject->SetStringField(TEXT("op"), TEXT("rename_or_move_asset"));
			ItemObject->SetStringField(TEXT("expected_class"), ManifestItem.ExpectedClass);
			ItemObject->SetStringField(TEXT("rule_id"), ManifestItem.RuleId);
			ItemObject->SetStringField(TEXT("reason"), ManifestItem.Reason);
			ItemObject->SetStringField(TEXT("target_object_path_declared"), ManifestItem.TargetObjectPath);
			if (ManifestItem.Confidence >= 0.0)
			{
				ItemObject->SetNumberField(TEXT("confidence"), ManifestItem.Confidence);
			}
			ItemObject->SetBoolField(TEXT("can_rename"), bCanRename);
			ItemObject->SetArrayField(TEXT("warnings"), Warnings);
			ItemObject->SetArrayField(TEXT("blockers"), Blockers);
			PlanItemsArray.Add(MakeShared<FJsonValueObject>(ItemObject));
		}
	}

	TArray<TSharedPtr<FJsonValue>> CleanupDirectoriesArray;
	int32 CleanupBlockerCount = 0;
	for (int32 Index = 0; Index < ManifestPlan.EmptyDirectories.Num(); ++Index)
	{
		const FString DirectoryPath = CleanLongPath(ManifestPlan.EmptyDirectories[Index]);
		TArray<TSharedPtr<FJsonValue>> Blockers;

		FString ProtectedReason;
		if (GetProtectedDirectoryReason(DirectoryPath, bAllowProtectedPaths, ProtectedReason))
		{
			AddReason(Blockers, ProtectedReason);
		}
		if (Blockers.Num() > 0)
		{
			CleanupBlockerCount++;
		}

		TSharedPtr<FJsonObject> DirectoryObject = MakeShared<FJsonObject>();
		DirectoryObject->SetNumberField(TEXT("index"), Index);
		DirectoryObject->SetStringField(TEXT("path"), DirectoryPath);
		DirectoryObject->SetStringField(TEXT("op"), TEXT("delete_empty_directory"));
		DirectoryObject->SetBoolField(TEXT("will_run_after_renames"), ManifestPlan.bDeleteEmptyDirectories);
		DirectoryObject->SetBoolField(TEXT("can_attempt_delete_after_apply"), Blockers.Num() == 0);
		DirectoryObject->SetArrayField(TEXT("blockers"), Blockers);
		CleanupDirectoriesArray.Add(MakeShared<FJsonValueObject>(DirectoryObject));
	}

	const FString PlanHash = BuildAssetMaintenancePlanHash(ManifestPlan);
	const int32 ManifestBlockerCount = ManifestPlan.ManifestBlockers.Num();
	const int32 TotalBlockerCount = BlockerCount + CleanupBlockerCount + ManifestBlockerCount;
	const int32 TotalWarningCount = WarningCount + ManifestPlan.ManifestWarnings.Num();
	const bool bHasBlockers = TotalBlockerCount > 0;

	TSharedPtr<FJsonObject> Result = MakeShared<FJsonObject>();
	Result->SetStringField(TEXT("mode"), Mode);
	Result->SetBoolField(TEXT("dry_run"), Mode != TEXT("apply"));
	Result->SetStringField(TEXT("schema"), ManifestPlan.Schema);
	Result->SetStringField(TEXT("project"), ManifestPlan.Project);
	Result->SetStringField(TEXT("plan_hash"), PlanHash);
	Result->SetStringField(TEXT("plan_hash_algorithm"), TEXT("md5-canonical-v1"));
	Result->SetNumberField(TEXT("requested_rename_count"), ManifestPlan.RenameItems.Num());
	Result->SetNumberField(TEXT("valid_rename_count"), ValidCount);
	Result->SetNumberField(TEXT("cleanup_directory_count"), ManifestPlan.EmptyDirectories.Num());
	Result->SetNumberField(TEXT("warning_count"), TotalWarningCount);
	Result->SetNumberField(TEXT("blocker_count"), TotalBlockerCount);
	Result->SetBoolField(TEXT("has_blockers"), bHasBlockers);
	Result->SetBoolField(TEXT("auto_fixup_redirectors"), ManifestPlan.bAutoFixupRedirectors);
	Result->SetBoolField(TEXT("delete_empty_directories"), ManifestPlan.bDeleteEmptyDirectories);
	Result->SetStringField(TEXT("fixup_mode"), ManifestPlan.FixupMode);
	Result->SetArrayField(TEXT("warnings"), StringsToJsonArray(ManifestPlan.ManifestWarnings));
	Result->SetArrayField(TEXT("manifest_blockers"), StringsToJsonArray(ManifestPlan.ManifestBlockers));
	Result->SetArrayField(TEXT("items"), PlanItemsArray);
	Result->SetArrayField(TEXT("cleanup_directories"), CleanupDirectoriesArray);
	Result->SetArrayField(TEXT("executable_rename_items"), BuildRenameItemsJson(ManifestPlan.RenameItems));

	if (Mode != TEXT("apply"))
	{
		return CreateSuccessResponse(Result);
	}

	FString ConfirmedPlanHash;
	if (!Params->TryGetStringField(TEXT("confirm_plan_hash"), ConfirmedPlanHash) || ConfirmedPlanHash.IsEmpty())
	{
		Result->SetStringField(TEXT("error"), TEXT("Apply mode requires confirm_plan_hash equal to plan_hash"));
		Result->SetStringField(TEXT("error_type"), TEXT("confirmation_required"));
		return CreateSuccessResponse(Result);
	}

	if (!ConfirmedPlanHash.Equals(PlanHash, ESearchCase::IgnoreCase))
	{
		Result->SetStringField(TEXT("error"), TEXT("confirm_plan_hash does not match current plan_hash"));
		Result->SetStringField(TEXT("error_type"), TEXT("plan_hash_mismatch"));
		return CreateSuccessResponse(Result);
	}

	if (bHasBlockers)
	{
		Result->SetStringField(TEXT("error"), TEXT("Manifest has blockers; apply refused"));
		Result->SetStringField(TEXT("error_type"), TEXT("plan_has_blockers"));
		return CreateSuccessResponse(Result);
	}

	bool bExecutedRename = false;
	TSharedPtr<FJsonObject> RenameApplyResult = MakeShared<FJsonObject>();
	RenameApplyResult->SetBoolField(TEXT("skipped"), true);
	if (ManifestPlan.RenameItems.Num() > 0)
	{
		TSharedPtr<FJsonObject> RenameParams = MakeShared<FJsonObject>();
		RenameParams->SetArrayField(TEXT("items"), BuildRenameItemsJson(ManifestPlan.RenameItems));
		RenameParams->SetBoolField(TEXT("auto_fixup_redirectors"), ManifestPlan.bAutoFixupRedirectors);
		RenameParams->SetBoolField(TEXT("allow_ui_prompts"), ManifestPlan.bAllowUIPrompts);
		RenameParams->SetStringField(TEXT("fixup_mode"), ManifestPlan.FixupMode);

		FRenameAssetsAction RenameAction;
		RenameApplyResult = RenameAction.Execute(RenameParams, Context);
		bool bRenameSuccess = false;
		if (!RenameApplyResult.IsValid() || !RenameApplyResult->TryGetBoolField(TEXT("success"), bRenameSuccess) || !bRenameSuccess)
		{
			Result->SetObjectField(TEXT("rename_result"), RenameApplyResult);
			Result->SetStringField(TEXT("error"), RenameApplyResult.IsValid() ? RenameApplyResult->GetStringField(TEXT("error")) : TEXT("rename returned null"));
			Result->SetStringField(TEXT("error_type"), TEXT("rename_apply_failed"));
			return CreateSuccessResponse(Result);
		}
		bExecutedRename = true;
	}

	bool bExecutedCleanup = false;
	TSharedPtr<FJsonObject> CleanupApplyResult = MakeShared<FJsonObject>();
	CleanupApplyResult->SetBoolField(TEXT("skipped"), true);
	if (ManifestPlan.bDeleteEmptyDirectories && ManifestPlan.EmptyDirectories.Num() > 0)
	{
		TSharedPtr<FJsonObject> CleanupParams = MakeShared<FJsonObject>();
		CleanupParams->SetArrayField(TEXT("paths"), StringsToJsonArray(ManifestPlan.EmptyDirectories));
		CleanupParams->SetBoolField(TEXT("dry_run"), false);
		CleanupParams->SetBoolField(TEXT("recursive"), true);
		CleanupParams->SetBoolField(TEXT("allow_protected_paths"), bAllowProtectedPaths);
		CleanupParams->SetNumberField(TEXT("max_directories"), GetOptionalNumber(Params, TEXT("max_directories"), 1000.0));

		FDeleteEmptyDirectoriesAction CleanupAction;
		CleanupApplyResult = CleanupAction.Execute(CleanupParams, Context);
		bool bCleanupSuccess = false;
		if (CleanupApplyResult.IsValid())
		{
			CleanupApplyResult->TryGetBoolField(TEXT("success"), bCleanupSuccess);
		}
		bExecutedCleanup = bCleanupSuccess;
	}

	Result->SetBoolField(TEXT("executed"), true);
	Result->SetBoolField(TEXT("executed_rename"), bExecutedRename);
	Result->SetBoolField(TEXT("executed_cleanup"), bExecutedCleanup);
	Result->SetObjectField(TEXT("rename_result"), RenameApplyResult);
	Result->SetObjectField(TEXT("cleanup_result"), CleanupApplyResult);
	return CreateSuccessResponse(Result);
}


// ========================================================================
// FGetSelectedAssetThumbnailAction
// ========================================================================

bool FGetSelectedAssetThumbnailAction::Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError)
{
	if (Params->HasField(TEXT("size")))
	{
		const double SizeValue = Params->GetNumberField(TEXT("size"));
		if (SizeValue < 1.0)
		{
			OutError = TEXT("Parameter 'size' must be greater than 0");
			return false;
		}
	}

	auto ValidateStringArrayField = [&Params, &OutError](const TCHAR* FieldName) -> bool
	{
		if (!Params->HasField(FieldName))
		{
			return true;
		}

		const TArray<TSharedPtr<FJsonValue>>* Values = nullptr;
		if (!Params->TryGetArrayField(FieldName, Values) || !Values)
		{
			OutError = FString::Printf(TEXT("'%s' must be an array of strings"), FieldName);
			return false;
		}

		for (const TSharedPtr<FJsonValue>& Value : *Values)
		{
			FString Parsed;
			if (!Value.IsValid() || !Value->TryGetString(Parsed) || Parsed.IsEmpty())
			{
				OutError = FString::Printf(TEXT("'%s' must contain only non-empty strings"), FieldName);
				return false;
			}
		}

		return true;
	};

	if (!ValidateStringArrayField(TEXT("asset_paths"))) return false;
	if (!ValidateStringArrayField(TEXT("asset_ids"))) return false;
	if (!ValidateStringArrayField(TEXT("ids"))) return false;

	return true;
}

TSharedPtr<FJsonObject> FGetSelectedAssetThumbnailAction::ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context)
{
	const int32 RequestedSize = Params->HasField(TEXT("size"))
		? static_cast<int32>(Params->GetNumberField(TEXT("size")))
		: 256;
	const int32 ThumbnailSize = FMath::Clamp(RequestedSize, 1, 256);

	TArray<FString> TargetAssetPaths;

	auto CollectStringArrayField = [&Params, &TargetAssetPaths](const TCHAR* FieldName)
	{
		const TArray<TSharedPtr<FJsonValue>>* Values = nullptr;
		if (!Params->TryGetArrayField(FieldName, Values) || !Values)
		{
			return;
		}

		for (const TSharedPtr<FJsonValue>& Value : *Values)
		{
			FString Parsed;
			if (Value.IsValid() && Value->TryGetString(Parsed) && !Parsed.IsEmpty())
			{
				TargetAssetPaths.Add(Parsed);
			}
		}
	};

	if (Params->HasField(TEXT("asset_path")))
	{
		const FString AssetPath = Params->GetStringField(TEXT("asset_path"));
		if (!AssetPath.IsEmpty())
		{
			TargetAssetPaths.Add(AssetPath);
		}
	}

	CollectStringArrayField(TEXT("asset_paths"));
	CollectStringArrayField(TEXT("asset_ids"));
	CollectStringArrayField(TEXT("ids"));

	TArray<FString> UniqueTargetAssetPaths;
	for (const FString& PathItem : TargetAssetPaths)
	{
		if (!PathItem.IsEmpty())
		{
			UniqueTargetAssetPaths.AddUnique(PathItem);
		}
	}
	TargetAssetPaths = MoveTemp(UniqueTargetAssetPaths);

	bool bFromSelection = false;
	int32 SelectedCount = 0;

	if (TargetAssetPaths.IsEmpty())
	{
		TArray<FAssetData> SelectedAssets;
		AssetSelectionUtils::GetSelectedAssets(SelectedAssets);
		SelectedCount = SelectedAssets.Num();

		if (SelectedAssets.IsEmpty())
		{
			return CreateErrorResponse(
				TEXT("No selected asset found in Content Browser. Select assets or provide asset_path/asset_paths/asset_ids/ids."),
				TEXT("no_selection")
			);
		}

		for (const FAssetData& SelectedAsset : SelectedAssets)
		{
			TargetAssetPaths.Add(SelectedAsset.GetObjectPathString());
		}
		bFromSelection = true;
	}

	TArray<TSharedPtr<FJsonValue>> ThumbnailItems;
	int32 SucceededCount = 0;
	int32 FailedCount = 0;

	for (const FString& AssetPath : TargetAssetPaths)
	{
		TSharedPtr<FJsonObject> Item = MakeShared<FJsonObject>();
		Item->SetStringField(TEXT("requested_asset"), AssetPath);
		Item->SetStringField(TEXT("mime_type"), TEXT("image/png"));
		Item->SetStringField(TEXT("image_format"), TEXT("png"));

		UObject* TargetObject = StaticLoadObject(UObject::StaticClass(), nullptr, *AssetPath);
		if (!TargetObject)
		{
			Item->SetBoolField(TEXT("success"), false);
			Item->SetStringField(TEXT("error"), TEXT("asset_not_found"));
			Item->SetStringField(TEXT("error_message"), FString::Printf(TEXT("Failed to load asset: %s"), *AssetPath));
			ThumbnailItems.Add(MakeShared<FJsonValueObject>(Item));
			++FailedCount;
			continue;
		}

		FObjectThumbnail RenderedThumbnail;
		ThumbnailTools::RenderThumbnail(
			TargetObject,
			static_cast<uint32>(ThumbnailSize),
			static_cast<uint32>(ThumbnailSize),
			ThumbnailTools::EThumbnailTextureFlushMode::NeverFlush,
			nullptr,
			&RenderedThumbnail
		);

		if (RenderedThumbnail.IsEmpty() || !RenderedThumbnail.HasValidImageData())
		{
			Item->SetBoolField(TEXT("success"), false);
			Item->SetStringField(TEXT("error"), TEXT("thumbnail_render_failed"));
			Item->SetStringField(TEXT("error_message"), FString::Printf(TEXT("Failed to render thumbnail: %s"), *TargetObject->GetPathName()));
			ThumbnailItems.Add(MakeShared<FJsonValueObject>(Item));
			++FailedCount;
			continue;
		}

		const int32 ImageWidth = RenderedThumbnail.GetImageWidth();
		const int32 ImageHeight = RenderedThumbnail.GetImageHeight();
		if (ImageWidth <= 0 || ImageHeight <= 0)
		{
			Item->SetBoolField(TEXT("success"), false);
			Item->SetStringField(TEXT("error"), TEXT("invalid_thumbnail"));
			Item->SetStringField(TEXT("error_message"), TEXT("Rendered thumbnail has invalid dimensions"));
			ThumbnailItems.Add(MakeShared<FJsonValueObject>(Item));
			++FailedCount;
			continue;
		}

		const TArray<uint8>& RawImageBytes = RenderedThumbnail.GetUncompressedImageData();
		const int64 PixelCount = static_cast<int64>(ImageWidth) * static_cast<int64>(ImageHeight);
		const int64 ExpectedBytes = PixelCount * static_cast<int64>(sizeof(FColor));
		if (RawImageBytes.Num() < ExpectedBytes)
		{
			Item->SetBoolField(TEXT("success"), false);
			Item->SetStringField(TEXT("error"), TEXT("invalid_thumbnail_buffer"));
			Item->SetStringField(TEXT("error_message"), TEXT("Rendered thumbnail buffer is smaller than expected"));
			ThumbnailItems.Add(MakeShared<FJsonValueObject>(Item));
			++FailedCount;
			continue;
		}

		TArray<FColor> ColorPixels;
		ColorPixels.SetNumUninitialized(static_cast<int32>(PixelCount));
		FMemory::Memcpy(ColorPixels.GetData(), RawImageBytes.GetData(), static_cast<SIZE_T>(ExpectedBytes));

		TArray<uint8> CompressedPngBytes;
		FImageUtils::ThumbnailCompressImageArray(ImageWidth, ImageHeight, ColorPixels, CompressedPngBytes);

		if (CompressedPngBytes.IsEmpty())
		{
			Item->SetBoolField(TEXT("success"), false);
			Item->SetStringField(TEXT("error"), TEXT("png_compress_failed"));
			Item->SetStringField(TEXT("error_message"), TEXT("Failed to compress thumbnail to PNG"));
			ThumbnailItems.Add(MakeShared<FJsonValueObject>(Item));
			++FailedCount;
			continue;
		}

		Item->SetBoolField(TEXT("success"), true);
		Item->SetStringField(TEXT("asset_name"), TargetObject->GetName());
		Item->SetStringField(TEXT("asset_path"), TargetObject->GetPathName());
		Item->SetStringField(TEXT("asset_class"), TargetObject->GetClass() ? TargetObject->GetClass()->GetName() : TEXT("Unknown"));
		Item->SetNumberField(TEXT("width"), ImageWidth);
		Item->SetNumberField(TEXT("height"), ImageHeight);
		Item->SetNumberField(TEXT("image_byte_size"), CompressedPngBytes.Num());
		Item->SetStringField(TEXT("image_base64"), FBase64::Encode(CompressedPngBytes));

		ThumbnailItems.Add(MakeShared<FJsonValueObject>(Item));
		++SucceededCount;
	}

	TSharedPtr<FJsonObject> Result = MakeShared<FJsonObject>();
	Result->SetBoolField(TEXT("from_selection"), bFromSelection);
	Result->SetNumberField(TEXT("selected_count"), SelectedCount);
	Result->SetNumberField(TEXT("requested_size"), RequestedSize);
	Result->SetNumberField(TEXT("applied_size"), ThumbnailSize);
	Result->SetNumberField(TEXT("requested_assets"), TargetAssetPaths.Num());
	Result->SetNumberField(TEXT("succeeded"), SucceededCount);
	Result->SetNumberField(TEXT("failed"), FailedCount);
	Result->SetArrayField(TEXT("thumbnails"), ThumbnailItems);

	if (ThumbnailItems.Num() > 0)
	{
		const TSharedPtr<FJsonObject>* FirstItem = nullptr;
		if (ThumbnailItems[0]->TryGetObject(FirstItem) && FirstItem && (*FirstItem)->GetBoolField(TEXT("success")))
		{
			// Backward compatibility fields for existing single-item consumers.
			Result->SetStringField(TEXT("asset_name"), (*FirstItem)->GetStringField(TEXT("asset_name")));
			Result->SetStringField(TEXT("asset_path"), (*FirstItem)->GetStringField(TEXT("asset_path")));
			Result->SetStringField(TEXT("asset_class"), (*FirstItem)->GetStringField(TEXT("asset_class")));
			Result->SetNumberField(TEXT("width"), (*FirstItem)->GetNumberField(TEXT("width")));
			Result->SetNumberField(TEXT("height"), (*FirstItem)->GetNumberField(TEXT("height")));
			Result->SetStringField(TEXT("image_format"), TEXT("png"));
			Result->SetStringField(TEXT("mime_type"), TEXT("image/png"));
			Result->SetNumberField(TEXT("image_byte_size"), (*FirstItem)->GetNumberField(TEXT("image_byte_size")));
			Result->SetStringField(TEXT("image_base64"), (*FirstItem)->GetStringField(TEXT("image_base64")));
		}
	}

	return CreateSuccessResponse(Result);
}


// ========================================================================
// FCaptureEditorScreenshotAction
// ========================================================================

namespace
{
	constexpr int32 MCPDefaultScreenshotMaxWidth = 512;
	constexpr int32 MCPDefaultScreenshotMaxHeight = 1920;


	constexpr int32 MCPMinScreenshotDimension = 64;
	constexpr int32 MCPMaxScreenshotDimension = 1920;

	bool IsValidScreenshotTarget(const FString& Target)
	{
		return Target.Equals(TEXT("active_window"), ESearchCase::IgnoreCase)
			|| Target.Equals(TEXT("active_viewport"), ESearchCase::IgnoreCase);
	}

	int32 ResolveScreenshotDimension(const TSharedPtr<FJsonObject>& Params, const TCHAR* FieldName, int32 DefaultValue)
	{
		if (!Params.IsValid() || !Params->HasField(FieldName))
		{
			return DefaultValue;
		}
		return FMath::Clamp(static_cast<int32>(Params->GetNumberField(FieldName)), MCPMinScreenshotDimension, MCPMaxScreenshotDimension);
	}

	void FitScreenshotToBounds(
		const TArray<FColor>& SourcePixels,
		int32 SourceWidth,
		int32 SourceHeight,
		int32 MaxWidth,
		int32 MaxHeight,
		TArray<FColor>& OutPixels,
		int32& OutWidth,
		int32& OutHeight)
	{
		OutWidth = SourceWidth;
		OutHeight = SourceHeight;

		const float WidthScale = SourceWidth > 0 ? static_cast<float>(MaxWidth) / static_cast<float>(SourceWidth) : 1.0f;
		const float HeightScale = SourceHeight > 0 ? static_cast<float>(MaxHeight) / static_cast<float>(SourceHeight) : 1.0f;
		const float Scale = FMath::Min(1.0f, FMath::Min(WidthScale, HeightScale));

		if (Scale < 1.0f)
		{
			OutWidth = FMath::Max(1, FMath::RoundToInt(static_cast<float>(SourceWidth) * Scale));
			OutHeight = FMath::Max(1, FMath::RoundToInt(static_cast<float>(SourceHeight) * Scale));
			FImageUtils::CropAndScaleImage(SourceWidth, SourceHeight, OutWidth, OutHeight, SourcePixels, OutPixels);
		}
		else
		{
			OutPixels = SourcePixels;
		}
	}

#if PLATFORM_WINDOWS
	using FMCPGetForegroundWindowFn = ::HWND(WINAPI*)();
	using FMCPIsWindowVisibleFn = ::BOOL(WINAPI*)(::HWND);
	using FMCPIsIconicFn = ::BOOL(WINAPI*)(::HWND);
	using FMCPGetWindowThreadProcessIdFn = ::DWORD(WINAPI*)(::HWND, ::LPDWORD);
	using FMCPGetWindowRectFn = ::BOOL(WINAPI*)(::HWND, ::LPRECT);
	using FMCPEnumWindowsFn = ::BOOL(WINAPI*)(::WNDENUMPROC, ::LPARAM);
	using FMCPGetWindowDCFn = ::HDC(WINAPI*)(::HWND);
	using FMCPReleaseDCFn = int(WINAPI*)(::HWND, ::HDC);
	using FMCPGetWindowTextFn = int(WINAPI*)(::HWND, ::LPWSTR, int);
	using FMCPCreateCompatibleDCFn = ::HDC(WINAPI*)(::HDC);
	using FMCPDeleteDCFn = ::BOOL(WINAPI*)(::HDC);
	using FMCPCreateDIBSectionFn = ::HBITMAP(WINAPI*)(::HDC, const ::BITMAPINFO*, ::UINT, void**, ::HANDLE, ::DWORD);
	using FMCPSelectObjectFn = ::HGDIOBJ(WINAPI*)(::HDC, ::HGDIOBJ);
	using FMCPBitBltFn = ::BOOL(WINAPI*)(::HDC, int, int, int, int, ::HDC, int, int, ::DWORD);
	using FMCPDeleteObjectFn = ::BOOL(WINAPI*)(::HGDIOBJ);

	struct FMCPWindowsScreenshotApi
	{
		FMCPGetForegroundWindowFn GetForegroundWindow = nullptr;
		FMCPIsWindowVisibleFn IsWindowVisible = nullptr;
		FMCPIsIconicFn IsIconic = nullptr;
		FMCPGetWindowThreadProcessIdFn GetWindowThreadProcessId = nullptr;
		FMCPGetWindowRectFn GetWindowRect = nullptr;
		FMCPEnumWindowsFn EnumWindows = nullptr;
		FMCPGetWindowDCFn GetWindowDC = nullptr;
		FMCPReleaseDCFn ReleaseDC = nullptr;
		FMCPGetWindowTextFn GetWindowText = nullptr;
		FMCPCreateCompatibleDCFn CreateCompatibleDC = nullptr;
		FMCPDeleteDCFn DeleteDC = nullptr;
		FMCPCreateDIBSectionFn CreateDIBSection = nullptr;
		FMCPSelectObjectFn SelectObject = nullptr;
		FMCPBitBltFn BitBlt = nullptr;
		FMCPDeleteObjectFn DeleteObject = nullptr;

		bool IsValid() const
		{
			return GetForegroundWindow && IsWindowVisible && IsIconic && GetWindowThreadProcessId && GetWindowRect && EnumWindows
				&& GetWindowDC && ReleaseDC && GetWindowText && CreateCompatibleDC && DeleteDC && CreateDIBSection
				&& SelectObject && BitBlt && DeleteObject;
		}
	};

	template <typename FuncType>
	FuncType LoadWindowsFunction(void* DllHandle, const TCHAR* FunctionName)
	{
		return reinterpret_cast<FuncType>(FPlatformProcess::GetDllExport(DllHandle, FunctionName));
	}

	FMCPWindowsScreenshotApi LoadWindowsScreenshotApi()
	{
		FMCPWindowsScreenshotApi Api;
		void* User32 = FPlatformProcess::GetDllHandle(TEXT("user32.dll"));
		void* Gdi32 = FPlatformProcess::GetDllHandle(TEXT("gdi32.dll"));
		if (!User32 || !Gdi32)
		{
			return Api;
		}

		Api.GetForegroundWindow = LoadWindowsFunction<FMCPGetForegroundWindowFn>(User32, TEXT("GetForegroundWindow"));
		Api.IsWindowVisible = LoadWindowsFunction<FMCPIsWindowVisibleFn>(User32, TEXT("IsWindowVisible"));
		Api.IsIconic = LoadWindowsFunction<FMCPIsIconicFn>(User32, TEXT("IsIconic"));
		Api.GetWindowThreadProcessId = LoadWindowsFunction<FMCPGetWindowThreadProcessIdFn>(User32, TEXT("GetWindowThreadProcessId"));
		Api.GetWindowRect = LoadWindowsFunction<FMCPGetWindowRectFn>(User32, TEXT("GetWindowRect"));
		Api.EnumWindows = LoadWindowsFunction<FMCPEnumWindowsFn>(User32, TEXT("EnumWindows"));
		Api.GetWindowDC = LoadWindowsFunction<FMCPGetWindowDCFn>(User32, TEXT("GetWindowDC"));
		Api.ReleaseDC = LoadWindowsFunction<FMCPReleaseDCFn>(User32, TEXT("ReleaseDC"));
		Api.GetWindowText = LoadWindowsFunction<FMCPGetWindowTextFn>(User32, TEXT("GetWindowTextW"));
		Api.CreateCompatibleDC = LoadWindowsFunction<FMCPCreateCompatibleDCFn>(Gdi32, TEXT("CreateCompatibleDC"));
		Api.DeleteDC = LoadWindowsFunction<FMCPDeleteDCFn>(Gdi32, TEXT("DeleteDC"));
		Api.CreateDIBSection = LoadWindowsFunction<FMCPCreateDIBSectionFn>(Gdi32, TEXT("CreateDIBSection"));
		Api.SelectObject = LoadWindowsFunction<FMCPSelectObjectFn>(Gdi32, TEXT("SelectObject"));
		Api.BitBlt = LoadWindowsFunction<FMCPBitBltFn>(Gdi32, TEXT("BitBlt"));
		Api.DeleteObject = LoadWindowsFunction<FMCPDeleteObjectFn>(Gdi32, TEXT("DeleteObject"));
		return Api;
	}

	struct FMCPWindowSearchState
	{
		const FMCPWindowsScreenshotApi* Api = nullptr;
		::DWORD ProcessId = 0;
		::HWND WindowHandle = nullptr;
	};

	bool IsUsableProcessWindow(const FMCPWindowsScreenshotApi& Api, ::HWND WindowHandle, ::DWORD ProcessId)
	{
		if (!WindowHandle || !Api.IsWindowVisible(WindowHandle) || Api.IsIconic(WindowHandle))
		{
			return false;
		}

		::DWORD WindowProcessId = 0;
		Api.GetWindowThreadProcessId(WindowHandle, &WindowProcessId);
		if (WindowProcessId != ProcessId)
		{
			return false;
		}

		::RECT WindowRect;
		if (!Api.GetWindowRect(WindowHandle, &WindowRect))
		{
			return false;
		}
		return (WindowRect.right - WindowRect.left) > 0 && (WindowRect.bottom - WindowRect.top) > 0;
	}

	::BOOL CALLBACK EnumCurrentProcessWindows(::HWND WindowHandle, ::LPARAM UserData)
	{
		FMCPWindowSearchState* SearchState = reinterpret_cast<FMCPWindowSearchState*>(UserData);
		if (SearchState && SearchState->Api && IsUsableProcessWindow(*SearchState->Api, WindowHandle, SearchState->ProcessId))
		{
			SearchState->WindowHandle = WindowHandle;
			return false;
		}
		return true;
	}

	::HWND FindCurrentProcessWindow(const FMCPWindowsScreenshotApi& Api)
	{
		const ::DWORD ProcessId = static_cast<::DWORD>(FPlatformProcess::GetCurrentProcessId());
		::HWND ForegroundWindow = Api.GetForegroundWindow();
		if (IsUsableProcessWindow(Api, ForegroundWindow, ProcessId))
		{
			return ForegroundWindow;
		}

		FMCPWindowSearchState SearchState;
		SearchState.Api = &Api;
		SearchState.ProcessId = ProcessId;
		Api.EnumWindows(&EnumCurrentProcessWindows, reinterpret_cast<::LPARAM>(&SearchState));
		return SearchState.WindowHandle;
	}

	bool CaptureWindowsWindowToPixels(::HWND WindowHandle, const FMCPWindowsScreenshotApi& Api, TArray<FColor>& OutPixels, int32& OutWidth, int32& OutHeight, FString& OutTitle)
	{
		if (!WindowHandle)
		{
			return false;
		}

		::RECT WindowRect;
		if (!Api.GetWindowRect(WindowHandle, &WindowRect))
		{
			return false;
		}

		OutWidth = WindowRect.right - WindowRect.left;
		OutHeight = WindowRect.bottom - WindowRect.top;
		if (OutWidth <= 0 || OutHeight <= 0)
		{
			return false;
		}

		::HDC WindowDC = Api.GetWindowDC(WindowHandle);
		if (!WindowDC)
		{
			return false;
		}

		::HDC MemoryDC = Api.CreateCompatibleDC(WindowDC);
		if (!MemoryDC)
		{
			Api.ReleaseDC(WindowHandle, WindowDC);
			return false;
		}

		::BITMAPINFO BitmapInfo;
		FMemory::Memzero(BitmapInfo);
		BitmapInfo.bmiHeader.biSize = sizeof(::BITMAPINFOHEADER);
		BitmapInfo.bmiHeader.biWidth = OutWidth;
		BitmapInfo.bmiHeader.biHeight = -OutHeight;
		BitmapInfo.bmiHeader.biPlanes = 1;
		BitmapInfo.bmiHeader.biBitCount = 32;
		BitmapInfo.bmiHeader.biCompression = BI_RGB;

		void* RawBits = nullptr;
		::HBITMAP Bitmap = Api.CreateDIBSection(WindowDC, &BitmapInfo, DIB_RGB_COLORS, &RawBits, nullptr, 0);
		if (!Bitmap || !RawBits)
		{
			if (Bitmap)
			{
				Api.DeleteObject(Bitmap);
			}
			Api.DeleteDC(MemoryDC);
			Api.ReleaseDC(WindowHandle, WindowDC);
			return false;
		}

		::HGDIOBJ OldBitmap = Api.SelectObject(MemoryDC, Bitmap);
		const ::BOOL bBitBltSucceeded = Api.BitBlt(MemoryDC, 0, 0, OutWidth, OutHeight, WindowDC, 0, 0, SRCCOPY | CAPTUREBLT);
		Api.SelectObject(MemoryDC, OldBitmap);

		if (bBitBltSucceeded)
		{
			const int64 PixelCount = static_cast<int64>(OutWidth) * static_cast<int64>(OutHeight);
			OutPixels.SetNumUninitialized(static_cast<int32>(PixelCount));
			FMemory::Memcpy(OutPixels.GetData(), RawBits, static_cast<SIZE_T>(PixelCount * sizeof(FColor)));
			for (FColor& Pixel : OutPixels)
			{
				Pixel.A = 255;
			}
		}

		WCHAR TitleBuffer[512] = { 0 };
		Api.GetWindowText(WindowHandle, TitleBuffer, UE_ARRAY_COUNT(TitleBuffer));
		OutTitle = TitleBuffer;
		if (OutTitle.IsEmpty())
		{
			OutTitle = TEXT("current_process_window");
		}

		Api.DeleteObject(Bitmap);
		Api.DeleteDC(MemoryDC);
		Api.ReleaseDC(WindowHandle, WindowDC);
		return bBitBltSucceeded && !OutPixels.IsEmpty();
	}
#endif
}

bool FCaptureEditorScreenshotAction::Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError)
{
	const FString Target = GetOptionalString(Params, TEXT("target"), TEXT("active_window"));
	if (!IsValidScreenshotTarget(Target))
	{
		OutError = FString::Printf(TEXT("Invalid target '%s'. Use active_window or active_viewport."), *Target);
		return false;
	}

	const TCHAR* DimensionFields[] = { TEXT("max_width"), TEXT("max_height") };
	for (const TCHAR* DimensionField : DimensionFields)
	{
		if (Params.IsValid() && Params->HasField(DimensionField) && Params->GetNumberField(DimensionField) <= 0.0)
		{
			OutError = FString::Printf(TEXT("%s must be > 0."), DimensionField);
			return false;
		}
	}
	return true;
}

TSharedPtr<FJsonObject> FCaptureEditorScreenshotAction::ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context)
{
	const FString Target = GetOptionalString(Params, TEXT("target"), TEXT("active_window"));
	const int32 MaxWidth = ResolveScreenshotDimension(Params, TEXT("max_width"), MCPDefaultScreenshotMaxWidth);
	const int32 MaxHeight = ResolveScreenshotDimension(Params, TEXT("max_height"), MCPDefaultScreenshotMaxHeight);
	const bool bIncludeBase64 = GetOptionalBool(Params, TEXT("include_base64"), true);
	const bool bFullResolution = GetOptionalBool(Params, TEXT("full_resolution"), false);


	TArray<FColor> SourcePixels;
	int32 SourceWidth = 0;
	int32 SourceHeight = 0;
	FString SourceName;

	if (Target.Equals(TEXT("active_viewport"), ESearchCase::IgnoreCase))
	{
		FViewport* Viewport = GEditor ? GEditor->GetActiveViewport() : nullptr;
		if (!Viewport)
		{
			return CreateErrorResponse(TEXT("No active editor viewport available."), TEXT("no_viewport"));
		}

		Viewport->InvalidateDisplay();
		const FIntPoint ViewportSize = Viewport->GetSizeXY();
		SourceWidth = ViewportSize.X;
		SourceHeight = ViewportSize.Y;
		if (SourceWidth <= 0 || SourceHeight <= 0)
		{
			return CreateErrorResponse(TEXT("Active viewport has invalid dimensions."), TEXT("invalid_viewport_size"));
		}

		FReadSurfaceDataFlags ReadSurfaceFlags(RCM_UNorm);
		ReadSurfaceFlags.SetLinearToGamma(true);
		if (!GetViewportScreenShot(Viewport, SourcePixels, FIntRect(0, 0, SourceWidth, SourceHeight), ReadSurfaceFlags))
		{
			return CreateErrorResponse(TEXT("Failed to capture active editor viewport."), TEXT("viewport_capture_failed"));
		}
		SourceName = TEXT("active_viewport");
	}
	else
	{
		bool bCapturedWindow = false;
		if (FSlateApplication::IsInitialized())
		{
			TSharedPtr<SWindow> TargetWindow = FSlateApplication::Get().GetActiveTopLevelWindow();
			if (!TargetWindow.IsValid())
			{
				TArray<TSharedRef<SWindow>> VisibleWindows;
				FSlateApplication::Get().GetAllVisibleWindowsOrdered(VisibleWindows);
				if (!VisibleWindows.IsEmpty())
				{
					TargetWindow = VisibleWindows.Last();
				}
			}

			if (TargetWindow.IsValid())
			{
				FSlateApplication::Get().ForceRedrawWindow(TargetWindow.ToSharedRef());
				FIntVector ScreenshotSize(0, 0, 0);
				if (FSlateApplication::Get().TakeScreenshot(StaticCastSharedRef<SWidget>(TargetWindow.ToSharedRef()), SourcePixels, ScreenshotSize))
				{
					SourceWidth = ScreenshotSize.X;
					SourceHeight = ScreenshotSize.Y;
					SourceName = TargetWindow->GetTitle().ToString();
					bCapturedWindow = true;
				}
			}
		}

#if PLATFORM_WINDOWS
		if (!bCapturedWindow)
		{
			const FMCPWindowsScreenshotApi WindowsApi = LoadWindowsScreenshotApi();
			if (WindowsApi.IsValid())
			{
				::HWND WindowHandle = FindCurrentProcessWindow(WindowsApi);
				bCapturedWindow = CaptureWindowsWindowToPixels(WindowHandle, WindowsApi, SourcePixels, SourceWidth, SourceHeight, SourceName);
				if (bCapturedWindow)
				{
					SourceName = FString::Printf(TEXT("%s (windows_fallback)"), *SourceName);
				}
			}
		}
#endif

		if (!bCapturedWindow)
		{
			FViewport* Viewport = GEditor ? GEditor->GetActiveViewport() : nullptr;
			if (Viewport)
			{
				Viewport->InvalidateDisplay();
				const FIntPoint ViewportSize = Viewport->GetSizeXY();
				SourceWidth = ViewportSize.X;
				SourceHeight = ViewportSize.Y;
				if (SourceWidth > 0 && SourceHeight > 0)
				{
					FReadSurfaceDataFlags ReadSurfaceFlags(RCM_UNorm);
					ReadSurfaceFlags.SetLinearToGamma(true);
					bCapturedWindow = GetViewportScreenShot(Viewport, SourcePixels, FIntRect(0, 0, SourceWidth, SourceHeight), ReadSurfaceFlags);
					if (bCapturedWindow)
					{
						SourceName = TEXT("active_viewport_fallback");
					}
				}
			}
		}

		if (!bCapturedWindow)
		{
			return CreateErrorResponse(TEXT("Failed to capture active Slate, process window, or active viewport fallback."), TEXT("window_capture_failed"));
		}
	}

	const int64 ExpectedPixelCount = static_cast<int64>(SourceWidth) * static_cast<int64>(SourceHeight);
	if (SourceWidth <= 0 || SourceHeight <= 0 || SourcePixels.Num() < ExpectedPixelCount)
	{
		return CreateErrorResponse(TEXT("Captured screenshot has invalid image data."), TEXT("invalid_image_data"));
	}

	TArray<FColor> OutputPixels;
	int32 OutputWidth = SourceWidth;
	int32 OutputHeight = SourceHeight;
	if (bFullResolution)
	{
		OutputPixels = SourcePixels;
	}
	else
	{
		FitScreenshotToBounds(SourcePixels, SourceWidth, SourceHeight, MaxWidth, MaxHeight, OutputPixels, OutputWidth, OutputHeight);
	}

	TArray<uint8> CompressedPngBytes;

	FImageUtils::ThumbnailCompressImageArray(OutputWidth, OutputHeight, OutputPixels, CompressedPngBytes);
	if (CompressedPngBytes.IsEmpty())
	{
		return CreateErrorResponse(TEXT("Failed to compress screenshot to PNG."), TEXT("png_compress_failed"));
	}

	TSharedPtr<FJsonObject> Result = MakeShared<FJsonObject>();
	Result->SetStringField(TEXT("target"), Target.ToLower());
	Result->SetStringField(TEXT("source_name"), SourceName);
	Result->SetStringField(TEXT("mime_type"), TEXT("image/png"));
	Result->SetStringField(TEXT("image_format"), TEXT("png"));
	Result->SetNumberField(TEXT("source_width"), SourceWidth);
	Result->SetNumberField(TEXT("source_height"), SourceHeight);
	Result->SetNumberField(TEXT("width"), OutputWidth);
	Result->SetNumberField(TEXT("height"), OutputHeight);
	Result->SetNumberField(TEXT("max_width"), MaxWidth);
	Result->SetNumberField(TEXT("max_height"), MaxHeight);
	Result->SetBoolField(TEXT("full_resolution"), bFullResolution);
	Result->SetBoolField(TEXT("scaled"), OutputWidth != SourceWidth || OutputHeight != SourceHeight);
	Result->SetNumberField(TEXT("image_byte_size"), CompressedPngBytes.Num());
	Result->SetBoolField(TEXT("include_base64"), bIncludeBase64);

	if (bIncludeBase64)
	{
		Result->SetStringField(TEXT("image_base64"), FBase64::Encode(CompressedPngBytes));
	}
	return CreateSuccessResponse(Result);
}


// ========================================================================
// FGetSelectedAssetsAction
// ========================================================================

TSharedPtr<FJsonObject> FGetSelectedAssetsAction::ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context)
{
	TArray<FAssetData> SelectedAssets;
	AssetSelectionUtils::GetSelectedAssets(SelectedAssets);

	if (SelectedAssets.IsEmpty())
	{
		return CreateErrorResponse(
			TEXT("No assets are currently selected in the Content Browser."),
			TEXT("no_selection")
		);
	}

	TArray<TSharedPtr<FJsonValue>> AssetsArray;

	for (const FAssetData& AssetData : SelectedAssets)
	{
		TSharedPtr<FJsonObject> AssetObj = MakeShared<FJsonObject>();
		AssetObj->SetStringField(TEXT("asset_name"), AssetData.AssetName.ToString());
		AssetObj->SetStringField(TEXT("asset_path"), AssetData.GetObjectPathString());
		AssetObj->SetStringField(TEXT("package_name"), AssetData.PackageName.ToString());
		AssetObj->SetStringField(TEXT("package_path"), AssetData.PackagePath.ToString());
		AssetObj->SetStringField(TEXT("asset_class"), AssetData.AssetClassPath.GetAssetName().ToString());
		AssetObj->SetStringField(TEXT("asset_class_path"), AssetData.AssetClassPath.ToString());
		AssetsArray.Add(MakeShared<FJsonValueObject>(AssetObj));
	}

	TSharedPtr<FJsonObject> Result = MakeShared<FJsonObject>();
	Result->SetNumberField(TEXT("count"), SelectedAssets.Num());
	Result->SetArrayField(TEXT("assets"), AssetsArray);

	return CreateSuccessResponse(Result);
}


// ========================================================================
// FGetBlueprintSummaryAction
// ========================================================================

bool FGetBlueprintSummaryAction::Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError)
{
	if (!Params->HasField(TEXT("blueprint_name")) && !Params->HasField(TEXT("asset_path")))
	{
		OutError = TEXT("Missing required 'blueprint_name' or 'asset_path' parameter");
		return false;
	}
	return true;
}

TSharedPtr<FJsonObject> FGetBlueprintSummaryAction::ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context)
{
	UBlueprint* Blueprint = nullptr;

	// Load blueprint by name or path
	if (Params->HasField(TEXT("asset_path")))
	{
		FString AssetPath = Params->GetStringField(TEXT("asset_path"));
		Blueprint = Cast<UBlueprint>(StaticLoadObject(UBlueprint::StaticClass(), nullptr, *AssetPath));
	}
	
	if (!Blueprint && Params->HasField(TEXT("blueprint_name")))
	{
		FString BlueprintName = Params->GetStringField(TEXT("blueprint_name"));
		Blueprint = FMCPCommonUtils::FindBlueprint(BlueprintName);
	}

	if (!Blueprint)
	{
		return CreateErrorResponse(TEXT("Blueprint not found"));
	}

	TSharedPtr<FJsonObject> Result = MakeShared<FJsonObject>();
	Result->SetStringField(TEXT("blueprint_name"), Blueprint->GetName());
	Result->SetStringField(TEXT("blueprint_path"), Blueprint->GetPathName());

	// Parent class
	if (Blueprint->ParentClass)
	{
		Result->SetStringField(TEXT("parent_class"), Blueprint->ParentClass->GetName());
		Result->SetStringField(TEXT("parent_class_path"), Blueprint->ParentClass->GetPathName());
	}

	// Blueprint type
	FString TypeStr;
	switch (Blueprint->BlueprintType)
	{
		case BPTYPE_Normal: TypeStr = TEXT("Normal"); break;
		case BPTYPE_Const: TypeStr = TEXT("Const"); break;
		case BPTYPE_MacroLibrary: TypeStr = TEXT("MacroLibrary"); break;
		case BPTYPE_Interface: TypeStr = TEXT("Interface"); break;
		case BPTYPE_LevelScript: TypeStr = TEXT("LevelScript"); break;
		case BPTYPE_FunctionLibrary: TypeStr = TEXT("FunctionLibrary"); break;
		default: TypeStr = TEXT("Unknown"); break;
	}
	Result->SetStringField(TEXT("blueprint_type"), TypeStr);

	// Compile status
	FString CompileStatus;
	switch (Blueprint->Status)
	{
		case BS_UpToDate: CompileStatus = TEXT("UpToDate"); break;
		case BS_Dirty: CompileStatus = TEXT("Dirty"); break;
		case BS_Error: CompileStatus = TEXT("Error"); break;
		case BS_BeingCreated: CompileStatus = TEXT("BeingCreated"); break;
		default: CompileStatus = TEXT("Unknown"); break;
	}
	Result->SetStringField(TEXT("compile_status"), CompileStatus);

	// ---- Variables ----
	TArray<TSharedPtr<FJsonValue>> VarsArray;
	for (const FBPVariableDescription& VarDesc : Blueprint->NewVariables)
	{
		TSharedPtr<FJsonObject> VarObj = MakeShared<FJsonObject>();
		VarObj->SetStringField(TEXT("name"), VarDesc.VarName.ToString());
		VarObj->SetStringField(TEXT("type"), VarDesc.VarType.PinCategory.ToString());

		if (VarDesc.VarType.PinSubCategoryObject.IsValid())
		{
			VarObj->SetStringField(TEXT("sub_type"), VarDesc.VarType.PinSubCategoryObject->GetName());
		}

		// Container type
		if (VarDesc.VarType.IsArray())
		{
			VarObj->SetStringField(TEXT("container"), TEXT("Array"));
		}
		else if (VarDesc.VarType.IsSet())
		{
			VarObj->SetStringField(TEXT("container"), TEXT("Set"));
		}
		else if (VarDesc.VarType.IsMap())
		{
			VarObj->SetStringField(TEXT("container"), TEXT("Map"));
		}

		VarObj->SetBoolField(TEXT("is_instance_editable"), VarDesc.PropertyFlags & CPF_Edit ? true : false);
		VarObj->SetBoolField(TEXT("is_blueprint_read_only"), VarDesc.PropertyFlags & CPF_BlueprintReadOnly ? true : false);

		if (!VarDesc.Category.IsEmpty())
		{
			VarObj->SetStringField(TEXT("category"), VarDesc.Category.ToString());
		}
		if (!VarDesc.DefaultValue.IsEmpty())
		{
			VarObj->SetStringField(TEXT("default_value"), VarDesc.DefaultValue);
		}

		VarsArray.Add(MakeShared<FJsonValueObject>(VarObj));
	}
	Result->SetArrayField(TEXT("variables"), VarsArray);

	// ---- Functions / Graphs ----
	TArray<TSharedPtr<FJsonValue>> FunctionsArray;
	for (UEdGraph* Graph : Blueprint->FunctionGraphs)
	{
		if (!Graph) continue;
		TSharedPtr<FJsonObject> FuncObj = MakeShared<FJsonObject>();
		FuncObj->SetStringField(TEXT("name"), Graph->GetName());
		FuncObj->SetNumberField(TEXT("node_count"), Graph->Nodes.Num());

		// Try to get access specifier and descriptions from function entry
		for (UEdGraphNode* Node : Graph->Nodes)
		{
			if (UK2Node_FunctionEntry* FuncEntry = Cast<UK2Node_FunctionEntry>(Node))
			{
				// Collect parameter pins
				TArray<TSharedPtr<FJsonValue>> ParamsArray;
				for (UEdGraphPin* Pin : FuncEntry->Pins)
				{
					if (Pin && Pin->Direction == EGPD_Output && Pin->PinName != UEdGraphSchema_K2::PN_Then)
					{
						TSharedPtr<FJsonObject> PinObj = MakeShared<FJsonObject>();
						PinObj->SetStringField(TEXT("name"), Pin->PinName.ToString());
						PinObj->SetStringField(TEXT("type"), Pin->PinType.PinCategory.ToString());
						if (Pin->PinType.PinSubCategoryObject.IsValid())
						{
							PinObj->SetStringField(TEXT("sub_type"), Pin->PinType.PinSubCategoryObject->GetName());
						}
						ParamsArray.Add(MakeShared<FJsonValueObject>(PinObj));
					}
				}
				FuncObj->SetArrayField(TEXT("parameters"), ParamsArray);
				break;
			}
		}

		FunctionsArray.Add(MakeShared<FJsonValueObject>(FuncObj));
	}
	Result->SetArrayField(TEXT("functions"), FunctionsArray);

	// ---- Macros ----
	TArray<TSharedPtr<FJsonValue>> MacrosArray;
	for (UEdGraph* Graph : Blueprint->MacroGraphs)
	{
		if (!Graph) continue;
		TSharedPtr<FJsonObject> MacroObj = MakeShared<FJsonObject>();
		MacroObj->SetStringField(TEXT("name"), Graph->GetName());
		MacroObj->SetNumberField(TEXT("node_count"), Graph->Nodes.Num());
		MacrosArray.Add(MakeShared<FJsonValueObject>(MacroObj));
	}
	Result->SetArrayField(TEXT("macros"), MacrosArray);

	// ---- Event Graphs ----
	TArray<TSharedPtr<FJsonValue>> EventGraphsArray;
	for (UEdGraph* Graph : Blueprint->UbergraphPages)
	{
		if (!Graph) continue;
		TSharedPtr<FJsonObject> GraphObj = MakeShared<FJsonObject>();
		GraphObj->SetStringField(TEXT("name"), Graph->GetName());
		GraphObj->SetNumberField(TEXT("node_count"), Graph->Nodes.Num());

		// Collect event nodes and key node types
		TArray<TSharedPtr<FJsonValue>> EventNodes;
		int32 FunctionCallCount = 0;
		int32 VarGetCount = 0;
		int32 VarSetCount = 0;
		int32 CustomEventCount = 0;

		for (UEdGraphNode* Node : Graph->Nodes)
		{
			if (UK2Node_Event* EventNode = Cast<UK2Node_Event>(Node))
			{
				TSharedPtr<FJsonObject> EvObj = MakeShared<FJsonObject>();
				EvObj->SetStringField(TEXT("event_name"), EventNode->GetNodeTitle(ENodeTitleType::ListView).ToString());
				EvObj->SetStringField(TEXT("node_id"), EventNode->NodeGuid.ToString());
				EventNodes.Add(MakeShared<FJsonValueObject>(EvObj));
			}
			else if (Cast<UK2Node_CustomEvent>(Node))
			{
				CustomEventCount++;
				TSharedPtr<FJsonObject> EvObj = MakeShared<FJsonObject>();
				EvObj->SetStringField(TEXT("event_name"), Node->GetNodeTitle(ENodeTitleType::ListView).ToString());
				EvObj->SetStringField(TEXT("node_id"), Node->NodeGuid.ToString());
				EvObj->SetStringField(TEXT("type"), TEXT("CustomEvent"));
				EventNodes.Add(MakeShared<FJsonValueObject>(EvObj));
			}
			else if (Cast<UK2Node_CallFunction>(Node))
			{
				FunctionCallCount++;
			}
			else if (Cast<UK2Node_VariableGet>(Node))
			{
				VarGetCount++;
			}
			else if (Cast<UK2Node_VariableSet>(Node))
			{
				VarSetCount++;
			}
		}

		GraphObj->SetArrayField(TEXT("events"), EventNodes);

		TSharedPtr<FJsonObject> StatsObj = MakeShared<FJsonObject>();
		StatsObj->SetNumberField(TEXT("function_calls"), FunctionCallCount);
		StatsObj->SetNumberField(TEXT("variable_gets"), VarGetCount);
		StatsObj->SetNumberField(TEXT("variable_sets"), VarSetCount);
		StatsObj->SetNumberField(TEXT("custom_events"), CustomEventCount);
		GraphObj->SetObjectField(TEXT("stats"), StatsObj);

		EventGraphsArray.Add(MakeShared<FJsonValueObject>(GraphObj));
	}
	Result->SetArrayField(TEXT("event_graphs"), EventGraphsArray);

	// ---- Components (from SCS) ----
	TArray<TSharedPtr<FJsonValue>> ComponentsArray;
	if (Blueprint->SimpleConstructionScript)
	{
		TArray<USCS_Node*> AllNodes = Blueprint->SimpleConstructionScript->GetAllNodes();
		for (USCS_Node* SCSNode : AllNodes)
		{
			if (!SCSNode) continue;
			TSharedPtr<FJsonObject> CompObj = MakeShared<FJsonObject>();
			CompObj->SetStringField(TEXT("name"), SCSNode->GetVariableName().ToString());
			if (SCSNode->ComponentClass)
			{
				CompObj->SetStringField(TEXT("class"), SCSNode->ComponentClass->GetName());
			}
			// Parent info via ParentComponentOrVariableName
			if (!SCSNode->ParentComponentOrVariableName.IsNone())
			{
				CompObj->SetStringField(TEXT("parent"), SCSNode->ParentComponentOrVariableName.ToString());
			}
			ComponentsArray.Add(MakeShared<FJsonValueObject>(CompObj));
		}
	}
	Result->SetArrayField(TEXT("components"), ComponentsArray);

	// ---- Interfaces ----
	TArray<TSharedPtr<FJsonValue>> InterfacesArray;
	for (const FBPInterfaceDescription& InterfaceDesc : Blueprint->ImplementedInterfaces)
	{
		if (InterfaceDesc.Interface)
		{
			InterfacesArray.Add(MakeShared<FJsonValueString>(InterfaceDesc.Interface->GetName()));
		}
	}
	Result->SetArrayField(TEXT("implemented_interfaces"), InterfacesArray);

	return CreateSuccessResponse(Result);
}


// ============================================================================
// P2: FGetEditorLogsAction
// ============================================================================

namespace
{
ELogVerbosity::Type ParseMinVerbosity(const FString& VerbosityStr)
{
	if (VerbosityStr.Equals(TEXT("Fatal"), ESearchCase::IgnoreCase)) return ELogVerbosity::Fatal;
	if (VerbosityStr.Equals(TEXT("Error"), ESearchCase::IgnoreCase)) return ELogVerbosity::Error;
	if (VerbosityStr.Equals(TEXT("Warning"), ESearchCase::IgnoreCase)) return ELogVerbosity::Warning;
	if (VerbosityStr.Equals(TEXT("Display"), ESearchCase::IgnoreCase)) return ELogVerbosity::Display;
	if (VerbosityStr.Equals(TEXT("Log"), ESearchCase::IgnoreCase)) return ELogVerbosity::Log;
	if (VerbosityStr.Equals(TEXT("Verbose"), ESearchCase::IgnoreCase)) return ELogVerbosity::Verbose;
	if (VerbosityStr.Equals(TEXT("VeryVerbose"), ESearchCase::IgnoreCase)) return ELogVerbosity::VeryVerbose;
	return ELogVerbosity::All;
}

FString VerbosityToString(ELogVerbosity::Type Verbosity)
{
	switch (Verbosity)
	{
	case ELogVerbosity::Fatal: return TEXT("Fatal");
	case ELogVerbosity::Error: return TEXT("Error");
	case ELogVerbosity::Warning: return TEXT("Warning");
	case ELogVerbosity::Display: return TEXT("Display");
	case ELogVerbosity::Log: return TEXT("Log");
	case ELogVerbosity::Verbose: return TEXT("Verbose");
	default: return TEXT("VeryVerbose");
	}
}

uint64 ParseLiveCursor(const FString& Cursor)
{
	if (!Cursor.StartsWith(TEXT("live:")))
	{
		return 0;
	}

	uint64 Seq = 0;
	LexFromString(Seq, *Cursor.RightChop(5));
	return Seq;
}
}

TSharedPtr<FJsonObject> FGetEditorLogsAction::ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context)
{
	const int32 Count = static_cast<int32>(GetOptionalNumber(Params, TEXT("count"), 100.0));
	const FString CategoryFilter = GetOptionalString(Params, TEXT("category"));

	// Parse verbosity filter
	const ELogVerbosity::Type MinVerbosity = ParseMinVerbosity(GetOptionalString(Params, TEXT("min_verbosity")));

	TArray<FMCPLogCapture::FLogEntry> Entries = FMCPLogCapture::Get().GetRecent(Count, CategoryFilter, MinVerbosity);

	TArray<TSharedPtr<FJsonValue>> LinesArray;
	for (const FMCPLogCapture::FLogEntry& Entry : Entries)
	{
		TSharedPtr<FJsonObject> LineObj = MakeShared<FJsonObject>();
		LineObj->SetNumberField(TEXT("timestamp"), Entry.Timestamp);
		LineObj->SetStringField(TEXT("category"), Entry.Category.ToString());

		// Convert verbosity to string
		LineObj->SetStringField(TEXT("verbosity"), VerbosityToString(Entry.Verbosity));
		LineObj->SetStringField(TEXT("message"), Entry.Message);

		LinesArray.Add(MakeShared<FJsonValueObject>(LineObj));
	}

	TSharedPtr<FJsonObject> ResultData = MakeShared<FJsonObject>();
	ResultData->SetArrayField(TEXT("lines"), LinesArray);
	ResultData->SetNumberField(TEXT("total"), static_cast<double>(LinesArray.Num()));
	ResultData->SetNumberField(TEXT("total_captured"), static_cast<double>(FMCPLogCapture::Get().GetTotalCaptured()));
	ResultData->SetBoolField(TEXT("capturing"), FMCPLogCapture::Get().IsCapturing());
	return CreateSuccessResponse(ResultData);
}

TSharedPtr<FJsonObject> FGetUnrealLogsAction::ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context)
{
	FMCPLogCapture& Capture = FMCPLogCapture::Get();
	if (!Capture.IsCapturing())
	{
		return CreateErrorResponse(TEXT("Live log capture is not active"), TEXT("capture_inactive"));
	}

	const int32 TailLines = FMath::Clamp(static_cast<int32>(GetOptionalNumber(Params, TEXT("tail_lines"), 200.0)), 20, 2000);
	const int32 MaxBytes = FMath::Clamp(static_cast<int32>(GetOptionalNumber(Params, TEXT("max_bytes"), 65536.0)), 8192, 1024 * 1024);
	const bool bIncludeMeta = GetOptionalBool(Params, TEXT("include_meta"), true);
	const bool bRequireRecent = GetOptionalBool(Params, TEXT("require_recent"), false);
	const double RecentWindowSeconds = FMath::Max(0.0, GetOptionalNumber(Params, TEXT("recent_window_seconds"), 2.0));

	if (bRequireRecent && !Capture.HasRecentData(RecentWindowSeconds))
	{
		return CreateErrorResponse(
			FString::Printf(TEXT("No live logs in the last %.2f seconds"), RecentWindowSeconds),
			TEXT("no_recent_live_data"));
	}

	const FString Cursor = GetOptionalString(Params, TEXT("cursor"));
	const uint64 AfterSeq = ParseLiveCursor(Cursor);

	TArray<FString> CategoryFilters;
	const FString CategoryFilterSingle = GetOptionalString(Params, TEXT("filter_category"));
	if (!CategoryFilterSingle.IsEmpty())
	{
		CategoryFilters.Add(CategoryFilterSingle);
	}

	const TArray<TSharedPtr<FJsonValue>>* CategoryFilterArray = GetOptionalArray(Params, TEXT("filter_categories"));
	if (CategoryFilterArray)
	{
		for (const TSharedPtr<FJsonValue>& Value : *CategoryFilterArray)
		{
			FString CategoryValue;
			if (Value.IsValid() && Value->TryGetString(CategoryValue) && !CategoryValue.IsEmpty())
			{
				CategoryFilters.Add(CategoryValue);
			}
		}
	}

	const ELogVerbosity::Type MinVerbosity = ParseMinVerbosity(GetOptionalString(Params, TEXT("filter_min_verbosity")));
	const FString ContainsFilter = GetOptionalString(Params, TEXT("filter_contains"));

	bool bTruncated = false;
	uint64 LastSeq = Capture.GetLatestSeq();
	TArray<FMCPLogCapture::FLogEntry> Entries = Capture.GetSince(
		AfterSeq,
		TailLines,
		MaxBytes,
		CategoryFilters,
		MinVerbosity,
		ContainsFilter,
		bTruncated,
		LastSeq);

	if (AfterSeq == 0)
	{
		if (Entries.Num() > TailLines)
		{
			const int32 Start = Entries.Num() - TailLines;
			Entries.RemoveAt(0, Start);
			bTruncated = true;
		}
	}

	FString Content;
	int32 BytesReturned = 0;
	for (const FMCPLogCapture::FLogEntry& Entry : Entries)
	{
		const FString Line = FString::Printf(
			TEXT("[%s][%s][%s] %s\n"),
			*Entry.TimestampUtc.ToIso8601(),
			*VerbosityToString(Entry.Verbosity),
			*Entry.Category.ToString(),
			*Entry.Message);

		const int32 LineBytes = FTCHARToUTF8(*Line).Length();
		if (BytesReturned + LineBytes > MaxBytes)
		{
			bTruncated = true;
			break;
		}

		Content.Append(Line);
		BytesReturned += LineBytes;
	}

	TSharedPtr<FJsonObject> ResultData = MakeShared<FJsonObject>();
	ResultData->SetStringField(TEXT("source"), TEXT("live"));
	ResultData->SetBoolField(TEXT("isLive"), true);
	ResultData->SetStringField(TEXT("filePath"), TEXT(""));
	ResultData->SetStringField(TEXT("projectLogDir"), FPaths::ProjectLogDir());
	ResultData->SetStringField(TEXT("cursor"), FString::Printf(TEXT("live:%llu"), LastSeq));
	ResultData->SetBoolField(TEXT("truncated"), bTruncated);
	ResultData->SetNumberField(TEXT("linesReturned"), Entries.Num());
	ResultData->SetNumberField(TEXT("bytesReturned"), BytesReturned);
	ResultData->SetStringField(TEXT("lastUpdateUtc"), Capture.GetLastReceivedUtc().ToIso8601());
	ResultData->SetStringField(TEXT("content"), Content);

	TArray<TSharedPtr<FJsonValue>> Notes;
	if (AfterSeq > 0)
	{
		Notes.Add(MakeShared<FJsonValueString>(FString::Printf(TEXT("incremental_from_seq=%llu"), AfterSeq)));
	}
	if (bTruncated)
	{
		Notes.Add(MakeShared<FJsonValueString>(TEXT("response_truncated_by_limits")));
	}
	if (bIncludeMeta)
	{
		ResultData->SetBoolField(TEXT("hasRecentLiveData"), Capture.HasRecentData(2.0));
		ResultData->SetNumberField(TEXT("totalCaptured"), static_cast<double>(Capture.GetTotalCaptured()));
	}
	ResultData->SetArrayField(TEXT("notes"), Notes);

	if (Entries.Num() == 0 && AfterSeq == 0)
	{
		return CreateErrorResponse(TEXT("Live log capture has no entries yet"), TEXT("live_buffer_empty"));
	}

	return CreateSuccessResponse(ResultData);
}


// ============================================================================
// P2: FBatchExecuteAction
// ============================================================================

bool FBatchExecuteAction::Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError)
{
	const TArray<TSharedPtr<FJsonValue>>* Commands = GetOptionalArray(Params, TEXT("commands"));
	if (!Commands || Commands->Num() == 0)
	{
		OutError = TEXT("Missing or empty 'commands' array");
		return false;
	}
	if (Commands->Num() > MaxBatchSize)
	{
		OutError = FString::Printf(TEXT("Batch too large: %d commands (max %d)"), Commands->Num(), MaxBatchSize);
		return false;
	}
	return true;
}

TSharedPtr<FJsonObject> FBatchExecuteAction::ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context)
{
	using namespace UEEditorMCPBatch;

	const TArray<TSharedPtr<FJsonValue>>* Commands = GetOptionalArray(Params, TEXT("commands"));
	const bool bStopOnError = GetOptionalBool(Params, TEXT("stop_on_error"), true);
	const FString ResultVerbosity = GetOptionalString(Params, TEXT("result_verbosity"), TEXT("compact"));
	const bool bFullResults = IsFullVerbosity(ResultVerbosity);

	// We need access to the Bridge to dispatch sub-commands
	UMCPBridge* Bridge = GEditor ? GEditor->GetEditorSubsystem<UMCPBridge>() : nullptr;
	if (!Bridge)
	{
		return CreateErrorResponse(TEXT("MCPBridge subsystem not available"));
	}

	const int32 Total = Commands->Num();
	TArray<TSharedPtr<FJsonValue>> ResultsArray;
	TArray<TSharedPtr<FJsonValue>> FailuresArray;
	TArray<TSharedPtr<FJsonObject>> StepResults;
	int32 Succeeded = 0;
	int32 Failed = 0;
	int32 Executed = 0;
	int32 FirstFailureIndex = INDEX_NONE;

	auto AddResult = [&](const TSharedPtr<FJsonObject>& FullResult, bool bSubSuccess)
	{
		const TSharedPtr<FJsonObject> StoredResult = bFullResults ? CloneJsonObject(FullResult) : MakeCompactResult(FullResult);
		ResultsArray.Add(MakeShared<FJsonValueObject>(StoredResult));
		StepResults.Add(CloneJsonObject(FullResult));
		if (!bSubSuccess)
		{
			FailuresArray.Add(MakeShared<FJsonValueObject>(MakeCompactResult(FullResult)));
			if (FirstFailureIndex == INDEX_NONE)
			{
				double IndexNumber = 0.0;
				FirstFailureIndex = FullResult->TryGetNumberField(TEXT("index"), IndexNumber) ? static_cast<int32>(IndexNumber) : Executed;
			}
		}
	};

	for (int32 i = 0; i < Total; ++i)
	{
		const TSharedPtr<FJsonObject>* CmdObj = nullptr;
		if (!(*Commands)[i]->TryGetObject(CmdObj) || !CmdObj || !(*CmdObj).IsValid())
		{
			TSharedPtr<FJsonObject> ErrResult = MakeShared<FJsonObject>();
			ErrResult->SetNumberField(TEXT("index"), i);
			ErrResult->SetBoolField(TEXT("success"), false);
			ErrResult->SetStringField(TEXT("error_type"), TEXT("invalid_command"));
			ErrResult->SetStringField(TEXT("error"), TEXT("Invalid command object"));
			AddResult(ErrResult, false);
			++Failed;
			++Executed;
			if (bStopOnError) break;
			continue;
		}

		FString CmdType;
		FString ActionId;
		(*CmdObj)->TryGetStringField(TEXT("action_id"), ActionId);
		if (!(*CmdObj)->TryGetStringField(TEXT("type"), CmdType) || CmdType.IsEmpty())
		{
			TSharedPtr<FJsonObject> ErrResult = MakeShared<FJsonObject>();
			ErrResult->SetNumberField(TEXT("index"), i);
			if (!ActionId.IsEmpty())
			{
				ErrResult->SetStringField(TEXT("action_id"), ActionId);
			}
			ErrResult->SetBoolField(TEXT("success"), false);
			ErrResult->SetStringField(TEXT("error_type"), TEXT("invalid_command"));
			ErrResult->SetStringField(TEXT("error"), TEXT("Missing 'type' field"));
			AddResult(ErrResult, false);
			++Failed;
			++Executed;
			if (bStopOnError) break;
			continue;
		}

		TSharedPtr<FJsonObject> CmdParams;
		const TSharedPtr<FJsonObject>* CmdParamsPtr = nullptr;
		if ((*CmdObj)->TryGetObjectField(TEXT("params"), CmdParamsPtr) && CmdParamsPtr)
		{
			FString RefError;
			CmdParams = ResolveJsonRefsInObject(*CmdParamsPtr, StepResults, RefError);
			if (!CmdParams.IsValid())
			{
				TSharedPtr<FJsonObject> ErrResult = MakeShared<FJsonObject>();
				ErrResult->SetNumberField(TEXT("index"), i);
				ErrResult->SetStringField(TEXT("type"), CmdType);
				if (!ActionId.IsEmpty())
				{
					ErrResult->SetStringField(TEXT("action_id"), ActionId);
				}
				ErrResult->SetBoolField(TEXT("success"), false);
				ErrResult->SetStringField(TEXT("error_type"), TEXT("ref_resolution_failed"));
				ErrResult->SetStringField(TEXT("error"), RefError);
				AddResult(ErrResult, false);
				++Failed;
				++Executed;
				if (bStopOnError) break;
				continue;
			}
		}
		else
		{
			CmdParams = MakeShared<FJsonObject>();
		}

		UE_LOG(LogMCP, Log, TEXT("Batch[%d/%d]: executing '%s'"), i + 1, Total, *CmdType);

		// Execute the sub-command via the Bridge (bypasses TCP, stays on GameThread)
		TSharedPtr<FJsonObject> SubResult = Bridge->ExecuteCommand(CmdType, CmdParams);
		if (!SubResult.IsValid())
		{
			SubResult = MakeShared<FJsonObject>();
			SubResult->SetBoolField(TEXT("success"), false);
			SubResult->SetStringField(TEXT("error_type"), TEXT("null_result"));
			SubResult->SetStringField(TEXT("error"), TEXT("Command returned null result"));
		}

		SubResult->SetNumberField(TEXT("index"), i);
		SubResult->SetStringField(TEXT("type"), CmdType);
		if (!ActionId.IsEmpty())
		{
			SubResult->SetStringField(TEXT("action_id"), ActionId);
		}

		bool bSubSuccess = false;
		if (SubResult->TryGetBoolField(TEXT("success"), bSubSuccess) && bSubSuccess)
		{
			++Succeeded;
		}
		else
		{
			++Failed;
		}

		AddResult(SubResult, bSubSuccess);
		++Executed;

		if (!bSubSuccess && bStopOnError)
		{
			UE_LOG(LogMCP, Warning, TEXT("Batch stopped at command %d/%d ('%s') due to stop_on_error"), i + 1, Total, *CmdType);
			break;
		}
	}

	TSharedPtr<FJsonObject> ResultData = MakeShared<FJsonObject>();
	ResultData->SetNumberField(TEXT("total"), Total);
	ResultData->SetNumberField(TEXT("executed"), Executed);
	ResultData->SetNumberField(TEXT("succeeded"), Succeeded);
	ResultData->SetNumberField(TEXT("failed"), Failed);
	ResultData->SetBoolField(TEXT("has_failures"), Failed > 0);
	ResultData->SetStringField(TEXT("result_verbosity"), bFullResults ? TEXT("full") : TEXT("compact"));
	ResultData->SetArrayField(TEXT("results"), ResultsArray);
	ResultData->SetArrayField(TEXT("failures"), FailuresArray);
	if (FirstFailureIndex != INDEX_NONE)
	{
		ResultData->SetNumberField(TEXT("first_failure_index"), FirstFailureIndex);
	}

	// The batch command itself always succeeds (it dispatched commands).
	// Partial sub-command failures are conveyed via failed/has_failures/failures[].
	return CreateSuccessResponse(ResultData);
}


// ============================================================================
// FEditorIsReadyAction
// ============================================================================

TSharedPtr<FJsonObject> FEditorIsReadyAction::ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context)
{
	TSharedPtr<FJsonObject> Result = MakeShared<FJsonObject>();

	// 1) GEditor exists and is valid
	bool bEditorValid = (GEditor != nullptr);
	Result->SetBoolField(TEXT("editor_valid"), bEditorValid);

	// 2) Editor world is available
	bool bWorldReady = false;
	if (bEditorValid)
	{
		UWorld* World = GEditor->GetEditorWorldContext(false).World();
		bWorldReady = (World != nullptr);
	}
	Result->SetBoolField(TEXT("world_ready"), bWorldReady);

	// 3) Asset registry has finished initial scan
	bool bAssetRegistryReady = false;
	if (FModuleManager::Get().IsModuleLoaded(TEXT("AssetRegistry")))
	{
		IAssetRegistry& AssetRegistry = FModuleManager::LoadModuleChecked<FAssetRegistryModule>(TEXT("AssetRegistry")).Get();
		bAssetRegistryReady = !AssetRegistry.IsLoadingAssets();
	}
	Result->SetBoolField(TEXT("asset_registry_ready"), bAssetRegistryReady);

	// 4) Overall readiness: all critical subsystems ready
	bool bFullyReady = bEditorValid && bWorldReady && bAssetRegistryReady;
	Result->SetBoolField(TEXT("ready"), bFullyReady);

	// 5) Uptime info
	Result->SetNumberField(TEXT("engine_uptime_seconds"), FPlatformTime::Seconds());

	return CreateSuccessResponse(Result);
}


// ============================================================================
// FRequestEditorShutdownAction
// ============================================================================

TSharedPtr<FJsonObject> FRequestEditorShutdownAction::ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context)
{
	bool bForce = GetOptionalBool(Params, TEXT("force"), false);

	TSharedPtr<FJsonObject> Result = MakeShared<FJsonObject>();
	Result->SetBoolField(TEXT("shutdown_requested"), true);
	Result->SetBoolField(TEXT("force"), bForce);

	// Schedule the exit on the next game-thread tick so we can send the response first
	AsyncTask(ENamedThreads::GameThread, [bForce]()
	{
		// Small delay to ensure the MCP response is sent before the process starts shutting down
		FTSTicker::GetCoreTicker().AddTicker(
			FTickerDelegate::CreateLambda([bForce](float DeltaTime) -> bool
			{
				if (bForce)
				{
					// Force immediate exit - no save dialogs
					FPlatformMisc::RequestExitWithStatus(bForce, 0);
				}
				else
				{
					// Graceful shutdown - may show save dialog if -unattended is not set
					FPlatformMisc::RequestExit(false);
				}
				return false; // Don't tick again
			}),
			0.2f // 200ms delay to let TCP response flush
		);
	});

	return CreateSuccessResponse(Result);
}

// ============================================================================
// FExecConsoleCommandAction — Execute a console command with strict allowlist
// ============================================================================

bool FExecConsoleCommandAction::IsCommandAllowed(const FString& Command, FString& OutError)
{
	if (Command.IsEmpty())
	{
		OutError = TEXT("Empty command rejected.");
		return false;
	}
	if (Command.Len() > 512)
	{
		OutError = TEXT("Command too long (>512 chars) — refusing.");
		return false;
	}

	// Forbid multi-command separators (prevents chaining destructive ops after an allowed verb).
	const TCHAR* ForbiddenSeparators[] = { TEXT(";"), TEXT("&&"), TEXT("||"), TEXT("|") };
	for (const TCHAR* Sep : ForbiddenSeparators)
	{
		if (Command.Contains(Sep))
		{
			OutError = FString::Printf(TEXT("Command contains forbidden separator '%s' — one command per call only."), Sep);
			return false;
		}
	}

	// Denylist: anything in this list anywhere in the command (case-insensitive) is rejected.
	// Even if a prefix matches the allowlist, these substrings short-circuit a reject.
	const TCHAR* Denylist[] = {
		TEXT("quit"),
		TEXT("exit"),
		TEXT("open "),
		TEXT("travel "),
		TEXT("restart"),
		TEXT("crash"),
		TEXT("fatal"),
		TEXT("obj gc"),
		TEXT("rhi."),       // Render hardware interface knobs — too dangerous
		TEXT("..\\"),
		TEXT("../"),
		TEXT(":\\"),         // Absolute Windows paths (e.g. C:\)
		TEXT(":/"),          // Absolute Unix-style paths
	};
	for (const TCHAR* Bad : Denylist)
	{
		if (Command.Contains(Bad, ESearchCase::IgnoreCase))
		{
			OutError = FString::Printf(TEXT("Command contains forbidden substring '%s'."), Bad);
			return false;
		}
	}

	// Allowlist: command (after leading-whitespace trim) must START WITH one of these prefixes.
	// Lowercase comparison; case-insensitive UE convention.
	const TCHAR* AllowedPrefixes[] = {
		TEXT("automation "),
		TEXT("stat "),
		TEXT("log "),
		TEXT("viewmode "),
		TEXT("showflag."),
		TEXT("r."),
		TEXT("p."),
		TEXT("t."),
		TEXT("ai."),
		TEXT("slomo "),
		TEXT("ke "),
	};
	const FString Lower = Command.ToLower().TrimStart();
	for (const TCHAR* Allowed : AllowedPrefixes)
	{
		if (Lower.StartsWith(Allowed))
		{
			return true;
		}
	}

	OutError = FString::Printf(
		TEXT("Command does not match any allowed prefix. Allowed: Automation, Stat, log, viewmode, showflag., r., p., t., ai., slomo, ke. Got: '%.64s'"),
		*Command);
	return false;
}

bool FExecConsoleCommandAction::Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError)
{
	if (!Params.IsValid() || !Params->HasField(TEXT("command")))
	{
		OutError = TEXT("Missing required parameter: command");
		return false;
	}
	const FString Command = Params->GetStringField(TEXT("command"));
	return IsCommandAllowed(Command, OutError);
}

TSharedPtr<FJsonObject> FExecConsoleCommandAction::ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context)
{
	const FString Command = Params->GetStringField(TEXT("command"));
	const bool bCaptureLogs = GetOptionalBool(Params, TEXT("capture_logs"), true);
	const int32 CaptureLines = static_cast<int32>(GetOptionalNumber(Params, TEXT("capture_lines"), 200.0));

	UE_LOG(LogMCP, Log, TEXT("UEEditorMCP: exec_console_command='%s' (capture=%d, lines=%d)"),
		*Command, bCaptureLogs ? 1 : 0, CaptureLines);

	// Snapshot log seq before Exec so we can return only what this command produced.
	uint64 PreSeq = 0;
	if (bCaptureLogs)
	{
		PreSeq = FMCPLogCapture::Get().GetLatestSeq();
	}

	// Synchronous Exec on the global engine. Output device is *GLog so messages route normally.
	// Note: GEngine->Exec returns false if the command is not handled by any registered exec listener.
	// For "Automation RunTests X" this is actually async — Exec returns true immediately and tests run
	// over subsequent ticks. Caller should poll editor.assert_log / editor.get_logs to await results.
	bool bExecOk = false;
	if (GEngine != nullptr)
	{
		// Runtime validation commands such as "ce <EventName>" must execute in
		// the active PIE world. Falling back to the editor world while PIE is
		// running can mutate the authored level instead of the transient test
		// instance.
		UWorld* World = GEditor
			? (GEditor->PlayWorld
				? GEditor->PlayWorld.Get()
				: GEditor->GetEditorWorldContext(false).World())
			: nullptr;
		bExecOk = GEngine->Exec(World, *Command, *GLog);
	}

	TSharedPtr<FJsonObject> Result = MakeShared<FJsonObject>();
	Result->SetStringField(TEXT("command"), Command);
	Result->SetBoolField(TEXT("exec_succeeded"), bExecOk);

	if (bCaptureLogs)
	{
		bool bTruncated = false;
		uint64 LastSeq = 0;
		TArray<FMCPLogCapture::FLogEntry> NewEntries = FMCPLogCapture::Get().GetSince(
			PreSeq,
			CaptureLines,
			/*MaxBytes*/ 64 * 1024,
			TArray<FString>{},
			ELogVerbosity::All,
			/*ContainsFilter*/ FString(),
			bTruncated,
			LastSeq);

		TArray<TSharedPtr<FJsonValue>> LogArray;
		for (const FMCPLogCapture::FLogEntry& Entry : NewEntries)
		{
			TSharedPtr<FJsonObject> EntryObj = MakeShared<FJsonObject>();
			EntryObj->SetStringField(TEXT("category"), Entry.Category.ToString());
			EntryObj->SetStringField(TEXT("verbosity"), ToString(Entry.Verbosity));
			EntryObj->SetStringField(TEXT("message"), Entry.Message);
			EntryObj->SetNumberField(TEXT("seq"), static_cast<double>(Entry.Seq));
			LogArray.Add(MakeShared<FJsonValueObject>(EntryObj));
		}
		Result->SetArrayField(TEXT("captured_logs"), LogArray);
		Result->SetNumberField(TEXT("captured_count"), NewEntries.Num());
		Result->SetBoolField(TEXT("captured_truncated"), bTruncated);
	}

	return CreateSuccessResponse(Result);
}

// ============================================================================
// FDescribeFullAction — Single-call comprehensive Blueprint snapshot
// ============================================================================

bool FDescribeFullAction::Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError)
{
	if (!Params->HasField(TEXT("blueprint_name")) && !Params->HasField(TEXT("asset_path")))
	{
		OutError = TEXT("Either 'blueprint_name' or 'asset_path' is required");
		return false;
	}
	return true;
}

TSharedPtr<FJsonObject> FDescribeFullAction::SerializePinCompact(const UEdGraphPin* Pin)
{
	if (!Pin || Pin->bHidden)
	{
		return nullptr;
	}

	TSharedPtr<FJsonObject> PinObj = MakeShared<FJsonObject>();
	PinObj->SetStringField(TEXT("pin_name"), Pin->PinName.ToString());
	PinObj->SetStringField(TEXT("direction"), Pin->Direction == EGPD_Input ? TEXT("input") : TEXT("output"));
	PinObj->SetStringField(TEXT("category"), Pin->PinType.PinCategory.ToString());

	if (Pin->PinType.PinSubCategoryObject.IsValid())
	{
		PinObj->SetStringField(TEXT("sub_type"), Pin->PinType.PinSubCategoryObject->GetName());
	}

	if (Pin->LinkedTo.Num() > 0)
	{
		TArray<TSharedPtr<FJsonValue>> LinkedArray;
		for (const UEdGraphPin* LinkedPin : Pin->LinkedTo)
		{
			if (!LinkedPin || !LinkedPin->GetOwningNode()) continue;
			TSharedPtr<FJsonObject> LinkedObj = MakeShared<FJsonObject>();
			LinkedObj->SetStringField(TEXT("node_id"), LinkedPin->GetOwningNode()->NodeGuid.ToString());
			LinkedObj->SetStringField(TEXT("pin_name"), LinkedPin->PinName.ToString());
			LinkedArray.Add(MakeShared<FJsonValueObject>(LinkedObj));
		}
		PinObj->SetArrayField(TEXT("linked_to"), LinkedArray);
	}

	if (!Pin->DefaultValue.IsEmpty())
	{
		PinObj->SetStringField(TEXT("default_value"), Pin->DefaultValue);
	}
	else if (!Pin->AutogeneratedDefaultValue.IsEmpty())
	{
		PinObj->SetStringField(TEXT("default_value"), Pin->AutogeneratedDefaultValue);
	}
	if (Pin->DefaultObject)
	{
		PinObj->SetStringField(TEXT("default_object"), Pin->DefaultObject->GetPathName());
	}

	return PinObj;
}

TSharedPtr<FJsonObject> FDescribeFullAction::SerializeGraph(UBlueprint* Blueprint, UEdGraph* Graph,
	bool bIncludePinDetails, bool bIncludeFunctionSignatures) const
{
	if (!Graph) return nullptr;

	TSharedPtr<FJsonObject> GraphObj = MakeShared<FJsonObject>();
	GraphObj->SetStringField(TEXT("name"), Graph->GetName());
	GraphObj->SetNumberField(TEXT("node_count"), Graph->Nodes.Num());

	TArray<TSharedPtr<FJsonValue>> NodesArray;
	TArray<TSharedPtr<FJsonValue>> EdgesArray;
	TSet<FString> SeenEdges;

	for (const UEdGraphNode* Node : Graph->Nodes)
	{
		if (!Node) continue;

		TSharedPtr<FJsonObject> NodeObj = MakeShared<FJsonObject>();
		NodeObj->SetStringField(TEXT("node_id"), Node->NodeGuid.ToString());
		NodeObj->SetStringField(TEXT("node_class"), Node->GetClass()->GetName());
		NodeObj->SetStringField(TEXT("node_title"), Node->GetNodeTitle(ENodeTitleType::FullTitle).ToString());
		NodeObj->SetNumberField(TEXT("pos_x"), Node->NodePosX);
		NodeObj->SetNumberField(TEXT("pos_y"), Node->NodePosY);

		if (!Node->NodeComment.IsEmpty())
		{
			NodeObj->SetStringField(TEXT("comment"), Node->NodeComment);
		}

		// Function signature (optional, for function call nodes)
		if (bIncludeFunctionSignatures)
		{
			if (const UK2Node_CallFunction* FuncNode = Cast<UK2Node_CallFunction>(Node))
			{
				if (const UFunction* Function = FuncNode->GetTargetFunction())
				{
					TSharedPtr<FJsonObject> SigObj = MakeShared<FJsonObject>();
					SigObj->SetStringField(TEXT("function_name"), Function->GetName());
					SigObj->SetStringField(TEXT("owner_class"),
						Function->GetOwnerClass() ? Function->GetOwnerClass()->GetName() : TEXT("Unknown"));
					SigObj->SetBoolField(TEXT("is_static"), Function->HasAnyFunctionFlags(FUNC_Static));
					SigObj->SetBoolField(TEXT("is_pure"), Function->HasAnyFunctionFlags(FUNC_BlueprintPure));
					NodeObj->SetObjectField(TEXT("function_signature"), SigObj);
				}
			}
		}

		// Pins — compact mode by default
		TArray<TSharedPtr<FJsonValue>> PinsArray;
		for (const UEdGraphPin* Pin : Node->Pins)
		{
			if (!Pin || Pin->bHidden) continue;

			TSharedPtr<FJsonObject> PinObj = SerializePinCompact(Pin);
			if (PinObj.IsValid())
			{
				// Add full PinType details only if requested
				if (bIncludePinDetails)
				{
					TSharedPtr<FJsonObject> PinTypeObj = MakeShared<FJsonObject>();
					PinTypeObj->SetStringField(TEXT("category"), Pin->PinType.PinCategory.ToString());
					if (Pin->PinType.PinSubCategory != NAME_None)
						PinTypeObj->SetStringField(TEXT("sub_category"), Pin->PinType.PinSubCategory.ToString());
					if (Pin->PinType.PinSubCategoryObject.Get())
						PinTypeObj->SetStringField(TEXT("sub_category_object"), Pin->PinType.PinSubCategoryObject->GetPathName());
					PinTypeObj->SetBoolField(TEXT("is_array"), Pin->PinType.IsArray());
					PinTypeObj->SetBoolField(TEXT("is_reference"), Pin->PinType.bIsReference);
					PinObj->SetObjectField(TEXT("pin_type"), PinTypeObj);
				}
				PinsArray.Add(MakeShared<FJsonValueObject>(PinObj));
			}

			// Collect edges (output pins only, deduplicated)
			if (Pin->Direction == EGPD_Output)
			{
				for (const UEdGraphPin* LinkedPin : Pin->LinkedTo)
				{
					if (!LinkedPin || !LinkedPin->GetOwningNode()) continue;
					FString EdgeKey = FString::Printf(TEXT("%s:%s->%s:%s"),
						*Node->NodeGuid.ToString(), *Pin->PinName.ToString(),
						*LinkedPin->GetOwningNode()->NodeGuid.ToString(), *LinkedPin->PinName.ToString());
					if (!SeenEdges.Contains(EdgeKey))
					{
						SeenEdges.Add(EdgeKey);
						TSharedPtr<FJsonObject> EdgeObj = MakeShared<FJsonObject>();
						EdgeObj->SetStringField(TEXT("from_node"), Node->NodeGuid.ToString());
						EdgeObj->SetStringField(TEXT("from_pin"), Pin->PinName.ToString());
						EdgeObj->SetStringField(TEXT("to_node"), LinkedPin->GetOwningNode()->NodeGuid.ToString());
						EdgeObj->SetStringField(TEXT("to_pin"), LinkedPin->PinName.ToString());
						EdgesArray.Add(MakeShared<FJsonValueObject>(EdgeObj));
					}
				}
			}
		}
		NodeObj->SetArrayField(TEXT("pins"), PinsArray);
		NodesArray.Add(MakeShared<FJsonValueObject>(NodeObj));
	}

	GraphObj->SetArrayField(TEXT("nodes"), NodesArray);
	GraphObj->SetNumberField(TEXT("edge_count"), EdgesArray.Num());
	GraphObj->SetArrayField(TEXT("edges"), EdgesArray);

	return GraphObj;
}

TSharedPtr<FJsonObject> FDescribeFullAction::ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context)
{
	UBlueprint* Blueprint = nullptr;

	if (Params->HasField(TEXT("asset_path")))
	{
		FString AssetPath = Params->GetStringField(TEXT("asset_path"));
		if (AssetPath == TEXT("__LEVEL_BLUEPRINT__"))
		{
			Blueprint =
				Context.GetBlueprintByNameOrCurrent(
					TEXT("__LEVEL_BLUEPRINT__"));
		}
		else
		{
			Blueprint = Cast<UBlueprint>(
				StaticLoadObject(
					UBlueprint::StaticClass(),
					nullptr,
					*AssetPath));
		}
	}
	if (!Blueprint && Params->HasField(TEXT("blueprint_name")))
	{
		FString BlueprintName = Params->GetStringField(TEXT("blueprint_name"));
		Blueprint =
			BlueprintName == TEXT("__LEVEL_BLUEPRINT__")
				? Context.GetBlueprintByNameOrCurrent(BlueprintName)
				: FMCPCommonUtils::FindBlueprint(BlueprintName);
	}
	if (!Blueprint)
	{
		return CreateErrorResponse(TEXT("Blueprint not found"));
	}

	const bool bIncludePinDetails = GetOptionalBool(Params, TEXT("include_pin_details"), false);
	const bool bIncludeFunctionSignatures = GetOptionalBool(Params, TEXT("include_function_signatures"), false);

	TSharedPtr<FJsonObject> Result = MakeShared<FJsonObject>();

	// ---- Basic Info ----
	Result->SetStringField(TEXT("blueprint_name"), Blueprint->GetName());
	Result->SetStringField(TEXT("blueprint_path"), Blueprint->GetPathName());

	if (Blueprint->ParentClass)
	{
		Result->SetStringField(TEXT("parent_class"), Blueprint->ParentClass->GetName());
		Result->SetStringField(TEXT("parent_class_path"), Blueprint->ParentClass->GetPathName());
	}

	FString TypeStr;
	switch (Blueprint->BlueprintType)
	{
		case BPTYPE_Normal: TypeStr = TEXT("Normal"); break;
		case BPTYPE_Const: TypeStr = TEXT("Const"); break;
		case BPTYPE_MacroLibrary: TypeStr = TEXT("MacroLibrary"); break;
		case BPTYPE_Interface: TypeStr = TEXT("Interface"); break;
		case BPTYPE_LevelScript: TypeStr = TEXT("LevelScript"); break;
		case BPTYPE_FunctionLibrary: TypeStr = TEXT("FunctionLibrary"); break;
		default: TypeStr = TEXT("Unknown"); break;
	}
	Result->SetStringField(TEXT("blueprint_type"), TypeStr);

	FString CompileStatus;
	switch (Blueprint->Status)
	{
		case BS_UpToDate: CompileStatus = TEXT("UpToDate"); break;
		case BS_Dirty: CompileStatus = TEXT("Dirty"); break;
		case BS_Error: CompileStatus = TEXT("Error"); break;
		case BS_BeingCreated: CompileStatus = TEXT("BeingCreated"); break;
		default: CompileStatus = TEXT("Unknown"); break;
	}
	Result->SetStringField(TEXT("compile_status"), CompileStatus);

	// ---- Variables ----
	TArray<TSharedPtr<FJsonValue>> VarsArray;
	for (const FBPVariableDescription& VarDesc : Blueprint->NewVariables)
	{
		TSharedPtr<FJsonObject> VarObj = MakeShared<FJsonObject>();
		VarObj->SetStringField(TEXT("name"), VarDesc.VarName.ToString());
		VarObj->SetStringField(TEXT("type"), VarDesc.VarType.PinCategory.ToString());
		if (VarDesc.VarType.PinSubCategoryObject.IsValid())
			VarObj->SetStringField(TEXT("sub_type"), VarDesc.VarType.PinSubCategoryObject->GetName());
		if (VarDesc.VarType.IsArray())
			VarObj->SetStringField(TEXT("container"), TEXT("Array"));
		VarObj->SetBoolField(TEXT("is_instance_editable"), (VarDesc.PropertyFlags & CPF_Edit) != 0);
		if (!VarDesc.DefaultValue.IsEmpty())
			VarObj->SetStringField(TEXT("default_value"), VarDesc.DefaultValue);
		VarsArray.Add(MakeShared<FJsonValueObject>(VarObj));
	}
	Result->SetArrayField(TEXT("variables"), VarsArray);

	// ---- Components (SCS) ----
	TArray<TSharedPtr<FJsonValue>> ComponentsArray;
	if (Blueprint->SimpleConstructionScript)
	{
		TArray<USCS_Node*> AllNodes = Blueprint->SimpleConstructionScript->GetAllNodes();
		for (USCS_Node* SCSNode : AllNodes)
		{
			if (!SCSNode) continue;
			TSharedPtr<FJsonObject> CompObj = MakeShared<FJsonObject>();
			CompObj->SetStringField(TEXT("name"), SCSNode->GetVariableName().ToString());
			if (SCSNode->ComponentClass)
				CompObj->SetStringField(TEXT("class"), SCSNode->ComponentClass->GetName());
			if (!SCSNode->ParentComponentOrVariableName.IsNone())
				CompObj->SetStringField(TEXT("parent"), SCSNode->ParentComponentOrVariableName.ToString());
			ComponentsArray.Add(MakeShared<FJsonValueObject>(CompObj));
		}
	}
	Result->SetArrayField(TEXT("components"), ComponentsArray);

	// ---- Interfaces ----
	TArray<TSharedPtr<FJsonValue>> InterfacesArray;
	for (const FBPInterfaceDescription& InterfaceDesc : Blueprint->ImplementedInterfaces)
	{
		if (InterfaceDesc.Interface)
			InterfacesArray.Add(MakeShared<FJsonValueString>(InterfaceDesc.Interface->GetName()));
	}
	Result->SetArrayField(TEXT("implemented_interfaces"), InterfacesArray);

	// ---- All Graph Topologies ----
	TArray<TSharedPtr<FJsonValue>> AllGraphs;

	// Event Graphs (UbergraphPages)
	for (UEdGraph* Graph : Blueprint->UbergraphPages)
	{
		TSharedPtr<FJsonObject> GraphObj = SerializeGraph(Blueprint, Graph, bIncludePinDetails, bIncludeFunctionSignatures);
		if (GraphObj.IsValid())
		{
			GraphObj->SetStringField(TEXT("graph_type"), TEXT("EventGraph"));
			AllGraphs.Add(MakeShared<FJsonValueObject>(GraphObj));
		}
	}

	// Function Graphs
	for (UEdGraph* Graph : Blueprint->FunctionGraphs)
	{
		TSharedPtr<FJsonObject> GraphObj = SerializeGraph(Blueprint, Graph, bIncludePinDetails, bIncludeFunctionSignatures);
		if (GraphObj.IsValid())
		{
			GraphObj->SetStringField(TEXT("graph_type"), TEXT("Function"));
			AllGraphs.Add(MakeShared<FJsonValueObject>(GraphObj));
		}
	}

	// Macro Graphs
	for (UEdGraph* Graph : Blueprint->MacroGraphs)
	{
		TSharedPtr<FJsonObject> GraphObj = SerializeGraph(Blueprint, Graph, bIncludePinDetails, bIncludeFunctionSignatures);
		if (GraphObj.IsValid())
		{
			GraphObj->SetStringField(TEXT("graph_type"), TEXT("Macro"));
			AllGraphs.Add(MakeShared<FJsonValueObject>(GraphObj));
		}
	}

	Result->SetArrayField(TEXT("graphs"), AllGraphs);

	// Summary counts
	int32 TotalNodes = 0;
	int32 TotalEdges = 0;
	for (const auto& GraphVal : AllGraphs)
	{
		const TSharedPtr<FJsonObject>* GraphObjPtr;
		if (GraphVal->TryGetObject(GraphObjPtr) && GraphObjPtr)
		{
			TotalNodes += static_cast<int32>((*GraphObjPtr)->GetNumberField(TEXT("node_count")));
			TotalEdges += static_cast<int32>((*GraphObjPtr)->GetNumberField(TEXT("edge_count")));
		}
	}
	Result->SetNumberField(TEXT("total_graphs"), AllGraphs.Num());
	Result->SetNumberField(TEXT("total_nodes"), TotalNodes);
	Result->SetNumberField(TEXT("total_edges"), TotalEdges);

	return CreateSuccessResponse(Result);
}


// =========================================================================
// P6: PIE Control Actions
// =========================================================================

// ---- P6.1 FStartPIEAction ----

bool FStartPIEAction::Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError)
{
	if (!GEditor)
	{
		OutError = TEXT("GEditor is not available");
		return false;
	}
	if (GEditor->PlayWorld)
	{
		OutError = TEXT("A PIE session is already running. Stop it first with editor.stop_pie.");
		return false;
	}
	return true;
}

TSharedPtr<FJsonObject> FStartPIEAction::ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context)
{
	FString ModeStr      = GetOptionalString(Params, TEXT("mode"), TEXT("SelectedViewport"));
	FString NetModeStr   = GetOptionalString(Params, TEXT("net_mode"), TEXT("Standalone"));
	int32   PlayerCount  = (int32)GetOptionalNumber(Params, TEXT("player_count"), 1);
	FString StartingMap  = GetOptionalString(Params, TEXT("starting_map"), TEXT(""));

	if (PlayerCount < 1) { PlayerCount = 1; }
	if (PlayerCount > 4) { PlayerCount = 4; }

	FRequestPlaySessionParams SessionParams;
	SessionParams.SessionDestination = EPlaySessionDestinationType::InProcess;

	if (ModeStr.Equals(TEXT("Simulate"), ESearchCase::IgnoreCase))
	{
		SessionParams.WorldType = EPlaySessionWorldType::SimulateInEditor;
	}
	else
	{
		SessionParams.WorldType = EPlaySessionWorldType::PlayInEditor;
	}

	// 配置 PIE 启动模式
	ULevelEditorPlaySettings* PlaySettings = GetMutableDefault<ULevelEditorPlaySettings>();
	if (PlaySettings)
	{
		if (ModeStr.Equals(TEXT("NewWindow"), ESearchCase::IgnoreCase))
		{
			PlaySettings->LastExecutedPlayModeType = PlayMode_InEditorFloating;
		}
		else if (ModeStr.Equals(TEXT("Simulate"), ESearchCase::IgnoreCase))
		{
			PlaySettings->LastExecutedPlayModeType = PlayMode_Simulate;
		}
		else // SelectedViewport (default)
		{
			PlaySettings->LastExecutedPlayModeType = PlayMode_InViewPort;
		}

		// 配置网络模式与多客户端
		EPlayNetMode NetMode = EPlayNetMode::PIE_Standalone;
		if (NetModeStr.Equals(TEXT("ListenServer"), ESearchCase::IgnoreCase))
		{
			NetMode = EPlayNetMode::PIE_ListenServer;
		}
		else if (NetModeStr.Equals(TEXT("Client"), ESearchCase::IgnoreCase))
		{
			NetMode = EPlayNetMode::PIE_Client;
		}
		else if (NetModeStr.Equals(TEXT("DedicatedServer"), ESearchCase::IgnoreCase) ||
		         NetModeStr.Equals(TEXT("Dedicated"),       ESearchCase::IgnoreCase))
		{
			// 注意：UE 中没有 PIE_DedicatedServer 枚举，专用服务器通过 bLaunchSeparateServer 实现
			NetMode = EPlayNetMode::PIE_Client;
			PlaySettings->bLaunchSeparateServer = true;
		}
		else
		{
			PlaySettings->bLaunchSeparateServer = false;
		}

		PlaySettings->SetPlayNetMode(NetMode);
		PlaySettings->SetPlayNumberOfClients(PlayerCount);

		// 可选：在新窗口模式下使用合适的客户端窗口尺寸（默认 1280x720）
		if (ModeStr.Equals(TEXT("NewWindow"), ESearchCase::IgnoreCase))
		{
			PlaySettings->NewWindowWidth  = 1280;
			PlaySettings->NewWindowHeight = 720;
		}
	}

	// 可选：在启动 PIE 之前先切换关卡
	if (!StartingMap.IsEmpty())
	{
		const FString ResolvedMap = FPackageName::ObjectPathToPackageName(StartingMap);
		if (!FEditorFileUtils::LoadMap(ResolvedMap.IsEmpty() ? StartingMap : ResolvedMap, /*LoadAsTemplate*/ false, /*bShowProgress*/ true))
		{
			UE_LOG(LogMCP, Warning, TEXT("PIE: failed to load starting_map=%s, will use current editor map"), *StartingMap);
		}
	}

	GEditor->RequestPlaySession(SessionParams);

	TSharedPtr<FJsonObject> Result = MakeShared<FJsonObject>();
	Result->SetStringField(TEXT("mode"), ModeStr);
	Result->SetStringField(TEXT("net_mode"), NetModeStr);
	Result->SetNumberField(TEXT("player_count"), PlayerCount);
	if (!StartingMap.IsEmpty())
	{
		Result->SetStringField(TEXT("starting_map"), StartingMap);
	}
	Result->SetStringField(TEXT("message"), TEXT("PIE session requested"));
	Result->SetBoolField(TEXT("is_async"), true);

	UE_LOG(LogMCP, Log, TEXT("PIE start requested (mode=%s, net_mode=%s, player_count=%d, map=%s)"),
		*ModeStr, *NetModeStr, PlayerCount, *StartingMap);

	return CreateSuccessResponse(Result);
}

// ---- P6.2 FStopPIEAction ----

TSharedPtr<FJsonObject> FStopPIEAction::ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context)
{
	TSharedPtr<FJsonObject> Result = MakeShared<FJsonObject>();

	if (!GEditor || !GEditor->PlayWorld)
	{
		Result->SetStringField(TEXT("state"), TEXT("already_stopped"));
		Result->SetStringField(TEXT("message"), TEXT("No PIE session is currently running"));
		return CreateSuccessResponse(Result);
	}

	GEditor->RequestEndPlayMap();

	Result->SetStringField(TEXT("state"), TEXT("stop_requested"));
	Result->SetStringField(TEXT("message"), TEXT("PIE stop requested"));

	UE_LOG(LogMCP, Log, TEXT("PIE stop requested"));

	return CreateSuccessResponse(Result);
}

// ---- P6.3 FGetPIEStateAction ----

TSharedPtr<FJsonObject> FGetPIEStateAction::ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context)
{
	TSharedPtr<FJsonObject> Result = MakeShared<FJsonObject>();

	if (!GEditor)
	{
		Result->SetStringField(TEXT("state"), TEXT("Stopped"));
		return CreateSuccessResponse(Result);
	}

	if (GEditor->PlayWorld)
	{
		Result->SetStringField(TEXT("state"), TEXT("Running"));
		Result->SetStringField(TEXT("world_name"), GEditor->PlayWorld->GetName());
		Result->SetBoolField(TEXT("is_paused"), GEditor->PlayWorld->IsPaused());
		Result->SetBoolField(TEXT("is_simulating"), GEditor->IsSimulateInEditorInProgress());

		// Duration: use engine uptime difference (best available method)
		double CurrentTime = FPlatformTime::Seconds();
		Result->SetNumberField(TEXT("engine_time"), CurrentTime);

		// Check if a request to end is already queued
		Result->SetBoolField(TEXT("is_play_session_in_progress"), GEditor->IsPlaySessionInProgress());
	}
	else
	{
		Result->SetStringField(TEXT("state"), TEXT("Stopped"));
		Result->SetBoolField(TEXT("is_play_session_in_progress"), GEditor->IsPlaySessionInProgress());
	}

	return CreateSuccessResponse(Result);
}


// =========================================================================
// P6: Log Enhancement Actions
// =========================================================================

#include "MCPLogCapture.h"

// ---- P6.4 FClearLogsAction ----

TSharedPtr<FJsonObject> FClearLogsAction::ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context)
{
	FMCPLogCapture& LogCapture = FMCPLogCapture::Get();

	// Get pre-clear stats
	int64 PrevCount = LogCapture.GetTotalCaptured();
	uint64 PrevSeq = LogCapture.GetLatestSeq();

	// Optionally insert a session tag before clearing
	FString Tag = GetOptionalString(Params, TEXT("tag"), TEXT(""));
	if (!Tag.IsEmpty())
	{
		UE_LOG(LogMCP, Log, TEXT("[SESSION] %s"), *Tag);
	}

	// Clear the ring buffer
	LogCapture.Clear();

	TSharedPtr<FJsonObject> Result = MakeShared<FJsonObject>();
	Result->SetNumberField(TEXT("cleared_total_captured"), static_cast<double>(PrevCount));
	Result->SetStringField(TEXT("previous_cursor"), FString::Printf(TEXT("live:%llu"), PrevSeq));
	Result->SetStringField(TEXT("new_cursor"), FString::Printf(TEXT("live:%llu"), LogCapture.GetLatestSeq()));
	if (!Tag.IsEmpty())
	{
		Result->SetStringField(TEXT("session_tag"), Tag);
	}
	Result->SetStringField(TEXT("message"), TEXT("Log buffer cleared"));

	UE_LOG(LogMCP, Log, TEXT("Log buffer cleared (prev total=%lld, prev seq=%llu)"), PrevCount, PrevSeq);

	return CreateSuccessResponse(Result);
}

// ---- P6.5 FAssertLogAction ----

bool FAssertLogAction::Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError)
{
	const TArray<TSharedPtr<FJsonValue>>* Assertions = GetOptionalArray(Params, TEXT("assertions"));
	if (!Assertions || Assertions->Num() == 0)
	{
		OutError = TEXT("'assertions' array is required and must not be empty");
		return false;
	}
	return true;
}

TSharedPtr<FJsonObject> FAssertLogAction::ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context)
{
	FMCPLogCapture& LogCapture = FMCPLogCapture::Get();

	// Parse optional cursor
	FString SinceCursor = GetOptionalString(Params, TEXT("since_cursor"), TEXT(""));
	uint64 AfterSeq = 0;
	if (SinceCursor.StartsWith(TEXT("live:")))
	{
		FString SeqStr = SinceCursor.Mid(5);
		AfterSeq = FCString::Strtoui64(*SeqStr, nullptr, 10);
	}

	// Gather log entries
	bool bTruncated = false;
	uint64 LastSeq = 0;
	TArray<FString> EmptyCategories;
	TArray<FMCPLogCapture::FLogEntry> LogEntries = LogCapture.GetSince(
		AfterSeq, 10000, 5 * 1024 * 1024,
		EmptyCategories, ELogVerbosity::All, TEXT(""),
		bTruncated, LastSeq);

	// Parse assertions and check
	const TArray<TSharedPtr<FJsonValue>>* Assertions = GetOptionalArray(Params, TEXT("assertions"));
	TArray<TSharedPtr<FJsonValue>> ResultsArray;
	int32 PassedCount = 0;
	int32 FailedCount = 0;

	for (const TSharedPtr<FJsonValue>& AssertVal : *Assertions)
	{
		const TSharedPtr<FJsonObject>* AssertObjPtr;
		if (!AssertVal->TryGetObject(AssertObjPtr) || !AssertObjPtr)
		{
			continue;
		}

		const TSharedPtr<FJsonObject>& AssertObj = *AssertObjPtr;
		FString Keyword;
		if (!AssertObj->TryGetStringField(TEXT("keyword"), Keyword) || Keyword.IsEmpty())
		{
			continue;
		}

		int32 ExpectedCount = static_cast<int32>(AssertObj->GetNumberField(TEXT("expected_count")));
		FString Comparison = TEXT(">=");
		AssertObj->TryGetStringField(TEXT("comparison"), Comparison);
		FString CategoryFilter;
		AssertObj->TryGetStringField(TEXT("category"), CategoryFilter);

		// Count keyword occurrences
		int32 ActualCount = 0;
		for (const FMCPLogCapture::FLogEntry& Entry : LogEntries)
		{
			// Optional category filter
			if (!CategoryFilter.IsEmpty() && !Entry.Category.ToString().Contains(CategoryFilter))
			{
				continue;
			}
			if (Entry.Message.Contains(Keyword))
			{
				ActualCount++;
			}
		}

		// Evaluate comparison
		bool bPassed = false;
		if (Comparison == TEXT("=="))
		{
			bPassed = (ActualCount == ExpectedCount);
		}
		else if (Comparison == TEXT(">="))
		{
			bPassed = (ActualCount >= ExpectedCount);
		}
		else if (Comparison == TEXT("<="))
		{
			bPassed = (ActualCount <= ExpectedCount);
		}
		else if (Comparison == TEXT(">"))
		{
			bPassed = (ActualCount > ExpectedCount);
		}
		else if (Comparison == TEXT("<"))
		{
			bPassed = (ActualCount < ExpectedCount);
		}

		if (bPassed)
		{
			PassedCount++;
		}
		else
		{
			FailedCount++;
		}

		TSharedPtr<FJsonObject> AssertResult = MakeShared<FJsonObject>();
		AssertResult->SetStringField(TEXT("keyword"), Keyword);
		AssertResult->SetNumberField(TEXT("expected"), ExpectedCount);
		AssertResult->SetNumberField(TEXT("actual"), ActualCount);
		AssertResult->SetStringField(TEXT("comparison"), Comparison);
		AssertResult->SetBoolField(TEXT("passed"), bPassed);
		ResultsArray.Add(MakeShared<FJsonValueObject>(AssertResult));
	}

	TSharedPtr<FJsonObject> Result = MakeShared<FJsonObject>();
	Result->SetStringField(TEXT("overall"), FailedCount == 0 ? TEXT("pass") : TEXT("fail"));
	Result->SetNumberField(TEXT("total_assertions"), ResultsArray.Num());
	Result->SetNumberField(TEXT("passed"), PassedCount);
	Result->SetNumberField(TEXT("failed"), FailedCount);
	Result->SetArrayField(TEXT("results"), ResultsArray);

	TSharedPtr<FJsonObject> LogRange = MakeShared<FJsonObject>();
	LogRange->SetNumberField(TEXT("from_seq"), static_cast<double>(AfterSeq));
	LogRange->SetNumberField(TEXT("to_seq"), static_cast<double>(LastSeq));
	LogRange->SetNumberField(TEXT("lines_scanned"), LogEntries.Num());
	Result->SetObjectField(TEXT("log_range"), LogRange);

	return CreateSuccessResponse(Result);
}


// =========================================================================
// P6: Outliner Management Actions
// =========================================================================

// ---- Shared helper: find actor by name or label ----

static AActor* FindActorInWorld(UWorld* World, const FString& ActorName)
{
	if (!World)
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

		// Match by name (GetName)
		if (Actor->GetName().Equals(ActorName, ESearchCase::IgnoreCase))
		{
			return Actor;
		}

		// Match by label (display name in Outliner)
		if (Actor->GetActorLabel().Equals(ActorName, ESearchCase::IgnoreCase))
		{
			return Actor;
		}
	}

	return nullptr;
}

// ---- P6.6 FRenameActorLabelAction ----

bool FRenameActorLabelAction::Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError)
{
	// Need either (actor_name + new_label) or items[]
	const TArray<TSharedPtr<FJsonValue>>* Items = GetOptionalArray(Params, TEXT("items"));
	if (Items && Items->Num() > 0)
	{
		return true;
	}

	FString ActorName = GetOptionalString(Params, TEXT("actor_name"));
	FString NewLabel = GetOptionalString(Params, TEXT("new_label"));
	if (ActorName.IsEmpty() || NewLabel.IsEmpty())
	{
		OutError = TEXT("Either 'items' array or both 'actor_name' and 'new_label' are required");
		return false;
	}
	return true;
}

AActor* FRenameActorLabelAction::FindActorByName(UWorld* World, const FString& ActorName) const
{
	return FindActorInWorld(World, ActorName);
}

TSharedPtr<FJsonObject> FRenameActorLabelAction::ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context)
{
	UWorld* World = GEditor ? GEditor->GetEditorWorldContext().World() : nullptr;
	if (!World)
	{
		return CreateErrorResponse(TEXT("No editor world available"));
	}

	struct FRenameItem
	{
		FString ActorName;
		FString NewLabel;
	};

	TArray<FRenameItem> ItemsList;
	const TArray<TSharedPtr<FJsonValue>>* Items = GetOptionalArray(Params, TEXT("items"));
	if (Items && Items->Num() > 0)
	{
		for (const TSharedPtr<FJsonValue>& ItemVal : *Items)
		{
			const TSharedPtr<FJsonObject>* ItemObjPtr;
			if (ItemVal->TryGetObject(ItemObjPtr) && ItemObjPtr)
			{
				FRenameItem Item;
				(*ItemObjPtr)->TryGetStringField(TEXT("actor_name"), Item.ActorName);
				(*ItemObjPtr)->TryGetStringField(TEXT("new_label"), Item.NewLabel);
				if (!Item.ActorName.IsEmpty() && !Item.NewLabel.IsEmpty())
				{
					ItemsList.Add(MoveTemp(Item));
				}
			}
		}
	}
	else
	{
		FRenameItem Item;
		Item.ActorName = GetOptionalString(Params, TEXT("actor_name"));
		Item.NewLabel = GetOptionalString(Params, TEXT("new_label"));
		ItemsList.Add(MoveTemp(Item));
	}

	FScopedTransaction Transaction(FText::FromString(TEXT("MCP Rename Actor Labels")));

	TArray<TSharedPtr<FJsonValue>> ResultsArray;
	int32 SuccessCount = 0;

	for (const FRenameItem& Item : ItemsList)
	{
		TSharedPtr<FJsonObject> ItemResult = MakeShared<FJsonObject>();
		ItemResult->SetStringField(TEXT("actor_name"), Item.ActorName);

		AActor* Actor = FindActorByName(World, Item.ActorName);
		if (!Actor)
		{
			ItemResult->SetBoolField(TEXT("success"), false);
			ItemResult->SetStringField(TEXT("error"), FString::Printf(TEXT("Actor '%s' not found"), *Item.ActorName));
		}
		else
		{
			FString OldLabel = Actor->GetActorLabel();
			Actor->SetActorLabel(Item.NewLabel);
			ItemResult->SetBoolField(TEXT("success"), true);
			ItemResult->SetStringField(TEXT("old_label"), OldLabel);
			ItemResult->SetStringField(TEXT("new_label"), Item.NewLabel);
			SuccessCount++;
		}

		ResultsArray.Add(MakeShared<FJsonValueObject>(ItemResult));
	}

	TSharedPtr<FJsonObject> Result = MakeShared<FJsonObject>();
	Result->SetNumberField(TEXT("total"), ItemsList.Num());
	Result->SetNumberField(TEXT("succeeded"), SuccessCount);
	Result->SetArrayField(TEXT("results"), ResultsArray);

	return CreateSuccessResponse(Result);
}

// ---- P6.7 FSetActorFolderAction ----

bool FSetActorFolderAction::Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError)
{
	const TArray<TSharedPtr<FJsonValue>>* Items = GetOptionalArray(Params, TEXT("items"));
	if (Items && Items->Num() > 0)
	{
		return true;
	}

	FString ActorName = GetOptionalString(Params, TEXT("actor_name"));
	FString FolderPath = GetOptionalString(Params, TEXT("folder_path"));
	if (ActorName.IsEmpty())
	{
		OutError = TEXT("Either 'items' array or 'actor_name' is required");
		return false;
	}
	return true;
}

AActor* FSetActorFolderAction::FindActorByName(UWorld* World, const FString& ActorName) const
{
	return FindActorInWorld(World, ActorName);
}

TSharedPtr<FJsonObject> FSetActorFolderAction::ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context)
{
	UWorld* World = GEditor ? GEditor->GetEditorWorldContext().World() : nullptr;
	if (!World)
	{
		return CreateErrorResponse(TEXT("No editor world available"));
	}

	struct FFolderItem
	{
		FString ActorName;
		FString FolderPath;
	};

	TArray<FFolderItem> ItemsList;
	const TArray<TSharedPtr<FJsonValue>>* Items = GetOptionalArray(Params, TEXT("items"));
	if (Items && Items->Num() > 0)
	{
		for (const TSharedPtr<FJsonValue>& ItemVal : *Items)
		{
			const TSharedPtr<FJsonObject>* ItemObjPtr;
			if (ItemVal->TryGetObject(ItemObjPtr) && ItemObjPtr)
			{
				FFolderItem Item;
				(*ItemObjPtr)->TryGetStringField(TEXT("actor_name"), Item.ActorName);
				(*ItemObjPtr)->TryGetStringField(TEXT("folder_path"), Item.FolderPath);
				if (!Item.ActorName.IsEmpty())
				{
					ItemsList.Add(MoveTemp(Item));
				}
			}
		}
	}
	else
	{
		FFolderItem Item;
		Item.ActorName = GetOptionalString(Params, TEXT("actor_name"));
		Item.FolderPath = GetOptionalString(Params, TEXT("folder_path"));
		ItemsList.Add(MoveTemp(Item));
	}

	FScopedTransaction Transaction(FText::FromString(TEXT("MCP Set Actor Folders")));

	TArray<TSharedPtr<FJsonValue>> ResultsArray;
	int32 SuccessCount = 0;

	for (const FFolderItem& Item : ItemsList)
	{
		TSharedPtr<FJsonObject> ItemResult = MakeShared<FJsonObject>();
		ItemResult->SetStringField(TEXT("actor_name"), Item.ActorName);

		AActor* Actor = FindActorByName(World, Item.ActorName);
		if (!Actor)
		{
			ItemResult->SetBoolField(TEXT("success"), false);
			ItemResult->SetStringField(TEXT("error"), FString::Printf(TEXT("Actor '%s' not found"), *Item.ActorName));
		}
		else
		{
			FString OldFolder = Actor->GetFolderPath().ToString();
			Actor->SetFolderPath(FName(*Item.FolderPath));
			ItemResult->SetBoolField(TEXT("success"), true);
			ItemResult->SetStringField(TEXT("old_folder"), OldFolder);
			ItemResult->SetStringField(TEXT("new_folder"), Item.FolderPath);
			SuccessCount++;
		}

		ResultsArray.Add(MakeShared<FJsonValueObject>(ItemResult));
	}

	TSharedPtr<FJsonObject> Result = MakeShared<FJsonObject>();
	Result->SetNumberField(TEXT("total"), ItemsList.Num());
	Result->SetNumberField(TEXT("succeeded"), SuccessCount);
	Result->SetArrayField(TEXT("results"), ResultsArray);

	return CreateSuccessResponse(Result);
}

// ---- P6.8 FSelectActorsAction ----

bool FSelectActorsAction::Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError)
{
	const TArray<TSharedPtr<FJsonValue>>* ActorNames = GetOptionalArray(Params, TEXT("actor_names"));
	if (!ActorNames || ActorNames->Num() == 0)
	{
		OutError = TEXT("'actor_names' array is required and must not be empty");
		return false;
	}
	return true;
}

AActor* FSelectActorsAction::FindActorByName(UWorld* World, const FString& ActorName) const
{
	return FindActorInWorld(World, ActorName);
}

TSharedPtr<FJsonObject> FSelectActorsAction::ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context)
{
	UWorld* World = GEditor ? GEditor->GetEditorWorldContext().World() : nullptr;
	if (!World)
	{
		return CreateErrorResponse(TEXT("No editor world available"));
	}

	FString Mode = GetOptionalString(Params, TEXT("mode"), TEXT("set"));
	const TArray<TSharedPtr<FJsonValue>>* ActorNames = GetOptionalArray(Params, TEXT("actor_names"));

	// If mode is "set", deselect all first
	if (Mode.Equals(TEXT("set"), ESearchCase::IgnoreCase))
	{
		GEditor->SelectNone(/*bNoteSelectionChange=*/false, /*bDeselectBSPSurfs=*/true);
	}

	int32 FoundCount = 0;
	int32 NotFoundCount = 0;
	TArray<FString> NotFoundNames;

	for (const TSharedPtr<FJsonValue>& NameVal : *ActorNames)
	{
		FString ActorName;
		if (!NameVal->TryGetString(ActorName) || ActorName.IsEmpty())
		{
			continue;
		}

		AActor* Actor = FindActorByName(World, ActorName);
		if (!Actor)
		{
			NotFoundCount++;
			NotFoundNames.Add(ActorName);
			continue;
		}

		if (Mode.Equals(TEXT("set"), ESearchCase::IgnoreCase) || Mode.Equals(TEXT("add"), ESearchCase::IgnoreCase))
		{
			GEditor->SelectActor(Actor, /*bInSelected=*/true, /*bNotify=*/false);
		}
		else if (Mode.Equals(TEXT("remove"), ESearchCase::IgnoreCase))
		{
			GEditor->SelectActor(Actor, /*bInSelected=*/false, /*bNotify=*/false);
		}
		else if (Mode.Equals(TEXT("toggle"), ESearchCase::IgnoreCase))
		{
			bool bIsSelected = Actor->IsSelected();
			GEditor->SelectActor(Actor, /*bInSelected=*/!bIsSelected, /*bNotify=*/false);
		}

		FoundCount++;
	}

	// Notify after all selection changes
	GEditor->NoteSelectionChange();

	// Count total selected
	int32 SelectedCount = 0;
	for (FSelectionIterator It(GEditor->GetSelectedActorIterator()); It; ++It)
	{
		SelectedCount++;
	}

	TSharedPtr<FJsonObject> Result = MakeShared<FJsonObject>();
	Result->SetStringField(TEXT("mode"), Mode);
	Result->SetNumberField(TEXT("requested"), ActorNames->Num());
	Result->SetNumberField(TEXT("found"), FoundCount);
	Result->SetNumberField(TEXT("not_found"), NotFoundCount);
	Result->SetNumberField(TEXT("selected_count"), SelectedCount);
	if (NotFoundNames.Num() > 0)
	{
		TArray<TSharedPtr<FJsonValue>> NotFoundArr;
		for (const FString& Name : NotFoundNames)
		{
			NotFoundArr.Add(MakeShared<FJsonValueString>(Name));
		}
		Result->SetArrayField(TEXT("not_found_names"), NotFoundArr);
	}

	return CreateSuccessResponse(Result);
}

// ---- P6.9 FGetOutlinerTreeAction ----

TSharedPtr<FJsonObject> FGetOutlinerTreeAction::ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context)
{
	UWorld* World = GEditor ? GEditor->GetEditorWorldContext().World() : nullptr;
	if (!World)
	{
		return CreateErrorResponse(TEXT("No editor world available"));
	}

	FString ClassFilter = GetOptionalString(Params, TEXT("class_filter"));
	FString FolderFilter = GetOptionalString(Params, TEXT("folder_filter"));

	// Organize actors by folder
	TMap<FString, TArray<TSharedPtr<FJsonValue>>> FolderMap;
	TArray<TSharedPtr<FJsonValue>> UnfolderedActors;
	int32 TotalActors = 0;

	for (TActorIterator<AActor> It(World); It; ++It)
	{
		AActor* Actor = *It;
		if (!Actor || Actor->IsA(AWorldSettings::StaticClass()))
		{
			continue;
		}

		FString ClassName = Actor->GetClass()->GetName();

		// Class filter
		if (!ClassFilter.IsEmpty() && !ClassName.Contains(ClassFilter))
		{
			continue;
		}

		FString FolderPath = Actor->GetFolderPath().ToString();

		// Folder filter
		if (!FolderFilter.IsEmpty() && !FolderPath.StartsWith(FolderFilter))
		{
			// If folder doesn't match and actor is not unfoldered, skip
			if (!FolderPath.IsEmpty())
			{
				continue;
			}
		}

		TSharedPtr<FJsonObject> ActorObj = MakeShared<FJsonObject>();
		ActorObj->SetStringField(TEXT("name"), Actor->GetName());
		ActorObj->SetStringField(TEXT("class"), ClassName);
		ActorObj->SetStringField(TEXT("label"), Actor->GetActorLabel());

		TotalActors++;

		if (FolderPath.IsEmpty())
		{
			UnfolderedActors.Add(MakeShared<FJsonValueObject>(ActorObj));
		}
		else
		{
			FolderMap.FindOrAdd(FolderPath).Add(MakeShared<FJsonValueObject>(ActorObj));
		}
	}

	// Build folders array
	TArray<TSharedPtr<FJsonValue>> FoldersArray;
	// Sort folder paths
	TArray<FString> FolderPaths;
	FolderMap.GetKeys(FolderPaths);
	FolderPaths.Sort();

	for (const FString& Path : FolderPaths)
	{
		TSharedPtr<FJsonObject> FolderObj = MakeShared<FJsonObject>();
		FolderObj->SetStringField(TEXT("path"), Path);
		FolderObj->SetArrayField(TEXT("actors"), FolderMap[Path]);
		FolderObj->SetNumberField(TEXT("actor_count"), FolderMap[Path].Num());
		FoldersArray.Add(MakeShared<FJsonValueObject>(FolderObj));
	}

	TSharedPtr<FJsonObject> Result = MakeShared<FJsonObject>();
	Result->SetNumberField(TEXT("total_actors"), TotalActors);
	Result->SetNumberField(TEXT("folder_count"), FoldersArray.Num());
	Result->SetArrayField(TEXT("folders"), FoldersArray);
	Result->SetArrayField(TEXT("unfoldered_actors"), UnfolderedActors);

	return CreateSuccessResponse(Result);
}


// ============================================================================
// FOpenAssetEditorAction — Open an asset editor and optionally focus it
// ============================================================================

bool FOpenAssetEditorAction::Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError)
{
	if (!Params->HasField(TEXT("asset_path")))
	{
		OutError = TEXT("'asset_path' is required (e.g. '/Game/Characters/BP_Hero')");
		return false;
	}
	return true;
}

TSharedPtr<FJsonObject> FOpenAssetEditorAction::ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context)
{
	FString AssetPath = Params->GetStringField(TEXT("asset_path"));
	bool bFocus = GetOptionalBool(Params, TEXT("focus"), true);

	// 1) Validate GEditor
	if (!GEditor)
	{
		return CreateErrorResponse(TEXT("GEditor is not available"), TEXT("editor_not_ready"));
	}

	// 2) Load the asset
	UObject* Asset = StaticLoadObject(UObject::StaticClass(), nullptr, *AssetPath);
	if (!Asset)
	{
		return CreateErrorResponse(
			FString::Printf(TEXT("Failed to load asset: %s"), *AssetPath),
			TEXT("asset_not_found")
		);
	}

	// 3) Get AssetEditorSubsystem
	UAssetEditorSubsystem* AssetEditorSS = GEditor->GetEditorSubsystem<UAssetEditorSubsystem>();
	if (!AssetEditorSS)
	{
		return CreateErrorResponse(TEXT("AssetEditorSubsystem is not available"), TEXT("subsystem_error"));
	}

	// 4) Open the editor
	bool bOpened = AssetEditorSS->OpenEditorForAsset(Asset);
	if (!bOpened)
	{
		return CreateErrorResponse(
			FString::Printf(TEXT("Failed to open editor for asset: %s"), *AssetPath),
			TEXT("open_failed")
		);
	}

	// 5) Optionally focus the editor window
	FString EditorName = TEXT("Unknown");
	if (bFocus)
	{
		IAssetEditorInstance* EditorInstance = AssetEditorSS->FindEditorForAsset(Asset, /*bFocusIfOpen=*/ true);
		if (EditorInstance)
		{
			EditorName = EditorInstance->GetEditorName().ToString();
		}
	}
	else
	{
		IAssetEditorInstance* EditorInstance = AssetEditorSS->FindEditorForAsset(Asset, false);
		if (EditorInstance)
		{
			EditorName = EditorInstance->GetEditorName().ToString();
		}
	}

	// 6) Build result
	TSharedPtr<FJsonObject> Result = MakeShared<FJsonObject>();
	Result->SetStringField(TEXT("asset_path"), AssetPath);
	Result->SetStringField(TEXT("asset_name"), Asset->GetName());
	Result->SetStringField(TEXT("asset_class"), Asset->GetClass()->GetName());
	Result->SetStringField(TEXT("editor_name"), EditorName);
	Result->SetBoolField(TEXT("focused"), bFocus);

	return CreateSuccessResponse(Result);
}


// =========================================================================
// P8: PIE Automation Test Actions（关卡切换 + 多人 PIE + 输入模拟）
// =========================================================================

// ---- P8.1 FOpenLevelAction ----

bool FOpenLevelAction::Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError)
{
	if (!GEditor)
	{
		OutError = TEXT("GEditor is not available");
		return false;
	}
	if (!Params.IsValid() || !Params->HasField(TEXT("level_path")))
	{
		OutError = TEXT("Missing required parameter: level_path");
		return false;
	}
	if (GEditor->PlayWorld)
	{
		OutError = TEXT("Cannot switch level while PIE is running. Stop PIE first via editor.stop_pie.");
		return false;
	}
	return true;
}

TSharedPtr<FJsonObject> FOpenLevelAction::ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context)
{
	const FString LevelPath = Params->GetStringField(TEXT("level_path"));
	const bool    bSaveDirty = GetOptionalBool(Params, TEXT("save_dirty"), false);

	// 解析为 Long Package Name（接受 "/Game/Foo/L_Foo" 或 "/Game/Foo/L_Foo.L_Foo"）
	FString PackageName = LevelPath;
	if (PackageName.Contains(TEXT(".")))
	{
		PackageName = FPackageName::ObjectPathToPackageName(LevelPath);
	}

	// 资产存在性校验
	if (!FPackageName::DoesPackageExist(PackageName))
	{
		return CreateErrorResponse(
			FString::Printf(TEXT("Level package not found: %s"), *PackageName),
			TEXT("level_not_found"));
	}

	if (bSaveDirty)
	{
		FEditorFileUtils::SaveDirtyPackages(/*bPromptUserToSave*/ false,
		                                    /*bSaveMapPackages*/   true,
		                                    /*bSaveContentPackages*/ true);
	}

	const bool bLoaded = FEditorFileUtils::LoadMap(PackageName, /*LoadAsTemplate*/ false, /*bShowProgress*/ true);
	if (!bLoaded)
	{
		return CreateErrorResponse(
			FString::Printf(TEXT("Failed to load level: %s"), *PackageName),
			TEXT("load_failed"));
	}

	UWorld* World = GEditor->GetEditorWorldContext().World();

	TSharedPtr<FJsonObject> Result = MakeShared<FJsonObject>();
	Result->SetStringField(TEXT("level_path"), LevelPath);
	Result->SetStringField(TEXT("package_name"), PackageName);
	Result->SetStringField(TEXT("world_name"), World ? World->GetName() : FString());
	Result->SetStringField(TEXT("message"), TEXT("Level loaded"));

	UE_LOG(LogMCP, Log, TEXT("Editor level switched to: %s"), *PackageName);

	return CreateSuccessResponse(Result);
}

// ---- P8.1b FCreateLevelAction ----

bool FCreateLevelAction::Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError)
{
	if (!GEditor)
	{
		OutError = TEXT("GEditor is not available");
		return false;
	}
	if (!Params.IsValid() || !Params->HasField(TEXT("level_path")))
	{
		OutError = TEXT("Missing required parameter: level_path");
		return false;
	}
	if (GEditor->PlayWorld)
	{
		OutError = TEXT("Cannot create a level while PIE is running. Stop PIE first.");
		return false;
	}

	FString LevelPath = Params->GetStringField(TEXT("level_path"));
	if (LevelPath.Contains(TEXT(".")))
	{
		LevelPath = FPackageName::ObjectPathToPackageName(LevelPath);
	}
	if (!FPackageName::IsValidLongPackageName(LevelPath))
	{
		OutError = FString::Printf(TEXT("Invalid level_path long package name: %s"), *LevelPath);
		return false;
	}

	const FString IfExists = GetOptionalString(Params, TEXT("if_exists"), TEXT("error")).ToLower();
	if (IfExists != TEXT("error") && IfExists != TEXT("overwrite") && IfExists != TEXT("skip") && IfExists != TEXT("reuse"))
	{
		OutError = TEXT("if_exists must be one of: error, overwrite, skip, reuse");
		return false;
	}

	return true;
}

TSharedPtr<FJsonObject> FCreateLevelAction::ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context)
{
	FString LevelPath = Params->GetStringField(TEXT("level_path"));
	if (LevelPath.Contains(TEXT(".")))
	{
		LevelPath = FPackageName::ObjectPathToPackageName(LevelPath);
	}

	const FString IfExists = GetOptionalString(Params, TEXT("if_exists"), TEXT("error")).ToLower();
	const bool bOpenLevel = GetOptionalBool(Params, TEXT("open_level"), true);
	const bool bSaveDirty = GetOptionalBool(Params, TEXT("save_dirty"), false);
	const bool bExists = FPackageName::DoesPackageExist(LevelPath);

	if (bExists)
	{
		if (IfExists == TEXT("skip") || IfExists == TEXT("reuse"))
		{
			if (bOpenLevel && !FEditorFileUtils::LoadMap(LevelPath, /*LoadAsTemplate*/ false, /*bShowProgress*/ true))
			{
				return CreateErrorResponse(FString::Printf(TEXT("Existing level found but failed to load: %s"), *LevelPath), TEXT("load_failed"));
			}

			TSharedPtr<FJsonObject> Result = MakeShared<FJsonObject>();
			Result->SetStringField(TEXT("level_path"), LevelPath);
			Result->SetStringField(TEXT("object_path"), FString::Printf(TEXT("%s.%s"), *LevelPath, *FPackageName::GetShortName(LevelPath)));
			Result->SetBoolField(TEXT("created"), false);
			Result->SetBoolField(TEXT("existing"), true);
			Result->SetBoolField(TEXT("skipped"), true);
			Result->SetBoolField(TEXT("opened"), bOpenLevel);
			return CreateSuccessResponse(Result);
		}
		if (IfExists != TEXT("overwrite"))
		{
			return CreateErrorResponse(FString::Printf(TEXT("Level already exists: %s"), *LevelPath), TEXT("asset_exists"));
		}
	}

	if (bSaveDirty)
	{
		FEditorFileUtils::SaveDirtyPackages(/*bPromptUserToSave*/ false,
		                                    /*bSaveMapPackages*/   true,
		                                    /*bSaveContentPackages*/ true);
	}

	UWorld* NewWorld = UEditorLoadingAndSavingUtils::NewBlankMap(/*bSaveExistingMap*/ false);
	if (!NewWorld)
	{
		return CreateErrorResponse(TEXT("NewBlankMap failed"), TEXT("create_failed"));
	}

	const FString MapFilename = FPackageName::LongPackageNameToFilename(LevelPath, FPackageName::GetMapPackageExtension());
	const bool bSaved = UEditorLoadingAndSavingUtils::SaveMap(NewWorld, LevelPath);
	if (!bSaved)
	{
		return CreateErrorResponse(FString::Printf(TEXT("SaveMap failed for %s"), *LevelPath), TEXT("save_failed"));
	}

	FAssetRegistryModule::AssetCreated(NewWorld);

	if (bOpenLevel && !FEditorFileUtils::LoadMap(LevelPath, /*LoadAsTemplate*/ false, /*bShowProgress*/ true))
	{
		return CreateErrorResponse(FString::Printf(TEXT("Created level but failed to reopen: %s"), *LevelPath), TEXT("load_failed"));
	}

	UWorld* World = GEditor->GetEditorWorldContext().World();

	TSharedPtr<FJsonObject> Result = MakeShared<FJsonObject>();
	Result->SetStringField(TEXT("level_path"), LevelPath);
	Result->SetStringField(TEXT("object_path"), FString::Printf(TEXT("%s.%s"), *LevelPath, *FPackageName::GetShortName(LevelPath)));
	Result->SetStringField(TEXT("filename"), MapFilename);
	Result->SetStringField(TEXT("world_name"), World ? World->GetName() : FString());
	Result->SetBoolField(TEXT("created"), true);
	Result->SetBoolField(TEXT("existing"), false);
	Result->SetBoolField(TEXT("opened"), bOpenLevel);
	Result->SetBoolField(TEXT("saved"), bSaved);

	UE_LOG(LogMCP, Log, TEXT("Created editor level: %s"), *LevelPath);

	return CreateSuccessResponse(Result);
}

// ---- P8.1c FDuplicateAssetAction ----

bool FDuplicateAssetAction::Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError)
{
	FString SourceAssetPath;
	FString DestinationAssetPath;
	if (!GetRequiredString(Params, TEXT("source_asset_path"), SourceAssetPath, OutError))
	{
		return false;
	}
	if (!GetRequiredString(Params, TEXT("destination_asset_path"), DestinationAssetPath, OutError))
	{
		return false;
	}

	const FString DestinationPackagePath = DestinationAssetPath.Contains(TEXT("."))
		? FPackageName::ObjectPathToPackageName(DestinationAssetPath)
		: DestinationAssetPath;
	if (!FPackageName::IsValidLongPackageName(DestinationPackagePath))
	{
		OutError = FString::Printf(TEXT("Invalid destination_asset_path long package name: %s"), *DestinationAssetPath);
		return false;
	}

	const FString IfExists = GetOptionalString(Params, TEXT("if_exists"), TEXT("error")).ToLower();
	if (IfExists != TEXT("error") && IfExists != TEXT("overwrite") && IfExists != TEXT("skip") && IfExists != TEXT("reuse"))
	{
		OutError = TEXT("if_exists must be one of: error, overwrite, skip, reuse");
		return false;
	}

	return true;
}

TSharedPtr<FJsonObject> FDuplicateAssetAction::ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context)
{
	const FString SourceAssetPath = Params->GetStringField(TEXT("source_asset_path"));
	const FString DestinationAssetPathRaw = Params->GetStringField(TEXT("destination_asset_path"));
	const FString DestinationPackagePath = DestinationAssetPathRaw.Contains(TEXT("."))
		? FPackageName::ObjectPathToPackageName(DestinationAssetPathRaw)
		: DestinationAssetPathRaw;
	const FString DestinationObjectPath = FString::Printf(TEXT("%s.%s"), *DestinationPackagePath, *FPackageName::GetShortName(DestinationPackagePath));
	const FString IfExists = GetOptionalString(Params, TEXT("if_exists"), TEXT("error")).ToLower();
	const bool bSave = GetOptionalBool(Params, TEXT("save"), true);

	if (!GEditor)
	{
		return CreateErrorResponse(TEXT("GEditor is not available"), TEXT("editor_not_ready"));
	}

	UEditorAssetSubsystem* AssetSS = GEditor->GetEditorSubsystem<UEditorAssetSubsystem>();
	if (!AssetSS)
	{
		return CreateErrorResponse(TEXT("EditorAssetSubsystem unavailable"), TEXT("subsystem_error"));
	}

	if (!AssetSS->DoesAssetExist(SourceAssetPath))
	{
		return CreateErrorResponse(FString::Printf(TEXT("Source asset not found: %s"), *SourceAssetPath), TEXT("asset_not_found"));
	}

	const bool bDestinationExists = AssetSS->DoesAssetExist(DestinationPackagePath) || AssetSS->DoesAssetExist(DestinationObjectPath);
	if (bDestinationExists)
	{
		if (IfExists == TEXT("skip") || IfExists == TEXT("reuse"))
		{
			UObject* ExistingAsset = LoadObject<UObject>(nullptr, *DestinationObjectPath);
			TSharedPtr<FJsonObject> Result = MakeShared<FJsonObject>();
			Result->SetStringField(TEXT("source_asset_path"), SourceAssetPath);
			Result->SetStringField(TEXT("asset_path"), ExistingAsset ? ExistingAsset->GetPathName() : DestinationObjectPath);
			Result->SetBoolField(TEXT("created"), false);
			Result->SetBoolField(TEXT("existing"), true);
			Result->SetBoolField(TEXT("skipped"), true);
			Result->SetBoolField(TEXT("saved"), false);
			return CreateSuccessResponse(Result);
		}
		if (IfExists != TEXT("overwrite"))
		{
			return CreateErrorResponse(FString::Printf(TEXT("Destination asset already exists: %s"), *DestinationPackagePath), TEXT("asset_exists"));
		}
		if (!AssetSS->DeleteAsset(DestinationPackagePath))
		{
			return CreateErrorResponse(FString::Printf(TEXT("Failed to delete existing destination asset: %s"), *DestinationPackagePath), TEXT("delete_failed"));
		}
	}

	UObject* DuplicatedAsset = AssetSS->DuplicateAsset(SourceAssetPath, DestinationPackagePath);
	if (!DuplicatedAsset)
	{
		return CreateErrorResponse(FString::Printf(TEXT("DuplicateAsset failed: %s -> %s"), *SourceAssetPath, *DestinationPackagePath), TEXT("duplicate_failed"));
	}

	bool bSaved = false;
	if (bSave)
	{
		bSaved = AssetSS->SaveLoadedAsset(DuplicatedAsset, /*bOnlyIfIsDirty*/ false);
	}

	TSharedPtr<FJsonObject> Result = MakeShared<FJsonObject>();
	Result->SetStringField(TEXT("source_asset_path"), SourceAssetPath);
	Result->SetStringField(TEXT("asset_path"), DuplicatedAsset->GetPathName());
	Result->SetStringField(TEXT("package_path"), DuplicatedAsset->GetOutermost()->GetName());
	Result->SetStringField(TEXT("asset_class"), DuplicatedAsset->GetClass()->GetName());
	Result->SetBoolField(TEXT("created"), true);
	Result->SetBoolField(TEXT("existing"), false);
	Result->SetBoolField(TEXT("saved"), bSaved);

	UE_LOG(LogMCP, Log, TEXT("Duplicated asset: %s -> %s"), *SourceAssetPath, *DuplicatedAsset->GetPathName());

	return CreateSuccessResponse(Result);
}

// ---- P8.1d FSetWorldSettingsClassAction ----

bool FSetWorldSettingsClassAction::Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError)
{
	if (!GEditor)
	{
		OutError = TEXT("GEditor is not available");
		return false;
	}
	if (GEditor->PlayWorld)
	{
		OutError = TEXT("Cannot edit WorldSettings while PIE is running. Stop PIE first.");
		return false;
	}
	if (!Params.IsValid() || !Params->HasField(TEXT("property_name")))
	{
		OutError = TEXT("Missing required parameter: property_name");
		return false;
	}
	if (!Params->HasField(TEXT("class_path")))
	{
		OutError = TEXT("Missing required parameter: class_path");
		return false;
	}

	UWorld* World = GEditor->GetEditorWorldContext().World();
	if (!World || !World->GetWorldSettings())
	{
		OutError = TEXT("No editor WorldSettings available");
		return false;
	}

	FString PropertyName = Params->GetStringField(TEXT("property_name"));
	if (PropertyName == TEXT("GameModeOverride"))
	{
		PropertyName = TEXT("DefaultGameMode");
	}
	FProperty* Property = AWorldSettings::StaticClass()->FindPropertyByName(*PropertyName);
	if (!Property)
	{
		OutError = FString::Printf(TEXT("WorldSettings property not found: %s"), *PropertyName);
		return false;
	}
	if (!CastField<FClassProperty>(Property))
	{
		OutError = FString::Printf(TEXT("WorldSettings property is not a class property: %s"), *PropertyName);
		return false;
	}

	return true;
}

TSharedPtr<FJsonObject> FSetWorldSettingsClassAction::ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context)
{
	FString PropertyName = Params->GetStringField(TEXT("property_name"));
	if (PropertyName == TEXT("GameModeOverride"))
	{
		PropertyName = TEXT("DefaultGameMode");
	}
	const FString ClassPath = Params->GetStringField(TEXT("class_path"));

	UWorld* World = GEditor ? GEditor->GetEditorWorldContext().World() : nullptr;
	AWorldSettings* WorldSettings = World ? World->GetWorldSettings() : nullptr;
	if (!WorldSettings)
	{
		return CreateErrorResponse(TEXT("No editor WorldSettings available"), TEXT("world_settings_not_found"));
	}

	FClassProperty* ClassProperty = CastField<FClassProperty>(AWorldSettings::StaticClass()->FindPropertyByName(*PropertyName));
	if (!ClassProperty)
	{
		return CreateErrorResponse(FString::Printf(TEXT("WorldSettings property is not a class property: %s"), *PropertyName), TEXT("invalid_property"));
	}

	UClass* ClassValue = StaticLoadClass(UObject::StaticClass(), nullptr, *ClassPath);
	if (!ClassValue)
	{
		return CreateErrorResponse(FString::Printf(TEXT("Class not found: %s"), *ClassPath), TEXT("class_not_found"));
	}
	if (ClassProperty->MetaClass && !ClassValue->IsChildOf(ClassProperty->MetaClass))
	{
		return CreateErrorResponse(
			FString::Printf(TEXT("Class %s is not a child of required class %s"), *ClassValue->GetName(), *ClassProperty->MetaClass->GetName()),
			TEXT("class_type_mismatch"));
	}

	WorldSettings->Modify();
	ClassProperty->SetPropertyValue_InContainer(WorldSettings, ClassValue);
	WorldSettings->PostEditChange();
	WorldSettings->MarkPackageDirty();

	bool bSaved = false;
	if (UPackage* Package = World->GetOutermost())
	{
		bSaved = FEditorFileUtils::SaveMap(World, Package->GetName());
	}

	TSharedPtr<FJsonObject> Result = MakeShared<FJsonObject>();
	Result->SetStringField(TEXT("property_name"), PropertyName);
	Result->SetStringField(TEXT("class_path"), ClassValue->GetPathName());
	Result->SetStringField(TEXT("world_name"), World->GetName());
	Result->SetBoolField(TEXT("saved"), bSaved);

	UE_LOG(LogMCP, Log, TEXT("Set WorldSettings.%s = %s"), *PropertyName, *ClassValue->GetPathName());

	return CreateSuccessResponse(Result);
}


// ---- P8.2 FSimulateInputAction ----

bool FSimulateInputAction::Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError)
{
	if (!GEditor)
	{
		OutError = TEXT("GEditor is not available");
		return false;
	}
	if (!GEditor->PlayWorld)
	{
		OutError = TEXT("No PIE session running. Start PIE first via editor.start_pie.");
		return false;
	}
	if (!Params.IsValid() || !Params->HasField(TEXT("key")))
	{
		OutError = TEXT("Missing required parameter: key");
		return false;
	}
	return true;
}

namespace
{
	/**
	 * 按 PIE 实例索引获取对应的 PIE World。
	 * 索引规则：按 GEngine->GetWorldContexts() 中 WorldType==PIE 的出现顺序计数。
	 * 通常 0 = Listen Server / Standalone，1+ = 其他客户端窗口。
	 */
	UWorld* GetPIEWorldByIndex(int32 ClientIndex)
	{
		if (!GEngine)
		{
			return nullptr;
		}
		int32 PIESeen = 0;
		for (const FWorldContext& Ctx : GEngine->GetWorldContexts())
		{
			if (Ctx.WorldType == EWorldType::PIE && Ctx.World())
			{
				if (PIESeen == ClientIndex)
				{
					return Ctx.World();
				}
				++PIESeen;
			}
		}
		return nullptr;
	}

	/** 在 PIE World 上派发一次按键事件。bPressed=true → 按下，false → 抬起 */
	bool DispatchKeyEvent(UWorld* PIEWorld, const FKey& Key, bool bPressed)
	{
		if (!PIEWorld)
		{
			return false;
		}
		APlayerController* PC = UGameplayStatics::GetPlayerController(PIEWorld, 0);
		if (!PC || !PC->PlayerInput)
		{
			return false;
		}

		// UE 5.7：FInputKeyParams 已被删除，改用 FInputKeyEventArgs。
		// CreateSimulated 是引擎为模拟输入提供的静态便捷构造器，会自动设置 bIsSimulatedInput=true。
		FInputKeyEventArgs KeyArgs = FInputKeyEventArgs::CreateSimulated(
			Key,
			bPressed ? IE_Pressed : IE_Released,
			/*AmountDepressed*/ bPressed ? 1.0f : 0.0f,
			/*NumSamplesOverride*/ 1,
			/*InputDevice*/ INPUTDEVICEID_NONE,
			/*bIsTouchEvent*/ false,
			/*Viewport*/ nullptr);
		return PC->InputKey(KeyArgs);
	}
}

TSharedPtr<FJsonObject> FSimulateInputAction::ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context)
{
	const int32   ClientIndex   = (int32)GetOptionalNumber(Params, TEXT("client_index"), 0);
	const FString KeyName       = Params->GetStringField(TEXT("key"));
	const FString EventStr      = GetOptionalString(Params, TEXT("event"), TEXT("Pressed"));
	const int32   DurationMs    = (int32)GetOptionalNumber(Params, TEXT("duration_ms"), 50);
	const bool    bFocusViewport= GetOptionalBool(Params, TEXT("focus_viewport"), true);

	// 1) 找到目标 PIE World
	UWorld* PIEWorld = GetPIEWorldByIndex(ClientIndex);
	if (!PIEWorld)
	{
		return CreateErrorResponse(
			FString::Printf(TEXT("PIE world not found for client_index=%d"), ClientIndex),
			TEXT("pie_world_not_found"));
	}

	APlayerController* PC = UGameplayStatics::GetPlayerController(PIEWorld, 0);
	if (!PC)
	{
		return CreateErrorResponse(
			FString::Printf(TEXT("PlayerController not ready for client_index=%d"), ClientIndex),
			TEXT("pc_not_ready"));
	}

	// 2) 焦点修复（避免按键被 UMG / 编辑器 UI 焦点吞掉）
	if (bFocusViewport && FSlateApplication::IsInitialized())
	{
		FSlateApplication::Get().SetAllUserFocusToGameViewport(EFocusCause::SetDirectly);
	}

	// 3) 解析按键名为 FKey
	const FKey Key(*KeyName);
	if (!Key.IsValid())
	{
		return CreateErrorResponse(
			FString::Printf(TEXT("Invalid key name: %s"), *KeyName),
			TEXT("invalid_key"));
	}

	// 4) 派发事件
	bool bHandled = false;
	if (EventStr.Equals(TEXT("Pressed"), ESearchCase::IgnoreCase))
	{
		bHandled = DispatchKeyEvent(PIEWorld, Key, true);
	}
	else if (EventStr.Equals(TEXT("Released"), ESearchCase::IgnoreCase))
	{
		bHandled = DispatchKeyEvent(PIEWorld, Key, false);
	}
	else if (EventStr.Equals(TEXT("Click"), ESearchCase::IgnoreCase))
	{
		// Click = Pressed → 等待 DurationMs → Released
		const bool bP = DispatchKeyEvent(PIEWorld, Key, true);
		const int32 ClampedMs = FMath::Clamp(DurationMs, 1, 5000);

		// 在 ClampedMs 后派发 Released（异步，避免阻塞主线程过久）
		TWeakObjectPtr<UWorld> WeakWorld(PIEWorld);
		FTSTicker::GetCoreTicker().AddTicker(FTickerDelegate::CreateLambda(
			[WeakWorld, Key](float)
			{
				if (UWorld* W = WeakWorld.Get())
				{
					DispatchKeyEvent(W, Key, false);
				}
				return false; // one-shot
			}),
			ClampedMs / 1000.0f);

		bHandled = bP;
	}
	else
	{
		return CreateErrorResponse(
			FString::Printf(TEXT("Invalid event: %s (expected Pressed|Released|Click)"), *EventStr),
			TEXT("invalid_event"));
	}

	TSharedPtr<FJsonObject> Result = MakeShared<FJsonObject>();
	Result->SetNumberField(TEXT("client_index"), ClientIndex);
	Result->SetStringField(TEXT("key"), KeyName);
	Result->SetStringField(TEXT("event"), EventStr);
	Result->SetNumberField(TEXT("duration_ms"), DurationMs);
	Result->SetBoolField(TEXT("handled"), bHandled);
	Result->SetStringField(TEXT("world_name"), PIEWorld->GetName());

	UE_LOG(LogMCP, Log, TEXT("simulate_input client=%d key=%s event=%s handled=%d"),
		ClientIndex, *KeyName, *EventStr, bHandled ? 1 : 0);

	return CreateSuccessResponse(Result);
}


// ============================================================================
// FSetDataAssetPropertyAction / FGetDataAssetPropertyAction
//
// 直接修改 / 读取 UObject 资产（DataAsset、PrimaryDataAsset 等）上的 UPROPERTY。
// 走 FProperty::ImportText_Direct（写） / ExportText_Direct（读），覆盖 USTRUCT、
// 数组、Map、Set 等复杂类型。专门用于资产配置（DataAsset Entries 等），不要
// 与 set_object_property（创建 K2Node_VariableSet 节点）混淆。
// ============================================================================

namespace UEEditorMCP_DataAssetUtils
{
	/** 把 "/Game/X/Y/Asset" 规范化为 "/Game/X/Y/Asset.Asset"（StaticLoadObject 需要带尾随对象名）。 */
	static FString NormalizeAssetObjectPath(const FString& InPath)
	{
		// 已经带 . 的视为完整 ObjectPath
		int32 DotIdx = INDEX_NONE;
		if (InPath.FindChar(TEXT('.'), DotIdx))
		{
			return InPath;
		}
		int32 SlashIdx = INDEX_NONE;
		InPath.FindLastChar(TEXT('/'), SlashIdx);
		if (SlashIdx == INDEX_NONE)
		{
			return InPath;
		}
		const FString AssetName = InPath.Mid(SlashIdx + 1);
		return InPath + TEXT(".") + AssetName;
	}

	/** 加载资产（容错路径形式）。 */
	static UObject* LoadAssetFlexible(const FString& InPath, FString& OutErrorMessage)
	{
		const FString FullPath = NormalizeAssetObjectPath(InPath);
		UObject* Asset = StaticLoadObject(UObject::StaticClass(), nullptr, *FullPath);
		if (!Asset)
		{
			OutErrorMessage = FString::Printf(TEXT("Failed to load asset: %s"), *FullPath);
			return nullptr;
		}
		return Asset;
	}

	/** 把当前属性值导出成 UE 文本字面量（供 GET 接口 / SET 后回读）。 */
	/**
	 * Blueprint assets store gameplay defaults on their generated class default
	 * object rather than on UBlueprint itself. Resolve that container so the
	 * generic property reader matches its advertised Blueprint CDO support.
	 */
	static UObject* ResolvePropertyContainer(UObject* Asset, FString& OutErrorMessage)
	{
		UBlueprint* Blueprint = Cast<UBlueprint>(Asset);
		if (!Blueprint)
		{
			return Asset;
		}

		if (!Blueprint->GeneratedClass)
		{
			OutErrorMessage = FString::Printf(
				TEXT("Blueprint '%s' has no generated class; compile it first."),
				*Blueprint->GetPathName());
			return nullptr;
		}

		UObject* DefaultObject = Blueprint->GeneratedClass->GetDefaultObject();
		if (!DefaultObject)
		{
			OutErrorMessage = FString::Printf(
				TEXT("Failed to resolve class default object for Blueprint '%s'."),
				*Blueprint->GetPathName());
			return nullptr;
		}

		return DefaultObject;
	}

	static FString ExportPropertyAsText(UObject* Asset, FProperty* Property)
	{
		if (!Asset || !Property)
		{
			return FString();
		}
		FString Out;
		void* PropertyAddr = Property->ContainerPtrToValuePtr<void>(Asset);
		Property->ExportText_Direct(Out, PropertyAddr, PropertyAddr, Asset, PPF_None);
		return Out;
	}

	static int32 GetArrayFieldNum(void* StructValuePtr, UScriptStruct* Struct, const FName FieldName)
	{
		if (!StructValuePtr || !Struct)
		{
			return 0;
		}
		FArrayProperty* ArrayProperty = CastField<FArrayProperty>(Struct->FindPropertyByName(FieldName));
		if (!ArrayProperty)
		{
			return 0;
		}
		void* ArrayPtr = ArrayProperty->ContainerPtrToValuePtr<void>(StructValuePtr);
		FScriptArrayHelper ArrayHelper(ArrayProperty, ArrayPtr);
		return ArrayHelper.Num();
	}

	static FVector GetVectorField(void* StructValuePtr, UScriptStruct* Struct, const FName FieldName)
	{
		if (!StructValuePtr || !Struct)
		{
			return FVector::ZeroVector;
		}
		FStructProperty* StructProperty = CastField<FStructProperty>(Struct->FindPropertyByName(FieldName));
		if (!StructProperty)
		{
			return FVector::ZeroVector;
		}
		if (StructProperty->Struct != TBaseStructure<FVector>::Get())
		{
			return FVector::ZeroVector;
		}
		return *StructProperty->ContainerPtrToValuePtr<FVector>(StructValuePtr);
	}

	static float GetFloatField(void* StructValuePtr, UScriptStruct* Struct, const FName FieldName, float DefaultValue = 0.f)
	{
		if (!StructValuePtr || !Struct)
		{
			return DefaultValue;
		}
		FNumericProperty* NumericProperty = CastField<FNumericProperty>(Struct->FindPropertyByName(FieldName));
		if (!NumericProperty)
		{
			return DefaultValue;
		}
		void* ValuePtr = NumericProperty->ContainerPtrToValuePtr<void>(StructValuePtr);
		return NumericProperty->IsFloatingPoint()
			? static_cast<float>(NumericProperty->GetFloatingPointPropertyValue(ValuePtr))
			: static_cast<float>(NumericProperty->GetSignedIntPropertyValue(ValuePtr));
	}

	static bool GetBoolField(void* StructValuePtr, UScriptStruct* Struct, const FName FieldName)
	{
		if (!StructValuePtr || !Struct)
		{
			return false;
		}
		FBoolProperty* BoolProperty = CastField<FBoolProperty>(Struct->FindPropertyByName(FieldName));
		if (!BoolProperty)
		{
			return false;
		}
		return BoolProperty->GetPropertyValue(BoolProperty->ContainerPtrToValuePtr<void>(StructValuePtr));
	}

	static TArray<TSharedPtr<FJsonValue>> VectorToJsonArray(const FVector& Vector)
	{
		TArray<TSharedPtr<FJsonValue>> Array;
		Array.Add(MakeShared<FJsonValueNumber>(Vector.X));
		Array.Add(MakeShared<FJsonValueNumber>(Vector.Y));
		Array.Add(MakeShared<FJsonValueNumber>(Vector.Z));
		return Array;
	}

	static bool TryBuildLJCPackedChunkSummary(UObject* Asset, TSharedPtr<FJsonObject>& OutSummary, FString& OutError)
	{
		if (!Asset)
		{
			OutError = TEXT("Asset is null.");
			return false;
		}

		FArrayProperty* ChunksProperty = CastField<FArrayProperty>(Asset->GetClass()->FindPropertyByName(TEXT("Chunks")));
		FStructProperty* ChunkStructProperty = ChunksProperty ? CastField<FStructProperty>(ChunksProperty->Inner) : nullptr;
		if (!ChunksProperty || !ChunkStructProperty || !ChunkStructProperty->Struct)
		{
			OutError = TEXT("Asset does not expose a reflected Chunks array.");
			return false;
		}

		void* ChunksPtr = ChunksProperty->ContainerPtrToValuePtr<void>(Asset);
		FScriptArrayHelper Chunks(ChunksProperty, ChunksPtr);
		UScriptStruct* ChunkStruct = ChunkStructProperty->Struct;

		int32 ParentChunkCount = 0;
		int32 ChildChunkCount = 0;
		int32 ChunksWithRenderableData = 0;
		int32 ChunksWithoutRenderableData = 0;
		int32 SectionCount = 0;
		int32 RenderableSectionCount = 0;
		int64 TotalVertices = 0;
		int64 TotalTriangles = 0;
		int32 ParentRenderable = 0;
		int32 ChildRenderable = 0;
		float MaxPhysicsWeightScale = 0.f;
		FVector MaxBoundsExtent = FVector::ZeroVector;
		FVector ParentMaxBoundsExtent = FVector::ZeroVector;
		FVector ChildMaxBoundsExtent = FVector::ZeroVector;

		FArrayProperty* MeshSectionsProperty = CastField<FArrayProperty>(ChunkStruct->FindPropertyByName(TEXT("MeshSections")));
		FStructProperty* MeshSectionStructProperty = MeshSectionsProperty ? CastField<FStructProperty>(MeshSectionsProperty->Inner) : nullptr;
		UScriptStruct* MeshSectionStruct = MeshSectionStructProperty ? MeshSectionStructProperty->Struct : nullptr;

		TArray<TSharedPtr<FJsonValue>> SampleChunks;
		const int32 MaxSampleChunks = 12;
		for (int32 ChunkIndex = 0; ChunkIndex < Chunks.Num(); ++ChunkIndex)
		{
			void* ChunkPtr = Chunks.GetRawPtr(ChunkIndex);
			const bool bChild = GetBoolField(ChunkPtr, ChunkStruct, TEXT("bMidFallSplitChild"));
			const FVector BoundsExtent = GetVectorField(ChunkPtr, ChunkStruct, TEXT("BoundsExtent"));
			const float PhysicsWeightScale = GetFloatField(ChunkPtr, ChunkStruct, TEXT("PhysicsWeightScale"), 1.f);
			MaxPhysicsWeightScale = FMath::Max(MaxPhysicsWeightScale, PhysicsWeightScale);
			MaxBoundsExtent.X = FMath::Max(MaxBoundsExtent.X, BoundsExtent.X);
			MaxBoundsExtent.Y = FMath::Max(MaxBoundsExtent.Y, BoundsExtent.Y);
			MaxBoundsExtent.Z = FMath::Max(MaxBoundsExtent.Z, BoundsExtent.Z);
			if (bChild)
			{
				++ChildChunkCount;
				ChildMaxBoundsExtent.X = FMath::Max(ChildMaxBoundsExtent.X, BoundsExtent.X);
				ChildMaxBoundsExtent.Y = FMath::Max(ChildMaxBoundsExtent.Y, BoundsExtent.Y);
				ChildMaxBoundsExtent.Z = FMath::Max(ChildMaxBoundsExtent.Z, BoundsExtent.Z);
			}
			else
			{
				++ParentChunkCount;
				ParentMaxBoundsExtent.X = FMath::Max(ParentMaxBoundsExtent.X, BoundsExtent.X);
				ParentMaxBoundsExtent.Y = FMath::Max(ParentMaxBoundsExtent.Y, BoundsExtent.Y);
				ParentMaxBoundsExtent.Z = FMath::Max(ParentMaxBoundsExtent.Z, BoundsExtent.Z);
			}

			int32 ChunkSectionCount = 0;
			int32 ChunkRenderableSections = 0;
			int64 ChunkVertices = 0;
			int64 ChunkTriangles = 0;
			if (MeshSectionsProperty && MeshSectionStruct)
			{
				void* MeshSectionsPtr = MeshSectionsProperty->ContainerPtrToValuePtr<void>(ChunkPtr);
				FScriptArrayHelper MeshSections(MeshSectionsProperty, MeshSectionsPtr);
				ChunkSectionCount = MeshSections.Num();
				SectionCount += MeshSections.Num();
				for (int32 SectionIndex = 0; SectionIndex < MeshSections.Num(); ++SectionIndex)
				{
					void* SectionPtr = MeshSections.GetRawPtr(SectionIndex);
					const int32 QuantizedVertexItems = GetArrayFieldNum(SectionPtr, MeshSectionStruct, TEXT("VerticesQuantized"));
					const int32 VertexCount = QuantizedVertexItems > 0
						? QuantizedVertexItems / 3
						: GetArrayFieldNum(SectionPtr, MeshSectionStruct, TEXT("Vertices"));
					const int32 IndexCount = GetArrayFieldNum(SectionPtr, MeshSectionStruct, TEXT("Indices16")) > 0
						? GetArrayFieldNum(SectionPtr, MeshSectionStruct, TEXT("Indices16"))
						: GetArrayFieldNum(SectionPtr, MeshSectionStruct, TEXT("Triangles"));
					const int32 TriangleCount = IndexCount / 3;
					const bool bRenderable = VertexCount > 0 && IndexCount >= 3;
					ChunkVertices += VertexCount;
					ChunkTriangles += TriangleCount;
					TotalVertices += VertexCount;
					TotalTriangles += TriangleCount;
					if (bRenderable)
					{
						++ChunkRenderableSections;
						++RenderableSectionCount;
					}
				}
			}

			const bool bChunkRenderable = ChunkRenderableSections > 0;
			if (bChunkRenderable)
			{
				++ChunksWithRenderableData;
				if (bChild)
				{
					++ChildRenderable;
				}
				else
				{
					++ParentRenderable;
				}
			}
			else
			{
				++ChunksWithoutRenderableData;
			}

			if (SampleChunks.Num() < MaxSampleChunks)
			{
				TSharedPtr<FJsonObject> Sample = MakeShared<FJsonObject>();
				Sample->SetNumberField(TEXT("chunk_index"), ChunkIndex);
				Sample->SetBoolField(TEXT("is_child"), bChild);
				Sample->SetNumberField(TEXT("section_count"), ChunkSectionCount);
				Sample->SetNumberField(TEXT("renderable_sections"), ChunkRenderableSections);
				Sample->SetNumberField(TEXT("vertices"), static_cast<double>(ChunkVertices));
				Sample->SetNumberField(TEXT("triangles"), static_cast<double>(ChunkTriangles));
				Sample->SetArrayField(TEXT("bounds_extent"), VectorToJsonArray(BoundsExtent));
				Sample->SetNumberField(TEXT("physics_weight_scale"), PhysicsWeightScale);
				SampleChunks.Add(MakeShared<FJsonValueObject>(Sample));
			}
		}

		int32 CellBindingCount = 0;
		int32 TotalBoundChunkIndices = 0;
		int32 MaxChunksPerCell = 0;
		if (FArrayProperty* BindingsProperty = CastField<FArrayProperty>(Asset->GetClass()->FindPropertyByName(TEXT("CellChunkBindings"))))
		{
			if (FStructProperty* BindingStructProperty = CastField<FStructProperty>(BindingsProperty->Inner))
			{
				void* BindingsPtr = BindingsProperty->ContainerPtrToValuePtr<void>(Asset);
				FScriptArrayHelper Bindings(BindingsProperty, BindingsPtr);
				CellBindingCount = Bindings.Num();
				UScriptStruct* BindingStruct = BindingStructProperty->Struct;
				for (int32 BindingIndex = 0; BindingIndex < Bindings.Num(); ++BindingIndex)
				{
					void* BindingPtr = Bindings.GetRawPtr(BindingIndex);
					const int32 NumChunkIndices = GetArrayFieldNum(BindingPtr, BindingStruct, TEXT("ChunkIndices"));
					TotalBoundChunkIndices += NumChunkIndices;
					MaxChunksPerCell = FMath::Max(MaxChunksPerCell, NumChunkIndices);
				}
			}
		}

		int32 SecondaryBindingCount = 0;
		int32 TotalSecondaryChildIndices = 0;
		if (FArrayProperty* SecondaryProperty = CastField<FArrayProperty>(Asset->GetClass()->FindPropertyByName(TEXT("MidFallSplitChildBindings"))))
		{
			if (FStructProperty* SecondaryStructProperty = CastField<FStructProperty>(SecondaryProperty->Inner))
			{
				void* SecondaryPtr = SecondaryProperty->ContainerPtrToValuePtr<void>(Asset);
				FScriptArrayHelper SecondaryBindings(SecondaryProperty, SecondaryPtr);
				SecondaryBindingCount = SecondaryBindings.Num();
				UScriptStruct* SecondaryStruct = SecondaryStructProperty->Struct;
				for (int32 BindingIndex = 0; BindingIndex < SecondaryBindings.Num(); ++BindingIndex)
				{
					void* BindingPtr = SecondaryBindings.GetRawPtr(BindingIndex);
					TotalSecondaryChildIndices += GetArrayFieldNum(BindingPtr, SecondaryStruct, TEXT("ChildChunkIndices"));
				}
			}
		}

		OutSummary = MakeShared<FJsonObject>();
		OutSummary->SetStringField(TEXT("asset_path"), Asset->GetPathName());
		OutSummary->SetStringField(TEXT("asset_class"), Asset->GetClass()->GetName());
		OutSummary->SetNumberField(TEXT("chunk_count"), Chunks.Num());
		OutSummary->SetNumberField(TEXT("parent_chunk_count"), ParentChunkCount);
		OutSummary->SetNumberField(TEXT("child_chunk_count"), ChildChunkCount);
		OutSummary->SetNumberField(TEXT("chunks_with_renderable_data"), ChunksWithRenderableData);
		OutSummary->SetNumberField(TEXT("chunks_without_renderable_data"), ChunksWithoutRenderableData);
		OutSummary->SetNumberField(TEXT("parent_chunks_with_renderable_data"), ParentRenderable);
		OutSummary->SetNumberField(TEXT("child_chunks_with_renderable_data"), ChildRenderable);
		OutSummary->SetNumberField(TEXT("mesh_section_count"), SectionCount);
		OutSummary->SetNumberField(TEXT("renderable_section_count"), RenderableSectionCount);
		OutSummary->SetNumberField(TEXT("total_vertices"), static_cast<double>(TotalVertices));
		OutSummary->SetNumberField(TEXT("total_triangles"), static_cast<double>(TotalTriangles));
		OutSummary->SetNumberField(TEXT("cell_binding_count"), CellBindingCount);
		OutSummary->SetNumberField(TEXT("total_bound_parent_chunk_indices"), TotalBoundChunkIndices);
		OutSummary->SetNumberField(TEXT("max_chunks_per_cell_binding"), MaxChunksPerCell);
		OutSummary->SetNumberField(TEXT("secondary_binding_count"), SecondaryBindingCount);
		OutSummary->SetNumberField(TEXT("total_secondary_child_indices"), TotalSecondaryChildIndices);
		OutSummary->SetNumberField(TEXT("max_physics_weight_scale"), MaxPhysicsWeightScale);
		OutSummary->SetArrayField(TEXT("max_bounds_extent"), VectorToJsonArray(MaxBoundsExtent));
		OutSummary->SetArrayField(TEXT("parent_max_bounds_extent"), VectorToJsonArray(ParentMaxBoundsExtent));
		OutSummary->SetArrayField(TEXT("child_max_bounds_extent"), VectorToJsonArray(ChildMaxBoundsExtent));
		OutSummary->SetArrayField(TEXT("sample_chunks"), SampleChunks);
		return true;
	}

	/** SavePackage 一个已加载资产；失败时把原因塞 OutError。 */
	static bool SaveAssetPackage(UObject* Asset, FString& OutError)
	{
		if (!Asset)
		{
			OutError = TEXT("Asset is null; cannot save.");
			return false;
		}
		UPackage* Package = Asset->GetOutermost();
		if (!Package)
		{
			OutError = TEXT("Asset has no outer package.");
			return false;
		}

		Package->SetDirtyFlag(true);

		FString PackageFilename;
		const FString PackageName = Package->GetName();
		const bool bIsMap = Package->ContainsMap();
		const FString Extension = bIsMap
			? FPackageName::GetMapPackageExtension()
			: FPackageName::GetAssetPackageExtension();

		if (!FPackageName::TryConvertLongPackageNameToFilename(PackageName, PackageFilename, Extension))
		{
			OutError = FString::Printf(TEXT("TryConvertLongPackageNameToFilename failed for %s"), *PackageName);
			return false;
		}

		FSavePackageArgs SaveArgs;
		SaveArgs.TopLevelFlags = RF_Standalone;
		const bool bSaved = UPackage::SavePackage(Package, /*Asset=*/nullptr, *PackageFilename, SaveArgs);
		if (!bSaved)
		{
			OutError = FString::Printf(TEXT("UPackage::SavePackage returned false for %s"), *PackageName);
			return false;
		}
		return true;
	}
}

bool FSetDataAssetPropertyAction::Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError)
{
	FString AssetPath, PropertyName;
	if (!GetRequiredString(Params, TEXT("asset_path"), AssetPath, OutError)) return false;
	if (!GetRequiredString(Params, TEXT("property_name"), PropertyName, OutError)) return false;
	if (!Params->HasField(TEXT("property_value")))
	{
		OutError = TEXT("'property_value' is required (string|number|bool|object).");
		return false;
	}
	return true;
}

TSharedPtr<FJsonObject> FSetDataAssetPropertyAction::ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context)
{
	const FString AssetPath = Params->GetStringField(TEXT("asset_path"));
	const FString PropertyName = Params->GetStringField(TEXT("property_name"));
	const bool bSave = GetOptionalBool(Params, TEXT("save"), true);

	FString LoadError;
	UObject* Asset = UEEditorMCP_DataAssetUtils::LoadAssetFlexible(AssetPath, LoadError);
	if (!Asset)
	{
		return CreateErrorResponse(LoadError, TEXT("asset_not_found"));
	}

	if (PropertyName.Equals(TEXT("__ljc_packed_chunk_summary"), ESearchCase::IgnoreCase))
	{
		TSharedPtr<FJsonObject> Summary;
		FString SummaryError;
		if (!UEEditorMCP_DataAssetUtils::TryBuildLJCPackedChunkSummary(Asset, Summary, SummaryError))
		{
			return CreateErrorResponse(SummaryError, TEXT("summary_unavailable"));
		}

		Summary->SetStringField(TEXT("property_name"), PropertyName);
		return CreateSuccessResponse(Summary);
	}

	FProperty* Property = Asset->GetClass()->FindPropertyByName(*PropertyName);
	if (!Property)
	{
		return CreateErrorResponse(
			FString::Printf(TEXT("Property '%s' not found on '%s'"), *PropertyName, *Asset->GetClass()->GetName()),
			TEXT("property_not_found"));
	}

	// 取 JSON 值（任意类型；FMCPCommonUtils::SetObjectProperty 会按类型分派）。
	TSharedPtr<FJsonValue> JsonValue = Params->TryGetField(TEXT("property_value"));
	if (!JsonValue.IsValid())
	{
		return CreateErrorResponse(TEXT("'property_value' missing or invalid."), TEXT("invalid_value"));
	}

	// PreEditChange / PostEditChange 走标准编辑器修改流程，让 OnObjectModified
	// 等钩子能正常触发（DataAsset Editor 打开状态下，UI 也能即时刷新）。
	Asset->PreEditChange(Property);
	Asset->Modify();

	FString SetError;
	const bool bOk = FMCPCommonUtils::SetObjectProperty(Asset, PropertyName, JsonValue, SetError);

	FPropertyChangedEvent ChangeEvent(Property, EPropertyChangeType::ValueSet);
	Asset->PostEditChangeProperty(ChangeEvent);

	if (!bOk)
	{
		return CreateErrorResponse(
			FString::Printf(TEXT("SetObjectProperty failed: %s"), *SetError),
			TEXT("import_text_failed"));
	}

	const FString ValueAfter = UEEditorMCP_DataAssetUtils::ExportPropertyAsText(Asset, Property);

	bool bSaved = false;
	FString SaveError;
	if (bSave)
	{
		bSaved = UEEditorMCP_DataAssetUtils::SaveAssetPackage(Asset, SaveError);
	}
	else
	{
		// 不立刻保存也至少标脏，方便用户用 save_all 一并落盘。
		if (UPackage* Pkg = Asset->GetOutermost())
		{
			Pkg->SetDirtyFlag(true);
		}
	}

	TSharedPtr<FJsonObject> Result = MakeShared<FJsonObject>();
	Result->SetStringField(TEXT("asset_path"), Asset->GetPathName());
	Result->SetStringField(TEXT("asset_class"), Asset->GetClass()->GetName());
	Result->SetStringField(TEXT("property_name"), PropertyName);
	Result->SetStringField(TEXT("value_after"), ValueAfter);
	Result->SetBoolField(TEXT("saved"), bSaved);
	if (bSave && !bSaved)
	{
		Result->SetStringField(TEXT("save_error"), SaveError);
	}

	UE_LOG(LogMCP, Log, TEXT("set_data_asset_property: %s.%s = %s (saved=%d)"),
		*Asset->GetPathName(), *PropertyName, *ValueAfter, bSaved ? 1 : 0);

	return CreateSuccessResponse(Result);
}


bool FGetDataAssetPropertyAction::Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError)
{
	FString AssetPath, PropertyName;
	if (!GetRequiredString(Params, TEXT("asset_path"), AssetPath, OutError)) return false;
	if (!GetRequiredString(Params, TEXT("property_name"), PropertyName, OutError)) return false;
	return true;
}

TSharedPtr<FJsonObject> FGetDataAssetPropertyAction::ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context)
{
	const FString AssetPath = Params->GetStringField(TEXT("asset_path"));
	const FString PropertyName = Params->GetStringField(TEXT("property_name"));

	FString LoadError;
	UObject* Asset = UEEditorMCP_DataAssetUtils::LoadAssetFlexible(AssetPath, LoadError);
	if (!Asset)
	{
		return CreateErrorResponse(LoadError, TEXT("asset_not_found"));
	}

	FString ResolveError;
	UObject* PropertyContainer =
		UEEditorMCP_DataAssetUtils::ResolvePropertyContainer(Asset, ResolveError);
	if (!PropertyContainer)
	{
		return CreateErrorResponse(ResolveError, TEXT("property_container_unavailable"));
	}

	FProperty* Property =
		PropertyContainer->GetClass()->FindPropertyByName(*PropertyName);
	if (!Property)
	{
		return CreateErrorResponse(
			FString::Printf(
				TEXT("Property '%s' not found on '%s'"),
				*PropertyName,
				*PropertyContainer->GetClass()->GetName()),
			TEXT("property_not_found"));
	}

	const FString Value =
		UEEditorMCP_DataAssetUtils::ExportPropertyAsText(PropertyContainer, Property);

	TSharedPtr<FJsonObject> Result = MakeShared<FJsonObject>();
	Result->SetStringField(TEXT("asset_path"), Asset->GetPathName());
	Result->SetStringField(TEXT("asset_class"), Asset->GetClass()->GetName());
	Result->SetStringField(TEXT("property_owner_path"), PropertyContainer->GetPathName());
	Result->SetStringField(TEXT("property_owner_class"), PropertyContainer->GetClass()->GetName());
	Result->SetStringField(
		TEXT("property_source"),
		PropertyContainer == Asset ? TEXT("asset") : TEXT("blueprint_cdo"));
	Result->SetStringField(TEXT("property_name"), PropertyName);
	Result->SetStringField(TEXT("value"), Value);
	return CreateSuccessResponse(Result);
}

namespace UEEditorMCP_GameplayTagCDOUtils
{
	static TSharedPtr<FJsonValue> MakeStringValue(const FString& Value)
	{
		return MakeShared<FJsonValueString>(Value);
	}

	static FString ExportPropertyValue(FProperty* Property, const void* ValuePtr, const UObject* Owner)
	{
		if (Property == nullptr || ValuePtr == nullptr)
		{
			return FString();
		}

		FString Out;
		Property->ExportText_Direct(Out, ValuePtr, ValuePtr, const_cast<UObject*>(Owner), PPF_None);
		return Out;
	}

	static TArray<TSharedPtr<FJsonValue>> TagsToJsonArray(const TArray<FString>& Tags)
	{
		TArray<TSharedPtr<FJsonValue>> Values;
		for (const FString& Tag : Tags)
		{
			Values.Add(MakeStringValue(Tag));
		}
		return Values;
	}

	static void AddResult(const FString& PropertyPath, FProperty* Property, const FString& ValueText, const TArray<FString>& Tags, bool bIncludeEmpty, TArray<TSharedPtr<FJsonValue>>& OutProperties)
	{
		if (!bIncludeEmpty && Tags.IsEmpty())
		{
			return;
		}

		TSharedPtr<FJsonObject> Item = MakeShared<FJsonObject>();
		Item->SetStringField(TEXT("property_path"), PropertyPath);
		Item->SetStringField(TEXT("property_name"), Property ? Property->GetName() : PropertyPath);
		Item->SetStringField(TEXT("cpp_type"), Property ? Property->GetCPPType() : FString());
		Item->SetStringField(TEXT("value"), ValueText);
		Item->SetArrayField(TEXT("tags"), TagsToJsonArray(Tags));
		OutProperties.Add(MakeShared<FJsonValueObject>(Item));
	}

	static bool IsGameplayTagStruct(const FStructProperty* StructProperty)
	{
		return StructProperty != nullptr && StructProperty->Struct == FGameplayTag::StaticStruct();
	}

	static bool IsGameplayTagContainerStruct(const FStructProperty* StructProperty)
	{
		return StructProperty != nullptr && StructProperty->Struct == FGameplayTagContainer::StaticStruct();
	}

	static void CollectFromProperty(const FString& PropertyPath, FProperty* Property, void* ValuePtr, const UObject* Owner, bool bIncludeEmpty, TArray<TSharedPtr<FJsonValue>>& OutProperties, int32 Depth);

	static void CollectFromStruct(const FString& PropertyPath, UScriptStruct* Struct, void* StructValuePtr, const UObject* Owner, bool bIncludeEmpty, TArray<TSharedPtr<FJsonValue>>& OutProperties, int32 Depth)
	{
		if (Struct == nullptr || StructValuePtr == nullptr || Depth > 16)
		{
			return;
		}

		for (TFieldIterator<FProperty> It(Struct); It; ++It)
		{
			FProperty* ChildProperty = *It;
			void* ChildValuePtr = ChildProperty->ContainerPtrToValuePtr<void>(StructValuePtr);
			CollectFromProperty(PropertyPath + TEXT(".") + ChildProperty->GetName(), ChildProperty, ChildValuePtr, Owner, bIncludeEmpty, OutProperties, Depth + 1);
		}
	}

	static void CollectFromProperty(const FString& PropertyPath, FProperty* Property, void* ValuePtr, const UObject* Owner, bool bIncludeEmpty, TArray<TSharedPtr<FJsonValue>>& OutProperties, int32 Depth)
	{
		if (Property == nullptr || ValuePtr == nullptr || Depth > 16)
		{
			return;
		}

		if (FStructProperty* StructProperty = CastField<FStructProperty>(Property))
		{
			if (IsGameplayTagStruct(StructProperty))
			{
				const FGameplayTag* Tag = reinterpret_cast<const FGameplayTag*>(ValuePtr);
				TArray<FString> Tags;
				if (Tag != nullptr && Tag->IsValid())
				{
					Tags.Add(Tag->ToString());
				}
				AddResult(PropertyPath, Property, ExportPropertyValue(Property, ValuePtr, Owner), Tags, bIncludeEmpty, OutProperties);
				return;
			}

			if (IsGameplayTagContainerStruct(StructProperty))
			{
				const FGameplayTagContainer* Container = reinterpret_cast<const FGameplayTagContainer*>(ValuePtr);
				TArray<FGameplayTag> TagArray;
				if (Container != nullptr)
				{
					Container->GetGameplayTagArray(TagArray);
				}

				TArray<FString> Tags;
				for (const FGameplayTag& Tag : TagArray)
				{
					if (Tag.IsValid())
					{
						Tags.Add(Tag.ToString());
					}
				}
				AddResult(PropertyPath, Property, ExportPropertyValue(Property, ValuePtr, Owner), Tags, bIncludeEmpty, OutProperties);
				return;
			}

			CollectFromStruct(PropertyPath, StructProperty->Struct, ValuePtr, Owner, bIncludeEmpty, OutProperties, Depth + 1);
			return;
		}

		if (FArrayProperty* ArrayProperty = CastField<FArrayProperty>(Property))
		{
			FScriptArrayHelper Helper(ArrayProperty, ValuePtr);
			for (int32 Index = 0; Index < Helper.Num(); ++Index)
			{
				CollectFromProperty(FString::Printf(TEXT("%s[%d]"), *PropertyPath, Index), ArrayProperty->Inner, Helper.GetRawPtr(Index), Owner, bIncludeEmpty, OutProperties, Depth + 1);
			}
			return;
		}

		if (FSetProperty* SetProperty = CastField<FSetProperty>(Property))
		{
			FScriptSetHelper Helper(SetProperty, ValuePtr);
			int32 CompactIndex = 0;
			for (int32 Index = 0; Index < Helper.GetMaxIndex(); ++Index)
			{
				if (!Helper.IsValidIndex(Index))
				{
					continue;
				}
				CollectFromProperty(FString::Printf(TEXT("%s[%d]"), *PropertyPath, CompactIndex++), SetProperty->ElementProp, Helper.GetElementPtr(Index), Owner, bIncludeEmpty, OutProperties, Depth + 1);
			}
			return;
		}

		if (FMapProperty* MapProperty = CastField<FMapProperty>(Property))
		{
			FScriptMapHelper Helper(MapProperty, ValuePtr);
			int32 CompactIndex = 0;
			for (int32 Index = 0; Index < Helper.GetMaxIndex(); ++Index)
			{
				if (!Helper.IsValidIndex(Index))
				{
					continue;
				}
				const FString KeyPath = FString::Printf(TEXT("%s{key:%d}"), *PropertyPath, CompactIndex);
				const FString ValuePath = FString::Printf(TEXT("%s{value:%d}"), *PropertyPath, CompactIndex);
				CollectFromProperty(KeyPath, MapProperty->KeyProp, Helper.GetKeyPtr(Index), Owner, bIncludeEmpty, OutProperties, Depth + 1);
				CollectFromProperty(ValuePath, MapProperty->ValueProp, Helper.GetValuePtr(Index), Owner, bIncludeEmpty, OutProperties, Depth + 1);
				++CompactIndex;
			}
		}
	}
}

bool FGetBlueprintCDOGameplayTagsAction::Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError)
{
	FString AssetPath;
	if (!GetRequiredString(Params, TEXT("asset_path"), AssetPath, OutError)) return false;
	return true;
}

TSharedPtr<FJsonObject> FGetBlueprintCDOGameplayTagsAction::ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context)
{
	const FString AssetPath = Params->GetStringField(TEXT("asset_path"));
	const bool bIncludeEmpty = GetOptionalBool(Params, TEXT("include_empty"), false);

	FString LoadError;
	UObject* Asset = UEEditorMCP_DataAssetUtils::LoadAssetFlexible(AssetPath, LoadError);
	if (!Asset)
	{
		return CreateErrorResponse(LoadError, TEXT("asset_not_found"));
	}

	UBlueprint* Blueprint = Cast<UBlueprint>(Asset);
	UClass* TargetClass = nullptr;
	if (Blueprint != nullptr)
	{
		TargetClass = Blueprint->GeneratedClass;
	}
	else
	{
		TargetClass = Cast<UClass>(Asset);
	}

	if (TargetClass == nullptr)
	{
		return CreateErrorResponse(
			FString::Printf(TEXT("Asset is not a Blueprint or generated class: %s (%s)"), *Asset->GetPathName(), *Asset->GetClass()->GetName()),
			TEXT("invalid_asset_type"));
	}

	UObject* CDO = TargetClass->GetDefaultObject();
	if (CDO == nullptr)
	{
		return CreateErrorResponse(
			FString::Printf(TEXT("Class has no default object: %s"), *TargetClass->GetPathName()),
			TEXT("cdo_not_found"));
	}

	TArray<TSharedPtr<FJsonValue>> Properties;
	for (TFieldIterator<FProperty> It(TargetClass); It; ++It)
	{
		FProperty* Property = *It;
		void* ValuePtr = Property->ContainerPtrToValuePtr<void>(CDO);
		UEEditorMCP_GameplayTagCDOUtils::CollectFromProperty(Property->GetName(), Property, ValuePtr, CDO, bIncludeEmpty, Properties, 0);
	}

	TSet<FString> UniqueTags;
	for (const TSharedPtr<FJsonValue>& Value : Properties)
	{
		const TSharedPtr<FJsonObject>* Obj = nullptr;
		if (!Value.IsValid() || !Value->TryGetObject(Obj) || Obj == nullptr || !Obj->IsValid())
		{
			continue;
		}

		const TArray<TSharedPtr<FJsonValue>>* Tags = nullptr;
		if ((*Obj)->TryGetArrayField(TEXT("tags"), Tags) && Tags != nullptr)
		{
			for (const TSharedPtr<FJsonValue>& TagValue : *Tags)
			{
				FString Tag;
				if (TagValue.IsValid() && TagValue->TryGetString(Tag))
				{
					UniqueTags.Add(Tag);
				}
			}
		}
	}

	TArray<FString> SortedTags = UniqueTags.Array();
	SortedTags.Sort();
	TArray<TSharedPtr<FJsonValue>> TagsJson;
	for (const FString& Tag : SortedTags)
	{
		TagsJson.Add(MakeShared<FJsonValueString>(Tag));
	}

	TSharedPtr<FJsonObject> Result = MakeShared<FJsonObject>();
	Result->SetStringField(TEXT("asset_path"), Asset->GetPathName());
	Result->SetStringField(TEXT("asset_class"), Asset->GetClass()->GetName());
	Result->SetStringField(TEXT("generated_class"), TargetClass->GetPathName());
	Result->SetStringField(TEXT("cdo_name"), CDO->GetName());
	Result->SetBoolField(TEXT("include_empty"), bIncludeEmpty);
	Result->SetNumberField(TEXT("property_count"), Properties.Num());
	Result->SetNumberField(TEXT("unique_tag_count"), SortedTags.Num());
	Result->SetArrayField(TEXT("unique_tags"), TagsJson);
	Result->SetArrayField(TEXT("properties"), Properties);
	return CreateSuccessResponse(Result);
}

// ============================================================================
// FConfigureGameplayEffectTargetTagsAction
// ============================================================================

bool FConfigureGameplayEffectTargetTagsAction::Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError)
{
	FString AssetPath;
	FString TagName;
	if (!GetRequiredString(Params, TEXT("asset_path"), AssetPath, OutError)) return false;
	if (!GetRequiredString(Params, TEXT("tag_name"), TagName, OutError)) return false;
	return true;
}

TSharedPtr<FJsonObject> FConfigureGameplayEffectTargetTagsAction::ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context)
{
	const FString AssetPath = Params->GetStringField(TEXT("asset_path"));
	const FString TagName = Params->GetStringField(TEXT("tag_name"));
	const bool bSave = GetOptionalBool(Params, TEXT("save"), true);

	FString LoadError;
	UObject* Asset = UEEditorMCP_DataAssetUtils::LoadAssetFlexible(AssetPath, LoadError);
	UBlueprint* Blueprint = Cast<UBlueprint>(Asset);
	if (!Blueprint)
	{
		return CreateErrorResponse(
			FString::Printf(TEXT("Asset is not a GameplayEffect Blueprint: %s"), *AssetPath),
			TEXT("invalid_asset_type"));
	}

	UClass* GeneratedClass = Blueprint->GeneratedClass;
	UGameplayEffect* EffectCDO = GeneratedClass ? Cast<UGameplayEffect>(GeneratedClass->GetDefaultObject()) : nullptr;
	if (!EffectCDO)
	{
		return CreateErrorResponse(
			FString::Printf(TEXT("Blueprint does not generate a GameplayEffect class: %s"), *Blueprint->GetPathName()),
			TEXT("invalid_gameplay_effect"));
	}

	const FGameplayTag Tag = FGameplayTag::RequestGameplayTag(FName(*TagName), false);
	if (!Tag.IsValid())
	{
		return CreateErrorResponse(
			FString::Printf(TEXT("GameplayTag not found: %s"), *TagName),
			TEXT("invalid_gameplay_tag"));
	}

	Blueprint->Modify();
	EffectCDO->Modify();

	UTargetTagsGameplayEffectComponent& TargetTagsComponent = EffectCDO->FindOrAddComponent<UTargetTagsGameplayEffectComponent>();
	TargetTagsComponent.Modify();

	FInheritedTagContainer TargetTagChanges = TargetTagsComponent.GetConfiguredTargetTagChanges();
	const TArray<TSharedPtr<FJsonValue>>* ReplacementTagValues = nullptr;
	const bool bReplaceTags = Params->TryGetArrayField(TEXT("replace_tag_names"), ReplacementTagValues) && ReplacementTagValues != nullptr;
	TArray<FGameplayTag> ReplacementTags;

	if (bReplaceTags)
	{
		if (ReplacementTagValues->IsEmpty())
		{
			return CreateErrorResponse(TEXT("replace_tag_names must contain at least one GameplayTag"), TEXT("invalid_params"));
		}

		for (const TSharedPtr<FJsonValue>& ReplacementTagValue : *ReplacementTagValues)
		{
			if (!ReplacementTagValue.IsValid() || ReplacementTagValue->Type != EJson::String)
			{
				return CreateErrorResponse(TEXT("replace_tag_names must be an array of strings"), TEXT("invalid_params"));
			}

			const FString ReplacementTagName = ReplacementTagValue->AsString();
			const FGameplayTag ReplacementTag = FGameplayTag::RequestGameplayTag(FName(*ReplacementTagName), false);
			if (!ReplacementTag.IsValid())
			{
				return CreateErrorResponse(
					FString::Printf(TEXT("GameplayTag not found: %s"), *ReplacementTagName),
					TEXT("invalid_gameplay_tag"));
			}

			ReplacementTags.Add(ReplacementTag);
		}
	}

	const bool bAlreadyHadTag = TargetTagChanges.Added.HasTagExact(Tag);
	if (bReplaceTags)
	{
		TargetTagChanges = FInheritedTagContainer{};
		for (const FGameplayTag& ReplacementTag : ReplacementTags)
		{
			TargetTagChanges.AddTag(ReplacementTag);
		}
	}
	else
	{
		TargetTagChanges.AddTag(Tag);
	}
	TargetTagsComponent.SetAndApplyTargetTagChanges(TargetTagChanges);

	FProperty* ChangedProperty = UTargetTagsGameplayEffectComponent::StaticClass()->FindPropertyByName(TEXT("InheritableGrantedTagsContainer"));
	FPropertyChangedEvent ChangeEvent(ChangedProperty, EPropertyChangeType::ValueSet);
	TargetTagsComponent.PostEditChangeProperty(ChangeEvent);
	EffectCDO->PostEditChange();

	UPackage* Package = Blueprint->GetOutermost();
	if (Package)
	{
		Package->SetDirtyFlag(true);
	}

	bool bSaved = false;
	FString SaveError;
	if (bSave)
	{
		bSaved = UEEditorMCP_DataAssetUtils::SaveAssetPackage(Blueprint, SaveError);
	}

	const FGameplayTagContainer& GrantedTags = EffectCDO->GetGrantedTags();

	TSharedPtr<FJsonObject> Result = MakeShared<FJsonObject>();
	Result->SetStringField(TEXT("asset_path"), Blueprint->GetPathName());
	Result->SetStringField(TEXT("generated_class"), GeneratedClass->GetPathName());
	Result->SetStringField(TEXT("tag_name"), Tag.ToString());
	Result->SetBoolField(TEXT("already_had_tag"), bAlreadyHadTag);
	Result->SetBoolField(TEXT("replace_mode"), bReplaceTags);
	if (bReplaceTags)
	{
		TArray<TSharedPtr<FJsonValue>> ReplacementTagNamesJson;
		for (const FGameplayTag& ReplacementTag : ReplacementTags)
		{
			ReplacementTagNamesJson.Add(MakeShared<FJsonValueString>(ReplacementTag.ToString()));
		}
		Result->SetArrayField(TEXT("replacement_tag_names"), ReplacementTagNamesJson);
	}
	Result->SetStringField(TEXT("component"), TargetTagsComponent.GetClass()->GetName());
	Result->SetStringField(TEXT("granted_tags"), GrantedTags.ToStringSimple());
	Result->SetBoolField(TEXT("saved"), bSaved);
	if (bSave && !bSaved)
	{
		Result->SetStringField(TEXT("save_error"), SaveError);
	}

	UE_LOG(LogMCP, Log, TEXT("configure_gameplay_effect_target_tags: %s grants %s (alreadyHad=%d replace=%d saved=%d)"),
		*Blueprint->GetPathName(), *Tag.ToString(), bAlreadyHadTag ? 1 : 0, bReplaceTags ? 1 : 0, bSaved ? 1 : 0);

	return CreateSuccessResponse(Result);
}

// ============================================================================
// FConfigureGameplayEffectIgnoreTagsAction
// ============================================================================

bool FConfigureGameplayEffectIgnoreTagsAction::Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError)
{
	FString AssetPath;
	FString TagName;
	if (!GetRequiredString(Params, TEXT("asset_path"), AssetPath, OutError)) return false;
	if (!GetRequiredString(Params, TEXT("tag_name"), TagName, OutError)) return false;
	return true;
}

TSharedPtr<FJsonObject> FConfigureGameplayEffectIgnoreTagsAction::ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context)
{
	const FString AssetPath = Params->GetStringField(TEXT("asset_path"));
	const FString TagName = Params->GetStringField(TEXT("tag_name"));
	const bool bSave = GetOptionalBool(Params, TEXT("save"), true);

	FString LoadError;
	UObject* Asset = UEEditorMCP_DataAssetUtils::LoadAssetFlexible(AssetPath, LoadError);
	UBlueprint* Blueprint = Cast<UBlueprint>(Asset);
	if (!Blueprint)
	{
		return CreateErrorResponse(
			FString::Printf(TEXT("Asset is not a GameplayEffect Blueprint: %s"), *AssetPath),
			TEXT("invalid_asset_type"));
	}

	UClass* GeneratedClass = Blueprint->GeneratedClass;
	UGameplayEffect* EffectCDO = GeneratedClass ? Cast<UGameplayEffect>(GeneratedClass->GetDefaultObject()) : nullptr;
	if (!EffectCDO)
	{
		return CreateErrorResponse(
			FString::Printf(TEXT("Blueprint does not generate a GameplayEffect class: %s"), *Blueprint->GetPathName()),
			TEXT("invalid_gameplay_effect"));
	}

	const FGameplayTag Tag = FGameplayTag::RequestGameplayTag(FName(*TagName), false);
	if (!Tag.IsValid())
	{
		return CreateErrorResponse(
			FString::Printf(TEXT("GameplayTag not found: %s"), *TagName),
			TEXT("invalid_gameplay_tag"));
	}

	Blueprint->Modify();
	EffectCDO->Modify();

	UTargetTagRequirementsGameplayEffectComponent& ReqComponent = EffectCDO->FindOrAddComponent<UTargetTagRequirementsGameplayEffectComponent>();
	ReqComponent.Modify();

	const bool bAlreadyHadTag = ReqComponent.ApplicationTagRequirements.IgnoreTags.HasTagExact(Tag);
	ReqComponent.ApplicationTagRequirements.IgnoreTags.AddTag(Tag);

	FProperty* ChangedProperty = UTargetTagRequirementsGameplayEffectComponent::StaticClass()->FindPropertyByName(TEXT("ApplicationTagRequirements"));
	FPropertyChangedEvent ChangeEvent(ChangedProperty, EPropertyChangeType::ValueSet);
	ReqComponent.PostEditChangeProperty(ChangeEvent);
	EffectCDO->PostEditChange();

	UPackage* Package = Blueprint->GetOutermost();
	if (Package)
	{
		Package->SetDirtyFlag(true);
	}

	bool bSaved = false;
	FString SaveError;
	if (bSave)
	{
		bSaved = UEEditorMCP_DataAssetUtils::SaveAssetPackage(Blueprint, SaveError);
	}

	TSharedPtr<FJsonObject> Result = MakeShared<FJsonObject>();
	Result->SetStringField(TEXT("asset_path"), Blueprint->GetPathName());
	Result->SetStringField(TEXT("generated_class"), GeneratedClass->GetPathName());
	Result->SetStringField(TEXT("tag_name"), Tag.ToString());
	Result->SetBoolField(TEXT("already_had_tag"), bAlreadyHadTag);
	Result->SetStringField(TEXT("component"), ReqComponent.GetClass()->GetName());
	Result->SetStringField(TEXT("ignore_tags"), ReqComponent.ApplicationTagRequirements.IgnoreTags.ToStringSimple());
	Result->SetBoolField(TEXT("saved"), bSaved);
	if (bSave && !bSaved)
	{
		Result->SetStringField(TEXT("save_error"), SaveError);
	}

	UE_LOG(LogMCP, Log, TEXT("configure_gameplay_effect_ignore_tags: %s ignores %s (alreadyHad=%d saved=%d)"),
		*Blueprint->GetPathName(), *Tag.ToString(), bAlreadyHadTag ? 1 : 0, bSaved ? 1 : 0);

	return CreateSuccessResponse(Result);
}
// ============================================================================
// FSetGameplayEffectModifierScalableFloatAction
// ============================================================================

namespace UEEditorMCP_GameplayEffectModifierUtils
{
	static bool SetScalableFloatRawValue(FGameplayEffectModifierMagnitude& ModifierMagnitude, double NewValue, bool bWrite, double& OutPreviousValue, FString& OutError)
	{
		UScriptStruct* MagnitudeStruct = FGameplayEffectModifierMagnitude::StaticStruct();
		UScriptStruct* ScalableFloatStruct = FScalableFloat::StaticStruct();
		if (!MagnitudeStruct || !ScalableFloatStruct)
		{
			OutError = TEXT("GameplayEffect magnitude reflection data is unavailable.");
			return false;
		}

		FStructProperty* ScalableFloatProperty = CastField<FStructProperty>(
			MagnitudeStruct->FindPropertyByName(TEXT("ScalableFloatMagnitude")));
		if (!ScalableFloatProperty || ScalableFloatProperty->Struct != ScalableFloatStruct)
		{
			OutError = TEXT("ScalableFloatMagnitude property was not found on FGameplayEffectModifierMagnitude.");
			return false;
		}

		FProperty* ValueProperty = ScalableFloatStruct->FindPropertyByName(TEXT("Value"));
		FNumericProperty* NumericValueProperty = CastField<FNumericProperty>(ValueProperty);
		if (!NumericValueProperty || !NumericValueProperty->IsFloatingPoint())
		{
			OutError = TEXT("Value property was not found on FScalableFloat or is not floating point.");
			return false;
		}

		void* ScalableFloatAddress = ScalableFloatProperty->ContainerPtrToValuePtr<void>(&ModifierMagnitude);
		void* ValueAddress = NumericValueProperty->ContainerPtrToValuePtr<void>(ScalableFloatAddress);
		OutPreviousValue = NumericValueProperty->GetFloatingPointPropertyValue(ValueAddress);
		if (bWrite)
		{
			NumericValueProperty->SetFloatingPointPropertyValue(ValueAddress, NewValue);
		}
		return true;
	}

	static FString MagnitudeTypeToString(EGameplayEffectMagnitudeCalculation Type)
	{
		switch (Type)
		{
		case EGameplayEffectMagnitudeCalculation::ScalableFloat:
			return TEXT("ScalableFloat");
		case EGameplayEffectMagnitudeCalculation::AttributeBased:
			return TEXT("AttributeBased");
		case EGameplayEffectMagnitudeCalculation::CustomCalculationClass:
			return TEXT("CustomCalculationClass");
		case EGameplayEffectMagnitudeCalculation::SetByCaller:
			return TEXT("SetByCaller");
		default:
			return TEXT("Unknown");
		}
	}
}

bool FSetGameplayEffectModifierScalableFloatAction::Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError)
{
	FString AssetPath;
	const bool bHasSingleAsset = Params.IsValid() && Params->TryGetStringField(TEXT("asset_path"), AssetPath) && !AssetPath.IsEmpty();
	const TArray<TSharedPtr<FJsonValue>>* AssetPaths = nullptr;
	const bool bHasAssetArray = Params.IsValid() && Params->TryGetArrayField(TEXT("asset_paths"), AssetPaths) && AssetPaths && AssetPaths->Num() > 0;
	if (!bHasSingleAsset && !bHasAssetArray)
	{
		OutError = TEXT("Either 'asset_path' or non-empty 'asset_paths' is required.");
		return false;
	}
	return true;
}

TSharedPtr<FJsonObject> FSetGameplayEffectModifierScalableFloatAction::ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context)
{
	TArray<FString> AssetPaths;
	FString SingleAssetPath;
	if (Params->TryGetStringField(TEXT("asset_path"), SingleAssetPath) && !SingleAssetPath.IsEmpty())
	{
		AssetPaths.Add(SingleAssetPath);
	}

	const TArray<TSharedPtr<FJsonValue>>* AssetPathValues = nullptr;
	if (Params->TryGetArrayField(TEXT("asset_paths"), AssetPathValues) && AssetPathValues)
	{
		for (const TSharedPtr<FJsonValue>& AssetPathValue : *AssetPathValues)
		{
			if (AssetPathValue.IsValid() && AssetPathValue->Type == EJson::String)
			{
				const FString AssetPath = AssetPathValue->AsString();
				if (!AssetPath.IsEmpty())
				{
					AssetPaths.AddUnique(AssetPath);
				}
			}
		}
	}

	const double NewValue = GetOptionalNumber(Params, TEXT("new_value"), 1.0);
	const bool bSave = GetOptionalBool(Params, TEXT("save"), true);
	const bool bDryRun = GetOptionalBool(Params, TEXT("dry_run"), false);

	TArray<TSharedPtr<FJsonValue>> AssetResults;
	int32 TotalModifierCount = 0;
	int32 TotalScalableFloatCount = 0;
	int32 TotalChangedCount = 0;
	int32 FailedAssetCount = 0;

	FProperty* ModifiersProperty = UGameplayEffect::StaticClass()->FindPropertyByName(GET_MEMBER_NAME_CHECKED(UGameplayEffect, Modifiers));

	for (const FString& AssetPath : AssetPaths)
	{
		TSharedPtr<FJsonObject> AssetResult = MakeShared<FJsonObject>();
		AssetResult->SetStringField(TEXT("requested_asset_path"), AssetPath);

		FString LoadError;
		UObject* Asset = UEEditorMCP_DataAssetUtils::LoadAssetFlexible(AssetPath, LoadError);
		UBlueprint* Blueprint = Cast<UBlueprint>(Asset);
		if (!Blueprint)
		{
			AssetResult->SetBoolField(TEXT("success"), false);
			AssetResult->SetStringField(TEXT("error_type"), TEXT("asset_not_gameplay_effect_blueprint"));
			AssetResult->SetStringField(TEXT("error"), Asset ? FString::Printf(TEXT("Asset is not a Blueprint: %s"), *Asset->GetPathName()) : LoadError);
			AssetResults.Add(MakeShared<FJsonValueObject>(AssetResult));
			++FailedAssetCount;
			continue;
		}

		UBlueprintGeneratedClass* GeneratedClass = Cast<UBlueprintGeneratedClass>(Blueprint->GeneratedClass);
		UGameplayEffect* EffectCDO = GeneratedClass ? Cast<UGameplayEffect>(GeneratedClass->GetDefaultObject()) : nullptr;
		if (!EffectCDO)
		{
			AssetResult->SetBoolField(TEXT("success"), false);
			AssetResult->SetStringField(TEXT("asset_path"), Blueprint->GetPathName());
			AssetResult->SetStringField(TEXT("error_type"), TEXT("generated_class_not_gameplay_effect"));
			AssetResult->SetStringField(TEXT("error"), FString::Printf(TEXT("Blueprint does not generate a GameplayEffect class: %s"), *Blueprint->GetPathName()));
			AssetResults.Add(MakeShared<FJsonValueObject>(AssetResult));
			++FailedAssetCount;
			continue;
		}

		TArray<TSharedPtr<FJsonValue>> ModifierResults;
		int32 AssetScalableFloatCount = 0;
		int32 AssetChangedCount = 0;

		bool bStartedEdit = false;

		for (int32 ModifierIndex = 0; ModifierIndex < EffectCDO->Modifiers.Num(); ++ModifierIndex)
		{
			FGameplayModifierInfo& Modifier = EffectCDO->Modifiers[ModifierIndex];
			const EGameplayEffectMagnitudeCalculation MagnitudeType = Modifier.ModifierMagnitude.GetMagnitudeCalculationType();

			TSharedPtr<FJsonObject> ModifierResult = MakeShared<FJsonObject>();
			ModifierResult->SetNumberField(TEXT("index"), ModifierIndex);
			ModifierResult->SetStringField(TEXT("attribute"), Modifier.Attribute.GetName());
			ModifierResult->SetStringField(TEXT("magnitude_type"), UEEditorMCP_GameplayEffectModifierUtils::MagnitudeTypeToString(MagnitudeType));

			++TotalModifierCount;
			if (MagnitudeType != EGameplayEffectMagnitudeCalculation::ScalableFloat)
			{
				ModifierResult->SetBoolField(TEXT("skipped"), true);
				ModifierResult->SetStringField(TEXT("skip_reason"), TEXT("magnitude is not ScalableFloat"));
				ModifierResults.Add(MakeShared<FJsonValueObject>(ModifierResult));
				continue;
			}

			++AssetScalableFloatCount;
			++TotalScalableFloatCount;

			double PreviousValue = 0.0;
			FString SetError;
			if (!UEEditorMCP_GameplayEffectModifierUtils::SetScalableFloatRawValue(Modifier.ModifierMagnitude, NewValue, false, PreviousValue, SetError))
			{
				ModifierResult->SetBoolField(TEXT("success"), false);
				ModifierResult->SetStringField(TEXT("error"), SetError);
				ModifierResults.Add(MakeShared<FJsonValueObject>(ModifierResult));
				continue;
			}

			const bool bWouldChange = !FMath::IsNearlyEqual(static_cast<float>(PreviousValue), static_cast<float>(NewValue));
			if (bWouldChange && !bDryRun)
			{
				if (!bStartedEdit)
				{
					Blueprint->Modify();
					EffectCDO->PreEditChange(ModifiersProperty);
					EffectCDO->Modify();
					bStartedEdit = true;
				}

				if (!UEEditorMCP_GameplayEffectModifierUtils::SetScalableFloatRawValue(Modifier.ModifierMagnitude, NewValue, true, PreviousValue, SetError))
				{
					ModifierResult->SetBoolField(TEXT("success"), false);
					ModifierResult->SetStringField(TEXT("error"), SetError);
					ModifierResults.Add(MakeShared<FJsonValueObject>(ModifierResult));
					continue;
				}
			}
			ModifierResult->SetBoolField(TEXT("success"), true);
			ModifierResult->SetBoolField(TEXT("skipped"), false);
			ModifierResult->SetBoolField(TEXT("changed"), bWouldChange && !bDryRun);
			ModifierResult->SetBoolField(TEXT("would_change"), bWouldChange);
			ModifierResult->SetNumberField(TEXT("previous_value"), PreviousValue);
			ModifierResult->SetNumberField(TEXT("new_value"), NewValue);
			ModifierResults.Add(MakeShared<FJsonValueObject>(ModifierResult));

			UE_LOG(LogMCP, Log, TEXT("set_gameplay_effect_modifier_scalable_float: asset=%s modifier=%d attribute=%s op=%d previous=%.6f new=%.6f wouldChange=%d changed=%d dryRun=%d"),
				*Blueprint->GetPathName(), ModifierIndex, *Modifier.Attribute.GetName(), static_cast<int32>(Modifier.ModifierOp),
				PreviousValue, NewValue, bWouldChange ? 1 : 0, (bWouldChange && !bDryRun) ? 1 : 0, bDryRun ? 1 : 0);

			if (bWouldChange)
			{
				++AssetChangedCount;
				if (!bDryRun)
				{
					++TotalChangedCount;
				}
			}
		}

		bool bSaved = false;
		FString SaveError;
		if (!bDryRun && AssetChangedCount > 0)
		{
			if (ModifiersProperty)
			{
				FPropertyChangedEvent ChangeEvent(ModifiersProperty, EPropertyChangeType::ValueSet);
				EffectCDO->PostEditChangeProperty(ChangeEvent);
			}
			if (UPackage* Package = Blueprint->GetOutermost())
			{
				Package->SetDirtyFlag(true);
			}
			if (bSave)
			{
				bSaved = UEEditorMCP_DataAssetUtils::SaveAssetPackage(Blueprint, SaveError);
			}
		}

		AssetResult->SetBoolField(TEXT("success"), true);
		AssetResult->SetStringField(TEXT("asset_path"), Blueprint->GetPathName());
		AssetResult->SetStringField(TEXT("generated_class"), GeneratedClass->GetPathName());
		AssetResult->SetNumberField(TEXT("modifier_count"), EffectCDO->Modifiers.Num());
		AssetResult->SetNumberField(TEXT("scalable_float_count"), AssetScalableFloatCount);
		AssetResult->SetNumberField(TEXT("changed_count"), bDryRun ? 0 : AssetChangedCount);
		AssetResult->SetNumberField(TEXT("would_change_count"), AssetChangedCount);
		AssetResult->SetBoolField(TEXT("saved"), bSaved);
		AssetResult->SetBoolField(TEXT("dry_run"), bDryRun);
		if (bSave && !bDryRun && AssetChangedCount > 0 && !bSaved)
		{
			AssetResult->SetStringField(TEXT("save_error"), SaveError);
		}
		AssetResult->SetArrayField(TEXT("modifiers"), ModifierResults);
		AssetResults.Add(MakeShared<FJsonValueObject>(AssetResult));
	}

	TSharedPtr<FJsonObject> Result = MakeShared<FJsonObject>();
	Result->SetNumberField(TEXT("asset_count"), AssetPaths.Num());
	Result->SetNumberField(TEXT("failed_asset_count"), FailedAssetCount);
	Result->SetNumberField(TEXT("modifier_count"), TotalModifierCount);
	Result->SetNumberField(TEXT("scalable_float_count"), TotalScalableFloatCount);
	Result->SetNumberField(TEXT("changed_count"), TotalChangedCount);
	Result->SetNumberField(TEXT("new_value"), NewValue);
	Result->SetBoolField(TEXT("dry_run"), bDryRun);
	Result->SetBoolField(TEXT("save_requested"), bSave);
	Result->SetArrayField(TEXT("assets"), AssetResults);

	UE_LOG(LogMCP, Log, TEXT("set_gameplay_effect_modifier_scalable_float: assets=%d modifiers=%d scalable=%d changed=%d newValue=%.3f dryRun=%d"),
		AssetPaths.Num(), TotalModifierCount, TotalScalableFloatCount, TotalChangedCount, NewValue, bDryRun ? 1 : 0);

	return CreateSuccessResponse(Result);
}
// ============================================================================
// FSaveLoadedAssetAction
// 通过 UEditorAssetSubsystem 走 GUI Save 的同条路径，强制保存已加载资产。
// 用于绕过 compile_blueprint 内置 SavePackage 的 WidgetBlueprintExtension
// 序列化时序问题。
// ============================================================================

bool FSaveLoadedAssetAction::Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError)
{
	FString AssetPath;
	if (!GetRequiredString(Params, TEXT("asset_path"), AssetPath, OutError)) return false;
	return true;
}

TSharedPtr<FJsonObject> FSaveLoadedAssetAction::ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context)
{
	const FString AssetPath = Params->GetStringField(TEXT("asset_path"));
	const bool bOnlyIfDirty = GetOptionalBool(Params, TEXT("only_if_dirty"), false);

	FString LoadError;
	UObject* Asset = UEEditorMCP_DataAssetUtils::LoadAssetFlexible(AssetPath, LoadError);
	if (!Asset)
	{
		return CreateErrorResponse(LoadError, TEXT("asset_not_found"));
	}

	if (!GEditor)
	{
		return CreateErrorResponse(TEXT("GEditor is not available"), TEXT("editor_not_ready"));
	}

	UEditorAssetSubsystem* AssetSS = GEditor->GetEditorSubsystem<UEditorAssetSubsystem>();
	if (!AssetSS)
	{
		return CreateErrorResponse(TEXT("EditorAssetSubsystem unavailable"), TEXT("subsystem_error"));
	}

	const bool bSaved = AssetSS->SaveLoadedAsset(Asset, bOnlyIfDirty);

	TSharedPtr<FJsonObject> Result = MakeShared<FJsonObject>();
	Result->SetStringField(TEXT("asset_path"), Asset->GetPathName());
	Result->SetStringField(TEXT("asset_class"), Asset->GetClass()->GetName());
	Result->SetBoolField(TEXT("saved"), bSaved);

	UE_LOG(LogMCP, Log, TEXT("save_loaded_asset: %s saved=%d only_if_dirty=%d"),
		*Asset->GetPathName(), bSaved ? 1 : 0, bOnlyIfDirty ? 1 : 0);

	return CreateSuccessResponse(Result);
}


// ============================================================================
// FCreateDataAssetAction
// 创建一个 UDataAsset 派生类实例。
// ============================================================================

bool FCreateDataAssetAction::Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError)
{
	FString AssetName, PackagePath, AssetClass;
	if (!GetRequiredString(Params, TEXT("asset_name"), AssetName, OutError)) return false;
	if (!GetRequiredString(Params, TEXT("package_path"), PackagePath, OutError)) return false;
	if (!GetRequiredString(Params, TEXT("asset_class"), AssetClass, OutError)) return false;
	return true;
}

TSharedPtr<FJsonObject> FCreateDataAssetAction::ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context)
{
	const FString AssetName = Params->GetStringField(TEXT("asset_name"));
	const FString PackagePath = Params->GetStringField(TEXT("package_path"));
	const FString AssetClassStr = Params->GetStringField(TEXT("asset_class"));
	const bool bSave = GetOptionalBool(Params, TEXT("save"), true);

	// Resolve the DataAsset class
	UClass* DataAssetClass = nullptr;

	// Try /Script/... format first
	if (AssetClassStr.StartsWith(TEXT("/Script/")))
	{
		DataAssetClass = FindObject<UClass>(nullptr, *AssetClassStr);
	}
	// Try blueprint _C path
	else if (AssetClassStr.EndsWith(TEXT("_C")) || AssetClassStr.Contains(TEXT("/Game/")))
	{
		DataAssetClass = LoadObject<UClass>(nullptr, *AssetClassStr);
	}
	// Short name: try FindFirstObject then /Script/P111 fallback
	else
	{
		DataAssetClass = FindFirstObject<UClass>(*AssetClassStr, EFindFirstObjectOptions::ExactClass);
		if (!DataAssetClass)
		{
			const FString ScriptPath = FString::Printf(TEXT("/Script/P111.%s"), *AssetClassStr);
			DataAssetClass = FindObject<UClass>(nullptr, *ScriptPath);
		}
		if (!DataAssetClass)
		{
			const FString ScriptPath2 = FString::Printf(TEXT("/Script/Engine.%s"), *AssetClassStr);
			DataAssetClass = FindObject<UClass>(nullptr, *ScriptPath2);
		}
	}

	if (!DataAssetClass)
	{
		return CreateErrorResponse(
			FString::Printf(TEXT("Could not resolve DataAsset class: %s"), *AssetClassStr),
			TEXT("class_not_found"));
	}

	// Verify it's a DataAsset-derived class
	if (!DataAssetClass->IsChildOf(UDataAsset::StaticClass()))
	{
		return CreateErrorResponse(
			FString::Printf(TEXT("Class '%s' is not a UDataAsset derivative"), *AssetClassStr),
			TEXT("invalid_class"));
	}

	// Build full asset path
	const FString FullAssetPath = FString::Printf(TEXT("%s/%s"), *PackagePath, *AssetName);

	// Check if already exists
	UObject* Existing = LoadObject<UObject>(nullptr, *FullAssetPath);
	if (Existing)
	{
		TSharedPtr<FJsonObject> Result = MakeShared<FJsonObject>();
		Result->SetStringField(TEXT("asset_path"), Existing->GetPathName());
		Result->SetStringField(TEXT("asset_class"), Existing->GetClass()->GetName());
		Result->SetBoolField(TEXT("already_exists"), true);
		Result->SetBoolField(TEXT("saved"), false);
		return CreateSuccessResponse(Result);
	}

	// Create the asset using UObject framework
	UPackage* Package = CreatePackage(*FString::Printf(TEXT("%s/%s"), *PackagePath, *AssetName));
	if (!Package)
	{
		return CreateErrorResponse(
			FString::Printf(TEXT("CreatePackage failed for %s/%s"), *PackagePath, *AssetName),
			TEXT("create_package_failed"));
	}

	UObject* NewAsset = NewObject<UObject>(Package, DataAssetClass, *AssetName, RF_Public | RF_Standalone | RF_Transactional);
	if (!NewAsset)
	{
		return CreateErrorResponse(
			FString::Printf(TEXT("NewObject failed for %s as %s"), *AssetName, *AssetClassStr),
			TEXT("create_failed"));
	}

	// Notify the asset registry
	FAssetRegistryModule::AssetCreated(NewAsset);

	// Mark the package dirty
	Package->MarkPackageDirty();

	// Save if requested
	bool bSaved = false;
	if (bSave)
	{
		UPackage* Pkg = NewAsset->GetOutermost();
		if (Pkg)
		{
			const FString PackageFileName = FPackageName::LongPackageNameToFilename(Pkg->GetName(), FPackageName::GetAssetPackageExtension());
			FSavePackageArgs SaveArgs;
			SaveArgs.TopLevelFlags = RF_Public | RF_Standalone;
			bSaved = GEditor->SavePackage(Pkg, NewAsset, *PackageFileName, SaveArgs);
		}
	}

	TSharedPtr<FJsonObject> Result = MakeShared<FJsonObject>();
	Result->SetStringField(TEXT("asset_path"), NewAsset->GetPathName());
	Result->SetStringField(TEXT("asset_class"), NewAsset->GetClass()->GetName());
	Result->SetBoolField(TEXT("already_exists"), false);
	Result->SetBoolField(TEXT("saved"), bSaved);

	UE_LOG(LogMCP, Log, TEXT("create_data_asset: %s class=%s saved=%d"),
		*NewAsset->GetPathName(), *NewAsset->GetClass()->GetName(), bSaved ? 1 : 0);

	return CreateSuccessResponse(Result);
}


// ============================================================================
// FCreateDataTableAction
// 创建 DataTable 并绑定 RowStruct，供配置表自动化迁移使用。
// ============================================================================

bool FCreateDataTableAction::Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError)
{
	FString AssetName, PackagePath, RowStructPath;
	if (!GetRequiredString(Params, TEXT("asset_name"), AssetName, OutError)) return false;
	if (!GetRequiredString(Params, TEXT("package_path"), PackagePath, OutError)) return false;
	if (!GetRequiredString(Params, TEXT("row_struct"), RowStructPath, OutError)) return false;
	return true;
}

TSharedPtr<FJsonObject> FCreateDataTableAction::ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context)
{
	const FString AssetName = Params->GetStringField(TEXT("asset_name"));
	const FString PackagePath = Params->GetStringField(TEXT("package_path"));
	const FString RowStructPath = Params->GetStringField(TEXT("row_struct"));
	const bool bSave = GetOptionalBool(Params, TEXT("save"), true);

	UScriptStruct* RowStruct = LoadObject<UScriptStruct>(nullptr, *RowStructPath);
	if (!RowStruct)
	{
		return CreateErrorResponse(
			FString::Printf(TEXT("Failed to load RowStruct: %s"), *RowStructPath),
			TEXT("row_struct_load_failed"));
	}

	const FString PackageName = FString::Printf(TEXT("%s/%s"), *PackagePath, *AssetName);
	const FString FullAssetPath = FString::Printf(TEXT("%s.%s"), *PackageName, *AssetName);
	UObject* Existing = LoadObject<UObject>(nullptr, *FullAssetPath);
	if (Existing)
	{
		UDataTable* ExistingTable = Cast<UDataTable>(Existing);
		if (!ExistingTable)
		{
			return CreateErrorResponse(
				FString::Printf(TEXT("Existing asset is not a DataTable: %s (class=%s)"),
					*FullAssetPath, *Existing->GetClass()->GetName()),
				TEXT("asset_type_mismatch"));
		}

		if (ExistingTable->GetRowStruct() != RowStruct)
		{
			ExistingTable->Modify();
			ExistingTable->RowStruct = RowStruct;
			ExistingTable->EmptyTable();
		}

		bool bSaved = false;
		FString SaveError;
		if (bSave)
		{
			bSaved = UEEditorMCP_DataAssetUtils::SaveAssetPackage(ExistingTable, SaveError);
		}

		TSharedPtr<FJsonObject> Result = MakeShared<FJsonObject>();
		Result->SetStringField(TEXT("asset_path"), ExistingTable->GetPathName());
		Result->SetStringField(TEXT("asset_class"), ExistingTable->GetClass()->GetName());
		Result->SetStringField(TEXT("row_struct"), ExistingTable->GetRowStruct() ? ExistingTable->GetRowStruct()->GetPathName() : FString());
		Result->SetBoolField(TEXT("already_exists"), true);
		Result->SetBoolField(TEXT("saved"), bSaved);
		if (bSave && !bSaved)
		{
			Result->SetStringField(TEXT("save_error"), SaveError);
		}
		return CreateSuccessResponse(Result);
	}

	UPackage* Package = CreatePackage(*PackageName);
	if (!Package)
	{
		return CreateErrorResponse(
			FString::Printf(TEXT("CreatePackage failed for %s"), *PackageName),
			TEXT("create_package_failed"));
	}

	UDataTable* NewTable = NewObject<UDataTable>(Package, UDataTable::StaticClass(), *AssetName, RF_Public | RF_Standalone | RF_Transactional);
	if (!NewTable)
	{
		return CreateErrorResponse(
			FString::Printf(TEXT("NewObject failed for DataTable %s"), *AssetName),
			TEXT("create_failed"));
	}

	NewTable->RowStruct = RowStruct;
	FAssetRegistryModule::AssetCreated(NewTable);
	Package->MarkPackageDirty();

	bool bSaved = false;
	FString SaveError;
	if (bSave)
	{
		bSaved = UEEditorMCP_DataAssetUtils::SaveAssetPackage(NewTable, SaveError);
	}

	TSharedPtr<FJsonObject> Result = MakeShared<FJsonObject>();
	Result->SetStringField(TEXT("asset_path"), NewTable->GetPathName());
	Result->SetStringField(TEXT("asset_class"), NewTable->GetClass()->GetName());
	Result->SetStringField(TEXT("row_struct"), NewTable->GetRowStruct() ? NewTable->GetRowStruct()->GetPathName() : FString());
	Result->SetBoolField(TEXT("already_exists"), false);
	Result->SetBoolField(TEXT("saved"), bSaved);
	if (bSave && !bSaved)
	{
		Result->SetStringField(TEXT("save_error"), SaveError);
	}

	UE_LOG(LogMCP, Log, TEXT("create_data_table: %s row_struct=%s saved=%d"),
		*NewTable->GetPathName(), *RowStruct->GetPathName(), bSaved ? 1 : 0);

	return CreateSuccessResponse(Result);
}

// ============================================================================
// FLiveCodingCompileAction / FLiveCodingStatusAction
//
// 通过 ILiveCodingModule 调用编辑器 Live Coding（Quick Compile）。这是 UE 5.x
// 标准的"无需关闭编辑器即可热重载 C++"机制，对接 Agent 自主开发-验证闭环。
//
// 注意：
//   1) ILiveCodingModule 只在 Windows 平台存在（Engine/Source/Developer/Windows/LiveCoding）。
//   2) UEEditorMCP.Build.cs 在 Win64 才把 LiveCoding 加入私有依赖，并定义
//      UEEDITORMCP_HAS_LIVECODING=1；其它平台定义为 0，action 仍注册但直接返回
//      not_supported，保证跨平台编译通过。
// ============================================================================

#if defined(UEEDITORMCP_HAS_LIVECODING) && UEEDITORMCP_HAS_LIVECODING
#include "ILiveCodingModule.h"

namespace UEEditorMCP_LiveCoding
{
	static ILiveCodingModule* GetModule()
	{
		// LoadModule 不强制；若编辑器未启用 LC 则返回 nullptr，由调用方降级处理
		return FModuleManager::GetModulePtr<ILiveCodingModule>(TEXT("LiveCoding"));
	}
}
#endif // UEEDITORMCP_HAS_LIVECODING

TSharedPtr<FJsonObject> FLiveCodingStatusAction::ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context)
{
	TSharedPtr<FJsonObject> Result = MakeShared<FJsonObject>();

#if defined(UEEDITORMCP_HAS_LIVECODING) && UEEDITORMCP_HAS_LIVECODING
	const bool bModuleLoaded = FModuleManager::Get().IsModuleLoaded(TEXT("LiveCoding"));
	Result->SetBoolField(TEXT("module_loaded"), bModuleLoaded);

	ILiveCodingModule* LC = UEEditorMCP_LiveCoding::GetModule();
	if (!LC)
	{
		Result->SetBoolField(TEXT("enabled"), false);
		Result->SetBoolField(TEXT("compile_in_progress"), false);
		Result->SetBoolField(TEXT("can_enable_for_session"), false);
		return CreateSuccessResponse(Result);
	}

	Result->SetBoolField(TEXT("enabled"), LC->IsEnabledByDefault() || LC->IsEnabledForSession());
	Result->SetBoolField(TEXT("compile_in_progress"), LC->IsCompiling());
	Result->SetBoolField(TEXT("can_enable_for_session"), LC->CanEnableForSession());

	return CreateSuccessResponse(Result);
#else
	Result->SetBoolField(TEXT("module_loaded"), false);
	Result->SetBoolField(TEXT("enabled"), false);
	Result->SetBoolField(TEXT("compile_in_progress"), false);
	Result->SetBoolField(TEXT("can_enable_for_session"), false);
	Result->SetStringField(TEXT("note"), TEXT("LiveCoding is only supported on Win64 in this build."));
	return CreateSuccessResponse(Result);
#endif
}

TSharedPtr<FJsonObject> FLiveCodingCompileAction::ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context)
{
	// 兼容旧调用方：仍然解析这两个参数，但**不再使用**（见下方 deadlock 注释）。
	const bool bWaitRequested = GetOptionalBool(Params, TEXT("wait_for_completion"), false);
	(void)GetOptionalNumber(Params, TEXT("timeout_seconds"), 120.0);

	TSharedPtr<FJsonObject> Result = MakeShared<FJsonObject>();

	// ------------------------------------------------------------------
	// 强制 fire-and-forget 模式（修复 GameThread 自死锁，方案 A）
	// ------------------------------------------------------------------
	// 背景：MCPServer 通过 AsyncTask(ENamedThreads::GameThread, ...) 把每个 action
	// 派发到 GameThread 同步执行。而 ILiveCodingModule::Compile() 是异步的——
	// 编译完成后的状态翻转、patch apply 都必须由 GameThread 的 Tick 推动。
	// 旧实现里如果 wait_for_completion=true，会在 GameThread 自旋
	// `while (LC->IsCompiling()) Sleep(0.2)`，这等同于 GameThread 等待自己
	// 推进的状态——典型自死锁，表现为编辑器 UI 冻结直到 timeout（120s）甚至
	// MCPServer 的 240s 兜底超时才解冻。
	//
	// 决策：彻底移除 wait 分支。本 action 只负责"发起编译"，调用方必须用
	// editor.live_coding_status 轮询 compile_in_progress 字段。轮询调用本身
	// 也走 GameThread，但每次只读状态，不阻塞，不会卡 Tick。
	// ------------------------------------------------------------------

#if defined(UEEDITORMCP_HAS_LIVECODING) && UEEDITORMCP_HAS_LIVECODING
	ILiveCodingModule* LC = UEEditorMCP_LiveCoding::GetModule();
	if (!LC)
	{
		Result->SetBoolField(TEXT("enabled"), false);
		Result->SetBoolField(TEXT("compile_started"), false);
		Result->SetBoolField(TEXT("compile_in_progress"), false);
		Result->SetBoolField(TEXT("waited"), false);
		Result->SetBoolField(TEXT("timed_out"), false);
		return CreateErrorResponse(
			TEXT("LiveCoding module is not loaded — start the editor with Live Coding enabled."),
			TEXT("live_coding_unavailable"));
	}

	const bool bEnabled = LC->IsEnabledByDefault() || LC->IsEnabledForSession();
	Result->SetBoolField(TEXT("enabled"), bEnabled);

	// 如果 session 未启用且允许启用，主动开启
	if (!bEnabled && LC->CanEnableForSession())
	{
		LC->EnableForSession(true);
	}

	if (LC->IsCompiling())
	{
		// 已经在编译中，无需重复触发
		Result->SetBoolField(TEXT("compile_started"), false);
		Result->SetBoolField(TEXT("compile_in_progress"), true);
	}
	else
	{
		LC->Compile();
		Result->SetBoolField(TEXT("compile_started"), true);
		Result->SetBoolField(TEXT("compile_in_progress"), LC->IsCompiling());
	}

	// 永远 fire-and-forget：waited=false / timed_out=false
	Result->SetBoolField(TEXT("waited"), false);
	Result->SetBoolField(TEXT("timed_out"), false);

	// 显式告知调用方这是 fire-and-forget；如果传了 wait_for_completion=true 给出
	// deprecation 警告，方便前端日志排查。
	Result->SetBoolField(TEXT("fire_and_forget"), true);
	if (bWaitRequested)
	{
		Result->SetStringField(
			TEXT("deprecation_warning"),
			TEXT("wait_for_completion is ignored: blocking on GameThread would deadlock LiveCoding. "
			     "Poll editor.live_coding_status until compile_in_progress=false."));
	}

	return CreateSuccessResponse(Result);
#else
	(void)bWaitRequested;
	return CreateErrorResponse(
		TEXT("LiveCoding is only supported on Win64; this build was compiled without it."),
		TEXT("live_coding_unavailable"));
#endif
}


// ============================================================================
// P10: DataTable Row CRUD Helpers
// ============================================================================

namespace UEEditorMCP_DataTableUtils
{
	/** 加载 DataTable 资产并校验类型。失败时填 OutError 并返回 nullptr。 */
	static UDataTable* LoadDataTable(const FString& AssetPath, FString& OutError)
	{
		const FString FullPath = UEEditorMCP_DataAssetUtils::NormalizeAssetObjectPath(AssetPath);
		UObject* Obj = StaticLoadObject(UObject::StaticClass(), nullptr, *FullPath);
		if (!Obj)
		{
			OutError = FString::Printf(TEXT("Failed to load DataTable: %s"), *FullPath);
			return nullptr;
		}
		UDataTable* DT = Cast<UDataTable>(Obj);
		if (!DT)
		{
			OutError = FString::Printf(TEXT("Asset is not a DataTable: %s (class=%s)"),
				*FullPath, *Obj->GetClass()->GetName());
			return nullptr;
		}
		if (!DT->GetRowStruct())
		{
			OutError = FString::Printf(TEXT("DataTable has no RowStruct: %s"), *FullPath);
			return nullptr;
		}
		return DT;
	}

	/** 把单个 JSON field value 转成 UE ImportText 字符串。 */
	static FString JsonValueToImportTextString(const TSharedPtr<FJsonValue>& JsonValue)
	{
		if (!JsonValue.IsValid())
		{
			return TEXT("");
		}
		switch (JsonValue->Type)
		{
		case EJson::String:  return JsonValue->AsString();
		case EJson::Number:  return FString::SanitizeFloat(JsonValue->AsNumber(), 0);
		case EJson::Boolean: return JsonValue->AsBool() ? TEXT("true") : TEXT("false");
		case EJson::Null:    return TEXT("");
		default:
			// Object/Array → 尝试序列化为 JSON 文本（通常调用方应传字符串）
			return TEXT("");
		}
	}

	/**
	 * 用 JSON object 的键值对填写一个 UScriptStruct 实例。
	 * 每个 JSON key 对应 RowStruct 的一个 UPROPERTY 字段名，value 走 ImportText。
	 * 如果字段不存在或 ImportText 失败，填 error 数组并返回 false。
	 */
	static bool FillStructFromJson(UScriptStruct* RowStruct, void* StructPtr,
		const TSharedPtr<FJsonObject>& JsonValues, TArray<FString>& OutErrors)
	{
		bool bAllOk = true;
		for (const auto& Pair : JsonValues->Values)
		{
			const FString PropName(Pair.Key.ToView());
			FProperty* Prop = RowStruct->FindPropertyByName(*PropName);
			if (!Prop)
			{
				OutErrors.Add(FString::Printf(TEXT("Property '%s' not found on row struct '%s'"),
					*PropName, *RowStruct->GetName()));
				bAllOk = false;
				continue;
			}

			void* PropAddr = Prop->ContainerPtrToValuePtr<void>(StructPtr);
			const FString ImportStr = JsonValueToImportTextString(Pair.Value);

			// FTextProperty 特殊处理：ImportText 期望 (NSLOCTEXT("namespace","key","text"))，
			// 但我们鼓励调用方直接传裸字符串。
			if (FTextProperty* TextProp = CastField<FTextProperty>(Prop))
			{
				TextProp->SetPropertyValue(PropAddr, FText::FromString(ImportStr));
			}
			else
			{
				const TCHAR* Result = Prop->ImportText_Direct(*ImportStr, PropAddr, nullptr, PPF_None);
				if (Result && *Result)
				{
					OutErrors.Add(FString::Printf(TEXT("ImportText failed for '%s' (value='%s'): %s"),
						*PropName, *ImportStr, Result));
					bAllOk = false;
				}
			}
		}
		return bAllOk;
	}

	/**
	 * 将 FProperty 的值导出为 JSON 兼容字符串。
	 */
	static FString ExportPropertyValueToJsonString(FProperty* Prop, void* StructPtr)
	{
		if (FTextProperty* TextProp = CastField<FTextProperty>(Prop))
		{
			FText TextVal = TextProp->GetPropertyValue(Prop->ContainerPtrToValuePtr<void>(StructPtr));
			return TextVal.ToString();
		}
		if (FStrProperty* StrProp = CastField<FStrProperty>(Prop))
		{
			return StrProp->GetPropertyValue(Prop->ContainerPtrToValuePtr<void>(StructPtr));
		}
		if (FNumericProperty* NumProp = CastField<FNumericProperty>(Prop))
		{
			if (NumProp->IsFloatingPoint())
			{
				return FString::SanitizeFloat(NumProp->GetFloatingPointPropertyValue(
					Prop->ContainerPtrToValuePtr<void>(StructPtr)));
			}
			return FString::Printf(TEXT("%lld"),
				NumProp->GetSignedIntPropertyValue(Prop->ContainerPtrToValuePtr<void>(StructPtr)));
		}
		if (FBoolProperty* BoolProp = CastField<FBoolProperty>(Prop))
		{
			return BoolProp->GetPropertyValue(Prop->ContainerPtrToValuePtr<void>(StructPtr))
				? TEXT("true") : TEXT("false");
		}
		// Fallback: ExportText
		FString Out;
		void* PropAddr = Prop->ContainerPtrToValuePtr<void>(StructPtr);
		Prop->ExportText_Direct(Out, PropAddr, PropAddr, nullptr, PPF_None);
		return Out;
	}
}


// ============================================================================
// FDataTableGetRowsAction
// ============================================================================

bool FDataTableGetRowsAction::Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError)
{
	FString AssetPath;
	if (!GetRequiredString(Params, TEXT("asset_path"), AssetPath, OutError)) return false;
	return true;
}

TSharedPtr<FJsonObject> FDataTableGetRowsAction::ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context)
{
	const FString AssetPath = Params->GetStringField(TEXT("asset_path"));

	FString LoadError;
	UDataTable* DT = UEEditorMCP_DataTableUtils::LoadDataTable(AssetPath, LoadError);
	if (!DT)
	{
		return CreateErrorResponse(LoadError, TEXT("datatable_load_failed"));
	}

	UScriptStruct* RowStruct = const_cast<UScriptStruct*>(DT->GetRowStruct());
	TArray<FName> RowNames = DT->GetRowNames();

	TArray<TSharedPtr<FJsonValue>> RowsArray;
	const TMap<FName, uint8*>& RowMap = DT->GetRowMap();

	for (const FName& RowName : RowNames)
	{
		const uint8* RowPtr = RowMap.FindRef(RowName);
		if (!RowPtr) continue;

		TSharedPtr<FJsonObject> RowObj = MakeShared<FJsonObject>();
		RowObj->SetStringField(TEXT("row_name"), RowName.ToString());

		// 遍历 RowStruct 的所有 FProperty
		for (TFieldIterator<FProperty> It(RowStruct); It; ++It)
		{
			FProperty* Prop = *It;
			const FString ValueStr = UEEditorMCP_DataTableUtils::ExportPropertyValueToJsonString(
				Prop, const_cast<uint8*>(RowPtr));
			RowObj->SetStringField(Prop->GetName(), ValueStr);
		}

		RowsArray.Add(MakeShared<FJsonValueObject>(RowObj));
	}

	TSharedPtr<FJsonObject> Result = MakeShared<FJsonObject>();
	Result->SetStringField(TEXT("asset_path"), DT->GetPathName());
	Result->SetStringField(TEXT("row_struct"), RowStruct->GetPathName());
	Result->SetNumberField(TEXT("row_count"), RowNames.Num());
	Result->SetArrayField(TEXT("rows"), RowsArray);

	UE_LOG(LogMCP, Log, TEXT("data_table_get_rows: %s -> %d rows"),
		*AssetPath, RowNames.Num());

	return CreateSuccessResponse(Result);
}


// ============================================================================
// FDataTableAddRowAction
// ============================================================================

bool FDataTableAddRowAction::Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError)
{
	FString AssetPath, RowName;
	if (!GetRequiredString(Params, TEXT("asset_path"), AssetPath, OutError)) return false;
	if (!GetRequiredString(Params, TEXT("row_name"), RowName, OutError)) return false;

	const TSharedPtr<FJsonObject>* PVObj = nullptr;
	if (!Params->TryGetObjectField(TEXT("property_values"), PVObj) || !PVObj->IsValid())
	{
		OutError = TEXT("'property_values' is required and must be a JSON object.");
		return false;
	}
	return true;
}

TSharedPtr<FJsonObject> FDataTableAddRowAction::ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context)
{
	const FString AssetPath = Params->GetStringField(TEXT("asset_path"));
	const FString RowNameStr = Params->GetStringField(TEXT("row_name"));
	const FName RowName(*RowNameStr);
	const bool bSave = GetOptionalBool(Params, TEXT("save"), true);
	const TSharedPtr<FJsonObject> PropertyValues = Params->GetObjectField(TEXT("property_values"));

	FString LoadError;
	UDataTable* DT = UEEditorMCP_DataTableUtils::LoadDataTable(AssetPath, LoadError);
	if (!DT)
	{
		return CreateErrorResponse(LoadError, TEXT("datatable_load_failed"));
	}

	// 行名去重
	if (DT->GetRowMap().Contains(RowName))
	{
		return CreateErrorResponse(
			FString::Printf(TEXT("Row '%s' already exists in DataTable. Use data_table_set_row_property to modify it."),
				*RowNameStr),
			TEXT("duplicate_row"));
	}

	UScriptStruct* RowStruct = const_cast<UScriptStruct*>(DT->GetRowStruct());

	// 分配新的 struct 实例
	uint8* NewRowData = (uint8*)FMemory::Malloc(RowStruct->GetStructureSize());
	RowStruct->InitializeStruct(NewRowData);

	// 填充属性值
	TArray<FString> FillErrors;
	const bool bFillOk = UEEditorMCP_DataTableUtils::FillStructFromJson(
		RowStruct, NewRowData, PropertyValues, FillErrors);

	if (!bFillOk)
	{
		RowStruct->DestroyStruct(NewRowData);
		FMemory::Free(NewRowData);
		return CreateErrorResponse(
			FString::Printf(TEXT("Failed to fill row struct: %s"), *FString::Join(FillErrors, TEXT("; "))),
			TEXT("import_text_failed"));
	}

	// 写入 RowMap（UDataTable 没有公开的 AddRow 走 uint8* 的接口，只能 const_cast 访问）
	TMap<FName, uint8*>& RowMap = const_cast<TMap<FName, uint8*>&>(DT->GetRowMap());
	RowMap.Add(RowName, NewRowData);

	DT->Modify();

	// 保存
	bool bSaved = false;
	FString SaveError;
	if (bSave)
	{
		bSaved = UEEditorMCP_DataAssetUtils::SaveAssetPackage(DT, SaveError);
	}
	else if (UPackage* Pkg = DT->GetOutermost())
	{
		Pkg->SetDirtyFlag(true);
	}

	TSharedPtr<FJsonObject> Result = MakeShared<FJsonObject>();
	Result->SetStringField(TEXT("asset_path"), DT->GetPathName());
	Result->SetStringField(TEXT("row_name"), RowNameStr);
	Result->SetNumberField(TEXT("row_count_after"), DT->GetRowNames().Num());
	Result->SetBoolField(TEXT("saved"), bSaved);
	if (bSave && !bSaved)
	{
		Result->SetStringField(TEXT("save_error"), SaveError);
	}
	if (FillErrors.Num() > 0)
	{
		TArray<TSharedPtr<FJsonValue>> ErrArr;
		for (const FString& E : FillErrors)
		{
			ErrArr.Add(MakeShared<FJsonValueString>(E));
		}
		Result->SetArrayField(TEXT("fill_warnings"), ErrArr);
	}

	UE_LOG(LogMCP, Log, TEXT("data_table_add_row: %s + '%s' (saved=%d)"),
		*AssetPath, *RowNameStr, bSaved ? 1 : 0);

	return CreateSuccessResponse(Result);
}


// ============================================================================
// FDataTableSetRowPropertyAction
// ============================================================================

bool FDataTableSetRowPropertyAction::Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError)
{
	FString AssetPath, RowName, PropName;
	if (!GetRequiredString(Params, TEXT("asset_path"), AssetPath, OutError)) return false;
	if (!GetRequiredString(Params, TEXT("row_name"), RowName, OutError)) return false;
	if (!GetRequiredString(Params, TEXT("property_name"), PropName, OutError)) return false;
	if (!Params->HasField(TEXT("property_value")))
	{
		OutError = TEXT("'property_value' is required.");
		return false;
	}
	return true;
}

TSharedPtr<FJsonObject> FDataTableSetRowPropertyAction::ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context)
{
	const FString AssetPath = Params->GetStringField(TEXT("asset_path"));
	const FName RowName(*Params->GetStringField(TEXT("row_name")));
	const FString PropertyName = Params->GetStringField(TEXT("property_name"));
	const bool bSave = GetOptionalBool(Params, TEXT("save"), true);
	TSharedPtr<FJsonValue> JsonVal = Params->TryGetField(TEXT("property_value"));

	FString LoadError;
	UDataTable* DT = UEEditorMCP_DataTableUtils::LoadDataTable(AssetPath, LoadError);
	if (!DT)
	{
		return CreateErrorResponse(LoadError, TEXT("datatable_load_failed"));
	}

	// 查找行
	TMap<FName, uint8*>& RowMap = const_cast<TMap<FName, uint8*>&>(DT->GetRowMap());
	uint8** RowPtrPtr = RowMap.Find(RowName);
	if (!RowPtrPtr || !*RowPtrPtr)
	{
		return CreateErrorResponse(
			FString::Printf(TEXT("Row '%s' not found in DataTable. Available rows: %s"),
				*RowName.ToString(),
				*FString::JoinBy(DT->GetRowNames(), TEXT(", "), [](const FName& N) { return N.ToString(); })),
			TEXT("row_not_found"));
	}

	UScriptStruct* RowStruct = const_cast<UScriptStruct*>(DT->GetRowStruct());
	FProperty* Prop = RowStruct->FindPropertyByName(*PropertyName);
	if (!Prop)
	{
		return CreateErrorResponse(
			FString::Printf(TEXT("Property '%s' not found on row struct '%s'"),
				*PropertyName, *RowStruct->GetName()),
			TEXT("property_not_found"));
	}

	void* RowPtr = *RowPtrPtr;
	void* PropAddr = Prop->ContainerPtrToValuePtr<void>(RowPtr);

	const FString ImportStr = UEEditorMCP_DataTableUtils::JsonValueToImportTextString(JsonVal);

	DT->PreEditChange(Prop);
	DT->Modify();

	// FText 特殊处理（ImportText 对 FText 不走 FromString 路径）
	bool bOk = true;
	FString SetError;
	if (FTextProperty* TextProp = CastField<FTextProperty>(Prop))
	{
		TextProp->SetPropertyValue(PropAddr, FText::FromString(ImportStr));
	}
	else
	{
		const TCHAR* Result = Prop->ImportText_Direct(*ImportStr, PropAddr, DT, PPF_None);
		if (Result && *Result)
		{
			bOk = false;
			SetError = FString::Printf(TEXT("ImportText failed: %s"), Result);
		}
	}

	FPropertyChangedEvent ChangeEvent(Prop, EPropertyChangeType::ValueSet);
	DT->PostEditChangeProperty(ChangeEvent);

	if (!bOk)
	{
		return CreateErrorResponse(SetError, TEXT("import_text_failed"));
	}

	// 回读
	const FString ValueAfter = UEEditorMCP_DataTableUtils::ExportPropertyValueToJsonString(Prop, RowPtr);

	// 保存
	bool bSaved = false;
	FString SaveError;
	if (bSave)
	{
		bSaved = UEEditorMCP_DataAssetUtils::SaveAssetPackage(DT, SaveError);
	}
	else if (UPackage* Pkg = DT->GetOutermost())
	{
		Pkg->SetDirtyFlag(true);
	}

	TSharedPtr<FJsonObject> Result = MakeShared<FJsonObject>();
	Result->SetStringField(TEXT("asset_path"), DT->GetPathName());
	Result->SetStringField(TEXT("row_name"), RowName.ToString());
	Result->SetStringField(TEXT("property_name"), PropertyName);
	Result->SetStringField(TEXT("value_after"), ValueAfter);
	Result->SetBoolField(TEXT("saved"), bSaved);
	if (bSave && !bSaved)
	{
		Result->SetStringField(TEXT("save_error"), SaveError);
	}

	UE_LOG(LogMCP, Log, TEXT("data_table_set_row_property: %s[%s].%s = %s (saved=%d)"),
		*AssetPath, *RowName.ToString(), *PropertyName, *ValueAfter, bSaved ? 1 : 0);

	return CreateSuccessResponse(Result);
}
