from collections import Counter
import json
from pathlib import Path
import re
from urllib.parse import urlsplit
import xml.etree.ElementTree as ET

from envaudit.arch import pyast
from envaudit.arch.context import ArchContext
from envaudit.arch.php_lexer import strip_php
from envaudit.core.runner import git


KEY = "langs"
ORDER = 75
PHP_EXTENSIONS = frozenset({".php"})
JS_EXTENSIONS = frozenset({".js", ".jsx", ".ts", ".tsx"})
CS_EXTENSIONS = frozenset({".cs"})
DATED_NAME = re.compile(
    r"(?<!\d)20\d{2}[-_.]?(?:0[1-9]|1[0-2])[-_.]?(?:0[1-9]|[12]\d|3[01])(?!\d)"
)
HOST_MARKERS = (
    rb"\bCCrmDeal\b",
    rb"\\Bitrix\\Main\b",
    rb"\bCModule\b",
    rb"\$USER\b",
    rb"\$DB\b",
    rb"\bgetConnection\b",
    rb"\bCIBlock\b",
)
PRIMITIVE_TYPES = frozenset(
    {
        "bool",
        "byte",
        "sbyte",
        "short",
        "ushort",
        "int",
        "uint",
        "long",
        "ulong",
        "nint",
        "nuint",
        "float",
        "double",
        "decimal",
        "char",
        "string",
        "object",
        "cancellationtoken",
    }
)


def _lines(data: bytes) -> int:
    return data.count(b"\n") + (1 if data and not data.endswith(b"\n") else 0)


def _read(actx: ArchContext, entry, limit: int = 20 * 1024 * 1024) -> bytes | None:
    return actx.read(entry, max_bytes=limit)


def _literal_share(data: bytes) -> float:
    lines = [line.strip() for line in data.splitlines() if line.strip()]
    if not lines:
        return 0.0
    literal = sum(
        line[:1] in {b"'", b'"', b"[", b"{", b"(", b"]", b"}"}
        or line[:1].isdigit()
        or b"=>" in line
        for line in lines
    )
    return literal / len(lines)


def _html_share(data: bytes) -> float:
    html_lines = set()
    nonempty_lines = {
        index for index, line in enumerate(data.splitlines(), 1) if line.strip()
    }
    position = 0
    line = 1
    in_php = False
    while position < len(data):
        if data[position] == 10:
            line += 1
            position += 1
            continue
        if not in_php and data.startswith(b"<?", position):
            in_php = True
            position += 2
            continue
        if in_php and data.startswith(b"?>", position):
            in_php = False
            position += 2
            continue
        if not in_php and chr(data[position]).strip():
            html_lines.add(line)
        position += 1
    return len(html_lines) / len(nonempty_lines) if nonempty_lines else 0.0


def _component(rel: str) -> str:
    parts = Path(rel).parts
    return parts[0] if len(parts) > 1 else "."


def _churn_share(actx: ArchContext, rel: str) -> float | None:
    churn = actx.churn()
    if churn is None or rel not in churn:
        return None
    tree = actx.out.get("tree", {})
    ref = tree.get("head") if isinstance(tree, dict) else None
    if not isinstance(ref, str):
        return None
    component = _component(rel)
    cache_key = f"lang_component_commits:{ref}:{component}"
    cached = actx.cache.get(cache_key)
    if isinstance(cached, int):
        total = cached
    else:
        result = git(
            actx.root,
            "rev-list",
            "--count",
            ref,
            "--",
            component,
            timeout=120,
        )
        if result.rc != 0:
            return None
        try:
            total = int(result.stdout.strip())
        except ValueError:
            return None
        actx.cache[cache_key] = total
    return round(churn[rel][1] / total, 6) if total else None


