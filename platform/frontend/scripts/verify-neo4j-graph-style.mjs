import { readFileSync } from 'node:fs';
import { join } from 'node:path';

const root = process.cwd();

const shellFile = 'src/components/Neo4jGraphShell.jsx';
const graphViewFiles = [
  'src/components/KnowledgeGraphViewer.jsx',
  'src/components/RawGraphComponent.jsx',
];

const requiredShellTokens = [
  'NEO4J_LABEL_COLORS',
  'neo4j-graph-shell',
  'neo4j-results-overview',
  'neo4j-graph-toolbar',
  'Graph visualization',
  '#1b1f23',
  '#9aa3af',
];

const failures = [];

const shellSource = readFileSync(join(root, shellFile), 'utf8');
for (const token of requiredShellTokens) {
  if (!shellSource.includes(token)) {
    failures.push(`${shellFile} is missing ${token}`);
  }
}

for (const file of graphViewFiles) {
  const source = readFileSync(join(root, file), 'utf8');
  for (const token of ['Neo4jGraphShell', 'drawNeo4jNode', 'drawNeo4jLinkLabel', 'onNodeClick']) {
    if (!source.includes(token)) {
      failures.push(`${file} is missing ${token}`);
    }
  }
}

if (failures.length > 0) {
  console.error(failures.join('\n'));
  process.exit(1);
}

console.log('Neo4j graph style markers are present in all graph views.');
