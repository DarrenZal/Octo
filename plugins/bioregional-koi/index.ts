import type { OpenClawPluginApi } from "openclaw/plugin-sdk";

const KOI_API = process.env.KOI_API_ENDPOINT || "http://127.0.0.1:8351";
const VAULT_PATH = process.env.OBSIDIAN_VAULT_PATH || "/root/.openclaw/workspace/vault";

async function koiRequest(path: string, method = "GET", body?: any) {
  const url = `${KOI_API}${path}`;
  const opts: RequestInit = {
    method,
    headers: { "Content-Type": "application/json" },
  };
  if (body) opts.body = JSON.stringify(body);
  const res = await fetch(url, opts);
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`KOI API ${method} ${path} failed (${res.status}): ${text}`);
  }
  return res.json();
}

async function resolveToUri(nameOrUri: string): Promise<string> {
  // If it already looks like a URI, return as-is
  if (nameOrUri.startsWith("orn:")) return nameOrUri;
  // Otherwise resolve the name to a URI
  const data = await koiRequest("/entity/resolve", "POST", { label: nameOrUri });
  const candidates = data.candidates || [];
  if (candidates.length > 0 && candidates[0].confidence >= 0.5) {
    return candidates[0].uri;
  }
  throw new Error(`Could not resolve "${nameOrUri}" to a known entity`);
}

