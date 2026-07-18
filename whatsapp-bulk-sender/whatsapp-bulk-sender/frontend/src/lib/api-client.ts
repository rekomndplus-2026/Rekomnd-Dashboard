/**
 * API Client for frontend to communicate with FastAPI backend
 */

const API_BASE_URL = process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8000";

export async function createSession() {
  const res = await fetch(`${API_BASE_URL}/api/whatsapp/session/create`, {
    method: "POST",
  });
  if (!res.ok) throw new Error("Failed to create session");
  return res.json();
}

export async function getSessionStatus() {
  const res = await fetch(`${API_BASE_URL}/api/whatsapp/session/status`);
  if (!res.ok) throw new Error("Failed to get session status");
  return res.json();
}

export async function getQrCode() {
  const res = await fetch(`${API_BASE_URL}/api/whatsapp/session/qr`);
  if (!res.ok) throw new Error("Failed to get QR code");
  return res.json();
}

export async function uploadContactsFile(file: File) {
  const formData = new FormData();
  formData.append("file", file);

  const res = await fetch(`${API_BASE_URL}/api/contacts/upload`, {
    method: "POST",
    body: formData,
  });
  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: "Upload failed" }));
    throw new Error(error.detail || "Failed to upload contacts");
  }
  return res.json();
}

export async function previewCleanedContacts(fileId: string, phoneColumn: string, countryCode: string) {
  const formData = new FormData();
  formData.append("file_id", fileId);
  formData.append("phone_column", phoneColumn);
  formData.append("country_code", countryCode);

  const res = await fetch(`${API_BASE_URL}/api/contacts/preview-cleaned`, {
    method: "POST",
    body: formData,
  });
  if (!res.ok) throw new Error("Failed to preview cleaned contacts");
  return res.json();
}

export async function sendMessages(payload: {
  file_id: string;
  phone_column: string;
  country_code: string;
  message_template: string;
  instance_name: string;
}) {
  const res = await fetch(`${API_BASE_URL}/api/messages/send`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: "Send failed" }));
    throw new Error(error.detail || "Failed to start sending process");
  }
  return res.json();
}

export async function getJobStatus(jobId: string) {
  const res = await fetch(`${API_BASE_URL}/api/messages/job/${jobId}`);
  if (!res.ok) throw new Error("Failed to get job status");
  return res.json();
}

export async function cancelJob(jobId: string) {
  const res = await fetch(`${API_BASE_URL}/api/messages/job/${jobId}`, {
    method: "DELETE",
  });
  if (!res.ok) throw new Error("Failed to cancel job");
  return res.json();
}
