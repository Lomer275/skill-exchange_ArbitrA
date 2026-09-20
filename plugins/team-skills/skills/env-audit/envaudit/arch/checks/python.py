from envaudit.arch.context import ArchContext
from envaudit.arch.py import (
    channels,
    config,
    conventions,
    dups,
    god,
    graph as graph_module,
    layers,
    orphans,
    tests as tests_module,
)


KEY = "python"
ORDER = 70
RULES = tuple(f"A{number}" for number in range(9, 22))


def _budget(actx: ArchContext, rule: str) -> bool:
    if not actx.ctx.expired():
        return True
    actx.rule_inputs.setdefault(rule, {"skipped": "budget"})
    actx.skip(KEY, "budget", rule)
    actx.ctx.mark_truncated()
    return False


def _metrics_only(actx: ArchContext, rule: str) -> None:
    classification = actx.out.get("classification")
    if isinstance(classification, dict) and classification.get("size_tier") == "S":
        actx.rule_inputs.setdefault(rule, {})["metrics_only"] = True


def _parse_errors(actx: ArchContext) -> list[dict]:
    errors = actx.cache.get("parse_errors", [])
    if not isinstance(errors, list):
        return []
    unique = {}
    for item in errors:
        if not isinstance(item, dict):
            continue
        key = (item.get("path"), item.get("kind"), item.get("line"))
        unique[key] = {
            "path": item.get("path"),
            "kind": item.get("kind"),
            "line": item.get("line"),
        }
    return [unique[key] for key in sorted(unique, key=lambda value: tuple(str(item) for item in value))]


def _rankings(graph: graph_module.Graph) -> tuple[list[dict], list[dict]]:
    fan_in = []
    fan_out = []
    for name, item in graph.modules.items():
        if not item.prod or name in graph.package_nodes:
            continue
        incoming = {
            edge.source
            for edge in graph.edges
            if edge.target == name
            and graph.modules[edge.source].prod
            and edge.source not in graph.package_nodes
            and not edge.type_checking
        }
        outgoing = {
            edge.target
            for edge in graph.edges
            if edge.source == name
            and graph.modules[edge.target].prod
            and edge.target not in graph.package_nodes
            and not edge.type_checking
        }
        if incoming:
            fan_in.append({"path": item.path, "fan_in": len(incoming)})
        if outgoing:
            fan_out.append({"path": item.path, "fan_out": len(outgoing)})
    fan_in.sort(key=lambda row: (-row["fan_in"], row["path"]))
    fan_out.sort(key=lambda row: (-row["fan_out"], row["path"]))
    return fan_in[:30], fan_out[:30]


def _not_applicable(actx: ArchContext, graph: graph_module.Graph) -> None:
    test_metrics = tests_module.analyse(actx, graph)
    test_rule = test_metrics.pop("rule")
    disabled = {"applicable": False}
    actx.out[KEY] = {
        "modules": len(graph.modules),
        "parse_errors": _parse_errors(actx),
        "modules_top": [
            {
                "path": item.path,
                "lines": item.lines,
                "sloc": item.sloc,
                "sloc_no_strings": item.sloc_no_strings,
            }
            for item in sorted(
                graph.modules.values(), key=lambda item: (-item.sloc_no_strings, item.path)
            )[:30]
        ],
        "tests": test_metrics,
        "edges": disabled,
        "scc": disabled,
        "duplicates": disabled,
        "orphans": disabled,
        "channels": disabled,
        "layers": disabled,
        "config": disabled,
    }
    for rule in RULES[:-1]:
        actx.rule_inputs[rule] = {"applicable": False}
        actx.skip(KEY, "not_applicable", rule)
    actx.rule_inputs["A21"] = {
        **test_rule,
        "files": test_metrics["files"],
        "lines": test_metrics["lines"],
        "collected": test_metrics["collected"],
        "collect_errors": test_metrics["collect_errors"],
        "components_without_tests": len(test_metrics["components_without_tests"]),
    }


