"use client";

/**
 * Global error boundary — the last line of defense. Catches errors thrown in the
 * root layout itself, so it must render its own <html>/<body>.
 */
export default function GlobalError({ reset }: { error: Error; reset: () => void }) {
  return (
    <html lang="en">
      <body>
        <div
          style={{
            display: "flex",
            minHeight: "100vh",
            alignItems: "center",
            justifyContent: "center",
            flexDirection: "column",
            gap: "1rem",
            fontFamily: "system-ui",
          }}
        >
          <h2>Application error</h2>
          <button onClick={reset}>Reload</button>
        </div>
      </body>
    </html>
  );
}
