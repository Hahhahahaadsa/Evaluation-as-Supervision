import assert from "node:assert/strict";
import test from "node:test";

import { createReport, searchBusinesses, streamReport } from "./client.js";

test("search and report calls preserve the frontend API contract", async (t) => {
  const calls = [];
  t.mock.method(globalThis, "fetch", async (url, options = {}) => {
    calls.push({ url, options });
    return new Response(JSON.stringify({ status: "success" }), {
      headers: { "Content-Type": "application/json" },
    });
  });

  await searchBusinesses("A&B", 3);
  await createReport({ restaurant_name: "A&B", business_id: "b1", sample_size: 2 });

  assert.equal(calls[0].url, "http://localhost:8000/api/businesses/search?name=A%26B&top_n=3");
  assert.equal(calls[1].options.method, "POST");
  assert.deepEqual(JSON.parse(calls[1].options.body), {
    restaurant_name: "A&B",
    business_id: "b1",
    sample_size: 2,
  });
});

test("streamReport parses SSE messages and closes on errors", (t) => {
  class FakeEventSource {
    constructor(url) {
      this.url = url;
    }

    close() {
      this.closed = true;
    }
  }

  globalThis.EventSource = FakeEventSource;
  t.after(() => { delete globalThis.EventSource; });
  const events = [];
  let errored = false;
  const source = streamReport("A&B", {
    businessId: "b/1",
    onEvent: (event) => events.push(event),
    onError: () => { errored = true; },
  });

  source.onmessage({ data: JSON.stringify({ type: "done" }) });
  source.onerror();

  assert.equal(source.url, "http://localhost:8000/api/reports/stream?restaurant_name=A%26B&business_id=b%2F1");
  assert.deepEqual(events, [{ type: "done" }]);
  assert.equal(errored, true);
  assert.equal(source.closed, true);
});
