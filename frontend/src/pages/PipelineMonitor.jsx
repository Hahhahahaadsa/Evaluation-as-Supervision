import { useEffect, useMemo, useRef, useState } from "react";
import {
  CheckCircle2,
  Clock3,
  Loader2,
  MapPin,
  Play,
  TimerReset,
  XCircle,
} from "lucide-react";
import { streamReport } from "../api/client.js";
import BusinessPicker from "../components/BusinessPicker.jsx";

// Canonical stage order, matching the backend SSE event names.
const STAGES = [
  { key: "search_business", label: "Tìm nhà hàng", hint: "Fuzzy search business" },
  { key: "load_reviews", label: "Tải reviews", hint: "Quét dataset review" },
  { key: "preprocess", label: "Tiền xử lý", hint: "Làm sạch dữ liệu" },
  { key: "analysis_agent", label: "Phân tích · Analysis", hint: "LLM theo lô review" },
  { key: "reasoning_agent", label: "Suy luận · Reasoning", hint: "Tìm pattern & nguyên nhân" },
  { key: "strategy_agent", label: "Chiến lược · Strategy", hint: "Sinh khuyến nghị" },
  { key: "report_agent", label: "Báo cáo · Report", hint: "Tổng hợp báo cáo" },
];

const STAGE_LABEL = Object.fromEntries(STAGES.map((s) => [s.key, s.label]));

function emptyStages() {
  return STAGES.map((s) => ({
    ...s,
    status: "pending", // pending | running | done | error
    durationMs: null,
    info: null,
    startedAt: null,
  }));
}

function fmt(ms) {
  if (ms == null) return "—";
  if (ms < 1000) return `${ms} ms`;
  return `${(ms / 1000).toFixed(1)} s`;
}

function StageIcon({ status }) {
  if (status === "running") return <Loader2 size={18} className="spin" aria-hidden="true" />;
  if (status === "done") return <CheckCircle2 size={18} aria-hidden="true" />;
  if (status === "error") return <XCircle size={18} aria-hidden="true" />;
  return <Clock3 size={18} aria-hidden="true" />;
}

