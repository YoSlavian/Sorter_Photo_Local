"""Structural BPMN rules.

Each rule is a small function over the model; the validator simply runs the
registry.  Keeping them separate makes the rule set reviewable — a modelling
guideline maps to exactly one function — and lets projects extend or disable
individual checks without forking the validator.

Severities follow one principle: an **error** means the file would be wrong or
unusable (an unreachable element, a start event with an inbound flow); a
**warning** means the diagram is valid but violates modelling convention (an
unnamed decision, an implicit split); an **info** points out something worth a
second look that is often entirely intentional.  Codes mirror that split:
``Exxx``, ``Wxxx``, ``Ixxx``.
"""

from __future__ import annotations

from collections.abc import Callable

from bpmn_architect.domain.model import GatewayDirection, NodeKind, ProcessModel
from bpmn_architect.validation.diagnostics import Diagnostics

__all__ = ["RULES", "Rule"]

Rule = Callable[[ProcessModel, Diagnostics], None]


def rule_has_start_event(model: ProcessModel, diagnostics: Diagnostics) -> None:
    if not model.start_events:
        diagnostics.error("E001", "the process has no start event")


def rule_has_end_event(model: ProcessModel, diagnostics: Diagnostics) -> None:
    if not model.end_events:
        diagnostics.error("E002", "the process has no end event")


def rule_all_reachable(model: ProcessModel, diagnostics: Diagnostics) -> None:
    starts = [node.id for node in model.start_events]
    if not starts:
        return
    reachable = model.reachable_from(starts)
    for node in model.nodes:
        if node.id not in reachable:
            diagnostics.error(
                "E003", f"{node.label!r} is not reachable from any start event", node.id
            )


def rule_no_dead_ends(model: ProcessModel, diagnostics: Diagnostics) -> None:
    ends = [node.id for node in model.end_events]
    if not ends:
        return
    productive = model.reaching(ends)
    for node in model.nodes:
        if node.id not in productive:
            diagnostics.error(
                "E004", f"no end event can be reached from {node.label!r}", node.id
            )


def rule_flow_node_connectivity(model: ProcessModel, diagnostics: Diagnostics) -> None:
    for node in model.nodes:
        if not node.kind.is_end and not model.outgoing(node.id):
            diagnostics.error("E005", f"{node.label!r} has no outgoing sequence flow", node.id)
        if not node.kind.is_start and not model.incoming(node.id):
            diagnostics.error("E006", f"{node.label!r} has no incoming sequence flow", node.id)


def rule_event_direction(model: ProcessModel, diagnostics: Diagnostics) -> None:
    for node in model.nodes:
        if node.kind.is_start and model.incoming(node.id):
            diagnostics.error(
                "E007", f"start event {node.label!r} must not have an incoming flow", node.id
            )
        if node.kind.is_end and model.outgoing(node.id):
            diagnostics.error(
                "E008", f"end event {node.label!r} must not have an outgoing flow", node.id
            )


def rule_default_flow_integrity(model: ProcessModel, diagnostics: Diagnostics) -> None:
    for node in model.nodes:
        defaults = [flow for flow in model.outgoing(node.id) if flow.is_default]
        if len(defaults) > 1:
            diagnostics.error(
                "E009", f"{node.label!r} declares {len(defaults)} default flows", node.id
            )
        if defaults and not node.kind.is_gateway:
            diagnostics.error(
                "E010", f"{node.label!r} is not a gateway and cannot own a default flow", node.id
            )


def rule_named_decisions(model: ProcessModel, diagnostics: Diagnostics) -> None:
    for node in model.nodes:
        if not node.kind.is_gateway:
            continue
        if (
            model.gateway_direction(node.id) is GatewayDirection.DIVERGING
            and not node.name
            and node.kind is not NodeKind.PARALLEL_GATEWAY
        ):
            diagnostics.warning(
                "W101",
                "a diverging gateway should be labelled with the question it answers",
                node.id,
            )


def rule_named_activities(model: ProcessModel, diagnostics: Diagnostics) -> None:
    for node in model.nodes:
        if node.kind.is_activity and not node.name:
            diagnostics.warning("W102", f"activity {node.id} has no name", node.id)


def rule_labelled_alternatives(model: ProcessModel, diagnostics: Diagnostics) -> None:
    for node in model.nodes:
        if node.kind not in {NodeKind.EXCLUSIVE_GATEWAY, NodeKind.INCLUSIVE_GATEWAY}:
            continue
        outgoing = model.outgoing(node.id)
        if len(outgoing) < 2:
            continue
        unlabelled = [flow for flow in outgoing if not flow.name and not flow.condition]
        if unlabelled:
            diagnostics.warning(
                "W103",
                f"{len(unlabelled)} alternative(s) leaving {node.label!r} carry neither a label "
                f"nor a condition",
                node.id,
            )


def rule_degenerate_gateways(model: ProcessModel, diagnostics: Diagnostics) -> None:
    for node in model.nodes:
        if not node.kind.is_gateway:
            continue
        if len(model.incoming(node.id)) <= 1 and len(model.outgoing(node.id)) <= 1:
            diagnostics.warning(
                "W104", f"gateway {node.label!r} neither splits nor merges the flow", node.id
            )


def rule_mixed_gateways(model: ProcessModel, diagnostics: Diagnostics) -> None:
    for node in model.nodes:
        if node.kind.is_gateway and model.gateway_direction(node.id) is GatewayDirection.MIXED:
            diagnostics.warning(
                "W105",
                f"gateway {node.label!r} splits and merges at once; split it into two gateways",
                node.id,
            )


def rule_implicit_branching(model: ProcessModel, diagnostics: Diagnostics) -> None:
    for node in model.nodes:
        if node.kind.is_gateway:
            continue
        if len(model.outgoing(node.id)) > 1:
            diagnostics.warning(
                "W106",
                f"{node.label!r} splits the flow implicitly; use a gateway instead",
                node.id,
            )
        if len(model.incoming(node.id)) > 1 and not node.kind.is_end:
            diagnostics.info(
                "I101", f"{node.label!r} merges several paths implicitly", node.id
            )


def rule_single_start(model: ProcessModel, diagnostics: Diagnostics) -> None:
    starts = model.start_events
    if len(starts) > 1:
        diagnostics.info(
            "I102",
            f"the process declares {len(starts)} start events; make sure that is intended",
            starts[0].id,
        )


def rule_lane_membership(model: ProcessModel, diagnostics: Diagnostics) -> None:
    if not model.has_lanes:
        return
    for node in model.nodes:
        if node.lane_id is None:
            diagnostics.warning(
                "W109", f"{node.label!r} does not belong to any lane", node.id
            )


#: Evaluation order is the reporting order for equal severities.
RULES: tuple[Rule, ...] = (
    rule_has_start_event,
    rule_has_end_event,
    rule_all_reachable,
    rule_no_dead_ends,
    rule_flow_node_connectivity,
    rule_event_direction,
    rule_default_flow_integrity,
    rule_named_decisions,
    rule_named_activities,
    rule_labelled_alternatives,
    rule_degenerate_gateways,
    rule_mixed_gateways,
    rule_implicit_branching,
    rule_single_start,
    rule_lane_membership,
)
