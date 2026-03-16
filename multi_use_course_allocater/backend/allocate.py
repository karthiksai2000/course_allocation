import argparse
import json
import os
import re
from typing import Any

import pandas as pd


def _first_matching_column(columns: list[str], keyword: str) -> str:
    for col in columns:
        if keyword in col.lower():
            return col
    raise ValueError(f"Missing required column containing '{keyword}'")


def _preference_order(col_name: str) -> int:
    match = re.search(r"row\s*(\d+)", col_name, flags=re.IGNORECASE)
    if match:
        return int(match.group(1))
    digits = re.findall(r"\d+", col_name)
    return int(digits[-1]) if digits else 10**9


def normalize_config(config: dict[str, Any]) -> dict[str, Any]:
    required = {"xWeight", "sectionSkillLimit", "sectionSlot"}
    missing = sorted(required - set(config.keys()))
    if missing:
        raise ValueError(f"Missing config keys: {', '.join(missing)}")

    x_weight = float(config["xWeight"])
    if x_weight < 0 or x_weight > 1:
        raise ValueError("xWeight must be between 0 and 1")

    section_skill_limit = int(config["sectionSkillLimit"])
    if section_skill_limit <= 0:
        raise ValueError("sectionSkillLimit must be greater than 0")

    raw_section_slot = config["sectionSlot"]
    if not isinstance(raw_section_slot, dict) or not raw_section_slot:
        raise ValueError("sectionSlot must be a non-empty object")

    section_slot: dict[int, str] = {}
    for section, slot in raw_section_slot.items():
        normalized_section = int(section)
        normalized_slot = str(slot).strip()
        if not normalized_slot:
            raise ValueError(f"Section {normalized_section} has an empty slot value")
        section_slot[normalized_section] = normalized_slot

    raw_skill_capacity = config.get("skillCapacity")
    skill_capacity: dict[str, int] | None = None
    if raw_skill_capacity is not None:
        if not isinstance(raw_skill_capacity, dict) or not raw_skill_capacity:
            raise ValueError("skillCapacity must be a non-empty object when provided")

        skill_capacity = {}
        for skill, capacity in raw_skill_capacity.items():
            normalized_skill = str(skill).strip()
            normalized_capacity = int(capacity)
            if not normalized_skill:
                raise ValueError("skillCapacity contains an empty skill name")
            if normalized_capacity <= 0:
                raise ValueError(f"Capacity for skill '{normalized_skill}' must be greater than 0")
            skill_capacity[normalized_skill] = normalized_capacity

    default_skill_capacity = config.get("defaultSkillCapacity")
    if default_skill_capacity is not None:
        default_skill_capacity = int(default_skill_capacity)
        if default_skill_capacity <= 0:
            raise ValueError("defaultSkillCapacity must be greater than 0 when provided")

    return {
        "xWeight": x_weight,
        "sectionSkillLimit": section_skill_limit,
        "sectionSlot": section_slot,
        "skillCapacity": skill_capacity,
        "defaultSkillCapacity": default_skill_capacity,
    }


