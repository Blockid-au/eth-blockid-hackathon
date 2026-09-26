import { Suspense } from "react";
import { Route, Routes, useLocation } from "react-router-dom";
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
            <Route path="/new" element={<NewWizard />} />
            <Route path="/v/:id" element={<ValuationPage />} />
            <Route path="/c/:ticker" element={<CompanyPage />} />
            <Route path="/companies" element={<CompaniesPage />} />
            <Route path="/admin" element={<AdminPage />} />
            <Route path="/hsk" element={<HskPage />} />
            <Route path="/verify" element={<VerifyPage />} />
            <Route path="/verify/:ticker" element={<VerifyPage />} />
            <Route path="*" element={<NotFound />} />
          </Routes>
        </Suspense>
        </ErrorBoundary>
      </main>
      <Footer />
    </>
  );
}
