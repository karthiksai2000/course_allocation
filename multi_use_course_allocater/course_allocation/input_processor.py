"""
input_processor.py
------------------
Handles loading course configuration and student response data,
cleaning/normalising raw values, and validating course preferences.
"""

import json
import logging
import re
from datetime import datetime
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

# ── Standard column names (after normalisation) ──────────────────────────────
COL_TIMESTAMP = "Timestamp"
COL_NAME = "Name"
COL_REG = "Registration Number"
COL_EMAIL = "Email"
COL_PHONE = "Phone Number"
COL_SECTION = "Section"
COL_CGPA = "CGPA"
COL_COMPLETED = "Courses Already Completed"
COL_G1 = "Select Primary Course (G1)"
COL_G2 = "Select Secondary Course (G2)"


def _normalise_course_name(raw: object) -> str:
    """Normalise course names to improve matching across sheets/forms."""
    text = str(raw).replace("\xa0", " ").strip()
    text = re.sub(r"\s+", " ", text)
    return text


# ─────────────────────────────────────────────────────────────────────────────
# Course configuration loader
# ─────────────────────────────────────────────────────────────────────────────

def auto_build_config(
    responses_path: str,
    save_path: str = "course_config.xlsx",
    default_sections: int = 2,
    default_capacity: int = 60,
) -> list[dict]:
    """
    Auto-generate a course configuration by reading the unique G1 / G2 course
    names directly from the responses Excel file.

    Produces a ``course_config.xlsx`` with sane defaults that the admin can
    later edit to fine-tune sections, capacities, and prerequisites.

    Returns the same list-of-dicts format as ``load_courses_config()``.
    """
    try:
        df = pd.read_excel(responses_path, engine="openpyxl")
    except Exception as exc:
        raise RuntimeError(f"Cannot read responses file for auto-config: {exc}") from exc

    # Find all G1 and G2 preference columns by keyword (supports rank [1..N]).
    g1_cols = [
        c for c in df.columns
        if "primary" in c.lower() or ("g1" in c.lower() and "course" in c.lower())
    ]
    g2_cols = [
        c for c in df.columns
        if "secondary" in c.lower() or ("g2" in c.lower() and "course" in c.lower())
    ]

    if not g1_cols and not g2_cols:
        raise ValueError(
            "Could not find G1/G2 course columns in responses file. "
            "Please provide a course_config.xlsx manually."
        )

    def _collect_courses(cols: list[str]) -> list[str]:
        found: set[str] = set()
        for col in cols:
            for value in df[col].dropna().tolist():
                for item in str(value).split(","):
                    name = item.strip()
                    if name and name.lower() not in {"none", "nil", "na", "n/a", "-"}:
                        found.add(name)
        return sorted(found)

    g1_courses = _collect_courses(g1_cols)
    g2_courses = _collect_courses(g2_cols)

    rows = []
    courses: list[dict] = []

    for name in g1_courses:
        name = str(name).strip()
        if not name:
            continue
        rows.append({
            "Course": name, "Group": "G1",
            "Sections": default_sections, "Capacity": default_capacity,
            "Prerequisites": "None",
        })
        courses.append({
            "course_name": name, "group": "G1",
            "sections": default_sections, "capacity": default_capacity,
            "prerequisites": [],
        })

    for name in g2_courses:
        name = str(name).strip()
        if not name:
            continue
        rows.append({
            "Course": name, "Group": "G2",
            "Sections": default_sections, "Capacity": default_capacity,
            "Prerequisites": "None",
        })
        courses.append({
            "course_name": name, "group": "G2",
            "sections": default_sections, "capacity": default_capacity,
            "prerequisites": [],
        })

    import pandas as _pd
    _pd.DataFrame(rows).to_excel(save_path, index=False)
    logger.info(
        "Auto-generated course config from responses → '%s'  "
        "(%d G1, %d G2 courses).",
        save_path, len(g1_courses), len(g2_courses),
    )
    logger.info(
        "  Edit '%s' to set correct Sections, Capacity and Prerequisites, "
        "then re-run.", save_path,
    )
    return courses


