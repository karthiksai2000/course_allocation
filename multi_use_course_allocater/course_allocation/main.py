"""
main.py
-------
Entry point for the Student Course Allocation Automation System.

Usage
-----
  python main.py                                       # uses defaults
  python main.py --responses path/to/responses.xlsx
  python main.py --config path/to/config.xlsx --output result.xlsx
"""

import argparse
import logging
import sys
from pathlib import Path

import pandas as pd


# ── Logging setup ─────────────────────────────────────────────────────────────
def _configure_logging(log_file: str = "allocation.log") -> None:
    fmt = "[%(levelname)s] %(message)s"
    root = logging.getLogger()
    # Remove all existing handlers (basicConfig is a no-op if already configured).
    for h in root.handlers[:]:
        root.removeHandler(h)
        h.close()
    root.setLevel(logging.INFO)
    formatter = logging.Formatter(fmt)
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(formatter)
    fh = logging.FileHandler(log_file, mode="w", encoding="utf-8")
    fh.setFormatter(formatter)
    root.addHandler(sh)
    root.addHandler(fh)


# ── Imports (after logging is configured) ─────────────────────────────────────
def _apply_admin_overrides(
    overrides_path: str,
    allocated: list[dict],
    section_manager,
    unallocated: list[dict] | None = None,
) -> int:
    """
    Apply manual admin moves before final report export.

    Expected columns in overrides file (case-insensitive):
      - reg_no (or Registration Number)          [required]
      - section (target section number, e.g. 3) [optional — honours after combo formation]
      - primary (target G1 course)              [optional]
      - secondary (target G2 course)            [optional]

    Course changes take effect immediately; section overrides are applied after
    combo section formation in ReportGenerator so numeric labels are stable.
    """
    logger = logging.getLogger(__name__)
    path = Path(overrides_path)
    if not path.exists():
        raise FileNotFoundError(f"Overrides file not found: {overrides_path}")

    df = pd.read_excel(path, engine="openpyxl")
    if df.empty:
        logger.info("Overrides file '%s' is empty — no manual moves applied.", overrides_path)
        return 0

    df.columns = [str(c).strip().lower() for c in df.columns]

    def _pick_col(*keys: str) -> str | None:
        for c in df.columns:
            if any(k in c for k in keys):
                return c
        return None

    reg_col = _pick_col("registration", "reg_no", "reg no", "reg")
    sec_col = _pick_col("section")
    pri_col = _pick_col("primary", "g1")
    sec_course_col = _pick_col("secondary", "g2")

    if not reg_col:
        raise ValueError(
            "Overrides file must include a registration number column."
        )

    by_reg = {s["reg_no"]: s for s in allocated}
    unalloc_by_reg = {s["reg_no"]: s for s in (unallocated or [])}
    applied = 0

    for _, row in df.iterrows():
        reg_no = str(row.get(reg_col, "")).strip()
        if not reg_no or reg_no.lower() == "nan":
            continue

        student = by_reg.get(reg_no)
        if not student:
            # Check if student is in unallocated list — promote them.
            student = unalloc_by_reg.get(reg_no)
            if not student:
                logger.warning("Override skipped for %s: student not found.", reg_no)
                continue
            # Promote: move from unallocated to allocated.
            if unallocated is not None and student in unallocated:
                unallocated.remove(student)
            allocated.append(student)
            by_reg[reg_no] = student
            logger.info("Override promoting unallocated student %s into allocation.", reg_no)

        # Resolve course overrides (empty / NaN → keep existing)
        target_primary = (
            str(row.get(pri_col, "")).strip() if pri_col else ""
        )
        if not target_primary or target_primary.lower() == "nan":
            target_primary = student.get("allocated_primary", "")

        target_secondary = (
            str(row.get(sec_course_col, "")).strip() if sec_course_col else ""
        )
        if not target_secondary or target_secondary.lower() == "nan":
            target_secondary = student.get("allocated_secondary", "")

        if not target_primary:
            logger.warning("Override skipped for %s: no primary course available.", reg_no)
            continue

        if target_secondary and target_secondary == target_primary:
            logger.warning(
                "Override skipped for %s: primary and secondary cannot be the same (%s).",
                reg_no, target_primary,
            )
            continue

        # Apply course changes directly on the student record.
        student["allocated_primary"] = target_primary
        student["allocated_secondary"] = target_secondary or None

        # Store desired section label so ReportGenerator can honour it after
        # combo section formation (numeric labels become stable at that point).
        if sec_col:
            raw_sec = str(row.get(sec_col, "")).strip()
            if raw_sec and raw_sec.lower() != "nan":
                student["_admin_section"] = raw_sec

        applied += 1
        logger.info(
            "Override queued for %s: G1=%s  G2=%s  section=%s",
            reg_no,
            target_primary,
            target_secondary or "—",
            student.get("_admin_section", "auto"),
        )

    return applied


