import React from "react";
import { createRoot } from "react-dom/client";
import App from "../../next-ui/src/components/App";
import { setAuthTokenGetter } from "../../next-ui/src/components/api";

setAuthTokenGetter(async () => "ui-test-token");

const params = new URLSearchParams(window.location.search);
const page = params.get("page") === "datalake" ? "datalake" : "home";
const previewMode = params.get("preview") === "1";

createRoot(document.getElementById("root")).render(
  <App initialPage={page} previewMode={previewMode} />,
);