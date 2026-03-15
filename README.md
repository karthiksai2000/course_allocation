

# Life Skill Allocation System

Life Skill Allocation + Course Allocation — one repo, two engines, zero excuses.

---

## What lives here
- Life Skill allocator (slot/skill fairness) — FastAPI backend in [multi_use_course_allocater/backend](multi_use_course_allocater/backend) with a Vite frontend.
- Google Form course allocator (G1/G2) — CLI and Flask UI in [multi_use_course_allocater/course_allocation](multi_use_course_allocater/course_allocation).
- Frontend shell for the life-skill API in [multi_use_course_allocater/frontend](multi_use_course_allocater/frontend).

---

## Quick start: Life Skill API (FastAPI)
- Install deps: `pip install -r multi_use_course_allocater/backend/requirements.txt`
- Run API (from the backend folder): `uvicorn backend_api:app --reload --port 8000`
- Health check: `http://localhost:8000/health`
- Sample config: [multi_use_course_allocater/backend/sample_config.json](multi_use_course_allocater/backend/sample_config.json)

**Fire a run**
- `curl -X POST http://localhost:8000/run-allocation -F "file=@responses.xlsx" -F "config=$(cat sample_config.json)"`
- Or CLI: `python allocate.py --input responses.xlsx --config-json sample_config.json --output-dir output`
- Validate outputs: `python validate_outputs.py --config-json sample_config.json`

**Frontend (optional)**
- `cd multi_use_course_allocater/frontend && npm install && npm run dev`
- Frontend expects API at `http://localhost:8000`; Vite serves at `http://localhost:5173`.

---

## Quick start: Course Allocation (G1/G2 Google Form flow)
- Install deps: `pip install -r multi_use_course_allocater/course_allocation/requirements.txt`
- Default CLI: `python main.py --responses responses.xlsx --config course_config.xlsx --output allocation_output.xlsx --mode auto`
- Generate sample data: `python create_sample_data.py`
- Web UI: `python web_app.py` then open `http://127.0.0.1:5000` (uploads responses/config/overrides, downloads reports per run).

---

## Data expectations
- Life Skill API input Excel must include name, reg no, CGPA, section, and preference columns containing “Row”. Column names are detected by keywords.
- Life Skill config requires `xWeight`, `sectionSkillLimit`, `sectionSlot`, `skillCapacity` (see sample config). Merit score uses $Score = xWeight \times Attendance + (1 - xWeight) \times CGPA$.
- Course Allocation responses follow the Google Form layout described in [multi_use_course_allocater/course_allocation/README.md](multi_use_course_allocater/course_allocation/README.md); config.xlsx lists Course, Group (G1/G2), Sections, Capacity, Prerequisites.

---

## Outputs
- Life Skill API: student_wise.xlsx, section_wise.xlsx, skill_wise.xlsx, slot_wise.xlsx, capacity_dashboard.xlsx, allocation_log.txt, duplicate_students_removed.txt, invalid_cgpa_rows.txt.
- Course Allocation: allocation_output.xlsx with per-section sheets, Course Summary, Unallocated Students; run artifacts live under `multi_use_course_allocater/course_allocation/web_runs/`.

---

## Design highlights
- Section-fair allocation: round-robin within sections; respects per-slot capacity and per-section skill limits ([multi_use_course_allocater/backend/allocate.py](multi_use_course_allocater/backend/allocate.py)).
- Dynamic config: config must ride along with every API call—no stale server state.
- Demand-driven sections: new sections open only when earlier ones fill (see SectionManager in [multi_use_course_allocater/course_allocation/section_manager.py](multi_use_course_allocater/course_allocation/section_manager.py)).
- Admin overrides: drop an overrides Excel to surgically move students before report generation ([multi_use_course_allocater/course_allocation/main.py](multi_use_course_allocater/course_allocation/main.py)).
- Rich reports: Excel styling, per-combo summaries, and unallocated reasons ([multi_use_course_allocater/course_allocation/report_generator.py](multi_use_course_allocater/course_allocation/report_generator.py)).

---

## Troubleshooting fast
- “Missing config keys” or “preference columns not found”: your JSON or Excel headers don’t match the expected keywords—check the sample files.
- “No skills available for section …”: capacity or sectionSkillLimit too low for that slot; raise limits or reduce sections in config.
- Web UI uploads failing: ensure Excel file extensions are .xlsx/.xlsm/.xls and keep API at `http://localhost:8000`.
- Vite frontend cannot reach API: adjust CORS or change `vite.config.js` proxy to your backend port.
* Skill capacity enforcement
* Robust handling of invalid data

This results in a transparent and automated allocation process.
