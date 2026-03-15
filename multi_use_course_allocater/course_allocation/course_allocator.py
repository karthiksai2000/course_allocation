"""
course_allocator.py
-------------------
Core allocation engine.

Allocation order (students already sorted by CGPA desc / Timestamp asc):

  For each student:
    1. Allocate G1 primary course   → allocate_primary_course()
    2. Allocate G2 secondary course → allocate_secondary_course()
       a. Try the same section as primary.
       b. If primary-section full, attempt a section swap.
       c. Fall back to the section with the majority of students.
       d. If every section of every G2 preference is full → unallocated secondary.
    3. If no G1 course can be allocated → unallocated.

After all students are processed, call balance_sections() on the
SectionManager and then generate_reports() on the ReportGenerator.
"""

import logging
from collections import Counter, defaultdict

logger = logging.getLogger(__name__)


class CourseAllocator:
    """Allocates G1 and G2 elective courses to each student."""

    def __init__(
        self,
        courses_config: list[dict],
        section_manager,
        allocation_mode: str = "auto",
        fill_all_secondary: bool = True,
    ):
        """
        Args:
            courses_config: list of course-config dicts
                (course_name, group, sections, capacity, prerequisites).
            section_manager: an initialised ``SectionManager`` instance.
            allocation_mode: one of "single", "dual", or "auto".
                single -> allocate only G1.
                dual   -> require/attempt both G1 and G2.
                auto   -> allocate G2 only when G2 preferences exist.
        """
        self.courses_config: dict[str, dict] = {
            c["course_name"]: c for c in courses_config
        }
        self.sm = section_manager
        # Populated during allocate_all() for use in swap look-ups
        self._students_by_reg: dict[str, dict] = {}
        # Per-course strategy computed at run time:
        #   single   -> fill one section first
        #   balanced -> spread across sections evenly
        self._course_mode: dict[str, str] = {}
        # Tracks where each (G1, G2) combination is concentrated by section.
        self._combo_section_counts: dict[tuple[str, str], Counter] = defaultdict(Counter)
        self.allocation_mode = (allocation_mode or "auto").strip().lower()
        self.fill_all_secondary = bool(fill_all_secondary)
        if self.allocation_mode not in {"single", "dual", "auto"}:
            raise ValueError(
                f"Invalid allocation_mode '{allocation_mode}'. Expected single|dual|auto."
            )

    # ── Public API ───────────────────────────────────────────────────────────

    def allocate_all(
        self, students: list[dict]
    ) -> tuple[list[dict], list[dict]]:
        """
        Run the full allocation for *all* students.

        Students must already be sorted by CGPA desc / Timestamp asc.

        Returns:
            (allocated, unallocated)
            A student with a primary but no secondary is still in *allocated*
            (visible in the section sheet) but has ``allocated_secondary=None``.
        """
        self._students_by_reg = {s["reg_no"]: s for s in students}
        self._course_mode = self._compute_course_modes(students)
        self._combo_section_counts = defaultdict(Counter)

        allocated: list[dict] = []
        unallocated: list[dict] = []

        for student in students:
            primary, section = self.allocate_primary_course(student)
            if primary is None:
                student["unallocated_reason"] = "No valid G1 course available"
                unallocated.append(student)
                logger.warning(
                    "%s unallocated — no valid G1 course.", student["reg_no"]
                )
                continue

            student["allocated_primary"] = primary
            student["allocated_section"] = section

            should_allocate_secondary = self.allocation_mode in {"dual", "auto"}

            if not should_allocate_secondary:
                allocated.append(student)
                continue

            secondary, sec_section = self.allocate_secondary_course(student)
            if secondary:
                student["allocated_secondary"] = secondary
                # Update canonical section only if secondary changed it
                student["allocated_section"] = sec_section
            else:
                logger.warning(
                    "%s has G1=%s/%s but no valid G2 course.",
                    student["reg_no"], primary, section,
                )

            allocated.append(student)

        # Demand-driven policy: preserve the live sequential seat filling
        # decisions; do not repartition into synthetic combo clusters.

        logger.info(
            "Allocation complete — allocated: %d, unallocated: %d",
            len(allocated), len(unallocated),
        )
        return allocated, unallocated

    def _rebuild_sections_by_combo(self, allocated: list[dict]) -> None:
        """
        Recompute section assignment from final (G1, G2) clusters.

        Rules implemented:
          1. Build natural groups by exact (G1, G2) combination first.
          2. Try to keep each combo in its own section if capacity allows.
          3. If a group must merge, prefer same G1, then same G2, then
             smallest-loaded section with available capacity.
          4. Never exceed section capacity on either paired course.
          5. For students without G2, assign section-majority G2 when possible.
        """
        if not allocated:
            return

        # Ensure each student has at least a candidate G2 before grouping.
        self._seed_missing_g2_for_grouping(allocated)

        capacities = self._build_course_section_capacities()
        section_state: dict[str, dict] = defaultdict(
            lambda: {"size": 0, "combo_counts": Counter()}
        )
        course_counts: Counter = Counter()
        planned_section: dict[str, str] = {}

        combo_groups: dict[tuple[str, str | None], list[dict]] = defaultdict(list)
        for student in allocated:
            g1 = student.get("allocated_primary")
            if not g1:
                continue
            combo_groups[(g1, student.get("allocated_secondary"))].append(student)

        # Large groups first improves packing and reduces fragmented leftovers.
        ordered_combos = sorted(
            combo_groups.items(),
            key=lambda kv: (-len(kv[1]), str(kv[0][0]), str(kv[0][1] or "")),
        )

        for combo, students_in_combo in ordered_combos:
            g1, g2 = combo
            remaining = list(students_in_combo)

            while remaining:
                valid_sections = self._valid_sections_for_combo(g1, g2)
                sec = self._choose_section_for_combo(
                    combo,
                    valid_sections,
                    section_state,
                    course_counts,
                    capacities,
                    remaining_count=len(remaining),
                )
                if sec is None:
                    break

                fit = self._combo_fit_count(g1, g2, sec, course_counts, capacities)
                if fit <= 0:
                    break

                take = min(len(remaining), fit)
                chunk, remaining = remaining[:take], remaining[take:]
                for s in chunk:
                    planned_section[s["reg_no"]] = sec

                course_counts[(g1, sec)] += take
                if g2:
                    course_counts[(g2, sec)] += take
                section_state[sec]["size"] += take
                section_state[sec]["combo_counts"][combo] += take

        # Place any leftovers by best-effort capacity-aware fallback.
        for student in allocated:
            reg_no = student.get("reg_no")
            if not reg_no or reg_no in planned_section:
                continue

            g1 = student.get("allocated_primary")
            g2 = student.get("allocated_secondary")
            if not g1:
                continue

            valid_sections = self._valid_sections_for_combo(g1, g2)
            sec = self._choose_section_for_combo(
                (g1, g2),
                valid_sections,
                section_state,
                course_counts,
                capacities,
                remaining_count=1,
            )
            if sec is None:
                sec = self._find_any_section_with_capacity(g1, g2, course_counts, capacities)
            if sec is None:
                continue

            planned_section[reg_no] = sec
            course_counts[(g1, sec)] += 1
            if g2:
                course_counts[(g2, sec)] += 1
            section_state[sec]["size"] += 1
            section_state[sec]["combo_counts"][(g1, g2)] += 1

        # Rule: missing G2 should follow section-majority G2 where possible.
        self._fill_missing_g2_by_section_majority(
            allocated,
            planned_section,
            section_state,
            course_counts,
            capacities,
        )

        # Rebuild section manager seats from planned sections.
        for sections in self.sm.section_seats.values():
            for data in sections.values():
                data["enrolled"] = []

        self._combo_section_counts = defaultdict(Counter)

        for student in allocated:
            reg_no = student.get("reg_no")
            g1 = student.get("allocated_primary")
            g2 = student.get("allocated_secondary")
            if not reg_no or not g1:
                continue

            sec = planned_section.get(reg_no)
            if not sec:
                sec = self._find_any_section_with_capacity(g1, g2, Counter(), capacities)
                if not sec:
                    continue

            # Always assign primary seat.
            if not self.sm.section_exists(g1, sec) or not self.sm.assign(g1, sec, reg_no):
                continue

            # Assign secondary in same section only when valid and capacity exists.
            if g2 and self.sm.section_exists(g2, sec) and self.sm.has_seat(g2, sec):
                self.sm.assign(g2, sec, reg_no)
                self._record_combo(student, g2, sec)
            else:
                student["allocated_secondary"] = None

            student["allocated_section"] = sec

    def _build_course_section_capacities(self) -> dict[tuple[str, str], int]:
        capacities: dict[tuple[str, str], int] = {}
        for course, sections in self.sm.section_seats.items():
            for sec, data in sections.items():
                capacities[(course, sec)] = int(data.get("capacity", 0))
        return capacities

    def _valid_sections_for_combo(self, g1: str, g2: str | None) -> list[str]:
        g1_sections = set(self.sm.all_sections(g1))
        if not g1_sections:
            return []
        if not g2:
            return sorted(g1_sections)
        g2_sections = set(self.sm.all_sections(g2))
        return sorted(g1_sections & g2_sections)

    def _combo_fit_count(
        self,
        g1: str,
        g2: str | None,
        section: str,
        course_counts: Counter,
        capacities: dict[tuple[str, str], int],
    ) -> int:
        g1_left = capacities.get((g1, section), 0) - course_counts[(g1, section)]
        if g2:
            g2_left = capacities.get((g2, section), 0) - course_counts[(g2, section)]
            return max(0, min(g1_left, g2_left))
        return max(0, g1_left)

    def _choose_section_for_combo(
        self,
        combo: tuple[str, str | None],
        valid_sections: list[str],
        section_state: dict[str, dict],
        course_counts: Counter,
        capacities: dict[tuple[str, str], int],
        remaining_count: int,
    ) -> str | None:
        g1, g2 = combo
        candidates = [
            sec
            for sec in valid_sections
            if self._combo_fit_count(g1, g2, sec, course_counts, capacities) > 0
        ]
        if not candidates:
            return None

        # Try giving this combo its own empty section if it fits entirely.
        empty_fit = [
            sec for sec in candidates
            if section_state[sec]["size"] == 0
            and self._combo_fit_count(g1, g2, sec, course_counts, capacities) >= remaining_count
        ]
        if empty_fit:
            return sorted(
                empty_fit,
                key=lambda sec: (
                    -self._combo_fit_count(g1, g2, sec, course_counts, capacities),
                    sec,
                ),
            )[0]

        same_g1 = []
        same_g2 = []
        for sec in candidates:
            existing = section_state[sec]["combo_counts"]
            has_same_g1 = any(k[0] == g1 and v > 0 for k, v in existing.items())
            has_same_g2 = bool(g2) and any(k[1] == g2 and v > 0 for k, v in existing.items())
            if has_same_g1:
                same_g1.append(sec)
            elif has_same_g2:
                same_g2.append(sec)

        def _rank(sec: str) -> tuple:
            return (
                section_state[sec]["size"],
                -self._combo_fit_count(g1, g2, sec, course_counts, capacities),
                sec,
            )

        if same_g1:
            return sorted(same_g1, key=_rank)[0]
        if same_g2:
            return sorted(same_g2, key=_rank)[0]
        return sorted(candidates, key=_rank)[0]

    def _find_any_section_with_capacity(
        self,
        g1: str,
        g2: str | None,
        course_counts: Counter,
        capacities: dict[tuple[str, str], int],
    ) -> str | None:
        best = None
        best_left = -1
        for sec in self._valid_sections_for_combo(g1, g2):
            left = self._combo_fit_count(g1, g2, sec, course_counts, capacities)
            if left > best_left:
                best_left = left
                best = sec
        return best if best_left > 0 else None

    def _seed_missing_g2_for_grouping(self, allocated: list[dict]) -> None:
        """Pre-fill missing G2 with a plausible course for clustering."""
        g1_g2_popularity: dict[str, Counter] = defaultdict(Counter)
        for s in allocated:
            g1 = s.get("allocated_primary")
            g2 = s.get("allocated_secondary")
            if g1 and g2:
                g1_g2_popularity[g1][g2] += 1

        global_g2 = Counter(
            s.get("allocated_secondary")
            for s in allocated
            if s.get("allocated_secondary")
        )

        for student in allocated:
            if student.get("allocated_secondary"):
                continue
            g1 = student.get("allocated_primary")
            if not g1:
                continue

            completed = set(student.get("completed_courses", []))
            chosen = None

            for g2, _ in g1_g2_popularity.get(g1, Counter()).most_common():
                cfg = self.courses_config.get(g2)
                if not cfg or cfg.get("group") != "G2":
                    continue
                if g2 in completed or g2 == g1:
                    continue
                prereqs = set(cfg.get("prerequisites", []))
                if prereqs and not prereqs.issubset(completed):
                    continue
                chosen = g2
                break

            if not chosen:
                for g2, _ in global_g2.most_common():
                    cfg = self.courses_config.get(g2)
                    if not cfg or cfg.get("group") != "G2":
                        continue
                    if g2 in completed or g2 == g1:
                        continue
                    prereqs = set(cfg.get("prerequisites", []))
                    if prereqs and not prereqs.issubset(completed):
                        continue
                    chosen = g2
                    break

            if chosen:
                student["allocated_secondary"] = chosen

    def _fill_missing_g2_by_section_majority(
        self,
        allocated: list[dict],
        planned_section: dict[str, str],
        section_state: dict[str, dict],
        course_counts: Counter,
        capacities: dict[tuple[str, str], int],
    ) -> None:
        """Assign missing G2 from section-majority preference (Rule 8)."""
        section_g2_majority: dict[str, Counter] = defaultdict(Counter)
        for student in allocated:
            reg_no = student.get("reg_no")
            g2 = student.get("allocated_secondary")
            sec = planned_section.get(reg_no)
            if g2 and sec:
                section_g2_majority[sec][g2] += 1

        global_g2 = Counter(
            s.get("allocated_secondary")
            for s in allocated
            if s.get("allocated_secondary")
        )

        for student in allocated:
            if student.get("allocated_secondary"):
                continue

            reg_no = student.get("reg_no")
            g1 = student.get("allocated_primary")
            sec = planned_section.get(reg_no)
            if not g1 or not sec:
                continue

            completed = set(student.get("completed_courses", []))
            selected = None

            for g2, _ in section_g2_majority.get(sec, Counter()).most_common():
                cfg = self.courses_config.get(g2)
                if not cfg or cfg.get("group") != "G2":
                    continue
                if g2 in completed or g2 == g1:
                    continue
                if sec not in self.sm.all_sections(g2):
                    continue
                if course_counts[(g2, sec)] >= capacities.get((g2, sec), 0):
                    continue
                prereqs = set(cfg.get("prerequisites", []))
                if prereqs and not prereqs.issubset(completed):
                    continue
                selected = g2
                break

            if not selected:
                for g2, _ in global_g2.most_common():
                    cfg = self.courses_config.get(g2)
                    if not cfg or cfg.get("group") != "G2":
                        continue
                    if g2 in completed or g2 == g1:
                        continue
                    if sec not in self.sm.all_sections(g2):
                        continue
                    if course_counts[(g2, sec)] >= capacities.get((g2, sec), 0):
                        continue
                    prereqs = set(cfg.get("prerequisites", []))
                    if prereqs and not prereqs.issubset(completed):
                        continue
                    selected = g2
                    break

            if not selected:
                continue

            student["allocated_secondary"] = selected
            course_counts[(selected, sec)] += 1
            section_state[sec]["combo_counts"][(g1, selected)] += 1


    # ── Primary course (G1) ──────────────────────────────────────────────────

    def allocate_primary_course(
        self, student: dict
    ) -> tuple[str | None, str | None]:
        """
        Try each G1 preference in order.

        Returns (course_name, section) or (None, None).
        """
        completed = set(student["completed_courses"])

        for course_name in student["g1_preferences"]:
            cfg = self.courses_config.get(course_name)
            if cfg is None or cfg["group"] != "G1":
                continue
            if course_name in completed:
                continue

            prereqs = set(cfg.get("prerequisites", []))
            if prereqs and not prereqs.issubset(completed):
                missing = prereqs - completed
                logger.info(
                    "%s skipped for %s: missing prerequisite(s) %s.",
                    course_name, student["reg_no"], missing,
                )
                continue

            available = self.sm.available_sections(course_name)
            if not available:
                logger.info(
                    "%s skipped for %s: all sections full.",
                    course_name, student["reg_no"],
                )
                continue

            # In single mode, keep deterministic sequential fill (A -> B -> C).
            if self.allocation_mode == "single":
                section = self._select_section_for_course(course_name)
            else:
                section = self._select_section_for_primary(course_name, student)
            if section is None:
                continue
            self.sm.assign(course_name, section, student["reg_no"])
            logger.info(
                "%s allocated in Section %s for %s.",
                course_name, section, student["reg_no"],
            )
            return course_name, section

        # Fallback: allocate any eligible G1 course with available seats.
        fb_course, fb_section = self._allocate_group_fallback(student, group="G1")
        if fb_course:
            logger.info(
                "%s fallback-allocated in Section %s for %s (no valid G1 preference could be placed).",
                fb_course, fb_section, student["reg_no"],
            )
            return fb_course, fb_section

        return None, None

    # ── Secondary course (G2) ────────────────────────────────────────────────

    def allocate_secondary_course(
        self, student: dict
    ) -> tuple[str | None, str | None]:
        """
        Try each G2 preference in order.

        Priority for section assignment:
          1. Same section as G1 (primary_section).
          2. Section swap to free a spot in primary_section.
          3. Section with the majority of students for this course.
          4. Any remaining available section.

        Returns (course_name, section) or (None, None).
        """
        primary_section = student["allocated_section"]
        completed = set(student["completed_courses"])
        primary_course = student.get("allocated_primary")

        for course_name in student["g2_preferences"]:
            cfg = self.courses_config.get(course_name)
            if cfg is None or cfg["group"] != "G2":
                continue
            # Enterprise guard: no student can be allocated the same course twice.
            if primary_course and course_name == primary_course:
                continue
            if course_name in completed:
                continue

            prereqs = set(cfg.get("prerequisites", []))
            if prereqs and not prereqs.issubset(completed):
                missing = prereqs - completed
                logger.info(
                    "%s skipped for %s: missing prerequisite(s) %s.",
                    course_name, student["reg_no"], missing,
                )
                continue

            # ── Try primary section directly ──────────────────────────────
            if primary_section and self.sm.has_seat(course_name, primary_section):
                self.sm.assign(course_name, primary_section, student["reg_no"])
                self._record_combo(student, course_name, primary_section)
                logger.info(
                    "%s allocated in Section %s for %s (matched primary).",
                    course_name, primary_section, student["reg_no"],
                )
                return course_name, primary_section

            # ── Try section swap ──────────────────────────────────────────
            if primary_section:
                swapped = self._try_section_swap(
                    student, course_name, primary_section
                )
                if swapped:
                    self.sm.assign(course_name, primary_section, student["reg_no"])
                    self._record_combo(student, course_name, primary_section)
                    logger.info(
                        "%s allocated in Section %s for %s (after swap).",
                        course_name, primary_section, student["reg_no"],
                    )
                    return course_name, primary_section

            # ── Fallback: demand-aware section selection ───────────────────
            target = self._select_section_for_course(course_name)
            if (
                target is None
                and self.fill_all_secondary
                and self.allocation_mode in {"auto", "dual"}
            ):
                target = self.sm.ensure_available_section(course_name, allow_overflow=True)
            if target is None:
                logger.info(
                    "%s skipped for %s: all sections full.",
                    course_name, student["reg_no"],
                )
                continue

            self.sm.assign(course_name, target, student["reg_no"])
            # Update the student's canonical section to reflect actual placement
            student["allocated_section"] = target
            self._record_combo(student, course_name, target)
            logger.info(
                "%s allocated in Section %s for %s (demand-aware fallback).",
                course_name, target, student["reg_no"],
            )
            return course_name, target

        # If no G2 is allocated/selected, assign section-majority G2 if possible.
        auto_course, auto_section = self._auto_assign_majority_g2(student)
        if auto_course:
            return auto_course, auto_section

        # Final fallback: allocate any eligible G2 course with seats.
        fb_course, fb_section = self._allocate_group_fallback(
            student,
            group="G2",
            preferred_section=primary_section,
            exclude_courses={primary_course} if primary_course else None,
        )
        if fb_course:
            self._record_combo(student, fb_course, fb_section)
            student["allocated_section"] = fb_section
            logger.info(
                "%s fallback-allocated in Section %s for %s (no valid G2 preference could be placed).",
                fb_course, fb_section, student["reg_no"],
            )
            return fb_course, fb_section

        # Final safety net: never leave G2 blank in dual/auto when G2 courses exist.
        if self.fill_all_secondary and self.allocation_mode in {"auto", "dual"}:
            force_course, force_section = self._force_assign_any_g2(
                student,
                exclude_courses={primary_course} if primary_course else None,
            )
            if force_course:
                self._record_combo(student, force_course, force_section)
                student["allocated_section"] = force_section
                logger.info(
                    "%s force-assigned in Section %s for %s (guaranteed G2 fill).",
                    force_course, force_section, student["reg_no"],
                )
                return force_course, force_section

        return None, None

    # ── Section swap ─────────────────────────────────────────────────────────

    def _try_section_swap(
        self,
        student: dict,
        course_name: str,
        needed_section: str,
    ) -> bool:
        """
        Attempt to vacate a spot in ``course_name``-``needed_section`` by
        moving an existing occupant to an alternate section.

        The candidate's *primary* course must also have a free seat in the
        alternate section (to preserve the G1/G2 pairing constraint).

        Returns True if a swap was performed (spot is now free in needed_section).
        """
        for alt_section in self.sm.all_sections(course_name):
            if alt_section == needed_section:
                continue
            if not self.sm.has_seat(course_name, alt_section):
                continue

            # Look for a movable candidate in needed_section
            for candidate_reg in self.sm.get_enrolled(course_name, needed_section):
                candidate = self._students_by_reg.get(candidate_reg)
                if candidate is None:
                    continue

                primary_course = candidate.get("allocated_primary")
                if not primary_course:
                    continue

                # Primary must also accept alt_section
                if not self.sm.has_seat(primary_course, alt_section):
                    continue

                # ── Perform the swap ──────────────────────────────────────
                # Move candidate's G2 (course_name) to alt_section
                self.sm.remove(course_name, needed_section, candidate_reg)
                self.sm.assign(course_name, alt_section, candidate_reg)

                # Move candidate's G1 (primary_course) to alt_section
                self.sm.remove(primary_course, needed_section, candidate_reg)
                self.sm.assign(primary_course, alt_section, candidate_reg)

                candidate["allocated_section"] = alt_section

                logger.info(
                    "Section swap: moved %s from %s-%s to %s-%s "
                    "(making room for %s).",
                    candidate_reg,
                    course_name, needed_section,
                    course_name, alt_section,
                    student["reg_no"],
                )
                return True  # needed_section now has a free slot

        return False

    # ── Course distribution strategy ────────────────────────────────────────

    def _compute_course_modes(self, students: list[dict]) -> dict[str, str]:
        """
        Decide per-course section strategy from expected demand.

                Rule:
                    - if configured sections <= 1          -> 'single'
                    - if configured sections >  1          -> 'balanced'

                Rationale:
                    Admin has explicitly configured multiple sections, so we should
                    actively use those sections instead of collapsing to Section A.
        """
        demand: dict[str, int] = {name: 0 for name in self.courses_config}

        for s in students:
            # Estimate demand from top choice per group to avoid rank overcounting.
            if s.get("g1_preferences"):
                c = s["g1_preferences"][0]
                if c in demand and self.courses_config[c]["group"] == "G1":
                    demand[c] += 1
            if s.get("g2_preferences"):
                c = s["g2_preferences"][0]
                if c in demand and self.courses_config[c]["group"] == "G2":
                    demand[c] += 1

        modes: dict[str, str] = {}
        for course_name, cfg in self.courses_config.items():
            if self.allocation_mode == "single":
                mode = "single"
            else:
                mode = "single" if cfg.get("sections", 1) <= 1 else "balanced"
            modes[course_name] = mode
            logger.info(
                "Distribution mode for %s: %s (expected demand=%d, sections=%d, capacity/section=%d)",
                course_name,
                mode,
                demand.get(course_name, 0),
                cfg.get("sections", 1),
                cfg["capacity"],
            )
        return modes

    def _select_section_for_course(self, course_name: str) -> str | None:
        """
        Pick a section according to computed strategy.

        single:
          Fill the first section until full, then next section.
        balanced:
          Place into the least-filled available section.
        """
        available = self.sm.available_sections(course_name)
        if not available:
            return None

        mode = self._course_mode.get(course_name, "single")
        if mode == "single":
            return available[0]

        # balanced mode: choose section with minimum occupancy; tie -> alphabetic
        return min(available, key=lambda sec: (self.sm.count(course_name, sec), sec))

    def _select_section_for_primary(self, g1_course: str, student: dict) -> str | None:
        """
        Choose G1 section with combo-aware priority.

        Priority:
          1. Keep dominant (G1, G2) combinations in the same section.
          2. Otherwise fall back to generic course strategy.
        """
        available = self.sm.available_sections(g1_course)
        if not available:
            return None

        best_section = None
        best_score = -1

        for sec in available:
            score = 0
            for g2_course in student.get("g2_preferences", []):
                cfg = self.courses_config.get(g2_course)
                if not cfg or cfg.get("group") != "G2":
                    continue
                if not self.sm.section_exists(g2_course, sec):
                    continue
                if not self.sm.has_seat(g2_course, sec):
                    continue
                score = max(score, self._combo_section_counts[(g1_course, g2_course)][sec])

            if score > best_score:
                best_score = score
                best_section = sec
            elif score == best_score and best_section is not None:
                if self.sm.count(g1_course, sec) < self.sm.count(g1_course, best_section):
                    best_section = sec

        if best_section is not None and best_score > 0:
            # Guardrail: preserve combo cohesion, but do not over-concentrate
            # a course into one section when another section is available.
            least_loaded = min(available, key=lambda sec: (self.sm.count(g1_course, sec), sec))
            if self.sm.count(g1_course, best_section) - self.sm.count(g1_course, least_loaded) >= 2:
                return least_loaded
            return best_section

        return self._select_section_for_course(g1_course)

    def _record_combo(self, student: dict, g2_course: str, section: str) -> None:
        """Record final (G1, G2) placement to improve combo clustering."""
        g1_course = student.get("allocated_primary")
        if not g1_course or not g2_course or not section:
            return
        self._combo_section_counts[(g1_course, g2_course)][section] += 1

    def _auto_assign_majority_g2(self, student: dict) -> tuple[str | None, str | None]:
        """
        If a student has no G2 allocated, assign the section-majority G2.

        Capacity and prerequisite constraints are always respected.
        """
        section = student.get("allocated_section")
        if not section:
            return None, None

        completed = set(student.get("completed_courses", []))
        for g2_course, _count in self._g2_majority_for_section(section):
            cfg = self.courses_config.get(g2_course)
            if not cfg or cfg.get("group") != "G2":
                continue
            if g2_course in completed:
                continue
            prereqs = set(cfg.get("prerequisites", []))
            if prereqs and not prereqs.issubset(completed):
                continue
            if not self.sm.section_exists(g2_course, section):
                continue
            if not self.sm.has_seat(g2_course, section):
                continue

            self.sm.assign(g2_course, section, student["reg_no"])
            self._record_combo(student, g2_course, section)
            logger.info(
                "%s auto-assigned to %s in Section %s (majority G2 for section).",
                student["reg_no"], g2_course, section,
            )
            return g2_course, section

        return None, None

    def _g2_majority_for_section(self, section: str) -> list[tuple[str, int]]:
        """Return G2 course frequency ranking among students in this section."""
        counts = Counter(
            s.get("allocated_secondary")
            for s in self._students_by_reg.values()
            if s.get("allocated_section") == section and s.get("allocated_secondary")
        )
        return counts.most_common()

    def _allocate_group_fallback(
        self,
        student: dict,
        group: str,
        preferred_section: str | None = None,
        exclude_courses: set[str] | None = None,
    ) -> tuple[str | None, str | None]:
        """
        Allocate first eligible course from a group when all preferences fail.

        Selection order:
          1. Courses with the lowest total enrolment first.
          2. Preferred section first (if provided and available).
          3. Otherwise use demand-aware course section strategy.
        """
        completed = set(student.get("completed_courses", []))
        exclude_courses = exclude_courses or set()

        candidates: list[str] = [
            name
            for name, cfg in self.courses_config.items()
            if cfg.get("group") == group and name not in exclude_courses
        ]

        candidates.sort(
            key=lambda name: (
                sum(self.sm.count(name, sec) for sec in self.sm.all_sections(name)),
                name,
            )
        )

        for course_name in candidates:
            if course_name in completed:
                continue
            cfg = self.courses_config.get(course_name, {})
            prereqs = set(cfg.get("prerequisites", []))
            if prereqs and not prereqs.issubset(completed):
                continue

            if preferred_section and self.sm.has_seat(course_name, preferred_section):
                self.sm.assign(course_name, preferred_section, student["reg_no"])
                return course_name, preferred_section

            target = self._select_section_for_course(course_name)
            if (
                target is None
                and group == "G2"
                and self.fill_all_secondary
                and self.allocation_mode in {"auto", "dual"}
            ):
                target = self.sm.ensure_available_section(course_name, allow_overflow=True)
            if target is None:
                continue

            self.sm.assign(course_name, target, student["reg_no"])
            return course_name, target

        return None, None

    def _force_assign_any_g2(
        self,
        student: dict,
        exclude_courses: set[str] | None = None,
    ) -> tuple[str | None, str | None]:
        """
        Last-resort G2 assignment to avoid blank secondary entries.

        Ignores prerequisite/completed-course checks and creates overflow
        sections when configured G2 capacity is exhausted.
        """
        exclude_courses = exclude_courses or set()
        preferred_section = student.get("allocated_section")

        g2_courses = sorted(
            [
                name
                for name, cfg in self.courses_config.items()
                if cfg.get("group") == "G2" and name not in exclude_courses
            ],
            key=lambda name: (
                sum(self.sm.count(name, sec) for sec in self.sm.all_sections(name)),
                name,
            ),
        )

        if not g2_courses:
            return None, None

        for course_name in g2_courses:
            if preferred_section and self.sm.has_seat(course_name, preferred_section):
                self.sm.assign(course_name, preferred_section, student["reg_no"])
                return course_name, preferred_section

            target = self.sm.ensure_available_section(course_name, allow_overflow=True)
            if target is None:
                continue

            self.sm.assign(course_name, target, student["reg_no"])
            return course_name, target

        return None, None
