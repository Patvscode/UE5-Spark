"""Read-only inspection of the assembled Ada Blueprint's runtime contract."""

import unreal


ASSET_PATH = "/Game/FayMetaHumans/Built/AdaFay/BP_AdaFay"
INTEREST_TERMS = ("anim", "face", "link", "setup", "subject", "use_live")


def emit(name, value):
    unreal.log(f"MH_RUNTIME_CONTRACT_{name}={value}")


def get_property(obj, names):
    for name in names:
        try:
            return name, obj.get_editor_property(name)
        except Exception:
            pass
    return None, None


asset = unreal.load_asset(ASSET_PATH)
if asset is None:
    raise RuntimeError(f"Missing assembled Blueprint: {ASSET_PATH}")

generated_class = asset.generated_class()
if generated_class is None:
    raise RuntimeError(f"Blueprint has no generated class: {ASSET_PATH}")

cdo = unreal.get_default_object(generated_class)
if cdo is None:
    raise RuntimeError(f"Blueprint has no class default object: {ASSET_PATH}")

emit("ASSET", asset.get_path_name())
emit("CLASS", generated_class.get_path_name())
emit("CDO", cdo.get_path_name())

interesting_names = sorted(
    name for name in dir(cdo) if any(term in name.lower() for term in INTEREST_TERMS)
)
emit("PYTHON_NAMES", ",".join(interesting_names))

for label, candidates in (
    ("USE_LIVE_LINK", ("use_live_link", "UseLiveLink")),
    ("LIVE_LINK_SUBJECT", ("live_link_subject", "LiveLinkSubject")),
    ("FACE", ("face", "Face")),
):
    property_name, value = get_property(cdo, candidates)
    emit(f"{label}_PROPERTY", property_name or "missing")
    if value is not None:
        value_path = value.get_path_name() if hasattr(value, "get_path_name") else str(value)
        emit(f"{label}_VALUE", value_path)

setup_names = [
    name
    for name in dir(cdo)
    if "live" in name.lower() or "setup" in name.lower()
]
emit("SETUP_NAMES", ",".join(sorted(setup_names)))

for index, function_path in enumerate(
    (
        f"{generated_class.get_path_name()}:LiveLinkSetup",
        f"{ASSET_PATH}.BP_AdaFay_C:LiveLinkSetup",
    )
):
    try:
        function = unreal.find_object(None, function_path)
    except Exception:
        function = None
    emit(f"SETUP_OBJECT_{index}", function.get_path_name() if function else "missing")

skeletal_components = cdo.get_components_by_class(unreal.SkeletalMeshComponent)
emit("SKELETAL_COMPONENT_COUNT", len(skeletal_components))
for index, component in enumerate(skeletal_components):
    stable_name = component.get_name().removesuffix("_GEN_VARIABLE")
    emit(f"SKELETAL_{index}_NAME", stable_name)
    if stable_name == "Face":
        anim_property, anim_class = get_property(component, ("anim_class", "AnimClass"))
        emit("FACE_ANIM_CLASS_PROPERTY", anim_property or "missing")
        if anim_class is not None:
            emit("FACE_ANIM_CLASS", anim_class.get_path_name())

editor_actors = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
if editor_actors is None:
    raise RuntimeError("EditorActorSubsystem is unavailable")

