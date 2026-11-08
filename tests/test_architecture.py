"""The shape of the engine, enforced: features are vertical slices that stand on `shared` and never on each other.

    app       composes everything (engine, HTTP application, the panel's overview); may import anything
    features  one folder per capability (agenda, automations, browser, chat, computer, home, research, whatsapp)
    shared    what several features need (config, llm, approvals, guard, jobs, notices, voice, gate...); imports nothing above it

A feature may import `shared` and itself. Anything else needs a line in ALLOWED, with the reason, and the list should only shrink."""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "src" / "chakmati"

# (importer, imported): the one place where a feature talks to another one directly.
ALLOWED = {
    ("automations", "whatsapp"): "an automation answers through WhatsApp: it reuses its chat model and the contact lookup",
    ("automations", "home"): "an automation can run house commands: it validates them with the same table of services (and the same 'this opens the house' check) the house uses",
}


def layer(module: str) -> tuple[str, str]:
    """('feature', 'agenda') / ('shared', '') / ('app', '') / ('root', '') for a dotted module name under chakmati."""
    parts = module.split(".")[1:]
    if not parts:
        return ("root", "")
    if parts[0] == "features":
        return ("feature", parts[1] if len(parts) > 1 else "")
    return (parts[0], "") if parts[0] in {"shared", "app"} else ("root", "")


def imports():
    for path in ROOT.rglob("*.py"):
        module = "chakmati." + ".".join(path.relative_to(ROOT).with_suffix("").parts)
        for node in ast.walk(ast.parse(path.read_text())):
            targets = []
            if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                targets = [node.module]
            elif isinstance(node, ast.Import):
                targets = [a.name for a in node.names]
            for target in targets:
                if target.startswith("chakmati"):
                    yield module, target


def test_no_relative_imports_so_the_layers_can_be_checked():
    for path in ROOT.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            assert not (isinstance(node, ast.ImportFrom) and node.level > 0), f"{path.relative_to(ROOT)}: use an absolute import"


def test_shared_stands_alone():
    bad = [f"{m} -> {t}" for m, t in imports() if layer(m)[0] == "shared" and layer(t)[0] in {"feature", "app"}]
    assert not bad, "shared must not depend on features or app:\n" + "\n".join(bad)


def test_features_do_not_depend_on_app():
    bad = [f"{m} -> {t}" for m, t in imports() if layer(m)[0] == "feature" and layer(t)[0] in {"app", "root"} and not t == "chakmati"]
    assert not bad, "a feature must not depend on the app that composes it:\n" + "\n".join(bad)


def test_features_do_not_depend_on_each_other():
    bad = []
    for m, t in imports():
        (lm, fm), (lt, ft) = layer(m), layer(t)
        if lm == "feature" and lt == "feature" and fm != ft and (fm, ft) not in ALLOWED:
            bad.append(f"{m} -> {t}")
    assert not bad, "a feature talks to another one only through shared (or a reasoned entry in ALLOWED):\n" + "\n".join(bad)


def test_every_allowed_exception_is_still_needed():
    used = {(layer(m)[1], layer(t)[1]) for m, t in imports() if layer(m)[0] == "feature" and layer(t)[0] == "feature" and layer(m)[1] != layer(t)[1]}
    stale = set(ALLOWED) - used
    assert not stale, f"remove from ALLOWED: {sorted(stale)}"
