// Copyright (c) 2025 zolnoor. All rights reserved.

#include "Actions/UMGActions.h"
#include "MCPCommonUtils.h"
#include "Editor.h"
#include "EditorAssetLibrary.h"
#include "AssetRegistry/AssetRegistryModule.h"
#include "Blueprint/UserWidget.h"
#include "Components/TextBlock.h"
#include "WidgetBlueprint.h"
#include "WidgetBlueprintEditor.h"
#include "Blueprint/WidgetTree.h"
#include "Components/CanvasPanel.h"
#include "Components/CanvasPanelSlot.h"
#include "Components/PanelWidget.h"
#include "Components/PanelSlot.h"
#include "Kismet2/BlueprintEditorUtils.h"
#include "Components/Button.h"
#include "Components/Image.h"
#include "Components/Border.h"
#include "Components/Overlay.h"
#include "Components/HorizontalBox.h"
#include "Components/VerticalBox.h"
#include "Components/Slider.h"
#include "Components/ProgressBar.h"
#include "Components/SizeBox.h"
#include "Components/ScaleBox.h"
#include "Components/VerticalBoxSlot.h"
#include "Components/HorizontalBoxSlot.h"
#include "Components/OverlaySlot.h"
#include "Components/ComboBoxString.h"
#include "Components/CheckBox.h"

// MVVM includes
#include "MVVMBlueprintView.h"
#include "MVVMWidgetBlueprintExtension_View.h"
#include "MVVMBlueprintViewModelContext.h"
#include "MVVMBlueprintViewBinding.h"
#include "MVVMBlueprintViewEvent.h"
#include "MVVMPropertyPath.h"
#include "Types/MVVMBindingMode.h"
#include "Types/MVVMExecutionMode.h"
#include "INotifyFieldValueChanged.h"
#include "Components/SpinBox.h"
#include "Components/EditableTextBox.h"
#include "Dom/JsonValue.h"
#include "K2Node_CallFunction.h"
#include "K2Node_FunctionEntry.h"
#include "K2Node_VariableGet.h"
#include "K2Node_CustomEvent.h"
#include "K2Node_ComponentBoundEvent.h"

#include "Kismet2/KismetEditorUtilities.h"
#include "Engine/Texture2D.h"
#include "Components/ScrollBox.h"
#include "Components/WidgetSwitcher.h"
#include "Components/BackgroundBlur.h"
#include "Components/UniformGridPanel.h"
#include "Components/Spacer.h"
#include "Components/RichTextBlock.h"
#include "Components/WrapBox.h"
#include "Components/CircularThrobber.h"
#include "ObjectTools.h"
#include "ScopedTransaction.h"


#define LOCTEXT_NAMESPACE "UEEditorMCPUMGActions"

// Helper to find widget blueprint anywhere under /Game/

static UWidgetBlueprint* FindWidgetBlueprintByName(const FString& BlueprintName)
{
	// If the name already contains a full path (e.g. /Game/UI/MyWidget), try it directly first
	if (BlueprintName.StartsWith(TEXT("/Game/")))
	{
		if (UEditorAssetLibrary::DoesAssetExist(BlueprintName))
		{
			UWidgetBlueprint* Widget = Cast<UWidgetBlueprint>(UEditorAssetLibrary::LoadAsset(BlueprintName));
			if (Widget)
			{
				return Widget;
			}
		}
	}

	// Try common paths first for speed
	TArray<FString> PriorityPaths = {
		FString::Printf(TEXT("/Game/UI/%s"), *BlueprintName),
		FString::Printf(TEXT("/Game/Widgets/%s"), *BlueprintName),
		FString::Printf(TEXT("/Game/%s"), *BlueprintName)
	};

	for (const FString& Path : PriorityPaths)
	{
		if (UEditorAssetLibrary::DoesAssetExist(Path))
		{
			UWidgetBlueprint* Widget = Cast<UWidgetBlueprint>(UEditorAssetLibrary::LoadAsset(Path));
			if (Widget)
			{
				return Widget;
			}
		}
	}

	// Fall back to Asset Registry: search all WidgetBlueprints under /Game/ recursively
	FAssetRegistryModule& AssetRegistryModule = FModuleManager::LoadModuleChecked<FAssetRegistryModule>("AssetRegistry");
	IAssetRegistry& AssetRegistry = AssetRegistryModule.Get();

	TArray<FAssetData> AssetList;
	AssetRegistry.GetAssetsByClass(UWidgetBlueprint::StaticClass()->GetClassPathName(), AssetList, true);

	for (const FAssetData& AssetData : AssetList)
	{
		if (AssetData.AssetName.ToString() == BlueprintName && AssetData.PackagePath.ToString().StartsWith(TEXT("/Game")))
		{
			UWidgetBlueprint* Widget = Cast<UWidgetBlueprint>(AssetData.GetAsset());
			if (Widget)
			{
				return Widget;
			}
		}
	}

	return nullptr;
}

static bool TryGetVector2Field(const TSharedPtr<FJsonObject>& Params, const FString& FieldName, FVector2D& OutValue)
{
	const TArray<TSharedPtr<FJsonValue>>* Array;
	if (!Params->TryGetArrayField(FieldName, Array) || Array->Num() < 2)
	{
		return false;
	}

	OutValue.X = (*Array)[0]->AsNumber();
	OutValue.Y = (*Array)[1]->AsNumber();
	return true;
}

static bool TryGetColorField(const TSharedPtr<FJsonObject>& Params, const FString& FieldName, FLinearColor& OutValue)
{
	const TArray<TSharedPtr<FJsonValue>>* Array;
	if (!Params->TryGetArrayField(FieldName, Array) || Array->Num() < 4)
	{
		return false;
	}

	OutValue = FLinearColor(
		(*Array)[0]->AsNumber(),
		(*Array)[1]->AsNumber(),
		(*Array)[2]->AsNumber(),
		(*Array)[3]->AsNumber());
	return true;
}

static void ApplyCanvasSlot(UCanvasPanelSlot* Slot, const TSharedPtr<FJsonObject>& Params)
{
	if (!Slot)
	{
		return;
	}

	const TArray<TSharedPtr<FJsonValue>>* AnchorsArray = nullptr;
	if (Params->TryGetArrayField(TEXT("anchors"), AnchorsArray) && AnchorsArray && AnchorsArray->Num() >= 4)
	{
		const float MinX = static_cast<float>((*AnchorsArray)[0]->AsNumber());
		const float MinY = static_cast<float>((*AnchorsArray)[1]->AsNumber());
		const float MaxX = static_cast<float>((*AnchorsArray)[2]->AsNumber());
		const float MaxY = static_cast<float>((*AnchorsArray)[3]->AsNumber());
		Slot->SetAnchors(FAnchors(MinX, MinY, MaxX, MaxY));
	}

	FVector2D Alignment;
	if (TryGetVector2Field(Params, TEXT("alignment"), Alignment))
	{
		Slot->SetAlignment(Alignment);
	}

	FVector2D Position;
	if (TryGetVector2Field(Params, TEXT("position"), Position))
	{
		Slot->SetPosition(Position);
	}

	FVector2D Size;
	if (TryGetVector2Field(Params, TEXT("size"), Size))
	{
		Slot->SetSize(Size);
		Slot->SetAutoSize(false);
	}

	int32 ZOrder = 0;
	if (Params->TryGetNumberField(TEXT("z_order"), ZOrder))
	{
		Slot->SetZOrder(ZOrder);
	}
}

/**
 * If "parent" parameter is present, reparent the newly created widget
 * from the root canvas into the specified parent container.
 * Returns true on success (or if no parent specified). Sets OutError on failure.
 */
static bool TryReparentToParent(UWidgetBlueprint* WidgetBlueprint, UWidget* NewWidget,
	const TSharedPtr<FJsonObject>& Params, FString& OutError)
{
	FString ParentName;
	if (!Params->TryGetStringField(TEXT("parent"), ParentName) || ParentName.IsEmpty())
	{
		return true; // No parent specified, keep in root canvas
	}

	UWidget* ParentWidget = WidgetBlueprint->WidgetTree->FindWidget(FName(*ParentName));
	if (!ParentWidget)
	{
		OutError = FString::Printf(TEXT("Parent widget '%s' not found"), *ParentName);
		return false;
	}

	UPanelWidget* ParentPanel = Cast<UPanelWidget>(ParentWidget);
	if (!ParentPanel)
	{
		OutError = FString::Printf(TEXT("Parent '%s' is not a container widget"), *ParentName);
		return false;
	}

	NewWidget->RemoveFromParent();
	UPanelSlot* NewSlot = ParentPanel->AddChild(NewWidget);
	if (!NewSlot)
	{
		OutError = FString::Printf(TEXT("Failed to add widget as child of '%s'"), *ParentName);
		return false;
	}

	return true;
}

/**
 * Repair: keep WidgetVariableNameToGuidMap in sync with the current WidgetTree.
 *
 * MCP-created widgets need GUID entries before WidgetBlueprintCompiler runs, while
 * deleted widgets must have stale GUID entries removed to avoid line 828 ensures.
 */
static void EnsureWidgetVariableGuids(UWidgetBlueprint* WidgetBlueprint)
{
	if (!WidgetBlueprint || !WidgetBlueprint->WidgetTree)
	{
		return;
	}

	TSet<FName> ExistingWidgetNames;
	WidgetBlueprint->WidgetTree->ForEachWidget([&](UWidget* Widget)
	{
		if (!Widget)
		{
			return;
		}

		const FName WidgetFName = Widget->GetFName();
		ExistingWidgetNames.Add(WidgetFName);
		if (!WidgetBlueprint->WidgetVariableNameToGuidMap.Contains(WidgetFName))
		{
			WidgetBlueprint->WidgetVariableNameToGuidMap.Add(WidgetFName, FGuid::NewGuid());
		}
	});

	for (TMap<FName, FGuid>::TIterator It = WidgetBlueprint->WidgetVariableNameToGuidMap.CreateIterator(); It; ++It)
	{
		if (!ExistingWidgetNames.Contains(It.Key()))
		{
			It.RemoveCurrent();
		}
	}
}

static void MarkWidgetBlueprintDirty(UWidgetBlueprint* WidgetBlueprint, FMCPEditorContext& Context)
{
	if (!WidgetBlueprint)
	{
		return;
	}

	// Repair WidgetVariableNameToGuidMap before triggering compilation.
	// MCP's ConstructWidget API adds controls to the WidgetTree but never writes to
	// this map.  Without this repair, WidgetBlueprintCompiler asserts:
	//   ensure(WidgetBP->WidgetVariableNameToGuidMap.Contains(Widget->GetFName()))
	EnsureWidgetVariableGuids(WidgetBlueprint);

	UPackage* Package = WidgetBlueprint->GetOutermost();
	Context.MarkPackageDirty(Package);

	// Use MarkBlueprintAsModified instead of MarkBlueprintAsStructurallyModified.
	// MarkBlueprintAsStructurallyModified triggers synchronous compilation which can
	// cause ensure() assertions in the Widget Designer editor when the Blueprint is open.
	// MarkBlueprintAsModified is safer - it marks the blueprint as needing recompilation
	// without triggering it immediately. The compile will happen when the user saves
	// or manually compiles the blueprint.
	if (!WidgetBlueprint->bBeingCompiled && WidgetBlueprint->Status != BS_BeingCreated)
	{
		FBlueprintEditorUtils::MarkBlueprintAsModified(WidgetBlueprint);
	}
}

// =============================================================================
// FCreateUMGWidgetBlueprintAction
// =============================================================================

bool FCreateUMGWidgetBlueprintAction::Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError)
{
	if (!Params->HasField(TEXT("widget_name")))
	{
		OutError = TEXT("Missing 'widget_name' parameter");
		return false;
	}
	return true;
}

TSharedPtr<FJsonObject> FCreateUMGWidgetBlueprintAction::ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context)
{
	FString BlueprintName = Params->GetStringField(TEXT("widget_name"));

	// Get optional path parameter
	FString PackagePath = TEXT("/Game/UI/");
	FString PathParam;
	if (Params->TryGetStringField(TEXT("path"), PathParam))
	{
		PackagePath = PathParam;
		if (!PackagePath.EndsWith(TEXT("/")))
		{
			PackagePath += TEXT("/");
		}
	}

	FString AssetName = BlueprintName;
	FString FullPath = PackagePath + AssetName;

	// Aggressive cleanup: remove any existing widget blueprint
	TArray<FString> PathsToCheck = {
		FullPath,
		TEXT("/Game/Widgets/") + AssetName,
		TEXT("/Game/UI/") + AssetName
	};

	for (const FString& CheckPath : PathsToCheck)
	{
		// Delete from disk first
		if (UEditorAssetLibrary::DoesAssetExist(CheckPath))
		{
			UE_LOG(LogMCP, Log, TEXT("Widget Blueprint exists at '%s', deleting from disk"), *CheckPath);
			UEditorAssetLibrary::DeleteAsset(CheckPath);
		}

		// Clean up from memory
		UPackage* ExistingPackage = FindPackage(nullptr, *CheckPath);
		if (ExistingPackage)
		{
			UBlueprint* ExistingBP = FindObject<UBlueprint>(ExistingPackage, *AssetName);
			if (!ExistingBP)
			{
				ExistingBP = FindObject<UBlueprint>(ExistingPackage, nullptr);
			}

			if (ExistingBP)
			{
				UE_LOG(LogMCP, Log, TEXT("Widget Blueprint '%s' found in memory, cleaning up"), *AssetName);
				FString TempName = FString::Printf(TEXT("%s_OLD_%d"), *AssetName, FMath::Rand());
				ExistingBP->Rename(*TempName, GetTransientPackage(), REN_DoNotDirty | REN_DontCreateRedirectors | REN_NonTransactional | REN_ForceNoResetLoaders);
				ExistingBP->ClearFlags(RF_Public | RF_Standalone);
				ExistingBP->MarkAsGarbage();
			}

			ExistingPackage->ClearFlags(RF_Public | RF_Standalone);
			ExistingPackage->MarkAsGarbage();
		}
	}

	// Force garbage collection
	CollectGarbage(GARBAGE_COLLECTION_KEEPFLAGS);

	// Create package
	UPackage* Package = CreatePackage(*FullPath);
	if (!Package)
	{
		return FMCPCommonUtils::CreateErrorResponse(TEXT("Failed to create package"));
	}

	// Double-check cleanup worked
	if (FindObject<UBlueprint>(Package, *AssetName))
	{
		return FMCPCommonUtils::CreateErrorResponse(FString::Printf(
			TEXT("Failed to clean up existing Widget Blueprint '%s'. Try restarting the editor."), *AssetName));
	}

	// Create Widget Blueprint
	UBlueprint* NewBlueprint = FKismetEditorUtilities::CreateBlueprint(
		UUserWidget::StaticClass(),
		Package,
		FName(*AssetName),
		BPTYPE_Normal,
		UWidgetBlueprint::StaticClass(),
		UBlueprintGeneratedClass::StaticClass(),
		FName("CreateUMGWidget")
	);

	UWidgetBlueprint* WidgetBlueprint = Cast<UWidgetBlueprint>(NewBlueprint);
	if (!WidgetBlueprint)
	{
		return FMCPCommonUtils::CreateErrorResponse(TEXT("Failed to create Widget Blueprint"));
	}

	// Add default Canvas Panel
	if (!WidgetBlueprint->WidgetTree->RootWidget)
	{
		UCanvasPanel* RootCanvas = WidgetBlueprint->WidgetTree->ConstructWidget<UCanvasPanel>(UCanvasPanel::StaticClass());
		WidgetBlueprint->WidgetTree->RootWidget = RootCanvas;
	}

	// Register asset with asset registry
	FAssetRegistryModule::AssetCreated(WidgetBlueprint);
	WidgetBlueprint->MarkPackageDirty();

	// Mark modified, compile, and refresh the Widget Designer
	MarkWidgetBlueprintDirty(WidgetBlueprint, Context);

	UE_LOG(LogMCP, Log, TEXT("Widget Blueprint '%s' created at '%s'"), *BlueprintName, *FullPath);

	TSharedPtr<FJsonObject> ResultObj = MakeShared<FJsonObject>();
	ResultObj->SetBoolField(TEXT("success"), true);
	ResultObj->SetStringField(TEXT("name"), BlueprintName);
	ResultObj->SetStringField(TEXT("path"), FullPath);
	return ResultObj;
}

// =============================================================================
// FAddTextBlockToWidgetAction
// =============================================================================

bool FAddTextBlockToWidgetAction::Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError)
{
	if (!Params->HasField(TEXT("widget_name")))
	{
		OutError = TEXT("Missing 'widget_name' parameter");
		return false;
	}
	if (!Params->HasField(TEXT("text_block_name")))
	{
		OutError = TEXT("Missing 'text_block_name' parameter");
		return false;
	}
	return true;
}

TSharedPtr<FJsonObject> FAddTextBlockToWidgetAction::ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context)
{
	FString BlueprintName = Params->GetStringField(TEXT("widget_name"));
	FString WidgetName = Params->GetStringField(TEXT("text_block_name"));

	UWidgetBlueprint* WidgetBlueprint = FindWidgetBlueprintByName(BlueprintName);
	if (!WidgetBlueprint)
	{
		return FMCPCommonUtils::CreateErrorResponse(FString::Printf(
			TEXT("Widget Blueprint '%s' not found in /Game/UI, /Game/Widgets, or /Game"), *BlueprintName));
	}

	// Optional parameters
	FString InitialText = TEXT("New Text Block");
	Params->TryGetStringField(TEXT("text"), InitialText);

	FVector2D Position(0.0f, 0.0f);
	if (Params->HasField(TEXT("position")))
	{
		const TArray<TSharedPtr<FJsonValue>>* PosArray;
		if (Params->TryGetArrayField(TEXT("position"), PosArray) && PosArray->Num() >= 2)
		{
			Position.X = (*PosArray)[0]->AsNumber();
			Position.Y = (*PosArray)[1]->AsNumber();
		}
	}

	// Create Text Block
	UTextBlock* TextBlock = WidgetBlueprint->WidgetTree->ConstructWidget<UTextBlock>(UTextBlock::StaticClass(), *WidgetName);
	if (!TextBlock)
	{
		return FMCPCommonUtils::CreateErrorResponse(TEXT("Failed to create Text Block widget"));
	}

	TextBlock->SetText(FText::FromString(InitialText));

	// Add to canvas
	UCanvasPanel* RootCanvas = Cast<UCanvasPanel>(WidgetBlueprint->WidgetTree->RootWidget);
	if (!RootCanvas)
	{
		return FMCPCommonUtils::CreateErrorResponse(TEXT("Root Canvas Panel not found"));
	}

	UCanvasPanelSlot* PanelSlot = RootCanvas->AddChildToCanvas(TextBlock);
	PanelSlot->SetPosition(Position);

	// Mark modified, compile, and refresh the Widget Designer
	WidgetBlueprint->MarkPackageDirty();
	MarkWidgetBlueprintDirty(WidgetBlueprint, Context);

	TSharedPtr<FJsonObject> ResultObj = MakeShared<FJsonObject>();
	ResultObj->SetBoolField(TEXT("success"), true);
	ResultObj->SetStringField(TEXT("widget_name"), WidgetName);
	ResultObj->SetStringField(TEXT("text"), InitialText);
	return ResultObj;
}

// =============================================================================
// FAddButtonToWidgetAction
// =============================================================================

bool FAddButtonToWidgetAction::Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError)
{
	if (!Params->HasField(TEXT("widget_name")))
	{
		OutError = TEXT("Missing 'widget_name' parameter");
		return false;
	}
	if (!Params->HasField(TEXT("button_name")))
	{
		OutError = TEXT("Missing 'button_name' parameter");
		return false;
	}
	return true;
}

TSharedPtr<FJsonObject> FAddButtonToWidgetAction::ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context)
{
	FString BlueprintName = Params->GetStringField(TEXT("widget_name"));
	FString WidgetName = Params->GetStringField(TEXT("button_name"));

	FString ButtonText = TEXT("Button");
	Params->TryGetStringField(TEXT("text"), ButtonText);

	UWidgetBlueprint* WidgetBlueprint = FindWidgetBlueprintByName(BlueprintName);
	if (!WidgetBlueprint)
	{
		return FMCPCommonUtils::CreateErrorResponse(FString::Printf(
			TEXT("Widget Blueprint '%s' not found in /Game/UI, /Game/Widgets, or /Game"), *BlueprintName));
	}

	UCanvasPanel* RootCanvas = Cast<UCanvasPanel>(WidgetBlueprint->WidgetTree->RootWidget);
	if (!RootCanvas)
	{
		return FMCPCommonUtils::CreateErrorResponse(TEXT("Root widget is not a Canvas Panel"));
	}

	// Create Button
	UButton* Button = WidgetBlueprint->WidgetTree->ConstructWidget<UButton>(UButton::StaticClass(), *WidgetName);
	if (!Button)
	{
		return FMCPCommonUtils::CreateErrorResponse(TEXT("Failed to create Button widget"));
	}

	// Create text block for button label
	FString TextBlockName = WidgetName + TEXT("_Text");
	UTextBlock* ButtonTextBlock = WidgetBlueprint->WidgetTree->ConstructWidget<UTextBlock>(UTextBlock::StaticClass(), *TextBlockName);
	if (ButtonTextBlock)
	{
		ButtonTextBlock->SetText(FText::FromString(ButtonText));
		Button->AddChild(ButtonTextBlock);
	}

	// Add to canvas
	UCanvasPanelSlot* ButtonSlot = RootCanvas->AddChildToCanvas(Button);
	if (ButtonSlot)
	{
		const TArray<TSharedPtr<FJsonValue>>* Position;
		if (Params->TryGetArrayField(TEXT("position"), Position) && Position->Num() >= 2)
		{
			FVector2D Pos((*Position)[0]->AsNumber(), (*Position)[1]->AsNumber());
			ButtonSlot->SetPosition(Pos);
		}

		const TArray<TSharedPtr<FJsonValue>>* Size;
		if (Params->TryGetArrayField(TEXT("size"), Size) && Size->Num() >= 2)
		{
			FVector2D SizeVec((*Size)[0]->AsNumber(), (*Size)[1]->AsNumber());
			ButtonSlot->SetSize(SizeVec);
			ButtonSlot->SetAutoSize(false);
		}
	}

	// Mark modified, compile, and refresh the Widget Designer
	WidgetBlueprint->MarkPackageDirty();
	MarkWidgetBlueprintDirty(WidgetBlueprint, Context);

	TSharedPtr<FJsonObject> ResultObj = MakeShared<FJsonObject>();
	ResultObj->SetBoolField(TEXT("success"), true);
	ResultObj->SetStringField(TEXT("widget_name"), WidgetName);
	return ResultObj;
}

// =============================================================================
// FAddImageToWidgetAction
// =============================================================================

bool FAddImageToWidgetAction::Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError)
{
	if (!Params->HasField(TEXT("widget_name")))
	{
		OutError = TEXT("Missing 'widget_name' parameter");
		return false;
	}
	if (!Params->HasField(TEXT("image_name")))
	{
		OutError = TEXT("Missing 'image_name' parameter");
		return false;
	}
	return true;
}

TSharedPtr<FJsonObject> FAddImageToWidgetAction::ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context)
{
	FString BlueprintName = Params->GetStringField(TEXT("widget_name"));
	FString WidgetName = Params->GetStringField(TEXT("image_name"));

	UWidgetBlueprint* WidgetBlueprint = FindWidgetBlueprintByName(BlueprintName);
	if (!WidgetBlueprint)
	{
		return FMCPCommonUtils::CreateErrorResponse(FString::Printf(
			TEXT("Widget Blueprint '%s' not found in /Game/UI, /Game/Widgets, or /Game"), *BlueprintName));
	}

	UCanvasPanel* RootCanvas = Cast<UCanvasPanel>(WidgetBlueprint->WidgetTree->RootWidget);
	if (!RootCanvas)
	{
		return FMCPCommonUtils::CreateErrorResponse(TEXT("Root widget is not a Canvas Panel"));
	}

	// Optional parameters
	FVector2D Position(0.0f, 0.0f);
	if (Params->HasField(TEXT("position")))
	{
		const TArray<TSharedPtr<FJsonValue>>* PosArray;
		if (Params->TryGetArrayField(TEXT("position"), PosArray) && PosArray->Num() >= 2)
		{
			Position.X = (*PosArray)[0]->AsNumber();
			Position.Y = (*PosArray)[1]->AsNumber();
		}
	}

	bool bHasSize = false;
	FVector2D Size(0.0f, 0.0f);
	if (Params->HasField(TEXT("size")))
	{
		const TArray<TSharedPtr<FJsonValue>>* SizeArray;
		if (Params->TryGetArrayField(TEXT("size"), SizeArray) && SizeArray->Num() >= 2)
		{
			Size.X = (*SizeArray)[0]->AsNumber();
			Size.Y = (*SizeArray)[1]->AsNumber();
			bHasSize = true;
		}
	}

	int32 ZOrder = 0;
	Params->TryGetNumberField(TEXT("z_order"), ZOrder);

	bool bHasTint = false;
	FLinearColor Tint = FLinearColor::White;
	if (Params->HasField(TEXT("color")))
	{
		const TArray<TSharedPtr<FJsonValue>>* ColorArray;
		if (Params->TryGetArrayField(TEXT("color"), ColorArray) && ColorArray->Num() >= 4)
		{
			Tint = FLinearColor(
				(*ColorArray)[0]->AsNumber(),
				(*ColorArray)[1]->AsNumber(),
				(*ColorArray)[2]->AsNumber(),
				(*ColorArray)[3]->AsNumber());
			bHasTint = true;
		}
	}

	FString TexturePath;
	Params->TryGetStringField(TEXT("texture_path"), TexturePath);

	// Create Image
	UImage* Image = WidgetBlueprint->WidgetTree->ConstructWidget<UImage>(UImage::StaticClass(), *WidgetName);
	if (!Image)
	{
		return FMCPCommonUtils::CreateErrorResponse(TEXT("Failed to create Image widget"));
	}

	if (!TexturePath.IsEmpty())
	{
		UObject* TextureObj = UEditorAssetLibrary::LoadAsset(TexturePath);
		UTexture2D* Texture = Cast<UTexture2D>(TextureObj);
		if (!Texture)
		{
			return FMCPCommonUtils::CreateErrorResponse(FString::Printf(
				TEXT("Texture not found or invalid: %s"), *TexturePath));
		}
		Image->SetBrushFromTexture(Texture);
	}

	if (bHasTint)
	{
		Image->SetColorAndOpacity(Tint);
	}

	// Add to canvas
	UCanvasPanelSlot* ImageSlot = RootCanvas->AddChildToCanvas(Image);
	if (ImageSlot)
	{
		ApplyCanvasSlot(ImageSlot, Params);
	}

	// Optional: reparent into a specified parent container
	{
		FString ReparentError;
		if (!TryReparentToParent(WidgetBlueprint, Image, Params, ReparentError))
		{
			return FMCPCommonUtils::CreateErrorResponse(ReparentError);
		}
	}

	// Mark modified, compile, and refresh the Widget Designer
	WidgetBlueprint->MarkPackageDirty();
	MarkWidgetBlueprintDirty(WidgetBlueprint, Context);

	TSharedPtr<FJsonObject> ResultObj = MakeShared<FJsonObject>();
	ResultObj->SetBoolField(TEXT("success"), true);
	ResultObj->SetStringField(TEXT("widget_name"), WidgetName);
	if (!TexturePath.IsEmpty())
	{
		ResultObj->SetStringField(TEXT("texture_path"), TexturePath);
	}
	return ResultObj;
}

