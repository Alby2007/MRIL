def binary_search(arr, target):
    """Return index of target in sorted arr, or -1."""
    lo, hi = 0, len(arr)
    while lo < hi:
        mid = (lo + hi) // 2
        if arr[mid] == target:
            return mid
        elif arr[mid] < target:
            lo = mid          # BUG: should be mid + 1; loops forever
        else:
            hi = mid
    return -1
