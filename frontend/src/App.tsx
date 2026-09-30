import { useQuery } from "@tanstack/react-query";
import { NavLink, Route, Routes } from "react-router-dom";
import { api } from "./api";
import { SelectionProvider, useSelection } from "./context";
import AnalysisPage from "./pages/AnalysisPage";
import HomePage from "./pages/HomePage";
import ImportPage from "./pages/ImportPage";
import PlanPage from "./pages/PlanPage";
import PricesPage from "./pages/PricesPage";
import ProcurementPage from "./pages/ProcurementPage";

function ContextPicker() {
  const { organisationId, versionId, setOrganisationId, setVersionId } = useSelection();
  const orgs = useQuery({ queryKey: ["organisations"], queryFn: api.organisations });
  const versions = useQuery({
    queryKey: ["versions", organisationId],
    queryFn: () => api.versions(organisationId!),
    enabled: !!organisationId,
  });
  return (
    <div className="context">
      <label>
        Structure
        <select value={organisationId ?? ""} onChange={(e) => setOrganisationId(e.target.value || null)}>
          <option value="">— choisir —</option>
          {orgs.data?.map((o) => (
            <option key={o.id} value={o.id}>
              {o.code} — {o.name}
            </option>
          ))}
        </select>
      </label>
      {organisationId && (
        <label style={{ display: "block", marginTop: 8 }}>
          Version du PTA
          <select value={versionId ?? ""} onChange={(e) => setVersionId(e.target.value || null)}>
            <option value="">— choisir —</option>
            {versions.data?.map((v) => (
              <option key={v.id} value={v.id}>
                {v.label} ({v.status})
              </option>
            ))}
          </select>
        </label>
      )}
    </div>
  );
}

function Shell() {
  return (
    <div className="layout">
      <aside className="sidebar">
        <div className="brand">
          Budget Intelligence Engine
          <small>Planification, PPM et performance</small>
        </div>
        <nav className="nav">
          <NavLink to="/" end>
            Accueil
          </NavLink>
          <div className="section">Programmer</div>
          <NavLink to="/pta">PTA : activités et coûts</NavLink>
          <NavLink to="/import">Importer un PTA</NavLink>
          <div className="section">Contrôler</div>
          <NavLink to="/analyse">Enveloppes et contrôles</NavLink>
          <NavLink to="/ppm">Plan de passation (PPM)</NavLink>
          <div className="section">Référentiels</div>
          <NavLink to="/prix">e-Répertoire des prix</NavLink>
        </nav>
        <ContextPicker />
      </aside>
      <main>
        <Routes>
          <Route path="/" element={<HomePage />} />
          <Route path="/import" element={<ImportPage />} />
          <Route path="/pta" element={<PlanPage />} />
          <Route path="/analyse" element={<AnalysisPage />} />
          <Route path="/ppm" element={<ProcurementPage />} />
          <Route path="/prix" element={<PricesPage />} />
        </Routes>
      </main>
    </div>
  );
}

export default function App() {
  return (
    <SelectionProvider>
      <Shell />
    </SelectionProvider>
  );
}
