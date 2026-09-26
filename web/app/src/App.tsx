import { lazy, Suspense } from "react";
import { Route, Routes } from "react-router-dom";
import { Footer, Loading, Nav, ScrollManager } from "./components/Layout";
import { Home } from "./pages/Home";
import { NotFound } from "./pages/NotFound";

const NewWizard = lazy(() => import("./pages/NewWizard"));
const ValuationPage = lazy(() => import("./pages/Valuation"));
const CompanyPage = lazy(() => import("./pages/Company"));
const CompaniesPage = lazy(() => import("./pages/Companies"));
const AdminPage = lazy(() => import("./pages/Admin"));
const HskPage = lazy(() => import("./pages/Hsk"));

export function App() {
  return (
    <>
      <ScrollManager />
      <Nav />
      <main id="main" tabIndex={-1}>
        <Suspense fallback={<Loading />}>
          <Routes>
            <Route path="/" element={<Home />} />
            <Route path="/new" element={<NewWizard />} />
            <Route path="/v/:id" element={<ValuationPage />} />
            <Route path="/c/:ticker" element={<CompanyPage />} />
            <Route path="/companies" element={<CompaniesPage />} />
            <Route path="/admin" element={<AdminPage />} />
            <Route path="/hsk" element={<HskPage />} />
            <Route path="*" element={<NotFound />} />
          </Routes>
        </Suspense>
      </main>
      <Footer />
    </>
  );
}