// =============================================================================
// FAddBorderToWidgetAction
// =============================================================================

bool FAddBorderToWidgetAction::Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError)
{
	if (!Params->HasField(TEXT("widget_name")))
	{
		OutError = TEXT("Missing 'widget_name' parameter");
		return false;
	}
	if (!Params->HasField(TEXT("border_name")))
	{
		OutError = TEXT("Missing 'border_name' parameter");
		return false;
	}
	return true;
}

TSharedPtr<FJsonObject> FAddBorderToWidgetAction::ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context)
{
	FString BlueprintName = Params->GetStringField(TEXT("widget_name"));
	FString WidgetName = Params->GetStringField(TEXT("border_name"));

	UWidgetBlueprint* WidgetBlueprint = FindWidgetBlueprintByName(BlueprintName);
	if (!WidgetBlueprint)
	{
		return FMCPCommonUtils::CreateErrorResponse(FString::Printf(
			TEXT("Widget Blueprint '%s' not found in /Game/UI, /Game/Widgets, or /Game"), *BlueprintName));
	}

	UCanvasPanel* RootCanvas = Cast<UCanvasPanel>(WidgetBlueprint->WidgetTree->RootWidget);
	if (!RootCanvas)
	{
		return FMCPCommonUtils::CreateErrorResponse(TEXT("Root widget is not a Canvas Panel"));
	}

	UBorder* Border = WidgetBlueprint->WidgetTree->ConstructWidget<UBorder>(UBorder::StaticClass(), *WidgetName);
	if (!Border)
	{
		return FMCPCommonUtils::CreateErrorResponse(TEXT("Failed to create Border widget"));
	}

	FLinearColor Tint;
	if (TryGetColorField(Params, TEXT("color"), Tint))
	{
		Border->SetBrushColor(Tint);
	}

	UCanvasPanelSlot* Slot = RootCanvas->AddChildToCanvas(Border);
	ApplyCanvasSlot(Slot, Params);

	// Optional: reparent into a specified parent container
	if (Slot && Slot->Content)
	{
		FString ReparentError;
		if (!TryReparentToParent(WidgetBlueprint, Slot->Content, Params, ReparentError))
		{
			return FMCPCommonUtils::CreateErrorResponse(ReparentError);
		}
	}

	WidgetBlueprint->MarkPackageDirty();
	MarkWidgetBlueprintDirty(WidgetBlueprint, Context);

	TSharedPtr<FJsonObject> ResultObj = MakeShared<FJsonObject>();
	ResultObj->SetBoolField(TEXT("success"), true);
	ResultObj->SetStringField(TEXT("widget_name"), WidgetName);
	return ResultObj;
}

// =============================================================================
// FAddOverlayToWidgetAction
// =============================================================================

bool FAddOverlayToWidgetAction::Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError)
{
	if (!Params->HasField(TEXT("widget_name")))
	{
		OutError = TEXT("Missing 'widget_name' parameter");
		return false;
	}
	if (!Params->HasField(TEXT("overlay_name")))
	{
		OutError = TEXT("Missing 'overlay_name' parameter");
		return false;
	}
	return true;
}

TSharedPtr<FJsonObject> FAddOverlayToWidgetAction::ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context)
{
	FString BlueprintName = Params->GetStringField(TEXT("widget_name"));
	FString WidgetName = Params->GetStringField(TEXT("overlay_name"));

	UWidgetBlueprint* WidgetBlueprint = FindWidgetBlueprintByName(BlueprintName);
	if (!WidgetBlueprint)
	{
		return FMCPCommonUtils::CreateErrorResponse(FString::Printf(
			TEXT("Widget Blueprint '%s' not found in /Game/UI, /Game/Widgets, or /Game"), *BlueprintName));
	}

	UCanvasPanel* RootCanvas = Cast<UCanvasPanel>(WidgetBlueprint->WidgetTree->RootWidget);
	if (!RootCanvas)
	{
		return FMCPCommonUtils::CreateErrorResponse(TEXT("Root widget is not a Canvas Panel"));
	}

	UOverlay* Overlay = WidgetBlueprint->WidgetTree->ConstructWidget<UOverlay>(UOverlay::StaticClass(), *WidgetName);
	if (!Overlay)
	{
		return FMCPCommonUtils::CreateErrorResponse(TEXT("Failed to create Overlay widget"));
	}

	UCanvasPanelSlot* Slot = RootCanvas->AddChildToCanvas(Overlay);
	ApplyCanvasSlot(Slot, Params);

	// Optional: reparent into a specified parent container
	if (Slot && Slot->Content)
	{
		FString ReparentError;
		if (!TryReparentToParent(WidgetBlueprint, Slot->Content, Params, ReparentError))
		{
			return FMCPCommonUtils::CreateErrorResponse(ReparentError);
		}
	}

	WidgetBlueprint->MarkPackageDirty();
	MarkWidgetBlueprintDirty(WidgetBlueprint, Context);

	TSharedPtr<FJsonObject> ResultObj = MakeShared<FJsonObject>();
	ResultObj->SetBoolField(TEXT("success"), true);
	ResultObj->SetStringField(TEXT("widget_name"), WidgetName);
	return ResultObj;
}

// =============================================================================
// FAddHorizontalBoxToWidgetAction
// =============================================================================

bool FAddHorizontalBoxToWidgetAction::Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError)
{
	if (!Params->HasField(TEXT("widget_name")))
	{
		OutError = TEXT("Missing 'widget_name' parameter");
		return false;
	}
	if (!Params->HasField(TEXT("horizontal_box_name")))
	{
		OutError = TEXT("Missing 'horizontal_box_name' parameter");
		return false;
	}
	return true;
}

TSharedPtr<FJsonObject> FAddHorizontalBoxToWidgetAction::ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context)
{
	FString BlueprintName = Params->GetStringField(TEXT("widget_name"));
	FString WidgetName = Params->GetStringField(TEXT("horizontal_box_name"));

	UWidgetBlueprint* WidgetBlueprint = FindWidgetBlueprintByName(BlueprintName);
	if (!WidgetBlueprint)
	{
		return FMCPCommonUtils::CreateErrorResponse(FString::Printf(
			TEXT("Widget Blueprint '%s' not found in /Game/UI, /Game/Widgets, or /Game"), *BlueprintName));
	}

	UCanvasPanel* RootCanvas = Cast<UCanvasPanel>(WidgetBlueprint->WidgetTree->RootWidget);
	if (!RootCanvas)
	{
		return FMCPCommonUtils::CreateErrorResponse(TEXT("Root widget is not a Canvas Panel"));
	}

	UHorizontalBox* HorizontalBox = WidgetBlueprint->WidgetTree->ConstructWidget<UHorizontalBox>(UHorizontalBox::StaticClass(), *WidgetName);
	if (!HorizontalBox)
	{
		return FMCPCommonUtils::CreateErrorResponse(TEXT("Failed to create HorizontalBox widget"));
	}

	UCanvasPanelSlot* Slot = RootCanvas->AddChildToCanvas(HorizontalBox);
	ApplyCanvasSlot(Slot, Params);

	// Optional: reparent into a specified parent container
	if (Slot && Slot->Content)
	{
		FString ReparentError;
		if (!TryReparentToParent(WidgetBlueprint, Slot->Content, Params, ReparentError))
		{
			return FMCPCommonUtils::CreateErrorResponse(ReparentError);
		}
	}

	WidgetBlueprint->MarkPackageDirty();
	MarkWidgetBlueprintDirty(WidgetBlueprint, Context);

	TSharedPtr<FJsonObject> ResultObj = MakeShared<FJsonObject>();
	ResultObj->SetBoolField(TEXT("success"), true);
	ResultObj->SetStringField(TEXT("widget_name"), WidgetName);
	return ResultObj;
}

// =============================================================================
// FAddVerticalBoxToWidgetAction
// =============================================================================

bool FAddVerticalBoxToWidgetAction::Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError)
{
	if (!Params->HasField(TEXT("widget_name")))
	{
		OutError = TEXT("Missing 'widget_name' parameter");
		return false;
	}
	if (!Params->HasField(TEXT("vertical_box_name")))
	{
		OutError = TEXT("Missing 'vertical_box_name' parameter");
		return false;
	}
	return true;
}

TSharedPtr<FJsonObject> FAddVerticalBoxToWidgetAction::ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context)
{
	FString BlueprintName = Params->GetStringField(TEXT("widget_name"));
	FString WidgetName = Params->GetStringField(TEXT("vertical_box_name"));

	UWidgetBlueprint* WidgetBlueprint = FindWidgetBlueprintByName(BlueprintName);
	if (!WidgetBlueprint)
	{
		return FMCPCommonUtils::CreateErrorResponse(FString::Printf(
			TEXT("Widget Blueprint '%s' not found in /Game/UI, /Game/Widgets, or /Game"), *BlueprintName));
	}

	UCanvasPanel* RootCanvas = Cast<UCanvasPanel>(WidgetBlueprint->WidgetTree->RootWidget);
	if (!RootCanvas)
	{
		return FMCPCommonUtils::CreateErrorResponse(TEXT("Root widget is not a Canvas Panel"));
	}

	UVerticalBox* VerticalBox = WidgetBlueprint->WidgetTree->ConstructWidget<UVerticalBox>(UVerticalBox::StaticClass(), *WidgetName);
	if (!VerticalBox)
	{
		return FMCPCommonUtils::CreateErrorResponse(TEXT("Failed to create VerticalBox widget"));
	}

	UCanvasPanelSlot* Slot = RootCanvas->AddChildToCanvas(VerticalBox);
	ApplyCanvasSlot(Slot, Params);

	// Optional: reparent into a specified parent container
	if (Slot && Slot->Content)
	{
		FString ReparentError;
		if (!TryReparentToParent(WidgetBlueprint, Slot->Content, Params, ReparentError))
		{
			return FMCPCommonUtils::CreateErrorResponse(ReparentError);
		}
	}

	WidgetBlueprint->MarkPackageDirty();
	MarkWidgetBlueprintDirty(WidgetBlueprint, Context);

	TSharedPtr<FJsonObject> ResultObj = MakeShared<FJsonObject>();
	ResultObj->SetBoolField(TEXT("success"), true);
	ResultObj->SetStringField(TEXT("widget_name"), WidgetName);
	return ResultObj;
}

// =============================================================================
// FAddSliderToWidgetAction
// =============================================================================

bool FAddSliderToWidgetAction::Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError)
{
	if (!Params->HasField(TEXT("widget_name")))
	{
		OutError = TEXT("Missing 'widget_name' parameter");
		return false;
	}
	if (!Params->HasField(TEXT("slider_name")))
	{
		OutError = TEXT("Missing 'slider_name' parameter");
		return false;
	}
	return true;
}

TSharedPtr<FJsonObject> FAddSliderToWidgetAction::ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context)
{
	FString BlueprintName = Params->GetStringField(TEXT("widget_name"));
	FString WidgetName = Params->GetStringField(TEXT("slider_name"));

	UWidgetBlueprint* WidgetBlueprint = FindWidgetBlueprintByName(BlueprintName);
	if (!WidgetBlueprint)
	{
		return FMCPCommonUtils::CreateErrorResponse(FString::Printf(
			TEXT("Widget Blueprint '%s' not found in /Game/UI, /Game/Widgets, or /Game"), *BlueprintName));
	}

	UCanvasPanel* RootCanvas = Cast<UCanvasPanel>(WidgetBlueprint->WidgetTree->RootWidget);
	if (!RootCanvas)
	{
		return FMCPCommonUtils::CreateErrorResponse(TEXT("Root widget is not a Canvas Panel"));
	}

	USlider* Slider = WidgetBlueprint->WidgetTree->ConstructWidget<USlider>(USlider::StaticClass(), *WidgetName);
	if (!Slider)
	{
		return FMCPCommonUtils::CreateErrorResponse(TEXT("Failed to create Slider widget"));
	}

	double Value = 0.0;
	if (Params->TryGetNumberField(TEXT("value"), Value))
	{
		Slider->SetValue(static_cast<float>(Value));
	}

	UCanvasPanelSlot* Slot = RootCanvas->AddChildToCanvas(Slider);
	ApplyCanvasSlot(Slot, Params);

	// Optional: reparent into a specified parent container
	if (Slot && Slot->Content)
	{
		FString ReparentError;
		if (!TryReparentToParent(WidgetBlueprint, Slot->Content, Params, ReparentError))
		{
			return FMCPCommonUtils::CreateErrorResponse(ReparentError);
		}
	}

	WidgetBlueprint->MarkPackageDirty();
	MarkWidgetBlueprintDirty(WidgetBlueprint, Context);

	TSharedPtr<FJsonObject> ResultObj = MakeShared<FJsonObject>();
	ResultObj->SetBoolField(TEXT("success"), true);
	ResultObj->SetStringField(TEXT("widget_name"), WidgetName);
	return ResultObj;
}

// =============================================================================
// FAddProgressBarToWidgetAction
// =============================================================================

bool FAddProgressBarToWidgetAction::Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError)
{
	if (!Params->HasField(TEXT("widget_name")))
	{
		OutError = TEXT("Missing 'widget_name' parameter");
		return false;
	}
	if (!Params->HasField(TEXT("progress_bar_name")))
	{
		OutError = TEXT("Missing 'progress_bar_name' parameter");
		return false;
	}
	return true;
}

TSharedPtr<FJsonObject> FAddProgressBarToWidgetAction::ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context)
{
	FString BlueprintName = Params->GetStringField(TEXT("widget_name"));
	FString WidgetName = Params->GetStringField(TEXT("progress_bar_name"));

	UWidgetBlueprint* WidgetBlueprint = FindWidgetBlueprintByName(BlueprintName);
	if (!WidgetBlueprint)
	{
		return FMCPCommonUtils::CreateErrorResponse(FString::Printf(
			TEXT("Widget Blueprint '%s' not found in /Game/UI, /Game/Widgets, or /Game"), *BlueprintName));
	}

	UCanvasPanel* RootCanvas = Cast<UCanvasPanel>(WidgetBlueprint->WidgetTree->RootWidget);
	if (!RootCanvas)
	{
		return FMCPCommonUtils::CreateErrorResponse(TEXT("Root widget is not a Canvas Panel"));
	}

	UProgressBar* ProgressBar = WidgetBlueprint->WidgetTree->ConstructWidget<UProgressBar>(UProgressBar::StaticClass(), *WidgetName);
	if (!ProgressBar)
	{
		return FMCPCommonUtils::CreateErrorResponse(TEXT("Failed to create ProgressBar widget"));
	}

	double Percent = 0.0;
	if (Params->TryGetNumberField(TEXT("percent"), Percent))
	{
		ProgressBar->SetPercent(static_cast<float>(Percent));
	}

	FLinearColor Tint;
	if (TryGetColorField(Params, TEXT("color"), Tint))
	{
		ProgressBar->SetFillColorAndOpacity(Tint);
	}

	UCanvasPanelSlot* Slot = RootCanvas->AddChildToCanvas(ProgressBar);
	ApplyCanvasSlot(Slot, Params);

	// Optional: reparent into a specified parent container
	if (Slot && Slot->Content)
	{
		FString ReparentError;
		if (!TryReparentToParent(WidgetBlueprint, Slot->Content, Params, ReparentError))
		{
			return FMCPCommonUtils::CreateErrorResponse(ReparentError);
		}
	}

	WidgetBlueprint->MarkPackageDirty();
	MarkWidgetBlueprintDirty(WidgetBlueprint, Context);

	TSharedPtr<FJsonObject> ResultObj = MakeShared<FJsonObject>();
	ResultObj->SetBoolField(TEXT("success"), true);
	ResultObj->SetStringField(TEXT("widget_name"), WidgetName);
	return ResultObj;
}

// =============================================================================
// FAddSizeBoxToWidgetAction
// =============================================================================

bool FAddSizeBoxToWidgetAction::Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError)
{
	if (!Params->HasField(TEXT("widget_name")))
	{
		OutError = TEXT("Missing 'widget_name' parameter");
		return false;
	}
	if (!Params->HasField(TEXT("size_box_name")))
	{
		OutError = TEXT("Missing 'size_box_name' parameter");
		return false;
	}
	return true;
}

TSharedPtr<FJsonObject> FAddSizeBoxToWidgetAction::ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context)
{
	FString BlueprintName = Params->GetStringField(TEXT("widget_name"));
	FString WidgetName = Params->GetStringField(TEXT("size_box_name"));

	UWidgetBlueprint* WidgetBlueprint = FindWidgetBlueprintByName(BlueprintName);
	if (!WidgetBlueprint)
	{
		return FMCPCommonUtils::CreateErrorResponse(FString::Printf(
			TEXT("Widget Blueprint '%s' not found in /Game/UI, /Game/Widgets, or /Game"), *BlueprintName));
	}

	UCanvasPanel* RootCanvas = Cast<UCanvasPanel>(WidgetBlueprint->WidgetTree->RootWidget);
	if (!RootCanvas)
	{
		return FMCPCommonUtils::CreateErrorResponse(TEXT("Root widget is not a Canvas Panel"));
	}

	USizeBox* SizeBox = WidgetBlueprint->WidgetTree->ConstructWidget<USizeBox>(USizeBox::StaticClass(), *WidgetName);
	if (!SizeBox)
	{
		return FMCPCommonUtils::CreateErrorResponse(TEXT("Failed to create SizeBox widget"));
	}

	FVector2D OverrideSize;
	if (TryGetVector2Field(Params, TEXT("size"), OverrideSize))
	{
		SizeBox->SetWidthOverride(OverrideSize.X);
		SizeBox->SetHeightOverride(OverrideSize.Y);
	}

	UCanvasPanelSlot* Slot = RootCanvas->AddChildToCanvas(SizeBox);
	ApplyCanvasSlot(Slot, Params);

	// Optional: reparent into a specified parent container
	if (Slot && Slot->Content)
	{
		FString ReparentError;
		if (!TryReparentToParent(WidgetBlueprint, Slot->Content, Params, ReparentError))
		{
			return FMCPCommonUtils::CreateErrorResponse(ReparentError);
		}
	}

	WidgetBlueprint->MarkPackageDirty();
	MarkWidgetBlueprintDirty(WidgetBlueprint, Context);

	TSharedPtr<FJsonObject> ResultObj = MakeShared<FJsonObject>();
	ResultObj->SetBoolField(TEXT("success"), true);
	ResultObj->SetStringField(TEXT("widget_name"), WidgetName);
	return ResultObj;
}

// =============================================================================
// FAddScaleBoxToWidgetAction
// =============================================================================

bool FAddScaleBoxToWidgetAction::Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError)
{
	if (!Params->HasField(TEXT("widget_name")))
	{
		OutError = TEXT("Missing 'widget_name' parameter");
		return false;
	}
	if (!Params->HasField(TEXT("scale_box_name")))
	{
		OutError = TEXT("Missing 'scale_box_name' parameter");
		return false;
	}
	return true;
}

TSharedPtr<FJsonObject> FAddScaleBoxToWidgetAction::ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context)
{
	FString BlueprintName = Params->GetStringField(TEXT("widget_name"));
	FString WidgetName = Params->GetStringField(TEXT("scale_box_name"));

	UWidgetBlueprint* WidgetBlueprint = FindWidgetBlueprintByName(BlueprintName);
	if (!WidgetBlueprint)
	{
		return FMCPCommonUtils::CreateErrorResponse(FString::Printf(
			TEXT("Widget Blueprint '%s' not found in /Game/UI, /Game/Widgets, or /Game"), *BlueprintName));
	}

	UCanvasPanel* RootCanvas = Cast<UCanvasPanel>(WidgetBlueprint->WidgetTree->RootWidget);
	if (!RootCanvas)
	{
		return FMCPCommonUtils::CreateErrorResponse(TEXT("Root widget is not a Canvas Panel"));
	}

	UScaleBox* ScaleBox = WidgetBlueprint->WidgetTree->ConstructWidget<UScaleBox>(UScaleBox::StaticClass(), *WidgetName);
	if (!ScaleBox)
	{
		return FMCPCommonUtils::CreateErrorResponse(TEXT("Failed to create ScaleBox widget"));
	}

	UCanvasPanelSlot* Slot = RootCanvas->AddChildToCanvas(ScaleBox);
	ApplyCanvasSlot(Slot, Params);

	// Optional: reparent into a specified parent container
	if (Slot && Slot->Content)
	{
		FString ReparentError;
		if (!TryReparentToParent(WidgetBlueprint, Slot->Content, Params, ReparentError))
		{
			return FMCPCommonUtils::CreateErrorResponse(ReparentError);
		}
	}

	WidgetBlueprint->MarkPackageDirty();
	MarkWidgetBlueprintDirty(WidgetBlueprint, Context);

	TSharedPtr<FJsonObject> ResultObj = MakeShared<FJsonObject>();
	ResultObj->SetBoolField(TEXT("success"), true);
	ResultObj->SetStringField(TEXT("widget_name"), WidgetName);
	return ResultObj;
}

// =============================================================================
// FAddCanvasPanelToWidgetAction
// =============================================================================

bool FAddCanvasPanelToWidgetAction::Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError)
{
	if (!Params->HasField(TEXT("widget_name")))
	{
		OutError = TEXT("Missing 'widget_name' parameter");
		return false;
	}
	if (!Params->HasField(TEXT("canvas_panel_name")))
	{
		OutError = TEXT("Missing 'canvas_panel_name' parameter");
		return false;
	}
	return true;
}

TSharedPtr<FJsonObject> FAddCanvasPanelToWidgetAction::ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context)
{
	FString BlueprintName = Params->GetStringField(TEXT("widget_name"));
	FString WidgetName = Params->GetStringField(TEXT("canvas_panel_name"));

	UWidgetBlueprint* WidgetBlueprint = FindWidgetBlueprintByName(BlueprintName);
	if (!WidgetBlueprint)
	{
		return FMCPCommonUtils::CreateErrorResponse(FString::Printf(
			TEXT("Widget Blueprint '%s' not found in /Game/UI, /Game/Widgets, or /Game"), *BlueprintName));
	}

	UCanvasPanel* RootCanvas = Cast<UCanvasPanel>(WidgetBlueprint->WidgetTree->RootWidget);
	if (!RootCanvas)
	{
		return FMCPCommonUtils::CreateErrorResponse(TEXT("Root widget is not a Canvas Panel"));
	}

	UCanvasPanel* CanvasPanel = WidgetBlueprint->WidgetTree->ConstructWidget<UCanvasPanel>(UCanvasPanel::StaticClass(), *WidgetName);
	if (!CanvasPanel)
	{
		return FMCPCommonUtils::CreateErrorResponse(TEXT("Failed to create CanvasPanel widget"));
	}

	UCanvasPanelSlot* Slot = RootCanvas->AddChildToCanvas(CanvasPanel);
	ApplyCanvasSlot(Slot, Params);

	// Optional: reparent into a specified parent container
	if (Slot && Slot->Content)
	{
		FString ReparentError;
		if (!TryReparentToParent(WidgetBlueprint, Slot->Content, Params, ReparentError))
		{
			return FMCPCommonUtils::CreateErrorResponse(ReparentError);
		}
	}

	WidgetBlueprint->MarkPackageDirty();
	MarkWidgetBlueprintDirty(WidgetBlueprint, Context);

	TSharedPtr<FJsonObject> ResultObj = MakeShared<FJsonObject>();
	ResultObj->SetBoolField(TEXT("success"), true);
	ResultObj->SetStringField(TEXT("widget_name"), WidgetName);
	return ResultObj;
}

// =============================================================================
// FAddComboBoxToWidgetAction
// =============================================================================

bool FAddComboBoxToWidgetAction::Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError)
{
	if (!Params->HasField(TEXT("widget_name")))
	{
		OutError = TEXT("Missing 'widget_name' parameter");
		return false;
	}
	if (!Params->HasField(TEXT("combo_box_name")))
	{
		OutError = TEXT("Missing 'combo_box_name' parameter");
		return false;
	}
	return true;
}

