import { useMemo, useState } from "react";
import {
  Activity,
  AlertTriangle,
  BarChart3,
  CheckCircle2,
  Clock3,
  ListChecks,
  Play,
} from "lucide-react";
import { createReport } from "../api/client.js";
import BusinessPicker from "../components/BusinessPicker.jsx";

const PREVIEW_REPORT = {
  title: "Restaurant Review Analysis Report",
  business_name: "Example Bistro",
  sample_size: 87,
  status: "success",
  error_detail: null,
  executive_summary:
    "The selected review sample shows strong food-quality feedback, but repeated service delays and inconsistent staff responses are lowering the customer experience.",
  key_findings: [
    "Food quality is the strongest positive signal in the selected sample.",
    "Wait-time complaints appear repeatedly and are the clearest operational issue.",
    "Negative staff-attitude mentions often appear together with long waits.",
  ],
  analysis_summary: {
    sentiment_counts: {
      positive: 38,
      mixed: 24,
      neutral: 7,
      negative: 18,
    },
    aspect_counts: {
      food_quality: { positive: 41, negative: 9, neutral: 5 },
      staff_attitude: { positive: 14, negative: 24, neutral: 6 },
      pricing: { positive: 11, negative: 8, neutral: 14 },
      wait_time: { positive: 5, negative: 37, neutral: 4 },
      ambience: { positive: 22, negative: 5, neutral: 10 },
      cleanliness: { positive: 17, negative: 6, neutral: 7 },
    },
  },
  reasoning_summary: {
    patterns: [
      {
        description: "Wait-time complaints appear repeatedly in the selected sample.",
        aspect: "wait_time",
        frequency: 0.42,
        evidence_review_ids: ["r102", "r118", "r144", "r177"],
      },
      {
        description: "Staff attitude is rated lower when customers mention long waits.",
        aspect: "staff_attitude",
        frequency: 0.31,
        evidence_review_ids: ["r118", "r203", "r250"],
      },
      {
        description: "Food quality remains a positive driver even in mixed reviews.",
        aspect: "food_quality",
        frequency: 0.47,
        evidence_review_ids: ["r091", "r144", "r301", "r322"],
      },
    ],
  },
  root_causes: [
    {
      pattern: "Repeated wait-time complaints",
      cause: "Possible staffing or table-turnover issue during busy periods.",
      confidence: "medium",
    },
    {
      pattern: "Staff attitude drops when wait time is mentioned",
      cause: "Front-of-house pressure may be affecting service consistency.",
      confidence: "medium",
    },
  ],
  recommendations: [
    {
      priority: 1,
      issue: "Possible staffing or table-turnover issue during busy periods.",
      action: "Review weekend staffing levels and table assignment workflow.",
      category: "operations",
      expected_impact: "Reduce wait-time complaints.",
    },
    {
      priority: 2,
      issue: "Service consistency drops during high wait periods.",
      action: "Add a simple wait-time update script for front-of-house staff.",
      category: "service",
      expected_impact: "Reduce frustration in mixed and negative reviews.",
    },
    {
      priority: 3,
      issue: "Positive food comments are not offsetting service complaints.",
      action: "Preserve food-quality strengths while fixing service bottlenecks first.",
      category: "prioritisation",
      expected_impact: "Protect the strongest positive driver while addressing the main complaint.",
    },
  ],
  limitations: [
    "This report uses a random sample, not every Yelp review.",
    "Root causes are inferred from review text and require business validation.",
  ],
};

const ASPECT_LABELS = {
  food_quality: "Food quality",
  staff_attitude: "Staff attitude",
  pricing: "Pricing",
  wait_time: "Wait time",
  ambience: "Ambience",
  cleanliness: "Cleanliness",
  other: "Other",
};

const SENTIMENT_LABELS = {
  positive: "Positive",
  mixed: "Mixed",
  neutral: "Neutral",
  negative: "Negative",
};

