"use client";

import { useEffect, useState } from "react";
import { onServerWaiting, serverReady } from "@/lib/api";

// Aviso discreto enquanto o servidor gratuito acorda (primeiro acesso depois de um tempo sem uso).
export default function ServerWake() {
  const [waiting, setWaiting] = useState(false);
  useEffect(() => {
    const off = onServerWaiting(setWaiting);
    void serverReady();
    return off;
  }, []);
  if (!waiting) return null;
  return (
    <div className="server-wake">
      <span className="spinner" />
      <span>
        <strong>Acordando o servidor…</strong> No plano gratuito ele dorme quando ninguém usa. Pode levar até 1 minuto; a página continua sozinha.
      </span>
    </div>
  );
}