def load_courses_config(config_path: str = "course_config.xlsx") -> list[dict]:
    """
    Load course configuration from an Excel file.

    Expected columns (case-insensitive, flexible naming):
        Course  |  Group  |  Sections  |  Capacity  |  Prerequisite(s)

    Returns a list of dicts with keys:
        course_name, group, sections, capacity, prerequisites (list)
    """
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(config_path)

    try:
        sheets = pd.read_excel(config_path, sheet_name=None, engine="openpyxl")
    except Exception as exc:
        raise RuntimeError(f"Failed to read config file: {exc}") from exc

    def _norm_token(value: object) -> str:
        return re.sub(r"[^a-z0-9]+", "", str(value).strip().lower())

    def _normalise_group(raw_group: object, sheet_name: str) -> str:
        value = _norm_token(raw_group)
        sheet = _norm_token(sheet_name)

        if value in {"g1", "group1", "1", "primary", "p"}:
            return "G1"
        if value in {"g2", "group2", "2", "secondary", "s"}:
            return "G2"

        if "g1" in value or "primary" in value:
            return "G1"
        if "g2" in value or "secondary" in value:
            return "G2"

        # Fallback from sheet names like "G1", "Primary", "Group 2".
        if sheet in {"g1", "group1", "primary"} or "g1" in sheet or "primary" in sheet:
            return "G1"
        if sheet in {"g2", "group2", "secondary"} or "g2" in sheet or "secondary" in sheet:
            return "G2"
        return ""

    def _map_columns(df_sheet: pd.DataFrame) -> pd.DataFrame:
        df_sheet.columns = [str(c).strip() for c in df_sheet.columns]
        col_map: dict[str, str] = {}
        for col in df_sheet.columns:
            cl = str(col).strip().lower()
            token = _norm_token(cl)

            # Map specific columns before generic checks.
            if any(k in cl for k in ("prereq", "prerequisite", "required")):
                col_map[col] = "Prerequisites"
            elif token in {"group", "coursegroup", "type", "category", "bucket"}:
                col_map[col] = "Group"
            elif (
                "section" in cl and "cap" not in cl and "seat" not in cl
            ) or token in {"sections", "section", "numsections", "numberofsections", "noofsections"}:
                col_map[col] = "Sections"
            elif any(k in cl for k in ("capacity", "seat", "strength", "intake", "limit")):
                col_map[col] = "Capacity"
            elif (
                "course name" in cl
                or token in {"course", "coursename", "elective", "electivename", "subject", "subjectname"}
            ):
                col_map[col] = "Course Name"

        return df_sheet.rename(columns=col_map)

    def _extract_scalar(value: object) -> object:
        """Pick first non-empty value when duplicate labels return a Series."""
        if isinstance(value, pd.Series):
            for item in value.tolist():
                if pd.isna(item):
                    continue
                text = str(item).strip()
                if text and text.lower() != "nan":
                    return item
            return ""
        return value

    courses: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for sheet_name, df in sheets.items():
        if df is None or df.empty:
            continue

        df = _map_columns(df)
        for _, row in df.iterrows():
            name = _normalise_course_name(_extract_scalar(row.get("Course Name", "")))
            if not name or name.lower() == "nan":
                continue

            group = _normalise_group(_extract_scalar(row.get("Group", "")), str(sheet_name))
            if group not in ("G1", "G2"):
                logger.warning(
                    "Course '%s' has invalid/missing group '%s' in sheet '%s'; expected G1 or G2 — skipped.",
                    name,
                    _extract_scalar(row.get("Group", "")),
                    sheet_name,
                )
                continue

            raw_prereq = _extract_scalar(row.get("Prerequisites", ""))
            if pd.isna(raw_prereq) or str(raw_prereq).strip().lower() in ("none", "nil", "", "na", "n/a", "-"):
                prereqs: list[str] = []
            else:
                prereqs = [
                    _normalise_course_name(p)
                    for p in re.split(r"[,;]", str(raw_prereq))
                    if _normalise_course_name(p)
                ]

            sections_raw = _extract_scalar(row.get("Sections", 1))
            capacity_raw = _extract_scalar(row.get("Capacity", 30))
            try:
                sections = max(1, int(float(sections_raw)))
            except Exception:
                sections = 1
            try:
                capacity = max(1, int(float(capacity_raw)))
            except Exception:
                capacity = 30

            key = (name.lower(), group)
            if key in seen:
                continue
            seen.add(key)

            course = {
                "course_name": name,
                "group": group,
                "sections": sections,
                "capacity": capacity,
                "prerequisites": prereqs,
            }
            courses.append(course)
            logger.debug("Config loaded: %s", course)

    if not courses:
        raise ValueError(
            f"No valid courses found in config file: {config_path}. "
            "Expected columns similar to: Course Name, Group (G1/G2), Sections, Capacity, Prerequisites."
        )

    logger.info("Loaded %d course(s) from config.", len(courses))
    return courses


