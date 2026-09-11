#if WITH_DEV_AUTOMATION_TESTS

#include "Misc/AutomationTest.h"
#include "MCPBridge.h"
#include "Editor.h"
#include "Dom/JsonObject.h"
#include "Dom/JsonValue.h"

namespace UEEditorMCPAssetMaintenanceTests
{
	static TSharedPtr<FJsonObject> Execute(const FString& CommandType, const TSharedPtr<FJsonObject>& Params)
	{
		UMCPBridge* Bridge = GEditor ? GEditor->GetEditorSubsystem<UMCPBridge>() : nullptr;
		return Bridge ? Bridge->ExecuteCommand(CommandType, Params) : nullptr;
	}

	static TSharedPtr<FJsonObject> MakeRenameItem(const FString& OldAssetPath, const FString& NewPackagePath, const FString& NewName)
	{
		TSharedPtr<FJsonObject> Item = MakeShared<FJsonObject>();
		Item->SetStringField(TEXT("old_asset_path"), OldAssetPath);
		Item->SetStringField(TEXT("new_package_path"), NewPackagePath);
		Item->SetStringField(TEXT("new_name"), NewName);
		return Item;
	}

	static TSharedPtr<FJsonObject> MakeManifestRenameItem(
		const FString& Id,
		const FString& OldObjectPath,
		const FString& NewDirectory,
		const FString& NewName,
		const FString& ExpectedClass = TEXT(""))
	{
		TSharedPtr<FJsonObject> Source = MakeShared<FJsonObject>();
		Source->SetStringField(TEXT("object_path"), OldObjectPath);
		if (!ExpectedClass.IsEmpty())
		{
			Source->SetStringField(TEXT("expected_class"), ExpectedClass);
		}

		TSharedPtr<FJsonObject> Target = MakeShared<FJsonObject>();
		Target->SetStringField(TEXT("directory"), NewDirectory);
		Target->SetStringField(TEXT("asset_name"), NewName);

		TSharedPtr<FJsonObject> Item = MakeShared<FJsonObject>();
		Item->SetStringField(TEXT("id"), Id);
		Item->SetStringField(TEXT("op"), TEXT("rename_or_move_asset"));
		Item->SetObjectField(TEXT("source"), Source);
		Item->SetObjectField(TEXT("target"), Target);
		Item->SetStringField(TEXT("rule_id"), TEXT("test_rule"));
		Item->SetStringField(TEXT("reason"), TEXT("automation test"));
		Item->SetNumberField(TEXT("confidence"), 0.95);
		return Item;
	}

	static TSharedPtr<FJsonObject> MakeManifest(const TArray<TSharedPtr<FJsonValue>>& Items)
	{
		TSharedPtr<FJsonObject> Defaults = MakeShared<FJsonObject>();
		Defaults->SetBoolField(TEXT("auto_fixup_redirectors"), true);
		Defaults->SetStringField(TEXT("fixup_mode"), TEXT("delete"));
		Defaults->SetBoolField(TEXT("delete_empty_dirs"), true);

		TSharedPtr<FJsonObject> Manifest = MakeShared<FJsonObject>();
		Manifest->SetStringField(TEXT("schema"), TEXT("ue.asset_maintenance_plan.v1"));
		Manifest->SetStringField(TEXT("project"), FApp::GetProjectName());
		Manifest->SetObjectField(TEXT("defaults"), Defaults);
		Manifest->SetArrayField(TEXT("items"), Items);
		return Manifest;
	}

	static bool JsonStringArrayContains(const TArray<TSharedPtr<FJsonValue>>* Values, const FString& Needle)
	{
		if (!Values)
		{
			return false;
		}

		for (const TSharedPtr<FJsonValue>& Value : *Values)
		{
			FString Parsed;
			if (Value.IsValid() && Value->TryGetString(Parsed) && Parsed == Needle)
			{
				return true;
			}
		}

		return false;
	}

