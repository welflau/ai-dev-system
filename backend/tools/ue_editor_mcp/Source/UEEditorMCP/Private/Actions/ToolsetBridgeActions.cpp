// Copyright (c) 2025 zolnoor. All rights reserved.

#include "Actions/ToolsetBridgeActions.h"

#include "Editor.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"
#include "ToolsetRegistry/Toolset.h"
#include "ToolsetRegistry/ToolsetRegistry.h"
#include "ToolsetRegistry/ToolsetRegistrySubsystem.h"

namespace UEEditorMCPToolsets
{
	struct FToolJob
	{
		FString Id;
		FString ToolsetName;
		FString ToolName;
		FDateTime CreatedAtUtc;
		TSharedPtr<TFuture<TValueOrError<FString, FString>>> Future;
	};

	static TMap<FString, TSharedPtr<FToolJob>> Jobs;
	static FCriticalSection JobsMutex;
	static constexpr double DefaultWaitSeconds = 0.15;

	static UE::ToolsetRegistry::FToolsetRegistry* GetRegistry()
	{
		UToolsetRegistrySubsystem* Subsystem = GEditor ? GEditor->GetEditorSubsystem<UToolsetRegistrySubsystem>() : nullptr;
		return Subsystem ? &Subsystem->ToolsetRegistry : nullptr;
	}

	static TSharedPtr<FJsonObject> MakeToolResultObject(const FString& Text)
	{
		TSharedPtr<FJsonObject> Result = MakeShared<FJsonObject>();
		Result->SetStringField(TEXT("content_type"), TEXT("tool_result"));
		Result->SetStringField(TEXT("text"), Text);

		TSharedPtr<FJsonObject> ParsedObject;
		TSharedRef<TJsonReader<>> Reader = TJsonReaderFactory<>::Create(Text);
		if (FJsonSerializer::Deserialize(Reader, ParsedObject) && ParsedObject.IsValid())
		{
			Result->SetObjectField(TEXT("object"), ParsedObject);
		}
		return Result;
	}

	static void SetJobFields(const TSharedPtr<FJsonObject>& Result, const FToolJob& Job, const FString& Status)
	{
		Result->SetStringField(TEXT("job_id"), Job.Id);
		Result->SetStringField(TEXT("status"), Status);
		Result->SetStringField(TEXT("toolset_name"), Job.ToolsetName);
		Result->SetStringField(TEXT("tool_name"), Job.ToolName);
		Result->SetStringField(TEXT("created_at_utc"), Job.CreatedAtUtc.ToIso8601());
		Result->SetStringField(TEXT("poll_tool"), TEXT("tool_job_status"));
		Result->SetStringField(TEXT("poll_instruction"), TEXT("This is a long-running ToolsetRegistry call. Poll tool_job_status with job_id until status is completed or failed."));
	}

	static TSharedPtr<FJsonObject> CompleteJobResult(const FToolJob& Job, TValueOrError<FString, FString>&& Value)
	{
		TSharedPtr<FJsonObject> Result = MakeShared<FJsonObject>();
		SetJobFields(Result, Job, Value.HasError() ? TEXT("failed") : TEXT("completed"));
		if (Value.HasError())
		{
			Result->SetStringField(TEXT("error"), Value.GetError());
		}
		else
		{
			Result->SetObjectField(TEXT("result"), MakeToolResultObject(Value.GetValue()));
		}
		return Result;
	}
}

TSharedPtr<FJsonObject> FListToolsetsAction::ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context)
{
	UE::ToolsetRegistry::FToolsetRegistry* Registry = UEEditorMCPToolsets::GetRegistry();
	if (!Registry)
	{
		return CreateErrorResponse(TEXT("ToolsetRegistry not available"), TEXT("toolset_registry_unavailable"));
	}

	TArray<TSharedPtr<FJsonValue>> Toolsets;
	Registry->ForEachToolset([&Toolsets](const FString& Name, const UE::ToolsetRegistry::FToolset& Toolset)
	{
		TSharedPtr<FJsonObject> Entry = MakeShared<FJsonObject>();
		Entry->SetStringField(TEXT("name"), Name);
		Entry->SetStringField(TEXT("description"), Toolset.GetToolsetDescription());
		Entry->SetStringField(TEXT("version"), Toolset.GetToolsetVersion());
		Toolsets.Add(MakeShared<FJsonValueObject>(Entry));
	});

	TSharedPtr<FJsonObject> Result = MakeShared<FJsonObject>();
	Result->SetStringField(TEXT("purpose"), TEXT("Official UE ToolsetRegistry discovery. Use describe_toolset next, then call_tool to execute a tool."));
	Result->SetArrayField(TEXT("toolsets"), Toolsets);
	Result->SetNumberField(TEXT("count"), Toolsets.Num());
	return CreateSuccessResponse(Result);
}

