#if WITH_DEV_AUTOMATION_TESTS

#include "Misc/AutomationTest.h"
#include "MCPBridge.h"
#include "Editor.h"
#include "Dom/JsonObject.h"
#include "Dom/JsonValue.h"

namespace UEEditorMCPBatchTests
{
	static TSharedPtr<FJsonObject> MakeCommand(const FString& Type, const FString& ActionId, const TSharedPtr<FJsonObject>& Params = nullptr)
	{
		TSharedPtr<FJsonObject> Command = MakeShared<FJsonObject>();
		if (!Type.IsEmpty())
		{
			Command->SetStringField(TEXT("type"), Type);
		}
		if (!ActionId.IsEmpty())
		{
			Command->SetStringField(TEXT("action_id"), ActionId);
		}
		Command->SetObjectField(TEXT("params"), Params.IsValid() ? Params : MakeShared<FJsonObject>());
		return Command;
	}

	static TSharedPtr<FJsonObject> ExecuteBatch(const TArray<TSharedPtr<FJsonValue>>& Commands, bool bStopOnError, const FString& Verbosity = TEXT("compact"))
	{
		UMCPBridge* Bridge = GEditor ? GEditor->GetEditorSubsystem<UMCPBridge>() : nullptr;
		if (!Bridge)
		{
			return nullptr;
		}

		TSharedPtr<FJsonObject> Params = MakeShared<FJsonObject>();
		Params->SetArrayField(TEXT("commands"), Commands);
		Params->SetBoolField(TEXT("stop_on_error"), bStopOnError);
		Params->SetStringField(TEXT("result_verbosity"), Verbosity);
		return Bridge->ExecuteCommand(TEXT("batch_execute"), Params);
	}
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(
	FUEEditorMCPBatchCompactFailuresTest,
	"P111.UEEditorMCP.Batch.CompactFailures",
	EAutomationTestFlags::EditorContext | EAutomationTestFlags::EngineFilter)

bool FUEEditorMCPBatchCompactFailuresTest::RunTest(const FString& Parameters)
{
	using namespace UEEditorMCPBatchTests;

	TArray<TSharedPtr<FJsonValue>> Commands;
	Commands.Add(MakeShared<FJsonValueObject>(MakeCommand(TEXT("is_ready"), TEXT("editor.is_ready"))));
	Commands.Add(MakeShared<FJsonValueObject>(MakeCommand(TEXT(""), TEXT("broken.missing_type"))));

	TSharedPtr<FJsonObject> Result = ExecuteBatch(Commands, false);
	TestNotNull(TEXT("batch result"), Result.Get());
	if (!Result.IsValid())
	{
		return false;
	}

	TestTrue(TEXT("batch command succeeds structurally"), Result->GetBoolField(TEXT("success")));
	TestEqual(TEXT("total"), static_cast<int32>(Result->GetIntegerField(TEXT("total"))), 2);
	TestEqual(TEXT("executed"), static_cast<int32>(Result->GetIntegerField(TEXT("executed"))), 2);
	TestEqual(TEXT("failed"), static_cast<int32>(Result->GetIntegerField(TEXT("failed"))), 1);
	TestTrue(TEXT("has_failures"), Result->GetBoolField(TEXT("has_failures")));
	TestEqual(TEXT("first_failure_index"), static_cast<int32>(Result->GetIntegerField(TEXT("first_failure_index"))), 1);

	const TArray<TSharedPtr<FJsonValue>>* Failures = nullptr;
	TestTrue(TEXT("failures array exists"), Result->TryGetArrayField(TEXT("failures"), Failures));
	TestTrue(TEXT("one failure"), Failures && Failures->Num() == 1);
	if (Failures && Failures->Num() == 1)
	{
		const TSharedPtr<FJsonObject> Failure = (*Failures)[0]->AsObject();
		TestEqual(TEXT("failure action id"), Failure->GetStringField(TEXT("action_id")), FString(TEXT("broken.missing_type")));
		TestEqual(TEXT("failure error type"), Failure->GetStringField(TEXT("error_type")), FString(TEXT("invalid_command")));
	}

	const TArray<TSharedPtr<FJsonValue>>* Results = nullptr;
	TestTrue(TEXT("results array exists"), Result->TryGetArrayField(TEXT("results"), Results));
	TestTrue(TEXT("compact results count"), Results && Results->Num() == 2);
	if (Results && Results->Num() == 2)
	{
		const TSharedPtr<FJsonObject> First = (*Results)[0]->AsObject();
		TestFalse(TEXT("compact result omits verbose readiness field"), First->HasField(TEXT("editor_valid")));
		TestEqual(TEXT("compact result action id"), First->GetStringField(TEXT("action_id")), FString(TEXT("editor.is_ready")));
	}

	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(
	FUEEditorMCPBatchRefFailureTest,
	"P111.UEEditorMCP.Batch.RefFailure",
	EAutomationTestFlags::EditorContext | EAutomationTestFlags::EngineFilter)

bool FUEEditorMCPBatchRefFailureTest::RunTest(const FString& Parameters)
{
	using namespace UEEditorMCPBatchTests;

	TSharedPtr<FJsonObject> RefParams = MakeShared<FJsonObject>();
	TSharedPtr<FJsonObject> RefObject = MakeShared<FJsonObject>();
	RefObject->SetStringField(TEXT("$ref"), TEXT("steps[0].missing_field"));
	RefParams->SetObjectField(TEXT("name"), RefObject);

	TArray<TSharedPtr<FJsonValue>> Commands;
	Commands.Add(MakeShared<FJsonValueObject>(MakeCommand(TEXT("is_ready"), TEXT("editor.is_ready"))));
	Commands.Add(MakeShared<FJsonValueObject>(MakeCommand(TEXT("get_actor_properties"), TEXT("editor.get_actor_properties"), RefParams)));

	TSharedPtr<FJsonObject> Result = ExecuteBatch(Commands, true);
	TestNotNull(TEXT("batch result"), Result.Get());
	if (!Result.IsValid())
	{
		return false;
	}

	TestTrue(TEXT("batch command succeeds structurally"), Result->GetBoolField(TEXT("success")));
	TestEqual(TEXT("executed stops at ref failure"), static_cast<int32>(Result->GetIntegerField(TEXT("executed"))), 2);
	TestEqual(TEXT("failed"), static_cast<int32>(Result->GetIntegerField(TEXT("failed"))), 1);
	TestEqual(TEXT("first_failure_index"), static_cast<int32>(Result->GetIntegerField(TEXT("first_failure_index"))), 1);

	const TArray<TSharedPtr<FJsonValue>>* Failures = nullptr;
	TestTrue(TEXT("failures array exists"), Result->TryGetArrayField(TEXT("failures"), Failures));
	TestTrue(TEXT("one failure"), Failures && Failures->Num() == 1);
	if (Failures && Failures->Num() == 1)
	{
		const TSharedPtr<FJsonObject> Failure = (*Failures)[0]->AsObject();
		TestEqual(TEXT("ref error type"), Failure->GetStringField(TEXT("error_type")), FString(TEXT("ref_resolution_failed")));
	}

	return true;
}

#endif // WITH_DEV_AUTOMATION_TESTS
