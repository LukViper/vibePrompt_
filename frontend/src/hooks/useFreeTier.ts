import { useCallback, useState } from "react";
import { api } from "../api/client";
import type { FreeTierStatus } from "../types";

export function useFreeTier() {
  const [freeTier, setFreeTier] = useState<FreeTierStatus | null>(null);

  const refreshFreeTier = useCallback(async () => {
    try {
      const status = await api.freeTierStatus();
      setFreeTier(status);
    } catch {
      setFreeTier(null);
    }
  }, []);

  const freeTierEnabled = freeTier?.enabled === true;
  const needsByok =
    freeTier?.requires_byok === true && !freeTier.byok_configured;

  const modePillLabel = (() => {
    if (freeTier?.funding === "BYOK" || freeTier?.byok_configured) {
      return "BYOK: Active";
    }
    if (freeTierEnabled) {
      const rem = freeTier?.remaining ?? 0;
      const alloc = freeTier?.allocated ?? 0;
      return `Free Tier: ${rem}/${alloc} left`;
    }
    return "API keys · BYOK";
  })();

  const modePillClass = needsByok
    ? "mode-pill exhausted"
    : freeTier?.funding === "BYOK" || freeTier?.byok_configured
      ? "mode-pill byok"
      : "mode-pill";

  return {
    freeTier,
    setFreeTier,
    refreshFreeTier,
    freeTierEnabled,
    needsByok,
    modePillLabel,
    modePillClass,
  };
}
