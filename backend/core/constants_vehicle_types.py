from __future__ import annotations

from typing import Iterable

VEHICLE_LIBRARY_SOURCES_BY_TYPE: dict[str, tuple[str, ...]] = {
    "incendie": ("remise",),
    "secours_a_personne": ("pharmacy",),
}


def resolve_vehicle_library_sources(vehicle_types: Iterable[str]) -> list[str]:
    sources: list[str] = []
    seen: set[str] = set()
    for vehicle_type in vehicle_types:
        for source in VEHICLE_LIBRARY_SOURCES_BY_TYPE.get(vehicle_type, ()):
            if source in seen:
                continue
            seen.add(source)
            sources.append(source)
    return sources