def run_allocation(df: pd.DataFrame, config: dict[str, Any]) -> dict[str, Any]:
    cfg = normalize_config(config)
    x_weight = cfg["xWeight"]
    section_slot = cfg["sectionSlot"]
    skill_capacity = cfg["skillCapacity"]
    section_skill_limit = cfg["sectionSkillLimit"]
    default_skill_capacity = cfg.get("defaultSkillCapacity")

    name_col = _first_matching_column(list(df.columns), "student")
    reg_col = _first_matching_column(list(df.columns), "reg")
    cgpa_col = _first_matching_column(list(df.columns), "cgpa")
    section_col = _first_matching_column(list(df.columns), "section")

    meta_keys = {"student", "name", "reg", "registration", "cgpa", "section", "attendance"}
    pref_keywords = ("row", "pref", "preference", "choice", "option", "skill")

    pref_cols = sorted(
        [c for c in df.columns if any(k in c.lower() for k in pref_keywords)],
        key=_preference_order,
    )

    # Heuristic fallback: treat non-meta object columns as preferences (helps sheets where headers are plain course names).
    if not pref_cols:
        for col in df.columns:
            cl = col.lower()
            if any(k in cl for k in meta_keys):
                continue
            if df[col].dtype == object:
                pref_cols.append(col)
        pref_cols = sorted(pref_cols, key=_preference_order)

    if not pref_cols:
        raise ValueError(
            "No preference columns found. Add headers with 'Row'/'Preference' or ensure preference columns are non-numeric text."
        )

    def _derive_skills_from_preferences(frame: pd.DataFrame, pref_columns: list[str]) -> list[str]:
        discovered: set[str] = set()
        for col in pref_columns:
            for value in frame[col].dropna().astype(str).str.strip():
                if not value or value.lower() in {"nan", "none", "na", "n/a", "-"}:
                    continue
                discovered.add(value)
        return sorted(discovered)

    if skill_capacity:
        skills = list(skill_capacity.keys())
    else:
        skills = _derive_skills_from_preferences(df, pref_cols)
        if not skills:
            raise ValueError("Could not auto-detect skills from preference columns.")

        # Set a generous default capacity per skill to allow allocation unless bounded explicitly.
        fallback_capacity = default_skill_capacity
        if fallback_capacity is None:
            fallback_capacity = section_skill_limit * max(1, len(section_slot))
        skill_capacity = {skill: fallback_capacity for skill in skills}

    for col in df.columns:
        if df[col].dtype == object:
            df[col] = df[col].astype(str).str.strip()

    df[reg_col] = df[reg_col].astype(str).str.upper().str.strip()
    df = df.dropna(subset=[name_col, reg_col, section_col])

    duplicate_regs = df[df.duplicated(subset=[reg_col], keep=False)][reg_col].astype(str).unique().tolist()
    df = df.drop_duplicates(subset=[reg_col], keep="last")

    df[cgpa_col] = df[cgpa_col].astype(str).str.strip().str.replace(",", ".", regex=False)
    df[cgpa_col] = pd.to_numeric(df[cgpa_col], errors="coerce")

    invalid_cgpa_regs = df[df[cgpa_col].isnull()][reg_col].astype(str).tolist()
    df = df.dropna(subset=[cgpa_col])

    df[section_col] = pd.to_numeric(df[section_col], errors="coerce")
    df = df.dropna(subset=[section_col])
    df[section_col] = df[section_col].astype(int)

    attendance_col = next((c for c in df.columns if "attendance" in c.lower()), None)
    if attendance_col:
        df[attendance_col] = pd.to_numeric(df[attendance_col], errors="coerce")
        df["attendance_norm"] = (df[attendance_col] / 10).fillna(0)
    else:
        df["attendance_norm"] = 0

    df["score"] = x_weight * df["attendance_norm"] + (1 - x_weight) * df[cgpa_col]

    slots = set(section_slot.values())
    skill_count = {slot: {skill: 0 for skill in skills} for slot in slots}
    section_skill_count = {section: {skill: 0 for skill in skills} for section in section_slot}

    results: list[dict[str, Any]] = []
    allocation_log: list[str] = []

    # Rank within each section, then allocate round-robin across sections for fairness
    sections = {}
    for section, group in df.groupby(section_col):
        sorted_group = group.sort_values(
            by=["score", cgpa_col, "attendance_norm", reg_col],
            ascending=[False, False, False, True],
        )
        sections[section] = sorted_group.to_dict("records")

    max_len = max(len(students) for students in sections.values()) if sections else 0

    for rank in range(max_len):
        for section, students in sections.items():
            if rank >= len(students):
                continue

            row = students[rank]
            name = row[name_col]
            reg = row[reg_col]

            if section not in section_slot:
                raise ValueError(f"Section {section} is not mapped in sectionSlot")

            slot = section_slot[section]
            preferences = [row[p] for p in pref_cols]
            allocated = False

            for skill in preferences:
                if skill not in skills:
                    continue

                if (
                    skill_count[slot][skill] < skill_capacity[skill]
                    and section_skill_count[section][skill] < section_skill_limit
                ):
                    skill_count[slot][skill] += 1
                    section_skill_count[section][skill] += 1
                    results.append(
                        {
                            "RegNo": reg,
                            "Name": name,
                            "Section": section,
                            "Slot": slot,
                            "Skill": skill,
                        }
                    )
                    allocation_log.append(f"{reg} -> {skill} ({slot}) preference")
                    allocated = True
                    break

            if allocated:
                continue

            available_skills = [
                s
                for s in skills
                if skill_count[slot][s] < skill_capacity[s]
                and section_skill_count[section][s] < section_skill_limit
            ]

            if not available_skills:
                raise ValueError(f"No skills available for section {section} in slot {slot}")

            least_skill = min(available_skills, key=lambda s: skill_count[slot][s])
            skill_count[slot][least_skill] += 1
            section_skill_count[section][least_skill] += 1
            results.append(
                {
                    "RegNo": reg,
                    "Name": name,
                    "Section": section,
                    "Slot": slot,
                    "Skill": least_skill,
                }
            )
            allocation_log.append(f"{reg} -> {least_skill} ({slot}) fallback")

    result_df = pd.DataFrame(results)
    section_wise_df = result_df.sort_values("Section")
    skill_wise_df = result_df.sort_values("Skill")
    slot_wise_df = result_df.sort_values("Slot")

    dashboard_rows: list[dict[str, Any]] = []
    for slot, slot_skills in skill_count.items():
        for skill, allocated in slot_skills.items():
            dashboard_rows.append(
                {
                    "Slot": slot,
                    "Skill": skill,
                    "Allocated": allocated,
                    "Capacity": skill_capacity[skill],
                }
            )
    dashboard_df = pd.DataFrame(dashboard_rows)

    unallocated = [
        {"RegNo": reg, "Reason": "Duplicate student removed"} for reg in duplicate_regs
    ] + [
        {"RegNo": reg, "Reason": "Invalid or missing CGPA"} for reg in invalid_cgpa_regs
    ]

    return {
        "summary": {
            "studentsLoaded": int(len(df)),
            "studentsAllocated": int(len(result_df)),
            "duplicateStudentsRemoved": int(len(duplicate_regs)),
            "invalidCgpaRowsRemoved": int(len(invalid_cgpa_regs)),
        },
        "studentWise": result_df.to_dict(orient="records"),
        "sectionWise": section_wise_df.to_dict(orient="records"),
        "skillWise": skill_wise_df.to_dict(orient="records"),
        "slotWise": slot_wise_df.to_dict(orient="records"),
        "capacityDashboard": dashboard_df.to_dict(orient="records"),
        "logs": {
            "allocationLog": allocation_log,
            "duplicateStudentsRemoved": duplicate_regs,
            "invalidCgpaRows": invalid_cgpa_regs,
            "unallocatedOverall": unallocated,
        },
    }


