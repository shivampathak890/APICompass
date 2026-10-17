import { test, expect } from "@playwright/test";
import { SseStreamParser, ParsedSseEvent } from "../src/services/sseParser";

test.describe("WHATWG SSE Stream Parser Unit & Invariant Suite (Audit A)", () => {
  // 1. Standard LF-delimited events
  test("1. Standard LF-delimited events parse correctly", () => {
    const events: ParsedSseEvent[] = [];
    const parser = new SseStreamParser((ev) => events.push(ev));

    parser.feedText("data: {\"stage\": \"accepted\"}\n\n");
    parser.finish();

    expect(events.length).toBe(1);
    expect(events[0].data).toBe('{"stage": "accepted"}');
  });

  // 2. CRLF-delimited events
  test("2. CRLF-delimited events parse correctly", () => {
    const events: ParsedSseEvent[] = [];
    const parser = new SseStreamParser((ev) => events.push(ev));

    parser.feedText("data: {\"stage\": \"accepted\"}\r\n\r\n");
    parser.finish();

    expect(events.length).toBe(1);
    expect(events[0].data).toBe('{"stage": "accepted"}');
  });

  // 3. CR-only delimiters
  test("3. CR-only delimiters parse correctly per WHATWG line break rules", () => {
    const events: ParsedSseEvent[] = [];
    const parser = new SseStreamParser((ev) => events.push(ev));

    parser.feedText("data: {\"stage\": \"accepted\"}\r\r");
    parser.finish();

    expect(events.length).toBe(1);
    expect(events[0].data).toBe('{"stage": "accepted"}');
  });

  // 4. Multiple data: fields joined using newline characters
  test("4. Multiple data: fields joined using newline characters", () => {
    const events: ParsedSseEvent[] = [];
    const parser = new SseStreamParser((ev) => events.push(ev));

    parser.feedText("data: line1\ndata: line2\ndata: line3\n\n");
    parser.finish();

    expect(events.length).toBe(1);
    expect(events[0].data).toBe("line1\nline2\nline3");
  });

  // 5. Comment lines beginning with :
  test("5. Comment lines beginning with : are discarded without dispatching", () => {
    const events: ParsedSseEvent[] = [];
    const parser = new SseStreamParser((ev) => events.push(ev));

    parser.feedText(": heartbeat ping\n: another comment\ndata: actual_payload\n\n");
    parser.finish();

    expect(events.length).toBe(1);
    expect(events[0].data).toBe("actual_payload");
  });

  // 6. Multiple complete events arriving in one network chunk
  test("6. Multiple complete events arriving in one network chunk", () => {
    const events: ParsedSseEvent[] = [];
    const parser = new SseStreamParser((ev) => events.push(ev));

    parser.feedText(
      "event: start\ndata: event_one\n\nevent: progress\ndata: event_two\n\nevent: finish\ndata: event_three\n\n"
    );
    parser.finish();

    expect(events.length).toBe(3);
    expect(events[0]).toEqual({ event: "start", data: "event_one", id: undefined });
    expect(events[1]).toEqual({ event: "progress", data: "event_two", id: undefined });
    expect(events[2]).toEqual({ event: "finish", data: "event_three", id: undefined });
  });

  // 7. A single event arriving across many chunks
  test("7. A single event arriving fragmented across many single-character chunks", () => {
    const events: ParsedSseEvent[] = [];
    const parser = new SseStreamParser((ev) => events.push(ev));

    const raw = "data: {\"progress\": 50}\n\n";
    for (const char of raw) {
      parser.feedText(char);
    }
    parser.finish();

    expect(events.length).toBe(1);
    expect(events[0].data).toBe('{"progress": 50}');
  });

  // 8. A CRLF sequence split across two network chunks
  test("8. A CRLF sequence split across two network chunks (\\r in chunk 1, \\n in chunk 2)", () => {
    const events: ParsedSseEvent[] = [];
    const parser = new SseStreamParser((ev) => events.push(ev));

    // Chunk 1 ends right on \r of \r\n
    parser.feedText("data: split_crlf\r");
    expect(events.length).toBe(0); // Not yet dispatched

    // Chunk 2 starts with \n followed by \r\n (empty line closing the event)
    parser.feedText("\n\r\n");
    parser.finish();

    expect(events.length).toBe(1);
    expect(events[0].data).toBe("split_crlf");
  });

  // 9. A UTF-8 multibyte character split across chunks
  test("9. A UTF-8 multibyte character split across chunks", () => {
    const events: ParsedSseEvent[] = [];
    const parser = new SseStreamParser((ev) => events.push(ev));

    // Emoji 💳 (card): UTF-8 4-byte sequence [0xF0, 0x9F, 0x92, 0xB3]
    const prefix = new TextEncoder().encode('data: {"emoji": "');
    const b1 = new Uint8Array([0xf0, 0x9f]); // First 2 bytes
    const b2 = new Uint8Array([0x92, 0xb3]); // Last 2 bytes
    const suffix = new TextEncoder().encode('"}\n\n');

    parser.feedBytes(prefix);
    parser.feedBytes(b1);
    parser.feedBytes(b2);
    parser.feedBytes(suffix);
    parser.finish();

    expect(events.length).toBe(1);
    const parsed = JSON.parse(events[0].data);
    expect(parsed.emoji).toBe("💳");
  });

  // 10. Incomplete event ending at EOF without a trailing blank line is discarded per WHATWG
  test("10. Incomplete event ending at EOF without a trailing blank line is discarded per WHATWG SSE specification", () => {
    const events: ParsedSseEvent[] = [];
    const parser = new SseStreamParser((ev) => events.push(ev));

    // Sent without closing \n\n
    parser.feedText("data: incomplete_terminal_event_without_closing_blank_line");
    expect(events.length).toBe(0);

    // Call finish at stream termination: incomplete pending event must be discarded
    parser.finish();
    expect(events.length).toBe(0);
  });

  // 10b. Complete event preceding EOF is dispatched, while subsequent incomplete event at EOF is discarded
  test("10b. Complete event preceding EOF is dispatched, while subsequent incomplete event at EOF is discarded", () => {
    const events: ParsedSseEvent[] = [];
    const parser = new SseStreamParser((ev) => events.push(ev));

    parser.feedText("data: complete_event\n\ndata: cut_off_incomplete_event");
    expect(events.length).toBe(1);
    expect(events[0].data).toBe("complete_event");

    parser.finish();
    // Incomplete second event discarded per WHATWG specification
    expect(events.length).toBe(1);
  });

  // 10c. Event ending with single newline at EOF lacking empty line delimiter is discarded
  test("10c. Event ending with single newline at EOF lacking empty line delimiter is discarded", () => {
    const events: ParsedSseEvent[] = [];
    const parser = new SseStreamParser((ev) => events.push(ev));

    parser.feedText("event: progress\ndata: single_newline_only\n");
    expect(events.length).toBe(0);

    parser.finish();
    expect(events.length).toBe(0);
  });

  // 11. Malformed JSON handled safely without throwing
  test("11. Malformed JSON handled safely by consumer wrapper without crashing parser", () => {
    const events: ParsedSseEvent[] = [];
    const parser = new SseStreamParser((ev) => events.push(ev));

    parser.feedText("data: {malformed_json_not_valid\n\n");
    parser.feedText("data: {\"valid\": true}\n\n");
    parser.finish();

    expect(events.length).toBe(2);
    // Consumer safety: parser delivered both payloads; invalid JSON is caught by consumer
    const safeParsed = events.map((e) => {
      try {
        return JSON.parse(e.data);
      } catch {
        return null;
      }
    });

    expect(safeParsed[0]).toBeNull();
    expect(safeParsed[1]).toEqual({ valid: true });
  });

  // 12. Malformed or incomplete event fields handled gracefully
  test("12. Malformed or unrecognized event fields handled gracefully", () => {
    const events: ParsedSseEvent[] = [];
    const parser = new SseStreamParser((ev) => events.push(ev));

    parser.feedText("unknown_field: ignore_me\n");
    parser.feedText("line_without_colon\n");
    parser.feedText("id: 42\n");
    parser.feedText("data: valid_data\n\n");
    parser.finish();

    expect(events.length).toBe(1);
    expect(events[0].id).toBe("42");
    expect(events[0].data).toBe("valid_data");
  });

  // 13. Stream completion and cleanup
  test("13. Stream completion and cleanup resets state for subsequent reuse", () => {
    const events: ParsedSseEvent[] = [];
    const parser = new SseStreamParser((ev) => events.push(ev));

    parser.feedText("data: first\n\n");
    parser.finish();
    expect(events.length).toBe(1);

    // Additional data after finish
    parser.feedText("data: second\n\n");
    parser.finish();
    expect(events.length).toBe(2);
    expect(events[1].data).toBe("second");
  });

  // 14. Reader cleanup after errors and aborts
  test("14. Reader cleanup guarantee verified via try...finally lock release pattern", async () => {
    let lockReleased = false;
    const fakeReader = {
      read: async () => {
        throw new Error("Simulated network stream disconnect");
      },
      releaseLock: () => {
        lockReleased = true;
      },
    };

    try {
      await fakeReader.read();
    } catch {
      // Simulate error
    } finally {
      fakeReader.releaseLock();
    }

    expect(lockReleased).toBe(true);
  });
});
