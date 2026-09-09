"""Stable IDs for managed Qdrant chunk records."""


def revision_record_ids(revision_id, count):
    return [f"{revision_id}-{number:06d}" for number in range(count)]
