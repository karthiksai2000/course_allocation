from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from uuid import uuid4

import pandas as pd
from flask import Flask, abort, flash, redirect, render_template, request, send_file, url_for
from werkzeug.utils import secure_filename

from main import _configure_logging, _run
from input_processor import auto_build_config

BASE_DIR = Path(__file__).resolve().parent
RUNS_DIR = BASE_DIR / "web_runs"
RUNS_DIR.mkdir(exist_ok=True)

ALLOWED_EXTENSIONS = {".xlsx", ".xlsm", ".xls"}

app = Flask(__name__)
app.secret_key = "course-allocation-web-ui"


def _allowed_file(filename: str) -> bool:
    return Path(filename).suffix.lower() in ALLOWED_EXTENSIONS


def _new_run_dir() -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    run_id = f"{stamp}-{uuid4().hex[:8]}"
    run_dir = RUNS_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def _normalise_section_label(raw: str) -> str:
    """Convert section letters (A/B/...) to 1/2/... for UI display."""
    token = (raw or "").strip()
    if not token:
        return token
    if token.isdigit():
        return token
    if len(token) == 1 and token.isalpha():
        return str(ord(token.upper()) - ord("A") + 1)
    return token


def _parse_summary(log_path: Path, output_path: Path | None = None) -> dict:
    summary = {
        "total": None,
        "fully_allocated": None,
        "partial": None,
        "unallocated": None,
        "sections": [],
        "combo_summary": False,
    }

    # Parse top-line totals from allocation log.
    if log_path.exists():
        total_re = re.compile(r"Total students\s*:\s*(\d+)")
        full_re = re.compile(r"Fully allocated\s*:\s*(\d+)")
        partial_re = re.compile(r"Partial \(G1 only\)\s*:\s*(\d+)")
        unalloc_re = re.compile(r"Unallocated\s*:\s*(\d+)")
        section_re = re.compile(r"\[INFO\]\s+(.+?)\s+Section\s+(\w+)\s*:\s*(\d+)\s*/\s*(\d+)")

        for line in log_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            if summary["total"] is None:
                m = total_re.search(line)
                if m:
                    summary["total"] = int(m.group(1))
            if summary["fully_allocated"] is None:
                m = full_re.search(line)
                if m:
                    summary["fully_allocated"] = int(m.group(1))
            if summary["partial"] is None:
                m = partial_re.search(line)
                if m:
                    summary["partial"] = int(m.group(1))
            if summary["unallocated"] is None:
                m = unalloc_re.search(line)
                if m:
                    summary["unallocated"] = int(m.group(1))

            # Legacy fallback rows when Course Summary sheet is unavailable.
            m = section_re.search(line)
            if m:
                summary["sections"].append(
                    {
                        "g1": m.group(1).strip(),
                        "g2": "",
                        "section": _normalise_section_label(m.group(2)),
                        "enrolled": int(m.group(3)),
                        "capacity": int(m.group(4)),
                        "available": max(int(m.group(4)) - int(m.group(3)), 0),
                        "fill": f"{round((int(m.group(3)) / int(m.group(4))) * 100, 1)}%" if int(m.group(4)) else "0.0%",
                    }
                )

    # Prefer reading section summary directly from output workbook.
    if output_path and output_path.exists():
        try:
            df = pd.read_excel(output_path, sheet_name="Course Summary", engine="openpyxl")
            cols = {str(c).strip().lower(): c for c in df.columns}

            has_combo = (
                "primary course (g1)" in cols
                and "secondary course (g2)" in cols
                and "section number" in cols
            )

            if has_combo:
                summary["sections"] = []
                for _, row in df.iterrows():
                    g1 = str(row.get(cols["primary course (g1)"], "")).strip()
                    if not g1 or g1.lower() == "nan":
                        continue
                    g2 = str(row.get(cols["secondary course (g2)"], "")).strip()
                    if g2.lower() == "nan":
                        g2 = ""
                    sec = str(row.get(cols["section number"], "")).strip()
                    enrolled = int(float(row.get(cols.get("enrolled"), 0) or 0))
                    capacity = int(float(row.get(cols.get("capacity"), 0) or 0))
                    available = int(float(row.get(cols.get("available"), 0) or 0))
                    fill = str(row.get(cols.get("fill %"), "")).strip() if "fill %" in cols else ""
                    summary["sections"].append(
                        {
                            "g1": g1,
                            "g2": g2,
                            "section": _normalise_section_label(sec),
                            "enrolled": enrolled,
                            "capacity": capacity,
                            "available": available,
                            "fill": fill,
                        }
                    )
                summary["combo_summary"] = True
        except Exception:
            pass

    return summary


