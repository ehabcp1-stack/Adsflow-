import { readFile } from 'node:fs/promises';
import path from 'node:path';

/**
 * Server layout for the project stage routes.
 *
 * Its only job is `generateStaticParams`, which lets the Demo Mode build
 * (`output: 'export'`) pre-render every stage of the seeded demo project.
 * In a normal build this is a no-op — other project ids still render on
 * demand.
 */
export async function generateStaticParams() {
  try {
    const raw = await readFile(path.join(process.cwd(), 'public', 'demo', 'snapshot.json'), 'utf8');
    const { projectId } = JSON.parse(raw) as { projectId?: string };
    return projectId ? [{ id: projectId }] : [];
  } catch {
    return [];
  }
}

export default function ProjectLayout({ children }: { children: React.ReactNode }) {
  return children;
}
