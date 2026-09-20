import { getSessionId, getSessionToken } from "./session";

const API_URL = `${import.meta.env.VITE_API_URL ?? "http://127.0.0.1:8000"}/api`;

export async function uploadFile(file: File) {
  const sessionId = await getSessionId();
  const token = getSessionToken();

  const formData = new FormData();
  formData.append("file", file);

  const response = await fetch(
    `${API_URL}/sessions/${sessionId}/files`,
    {
      method: "POST",
      headers: token ? { "X-Session-Token": token } : undefined,
      body: formData,
    }
  );

  if (!response.ok) {
    throw new Error("Upload failed");
  }

  return response.json();
}