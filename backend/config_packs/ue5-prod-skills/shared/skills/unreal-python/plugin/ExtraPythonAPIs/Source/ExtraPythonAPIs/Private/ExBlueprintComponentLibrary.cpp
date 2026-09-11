// Copyright Epic Games, Inc. All Rights Reserved.

#include "ExBlueprintComponentLibrary.h"
#include "SubobjectData.h"
#include "SubobjectDataSubsystem.h"

DEFINE_LOG_CATEGORY_STATIC(LogExtraPythonAPIs, Log, All);

bool UExBlueprintComponentLibrary::SetComponentSocketAttachment(const FSubobjectDataHandle& Handle, FName SocketName)
{
	// Get the SubobjectData from the handle
	FSubobjectData* Data = Handle.GetData();
	if (!Data)
	{
		UE_LOG(LogExtraPythonAPIs, Warning, TEXT("SetComponentSocketAttachment: Invalid handle"));
		return false;
	}

	// Use the public SetSocketName method which properly sets SCS_Node->AttachToName
	Data->SetSocketName(SocketName);

	UE_LOG(LogExtraPythonAPIs, Log, TEXT("SetComponentSocketAttachment: Set socket to '%s'"), *SocketName.ToString());
	return true;
}

FName UExBlueprintComponentLibrary::GetComponentSocketAttachment(const FSubobjectDataHandle& Handle)
{
	FSubobjectData* Data = Handle.GetData();
	if (!Data)
	{
		return NAME_None;
	}

	// Use the public GetSocketFName method
	return Data->GetSocketFName();
}

bool UExBlueprintComponentLibrary::SetupComponentAttachment(
	const FSubobjectDataHandle& ChildHandle,
	const FSubobjectDataHandle& ParentHandle,
	FName SocketName
)
{
	// Get child data
	FSubobjectData* ChildData = ChildHandle.GetData();
	if (!ChildData)
	{
		UE_LOG(LogExtraPythonAPIs, Warning, TEXT("SetupComponentAttachment: Invalid child handle"));
		return false;
	}

	// Get parent data
	FSubobjectData* ParentData = ParentHandle.GetData();
	if (!ParentData)
	{
		UE_LOG(LogExtraPythonAPIs, Warning, TEXT("SetupComponentAttachment: Invalid parent handle"));
		return false;
	}

	// NOTE: FSubobjectData::SetupAttachment ignores the SocketName parameter and sets AttachToName to NAME_None!
	// So we need to call SetupAttachment first (to set parent), then SetSocketName separately.

	// First set up the parent attachment (this sets socket to NAME_None internally)
	ChildData->SetupAttachment(NAME_None, ParentHandle);

	// Then set the socket name separately (this properly sets SCS_Node->AttachToName)
	ChildData->SetSocketName(SocketName);

	UE_LOG(LogExtraPythonAPIs, Log, TEXT("SetupComponentAttachment: Attached to socket '%s'"), *SocketName.ToString());
	return true;
}
