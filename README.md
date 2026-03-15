
---

# 🎓 University Course & Life Skill Allocation Platform

![Python](https://img.shields.io/badge/Python-3.10-blue)
![React](https://img.shields.io/badge/Frontend-React%20%2B%20Vite-green)
![FastAPI](https://img.shields.io/badge/API-FastAPI-teal)
![Flask](https://img.shields.io/badge/API-Flask-orange)
![Deployment](https://img.shields.io/badge/Hosted%20On-Render-purple)
![License](https://img.shields.io/badge/License-MIT-lightgrey)

A **production-ready full-stack university allocation platform** that automates:

* 🎯 Department elective course allocation
* 🎯 Life skill activity allocation

The system ensures **fairness, scalability, and transparency** using **data-driven allocation algorithms and constraint-based optimization**.

---

# 🌐 Live Production System

### Unified Allocation Dashboard

[https://course-allocation-2-frontend.onrender.com/](https://course-allocation-2-frontend.onrender.com/)

### Backend APIs

**Life Skill Allocation API**

```text
https://lifeskill-api.onrender.com
```

**Department Elective Allocation API**

```text
https://dept-allocator.onrender.com
```

Hosted on **Render Cloud Infrastructure**.

---

# 🏗 System Architecture

```
                   ┌────────────────────┐
                   │   React Frontend   │
                   │   (Vite Dashboard) │
                   └─────────┬──────────┘
                             │
                             ▼
                  ┌──────────────────────┐
                  │   Allocation Gateway │
                  │  (Frontend API calls)│
                  └─────────┬────────────┘
                            │
           ┌────────────────┴───────────────┐
           │                                │
           ▼                                ▼
┌───────────────────────┐        ┌───────────────────────┐
│ Life Skill API        │        │ Course Allocation API │
│ FastAPI Service       │        │ Flask Service         │
└────────────┬──────────┘        └────────────┬──────────┘
             │                                │
             ▼                                ▼
  ┌────────────────────┐           ┌─────────────────────┐
  │ Slot Skill Engine  │           │ G1/G2 Course Engine │
  │ (Section fairness) │           │ (CGPA priority)     │
  └────────────────────┘           └─────────────────────┘
```

---

# 🧠 Algorithms & Data Structures

The system applies multiple **DSA concepts** to guarantee efficient and fair allocation.

---

## Greedy Allocation Strategy

Students are allocated based on **best possible available option** under constraints.

Example:

```
Student → highest preference skill
subject to capacity and section limits
```

Used in both engines.

Time Complexity:

```
O(n log n)
```

---

## Round Robin Section Fairness

Life Skill allocation ensures **section-wise fairness**.

Instead of global ranking:

```
Round 1 → Section toppers
Round 2 → Second rank students
Round 3 → Third rank students
```

This prevents:

```
Large sections dominating seats
```

---

## Priority Ranking

Students ranked using **multi-criteria sorting**:

```
Score = xWeight × Attendance + (1 − xWeight) × CGPA
```

Tie breaking:

1️⃣ Score
2️⃣ CGPA
3️⃣ Attendance
4️⃣ Timestamp

Data structure used:

```
Sorted list / priority queue
```

---

## Hash Maps for O(1) Constraint Checking

Several constraints require instant lookup.

Example:

```
skill_count[slot][skill]
section_skill_count[section][skill]
```

Ensures **constant time seat validation**.

---

## Constraint Satisfaction Model

Allocation must satisfy:

| Constraint          | Purpose                      |
| ------------------- | ---------------------------- |
| Skill Capacity      | Limit students per skill     |
| Section Skill Limit | Maintain section fairness    |
| Prerequisites       | Ensure eligibility           |
| Section Balancing   | Prevent uneven distributions |
| Preference Priority | Respect student choices      |

This resembles a simplified **Constraint Satisfaction Problem (CSP)**.

---

# ⚙️ Core Modules

The platform consists of **two independent allocation engines**.

---

# 📘 Department Course Allocation Engine

Located in:

```
course_allocation/
```

Allocates **G1 and G2 department electives** based on:

* CGPA ranking
* Course prerequisites
* Seat availability
* Section balancing

### Allocation Workflow

```
1. Sort students by CGPA
2. Allocate G1 (primary elective)
3. Allocate G2 (secondary elective)
4. Attempt section swaps if needed
5. Apply section balancing
```

---

# 🧑‍🎓 Life Skill Allocation Engine

Located in:

```
backend/
```

Allocates life skill courses such as:

* Photography
* Cooking
* Yoga
* Dance
* Music
* Handcraft

### Allocation Strategy

```
Section Fair Round Robin
+
Preference Priority
+
Slot Capacity Constraints
```

Example:

```
Slot1 sections → 1,2,3,4,5
Section skill limit → 4
```

Maximum skill allocation:

```
4 × 5 = 20 students
```

Ensuring fair distribution across sections.

---

# 📊 Generated Reports

### Life Skill Reports

```
student_wise.xlsx
section_wise.xlsx
skill_wise.xlsx
slot_wise.xlsx
capacity_dashboard.xlsx
```

---

### Department Allocation Reports

```
allocation_output.xlsx
```

Contains:

| Sheet          | Description                 |
| -------------- | --------------------------- |
| Section Sheets | Allocated students          |
| Course Summary | Seat utilization            |
| Unallocated    | Students without allocation |

---

# 🖥 Frontend Dashboard

Built with:

```
React + Vite
```

Features:

✔ Upload student responses
✔ Upload configuration files
✔ Run allocation engines
✔ Download Excel reports
✔ View allocation results

Environment variables:

```
VITE_LIFESKILL_API=https://lifeskill-api.onrender.com
VITE_DEPT_ALLOC_URL=https://dept-allocator.onrender.com
```

---

# ☁️ Cloud Deployment

| Layer                 | Technology   |
| --------------------- | ------------ |
| Frontend              | React + Vite |
| Life Skill API        | FastAPI      |
| Course Allocation API | Flask        |
| Data Processing       | Pandas       |
| Excel Reports         | OpenPyXL     |
| Hosting               | Render       |

---

# 🚀 Performance

| Metric                  | Value       |
| ----------------------- | ----------- |
| Students supported      | 2000+       |
| Average allocation time | < 5 seconds |
| API response time       | < 2 seconds |

---

# 📂 Repository Structure

```
multi_use_course_allocater
│
├── backend
│   ├── allocate.py
│   ├── backend_api.py
│   └── validate_outputs.py
│
├── course_allocation
│   ├── main.py
│   ├── web_app.py
│   ├── section_manager.py
│   ├── course_allocator.py
│   └── report_generator.py
│
├── frontend
│   └── React dashboard
│
└── documentation
```

---

# 🔒 Data Validation

The system automatically detects and handles:

* duplicate student submissions
* invalid CGPA values
* missing preferences
* invalid skill selections

All anomalies are logged for transparency.

---

# 🔮 Future Improvements

Planned enhancements include:

* AI based preference prediction
* interactive allocation visualization
* admin override interface
* real-time seat tracking

---

# 📜 Project Goal

This platform demonstrates practical applications of:

* Data Structures
* Algorithm Design
* Full-Stack Development
* Cloud Deployment

to solve a **real university resource allocation problem**.

---

⭐ If you find this project useful, please consider starring the repository.

---
