import React, { useState, useEffect } from 'react';
import { useInvestigation } from '../context/InvestigationContext';
import { ConfirmModal } from '../components/ConfirmModal';
import {
  fetchSavedCases,
  saveCase,
  loadSavedCase,
  deleteSavedCase,
  getReportUrl,
  getErrorMessage,
} from '../api/client';

export const CasesScreen = () => {
  const {
    edges,
    startWallet,
    summary,
    sanctions,
    refreshGraphAndSummary,
    refreshFindings,
    showToast,
    actionLoading,
    setActionLoading,
  } = useInvestigation();

  const [savedCases, setSavedCases] = useState([]);
  const [isLoadingCases, setIsLoadingCases] = useState(false);
  const [newCaseName, setNewCaseName] = useState('');

  // Confirmation Modals
  const [loadTargetCase, setLoadTargetCase] = useState(null);
  const [deleteTargetCase, setDeleteTargetCase] = useState(null);

  // Load Saved Cases List
  const loadCasesList = async () => {
    setIsLoadingCases(true);
    try {
      const cases = await fetchSavedCases();
      setSavedCases(cases || []);
    } catch (err) {
      console.error(err);
      showToast('Failed to retrieve saved cases', 'error');
    } finally {
      setIsLoadingCases(false);
    }
  };

  useEffect(() => {
    loadCasesList();
  }, []);

  // Handle Save Current Case
  const handleSaveCurrentCase = async (e) => {
    e.preventDefault();
    if (!newCaseName.trim()) {
      showToast('Please enter a case name.', 'warning');
      return;
    }
    if (edges.length === 0) {
      showToast('Nothing to save — the graph is empty.', 'error');
      return;
    }

    setActionLoading(true);
    try {
      showToast(`Saving case "${newCaseName}"...`, 'info');
      await saveCase({
        name: newCaseName.trim(),
        start_wallet: startWallet || undefined,
      });
      showToast(`Case "${newCaseName}" saved successfully!`, 'success');
      setNewCaseName('');
      await loadCasesList();
    } catch (err) {
      console.error(err);
      showToast(getErrorMessage(err), 'error');
    } finally {
      setActionLoading(false);
    }
  };

  // Handle Confirm Load Case
  const handleConfirmLoad = async () => {
    if (!loadTargetCase) return;
    const caseName = loadTargetCase;
    setLoadTargetCase(null);
    setActionLoading(true);

    try {
      showToast(`Loading case "${caseName}"...`, 'info');
      const res = await loadSavedCase(caseName);
      await refreshGraphAndSummary();
      await refreshFindings(res.start_wallet);
      showToast(`Case "${caseName}" loaded successfully (${res.edge_count} edges).`, 'success');
    } catch (err) {
      console.error(err);
      showToast(getErrorMessage(err), 'error');
    } finally {
      setActionLoading(false);
    }
  };

  // Handle Confirm Delete Case
  const handleConfirmDelete = async () => {
    if (!deleteTargetCase) return;
    const caseName = deleteTargetCase;
    setDeleteTargetCase(null);
    setActionLoading(true);

    try {
      showToast(`Deleting case "${caseName}"...`, 'info');
      await deleteSavedCase(caseName);
      showToast(`Case "${caseName}" deleted.`, 'info');
      await loadCasesList();
    } catch (err) {
      console.error(err);
      showToast(getErrorMessage(err), 'error');
    } finally {
      setActionLoading(false);
    }
  };

  return (
    <div className="flex flex-col w-full px-xl py-lg gap-8 max-w-7xl mx-auto">
      {/* Header */}
      <div className="pb-4 border-b border-outline-variant/50">
        <h1 className="font-headline-lg text-3xl font-bold text-on-surface mb-2">
          Cases & Forensic Reports
        </h1>
        <p className="font-body-md text-sm text-on-surface-variant max-w-2xl">
          Archive, restore, and generate official audit-ready documentation for ongoing crypto crime investigations.
        </p>
      </div>

      {/* Investigation Report Card */}
      <section className="flex flex-col gap-3">
        <h2 className="font-headline-md text-xl font-bold text-on-surface flex items-center gap-2">
          <span className="material-symbols-outlined text-primary text-[22px]">description</span>
          <span>Investigation Dossier Report</span>
        </h2>

        <div className="bg-surface-container rounded-2xl shadow-md p-6 flex flex-col md:flex-row items-start md:items-center justify-between gap-6 border border-outline-variant/60 relative overflow-hidden">
          <div className="flex flex-col gap-2 relative z-10">
            <h3 className="font-headline-md text-lg font-bold text-on-surface">
              Active Case Summary Export
            </h3>
            <p className="font-body-md text-xs text-on-surface-variant max-w-2xl leading-relaxed">
              Comprehensive report detailing tracked addresses, heuristic detection breakdown, high-risk sanctions hits, and cryptographic verification status.
            </p>

            <div className="flex items-center gap-3 mt-2">
              <span
                className={`inline-flex items-center gap-1 px-3 py-1 rounded-full font-label-caps text-xs font-bold ${
                  sanctions.length > 0
                    ? 'bg-error/15 text-error border border-error/30'
                    : 'bg-[#e8f5e9] text-[#2e682c]'
                }`}
              >
                <span className="material-symbols-outlined text-[14px]">
                  {sanctions.length > 0 ? 'warning' : 'verified'}
                </span>
                <span>{sanctions.length > 0 ? `${sanctions.length} Sanction Flags` : 'Clean Sanctions'}</span>
              </span>

              <span className="inline-flex items-center gap-1 px-3 py-1 bg-surface text-on-surface rounded-full font-label-caps text-xs font-bold border border-outline-variant/60">
                <span className="material-symbols-outlined text-[14px]">account_tree</span>
                <span>{summary.wallets_traced} Wallets · {summary.transactions_mapped} Txs</span>
              </span>
            </div>
          </div>

          <div className="flex flex-col sm:flex-row gap-3 relative z-10 shrink-0">
            <a
              href={getReportUrl(startWallet)}
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center justify-center gap-2 px-6 py-3 bg-primary text-white hover:bg-primary-container transition-all font-label-caps text-xs uppercase rounded-xl shadow-md hover:shadow-lg font-bold"
            >
              <span className="material-symbols-outlined text-[18px]">download</span>
              <span>Download PDF Report</span>
            </a>
          </div>
        </div>
      </section>

      {/* Saved Investigation Cases Section */}
      <section className="flex flex-col gap-4 mt-4">
        <div className="flex flex-col md:flex-row items-start md:items-center justify-between gap-4">
          <div className="flex items-center gap-2">
            <h2 className="font-headline-md text-xl font-bold text-on-surface flex items-center gap-2">
              <span className="material-symbols-outlined text-tertiary text-[22px]">folder_shared</span>
              <span>Saved Investigation Cases</span>
            </h2>
            <span className="bg-surface-variant text-on-surface-variant px-2.5 py-0.5 rounded-full font-label-caps text-[10px] font-bold">
              {savedCases.length} TOTAL
            </span>
          </div>

          {/* Save Current Case Form */}
          <form onSubmit={handleSaveCurrentCase} className="flex items-center gap-2 w-full md:w-auto">
            <input
              type="text"
              value={newCaseName}
              onChange={(e) => setNewCaseName(e.target.value)}
              placeholder="Enter case name..."
              className="bg-surface text-on-surface border border-outline-variant focus:ring-1 focus:ring-primary text-xs px-3.5 py-2 rounded-lg outline-none w-full md:w-64 font-medium shadow-xs"
            />
            <button
              type="submit"
              disabled={actionLoading || edges.length === 0}
              className="flex items-center gap-1.5 px-4 py-2 bg-primary text-white hover:bg-primary-container transition-colors font-label-caps text-xs uppercase rounded-lg shadow-sm whitespace-nowrap font-bold disabled:opacity-50"
            >
              <span className="material-symbols-outlined text-[16px]">save</span>
              <span>Save Case</span>
            </button>
          </form>
        </div>

        {/* Data Table */}
        <div className="bg-surface rounded-2xl shadow-md border border-outline-variant/60 overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-left border-collapse">
              <thead>
                <tr className="bg-surface-container text-on-surface-variant border-b border-outline-variant font-label-caps text-[11px] uppercase tracking-wider">
                  <th className="p-4 font-bold w-1/3">Case Name</th>
                  <th className="p-4 font-bold">Date Saved</th>
                  <th className="p-4 font-bold">Transactions / Edges</th>
                  <th className="p-4 font-bold text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="font-body-sm text-xs text-on-surface divide-y divide-outline-variant/40">
                {isLoadingCases ? (
                  <tr>
                    <td colSpan="4" className="p-8 text-center text-on-surface-variant">
                      <div className="inline-flex items-center gap-2">
                        <div className="w-4 h-4 border-2 border-primary border-t-transparent rounded-full animate-spin" />
                        <span>Loading cases...</span>
                      </div>
                    </td>
                  </tr>
                ) : savedCases.length === 0 ? (
                  <tr>
                    <td colSpan="4" className="p-8 text-center text-on-surface-variant italic">
                      No saved investigation cases found. Enter a name above to save the current session.
                    </td>
                  </tr>
                ) : (
                  savedCases.map((c) => (
                    <tr
                      key={c.name}
                      className="hover:bg-surface-container-low transition-colors group"
                    >
                      <td className="p-4 font-semibold text-on-surface">
                        <div className="flex items-center gap-2.5">
                          <span className="material-symbols-outlined text-primary text-[18px]">
                            folder_open
                          </span>
                          <span>{c.name}</span>
                        </div>
                      </td>
                      <td className="p-4 text-on-surface-variant font-address-md text-[11px]">
                        {c.saved_at || 'Recently Saved'}
                      </td>
                      <td className="p-4 font-address-md font-mono text-on-surface-variant">
                        {c.edge_count} edges
                      </td>
                      <td className="p-4 text-right">
                        <div className="flex items-center justify-end gap-2">
                          <button
                            onClick={() => setLoadTargetCase(c.name)}
                            className="px-3 py-1 rounded bg-surface hover:bg-primary/10 text-primary border border-primary/40 font-label-caps text-[10px] uppercase font-bold transition-colors flex items-center gap-1"
                            title="Load this case into workspace"
                          >
                            <span className="material-symbols-outlined text-[14px]">file_open</span>
                            <span>Load</span>
                          </button>
                          <button
                            onClick={() => setDeleteTargetCase(c.name)}
                            className="p-1.5 text-error/70 hover:text-error hover:bg-error/10 rounded transition-colors"
                            title="Delete Case"
                          >
                            <span className="material-symbols-outlined text-[18px]">delete</span>
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>
      </section>

      {/* Confirmation Modal for Loading Case */}
      <ConfirmModal
        isOpen={!!loadTargetCase}
        title={`Load Case "${loadTargetCase}"?`}
        message="Loading this case will replace the entire current transaction graph and analysis session. Make sure you have saved any current work."
        confirmText="Load Case"
        confirmVariant="primary"
        onConfirm={handleConfirmLoad}
        onCancel={() => setLoadTargetCase(null)}
      />

      {/* Confirmation Modal for Deleting Case */}
      <ConfirmModal
        isOpen={!!deleteTargetCase}
        title={`Delete Case "${deleteTargetCase}"?`}
        message="Are you sure you want to permanently delete this saved investigation case? This cannot be undone."
        confirmText="Delete Case"
        confirmVariant="danger"
        onConfirm={handleConfirmDelete}
        onCancel={() => setDeleteTargetCase(null)}
      />
    </div>
  );
};
