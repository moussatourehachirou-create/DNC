import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { useSelection } from "../context";

export default function HomePage() {
  const queryClient = useQueryClient();
  const { organisationId, versionId, setOrganisationId, setVersionId } = useSelection();
  const orgs = useQuery({ queryKey: ["organisations"], queryFn: api.organisations });
  const [code, setCode] = useState("");
  const [name, setName] = useState("");
  const [year, setYear] = useState(new Date().getFullYear() + 1);

  const createOrg = useMutation({
    mutationFn: () => api.createOrganisation({ code, name, kind: "ministere" }),
    onSuccess: (org) => {
      queryClient.invalidateQueries({ queryKey: ["organisations"] });
      setOrganisationId(org.id);
      setCode("");
      setName("");
    },
  });
  const createVersion = useMutation({
    mutationFn: () => api.createVersion(organisationId!, year, `PTA ${year}`),
    onSuccess: (version) => {
      queryClient.invalidateQueries({ queryKey: ["versions", organisationId] });
      setVersionId(version.id);
    },
  });

  return (
    <>
      <h1>Bienvenue dans Budget Intelligence Engine</h1>
      <p className="muted">
        Une donnée saisie une seule fois alimente le PTA, le plan de consommation des crédits et le plan de passation
        des marchés.
      </p>

      <div className="grid kpis" style={{ marginTop: 16 }}>
        <div className="card">
          <strong>1. Choisir ou créer la structure</strong>
          <p className="muted">{orgs.data?.length ?? 0} structure(s) enregistrée(s).</p>
          <div className="row">
            <input placeholder="Code (ex. MESTFP)" value={code} onChange={(e) => setCode(e.target.value)} />
            <input placeholder="Nom" value={name} onChange={(e) => setName(e.target.value)} />
            <button className="primary" disabled={!code || !name} onClick={() => createOrg.mutate()}>
              Créer
            </button>
          </div>
          {createOrg.error && <p className="error">{String(createOrg.error.message)}</p>}
        </div>
        <div className="card">
          <strong>2. Ouvrir un PTA</strong>
          <p className="muted">Importez un PTA Excel existant ou démarrez une version vide.</p>
          <div className="row">
            <Link className="button" to="/import">
              Importer un PTA Excel
            </Link>
            <input type="number" value={year} onChange={(e) => setYear(Number(e.target.value))} style={{ width: 90 }} />
            <button disabled={!organisationId} onClick={() => createVersion.mutate()}>
              Nouvelle version
            </button>
          </div>
        </div>
        <div className="card">
          <strong>3. Programmer et contrôler</strong>
          <p className="muted">Activités, tâches, coûts ; enveloppes ; PPM généré automatiquement.</p>
          <div className="row">
            <Link className="button primary" to="/pta" aria-disabled={!versionId}>
              Ouvrir le PTA
            </Link>
            <Link className="button" to="/ppm">
              Voir le PPM
            </Link>
          </div>
        </div>
      </div>
    </>
  );
}
