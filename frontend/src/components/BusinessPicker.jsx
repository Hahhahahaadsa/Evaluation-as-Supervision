import { useState } from "react";
import { CheckCircle2, Loader2, MapPin, MessageSquare, Search } from "lucide-react";
import { searchBusinesses } from "../api/client.js";

/**
 * Type a name -> Search -> pick from the closest fuzzy matches.
 * Calls `onSelect(business)` with the chosen business object.
 */
export default function BusinessPicker({ selectedId, onSelect, defaultName = "" }) {
  const [query, setQuery] = useState(defaultName);
  const [results, setResults] = useState([]);
  const [state, setState] = useState("idle"); // idle | loading | done | empty | error
  const [message, setMessage] = useState("");

  async function handleSearch(event) {
    event.preventDefault();
    const name = query.trim();
    if (!name) return;

    setState("loading");
    setMessage("Đang tìm…");
    try {
      const matches = await searchBusinesses(name, 5);
      setResults(matches);
      if (!matches.length) {
        setState("empty");
        setMessage("Không tìm thấy nhà hàng khớp.");
      } else {
        setState("done");
        setMessage(`${matches.length} kết quả gần đúng nhất — chọn một để tiếp tục.`);
      }
    } catch (error) {
      setState("error");
      setMessage(error instanceof Error ? error.message : "Lỗi tìm kiếm.");
    }
  }

  return (
    <div className="picker">
      <form className="picker__form" onSubmit={handleSearch}>
        <div className="input-shell">
          <Search size={16} aria-hidden="true" />
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Nhập tên nhà hàng…"
            aria-label="Restaurant name"
          />
        </div>
        <button type="submit" disabled={state === "loading"}>
          {state === "loading" ? (
            <Loader2 size={16} className="spin" aria-hidden="true" />
          ) : (
            <Search size={16} aria-hidden="true" />
          )}
          Tìm kiếm
        </button>
      </form>

      {message ? <p className="picker__msg">{message}</p> : null}

      {results.length ? (
        <div className="picker__list">
          {results.map((biz) => {
            const active = selectedId === biz.business_id;
            const address =
              [biz.address, biz.city, biz.state].filter(Boolean).join(", ") || "—";
            return (
              <button
                type="button"
                key={biz.business_id}
                className={`biz-card${active ? " biz-card--active" : ""}`}
                onClick={() => onSelect(biz)}
              >
                <div className="biz-card__main">
                  <h3>{biz.name}</h3>
                  <p>
                    <MapPin size={13} aria-hidden="true" /> {address}
                  </p>
                </div>
                <div className="biz-card__meta">
                  <span className="biz-card__reviews">
                    <MessageSquare size={13} aria-hidden="true" /> {biz.review_count}
                  </span>
                  <span className="biz-card__score">{Math.round(biz.score)}%</span>
                  {active ? (
                    <CheckCircle2 size={18} className="biz-card__check" aria-hidden="true" />
                  ) : null}
                </div>
              </button>
            );
          })}
        </div>
      ) : null}
    </div>
  );
}
