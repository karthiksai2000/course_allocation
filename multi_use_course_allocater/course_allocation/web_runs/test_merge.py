import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from section_manager import SectionManager

cfg = [
    {"course_name": "ADS", "group": "G1", "sections": 3, "capacity": 60, "prerequisites": []},
    {"course_name": "ML",  "group": "G1", "sections": 2, "capacity": 60, "prerequisites": []},
]
sm = SectionManager(cfg)

# Simulate pre-demand-driven state: open extra sections manually
sm.section_seats["ADS"]["B"] = {"capacity": 60, "enrolled": []}
sm.section_seats["ADS"]["C"] = {"capacity": 60, "enrolled": []}
sm.section_seats["ML"]["B"]  = {"capacity": 60, "enrolled": []}

students = {}
for i in range(39):
    r = f"ADS_A_{i}"
    sm.section_seats["ADS"]["A"]["enrolled"].append(r)
    students[r] = {"reg_no": r, "allocated_primary": "ADS", "allocated_section": "A", "allocated_secondary": None}
for i in range(21):
    r = f"ADS_B_{i}"
    sm.section_seats["ADS"]["B"]["enrolled"].append(r)
    students[r] = {"reg_no": r, "allocated_primary": "ADS", "allocated_section": "B", "allocated_secondary": None}
for i in range(51):
    r = f"ML_A_{i}"
    sm.section_seats["ML"]["A"]["enrolled"].append(r)
    students[r] = {"reg_no": r, "allocated_primary": "ML", "allocated_section": "A", "allocated_secondary": None}
for i in range(9):
    r = f"ML_B_{i}"
    sm.section_seats["ML"]["B"]["enrolled"].append(r)
    students[r] = {"reg_no": r, "allocated_primary": "ML", "allocated_section": "B", "allocated_secondary": None}

print("BEFORE:")
for c in ["ADS", "ML"]:
    for s, d in sorted(sm.section_seats[c].items()):
        print(f"  {c} Section {s}: {len(d['enrolled'])}/{d['capacity']}")

removed = sm.merge_underfilled_sections(students)
sm.prune_empty_sections()

print(f"Sections removed: {removed}")
print("AFTER:")
for c in ["ADS", "ML"]:
    for s, d in sorted(sm.section_seats[c].items()):
        print(f"  {c} Section {s}: {len(d['enrolled'])}/{d['capacity']}")

moved_b_to_a = sum(1 for r in students if r.startswith("ADS_B_") and students[r]["allocated_section"] == "A")
print(f"ADS-B students moved to A: {moved_b_to_a}/21")
print("PASSED" if moved_b_to_a == 21 else "FAILED")
