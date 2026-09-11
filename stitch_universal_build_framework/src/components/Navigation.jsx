import React from 'react';
import { useInvestigation } from '../context/InvestigationContext';

export const Navigation = () => {
  const { activeTab, setActiveTab, summary } = useInvestigation();

  const navItems = [
    { id: 'investigate', label: 'Investigate', icon: 'search_insights' },
    { id: 'findings', label: 'Findings', icon: 'rule' },
    { id: 'certificates', label: 'Certificates', icon: 'verified_user' },
    { id: 'cases-reports', label: 'Cases & Reports', icon: 'folder_shared' },
  ];

  return (
    <aside className="fixed left-0 top-0 h-full w-[300px] bg-inverse-surface text-inverse-on-surface z-50 flex flex-col shadow-xl">
      {/* Brand Header */}
      <div className="p-lg mb-xl flex items-center justify-between border-b border-on-surface-variant/20">
        <div
          className="flex items-center gap-md cursor-pointer group"
          onClick={() => setActiveTab('landing')}
          title="Return to Homepage"
        >
          <div className="w-10 h-10 rounded-lg bg-primary-container flex items-center justify-center text-white shadow-md group-hover:scale-105 transition-transform">
            <span className="material-symbols-outlined text-[24px]">hub</span>
          </div>
          <div className="flex flex-col">
            <span className="font-headline-md text-headline-md tracking-tight uppercase text-white font-bold">
              BlockTrace
            </span>
            <span className="text-[10px] text-outline-variant uppercase tracking-widest font-semibold">
              Forensic System
            </span>
          </div>
        </div>
      </div>

      {/* Main Navigation Links */}
      <nav className="flex-1 px-md space-y-base">
        {navItems.map((item) => {
          const isActive = activeTab === item.id;
          return (
            <button
              key={item.id}
              onClick={() => setActiveTab(item.id)}
              className={`w-full flex items-center px-lg py-md rounded-lg transition-all text-left group ${
                isActive
                  ? 'bg-primary text-on-primary shadow-lg font-bold'
                  : 'text-on-surface-variant hover:bg-white/10 hover:text-white font-medium'
              }`}
            >
              <span
                className={`material-symbols-outlined mr-md transition-colors ${
                  isActive ? 'text-white' : 'text-on-surface-variant group-hover:text-white'
                }`}
              >
                {item.icon}
              </span>
              <span className="font-label-caps text-label-caps uppercase tracking-wider flex-1">
                {item.label}
              </span>
              {item.id === 'investigate' && summary.wallets_traced > 0 && (
                <span className={`text-[10px] font-address-md px-2 py-0.5 rounded-full ${
                  isActive ? 'bg-black/30 text-white' : 'bg-white/10 text-on-surface-variant'
                }`}>
                  {summary.wallets_traced}w
                </span>
              )}
            </button>
          );
        })}

        {/* Return to Landing Page Action */}
        <div className="pt-4 mt-4 border-t border-on-surface-variant/20">
          <button
            onClick={() => setActiveTab('landing')}
            className="w-full flex items-center px-lg py-sm rounded-lg text-on-surface-variant/70 hover:bg-white/5 hover:text-white transition-all text-xs group"
          >
            <span className="material-symbols-outlined text-[18px] mr-md text-on-surface-variant/70 group-hover:text-white">
              arrow_back
            </span>
            <span className="font-label-caps uppercase tracking-wider">Product Overview</span>
          </button>
        </div>
      </nav>

      {/* Investigator Profile */}
      <div className="mt-auto p-lg border-t border-on-surface-variant/20 flex items-center gap-md bg-black/10 hover:bg-black/20 transition-colors">
        <div className="w-10 h-10 rounded-full border-2 border-primary bg-surface-variant flex items-center justify-center text-on-surface-variant font-bold text-sm">
          AF
        </div>
        <div className="flex flex-col">
          <span className="font-body-sm text-body-sm text-white font-bold">
            Agent Forensics
          </span>
          <span className="text-[10px] uppercase text-primary-fixed-dim tracking-widest font-bold">
            Level 4 Investigator
          </span>
        </div>
      </div>
    </aside>
  );
};