TSharedPtr<FJsonObject> FAddComboBoxToWidgetAction::ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context)
{
	FString BlueprintName = Params->GetStringField(TEXT("widget_name"));
	FString WidgetName = Params->GetStringField(TEXT("combo_box_name"));

	UWidgetBlueprint* WidgetBlueprint = FindWidgetBlueprintByName(BlueprintName);
	if (!WidgetBlueprint)
	{
		return FMCPCommonUtils::CreateErrorResponse(FString::Printf(
			TEXT("Widget Blueprint '%s' not found in /Game/UI, /Game/Widgets, or /Game"), *BlueprintName));
	}

	UCanvasPanel* RootCanvas = Cast<UCanvasPanel>(WidgetBlueprint->WidgetTree->RootWidget);
	if (!RootCanvas)
	{
		return FMCPCommonUtils::CreateErrorResponse(TEXT("Root widget is not a Canvas Panel"));
	}

	UComboBoxString* ComboBox = WidgetBlueprint->WidgetTree->ConstructWidget<UComboBoxString>(UComboBoxString::StaticClass(), *WidgetName);
	if (!ComboBox)
	{
		return FMCPCommonUtils::CreateErrorResponse(TEXT("Failed to create ComboBoxString widget"));
	}

	// Add options
	const TArray<TSharedPtr<FJsonValue>>* OptionsArray = nullptr;
	if (Params->TryGetArrayField(TEXT("options"), OptionsArray))
	{
		for (const TSharedPtr<FJsonValue>& Val : *OptionsArray)
		{
			ComboBox->AddOption(Val->AsString());
		}
	}

	// Set default selected
	FString SelectedOption;
	if (Params->TryGetStringField(TEXT("selected_option"), SelectedOption))
	{
		ComboBox->SetSelectedOption(SelectedOption);
	}
	else if (OptionsArray && OptionsArray->Num() > 0)
	{
		ComboBox->SetSelectedOption((*OptionsArray)[0]->AsString());
	}

	UCanvasPanelSlot* Slot = RootCanvas->AddChildToCanvas(ComboBox);
	ApplyCanvasSlot(Slot, Params);

	// Optional: reparent into a specified parent container
	if (Slot && Slot->Content)
	{
		FString ReparentError;
		if (!TryReparentToParent(WidgetBlueprint, Slot->Content, Params, ReparentError))
		{
			return FMCPCommonUtils::CreateErrorResponse(ReparentError);
		}
	}

	WidgetBlueprint->MarkPackageDirty();
	MarkWidgetBlueprintDirty(WidgetBlueprint, Context);

	TSharedPtr<FJsonObject> ResultObj = MakeShared<FJsonObject>();
	ResultObj->SetBoolField(TEXT("success"), true);
	ResultObj->SetStringField(TEXT("widget_name"), WidgetName);
	return ResultObj;
}

// =============================================================================
// FAddCheckBoxToWidgetAction
// =============================================================================

bool FAddCheckBoxToWidgetAction::Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError)
{
	if (!Params->HasField(TEXT("widget_name")))
	{
		OutError = TEXT("Missing 'widget_name' parameter");
		return false;
	}
	if (!Params->HasField(TEXT("check_box_name")))
	{
		OutError = TEXT("Missing 'check_box_name' parameter");
		return false;
	}
	return true;
}

TSharedPtr<FJsonObject> FAddCheckBoxToWidgetAction::ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context)
{
	FString BlueprintName = Params->GetStringField(TEXT("widget_name"));
	FString WidgetName = Params->GetStringField(TEXT("check_box_name"));

	UWidgetBlueprint* WidgetBlueprint = FindWidgetBlueprintByName(BlueprintName);
	if (!WidgetBlueprint)
	{
		return FMCPCommonUtils::CreateErrorResponse(FString::Printf(
			TEXT("Widget Blueprint '%s' not found in /Game/UI, /Game/Widgets, or /Game"), *BlueprintName));
	}

	UCanvasPanel* RootCanvas = Cast<UCanvasPanel>(WidgetBlueprint->WidgetTree->RootWidget);
	if (!RootCanvas)
	{
		return FMCPCommonUtils::CreateErrorResponse(TEXT("Root widget is not a Canvas Panel"));
	}

	UCheckBox* CheckBox = WidgetBlueprint->WidgetTree->ConstructWidget<UCheckBox>(UCheckBox::StaticClass(), *WidgetName);
	if (!CheckBox)
	{
		return FMCPCommonUtils::CreateErrorResponse(TEXT("Failed to create CheckBox widget"));
	}

	bool bIsChecked = false;
	if (Params->TryGetBoolField(TEXT("is_checked"), bIsChecked) && bIsChecked)
	{
		CheckBox->SetIsChecked(true);
	}

	// Optional label text - add as a child TextBlock
	FString LabelText;
	if (Params->TryGetStringField(TEXT("label"), LabelText))
	{
		FString TextBlockName = WidgetName + TEXT("_Label");
		UTextBlock* Label = WidgetBlueprint->WidgetTree->ConstructWidget<UTextBlock>(UTextBlock::StaticClass(), *TextBlockName);
		if (Label)
		{
			Label->SetText(FText::FromString(LabelText));
			CheckBox->AddChild(Label);
		}
	}

	UCanvasPanelSlot* Slot = RootCanvas->AddChildToCanvas(CheckBox);
	ApplyCanvasSlot(Slot, Params);

	// Optional: reparent into a specified parent container
	if (Slot && Slot->Content)
	{
		FString ReparentError;
		if (!TryReparentToParent(WidgetBlueprint, Slot->Content, Params, ReparentError))
		{
			return FMCPCommonUtils::CreateErrorResponse(ReparentError);
		}
	}

	WidgetBlueprint->MarkPackageDirty();
	MarkWidgetBlueprintDirty(WidgetBlueprint, Context);

	TSharedPtr<FJsonObject> ResultObj = MakeShared<FJsonObject>();
	ResultObj->SetBoolField(TEXT("success"), true);
	ResultObj->SetStringField(TEXT("widget_name"), WidgetName);
	return ResultObj;
}

// =============================================================================
// FAddSpinBoxToWidgetAction
// =============================================================================

bool FAddSpinBoxToWidgetAction::Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError)
{
	if (!Params->HasField(TEXT("widget_name")))
	{
		OutError = TEXT("Missing 'widget_name' parameter");
		return false;
	}
	if (!Params->HasField(TEXT("spin_box_name")))
	{
		OutError = TEXT("Missing 'spin_box_name' parameter");
		return false;
	}
	return true;
}

TSharedPtr<FJsonObject> FAddSpinBoxToWidgetAction::ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context)
{
	FString BlueprintName = Params->GetStringField(TEXT("widget_name"));
	FString WidgetName = Params->GetStringField(TEXT("spin_box_name"));

	UWidgetBlueprint* WidgetBlueprint = FindWidgetBlueprintByName(BlueprintName);
	if (!WidgetBlueprint)
	{
		return FMCPCommonUtils::CreateErrorResponse(FString::Printf(
			TEXT("Widget Blueprint '%s' not found in /Game/UI, /Game/Widgets, or /Game"), *BlueprintName));
	}

	UCanvasPanel* RootCanvas = Cast<UCanvasPanel>(WidgetBlueprint->WidgetTree->RootWidget);
	if (!RootCanvas)
	{
		return FMCPCommonUtils::CreateErrorResponse(TEXT("Root widget is not a Canvas Panel"));
	}

	USpinBox* SpinBox = WidgetBlueprint->WidgetTree->ConstructWidget<USpinBox>(USpinBox::StaticClass(), *WidgetName);
	if (!SpinBox)
	{
		return FMCPCommonUtils::CreateErrorResponse(TEXT("Failed to create SpinBox widget"));
	}

	double Value = 0.0;
	if (Params->TryGetNumberField(TEXT("value"), Value))
	{
		SpinBox->SetValue(static_cast<float>(Value));
	}

	double MinValue = 0.0;
	if (Params->TryGetNumberField(TEXT("min_value"), MinValue))
	{
		SpinBox->SetMinValue(static_cast<float>(MinValue));
	}

	double MaxValue = 100.0;
	if (Params->TryGetNumberField(TEXT("max_value"), MaxValue))
	{
		SpinBox->SetMaxValue(static_cast<float>(MaxValue));
	}

	double Delta = 1.0;
	if (Params->TryGetNumberField(TEXT("delta"), Delta))
	{
		SpinBox->SetDelta(static_cast<float>(Delta));
	}

	UCanvasPanelSlot* Slot = RootCanvas->AddChildToCanvas(SpinBox);
	ApplyCanvasSlot(Slot, Params);

	// Optional: reparent into a specified parent container
	if (Slot && Slot->Content)
	{
		FString ReparentError;
		if (!TryReparentToParent(WidgetBlueprint, Slot->Content, Params, ReparentError))
		{
			return FMCPCommonUtils::CreateErrorResponse(ReparentError);
		}
	}

	WidgetBlueprint->MarkPackageDirty();
	MarkWidgetBlueprintDirty(WidgetBlueprint, Context);

	TSharedPtr<FJsonObject> ResultObj = MakeShared<FJsonObject>();
	ResultObj->SetBoolField(TEXT("success"), true);
	ResultObj->SetStringField(TEXT("widget_name"), WidgetName);
	return ResultObj;
}

// =============================================================================
// FAddEditableTextBoxToWidgetAction
// =============================================================================

bool FAddEditableTextBoxToWidgetAction::Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError)
{
	if (!Params->HasField(TEXT("widget_name")))
	{
		OutError = TEXT("Missing 'widget_name' parameter");
		return false;
	}
	if (!Params->HasField(TEXT("editable_text_box_name")))
	{
		OutError = TEXT("Missing 'editable_text_box_name' parameter");
		return false;
	}
	return true;
}

TSharedPtr<FJsonObject> FAddEditableTextBoxToWidgetAction::ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context)
{
	FString BlueprintName = Params->GetStringField(TEXT("widget_name"));
	FString WidgetName = Params->GetStringField(TEXT("editable_text_box_name"));

	UWidgetBlueprint* WidgetBlueprint = FindWidgetBlueprintByName(BlueprintName);
	if (!WidgetBlueprint)
	{
		return FMCPCommonUtils::CreateErrorResponse(FString::Printf(
			TEXT("Widget Blueprint '%s' not found in /Game/UI, /Game/Widgets, or /Game"), *BlueprintName));
	}

	UCanvasPanel* RootCanvas = Cast<UCanvasPanel>(WidgetBlueprint->WidgetTree->RootWidget);
	if (!RootCanvas)
	{
		return FMCPCommonUtils::CreateErrorResponse(TEXT("Root widget is not a Canvas Panel"));
	}

	UEditableTextBox* TextBox = WidgetBlueprint->WidgetTree->ConstructWidget<UEditableTextBox>(UEditableTextBox::StaticClass(), *WidgetName);
	if (!TextBox)
	{
		return FMCPCommonUtils::CreateErrorResponse(TEXT("Failed to create EditableTextBox widget"));
	}

	FString InitialText;
	if (Params->TryGetStringField(TEXT("text"), InitialText))
	{
		TextBox->SetText(FText::FromString(InitialText));
	}

	FString HintText;
	if (Params->TryGetStringField(TEXT("hint_text"), HintText))
	{
		TextBox->SetHintText(FText::FromString(HintText));
	}

	bool bIsReadOnly = false;
	if (Params->TryGetBoolField(TEXT("is_read_only"), bIsReadOnly))
	{
		TextBox->SetIsReadOnly(bIsReadOnly);
	}

	UCanvasPanelSlot* Slot = RootCanvas->AddChildToCanvas(TextBox);
	ApplyCanvasSlot(Slot, Params);

	// Optional: reparent into a specified parent container
	if (Slot && Slot->Content)
	{
		FString ReparentError;
		if (!TryReparentToParent(WidgetBlueprint, Slot->Content, Params, ReparentError))
		{
			return FMCPCommonUtils::CreateErrorResponse(ReparentError);
		}
	}

	WidgetBlueprint->MarkPackageDirty();
	MarkWidgetBlueprintDirty(WidgetBlueprint, Context);

	TSharedPtr<FJsonObject> ResultObj = MakeShared<FJsonObject>();
	ResultObj->SetBoolField(TEXT("success"), true);
	ResultObj->SetStringField(TEXT("widget_name"), WidgetName);
	return ResultObj;
}

// =============================================================================
// FBindWidgetEventAction
// =============================================================================

bool FBindWidgetEventAction::Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError)
{
	if (!Params->HasField(TEXT("widget_name")))
	{
		OutError = TEXT("Missing 'widget_name' parameter");
		return false;
	}
	if (!Params->HasField(TEXT("widget_component_name")))
	{
		OutError = TEXT("Missing 'widget_component_name' parameter");
		return false;
	}
	if (!Params->HasField(TEXT("event_name")))
	{
		OutError = TEXT("Missing 'event_name' parameter");
		return false;
	}
	return true;
}

TSharedPtr<FJsonObject> FBindWidgetEventAction::ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context)
{
	FString BlueprintName = Params->GetStringField(TEXT("widget_name"));
	FString WidgetComponentName = Params->GetStringField(TEXT("widget_component_name"));
	FString EventName = Params->GetStringField(TEXT("event_name"));

	UWidgetBlueprint* WidgetBlueprint = FindWidgetBlueprintByName(BlueprintName);
	if (!WidgetBlueprint)
	{
		return FMCPCommonUtils::CreateErrorResponse(FString::Printf(
			TEXT("Widget Blueprint '%s' not found"), *BlueprintName));
	}

	// Find the widget in the WidgetTree
	UWidget* Widget = WidgetBlueprint->WidgetTree->FindWidget(*WidgetComponentName);
	if (!Widget)
	{
		TArray<FString> AvailableWidgets;
		WidgetBlueprint->WidgetTree->ForEachWidget([&AvailableWidgets](UWidget* W) {
			if (W) AvailableWidgets.Add(W->GetName());
		});
		FString WidgetList = FString::Join(AvailableWidgets, TEXT(", "));
		return FMCPCommonUtils::CreateErrorResponse(FString::Printf(
			TEXT("Widget '%s' not found. Available: %s"), *WidgetComponentName, *WidgetList));
	}

	// Verify delegate exists
	FMulticastDelegateProperty* DelegateProp = nullptr;
	for (TFieldIterator<FMulticastDelegateProperty> It(Widget->GetClass()); It; ++It)
	{
		if (It->GetFName() == FName(*EventName))
		{
			DelegateProp = *It;
			break;
		}
	}

	if (!DelegateProp)
	{
		TArray<FString> AvailableDelegates;
		for (TFieldIterator<FMulticastDelegateProperty> It(Widget->GetClass()); It; ++It)
		{
			AvailableDelegates.Add(It->GetName());
		}
		FString DelegateList = FString::Join(AvailableDelegates, TEXT(", "));
		return FMCPCommonUtils::CreateErrorResponse(FString::Printf(
			TEXT("Delegate '%s' not found. Available: %s"), *EventName, *DelegateList));
	}

	// Get event graph
	UEdGraph* EventGraph = FBlueprintEditorUtils::FindEventGraph(WidgetBlueprint);
	if (!EventGraph)
	{
		return FMCPCommonUtils::CreateErrorResponse(TEXT("Failed to find event graph"));
	}

	// Check if Component Bound Event node already exists for this widget/delegate combo
	for (UEdGraphNode* Node : EventGraph->Nodes)
	{
		UK2Node_ComponentBoundEvent* ExistingEvent = Cast<UK2Node_ComponentBoundEvent>(Node);
		if (ExistingEvent &&
			ExistingEvent->ComponentPropertyName == FName(*WidgetComponentName) &&
			ExistingEvent->DelegatePropertyName == DelegateProp->GetFName())
		{
			// Already exists - return the existing node
			TSharedPtr<FJsonObject> ResultObj = MakeShared<FJsonObject>();
			ResultObj->SetBoolField(TEXT("success"), true);
			ResultObj->SetBoolField(TEXT("already_exists"), true);
			ResultObj->SetStringField(TEXT("widget_name"), WidgetComponentName);
			ResultObj->SetStringField(TEXT("event_name"), EventName);
			ResultObj->SetStringField(TEXT("node_id"), ExistingEvent->NodeGuid.ToString());
			return ResultObj;
		}
	}

	// Calculate position for new node (below existing nodes)
	float MaxY = 0.0f;
	for (UEdGraphNode* Node : EventGraph->Nodes)
	{
		MaxY = FMath::Max(MaxY, (float)Node->NodePosY);
	}

	// Create Component Bound Event node - this is the proper way to handle widget events
	UK2Node_ComponentBoundEvent* EventNode = NewObject<UK2Node_ComponentBoundEvent>(EventGraph);
	EventGraph->AddNode(EventNode, false, false);
	EventNode->CreateNewGuid();

	// Find the widget as FObjectProperty on the WidgetBlueprint's GeneratedClass
	// to use the proper engine initializer (sets EventReference, CustomFunctionName,
	// bOverrideFunction, bInternalEvent in addition to the 3 basic fields)
	FObjectProperty* WidgetProp = FindFProperty<FObjectProperty>(
		WidgetBlueprint->GeneratedClass, FName(*WidgetComponentName));
	if (WidgetProp)
	{
		EventNode->InitializeComponentBoundEventParams(WidgetProp, DelegateProp);
	}
	else
	{
		// Fallback: manual field assignment (legacy path for edge cases)
		EventNode->ComponentPropertyName = FName(*WidgetComponentName);
		EventNode->DelegatePropertyName = DelegateProp->GetFName();
		EventNode->DelegateOwnerClass = Widget->GetClass();
	}

	EventNode->NodePosX = 200;
	EventNode->NodePosY = (int32)(MaxY + 200);
	EventNode->AllocateDefaultPins();

	UE_LOG(LogMCP, Log, TEXT("Created Component Bound Event: %s.%s"), *WidgetComponentName, *EventName);

	// Mark modified, compile, and refresh the Widget Designer
	WidgetBlueprint->MarkPackageDirty();
	MarkWidgetBlueprintDirty(WidgetBlueprint, Context);

	TSharedPtr<FJsonObject> ResultObj = MakeShared<FJsonObject>();
	ResultObj->SetBoolField(TEXT("success"), true);
	ResultObj->SetStringField(TEXT("widget_name"), WidgetComponentName);
	ResultObj->SetStringField(TEXT("event_name"), EventName);
	ResultObj->SetStringField(TEXT("node_id"), EventNode->NodeGuid.ToString());
	return ResultObj;
}

// =============================================================================
// FAddWidgetToViewportAction
// =============================================================================

bool FAddWidgetToViewportAction::Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError)
{
	if (!Params->HasField(TEXT("widget_name")))
	{
		OutError = TEXT("Missing 'widget_name' parameter");
		return false;
	}
	return true;
}

TSharedPtr<FJsonObject> FAddWidgetToViewportAction::ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context)
{
	FString BlueprintName = Params->GetStringField(TEXT("widget_name"));

	UWidgetBlueprint* WidgetBlueprint = FindWidgetBlueprintByName(BlueprintName);
	if (!WidgetBlueprint)
	{
		return FMCPCommonUtils::CreateErrorResponse(FString::Printf(
			TEXT("Widget Blueprint '%s' not found"), *BlueprintName));
	}

	int32 ZOrder = 0;
	Params->TryGetNumberField(TEXT("z_order"), ZOrder);

	UClass* WidgetClass = WidgetBlueprint->GeneratedClass;
	if (!WidgetClass)
	{
		return FMCPCommonUtils::CreateErrorResponse(TEXT("Failed to get widget class"));
	}

	TSharedPtr<FJsonObject> ResultObj = MakeShared<FJsonObject>();
	ResultObj->SetBoolField(TEXT("success"), true);
	ResultObj->SetStringField(TEXT("blueprint_name"), BlueprintName);
	ResultObj->SetStringField(TEXT("class_path"), WidgetClass->GetPathName());
	ResultObj->SetNumberField(TEXT("z_order"), ZOrder);
	ResultObj->SetStringField(TEXT("note"), TEXT("Widget class ready. Use CreateWidget and AddToViewport nodes in Blueprint."));
	return ResultObj;
}

// =============================================================================
// FSetTextBlockBindingAction
// =============================================================================

bool FSetTextBlockBindingAction::Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError)
{
	if (!Params->HasField(TEXT("widget_name")))
	{
		OutError = TEXT("Missing 'widget_name' parameter");
		return false;
	}
	if (!Params->HasField(TEXT("text_block_name")))
	{
		OutError = TEXT("Missing 'text_block_name' parameter");
		return false;
	}
	if (!Params->HasField(TEXT("binding_property")))
	{
		OutError = TEXT("Missing 'binding_property' parameter");
		return false;
	}
	return true;
}

TSharedPtr<FJsonObject> FSetTextBlockBindingAction::ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context)
{
	FString BlueprintName = Params->GetStringField(TEXT("widget_name"));
	FString WidgetName = Params->GetStringField(TEXT("text_block_name"));
	FString BindingName = Params->GetStringField(TEXT("binding_property"));

	UWidgetBlueprint* WidgetBlueprint = FindWidgetBlueprintByName(BlueprintName);
	if (!WidgetBlueprint)
	{
		return FMCPCommonUtils::CreateErrorResponse(FString::Printf(
			TEXT("Widget Blueprint '%s' not found"), *BlueprintName));
	}

	// Create variable for binding
	FBlueprintEditorUtils::AddMemberVariable(
		WidgetBlueprint,
		FName(*BindingName),
		FEdGraphPinType(UEdGraphSchema_K2::PC_Text, NAME_None, nullptr, EPinContainerType::None, false, FEdGraphTerminalType())
	);

	// Find the TextBlock widget
	UTextBlock* TextBlock = Cast<UTextBlock>(WidgetBlueprint->WidgetTree->FindWidget(FName(*WidgetName)));
	if (!TextBlock)
	{
		return FMCPCommonUtils::CreateErrorResponse(FString::Printf(
			TEXT("TextBlock '%s' not found"), *WidgetName));
	}

	// Create binding function
	const FString FunctionName = FString::Printf(TEXT("Get%s"), *BindingName);
	UEdGraph* FuncGraph = FBlueprintEditorUtils::CreateNewGraph(
		WidgetBlueprint,
		FName(*FunctionName),
		UEdGraph::StaticClass(),
		UEdGraphSchema_K2::StaticClass()
	);

	if (FuncGraph)
	{
		FBlueprintEditorUtils::AddFunctionGraph<UClass>(WidgetBlueprint, FuncGraph, false, nullptr);

		// Create entry node
		UK2Node_FunctionEntry* EntryNode = NewObject<UK2Node_FunctionEntry>(FuncGraph);
		FuncGraph->AddNode(EntryNode, false, false);
		EntryNode->NodePosX = 0;
		EntryNode->NodePosY = 0;
		EntryNode->FunctionReference.SetExternalMember(FName(*FunctionName), WidgetBlueprint->GeneratedClass);
		EntryNode->AllocateDefaultPins();

		// Create get variable node
		UK2Node_VariableGet* GetVarNode = NewObject<UK2Node_VariableGet>(FuncGraph);
		GetVarNode->VariableReference.SetSelfMember(FName(*BindingName));
		FuncGraph->AddNode(GetVarNode, false, false);
		GetVarNode->NodePosX = 200;
		GetVarNode->NodePosY = 0;
		GetVarNode->AllocateDefaultPins();

		// Connect nodes
		UEdGraphPin* EntryThenPin = EntryNode->FindPin(UEdGraphSchema_K2::PN_Then);
		UEdGraphPin* GetVarOutPin = GetVarNode->FindPin(UEdGraphSchema_K2::PN_ReturnValue);
		if (EntryThenPin && GetVarOutPin)
		{
			EntryThenPin->MakeLinkTo(GetVarOutPin);
		}
	}

	// Mark modified, compile, and refresh the Widget Designer
	WidgetBlueprint->MarkPackageDirty();
	MarkWidgetBlueprintDirty(WidgetBlueprint, Context);

	TSharedPtr<FJsonObject> ResultObj = MakeShared<FJsonObject>();
	ResultObj->SetBoolField(TEXT("success"), true);
	ResultObj->SetStringField(TEXT("binding_name"), BindingName);
	return ResultObj;
}

// =============================================================================
// FListWidgetComponentsAction
// =============================================================================

bool FListWidgetComponentsAction::Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError)
{
	if (!Params->HasField(TEXT("widget_name")))
	{
		OutError = TEXT("Missing 'widget_name' parameter");
		return false;
	}
	return true;
}

TSharedPtr<FJsonObject> FListWidgetComponentsAction::ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context)
{
	FString BlueprintName = Params->GetStringField(TEXT("widget_name"));

	UWidgetBlueprint* WidgetBlueprint = FindWidgetBlueprintByName(BlueprintName);
	if (!WidgetBlueprint)
	{
		return FMCPCommonUtils::CreateErrorResponse(FString::Printf(
			TEXT("Widget Blueprint '%s' not found"), *BlueprintName));
	}

	if (!WidgetBlueprint->WidgetTree)
	{
		return FMCPCommonUtils::CreateErrorResponse(TEXT("Widget Blueprint has no WidgetTree"));
	}

	TArray<TSharedPtr<FJsonValue>> Components;
	WidgetBlueprint->WidgetTree->ForEachWidget([&Components](UWidget* Widget)
	{
		if (!Widget)
		{
			return;
		}

		TSharedPtr<FJsonObject> ComponentObj = MakeShared<FJsonObject>();
		ComponentObj->SetStringField(TEXT("name"), Widget->GetName());
		ComponentObj->SetStringField(TEXT("class"), Widget->GetClass()->GetName());
		Components.Add(MakeShared<FJsonValueObject>(ComponentObj));
	});

	TSharedPtr<FJsonObject> ResultObj = MakeShared<FJsonObject>();
	ResultObj->SetBoolField(TEXT("success"), true);
	ResultObj->SetStringField(TEXT("widget_name"), BlueprintName);
	ResultObj->SetNumberField(TEXT("count"), Components.Num());
	ResultObj->SetArrayField(TEXT("components"), Components);
	return ResultObj;
}