def _php_metrics(actx: ArchContext) -> dict | None:
    entries = actx.code_files(exts=PHP_EXTENSIONS)
    if not entries:
        return None
    records = []
    prod_lines = 0
    templates = []
    candidates = []
    bootstrap_refs = 0
    prod_paths = set()
    for entry in entries:
        data = _read(actx, entry)
        if data is None:
            continue
        lines = _lines(data)
        if actx.is_prod_path(entry.rel):
            prod_lines += lines
            prod_paths.add(entry.rel)
        stripped = strip_php(data)
        all_functions = len(
            re.findall(
                rb"\bfunction\s+(?:&\s*)?[A-Za-z_]\w*\s*\(",
                stripped,
                re.IGNORECASE,
            )
        )
        php_text = stripped.decode("utf-8", "replace")
        class_matches = list(re.finditer(r"\bclass\s+[A-Za-z_]\w*", php_text, re.IGNORECASE))
        methods = 0
        for class_match in class_matches:
            brace = php_text.find("{", class_match.end())
            end = _matching_brace(php_text, brace) if brace >= 0 else len(php_text)
            methods += len(
                re.findall(
                    r"\bfunction\s+(?:&\s*)?[A-Za-z_]\w*\s*\(",
                    php_text[brace:end],
                    re.IGNORECASE,
                )
            )
        functions = max(0, all_functions - methods)
        classes = len(class_matches)
        host_markers = sum(len(re.findall(pattern, stripped)) for pattern in HOST_MARKERS)
        curl_calls = len(re.findall(rb"\bcurl_init\s*\(", stripped, re.IGNORECASE))
        sql_calls = len(re.findall(rb"->\s*query\s*\(", stripped, re.IGNORECASE)) + len(
            re.findall(rb"\bgetConnection\s*\(", stripped)
        )
        data_shaped = _literal_share(stripped) >= 0.8
        if _html_share(data) >= 0.5:
            templates.append(entry.rel)
        records.append(
            {
                "path": entry.rel,
                "lines": lines,
                "functions": functions,
                "classes": classes,
                "methods": methods,
                "share_of_prod": 0.0,
                "host_markers": host_markers,
                "curl_calls": curl_calls,
                "sql_calls": sql_calls,
                "data_shaped": data_shaped,
                "churn": None,
            }
        )
        if lines > 800 or functions > 40:
            candidates.append(entry.rel)
        bootstrap_refs += len(
            re.findall(
                rb"\b(?:require|require_once|include|include_once)\b[^;\n]*"
                rb"(?:prolog_before\.php|header\.php)",
                data,
                re.IGNORECASE,
            )
        )
    for record in records:
        record["share_of_prod"] = (
            round(record["lines"] / prod_lines, 6)
            if prod_lines and record["path"] in prod_paths
            else 0.0
        )
    records.sort(key=lambda item: (-item["lines"], item["path"]))
    for record in records[:20]:
        record["churn"] = _churn_share(actx, record["path"])
    runtime = actx.out.get("runtime", {})
    anchors = runtime.get("anchors", []) if isinstance(runtime, dict) else []
    entrypoints = sorted(
        {
            item["entry"]
            for item in anchors
            if isinstance(item, dict)
            and item.get("kind") == "php_host_plugin"
            and isinstance(item.get("entry"), str)
        }
    )
    a11 = actx.rule_inputs.setdefault("A11", {})
    a11["php"] = {"candidates": sorted(candidates)}
    return {
        "files": len(entries),
        "prod_lines": prod_lines,
        "templates": sorted(templates),
        "files_top": records[:20],
        "entrypoints": entrypoints,
        "bootstrap_single": bootstrap_refs == 1,
    }


def _relative_imports(data: bytes) -> int:
    patterns = (
        rb"\b(?:import|export)\b[^;\n]*?\bfrom\s*['\"]\.",
        rb"\bimport\s*\(\s*['\"]\.",
        rb"\brequire\s*\(\s*['\"]\.",
        rb"^\s*import\s*['\"]\.",
    )
    return sum(len(re.findall(pattern, data, re.MULTILINE)) for pattern in patterns)


def _urls(value: object) -> list[str]:
    output = []
    if isinstance(value, dict):
        for name, item in value.items():
            if name == "url" and isinstance(item, str):
                host = urlsplit(item).hostname
                if host:
                    output.append(host)
            else:
                output.extend(_urls(item))
    elif isinstance(value, list):
        for item in value:
            output.extend(_urls(item))
    return output


def _n8n_workflows(actx: ArchContext) -> list[dict]:
    output = []
    for entry in actx.files():
        if Path(entry.rel).suffix.lower() != ".json":
            continue
        data = _read(actx, entry)
        if data is None:
            continue
        try:
            document = json.loads(data)
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        if not isinstance(document, dict) or not isinstance(document.get("nodes"), list) or "connections" not in document:
            continue
        nodes = document["nodes"]
        kinds = Counter(
            str(node.get("type"))
            for node in nodes
            if isinstance(node, dict) and isinstance(node.get("type"), str)
        )
        hosts = []
        for node in nodes:
            if isinstance(node, dict):
                hosts.extend(_urls(node.get("parameters", {})))
        output.append(
            {
                "path": entry.rel,
                "nodes": len(nodes),
                "node_types": [
                    {"type": name, "count": count}
                    for name, count in sorted(kinds.items(), key=lambda item: (-item[1], item[0]))[:10]
                ],
                "url_hosts": sorted(set(hosts)),
            }
        )
    return sorted(output, key=lambda item: item["path"])


