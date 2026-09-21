from typing import TypeVar

T = TypeVar("T")


def paginate(items: list[T], page: int, page_size: int) -> tuple[list[T], int]:
    total = len(items)
    start = (page - 1) * page_size
    return items[start : start + page_size], total
