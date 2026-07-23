#include "FayCasualGirlActor.h"

#include "Components/SkeletalMeshComponent.h"
#include "Engine/SkeletalMesh.h"
#include "UObject/ConstructorHelpers.h"

AFayCasualGirlActor::AFayCasualGirlActor()
{
    PrimaryActorTick.bCanEverTick = false;

    Body = CreateDefaultSubobject<USkeletalMeshComponent>(TEXT("Body"));
    SetRootComponent(Body);
    Body->SetCollisionEnabled(ECollisionEnabled::NoCollision);
    Body->SetGenerateOverlapEvents(false);
    Body->VisibilityBasedAnimTickOption =
        EVisibilityBasedAnimTickOption::AlwaysTickPoseAndRefreshBones;

    static ConstructorHelpers::FObjectFinder<USkeletalMesh> ReviewedBody(
        TEXT("/Game/Sample/Meshes/SK_Complete.SK_Complete"));
    if (ReviewedBody.Succeeded())
    {
        Body->SetSkeletalMesh(ReviewedBody.Object);
    }
}
