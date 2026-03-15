import argparse
import json
import os

import pandas as pd

from allocate import normalize_config


BASE = r"c:/karthik/projects/lifeskill_allocater"
INPUT_PATH = os.path.join(BASE, "LifeSkills1.xlsx")
OUTPUT_PATH = os.path.join(BASE, "output", "student_wise.xlsx")
SECTION_WISE_PATH = os.path.join(BASE, "output", "section_wise.xlsx")
SKILL_WISE_PATH = os.path.join(BASE, "output", "skill_wise.xlsx")
SLOT_WISE_PATH = os.path.join(BASE, "output", "slot_wise.xlsx")
DASHBOARD_PATH = os.path.join(BASE, "output", "capacity_dashboard.xlsx")


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate allocation outputs against runtime config")
    parser.add_argument("--config-json", required=True, help="Path to JSON config file")
    parser.add_argument("--input", default=INPUT_PATH, help="Input source Excel path")
    parser.add_argument("--output", default=OUTPUT_PATH, help="student_wise.xlsx path")
    parser.add_argument("--section-output", default=SECTION_WISE_PATH, help="section_wise.xlsx path")
    parser.add_argument("--skill-output", default=SKILL_WISE_PATH, help="skill_wise.xlsx path")
    parser.add_argument("--slot-output", default=SLOT_WISE_PATH, help="slot_wise.xlsx path")
    parser.add_argument("--dashboard-output", default=DASHBOARD_PATH, help="capacity_dashboard.xlsx path")
    args = parser.parse_args()

    with open(args.config_json, "r", encoding="utf-8") as file_obj:
        config = normalize_config(json.load(file_obj))

    x_weight = config["xWeight"]
    section_slot = config["sectionSlot"]
    skill_capacity = config["skillCapacity"]
    section_skill_limit = config["sectionSkillLimit"]

    src = pd.read_excel(args.input)
    out = pd.read_excel(args.output)
    section_out = pd.read_excel(args.section_output)
    skill_out = pd.read_excel(args.skill_output)
    slot_out = pd.read_excel(args.slot_output)
    dash = pd.read_excel(args.dashboard_output)

    name_col = [c for c in src.columns if "student" in c.lower()][0]
    reg_col = [c for c in src.columns if "reg" in c.lower()][0]
    cgpa_col = [c for c in src.columns if "cgpa" in c.lower()][0]
    section_col = [c for c in src.columns if "section" in c.lower()][0]

    attendance_col = next((c for c in src.columns if "attendance" in c.lower()), None)
    pref_cols = sorted(
        [c for c in src.columns if "row" in c.lower()],
        key=lambda x: int(x.split("Row")[1].replace("]", "")),
    )

    skills = set(skill_capacity.keys())

    src2 = src.drop_duplicates(subset=[reg_col], keep="last").copy()
    src2 = src2.dropna(subset=[name_col, reg_col, cgpa_col, section_col]).copy()
    src2[cgpa_col] = pd.to_numeric(src2[cgpa_col], errors="coerce")
    src2 = src2.dropna(subset=[cgpa_col]).copy()

    if attendance_col:
        src2[attendance_col] = pd.to_numeric(src2[attendance_col], errors="coerce")
        src2["attendance_norm"] = src2[attendance_col] / 10
    else:
        src2["attendance_norm"] = 0

    src2["score"] = x_weight * src2["attendance_norm"] + (1 - x_weight) * src2[cgpa_col]

    src2 = src2.sort_values(
        by=["score", cgpa_col, "attendance_norm", reg_col],
        ascending=[False, False, False, True],
    ).reset_index(drop=True)

    issues = []
    summary = {}

    summary["source_clean_rows"] = len(src2)
    summary["output_rows"] = len(out)
    if len(src2) != len(out):
        issues.append(f"Row count mismatch: cleaned source={len(src2)} output={len(out)}")

    summary["section_wise_rows"] = len(section_out)
    summary["skill_wise_rows"] = len(skill_out)
    summary["slot_wise_rows"] = len(slot_out)

    if len(section_out) != len(out):
        issues.append(f"section_wise row mismatch: {len(section_out)} vs {len(out)}")

    if len(skill_out) != len(out):
        issues.append(f"skill_wise row mismatch: {len(skill_out)} vs {len(out)}")

    if len(slot_out) != len(out):
        issues.append(f"slot_wise row mismatch: {len(slot_out)} vs {len(out)}")

    def _normalized_records(df: pd.DataFrame) -> set[tuple]:
        return {
            (str(r["RegNo"]), str(r["Name"]), str(r["Section"]), str(r["Slot"]), str(r["Skill"]))
            for _, r in df.iterrows()
        }

    base_records = _normalized_records(out)
    if _normalized_records(section_out) != base_records:
        issues.append("section_wise records differ from student_wise")

    if _normalized_records(skill_out) != base_records:
        issues.append("skill_wise records differ from student_wise")

    if _normalized_records(slot_out) != base_records:
        issues.append("slot_wise records differ from student_wise")

    dup_out = out[out.duplicated(subset=["RegNo"], keep=False)]
    summary["duplicate_reg_in_output"] = int(dup_out["RegNo"].nunique())
    if not dup_out.empty:
        issues.append(f"Duplicate allocations in output for {dup_out['RegNo'].nunique()} registers")

    invalid_slot_rows = []
    for _, r in out.iterrows():
        sec = int(r["Section"])
        expected_slot = section_slot.get(sec)
        if expected_slot is None or str(r["Slot"]) != str(expected_slot):
            invalid_slot_rows.append((r["RegNo"], sec, r["Slot"], expected_slot))

    summary["invalid_section_slot"] = len(invalid_slot_rows)
    if invalid_slot_rows:
        issues.append(f"Section-slot mismatch rows: {len(invalid_slot_rows)}")

    invalid_skill = out[~out["Skill"].isin(skills)]
    summary["invalid_skill_rows"] = len(invalid_skill)
    if not invalid_skill.empty:
        issues.append(f"Invalid skill names found: {len(invalid_skill)} rows")

    capacity_violations = []
    for (slot, skill), grp in out.groupby(["Slot", "Skill"]):
        cap = skill_capacity.get(skill)
        if cap is not None and len(grp) > cap:
            capacity_violations.append((slot, skill, len(grp), cap))

    summary["capacity_violations"] = len(capacity_violations)
    if capacity_violations:
        issues.append(f"Capacity violations: {len(capacity_violations)} slot-skill groups")

    sec_skill = out.groupby(["Section", "Skill"]).size().reset_index(name="count")
    sec_limit_bad = sec_skill[sec_skill["count"] > section_skill_limit]
    summary["section_skill_limit_violations"] = len(sec_limit_bad)
    if not sec_limit_bad.empty:
        issues.append(
            f"Per-section per-skill >{section_skill_limit} violations: {len(sec_limit_bad)} groups"
        )

    pref_map = {}
    for _, r in src2.iterrows():
        prefs = [r[c] for c in pref_cols if pd.notna(r[c])]
        pref_map[r[reg_col]] = prefs

    on_preference = 0
    fallback = 0
    missing_in_source = 0

    for _, r in out.iterrows():
        reg = r["RegNo"]
        skill = r["Skill"]
        prefs = pref_map.get(reg)

        if prefs is None:
            missing_in_source += 1
            continue

        if skill in prefs:
            on_preference += 1
        else:
            fallback += 1

    summary["allocated_on_preference"] = on_preference
    summary["fallback_allocations"] = fallback
    summary["output_reg_missing_in_clean_source"] = missing_in_source

    alloc_counts = out.groupby(["Slot", "Skill"]).size().to_dict()
    dash_mismatch = []
    for _, r in dash.iterrows():
        slot = r["Slot"]
        skill = r["Skill"]
        allocated = int(r["Allocated"])
        expected = int(alloc_counts.get((slot, skill), 0))
        if allocated != expected:
            dash_mismatch.append((slot, skill, allocated, expected))

    summary["dashboard_rows"] = len(dash)
    summary["dashboard_count_mismatches"] = len(dash_mismatch)
    if dash_mismatch:
        issues.append(f"capacity_dashboard allocation mismatches: {len(dash_mismatch)}")

    print("=== VALIDATION SUMMARY ===")
    for k, v in summary.items():
        print(f"{k}: {v}")

    print("\n=== FINDINGS ===")
    if issues:
        for idx, item in enumerate(issues, 1):
            print(f"{idx}. {item}")
    else:
        print("No hard-rule violations found against current constraints/config.")

    if fallback:
        fb = out[out.apply(lambda x: x["Skill"] not in pref_map.get(x["RegNo"], []), axis=1)]
        print("\nTop fallback-assigned skills:")
        print(fb["Skill"].value_counts().head(10).to_string())

    if invalid_slot_rows:
        print("\nSample section-slot mismatches (up to 10):")
        for row in invalid_slot_rows[:10]:
            print(row)

    if capacity_violations:
        print("\nSample capacity violations (up to 10):")
        for row in capacity_violations[:10]:
            print(row)

    if not sec_limit_bad.empty:
        print("\nSample section-skill > limit (up to 10):")
        print(sec_limit_bad.head(10).to_string(index=False))

    if dash_mismatch:
        print("\nSample dashboard mismatches (up to 10):")
        for row in dash_mismatch[:10]:
            print(row)


if __name__ == "__main__":
    main()
