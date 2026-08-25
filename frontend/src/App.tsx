import { Route, Routes } from "react-router-dom";
import NavBar from "./components/NavBar";
import Dashboard from "./pages/Dashboard";
import ProspectsList from "./pages/ProspectsList";
import ProspectDetail from "./pages/ProspectDetail";
import ReviewQueue from "./pages/ReviewQueue";
import Disqualified from "./pages/Disqualified";

export default function App() {
  return (
    <div className="min-h-screen bg-slate-50">
      <NavBar />
      <main>
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/prospects" element={<ProspectsList />} />
          <Route path="/prospects/:id" element={<ProspectDetail />} />
          <Route path="/review-queue" element={<ReviewQueue />} />
          <Route path="/disqualified" element={<Disqualified />} />
          <Route
            path="*"
            element={
              <div className="mx-auto max-w-4xl px-4 py-10 text-center text-slate-500">
                Page not found.
              </div>
            }
          />
        </Routes>
      </main>
    </div>
  );
}