	static bool JsonStringArrayContainsPrefix(const TArray<TSharedPtr<FJsonValue>>* Values, const FString& Prefix)
	{
		if (!Values)
		{
			return false;
		}

		for (const TSharedPtr<FJsonValue>& Value : *Values)
		{
			FString Parsed;
			if (Value.IsValid() && Value->TryGetString(Parsed) && Parsed.StartsWith(Prefix))
			{
				return true;
			}
		}

		return false;
	}
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(
	FUEEditorMCPPlanAssetRenamesPreflightTest,
	"p110_2.UEEditorMCP.AssetMaintenance.PlanRenamePreflight",
	EAutomationTestFlags::EditorContext | EAutomationTestFlags::EngineFilter)

bool FUEEditorMCPPlanAssetRenamesPreflightTest::RunTest(const FString& Parameters)
{
	using namespace UEEditorMCPAssetMaintenanceTests;

	TArray<TSharedPtr<FJsonValue>> Items;
	Items.Add(MakeShared<FJsonValueObject>(MakeRenameItem(TEXT("/Game/__MCPMissing/DA_A.DA_A"), TEXT("/Game/__MCPAssetMaintenance"), TEXT("DA_Conflict"))));
	Items.Add(MakeShared<FJsonValueObject>(MakeRenameItem(TEXT("/Game/__MCPMissing/DA_B.DA_B"), TEXT("/Game/__MCPAssetMaintenance"), TEXT("DA_Conflict"))));

	TSharedPtr<FJsonObject> Params = MakeShared<FJsonObject>();
	Params->SetArrayField(TEXT("items"), Items);
	Params->SetBoolField(TEXT("include_referencers"), false);

	TSharedPtr<FJsonObject> Result = Execute(TEXT("plan_asset_renames"), Params);
	TestNotNull(TEXT("plan result"), Result.Get());
	if (!Result.IsValid())
	{
		return false;
	}

	TestTrue(TEXT("plan command succeeds structurally"), Result->GetBoolField(TEXT("success")));
	TestTrue(TEXT("dry run"), Result->GetBoolField(TEXT("dry_run")));
	TestTrue(TEXT("has blockers"), Result->GetBoolField(TEXT("has_blockers")));
	TestEqual(TEXT("requested count"), static_cast<int32>(Result->GetIntegerField(TEXT("requested_count"))), 2);
	TestEqual(TEXT("blocker count"), static_cast<int32>(Result->GetIntegerField(TEXT("blocker_count"))), 2);

	const TArray<TSharedPtr<FJsonValue>>* ResultItems = nullptr;
	TestTrue(TEXT("items array exists"), Result->TryGetArrayField(TEXT("items"), ResultItems));
	TestTrue(TEXT("two items"), ResultItems && ResultItems->Num() == 2);
	if (ResultItems && ResultItems->Num() == 2)
	{
		for (const TSharedPtr<FJsonValue>& ItemValue : *ResultItems)
		{
			const TSharedPtr<FJsonObject> Item = ItemValue->AsObject();
			TestTrue(TEXT("item object valid"), Item.IsValid());
			if (!Item.IsValid())
			{
				continue;
			}

			const TArray<TSharedPtr<FJsonValue>>* Blockers = nullptr;
			TestTrue(TEXT("blockers array exists"), Item->TryGetArrayField(TEXT("blockers"), Blockers));
			TestFalse(TEXT("cannot rename blocked item"), Item->GetBoolField(TEXT("can_rename")));
			TestTrue(TEXT("missing source blocker"), JsonStringArrayContains(Blockers, TEXT("source_asset_not_found")));
			TestTrue(TEXT("duplicate destination blocker"), JsonStringArrayContains(Blockers, TEXT("duplicate_destination_in_plan")));
		}
	}

	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(
	FUEEditorMCPDeleteAssetsDryRunSafetyTest,
	"p110_2.UEEditorMCP.AssetMaintenance.DeleteAssetsDryRunSafety",
	EAutomationTestFlags::EditorContext | EAutomationTestFlags::EngineFilter)

bool FUEEditorMCPDeleteAssetsDryRunSafetyTest::RunTest(const FString& Parameters)
{
	using namespace UEEditorMCPAssetMaintenanceTests;

	TSharedPtr<FJsonObject> Params = MakeShared<FJsonObject>();
	Params->SetStringField(TEXT("asset_path"), TEXT("/Game/__MCPMissing/DA_None.DA_None"));
	Params->SetBoolField(TEXT("dry_run"), true);

	TSharedPtr<FJsonObject> Result = Execute(TEXT("delete_assets"), Params);
	TestNotNull(TEXT("delete result"), Result.Get());
	if (!Result.IsValid())
	{
		return false;
	}

	TestTrue(TEXT("delete command succeeds structurally"), Result->GetBoolField(TEXT("success")));
	TestTrue(TEXT("dry run"), Result->GetBoolField(TEXT("dry_run")));
	TestFalse(TEXT("not executed"), Result->GetBoolField(TEXT("executed")));
	TestTrue(TEXT("has blockers"), Result->GetBoolField(TEXT("has_blockers")));
	TestEqual(TEXT("deleted count"), static_cast<int32>(Result->GetIntegerField(TEXT("deleted_count"))), 0);

	const TArray<TSharedPtr<FJsonValue>>* Items = nullptr;
	TestTrue(TEXT("items array exists"), Result->TryGetArrayField(TEXT("items"), Items));
	TestTrue(TEXT("one item"), Items && Items->Num() == 1);
	if (Items && Items->Num() == 1)
	{
		const TSharedPtr<FJsonObject> Item = (*Items)[0]->AsObject();
		TestTrue(TEXT("item object valid"), Item.IsValid());
		if (Item.IsValid())
		{
			const TArray<TSharedPtr<FJsonValue>>* Blockers = nullptr;
			TestTrue(TEXT("blockers array exists"), Item->TryGetArrayField(TEXT("blockers"), Blockers));
			TestFalse(TEXT("cannot delete missing asset"), Item->GetBoolField(TEXT("can_delete")));
			TestTrue(TEXT("missing asset blocker"), JsonStringArrayContains(Blockers, TEXT("asset_not_found")));
		}
	}

	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(
	FUEEditorMCPDeleteEmptyDirectoriesProtectedRootTest,
	"p110_2.UEEditorMCP.AssetMaintenance.DeleteEmptyDirectoriesProtectedRoot",
	EAutomationTestFlags::EditorContext | EAutomationTestFlags::EngineFilter)

bool FUEEditorMCPDeleteEmptyDirectoriesProtectedRootTest::RunTest(const FString& Parameters)
{
	using namespace UEEditorMCPAssetMaintenanceTests;

	TSharedPtr<FJsonObject> Params = MakeShared<FJsonObject>();
	Params->SetStringField(TEXT("path"), TEXT("/Game"));
	Params->SetBoolField(TEXT("dry_run"), true);
	Params->SetBoolField(TEXT("recursive"), false);

	TSharedPtr<FJsonObject> Result = Execute(TEXT("delete_empty_directories"), Params);
	TestNotNull(TEXT("directory result"), Result.Get());
	if (!Result.IsValid())
	{
		return false;
	}

	TestTrue(TEXT("directory command succeeds structurally"), Result->GetBoolField(TEXT("success")));
	TestTrue(TEXT("dry run"), Result->GetBoolField(TEXT("dry_run")));
	TestTrue(TEXT("has blockers"), Result->GetBoolField(TEXT("has_blockers")));
	TestEqual(TEXT("candidate count"), static_cast<int32>(Result->GetIntegerField(TEXT("candidate_count"))), 1);
	TestEqual(TEXT("deleted count"), static_cast<int32>(Result->GetIntegerField(TEXT("deleted_count"))), 0);

	const TArray<TSharedPtr<FJsonValue>>* Directories = nullptr;
	TestTrue(TEXT("directories array exists"), Result->TryGetArrayField(TEXT("directories"), Directories));
	TestTrue(TEXT("one directory"), Directories && Directories->Num() == 1);
	if (Directories && Directories->Num() == 1)
	{
		const TSharedPtr<FJsonObject> Directory = (*Directories)[0]->AsObject();
		TestTrue(TEXT("directory object valid"), Directory.IsValid());
		if (Directory.IsValid())
		{
			const TArray<TSharedPtr<FJsonValue>>* Blockers = nullptr;
			TestTrue(TEXT("blockers array exists"), Directory->TryGetArrayField(TEXT("blockers"), Blockers));
			TestFalse(TEXT("cannot delete root"), Directory->GetBoolField(TEXT("can_delete")));
			TestTrue(TEXT("protected root blocker"), JsonStringArrayContains(Blockers, TEXT("game_root_protected")));
		}
	}

	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(
	FUEEditorMCPAssetMaintenanceManifestPlanTest,
	"p110_2.UEEditorMCP.AssetMaintenance.ManifestPlan",
	EAutomationTestFlags::EditorContext | EAutomationTestFlags::EngineFilter)

bool FUEEditorMCPAssetMaintenanceManifestPlanTest::RunTest(const FString& Parameters)
{
	using namespace UEEditorMCPAssetMaintenanceTests;

	TArray<TSharedPtr<FJsonValue>> Items;
	Items.Add(MakeShared<FJsonValueObject>(MakeManifestRenameItem(
		TEXT("ren_0001"),
		TEXT("/Game/__MCPMissing/DA_A.DA_A"),
		TEXT("/Game/__MCPAssetMaintenance"),
		TEXT("DA_Conflict"),
		TEXT("DataAsset"))));
	Items.Add(MakeShared<FJsonValueObject>(MakeManifestRenameItem(
		TEXT("ren_0002"),
		TEXT("/Game/__MCPMissing/DA_B.DA_B"),
		TEXT("/Game/__MCPAssetMaintenance"),
		TEXT("DA_Conflict"),
		TEXT("DataAsset"))));

	TSharedPtr<FJsonObject> Manifest = MakeManifest(Items);
	TSharedPtr<FJsonObject> Cleanup = MakeShared<FJsonObject>();
	TArray<TSharedPtr<FJsonValue>> EmptyDirectories;
	EmptyDirectories.Add(MakeShared<FJsonValueString>(TEXT("/Game/__MCPAssetMaintenance/Old")));
	Cleanup->SetArrayField(TEXT("empty_directories"), EmptyDirectories);
	Manifest->SetObjectField(TEXT("cleanup"), Cleanup);

	TSharedPtr<FJsonObject> Params = MakeShared<FJsonObject>();
	Params->SetStringField(TEXT("mode"), TEXT("plan"));
	Params->SetObjectField(TEXT("manifest"), Manifest);
	Params->SetBoolField(TEXT("include_referencers"), false);

	TSharedPtr<FJsonObject> Result = Execute(TEXT("process_asset_maintenance_manifest"), Params);
	TestNotNull(TEXT("manifest result"), Result.Get());
	if (!Result.IsValid())
	{
		return false;
	}

	TestTrue(TEXT("manifest command succeeds structurally"), Result->GetBoolField(TEXT("success")));
	TestTrue(TEXT("dry run"), Result->GetBoolField(TEXT("dry_run")));
	TestTrue(TEXT("has blockers"), Result->GetBoolField(TEXT("has_blockers")));
	TestEqual(TEXT("requested rename count"), static_cast<int32>(Result->GetIntegerField(TEXT("requested_rename_count"))), 2);
	TestEqual(TEXT("cleanup directory count"), static_cast<int32>(Result->GetIntegerField(TEXT("cleanup_directory_count"))), 1);
	TestFalse(TEXT("plan hash is non-empty"), Result->GetStringField(TEXT("plan_hash")).IsEmpty());

	const TArray<TSharedPtr<FJsonValue>>* ResultItems = nullptr;
	TestTrue(TEXT("items array exists"), Result->TryGetArrayField(TEXT("items"), ResultItems));
	TestTrue(TEXT("two items"), ResultItems && ResultItems->Num() == 2);
	if (ResultItems && ResultItems->Num() == 2)
	{
		const TSharedPtr<FJsonObject> FirstItem = (*ResultItems)[0]->AsObject();
		TestTrue(TEXT("first item object valid"), FirstItem.IsValid());
		if (FirstItem.IsValid())
		{
			const TArray<TSharedPtr<FJsonValue>>* Blockers = nullptr;
			TestTrue(TEXT("blockers array exists"), FirstItem->TryGetArrayField(TEXT("blockers"), Blockers));
			TestEqual(TEXT("manifest id copied"), FirstItem->GetStringField(TEXT("manifest_id")), FString(TEXT("ren_0001")));
			TestFalse(TEXT("cannot rename blocked item"), FirstItem->GetBoolField(TEXT("can_rename")));
			TestTrue(TEXT("missing source blocker"), JsonStringArrayContains(Blockers, TEXT("source_asset_not_found")));
			TestTrue(TEXT("duplicate destination blocker"), JsonStringArrayContains(Blockers, TEXT("duplicate_destination_in_plan")));
		}
	}

	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(
	FUEEditorMCPAssetMaintenanceManifestUnsupportedDeleteTest,
	"p110_2.UEEditorMCP.AssetMaintenance.ManifestRejectsDeleteAsset",
	EAutomationTestFlags::EditorContext | EAutomationTestFlags::EngineFilter)

bool FUEEditorMCPAssetMaintenanceManifestUnsupportedDeleteTest::RunTest(const FString& Parameters)
{
	using namespace UEEditorMCPAssetMaintenanceTests;

	TSharedPtr<FJsonObject> DeleteItem = MakeShared<FJsonObject>();
	DeleteItem->SetStringField(TEXT("id"), TEXT("del_0001"));
	DeleteItem->SetStringField(TEXT("op"), TEXT("delete_asset"));
	DeleteItem->SetStringField(TEXT("path"), TEXT("/Game/__MCPMissing/DA_None.DA_None"));

	TArray<TSharedPtr<FJsonValue>> Items;
	Items.Add(MakeShared<FJsonValueObject>(DeleteItem));

	TSharedPtr<FJsonObject> Params = MakeShared<FJsonObject>();
	Params->SetStringField(TEXT("mode"), TEXT("plan"));
	Params->SetObjectField(TEXT("manifest"), MakeManifest(Items));

	TSharedPtr<FJsonObject> Result = Execute(TEXT("process_asset_maintenance_manifest"), Params);
	TestNotNull(TEXT("manifest result"), Result.Get());
	if (!Result.IsValid())
	{
		return false;
	}

	TestTrue(TEXT("manifest command succeeds structurally"), Result->GetBoolField(TEXT("success")));
	TestTrue(TEXT("has blockers"), Result->GetBoolField(TEXT("has_blockers")));

	const TArray<TSharedPtr<FJsonValue>>* ManifestBlockers = nullptr;
	TestTrue(TEXT("manifest blockers array exists"), Result->TryGetArrayField(TEXT("manifest_blockers"), ManifestBlockers));
	TestTrue(TEXT("delete asset is blocked"), JsonStringArrayContainsPrefix(ManifestBlockers, TEXT("items[0].delete_asset_unsupported_use_editor_delete_assets")));

	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(
	FUEEditorMCPAssetMaintenanceManifestApplyRequiresHashTest,
	"p110_2.UEEditorMCP.AssetMaintenance.ManifestApplyRequiresHash",
	EAutomationTestFlags::EditorContext | EAutomationTestFlags::EngineFilter)

bool FUEEditorMCPAssetMaintenanceManifestApplyRequiresHashTest::RunTest(const FString& Parameters)
{
	using namespace UEEditorMCPAssetMaintenanceTests;

	TArray<TSharedPtr<FJsonValue>> Items;
	Items.Add(MakeShared<FJsonValueObject>(MakeManifestRenameItem(
		TEXT("ren_0001"),
		TEXT("/Game/__MCPMissing/DA_A.DA_A"),
		TEXT("/Game/__MCPAssetMaintenance"),
		TEXT("DA_A2"))));

	TSharedPtr<FJsonObject> Params = MakeShared<FJsonObject>();
	Params->SetStringField(TEXT("mode"), TEXT("apply"));
	Params->SetObjectField(TEXT("manifest"), MakeManifest(Items));
	Params->SetBoolField(TEXT("include_referencers"), false);

	TSharedPtr<FJsonObject> Result = Execute(TEXT("process_asset_maintenance_manifest"), Params);
	TestNotNull(TEXT("manifest result"), Result.Get());
	if (!Result.IsValid())
	{
		return false;
	}

	TestTrue(TEXT("manifest command returns plan payload"), Result->GetBoolField(TEXT("success")));
	TestEqual(TEXT("error type"), Result->GetStringField(TEXT("error_type")), FString(TEXT("confirmation_required")));
	TestFalse(TEXT("plan hash is non-empty"), Result->GetStringField(TEXT("plan_hash")).IsEmpty());

	return true;
}

#endif // WITH_DEV_AUTOMATION_TESTS
