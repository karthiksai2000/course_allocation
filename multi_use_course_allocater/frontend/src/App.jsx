import { useEffect, useMemo, useState } from "react";
import * as XLSX from "xlsx";
import Results from "./Results";

const DEPT_APP_URL = import.meta.env.VITE_DEPT_ALLOC_URL || "http://localhost:5000";
const API_BASE = import.meta.env.VITE_LIFESKILL_API || "http://localhost:8000";

function distributeSections(sections, slotNames) {
  const totalSlots = slotNames.length;
  if (!totalSlots) return [];
  const base = Math.floor(sections.length / totalSlots);
  const remainder = sections.length % totalSlots;
  const counts = slotNames.map((_, idx) => base + (idx < remainder ? 1 : 0));

  const result = [];
  let slotIdx = 0;
  let usedInSlot = 0;

  sections.forEach((section) => {
    result.push([section, slotNames[slotIdx]]);
    usedInSlot += 1;
    if (usedInSlot >= counts[slotIdx] && slotIdx < totalSlots - 1) {
      slotIdx += 1;
      usedInSlot = 0;
    }
  });

  return result;
}

const initialSectionSlots = [
  ["1", "Slot1"], ["2", "Slot1"], ["3", "Slot1"], ["4", "Slot1"],
  ["5", "Slot2"], ["6", "Slot2"], ["7", "Slot2"], ["8", "Slot2"],
  ["9", "Slot3"], ["10", "Slot3"], ["11", "Slot3"], ["12", "Slot3"],
  ["13", "Slot4"], ["14", "Slot4"], ["15", "Slot4"], ["16", "Slot4"], ["17", "Slot4"],
  ["18", "Slot5"], ["19", "Slot5"], ["20", "Slot5"], ["21", "Slot5"], ["22", "Slot5"],
];

const initialSkillCapacities = [
  ["German", 70],
  ["French", 70],
  ["Cookery", 70],
  ["Video Editing", 70],
  ["Yoga", 70],
  ["Painting", 70],
  ["Literary - Public Speaking", 70],
  ["Carnatic Music", 70],
  ["Photography", 70],
  ["APSSDC Electronics Home", 70],
  ["APSSDC Electrical", 70],
  ["Block printing-kalamkari", 70],
  ["Handcrafts", 70],
  ["Self Defence by Taekwondo", 70],
  ["Computational Thinking (only for slot-2 and slot-3)", 70],
  ["Pottery", 70],
  ["Western Dance", 70],
  ["Kuchipudi (Classical Dance)", 70],
];

