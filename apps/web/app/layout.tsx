import type { Metadata } from "next";
import Link from "next/link";
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
          <div>
            <Link className="brand" href="/">
              Agent<span>athon</span>
            </Link>
          </div>
          <nav>
            <Link href="/">Novo desafio</Link>
            <Link href="/runs">Histórico</Link>
          </nav>
        </header>
        <main>{children}</main>
        <footer>
          Agentathon MVP · apoio à decisão entre propostas de agentes; não executa a proposta vencedora. Conteúdo simulado leva o selo SIMULADO.
        </footer>
      </body>
    </html>
  );
}