// =============================================================================
// FReparentWidgetsAction
// =============================================================================

// Map of supported container types �� UClass*
static UClass* ResolveContainerClass(const FString& ContainerType)
{
	if (ContainerType.Equals(TEXT("VerticalBox"), ESearchCase::IgnoreCase)) return UVerticalBox::StaticClass();
	if (ContainerType.Equals(TEXT("HorizontalBox"), ESearchCase::IgnoreCase)) return UHorizontalBox::StaticClass();
	if (ContainerType.Equals(TEXT("Overlay"), ESearchCase::IgnoreCase)) return UOverlay::StaticClass();
	if (ContainerType.Equals(TEXT("CanvasPanel"), ESearchCase::IgnoreCase)) return UCanvasPanel::StaticClass();
	if (ContainerType.Equals(TEXT("SizeBox"), ESearchCase::IgnoreCase)) return USizeBox::StaticClass();
	if (ContainerType.Equals(TEXT("ScaleBox"), ESearchCase::IgnoreCase)) return UScaleBox::StaticClass();
	if (ContainerType.Equals(TEXT("Border"), ESearchCase::IgnoreCase)) return UBorder::StaticClass();
	return nullptr;
}

bool FReparentWidgetsAction::Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError)
{
	if (!Params->HasField(TEXT("widget_name")))
	{
		OutError = TEXT("Missing 'widget_name' parameter");
		return false;
	}
	if (!Params->HasField(TEXT("target_container_name")))
	{
		OutError = TEXT("Missing 'target_container_name' parameter");
		return false;
	}
	return true;
}

TSharedPtr<FJsonObject> FReparentWidgetsAction::ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context)
{
	FString BlueprintName = Params->GetStringField(TEXT("widget_name"));
	FString TargetContainerName = Params->GetStringField(TEXT("target_container_name"));

	// container_type: VerticalBox, HorizontalBox, Overlay, CanvasPanel, SizeBox, ScaleBox, Border
	FString ContainerType = TEXT("VerticalBox");
	Params->TryGetStringField(TEXT("container_type"), ContainerType);

	UWidgetBlueprint* WidgetBlueprint = FindWidgetBlueprintByName(BlueprintName);
	if (!WidgetBlueprint)
	{
		return FMCPCommonUtils::CreateErrorResponse(FString::Printf(
			TEXT("Widget Blueprint '%s' not found"), *BlueprintName));
	}

	UCanvasPanel* RootCanvas = Cast<UCanvasPanel>(WidgetBlueprint->WidgetTree->RootWidget);
	if (!RootCanvas)
	{
		return FMCPCommonUtils::CreateErrorResponse(TEXT("Root widget is not a Canvas Panel"));
	}

	// --- Resolve or create the target container ---
	UPanelWidget* TargetContainer = Cast<UPanelWidget>(WidgetBlueprint->WidgetTree->FindWidget(FName(*TargetContainerName)));
	if (!TargetContainer)
	{
		UClass* ContainerClass = ResolveContainerClass(ContainerType);
		if (!ContainerClass)
		{
			return FMCPCommonUtils::CreateErrorResponse(FString::Printf(
				TEXT("Unknown container_type '%s'. Supported: VerticalBox, HorizontalBox, Overlay, CanvasPanel, SizeBox, ScaleBox, Border"),
				*ContainerType));
		}

		UWidget* NewWidget = WidgetBlueprint->WidgetTree->ConstructWidget<UWidget>(ContainerClass, *TargetContainerName);
		TargetContainer = Cast<UPanelWidget>(NewWidget);
		if (!TargetContainer)
		{
			return FMCPCommonUtils::CreateErrorResponse(FString::Printf(
				TEXT("Failed to create container '%s' of type '%s'"), *TargetContainerName, *ContainerType));
		}

		UCanvasPanelSlot* Slot = RootCanvas->AddChildToCanvas(TargetContainer);
		ApplyCanvasSlot(Slot, Params);
	}
	else if (UCanvasPanelSlot* ExistingSlot = Cast<UCanvasPanelSlot>(TargetContainer->Slot))
	{
		ApplyCanvasSlot(ExistingSlot, Params);
	}

	// --- Determine which children to move ---
	TSet<FString> ChildFilter;
	const TArray<TSharedPtr<FJsonValue>>* ChildNames = nullptr;
	if (Params->TryGetArrayField(TEXT("children"), ChildNames))
	{
		for (const TSharedPtr<FJsonValue>& Val : *ChildNames)
		{
			ChildFilter.Add(Val->AsString());
		}
	}

	FString FilterClass;
	Params->TryGetStringField(TEXT("filter_class"), FilterClass);

	// Collect widgets to move (skip the target container itself)
	TArray<UWidget*> WidgetsToMove;
	WidgetBlueprint->WidgetTree->ForEachWidget([&](UWidget* Widget)
	{
		if (!Widget || Widget == TargetContainer)
		{
			return;
		}
		// Already a child of target
		if (Widget->GetParent() == TargetContainer)
		{
			return;
		}
		// If explicit children list provided, match by name
		if (ChildFilter.Num() > 0)
		{
			if (ChildFilter.Contains(Widget->GetName()))
			{
				WidgetsToMove.Add(Widget);
			}
			return;
		}
		// If filter_class provided, match by class name
		if (!FilterClass.IsEmpty())
		{
			if (Widget->GetClass()->GetName().Equals(FilterClass, ESearchCase::IgnoreCase))
			{
				WidgetsToMove.Add(Widget);
			}
			return;
		}
		// No filter �� move all direct children of root canvas (except target)
		if (Widget->GetParent() == RootCanvas)
		{
			WidgetsToMove.Add(Widget);
		}
	});

	// Move widgets into target container
	TArray<TSharedPtr<FJsonValue>> MovedNames;
	for (UWidget* Widget : WidgetsToMove)
	{
		Widget->RemoveFromParent();
		TargetContainer->AddChild(Widget);
		MovedNames.Add(MakeShared<FJsonValueString>(Widget->GetName()));
	}

	WidgetBlueprint->MarkPackageDirty();
	MarkWidgetBlueprintDirty(WidgetBlueprint, Context);

	TSharedPtr<FJsonObject> ResultObj = MakeShared<FJsonObject>();
	ResultObj->SetBoolField(TEXT("success"), true);
	ResultObj->SetStringField(TEXT("widget_name"), BlueprintName);
	ResultObj->SetStringField(TEXT("target_container"), TargetContainer->GetName());
	ResultObj->SetStringField(TEXT("container_class"), TargetContainer->GetClass()->GetName());
	ResultObj->SetNumberField(TEXT("moved_count"), WidgetsToMove.Num());
	ResultObj->SetArrayField(TEXT("moved_widgets"), MovedNames);
	return ResultObj;
}

// =============================================================================
// FSetWidgetPropertiesAction
// =============================================================================

bool FSetWidgetPropertiesAction::Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError)
{
	if (!Params->HasField(TEXT("widget_name")))
	{
		OutError = TEXT("Missing 'widget_name' parameter");
		return false;
	}
	if (!Params->HasField(TEXT("target")))
	{
		OutError = TEXT("Missing 'target' parameter (name of widget to modify)");
		return false;
	}
	return true;
}

TSharedPtr<FJsonObject> FSetWidgetPropertiesAction::ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context)
{
	FString BlueprintName = Params->GetStringField(TEXT("widget_name"));
	FString TargetName = Params->GetStringField(TEXT("target"));

	UWidgetBlueprint* WidgetBlueprint = FindWidgetBlueprintByName(BlueprintName);
	if (!WidgetBlueprint)
	{
		return FMCPCommonUtils::CreateErrorResponse(FString::Printf(
			TEXT("Widget Blueprint '%s' not found"), *BlueprintName));
	}

	UWidget* TargetWidget = WidgetBlueprint->WidgetTree->FindWidget(FName(*TargetName));
	if (!TargetWidget)
	{
		return FMCPCommonUtils::CreateErrorResponse(FString::Printf(
			TEXT("Widget '%s' not found in '%s'"), *TargetName, *BlueprintName));
	}

	TArray<FString> AppliedProps;

	// --- Render Transform: scale ---
	FVector2D Scale;
	if (TryGetVector2Field(Params, TEXT("render_scale"), Scale))
	{
		TargetWidget->SetRenderScale(Scale);
		AppliedProps.Add(TEXT("render_scale"));
	}

	// --- Render Transform: rotation angle ---
	double Angle = 0.0;
	if (Params->TryGetNumberField(TEXT("render_angle"), Angle))
	{
		TargetWidget->SetRenderTransformAngle(static_cast<float>(Angle));
		AppliedProps.Add(TEXT("render_angle"));
	}

	// --- Render Transform: shear ---
	FVector2D Shear;
	if (TryGetVector2Field(Params, TEXT("render_shear"), Shear))
	{
		TargetWidget->SetRenderShear(Shear);
		AppliedProps.Add(TEXT("render_shear"));
	}

	// --- Render Transform: translation ---
	FVector2D Translation;
	if (TryGetVector2Field(Params, TEXT("render_translation"), Translation))
	{
		FWidgetTransform CurrentTransform = TargetWidget->GetRenderTransform();
		CurrentTransform.Translation = Translation;
		TargetWidget->SetRenderTransform(CurrentTransform);
		AppliedProps.Add(TEXT("render_translation"));
	}

	// --- Render Transform: pivot ---
	FVector2D Pivot;
	if (TryGetVector2Field(Params, TEXT("render_pivot"), Pivot))
	{
		TargetWidget->SetRenderTransformPivot(Pivot);
		AppliedProps.Add(TEXT("render_pivot"));
	}

	// --- Visibility ---
	FString VisibilityStr;
	if (Params->TryGetStringField(TEXT("visibility"), VisibilityStr))
	{
		if (VisibilityStr.Equals(TEXT("Visible"), ESearchCase::IgnoreCase))
		{
			TargetWidget->SetVisibility(ESlateVisibility::Visible);
		}
		else if (VisibilityStr.Equals(TEXT("Collapsed"), ESearchCase::IgnoreCase))
		{
			TargetWidget->SetVisibility(ESlateVisibility::Collapsed);
		}
		else if (VisibilityStr.Equals(TEXT("Hidden"), ESearchCase::IgnoreCase))
		{
			TargetWidget->SetVisibility(ESlateVisibility::Hidden);
		}
		else if (VisibilityStr.Equals(TEXT("HitTestInvisible"), ESearchCase::IgnoreCase))
		{
			TargetWidget->SetVisibility(ESlateVisibility::HitTestInvisible);
		}
		else if (VisibilityStr.Equals(TEXT("SelfHitTestInvisible"), ESearchCase::IgnoreCase))
		{
			TargetWidget->SetVisibility(ESlateVisibility::SelfHitTestInvisible);
		}
		AppliedProps.Add(TEXT("visibility"));
	}

	// --- IsEnabled ---
	bool bIsEnabled = true;
	if (Params->TryGetBoolField(TEXT("is_enabled"), bIsEnabled))
	{
		TargetWidget->SetIsEnabled(bIsEnabled);
		AppliedProps.Add(TEXT("is_enabled"));
	}

	// --- Slot-specific properties ---
	UPanelSlot* Slot = TargetWidget->Slot;

	// CanvasPanelSlot: position, size, anchors, alignment
	if (UCanvasPanelSlot* CanvasSlot = Cast<UCanvasPanelSlot>(Slot))
	{
		FVector2D Position;
		if (TryGetVector2Field(Params, TEXT("position"), Position))
		{
			CanvasSlot->SetPosition(Position);
			AppliedProps.Add(TEXT("position"));
		}

		FVector2D Size;
		if (TryGetVector2Field(Params, TEXT("size"), Size))
		{
			CanvasSlot->SetSize(Size);
			CanvasSlot->SetAutoSize(false);
			AppliedProps.Add(TEXT("size"));
		}

		bool bAutoSize = false;
		if (Params->TryGetBoolField(TEXT("auto_size"), bAutoSize))
		{
			CanvasSlot->SetAutoSize(bAutoSize);
			AppliedProps.Add(TEXT("auto_size"));
		}

		int32 ZOrder = 0;
		if (Params->TryGetNumberField(TEXT("z_order"), ZOrder))
		{
			CanvasSlot->SetZOrder(ZOrder);
			AppliedProps.Add(TEXT("z_order"));
		}

		FVector2D Alignment;
		if (TryGetVector2Field(Params, TEXT("alignment"), Alignment))
		{
			CanvasSlot->SetAlignment(Alignment);
			AppliedProps.Add(TEXT("alignment"));
		}

		// Anchors: [MinX, MinY, MaxX, MaxY]
		FLinearColor AnchorValues;
		if (TryGetColorField(Params, TEXT("anchors"), AnchorValues))
		{
			FAnchors Anchors(AnchorValues.R, AnchorValues.G, AnchorValues.B, AnchorValues.A);
			CanvasSlot->SetAnchors(Anchors);
			AppliedProps.Add(TEXT("anchors"));
		}
	}

	// VerticalBoxSlot: padding, h-align, v-align, size rule
	if (UVerticalBoxSlot* VBoxSlot = Cast<UVerticalBoxSlot>(Slot))
	{
		FLinearColor PaddingValues;
		if (TryGetColorField(Params, TEXT("padding"), PaddingValues))
		{
			// [Left, Top, Right, Bottom]
			FMargin Margin(PaddingValues.R, PaddingValues.G, PaddingValues.B, PaddingValues.A);
			VBoxSlot->SetPadding(Margin);
			AppliedProps.Add(TEXT("padding"));
		}

		FString HAlign;
		if (Params->TryGetStringField(TEXT("h_align"), HAlign))
		{
			if (HAlign.Equals(TEXT("Fill"), ESearchCase::IgnoreCase)) VBoxSlot->SetHorizontalAlignment(EHorizontalAlignment::HAlign_Fill);
			else if (HAlign.Equals(TEXT("Left"), ESearchCase::IgnoreCase)) VBoxSlot->SetHorizontalAlignment(EHorizontalAlignment::HAlign_Left);
			else if (HAlign.Equals(TEXT("Center"), ESearchCase::IgnoreCase)) VBoxSlot->SetHorizontalAlignment(EHorizontalAlignment::HAlign_Center);
			else if (HAlign.Equals(TEXT("Right"), ESearchCase::IgnoreCase)) VBoxSlot->SetHorizontalAlignment(EHorizontalAlignment::HAlign_Right);
			AppliedProps.Add(TEXT("h_align"));
		}

		FString VAlign;
		if (Params->TryGetStringField(TEXT("v_align"), VAlign))
		{
			if (VAlign.Equals(TEXT("Fill"), ESearchCase::IgnoreCase)) VBoxSlot->SetVerticalAlignment(EVerticalAlignment::VAlign_Fill);
			else if (VAlign.Equals(TEXT("Top"), ESearchCase::IgnoreCase)) VBoxSlot->SetVerticalAlignment(EVerticalAlignment::VAlign_Top);
			else if (VAlign.Equals(TEXT("Center"), ESearchCase::IgnoreCase)) VBoxSlot->SetVerticalAlignment(EVerticalAlignment::VAlign_Center);
			else if (VAlign.Equals(TEXT("Bottom"), ESearchCase::IgnoreCase)) VBoxSlot->SetVerticalAlignment(EVerticalAlignment::VAlign_Bottom);
			AppliedProps.Add(TEXT("v_align"));
		}

		FString SizeRule;
		if (Params->TryGetStringField(TEXT("size_rule"), SizeRule))
		{
			FSlateChildSize ChildSize;
			if (SizeRule.Equals(TEXT("Auto"), ESearchCase::IgnoreCase))
			{
				ChildSize.SizeRule = ESlateSizeRule::Automatic;
			}
			else if (SizeRule.Equals(TEXT("Fill"), ESearchCase::IgnoreCase))
			{
				ChildSize.SizeRule = ESlateSizeRule::Fill;
			}
			VBoxSlot->SetSize(ChildSize);
			AppliedProps.Add(TEXT("size_rule"));
		}
	}

	// HorizontalBoxSlot: padding, h-align, v-align, size rule
	if (UHorizontalBoxSlot* HBoxSlot = Cast<UHorizontalBoxSlot>(Slot))
	{
		FLinearColor PaddingValues;
		if (TryGetColorField(Params, TEXT("padding"), PaddingValues))
		{
			FMargin Margin(PaddingValues.R, PaddingValues.G, PaddingValues.B, PaddingValues.A);
			HBoxSlot->SetPadding(Margin);
			AppliedProps.Add(TEXT("padding"));
		}

		FString HAlign;
		if (Params->TryGetStringField(TEXT("h_align"), HAlign))
		{
			if (HAlign.Equals(TEXT("Fill"), ESearchCase::IgnoreCase)) HBoxSlot->SetHorizontalAlignment(EHorizontalAlignment::HAlign_Fill);
			else if (HAlign.Equals(TEXT("Left"), ESearchCase::IgnoreCase)) HBoxSlot->SetHorizontalAlignment(EHorizontalAlignment::HAlign_Left);
			else if (HAlign.Equals(TEXT("Center"), ESearchCase::IgnoreCase)) HBoxSlot->SetHorizontalAlignment(EHorizontalAlignment::HAlign_Center);
			else if (HAlign.Equals(TEXT("Right"), ESearchCase::IgnoreCase)) HBoxSlot->SetHorizontalAlignment(EHorizontalAlignment::HAlign_Right);
			AppliedProps.Add(TEXT("h_align"));
		}

		FString VAlign;
		if (Params->TryGetStringField(TEXT("v_align"), VAlign))
		{
			if (VAlign.Equals(TEXT("Fill"), ESearchCase::IgnoreCase)) HBoxSlot->SetVerticalAlignment(EVerticalAlignment::VAlign_Fill);
			else if (VAlign.Equals(TEXT("Top"), ESearchCase::IgnoreCase)) HBoxSlot->SetVerticalAlignment(EVerticalAlignment::VAlign_Top);
			else if (VAlign.Equals(TEXT("Center"), ESearchCase::IgnoreCase)) HBoxSlot->SetVerticalAlignment(EVerticalAlignment::VAlign_Center);
			else if (VAlign.Equals(TEXT("Bottom"), ESearchCase::IgnoreCase)) HBoxSlot->SetVerticalAlignment(EVerticalAlignment::VAlign_Bottom);
			AppliedProps.Add(TEXT("v_align"));
		}

		FString SizeRule;
		if (Params->TryGetStringField(TEXT("size_rule"), SizeRule))
		{
			FSlateChildSize ChildSize;
			if (SizeRule.Equals(TEXT("Auto"), ESearchCase::IgnoreCase))
			{
				ChildSize.SizeRule = ESlateSizeRule::Automatic;
			}
			else if (SizeRule.Equals(TEXT("Fill"), ESearchCase::IgnoreCase))
			{
				ChildSize.SizeRule = ESlateSizeRule::Fill;
			}
			HBoxSlot->SetSize(ChildSize);
			AppliedProps.Add(TEXT("size_rule"));
		}
	}

	// OverlaySlot: padding, h-align, v-align
	if (UOverlaySlot* OvSlot = Cast<UOverlaySlot>(Slot))
	{
		FLinearColor PaddingValues;
		if (TryGetColorField(Params, TEXT("padding"), PaddingValues))
		{
			FMargin Margin(PaddingValues.R, PaddingValues.G, PaddingValues.B, PaddingValues.A);
			OvSlot->SetPadding(Margin);
			AppliedProps.Add(TEXT("padding"));
		}

		FString HAlign;
		if (Params->TryGetStringField(TEXT("h_align"), HAlign))
		{
			if (HAlign.Equals(TEXT("Fill"), ESearchCase::IgnoreCase)) OvSlot->SetHorizontalAlignment(EHorizontalAlignment::HAlign_Fill);
			else if (HAlign.Equals(TEXT("Left"), ESearchCase::IgnoreCase)) OvSlot->SetHorizontalAlignment(EHorizontalAlignment::HAlign_Left);
			else if (HAlign.Equals(TEXT("Center"), ESearchCase::IgnoreCase)) OvSlot->SetHorizontalAlignment(EHorizontalAlignment::HAlign_Center);
			else if (HAlign.Equals(TEXT("Right"), ESearchCase::IgnoreCase)) OvSlot->SetHorizontalAlignment(EHorizontalAlignment::HAlign_Right);
			AppliedProps.Add(TEXT("h_align"));
		}

		FString VAlign;
		if (Params->TryGetStringField(TEXT("v_align"), VAlign))
		{
			if (VAlign.Equals(TEXT("Fill"), ESearchCase::IgnoreCase)) OvSlot->SetVerticalAlignment(EVerticalAlignment::VAlign_Fill);
			else if (VAlign.Equals(TEXT("Top"), ESearchCase::IgnoreCase)) OvSlot->SetVerticalAlignment(EVerticalAlignment::VAlign_Top);
			else if (VAlign.Equals(TEXT("Center"), ESearchCase::IgnoreCase)) OvSlot->SetVerticalAlignment(EVerticalAlignment::VAlign_Center);
			else if (VAlign.Equals(TEXT("Bottom"), ESearchCase::IgnoreCase)) OvSlot->SetVerticalAlignment(EVerticalAlignment::VAlign_Bottom);
			AppliedProps.Add(TEXT("v_align"));
		}
	}

	// =================================================================
	// Type-specific widget properties
	// =================================================================

	// Image: brush_texture (set texture asset on Image widget)
	FString BrushTexture;
	if (Params->TryGetStringField(TEXT("brush_texture"), BrushTexture))
	{
		if (UImage* ImageWidget = Cast<UImage>(TargetWidget))
		{
			UObject* TextureObj = UEditorAssetLibrary::LoadAsset(BrushTexture);
			if (UTexture2D* Texture = Cast<UTexture2D>(TextureObj))
			{
				ImageWidget->SetBrushFromTexture(Texture);
				AppliedProps.Add(TEXT("brush_texture"));
			}
		}
	}

	// Image: brush_size
	FVector2D BrushSize;
	if (TryGetVector2Field(Params, TEXT("brush_size"), BrushSize))
	{
		if (UImage* ImageWidget = Cast<UImage>(TargetWidget))
		{
			FSlateBrush CurrentBrush = ImageWidget->GetBrush();
			CurrentBrush.ImageSize = BrushSize;
			ImageWidget->SetBrush(CurrentBrush);
			AppliedProps.Add(TEXT("brush_size"));
		}
	}

	// Image: color_and_opacity
	{
		FLinearColor ImgColor;
		if (TryGetColorField(Params, TEXT("color_and_opacity"), ImgColor))
		{
			if (UImage* ImageWidget = Cast<UImage>(TargetWidget))
			{
				ImageWidget->SetColorAndOpacity(ImgColor);
				AppliedProps.Add(TEXT("color_and_opacity"));
			}
		}
	}

	// Button: normal/hovered/pressed tint colors
	{
		FLinearColor BtnNormalColor;
		if (TryGetColorField(Params, TEXT("button_normal_color"), BtnNormalColor))
		{
			if (UButton* ButtonWidget = Cast<UButton>(TargetWidget))
			{
				FButtonStyle Style = ButtonWidget->GetStyle();
				Style.Normal.TintColor = FSlateColor(BtnNormalColor);
				ButtonWidget->SetStyle(Style);
				AppliedProps.Add(TEXT("button_normal_color"));
			}
		}

		FLinearColor BtnHoveredColor;
		if (TryGetColorField(Params, TEXT("button_hovered_color"), BtnHoveredColor))
		{
			if (UButton* ButtonWidget = Cast<UButton>(TargetWidget))
			{
				FButtonStyle Style = ButtonWidget->GetStyle();
				Style.Hovered.TintColor = FSlateColor(BtnHoveredColor);
				ButtonWidget->SetStyle(Style);
				AppliedProps.Add(TEXT("button_hovered_color"));
			}
		}

		FLinearColor BtnPressedColor;
		if (TryGetColorField(Params, TEXT("button_pressed_color"), BtnPressedColor))
		{
			if (UButton* ButtonWidget = Cast<UButton>(TargetWidget))
			{
				FButtonStyle Style = ButtonWidget->GetStyle();
				Style.Pressed.TintColor = FSlateColor(BtnPressedColor);
				ButtonWidget->SetStyle(Style);
				AppliedProps.Add(TEXT("button_pressed_color"));
			}
		}
	}

	// WidgetSwitcher: active_widget_index
	{
		int32 ActiveIndex = 0;
		if (Params->TryGetNumberField(TEXT("active_widget_index"), ActiveIndex))
		{
			if (UWidgetSwitcher* Switcher = Cast<UWidgetSwitcher>(TargetWidget))
			{
				Switcher->SetActiveWidgetIndex(ActiveIndex);
				AppliedProps.Add(TEXT("active_widget_index"));
			}
		}
	}

	// BackgroundBlur: blur_strength
	{
		double BlurStrength = 0;
		if (Params->TryGetNumberField(TEXT("blur_strength"), BlurStrength))
		{
			if (UBackgroundBlur* BlurWidget = Cast<UBackgroundBlur>(TargetWidget))
			{
				BlurWidget->SetBlurStrength(static_cast<float>(BlurStrength));
				AppliedProps.Add(TEXT("blur_strength"));
			}
		}
	}

	// Border: brush_color (TintColor of the background brush). 接受 [r,g,b,a] 0..1 浮点。
	{
		FLinearColor BorderTint;
		if (TryGetColorField(Params, TEXT("brush_color"), BorderTint))
		{
			if (UBorder* BorderWidget = Cast<UBorder>(TargetWidget))
			{
				BorderWidget->SetBrushColor(BorderTint);
				AppliedProps.Add(TEXT("brush_color"));
			}
		}
	}

	// Generic reflected FText UPROPERTY setter（专为子 UserWidget 暴露的 ButtonText / Caption 等公共变量）。
	// 例如 WBP_P111CommonButton 实例上的 ButtonText —— 不能用 SetText（不是 TextBlock），
	// 也不能用 BP CDO 顶层的 set_blueprint_property（属于 sub-object）；
	// 这里直接对 TargetWidget 自身反射 FindPropertyByName 然后 ImportText。
	{
		FString TextPropName, TextValue;
		if (Params->TryGetStringField(TEXT("text_property_name"), TextPropName) &&
			Params->TryGetStringField(TEXT("text_property_value"), TextValue))
		{
			if (FProperty* Prop = TargetWidget->GetClass()->FindPropertyByName(FName(*TextPropName)))
			{
				if (FTextProperty* TextProp = CastField<FTextProperty>(Prop))
				{
					FText NewText = FText::FromString(TextValue);
					TextProp->SetPropertyValue_InContainer(TargetWidget, NewText);
					AppliedProps.Add(FString::Printf(TEXT("text_property:%s"), *TextPropName));
				}
				else if (FStrProperty* StrProp = CastField<FStrProperty>(Prop))
				{
					StrProp->SetPropertyValue_InContainer(TargetWidget, TextValue);
					AppliedProps.Add(FString::Printf(TEXT("str_property:%s"), *TextPropName));
				}
			}
		}
	}

	WidgetBlueprint->MarkPackageDirty();
	MarkWidgetBlueprintDirty(WidgetBlueprint, Context);

	TSharedPtr<FJsonObject> ResultObj = MakeShared<FJsonObject>();
	ResultObj->SetBoolField(TEXT("success"), true);
	ResultObj->SetStringField(TEXT("widget_name"), BlueprintName);
	ResultObj->SetStringField(TEXT("target"), TargetName);
	ResultObj->SetStringField(TEXT("target_class"), TargetWidget->GetClass()->GetName());

	FString SlotType = TEXT("none");
	if (Slot)
	{
		SlotType = Slot->GetClass()->GetName();
	}
	ResultObj->SetStringField(TEXT("slot_type"), SlotType);

	TArray<TSharedPtr<FJsonValue>> AppliedArr;
	for (const FString& Prop : AppliedProps)
	{
		AppliedArr.Add(MakeShared<FJsonValueString>(Prop));
	}
	ResultObj->SetArrayField(TEXT("applied_properties"), AppliedArr);
	return ResultObj;
}