function App() {
  const [file, setFile] = useState(null);
  const [xWeight, setXWeight] = useState(0.3);
  const [sectionSkillLimit, setSectionSkillLimit] = useState(4);
  const [sectionSlots, setSectionSlots] = useState(initialSectionSlots);
  const [skillCapacities, setSkillCapacities] = useState(initialSkillCapacities);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState(null);
  const [searchTerm, setSearchTerm] = useState("");
  const [logSearch, setLogSearch] = useState("");
  const [activeTab, setActiveTab] = useState("summary");
  const [slotCount, setSlotCount] = useState(5);
  const [fetchedSections, setFetchedSections] = useState([]);
  const [showConfig, setShowConfig] = useState(false);
  const [showResultsPage, setShowResultsPage] = useState(false);
  const [selectedModule, setSelectedModule] = useState(null);

  const config = useMemo(() => {
    const sectionSlot = Object.fromEntries(sectionSlots);
    const skillCapacity = Object.fromEntries(
      skillCapacities.map(([skill, cap]) => [skill, Number(cap)])
    );
    return {
      xWeight: Number(xWeight),
      sectionSkillLimit: Number(sectionSkillLimit),
      sectionSlot,
      skillCapacity,
    };
  }, [xWeight, sectionSkillLimit, sectionSlots, skillCapacities]);

  const updateSectionSlot = (idx, key, value) => {
    setSectionSlots((prev) =>
      prev.map((item, i) => {
        if (i !== idx) return item;
        return key === "section" ? [value, item[1]] : [item[0], value];
      })
    );
  };

  const updateSkillCapacity = (idx, key, value) => {
    setSkillCapacities((prev) =>
      prev.map((item, i) => {
        if (i !== idx) return item;
        return key === "skill" ? [value, item[1]] : [item[0], value];
      })
    );
  };

  const handleFileChange = async (event) => {
    const picked = event.target.files?.[0] || null;
    setFile(picked);
    if (!picked) return;
    setShowConfig(true);
    setLogSearch("");
    setSelectedModule("lifeskill");

    try {
      const formData = new FormData();
      formData.append("file", picked);

      const response = await fetch(`${API_BASE}/inspect-excel`, {
        method: "POST",
        body: formData,
      });

      const data = await response.json();
      if (!response.ok) {
        throw new Error(data.detail || "Failed to inspect Excel");
      }

      const detectedSkills = data.skills || [];
      if (detectedSkills.length) {
        setSkillCapacities((prev) => {
          const prevMap = new Map(prev);
          return detectedSkills.map((skill) => [skill, prevMap.get(skill) ?? 70]);
        });
      }

      const detectedSections = data.sections || [];
      if (detectedSections.length) {
        const totalSlots = Math.max(1, Number(slotCount) || 1);
        const slotNames = Array.from({ length: totalSlots }, (_, i) => `Slot${i + 1}`);
        setSectionSlots(distributeSections(detectedSections, slotNames));
        setFetchedSections(detectedSections);
      }
    } catch (parseErr) {
      console.error("Inspect failed", parseErr);
      setError(parseErr.message || "Could not inspect Excel file");
    }
  };

  const runAllocation = async () => {
    setError("");
    setResult(null);

    if (!file) {
      setError("Please upload an Excel file before running allocation.");
      return;
    }

    setLoading(true);
    try {
      const formData = new FormData();
      formData.append("file", file);
      formData.append("config", JSON.stringify(config));

      const response = await fetch(`${API_BASE}/run-allocation`, {
        method: "POST",
        body: formData,
      });

      const data = await response.json();
      if (!response.ok) {
        throw new Error(data.detail || "Allocation request failed");
      }

      setResult(data);
      setActiveTab("summary");
      setShowResultsPage(true);
    } catch (err) {
      setError(err.message || "Unexpected error while running allocation");
    } finally {
      setLoading(false);
    }
  };

  const filteredStudents = useMemo(() => {
    if (!result?.studentWise) return [];
    const q = searchTerm.trim().toLowerCase();
    if (!q) return result.studentWise.slice(0, 200);
    return result.studentWise
      .filter((row) =>
        ["RegNo", "Name", "Skill", "Section", "Slot"].some((k) =>
          String(row[k] ?? "").toLowerCase().includes(q)
        )
      )
      .slice(0, 200);
  }, [result, searchTerm]);

  const capacityBySlot = useMemo(() => {
    if (!result?.capacityDashboard) return [];
    const grouped = {};
    result.capacityDashboard.forEach(({ Slot, Skill, Allocated, Capacity }) => {
      if (!grouped[Slot]) grouped[Slot] = [];
      grouped[Slot].push({ Skill, Allocated, Capacity });
    });
    return Object.entries(grouped).map(([slot, items]) => ({ slot, items }));
  }, [result]);

  const unallocatedRows = useMemo(() => {
    if (!result?.logs) return [];
    const rows = [];
    (result.logs.duplicateStudentsRemoved || []).forEach((reg) => {
      rows.push({ RegNo: reg, Reason: "Duplicate student removed" });
    });
    (result.logs.invalidCgpaRows || []).forEach((reg) => {
      rows.push({ RegNo: reg, Reason: "Invalid or missing CGPA" });
    });
    return rows;
  }, [result]);

  const topSkills = useMemo(() => {
    if (!result?.skillWise) return [];
    const counts = result.skillWise.reduce((acc, row) => {
      acc[row.Skill] = (acc[row.Skill] || 0) + 1;
      return acc;
    }, {});
    return Object.entries(counts)
      .map(([skill, count]) => ({ skill, count }))
      .sort((a, b) => b.count - a.count)
      .slice(0, 8);
  }, [result]);

  const downloadSheet = (rows, sheetName) => {
    if (!rows?.length) return;
    const workbook = XLSX.utils.book_new();
    const worksheet = XLSX.utils.json_to_sheet(rows);
    XLSX.utils.book_append_sheet(workbook, worksheet, sheetName.slice(0, 31));
    XLSX.writeFile(workbook, `${sheetName}.xlsx`);
  };

  const downloadAll = () => {
    if (!result) return;
    const workbook = XLSX.utils.book_new();
    const addSheet = (rows, name) => {
      if (!rows?.length) return;
      XLSX.utils.book_append_sheet(
        workbook,
        XLSX.utils.json_to_sheet(rows),
        name.slice(0, 31)
      );
    };
    addSheet(result.studentWise, "StudentWise");
    addSheet(result.sectionWise, "SectionWise");
    addSheet(result.skillWise, "SkillWise");
    addSheet(result.slotWise, "SlotWise");
    addSheet(result.capacityDashboard, "CapacityDashboard");
    if (result.logs?.allocationLog?.length) {
      const asRows = result.logs.allocationLog.map((line, idx) => ({ Index: idx + 1, Log: line }));
      addSheet(asRows, "AllocationLog");
    }
    XLSX.writeFile(workbook, "allocation-results.xlsx");
  };

  useEffect(() => {
    if (!fetchedSections.length) return;
    const totalSlots = Math.max(1, Number(slotCount) || 1);
    const slotNames = Array.from({ length: totalSlots }, (_, i) => `Slot${i + 1}`);
    setSectionSlots(distributeSections(fetchedSections, slotNames));
  }, [slotCount, fetchedSections]);

  const downloadLogs = () => {
    if (!result?.logs) return;
    const blob = new Blob(
      [
        "Allocation Log\n",
        ...(result.logs.allocationLog || []).map((l) => `${l}\n`),
        "\nDuplicate Students Removed\n",
        ...(result.logs.duplicateStudentsRemoved || []).map((r) => `${r}\n`),
        "\nInvalid CGPA Rows\n",
        ...(result.logs.invalidCgpaRows || []).map((r) => `${r}\n`),
      ],
      { type: "text/plain;charset=utf-8" }
    );
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = "allocation-logs.txt";
    link.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="page-shell">
      <header className="hero">
        <h1>Allocation Control Hub</h1>
        <p>Select a module to proceed: Life Skill allocator or Department Elective allocator.</p>
      </header>

      {!selectedModule && (
        <section className="panel module-grid">
          <div className="module-card">
            <h2>Life Skill Allocator</h2>
            <p>Upload Excel, configure constraints, and run the life skill allocation pipeline.</p>
            <button onClick={() => setSelectedModule("lifeskill")}>Open Life Skill Allocator</button>
          </div>
          <div className="module-card">
            <h2>Department Elective Allocator</h2>
            <p>Use the course allocation console for departmental electives.</p>
            <button onClick={() => window.open(DEPT_APP_URL, "_blank")}>Open Department Elective</button>
            <p className="meta">Opens the course allocation app (set VITE_DEPT_ALLOC_URL to change link).</p>
          </div>
        </section>
      )}

      {selectedModule === "lifeskill" && !showResultsPage && (
        <>
          <section className="panel two-col">
            <label>
              Attendance Weight
              <input
                type="number"
                min="0"
                max="1"
                step="0.05"
                value={xWeight}
                onChange={(e) => setXWeight(e.target.value)}
              />
            </label>

            <label>
              Section Skill Limit
              <p>the count of maximum students can alloted to same skill</p>
              <input
                type="number"
                min="1"
                value={sectionSkillLimit}
                onChange={(e) => setSectionSkillLimit(e.target.value)}
              />
            </label>

            <label>
              Number of Slots (auto-assign)
              <p>We distribute fetched sections across these slots by default. You can still edit after.</p>
              <input
                type="number"
                min="1"
                value={slotCount}
                onChange={(e) => setSlotCount(e.target.value)}
              />
            </label>

          </section>

          <section className="panel">
            <h2>Upload Excel</h2>
            <p className="meta">
              File should include columns for Student Name, Reg No, CGPA, Section, and preference columns named like
              Row1/Row2... (attendance column optional). We auto-detect sections and courses from the uploaded sheet.
            </p>
            <input
              type="file"
              accept=".xlsx,.xls"
              onChange={handleFileChange}
            />
            {!showConfig && (
              <div className="row-actions" style={{ justifyContent: "flex-start", marginTop: 10 }}>
                <button className="ghost" onClick={() => setShowConfig(true)}>Show default courses & slots</button>
              </div>
            )}
          </section>

          {showConfig && (
            <>
              <section className="panel">
                <h2>Skill Capacities <span className="pill">{skillCapacities.length}</span></h2>
                <div className="row-actions">
                  <button className="ghost" onClick={() => setSkillCapacities((prev) => [...prev, ["New Course", 70]])}>
                    + Add course
                  </button>
                </div>
                <div className="grid-table">
                  {skillCapacities.map(([skill, cap], idx) => (
                    <div className="grid-row" key={`skill-${idx}`}>
                      <input
                        value={skill}
                        onChange={(e) => updateSkillCapacity(idx, "skill", e.target.value)}
                      />
                      <div className="row-with-delete">
                        <input
                          type="number"
                          min="1"
                          value={cap}
                          onChange={(e) => updateSkillCapacity(idx, "capacity", e.target.value)}
                        />
                        <button
                          className="mini danger"
                          title="Remove course"
                          onClick={() =>
                            setSkillCapacities((prev) => prev.filter((_, i) => i !== idx))
                          }
                        >
                          ×
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              </section>

              <section className="panel">
                <h2>Section to Slot Mapping <span className="pill">{sectionSlots.length}</span></h2>
                <div className="row-actions">
                  <button className="ghost" onClick={() => setSectionSlots((prev) => [...prev, ["", "Slot1"]])}>
                    + Add section
                  </button>
                </div>
                <div className="grid-table">
                  {sectionSlots.map(([section, slot], idx) => (
                    <div className="grid-row" key={`section-${idx}`}>
                      <input
                        value={section}
                        onChange={(e) => updateSectionSlot(idx, "section", e.target.value)}
                      />
                      <div className="row-with-delete">
                        <input
                          value={slot}
                          onChange={(e) => updateSectionSlot(idx, "slot", e.target.value)}
                        />
                        <button
                          className="mini danger"
                          title="Remove section"
                          onClick={() => setSectionSlots((prev) => prev.filter((_, i) => i !== idx))}
                        >
                          ×
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              </section>
            </>
          )}

          <section className="panel">
            <div className="row-actions" style={{ justifyContent: "space-between" }}>
              <button className="ghost" onClick={() => setSelectedModule(null)}>Back to Home</button>
              <div>
                <button onClick={runAllocation} disabled={loading}>
                  {loading ? "Running..." : "Run Allocation"}
                </button>
              </div>
            </div>
            {error && <p className="error-text">{error}</p>}
          </section>
        </>
      )}

      {showResultsPage && result && selectedModule === "lifeskill" && (
        <Results
          result={result}
          searchTerm={searchTerm}
          onSearchChange={setSearchTerm}
          logSearch={logSearch}
          onLogSearchChange={setLogSearch}
          activeTab={activeTab}
          onTabChange={setActiveTab}
          filteredStudents={filteredStudents}
          capacityBySlot={capacityBySlot}
          topSkills={topSkills}
          unallocatedRows={unallocatedRows}
          downloadSheet={downloadSheet}
          downloadLogs={downloadLogs}
          downloadAll={downloadAll}
          onBack={() => setShowResultsPage(false)}
        />
      )}
    </div>
  );
}

export default App;