def _js_metrics(actx: ArchContext) -> dict | None:
    entries = actx.code_files(exts=JS_EXTENSIONS)
    workflows = _n8n_workflows(actx)
    if not entries and not workflows:
        return None
    lines = 0
    relative_edges = 0
    dated = 0
    for entry in entries:
        data = _read(actx, entry)
        if data is None:
            continue
        lines += _lines(data)
        relative_edges += _relative_imports(data)
        dated += int(DATED_NAME.search(Path(entry.rel).name) is not None)
    return {
        "files": len(entries),
        "lines": lines,
        "dated_share": round(dated / len(entries), 6) if entries else 0.0,
        "relative_import_edges": relative_edges,
        "n8n_workflows": workflows,
    }


def _xml_text(root: ET.Element, name: str) -> str | None:
    for element in root.iter():
        if element.tag.rsplit("}", 1)[-1] == name and element.text:
            return element.text.strip()
    return None


def _project(entry, data: bytes) -> dict | None:
    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        return None
    packages = sorted(
        {
            str(element.attrib["Include"])
            for element in root.iter()
            if element.tag.rsplit("}", 1)[-1] == "PackageReference"
            and isinstance(element.attrib.get("Include"), str)
        }
    )
    is_test = "Microsoft.NET.Test.Sdk" in packages or (_xml_text(root, "IsTestProject") or "").lower() == "true"
    return {
        "path": entry.rel,
        "output_type": _xml_text(root, "OutputType"),
        "use_wpf": (_xml_text(root, "UseWPF") or "").lower() == "true",
        "target_framework": _xml_text(root, "TargetFramework") or _xml_text(root, "TargetFrameworks"),
        "package_references": packages,
        "test_sdk": is_test,
    }


def _matching_brace(text: str, start: int) -> int:
    depth = 0
    for position in range(start, len(text)):
        if text[position] == "{":
            depth += 1
        elif text[position] == "}":
            depth -= 1
            if depth == 0:
                return position + 1
    return len(text)


def _split_parameters(value: str) -> list[str]:
    output = []
    start = 0
    depth = 0
    for position, character in enumerate(value):
        if character in "<([":
            depth += 1
        elif character in ">)]":
            depth = max(0, depth - 1)
        elif character == "," and depth == 0:
            output.append(value[start:position])
            start = position + 1
    output.append(value[start:])
    return [item.strip() for item in output if item.strip()]


def _nonprimitive_parameters(body: str, class_name: str) -> int:
    match = re.search(
        rf"\b(?:public|internal|protected|private)\s+{re.escape(class_name)}\s*\((.*?)\)",
        body,
        re.DOTALL,
    )
    if match is None:
        return 0
    count = 0
    for parameter in _split_parameters(match.group(1)):
        cleaned = re.sub(r"\[[^\]]*\]", " ", parameter).split("=", 1)[0].strip()
        words = [word for word in cleaned.split() if word not in {"ref", "out", "in", "params", "this"}]
        if len(words) < 2:
            continue
        type_name = words[-2].rstrip("?").split(".")[-1].lower()
        count += int(type_name not in PRIMITIVE_TYPES)
    return count


def _class_records(actx: ArchContext, entry, data: bytes) -> list[dict]:
    text = data.decode("utf-8", "replace")
    output = []
    for match in re.finditer(r"\bclass\s+([A-Za-z_]\w*)", text):
        class_name = match.group(1)
        brace = text.find("{", match.end())
        end = _matching_brace(text, brace) if brace >= 0 else len(text)
        start = match.start()
        body = text[start:end]
        lines = body.count("\n") + (1 if body and not body.endswith("\n") else 0)
        methods = len(
            re.findall(
                r"\b(?:public|internal|protected|private)\s+(?:static\s+|async\s+|virtual\s+|override\s+|sealed\s+)*"
                r"[A-Za-z_][\w<>,.?\[\]]*\s+[A-Za-z_]\w*\s*\(",
                body,
            )
        )
        bindables = len(re.findall(r"\{\s*get\s*;[^}]*\bset\s*;\s*\}", body)) + len(
            re.findall(r"\[ObservableProperty\]", body)
        )
        output.append(
            {
                "path": entry.rel,
                "class": class_name,
                "lines": lines,
                "methods_approx": methods,
                "ctor_params_nonprimitive": _nonprimitive_parameters(body, class_name),
                "bindables": bindables,
                "churn": None,
            }
        )
    return output