// =============================================================================
// FGetWidgetTreeAction
// =============================================================================

bool FGetWidgetTreeAction::Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError)
{
	if (!Params->HasField(TEXT("widget_name")))
	{
		OutError = TEXT("Missing 'widget_name' parameter");
		return false;
	}
	return true;
}

static TSharedPtr<FJsonObject> BuildWidgetNodeJson(UWidget* Widget, UWidgetTree* WidgetTree)
{
	if (!Widget)
	{
		return nullptr;
	}

	TSharedPtr<FJsonObject> NodeObj = MakeShared<FJsonObject>();
	NodeObj->SetStringField(TEXT("name"), Widget->GetName());
	NodeObj->SetStringField(TEXT("class"), Widget->GetClass()->GetName());
	NodeObj->SetBoolField(TEXT("is_visible"), Widget->IsVisible());

	// RenderTransform info
	FWidgetTransform RT = Widget->GetRenderTransform();
	{
		TSharedPtr<FJsonObject> TransformObj = MakeShared<FJsonObject>();
		TArray<TSharedPtr<FJsonValue>> TransArr;
		TransArr.Add(MakeShared<FJsonValueNumber>(RT.Translation.X));
		TransArr.Add(MakeShared<FJsonValueNumber>(RT.Translation.Y));
		TransformObj->SetArrayField(TEXT("translation"), TransArr);

		TArray<TSharedPtr<FJsonValue>> ScaleArr;
		ScaleArr.Add(MakeShared<FJsonValueNumber>(RT.Scale.X));
		ScaleArr.Add(MakeShared<FJsonValueNumber>(RT.Scale.Y));
		TransformObj->SetArrayField(TEXT("scale"), ScaleArr);

		TArray<TSharedPtr<FJsonValue>> ShearArr;
		ShearArr.Add(MakeShared<FJsonValueNumber>(RT.Shear.X));
		ShearArr.Add(MakeShared<FJsonValueNumber>(RT.Shear.Y));
		TransformObj->SetArrayField(TEXT("shear"), ShearArr);

		TransformObj->SetNumberField(TEXT("angle"), RT.Angle);
		NodeObj->SetObjectField(TEXT("render_transform"), TransformObj);
	}

	// Slot info
	UPanelSlot* Slot = Widget->Slot;
	if (Slot)
	{
		TSharedPtr<FJsonObject> SlotObj = MakeShared<FJsonObject>();
		SlotObj->SetStringField(TEXT("type"), Slot->GetClass()->GetName());

		if (UCanvasPanelSlot* CanvasSlot = Cast<UCanvasPanelSlot>(Slot))
		{
			FVector2D Pos = CanvasSlot->GetPosition();
			FVector2D Sz = CanvasSlot->GetSize();
			TArray<TSharedPtr<FJsonValue>> PosArr;
			PosArr.Add(MakeShared<FJsonValueNumber>(Pos.X));
			PosArr.Add(MakeShared<FJsonValueNumber>(Pos.Y));
			SlotObj->SetArrayField(TEXT("position"), PosArr);

			TArray<TSharedPtr<FJsonValue>> SzArr;
			SzArr.Add(MakeShared<FJsonValueNumber>(Sz.X));
			SzArr.Add(MakeShared<FJsonValueNumber>(Sz.Y));
			SlotObj->SetArrayField(TEXT("size"), SzArr);

			SlotObj->SetBoolField(TEXT("auto_size"), CanvasSlot->GetAutoSize());
			SlotObj->SetNumberField(TEXT("z_order"), CanvasSlot->GetZOrder());

			FAnchors Anchors = CanvasSlot->GetAnchors();
			TArray<TSharedPtr<FJsonValue>> AnchorArr;
			AnchorArr.Add(MakeShared<FJsonValueNumber>(Anchors.Minimum.X));
			AnchorArr.Add(MakeShared<FJsonValueNumber>(Anchors.Minimum.Y));
			AnchorArr.Add(MakeShared<FJsonValueNumber>(Anchors.Maximum.X));
			AnchorArr.Add(MakeShared<FJsonValueNumber>(Anchors.Maximum.Y));
			SlotObj->SetArrayField(TEXT("anchors"), AnchorArr);

			FVector2D Alignment = CanvasSlot->GetAlignment();
			TArray<TSharedPtr<FJsonValue>> AlignArr;
			AlignArr.Add(MakeShared<FJsonValueNumber>(Alignment.X));
			AlignArr.Add(MakeShared<FJsonValueNumber>(Alignment.Y));
			SlotObj->SetArrayField(TEXT("alignment"), AlignArr);
		}

		if (UVerticalBoxSlot* VSlot = Cast<UVerticalBoxSlot>(Slot))
		{
			FMargin Pad = VSlot->GetPadding();
			TArray<TSharedPtr<FJsonValue>> PadArr;
			PadArr.Add(MakeShared<FJsonValueNumber>(Pad.Left));
			PadArr.Add(MakeShared<FJsonValueNumber>(Pad.Top));
			PadArr.Add(MakeShared<FJsonValueNumber>(Pad.Right));
			PadArr.Add(MakeShared<FJsonValueNumber>(Pad.Bottom));
			SlotObj->SetArrayField(TEXT("padding"), PadArr);
		}

		if (UHorizontalBoxSlot* HSlot = Cast<UHorizontalBoxSlot>(Slot))
		{
			FMargin Pad = HSlot->GetPadding();
			TArray<TSharedPtr<FJsonValue>> PadArr;
			PadArr.Add(MakeShared<FJsonValueNumber>(Pad.Left));
			PadArr.Add(MakeShared<FJsonValueNumber>(Pad.Top));
			PadArr.Add(MakeShared<FJsonValueNumber>(Pad.Right));
			PadArr.Add(MakeShared<FJsonValueNumber>(Pad.Bottom));
			SlotObj->SetArrayField(TEXT("padding"), PadArr);
		}

		if (UOverlaySlot* OSlot = Cast<UOverlaySlot>(Slot))
		{
			FMargin Pad = OSlot->GetPadding();
			TArray<TSharedPtr<FJsonValue>> PadArr;
			PadArr.Add(MakeShared<FJsonValueNumber>(Pad.Left));
			PadArr.Add(MakeShared<FJsonValueNumber>(Pad.Top));
			PadArr.Add(MakeShared<FJsonValueNumber>(Pad.Right));
			PadArr.Add(MakeShared<FJsonValueNumber>(Pad.Bottom));
			SlotObj->SetArrayField(TEXT("padding"), PadArr);
		}

		NodeObj->SetObjectField(TEXT("slot"), SlotObj);
	}

	// Children
	UPanelWidget* Panel = Cast<UPanelWidget>(Widget);
	if (Panel)
	{
		TArray<TSharedPtr<FJsonValue>> ChildArr;
		for (int32 i = 0; i < Panel->GetChildrenCount(); ++i)
		{
			UWidget* Child = Panel->GetChildAt(i);
			TSharedPtr<FJsonObject> ChildNode = BuildWidgetNodeJson(Child, WidgetTree);
			if (ChildNode)
			{
				ChildArr.Add(MakeShared<FJsonValueObject>(ChildNode));
			}
		}
		if (ChildArr.Num() > 0)
		{
			NodeObj->SetArrayField(TEXT("children"), ChildArr);
		}
	}

	return NodeObj;
}

TSharedPtr<FJsonObject> FGetWidgetTreeAction::ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context)
{
	FString BlueprintName = Params->GetStringField(TEXT("widget_name"));

	UWidgetBlueprint* WidgetBlueprint = FindWidgetBlueprintByName(BlueprintName);
	if (!WidgetBlueprint)
	{
		return FMCPCommonUtils::CreateErrorResponse(FString::Printf(
			TEXT("Widget Blueprint '%s' not found"), *BlueprintName));
	}

	if (!WidgetBlueprint->WidgetTree || !WidgetBlueprint->WidgetTree->RootWidget)
	{
		return FMCPCommonUtils::CreateErrorResponse(TEXT("Widget Blueprint has no root widget"));
	}

	TSharedPtr<FJsonObject> TreeNode = BuildWidgetNodeJson(WidgetBlueprint->WidgetTree->RootWidget, WidgetBlueprint->WidgetTree);

	TSharedPtr<FJsonObject> ResultObj = MakeShared<FJsonObject>();
	ResultObj->SetBoolField(TEXT("success"), true);
	ResultObj->SetStringField(TEXT("widget_name"), BlueprintName);
	ResultObj->SetObjectField(TEXT("tree"), TreeNode);
	return ResultObj;
}

// =============================================================================
// FDeleteWidgetFromBlueprintAction
// =============================================================================

bool FDeleteWidgetFromBlueprintAction::Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError)
{
	if (!Params->HasField(TEXT("widget_name")))
	{
		OutError = TEXT("Missing 'widget_name' parameter");
		return false;
	}
	if (!Params->HasField(TEXT("target")))
	{
		OutError = TEXT("Missing 'target' parameter");
		return false;
	}
	return true;
}

TSharedPtr<FJsonObject> FDeleteWidgetFromBlueprintAction::ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context)
{
	FString BlueprintName = Params->GetStringField(TEXT("widget_name"));
	FString TargetName = Params->GetStringField(TEXT("target"));

	UWidgetBlueprint* WidgetBlueprint = FindWidgetBlueprintByName(BlueprintName);
	if (!WidgetBlueprint)
	{
		return FMCPCommonUtils::CreateErrorResponse(FString::Printf(
			TEXT("Widget Blueprint '%s' not found"), *BlueprintName));
	}

	UWidget* TargetWidget = WidgetBlueprint->WidgetTree->FindWidget(FName(*TargetName));
	if (!TargetWidget)
	{
		return FMCPCommonUtils::CreateErrorResponse(FString::Printf(
			TEXT("Widget '%s' not found in '%s'"), *TargetName, *BlueprintName));
	}

	// Cannot delete root widget
	if (TargetWidget == WidgetBlueprint->WidgetTree->RootWidget)
	{
		return FMCPCommonUtils::CreateErrorResponse(TEXT("Cannot delete the root widget"));
	}

	// Remove from parent
	TargetWidget->RemoveFromParent();

	// Remove widget and its children from the widget tree
	WidgetBlueprint->WidgetTree->RemoveWidget(TargetWidget);

	WidgetBlueprint->MarkPackageDirty();
	MarkWidgetBlueprintDirty(WidgetBlueprint, Context);

	TSharedPtr<FJsonObject> ResultObj = MakeShared<FJsonObject>();
	ResultObj->SetBoolField(TEXT("success"), true);
	ResultObj->SetStringField(TEXT("widget_name"), BlueprintName);
	ResultObj->SetStringField(TEXT("deleted_widget"), TargetName);
	return ResultObj;
}

// =============================================================================
// FRenameWidgetInBlueprintAction
// =============================================================================

bool FRenameWidgetInBlueprintAction::Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError)
{
	if (!Params->HasField(TEXT("widget_name")))
	{
		OutError = TEXT("Missing 'widget_name' parameter");
		return false;
	}
	if (!Params->HasField(TEXT("target")))
	{
		OutError = TEXT("Missing 'target' parameter");
		return false;
	}
	if (!Params->HasField(TEXT("new_name")))
	{
		OutError = TEXT("Missing 'new_name' parameter");
		return false;
	}
	return true;
}

TSharedPtr<FJsonObject> FRenameWidgetInBlueprintAction::ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context)
{
	FString BlueprintName = Params->GetStringField(TEXT("widget_name"));
	FString TargetName = Params->GetStringField(TEXT("target"));
	FString NewName = Params->GetStringField(TEXT("new_name"));

	UWidgetBlueprint* WidgetBlueprint = FindWidgetBlueprintByName(BlueprintName);
	if (!WidgetBlueprint)
	{
		return FMCPCommonUtils::CreateErrorResponse(FString::Printf(
			TEXT("Widget Blueprint '%s' not found"), *BlueprintName));
	}

	UWidget* TargetWidget = WidgetBlueprint->WidgetTree->FindWidget(FName(*TargetName));
	if (!TargetWidget)
	{
		return FMCPCommonUtils::CreateErrorResponse(FString::Printf(
			TEXT("Widget '%s' not found in '%s'"), *TargetName, *BlueprintName));
	}

	// Check if new name already exists
	UWidget* ExistingWidget = WidgetBlueprint->WidgetTree->FindWidget(FName(*NewName));
	if (ExistingWidget && ExistingWidget != TargetWidget)
	{
		return FMCPCommonUtils::CreateErrorResponse(FString::Printf(
			TEXT("A widget named '%s' already exists in '%s'"), *NewName, *BlueprintName));
	}

	FString OldName = TargetWidget->GetName();
	TargetWidget->Rename(*NewName, WidgetBlueprint->WidgetTree);

	WidgetBlueprint->MarkPackageDirty();
	MarkWidgetBlueprintDirty(WidgetBlueprint, Context);

	TSharedPtr<FJsonObject> ResultObj = MakeShared<FJsonObject>();
	ResultObj->SetBoolField(TEXT("success"), true);
	ResultObj->SetStringField(TEXT("widget_name"), BlueprintName);
	ResultObj->SetStringField(TEXT("old_name"), OldName);
	ResultObj->SetStringField(TEXT("new_name"), TargetWidget->GetName());
	return ResultObj;
}

// =============================================================================
// FAddWidgetChildAction
// =============================================================================

bool FAddWidgetChildAction::Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError)
{
	if (!Params->HasField(TEXT("widget_name")))
	{
		OutError = TEXT("Missing 'widget_name' parameter");
		return false;
	}
	if (!Params->HasField(TEXT("child")))
	{
		OutError = TEXT("Missing 'child' parameter");
		return false;
	}
	if (!Params->HasField(TEXT("parent")))
	{
		OutError = TEXT("Missing 'parent' parameter");
		return false;
	}
	return true;
}

TSharedPtr<FJsonObject> FAddWidgetChildAction::ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context)
{
	FString BlueprintName = Params->GetStringField(TEXT("widget_name"));
	FString ChildName = Params->GetStringField(TEXT("child"));
	FString ParentName = Params->GetStringField(TEXT("parent"));

	UWidgetBlueprint* WidgetBlueprint = FindWidgetBlueprintByName(BlueprintName);
	if (!WidgetBlueprint)
	{
		return FMCPCommonUtils::CreateErrorResponse(FString::Printf(
			TEXT("Widget Blueprint '%s' not found"), *BlueprintName));
	}

	UWidget* ChildWidget = WidgetBlueprint->WidgetTree->FindWidget(FName(*ChildName));
	if (!ChildWidget)
	{
		return FMCPCommonUtils::CreateErrorResponse(FString::Printf(
			TEXT("Child widget '%s' not found in '%s'"), *ChildName, *BlueprintName));
	}

	UWidget* ParentWidget = WidgetBlueprint->WidgetTree->FindWidget(FName(*ParentName));
	if (!ParentWidget)
	{
		return FMCPCommonUtils::CreateErrorResponse(FString::Printf(
			TEXT("Parent widget '%s' not found in '%s'"), *ParentName, *BlueprintName));
	}

	UPanelWidget* ParentPanel = Cast<UPanelWidget>(ParentWidget);
	if (!ParentPanel)
	{
		return FMCPCommonUtils::CreateErrorResponse(FString::Printf(
			TEXT("Widget '%s' is not a container (PanelWidget) and cannot have children"), *ParentName));
	}

	// Avoid circular parenting
	if (ChildWidget == ParentWidget)
	{
		return FMCPCommonUtils::CreateErrorResponse(TEXT("Cannot parent a widget to itself"));
	}

	// Remove child from its current parent
	ChildWidget->RemoveFromParent();

	// Add to new parent
	UPanelSlot* Slot = ParentPanel->AddChild(ChildWidget);
	if (!Slot)
	{
		return FMCPCommonUtils::CreateErrorResponse(FString::Printf(
			TEXT("Failed to add '%s' as child of '%s'"), *ChildName, *ParentName));
	}

	WidgetBlueprint->MarkPackageDirty();
	MarkWidgetBlueprintDirty(WidgetBlueprint, Context);

	TSharedPtr<FJsonObject> ResultObj = MakeShared<FJsonObject>();
	ResultObj->SetBoolField(TEXT("success"), true);
	ResultObj->SetStringField(TEXT("widget_name"), BlueprintName);
	ResultObj->SetStringField(TEXT("child"), ChildWidget->GetName());
	ResultObj->SetStringField(TEXT("parent"), ParentPanel->GetName());
	ResultObj->SetStringField(TEXT("parent_class"), ParentPanel->GetClass()->GetName());
	return ResultObj;
}

// =============================================================================
// FDeleteUMGWidgetBlueprintAction
// =============================================================================

bool FDeleteUMGWidgetBlueprintAction::Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError)
{
	if (!Params->HasField(TEXT("widget_name")))
	{
		OutError = TEXT("Missing 'widget_name' parameter");
		return false;
	}
	return true;
}

TSharedPtr<FJsonObject> FDeleteUMGWidgetBlueprintAction::ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context)
{
	FString BlueprintName = Params->GetStringField(TEXT("widget_name"));

	UWidgetBlueprint* WidgetBlueprint = FindWidgetBlueprintByName(BlueprintName);
	if (!WidgetBlueprint)
	{
		return FMCPCommonUtils::CreateErrorResponse(FString::Printf(
			TEXT("Widget Blueprint '%s' not found"), *BlueprintName));
	}

	FString AssetPath = WidgetBlueprint->GetPathName();
	// Get the package path (without object name)
	FString PackagePath = FPackageName::ObjectPathToPackageName(AssetPath);

	bool bDeleted = UEditorAssetLibrary::DeleteAsset(PackagePath);
	if (!bDeleted)
	{
		return FMCPCommonUtils::CreateErrorResponse(FString::Printf(
			TEXT("Failed to delete Widget Blueprint '%s' at path '%s'"), *BlueprintName, *PackagePath));
	}

	TSharedPtr<FJsonObject> ResultObj = MakeShared<FJsonObject>();
	ResultObj->SetBoolField(TEXT("success"), true);
	ResultObj->SetStringField(TEXT("deleted_asset"), PackagePath);
	return ResultObj;
}


// =============================================================================
// FSetComboBoxOptionsAction
// =============================================================================

bool FSetComboBoxOptionsAction::Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError)
{
	if (!Params->HasField(TEXT("widget_name")))
	{
		OutError = TEXT("Missing 'widget_name' parameter");
		return false;
	}
	if (!Params->HasField(TEXT("target")))
	{
		OutError = TEXT("Missing 'target' parameter (name of ComboBoxString widget)");
		return false;
	}
	return true;
}

TSharedPtr<FJsonObject> FSetComboBoxOptionsAction::ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context)
{
	FString BlueprintName = Params->GetStringField(TEXT("widget_name"));
	FString TargetName = Params->GetStringField(TEXT("target"));
	FString Mode = GetOptionalString(Params, TEXT("mode"), TEXT("replace"));

	UWidgetBlueprint* WidgetBlueprint = FindWidgetBlueprintByName(BlueprintName);
	if (!WidgetBlueprint)
	{
		return FMCPCommonUtils::CreateErrorResponse(FString::Printf(
			TEXT("Widget Blueprint '%s' not found"), *BlueprintName));
	}

	UWidget* TargetWidget = WidgetBlueprint->WidgetTree->FindWidget(FName(*TargetName));
	if (!TargetWidget)
	{
		return FMCPCommonUtils::CreateErrorResponse(FString::Printf(
			TEXT("Widget '%s' not found in '%s'"), *TargetName, *BlueprintName));
	}

	UComboBoxString* ComboBox = Cast<UComboBoxString>(TargetWidget);
	if (!ComboBox)
	{
		return FMCPCommonUtils::CreateErrorResponse(FString::Printf(
			TEXT("Widget '%s' is not a ComboBoxString (actual: %s)"), *TargetName, *TargetWidget->GetClass()->GetName()));
	}

	const TArray<TSharedPtr<FJsonValue>>* OptionsArray = nullptr;
	Params->TryGetArrayField(TEXT("options"), OptionsArray);

	if (Mode.Equals(TEXT("replace"), ESearchCase::IgnoreCase))
	{
		// Clear existing and add new
		ComboBox->ClearOptions();
		if (OptionsArray)
		{
			for (const TSharedPtr<FJsonValue>& Val : *OptionsArray)
			{
				ComboBox->AddOption(Val->AsString());
			}
		}
	}
	else if (Mode.Equals(TEXT("add"), ESearchCase::IgnoreCase))
	{
		// Add to existing
		if (OptionsArray)
		{
			for (const TSharedPtr<FJsonValue>& Val : *OptionsArray)
			{
				ComboBox->AddOption(Val->AsString());
			}
		}
	}
	else if (Mode.Equals(TEXT("remove"), ESearchCase::IgnoreCase))
	{
		// Remove specified options
		if (OptionsArray)
		{
			for (const TSharedPtr<FJsonValue>& Val : *OptionsArray)
			{
				ComboBox->RemoveOption(Val->AsString());
			}
		}
	}
	else if (Mode.Equals(TEXT("clear"), ESearchCase::IgnoreCase))
	{
		ComboBox->ClearOptions();
	}

	// Set selected option if specified
	FString SelectedOption;
	if (Params->TryGetStringField(TEXT("selected_option"), SelectedOption))
	{
		ComboBox->SetSelectedOption(SelectedOption);
	}

	WidgetBlueprint->MarkPackageDirty();
	MarkWidgetBlueprintDirty(WidgetBlueprint, Context);

	TSharedPtr<FJsonObject> ResultObj = MakeShared<FJsonObject>();
	ResultObj->SetBoolField(TEXT("success"), true);
	ResultObj->SetStringField(TEXT("widget_name"), TargetName);
	ResultObj->SetStringField(TEXT("mode"), Mode);
	ResultObj->SetNumberField(TEXT("option_count"), ComboBox->GetOptionCount());
	return ResultObj;
}


// =============================================================================
// FSetWidgetTextAction
// =============================================================================

bool FSetWidgetTextAction::Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError)
{
	if (!Params->HasField(TEXT("widget_name")))
	{
		OutError = TEXT("Missing 'widget_name' parameter");
		return false;
	}
	if (!Params->HasField(TEXT("target")))
	{
		OutError = TEXT("Missing 'target' parameter (name of TextBlock or Button widget)");
		return false;
	}
	return true;
}

