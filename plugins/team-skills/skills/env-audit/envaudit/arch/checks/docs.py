from envaudit.arch.context import ArchContext
from envaudit.arch.docs import agent_documents
from envaudit.arch.docs import claims, freshness, mdcode, paths, specs


KEY = "docs"
ORDER = 80


def run(actx: ArchContext) -> None:
    documents = agent_documents(actx)
    missing = paths.missing_paths(actx, documents)
    stack = claims.stack_contradictions(actx, documents)
    versions = claims.python_version_claims(actx, documents)
    statuses = claims.status_claims(actx, documents)
    labels = claims.app_label_mismatches(actx, documents)
    fresh = freshness.collect(actx)
    spec_facts = specs.collect(actx, documents)
    copies = mdcode.collect(actx)
    locations = paths.document_locations(actx, documents)

    actx.out[KEY] = {
        "agent_files": [document.rel for document in documents],
        "missing_paths": missing,
        "stack_contradictions": stack,
        "python_version_claims": versions,
        "status_claims": statuses,
        "app_label_mismatches": labels,
        "freshness": fresh,
        "specs": spec_facts,
        "md_code_copies": copies,
        "doc_locations": locations,
    }
    actx.rule_inputs["A5"] = {
        "missing_paths": missing,
        "stack_contradictions": stack,
        "python_version_claims": versions,
        "status_claims": statuses,
        "app_label_mismatches": labels,
    }
    actx.rule_inputs["A6"] = {"freshness": fresh}
    actx.rule_inputs["A7"] = dict(spec_facts)
    actx.rule_inputs["A8"] = {"md_code_copies": copies}
