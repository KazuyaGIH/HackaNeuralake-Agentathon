import ProjectWorkspace from "@/components/workspace/ProjectWorkspace";

export default async function ProjectPage({ params, searchParams }: { params: Promise<{ id: string }>; searchParams: Promise<{ aba?: string }> }) {
  const { id } = await params;
  const { aba } = await searchParams;
  return <ProjectWorkspace projectId={id} initialTab={aba} />;
}