TSharedPtr<FJsonObject> FSetWidgetTextAction::ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context)
{
	FString BlueprintName = Params->GetStringField(TEXT("widget_name"));
	FString TargetName = Params->GetStringField(TEXT("target"));

	UWidgetBlueprint* WidgetBlueprint = FindWidgetBlueprintByName(BlueprintName);
	if (!WidgetBlueprint)
	{
		return FMCPCommonUtils::CreateErrorResponse(FString::Printf(
			TEXT("Widget Blueprint '%s' not found"), *BlueprintName));
	}

	UWidget* TargetWidget = WidgetBlueprint->WidgetTree->FindWidget(FName(*TargetName));
	if (!TargetWidget)
	{
		return FMCPCommonUtils::CreateErrorResponse(FString::Printf(
			TEXT("Widget '%s' not found in '%s'"), *TargetName, *BlueprintName));
	}

	TArray<FString> AppliedProps;

	// Handle TextBlock
	if (UTextBlock* TextBlock = Cast<UTextBlock>(TargetWidget))
	{
		FString Text;
		if (Params->TryGetStringField(TEXT("text"), Text))
		{
			TextBlock->SetText(FText::FromString(Text));
			AppliedProps.Add(TEXT("text"));
		}

		double FontSize = 0;
		if (Params->TryGetNumberField(TEXT("font_size"), FontSize))
		{
			FSlateFontInfo FontInfo = TextBlock->GetFont();
			FontInfo.Size = static_cast<int32>(FontSize);
			TextBlock->SetFont(FontInfo);
			AppliedProps.Add(TEXT("font_size"));
		}

		FLinearColor Color;
		if (TryGetColorField(Params, TEXT("color"), Color))
		{
			TextBlock->SetColorAndOpacity(FSlateColor(Color));
			AppliedProps.Add(TEXT("color"));
		}

		FString Justification;
		if (Params->TryGetStringField(TEXT("justification"), Justification))
		{
			if (Justification.Equals(TEXT("Left"), ESearchCase::IgnoreCase))
			{
				TextBlock->SetJustification(ETextJustify::Left);
			}
			else if (Justification.Equals(TEXT("Center"), ESearchCase::IgnoreCase))
			{
				TextBlock->SetJustification(ETextJustify::Center);
			}
			else if (Justification.Equals(TEXT("Right"), ESearchCase::IgnoreCase))
			{
				TextBlock->SetJustification(ETextJustify::Right);
			}
			AppliedProps.Add(TEXT("justification"));
		}
	}
	// Handle Button (look for child TextBlock)
	else if (UButton* Button = Cast<UButton>(TargetWidget))
	{
		FString Text;
		if (Params->TryGetStringField(TEXT("text"), Text))
		{
			// Find child TextBlock in button
			UPanelWidget* Panel = Cast<UPanelWidget>(Button);
			if (Panel)
			{
				for (int32 i = 0; i < Panel->GetChildrenCount(); ++i)
				{
					if (UTextBlock* ChildText = Cast<UTextBlock>(Panel->GetChildAt(i)))
					{
						ChildText->SetText(FText::FromString(Text));
						AppliedProps.Add(TEXT("text"));
						break;
					}
				}
			}
		}

		FLinearColor BGColor;
		if (TryGetColorField(Params, TEXT("background_color"), BGColor))
		{
			Button->SetBackgroundColor(BGColor);
			AppliedProps.Add(TEXT("background_color"));
		}
	}
	else
	{
		return FMCPCommonUtils::CreateErrorResponse(FString::Printf(
			TEXT("Widget '%s' is not a TextBlock or Button (actual: %s)"), *TargetName, *TargetWidget->GetClass()->GetName()));
	}

	WidgetBlueprint->MarkPackageDirty();
	MarkWidgetBlueprintDirty(WidgetBlueprint, Context);

	TSharedPtr<FJsonObject> ResultObj = MakeShared<FJsonObject>();
	ResultObj->SetBoolField(TEXT("success"), true);
	ResultObj->SetStringField(TEXT("widget_name"), TargetName);
	TArray<TSharedPtr<FJsonValue>> AppliedArray;
	for (const FString& Prop : AppliedProps)
	{
		AppliedArray.Add(MakeShared<FJsonValueString>(Prop));
	}
	ResultObj->SetArrayField(TEXT("applied_properties"), AppliedArray);
	return ResultObj;
}


// =============================================================================
// FSetSliderPropertiesAction
// =============================================================================

bool FSetSliderPropertiesAction::Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError)
{
	if (!Params->HasField(TEXT("widget_name")))
	{
		OutError = TEXT("Missing 'widget_name' parameter");
		return false;
	}
	if (!Params->HasField(TEXT("target")))
	{
		OutError = TEXT("Missing 'target' parameter (name of Slider widget)");
		return false;
	}
	return true;
}

TSharedPtr<FJsonObject> FSetSliderPropertiesAction::ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context)
{
	FString BlueprintName = Params->GetStringField(TEXT("widget_name"));
	FString TargetName = Params->GetStringField(TEXT("target"));

	UWidgetBlueprint* WidgetBlueprint = FindWidgetBlueprintByName(BlueprintName);
	if (!WidgetBlueprint)
	{
		return FMCPCommonUtils::CreateErrorResponse(FString::Printf(
			TEXT("Widget Blueprint '%s' not found"), *BlueprintName));
	}

	UWidget* TargetWidget = WidgetBlueprint->WidgetTree->FindWidget(FName(*TargetName));
	if (!TargetWidget)
	{
		return FMCPCommonUtils::CreateErrorResponse(FString::Printf(
			TEXT("Widget '%s' not found in '%s'"), *TargetName, *BlueprintName));
	}

	USlider* Slider = Cast<USlider>(TargetWidget);
	if (!Slider)
	{
		return FMCPCommonUtils::CreateErrorResponse(FString::Printf(
			TEXT("Widget '%s' is not a Slider (actual: %s)"), *TargetName, *TargetWidget->GetClass()->GetName()));
	}

	TArray<FString> AppliedProps;

	double Value = 0;
	if (Params->TryGetNumberField(TEXT("value"), Value))
	{
		Slider->SetValue(static_cast<float>(Value));
		AppliedProps.Add(TEXT("value"));
	}

	double MinValue = 0;
	if (Params->TryGetNumberField(TEXT("min_value"), MinValue))
	{
		Slider->SetMinValue(static_cast<float>(MinValue));
		AppliedProps.Add(TEXT("min_value"));
	}

	double MaxValue = 0;
	if (Params->TryGetNumberField(TEXT("max_value"), MaxValue))
	{
		Slider->SetMaxValue(static_cast<float>(MaxValue));
		AppliedProps.Add(TEXT("max_value"));
	}

	double StepSize = 0;
	if (Params->TryGetNumberField(TEXT("step_size"), StepSize))
	{
		Slider->SetStepSize(static_cast<float>(StepSize));
		AppliedProps.Add(TEXT("step_size"));
	}

	bool bLocked = false;
	if (Params->TryGetBoolField(TEXT("locked"), bLocked))
	{
		Slider->SetLocked(bLocked);
		AppliedProps.Add(TEXT("locked"));
	}

	WidgetBlueprint->MarkPackageDirty();
	MarkWidgetBlueprintDirty(WidgetBlueprint, Context);

	TSharedPtr<FJsonObject> ResultObj = MakeShared<FJsonObject>();
	ResultObj->SetBoolField(TEXT("success"), true);
	ResultObj->SetStringField(TEXT("widget_name"), TargetName);
	TArray<TSharedPtr<FJsonValue>> AppliedArray;
	for (const FString& Prop : AppliedProps)
	{
		AppliedArray.Add(MakeShared<FJsonValueString>(Prop));
	}
	ResultObj->SetArrayField(TEXT("applied_properties"), AppliedArray);
	return ResultObj;
}

// =============================================================================
// FAddGenericWidgetAction
// =============================================================================

UClass* FAddGenericWidgetAction::ResolveWidgetClass(const FString& ClassName) const
{
	if (ClassName.Equals(TEXT("ScrollBox"), ESearchCase::IgnoreCase)) return UScrollBox::StaticClass();
	if (ClassName.Equals(TEXT("WidgetSwitcher"), ESearchCase::IgnoreCase)) return UWidgetSwitcher::StaticClass();
	if (ClassName.Equals(TEXT("BackgroundBlur"), ESearchCase::IgnoreCase)) return UBackgroundBlur::StaticClass();
	if (ClassName.Equals(TEXT("UniformGridPanel"), ESearchCase::IgnoreCase)) return UUniformGridPanel::StaticClass();
	if (ClassName.Equals(TEXT("Spacer"), ESearchCase::IgnoreCase)) return USpacer::StaticClass();
	if (ClassName.Equals(TEXT("RichTextBlock"), ESearchCase::IgnoreCase)) return URichTextBlock::StaticClass();
	if (ClassName.Equals(TEXT("WrapBox"), ESearchCase::IgnoreCase)) return UWrapBox::StaticClass();
	if (ClassName.Equals(TEXT("CircularThrobber"), ESearchCase::IgnoreCase)) return UCircularThrobber::StaticClass();

	TArray<FString> CandidateClassPaths;
	if (ClassName.Equals(TEXT("CommonButtonBase"), ESearchCase::IgnoreCase))
	{
		CandidateClassPaths.Add(TEXT("/Script/CommonUI.CommonButtonBase"));
	}
	else if (ClassName.Equals(TEXT("CommonTextBlock"), ESearchCase::IgnoreCase))
	{
		CandidateClassPaths.Add(TEXT("/Script/CommonUI.CommonTextBlock"));
	}
	else if (ClassName.StartsWith(TEXT("/Script/")))
	{
		CandidateClassPaths.Add(ClassName);
	}
	else if (ClassName.StartsWith(TEXT("/Game/")))
	{
		CandidateClassPaths.Add(ClassName);
		if (!ClassName.EndsWith(TEXT("_C")))
		{
			CandidateClassPaths.Add(ClassName + TEXT("_C"));
			FString PackagePath;
			FString AssetName;
			if (ClassName.Split(TEXT("."), &PackagePath, &AssetName, ESearchCase::CaseSensitive, ESearchDir::FromEnd))
			{
				CandidateClassPaths.Add(PackagePath + TEXT(".") + AssetName + TEXT("_C"));
			}
		}
	}
	else if (UWidgetBlueprint* WidgetBlueprint = FindWidgetBlueprintByName(ClassName))
	{
		if (WidgetBlueprint->GeneratedClass)
		{
			return WidgetBlueprint->GeneratedClass;
		}
	}

	for (const FString& CandidateClassPath : CandidateClassPaths)
	{
		if (UClass* LoadedClass = LoadClass<UWidget>(nullptr, *CandidateClassPath))
		{
			return LoadedClass;
		}
	}

	return nullptr;
}

bool FAddGenericWidgetAction::Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError)
{
	if (!Params->HasField(TEXT("widget_name")))
	{
		OutError = TEXT("Missing 'widget_name' parameter");
		return false;
	}
	if (!Params->HasField(TEXT("component_name")))
	{
		OutError = TEXT("Missing 'component_name' parameter");
		return false;
	}
	if (!Params->HasField(TEXT("component_class")))
	{
		OutError = TEXT("Missing 'component_class' parameter");
		return false;
	}
	FString ClassName = Params->GetStringField(TEXT("component_class"));
	if (!ResolveWidgetClass(ClassName))
	{
		OutError = FString::Printf(TEXT("Unknown component_class: %s. Supported: ScrollBox, WidgetSwitcher, BackgroundBlur, UniformGridPanel, Spacer, RichTextBlock, WrapBox, CircularThrobber, CommonButtonBase, WidgetBlueprint name, /Game/..._C, or /Script/... class path"), *ClassName);
		return false;
	}
	return true;
}

TSharedPtr<FJsonObject> FAddGenericWidgetAction::ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context)
{
	FString BlueprintName = Params->GetStringField(TEXT("widget_name"));
	FString WidgetName = Params->GetStringField(TEXT("component_name"));
	FString ClassName = Params->GetStringField(TEXT("component_class"));

	UWidgetBlueprint* WidgetBlueprint = FindWidgetBlueprintByName(BlueprintName);
	if (!WidgetBlueprint)
	{
		return FMCPCommonUtils::CreateErrorResponse(FString::Printf(
			TEXT("Widget Blueprint '%s' not found in /Game/UI, /Game/Widgets, or /Game"), *BlueprintName));
	}

	UCanvasPanel* RootCanvas = Cast<UCanvasPanel>(WidgetBlueprint->WidgetTree->RootWidget);
	if (!RootCanvas)
	{
		return FMCPCommonUtils::CreateErrorResponse(TEXT("Root widget is not a Canvas Panel"));
	}

	UClass* WidgetClass = ResolveWidgetClass(ClassName);
	if (!WidgetClass)
	{
		return FMCPCommonUtils::CreateErrorResponse(FString::Printf(
			TEXT("Unknown component class: %s"), *ClassName));
	}

	UWidget* NewWidget = WidgetBlueprint->WidgetTree->ConstructWidget<UWidget>(WidgetClass, *WidgetName);
	if (!NewWidget)
	{
		return FMCPCommonUtils::CreateErrorResponse(FString::Printf(
			TEXT("Failed to create %s widget"), *ClassName));
	}

	// Apply type-specific initialization properties
	if (UBackgroundBlur* Blur = Cast<UBackgroundBlur>(NewWidget))
	{
		double BlurStrength = 10.0;
		Params->TryGetNumberField(TEXT("blur_strength"), BlurStrength);
		Blur->SetBlurStrength(static_cast<float>(BlurStrength));
	}

	if (URichTextBlock* RichText = Cast<URichTextBlock>(NewWidget))
	{
		FString Text;
		if (Params->TryGetStringField(TEXT("text"), Text))
		{
			RichText->SetText(FText::FromString(Text));
		}
	}

	if (UScrollBox* ScrollBox = Cast<UScrollBox>(NewWidget))
	{
		FString Orientation;
		if (Params->TryGetStringField(TEXT("orientation"), Orientation))
		{
			if (Orientation.Equals(TEXT("Horizontal"), ESearchCase::IgnoreCase))
			{
				ScrollBox->SetOrientation(Orient_Horizontal);
			}
		}
	}

	if (UWidgetSwitcher* Switcher = Cast<UWidgetSwitcher>(NewWidget))
	{
		int32 ActiveIndex = 0;
		if (Params->TryGetNumberField(TEXT("active_index"), ActiveIndex))
		{
			Switcher->SetActiveWidgetIndex(ActiveIndex);
		}
	}

	// Add to canvas and apply slot properties
	UCanvasPanelSlot* Slot = RootCanvas->AddChildToCanvas(NewWidget);
	ApplyCanvasSlot(Slot, Params);

	// Optional: reparent into a specified parent container
	if (Slot && Slot->Content)
	{
		FString ReparentError;
		if (!TryReparentToParent(WidgetBlueprint, Slot->Content, Params, ReparentError))
		{
			return FMCPCommonUtils::CreateErrorResponse(ReparentError);
		}
	}

	WidgetBlueprint->MarkPackageDirty();
	MarkWidgetBlueprintDirty(WidgetBlueprint, Context);

	TSharedPtr<FJsonObject> ResultObj = MakeShared<FJsonObject>();
	ResultObj->SetBoolField(TEXT("success"), true);
	ResultObj->SetStringField(TEXT("widget_name"), WidgetName);
	ResultObj->SetStringField(TEXT("widget_class"), ClassName);
	return ResultObj;
}

// =============================================================================
// Helper: Resolve a UClass by short name or full path
// =============================================================================
static UClass* ResolveClassByName(const FString& ClassName)
{
	// Try full path first (e.g. "/Script/MyModule.UMyViewModel")
	UClass* FoundClass = FindFirstObject<UClass>(*ClassName, EFindFirstObjectOptions::EnsureIfAmbiguous);
	if (FoundClass)
	{
		return FoundClass;
	}

	// Try with common prefixes
	TArray<FString> Candidates = {
		FString::Printf(TEXT("U%s"), *ClassName),   // UMyViewModel
		FString::Printf(TEXT("%s_C"), *ClassName),   // Blueprint generated class
	};

	for (const FString& Candidate : Candidates)
	{
		FoundClass = FindFirstObject<UClass>(*Candidate, EFindFirstObjectOptions::EnsureIfAmbiguous);
		if (FoundClass)
		{
			return FoundClass;
		}
	}

	// Search via Asset Registry for Blueprint-based ViewModels
	FAssetRegistryModule& AssetRegistryModule = FModuleManager::LoadModuleChecked<FAssetRegistryModule>("AssetRegistry");
	IAssetRegistry& AssetRegistry = AssetRegistryModule.Get();

	TArray<FAssetData> AssetList;
	AssetRegistry.GetAssetsByClass(UBlueprint::StaticClass()->GetClassPathName(), AssetList, true);

	for (const FAssetData& AssetData : AssetList)
	{
		if (AssetData.AssetName.ToString() == ClassName)
		{
			UBlueprint* BP = Cast<UBlueprint>(AssetData.GetAsset());
			if (BP && BP->GeneratedClass)
			{
				return BP->GeneratedClass;
			}
		}
	}

	return nullptr;
}

// =============================================================================
// FMVVMAddViewModelAction
// =============================================================================

bool FMVVMAddViewModelAction::Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError)
{
	if (!Params->HasField(TEXT("widget_name")))
	{
		OutError = TEXT("Missing 'widget_name' parameter");
		return false;
	}
	if (!Params->HasField(TEXT("viewmodel_class")))
	{
		OutError = TEXT("Missing 'viewmodel_class' parameter");
		return false;
	}
	return true;
}

TSharedPtr<FJsonObject> FMVVMAddViewModelAction::ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context)
{
	FString BlueprintName = Params->GetStringField(TEXT("widget_name"));
	FString ViewModelClassName = Params->GetStringField(TEXT("viewmodel_class"));
	FString ViewModelName = Params->HasField(TEXT("viewmodel_name"))
		? Params->GetStringField(TEXT("viewmodel_name"))
		: ViewModelClassName;
	FString CreationTypeStr = Params->HasField(TEXT("creation_type"))
		? Params->GetStringField(TEXT("creation_type"))
		: TEXT("CreateInstance");

	// Find Widget Blueprint
	UWidgetBlueprint* WidgetBlueprint = FindWidgetBlueprintByName(BlueprintName);
	if (!WidgetBlueprint)
	{
		return FMCPCommonUtils::CreateErrorResponse(FString::Printf(
			TEXT("Widget Blueprint '%s' not found"), *BlueprintName));
	}

	// Resolve ViewModel class
	UClass* VMClass = ResolveClassByName(ViewModelClassName);
	if (!VMClass)
	{
		return FMCPCommonUtils::CreateErrorResponse(FString::Printf(
			TEXT("ViewModel class '%s' not found. Ensure it is compiled and loaded."), *ViewModelClassName));
	}

	// Verify it implements INotifyFieldValueChanged
	if (!VMClass->ImplementsInterface(UNotifyFieldValueChanged::StaticClass()))
	{
		return FMCPCommonUtils::CreateErrorResponse(FString::Printf(
			TEXT("Class '%s' does not implement INotifyFieldValueChanged. "
			     "It must derive from UMVVMViewModelBase or implement the interface."),
			*VMClass->GetName()));
	}

	// Get or create the MVVM extension on the Widget Blueprint
	UMVVMWidgetBlueprintExtension_View* MVVMExt =
		UWidgetBlueprintExtension::RequestExtension<UMVVMWidgetBlueprintExtension_View>(WidgetBlueprint);
	if (!MVVMExt)
	{
		return FMCPCommonUtils::CreateErrorResponse(TEXT("Failed to create MVVM extension on Widget Blueprint"));
	}

	// Ensure BlueprintView exists
	UMVVMBlueprintView* BPView = MVVMExt->GetBlueprintView();
	if (!BPView)
	{
		MVVMExt->CreateBlueprintViewInstance();
		BPView = MVVMExt->GetBlueprintView();
	}
	if (!BPView)
	{
		return FMCPCommonUtils::CreateErrorResponse(TEXT("Failed to create MVVM BlueprintView"));
	}

	// Check if ViewModel already exists with this name
	FName VMFName(*ViewModelName);
	const FMVVMBlueprintViewModelContext* ExistingVM = BPView->FindViewModel(VMFName);
	if (ExistingVM)
	{
		return FMCPCommonUtils::CreateErrorResponse(FString::Printf(
			TEXT("ViewModel '%s' already exists on this Widget Blueprint"), *ViewModelName));
	}

	// Create ViewModel context
	FMVVMBlueprintViewModelContext VMContext(VMClass, VMFName);

	// Set creation type
	if (CreationTypeStr.Equals(TEXT("Manual"), ESearchCase::IgnoreCase))
	{
		VMContext.CreationType = EMVVMBlueprintViewModelContextCreationType::Manual;
	}
	else if (CreationTypeStr.Equals(TEXT("CreateInstance"), ESearchCase::IgnoreCase))
	{
		VMContext.CreationType = EMVVMBlueprintViewModelContextCreationType::CreateInstance;
	}
	else if (CreationTypeStr.Equals(TEXT("GlobalViewModelCollection"), ESearchCase::IgnoreCase))
	{
		VMContext.CreationType = EMVVMBlueprintViewModelContextCreationType::GlobalViewModelCollection;
	}
	else if (CreationTypeStr.Equals(TEXT("PropertyPath"), ESearchCase::IgnoreCase))
	{
		VMContext.CreationType = EMVVMBlueprintViewModelContextCreationType::PropertyPath;
	}
	else if (CreationTypeStr.Equals(TEXT("Resolver"), ESearchCase::IgnoreCase))
	{
		VMContext.CreationType = EMVVMBlueprintViewModelContextCreationType::Resolver;
	}

	// Optional: getter/setter generation
	if (Params->HasField(TEXT("create_setter")))
	{
		VMContext.bCreateSetterFunction = Params->GetBoolField(TEXT("create_setter"));
	}
	if (Params->HasField(TEXT("create_getter")))
	{
		VMContext.bCreateGetterFunction = Params->GetBoolField(TEXT("create_getter"));
	}

	// Add ViewModel
	BPView->AddViewModel(VMContext);

	// Notify MVVM system
	BPView->OnBindingsUpdated.Broadcast();

	// Mark modified and compile
	FBlueprintEditorUtils::MarkBlueprintAsStructurallyModified(WidgetBlueprint);
	WidgetBlueprint->MarkPackageDirty();
	MarkWidgetBlueprintDirty(WidgetBlueprint, Context);

	TSharedPtr<FJsonObject> ResultObj = MakeShared<FJsonObject>();
	ResultObj->SetBoolField(TEXT("success"), true);
	ResultObj->SetStringField(TEXT("viewmodel_name"), ViewModelName);
	ResultObj->SetStringField(TEXT("viewmodel_class"), VMClass->GetName());
	ResultObj->SetStringField(TEXT("viewmodel_id"), VMContext.GetViewModelId().ToString());
	ResultObj->SetStringField(TEXT("creation_type"), CreationTypeStr);
	return ResultObj;
}

// =============================================================================
// FMVVMAddBindingAction
// =============================================================================

bool FMVVMAddBindingAction::Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError)
{
	if (!Params->HasField(TEXT("widget_name")))
	{
		OutError = TEXT("Missing 'widget_name' parameter");
		return false;
	}
	if (!Params->HasField(TEXT("viewmodel_name")))
	{
		OutError = TEXT("Missing 'viewmodel_name' parameter");
		return false;
	}
	if (!Params->HasField(TEXT("source_property")))
	{
		OutError = TEXT("Missing 'source_property' parameter");
		return false;
	}
	if (!Params->HasField(TEXT("destination_widget")))
	{
		OutError = TEXT("Missing 'destination_widget' parameter");
		return false;
	}
	if (!Params->HasField(TEXT("destination_property")))
	{
		OutError = TEXT("Missing 'destination_property' parameter");
		return false;
	}
	return true;
}