function normalizeReport(apiReport) {
  if (!apiReport || apiReport.status === "not_implemented") {
    return PREVIEW_REPORT;
  }

  return {
    ...PREVIEW_REPORT,
    ...apiReport,
    analysis_summary: apiReport.analysis_summary ?? PREVIEW_REPORT.analysis_summary,
    reasoning_summary: apiReport.reasoning_summary ?? PREVIEW_REPORT.reasoning_summary,
    root_causes: apiReport.root_causes ?? [],
    recommendations: apiReport.recommendations ?? [],
    limitations: apiReport.limitations ?? PREVIEW_REPORT.limitations,
  };
}

function getSentimentTotal(sentimentCounts) {
  return Object.values(sentimentCounts).reduce((sum, value) => sum + value, 0);
}

function getTopAspect(aspectCounts) {
  return Object.entries(aspectCounts)
    .map(([aspect, counts]) => ({
      aspect,
      negative: counts.negative ?? 0,
      total: Object.values(counts).reduce((sum, value) => sum + value, 0),
    }))
    .sort((a, b) => b.negative - a.negative)[0];
}

function StatusBadge({ status }) {
  const normalized = status === "success" ? "success" : status === "error" ? "error" : "partial";
  return <span className={`status-badge status-badge--${normalized}`}>{status}</span>;
}

function KpiCard({ icon: Icon, label, value, detail }) {
  return (
    <section className="kpi-card" aria-label={label}>
      <div className="kpi-card__icon">
        <Icon size={18} aria-hidden="true" />
      </div>
      <div>
        <p>{label}</p>
        <strong>{value}</strong>
        <span>{detail}</span>
      </div>
    </section>
  );
}

function SentimentBar({ counts }) {
  const total = getSentimentTotal(counts);

  return (
    <div className="sentiment">
      <div className="sentiment__bar" aria-label="Sentiment distribution">
        {Object.entries(counts).map(([key, value]) => (
          <span
            key={key}
            className={`sentiment__segment sentiment__segment--${key}`}
            style={{ width: `${total ? (value / total) * 100 : 0}%` }}
            title={`${SENTIMENT_LABELS[key]}: ${value}`}
          />
        ))}
      </div>
      <div className="sentiment__legend">
        {Object.entries(counts).map(([key, value]) => (
          <span key={key}>
            <i className={`legend-dot legend-dot--${key}`} />
            {SENTIMENT_LABELS[key]} {value}
          </span>
        ))}
      </div>
    </div>
  );
}

