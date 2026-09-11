import React from 'react';
import { InvestigationProvider, useInvestigation } from './context/InvestigationContext';
import { Navigation } from './components/Navigation';
import { Header } from './components/Header';
import { ToastContainer } from './components/Toast';
import { LandingScreen } from './screens/LandingScreen';
import { InvestigateScreen } from './screens/InvestigateScreen';
import { FindingsScreen } from './screens/FindingsScreen';
import { CertificatesScreen } from './screens/CertificatesScreen';
import { CasesScreen } from './screens/CasesScreen';

const MainLayout = () => {
  const { activeTab } = useInvestigation();

  if (activeTab === 'landing') {
    return (
      <div className="w-full min-h-screen bg-surface">
        <LandingScreen />
        <ToastContainer />
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-surface text-on-surface flex">
      {/* Left Sidebar Navigation */}
      <Navigation />

      {/* Main Content Area */}
      <div className="pl-[300px] w-full flex flex-col min-h-screen">
        <Header />
        <main className="relative pt-16 bg-surface min-h-[calc(100vh-64px)] flex flex-col flex-1">
          {activeTab === 'investigate' && <InvestigateScreen />}
          {activeTab === 'findings' && <FindingsScreen />}
          {activeTab === 'certificates' && <CertificatesScreen />}
          {activeTab === 'cases-reports' && <CasesScreen />}
        </main>
      </div>

      {/* Global Toast Notifications */}
      <ToastContainer />
    </div>
  );
};

export function App() {
  return (
    <InvestigationProvider>
      <MainLayout />
    </InvestigationProvider>
  );
}

export default App;
