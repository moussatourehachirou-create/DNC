import { createContext, useContext, useState, type ReactNode } from "react";

// Structure et version de PTA sélectionnées, partagées par toutes les pages.
type Selection = {
  organisationId: string | null;
  versionId: string | null;
  setOrganisationId: (id: string | null) => void;
  setVersionId: (id: string | null) => void;
};

const SelectionContext = createContext<Selection | null>(null);

function stored(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

function store(key: string, value: string | null) {
  try {
    if (value) localStorage.setItem(key, value);
    else localStorage.removeItem(key);
  } catch {
    /* stockage indisponible : la sélection reste en mémoire */
  }
}

export function SelectionProvider({ children }: { children: ReactNode }) {
  const [organisationId, setOrg] = useState<string | null>(() => stored("bie.org"));
  const [versionId, setVersion] = useState<string | null>(() => stored("bie.version"));
  const value: Selection = {
    organisationId,
    versionId,
    setOrganisationId: (id) => {
      setOrg(id);
      store("bie.org", id);
      setVersion(null);
      store("bie.version", null);
    },
    setVersionId: (id) => {
      setVersion(id);
      store("bie.version", id);
    },
  };
  return <SelectionContext.Provider value={value}>{children}</SelectionContext.Provider>;
}

export function useSelection(): Selection {
  const value = useContext(SelectionContext);
  if (!value) throw new Error("SelectionProvider manquant");
  return value;
}