bool FDescribeToolsetAction::Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError)
{
	FString ToolsetName;
	return GetRequiredString(Params, TEXT("toolset_name"), ToolsetName, OutError);
}

TSharedPtr<FJsonObject> FDescribeToolsetAction::ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context)
{
	UE::ToolsetRegistry::FToolsetRegistry* Registry = UEEditorMCPToolsets::GetRegistry();
	if (!Registry)
	{
		return CreateErrorResponse(TEXT("ToolsetRegistry not available"), TEXT("toolset_registry_unavailable"));
	}

	FString ToolsetName;
	Params->TryGetStringField(TEXT("toolset_name"), ToolsetName);

	TSharedPtr<UE::ToolsetRegistry::FToolset> Toolset = Registry->Find(ToolsetName);
	if (!Toolset.IsValid())
	{
		TArray<FString> Names;
		Registry->ForEachToolset([&Names](const FString& Name, const UE::ToolsetRegistry::FToolset&)
		{
			Names.Add(Name);
		});
		return CreateErrorResponse(FString::Printf(TEXT("Toolset '%s' not found. Available toolsets: %s"), *ToolsetName, *FString::Join(Names, TEXT(", "))), TEXT("toolset_not_found"));
	}

	TSharedPtr<FJsonObject> Result = MakeShared<FJsonObject>();
	Result->SetStringField(TEXT("purpose"), TEXT("Official UE ToolsetRegistry schema. Use call_tool with this toolset_name, a tool_name from the schema, and schema-matching arguments."));
	Result->SetStringField(TEXT("toolset_name"), ToolsetName);
	Result->SetStringField(TEXT("schema_json"), Toolset->GetJsonSchema());

	TSharedPtr<FJsonObject> ParsedSchema;
	TSharedRef<TJsonReader<>> Reader = TJsonReaderFactory<>::Create(Toolset->GetJsonSchema());
	if (FJsonSerializer::Deserialize(Reader, ParsedSchema) && ParsedSchema.IsValid())
	{
		Result->SetObjectField(TEXT("schema"), ParsedSchema);
	}
	return CreateSuccessResponse(Result);
}

bool FCallToolAction::Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError)
{
	FString ToolName;
	return GetRequiredString(Params, TEXT("tool_name"), ToolName, OutError);
}

