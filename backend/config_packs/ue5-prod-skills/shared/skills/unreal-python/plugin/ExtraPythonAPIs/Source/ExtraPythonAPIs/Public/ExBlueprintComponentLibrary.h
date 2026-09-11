// Copyright Epic Games, Inc. All Rights Reserved.

#pragma once

#include "CoreMinimal.h"
#include "Kismet/BlueprintFunctionLibrary.h"
#include "SubobjectDataHandle.h"
#include "ExBlueprintComponentLibrary.generated.h"

class UBlueprint;
struct FSubobjectDataHandle;

/**
 * Python/Blueprint utility library for manipulating Blueprint components
 * Specifically provides access to SCS_Node properties that are not exposed to Python
 *
 * This library fills the gap in UE5's Python API where setting socket/bone attachment
 * for Blueprint components (SCS_Node.AttachToName) is not possible.
 */
UCLASS()
class EXTRAPYTHONAPIS_API UExBlueprintComponentLibrary : public UBlueprintFunctionLibrary
{
	GENERATED_BODY()

public:
	/**
	 * Set the socket/bone name that a Blueprint component should attach to
	 * This sets the SCS_Node.AttachToName property which is not exposed to Python
	 *
	 * @param Handle The subobject data handle for the component (from SubobjectDataSubsystem)
	 * @param SocketName The socket/bone name to attach to
	 * @return True if successful
	 */
	UFUNCTION(BlueprintCallable, Category = "Python|BlueprintComponent", meta = (DevelopmentOnly))
	static bool SetComponentSocketAttachment(const FSubobjectDataHandle& Handle, FName SocketName);

	/**
	 * Get the socket/bone name that a Blueprint component is attached to
	 *
	 * @param Handle The subobject data handle for the component
	 * @return The socket name, or NAME_None if not attached to a socket
	 */
	UFUNCTION(BlueprintPure, Category = "Python|BlueprintComponent", meta = (DevelopmentOnly))
	static FName GetComponentSocketAttachment(const FSubobjectDataHandle& Handle);

	/**
	 * Setup full attachment for a Blueprint component to a parent with socket
	 * This properly configures both the socket name and parent relationship in SCS_Node
	 *
	 * NOTE: UE5's FSubobjectData::SetupAttachment() ignores the SocketName parameter,
	 * so this function calls SetupAttachment first, then SetSocketName separately.
	 *
	 * @param ChildHandle The subobject data handle for the child component to attach
	 * @param ParentHandle The subobject data handle for the parent component
	 * @param SocketName The socket/bone name to attach to on the parent
	 * @return True if successful
	 */
	UFUNCTION(BlueprintCallable, Category = "Python|BlueprintComponent", meta = (DevelopmentOnly))
	static bool SetupComponentAttachment(
		const FSubobjectDataHandle& ChildHandle,
		const FSubobjectDataHandle& ParentHandle,
		FName SocketName
	);
};