def _run(
    responses: str,
    config: str,
    output: str,
    allocation_mode: str,
    balance_sections_enabled: bool,
    overrides: str | None,
) -> None:
    from input_processor import DataProcessor, load_courses_config, auto_build_config
    from section_manager import SectionManager
    from course_allocator import CourseAllocator
    from report_generator import ReportGenerator

    logger = logging.getLogger(__name__)

    banner = "=" * 62
    logger.info(banner)
    logger.info("  Student Course Allocation System")
    logger.info(banner)

    # ── 1. Course configuration ───────────────────────────────────────────────
    if not Path(config).exists():
        logger.info(
            "Step 1/7  '%s' not found — auto-detecting courses from '%s' …",
            config, responses,
        )
        courses_config = auto_build_config(responses, save_path=config)
    else:
        logger.info("Step 1/7  Loading course configuration from '%s' …", config)
        courses_config = load_courses_config(config)

    # ── 2. Load student responses ─────────────────────────────────────────────
    logger.info("Step 2/7  Loading student responses from '%s' …", responses)
    processor = DataProcessor(responses, courses_config)
    processor.load_data()

    # ── 3. Clean data ─────────────────────────────────────────────────────────
    logger.info("Step 3/7  Cleaning data (dedup, CGPA normalisation) …")
    students = processor.clean_data()

    # ── 4. Validate preferences ───────────────────────────────────────────────
    logger.info("Step 4/7  Validating course preferences …")
    students = processor.validate_preferences(students)
    processor.save_clean_data("clean_students.json")

    # Guardrails for dual mode: require both G2 config and G2 preferences.
    if allocation_mode == "dual":
        g2_courses = [c for c in courses_config if c.get("group") == "G2"]
        if not g2_courses:
            raise ValueError(
                "Dual mode requires G2 courses in the config. "
                "Add at least one course with Group=G2."
            )

        students_with_g2 = sum(1 for s in students if s.get("g2_preferences"))
        if students_with_g2 == 0:
            raise ValueError(
                "Dual mode requires G2 preferences in responses, but none were detected. "
                "Upload a response sheet that includes G2 choice columns."
            )

    # ── 5. Initialise section manager ─────────────────────────────────────────
    logger.info("Step 5/7  Initialising section manager …")
    section_manager = SectionManager(courses_config)

    # ── 6. Run allocation ─────────────────────────────────────────────────────
    logger.info("Step 6/7  Running course allocation …")
    allocator = CourseAllocator(
        courses_config,
        section_manager,
        allocation_mode=allocation_mode,
    )
    allocated, unallocated = allocator.allocate_all(students)

    # ── 6b. Balance sections ──────────────────────────────────────────────────
    if balance_sections_enabled and allocation_mode != "single":
        logger.info(
            "Step 6b/7 Balancing skipped (demand-driven section fill policy enabled)."
        )
    elif allocation_mode == "single":
        logger.info("Step 6b/7 Balancing skipped (single mode preserves A->B->C fill).")
    else:
        logger.info("Step 6b/7 Balancing skipped (--skip-balance enabled).")

    # Merge underfilled sections of the same course before reporting.
    students_dict = {s["reg_no"]: s for s in allocated}
    removed = section_manager.merge_underfilled_sections(students_dict)
    if removed:
        logger.info(
            "Step 6c/7 Compacted %d under-filled section(s) via merging.",
            removed,
        )
    else:
        logger.info("Step 6c/7 No section merges required.")

    redistributed_sections, redistributed_students = section_manager.redistribute_underfilled_sections(
        students_dict,
        min_section_size=5,
        allow_overflow=True,
    )
    if redistributed_sections or redistributed_students:
        logger.info(
            "Step 6d/7 Redistributed %d student(s); removed %d tiny section(s).",
            redistributed_students,
            redistributed_sections,
        )
    else:
        logger.info("Step 6d/7 No tiny-section redistribution required.")

    # Demand-driven cleanup: retain only sections that actually have allocations.
    section_manager.prune_empty_sections()

    # ── 6e. Optional admin overrides ─────────────────────────────────────────
    if overrides:
        logger.info("Step 6e/7 Applying admin overrides from '%s' …", overrides)
        applied = _apply_admin_overrides(overrides, allocated, section_manager, unallocated)
        logger.info("  Applied %d manual override(s).", applied)

    # ── 7. Generate report ────────────────────────────────────────────────────
    logger.info("Step 7/7  Generating report → '%s' …", output)
    reporter = ReportGenerator(output)
    reporter.generate_reports(allocated, unallocated, section_manager, allocation_mode)

    # ── Summary ───────────────────────────────────────────────────────────────
    logger.info(banner)
    logger.info("ALLOCATION COMPLETE")
    fully_allocated = sum(
        1 for s in allocated
        if s.get("allocated_primary") and s.get("allocated_secondary")
    )
    partial_allocated = sum(
        1 for s in allocated
        if s.get("allocated_primary") and not s.get("allocated_secondary")
    )
    if allocation_mode == "single":
        fully_allocated = sum(1 for s in allocated if s.get("allocated_primary"))
        partial_allocated = 0

    logger.info("  Total students   : %d", len(students))
    logger.info("  Fully allocated  : %d", fully_allocated)
    logger.info("  Partial (G1 only): %d", partial_allocated)
    logger.info("  Unallocated      : %d", len(unallocated))
    logger.info("  Output file      : %s", Path(output).resolve())
    logger.info("  Log file         : %s", Path("allocation.log").resolve())
    logger.info(banner)

    # ── Section summary table ─────────────────────────────────────────────────
    logger.info("Section enrolment summary:")
    summary = section_manager.get_section_summary()
    for course, sections in summary.items():
        for sec, data in sections.items():
            logger.info(
                "  %-20s  Section %s : %3d / %3d",
                course, sec, data["enrolled"], data["capacity"],
            )