def run(actx: ArchContext) -> None:
    python_entries = actx.code_files(exts=frozenset({".py"}))
    if not python_entries:
        actx.out[KEY] = {
            "modules": 0,
            "parse_errors": [],
            "tests": {"files": 0, "lines": 0, "collected": None, "collect_errors": 0, "components_without_tests": []},
            "applicable": False,
        }
        for rule in RULES:
            actx.rule_inputs[rule] = {"applicable": False}
        return

    graph = graph_module.build(actx)
    classification = actx.out.get("classification", {})
    project_type = classification.get("type") if isinstance(classification, dict) else None
    if project_type in {"integration-scripts", "mixed", "docs"}:
        _not_applicable(actx, graph)
        return

    output = {
        "modules": len(graph.modules),
        "parse_errors": _parse_errors(actx),
    }

    if _budget(actx, "A9"):
        output["edges"] = graph_module.edge_counts(graph)
        output["package_edges"] = graph_module.package_edges(graph)
        actx.rule_inputs["A9"] = dict(output["edges"])
        _metrics_only(actx, "A9")

    if _budget(actx, "A10"):
        cycle_data = graph_module.cycles(graph)
        output["scc"] = cycle_data
        module_scc = cycle_data["module_level"]
        actx.rule_inputs["A10"] = {
            "cross_package_module_scc": sum(item["crosses_packages"] for item in module_scc),
            "in_package_module_scc": sum(not item["crosses_packages"] for item in module_scc),
        }
        _metrics_only(actx, "A10")

    # Layers are shared inputs for A11, A16, and A17; their own A19 output is
    # emitted in rule order below.
    layer_data = layers.analyse(actx, graph) if not actx.ctx.expired() else None
    modules_top = None
    longest = None

    if _budget(actx, "A11"):
        modules_top, longest, god_rule = god.analyse(
            actx,
            graph,
            layer_data["direct_io"] if layer_data else {},
            bool(layer_data and layer_data["project_has_adapters"]),
        )
        output["modules_top"] = modules_top
        actx.rule_inputs["A11"] = god_rule
        _metrics_only(actx, "A11")

    if _budget(actx, "A12"):
        if longest is None:
            modules_top, longest, _ = god.analyse(
                actx,
                graph,
                layer_data["direct_io"] if layer_data else {},
                bool(layer_data and layer_data["project_has_adapters"]),
            )
            output.setdefault("modules_top", modules_top)
        output["longest_functions"] = longest
        actx.rule_inputs["A12"] = {"longest_functions": longest}
        _metrics_only(actx, "A12")

    if _budget(actx, "A13"):
        fan_in, fan_out = _rankings(graph)
        output["fan_in_top"] = fan_in
        output["fan_out_top"] = fan_out
        actx.rule_inputs["A13"] = {
            "fan_in_top": fan_in,
            "fan_out_top": fan_out,
        }
        _metrics_only(actx, "A13")

    orphan_rows = []
    orphan_by_path = {}
    orphans_computed = False
    if _budget(actx, "A14"):
        orphan_rows, orphan_by_path = orphans.analyse(actx, graph)
        orphans_computed = True
        duplicate_data, duplicate_rule = dups.analyse(actx, graph, orphan_by_path)
        output["duplicates"] = duplicate_data
        actx.rule_inputs["A14"] = duplicate_rule
        _metrics_only(actx, "A14")

    if _budget(actx, "A15"):
        if not orphans_computed:
            orphan_rows, orphan_by_path = orphans.analyse(actx, graph)
            orphans_computed = True
        output["orphans"] = orphan_rows
        branch_stats = actx.cache.get("python_orphan_branch_stats", {})
        actx.rule_inputs["A15"] = {
            "orphans": len(orphan_rows),
            "test_only": sum(item["class"] == "test_only" for item in orphan_rows),
            "shadowed": actx.rule_inputs.get("A14", {}).get("same_basename_shadowed", 0),
            "branches_checked": branch_stats.get("checked", 0) if isinstance(branch_stats, dict) else 0,
            "branches_total": branch_stats.get("total", 0) if isinstance(branch_stats, dict) else 0,
        }
        _metrics_only(actx, "A15")

    channel_result = None
    if _budget(actx, "A16"):
        direct_io = layer_data["direct_io"] if layer_data else {}
        assignment = layer_data["layers"]["assignment"] if layer_data else {}
        channel_result = channels.analyse(actx, graph, direct_io, assignment)
        output["channels"] = channel_result[0]
        output["interface_to_client_edges"] = channel_result[1]
        output["runtime_to_tools_edges"] = channel_result[2]
        actx.rule_inputs["A16"] = channel_result[3]
        _metrics_only(actx, "A16")

    if _budget(actx, "A17"):
        if channel_result is None:
            direct_io = layer_data["direct_io"] if layer_data else {}
            assignment = layer_data["layers"]["assignment"] if layer_data else {}
            channel_result = channels.analyse(actx, graph, direct_io, assignment)
            output["channels"] = channel_result[0]
            output["interface_to_client_edges"] = channel_result[1]
            output["runtime_to_tools_edges"] = channel_result[2]
        actx.rule_inputs["A17"] = channel_result[4]
        _metrics_only(actx, "A17")

    if _budget(actx, "A18"):
        assignment = layer_data["layers"]["assignment"] if layer_data else {}
        convention_data, convention_rule = conventions.analyse(graph, assignment)
        output["framework_conventions"] = convention_data
        actx.rule_inputs["A18"] = convention_rule
        _metrics_only(actx, "A18")

    if _budget(actx, "A19"):
        if layer_data is None:
            layer_data = layers.analyse(actx, graph)
        output.update(
            {
                "fn_layers": layer_data["fn_layers"],
                "layers": layer_data["layers"],
                "layer_edges": layer_data["layer_edges"],
                "framework_libs": layer_data["framework_libs"],
                "core_io": layer_data["core_io"],
            }
        )
        actx.rule_inputs["A19"] = {
            "declared": layer_data["layers"]["source"] == "audit_json",
            "core_io_modules": len(layer_data["core_io"]),
            "layer_edges": len(layer_data["layer_edges"]),
            "io_list_size": layer_data["framework_libs"]["io_list_size"],
        }
        _metrics_only(actx, "A19")

    if _budget(actx, "A20"):
        config_data, config_rule = config.analyse(actx, graph)
        output["config"] = config_data
        actx.rule_inputs["A20"] = config_rule
        _metrics_only(actx, "A20")

    if _budget(actx, "A21"):
        test_data = tests_module.analyse(actx, graph)
        test_rule = test_data.pop("rule")
        output["tests"] = test_data
        actx.rule_inputs["A21"] = {
            **test_rule,
            "files": test_data["files"],
            "lines": test_data["lines"],
            "collected": test_data["collected"],
            "collect_errors": test_data["collect_errors"],
            "components_without_tests": len(test_data["components_without_tests"]),
        }
    actx.out[KEY] = output
