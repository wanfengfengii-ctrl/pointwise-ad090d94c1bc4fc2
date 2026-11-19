from collections.abc import Sequence
from fractions import Fraction


class SingularSystemError(ValueError):
    pass


def _exact(value: int | Fraction) -> Fraction:
    if type(value) is not int and not isinstance(value, Fraction):
        raise ValueError('linear system requires exact coefficients')
    return Fraction(value)


def solve_exact_system(
    matrix: Sequence[Sequence[int | Fraction]], rhs: Sequence[int | Fraction]
) -> tuple[Fraction, ...]:
    size = len(matrix)
    if len(rhs) != size or any(len(row) != size for row in matrix):
        raise ValueError('linear system dimensions disagree')
    augmented = [list(map(_exact, row)) + [_exact(term)] for row, term in zip(matrix, rhs)]
    for column in range(size):
        pivot = next((row for row in range(column, size) if augmented[row][column]), None)
        if pivot is None:
            raise SingularSystemError('linear system has no unique solution')
        augmented[column], augmented[pivot] = augmented[pivot], augmented[column]
        divisor = augmented[column][column]
        base = [entry / divisor for entry in augmented[column]]
        augmented[column] = base
        for row in range(size):
            if row == column or not augmented[row][column]:
                continue
            factor = augmented[row][column]
            augmented[row] = [value - factor * entry for value, entry in zip(augmented[row], base)]
    return tuple(row[-1] for row in augmented)
