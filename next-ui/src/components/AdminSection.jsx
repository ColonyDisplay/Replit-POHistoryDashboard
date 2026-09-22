"use client";

import { useState } from "react";
import UsersPage from "./UsersPage";

const ADMIN_PAGES = [
  {
    id: "users",
    label: "Users & access",
    description: "Manage company accounts, roles, and active status.",
  },
];

export default function AdminSection({ meEmail, previewMode = false }) {
  const [currentPage, setCurrentPage] = useState(ADMIN_PAGES[0].id);

  return (
    <main className="admin-section">
      <aside className="admin-section-sidebar">
        <span className="admin-section-kicker">ADMINISTRATION</span>
        <h2>Admin</h2>
        <p>Manage access and other administrative settings.</p>
        <nav className="admin-section-nav" aria-label="Admin pages">
          {ADMIN_PAGES.map((page) => (
            <button
              key={page.id}
              type="button"
              className={`admin-nav-item ${currentPage === page.id ? "active" : ""}`}
              onClick={() => setCurrentPage(page.id)}
              aria-current={currentPage === page.id ? "page" : undefined}
            >
              <strong>{page.label}</strong>
              <span>{page.description}</span>
            </button>
          ))}
        </nav>
      </aside>
      <section
        className="admin-section-content"
        aria-label="Administrative page content"
      >
        {currentPage === "users" && (
          <UsersPage meEmail={meEmail} previewMode={previewMode} />
        )}
      </section>
    </main>
  );
}