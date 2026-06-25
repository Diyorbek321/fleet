import { Component, type ErrorInfo, type ReactNode } from "react";
import { Button } from "@/components/ui/button";
import { logger } from "@/lib/logger";

interface ErrorBoundaryProps {
  children: ReactNode;
}

interface ErrorBoundaryState {
  hasError: boolean;
  error: Error | null;
}

/**
 * Top-level React error boundary.
 *
 * Catches render-time errors anywhere below it and shows a friendly fallback
 * instead of a blank white screen. In development the underlying error message
 * and stack are shown to aid debugging; in production (import.meta.env.PROD)
 * they are hidden so we don't leak internal detail to end users.
 *
 * Note: error boundaries only catch errors thrown during rendering, in
 * lifecycle methods, and in constructors of the tree below them. They do NOT
 * catch errors in event handlers or async code — those are handled at the call
 * site (e.g. via toasts).
 */
export class ErrorBoundary extends Component<
  ErrorBoundaryProps,
  ErrorBoundaryState
> {
  constructor(props: ErrorBoundaryProps) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo): void {
    // Developer diagnostics only; no-ops in production builds.
    logger.error("Uncaught render error:", error, errorInfo);
  }

  private handleReload = (): void => {
    window.location.reload();
  };

  render(): ReactNode {
    if (!this.state.hasError) {
      return this.props.children;
    }

    return (
      <div className="flex min-h-screen w-full flex-col items-center justify-center gap-6 bg-background p-6 text-center">
        <div className="flex flex-col items-center gap-3">
          <div className="flex h-16 w-16 items-center justify-center rounded-full bg-destructive/10 text-3xl">
            ⚠️
          </div>
          <h1 className="text-2xl font-semibold text-foreground">
            Something went wrong
          </h1>
          <p className="max-w-md text-sm text-muted-foreground">
            An unexpected error occurred. Please reload the page. If the problem
            persists, contact your administrator.
          </p>
        </div>

        {!import.meta.env.PROD && this.state.error && (
          <pre className="max-h-64 max-w-2xl overflow-auto rounded-md border border-border bg-muted p-4 text-left text-xs text-destructive">
            {this.state.error.message}
            {"\n\n"}
            {this.state.error.stack}
          </pre>
        )}

        <Button onClick={this.handleReload}>Reload</Button>
      </div>
    );
  }
}
