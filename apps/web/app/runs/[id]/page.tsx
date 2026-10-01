import RunView from "@/components/RunView";

export default async function RunPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return (
    <div className="container">
      <RunView runId={id} />
    </div>
  );
}
