/**
 * DeployHub API client
 * All calls go through Next.js API routes (/api/*) which proxy to the
 * backend API server — this keeps the backend URL server-side only.
 */

let BASE = "http://localhost:8000";
if (typeof window !== "undefined") {
  if (window.location.hostname === "localhost" || window.location.hostname === "127.0.0.1") {
    BASE = "http://localhost:8000";
  } else {
    BASE = "https://api." + window.location.hostname;
  }
} else {
  BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
}
async function request<T>(
  path: string,
  options: RequestInit = {}
): Promise<T> {
  let token: string | undefined;
  
  if (typeof window === "undefined") {
    const { auth } = await import("@/auth");
    const session = await auth();
    token = (session as any)?.accessToken;
  } else {
    const { getSession } = await import("next-auth/react");
    const session = await getSession();
    token = (session as any)?.accessToken;
  }

  const headers: Record<string, string> = { 
    "Content-Type": "application/json", 
    ...(options.headers as Record<string, string>) 
  };

  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  const res = await fetch(`${BASE}${path}`, {
    ...options,
    headers,
  });

  if (!res.ok) {
    let message = `HTTP ${res.status}`;
    try {
      const body = await res.json();
      message = body.detail ?? body.message ?? message;
    } catch {}
    throw new Error(message);
  }

  // 204 No Content or empty body
  const text = await res.text();
  return text ? JSON.parse(text) : ({} as T);
}

// ── Types ─────────────────────────────────────────────────────────────────────

export interface Project {
  id: string;
  name: string;
  namespace: string;
  status: "Provisioning" | "Ready" | "Terminating";
  created_at: string;
  deleted_at: string | null;
  webhook_secret?: string;
}

export interface Deployment {
  deployment_id: string;
  project_id: string;
  repo_url: string;
  image_uri: string;
  replicas: number;
  port: number;
  state: "Queued" | "Building" | "Deploying" | "Verifying" | "Running" | "Failed" | "Retry" | "DLQ";
  updated_at: string;
  last_error: string | null;
}

export interface Build {
  build_id: string;
  deployment_id: string;
  s3_log_uri: string | null;
  status: "Success" | "Failed" | "In Progress";
  started_at: string;
  completed_at: string | null;
}

export interface AuditLog {
  id: number;
  project_id: string;
  user_id: string;
  action: string;
  resource_type: string;
  resource_id: string;
  details: Record<string, unknown>;
  timestamp: string;
}

// ── Projects ──────────────────────────────────────────────────────────────────

export const api = {
  projects: {
    list: () => request<Project[]>("/projects"),
    get: (id: string) => request<Project>(`/projects/${id}`),
    create: (body: { name: string; namespace: string }) =>
      request<Project>("/projects", { method: "POST", body: JSON.stringify(body) }),
    delete: (id: string) =>
      request<{ message: string }>(`/projects/${id}`, { method: "DELETE" }),
  },

  deployments: {
    list: (projectId: string) =>
      request<Deployment[]>(`/projects/${projectId}/deployments`),
    get: (projectId: string, deploymentId: string) =>
      request<Deployment>(`/projects/${projectId}/deployments/${deploymentId}`),
    create: (
      projectId: string,
      body: { repo_url: string; port?: number; branch?: string }
    ) =>
      request<Deployment>(`/projects/${projectId}/deployments`, {
        method: "POST",
        body: JSON.stringify(body),
      }),
  },

  builds: {
    list: (projectId: string, deploymentId: string) =>
      request<Build[]>(
        `/projects/${projectId}/deployments/${deploymentId}/builds`
      ),
  },

  audit: {
    list: (projectId: string) =>
      request<AuditLog[]>(`/projects/${projectId}/audit`),
    listGlobal: () =>
      request<AuditLog[]>("/audit"),
  },

  env: {
    list: (projectId: string) =>
      request<{ keys: string[] }>(`/projects/${projectId}/env`),
    put: (projectId: string, key: string, value: string) =>
      request<{ message: string }>(`/projects/${projectId}/env`, {
        method: "PUT",
        body: JSON.stringify({ key, value }),
      }),
    delete: (projectId: string, key: string) =>
      request<{ message: string }>(`/projects/${projectId}/env/${key}`, {
        method: "DELETE",
      }),
  },
};
