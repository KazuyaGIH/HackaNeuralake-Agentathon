import ChallengeForm from "@/components/ChallengeForm";

export default function HomePage() {
  return (
    <div>
      <h1>Configurar um desafio</h1>
      <p className="lead">
        Defina objetivo, evidências, restrições, critérios e orçamento. Equipes de agentes geram propostas concorrentes, criticam-se uma vez, passam por
        verificações objetivas e por um Judge com rubrica fixa; o ranking é calculado em código.
      </p>
      <ChallengeForm />
    </div>
  );
}
