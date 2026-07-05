import Link from "next/link";
import { Button } from "@/components/ui/button";
import { env } from "@/env";

/**
 * Landing page. Deliberately a foundation placeholder — not a product screen.
 * It exists to prove the shell (layout, theme, fonts, routing, design tokens)
 * renders end-to-end.
 */
export default function HomePage() {
  return (
    <main className="mx-auto flex min-h-screen max-w-3xl flex-col items-center justify-center gap-6 px-6 text-center">
      <span className="text-muted-foreground rounded-full border px-3 py-1 text-xs font-medium">
        Engineering Foundation · v0.1.0 · {env.NEXT_PUBLIC_APP_ENV}
      </span>
      <h1 className="text-4xl font-bold tracking-tight sm:text-5xl">SATRAK</h1>
      <p className="text-muted-foreground max-w-xl text-balance">
        AI-Powered Government Urban Compliance Intelligence Platform. This is the engineering
        skeleton — application modules plug in from here.
      </p>
      <div className="flex gap-3">
        <Button asChild>
          <Link href="/system">System status</Link>
        </Button>
        <Button asChild variant="outline">
          <a href={`${env.NEXT_PUBLIC_API_URL}/docs`} target="_blank" rel="noreferrer">
            API docs
          </a>
        </Button>
      </div>
    </main>
  );
}