TSharedPtr<FJsonObject> FMVVMAddBindingAction::ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context)
{
	FString BlueprintName = Params->GetStringField(TEXT("widget_name"));
	FString ViewModelName = Params->GetStringField(TEXT("viewmodel_name"));
	FString SourcePropName = Params->GetStringField(TEXT("source_property"));
	FString DestWidgetName = Params->GetStringField(TEXT("destination_widget"));
	FString DestPropName = Params->GetStringField(TEXT("destination_property"));
	FString BindingModeStr = Params->HasField(TEXT("binding_mode"))
		? Params->GetStringField(TEXT("binding_mode"))
		: TEXT("OneWayToDestination");
	FString ExecutionModeStr = Params->HasField(TEXT("execution_mode"))
		? Params->GetStringField(TEXT("execution_mode"))
		: TEXT("");

	// Find Widget Blueprint
	UWidgetBlueprint* WidgetBlueprint = FindWidgetBlueprintByName(BlueprintName);
	if (!WidgetBlueprint)
	{
		return FMCPCommonUtils::CreateErrorResponse(FString::Printf(
			TEXT("Widget Blueprint '%s' not found"), *BlueprintName));
	}

	// Get MVVM extension
	UMVVMWidgetBlueprintExtension_View* MVVMExt =
		UWidgetBlueprintExtension::GetExtension<UMVVMWidgetBlueprintExtension_View>(WidgetBlueprint);
	if (!MVVMExt)
	{
		return FMCPCommonUtils::CreateErrorResponse(
			TEXT("No MVVM extension found on Widget Blueprint. Use widget.mvvm_add_viewmodel first."));
	}

	UMVVMBlueprintView* BPView = MVVMExt->GetBlueprintView();
	if (!BPView)
	{
		return FMCPCommonUtils::CreateErrorResponse(TEXT("No MVVM BlueprintView found."));
	}

	// Find the ViewModel context
	FName VMFName(*ViewModelName);
	const FMVVMBlueprintViewModelContext* VMContext = BPView->FindViewModel(VMFName);
	if (!VMContext)
	{
		return FMCPCommonUtils::CreateErrorResponse(FString::Printf(
			TEXT("ViewModel '%s' not found on this Widget Blueprint"), *ViewModelName));
	}

	UClass* VMClass = VMContext->GetViewModelClass();
	if (!VMClass)
	{
		return FMCPCommonUtils::CreateErrorResponse(TEXT("ViewModel class is null"));
	}

	// Resolve source field on ViewModel (property or FieldNotify function)
	UE::MVVM::FMVVMConstFieldVariant SourceFieldVariant;
	FProperty* SourceProp = VMClass->FindPropertyByName(FName(*SourcePropName));
	if (SourceProp)
	{
		SourceFieldVariant = UE::MVVM::FMVVMConstFieldVariant(SourceProp);
	}
	else
	{
		// Fall back to UFunction (FieldNotify functions like GetHealthPercent)
		UFunction* SourceFunc = VMClass->FindFunctionByName(FName(*SourcePropName));
		if (SourceFunc)
		{
			SourceFieldVariant = UE::MVVM::FMVVMConstFieldVariant(SourceFunc);
		}
		else
		{
			return FMCPCommonUtils::CreateErrorResponse(FString::Printf(
				TEXT("Property or function '%s' not found on ViewModel class '%s'"), *SourcePropName, *VMClass->GetName()));
		}
	}

	// Resolve destination widget in the tree
	UWidget* DestWidget = WidgetBlueprint->WidgetTree
		? WidgetBlueprint->WidgetTree->FindWidget(FName(*DestWidgetName))
		: nullptr;
	if (!DestWidget)
	{
		return FMCPCommonUtils::CreateErrorResponse(FString::Printf(
			TEXT("Widget '%s' not found in Widget Tree"), *DestWidgetName));
	}

	// Resolve destination field on the widget class (property or function)
	UE::MVVM::FMVVMConstFieldVariant DestFieldVariant;
	FProperty* DestProp = DestWidget->GetClass()->FindPropertyByName(FName(*DestPropName));
	if (DestProp)
	{
		DestFieldVariant = UE::MVVM::FMVVMConstFieldVariant(DestProp);
	}
	else
	{
		UFunction* DestFunc = DestWidget->GetClass()->FindFunctionByName(FName(*DestPropName));
		if (DestFunc)
		{
			DestFieldVariant = UE::MVVM::FMVVMConstFieldVariant(DestFunc);
		}
		else
		{
			return FMCPCommonUtils::CreateErrorResponse(FString::Printf(
				TEXT("Property or function '%s' not found on widget '%s' (class: %s)"),
				*DestPropName, *DestWidgetName, *DestWidget->GetClass()->GetName()));
		}
	}

	// Create binding
	FMVVMBlueprintViewBinding& NewBinding = BPView->AddDefaultBinding();

	// Configure source path (ViewModel side)
	NewBinding.SourcePath.SetViewModelId(VMContext->GetViewModelId());
	NewBinding.SourcePath.SetPropertyPath(WidgetBlueprint, SourceFieldVariant);

	// Configure destination path (Widget side)
	NewBinding.DestinationPath.SetWidgetName(FName(*DestWidgetName));
	NewBinding.DestinationPath.SetPropertyPath(WidgetBlueprint, DestFieldVariant);

	// Parse binding mode
	if (BindingModeStr.Equals(TEXT("OneTimeToDestination"), ESearchCase::IgnoreCase))
	{
		NewBinding.BindingType = EMVVMBindingMode::OneTimeToDestination;
	}
	else if (BindingModeStr.Equals(TEXT("OneWayToDestination"), ESearchCase::IgnoreCase))
	{
		NewBinding.BindingType = EMVVMBindingMode::OneWayToDestination;
	}
	else if (BindingModeStr.Equals(TEXT("TwoWay"), ESearchCase::IgnoreCase))
	{
		NewBinding.BindingType = EMVVMBindingMode::TwoWay;
	}
	else if (BindingModeStr.Equals(TEXT("OneTimeToSource"), ESearchCase::IgnoreCase))
	{
		NewBinding.BindingType = EMVVMBindingMode::OneTimeToSource;
	}
	else if (BindingModeStr.Equals(TEXT("OneWayToSource"), ESearchCase::IgnoreCase))
	{
		NewBinding.BindingType = EMVVMBindingMode::OneWayToSource;
	}

	// Parse execution mode (optional)
	if (!ExecutionModeStr.IsEmpty())
	{
		NewBinding.bOverrideExecutionMode = true;
		if (ExecutionModeStr.Equals(TEXT("Immediate"), ESearchCase::IgnoreCase))
		{
			NewBinding.OverrideExecutionMode = EMVVMExecutionMode::Immediate;
		}
		else if (ExecutionModeStr.Equals(TEXT("Delayed"), ESearchCase::IgnoreCase))
		{
			NewBinding.OverrideExecutionMode = EMVVMExecutionMode::Delayed;
		}
		else if (ExecutionModeStr.Equals(TEXT("Tick"), ESearchCase::IgnoreCase))
		{
			NewBinding.OverrideExecutionMode = EMVVMExecutionMode::Tick;
		}
		else if (ExecutionModeStr.Equals(TEXT("Auto"), ESearchCase::IgnoreCase))
		{
			NewBinding.OverrideExecutionMode = EMVVMExecutionMode::DelayedWhenSharedElseImmediate;
		}
	}

	// Notify MVVM system that bindings changed (critical for compilation stability)
	BPView->OnBindingsUpdated.Broadcast();

	// Mark modified
	FBlueprintEditorUtils::MarkBlueprintAsStructurallyModified(WidgetBlueprint);
	WidgetBlueprint->MarkPackageDirty();
	MarkWidgetBlueprintDirty(WidgetBlueprint, Context);

	TSharedPtr<FJsonObject> ResultObj = MakeShared<FJsonObject>();
	ResultObj->SetBoolField(TEXT("success"), true);
	ResultObj->SetStringField(TEXT("binding_id"), NewBinding.BindingId.ToString());
	ResultObj->SetStringField(TEXT("source"), FString::Printf(TEXT("%s.%s"), *ViewModelName, *SourcePropName));
	ResultObj->SetStringField(TEXT("destination"), FString::Printf(TEXT("%s.%s"), *DestWidgetName, *DestPropName));
	ResultObj->SetStringField(TEXT("binding_mode"), BindingModeStr);
	if (!ExecutionModeStr.IsEmpty())
	{
		ResultObj->SetStringField(TEXT("execution_mode"), ExecutionModeStr);
	}
	return ResultObj;
}


// =============================================================================
// FMVVMAddEventAction
// =============================================================================

bool FMVVMAddEventAction::Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError)
{
	if (!Params->HasField(TEXT("widget_name")))
	{
		OutError = TEXT("Missing 'widget_name' parameter");
		return false;
	}
	if (!Params->HasField(TEXT("viewmodel_name")))
	{
		OutError = TEXT("Missing 'viewmodel_name' parameter");
		return false;
	}
	if (!Params->HasField(TEXT("event_widget")))
	{
		OutError = TEXT("Missing 'event_widget' parameter");
		return false;
	}
	if (!Params->HasField(TEXT("event_property")))
	{
		OutError = TEXT("Missing 'event_property' parameter");
		return false;
	}
	if (!Params->HasField(TEXT("destination_function")))
	{
		OutError = TEXT("Missing 'destination_function' parameter");
		return false;
	}
	return true;
}

TSharedPtr<FJsonObject> FMVVMAddEventAction::ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context)
{
	const FString BlueprintName = Params->GetStringField(TEXT("widget_name"));
	const FString ViewModelName = Params->GetStringField(TEXT("viewmodel_name"));
	const FString EventWidgetName = Params->GetStringField(TEXT("event_widget"));
	FString EventPropertyName = Params->GetStringField(TEXT("event_property"));
	const FString DestinationFunctionName = Params->GetStringField(TEXT("destination_function"));

	UWidgetBlueprint* WidgetBlueprint = FindWidgetBlueprintByName(BlueprintName);
	if (!WidgetBlueprint)
	{
		return FMCPCommonUtils::CreateErrorResponse(FString::Printf(TEXT("Widget Blueprint '%s' not found"), *BlueprintName));
	}

	UMVVMWidgetBlueprintExtension_View* MVVMExt = UWidgetBlueprintExtension::GetExtension<UMVVMWidgetBlueprintExtension_View>(WidgetBlueprint);
	if (!MVVMExt)
	{
		return FMCPCommonUtils::CreateErrorResponse(TEXT("No MVVM extension found on Widget Blueprint. Use mvvm_add_viewmodel first."));
	}

	UMVVMBlueprintView* BPView = MVVMExt->GetBlueprintView();
	if (!BPView)
	{
		return FMCPCommonUtils::CreateErrorResponse(TEXT("No MVVM BlueprintView found."));
	}

	const FMVVMBlueprintViewModelContext* VMContext = BPView->FindViewModel(FName(*ViewModelName));
	if (!VMContext)
	{
		return FMCPCommonUtils::CreateErrorResponse(FString::Printf(TEXT("ViewModel '%s' not found on this Widget Blueprint"), *ViewModelName));
	}

	UClass* VMClass = VMContext->GetViewModelClass();
	if (!VMClass)
	{
		return FMCPCommonUtils::CreateErrorResponse(TEXT("ViewModel class is null"));
	}

	UWidget* EventWidget = WidgetBlueprint->WidgetTree ? WidgetBlueprint->WidgetTree->FindWidget(FName(*EventWidgetName)) : nullptr;
	if (!EventWidget)
	{
		return FMCPCommonUtils::CreateErrorResponse(FString::Printf(TEXT("Widget '%s' not found in Widget Tree"), *EventWidgetName));
	}

	FProperty* EventProperty = EventWidget->GetClass()->FindPropertyByName(FName(*EventPropertyName));
	if (!EventProperty && EventPropertyName.Equals(TEXT("OnClicked"), ESearchCase::IgnoreCase))
	{
		EventPropertyName = TEXT("OnButtonBaseClicked");
		EventProperty = EventWidget->GetClass()->FindPropertyByName(FName(*EventPropertyName));
		if (!EventProperty)
		{
			EventPropertyName = TEXT("OnClicked");
			EventProperty = EventWidget->GetClass()->FindPropertyByName(FName(*EventPropertyName));
		}
	}
	if (!EventProperty)
	{
		return FMCPCommonUtils::CreateErrorResponse(FString::Printf(TEXT("Event property '%s' not found on widget '%s' (class: %s)"), *EventPropertyName, *EventWidgetName, *EventWidget->GetClass()->GetName()));
	}
	if (!CastField<FMulticastDelegateProperty>(EventProperty))
	{
		return FMCPCommonUtils::CreateErrorResponse(FString::Printf(TEXT("Property '%s' on widget '%s' is not a multicast delegate event"), *EventPropertyName, *EventWidgetName));
	}

	UFunction* DestinationFunction = VMClass->FindFunctionByName(FName(*DestinationFunctionName));
	if (!DestinationFunction)
	{
		return FMCPCommonUtils::CreateErrorResponse(FString::Printf(TEXT("Function '%s' not found on ViewModel class '%s'"), *DestinationFunctionName, *VMClass->GetName()));
	}

	FMVVMBlueprintPropertyPath EventPath;
	EventPath.SetWidgetName(FName(*EventWidgetName));
	EventPath.SetPropertyPath(WidgetBlueprint, UE::MVVM::FMVVMConstFieldVariant(EventProperty));

	if (!UMVVMBlueprintViewEvent::Supports(WidgetBlueprint, EventPath))
	{
		return FMCPCommonUtils::CreateErrorResponse(FString::Printf(TEXT("MVVM event path '%s.%s' is not supported. Check Project Settings > MVVM > Allow Binding Event."), *EventWidgetName, *EventPropertyName));
	}

	FMVVMBlueprintPropertyPath DestinationPath;
	DestinationPath.SetViewModelId(VMContext->GetViewModelId());
	DestinationPath.SetPropertyPath(WidgetBlueprint, UE::MVVM::FMVVMConstFieldVariant(DestinationFunction));

	TArray<UMVVMBlueprintViewEvent*> ExistingMatches;
	for (UMVVMBlueprintViewEvent* ExistingEvent : BPView->GetEvents())
	{
		if (!ExistingEvent)
		{
			continue;
		}
		const FMVVMBlueprintPropertyPath& ExistingEventPath = ExistingEvent->GetEventPath();
		const bool bSameWidget = ExistingEventPath.GetWidgetName() == FName(*EventWidgetName);
		const bool bSameEvent = ExistingEventPath.GetFieldPaths().Num() > 0 && ExistingEventPath.GetFieldPaths().Last().GetRawFieldName() == FName(*EventPropertyName);
		if (bSameWidget && bSameEvent)
		{
			ExistingMatches.Add(ExistingEvent);
		}
	}
	for (UMVVMBlueprintViewEvent* ExistingEvent : ExistingMatches)
	{
		BPView->RemoveEvent(ExistingEvent);
	}

	UMVVMBlueprintViewEvent* NewEvent = BPView->AddDefaultEvent();
	if (!NewEvent)
	{
		return FMCPCommonUtils::CreateErrorResponse(TEXT("Failed to create MVVM event binding"));
	}

	NewEvent->SetEventPath(EventPath);
	NewEvent->SetDestinationPath(DestinationPath);
	NewEvent->bEnabled = true;
	NewEvent->bCompile = true;

	BPView->OnEventsUpdated.Broadcast();
	FBlueprintEditorUtils::MarkBlueprintAsStructurallyModified(WidgetBlueprint);
	WidgetBlueprint->MarkPackageDirty();
	MarkWidgetBlueprintDirty(WidgetBlueprint, Context);

	TSharedPtr<FJsonObject> ResultObj = MakeShared<FJsonObject>();
	ResultObj->SetBoolField(TEXT("success"), true);
	ResultObj->SetStringField(TEXT("event"), FString::Printf(TEXT("%s.%s"), *EventWidgetName, *EventPropertyName));
	ResultObj->SetStringField(TEXT("destination"), FString::Printf(TEXT("%s.%s"), *ViewModelName, *DestinationFunctionName));
	ResultObj->SetStringField(TEXT("event_display_name"), NewEvent->GetDisplayName(false).ToString());
	ResultObj->SetStringField(TEXT("wrapper_graph"), NewEvent->GetWrapperGraphName().ToString());
	return ResultObj;
}

// =============================================================================
// FMVVMRemoveEventAction
// =============================================================================

bool FMVVMRemoveEventAction::Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError)
{
	if (!Params->HasField(TEXT("widget_name")))
	{
		OutError = TEXT("Missing 'widget_name' parameter");
		return false;
	}
	if (!Params->HasField(TEXT("event_widget")))
	{
		OutError = TEXT("Missing 'event_widget' parameter");
		return false;
	}
	return true;
}

TSharedPtr<FJsonObject> FMVVMRemoveEventAction::ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context)
{
	const FString BlueprintName = Params->GetStringField(TEXT("widget_name"));
	const FString EventWidgetName = Params->GetStringField(TEXT("event_widget"));
	FString EventPropertyName;
	const bool bHasPropertyFilter = Params->TryGetStringField(TEXT("event_property"), EventPropertyName);

	UWidgetBlueprint* WidgetBlueprint = FindWidgetBlueprintByName(BlueprintName);
	if (!WidgetBlueprint)
	{
		return FMCPCommonUtils::CreateErrorResponse(FString::Printf(TEXT("Widget Blueprint '%s' not found"), *BlueprintName));
	}

	UMVVMWidgetBlueprintExtension_View* MVVMExt = UWidgetBlueprintExtension::GetExtension<UMVVMWidgetBlueprintExtension_View>(WidgetBlueprint);
	if (!MVVMExt)
	{
		return FMCPCommonUtils::CreateErrorResponse(TEXT("No MVVM extension found on Widget Blueprint."));
	}

	UMVVMBlueprintView* BPView = MVVMExt->GetBlueprintView();
	if (!BPView)
	{
		return FMCPCommonUtils::CreateErrorResponse(TEXT("No MVVM BlueprintView found."));
	}

	TArray<UMVVMBlueprintViewEvent*> ToRemove;
	for (UMVVMBlueprintViewEvent* ExistingEvent : BPView->GetEvents())
	{
		if (!ExistingEvent)
		{
			continue;
		}
		const FMVVMBlueprintPropertyPath& ExistingEventPath = ExistingEvent->GetEventPath();
		const bool bSameWidget = ExistingEventPath.GetWidgetName() == FName(*EventWidgetName);
		bool bSameProperty = true;
		if (bHasPropertyFilter)
		{
			bSameProperty = ExistingEventPath.GetFieldPaths().Num() > 0
				&& ExistingEventPath.GetFieldPaths().Last().GetRawFieldName() == FName(*EventPropertyName);
		}
		if (bSameWidget && bSameProperty)
		{
			ToRemove.Add(ExistingEvent);
		}
	}

	const int32 RemovedCount = ToRemove.Num();
	for (UMVVMBlueprintViewEvent* Ev : ToRemove)
	{
		BPView->RemoveEvent(Ev);
	}

	if (RemovedCount > 0)
	{
		BPView->OnEventsUpdated.Broadcast();
		FBlueprintEditorUtils::MarkBlueprintAsStructurallyModified(WidgetBlueprint);
		WidgetBlueprint->MarkPackageDirty();
		MarkWidgetBlueprintDirty(WidgetBlueprint, Context);
	}

	TSharedPtr<FJsonObject> ResultObj = MakeShared<FJsonObject>();
	ResultObj->SetBoolField(TEXT("success"), true);
	ResultObj->SetNumberField(TEXT("removed_count"), RemovedCount);
	ResultObj->SetStringField(TEXT("event_widget"), EventWidgetName);
	if (bHasPropertyFilter)
	{
		ResultObj->SetStringField(TEXT("event_property"), EventPropertyName);
	}
	return ResultObj;
}

// =============================================================================
// FMVVMGetBindingsAction
// =============================================================================


bool FMVVMGetBindingsAction::Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError)
{
	if (!Params->HasField(TEXT("widget_name")))
	{
		OutError = TEXT("Missing 'widget_name' parameter");
		return false;
	}
	return true;
}

TSharedPtr<FJsonObject> FMVVMGetBindingsAction::ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context)
{
	FString BlueprintName = Params->GetStringField(TEXT("widget_name"));

	// Find Widget Blueprint
	UWidgetBlueprint* WidgetBlueprint = FindWidgetBlueprintByName(BlueprintName);
	if (!WidgetBlueprint)
	{
		return FMCPCommonUtils::CreateErrorResponse(FString::Printf(
			TEXT("Widget Blueprint '%s' not found"), *BlueprintName));
	}

	// Get MVVM extension
	UMVVMWidgetBlueprintExtension_View* MVVMExt =
		UWidgetBlueprintExtension::GetExtension<UMVVMWidgetBlueprintExtension_View>(WidgetBlueprint);

	TSharedPtr<FJsonObject> ResultObj = MakeShared<FJsonObject>();
	ResultObj->SetBoolField(TEXT("success"), true);

	if (!MVVMExt)
	{
		ResultObj->SetBoolField(TEXT("has_mvvm"), false);
		ResultObj->SetArrayField(TEXT("viewmodels"), TArray<TSharedPtr<FJsonValue>>());
		ResultObj->SetArrayField(TEXT("bindings"), TArray<TSharedPtr<FJsonValue>>());
		return ResultObj;
	}

	UMVVMBlueprintView* BPView = MVVMExt->GetBlueprintView();
	if (!BPView)
	{
		ResultObj->SetBoolField(TEXT("has_mvvm"), false);
		ResultObj->SetArrayField(TEXT("viewmodels"), TArray<TSharedPtr<FJsonValue>>());
		ResultObj->SetArrayField(TEXT("bindings"), TArray<TSharedPtr<FJsonValue>>());
		return ResultObj;
	}

	ResultObj->SetBoolField(TEXT("has_mvvm"), true);

	// Serialize ViewModels
	TArray<TSharedPtr<FJsonValue>> VMArray;
	TArrayView<const FMVVMBlueprintViewModelContext> ViewModels = BPView->GetViewModels();
	for (const FMVVMBlueprintViewModelContext& VM : ViewModels)
	{
		TSharedPtr<FJsonObject> VMObj = MakeShared<FJsonObject>();
		VMObj->SetStringField(TEXT("id"), VM.GetViewModelId().ToString());
		VMObj->SetStringField(TEXT("name"), VM.GetViewModelName().ToString());
		VMObj->SetStringField(TEXT("class"), VM.GetViewModelClass() ? VM.GetViewModelClass()->GetName() : TEXT("null"));

		FString CreationStr;
		switch (VM.CreationType)
		{
		case EMVVMBlueprintViewModelContextCreationType::Manual:
			CreationStr = TEXT("Manual"); break;
		case EMVVMBlueprintViewModelContextCreationType::CreateInstance:
			CreationStr = TEXT("CreateInstance"); break;
		case EMVVMBlueprintViewModelContextCreationType::GlobalViewModelCollection:
			CreationStr = TEXT("GlobalViewModelCollection"); break;
		case EMVVMBlueprintViewModelContextCreationType::PropertyPath:
			CreationStr = TEXT("PropertyPath"); break;
		case EMVVMBlueprintViewModelContextCreationType::Resolver:
			CreationStr = TEXT("Resolver"); break;
		default:
			CreationStr = TEXT("Unknown"); break;
		}
		VMObj->SetStringField(TEXT("creation_type"), CreationStr);
		VMObj->SetBoolField(TEXT("create_setter"), VM.bCreateSetterFunction);
		VMObj->SetBoolField(TEXT("create_getter"), VM.bCreateGetterFunction);
		VMObj->SetBoolField(TEXT("optional"), VM.bOptional);

		VMArray.Add(MakeShared<FJsonValueObject>(VMObj));
	}
	ResultObj->SetArrayField(TEXT("viewmodels"), VMArray);

	// Serialize Bindings
	TArray<TSharedPtr<FJsonValue>> BindingArray;
	TArrayView<FMVVMBlueprintViewBinding> Bindings = BPView->GetBindings();
	for (const FMVVMBlueprintViewBinding& Binding : Bindings)
	{
		TSharedPtr<FJsonObject> BindObj = MakeShared<FJsonObject>();
		BindObj->SetStringField(TEXT("binding_id"), Binding.BindingId.ToString());
		BindObj->SetStringField(TEXT("display_name"), Binding.GetDisplayNameString(WidgetBlueprint));
		BindObj->SetBoolField(TEXT("enabled"), Binding.bEnabled);
		BindObj->SetBoolField(TEXT("compile"), Binding.bCompile);

		// Binding mode
		FString ModeStr;
		switch (Binding.BindingType)
		{
		case EMVVMBindingMode::OneTimeToDestination:
			ModeStr = TEXT("OneTimeToDestination"); break;
		case EMVVMBindingMode::OneWayToDestination:
			ModeStr = TEXT("OneWayToDestination"); break;
		case EMVVMBindingMode::TwoWay:
			ModeStr = TEXT("TwoWay"); break;
		case EMVVMBindingMode::OneTimeToSource:
			ModeStr = TEXT("OneTimeToSource"); break;
		case EMVVMBindingMode::OneWayToSource:
			ModeStr = TEXT("OneWayToSource"); break;
		default:
			ModeStr = TEXT("Unknown"); break;
		}
		BindObj->SetStringField(TEXT("binding_mode"), ModeStr);

		// Execution mode
		if (Binding.bOverrideExecutionMode)
		{
			FString ExecStr;
			switch (Binding.OverrideExecutionMode)
			{
			case EMVVMExecutionMode::Immediate:
				ExecStr = TEXT("Immediate"); break;
			case EMVVMExecutionMode::Delayed:
				ExecStr = TEXT("Delayed"); break;
			case EMVVMExecutionMode::Tick:
				ExecStr = TEXT("Tick"); break;
			case EMVVMExecutionMode::DelayedWhenSharedElseImmediate:
				ExecStr = TEXT("Auto"); break;
			default:
				ExecStr = TEXT("Unknown"); break;
			}
			BindObj->SetStringField(TEXT("execution_mode"), ExecStr);
		}

		BindingArray.Add(MakeShared<FJsonValueObject>(BindObj));
	}
	ResultObj->SetArrayField(TEXT("bindings"), BindingArray);

	return ResultObj;
}

// =============================================================================
// FMVVMRemoveBindingAction
// =============================================================================

bool FMVVMRemoveBindingAction::Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError)
{
	if (!Params->HasField(TEXT("widget_name")))
	{
		OutError = TEXT("Missing 'widget_name' parameter");
		return false;
	}
	if (!Params->HasField(TEXT("binding_id")))
	{
		OutError = TEXT("Missing 'binding_id' parameter");
		return false;
	}
	return true;
}

TSharedPtr<FJsonObject> FMVVMRemoveBindingAction::ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context)
{
	FString BlueprintName = Params->GetStringField(TEXT("widget_name"));
	FString BindingIdStr = Params->GetStringField(TEXT("binding_id"));

	// Find Widget Blueprint
	UWidgetBlueprint* WidgetBlueprint = FindWidgetBlueprintByName(BlueprintName);
	if (!WidgetBlueprint)
	{
		return FMCPCommonUtils::CreateErrorResponse(FString::Printf(
			TEXT("Widget Blueprint '%s' not found"), *BlueprintName));
	}

	// Get MVVM extension
	UMVVMWidgetBlueprintExtension_View* MVVMExt =
		UWidgetBlueprintExtension::GetExtension<UMVVMWidgetBlueprintExtension_View>(WidgetBlueprint);
	if (!MVVMExt)
	{
		return FMCPCommonUtils::CreateErrorResponse(TEXT("No MVVM extension found on Widget Blueprint."));
	}

	UMVVMBlueprintView* BPView = MVVMExt->GetBlueprintView();
	if (!BPView)
	{
		return FMCPCommonUtils::CreateErrorResponse(TEXT("No MVVM BlueprintView found."));
	}

	// Find and remove binding by ID
	FGuid TargetGuid;
	FGuid::Parse(BindingIdStr, TargetGuid);

	TArrayView<FMVVMBlueprintViewBinding> Bindings = BPView->GetBindings();
	int32 FoundIndex = INDEX_NONE;
	for (int32 i = 0; i < Bindings.Num(); ++i)
	{
		if (Bindings[i].BindingId == TargetGuid)
		{
			FoundIndex = i;
			break;
		}
	}

	if (FoundIndex == INDEX_NONE)
	{
		return FMCPCommonUtils::CreateErrorResponse(FString::Printf(
			TEXT("Binding with ID '%s' not found"), *BindingIdStr));
	}

	FString DisplayName = Bindings[FoundIndex].GetDisplayNameString(WidgetBlueprint);
	// RemoveBindingAt internally handles cleanup, broadcasts OnBindingsUpdated,
	// and marks the blueprint as structurally modified
	BPView->RemoveBindingAt(FoundIndex);

	// Only mark package dirty and auto-save (RemoveBindingAt already did MarkAsStructurallyModified)
	WidgetBlueprint->MarkPackageDirty();
	MarkWidgetBlueprintDirty(WidgetBlueprint, Context);

	TSharedPtr<FJsonObject> ResultObj = MakeShared<FJsonObject>();
	ResultObj->SetBoolField(TEXT("success"), true);
	ResultObj->SetStringField(TEXT("removed_binding_id"), BindingIdStr);
	ResultObj->SetStringField(TEXT("removed_display_name"), DisplayName);
	return ResultObj;
}

