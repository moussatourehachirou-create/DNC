import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api, fcfa } from "../api";

export default function PricesPage() {
  const [q, setQ] = useState("");
  const hits = useQuery({ queryKey: ["prices", q], queryFn: () => api.searchPrices(q), enabled: q.length >= 3 });
  const load = useMutation({ mutationFn: api.loadBundledPrices });

  return (
    <>
      <h1>e-Répertoire des prix de référence</h1>
      <p className="muted">
        Référentiel de BIE construit à partir des éditions publiées par le ministère des Finances. Chaque article porte
        une fourchette (BI – BS) et sa nature économique (premier segment du code).
      </p>
      <div className="row" style={{ margin: "12px 0" }}>
        <button onClick={() => load.mutate()} disabled={load.isPending}>
          {load.isPending ? "Chargement…" : "Charger l'édition v26.3 livrée"}
        </button>
        {load.data && (
          <span className="badge ok">
            {load.data.items} articles chargés — {load.data.label}
          </span>
        )}
        {load.error && <span className="error">{load.error.message}</span>}
      </div>
      <input
        placeholder="Rechercher un article (3 lettres minimum)"
        value={q}
        onChange={(e) => setQ(e.target.value)}
        style={{ width: "100%", maxWidth: 520 }}
      />
      {hits.data && (
        <div className="table-wrap" style={{ marginTop: 12 }}>
          <table>
            <thead>
              <tr>
                <th>Code</th>
                <th>Désignation</th>
                <th>Unité</th>
                <th className="num">BI</th>
                <th className="num">BS</th>
                <th>Nature</th>
              </tr>
            </thead>
            <tbody>
              {hits.data.map((h) => (
                <tr key={h.id}>
                  <td style={{ whiteSpace: "nowrap" }}>{h.code}</td>
                  <td>{h.label}</td>
                  <td>{h.unit}</td>
                  <td className="num">{fcfa(h.price_min)}</td>
                  <td className="num">{fcfa(h.price_max)}</td>
                  <td>
                    {h.nature}
                    <div className="muted" style={{ fontSize: 12 }}>
                      {h.nature_label}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