# ─────────────────────────────────────────────────────────────────────────────
# Student data processor
# ─────────────────────────────────────────────────────────────────────────────

class DataProcessor:
    """Loads, cleans and validates student Google-Form response data."""

    def __init__(self, responses_path: str, courses_config: list[dict]):
        self.responses_path = responses_path
        self.courses_config: dict[str, dict] = {
            c["course_name"]: c for c in courses_config
        }
        self._course_ci_map: dict[str, str] = {
            str(name).strip().lower(): name for name in self.courses_config
        }
        self._course_token_map: dict[str, str] = {
            self._course_token(name): name for name in self.courses_config
        }
        self._raw_df: pd.DataFrame | None = None
        self.students: list[dict] = []

    # ── Public API ───────────────────────────────────────────────────────────

    def load_data(self) -> pd.DataFrame:
        """Read the Excel responses file and return the raw DataFrame."""
        path = Path(self.responses_path)
        if not path.exists():
            raise FileNotFoundError(
                f"Responses file not found: {self.responses_path}\n"
                "Run  python create_sample_data.py  to generate sample data."
            )
        try:
            df = pd.read_excel(self.responses_path, engine="openpyxl")
        except Exception as exc:
            raise RuntimeError(f"Failed to read responses file: {exc}") from exc

        self._raw_df = df
        logger.info(
            "Loaded %d response row(s) from '%s'.", len(df), self.responses_path
        )
        return df

    def clean_data(self) -> list[dict]:
        """
        Clean raw data:
          - normalise column names
          - parse Timestamp
          - deduplicate by Registration Number (keep latest)
          - normalise CGPA
          - parse completed courses
          - parse course preferences
        """
        if self._raw_df is None:
            self.load_data()

        df = self._normalise_columns(self._raw_df.copy())

        # Guardrail: prevent silent 0-student runs when a summary/pivot sheet
        # is uploaded instead of raw student response data.
        has_reg = COL_REG in df.columns
        has_pref = (COL_G1 in df.columns) or (COL_G2 in df.columns)
        if not has_reg or not has_pref:
            raw_cols = [str(c).strip() for c in self._raw_df.columns]
            raise ValueError(
                "Invalid responses file format. Required columns were not found "
                "(need Registration Number and at least one G1/G2 preference column). "
                f"Detected columns: {raw_cols}. "
                "If this file contains 'Row Labels' or counts, it is a summary report, "
                "not the raw Google Form response export."
            )

        # Parse timestamps
        if COL_TIMESTAMP in df.columns:
            df[COL_TIMESTAMP] = pd.to_datetime(df[COL_TIMESTAMP], errors="coerce")
        else:
            df[COL_TIMESTAMP] = pd.Timestamp.min

        # Deduplicate — keep the latest submission per registration number
        if COL_REG in df.columns:
            before = len(df)
            df = (
                df.sort_values(COL_TIMESTAMP, ascending=True, na_position="first")
                .drop_duplicates(subset=[COL_REG], keep="last")
                .reset_index(drop=True)
            )
            removed = before - len(df)
            for reg in self._find_duplicates(self._raw_df):
                logger.info("Duplicate response removed: %s", reg)
            if removed:
                logger.info("Total duplicate(s) removed: %d", removed)

        students: list[dict] = []
        for _, row in df.iterrows():
            student = self._process_row(row)
            if student is not None:
                students.append(student)

        # Sort: CGPA descending, Timestamp ascending (tie-breaker)
        students.sort(key=lambda s: (-s["cgpa"], s["timestamp"]))

        self.students = students
        logger.info("Processed %d unique student(s).", len(students))
        return students

    def validate_preferences(self, students: list[dict] | None = None) -> list[dict]:
        """
        Remove invalid preferences for each student:
          - courses already completed
          - courses with unmet prerequisites
          - unknown course names
        """
        if students is None:
            students = self.students

        for student in students:
            completed = set(student["completed_courses"])
            for pref_key in ("g1_preferences", "g2_preferences"):
                valid: list[str] = []
                for course_name in student[pref_key]:
                    cfg = self.courses_config.get(course_name)
                    if cfg is None:
                        logger.warning(
                            "Unknown course '%s' for %s — skipped.",
                            course_name, student["reg_no"],
                        )
                        continue
                    if course_name in completed:
                        logger.info(
                            "Removed '%s' from %s preferences: already completed.",
                            course_name, student["reg_no"],
                        )
                        continue
                    prereqs = set(cfg.get("prerequisites", []))
                    if prereqs and not prereqs.issubset(completed):
                        missing = prereqs - completed
                        logger.info(
                            "%s skipped for %s: missing prerequisite(s) %s.",
                            course_name, student["reg_no"], missing,
                        )
                        continue
                    valid.append(course_name)
                student[pref_key] = valid

        return students

    def save_clean_data(self, output_path: str = "clean_students.json") -> None:
        """Serialise the cleaned student list to JSON."""
        if not self.students:
            logger.warning("No student data to save.")
            return
        records: list[dict] = []
        for s in self.students:
            rec = s.copy()
            if isinstance(rec.get("timestamp"), datetime):
                rec["timestamp"] = rec["timestamp"].isoformat()
            records.append(rec)
        with open(output_path, "w", encoding="utf-8") as fh:
            json.dump(records, fh, indent=2, ensure_ascii=False)
        logger.info("Clean student data saved to '%s'.", output_path)

    # ── Private helpers ───────────────────────────────────────────────────────

    def _normalise_columns(self, df: pd.DataFrame) -> pd.DataFrame:
        """Map flexible column names to the canonical set."""
        rename: dict[str, str] = {}
        has_explicit_pref = False
        for col in df.columns:
            cl = col.lower().strip()
            if "timestamp" in cl:
                rename[col] = COL_TIMESTAMP
            elif (
                "name" in cl
                and "course" not in cl
                and "registration" not in cl
                and "username" not in cl
            ):
                rename[col] = COL_NAME
            elif (
                "registration" in cl
                or "regd" in cl
                or ("reg" in cl and "no" in cl)
            ):
                rename[col] = COL_REG
            elif cl == "email" or "email" in cl:
                rename[col] = COL_EMAIL
            elif "phone" in cl or "mobile" in cl:
                rename[col] = COL_PHONE
            elif cl == "section":
                rename[col] = COL_SECTION
            elif "cgpa" in cl:
                rename[col] = COL_CGPA
            elif "completed" in cl or "pursued" in cl or "pursed" in cl:
                rename[col] = COL_COMPLETED
            elif "primary" in cl or ("g1" in cl and "course" in cl):
                rename[col] = COL_G1
                has_explicit_pref = True
            elif "secondary" in cl or ("g2" in cl and "course" in cl):
                rename[col] = COL_G2
                has_explicit_pref = True

        # Fallback for changing Google Form headers:
        # If no explicit G1/G2 columns found, map preference/choice/option
        # elective columns to G1 by default.
        if not has_explicit_pref:
            for col in df.columns:
                if col in rename:
                    continue
                cl = col.lower().strip()
                token = re.sub(r"[^a-z0-9]+", "", cl)
                is_preference_col = (
                    "choice" in cl
                    or "option" in cl
                    or "preference" in cl
                    or "elective" in cl
                    or "dept elective" in cl
                    or ("course" in cl and any(d in cl for d in ("iii-ii", "iii ii", "semester", "sem")))
                )

                # Avoid accidental mapping of generic identity fields.
                is_identity_col = any(
                    word in token
                    for word in (
                        "timestamp",
                        "name",
                        "studentname",
                        "regno",
                        "regdno",
                        "registrationnumber",
                        "section",
                        "email",
                        "phone",
                        "mobile",
                        "cgpa",
                    )
                )

                if is_preference_col and not is_identity_col:
                    rename[col] = COL_G1

        return df.rename(columns=rename)

    def _process_row(self, row) -> dict | None:
        """Convert a single DataFrame row to a student record dict."""
        reg_no = str(self._extract_scalar(row, COL_REG)).strip()
        if not reg_no or reg_no.lower() == "nan":
            return None

        ts_raw = self._extract_scalar(row, COL_TIMESTAMP)
        if pd.isna(ts_raw) if not isinstance(ts_raw, datetime) else False:
            timestamp = datetime.min
        else:
            try:
                timestamp = pd.to_datetime(ts_raw).to_pydatetime()
            except Exception:
                timestamp = datetime.min

        cgpa = self._normalise_cgpa(self._extract_scalar(row, COL_CGPA), reg_no)
        completed = self._extract_course_list(row, COL_COMPLETED)
        g1_prefs = self._extract_course_list(row, COL_G1)
        g2_prefs = self._extract_course_list(row, COL_G2)

        return {
            "timestamp": timestamp,
            "name": str(self._extract_scalar(row, COL_NAME)).strip(),
            "reg_no": reg_no,
            "email": str(self._extract_scalar(row, COL_EMAIL)).strip() or "N/A",
            "phone": str(self._extract_scalar(row, COL_PHONE)).strip(),
            "section": str(self._extract_scalar(row, COL_SECTION)).strip().upper(),
            "cgpa": cgpa,
            "completed_courses": completed,
            "g1_preferences": g1_prefs,
            "g2_preferences": g2_prefs,
            # allocation results (filled later)
            "allocated_primary": None,
            "allocated_secondary": None,
            "allocated_section": None,
            "unallocated_reason": None,
        }

    def _normalise_cgpa(self, raw: object, reg_no: str = "") -> float:
        """
        Normalise CGPA to [0, 10].
        Handles: 8.9 / 8.90 / 89 / 89% / 8.9/10 / 8.9/100
        """
        if pd.isna(raw) if not isinstance(raw, str) else False:
            return 0.0
        text = str(raw).strip()
        # Strip common suffixes/denominators
        text = re.sub(r"\s*/\s*100", "", text)
        text = re.sub(r"\s*/\s*10", "", text)
        text = text.replace("%", "").strip()
        try:
            value = float(text)
        except ValueError:
            logger.warning(
                "Invalid CGPA '%s' for %s — defaulting to 0.0.", raw, reg_no
            )
            return 0.0
        if value > 10.0:
            normalised = round(value / 10.0, 2)
            logger.info("CGPA converted: %s → %s", raw, normalised)
            return normalised
        return round(value, 2)

    def _parse_course_list(self, raw: object) -> list[str]:
        """Parse a comma/semicolon-separated course list; 'None' → []."""
        if pd.isna(raw) if not isinstance(raw, str) else False:
            return []
        text = str(raw).replace("\xa0", " ").strip()
        if not text or text.lower() in ("none", "nil", "na", "n/a", "-"):
            return []
        return [_normalise_course_name(c) for c in re.split(r"[,;]", text) if _normalise_course_name(c)]

    def _extract_scalar(self, row, key: str, default: object = "") -> object:
        """
        Safely fetch one value from a row where duplicate column names may exist.

        If pandas returns a Series (duplicate labels), choose the first non-empty
        value. Otherwise return the scalar directly.
        """
        value = row.get(key, default)
        if isinstance(value, pd.Series):
            for item in value.tolist():
                if pd.isna(item):
                    continue
                text = str(item).strip()
                if text and text.lower() != "nan":
                    return item
            return default
        return value

    def _extract_course_list(self, row, key: str) -> list[str]:
        """
        Safely parse course lists from one or multiple mapped columns.

        If duplicate columns map to the same key (e.g. multiple G1 rank columns),
        merge values in order and de-duplicate while preserving preference order.
        """
        value = row.get(key, "")
        if isinstance(value, pd.Series):
            merged: list[str] = []
            for item in value.tolist():
                merged.extend(self._parse_course_list(item))
        else:
            merged = self._parse_course_list(value)

        # Order-preserving de-duplication
        seen = set()
        result: list[str] = []
        for course in merged:
            canonical = self._resolve_course_name(course)
            if canonical not in seen:
                seen.add(canonical)
                result.append(canonical)
        return result

    @staticmethod
    def _course_token(name: str) -> str:
        return re.sub(r"[^a-z0-9]+", "", str(name).strip().lower())

    def _resolve_course_name(self, raw_name: str) -> str:
        """Resolve shorthand/variant course names to config course names."""
        name = _normalise_course_name(raw_name)
        if not name:
            return name

        if name in self.courses_config:
            return name

        lower = name.lower()
        if lower in self._course_ci_map:
            return self._course_ci_map[lower]

        token = self._course_token(name)
        if token in self._course_token_map:
            return self._course_token_map[token]

        # Allow safe shorthand matches like "AR/VR" -> "AR/VR Systems"
        candidates = [
            cname
            for ctok, cname in self._course_token_map.items()
            if ctok.startswith(token) or token.startswith(ctok)
        ]
        if len(candidates) == 1:
            return candidates[0]

        return name

    @staticmethod
    def _find_duplicates(df: pd.DataFrame) -> list[str]:
        """Return registration numbers that appear more than once."""
        # Try to find the registration column by name pattern
        for col in df.columns:
            if "registration" in col.lower() or ("reg" in col.lower() and "no" in col.lower()):
                dups = df[col][df[col].duplicated(keep="first")]
                return list(dups.dropna().astype(str))
        return []
