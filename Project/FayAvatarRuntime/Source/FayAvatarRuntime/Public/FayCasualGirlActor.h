#pragma once

#include "CoreMinimal.h"
#include "GameFramework/Actor.h"

#include "FayCasualGirlActor.generated.h"

class USkeletalMeshComponent;

/**
 * Minimal runtime host for the locally installed Casual Girl sample.
 *
 * The licensed mesh remains private project content.  Keeping the host native
 * avoids requiring a generated wrapper Blueprint.  The reviewed SK_Complete
 * mesh remains the single face/body animation driver, while a fixed default
 * outfit follows that mesh through Unreal's leader-pose mechanism.
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

    UPROPERTY(VisibleAnywhere, Category = "Fay|Casual Girl")
    TObjectPtr<USkeletalMeshComponent> Hair1;

    UPROPERTY(VisibleAnywhere, Category = "Fay|Casual Girl")
    TObjectPtr<USkeletalMeshComponent> Top1;

    UPROPERTY(VisibleAnywhere, Category = "Fay|Casual Girl")
    TObjectPtr<USkeletalMeshComponent> Pants;

    UPROPERTY(VisibleAnywhere, Category = "Fay|Casual Girl")
    TObjectPtr<USkeletalMeshComponent> Shoes_Socks;
};
