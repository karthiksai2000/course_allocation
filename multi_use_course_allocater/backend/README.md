# Life Skill Allocation - Dynamic Config Architecture

This project now uses runtime configuration from frontend to backend to allocator.

## Architecture

React UI -> FastAPI -> allocation engine (`allocate.py`)

`config.py` has been removed. Configuration is now mandatory in request payloads.

## Backend setup

1. Create/activate Python environment.
2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Run API:

```bash
uvicorn backend_api:app --reload --port 8000
```

4. Health check:

```bash
GET http://localhost:8000/health
```

## Frontend setup (no Tailwind)

```bash
cd frontend
npm install
npm run dev
```

Frontend runs on `http://localhost:5173` and calls backend on `http://localhost:8000`.

## API contract

### POST `/run-allocation`

Multipart form fields:
- `file`: Excel file (`.xlsx`/`.xls`)
- `config`: JSON string

Config shape:

```json
{
  "xWeight": 0.3,
  "sectionSkillLimit": 4,
  "sectionSlot": {
    "1": "Slot1",
    "2": "Slot1"
  },
  "skillCapacity": {
    "German": 70,
    "French": 70
  }
}
```

Response includes:
- `summary`
- `studentWise`
- `sectionWise`
- `skillWise`
- `slotWise`
- `capacityDashboard`
- `logs`

## CLI usage without API (still dynamic)

```bash
python allocate.py --input LifeSkills1.xlsx --config-json sample_config.json --output-dir output
```

## Validation usage

```bash
python validate_outputs.py --config-json sample_config.json
```
