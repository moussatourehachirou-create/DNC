import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api, type Finding } from "../api";

const CODE_LABELS: Record<string, string> = {
  sous_elements_depassent: "Sous-éléments supérieurs au montant déclaré",
  ae_inferieure_cp:
    "Autorisation d'engagement inférieure au crédit de paiement",
  hors_periode_parent: "Période hors de celle du niveau supérieur",
  periode_inversee: "Début après la fin",
  executant_validateur: "Responsable et validateur identiques",
  reste_a_repartir: "Montant restant à répartir",
  responsable_manquant: "Sans responsable",
  indicateur_manquant: "Tâches sans indicateur de suivi",
  poids_incomplet: "Poids incomplets",
};

/** Mode brouillon / programmation et contrôle de cohérence de la version, avec corrections assistées. */
export default function CoherencePanel({
  versionId,
  labelOf,
  onSelect,
}: {
  versionId: string;
  labelOf: (nodeId: string) => string;
  onSelect: (nodeId: string) => void;
}) {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [code, setCode] = useState<string | null>(null);
  const coherence = useQuery({
    queryKey: ["coherence", versionId],
    queryFn: () => api.coherence(versionId),
  });
  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ["coherence", versionId] });
    queryClient.invalidateQueries({ queryKey: ["tree", versionId] });
    queryClient.invalidateQueries({ queryKey: ["versions"] });
  };
  const setMode = useMutation({
    mutationFn: (mode: "brouillon" | "programmation") =>
      api.setMode(versionId, mode),
    onSuccess: refresh,
    onError: () => setOpen(true),
  });
  const applyFix = useMutation({
    mutationFn: (f: Finding) => api.applyFix(versionId, f.fix!),
    onSuccess: refresh,
  });

  const data = coherence.data;
  if (!data) return null;
  const programming = data.mode === "programmation";
  const blocking = data.counts.bloquant;
  const codes = Object.entries(data.by_code).sort(
    ([, a], [, b]) =>
      Number(b.severity === "bloquant") - Number(a.severity === "bloquant") ||
      b.count - a.count,
  );
  const current = code && data.by_code[code] ? code : codes[0]?.[0];
  const shown = data.findings.filter((f) => f.code === current);
  const hidden = current ? data.by_code[current].count - shown.length : 0;

  return (
    <div className="card" style={{ margin: "12px 0" }}>
      <div className="row" style={{ justifyContent: "space-between" }}>
        <div className="row">
          <span
            className={`badge ${programming ? "ok" : "soumis_a_validation"}`}
          >
            {programming
              ? "Mode programmation — contrôles actifs"
              : "Mode brouillon — saisie libre"}
          </span>
          <span className={`badge ${blocking ? "bloquant" : "ok"}`}>
            {blocking} anomalie(s) bloquante(s)
          </span>
          <span className="badge avertissement">
            {data.counts.avertissement} avertissement(s)
          </span>
          <button onClick={() => setOpen(!open)}>
            {open ? "Masquer" : "Voir le contrôle de cohérence"}
          </button>
        </div>
        {programming ? (
          <button onClick={() => setMode.mutate("brouillon")}>
            Revenir au brouillon
          </button>
        ) : (
          <button
            className="primary"
            onClick={() => setMode.mutate("programmation")}
            disabled={setMode.isPending}
          >
            Activer les contrôles
          </button>
        )}
      </div>
      {setMode.error && <p className="error">{setMode.error.message}</p>}
      {applyFix.error && <p className="error">{applyFix.error.message}</p>}
      {open && (
        <>
          <p className="muted" style={{ fontSize: 13 }}>
            {programming
              ? "Toute modification qui créerait une anomalie bloquante est refusée."
              : "En brouillon, les anomalies sont signalées sans bloquer la saisie. Corrigez les anomalies bloquantes pour activer les contrôles, préalable à la soumission du PTA."}
          </p>
          {codes.length === 0 ? (
            <p className="badge ok">
              Aucune anomalie : la programmation est cohérente.
            </p>
          ) : (
            <>
              <div className="row" style={{ margin: "8px 0" }}>
                {codes.map(([c, g]) => (
                  <button
                    key={c}
                    className={c === current ? "primary" : ""}
                    onClick={() => setCode(c)}
                  >
                    <span className={`badge ${g.severity}`}>{g.count}</span>{" "}
                    {CODE_LABELS[c] ?? c}
                  </button>
                ))}
              </div>
              <div
                className="table-wrap"
                style={{ maxHeight: 320, overflow: "auto" }}
              >
                <table>
                  <tbody>
                    {shown.map((f, i) => (
                      <tr key={`${f.code}-${f.node_id}-${i}`}>
                        <td>
                          <span className={`badge ${f.severity}`}>
                            {f.severity === "bloquant"
                              ? "bloquant"
                              : "avertissement"}
                          </span>
                        </td>
                        <td>
                          {f.message}
                          <div
                            className="muted"
                            style={{ fontSize: 12, cursor: "pointer" }}
                            onClick={() => onSelect(f.node_id)}
                          >
                            → {labelOf(f.node_id)}
                          </div>
                        </td>
                        <td>
                          {f.fix && (
                            <button
                              onClick={() => applyFix.mutate(f)}
                              disabled={applyFix.isPending}
                            >
                              {f.fix.label}
                            </button>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {hidden > 0 && (
                  <p className="muted" style={{ fontSize: 12 }}>
                    … et {hidden} autre(s) du même type.
                  </p>
                )}
              </div>
            </>
          )}
        </>
      )}
    </div>
  );
}
