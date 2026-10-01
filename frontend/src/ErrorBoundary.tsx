import { Component, type ReactNode } from 'react'

export class ErrorBoundary extends Component<{ children: ReactNode; label: string }, { error: Error | null }> {
  state = { error: null as Error | null }
  static getDerivedStateFromError(error: Error) { return { error } }
  render() {
    if (this.state.error) {
      return <div className="boundary"><b>{this.props.label} gặp lỗi.</b><code>{this.state.error.message}</code></div>
    }
    return this.props.children
  }
}
