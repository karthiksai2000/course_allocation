"""
create_sample_data.py
---------------------
Generates two helper files for testing / demonstration:

  config.xlsx    — course configuration matching the real Google Form structure
  responses.xlsx — 120 simulated Google Form responses
                   (includes duplicates, mixed CGPA formats, edge cases)

Course names, sections and prerequisites are taken directly from
sample_google_form_responses.xlsx:

  G1 (Primary):
    Artificial Intelligence  — no prereq       (2 sections × 35)
    Cloud Computing          — no prereq       (2 sections × 35)
    Data Engineering         — prereq: Data Science (1 section × 30)
    Deep Learning            — prereq: Machine Learning (1 section × 30)

  G2 (Secondary):
    AR/VR                    — no prereq       (2 sections × 30)
    Blockchain               — no prereq       (2 sections × 30)
    Cyber Security           — no prereq       (2 sections × 35)
    Internet of Things       — no prereq       (2 sections × 30)

  Completed courses pool: Machine Learning, Data Science

Run once before executing main.py:
  python create_sample_data.py
"""

import random
from datetime import datetime, timedelta

import pandas as pd


# ── Course configuration — mirrors sample_google_form_responses.xlsx ──────────

COURSE_CONFIG = [
    # G1 — Primary electives
    {
        "Course Name": "Artificial Intelligence",
        "Group": "G1",
        "Sections": 2,
        "Capacity": 35,
        "Prerequisites": "None",
    },
    {
        "Course Name": "Cloud Computing",
        "Group": "G1",
        "Sections": 2,
        "Capacity": 35,
        "Prerequisites": "None",
    },
    {
        "Course Name": "Data Engineering",
        "Group": "G1",
        "Sections": 1,
        "Capacity": 30,
        "Prerequisites": "Data Science",
    },
    {
        "Course Name": "Deep Learning",
        "Group": "G1",
        "Sections": 1,
        "Capacity": 30,
        "Prerequisites": "Machine Learning",
    },
    # G2 — Secondary electives
    {
        "Course Name": "AR/VR",
        "Group": "G2",
        "Sections": 2,
        "Capacity": 30,
        "Prerequisites": "None",
    },
    {
        "Course Name": "Blockchain",
        "Group": "G2",
        "Sections": 2,
        "Capacity": 30,
        "Prerequisites": "None",
    },
    {
        "Course Name": "Cyber Security",
        "Group": "G2",
        "Sections": 2,
        "Capacity": 35,
        "Prerequisites": "None",
    },
    {
        "Course Name": "Internet of Things",
        "Group": "G2",
        "Sections": 2,
        "Capacity": 30,
        "Prerequisites": "None",
    },
]

G1_COURSES = [c["Course Name"] for c in COURSE_CONFIG if c["Group"] == "G1"]
G2_COURSES = [c["Course Name"] for c in COURSE_CONFIG if c["Group"] == "G2"]

# Sections as they appear in the real Google Form (student's class section)
SECTIONS = ["CSE-A", "CSE-B", "CSE-C"]

# Completed-course combinations drawn from the real sample file
COMPLETED_OPTIONS = [
    "None",
    "None",
    "None",
    "None",
    "Machine Learning",
    "Data Science",
    "Machine Learning, Data Science",
    "Machine Learning",
    "Data Science",
]


# ── CGPA formats seen in real data ───────────────────────────────────────────

def _random_cgpa() -> str | float:
    value = round(random.uniform(6.0, 9.9), 2)
    fmt = random.choice(["decimal", "percent_float", "percent_int", "int"])
    if fmt == "decimal":
        return value                            # e.g. 8.76
    if fmt == "percent_float":
        return f"{value * 10:.1f}%"             # e.g. 87.6%
    if fmt == "percent_int":
        return f"{int(round(value * 10))}%"     # e.g. 88%
    return int(round(value * 10))               # e.g. 88


# ── Builders ──────────────────────────────────────────────────────────────────

def create_config(path: str = "course_config.xlsx") -> None:
    # Rename 'Course Name' → 'Course' to match admin-facing column label
    df = pd.DataFrame(COURSE_CONFIG).rename(columns={"Course Name": "Course"})
    df.to_excel(path, index=False)
    print(f"[OK] Created {path}  ({len(df)} courses)")


def create_responses(path: str = "responses.xlsx", n: int = 120) -> None:
    base_time = datetime(2026, 3, 1, 9, 0)
    rows = []

    for i in range(1, n + 1):
        reg = f"21BCS{i:03d}"
        ts = base_time + timedelta(minutes=random.randint(0, 60 * 24 * 45))

        # Intentional duplicates for first 10 students (tests deduplication)
        if 1 <= i <= 10:
            rows.append(_make_row(reg, base_time - timedelta(hours=1), i))

        rows.append(_make_row(reg, ts, i))

    random.shuffle(rows)
    df = pd.DataFrame(rows)
    df.to_excel(path, index=False)
    print(f"[OK] Created {path}  ({len(df)} rows, includes duplicates & edge cases)")


def _make_row(reg: str, ts: datetime, seed: int) -> dict:
    random.seed(seed + int(ts.timestamp()) % 9999)
    g1 = random.choice(G1_COURSES)
    g2 = random.choice(G2_COURSES)
    completed = random.choice(COMPLETED_OPTIONS)

    return {
        "Timestamp": ts,
        "Name": random.choice([
            "Ravi Kumar", "Sneha Reddy", "Kiran Teja", "Arjun Varma",
            "Priya Sharma", "Anil Nair", "Divya Menon", "Suresh Babu",
            "Lakshmi Rao", "Vijay Krishnan",
        ]) + f" {seed:03d}",
        "Registration Number": reg,
        "Email": f"student{seed:03d}@university.edu",
        "Phone Number": f"9{random.randint(100_000_000, 999_999_999)}",
        "Section": random.choice(SECTIONS),
        "CGPA": _random_cgpa(),
        "Courses Already Completed": completed,
        "Select Primary Course (G1)": g1,
        "Select Secondary Course (G2)": g2,
    }


if __name__ == "__main__":
    random.seed(42)
    create_config()                    # → course_config.xlsx
    create_responses()                 # → responses.xlsx
    print("\nInputs ready:")
    print("  Input 1 (student data) : responses.xlsx")
    print("  Input 2 (admin config) : course_config.xlsx")
    print("\nRun:  python main.py")
