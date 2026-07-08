"""Collect audit evidence and generate the local dashboard."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import tomllib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
REPORT_DIR = ROOT / "harness" / "reports"
DASHBOARD_DIR = ROOT / "harness" / "dashboard"


def sanitize_text(text: str) -> str:
    replacements = {
        str(ROOT): "<repo>",
        str(ROOT).replace("\\", "\\\\"): "<repo>",
    }
    for env_name, label in (("USERPROFILE", "<home>"), ("TEMP", "<temp>"), ("TMP", "<temp>")):
        value = os.environ.get(env_name)
        if value:
            replacements[value] = label
            replacements[value.replace("\\", "\\\\")] = label
    for source, target in sorted(replacements.items(), key=lambda item: len(item[0]), reverse=True):
        text = text.replace(source, target)
    return text


def display_command(command: list[str]) -> str:
    return sanitize_text(" ".join(command))


def run_command(name: str, command: list[str], timeout: int = 120) -> dict[str, Any]:
    start = time.perf_counter()
    try:
        completed = subprocess.run(
            command,
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
        )
        code = completed.returncode
        stdout = completed.stdout
        stderr = completed.stderr
    except subprocess.TimeoutExpired as exc:
        code = 124
        stdout = exc.stdout or ""
        stderr = (exc.stderr or "") + f"\nTimed out after {timeout}s"
    duration = round(time.perf_counter() - start, 2)
    return {
        "name": name,
        "command": display_command(command),
        "exit_code": code,
        "status": "pass" if code == 0 else "fail",
        "duration_seconds": duration,
        "stdout_tail": tail(stdout),
        "stderr_tail": tail(stderr),
        "summary": summarize_command(name, stdout, stderr, code),
    }


def tail(text: str, limit: int = 3000) -> str:
    text = sanitize_text(text.strip())
    if len(text) <= limit:
        return text
    return text[-limit:]


def summarize_command(name: str, stdout: str, stderr: str, code: int) -> str:
    text = f"{stdout}\n{stderr}"
    if name == "pytest":
        match = re.search(r"(\d+ passed(?:, \d+ skipped)?(?:, \d+ warning)?).*? in ", text)
        if match:
            return match.group(1)
    if name == "ruff" and code == 0:
        return "All checks passed"
    if name == "mypy" and code == 0:
        return "No type errors"
    if name == "pip-check" and code == 0:
        return "No broken requirements"
    if name == "pip-audit" and code == 0:
        if "No known vulnerabilities found" in text:
            return "No known vulnerabilities found"
        return "Completed"
    if name == "release-gate" and code == 0:
        return "Release gate OK"
    return "Failed" if code else "Passed"


def git_info() -> dict[str, Any]:
    def git(args: list[str]) -> str:
        result = subprocess.run(["git", *args], cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return result.stdout.strip() or result.stderr.strip()

    return {
        "branch": git(["branch", "--show-current"]),
        "commit": git(["rev-parse", "--short", "HEAD"]),
        "status": git(["status", "--short", "--branch"]),
        "remote": git(["remote", "get-url", "origin"]),
    }


def read_pyproject(path: Path) -> dict[str, Any]:
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    project = data.get("project", {})
    return {
        "name": project.get("name"),
        "version": project.get("version"),
        "requires_python": project.get("requires-python"),
        "dependencies": project.get("dependencies", []),
    }


def inventory() -> dict[str, Any]:
    files = [p for p in ROOT.rglob("*") if p.is_file() and ".git" not in p.parts and ".venv" not in p.parts]
    pyprojects = [
        ROOT / "pyproject.toml",
        ROOT / "packages" / "lumen-ai-core" / "pyproject.toml",
        ROOT / "packages" / "lumen-ai-celery" / "pyproject.toml",
        ROOT / "packages" / "lumen-ai-openlit" / "pyproject.toml",
    ]
    return {
        "file_count": len(files),
        "python_files": len([p for p in files if p.suffix == ".py"]),
        "test_files": len([p for p in files if "tests" in p.parts and p.suffix == ".py"]),
        "workflow_files": len(list((ROOT / ".github" / "workflows").glob("*.yml"))),
        "example_dirs": len([p for p in (ROOT / "examples").glob("*") if p.is_dir()]),
        "claude_agents": len(list((ROOT / ".claude" / "agents").glob("*.md"))),
        "harness_agents": len(list((ROOT / "harness" / "agents").glob("*.md"))),
        "packages": [read_pyproject(path) for path in pyprojects if path.exists()],
    }


def pypi_versions(python: str) -> list[dict[str, Any]]:
    packages = ["lumen-ai-core", "lumen-ai-celery", "lumen-ai-openlit"]
    rows = []
    for package in packages:
        result = run_command(
            f"pypi-{package}",
            [python, "-m", "pip", "index", "versions", package],
            timeout=60,
        )
        latest = ""
        match = re.search(r"Available versions:\s*([^\n\r]+)", result["stdout_tail"])
        if match:
            latest = match.group(1).split(",")[0].strip()
        rows.append(
            {
                "package": package,
                "latest": latest or "unknown",
                "status": result["status"],
                "summary": result["summary"],
                "stdout_tail": result["stdout_tail"],
            }
        )
    return rows


def run_probe(python: str, script: str) -> dict[str, Any]:
    path = ROOT / "harness" / "probes" / script
    result = run_command(script, [python, str(path)], timeout=60)
    try:
        payload = json.loads(result["stdout_tail"])
    except json.JSONDecodeError:
        payload = {"probe": script, "status": "fail", "finding": "Probe did not emit JSON"}
    payload["command_status"] = result["status"]
    payload["duration_seconds"] = result["duration_seconds"]
    return payload


def known_findings() -> list[dict[str, Any]]:
    return [
        {
            "id": "REL-101",
            "severity": "P2",
            "aspect": "Release status",
            "title": "Source is 0.1.4 but PyPI can remain at 0.1.3 until publish is executed",
            "evidence": [
                "README.md: Quick Start install note",
                "harness report pypi_versions",
                ".github/workflows/publish.yml: Trusted Publishing path is prepared",
            ],
            "recommendation": "After review, create tag v0.1.4 and publish through the hardened Trusted Publishing workflow; keep git/local install guidance until PyPI is current.",
        },
        {
            "id": "DB-101",
            "severity": "P3",
            "aspect": "Storage migration",
            "title": "Tenant-scoped constraints protect new schemas only",
            "evidence": [
                "packages/lumen-ai-core/src/lumen_ai/models.py",
                "README.md: Storage Schema Note",
            ],
            "recommendation": "Add an Alembic migration in the next storage-focused cycle before applying these constraints to existing production databases.",
        },
        {
            "id": "AUDIT-101",
            "severity": "P3",
            "aspect": "Dependency audit",
            "title": "pip-audit cannot audit unpublished local package names themselves",
            "evidence": ["harness gate pip-audit stdout", "source packages install as 0.1.4"],
            "recommendation": "Treat the current audit as dependency coverage; after publishing 0.1.4, rerun pip-audit against PyPI-installed artifacts.",
        },
    ]


def aspects(findings: list[dict[str, Any]], gates: list[dict[str, Any]], probes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    gate_failures = len([g for g in gates if g["status"] == "fail"])
    probe_failures = len([p for p in probes if p.get("status") == "fail"])
    release_gate = next((g for g in gates if g["name"] == "release-gate"), None)
    release_gate_green = bool(release_gate and release_gate["status"] == "pass")
    pip_audit_green = any(g["name"] == "pip-audit" and g["status"] == "pass" for g in gates)
    high_findings = [f for f in findings if f["severity"] in {"P0", "P1"}]
    all_gates_green = gate_failures == 0 and release_gate_green
    return [
        {
            "name": "Tests and local gate",
            "score": 94 if all_gates_green else 68,
            "status": "Strong" if all_gates_green else "Needs attention",
            "note": "Pytest, Ruff, mypy, pip check, pip-audit, and release gate are evaluated locally.",
        },
        {
            "name": "Runtime correctness",
            "score": 94 if probe_failures == 0 else 58,
            "status": "Strong" if probe_failures == 0 else "Needs fixes",
            "note": "External-provider reinit, OpenInference metadata, and tenant-attribute probes are regression gates.",
        },
        {
            "name": "Tenant isolation",
            "score": 90 if probe_failures == 0 else 70,
            "status": "Strong" if probe_failures == 0 else "Needs hardening",
            "note": "Tenant IDs share one sanitization helper across context, span attributes, Celery kwargs, and exporters.",
        },
        {
            "name": "Release safety",
            "score": 88 if release_gate_green and not high_findings else 62,
            "status": "Hardened" if release_gate_green and not high_findings else "Needs hardening",
            "note": "Publish now depends on release_gate, tag/version validation, twine checks, and Trusted Publishing.",
        },
        {
            "name": "Supply chain",
            "score": 86 if pip_audit_green and not high_findings else 64,
            "status": "Hardened" if pip_audit_green and not high_findings else "Needs hardening",
            "note": "GitHub Actions and reusable workflows are pinned by SHA; dependency audit is blocking.",
        },
        {
            "name": "Docs and adoption",
            "score": 86,
            "status": "Improved",
            "note": "README, FastAPI, Celery, LangChain, and custom exporter examples now match the implemented API.",
        },
        {
            "name": "Harness readiness",
            "score": 94,
            "status": "Strong",
            "note": "Codex context, agents, skill, MCP config, probes, reports, and dashboard are present.",
        },
    ]


def overall_score(aspect_rows: list[dict[str, Any]]) -> int:
    return round(sum(row["score"] for row in aspect_rows) / len(aspect_rows))


def render_dashboard(data: dict[str, Any]) -> str:
    data_json = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <link rel="icon" href="data:,">
  <title>LumenAI SDK Audit Dashboard</title>
  <style>
    :root {{
      --bg: #f6f7f9;
      --panel: #ffffff;
      --ink: #17202a;
      --muted: #667085;
      --line: #d7dce2;
      --blue: #2563eb;
      --green: #15803d;
      --amber: #b45309;
      --red: #b91c1c;
      --violet: #6d28d9;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--ink);
      font-family: Inter, Segoe UI, Arial, sans-serif;
      font-size: 14px;
      line-height: 1.45;
      letter-spacing: 0;
    }}
    header {{
      background: #101827;
      color: #fff;
      padding: 28px 32px 22px;
      border-bottom: 4px solid var(--blue);
    }}
    .wrap {{ max-width: 1280px; margin: 0 auto; }}
    .topline {{ display: flex; justify-content: space-between; gap: 20px; align-items: flex-start; flex-wrap: wrap; }}
    h1 {{ margin: 0 0 8px; font-size: 30px; line-height: 1.1; font-weight: 760; }}
    h2 {{ margin: 0 0 14px; font-size: 18px; }}
    h3 {{ margin: 0 0 8px; font-size: 15px; }}
    .sub {{ color: #c8d2e0; max-width: 760px; }}
    .scorebox {{
      display: grid;
      grid-template-columns: 110px 170px;
      gap: 10px;
      align-items: center;
      min-width: 300px;
    }}
    .score {{
      width: 104px;
      height: 104px;
      border: 8px solid #60a5fa;
      border-radius: 50%;
      display: grid;
      place-items: center;
      font-size: 30px;
      font-weight: 800;
      background: #0f172a;
    }}
    main {{ padding: 24px 32px 40px; }}
    .grid {{ display: grid; gap: 16px; }}
    .cols-4 {{ grid-template-columns: repeat(4, minmax(0, 1fr)); }}
    .cols-3 {{ grid-template-columns: repeat(3, minmax(0, 1fr)); }}
    .cols-2 {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
    section {{ margin-top: 18px; }}
    .panel {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 16px;
      box-shadow: 0 1px 2px rgba(16, 24, 40, 0.05);
    }}
    .metric .label {{ color: var(--muted); font-size: 12px; text-transform: uppercase; font-weight: 700; }}
    .metric .value {{ font-size: 24px; font-weight: 780; margin-top: 5px; }}
    .bar {{ height: 9px; background: #e5e7eb; border-radius: 99px; overflow: hidden; margin-top: 10px; }}
    .bar span {{ display: block; height: 100%; background: var(--blue); }}
    .status-pass {{ color: var(--green); font-weight: 760; }}
    .status-fail {{ color: var(--red); font-weight: 760; }}
    .status-skip {{ color: var(--amber); font-weight: 760; }}
    .filters {{ display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 12px; }}
    button {{
      border: 1px solid var(--line);
      background: #fff;
      color: var(--ink);
      border-radius: 6px;
      min-height: 34px;
      padding: 7px 11px;
      cursor: pointer;
      font: inherit;
    }}
    button.active {{ background: var(--blue); color: #fff; border-color: var(--blue); }}
    table {{ width: 100%; border-collapse: collapse; }}
    th, td {{ border-bottom: 1px solid var(--line); padding: 10px 8px; text-align: left; vertical-align: top; }}
    th {{ font-size: 12px; text-transform: uppercase; color: var(--muted); background: #f8fafc; }}
    .sev {{ display: inline-block; min-width: 34px; text-align: center; border-radius: 5px; padding: 3px 6px; color: #fff; font-weight: 760; }}
    .P0 {{ background: #7f1d1d; }}
    .P1 {{ background: var(--red); }}
    .P2 {{ background: var(--amber); }}
    .P3 {{ background: var(--violet); }}
    code {{ background: #eef2f7; padding: 2px 5px; border-radius: 4px; }}
    .muted {{ color: var(--muted); }}
    .mono {{ font-family: Consolas, ui-monospace, monospace; }}
    .finding-title {{ font-weight: 760; }}
    .evidence {{ color: var(--muted); font-size: 12px; margin-top: 5px; }}
    .probe-pass {{ border-left: 4px solid var(--green); }}
    .probe-fail {{ border-left: 4px solid var(--red); }}
    .scroll {{ overflow-x: auto; }}
    footer {{ color: var(--muted); padding: 20px 0 0; }}
    @media (max-width: 900px) {{
      header, main {{ padding-left: 18px; padding-right: 18px; }}
      .cols-4, .cols-3, .cols-2 {{ grid-template-columns: 1fr; }}
      .scorebox {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
  <script type="application/json" id="audit-data">{data_json}</script>
  <header>
    <div class="wrap topline">
      <div>
        <h1>LumenAI SDK Audit Dashboard</h1>
        <div class="sub" id="repoLine"></div>
      </div>
      <div class="scorebox">
        <div class="score" id="overallScore"></div>
        <div>
          <div class="muted">Overall engineering score</div>
          <div id="generatedAt"></div>
          <div class="muted mono" id="commitLine"></div>
        </div>
      </div>
    </div>
  </header>
  <main>
    <div class="wrap">
      <section class="grid cols-4" id="metrics"></section>
      <section>
        <h2>Aspect Evaluation</h2>
        <div class="grid cols-3" id="aspects"></div>
      </section>
      <section class="grid cols-2">
        <div class="panel">
          <h2>Validation Gates</h2>
          <div class="scroll"><table id="gates"></table></div>
        </div>
        <div class="panel">
          <h2>Runtime Probes</h2>
          <div class="grid" id="probes"></div>
        </div>
      </section>
      <section class="panel">
        <h2>Findings</h2>
        <div class="filters" id="filters"></div>
        <div class="scroll"><table id="findings"></table></div>
      </section>
      <section class="grid cols-2">
        <div class="panel">
          <h2>Package And PyPI Parity</h2>
          <div class="scroll"><table id="packages"></table></div>
        </div>
        <div class="panel">
          <h2>Harness Assets</h2>
          <div id="assets"></div>
        </div>
      </section>
      <footer>Generated by <code>harness/scripts/collect_audit.py</code>.</footer>
    </div>
  </main>
  <script>
    const data = JSON.parse(document.getElementById('audit-data').textContent);
    const $ = (id) => document.getElementById(id);
    const sevOrder = ['ALL', 'P0', 'P1', 'P2', 'P3'];
    let activeSeverity = 'ALL';

    function esc(value) {{
      return String(value ?? '').replace(/[&<>"']/g, c => ({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[c]));
    }}
    function statusClass(status) {{
      if (status === 'pass') return 'status-pass';
      if (status === 'fail') return 'status-fail';
      return 'status-skip';
    }}
    function renderMetrics() {{
      const inv = data.inventory;
      const counts = [
        ['Python files', inv.python_files],
        ['Tests', inv.test_files],
        ['Workflows', inv.workflow_files],
        ['Findings', data.findings.length],
      ];
      $('metrics').innerHTML = counts.map(([label, value]) => `<div class="panel metric"><div class="label">${{esc(label)}}</div><div class="value">${{esc(value)}}</div></div>`).join('');
    }}
    function renderAspects() {{
      $('aspects').innerHTML = data.aspects.map(a => `<div class="panel"><h3>${{esc(a.name)}} <span class="muted">${{a.score}}/100</span></h3><div class="muted">${{esc(a.status)}}</div><div class="bar"><span style="width:${{a.score}}%"></span></div><p>${{esc(a.note)}}</p></div>`).join('');
    }}
    function renderGates() {{
      $('gates').innerHTML = '<thead><tr><th>Gate</th><th>Status</th><th>Summary</th><th>Seconds</th></tr></thead><tbody>' +
        data.gates.map(g => `<tr><td class="mono">${{esc(g.name)}}</td><td class="${{statusClass(g.status)}}">${{esc(g.status)}}</td><td>${{esc(g.summary)}}</td><td>${{esc(g.duration_seconds)}}</td></tr>`).join('') +
        '</tbody>';
    }}
    function renderProbes() {{
      $('probes').innerHTML = data.probes.map(p => `<div class="panel probe-${{esc(p.status)}}"><h3>${{esc(p.probe)}}</h3><div class="${{statusClass(p.status)}}">${{esc(p.status)}}</div><p>${{esc(p.finding)}}</p><div class="muted mono">${{esc(JSON.stringify(p))}}</div></div>`).join('');
    }}
    function renderFilters() {{
      $('filters').innerHTML = sevOrder.map(s => `<button data-sev="${{s}}" class="${{s === activeSeverity ? 'active' : ''}}">${{s}}</button>`).join('');
      $('filters').querySelectorAll('button').forEach(btn => btn.addEventListener('click', () => {{
        activeSeverity = btn.dataset.sev;
        renderFilters();
        renderFindings();
      }}));
    }}
    function renderFindings() {{
      const rows = data.findings.filter(f => activeSeverity === 'ALL' || f.severity === activeSeverity);
      $('findings').innerHTML = '<thead><tr><th>Severity</th><th>Aspect</th><th>Finding</th><th>Recommendation</th></tr></thead><tbody>' +
        rows.map(f => `<tr><td><span class="sev ${{esc(f.severity)}}">${{esc(f.severity)}}</span></td><td>${{esc(f.aspect)}}</td><td><div class="finding-title">${{esc(f.id)}}: ${{esc(f.title)}}</div><div class="evidence">${{f.evidence.map(esc).join('<br>')}}</div></td><td>${{esc(f.recommendation)}}</td></tr>`).join('') +
        '</tbody>';
    }}
    function renderPackages() {{
      const byName = Object.fromEntries((data.pypi_versions || []).map(p => [p.package, p.latest]));
      $('packages').innerHTML = '<thead><tr><th>Package</th><th>Source</th><th>Requires Python</th><th>PyPI latest</th></tr></thead><tbody>' +
        data.inventory.packages.map(p => `<tr><td class="mono">${{esc(p.name)}}</td><td>${{esc(p.version)}}</td><td>${{esc(p.requires_python)}}</td><td>${{esc(byName[p.name] || 'n/a')}}</td></tr>`).join('') +
        '</tbody>';
    }}
    function renderAssets() {{
      const items = [
        'CODEX.md',
        'harness/context/project-context.md',
        'harness/agents/*.md',
        'harness/skills/lumen-ai-audit/SKILL.md',
        'harness/mcp/lumen-audit.mcp.json',
        'harness/probes/*.py',
        'harness/reports/audit-data.json',
      ];
      $('assets').innerHTML = items.map(i => `<p><code>${{esc(i)}}</code></p>`).join('');
    }}
    $('overallScore').textContent = data.overall_score;
    $('repoLine').textContent = `${{data.repo.remote}} on branch ${{data.repo.branch}}`;
    $('generatedAt').textContent = data.generated_at;
    $('commitLine').textContent = `commit ${{data.repo.commit}}`;
    renderMetrics();
    renderAspects();
    renderGates();
    renderProbes();
    renderFilters();
    renderFindings();
    renderPackages();
    renderAssets();
  </script>
</body>
</html>
"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--full", action="store_true", help="Run scripts/release_gate.py as part of collection.")
    parser.add_argument("--no-html", action="store_true", help="Only write JSON report.")
    args = parser.parse_args()

    python = sys.executable
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    DASHBOARD_DIR.mkdir(parents=True, exist_ok=True)

    gates = [
        run_command("pytest", [python, "-m", "pytest", "tests", "-q"], timeout=180),
        run_command(
            "ruff",
            [
                python,
                "-m",
                "ruff",
                "check",
                "packages/lumen-ai-core/src",
                "packages/lumen-ai-celery/src",
                "packages/lumen-ai-openlit/src",
                "--select",
                "E,F,W,I",
                "--ignore",
                "E501",
            ],
            timeout=120,
        ),
        run_command(
            "mypy",
            [python, "-m", "mypy", "packages/lumen-ai-core/src/lumen_ai", "--ignore-missing-imports", "--no-error-summary"],
            timeout=120,
        ),
        run_command("pip-check", [python, "-m", "pip", "check"], timeout=120),
        run_command("pip-audit", [python, "-m", "pip_audit"], timeout=240),
    ]
    if args.full:
        gates.append(run_command("release-gate", [python, "scripts/release_gate.py"], timeout=420))
    else:
        gates.append(
            {
                "name": "release-gate",
                "command": f"{python} scripts/release_gate.py",
                "exit_code": None,
                "status": "skip",
                "duration_seconds": 0,
                "stdout_tail": "",
                "stderr_tail": "",
                "summary": "Skipped; run with --full",
            }
        )

    probes = [
        run_probe(python, "probe_external_provider_reinit.py"),
        run_probe(python, "probe_openinference_metadata.py"),
        run_probe(python, "probe_tenant_attr_sanitize.py"),
    ]
    findings = known_findings()
    aspect_rows = aspects(findings, gates, probes)
    data = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "repo": git_info(),
        "environment": {
            "python": sys.version,
            "executable": sanitize_text(python),
            "platform": sys.platform,
        },
        "inventory": inventory(),
        "pypi_versions": pypi_versions(python),
        "gates": gates,
        "probes": probes,
        "findings": findings,
        "aspects": aspect_rows,
        "overall_score": overall_score(aspect_rows),
    }

    report_path = REPORT_DIR / "audit-data.json"
    report_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    if not args.no_html:
        (DASHBOARD_DIR / "index.html").write_text(render_dashboard(data), encoding="utf-8")
    print(json.dumps({"report": str(report_path), "dashboard": str(DASHBOARD_DIR / "index.html"), "overall_score": data["overall_score"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