def _csharp_metrics(actx: ArchContext) -> dict | None:
    cs_entries = actx.code_files(exts=CS_EXTENSIONS)
    xaml_entries = [entry for entry in actx.files() if Path(entry.rel).suffix.lower() == ".xaml"]
    project_entries = [entry for entry in actx.files() if Path(entry.rel).suffix.lower() == ".csproj"]
    solutions = sorted(entry.rel for entry in actx.files() if Path(entry.rel).suffix.lower() == ".sln")
    if not cs_entries and not xaml_entries and not project_entries and not solutions:
        return None
    projects = []
    for entry in project_entries:
        data = _read(actx, entry)
        record = _project(entry, data) if data is not None else None
        if record is None:
            actx.error(KEY, "csproj_parse")
        else:
            projects.append(record)
    classes = []
    for entry in cs_entries:
        data = _read(actx, entry)
        if data is not None:
            classes.extend(_class_records(actx, entry, data))
    classes.sort(key=lambda item: (-item["lines"], item["class"], item["path"]))
    churn_by_path = {}
    for item in [*classes[:20], *(item for item in classes if item["lines"] > 800)]:
        if item["path"] not in churn_by_path:
            churn_by_path[item["path"]] = _churn_share(actx, item["path"])
        item["churn"] = churn_by_path[item["path"]]
    csharp_g = [
        {
            "class": item["class"],
            "lines": item["lines"],
            "ctor_params_nonprimitive": item["ctor_params_nonprimitive"],
            "churn_share": item["churn"],
        }
        for item in classes
        if item["lines"] > 800
    ]
    a11 = actx.rule_inputs.setdefault("A11", {})
    a11["csharp_g"] = csharp_g
    dictionaries = 0
    for entry in xaml_entries:
        data = _read(actx, entry)
        if data is not None:
            dictionaries += len(re.findall(rb"<\s*ResourceDictionary\b", data))
    return {
        "solutions": solutions,
        "projects": sorted(projects, key=lambda item: item["path"]),
        "classes_top": classes[:20],
        "xaml": {"files": len(xaml_entries), "resource_dictionaries": dictionaries},
    }


def _language_lines(actx: ArchContext, language: str, fallback: int) -> int:
    size = actx.out.get("size", {})
    by_language = size.get("by_language", {}) if isinstance(size, dict) else {}
    metric = by_language.get(language, {}) if isinstance(by_language, dict) else {}
    value = metric.get("prod_sloc") if isinstance(metric, dict) else None
    return value if isinstance(value, int) and value > 0 else fallback


def run(actx: ArchContext) -> None:
    php = _php_metrics(actx)
    js = _js_metrics(actx)
    csharp = _csharp_metrics(actx)
    if php is not None:
        actx.out["php"] = php
    if js is not None:
        actx.out["js"] = js
    if csharp is not None:
        actx.out["csharp"] = csharp

    size = actx.out.get("size", {})
    by_language = size.get("by_language", {}) if isinstance(size, dict) else {}
    total = 0
    if isinstance(by_language, dict):
        total = sum(
            metric.get("prod_sloc", 0)
            for metric in by_language.values()
            if isinstance(metric, dict) and isinstance(metric.get("prod_sloc"), int)
        )
    xaml_lines = 0
    if csharp is not None:
        for entry in actx.files():
            if Path(entry.rel).suffix.lower() == ".xaml":
                data = _read(actx, entry)
                if data is not None:
                    xaml_lines += _lines(data)
        total += xaml_lines

    language_values = []
    if php is not None:
        php_lines = _language_lines(actx, "php", php["prod_lines"])
        if php_lines:
            language_values.append(("php", php_lines, "dynamic_calls_host_runtime"))
    if js is not None:
        js_lines = _language_lines(actx, "js_ts", js["lines"])
        if js_lines or js["n8n_workflows"]:
            language_values.append(("js", max(js_lines, len(js["n8n_workflows"])), "bundler_tsconfig_dynamic_import_voximplant"))
    if csharp is not None:
        cs_lines = _language_lines(actx, "csharp", sum(item["lines"] for item in csharp["classes_top"])) + xaml_lines
        if cs_lines:
            language_values.append(("csharp", cs_lines, "semantic_graph_partial_di_bindings_generators"))
    for language, lines, specific in language_values:
        share = round(lines / total, 6) if total else 0.0
        actx.blind_spot(language, share, specific)
        actx.blind_spot(language, share, "graph_not_in_v3")
        if share > 0.5:
            actx.blind_spot(language, share, "majority_language_metrics_only")
