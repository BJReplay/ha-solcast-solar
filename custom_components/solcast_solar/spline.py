"""Cubic spline from one-dimensional arrays."""

# pylint: disable=C0200, C0304, C0321, R0914

import math

def cubic_interp(x0, x, y):
    """Build a cubic spline.

    x0: Array of floats to interpolate at
    x : Array of floats in increasing order
    y : Array of floats to interpolate

    Returns array of interpolated values.
    """
    def diff(lst): # numpy-like diff
        size = len(lst) - 1
        r = [0] * size
        for i in range(size): r[i] = lst[i+1] - lst[i]
        return r

    def clip(lst, min_val, max_val, in_place = False): # numpy-like clip
        if not in_place: lst = lst[:]
        for i in range(len(lst)):
            if lst[i] < min_val:
                lst[i] = min_val
            elif lst[i] > max_val:
                lst[i] = max_val
        return lst

    def searchsorted(list_to_insert, insert_into): # numpy-like searchsorted
        def float_searchsorted(float_to_insert, insert_into):
            for i in range(len(insert_into)):
                if float_to_insert <= insert_into[i]: return i
            return len(insert_into)
        return [float_searchsorted(i, insert_into) for i in list_to_insert]

    def subtract(a, b):
        return a - b

    size = len(x)
    xdiff = diff(x)
    ydiff = diff(y)

    li = [0] * size
    li_1 = [0] * (size - 1)
    z = [0] * (size)

    li[0] = math.sqrt(2 * xdiff[0])
    li_1[0] = 0.0
    b0 = 0.0
    z[0] = b0 / li[0]

    for i in range(1, size - 1, 1):
        li_1[i] = xdiff[i-1] / li[i-1]
        li[i] = math.sqrt(2 * (xdiff[i-1] + xdiff[i]) - li_1[i-1] * li_1[i-1])
        bi = 6 * (ydiff[i] / xdiff[i] - ydiff[i-1] / xdiff[i-1])
        z[i] = (bi - li_1[i-1] * z[i-1]) / li[i]

    i = size - 1
    li_1[i-1] = xdiff[-1] / li[i-1]
    li[i] = math.sqrt(2 * xdiff[-1] - li_1[i-1] * li_1[i-1])
    bi = 0.0
    z[i] = (bi - li_1[i-1] * z[i-1]) / li[i]

    i = size - 1
    z[i] = z[i] / li[i]
    for i in range(size - 2, -1, -1):
        z[i] = (z[i] - li_1[i-1] * z[i+1]) / li[i]

    index = searchsorted(x0, x)
    index = clip(index, 1, size - 1)

    xi1 = [x[num] for num in index]
    xi0 = [x[num-1] for num in index]
    yi1 = [y[num] for num in index]
    yi0 = [y[num-1] for num in index]
    zi1 = [z[num] for num in index]
    zi0 = [z[num-1] for num in index]
    hi1 = list(map(subtract, xi1, xi0) )

    f0 = [0] * len(hi1)
    for j in range(len(f0)):
        f0[j] = round(
            zi0[j] / (6 * hi1[j]) * (xi1[j] - x0[j]) ** 3 + \
            zi1[j] / (6 * hi1[j]) * (x0[j] - xi0[j]) ** 3 + \
            (yi1[j] / hi1[j] - zi1[j] * hi1[j] / 6) * (x0[j] - xi0[j]) + \
            (yi0[j] / hi1[j] - zi0[j] * hi1[j] / 6) * (xi1[j] - x0[j])
            ,4
        )

    return f0