"""Portable arithmetic for a finite, additional virtual-address budget."""
MIB = 1024**2


def address_limit(vm_bytes, soft, hard, required_extra, allowance=256 * MIB):
    if type(vm_bytes) is not int or vm_bytes <= 0 or not 0 <= required_extra <= allowance:
        raise ValueError("Invalid virtual-address budget")
    target = vm_bytes + allowance
    # -1 denotes infinity on the supported Linux backend; never raise an inherited limit.
    for inherited in (soft, hard):
        if inherited != -1:
            target = min(target, inherited)
    if target - vm_bytes < required_extra:
        raise RuntimeError(f"RLIMIT_AS_HEADROOM_TOO_SMALL: VmSize={vm_bytes}, soft={soft}, hard={hard}, "
                           f"required_extra={required_extra}, proposed_limit={target}")
    return target
