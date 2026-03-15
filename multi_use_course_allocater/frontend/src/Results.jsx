import React from "react";

function DataTable({ rows }) {
  if (!rows.length) return <p>No rows to display.</p>;
  const keys = Object.keys(rows[0]);
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            {keys.map((key) => (
              <th key={key}>{key}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, idx) => (
            <tr key={idx}>
              {keys.map((key) => (
                <td key={`${idx}-${key}`}>{String(row[key] ?? "")}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function SummaryCard({ title, value, tone = "ink" }) {
  return (
    <div className={`summary-card tone-${tone}`}>
      <p className="meta">{title}</p>
      <div className="summary-value">{value ?? "-"}</div>
    </div>
  );
}

function LogList({ title, items, query }) {
  const filtered = (items || []).filter((item) =>
    String(item).toLowerCase().includes(query.toLowerCase())
  );
  const display = query ? filtered : items || [];

  return (
    <div className="log-card">
      <div className="log-title">{title}</div>
      <div className="log-body">
        {display.length ? (
          <ul>
            {display.slice(0, 200).map((item, idx) => (
              <li key={`${title}-${idx}`}>{String(item)}</li>
            ))}
          </ul>
        ) : (
          <p className="meta">Nothing recorded.</p>
        )}
      </div>
    </div>
  );
}

function Results({
  result,
  searchTerm,
  onSearchChange,
  logSearch = "",
  onLogSearchChange = () => {},
  activeTab,
  onTabChange,
  filteredStudents,
  capacityBySlot,
  topSkills,
  unallocatedRows,
  downloadSheet,
  downloadLogs,
  downloadAll,
  onBack,
}) {
  return (
    <section className="panel">
      <div className="row-actions" style={{ justifyContent: "space-between", marginBottom: 6 }}>
        <div className="meta">Results view</div>
        {onBack && (
          <button className="ghost" onClick={onBack}>Back to settings</button>
        )}
      </div>
      <div className="tab-bar">
        {[
          { id: "summary", label: "Summary" },
          { id: "students", label: "Students" },
          { id: "sections", label: "Section-wise" },
          { id: "skills", label: "Skill-wise" },
          { id: "slots", label: "Slot-wise" },
          { id: "capacity", label: "Capacity" },
          { id: "logs", label: "Logs" },
        ].map((tab) => (
          <button
            key={tab.id}
            className={`tab-btn ${activeTab === tab.id ? "active" : ""}`}
            onClick={() => onTabChange(tab.id)}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {activeTab === "summary" && (
        <div className="tab-content">
          <div className="summary-grid">
            <SummaryCard title="Students Loaded" value={result.summary?.studentsLoaded} tone="ink" />
            <SummaryCard title="Students Allocated" value={result.summary?.studentsAllocated} tone="success" />
            <SummaryCard title="Duplicate Removed" value={result.summary?.duplicateStudentsRemoved} tone="warn" />
            <SummaryCard title="Invalid CGPA Removed" value={result.summary?.invalidCgpaRowsRemoved} tone="danger" />
          </div>

          <div className="export-row">
            <button onClick={() => downloadSheet(result.studentWise, "student-wise")}>Download Student-wise</button>
            <button onClick={() => downloadSheet(result.sectionWise, "section-wise")}>Download Section-wise</button>
            <button onClick={() => downloadSheet(result.skillWise, "skill-wise")}>Download Skill-wise</button>
            <button onClick={() => downloadSheet(result.capacityDashboard, "capacity-dashboard")}>Download Capacity</button>
            <button onClick={() => downloadSheet(unallocatedRows, "unallocated-overall")}>
              Download Unallocated
            </button>
            <button onClick={downloadLogs}>Download Logs</button>
            <button onClick={downloadAll}>Download Workbook</button>
          </div>

          <div className="panel inset">
            <div className="panel-heading">
              <h3>Top Skills</h3>
              <span className="meta">by allocations</span>
            </div>
            <div className="chip-list">
              {topSkills.map(({ skill, count }) => (
                <div key={skill} className="chip">
                  <span>{skill}</span>
                  <span className="pill">{count}</span>
                </div>
              ))}
              {!topSkills.length && <p className="meta">No skill data.</p>}
            </div>
          </div>
        </div>
      )}

      {activeTab === "students" && (
        <div className="tab-content">
          <div className="panel inset">
            <div className="panel-heading stack">
              <div>
                <h3>Find a Student</h3>
                <p className="meta">Search by reg no, name, section, slot, or skill. Showing up to 200 hits.</p>
              </div>
              <input
                className="search"
                placeholder="Search students..."
                value={searchTerm}
                onChange={(e) => onSearchChange(e.target.value)}
              />
            </div>
            <DataTable rows={filteredStudents} />
          </div>
        </div>
      )}

      {activeTab === "sections" && (
        <div className="tab-content">
          <div className="panel inset">
            <div className="panel-heading">
              <h3>Section-wise</h3>
            </div>
            <DataTable rows={result.sectionWise || []} />
          </div>
        </div>
      )}

      {activeTab === "skills" && (
        <div className="tab-content">
          <div className="panel inset">
            <div className="panel-heading">
              <h3>Skill-wise</h3>
            </div>
            <DataTable rows={result.skillWise || []} />
          </div>
        </div>
      )}

      {activeTab === "slots" && (
        <div className="tab-content">
          <div className="panel inset">
            <div className="panel-heading">
              <h3>Slot-wise</h3>
            </div>
            <DataTable rows={result.slotWise || []} />
          </div>
        </div>
      )}

      {activeTab === "capacity" && (
        <div className="tab-content">
          <div className="panel inset">
            <div className="panel-heading">
              <h3>Slot Capacity Usage</h3>
              <span className="meta">live after allocation</span>
            </div>
            <div className="slot-grid">
              {capacityBySlot.map(({ slot, items }) => (
                <div key={slot} className="slot-card">
                  <div className="slot-title">{slot}</div>
                  {items.map(({ Skill, Allocated, Capacity }) => {
                    const pct = Math.min(100, Math.round((Allocated / Capacity) * 100));
                    return (
                      <div key={`${slot}-${Skill}`} className="bar-row">
                        <div className="bar-label">
                          <span>{Skill}</span>
                          <span className="meta">{Allocated}/{Capacity}</span>
                        </div>
                        <div className="bar-shell">
                          <div className="bar-fill" style={{ width: `${pct}%` }} />
                        </div>
                      </div>
                    );
                  })}
                </div>
              ))}
              {!capacityBySlot.length && <p className="meta">No capacity data.</p>}
            </div>
          </div>
          <div className="panel inset">
            <div className="panel-heading">
              <h3>Capacity Table</h3>
            </div>
            <DataTable rows={result.capacityDashboard || []} />
          </div>
        </div>
      )}

      {activeTab === "logs" && (
        <div className="tab-content">
          <div className="panel inset">
            <div className="panel-heading stack">
              <h3>Allocation Logs</h3>
              <div className="meta">Use download for full text</div>
              <input
                className="search"
                placeholder="Search logs..."
                value={logSearch}
                onChange={(e) => onLogSearchChange(e.target.value)}
              />
            </div>
            <div className="log-grid">
              <LogList title="Allocation" items={result.logs?.allocationLog || []} query={logSearch} />
              <LogList title="Duplicate Students Removed" items={result.logs?.duplicateStudentsRemoved || []} query={logSearch} />
              <LogList title="Invalid CGPA Rows" items={result.logs?.invalidCgpaRows || []} query={logSearch} />
            </div>
          </div>
        </div>
      )}
    </section>
  );
}

export default Results;
