import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { RichText } from "./RichText";

describe("RichText", () => {
  it("renders bold, bullets and paragraphs", () => {
    const html = renderToStaticMarkup(
      <RichText text={"Bought:\n- **SPY** 130 shares\n- **AAPL** 291 shares\n\nDone."} />,
    );
    expect(html).toBe(
      '<div class="rich"><p>Bought:</p><ul><li><strong>SPY</strong> 130 shares</li>' +
        "<li><strong>AAPL</strong> 291 shares</li></ul><p>Done.</p></div>",
    );
  });

  it("never injects HTML from model output", () => {
    const html = renderToStaticMarkup(<RichText text={"<img src=x onerror=alert(1)>"} />);
    expect(html).toContain("&lt;img");
  });
});
