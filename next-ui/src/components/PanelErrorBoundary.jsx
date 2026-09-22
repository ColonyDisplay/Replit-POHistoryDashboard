"use client";

import { Component } from "react";

export default class PanelErrorBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { failed: false };
  }

  static getDerivedStateFromError() {
    return { failed: true };
  }

  render() {
    if (this.state.failed) {
      return (
        <div className="kpi-state kpi-state-error" role="alert">
          <strong>Operations KPI could not be displayed.</strong>
          <span>The rest of the dashboard is still available. Reload this page to try again.</span>
          <button type="button" onClick={() => window.location.reload()}>Reload</button>
        </div>
      );
    }
    return this.props.children;
  }
}