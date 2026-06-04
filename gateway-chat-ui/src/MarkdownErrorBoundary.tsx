import { Component, type ErrorInfo, type ReactNode } from "react";

type Props = { text: string; children: ReactNode };
type State = { failed: boolean };

export class MarkdownErrorBoundary extends Component<Props, State> {
  state: State = { failed: false };

  static getDerivedStateFromError(): State {
    return { failed: true };
  }

  componentDidCatch(err: Error, info: ErrorInfo): void {
    console.warn("Markdown render failed:", err.message, info.componentStack);
  }

  componentDidUpdate(prevProps: Props): void {
    if (prevProps.text !== this.props.text && this.state.failed) {
      this.setState({ failed: false });
    }
  }

  render(): ReactNode {
    if (this.state.failed) {
      return (
        <pre className="md-pre md-render-fallback">{this.props.text.replace(/\r\n/g, "\n")}</pre>
      );
    }
    return this.props.children;
  }
}
