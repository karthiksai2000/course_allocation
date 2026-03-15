Below is a **clean README you can place in your project**. It explains **what the system does, constraints, algorithm, column detection, and outputs** in a professional way suitable for submission or documentation.

---

# Life Skill Allocation System

## Overview

The **Life Skill Allocation System** is designed to automatically assign students to life skill courses based on:

* Student preferences
* Academic merit (CGPA)
* Attendance
* Section fairness constraints
* Skill capacity limits

The system reads student responses from an Excel file and produces allocation results in multiple structured reports.

The allocation ensures fairness by prioritizing **top students within each section** rather than only global toppers.

---

# Input Data

The system expects an Excel file containing student responses collected through a form.

### Required Columns

The system automatically detects required columns using keyword matching.

| Required Field     | Detection Keyword     |
| ------------------ | --------------------- |
| Student Name       | `student`             |
| Register Number    | `reg`                 |
| CGPA               | `cgpa`                |
| Section            | `section`             |
| Preference Columns | `Row1, Row2, Row3...` |

Example input structure:

| Student Name | Register No | CGPA | Section | Row1        | Row2        | Row3     |
| ------------ | ----------- | ---- | ------- | ----------- | ----------- | -------- |
| Rahul        | 21BCE001    | 9.1  | 1       | Photography | Cooking     | Yoga     |
| Arjun        | 21BCE002    | 8.8  | 1       | Cooking     | Photography | Painting |

---

# Automatic Column Detection

The system automatically identifies columns using flexible keyword matching.

### Student Column Detection

```python
_first_matching_column(columns, keyword)
```

Example:

```
Student Name
Student
Student_Name
```

All will be detected.

---

### Preference Column Ordering

Preference columns are detected and sorted using:

```
Row1
Row2
Row3
```

Sorting logic extracts the number from the column name.

Example:

| Column | Order |
| ------ | ----- |
| Row1   | 1     |
| Row2   | 2     |
| Row10  | 10    |

---

# Configuration Parameters

Allocation rules are controlled through a JSON configuration.

Example configuration:

```json
{
 "xWeight": 0.3,
 "sectionSkillLimit": 4,
 "sectionSlot": {
   "1": "Slot1",
   "2": "Slot1",
   "3": "Slot2"
 },
 "skillCapacity": {
   "Photography": 70,
   "Cooking": 70,
   "Yoga": 70
 }
}
```

---

# Allocation Score Formula

Student merit score is calculated using:

```
Score = xWeight * Attendance + (1 - xWeight) * CGPA
```

Example:

```
xWeight = 0.3
Attendance = 8
CGPA = 9
Score = 0.3 × 8 + 0.7 × 9 = 8.7
```

Students are ranked based on:

1. Score
2. CGPA
3. Attendance
4. Register Number

---

# Constraints Considered

The allocation algorithm enforces the following constraints.

---

## 1. Section to Slot Mapping

Each section belongs to exactly one slot.

Example:

```
Section 1 → Slot1
Section 2 → Slot1
Section 3 → Slot2
```

Students compete only within their assigned slot.

---

## 2. Skill Capacity Constraint

Each skill has a maximum capacity per slot.

Example:

```
Cooking capacity = 70
Photography capacity = 70
```

Allocation cannot exceed this capacity.

---

## 3. Section Skill Limit

To maintain fairness across sections, a maximum number of students from a section can enroll in the same skill.

Example:

```
Section skill limit = 4
```

If a slot contains 5 sections:

```
Max students per skill
= 4 × 5
= 20
```

---

## 4. Section Fairness Constraint

Students are ranked **within their own section**.

Example:

Section 2:

| Rank | Score | Preference |
| ---- | ----- | ---------- |
| 1    | 9.2   | Cooking    |
| 2    | 8.9   | Cooking    |
| 3    | 8.7   | Cooking    |
| 4    | 8.5   | Cooking    |

These top 4 students will be allocated before lower ranked students from the same section.

This ensures:

```
Top students of each section get priority
```

rather than only global toppers.

---

## 5. Preference Order Constraint

Student preferences are respected in order.

```
Row1 → Row2 → Row3
```

The allocator attempts:

1. First preference
2. Second preference
3. Third preference

---

## 6. Fallback Allocation

If all preferences are full or violate constraints, the system assigns the **least filled skill** within the slot.

This prevents allocation failures.

---

## 7. Duplicate Student Handling

If duplicate register numbers appear:

```
latest submission is retained
```

Duplicates are logged separately.

---

## 8. Invalid Data Handling

The system removes rows with:

* Missing CGPA
* Invalid CGPA values
* Missing section
* Missing register number

All removed rows are logged.

---

# Allocation Algorithm

The allocator uses a **section-wise round-robin allocation strategy**.

### Step 1

Students are grouped by section.

### Step 2

Students inside each section are ranked by merit.

### Step 3

Allocation runs in rounds:

```
Round 1 → Topper of each section
Round 2 → 2nd ranked student
Round 3 → 3rd ranked student
```

This ensures fair distribution across sections.

---

# Output Files

The system generates several reports.

### Student Wise Allocation

```
student_wise.xlsx
```

| RegNo | Name | Section | Slot | Skill |
| ----- | ---- | ------- | ---- | ----- |

---

### Section Wise Allocation

```
section_wise.xlsx
```

Sorted by section.

---

### Skill Wise Allocation

```
skill_wise.xlsx
```

Sorted by skill.

---

### Slot Wise Allocation

```
slot_wise.xlsx
```

Sorted by slot.

---

### Capacity Dashboard

```
capacity_dashboard.xlsx
```

| Slot | Skill | Allocated | Capacity |

---

### Logs

```
allocation_log.txt
duplicate_students_removed.txt
invalid_cgpa_rows.txt
```

---

# System Workflow

1. Read Excel responses.
2. Normalize and validate data.
3. Calculate student scores.
4. Rank students within each section.
5. Allocate skills based on preferences and constraints.
6. Generate reports and logs.

---

# Technologies Used

* Python
* Pandas
* Excel processing
* JSON configuration

---

# Future Extensions

Possible improvements:

* Web based dashboard
* API integration
* React admin interface
* Visualization of allocation statistics
* Dynamic configuration interface

---

# Summary

The Life Skill Allocation System ensures:

* Fair distribution across sections
* Preference based allocation
* Skill capacity enforcement
* Robust handling of invalid data

This results in a transparent and automated allocation process.
