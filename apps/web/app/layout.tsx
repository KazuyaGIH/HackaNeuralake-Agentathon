import type { Metadata } from "next";
import Link from "next/link";
import ServerWake from "@/components/ServerWake";
import "./globals.css";

export const metadata: Metadata = {
  title: "Agentathon",
  description: "Hackathon entre equipes de agentes de IA: propostas concorrentes, crítica limitada, verificação objetiva e ranking rastreável.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="pt-BR">
      <body>
        <header className="topbar">
          <Link className="brand" href="/">
            <span className="brand-mark">A</span>
            Agentathon
          </Link>
          <nav>
            <Link href="/">Projetos</Link>
            <Link href="/runs">Histórico</Link>
          </nav>
        </header>
        <ServerWake />
        <main>{children}</main>
      </body>
    </html>
  );
}
