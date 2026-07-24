#include "FayCasualGirlActor.h"

#include "Components/SkeletalMeshComponent.h"
#include "Engine/SkeletalMesh.h"
#include "UObject/ConstructorHelpers.h"

namespace
{
void ConfigureLeaderPoseFollower(
    USkeletalMeshComponent* Follower,
    USkeletalMeshComponent* Leader,
    USkeletalMesh* Mesh)
{
    check(Follower);
    check(Leader);

    Follower->SetupAttachment(Leader);
    Follower->SetCollisionEnabled(ECollisionEnabled::NoCollision);
    Follower->SetGenerateOverlapEvents(false);
    Follower->bUseAttachParentBound = true;
    if (Mesh)
    {
        Follower->SetSkeletalMesh(Mesh);
    }

    // Followers consume Body's evaluated transforms and never run a competing
    // animation pose.  This keeps ARKit and ARDY ownership on Body alone.
    Follower->SetLeaderPoseComponent(Leader, true, false);
}
} // namespace

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

    Hair1 = CreateDefaultSubobject<USkeletalMeshComponent>(TEXT("Hair1"));
    Top1 = CreateDefaultSubobject<USkeletalMeshComponent>(TEXT("Top1"));
    Pants = CreateDefaultSubobject<USkeletalMeshComponent>(TEXT("Pants"));
    Shoes_Socks =
        CreateDefaultSubobject<USkeletalMeshComponent>(TEXT("Shoes_Socks"));

    static ConstructorHelpers::FObjectFinder<USkeletalMesh> ReviewedHair1(
        TEXT("/Game/Sample/Meshes/SK_Hair_1.SK_Hair_1"));
    static ConstructorHelpers::FObjectFinder<USkeletalMesh> ReviewedTop1(
        TEXT("/Game/Sample/Meshes/SK_Top_1.SK_Top_1"));
    static ConstructorHelpers::FObjectFinder<USkeletalMesh> ReviewedPants(
        TEXT("/Game/Sample/Meshes/SK_Pants.SK_Pants"));
    static ConstructorHelpers::FObjectFinder<USkeletalMesh> ReviewedShoesSocks(
        TEXT("/Game/Sample/Meshes/SK_Shoes_Socks.SK_Shoes_Socks"));

    ConfigureLeaderPoseFollower(Hair1, Body, ReviewedHair1.Object);
    ConfigureLeaderPoseFollower(Top1, Body, ReviewedTop1.Object);
    ConfigureLeaderPoseFollower(Pants, Body, ReviewedPants.Object);
    ConfigureLeaderPoseFollower(
        Shoes_Socks,
        Body,
        ReviewedShoesSocks.Object);
}