TSharedPtr<FJsonObject> FCallToolAction::ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context)
{
	UE::ToolsetRegistry::FToolsetRegistry* Registry = UEEditorMCPToolsets::GetRegistry();
	if (!Registry)
	{
		return CreateErrorResponse(TEXT("ToolsetRegistry not available"), TEXT("toolset_registry_unavailable"));
	}

	FString ToolsetName;
	Params->TryGetStringField(TEXT("toolset_name"), ToolsetName);
	FString ToolName;
	Params->TryGetStringField(TEXT("tool_name"), ToolName);

	if (ToolsetName.IsEmpty())
	{
		return CreateErrorResponse(TEXT("UEEditorMCP call_tool bridge requires toolset_name. Top-level MCP self-dispatch is intentionally not supported."), TEXT("missing_toolset_name"));
	}

	FString QualifiedToolName = ToolName;
	if (!QualifiedToolName.StartsWith(ToolsetName + TEXT(".")))
	{
		QualifiedToolName = ToolsetName + TEXT(".") + ToolName;
	}

	const TSharedPtr<FJsonObject>* ArgumentsObject = nullptr;
	TSharedPtr<FJsonObject> Arguments = MakeShared<FJsonObject>();
	if (Params->TryGetObjectField(TEXT("arguments"), ArgumentsObject) && ArgumentsObject && ArgumentsObject->IsValid())
	{
		Arguments = *ArgumentsObject;
	}

	FString ArgumentsJson;
	TSharedRef<TJsonWriter<>> Writer = TJsonWriterFactory<>::Create(&ArgumentsJson);
	if (!FJsonSerializer::Serialize(Arguments.ToSharedRef(), Writer))
	{
		return CreateErrorResponse(TEXT("Failed to serialize arguments JSON for ToolsetRegistry call."), TEXT("json_serialize_failed"));
	}

	const double WaitSeconds = FMath::Max(0.0, GetOptionalNumber(Params, TEXT("wait_seconds"), UEEditorMCPToolsets::DefaultWaitSeconds));
	TFuture<TValueOrError<FString, FString>> Future = Registry->ExecuteTool(QualifiedToolName, ArgumentsJson);

	if (Future.WaitFor(FTimespan::FromSeconds(WaitSeconds)))
	{
		TValueOrError<FString, FString> ToolResult = Future.Get();
		if (ToolResult.HasError())
		{
			return CreateErrorResponse(ToolResult.GetError(), TEXT("tool_call_failed"));
		}

		TSharedPtr<FJsonObject> Result = MakeShared<FJsonObject>();
		Result->SetStringField(TEXT("purpose"), TEXT("Official UE ToolsetRegistry call_tool result."));
		Result->SetStringField(TEXT("toolset_name"), ToolsetName);
		Result->SetStringField(TEXT("tool_name"), ToolName);
		Result->SetStringField(TEXT("mode"), TEXT("completed_inline"));
		Result->SetObjectField(TEXT("result"), UEEditorMCPToolsets::MakeToolResultObject(ToolResult.GetValue()));
		return CreateSuccessResponse(Result);
	}

	TSharedPtr<UEEditorMCPToolsets::FToolJob> Job = MakeShared<UEEditorMCPToolsets::FToolJob>();
	Job->Id = FGuid::NewGuid().ToString(EGuidFormats::DigitsWithHyphensLower);
	Job->ToolsetName = ToolsetName;
	Job->ToolName = ToolName;
	Job->CreatedAtUtc = FDateTime::UtcNow();
	Job->Future = MakeShared<TFuture<TValueOrError<FString, FString>>>(MoveTemp(Future));

	{
		FScopeLock Lock(&UEEditorMCPToolsets::JobsMutex);
		UEEditorMCPToolsets::Jobs.Add(Job->Id, Job);
	}

	TSharedPtr<FJsonObject> Result = MakeShared<FJsonObject>();
	UEEditorMCPToolsets::SetJobFields(Result, *Job, TEXT("running"));
	Result->SetStringField(TEXT("purpose"), TEXT("Official UE ToolsetRegistry call_tool accepted as a long-running job. Do not wait on this MCP request; poll tool_job_status."));
	return CreateSuccessResponse(Result);
}

bool FToolJobStatusAction::Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError)
{
	FString JobId;
	return GetRequiredString(Params, TEXT("job_id"), JobId, OutError);
}

TSharedPtr<FJsonObject> FToolJobStatusAction::ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context)
{
	FString JobId;
	Params->TryGetStringField(TEXT("job_id"), JobId);

	TSharedPtr<UEEditorMCPToolsets::FToolJob> Job;
	{
		FScopeLock Lock(&UEEditorMCPToolsets::JobsMutex);
		if (TSharedPtr<UEEditorMCPToolsets::FToolJob>* Found = UEEditorMCPToolsets::Jobs.Find(JobId))
		{
			Job = *Found;
		}
	}

	if (!Job.IsValid())
	{
		return CreateErrorResponse(FString::Printf(TEXT("Tool job '%s' not found"), *JobId), TEXT("job_not_found"));
	}

	if (!Job->Future.IsValid() || !Job->Future->IsValid())
	{
		return CreateErrorResponse(FString::Printf(TEXT("Tool job '%s' has invalid future"), *JobId), TEXT("job_invalid"));
	}

	if (!Job->Future->IsReady())
	{
		TSharedPtr<FJsonObject> Result = MakeShared<FJsonObject>();
		UEEditorMCPToolsets::SetJobFields(Result, *Job, TEXT("running"));
		return CreateSuccessResponse(Result);
	}

	TValueOrError<FString, FString> ToolResult = Job->Future->Get();
	TSharedPtr<FJsonObject> Result = UEEditorMCPToolsets::CompleteJobResult(*Job, MoveTemp(ToolResult));

	{
		FScopeLock Lock(&UEEditorMCPToolsets::JobsMutex);
		UEEditorMCPToolsets::Jobs.Remove(JobId);
	}

	return CreateSuccessResponse(Result);
}