import configparser
import json
from pathlib import Path
import re


HOST_RE = re.compile(r"^([A-Za-z0-9.-]+):\s*$")


def collect_external_access(home: Path) -> dict:
    gh_hosts: list[str] = []
    try:
        for line in (home / ".config" / "gh" / "hosts.yml").read_text(
            encoding="utf-8"
        ).splitlines():
            match = HOST_RE.fullmatch(line)
            if match:
                gh_hosts.append(match.group(1))
    except (OSError, UnicodeError):
        pass

    docker_registries: list[str] = []
    try:
        document = json.loads((home / ".docker" / "config.json").read_bytes())
        auths = document.get("auths", {}) if isinstance(document, dict) else {}
        if isinstance(auths, dict):
            docker_registries = sorted(str(key) for key in auths)
    except (OSError, UnicodeError, json.JSONDecodeError):
        pass

    aws_profiles = 0
    parser = configparser.RawConfigParser()
    try:
        with (home / ".aws" / "credentials").open(encoding="utf-8") as stream:
            parser.read_file(stream)
        aws_profiles = len(parser.sections())
    except (OSError, UnicodeError, configparser.Error):
        pass

    kube_contexts = 0
    try:
        kube_contexts = sum(
            1
            for line in (home / ".kube" / "config").read_text(
                encoding="utf-8"
            ).splitlines()
            if re.match(r"^\s*-\s+context:\s*$", line)
        )
    except (OSError, UnicodeError):
        pass

    return {
        "gh_hosts": sorted(set(gh_hosts)),
        "docker_registries": docker_registries,
        "aws_profiles": aws_profiles,
        "kube_contexts": kube_contexts,
    }

