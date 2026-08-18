const API_BASE_URL = import.meta.env?.VITE_API_BASE_URL ?? "http://localhost:8000";

/** Fuzzy-search businesses by name. Returns [] when nothing matches. */
export async function searchBusinesses(name, topN = 5) {
  const url = `${API_BASE_URL}/api/businesses/search?name=${encodeURIComponent(
    name,
  )}&top_n=${topN}`;
  const response = await fetch(url);
  if (response.status === 404) return [];
  if (!response.ok) {
    throw new Error(`Search failed: ${response.status}`);
  }
  return response.json();
}

export async function createReport(payload) {
  const response = await fetch(`${API_BASE_URL}/api/reports`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });

  if (!response.ok) {
    throw new Error(`Report request failed: ${response.status}`);
  }

  return response.json();
}

/**
 * Stream live pipeline progress via Server-Sent Events.
 * Returns the EventSource so the caller can close it.
 * `onEvent` receives each parsed event object ({ type, stage, duration_ms, ... }).
 */
export function streamReport(restaurantName, { businessId, onEvent, onError } = {}) {
  let url = `${API_BASE_URL}/api/reports/stream?restaurant_name=${encodeURIComponent(
    restaurantName,
  )}`;
  if (businessId) {
    url += `&business_id=${encodeURIComponent(businessId)}`;
  }
  const source = new EventSource(url);

  source.onmessage = (event) => {
    try {
      onEvent?.(JSON.parse(event.data));
    } catch {
      /* ignore malformed event */
    }
  };

  source.onerror = () => {
    onError?.();
    source.close();
  };

  return source;
}