export default function PipelineMonitor() {
  const [selected, setSelected] = useState(null);
  const [stages, setStages] = useState(emptyStages);
  const [runState, setRunState] = useState("idle"); // idle | running | done | error
  const [message, setMessage] = useState("Nhập tên nhà hàng rồi bấm Run để xem tiến trình.");
  const [report, setReport] = useState(null);
  const [now, setNow] = useState(Date.now());

  const sourceRef = useRef(null);
  const doneRef = useRef(false);

  // Tick a clock so the running stage shows a live elapsed timer.
  useEffect(() => {
    if (runState !== "running") return undefined;
    const id = setInterval(() => setNow(Date.now()), 100);
    return () => clearInterval(id);
  }, [runState]);

  // Clean up the SSE connection on unmount.
  useEffect(() => () => sourceRef.current?.close(), []);

  const totalMs = useMemo(
    () => stages.reduce((sum, s) => sum + (s.durationMs ?? 0), 0),
    [stages],
  );
  const maxMs = useMemo(
    () => Math.max(1, ...stages.map((s) => s.durationMs ?? 0)),
    [stages],
  );
  const slowest = useMemo(() => {
    const done = stages.filter((s) => s.durationMs != null);
    if (!done.length) return null;
    return done.reduce((a, b) => (b.durationMs > a.durationMs ? b : a));
  }, [stages]);

  function handleEvent(evt) {
    if (evt.type === "stage_start") {
      setStages((prev) =>
        prev.map((s) =>
          s.key === evt.stage ? { ...s, status: "running", startedAt: Date.now() } : s,
        ),
      );
      setMessage(`Đang chạy: ${STAGE_LABEL[evt.stage] ?? evt.stage}…`);
    } else if (evt.type === "stage_end") {
      setStages((prev) =>
        prev.map((s) =>
          s.key === evt.stage
            ? { ...s, status: "done", durationMs: evt.duration_ms, info: evt.info ?? s.info }
            : s,
        ),
      );
    } else if (evt.type === "done") {
      doneRef.current = true;
      setReport(evt.report ?? null);
      setRunState("done");
      setMessage("Hoàn tất. Xem bước chậm nhất bên dưới.");
      sourceRef.current?.close();
    } else if (evt.type === "error") {
      doneRef.current = true;
      setStages((prev) =>
        prev.map((s) =>
          s.key === evt.stage ? { ...s, status: "error", info: evt.detail } : s,
        ),
      );
      setRunState("error");
      setMessage(evt.detail || "Pipeline lỗi.");
      sourceRef.current?.close();
    }
  }

  function handleRun(event) {
    event.preventDefault();
    if (runState === "running" || !selected) return;

    sourceRef.current?.close();
    doneRef.current = false;
    setStages(emptyStages());
    setReport(null);
    setRunState("running");
    setMessage("Đang kết nối tới pipeline…");

    sourceRef.current = streamReport(selected.name, {
      businessId: selected.business_id,
      onEvent: handleEvent,
      onError: () => {
        if (doneRef.current) return; // normal close after done/error
        setRunState("error");
        setMessage("Mất kết nối tới server (kiểm tra backend đã chạy chưa).");
      },
    });
  }

  return (
    <main className="app-shell">
      <header className="topbar">
        <div>
          <h1>Pipeline Monitor</h1>
          <p>Theo dõi từng bước xử lý & thời gian để tìm bước chậm nhất</p>
        </div>
      </header>

      <section className="panel" style={{ marginBottom: 18 }}>
        <div className="section-title">
          <h2>1. Chọn nhà hàng</h2>
          <span>tìm theo tên, chọn từ kết quả gần nhất</span>
        </div>
        <BusinessPicker
          selectedId={selected?.business_id}
          onSelect={setSelected}
        />

        <div className="run-bar">
          <div className="run-bar__sel">
            {selected ? (
              <>
                <CheckCircle2 size={18} aria-hidden="true" />
                <div>
                  <strong>{selected.name}</strong>
                  <span>
                    <MapPin size={13} aria-hidden="true" />{" "}
                    {[selected.address, selected.city, selected.state]
                      .filter(Boolean)
                      .join(", ") || "—"}{" "}
                    · {selected.review_count} reviews
                  </span>
                </div>
              </>
            ) : (
              <span className="run-bar__hint">Chưa chọn nhà hàng nào.</span>
            )}
          </div>
          <button
            type="button"
            className="run-bar__btn"
            onClick={handleRun}
            disabled={!selected || runState === "running"}
          >
            <Play size={16} aria-hidden="true" />
            {runState === "running" ? "Running…" : "Run pipeline"}
          </button>
        </div>
      </section>

      <section className={`api-note api-note--${runState === "error" ? "error" : "ok"}`}>
        {runState === "error" ? <XCircle size={18} /> : <CheckCircle2 size={18} />}
        <span>{message}</span>
      </section>

      <section className="kpi-grid kpi-grid--mon">
        <div className="kpi-card">
          <div className="kpi-card__icon"><TimerReset size={18} /></div>
          <div>
            <p>Tổng thời gian</p>
            <strong>{fmt(totalMs)}</strong>
            <span>cộng dồn tất cả các bước</span>
          </div>
        </div>
        <div className="kpi-card">
          <div className="kpi-card__icon"><Clock3 size={18} /></div>
          <div>
            <p>Bước chậm nhất</p>
            <strong>{slowest ? slowest.label : "—"}</strong>
            <span>{slowest ? fmt(slowest.durationMs) : "chưa có dữ liệu"}</span>
          </div>
        </div>
        <div className="kpi-card">
          <div className="kpi-card__icon"><CheckCircle2 size={18} /></div>
          <div>
            <p>Tiến độ</p>
            <strong>
              {stages.filter((s) => s.status === "done").length}/{STAGES.length}
            </strong>
            <span>bước đã hoàn tất</span>
          </div>
        </div>
      </section>

      <section className="panel">
        <div className="section-title">
          <h2>Các bước xử lý</h2>
          <span>thời lượng theo tỉ lệ với bước chậm nhất</span>
        </div>

        <div className="stage-list">
          {stages.map((s) => {
            const isRunning = s.status === "running";
            const liveMs = isRunning && s.startedAt ? now - s.startedAt : null;
            const shown = s.durationMs ?? liveMs;
            const barPct = s.durationMs != null ? (s.durationMs / maxMs) * 100 : isRunning ? 100 : 0;
            const isSlowest = slowest && s.key === slowest.key && s.durationMs != null;

            return (
              <article
                key={s.key}
                className={`stage-row stage-row--${s.status}${isSlowest ? " stage-row--slow" : ""}`}
              >
                <div className="stage-row__icon"><StageIcon status={s.status} /></div>
                <div className="stage-row__main">
                  <div className="stage-row__head">
                    <h3>{s.label}</h3>
                    {isSlowest ? <span className="stage-tag">chậm nhất</span> : null}
                  </div>
                  <p>{s.info ?? s.hint}</p>
                  <div className="stage-row__bar">
                    <i
                      className={`stage-row__fill stage-row__fill--${s.status}`}
                      style={{ width: `${barPct}%` }}
                    />
                  </div>
                </div>
                <div className="stage-row__time">{fmt(shown)}</div>
              </article>
            );
          })}
        </div>
      </section>

      {report ? (
        <section className="panel panel--muted" style={{ marginTop: 18 }}>
          <div className="section-title">
            <h2>Kết quả</h2>
            <span>{report.business_name}</span>
          </div>
          <p style={{ margin: 0, lineHeight: 1.6, color: "#344249" }}>
            <strong>{report.sample_size}</strong> reviews · {report.executive_summary}
          </p>
        </section>
      ) : null}
    </main>
  );
}
