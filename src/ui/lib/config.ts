declare global {
  interface Window {
    __MESH_BASE_PATH__?: string;
    __MESH_REGISTRY_URL__?: string;
  }
}

export function getBasePath(): string {
  return window.__MESH_BASE_PATH__ || "";
}

export function getApiBase(): string {
  if (window.__MESH_REGISTRY_URL__) {
    return window.__MESH_REGISTRY_URL__;
  }
  const base = getBasePath();
  return base ? `${base}/api` : "/api";
}