const bioregionalKoiPlugin = {
  id: "bioregional-koi",
  name: "Bioregional KOI",
  description: "Knowledge graph tools for bioregional knowledge commoning",
  configSchema: {
    type: "object" as const,
    additionalProperties: false,
    properties: {
      apiEndpoint: { type: "string" as const, default: "http://127.0.0.1:8351" },
      vaultPath: { type: "string" as const, default: VAULT_PATH },
    },
  },

  register(api: OpenClawPluginApi) {
    // resolve_entity — disambiguate a name to a canonical entity
    api.registerTool(
      {
        name: "resolve_entity",
        description:
          "Resolve an entity name to its canonical form in the knowledge graph. Use this when someone mentions a person, organization, project, or concept by name. Returns the best match with type, URI, and confidence.",
        parameters: {
          type: "object",
          properties: {
            label: { type: "string", description: "The entity name or label to resolve (e.g. 'Bill', 'r3.0', 'pattern mining')" },
            type_hint: { type: "string", description: "Optional type hint: Person, Organization, Project, Concept, Location, Meeting" },
          },
          required: ["label"],
        },
        async execute(_id: string, params: Record<string, unknown>) {
          const label = params.label as string;
          const type_hint = params.type_hint as string | undefined;
          const data = await koiRequest("/entity/resolve", "POST", {
            label,
            type_hint: type_hint || undefined,
          });
          return { content: [{ type: "text", text: JSON.stringify(data, null, 2) }] };
        },
      },
      { names: ["resolve_entity"] },
    );

    // get_entity_neighborhood — see relationships around an entity
    api.registerTool(
      {
        name: "get_entity_neighborhood",
        description:
          "Get the neighborhood of an entity in the knowledge graph — its relationships, affiliated organizations, projects, and connected people. Use when asked 'who works with X?' or 'what is Y involved in?'",
        parameters: {
          type: "object",
          properties: {
            entity_uri: { type: "string", description: "The entity URI or name (e.g. 'bill-baue', 'r3.0')" },
          },
          required: ["entity_uri"],
        },
        async execute(_id: string, params: Record<string, unknown>) {
          const input = params.entity_uri as string;
          const uri = await resolveToUri(input);
          const data = await koiRequest(`/relationships/${encodeURIComponent(uri)}`);
          return { content: [{ type: "text", text: JSON.stringify(data, null, 2) }] };
        },
      },
      { names: ["get_entity_neighborhood"] },
    );

    // get_entity_documents — find documents mentioning an entity
    api.registerTool(
      {
        name: "get_entity_documents",
        description:
          "Find all documents that mention a specific entity. Use when asked 'what documents mention X?' or 'where is Y referenced?'",
        parameters: {
          type: "object",
          properties: {
            entity_uri: { type: "string", description: "The entity URI or name" },
          },
          required: ["entity_uri"],
        },
        async execute(_id: string, params: Record<string, unknown>) {
          const input = params.entity_uri as string;
          const uri = await resolveToUri(input);
          const data = await koiRequest(`/entity/${encodeURIComponent(uri)}/mentioned-in`);
          return { content: [{ type: "text", text: JSON.stringify(data, null, 2) }] };
        },
      },
      { names: ["get_entity_documents"] },
    );

    // search — semantic search across the knowledge base
    api.registerTool(
      {
        name: "koi_search",
        description:
          "Search the bioregional knowledge graph using semantic similarity. Returns entities and documents matching the query. Use for broad knowledge questions.",
        parameters: {
          type: "object",
          properties: {
            query: { type: "string", description: "The search query" },
            type_filter: { type: "string", description: "Optional: filter by entity type (Person, Organization, Project, Concept)" },
            limit: { type: "number", description: "Max results (default 10)" },
          },
          required: ["query"],
        },
        async execute(_id: string, params: Record<string, unknown>) {
          const query = params.query as string;
          const type_filter = params.type_filter as string | undefined;
          const limit = (params.limit as number) || 10;
          const qs = new URLSearchParams({ query, limit: String(limit) });
          if (type_filter) qs.set("type_filter", type_filter);
          const data = await koiRequest(`/entity-search?${qs}`);
          return { content: [{ type: "text", text: JSON.stringify(data, null, 2) }] };
        },
      },
      { names: ["koi_search"] },
    );

    // vault_read_note — read a markdown note from the vault
    api.registerTool(
      {
        name: "vault_read_note",
        description:
          "Read a structured entity note from the bioregional knowledge vault. Notes are in folders: People/, Organizations/, Projects/, Concepts/, Bioregions/",
        parameters: {
          type: "object",
          properties: {
            path: { type: "string", description: "Relative path within the vault (e.g. 'People/Bill Baue.md')" },
          },
          required: ["path"],
        },
        async execute(_id: string, params: Record<string, unknown>) {
          const notePath = params.path as string;
          const fs = await import("node:fs/promises");
          const fullPath = `${VAULT_PATH}/${notePath}`;
          try {
            const content = await fs.readFile(fullPath, "utf-8");
            return { content: [{ type: "text", text: content }] };
          } catch (e: any) {
            return { content: [{ type: "text", text: `Error reading ${notePath}: ${e.message}` }], isError: true };
          }
        },
      },
      { names: ["vault_read_note"] },
    );

    // vault_write_note — create/update a note in the vault
    api.registerTool(
      {
        name: "vault_write_note",
        description:
          "Create or update an entity note in the bioregional knowledge vault. Use when learning about new entities. Include proper frontmatter with @type.",
        parameters: {
          type: "object",
          properties: {
            path: { type: "string", description: "Relative path (e.g. 'People/New Person.md')" },
            content: { type: "string", description: "Full markdown content including YAML frontmatter" },
          },
          required: ["path", "content"],
        },
        async execute(_id: string, params: Record<string, unknown>) {
          const notePath = params.path as string;
          const content = params.content as string;
          const fs = await import("node:fs/promises");
          const path = await import("node:path");
          const fullPath = `${VAULT_PATH}/${notePath}`;
          const dir = path.dirname(fullPath);
          await fs.mkdir(dir, { recursive: true });
          await fs.writeFile(fullPath, content, "utf-8");
          return { content: [{ type: "text", text: `Written: ${notePath}` }] };
        },
      },
      { names: ["vault_write_note"] },
    );

    // vault_list_notes — list notes in a vault folder
    api.registerTool(
      {
        name: "vault_list_notes",
        description:
          "List entity notes in a vault folder. Folders: People, Organizations, Projects, Concepts, Bioregions",
        parameters: {
          type: "object",
          properties: {
            folder: { type: "string", description: "Folder name (e.g. 'People', 'Organizations')" },
          },
          required: ["folder"],
        },
        async execute(_id: string, params: Record<string, unknown>) {
          const folder = params.folder as string;
          const fs = await import("node:fs/promises");
          const fullPath = `${VAULT_PATH}/${folder}`;
          try {
            const files = await fs.readdir(fullPath);
            const mdFiles = files.filter((f: string) => f.endsWith(".md"));
            return { content: [{ type: "text", text: mdFiles.join("\n") }] };
          } catch (e: any) {
            return { content: [{ type: "text", text: `Error listing ${folder}: ${e.message}` }], isError: true };
          }
        },
      },
      { names: ["vault_list_notes"] },
    );

    // preview_url — fetch and preview a URL for evaluation
    api.registerTool(
      {
        name: "preview_url",
        description:
          "Fetch and preview a URL someone shared. Returns title, content summary, detected entities, and safety check. Use when someone shares a URL. Does NOT ingest — just previews so you can evaluate relevance.",
        parameters: {
          type: "object",
          properties: {
            url: { type: "string", description: "The URL to preview" },
            submitted_by: { type: "string", description: "Username of the person who shared the URL" },
            submitted_via: { type: "string", description: "Channel: telegram, discord, or api" },
          },
          required: ["url"],
        },
        async execute(_id: string, params: Record<string, unknown>) {
          const url = params.url as string;
          const submitted_by = params.submitted_by as string | undefined;
          const submitted_via = (params.submitted_via as string) || "telegram";
          const data = await koiRequest("/web/preview", "POST", {
            url,
            submitted_by,
            submitted_via,
          });
          return { content: [{ type: "text", text: JSON.stringify(data, null, 2) }] };
        },
      },
      { names: ["preview_url"] },
    );

    // ingest_url — ingest a previously previewed URL
    api.registerTool(
      {
        name: "ingest_url",
        description:
          "Ingest a previously previewed URL into the knowledge graph. Call AFTER preview_url and your evaluation. Pass the entities and relationships you identified from the preview.",
        parameters: {
          type: "object",
          properties: {
            url: { type: "string", description: "The URL to ingest (must have been previewed first)" },
            entities: {
              type: "array",
              description: "Entities to resolve and link to this URL",
              items: {
                type: "object",
                properties: {
                  name: { type: "string" },
                  type: { type: "string", description: "Person, Organization, Project, Concept, Location, Bioregion, Practice, etc." },
                  context: { type: "string", description: "Brief context for how this entity relates" },
                },
                required: ["name", "type"],
              },
            },
            relationships: {
              type: "array",
              description: "Relationships between entities",
              items: {
                type: "object",
                properties: {
                  subject: { type: "string" },
                  predicate: { type: "string" },
                  object: { type: "string" },
                },
                required: ["subject", "predicate", "object"],
              },
            },
          },
          required: ["url"],
        },
        async execute(_id: string, params: Record<string, unknown>) {
          const url = params.url as string;
          const entities = (params.entities as any[]) || [];
          const relationships = (params.relationships as any[]) || [];
          const data = await koiRequest("/web/ingest", "POST", {
            url,
            entities,
            relationships,
          });
          return { content: [{ type: "text", text: JSON.stringify(data, null, 2) }] };
        },
      },
      { names: ["ingest_url"] },
    );
  },
};

export default bioregionalKoiPlugin;
