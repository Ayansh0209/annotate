let workspace = localStorage.getItem('annotateqa-workspace') || 'practice';
export const getWorkspace = () => workspace;
export function setWorkspace(value:string) { workspace=value; localStorage.setItem('annotateqa-workspace', value); }
export async function api<T>(path:string, options:RequestInit={}):Promise<T> {
  const multipart = options.body instanceof FormData;
  const response = await fetch(`/api${path}`, {...options, headers:{...(!multipart ? {'Content-Type':'application/json'} : {}), 'X-Workspace':workspace, ...options.headers}});
  const body = await response.json().catch(() => ({error:'The server returned an unreadable response.'}));
  if (!response.ok) throw new Error(body.error || `Request failed (${response.status}).`);
  return body as T;
}
export const post = <T,>(path:string, body:unknown={}) => api<T>(path, {method:'POST',body:JSON.stringify(body)});
export const exportUrl = (format='zip') => `/api/export?workspace=${workspace}&format=${format}`;
export const time = (seconds:number) => `${Math.floor(seconds/60).toString().padStart(2,'0')}:${Math.floor(seconds%60).toString().padStart(2,'0')}`;