def _parse_manual_config_rows(
    text: str,
    default_sections: int,
    default_capacity: int,
) -> list[dict]:
    """Parse manual config rows entered in textarea.

    Expected per row:
      Course, Group, Sections, Capacity, Prerequisites
    Delimiter can be comma or pipe.
    """
    rows: list[dict] = []
    if not text.strip():
        return rows

    for i, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue

        parts = [p.strip() for p in re.split(r"\s*[|,]\s*", line)]

        # Skip optional header row.
        if i == 1 and parts:
            first = re.sub(r"[^a-z0-9]+", "", parts[0].lower())
            if first in {"course", "coursename", "subject"}:
                continue

        course = parts[0] if len(parts) > 0 else ""
        group = (parts[1] if len(parts) > 1 else "").strip().upper()
        sections_raw = parts[2] if len(parts) > 2 else ""
        capacity_raw = parts[3] if len(parts) > 3 else ""
        prereq = parts[4] if len(parts) > 4 else "None"

        if not course:
            continue

        if group in {"PRIMARY", "P", "1"}:
            group = "G1"
        elif group in {"SECONDARY", "S", "2"}:
            group = "G2"

        if group not in {"G1", "G2"}:
            raise ValueError(f"Line {i}: group must be G1 or G2 for course '{course}'.")

        try:
            sections = max(1, int(float(sections_raw))) if sections_raw else default_sections
        except Exception as exc:
            raise ValueError(f"Line {i}: invalid sections value '{sections_raw}'.") from exc

        try:
            capacity = max(1, int(float(capacity_raw))) if capacity_raw else default_capacity
        except Exception as exc:
            raise ValueError(f"Line {i}: invalid capacity value '{capacity_raw}'.") from exc

        rows.append(
            {
                "Course": course,
                "Group": group,
                "Sections": sections,
                "Capacity": capacity,
                "Prerequisites": prereq or "None",
            }
        )

    return rows


def _parse_manual_config_form(
    form,
    default_sections: int,
    default_capacity: int,
) -> list[dict]:
    """Parse structured manual config rows from repeated form fields."""
    names = form.getlist("manual_course_name[]")
    groups = form.getlist("manual_group[]")
    sections_list = form.getlist("manual_sections[]")
    capacities = form.getlist("manual_capacity[]")
    prereqs = form.getlist("manual_prereq[]")

    rows: list[dict] = []
    for idx, raw_name in enumerate(names, start=1):
        course = (raw_name or "").strip()
        if not course:
            continue

        group = (groups[idx - 1] if idx - 1 < len(groups) else "").strip().upper()
        if group in {"PRIMARY", "P", "1"}:
            group = "G1"
        elif group in {"SECONDARY", "S", "2"}:
            group = "G2"

        if group not in {"G1", "G2"}:
            raise ValueError(f"Row {idx}: group must be G1 or G2 for course '{course}'.")

        section_raw = (sections_list[idx - 1] if idx - 1 < len(sections_list) else "").strip()
        capacity_raw = (capacities[idx - 1] if idx - 1 < len(capacities) else "").strip()
        prereq = (prereqs[idx - 1] if idx - 1 < len(prereqs) else "").strip()

        try:
            sections = max(1, int(float(section_raw))) if section_raw else default_sections
        except Exception as exc:
            raise ValueError(f"Row {idx}: invalid sections value '{section_raw}'.") from exc

        try:
            capacity = max(1, int(float(capacity_raw))) if capacity_raw else default_capacity
        except Exception as exc:
            raise ValueError(f"Row {idx}: invalid class strength value '{capacity_raw}'.") from exc

        rows.append(
            {
                "Course": course,
                "Group": group,
                "Sections": sections,
                "Capacity": capacity,
                "Prerequisites": prereq or "None",
            }
        )

    return rows


def _recent_runs(limit: int = 8) -> list[dict]:
    runs = []
    for p in sorted(RUNS_DIR.glob("*"), reverse=True):
        if not p.is_dir():
            continue
        manifest = p / "manifest.json"
        item = {
            "run_id": p.name,
            "mode": "-",
            "created": p.name,
            "output_exists": (p / "allocation_output.xlsx").exists(),
        }
        if manifest.exists():
            try:
                data = json.loads(manifest.read_text(encoding="utf-8"))
                item["mode"] = data.get("mode", "-")
                item["created"] = data.get("created", p.name)
            except Exception:
                pass
        runs.append(item)
        if len(runs) >= limit:
            break
    return runs


@app.get("/")
def index():
    return render_template("index.html", recent_runs=_recent_runs())


