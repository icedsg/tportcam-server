export type Urls = { webrtc: string; hls: string; rtsp: string };

export type Camera = {
  id: string;
  name: string;
  ip: string;
  manufacturer: string;
  model: string;
  error: string;
  has_sub: boolean;
  snapshot?: string;
  main?: Urls;
  sub?: Urls;
};

export type Hub = { name: string; cameras: number; api: number };

async function getJson<T>(path: string): Promise<T> {
  const r = await fetch(path);
  if (!r.ok) throw new Error(`${path}: ${r.status}`);
  return r.json() as Promise<T>;
}

export const getHub = () => getJson<Hub>("/api/hub");
export const getCameras = () => getJson<{ hub: string; cameras: Camera[] }>("/api/cameras");

export type CloudLink = { stream_id: string; quality: "sub" | "main"; enabled: boolean; has_key: boolean; status: string };
export type Cloud = { relay: string; cameras: Record<string, CloudLink> };

export const getCloud = () => getJson<Cloud>("/api/cloud");

async function send(method: string, path: string, body?: unknown) {
  const r = await fetch(path, { method, headers: { "content-type": "application/json" }, body: body === undefined ? undefined : JSON.stringify(body) });
  if (!r.ok) throw new Error((await r.json().catch(() => null))?.detail || `${path}: ${r.status}`);
}

export const saveCloud = (id: string, link: { stream_id: string; key: string; quality: string; enabled: boolean }) =>
  send("PUT", `/api/cloud/${id}`, link);
export const removeCloud = (id: string) => send("DELETE", `/api/cloud/${id}`);