actor = None
if editor_actors is not None:
    try:
        actor = editor_actors.spawn_actor_from_class(
            actor_class=generated_class,
            location=unreal.Vector(),
            rotation=unreal.Rotator(),
            transient=True,
        )
        if actor is None:
            raise RuntimeError("Failed to spawn the assembled Ada Blueprint")
        emit("SPAWNED", actor.get_path_name())
        if actor is not None:
            for label, candidates in (
                ("SPAWN_USE_LIVE_LINK", ("use_live_link", "UseLiveLink")),
                ("SPAWN_LIVE_LINK_SUBJECT", ("live_link_subject", "LiveLinkSubject")),
                (
                    "SPAWN_LIVE_LINK_RETARGET_ASSET",
                    ("live_link_retarget_asset", "LiveLinkRetargetAsset"),
                ),
                ("SPAWN_FACE", ("face", "Face")),
            ):
                property_name, value = get_property(actor, candidates)
                emit(f"{label}_PROPERTY", property_name or "missing")
                if value is not None:
                    value_path = (
                        value.get_path_name()
                        if hasattr(value, "get_path_name")
                        else str(value)
                    )
                    emit(f"{label}_VALUE", value_path)

            spawned_skeletal_components = actor.get_components_by_class(
                unreal.SkeletalMeshComponent
            )
            emit("SPAWN_SKELETAL_COMPONENT_COUNT", len(spawned_skeletal_components))
            for index, component in enumerate(spawned_skeletal_components):
                stable_name = component.get_name().removesuffix("_GEN_VARIABLE")
                emit(f"SPAWN_SKELETAL_{index}_NAME", stable_name)
                anim_instance = component.get_anim_instance()
                emit(
                    f"SPAWN_SKELETAL_{index}_ANIM_CLASS",
                    (
                        anim_instance.get_class().get_path_name()
                        if anim_instance is not None
                        else "missing"
                    ),
                )
                if stable_name == "Face":
                    emit(
                        "SPAWN_FACE_ANIM_INSTANCE",
                        anim_instance.get_path_name() if anim_instance else "missing",
                    )
                    if anim_instance is not None:
                        emit(
                            "SPAWN_FACE_ANIM_NAMES",
                            ",".join(
                                sorted(
                                    name
                                    for name in dir(anim_instance)
                                    if "link" in name.lower()
                                    or "subj" in name.lower()
                                )
                            ),
                        )
                        subject_property, subject = get_property(
                            anim_instance,
                            (
                                "l_link_face_subj",
                                "l_link__face__subj",
                                "LLink_Face_Subj",
                            ),
                        )
                        emit(
                            "SPAWN_FACE_SUBJECT_PROPERTY",
                            subject_property or "missing",
                        )
                        if subject is not None:
                            emit("SPAWN_FACE_SUBJECT_VALUE", subject)

            try:
                actor.set_editor_property("UseLiveLink", True)
                actor.set_editor_property(
                    "LiveLinkSubject",
                    unreal.LiveLinkSubjectName(name="FayAudio"),
                )
                face_property, face = get_property(actor, ("face", "Face"))
                if face is None:
                    raise RuntimeError("spawned Ada has no Face component")
                _, retarget_asset = get_property(
                    actor,
                    ("live_link_retarget_asset", "LiveLinkRetargetAsset"),
                )
                configured_skeletal_components = {
                    component.get_name().removesuffix("_GEN_VARIABLE"): component
                    for component in actor.get_components_by_class(
                        unreal.SkeletalMeshComponent
                    )
                }
                for index, (component_name, component) in enumerate(
                    sorted(configured_skeletal_components.items())
                ):
                    anim_instance = component.get_anim_instance()
                    emit(
                        f"AFTER_PROPERTY_SKELETAL_{index}_NAME",
                        component_name,
                    )
                    emit(
                        f"AFTER_PROPERTY_SKELETAL_{index}_ANIM_CLASS",
                        (
                            anim_instance.get_class().get_path_name()
                            if anim_instance is not None
                            else "missing"
                        ),
                    )
                for component_name in ("Body", "Face"):
                    component = configured_skeletal_components.get(component_name)
                    if component is None:
                        raise RuntimeError(
                            f"spawned Ada has no {component_name} component"
                        )
                    actor.call_method(
                        "LiveLinkSetup",
                        args=(
                            component,
                            unreal.LiveLinkSubjectName(name="FayAudio"),
                            retarget_asset,
                            True,
                        ),
                    )
                emit("SPAWN_SETUP_CALL", "OK")
            except Exception as error:
                emit("SPAWN_SETUP_CALL", f"ERROR:{error}")

            face_property, face = get_property(actor, ("face", "Face"))
            emit("POST_SETUP_FACE_PROPERTY", face_property or "missing")
            if face is not None:
                anim_instance = face.get_anim_instance()
                emit(
                    "POST_SETUP_FACE_ANIM_INSTANCE",
                    anim_instance.get_path_name() if anim_instance else "missing",
                )
                if anim_instance is not None:
                    emit(
                        "POST_SETUP_FACE_ANIM_NAMES",
                        ",".join(
                            sorted(
                                name
                                for name in dir(anim_instance)
                                if "link" in name.lower() or "subj" in name.lower()
                            )
                        ),
                    )
                    subject_property, subject = get_property(
                        anim_instance,
                        (
                            "l_link_face_subj",
                            "l_link__face__subj",
                            "LLink_Face_Subj",
                        ),
                    )
                    emit(
                        "POST_SETUP_FACE_SUBJECT_PROPERTY",
                        subject_property or "missing",
                    )
                    if subject is not None:
                        emit("POST_SETUP_FACE_SUBJECT_VALUE", subject)

            post_setup_skeletal_components = actor.get_components_by_class(
                unreal.SkeletalMeshComponent
            )
            post_setup_body_is_live_link_instance = False
            for index, component in enumerate(post_setup_skeletal_components):
                stable_name = component.get_name().removesuffix("_GEN_VARIABLE")
                anim_instance = component.get_anim_instance()
                emit(f"POST_SETUP_SKELETAL_{index}_NAME", stable_name)
                emit(
                    f"POST_SETUP_SKELETAL_{index}_ANIM_INSTANCE",
                    anim_instance.get_path_name() if anim_instance else "missing",
                )
                if anim_instance is not None:
                    if stable_name == "Body":
                        post_setup_body_is_live_link_instance = (
                            anim_instance.get_class().get_path_name()
                            == "/Script/LiveLinkAnimationCore.LiveLinkInstance"
                        )
                    emit(
                        f"POST_SETUP_SKELETAL_{index}_ANIM_CLASS",
                        anim_instance.get_class().get_path_name(),
                    )
                    emit(
                        f"POST_SETUP_SKELETAL_{index}_ANIM_NAMES",
                        ",".join(
                            sorted(
                                name
                                for name in dir(anim_instance)
                                if "link" in name.lower()
                                or "subj" in name.lower()
                                or "retarget" in name.lower()
                            )
                        ),
                    )
                    subject_property, subject = get_property(
                        anim_instance,
                        (
                            "l_link_face_subj",
                            "l_link__face__subj",
                            "LLink_Face_Subj",
                        ),
                    )
                    emit(
                        f"POST_SETUP_SKELETAL_{index}_SUBJECT_PROPERTY",
                        subject_property or "missing",
                    )
                    if subject is not None:
                        emit(
                            f"POST_SETUP_SKELETAL_{index}_SUBJECT_VALUE",
                            subject,
                        )
            emit(
                "POST_SETUP_BODY_LIVE_LINK_INSTANCE",
                post_setup_body_is_live_link_instance,
            )
            if not post_setup_body_is_live_link_instance:
                raise RuntimeError(
                    "Ada Body did not install UE 5.8's native LiveLinkInstance"
                )
    finally:
        if actor is not None:
            editor_actors.destroy_actor(actor)

emit("COMPLETE", "OK")
