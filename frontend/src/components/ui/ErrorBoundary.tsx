import { Component } from "react";

type Props = { children: React.ReactNode };
type State = { hasError: boolean };

/**
 * App-wide safety net. Any uncaught render error in any route lands here and
 * shows a calm reload card instead of a white screen — so a single bug can
 * never take the whole product down mid-demo. Per-feature boundaries (e.g. the
 * Atlas board cards) handle finer-grained isolation; this is the last line.
 */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false };

  static getDerivedStateFromError(): State {
    return { hasError: true };
  }

  componentDidCatch(error: unknown) {
    // eslint-disable-next-line no-console
    console.error("App error boundary caught:", error);
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="min-h-[100dvh] flex items-center justify-center p-6 bg-surface">
          <div className="max-w-md text-center bg-surface-lowest rounded-2xl ring-1 ring-line/60 shadow-card p-8">
            <h1 className="text-xl font-bold tracking-tight text-ink">Something went wrong</h1>
            <p className="mt-2 text-sm text-text-muted leading-relaxed">
              This screen hit an unexpected error. Reloading usually clears it.
            </p>
            <button
              type="button"
              onClick={() => window.location.reload()}
              className="mt-5 inline-flex items-center justify-center h-11 px-5 rounded-full bg-primary text-white text-sm font-semibold hover:brightness-110 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40 focus-visible:ring-offset-2"
            >
              Reload
            </button>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}
