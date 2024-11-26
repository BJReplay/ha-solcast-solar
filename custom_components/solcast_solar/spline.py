"""Cubic spline from one-dimensional arrays."""

# pylint: disable=consider-using-enumerate

from __future__ import annotations

import math


def cubic_interp(x0: list, x: list, y: list) -> list:
    """Build a cubic spline.

    Arguments:
        x0 (list): List of floats to interpolate at
        x (list): List of floats in increasing order
        y (list): List of floats to interpolate

    Returns:
        list: Array of interpolated values.

    """

    def diff(lst: list):  # numpy-like diff
        size = len(lst) - 1
        r = [0] * size
        for i in range(size):
            r[i] = lst[i + 1] - lst[i]
        return r

    def clip(lst: list, min_val: float, max_val: float, in_place: bool = False):  # numpy-like clip
        if not in_place:
            lst = lst[:]
        for i in range(len(lst)):
            if lst[i] < min_val:
                lst[i] = min_val
            elif lst[i] > max_val:
                lst[i] = max_val
        return lst

    def search_sorted(list_to_insert: list, insert_into: list):  # numpy-like search_sorted
        def float_search_sorted(float_to_insert, insert_into):
            for i in range(len(insert_into)):
                if float_to_insert <= insert_into[i]:
                    return i
            return len(insert_into)

        return [float_search_sorted(i, insert_into) for i in list_to_insert]

    def subtract(a: float, b: float):
        return a - b

    size = len(x)
    x_diff = diff(x)
    y_diff = diff(y)

    li = [0] * size
    li_1 = [0] * (size - 1)
    z = [0] * (size)

    li[0] = math.sqrt(2 * x_diff[0])
    li_1[0] = 0.0
    b0 = 0.0
    z[0] = b0 / li[0]

    for i in range(1, size - 1, 1):
        li_1[i] = x_diff[i - 1] / li[i - 1]
        li[i] = math.sqrt(2 * (x_diff[i - 1] + x_diff[i]) - li_1[i - 1] * li_1[i - 1])
        bi = 6 * (y_diff[i] / x_diff[i] - y_diff[i - 1] / x_diff[i - 1])
        z[i] = (bi - li_1[i - 1] * z[i - 1]) / li[i]

    i = size - 1
    li_1[i - 1] = x_diff[-1] / li[i - 1]
    li[i] = math.sqrt(2 * x_diff[-1] - li_1[i - 1] * li_1[i - 1])
    bi = 0.0
    z[i] = (bi - li_1[i - 1] * z[i - 1]) / li[i]

    i = size - 1
    z[i] = z[i] / li[i]
    for i in range(size - 2, -1, -1):
        z[i] = (z[i] - li_1[i - 1] * z[i + 1]) / li[i]

    index = search_sorted(x0, x)
    index = clip(index, 1, size - 1)

    xi1 = [x[num] for num in index]
    xi0 = [x[num - 1] for num in index]
    yi1 = [y[num] for num in index]
    yi0 = [y[num - 1] for num in index]
    zi1 = [z[num] for num in index]
    zi0 = [z[num - 1] for num in index]
    hi1 = list(map(subtract, xi1, xi0))

    f0 = [0] * len(hi1)
    for j in range(len(f0)):
        f0[j] = round(
            zi0[j] / (6 * hi1[j]) * (xi1[j] - x0[j]) ** 3
            + zi1[j] / (6 * hi1[j]) * (x0[j] - xi0[j]) ** 3
            + (yi1[j] / hi1[j] - zi1[j] * hi1[j] / 6) * (x0[j] - xi0[j])
            + (yi0[j] / hi1[j] - zi0[j] * hi1[j] / 6) * (xi1[j] - x0[j]),
            4,
        )

    return f0
