from __future__ import annotations

import json
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

from services.windows_appcontainer_boundary import WindowsAppContainerBoundary, WindowsFirewallPackageGuard


def main() -> int:
    workspace = BASE.parent / "output" / "coding" / "appcontainer-probe"
    workspace.mkdir(parents=True, exist_ok=True)
    boundary = WindowsAppContainerBoundary()
    report = {"before": boundary.status()}
    try:
        installed = boundary.install(confirmed=True)
        report["install"] = installed
        try:
            report["firewall"] = WindowsFirewallPackageGuard().install(installed["sid"], confirmed=True)
        except Exception as exc:
            report["firewall"] = {"installed": False, "error": f"{type(exc).__name__}: {exc}"}
        report["probe"] = boundary.probe(workspace, confirmed_acl=True)
    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
    report["after"] = boundary.status()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report.get("probe", {}).get("passed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
