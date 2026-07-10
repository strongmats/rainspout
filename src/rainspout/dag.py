"""DAG machinery: general graph resolution plus the separate v1 linearity rule.

The graph code is deliberately general (topological sort over arbitrary
acyclic `from:` wiring) so branching later is a non-breaking addition; the
v1 restriction to a single linear chain is a distinct, loud check layered on
top, not an assumption baked into the machinery.
"""

from __future__ import annotations

from collections.abc import Mapping

from .errors import ConfigError


def topological_order(edges: Mapping[str, tuple[str, ...]]) -> tuple[str, ...]:
    """Order nodes so every node follows all its inputs; cycles fail loudly.

    ``edges`` maps each node to the nodes it consumes (its ``from:`` inputs);
    inputs that are not themselves keys (e.g. the seed) are treated as
    already-satisfied roots.
    """
    remaining = {node: {src for src in sources if src in edges} for node, sources in edges.items()}
    order: list[str] = []
    while remaining:
        ready = sorted(node for node, sources in remaining.items() if not sources)
        if not ready:
            cycle = ", ".join(sorted(remaining))
            raise ConfigError(f"the stage graph has a cycle among: {cycle}")
        for node in ready:
            del remaining[node]
            order.append(node)
        for sources in remaining.values():
            sources.difference_update(ready)
    return tuple(order)


def assert_linear_chain(
    seed_name: str,
    stage_from_edges: Mapping[str, tuple[str, ...]],
) -> None:
    """v1 rule: the `from:` wiring forms one chain seed -> stage -> ... -> stage.

    Every stage consumes exactly one upstream, every producer (seed or stage)
    feeds at most one stage, and every stage is reachable from the seed.
    """
    for stage, sources in stage_from_edges.items():
        if len(sources) != 1:
            raise ConfigError(
                f"stage '{stage}' has {len(sources)} `from:` inputs; in v1 every stage "
                "consumes exactly one upstream (branching/fan-in is not supported in v1)"
            )
    consumers: dict[str, list[str]] = {}
    for stage, sources in stage_from_edges.items():
        consumers.setdefault(sources[0], []).append(stage)
    for producer, consumed_by in consumers.items():
        if len(consumed_by) > 1:
            raise ConfigError(
                f"'{producer}' feeds {sorted(consumed_by)}; in v1 an output feeds at most "
                "one stage (branching/fan-in is not supported in v1)"
            )
    # walk the chain from the seed; it must visit every stage
    visited: list[str] = []
    current = seed_name
    while current in consumers:
        current = consumers[current][0]
        visited.append(current)
    unreached = set(stage_from_edges) - set(visited)
    if unreached:
        raise ConfigError(
            f"stages not reachable from the seed '{seed_name}' via `from:` wiring: "
            f"{sorted(unreached)} (in v1 all stages form one chain rooted at the seed)"
        )