def save_outputs(result: dict[str, Any], output_dir: str) -> None:
    os.makedirs(output_dir, exist_ok=True)

    student_df = pd.DataFrame(result["studentWise"])
    section_df = pd.DataFrame(result["sectionWise"])
    skill_df = pd.DataFrame(result["skillWise"])
    slot_df = pd.DataFrame(result["slotWise"])
    dash_df = pd.DataFrame(result["capacityDashboard"])
    unallocated_df = pd.DataFrame(result["logs"].get("unallocatedOverall", []))

    student_df.to_excel(os.path.join(output_dir, "student_wise.xlsx"), index=False)
    section_df.to_excel(os.path.join(output_dir, "section_wise.xlsx"), index=False)
    skill_df.to_excel(os.path.join(output_dir, "skill_wise.xlsx"), index=False)
    slot_df.to_excel(os.path.join(output_dir, "slot_wise.xlsx"), index=False)
    dash_df.to_excel(os.path.join(output_dir, "capacity_dashboard.xlsx"), index=False)
    if not unallocated_df.empty:
        unallocated_df.to_excel(os.path.join(output_dir, "unallocated_overall.xlsx"), index=False)

    with open(os.path.join(output_dir, "allocation_log.txt"), "w", encoding="utf-8") as file_obj:
        for line in result["logs"]["allocationLog"]:
            file_obj.write(line + "\n")

    with open(
        os.path.join(output_dir, "duplicate_students_removed.txt"), "w", encoding="utf-8"
    ) as file_obj:
        for reg in result["logs"]["duplicateStudentsRemoved"]:
            file_obj.write(str(reg) + "\n")

    with open(os.path.join(output_dir, "invalid_cgpa_rows.txt"), "w", encoding="utf-8") as file_obj:
        for reg in result["logs"]["invalidCgpaRows"]:
            file_obj.write(str(reg) + "\n")


def run_allocation_from_excel(
    input_file: str,
    config: dict[str, Any],
    output_dir: str | None = None,
) -> dict[str, Any]:
    dataframe = pd.read_excel(input_file)
    result = run_allocation(dataframe, config)
    if output_dir:
        save_outputs(result, output_dir)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Run life skill allocation from Excel and JSON config")
    parser.add_argument("--input", required=True, help="Path to input Excel file")
    parser.add_argument("--config-json", required=True, help="Path to JSON config file")
    parser.add_argument("--output-dir", default="output", help="Directory to save Excel outputs")
    args = parser.parse_args()

    with open(args.config_json, "r", encoding="utf-8") as file_obj:
        config = json.load(file_obj)

    result = run_allocation_from_excel(args.input, config, args.output_dir)
    print("Allocation completed")
    print(json.dumps(result["summary"], indent=2))


if __name__ == "__main__":
    main()