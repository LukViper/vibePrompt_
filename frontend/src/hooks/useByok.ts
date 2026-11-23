import { FormEvent, useState } from "react";
import { api } from "../api/client";
import type { ByokProvider } from "../types";

type Options = {
  refreshFreeTier: () => Promise<void>;
  setBusy: (v: boolean) => void;
  setError: (v: string | null) => void;
};

export function useByok({ refreshFreeTier, setBusy, setError }: Options) {
  const [showByok, setShowByok] = useState(false);
  const [byokProvider, setByokProvider] = useState<ByokProvider>("qwen");
  const [byokModel, setByokModel] = useState("qwen3.5-flash");
  const [byokKey, setByokKey] = useState("");
  const [byokBaseUrl, setByokBaseUrl] = useState("");

  async function handleByok(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.upsertByok({
        provider: byokProvider,
        api_key: byokKey.trim(),
        model: byokModel.trim(),
        base_url: byokBaseUrl.trim() || undefined,
        set_active: true,
      });
      setByokKey("");
      setShowByok(false);
      await refreshFreeTier();
    } catch (err) {
      setError(String(err));
    } finally {
      setBusy(false);
    }
  }

  return {
    showByok,
    setShowByok,
    byokProvider,
    setByokProvider,
    byokModel,
    setByokModel,
    byokKey,
    setByokKey,
    byokBaseUrl,
    setByokBaseUrl,
    handleByok,
  };
}
