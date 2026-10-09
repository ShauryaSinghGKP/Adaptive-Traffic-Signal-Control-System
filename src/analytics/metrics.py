"""Consistent simulation-level metric calculations."""

from pathlib import Path
import xml.etree.ElementTree as ET


def tripinfo_metrics(path: Path) -> tuple[float, int]:
    values = [float(node.attrib["waitingTime"]) for node in ET.parse(path).getroot().findall("tripinfo")]
    return (sum(values) / len(values) if values else 0.0, len(values))


def queue_metrics(samples: list[list[int]]) -> tuple[float, int]:
    if not samples:
        return 0.0, 0
    flattened = [value for sample in samples for value in sample]
    return sum(flattened) / len(flattened), max(flattened, default=0)