function AspectTable({ aspectCounts }) {
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Aspect</th>
            <th>Positive</th>
            <th>Negative</th>
            <th>Neutral</th>
            <th>Main Signal</th>
          </tr>
        </thead>
        <tbody>
          {Object.entries(aspectCounts).map(([aspect, counts]) => {
            const signal = Object.entries(counts).sort((a, b) => b[1] - a[1])[0]?.[0] ?? "neutral";
            return (
              <tr key={aspect}>
                <td>{ASPECT_LABELS[aspect] ?? aspect}</td>
                <td>{counts.positive ?? 0}</td>
                <td>{counts.negative ?? 0}</td>
                <td>{counts.neutral ?? 0}</td>
                <td>
                  <span className={`signal signal--${signal}`}>{signal}</span>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function PatternsList({ patterns }) {
  return (
    <div className="pattern-list">
      {patterns.map((pattern) => (
        <article className="pattern-row" key={`${pattern.aspect}-${pattern.description}`}>
          <div>
            <h3>{pattern.description}</h3>
            <p>
              {ASPECT_LABELS[pattern.aspect] ?? pattern.aspect} ·{" "}
              {pattern.evidence_review_ids?.length ?? 0} evidence reviews
            </p>
          </div>
          <div className="frequency">
            <strong>{Math.round((pattern.frequency ?? 0) * 100)}%</strong>
            <span>
              <i style={{ width: `${Math.round((pattern.frequency ?? 0) * 100)}%` }} />
            </span>
          </div>
        </article>
      ))}
    </div>
  );
}

function RootCauseList({ rootCauses }) {
  return (
    <div className="root-list">
      {rootCauses.map((rootCause) => (
        <article className="root-item" key={`${rootCause.pattern}-${rootCause.cause}`}>
          <div>
            <h3>{rootCause.pattern}</h3>
            <p>{rootCause.cause}</p>
          </div>
          <span className={`confidence confidence--${rootCause.confidence}`}>
            {rootCause.confidence}
          </span>
        </article>
      ))}
    </div>
  );
}

function RecommendationTable({ recommendations }) {
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Priority</th>
            <th>Issue</th>
            <th>Action</th>
            <th>Category</th>
            <th>Expected Impact</th>
          </tr>
        </thead>
        <tbody>
          {[...recommendations]
            .sort((a, b) => a.priority - b.priority)
            .map((recommendation) => (
              <tr key={`${recommendation.priority}-${recommendation.issue}`}>
                <td>
                  <span className="priority">{recommendation.priority}</span>
                </td>
                <td>{recommendation.issue}</td>
                <td>{recommendation.action}</td>
                <td>{recommendation.category}</td>
                <td>{recommendation.expected_impact}</td>
              </tr>
            ))}
        </tbody>
      </table>
    </div>
  );
}

export default function Dashboard() {
  const [selected, setSelected] = useState(null);
  const [sampleCap, setSampleCap] = useState(100);
  const [report, setReport] = useState(PREVIEW_REPORT);
  const [requestState, setRequestState] = useState("preview");
  const [message, setMessage] = useState("Local preview data. API report replaces it when available.");

  const sentimentCounts = report.analysis_summary?.sentiment_counts ?? {};
  const aspectCounts = report.analysis_summary?.aspect_counts ?? {};
  const patterns = report.reasoning_summary?.patterns ?? [];
  const topAspect = useMemo(() => getTopAspect(aspectCounts), [aspectCounts]);
  const topPattern = patterns.toSorted((a, b) => (b.frequency ?? 0) - (a.frequency ?? 0))[0];
  const highPriorityCount = report.recommendations.filter((item) => item.priority <= 2).length;
  const topIssueFrequency = topPattern ? `${Math.round(topPattern.frequency * 100)}%` : "n/a";

  async function handleSubmit(event) {
    event.preventDefault();
    if (!selected) {
      setRequestState("error");
      setMessage("Hãy tìm và chọn một nhà hàng trước.");
      return;
    }
    setRequestState("running");
    setMessage("Generating report...");

    try {
      const apiReport = await createReport({
        restaurant_name: selected.name,
        business_id: selected.business_id,
        sample_size: Number(sampleCap),
      });
      const normalized = normalizeReport(apiReport);
      setReport({
        ...normalized,
        business_name: normalized.business_name || selected.name,
        sample_size: normalized.sample_size || Number(sampleCap),
      });
      setRequestState(apiReport.status === "not_implemented" ? "preview" : "success");
      setMessage(
        apiReport.status === "not_implemented"
          ? "API returned placeholder data. Showing local preview."
          : "Report loaded from API.",
      );
    } catch (error) {
      setRequestState("error");
      setMessage(error instanceof Error ? error.message : "Report request failed.");
    }
  }

  return (
    <main className="app-shell">
      <header className="topbar">
        <div>
          <h1>Restaurant Review Analysis</h1>
          <p>Sample-based report dashboard</p>
        </div>
      </header>

      <section className="panel" style={{ marginBottom: 18 }}>
        <div className="section-title">
          <h2>1. Chọn nhà hàng</h2>
          <span>tìm theo tên, chọn từ kết quả gần nhất</span>
        </div>
        <BusinessPicker selectedId={selected?.business_id} onSelect={setSelected} />

        <form className="run-bar" onSubmit={handleSubmit}>
          <div className="run-bar__sel">
            {selected ? (
              <>
                <CheckCircle2 size={18} aria-hidden="true" />
                <div>
                  <strong>{selected.name}</strong>
                  <span>{selected.review_count} reviews</span>
                </div>
              </>
            ) : (
              <span className="run-bar__hint">Chưa chọn nhà hàng nào.</span>
            )}
          </div>
          <label className="sample-input">
            <span>Sample Cap</span>
            <input
              type="number"
              min="1"
              max="100"
              value={sampleCap}
              onChange={(event) => setSampleCap(event.target.value)}
              aria-label="Sample cap"
            />
          </label>
          <button
            type="submit"
            className="run-bar__btn"
            disabled={!selected || requestState === "running"}
          >
            <Play size={16} aria-hidden="true" />
            Generate Report
          </button>
        </form>
      </section>

      <section className="report-heading">
        <div>
          <div className="report-heading__meta">
            <StatusBadge status={report.status} />
            <span>{requestState}</span>
          </div>
          <h2>{report.business_name}</h2>
          <p>{report.executive_summary}</p>
        </div>
        <aside className={`api-note api-note--${requestState}`}>
          {requestState === "error" ? <AlertTriangle size={18} /> : <CheckCircle2 size={18} />}
          <span>{message}</span>
        </aside>
      </section>

      <section className="kpi-grid" aria-label="Report statistics">
        <KpiCard
          icon={BarChart3}
          label="Sample Size"
          value={`${report.sample_size} / ${sampleCap}`}
          detail="randomly sampled reviews"
        />
        <KpiCard
          icon={Clock3}
          label="Top Issue"
          value={ASPECT_LABELS[topAspect?.aspect] ?? "n/a"}
          detail={`${topAspect?.negative ?? 0} negative mentions`}
        />
        <KpiCard
          icon={Activity}
          label="Issue Frequency"
          value={topIssueFrequency}
          detail="highest detected pattern"
        />
        <KpiCard
          icon={ListChecks}
          label="Priority Actions"
          value={highPriorityCount}
          detail="priority 1-2 recommendations"
        />
      </section>

      <section className="content-grid">
        <section className="panel panel--wide">
          <div className="section-title">
            <h2>Sentiment Mix</h2>
            <span>{getSentimentTotal(sentimentCounts)} classified reviews</span>
          </div>
          <SentimentBar counts={sentimentCounts} />
        </section>

        <section className="panel panel--wide">
          <div className="section-title">
            <h2>Key Findings</h2>
            <span>{report.key_findings.length} findings</span>
          </div>
          <ul className="finding-list">
            {report.key_findings.map((finding) => (
              <li key={finding}>{finding}</li>
            ))}
          </ul>
        </section>

        <section className="panel panel--wide">
          <div className="section-title">
            <h2>Aspect Breakdown</h2>
            <span>positive, negative, neutral labels</span>
          </div>
          <AspectTable aspectCounts={aspectCounts} />
        </section>

        <section className="panel">
          <div className="section-title">
            <h2>Detected Patterns</h2>
            <span>{patterns.length} patterns</span>
          </div>
          <PatternsList patterns={patterns} />
        </section>

        <section className="panel">
          <div className="section-title">
            <h2>Root Causes</h2>
            <span>{report.root_causes.length} causes</span>
          </div>
          <RootCauseList rootCauses={report.root_causes} />
        </section>

        <section className="panel panel--full">
          <div className="section-title">
            <h2>Recommendations</h2>
            <span>{report.recommendations.length} actions</span>
          </div>
          <RecommendationTable recommendations={report.recommendations} />
        </section>

        <section className="panel panel--full panel--muted">
          <div className="section-title">
            <h2>Limitations</h2>
            <span>{report.error_detail ? "error detail included" : "sampling constraints"}</span>
          </div>
          <ul className="limitation-list">
            {report.limitations.map((limitation) => (
              <li key={limitation}>{limitation}</li>
            ))}
            {report.error_detail ? <li>{report.error_detail}</li> : null}
          </ul>
        </section>
      </section>
    </main>
  );
}