@app.post("/run")
def run_allocation():
    responses_file = request.files.get("responses")
    config_file = request.files.get("config")
    overrides_file = request.files.get("overrides")

    if not responses_file or not responses_file.filename:
        flash("Responses file is required.", "error")
        return redirect(url_for("index"))

    if not _allowed_file(responses_file.filename):
        flash("Responses must be an Excel file (.xlsx/.xlsm/.xls).", "error")
        return redirect(url_for("index"))

    mode = (request.form.get("mode") or "auto").strip().lower()
    if mode not in {"single", "dual", "auto"}:
        flash("Invalid allocation mode selected.", "error")
        return redirect(url_for("index"))

    config_mode = (request.form.get("config_mode") or "upload").strip().lower()
    if config_mode not in {"upload", "auto", "manual"}:
        flash("Invalid config mode selected.", "error")
        return redirect(url_for("index"))

    default_sections_raw = (request.form.get("default_sections") or "2").strip()
    default_capacity_raw = (request.form.get("default_capacity") or "60").strip()
    try:
        default_sections = max(1, int(float(default_sections_raw)))
        default_capacity = max(1, int(float(default_capacity_raw)))
    except Exception:
        flash("Default sections/capacity must be valid positive numbers.", "error")
        return redirect(url_for("index"))

    skip_balance = request.form.get("skip_balance") == "on"

    run_dir = _new_run_dir()
    responses_name = secure_filename(responses_file.filename)
    responses_path = run_dir / (responses_name or "responses.xlsx")
    responses_file.save(responses_path)

    config_path = run_dir / "course_config.xlsx"
    if config_mode == "upload":
        if config_file and config_file.filename:
            if not _allowed_file(config_file.filename):
                flash("Config must be an Excel file (.xlsx/.xlsm/.xls).", "error")
                return redirect(url_for("index"))
            config_file.save(config_path)
        # If upload mode is selected without a file, fallback stays auto via _run().
    elif config_mode == "auto":
        try:
            auto_build_config(
                responses_path=str(responses_path),
                save_path=str(config_path),
                default_sections=default_sections,
                default_capacity=default_capacity,
            )
        except Exception as exc:
            flash(f"Auto config generation failed: {exc}", "error")
            return redirect(url_for("index"))
    else:  # manual
        manual_text = (request.form.get("manual_config") or "").strip()
        try:
            rows = _parse_manual_config_form(
                form=request.form,
                default_sections=default_sections,
                default_capacity=default_capacity,
            )
            # Backward compatible fallback for pasted text format.
            if not rows and manual_text:
                rows = _parse_manual_config_rows(
                    text=manual_text,
                    default_sections=default_sections,
                    default_capacity=default_capacity,
                )
        except Exception as exc:
            flash(f"Manual config parsing failed: {exc}", "error")
            return redirect(url_for("index"))

        if not rows:
            flash(
                "Manual config is empty. Add at least one line like: "
                "AI,G1,2,60,None",
                "error",
            )
            return redirect(url_for("index"))

        pd.DataFrame(rows).to_excel(config_path, index=False)

    overrides_path = None
    if overrides_file and overrides_file.filename:
        if not _allowed_file(overrides_file.filename):
            flash("Overrides must be an Excel file (.xlsx/.xlsm/.xls).", "error")
            return redirect(url_for("index"))
        overrides_path = run_dir / "admin_overrides.xlsx"
        overrides_file.save(overrides_path)

    output_path = run_dir / "allocation_output.xlsx"
    log_path = run_dir / "allocation.log"

    try:
        _configure_logging(str(log_path))
        _run(
            responses=str(responses_path),
            config=str(config_path),
            output=str(output_path),
            allocation_mode=mode,
            balance_sections_enabled=not skip_balance,
            overrides=str(overrides_path) if overrides_path else None,
        )
    except Exception as exc:
        flash(f"Allocation failed: {exc}", "error")
        return redirect(url_for("index"))

    manifest = {
        "run_id": run_dir.name,
        "created": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "mode": mode,
        "config_mode": config_mode,
        "skip_balance": skip_balance,
        "responses": responses_path.name,
        "config": config_path.name if config_path.exists() else None,
        "overrides": overrides_path.name if overrides_path else None,
        "output": output_path.name,
    }
    (run_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    return redirect(url_for("run_result", run_id=run_dir.name))


@app.get("/runs/<run_id>")
def run_result(run_id: str):
    run_dir = RUNS_DIR / run_id
    if not run_dir.exists() or not run_dir.is_dir():
        abort(404)

    summary = _parse_summary(
        run_dir / "allocation.log",
        run_dir / "allocation_output.xlsx",
    )
    manifest_path = run_dir / "manifest.json"
    manifest = {}
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    return render_template(
        "result.html",
        run_id=run_id,
        summary=summary,
        manifest=manifest,
        output_exists=(run_dir / "allocation_output.xlsx").exists(),
        config_exists=(run_dir / "course_config.xlsx").exists(),
    )


@app.get("/download/<run_id>/<artifact>")
def download_artifact(run_id: str, artifact: str):
    run_dir = RUNS_DIR / run_id
    if not run_dir.exists() or not run_dir.is_dir():
        abort(404)

    allowed = {
        "output": run_dir / "allocation_output.xlsx",
        "config": run_dir / "course_config.xlsx",
    }
    path = allowed.get(artifact)
    if path is None or not path.exists():
        abort(404)

    return send_file(path, as_attachment=True)


if __name__ == "__main__":
    app.run(debug=True)
