"""
section_manager.py
------------------
Tracks seat availability and student enrolment per course-section,
and provides section-balancing logic after allocation is complete.
"""

import logging
import string

logger = logging.getLogger(__name__)

_SECTION_LABELS = list(string.ascii_uppercase)  # A, B, C, …


class SectionManager:
    """
    Manages seat quotas and enrolment lists for every (course, section) pair.

    Internal structure::

        section_seats = {
            "AI": {
                "A": {"capacity": 35, "enrolled": ["21BCS001", ...]},
                "B": {"capacity": 35, "enrolled": [...]},
            },
            "DS": { ... },
        }
    """

    def __init__(self, courses_config: list[dict]):
        """
        Args:
            courses_config: output of ``load_courses_config()`` — a list of
                dicts with keys: course_name, group, sections, capacity,
                prerequisites.
        """
        self.courses_config: dict[str, dict] = {
            c["course_name"]: c for c in courses_config
        }
        self._max_sections: dict[str, int] = {
            c["course_name"]: max(1, int(c.get("sections", 1)))
            for c in courses_config
        }
        self.section_seats: dict[str, dict[str, dict]] = {}
        self._init_sections()

    # ── Initialisation ───────────────────────────────────────────────────────

    def _init_sections(self) -> None:
        for name, cfg in self.courses_config.items():
            self.section_seats[name] = {}
            # Demand-driven model: start with a single section and grow only
            # when existing sections are full.
            self.section_seats[name]["A"] = {
                "capacity": cfg["capacity"],
                "enrolled": [],
            }

    def _can_grow(self, course: str) -> bool:
        if not self.course_exists(course):
            return False
        return len(self.section_seats[course]) < self._max_sections.get(course, 1)

    def _grow_next_section(self, course: str, allow_beyond_config: bool = False) -> str | None:
        """Create exactly one new section for a course when allowed."""
        if not self.course_exists(course):
            return None
        if not allow_beyond_config and not self._can_grow(course):
            return None

        next_index = len(self.section_seats[course])
        if next_index >= len(_SECTION_LABELS):
            return None

        label = _SECTION_LABELS[next_index]
        self.section_seats[course][label] = {
            "capacity": self.courses_config[course]["capacity"],
            "enrolled": [],
        }
        logger.info(
            "Opened new section %s for %s (demand-driven expansion).",
            label,
            course,
        )
        return label

    def ensure_available_section(self, course: str, allow_overflow: bool = False) -> str | None:
        """
        Return an available section for a course.

        If all configured sections are full and ``allow_overflow`` is True,
        create one additional section beyond configured limits.
        """
        available = self.available_sections(course)
        if available:
            return available[0]

        if allow_overflow:
            return self._grow_next_section(course, allow_beyond_config=True)

        return None

    # ── Query helpers ────────────────────────────────────────────────────────

    def course_exists(self, course: str) -> bool:
        return course in self.section_seats

    def section_exists(self, course: str, section: str) -> bool:
        return (
            course in self.section_seats
            and section in self.section_seats[course]
        )

    def has_seat(self, course: str, section: str) -> bool:
        """True if the section has at least one free seat."""
        if not self.section_exists(course, section):
            return False
        d = self.section_seats[course][section]
        return len(d["enrolled"]) < d["capacity"]

    def count(self, course: str, section: str) -> int:
        """Number of students currently enrolled in (course, section)."""
        if not self.section_exists(course, section):
            return 0
        return len(self.section_seats[course][section]["enrolled"])

    def available_sections(self, course: str) -> list[str]:
        """Sorted list of sections that still have free seats."""
        if not self.course_exists(course):
            return []
        available = sorted(
            s
            for s, d in self.section_seats[course].items()
            if len(d["enrolled"]) < d["capacity"]
        )

        # Strict sequential growth: open the next section only when all
        # currently opened sections are full.
        if not available:
            new_label = self._grow_next_section(course)
            if new_label:
                return [new_label]

        return available

    def all_sections(self, course: str) -> list[str]:
        if not self.course_exists(course):
            return []
        return sorted(self.section_seats[course])

    def get_enrolled(self, course: str, section: str) -> list[str]:
        """Return a copy of the enrolled list for (course, section)."""
        if not self.section_exists(course, section):
            return []
        return list(self.section_seats[course][section]["enrolled"])

    def majority_section(self, course: str) -> str | None:
        """Section with the highest current enrolment (for fallback assignment)."""
        if not self.course_exists(course):
            return None
        sections = self.section_seats[course]
        return max(sections, key=lambda s: len(sections[s]["enrolled"]), default=None)

    # ── Mutation helpers ─────────────────────────────────────────────────────

    def assign(self, course: str, section: str, reg_no: str) -> bool:
        """Enrol a student in (course, section). Returns False if no seat."""
        if not self.has_seat(course, section):
            return False
        self.section_seats[course][section]["enrolled"].append(reg_no)
        return True

    def assign_allow_overflow(self, course: str, section: str, reg_no: str) -> bool:
        """
        Enrol a student even when section is full (controlled overflow mode).
        Returns False only if the section does not exist.
        """
        if not self.section_exists(course, section):
            return False
        enrolled = self.section_seats[course][section]["enrolled"]
        if reg_no not in enrolled:
            enrolled.append(reg_no)
        return True

    def remove(self, course: str, section: str, reg_no: str) -> bool:
        """Remove a student from (course, section). Returns False if not found."""
        if not self.section_exists(course, section):
            return False
        enrolled = self.section_seats[course][section]["enrolled"]
        if reg_no in enrolled:
            enrolled.remove(reg_no)
            return True
        return False

    # ── Section balancing ────────────────────────────────────────────────────

    def balance_sections(self, students_dict: dict[str, dict]) -> list[str]:
        """
        Rebalance over-loaded sections after allocation is complete.

        Strategy per course:
          1. Find the most-loaded section (``max_sec``) and the least-loaded
             (``min_sec``).
          2. If the difference exceeds ``capacity // 3``, try moving students
             from ``max_sec`` to ``min_sec``.
          3. A student can only be moved if *both* their primary and secondary
             course can be accommodated in ``min_sec`` (preserving the pairing).

        Returns:
            List of registration numbers that were successfully moved.
        """
        moved: list[str] = []

        for course_name, sections in self.section_seats.items():
            if len(sections) < 2:
                continue

            capacity = self.courses_config[course_name]["capacity"]
            threshold = max(capacity // 3, 5)
            counts = {s: len(d["enrolled"]) for s, d in sections.items()}
            max_sec = max(counts, key=counts.get)
            min_sec = min(counts, key=counts.get)

            # Demand-driven policy: never split a full section into an empty one.
            if counts[min_sec] == 0:
                continue

            if counts[max_sec] - counts[min_sec] <= threshold:
                continue

            logger.info(
                "Balancing %s: Section %s=%d vs Section %s=%d",
                course_name, max_sec, counts[max_sec], min_sec, counts[min_sec],
            )

            group = self.courses_config[course_name]["group"]
            to_move_count = (counts[max_sec] - counts[min_sec]) // 2
            candidates = list(sections[max_sec]["enrolled"])  # snapshot

            moved_this_round = 0
            for reg_no in candidates:
                if moved_this_round >= to_move_count:
                    break
                if not self.has_seat(course_name, min_sec):
                    break

                student = students_dict.get(reg_no)
                if not student:
                    continue

                # Determine paired course
                if group == "G1":
                    paired_course = student.get("allocated_secondary")
                else:
                    paired_course = student.get("allocated_primary")

                # Both courses must have space in min_sec
                if paired_course:
                    if not self.section_exists(paired_course, min_sec):
                        continue
                    if not self.has_seat(paired_course, min_sec):
                        continue

                # Move this course
                self.remove(course_name, max_sec, reg_no)
                self.assign(course_name, min_sec, reg_no)

                # Move paired course too (keep them in sync)
                if paired_course:
                    self.remove(paired_course, max_sec, reg_no)
                    self.assign(paired_course, min_sec, reg_no)

                student["allocated_section"] = min_sec
                moved.append(reg_no)
                moved_this_round += 1
                logger.info(
                    "Section balance: moved %s from %s-%s to %s-%s",
                    reg_no, course_name, max_sec, course_name, min_sec,
                )

        return moved

    def merge_underfilled_sections(self, students_dict: dict[str, dict]) -> int:
        """
        Merge underfilled sections of the same course when their combined
        enrolment does not exceed the section capacity.

        Algorithm (per course, repeated until stable):
          1. Sort sections alphabetically (A, B, C, …).
          2. For each pair (sec_keep, sec_drain) where sec_keep < sec_drain:
               if enrolled(sec_keep) + enrolled(sec_drain) ≤ capacity:
                   move all students from sec_drain into sec_keep
                   remove sec_drain
                   update student["allocated_section"] for G1-course merges
          3. Repeat until no pair can be merged.

        Args:
            students_dict: reg_no → student record (mutated in-place).

        Returns:
            Total number of sections removed.
        """
        total_removed = 0

        for course in list(self.section_seats):
            capacity = self.courses_config[course]["capacity"]
            changed = True

            while changed:
                changed = False
                sections = self.section_seats[course]
                labels = sorted(sections)          # alphabetical order

                merged_this_pass = False
                for i, sec_keep in enumerate(labels):
                    for sec_drain in labels[i + 1:]:
                        count_keep = len(sections[sec_keep]["enrolled"])
                        count_drain = len(sections[sec_drain]["enrolled"])

                        if count_drain == 0:
                            # Empty sections are handled by prune_empty_sections.
                            continue

                        if count_keep + count_drain > capacity:
                            continue

                        # ── Perform the merge ────────────────────────────
                        for reg_no in list(sections[sec_drain]["enrolled"]):
                            sections[sec_keep]["enrolled"].append(reg_no)
                            student = students_dict.get(reg_no)
                            if student:
                                # When the merging course is the student's G1,
                                # update the canonical section field.
                                if student.get("allocated_primary") == course:
                                    student["allocated_section"] = sec_keep

                        del sections[sec_drain]
                        logger.info(
                            "Merged %s Section %s (%d) into Section %s (%d) "
                            "— combined %d / %d.",
                            course, sec_drain, count_drain,
                            course, sec_keep, count_keep,
                            count_keep + count_drain, capacity,
                        )
                        total_removed += 1
                        changed = True
                        merged_this_pass = True
                        break          # restart with updated labels

                    if merged_this_pass:
                        break

        return total_removed

    def redistribute_underfilled_sections(
        self,
        students_dict: dict[str, dict],
        min_section_size: int = 5,
        allow_overflow: bool = True,
    ) -> tuple[int, int]:
        """
        Redistribute tiny leftover sections into other sections of the same course.

        Rule:
          1. Try moving with strict capacity first.
          2. If no strict target exists and ``allow_overflow`` is True,
             allow move into least-loaded target section.
          3. Keep paired primary/secondary course section in sync whenever possible.

        Returns:
            (sections_removed, students_moved)
        """
        sections_removed = 0
        students_moved = 0

        for course in list(self.section_seats):
            sections = self.section_seats[course]
            if len(sections) < 2:
                continue

            group = self.courses_config.get(course, {}).get("group", "")
            labels = sorted(sections)

            # Drain smallest non-empty sections first.
            drain_labels = [
                sec
                for sec in labels
                if 0 < len(sections[sec]["enrolled"]) < min_section_size
            ]

            for sec_drain in drain_labels:
                if sec_drain not in sections:
                    continue

                target_labels = [s for s in sorted(sections) if s != sec_drain]
                if not target_labels:
                    continue

                moved_all = True
                for reg_no in list(sections[sec_drain]["enrolled"]):
                    student = students_dict.get(reg_no)
                    if not student:
                        moved_all = False
                        continue

                    paired_course = (
                        student.get("allocated_secondary")
                        if group == "G1"
                        else student.get("allocated_primary")
                    )

                    # Prefer strict-capacity targets.
                    strict_targets: list[str] = []
                    for sec_target in target_labels:
                        if not self.has_seat(course, sec_target):
                            continue
                        if paired_course:
                            if not self.section_exists(paired_course, sec_target):
                                continue
                            if not self.has_seat(paired_course, sec_target):
                                continue
                        strict_targets.append(sec_target)

                    if strict_targets:
                        target = min(
                            strict_targets,
                            key=lambda s: (len(sections[s]["enrolled"]), s),
                        )
                        use_overflow = False
                    elif allow_overflow:
                        overflow_targets = []
                        for sec_target in target_labels:
                            if paired_course and not self.section_exists(paired_course, sec_target):
                                continue
                            overflow_targets.append(sec_target)
                        if not overflow_targets:
                            moved_all = False
                            continue
                        target = min(
                            overflow_targets,
                            key=lambda s: (len(sections[s]["enrolled"]), s),
                        )
                        use_overflow = True
                    else:
                        moved_all = False
                        continue

                    # Move this course.
                    self.remove(course, sec_drain, reg_no)
                    if use_overflow:
                        self.assign_allow_overflow(course, target, reg_no)
                    else:
                        self.assign(course, target, reg_no)

                    # Move paired course too when the student is currently enrolled in it.
                    if paired_course and self.section_exists(paired_course, sec_drain):
                        if reg_no in self.get_enrolled(paired_course, sec_drain):
                            self.remove(paired_course, sec_drain, reg_no)
                            if use_overflow:
                                self.assign_allow_overflow(paired_course, target, reg_no)
                            else:
                                self.assign(paired_course, target, reg_no)

                    student["allocated_section"] = target
                    students_moved += 1

                if sec_drain in sections and len(sections[sec_drain]["enrolled"]) == 0:
                    del sections[sec_drain]
                    sections_removed += 1
                    logger.info(
                        "Redistributed and removed tiny section %s-%s.",
                        course,
                        sec_drain,
                    )
                elif not moved_all:
                    logger.info(
                        "Could not fully redistribute %s-%s; keeping section.",
                        course,
                        sec_drain,
                    )

        return sections_removed, students_moved

    def prune_empty_sections(self) -> None:
        """Remove sections that have zero enrolment to keep sections demand-driven."""
        for course, sections in self.section_seats.items():
            empty_labels = [
                sec
                for sec, data in sections.items()
                if not data["enrolled"]
            ]
            # Keep at least one section shell per course.
            if len(empty_labels) >= len(sections):
                empty_labels = empty_labels[1:]

            for sec in empty_labels:
                del sections[sec]

    # ── Reporting helper ─────────────────────────────────────────────────────

    def get_section_summary(self) -> dict:
        """
        Return nested dict:
            { course_name: { section: { enrolled, capacity, available } } }
        """
        return {
            course: {
                section: {
                    "enrolled": len(data["enrolled"]),
                    "capacity": data["capacity"],
                    "available": data["capacity"] - len(data["enrolled"]),
                }
                for section, data in sorted(sections.items())
            }
            for course, sections in sorted(self.section_seats.items())
        }
