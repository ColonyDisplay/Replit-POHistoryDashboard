"use client";
import { useState, useEffect, useCallback } from "react";
import {
  createUser,
  getRoleAccess,
  listUserAccessHistory,
  listUsers,
  updateUser,
} from "./api";

const ACTION_LABELS = {
  user_created: "User created",
  role_changed: "Role changed",
  activated: "Activated",
  deactivated: "Deactivated",
  access_changed: "Role and status changed",
};

function formatAccessState(state, roleAccess) {
  if (!state) return "No prior access";
  const role = roleAccess?.roles.find((entry) => entry.id === state.role);
  return `${role?.label || state.role} · ${state.active ? "Active" : "Deactivated"}`;
}

export default function UsersPage({ meEmail, previewMode = false }) {
  const [users, setUsers] = useState([]);
  const [accessHistory, setAccessHistory] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState(null);
  const [roleAccess, setRoleAccess] = useState(null);
  const [rolesLoading, setRolesLoading] = useState(true);
  const [rolesError, setRolesError] = useState(null);

  const [newEmail, setNewEmail] = useState("");
  const [newName, setNewName] = useState("");
  const [newRole, setNewRole] = useState("");
  const [saving, setSaving] = useState(false);
  const [pendingRoles, setPendingRoles] = useState({});
  const [savingRoleId, setSavingRoleId] = useState(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [nextUsers, nextHistory] = await Promise.all([
        listUsers(),
        listUserAccessHistory(),
      ]);
      setUsers(nextUsers);
      setAccessHistory(nextHistory);
    } catch {
      setError("Could not load users and access history");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const loadRoleAccess = useCallback(async () => {
    setRolesLoading(true);
    setRolesError(null);
    try {
      const data = await getRoleAccess();
      if (!Array.isArray(data?.roles) || !Array.isArray(data?.baselineSections)) {
        throw new Error("Role access metadata is incomplete");
      }
      const roleIds = new Set(data.roles.map((role) => role.id));
      if (!roleIds.has(data.defaultRole)) {
        throw new Error("Role access metadata has no valid default role");
      }
      setRoleAccess(data);
      setNewRole((current) => roleIds.has(current) ? current : data.defaultRole);
    } catch (err) {
      setRoleAccess(null);
      setRolesError(err.message || "Could not load role access metadata");
    } finally {
      setRolesLoading(false);
    }
  }, []);

  useEffect(() => {
    loadRoleAccess();
  }, [loadRoleAccess]);

  const flash = (msg) => {
    setNotice(msg);
    setTimeout(() => setNotice(null), 4000);
  };

  const handleAdd = async (e) => {
    e.preventDefault();
    if (previewMode) return;
    if (!newEmail.trim()) return;
    setSaving(true);
    setError(null);
    try {
      await createUser({ email: newEmail.trim(), name: newName.trim(), role: newRole });
      setNewEmail("");
      setNewName("");
      setNewRole(roleAccess.defaultRole);
      flash("User added");
      await refresh();
    } catch (err) {
      setError(err.message || "Failed to add user");
    } finally {
      setSaving(false);
    }
  };

  const handlePatch = async (id, patch) => {
    if (previewMode) return;
    setError(null);
    try {
      await updateUser(id, patch);
      await refresh();
      return true;
    } catch (err) {
      setError(err.message || "Failed to update user");
      return false;
    }
  };

  const getRole = (roleId) => roleAccess?.roles.find((role) => role.id === roleId);
  const handleRoleChange = (id, role, assignedRole) => {
    if (role === assignedRole) {
      cancelRoleChange(id);
      return;
    }
    setPendingRoles((current) => ({ ...current, [id]: role }));
  };
  const cancelRoleChange = (id) => {
    setPendingRoles((current) => {
      const next = { ...current };
      delete next[id];
      return next;
    });
  };
  const applyRoleChange = async (id) => {
    const role = pendingRoles[id];
    if (!role || previewMode) return;
    setSavingRoleId(id);
    try {
      const updated = await handlePatch(id, { role });
      if (updated) {
        cancelRoleChange(id);
        flash("Role updated");
      }
    } finally {
      setSavingRoleId(null);
    }
  };

  const AccessSummary = ({ roleId, compact = false }) => {
    const role = getRole(roleId);
    if (!role) return null;
    const baselineIds = new Set(roleAccess.baselineSections.map((section) => section.id));
    const adminOnlyIds = new Set(role.adminOnlySections.map((section) => section.id));
    const additionalSections = role.sections.filter((section) => !baselineIds.has(section.id));
    const additionsAreAdminOnly = (
      additionalSections.length > 0
      && additionalSections.every((section) => adminOnlyIds.has(section.id))
    );
    return (
      <div className={`access-summary ${compact ? "access-summary-compact" : ""}`}>
        {!compact && <span className="access-summary-title">Effective access</span>}
        <div className="access-group">
          <span className="access-group-label">Portal baseline</span>
          <div className="access-chip-list">
            {roleAccess.baselineSections.map((section) => <span className="access-chip" key={section.id}>{section.label}</span>)}
          </div>
        </div>
        <div className={`access-group ${additionsAreAdminOnly ? "access-group-admin" : ""}`}>
          <span className="access-group-label">
            {additionsAreAdminOnly ? "Admin-only capabilities" : "Additional capabilities"}
          </span>
          <div className="access-chip-list">
            {additionalSections.map((section) => (
              <span
                className={`access-chip ${adminOnlyIds.has(section.id) ? "access-chip-admin" : "access-chip-role"}`}
                key={section.id}
              >
                {section.label}
              </span>
            ))}
            {additionalSections.length === 0 && <span className="access-none">Baseline access only</span>}
          </div>
        </div>
      </div>
    );
  };

  return (
    <div className="users-page">
      <div className="users-page-heading">
        <div>
          <span className="users-eyebrow">ACCOUNT CONTROL</span>
          <h2>Users &amp; access</h2>
        </div>
        {roleAccess && <span className="role-count">{roleAccess.roles.length} roles available</span>}
      </div>
      <p className="users-intro">
        Add a colonydisplay.com email to grant access. Roles control which
        sections a person can use.
      </p>
      {previewMode && (
        <p className="preview-readonly-notice">
          Preview mode is read-only. No users or roles can be changed here.
        </p>
      )}

      <section className="add-user-panel" aria-label="Add user">
        <form onSubmit={handleAdd} className="add-user-form">
          <label>Email<input type="email" required disabled={previewMode || !roleAccess} placeholder="person@colonydisplay.com" value={newEmail} onChange={(e) => setNewEmail(e.target.value)} /></label>
          <label>Name <span>optional</span><input type="text" disabled={previewMode || !roleAccess} placeholder="Full name" value={newName} onChange={(e) => setNewName(e.target.value)} /></label>
          <label>Role<select disabled={previewMode || !roleAccess || rolesLoading} value={newRole} onChange={(e) => setNewRole(e.target.value)}>
            {roleAccess?.roles.map((role) => <option key={role.id} value={role.id}>{role.label}</option>)}
          </select></label>
          <button type="submit" disabled={previewMode || saving || !roleAccess || !newRole}>{saving ? "Adding…" : "Add user"}</button>
        </form>
        {rolesLoading && <div className="role-metadata-state">Loading role access metadata…</div>}
        {rolesError && <div className="role-metadata-error">Role access metadata is unavailable. User assignment is disabled. <button type="button" onClick={loadRoleAccess}>Retry</button></div>}
        {roleAccess && newRole && <AccessSummary roleId={newRole} />}
      </section>

      {notice && <p style={{ color: "#16a34a", margin: "0 0 0.75rem" }}>{notice}</p>}
      {error && <p className="error" style={{ margin: "0 0 0.75rem" }}>{error}</p>}

      {loading ? (
        <p style={{ color: "#64748b" }}>Loading…</p>
      ) : (
        <>
          <div className="users-table-wrap">
            <table className="users-table">
              <thead>
                <tr>
                  <th>Email</th><th>Name</th><th>Role &amp; effective access</th><th>Status</th><th />
                </tr>
              </thead>
              <tbody>
                {users.map((u) => {
                  const isSelf = u.email === meEmail;
                  const pendingRole = pendingRoles[u.id];
                  const shownRole = pendingRole || u.role;
                  return (
                    <tr key={u.id} className={!u.active ? "user-inactive" : ""}>
                      <td>
                        {u.email}
                        {isSelf && <span className="self-label">You</span>}
                      </td>
                      <td>{u.name || "—"}</td>
                      <td className="user-role-cell">
                        <select
                          value={shownRole}
                          disabled={previewMode || isSelf || !roleAccess || rolesLoading}
                          onChange={(e) => handleRoleChange(u.id, e.target.value, u.role)}
                        >
                          {roleAccess?.roles.map((role) => <option key={role.id} value={role.id}>{role.label}</option>)}
                        </select>
                        {pendingRole && <div className="pending-role-actions"><button type="button" onClick={() => applyRoleChange(u.id)} disabled={savingRoleId === u.id}>{savingRoleId === u.id ? "Applying…" : "Apply role"}</button><button type="button" className="subtle-action" onClick={() => cancelRoleChange(u.id)}>Cancel</button></div>}
                        {roleAccess && <AccessSummary roleId={shownRole} compact />}
                      </td>
                      <td><span className={`status-label ${u.active ? "status-active" : ""}`}>{u.active ? "Active" : "Deactivated"}</span></td>
                      <td>
                        <button
                          type="button"
                          disabled={previewMode || isSelf}
                          onClick={() => handlePatch(u.id, { active: !u.active })}
                          className={u.active ? "deactivate-action" : "reactivate-action"}
                        >
                          {u.active ? "Deactivate" : "Reactivate"}
                        </button>
                      </td>
                    </tr>
                  );
                })}
                {users.length === 0 && (
                  <tr>
                    <td colSpan={5} className="users-empty">
                      No users yet.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>

          <section style={{ marginTop: "2rem" }} aria-labelledby="access-history-heading">
            <h3 id="access-history-heading" style={{ margin: "0 0 0.25rem" }}>
              Access history
            </h3>
            <p style={{ margin: "0 0 0.75rem", color: "#64748b" }}>
              Recent user creation, role, and active-status changes.
            </p>
            <div style={{ overflowX: "auto" }}>
              <table style={{ width: "100%", borderCollapse: "collapse" }}>
                <thead>
                  <tr style={{ textAlign: "left", borderBottom: "2px solid #e2e8f0" }}>
                    <th style={{ padding: "0.5rem" }}>When</th>
                    <th style={{ padding: "0.5rem" }}>Actor</th>
                    <th style={{ padding: "0.5rem" }}>User</th>
                    <th style={{ padding: "0.5rem" }}>Change</th>
                    <th style={{ padding: "0.5rem" }}>Before</th>
                    <th style={{ padding: "0.5rem" }}>After</th>
                  </tr>
                </thead>
                <tbody>
                  {accessHistory.map((entry) => (
                    <tr key={entry.id} style={{ borderBottom: "1px solid #f1f5f9" }}>
                      <td style={{ padding: "0.5rem", whiteSpace: "nowrap" }}>
                        {new Date(entry.changed_at).toLocaleString()}
                      </td>
                      <td style={{ padding: "0.5rem" }}>
                        {entry.actor_label || entry.actor_email || "System"}
                      </td>
                      <td style={{ padding: "0.5rem" }}>{entry.target_email}</td>
                      <td style={{ padding: "0.5rem" }}>
                        {ACTION_LABELS[entry.action] || entry.action}
                      </td>
                      <td style={{ padding: "0.5rem", whiteSpace: "nowrap" }}>
                        {formatAccessState(entry.previous_state, roleAccess)}
                      </td>
                      <td style={{ padding: "0.5rem", whiteSpace: "nowrap" }}>
                        {formatAccessState(entry.resulting_state, roleAccess)}
                      </td>
                    </tr>
                  ))}
                  {accessHistory.length === 0 && (
                    <tr>
                      <td colSpan={6} style={{ padding: "1rem", color: "#64748b" }}>
                        No access changes have been recorded yet.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </section>
        </>
      )}
    </div>
  );
}
