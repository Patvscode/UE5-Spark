#!/usr/bin/env bash

# Shared advisory lock for every operation that can inspect or mutate the private
# Fab staging project. This file is sourced by the launchers; it is not a
# standalone command.

fab_phase_lock_fail() {
    printf 'error: %s\n' "$*" >&2
    return 1
}

fab_owned_directory() {
    if (( $# != 2 )); then
        fab_phase_lock_fail 'fab_owned_directory requires a path and shared/private mode'
        return 1
    fi
    local owned_path=$1
    local privacy=$2
    if [[ -e $owned_path || -L $owned_path ]]; then
        [[ -d $owned_path && ! -L $owned_path && -O $owned_path ]] || {
            fab_phase_lock_fail "workspace path must be one real user-owned directory: $owned_path"
            return 1
        }
    else
        install -d -m 0700 "$owned_path" || return 1
    fi
    case $privacy in
        shared) ;;
        private) chmod 0700 "$owned_path" || return 1 ;;
        *)
            fab_phase_lock_fail 'fab_owned_directory mode must be shared or private'
            return 1
            ;;
    esac
}

fab_phase_lock_exec_without_fd() {
    if [[ -z ${FAB_PHASE_LOCK_FD:-} ]]; then
        fab_phase_lock_fail 'Fab phase lock is not held'
        return 1
    fi
    exec {FAB_PHASE_LOCK_FD}>&-
    exec "$@"
}

fab_phase_lock_acquire() {
    if (( $# != 1 )); then
        fab_phase_lock_fail 'fab_phase_lock_acquire requires one canonical workspace path'
        return 1
    fi

    local lock_workspace=$1
    local state_root="$lock_workspace/state"
    local lock_root="$state_root/fab-phase"
    local lock_path="$lock_root/operation.lock"

    [[ $lock_workspace == /* && -d $lock_workspace && ! -L $lock_workspace ]] || {
        fab_phase_lock_fail 'the Fab phase-lock workspace must be a real absolute directory'
        return 1
    }
    [[ -O $lock_workspace ]] || {
        fab_phase_lock_fail 'the Fab phase-lock workspace must be owned by the invoking user'
        return 1
    }
    command -v flock >/dev/null 2>&1 || {
        fab_phase_lock_fail 'required command is missing: flock'
        return 1
    }
    command -v install >/dev/null 2>&1 || {
        fab_phase_lock_fail 'required command is missing: install'
        return 1
    }
    command -v readlink >/dev/null 2>&1 || {
        fab_phase_lock_fail 'required command is missing: readlink'
        return 1
    }

    fab_owned_directory "$state_root" shared || return 1
    fab_owned_directory "$lock_root" private || return 1

    # The parent is mode 0700 and owned by this user, so opening the fixed lock
    # path cannot be redirected by another account. Validate it again after open.
    # Append-open never truncates a target. Validate that the opened inode is
    # exactly the real path before changing its mode or using it as the lock.
    exec {FAB_PHASE_LOCK_FD}>>"$lock_path" || return 1
    [[ -f $lock_path && ! -L $lock_path && -O $lock_path \
        && -f /proc/self/fd/$FAB_PHASE_LOCK_FD \
        && -O /proc/self/fd/$FAB_PHASE_LOCK_FD \
        && /proc/self/fd/$FAB_PHASE_LOCK_FD -ef $lock_path ]] || {
        exec {FAB_PHASE_LOCK_FD}>&-
        fab_phase_lock_fail 'Fab phase lock must be a real user-owned file'
        return 1
    }
    chmod 0600 "/proc/self/fd/$FAB_PHASE_LOCK_FD" || return 1
    flock -n "$FAB_PHASE_LOCK_FD" || {
        exec {FAB_PHASE_LOCK_FD}>&-
        fab_phase_lock_fail 'another Fab acquisition, review, or transition is already running'
        return 1
    }
    [[ -f $lock_path && ! -L $lock_path \
        && /proc/self/fd/$FAB_PHASE_LOCK_FD -ef $lock_path ]] || {
        exec {FAB_PHASE_LOCK_FD}>&-
        fab_phase_lock_fail 'Fab phase lock path changed while acquiring it'
        return 1
    }
}
