import { Suspense } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { Footer, Nav, ScrollManager } from "./components/Layout";
import { ErrorBoundary, PageLoading } from "./components/Boundary";
import { lazyPage as lazy } from "./lib/chunks";
import { Home } from "./pages/Home";
import { NotFound } from "./pages/NotFound";

const NewWizard = lazy(() => import("./pages/NewWizard"));
const ValuationPage = lazy(() => import("./pages/Valuation"));
const CompanyPage = lazy(() => import("./pages/Company"));
const CompaniesPage = lazy(() => import("./pages/Companies"));
const AdminPage = lazy(() => import("./pages/Admin"));
const HskPage = lazy(() => import("./pages/Hsk"));
const VerifyPage = lazy(() => import("./pages/Verify"));
const InvestorPage = lazy(() => import("./pages/Investor"));
const DocsPage = lazy(() => import("./pages/Docs"));

export function App() {
  const { pathname } = useLocation();
  return (
    <>
      <ScrollManager />
      <Nav />
      <main id="main" tabIndex={-1}>
        <ErrorBoundary resetKey={pathname}>
        <Suspense fallback={<PageLoading />}>
          <Routes>
            <Route path="/" element={<Home />} />
            <Route path="/i/:view?/:tk?" element={<InvestorPage />} />
            <Route path="/start" element={<NewWizard />} />
            <Route path="/new" element={<Navigate to="/start" replace />} />
            <Route path="/v/:id/:step?" element={<ValuationPage />} />
            <Route path="/c/:ticker/:section?" element={<CompanyPage />} />
            <Route path="/companies" element={<CompaniesPage />} />
            <Route path="/explore" element={<Navigate to="/companies" replace />} />
            <Route path="/admin/:section?/:item?" element={<AdminPage />} />
            <Route path="/hsk" element={<HskPage />} />
            <Route path="/verify" element={<VerifyPage />} />
            <Route path="/verify/:ticker" element={<VerifyPage />} />
            <Route path="/docs" element={<DocsPage />} />
            <Route path="*" element={<NotFound />} />
          </Routes>
        </Suspense>
        </ErrorBoundary>
      </main>
      <Footer />
    </>
  );
}
