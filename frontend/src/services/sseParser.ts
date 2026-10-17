/**
 * Server-Sent Events (SSE) Stream Parser implementing WHATWG SSE specification.
 *
 * Capabilities:
 * - Incremental UTF-8 byte stream decoding with split multi-byte character safety
 * - Normalized line delimiter processing (LF, CRLF, and CR-only)
 * - Safe handling of CRLF sequences split across network chunks
 * - Multi-line 'data:' field concatenation with newline separators
 * - Leading space stripping from field values per WHATWG specification
 * - Comment line discarding (':')
 * - EOF flushing without requiring a trailing blank line
 * - Safe handling of malformed fields and payloads
 */

export interface ParsedSseEvent {
  event?: string;
  data: string;
  id?: string;
}

export class SseStreamParser {
  private decoder = new TextDecoder("utf-8");
  private buffer = "";
  private dataLines: string[] = [];
  private currentEventType = "";
  private currentEventId = "";

  constructor(
    private onEvent: (event: ParsedSseEvent) => void
  ) {}

  /**
   * Feed an incoming byte chunk from a ReadableStreamDefaultReader.
   */
  public feedBytes(chunk: Uint8Array): void {
    const text = this.decoder.decode(chunk, { stream: true });
    this.feedText(text);
  }

  /**
   * Feed pre-decoded text chunks into the parser.
   */
  public feedText(text: string): void {
    this.buffer += text;
    this.processBuffer(false);
  }

  /**
   * Flush any remaining bytes from the TextDecoder and process terminal buffer.
   * Per WHATWG SSE specification:
   * "Once the end of the file is reached, any pending data must be discarded.
   * (If the file ends in the middle of an event, before the final empty line,
   * the incomplete event is not dispatched.)"
   */
  public finish(): void {
    const flushed = this.decoder.decode();
    if (flushed) {
      this.buffer += flushed;
    }
    this.processBuffer(true);

    // Discard any incomplete pending event at EOF per WHATWG SSE specification
    this.buffer = "";
    this.dataLines = [];
    this.currentEventType = "";
    this.currentEventId = "";
  }

  /**
   * Scan buffer for line boundaries (\r\n, \n, \r) and dispatch completed lines.
   */
  private processBuffer(isEof: boolean): void {
    let i = 0;
    while (i < this.buffer.length) {
      const ch = this.buffer[i];
      if (ch === "\r") {
        if (i + 1 < this.buffer.length) {
          if (this.buffer[i + 1] === "\n") {
            // CRLF line break
            const line = this.buffer.slice(0, i);
            this.buffer = this.buffer.slice(i + 2);
            i = 0;
            this.handleLine(line);
          } else {
            // CR-only line break
            const line = this.buffer.slice(0, i);
            this.buffer = this.buffer.slice(i + 1);
            i = 0;
            this.handleLine(line);
          }
        } else {
          // \r is at the very end of the buffer
          if (isEof) {
            // At EOF, trailing CR is a line break
            const line = this.buffer.slice(0, i);
            this.buffer = "";
            this.handleLine(line);
          }
          // If not EOF, wait for next chunk to determine if followed by \n
          break;
        }
      } else if (ch === "\n") {
        // LF line break
        const line = this.buffer.slice(0, i);
        this.buffer = this.buffer.slice(i + 1);
        i = 0;
        this.handleLine(line);
      } else {
        i++;
      }
    }

    if (isEof && this.buffer.length > 0) {
      const line = this.buffer;
      this.buffer = "";
      this.handleLine(line);
    }
  }

  /**
   * Process a single line according to WHATWG SSE rules.
   */
  private handleLine(line: string): void {
    // Blank line dispatches accumulated event
    if (line === "") {
      if (this.dataLines.length > 0) {
        this.dispatchEvent();
      }
      return;
    }

    // Comment line
    if (line.startsWith(":")) {
      return;
    }

    // Field processing
    let field: string;
    let value: string;
    const colonIndex = line.indexOf(":");
    if (colonIndex !== -1) {
      field = line.slice(0, colonIndex);
      value = line.slice(colonIndex + 1);
      // Strip single leading space if present
      if (value.startsWith(" ")) {
        value = value.slice(1);
      }
    } else {
      field = line;
      value = "";
    }

    if (field === "data") {
      this.dataLines.push(value);
    } else if (field === "event") {
      this.currentEventType = value;
    } else if (field === "id") {
      this.currentEventId = value;
    }
  }

  /**
   * Dispatch accumulated event to callback and reset state.
   */
  private dispatchEvent(): void {
    const data = this.dataLines.join("\n");
    this.onEvent({
      event: this.currentEventType || undefined,
      data,
      id: this.currentEventId || undefined,
    });
    this.dataLines = [];
    this.currentEventType = "";
    this.currentEventId = "";
  }
}