// =============================================================================
// FMVVMRemoveViewModelAction
// =============================================================================

bool FMVVMRemoveViewModelAction::Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError)
{
	if (!Params->HasField(TEXT("widget_name")))
	{
		OutError = TEXT("Missing 'widget_name' parameter");
		return false;
	}
	if (!Params->HasField(TEXT("viewmodel_name")))
	{
		OutError = TEXT("Missing 'viewmodel_name' parameter");
		return false;
	}
	return true;
}

TSharedPtr<FJsonObject> FMVVMRemoveViewModelAction::ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context)
{
	FString BlueprintName = Params->GetStringField(TEXT("widget_name"));
	FString ViewModelName = Params->GetStringField(TEXT("viewmodel_name"));

	UWidgetBlueprint* WidgetBlueprint = FindWidgetBlueprintByName(BlueprintName);
	if (!WidgetBlueprint)
	{
		return FMCPCommonUtils::CreateErrorResponse(FString::Printf(
			TEXT("Widget Blueprint '%s' not found"), *BlueprintName));
	}

	UMVVMWidgetBlueprintExtension_View* MVVMExt =
		UWidgetBlueprintExtension::GetExtension<UMVVMWidgetBlueprintExtension_View>(WidgetBlueprint);
	if (!MVVMExt)
	{
		return FMCPCommonUtils::CreateErrorResponse(TEXT("No MVVM extension found on Widget Blueprint."));
	}

	UMVVMBlueprintView* BPView = MVVMExt->GetBlueprintView();
	if (!BPView)
	{
		return FMCPCommonUtils::CreateErrorResponse(TEXT("No MVVM BlueprintView found."));
	}

	const FMVVMBlueprintViewModelContext* VMContext = BPView->FindViewModel(FName(*ViewModelName));
	if (!VMContext)
	{
		return FMCPCommonUtils::CreateErrorResponse(FString::Printf(
			TEXT("ViewModel '%s' not found on this Widget Blueprint"), *ViewModelName));
	}

	const FGuid TargetId = VMContext->GetViewModelId();
	BPView->RemoveViewModel(TargetId);

	WidgetBlueprint->MarkPackageDirty();
	MarkWidgetBlueprintDirty(WidgetBlueprint, Context);

	TSharedPtr<FJsonObject> ResultObj = MakeShared<FJsonObject>();
	ResultObj->SetBoolField(TEXT("success"), true);
	ResultObj->SetStringField(TEXT("removed_viewmodel_name"), ViewModelName);
	ResultObj->SetStringField(TEXT("removed_viewmodel_id"), TargetId.ToString());
	return ResultObj;
}


// ============================================================================
// Set bIsVariable on a widget component
// ============================================================================

bool FSetWidgetIsVariableAction::Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError)
{
	FString WidgetBPName, TargetName;
	if (!GetRequiredString(Params, TEXT("widget_name"), WidgetBPName, OutError)) return false;
	if (!GetRequiredString(Params, TEXT("target"), TargetName, OutError)) return false;
	return true;
}

TSharedPtr<FJsonObject> FSetWidgetIsVariableAction::ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context)
{
	FString WidgetBPName = Params->GetStringField(TEXT("widget_name"));
	FString TargetName = Params->GetStringField(TEXT("target"));
	bool bIsVariable = true;
	if (Params->HasField(TEXT("is_variable")))
	{
		bIsVariable = Params->GetBoolField(TEXT("is_variable"));
	}

	UWidgetBlueprint* WidgetBlueprint = FindWidgetBlueprintByName(WidgetBPName);
	if (!WidgetBlueprint)
	{
		return FMCPCommonUtils::CreateErrorResponse(FString::Printf(
			TEXT("Widget Blueprint '%s' not found"), *WidgetBPName));
	}

	if (!WidgetBlueprint->WidgetTree)
	{
		return FMCPCommonUtils::CreateErrorResponse(TEXT("Widget Blueprint has no WidgetTree"));
	}

	// Find the target widget
	UWidget* TargetWidget = nullptr;
	WidgetBlueprint->WidgetTree->ForEachWidget([&](UWidget* Widget)
	{
		if (Widget && Widget->GetName() == TargetName)
		{
			TargetWidget = Widget;
		}
	});

	if (!TargetWidget)
	{
		return FMCPCommonUtils::CreateErrorResponse(FString::Printf(
			TEXT("Widget '%s' not found in '%s'"), *TargetName, *WidgetBPName));
	}

	TargetWidget->bIsVariable = bIsVariable;

	WidgetBlueprint->MarkPackageDirty();
	MarkWidgetBlueprintDirty(WidgetBlueprint, Context);

	TSharedPtr<FJsonObject> ResultObj = MakeShared<FJsonObject>();
	ResultObj->SetStringField(TEXT("widget_name"), WidgetBPName);
	ResultObj->SetStringField(TEXT("target"), TargetName);
	ResultObj->SetBoolField(TEXT("is_variable"), bIsVariable);
	ResultObj->SetBoolField(TEXT("success"), true);
	return ResultObj;
}

// =============================================================================
// FPurgePanelOrphansAction
//
// Walks every PanelWidget in the WidgetTree and removes Slots whose Content is
// invalid for that panel.  Specifically removes:
//   - Slots whose Content is null
//   - Slots whose Content->Slot != this slot (widget actually lives in another panel)
//
// This catches the "ghost" entries that show up duplicated in the Designer
// hierarchy but cannot be removed via the normal Delete path because UMG's
// RemoveChild requires Widget->Slot->Parent == this panel.
// =============================================================================

bool FPurgePanelOrphansAction::Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError)
{
	FString WidgetBPName;
	if (!GetRequiredString(Params, TEXT("widget_name"), WidgetBPName, OutError)) return false;
	return true;
}

TSharedPtr<FJsonObject> FPurgePanelOrphansAction::ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context)
{
	FString WidgetBPName = Params->GetStringField(TEXT("widget_name"));
	bool bDryRun = false;
	Params->TryGetBoolField(TEXT("dry_run"), bDryRun);

	UWidgetBlueprint* WidgetBlueprint = FindWidgetBlueprintByName(WidgetBPName);
	if (!WidgetBlueprint || !WidgetBlueprint->WidgetTree)
	{
		return FMCPCommonUtils::CreateErrorResponse(FString::Printf(
			TEXT("Widget Blueprint '%s' not found or has no WidgetTree"), *WidgetBPName));
	}

	// Collect all PanelWidgets up front (ForEachWidget is safe; we only mutate after).
	TArray<UPanelWidget*> Panels;
	WidgetBlueprint->WidgetTree->ForEachWidget([&Panels](UWidget* W)
	{
		if (UPanelWidget* P = Cast<UPanelWidget>(W))
		{
			Panels.AddUnique(P);
		}
	});

	// Snapshot every widget's authoritative Slot BEFORE we mutate anything.
	// UPanelWidget::RemoveChildAt() unconditionally clears Slot->Content->Slot to null,
	// so removing a stale duplicate slot would also wipe the authoritative slot pointer
	// of the *real* widget if we don't shield it.
	TMap<UWidget*, UPanelSlot*> AuthoritativeSlot;
	WidgetBlueprint->WidgetTree->ForEachWidget([&AuthoritativeSlot](UWidget* W)
	{
		if (W)
		{
			AuthoritativeSlot.Add(W, W->Slot);
		}
	});

	TArray<TSharedPtr<FJsonValue>> Removed;
	int32 TotalRemoved = 0;

	for (UPanelWidget* Panel : Panels)
	{
		if (!Panel) { continue; }

		// Iterate from the back so RemoveChildAt doesn't skip indices.
		for (int32 i = Panel->GetChildrenCount() - 1; i >= 0; --i)
		{
			UWidget* Child = Panel->GetChildAt(i);
			FString Reason;

			// Resolve the authoritative slot for this widget from our snapshot.
			UPanelSlot* AuthSlot = nullptr;
			if (Child)
			{
				if (UPanelSlot* const* Found = AuthoritativeSlot.Find(Child))
				{
					AuthSlot = *Found;
				}
			}

			if (!Child)
			{
				Reason = TEXT("null_child");
			}
			else if (!AuthSlot)
			{
				// Widget has no authoritative slot anywhere -> stale pointer in this Panel.Children
				Reason = TEXT("no_slot_on_widget");
			}
			else if (AuthSlot->Parent != Panel)
			{
				// Widget's authoritative parent is a different panel -> this slot is a duplicate.
				Reason = TEXT("slot_parent_mismatch");
			}

			if (!Reason.IsEmpty())
			{
				TSharedPtr<FJsonObject> Entry = MakeShared<FJsonObject>();
				Entry->SetStringField(TEXT("panel"), Panel->GetName());
				Entry->SetStringField(TEXT("child_name"), Child ? Child->GetName() : FString(TEXT("<null>")));
				Entry->SetNumberField(TEXT("child_index"), i);
				Entry->SetStringField(TEXT("reason"), Reason);
				Removed.Add(MakeShared<FJsonValueObject>(Entry));
				++TotalRemoved;

				if (!bDryRun)
				{
					// Shield the real widget: temporarily clear THIS slot's Content pointer so
					// UPanelWidget::RemoveChildAt() does not nuke Child->Slot.  We're removing
					// only the stale slot entry, not the widget itself.
					UPanelSlot* StaleSlot = (i < Panel->GetChildrenCount())
						? Panel->GetSlots()[i]
						: nullptr;
					if (!StaleSlot)
					{
						// Fallback: scan Panel slots to find the matching one.
						const TArray<UPanelSlot*>& AllSlots = Panel->GetSlots();
						if (AllSlots.IsValidIndex(i))
						{
							StaleSlot = AllSlots[i];
						}
					}
					if (StaleSlot && StaleSlot->Content == Child)
					{
						StaleSlot->Content = nullptr;
					}

					Panel->Modify();
					Panel->RemoveChildAt(i);
				}
			}
		}
	}

	if (TotalRemoved > 0 && !bDryRun)
	{
		WidgetBlueprint->MarkPackageDirty();
		MarkWidgetBlueprintDirty(WidgetBlueprint, Context);
	}

	TSharedPtr<FJsonObject> ResultObj = MakeShared<FJsonObject>();
	ResultObj->SetBoolField(TEXT("success"), true);
	ResultObj->SetStringField(TEXT("widget_name"), WidgetBPName);
	ResultObj->SetBoolField(TEXT("dry_run"), bDryRun);
	ResultObj->SetNumberField(TEXT("total_removed"), TotalRemoved);
	ResultObj->SetArrayField(TEXT("removed"), Removed);
	return ResultObj;
}

// =============================================================================
// FSetWidgetReflectedPropertyAction — generic UPROPERTY writer for any widget
// instance inside a Widget Blueprint. Supports inherited native UPROPERTYs
// (e.g. UP111CommonButton::SelectedBackgroundColor on a WBP_P111CommonButton_C
// instance placed in another WBP).
// =============================================================================

bool FSetWidgetReflectedPropertyAction::Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError)
{
	if (!Params->HasField(TEXT("widget_name")))   { OutError = TEXT("Missing 'widget_name'");    return false; }
	if (!Params->HasField(TEXT("target")))        { OutError = TEXT("Missing 'target'");         return false; }
	if (!Params->HasField(TEXT("property_name"))) { OutError = TEXT("Missing 'property_name'");  return false; }
	if (!Params->HasField(TEXT("property_value"))){ OutError = TEXT("Missing 'property_value'"); return false; }
	return true;
}

TSharedPtr<FJsonObject> FSetWidgetReflectedPropertyAction::ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context)
{
	const FString BlueprintName = Params->GetStringField(TEXT("widget_name"));
	const FString TargetName    = Params->GetStringField(TEXT("target"));
	const FString PropertyName  = Params->GetStringField(TEXT("property_name"));

	UWidgetBlueprint* WidgetBlueprint = FindWidgetBlueprintByName(BlueprintName);
	if (!WidgetBlueprint)
	{
		return FMCPCommonUtils::CreateErrorResponse(FString::Printf(
			TEXT("Widget Blueprint '%s' not found"), *BlueprintName));
	}

	UWidget* TargetWidget = WidgetBlueprint->WidgetTree->FindWidget(FName(*TargetName));
	if (!TargetWidget)
	{
		return FMCPCommonUtils::CreateErrorResponse(FString::Printf(
			TEXT("Widget '%s' not found in '%s'"), *TargetName, *BlueprintName));
	}

	// Resolve property on the widget instance class hierarchy (so inherited native
	// UPROPERTYs like SelectedBackgroundColor are reachable too).
	FProperty* Prop = FindFProperty<FProperty>(TargetWidget->GetClass(), FName(*PropertyName));
	if (!Prop)
	{
		return FMCPCommonUtils::CreateErrorResponse(FString::Printf(
			TEXT("Property '%s' not found on '%s' (class %s)"),
			*PropertyName, *TargetName, *TargetWidget->GetClass()->GetName()));
	}

	// Pull the JSON value through the same path used by set_blueprint_property,
	// so we get the same FLinearColor/FVector2D/FName/etc. coverage.
	TSharedPtr<FJsonValue> JsonValue = Params->Values.FindRef(TEXT("property_value"));
	FString ErrorMessage;
	if (!FMCPCommonUtils::SetObjectProperty(TargetWidget, PropertyName, JsonValue, ErrorMessage))
	{
		return FMCPCommonUtils::CreateErrorResponse(
			FString::Printf(TEXT("Failed to set '%s.%s': %s"), *TargetName, *PropertyName, *ErrorMessage));
	}

	WidgetBlueprint->MarkPackageDirty();
	MarkWidgetBlueprintDirty(WidgetBlueprint, Context);

	TSharedPtr<FJsonObject> ResultObj = MakeShared<FJsonObject>();
	ResultObj->SetBoolField(TEXT("success"), true);
	ResultObj->SetStringField(TEXT("widget_name"), BlueprintName);
	ResultObj->SetStringField(TEXT("target"), TargetName);
	ResultObj->SetStringField(TEXT("property_name"), PropertyName);
	ResultObj->SetStringField(TEXT("class"), TargetWidget->GetClass()->GetName());
	return ResultObj;
}

bool FRemoveWidgetDelegateBindingsAction::Validate(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context, FString& OutError)
{
	FString WidgetName;
	if (!GetRequiredString(Params, TEXT("widget_name"), WidgetName, OutError))
	{
		return false;
	}

	FString TargetName;
	FString PropertyName;
	FString FunctionName;
	FString GraphName;
	bool bRemoveInvalid = false;
	Params->TryGetStringField(TEXT("target"), TargetName);
	Params->TryGetStringField(TEXT("property_name"), PropertyName);
	Params->TryGetStringField(TEXT("function_name"), FunctionName);
	Params->TryGetStringField(TEXT("graph_name"), GraphName);
	Params->TryGetBoolField(TEXT("remove_invalid"), bRemoveInvalid);

	if (TargetName.IsEmpty() && PropertyName.IsEmpty() && FunctionName.IsEmpty() && GraphName.IsEmpty() && !bRemoveInvalid)

	{
		OutError = TEXT("Provide at least one selector: target, property_name, function_name, graph_name, or remove_invalid=true");

		return false;
	}
	return true;
}

TSharedPtr<FJsonObject> FRemoveWidgetDelegateBindingsAction::ExecuteInternal(const TSharedPtr<FJsonObject>& Params, FMCPEditorContext& Context)
{
	const FString BlueprintName = Params->GetStringField(TEXT("widget_name"));

	FString TargetName;
	FString PropertyName;
	FString FunctionName;
	FString GraphName;
	bool bRemoveInvalid = false;
	bool bDryRun = false;
	Params->TryGetStringField(TEXT("target"), TargetName);
	Params->TryGetStringField(TEXT("property_name"), PropertyName);
	Params->TryGetStringField(TEXT("function_name"), FunctionName);
	Params->TryGetStringField(TEXT("graph_name"), GraphName);
	Params->TryGetBoolField(TEXT("remove_invalid"), bRemoveInvalid);
	Params->TryGetBoolField(TEXT("dry_run"), bDryRun);


	UWidgetBlueprint* WidgetBlueprint = FindWidgetBlueprintByName(BlueprintName);
	if (!WidgetBlueprint)
	{
		return FMCPCommonUtils::CreateErrorResponse(FString::Printf(
			TEXT("Widget Blueprint '%s' not found"), *BlueprintName));
	}

	TArray<TSharedPtr<FJsonValue>> Removed;
	TArray<int32> MatchedIndexes;
	TArray<UK2Node_ComponentBoundEvent*> MatchedEventNodes;
	TArray<UEdGraph*> MatchedGraphs;
	const bool bHasExplicitSelector = !TargetName.IsEmpty() || !PropertyName.IsEmpty() || !FunctionName.IsEmpty();


	for (int32 Index = WidgetBlueprint->Bindings.Num() - 1; Index >= 0; --Index)

	{
		const FDelegateEditorBinding& Binding = WidgetBlueprint->Bindings[Index];

		const bool bTargetMatches = TargetName.IsEmpty() || Binding.ObjectName == TargetName;
		const bool bPropertyMatches = PropertyName.IsEmpty() || Binding.PropertyName == FName(*PropertyName);
		const bool bFunctionMatches = FunctionName.IsEmpty() || Binding.FunctionName == FName(*FunctionName);
		const bool bInvalidTarget = bRemoveInvalid && !Binding.DoesBindingTargetExist(WidgetBlueprint);

		if ((bHasExplicitSelector && bTargetMatches && bPropertyMatches && bFunctionMatches) || bInvalidTarget)
		{
			MatchedIndexes.Add(Index);


			TSharedPtr<FJsonObject> Entry = MakeShared<FJsonObject>();
			Entry->SetNumberField(TEXT("index"), Index);
			Entry->SetStringField(TEXT("object_name"), Binding.ObjectName);
			Entry->SetStringField(TEXT("property_name"), Binding.PropertyName.ToString());
			Entry->SetStringField(TEXT("function_name"), Binding.FunctionName.ToString());
			Entry->SetStringField(TEXT("source_property"), Binding.SourceProperty.ToString());
			Entry->SetStringField(TEXT("member_guid"), Binding.MemberGuid.ToString(EGuidFormats::Digits));
			Entry->SetNumberField(TEXT("kind"), static_cast<int32>(Binding.Kind));
			Entry->SetBoolField(TEXT("target_exists"), Binding.DoesBindingTargetExist(WidgetBlueprint));
			Removed.Add(MakeShared<FJsonValueObject>(Entry));
		}
	}

	if (UEdGraph* EventGraph = FBlueprintEditorUtils::FindEventGraph(WidgetBlueprint))
	{
		for (UEdGraphNode* Node : EventGraph->Nodes)
		{
			UK2Node_ComponentBoundEvent* EventNode = Cast<UK2Node_ComponentBoundEvent>(Node);
			if (!EventNode)
			{
				continue;
			}

			const bool bTargetMatches = TargetName.IsEmpty() || EventNode->ComponentPropertyName == FName(*TargetName);
			const bool bPropertyMatches = PropertyName.IsEmpty() || EventNode->DelegatePropertyName == FName(*PropertyName);
			const bool bFunctionMatches = FunctionName.IsEmpty() || EventNode->CustomFunctionName == FName(*FunctionName);
			const bool bInvalidTarget = bRemoveInvalid && !FindFProperty<FObjectProperty>(WidgetBlueprint->GeneratedClass, EventNode->ComponentPropertyName);

			if ((bHasExplicitSelector && bTargetMatches && bPropertyMatches && bFunctionMatches) || bInvalidTarget)
			{
				MatchedEventNodes.Add(EventNode);

				TSharedPtr<FJsonObject> Entry = MakeShared<FJsonObject>();
				Entry->SetStringField(TEXT("type"), TEXT("component_bound_event"));
				Entry->SetStringField(TEXT("node_id"), EventNode->NodeGuid.ToString());
				Entry->SetStringField(TEXT("node_title"), EventNode->GetNodeTitle(ENodeTitleType::FullTitle).ToString());
				Entry->SetStringField(TEXT("component_property"), EventNode->ComponentPropertyName.ToString());
				Entry->SetStringField(TEXT("delegate_property"), EventNode->DelegatePropertyName.ToString());
				Entry->SetStringField(TEXT("custom_function"), EventNode->CustomFunctionName.ToString());
				Entry->SetBoolField(TEXT("target_exists"), FindFProperty<FObjectProperty>(WidgetBlueprint->GeneratedClass, EventNode->ComponentPropertyName) != nullptr);
				Removed.Add(MakeShared<FJsonValueObject>(Entry));
			}
		}
	}

	if (!GraphName.IsEmpty() || !FunctionName.IsEmpty())
	{
		TArray<UObject*> ChildObjects;
		GetObjectsWithOuter(WidgetBlueprint, ChildObjects, true);
		for (UObject* ChildObject : ChildObjects)
		{
			UEdGraph* Graph = Cast<UEdGraph>(ChildObject);
			if (!Graph || Graph == FBlueprintEditorUtils::FindEventGraph(WidgetBlueprint))
			{
				continue;
			}

			bool bGraphMatches = !GraphName.IsEmpty() && Graph->GetName() == GraphName;
			if (!bGraphMatches && !FunctionName.IsEmpty())
			{
				for (UEdGraphNode* Node : Graph->Nodes)
				{
					const UK2Node_CallFunction* CallFunctionNode = Cast<UK2Node_CallFunction>(Node);
					if (CallFunctionNode && CallFunctionNode->FunctionReference.GetMemberName() == FName(*FunctionName))
					{
						bGraphMatches = true;
						break;
					}
				}
			}

			if (bGraphMatches)
			{
				MatchedGraphs.Add(Graph);

				TSharedPtr<FJsonObject> Entry = MakeShared<FJsonObject>();
				Entry->SetStringField(TEXT("type"), TEXT("ed_graph"));
				Entry->SetStringField(TEXT("graph_name"), Graph->GetName());
				Entry->SetStringField(TEXT("graph_path"), Graph->GetPathName());
				Entry->SetNumberField(TEXT("node_count"), Graph->Nodes.Num());
				Removed.Add(MakeShared<FJsonValueObject>(Entry));
			}
		}
	}

	if ((MatchedIndexes.Num() > 0 || MatchedEventNodes.Num() > 0 || MatchedGraphs.Num() > 0) && !bDryRun)
	{

		const FScopedTransaction Transaction(LOCTEXT("RemoveWidgetDelegateBindings", "Remove Widget Delegate Bindings"));
		WidgetBlueprint->Modify();
		for (const int32 Index : MatchedIndexes)
		{
			WidgetBlueprint->Bindings.RemoveAt(Index, 1, EAllowShrinking::No);
		}
		for (UK2Node_ComponentBoundEvent* EventNode : MatchedEventNodes)
		{
			if (EventNode && EventNode->GetGraph())
			{
				for (UEdGraphPin* Pin : EventNode->Pins)
				{
					if (Pin)
					{
						Pin->BreakAllPinLinks();
					}
				}
				EventNode->GetGraph()->RemoveNode(EventNode);
			}
		}
		bool bMovedGraphToTransient = false;
		for (UEdGraph* Graph : MatchedGraphs)
		{
			if (!Graph)
			{
				continue;
			}

			WidgetBlueprint->FunctionGraphs.Remove(Graph);
			WidgetBlueprint->MacroGraphs.Remove(Graph);
			WidgetBlueprint->DelegateSignatureGraphs.Remove(Graph);
			WidgetBlueprint->IntermediateGeneratedGraphs.Remove(Graph);
			WidgetBlueprint->UbergraphPages.Remove(Graph);
			Graph->Modify();
			Graph->ClearFlags(RF_Public | RF_Standalone | RF_Transactional);
			const FString TransientGraphName = FString::Printf(TEXT("Removed_%s_%s"), *Graph->GetName(), *FGuid::NewGuid().ToString(EGuidFormats::Short));
			if (Graph->Rename(*TransientGraphName, GetTransientPackage(), REN_DontCreateRedirectors | REN_ForceNoResetLoaders | REN_NonTransactional))
			{
				bMovedGraphToTransient = true;
				Graph->MarkAsGarbage();
			}
		}
		if (bMovedGraphToTransient)
		{
			CollectGarbage(GARBAGE_COLLECTION_KEEPFLAGS);
		}


		WidgetBlueprint->PropertyBindings = WidgetBlueprint->Bindings.Num();

		WidgetBlueprint->MarkPackageDirty();
		MarkWidgetBlueprintDirty(WidgetBlueprint, Context);
	}


	TSharedPtr<FJsonObject> ResultObj = MakeShared<FJsonObject>();
	ResultObj->SetBoolField(TEXT("success"), true);
	ResultObj->SetStringField(TEXT("widget_name"), BlueprintName);
	ResultObj->SetBoolField(TEXT("dry_run"), bDryRun);
	ResultObj->SetBoolField(TEXT("remove_invalid"), bRemoveInvalid);
	ResultObj->SetNumberField(TEXT("matched_count"), MatchedIndexes.Num() + MatchedEventNodes.Num() + MatchedGraphs.Num());
	ResultObj->SetNumberField(TEXT("matched_binding_count"), MatchedIndexes.Num());
	ResultObj->SetNumberField(TEXT("matched_event_node_count"), MatchedEventNodes.Num());
	ResultObj->SetNumberField(TEXT("matched_graph_count"), MatchedGraphs.Num());

	ResultObj->SetNumberField(TEXT("remaining_bindings"), WidgetBlueprint->Bindings.Num());
	ResultObj->SetArrayField(TEXT("removed"), Removed);

	return ResultObj;
}

#undef LOCTEXT_NAMESPACE