# ── CLI ────────────────────────────────────────────────────────────────────────

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Student Course Allocation Automation System",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--responses",
        default="responses.xlsx",
        metavar="FILE",
        help="Excel file exported from Google Form responses",
    )
    parser.add_argument(
        "--config",
        default="course_config.xlsx",
        metavar="FILE",
        help="Admin course configuration Excel file (course_config.xlsx)",
    )
    parser.add_argument(
        "--output",
        default="allocation_output.xlsx",
        metavar="FILE",
        help="Output Excel file path for allocation results",
    )
    parser.add_argument(
        "--log",
        default="allocation.log",
        metavar="FILE",
        help="Log file path",
    )
    parser.add_argument(
        "--mode",
        default="auto",
        choices=["single", "dual", "auto"],
        help="Allocation mode: single (G1 only), dual (G1+G2), auto (G2 only if present)",
    )
    parser.add_argument(
        "--skip-balance",
        action="store_true",
        help="Skip automatic post-allocation section balancing",
    )
    parser.add_argument(
        "--overrides",
        default=None,
        metavar="FILE",
        help="Optional Excel file with manual admin section/course overrides",
    )
    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    _configure_logging(args.log)
    try:
        _run(
            responses=args.responses,
            config=args.config,
            output=args.output,
            allocation_mode=args.mode,
            balance_sections_enabled=not args.skip_balance,
            overrides=args.overrides,
        )
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        logging.getLogger(__name__).error("%s", exc)
        sys.exit(1)


if __name__ == "__main__":
    main()
