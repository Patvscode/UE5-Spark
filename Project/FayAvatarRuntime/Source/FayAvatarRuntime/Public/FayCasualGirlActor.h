#pragma once

#include "CoreMinimal.h"
#include "GameFramework/Actor.h"

#include "FayCasualGirlActor.generated.h"

class USkeletalMeshComponent;

/**
 * Minimal runtime host for the locally installed Casual Girl sample.
 *
 * The licensed mesh remains private project content.  Keeping the host native
 * avoids requiring a generated wrapper Blueprint: the reviewed SK_Complete
 * mesh is the single visible body and also receives its Apple ARKit morphs.
 */
UCLASS(Blueprintable)
class FAYAVATARRUNTIME_API AFayCasualGirlActor : public AActor
{
    GENERATED_BODY()

public:
    AFayCasualGirlActor();

private:
    UPROPERTY(VisibleAnywhere, Category = "Fay|Casual Girl")
    TObjectPtr<USkeletalMeshComponent> Body;
};
